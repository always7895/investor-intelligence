#!/usr/bin/env python3
"""Test-only replay/deny transport guard helper (TASK0-3D step B, R4/R3 deltas).

R4 delta: separate DENIED_*_ATTEMPTS (from the real guard, can be > 0 when
testing denials) from RAW_*_DELEGATIONS (measured by a bottom-layer sentinel
installed BEFORE the real guard; must be 0). The bottom-layer sentinel counts
on call, immediately raises a fixed error, and does NOT enter real I/O.

R3 delta: the request identity key includes method, full URL/query, body digest
(when present), and the relevant headers (Accept, Content-type) that affect the
response in the existing path. urlopen(url, data=...) is NOT treated as a
no-body GET hit (the data is in the key). Unsupported forms are rejected.

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
    """Build the identity key for a string URL (+ data) or urllib.request.Request.

    R3: supports string URL (+ data) + standard Request. The key includes method,
    full URL/query, body digest (when present), and the relevant headers (Accept,
    Content-type) that affect the response. urlopen(url, data=...) is NOT treated
    as a no-body GET hit (the data is in the key). Unsupported forms return None.
    """
    if isinstance(url, str):
        method = "POST" if data else "GET"
        body_digest = hashlib.sha256(data).hexdigest()[:16] if data else ""
        return f"{method}|{url}|{body_digest}|"
    if isinstance(url, urllib.request.Request):
        method = (url.get_method() or "GET").upper()
        full_url = url.full_url
        body = url.data
        body_digest = hashlib.sha256(body).hexdigest()[:16] if body else ""
        accept = url.get_header("Accept") or ""
        content_type = url.get_header("Content-type") or ""
        return f"{method}|{full_url}|{body_digest}|{accept}|{content_type}"
    return None  # unsupported form -> rejected


class TransportGuard:
    """Replay/deny transport guard. Installed BEFORE the application loads."""

    def __init__(self) -> None:
        self.registry: dict[str, dict[str, Any]] = {}
        self.replay_hits: list[str] = []
        self.replay_misses: list[str] = []
        # R4: DENIED_*_ATTEMPTS (from the real guard, can be > 0 when testing denials).
        self.denied_resolver_attempts: int = 0
        self.denied_connect_attempts: int = 0
        self.denied_spawn_attempts: int = 0
        # R4: RAW_*_DELEGATIONS (measured by the bottom-layer sentinel; must be 0).
        self.raw_resolver_delegations: int = 0
        self.raw_connector_delegations: int = 0
        self.raw_spawn_delegations: int = 0
        self.harness_error: str | None = None
        self._orig_urlopen = urllib.request.urlopen
        self._orig_create_connection = socket.create_connection
        self._orig_getaddrinfo = socket.getaddrinfo
        self._orig_socket_class = socket.socket
        self._orig_popen = subprocess.Popen
        self._installed = False

    def register(self, url: Any, status: int, body: bytes, metadata: dict[str, Any] | None = None,
                 data: bytes | None = None) -> None:
        key = _request_key(url, data)
        if key is None:
            raise ValueError(f"unsupported request form: {type(url)}")
        self.registry[key] = {
            "status": status,
            "body": body,
            "sha256": hashlib.sha256(body).hexdigest(),
            "metadata": metadata or {},
        }

    def install(self) -> None:
        if self._installed:
            return
        guard = self

        # R4: install the bottom-layer sentinel FIRST (counts on call, immediately
        # raises a fixed error, does NOT enter real I/O). This measures
        # RAW_*_DELEGATIONS (must be 0 if the real guard denies before delegating).
        def sentinel_getaddrinfo(host, port, *args, **kwargs):
            guard.raw_resolver_delegations += 1
            raise ReplayMiss(f"SENTINEL: raw DNS delegation at {host}")

        def sentinel_create_connection(address, *args, **kwargs):
            guard.raw_connector_delegations += 1
            raise ReplayMiss(f"SENTINEL: raw connector delegation at {address}")

        def sentinel_popen(*args, **kwargs):
            guard.raw_spawn_delegations += 1
            raise ReplayMiss(f"SENTINEL: raw spawn delegation {args[:1]}")

        # Save the ORIGINAL functions (for uninstall); the sentinel replaces them
        # first, then the real guard replaces the sentinel.
        self._sentinel_getaddrinfo = sentinel_getaddrinfo
        self._sentinel_create_connection = sentinel_create_connection
        self._sentinel_popen = sentinel_popen
        socket.getaddrinfo = sentinel_getaddrinfo
        socket.create_connection = sentinel_create_connection
        subprocess.Popen = sentinel_popen

        # Now install the real guard (denies unregistered requests; does NOT
        # delegate to the sentinel, so RAW_*_DELEGATIONS stays 0).
        def guarded_urlopen(url, *args, **kwargs):
            data = kwargs.get("data")
            key = _request_key(url, data)
            if key is None:
                guard.denied_connect_attempts += 1
                raise ReplayMiss(f"REPLAY_INPUT_MISS: unsupported request form {type(url)}")
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

        urllib.request.urlopen = guarded_urlopen
        socket.create_connection = guarded_create_connection
        socket.getaddrinfo = guarded_getaddrinfo
        socket.socket = _GuardedSocket
        subprocess.Popen = guarded_popen
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        urllib.request.urlopen = self._orig_urlopen
        socket.create_connection = self._orig_create_connection
        socket.getaddrinfo = self._orig_getaddrinfo
        socket.socket = self._orig_socket_class
        subprocess.Popen = self._orig_popen
        self._installed = False

    def verdict(self) -> str:
        """R2: explicit mutually-exclusive results."""
        if self.harness_error:
            return "HARNESS_ERROR"
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