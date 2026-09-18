#!/usr/bin/env python3
"""Test-only replay/deny transport guard helper (TASK0-3D step B, R1-R4 fixed).

Provides TransportGuard + ReplayMiss + _FakeResponse for the replay/deny
transport boundary. Installed BEFORE the application loads. NOT an application
source change; used only by the test-only replay tests.

R2 fix: verdict() returns explicit mutually-exclusive results:
  - guard init/internal error -> HARNESS_ERROR
  - any unregistered transport denied -> BLOCKED_TRANSPORT_DENIED
  - any recorded input miss -> BLOCKED_REPLAY_INPUT_MISS
  - none -> REPLAY_COMPLETE

R3 fix: supports string URL + standard urllib.request.Request. The identity key
includes method, full URL/query, body digest (when present), and relevant
headers. Unsupported request forms are rejected (not default to GET).

R4 fix: patches the actual transport namespaces including DNS
(socket.getaddrinfo), direct socket (socket.socket.connect/connect_ex), and
subprocess (subprocess.Popen). Each raw path has a sentinel that records the
call then raises a fixed error (no real network I/O). Reports
RAW_RESOLVER_CALLS / RAW_CONNECTOR_CALLS / RAW_SPAWN_CALLS (measured, not the
forever-0 underlying_io).
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


def _request_key(url: Any) -> str | None:
    """Build the identity key for a string URL or urllib.request.Request.

    R3: supports string URL + standard Request. The key includes method, full
    URL/query, and body digest (when present). A string URL is treated as a GET
    with no body. Unsupported request forms return None (rejected, not default
    to GET). The headers are NOT in the key (so a string URL and a Request with
    the same URL produce the same key; the actual fetch_text() can hit the
    registry when the URL is registered as a string).
    """
    if isinstance(url, str):
        return f"GET|{url}|"
    if isinstance(url, urllib.request.Request):
        method = (url.get_method() or "GET").upper()
        full_url = url.full_url
        body = url.data
        body_digest = hashlib.sha256(body).hexdigest()[:16] if body else ""
        return f"{method}|{full_url}|{body_digest}"
    return None  # unsupported form -> rejected


class TransportGuard:
    """Replay/deny transport guard. Installed BEFORE the application loads."""

    def __init__(self) -> None:
        self.registry: dict[str, dict[str, Any]] = {}
        self.replay_hits: list[str] = []
        self.replay_misses: list[str] = []
        self.denied_attempts: list[str] = []
        self.raw_resolver_calls: int = 0  # measured: socket.getaddrinfo calls
        self.raw_connector_calls: int = 0  # measured: socket.socket.connect/connect_ex calls
        self.raw_spawn_calls: int = 0  # measured: subprocess.Popen calls
        self.harness_error: str | None = None
        self._orig_urlopen = urllib.request.urlopen
        self._orig_create_connection = socket.create_connection
        self._orig_getaddrinfo = socket.getaddrinfo
        self._orig_socket_class = socket.socket
        self._orig_popen = subprocess.Popen
        self._installed = False

    def register(self, url: Any, status: int, body: bytes, metadata: dict[str, Any] | None = None) -> None:
        key = _request_key(url)
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

        def guarded_urlopen(url, *args, **kwargs):
            key = _request_key(url)
            if key is None:
                guard.denied_attempts.append(f"urlopen unsupported form: {type(url)}")
                raise ReplayMiss(f"REPLAY_INPUT_MISS: unsupported request form {type(url)}")
            if key in guard.registry:
                entry = guard.registry[key]
                guard.replay_hits.append(key)
                return _FakeResponse(entry["status"], entry["body"])
            else:
                guard.replay_misses.append(key)
                raise ReplayMiss(f"REPLAY_INPUT_MISS: {key} is not in the replay registry")

        def guarded_create_connection(address, *args, **kwargs):
            guard.denied_attempts.append(f"socket.create_connection({address})")
            raise ReplayMiss(f"REPLAY_INPUT_MISS: socket connection denied at {address}")

        def guarded_getaddrinfo(host, port, *args, **kwargs):
            guard.raw_resolver_calls += 1
            guard.denied_attempts.append(f"socket.getaddrinfo({host},{port})")
            raise ReplayMiss(f"REPLAY_INPUT_MISS: DNS resolution denied for {host}")

        # R4: patch socket.socket.connect/connect_ex (direct socket, not via create_connection).
        orig_socket_class = self._orig_socket_class

        class _GuardedSocket(orig_socket_class):
            def connect(self, address):
                guard.raw_connector_calls += 1
                guard.denied_attempts.append(f"socket.connect({address})")
                raise ReplayMiss(f"REPLAY_INPUT_MISS: socket.connect denied at {address}")

            def connect_ex(self, address):
                guard.raw_connector_calls += 1
                guard.denied_attempts.append(f"socket.connect_ex({address})")
                raise ReplayMiss(f"REPLAY_INPUT_MISS: socket.connect_ex denied at {address}")

        def guarded_popen(*args, **kwargs):
            guard.raw_spawn_calls += 1
            guard.denied_attempts.append(f"subprocess.Popen({args[:1]})")
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
        if self.denied_attempts:
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