#!/usr/bin/env python3
"""Test-only replay/deny transport guard helper (TASK0-3D step B, final deltas).

REQUEST_CONTRACT (R3 final):
  - Support: GET, no body, 200 recorded response.
  - Reject: non-GET, any non-None body (including b""), unsupported response
    status. Positional data, keyword data, and Request.data are ALL checked.
    Rejection enters the ledger (not just raise). String and Request use the
    same structured key (method + full URL/query + body digest + relevant
    headers). Python's default method determination is `data is None`, not the
    truthiness of the data.

LIFECYCLE (R2 final):
  - install() applies patches via a tracked patch list; if install fails
    mid-way, _restore_applied() reverses the applied patches (no partial
    install left). A mid-install failure records HARNESS_ERROR and the
    application is NOT loaded.
  - uninstall() restores all patched objects to their original identity, even
    on exception (used in a finally/context by the full-gate).

SENTINEL (R4 final):
  - The TEST installs a safe bottom-layer sentinel FIRST, then creates/installs
    the actual TransportGuard. The guard's captured "original entry" is the
    safe sentinel; even if it erroneously delegates, it's only counted and
    raises, not entering real I/O.
  - verdict() checks raw_*_delegations: any non-zero raw delegation ->
    HARNESS_ERROR (not COMPLETE).

Provides TransportGuard + ReplayMiss + _FakeResponse. Installed BEFORE the
application loads. NOT an application source change.
"""
from __future__ import annotations

import hashlib
import socket
import subprocess
import urllib.request
from typing import Any


class ReplayMiss(Exception):
    """Fixed REPLAY_INPUT_MISS: the request is not in the replay registry."""


class _FakeResponse:
    """A minimal response object for a recorded replay hit (no external connection)."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _request_key(url: Any, data: bytes | None = None) -> str | None:
    """Build the identity key (method + full URL/query + body digest + headers).

    REQUEST_CONTRACT: support GET/no-body/200. Reject non-GET, any non-None body
    (including b""), unsupported response status. Positional data, keyword data,
    and Request.data are ALL checked. `data is None` (not truthiness) determines
    no-body. String and Request use the same structured key.
    """
    if isinstance(url, str):
        # data is None -> GET no-body; data is not None (including b"") -> reject.
        if data is not None:
            return None  # reject: non-None body (including b"")
        return f"GET|{url}||"
    if isinstance(url, urllib.request.Request):
        # If an explicit data is passed, it overrides Request.data.
        effective_data = data if data is not None else url.data
        if effective_data is not None:
            return None  # reject: non-None body (including b"")
        method = (url.get_method() or "GET").upper()
        if method != "GET":
            return None  # reject: non-GET
        full_url = url.full_url
        accept = url.get_header("Accept") or ""
        content_type = url.get_header("Content-type") or ""
        return f"GET|{full_url}||{accept}|{content_type}"
    return None  # unsupported form -> rejected


class TransportGuard:
    """Replay/deny transport guard. Installed BEFORE the application loads."""

    def __init__(self) -> None:
        self.registry: dict[str, dict[str, Any]] = {}
        self.replay_hits: list[str] = []
        self.replay_misses: list[str] = []
        self.denied_resolver_attempts: int = 0
        self.denied_connect_attempts: int = 0
        self.denied_spawn_attempts: int = 0
        self.raw_resolver_delegations: int = 0
        self.raw_connector_delegations: int = 0
        self.raw_spawn_delegations: int = 0
        self.harness_error: str | None = None
        # LIFECYCLE: tracked patch list for partial-install restore.
        self._applied_patches: list[tuple[Any, str, Any]] = []  # (obj, attr, original)
        self._orig_urlopen = urllib.request.urlopen
        self._orig_create_connection = socket.create_connection
        self._orig_getaddrinfo = socket.getaddrinfo
        self._orig_socket_class = socket.socket
        self._orig_popen = subprocess.Popen
        self._installed = False

    def register(self, url: Any, status: int, body: bytes, metadata: dict[str, Any] | None = None) -> None:
        if status != 200:
            raise ValueError(f"unsupported response status: {status} (only 200 supported)")
        key = _request_key(url)
        if key is None:
            raise ValueError(f"unsupported request form: {type(url)} (only GET/no-body supported)")
        self.registry[key] = {
            "status": status,
            "body": body,
            "sha256": hashlib.sha256(body).hexdigest(),
            "metadata": metadata or {},
        }

    def _apply(self, obj: Any, attr: str, value: Any) -> None:
        """Apply a patch, tracking it for partial-install restore."""
        original = getattr(obj, attr)
        self._applied_patches.append((obj, attr, original))
        setattr(obj, attr, value)

    def _restore_applied(self) -> None:
        """Reverse the applied patches (for partial-install failure)."""
        for obj, attr, original in reversed(self._applied_patches):
            setattr(obj, attr, original)
        self._applied_patches.clear()

    def install(self) -> None:
        if self._installed:
            return
        guard = self
        try:
            def guarded_urlopen(url, *args, **kwargs):
                # REQUEST_CONTRACT: check positional data (2nd arg) + keyword data.
                positional_data = args[0] if len(args) >= 1 else None
                keyword_data = kwargs.get("data")
                data = keyword_data if keyword_data is not None else positional_data
                key = _request_key(url, data)
                if key is None:
                    guard.denied_connect_attempts += 1
                    raise ReplayMiss(f"REPLAY_INPUT_MISS: unsupported request (non-GET or non-None body): {type(url)}")
                if key in guard.registry:
                    entry = guard.registry[key]
                    guard.replay_hits.append(key)
                    return _FakeResponse(entry["status"], entry["body"])
                else:
                    guard.replay_misses.append(key)
                    raise ReplayMiss(f"REPLAY_INPUT_MISS: {key} is not in the replay registry")

            def guarded_create_connection(address, *args, **kwargs):
                guard.denied_connect_attempts += 1
                raise ReplayMiss(f"REPLAY_INPUT_MISS: socket connection denied at {address}")

            def guarded_getaddrinfo(host, port, *args, **kwargs):
                guard.denied_resolver_attempts += 1
                raise ReplayMiss(f"REPLAY_INPUT_MISS: DNS resolution denied for {host}")

            orig_socket_class = self._orig_socket_class

            class _GuardedSocket(orig_socket_class):
                def connect(self, address):
                    guard.denied_connect_attempts += 1
                    raise ReplayMiss(f"REPLAY_INPUT_MISS: socket.connect denied at {address}")

                def connect_ex(self, address):
                    guard.denied_connect_attempts += 1
                    raise ReplayMiss(f"REPLAY_INPUT_MISS: socket.connect_ex denied at {address}")

            def guarded_popen(*args, **kwargs):
                guard.denied_spawn_attempts += 1
                raise ReplayMiss(f"REPLAY_INPUT_MISS: subprocess spawn denied: {args[:1]}")

            # Apply patches via the tracked patch list (LIFECYCLE).
            self._apply(urllib.request, "urlopen", guarded_urlopen)
            self._apply(socket, "create_connection", guarded_create_connection)
            self._apply(socket, "getaddrinfo", guarded_getaddrinfo)
            self._apply(socket, "socket", _GuardedSocket)
            self._apply(subprocess, "Popen", guarded_popen)
            self._installed = True
        except Exception as exc:
            # LIFECYCLE: partial-install failure -> restore applied patches.
            self._restore_applied()
            self.harness_error = f"install failed: {type(exc).__name__}: {exc}"
            self._installed = False
            raise

    def uninstall(self) -> None:
        # LIFECYCLE: restore all patched objects to their original identity,
        # even on exception (use in a finally/context by the full-gate).
        if self._applied_patches:
            self._restore_applied()
        # Also restore the saved originals (belt and suspenders).
        urllib.request.urlopen = self._orig_urlopen
        socket.create_connection = self._orig_create_connection
        socket.getaddrinfo = self._orig_getaddrinfo
        socket.socket = self._orig_socket_class
        subprocess.Popen = self._orig_popen
        self._installed = False

    def verdict(self) -> str:
        """R2 + SENTINEL: explicit mutually-exclusive results.

        SENTINEL: any non-zero raw delegation -> HARNESS_ERROR (not COMPLETE).
        """
        if self.harness_error:
            return "HARNESS_ERROR"
        if (self.raw_resolver_delegations or self.raw_connector_delegations or self.raw_spawn_delegations):
            return "HARNESS_ERROR"  # raw delegation non-zero -> the guard delegated (harness error)
        if (self.denied_resolver_attempts or self.denied_connect_attempts or self.denied_spawn_attempts):
            return "BLOCKED_TRANSPORT_DENIED"
        if self.replay_misses:
            return "BLOCKED_REPLAY_INPUT_MISS"
        return "REPLAY_COMPLETE"

    def __enter__(self) -> "TransportGuard":
        self.install()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.uninstall()
        return False