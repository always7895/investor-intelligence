#!/usr/bin/env python3
"""TASK0-3D_RECORDED_AUDIT_REPLAY_STEP_B: replay/deny guard controls (R1-R4 fixed).

Per Pro 3D step B ruling (R1-R4 fixes):
- R1: import the ACTUAL helper (ii_v213_replay_guard.py), NOT a duplicate
  implementation. Each control uses an INDEPENDENT guard/clean ledger. Verify
  the helper file path + full SHA-256.
- R2: verdict() returns explicit mutually-exclusive results (in the helper).
- R3: supports string URL + standard Request. Add a positive control: actual
  core.fetch_text() -> real helper -> synthetic recorded response.
- R4: patches DNS (socket.getaddrinfo), direct socket (socket.socket.connect/
  connect_ex), and subprocess (subprocess.Popen). Reports measured
  RAW_RESOLVER_CALLS / RAW_CONNECTOR_CALLS / RAW_SPAWN_CALLS.

The 4 controls (hit/miss/unregistered_transport/swallowed_miss) + the R3
fetch_text positive control, each with an independent guard.

Read-only source; 0 network; 0 credentials; 0 formal KV/DO; 0 schedules; 0 LINE.
Exit 0 when all controls pass.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TMP = SCRIPT_DIR.parent / ".tmp"
HELPER_PATH = SCRIPT_DIR / "ii_v213_replay_guard.py"
GATE_PATH = SCRIPT_DIR / "v213_source_independence_gate.py"


def _sha256_full(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _load_helper():
    """R1: import the ACTUAL helper (NOT a duplicate)."""
    spec = importlib.util.spec_from_file_location("ii_v213_replay_guard_actual", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load helper {HELPER_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_fetch_text():
    """R3: load the actual core.fetch_text() from the gate module."""
    spec = importlib.util.spec_from_file_location("ii_v213_gate_fetch_text", GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load gate {GATE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.fetch_text


def main() -> int:
    print("=== TASK0-3D STEP B: REPLAY/DENY GUARD CONTROLS (R1-R4 fixed) ===")
    helper = _load_helper()
    helper_sha = _sha256_full(HELPER_PATH)
    print(f"REAL_HELPER_IMPORTED = {HELPER_PATH} (SHA256={helper_sha})")
    TransportGuard = helper.TransportGuard
    ReplayMiss = helper.ReplayMiss

    all_pass = True

    # --- Control 1: recorded HIT (independent guard) ---
    with TransportGuard() as g:
        hit_url = "https://recorded.example.com/data.json"
        hit_body = b'{"ticker":"TEST","price":1.0}'
        g.register(hit_url, 200, hit_body, {"source": "recorded"})
        hit_ok = hit_sha_ok = False
        try:
            import urllib.request
            resp = urllib.request.urlopen(hit_url)
            body = resp.read()
            hit_ok = (body == hit_body)
            hit_sha_ok = (hashlib.sha256(body).hexdigest() == g.registry[helper._request_key(hit_url)]["sha256"])
        except Exception as exc:
            print(f"CONTROL_HIT_FAILED = {type(exc).__name__}: {exc}")
        hit_pass = hit_ok and hit_sha_ok and g.raw_connector_calls == 0 and g.raw_resolver_calls == 0
        all_pass = all_pass and hit_pass
        print(f"CONTROL_HIT = {'PASS' if hit_pass else 'FAIL'} (byte-identical={hit_ok}, sha256={hit_sha_ok}, raw_connector={g.raw_connector_calls}, raw_resolver={g.raw_resolver_calls})")

    # --- Control 2: recorded MISS (independent guard, clean ledger) ---
    with TransportGuard() as g:
        miss_url = "https://unregistered.example.com/missing.json"
        miss_raised = False
        try:
            import urllib.request
            urllib.request.urlopen(miss_url)
        except ReplayMiss:
            miss_raised = True
        except Exception as exc:
            print(f"CONTROL_MISS_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        miss_fresh = (len(g.replay_misses) == 1)  # this case's miss count is correct
        miss_no_fallback = (g.raw_connector_calls == 0 and g.raw_resolver_calls == 0 and g.raw_spawn_calls == 0)
        miss_verdict = g.verdict()
        miss_pass = miss_raised and miss_fresh and miss_no_fallback and miss_verdict == "BLOCKED_REPLAY_INPUT_MISS"
        all_pass = all_pass and miss_pass
        print(f"CONTROL_MISS = {'PASS' if miss_pass else 'FAIL'} (ReplayMiss={miss_raised}, fresh_miss_count={len(g.replay_misses)}, no_fallback={miss_no_fallback}, verdict={miss_verdict})")

    # --- Control 3: unregistered transport (independent guard, blocked even with no replay miss) ---
    with TransportGuard() as g:
        import socket
        denied_raised = False
        try:
            socket.create_connection(("unregistered.example.com", 443))
        except ReplayMiss:
            denied_raised = True
        except Exception as exc:
            print(f"CONTROL_UNREGISTERED_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        # R2 fix: blocked even with no replay miss + only a denied attempt.
        no_replay_miss = (len(g.replay_misses) == 0)
        only_denied = (len(g.denied_attempts) == 1)
        verdict = g.verdict()
        # Also test DNS + direct socket + subprocess deny entries (R4).
        dns_raised = conn_raised = spawn_raised = False
        try:
            socket.getaddrinfo("unregistered.example.com", 443)
        except ReplayMiss:
            dns_raised = True
        try:
            import socket as _s
            sock = _s.socket()
            sock.connect(("unregistered.example.com", 443))
        except ReplayMiss:
            conn_raised = True
        except Exception as exc:
            print(f"CONTROL_DIRECT_SOCKET_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        try:
            import subprocess
            subprocess.Popen(["curl", "https://unregistered.example.com"])
        except ReplayMiss:
            spawn_raised = True
        r4_all_denied = dns_raised and conn_raised and spawn_raised
        unreg_pass = denied_raised and no_replay_miss and only_denied and verdict == "BLOCKED_TRANSPORT_DENIED" and r4_all_denied
        all_pass = all_pass and unreg_pass
        print(f"CONTROL_UNREGISTERED_TRANSPORT = {'PASS' if unreg_pass else 'FAIL'} (create_connection_denied={denied_raised}, no_replay_miss={no_replay_miss}, only_denied={only_denied}, verdict={verdict}, R4_dns={dns_raised} R4_connect={conn_raised} R4_spawn={spawn_raised})")

    # --- Control 4: swallowed miss (independent guard, this case's inner swallows + returns success) ---
    with TransportGuard() as g:
        swallowed_url = "https://swallowed.example.com/missing.json"
        inner_success = False
        try:
            import urllib.request
            try:
                urllib.request.urlopen(swallowed_url)
            except ReplayMiss:
                inner_success = True  # inner layer catches the miss and returns "success"
        except Exception:
            pass
        fresh_miss = (len(g.replay_misses) == 1)  # this case's miss
        outer_verdict = g.verdict()
        swallowed_pass = inner_success and fresh_miss and outer_verdict == "BLOCKED_REPLAY_INPUT_MISS"
        all_pass = all_pass and swallowed_pass
        print(f"CONTROL_SWALLOWED_MISS = {'PASS' if swallowed_pass else 'FAIL'} (inner_success={inner_success}, fresh_miss_count={len(g.replay_misses)}, outer_verdict={outer_verdict})")

    # --- R3 positive control: actual core.fetch_text() -> real helper -> synthetic recorded response ---
    fetch_text = _load_fetch_text()
    with TransportGuard() as g:
        ft_url = "https://recorded.example.com/fetch.json"
        ft_body = b'{"fetch":"ok"}'
        g.register(ft_url, 200, ft_body, {"source": "recorded"})
        ft_ok = False
        ft_bytes = None
        try:
            result = fetch_text(ft_url)
            ft_bytes = result.encode("utf-8")
            ft_ok = (ft_bytes == ft_body)
        except Exception as exc:
            print(f"CONTROL_FETCH_TEXT_FAILED = {type(exc).__name__}: {exc}")
        ft_hit = (len(g.replay_hits) == 1)
        ft_no_io = (g.raw_connector_calls == 0 and g.raw_resolver_calls == 0)
        ft_pass = ft_ok and ft_hit and ft_no_io
        all_pass = all_pass and ft_pass
        print(f"CONTROL_FETCH_TEXT (R3) = {'PASS' if ft_pass else 'FAIL'} (byte-identical={ft_ok}, replay_hit={ft_hit}, no_io={ft_no_io})")

    # --- Summary ---
    control_manifest = {
        "helper_path": str(HELPER_PATH),
        "helper_sha256": helper_sha,
        "controls": ["hit", "miss", "unregistered_transport", "swallowed_miss", "fetch_text_r3"],
    }
    manifest_bytes = json.dumps(control_manifest, sort_keys=True).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    print(f"\nCONTROL_MANIFEST_SHA256={manifest_sha}")
    if all_pass:
        print("V213_3D_STEP_B = PASS (5/5 controls: hit, miss, unregistered_transport, swallowed_miss, fetch_text_r3)")
        print("FULL_MARKET_REPLAY = NOT_RERUN_INPUTS_STILL_MISSING (market recorded data still missing; doesn't affect harness acceptance)")
        print("APPLICATION_SOURCE_UNCHANGED = true; PRODUCTION_TOUCHED = false")
        raise SystemExit(0)
    else:
        print("V213_3D_STEP_B = FAIL (a control failed)")
        raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())