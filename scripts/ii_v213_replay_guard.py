#!/usr/bin/env python3
"""Test-only replay/deny transport guard helper (TASK0-3D step B).

Provides TransportGuard + ReplayMiss + _FakeResponse for the replay/deny
transport boundary. Installed BEFORE the application loads. NOT an application
source change; used only by the test-only replay tests.

The guard patches urllib.request.urlopen + socket.create_connection (the actual
HTTP transport namespaces) so that:
  - recorded HIT: registered request gets a byte-identical recorded response
  - recorded MISS: unregistered request raises ReplayMiss (no external connection)
  - unregistered transport: socket.create_connection denied before I/O
"""
from __future__ import annotations

import hashlib
import socket
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


class TransportGuard:
    """Replay/deny transport guard. Installed BEFORE the application loads."""

    def __init__(self) -> None:
        self.registry: dict[str, dict[str, Any]] = {}
        self.replay_hits: list[str] = []
        self.replay_misses: list[str] = []
        self.denied_attempts: list[str] = []
        self.underlying_io: int = 0  # actual succeeded connections (0; all denied)
        self._orig_urlopen = urllib.request.urlopen
        self._orig_create_connection = socket.create_connection
        self._installed = False

    def register(self, url: str, status: int, body: bytes, metadata: dict[str, Any] | None = None) -> None:
        self.registry[url] = {
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
            key = str(url)
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

        urllib.request.urlopen = guarded_urlopen
        socket.create_connection = guarded_create_connection
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        urllib.request.urlopen = self._orig_urlopen
        socket.create_connection = self._orig_create_connection
        self._installed = False

    def verdict(self) -> str:
        if self.replay_misses:
            return "BLOCKED_REPLAY_INPUT_MISS"
        return "REPLAY_COMPLETE"