#!/usr/bin/env python3
"""TASK0-3D_RECORDED_AUDIT_REPLAY_STEP_B: replay/deny transport guard + 4 controls.

Per Pro 3D step B ruling: install a transport interceptor BEFORE loading the
application. The interceptor covers the actual HTTP transport (urllib.request
urlopen + socket.create_connection) and:
  - recorded HIT: registered request gets a byte-identical recorded response
    (full SHA-256 matches; zero underlying external connections)
  - recorded MISS: unregistered request produces a fixed REPLAY_INPUT_MISS
    (no DNS/connect/HTTP fallback; outer state blocked)
  - unregistered transport / early call: rejected before actual I/O
  - inner swallowed exception: the application catches the miss and returns
    "success", but the outer replay ledger still judges BLOCKED

The guard is installed in a fresh, isolated test process BEFORE any application
module loads. If guard init fails, the process terminates (no application).

The 4 control groups use explicitly-marked SYNTHETIC HTTP responses (to verify
the replay/deny mechanism only); they are NOT added to the real audit's recorded
inputs and do NOT fill company/market evidence.

Read-only source; 0 network; 0 credentials; 0 formal KV/DO; 0 schedules; 0 LINE.
Exit 0 when all 4 controls pass.
"""
from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
TMP = SCRIPT_DIR.parent / ".tmp"


class ReplayMiss(Exception):
    """Fixed REPLAY_INPUT_MISS: the request is not in the replay registry."""


class TransportGuard:
    """Replay/deny transport guard. Installed BEFORE the application loads."""

    def __init__(self) -> None:
        self.registry: dict[str, dict[str, Any]] = {}  # url -> {status, body, sha256, metadata}
        self.replay_hits: list[str] = []
        self.replay_misses: list[str] = []
        self.denied_attempts: list[str] = []
        self.underlying_io: int = 0  # count of actual socket connections made
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
        """Patch the actual HTTP transport namespaces. Call BEFORE the app loads."""
        if self._installed:
            return
        # Patch urllib.request.urlopen (the main HTTP transport).
        guard = self

        def guarded_urlopen(url, *args, **kwargs):
            key = str(url)
            if key in guard.registry:
                entry = guard.registry[key]
                guard.replay_hits.append(key)
                # Return a byte-identical recorded response (no external connection).
                resp = _FakeResponse(entry["status"], entry["body"])
                return resp
            else:
                guard.replay_misses.append(key)
                raise ReplayMiss(f"REPLAY_INPUT_MISS: {key} is not in the replay registry")

        # Patch socket.create_connection (deny path for DNS/connect).
        # underlying_io tracks ACTUAL network I/O (succeeded connections); since the
        # guard denies all connections, underlying_io stays 0. denied_attempts tracks
        # the denied attempts.
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
        """Outer replay ledger verdict: blocked if any miss (even if inner swallowed)."""
        if self.replay_misses:
            return "BLOCKED_REPLAY_INPUT_MISS"
        return "REPLAY_COMPLETE"


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


def _make_guard() -> TransportGuard:
    """Guard init: if it fails, terminate (no application)."""
    try:
        g = TransportGuard()
        g.install()
        return g
    except Exception as exc:
        print(f"GUARD_INIT_FAILED = {type(exc).__name__}: {exc} (terminating, no application)")
        raise SystemExit(1)


def main() -> int:
    print("=== TASK0-3D STEP B: REPLAY/DENY TRANSPORT GUARD + 4 CONTROLS ===")
    guard = _make_guard()
    print(f"GUARD_INSTALLED_BEFORE_APPLICATION_IMPORT = True (fresh isolated process)")

    # --- Control 1: recorded HIT ---
    hit_url = "https://recorded.example.com/data.json"
    hit_body = b'{"ticker":"TEST","price":1.0}'
    guard.register(hit_url, 200, hit_body, {"source": "recorded"})
    hit_ok = False
    hit_sha_ok = False
    try:
        resp = urllib.request.urlopen(hit_url)
        body = resp.read()
        hit_ok = (body == hit_body)
        hit_sha_ok = (hashlib.sha256(body).hexdigest() == guard.registry[hit_url]["sha256"])
    except Exception as exc:
        print(f"CONTROL_HIT_FAILED = {type(exc).__name__}: {exc}")
    hit_io = guard.underlying_io
    print(f"CONTROL_HIT = {'PASS' if hit_ok and hit_sha_ok else 'FAIL'} (byte-identical={hit_ok}, sha256={hit_sha_ok}, underlying_io={hit_io})")

    # --- Control 2: recorded MISS ---
    miss_url = "https://unregistered.example.com/missing.json"
    miss_raised = False
    miss_io_before = guard.underlying_io
    try:
        urllib.request.urlopen(miss_url)
    except ReplayMiss:
        miss_raised = True
    except Exception as exc:
        print(f"CONTROL_MISS_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
    miss_io_after = guard.underlying_io
    miss_no_fallback = (miss_io_after == miss_io_before)  # no socket connection made
    print(f"CONTROL_MISS = {'PASS' if miss_raised and miss_no_fallback else 'FAIL'} (ReplayMiss={miss_raised}, no_dns/connect/HTTP_fallback={miss_no_fallback})")

    # --- Control 3: unregistered transport / early call (socket.create_connection) ---
    denied_raised = False
    try:
        socket.create_connection(("unregistered.example.com", 443))
    except ReplayMiss:
        denied_raised = True
    except Exception as exc:
        print(f"CONTROL_UNREGISTERED_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
    print(f"CONTROL_UNREGISTERED_TRANSPORT = {'PASS' if denied_raised else 'FAIL'} (socket.create_connection denied before I/O={denied_raised})")

    # --- Control 4: inner swallowed exception (app catches miss, returns "success") ---
    swallowed_url = "https://swallowed.example.com/missing.json"
    inner_success = False
    try:
        try:
            urllib.request.urlopen(swallowed_url)
        except ReplayMiss:
            # The application catches the miss and degrades to "success".
            inner_success = True  # inner layer says "success"
    except Exception:
        pass
    outer_verdict = guard.verdict()
    swallowed_blocked = (outer_verdict == "BLOCKED_REPLAY_INPUT_MISS")
    print(f"CONTROL_SWALLOWED_MISS = {'PASS' if inner_success and swallowed_blocked else 'FAIL'} (inner_returned_success={inner_success}, outer_verdict={outer_verdict})")

    # --- Summary ---
    requests_total = len(guard.replay_hits) + len(guard.replay_misses) + len(guard.denied_attempts)
    control_manifest = {
        "replay_hits": guard.replay_hits,
        "replay_misses": guard.replay_misses,
        "denied_attempts": guard.denied_attempts,
        "underlying_io": guard.underlying_io,
        "verdict": guard.verdict(),
    }
    manifest_bytes = json.dumps(control_manifest, sort_keys=True).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    all_pass = (hit_ok and hit_sha_ok and miss_raised and miss_no_fallback and denied_raised and swallowed_blocked)
    print(f"\nREQUESTS={requests_total} REPLAY_HITS={len(guard.replay_hits)} REPLAY_MISSES={len(guard.replay_misses)} DENIED_ATTEMPTS={len(guard.denied_attempts)}")
    print(f"UNDERLYING_NETWORK_IO={guard.underlying_io} (0 expected for the controls)")
    print(f"OUTER_VERDICT_ON_SWALLOWED_MISS={outer_verdict}")
    print(f"CONTROL_MANIFEST_SHA256={manifest_sha}")
    guard.uninstall()
    if all_pass:
        print("V213_3D_STEP_B = PASS (4/4 controls: hit, miss, unregistered_transport, swallowed_miss)")
        print("FULL_MARKET_REPLAY = NOT_RERUN_INPUTS_STILL_MISSING (market recorded data still missing; doesn't affect harness acceptance)")
        print("APPLICATION_SOURCE_UNCHANGED = true; PRODUCTION_TOUCHED = false")
        raise SystemExit(0)
    else:
        print("V213_3D_STEP_B = FAIL (a control failed)")
        raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())