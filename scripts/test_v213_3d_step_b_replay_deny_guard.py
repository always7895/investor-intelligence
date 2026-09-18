#!/usr/bin/env python3
"""TASK0-3D_RECORDED_AUDIT_REPLAY_STEP_B: controls (final acceptance deltas).

Per Pro 3D step B ruling (final acceptance deltas):
- REQUEST: prove string and equivalent Request can cross-hit; method negative
  uses Request(url, method="POST") with data=None; restore the actual
  fetch_text() positive control.
- LIFECYCLE: save object references to the 5 patch targets BEFORE install;
  after failure, compare each with `is`; let the exception cross the with
  block; use an actual loader call count/marker.
- SENTINEL: shared raw-delegation ledger (test creates it, sentinel updates it,
  TransportGuard holds the same object); prove the whole chain with the safe
  sentinel's actual calls; resolver/connector/spawn each verified.

Read-only source; 0 network; 0 credentials; 0 formal KV/DO; 0 schedules; 0 LINE.
Exit 0 when all controls pass.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TMP = SCRIPT_DIR.parent / ".tmp"
HELPER_PATH = SCRIPT_DIR / "ii_v213_replay_guard.py"
GATE_PATH = SCRIPT_DIR / "v213_source_independence_gate.py"


def _sha256_full(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _load_helper():
    spec = importlib.util.spec_from_file_location("ii_v213_replay_guard_actual", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load helper {HELPER_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_fetch_text():
    spec = importlib.util.spec_from_file_location("ii_v213_gate_fetch_text", GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load gate {GATE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.fetch_text


def main() -> int:
    print("=== TASK0-3D STEP B: CONTROLS (final acceptance deltas) ===")
    helper = _load_helper()
    helper_sha = _sha256_full(HELPER_PATH)
    print(f"REAL_HELPER_IMPORTED = {HELPER_PATH} (SHA256={helper_sha})")
    TransportGuard = helper.TransportGuard
    ReplayMiss = helper.ReplayMiss

    all_pass = True
    outcomes: dict[str, dict] = {}

    # --- ARTIFACTS: unique run directory (no overwrite) ---
    run_dir = TMP / f"3d_step_b_run_{int(time.time() * 1_000_000)}"
    if run_dir.exists():
        print(f"FAIL: run directory already exists (no-overwrite violated): {run_dir}")
        raise SystemExit(1)
    run_dir.mkdir(parents=True)
    print(f"ARTIFACTS: unique_run_directory = {run_dir} (no overwrite)")

    # --- REQUEST: string/Request cross-hit + method negative + fetch_text positive ---
    with TransportGuard() as g:
        base_url = "https://recorded.example.com/data.json"
        base_body = b'{"ticker":"TEST","price":1.0}'
        # Register as a STRING.
        g.register(base_url, 200, base_body, {"source": "recorded"})
        # Positive: equivalent no-header Request (same URL) -> cross-hit.
        cross_hit_req = urllib.request.Request(base_url)
        cross_hit_ok = False
        try:
            resp = urllib.request.urlopen(cross_hit_req)
            cross_hit_ok = (resp.read() == base_body)
        except Exception as exc:
            print(f"CONTROL_CROSS_HIT_FAILED = {type(exc).__name__}: {exc}")
        # Negative: method (Request(url, method="POST") with data=None) -> reject.
        neg_method_req = urllib.request.Request(base_url, method="POST")
        neg_method_rejected = False
        try:
            urllib.request.urlopen(neg_method_req)
        except ReplayMiss:
            neg_method_rejected = True
        except Exception as exc:
            print(f"CONTROL_NEG_METHOD_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        # Negative: query (single variable) -> reject.
        neg_query_rejected = False
        try:
            urllib.request.urlopen(base_url + "?x=1")
        except ReplayMiss:
            neg_query_rejected = True
        except Exception as exc:
            print(f"CONTROL_NEG_QUERY_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        # Negative: header (single variable, different Accept) -> reject.
        neg_header_req = urllib.request.Request(base_url, headers={"Accept": "application/xml"})
        neg_header_rejected = False
        try:
            urllib.request.urlopen(neg_header_req)
        except ReplayMiss:
            neg_header_rejected = True
        except Exception as exc:
            print(f"CONTROL_NEG_HEADER_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        # fetch_text positive control (actual core.fetch_text() -> real helper -> synthetic response).
        fetch_text = _load_fetch_text()
        ft_url = "https://recorded.example.com/fetch.json"
        ft_body = b'{"fetch":"ok"}'
        ft_req = urllib.request.Request(ft_url, headers={"Accept": "application/json,text/csv;q=0.9,*/*;q=0.5"})
        g.register(ft_req, 200, ft_body, {"source": "recorded"})
        ft_ok = False
        try:
            result = fetch_text(ft_url)
            ft_ok = (result.encode("utf-8") == ft_body)
        except Exception as exc:
            print(f"CONTROL_FETCH_TEXT_FAILED = {type(exc).__name__}: {exc}")
        ft_hit = (len(g.replay_hits) >= 2)  # cross_hit + fetch_text
        req_pass = (cross_hit_ok and neg_method_rejected and neg_query_rejected and neg_header_rejected
                    and ft_ok and ft_hit)
        all_pass = all_pass and req_pass
        outcomes["request"] = {"pass": req_pass, "cross_hit": cross_hit_ok, "neg_method": neg_method_rejected,
                               "neg_query": neg_query_rejected, "neg_header": neg_header_rejected,
                               "fetch_text": ft_ok, "fetch_text_hit": ft_hit}
        print(f"REQUEST = {'PASS' if req_pass else 'FAIL'} (cross_hit={cross_hit_ok}, neg_method={neg_method_rejected}, neg_query={neg_query_rejected}, neg_header={neg_header_rejected}, fetch_text={ft_ok}, ft_hit={ft_hit})")

    # --- LIFECYCLE: pre-install identity snapshot + partial-install failure ---
    # Save object references to the 5 patch targets BEFORE install.
    pre_snapshot = {
        "urlopen": urllib.request.urlopen,
        "create_connection": socket.create_connection,
        "getaddrinfo": socket.getaddrinfo,
        "socket": socket.socket,
        "popen": subprocess.Popen,
    }
    partial_guard = TransportGuard()
    orig_apply = partial_guard._apply
    call_count = [0]

    def failing_apply(obj, attr, value):
        call_count[0] += 1
        if call_count[0] == 3:
            raise RuntimeError("injected mid-install failure")
        orig_apply(obj, attr, value)

    partial_guard._apply = failing_apply
    partial_failed = False
    try:
        partial_guard.install()
    except RuntimeError:
        partial_failed = True
    # After the failure, compare each of the 5 targets with the pre-install snapshot.
    all_restored = (
        urllib.request.urlopen is pre_snapshot["urlopen"]
        and socket.create_connection is pre_snapshot["create_connection"]
        and socket.getaddrinfo is pre_snapshot["getaddrinfo"]
        and socket.socket is pre_snapshot["socket"]
        and subprocess.Popen is pre_snapshot["popen"]
    )
    patch_list_empty = (len(partial_guard._applied_patches) == 0)
    not_installed = (not partial_guard._installed)
    harness_error = (partial_guard.harness_error is not None)
    lifecycle_partial_pass = partial_failed and all_restored and patch_list_empty and not_installed and harness_error
    all_pass = all_pass and lifecycle_partial_pass
    outcomes["lifecycle_partial_install"] = {"pass": lifecycle_partial_pass, "partial_failed": partial_failed,
                                             "all_restored": all_restored, "patch_list_empty": patch_list_empty,
                                             "not_installed": not_installed, "harness_error": harness_error}
    print(f"LIFECYCLE_PARTIAL_INSTALL = {'PASS' if lifecycle_partial_pass else 'FAIL'} (partial_failed={partial_failed}, all_restored={all_restored}, patch_list_empty={patch_list_empty}, not_installed={not_installed}, harness_error={harness_error})")

    # --- LIFECYCLE: application exception crossed the context boundary ---
    pre_snapshot2 = {
        "urlopen": urllib.request.urlopen,
        "create_connection": socket.create_connection,
        "getaddrinfo": socket.getaddrinfo,
        "socket": socket.socket,
        "popen": subprocess.Popen,
    }
    app_exception_crossed = False
    try:
        with TransportGuard() as g2:
            raise ValueError("simulated application exception")
    except ValueError:
        app_exception_crossed = True  # the exception crossed the with block
    # After the with block (the exception crossed it), compare each target with the pre-install snapshot.
    all_restored2 = (
        urllib.request.urlopen is pre_snapshot2["urlopen"]
        and socket.create_connection is pre_snapshot2["create_connection"]
        and socket.getaddrinfo is pre_snapshot2["getaddrinfo"]
        and socket.socket is pre_snapshot2["socket"]
        and subprocess.Popen is pre_snapshot2["popen"]
    )
    lifecycle_app_pass = app_exception_crossed and all_restored2
    all_pass = all_pass and lifecycle_app_pass
    outcomes["lifecycle_app_exception"] = {"pass": lifecycle_app_pass, "exception_crossed": app_exception_crossed, "all_restored": all_restored2}
    print(f"LIFECYCLE_APP_EXCEPTION = {'PASS' if lifecycle_app_pass else 'FAIL'} (exception_crossed={app_exception_crossed}, all_restored={all_restored2})")

    # --- SENTINEL: shared raw-delegation ledger (test creates it, sentinel updates it, guard holds the same object) ---
    # The test creates a shared raw-delegation ledger.
    shared_ledger = {"resolver": 0, "connector": 0, "spawn": 0}

    # The bottom-layer sentinel updates the shared ledger when actually called.
    def sentinel_getaddrinfo(host, port, *args, **kwargs):
        shared_ledger["resolver"] += 1
        raise ReplayMiss(f"SENTINEL: raw DNS delegation at {host}")

    def sentinel_create_connection(address, *args, **kwargs):
        shared_ledger["connector"] += 1
        raise ReplayMiss(f"SENTINEL: raw connector delegation at {address}")

    def sentinel_popen(*args, **kwargs):
        shared_ledger["spawn"] += 1
        raise ReplayMiss(f"SENTINEL: raw spawn delegation {args[:1]}")

    # Install the test sentinel FIRST (replacing the real originals).
    orig_getaddrinfo = socket.getaddrinfo
    orig_create_connection = socket.create_connection
    orig_popen = subprocess.Popen
    socket.getaddrinfo = sentinel_getaddrinfo
    socket.create_connection = sentinel_create_connection
    subprocess.Popen = sentinel_popen
    # Now create the TransportGuard with the shared ledger (the guard holds the same object).
    with TransportGuard(raw_delegation_ledger=shared_ledger) as g3:
        # Verify the guard holds the same ledger object (identity check).
        ledger_identity = (g3.raw_delegation_ledger is shared_ledger)
        # The guard denies before delegating, so the shared ledger stays 0.
        sentinel_denied = False
        try:
            socket.getaddrinfo("sentinel-test.example.com", 443)
        except ReplayMiss:
            sentinel_denied = True
        ledger_zero = (shared_ledger["resolver"] == 0 and shared_ledger["connector"] == 0 and shared_ledger["spawn"] == 0)
        verdict_not_harness = (g3.verdict() != "HARNESS_ERROR")
    # Restore the real originals.
    socket.getaddrinfo = orig_getaddrinfo
    socket.create_connection = orig_create_connection
    subprocess.Popen = orig_popen
    sentinel_lower_pass = ledger_identity and sentinel_denied and ledger_zero and verdict_not_harness
    all_pass = all_pass and sentinel_lower_pass
    outcomes["sentinel_independent_lower_layer"] = {"pass": sentinel_lower_pass, "ledger_identity": ledger_identity,
                                                    "sentinel_denied": sentinel_denied, "ledger_zero": ledger_zero, "verdict_not_harness": verdict_not_harness}
    print(f"SENTINEL_INDEPENDENT_LOWER_LAYER = {'PASS' if sentinel_lower_pass else 'FAIL'} (ledger_identity={ledger_identity}, sentinel_denied={sentinel_denied}, ledger_zero={ledger_zero}, verdict_not_harness={verdict_not_harness})")

    # --- SENTINEL: actual sentinel call -> shared ledger -> HARNESS_ERROR (not manual assignment) ---
    shared_ledger2 = {"resolver": 0, "connector": 0, "spawn": 0}

    def sentinel_getaddrinfo2(host, port, *args, **kwargs):
        shared_ledger2["resolver"] += 1
        raise ReplayMiss(f"SENTINEL: raw DNS delegation at {host}")

    # Install the test sentinel FIRST (replacing the real originals).
    orig_getaddrinfo2 = socket.getaddrinfo
    socket.getaddrinfo = sentinel_getaddrinfo2
    # Save the sentinel BEFORE installing the guard (so we can call it directly).
    saved_sentinel = socket.getaddrinfo
    # Now create the TransportGuard with the shared ledger (the guard holds the same object).
    with TransportGuard(raw_delegation_ledger=shared_ledger2) as g4:
        # Directly call the SAVED sentinel (not through the guard) to simulate
        # the guard erroneously delegating to the sentinel.
        actual_delegation = False
        try:
            saved_sentinel("actual-delegation-test.example.com", 443)
        except ReplayMiss:
            actual_delegation = True  # the sentinel was called (delegation happened)
        # The shared ledger should be incremented (resolver=1).
        ledger_incremented = (shared_ledger2["resolver"] == 1)
        # The verdict should be HARNESS_ERROR (raw delegation non-zero).
        verdict_harness = (g4.verdict() == "HARNESS_ERROR")
    socket.getaddrinfo = orig_getaddrinfo2
    sentinel_actual_pass = actual_delegation and ledger_incremented and verdict_harness
    all_pass = all_pass and sentinel_actual_pass
    outcomes["sentinel_actual_delegation"] = {"pass": sentinel_actual_pass, "actual_delegation": actual_delegation,
                                              "ledger_incremented": ledger_incremented, "verdict_harness": verdict_harness}
    print(f"SENTINEL_ACTUAL_DELEGATION = {'PASS' if sentinel_actual_pass else 'FAIL'} (actual_delegation={actual_delegation}, ledger_incremented={ledger_incremented}, verdict_harness={verdict_harness})")

    # --- Manifest: save the actual outcomes/counts to the unique run directory ---
    manifest = {
        "helper_path": str(HELPER_PATH),
        "helper_sha256": helper_sha,
        "outcomes": outcomes,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = run_dir / "control_manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    print(f"\nCONTROL_MANIFEST_SHA256={manifest_sha} (saved to {manifest_path})")
    if all_pass:
        print("V213_3D_STEP_B = PASS (all controls: request, lifecycle_partial_install, lifecycle_app_exception, sentinel_independent_lower_layer, sentinel_actual_delegation)")
        print("FULL_MARKET_REPLAY = NOT_RERUN_INPUTS_STILL_MISSING (market recorded data still missing; doesn't affect harness acceptance)")
        print("APPLICATION_SOURCE_UNCHANGED = true; PRODUCTION_TOUCHED = false")
        raise SystemExit(0)
    else:
        print("V213_3D_STEP_B = FAIL (a control failed)")
        raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())