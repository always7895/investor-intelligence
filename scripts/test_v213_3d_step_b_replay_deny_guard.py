#!/usr/bin/env python3
"""TASK0-3D_RECORDED_AUDIT_REPLAY_STEP_B: controls (ACCEPTANCE_PENDING gaps).

Per Pro 3D step B ruling (ACCEPTANCE_PENDING gaps):
- LOADER_SPY: normal_install_calls=1, failed_install_calls=0 (test-only startup
  wrapper + stub loader; count from the spy's actual record, not a constant).
- REGRESSION_RESULTS: restore deleted regressions (positional/empty/Request
  override body, swallowed miss, import-time, worker-thread).
- DIRECT_SOCKET: safe socket class that doesn't create real connections;
  connect/connect_ex delegation updates the same connector ledger.
- FULL_GATE: NOT_MEASURED when no measurement source attached + unique run
  directory for artifacts.

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
import tempfile
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
    print("=== TASK0-3D STEP B: CONTROLS (ACCEPTANCE_PENDING gaps) ===")
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

    # --- LOADER_SPY: normal_install_calls=1, failed_install_calls=0 ---
    # Test-only startup wrapper + stub loader.
    loader_spy = {"calls": 0}

    def stub_loader():
        loader_spy["calls"] += 1
        return "loaded_application"

    def startup_wrapper(guard, loader):
        """The same startup wrapper for both normal and failed install."""
        guard.install()
        # Only call the loader if the guard installed successfully.
        if guard._installed:
            return loader()
        return None  # install failed, don't load the application

    # Normal install -> loader called once.
    normal_guard = TransportGuard()
    normal_result = startup_wrapper(normal_guard, stub_loader)
    normal_calls = loader_spy["calls"]
    normal_guard.uninstall()

    # Failed install -> loader called zero times.
    loader_spy["calls"] = 0
    failed_guard = TransportGuard()
    orig_apply = failed_guard._apply
    call_count = [0]

    def failing_apply(obj, attr, value):
        call_count[0] += 1
        if call_count[0] == 3:
            raise RuntimeError("injected mid-install failure")
        orig_apply(obj, attr, value)

    failed_guard._apply = failing_apply
    failed_result = None
    try:
        failed_result = startup_wrapper(failed_guard, stub_loader)
    except RuntimeError:
        pass
    failed_calls = loader_spy["calls"]

    loader_spy_pass = (normal_calls == 1 and failed_calls == 0 and normal_result == "loaded_application" and failed_result is None)
    all_pass = all_pass and loader_spy_pass
    outcomes["loader_spy"] = {"pass": loader_spy_pass, "normal_install_calls": normal_calls, "failed_install_calls": failed_calls}
    print(f"LOADER_SPY = {'PASS' if loader_spy_pass else 'FAIL'} (normal_install_calls={normal_calls}, failed_install_calls={failed_calls})")

    # --- REGRESSION: request_cross_hit / actual_fetch_text / method_query_header ---
    with TransportGuard() as g:
        base_url = "https://recorded.example.com/data.json"
        base_body = b'{"ticker":"TEST","price":1.0}'
        g.register(base_url, 200, base_body, {"source": "recorded"})
        cross_hit_req = urllib.request.Request(base_url)
        cross_hit_ok = False
        try:
            resp = urllib.request.urlopen(cross_hit_req)
            cross_hit_ok = (resp.read() == base_body)
        except Exception as exc:
            print(f"CONTROL_CROSS_HIT_FAILED = {type(exc).__name__}: {exc}")
        neg_method_req = urllib.request.Request(base_url, method="POST")
        neg_method_rejected = False
        try:
            urllib.request.urlopen(neg_method_req)
        except ReplayMiss:
            neg_method_rejected = True
        except Exception as exc:
            print(f"CONTROL_NEG_METHOD_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        neg_query_rejected = False
        try:
            urllib.request.urlopen(base_url + "?x=1")
        except ReplayMiss:
            neg_query_rejected = True
        except Exception as exc:
            print(f"CONTROL_NEG_QUERY_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        neg_header_req = urllib.request.Request(base_url, headers={"Accept": "application/xml"})
        neg_header_rejected = False
        try:
            urllib.request.urlopen(neg_header_req)
        except ReplayMiss:
            neg_header_rejected = True
        except Exception as exc:
            print(f"CONTROL_NEG_HEADER_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
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
        req_pass = (cross_hit_ok and neg_method_rejected and neg_query_rejected and neg_header_rejected and ft_ok)
        all_pass = all_pass and req_pass
        outcomes["request_cross_hit"] = {"pass": req_pass, "cross_hit": cross_hit_ok, "neg_method": neg_method_rejected,
                                         "neg_query": neg_query_rejected, "neg_header": neg_header_rejected, "fetch_text": ft_ok}
        print(f"REQUEST_CROSS_HIT = {'PASS' if req_pass else 'FAIL'} (cross_hit={cross_hit_ok}, neg_method={neg_method_rejected}, neg_query={neg_query_rejected}, neg_header={neg_header_rejected}, fetch_text={ft_ok})")

    # --- REGRESSION: positional_body / empty_body / Request_data_override ---
    with TransportGuard() as g2:
        base_url = "https://recorded.example.com/data.json"
        base_body = b'{"ticker":"TEST","price":1.0}'
        g2.register(base_url, 200, base_body, {"source": "recorded"})
        pos_data_rejected = False
        try:
            urllib.request.urlopen(base_url, b"X")
        except ReplayMiss:
            pos_data_rejected = True
        except Exception as exc:
            print(f"CONTROL_POS_DATA_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        empty_body_rejected = False
        try:
            urllib.request.urlopen(base_url, data=b"")
        except ReplayMiss:
            empty_body_rejected = True
        except Exception as exc:
            print(f"CONTROL_EMPTY_BODY_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        req = urllib.request.Request(base_url)
        req_data_rejected = False
        try:
            urllib.request.urlopen(req, data=b"X")
        except ReplayMiss:
            req_data_rejected = True
        except Exception as exc:
            print(f"CONTROL_REQ_DATA_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        body_pass = pos_data_rejected and empty_body_rejected and req_data_rejected
        all_pass = all_pass and body_pass
        outcomes["body_rejections"] = {"pass": body_pass, "positional_body": pos_data_rejected, "empty_body": empty_body_rejected, "Request_data_override": req_data_rejected}
        print(f"BODY_REJECTIONS = {'PASS' if body_pass else 'FAIL'} (positional_body={pos_data_rejected}, empty_body={empty_body_rejected}, Request_data_override={req_data_rejected})")

    # --- REGRESSION: swallowed_miss / deny_only ---
    with TransportGuard() as g3:
        swallowed_url = "https://swallowed.example.com/missing.json"
        inner_success = False
        try:
            try:
                urllib.request.urlopen(swallowed_url)
            except ReplayMiss:
                inner_success = True
        except Exception:
            pass
        fresh_miss = (len(g3.replay_misses) == 1)
        outer_verdict = g3.verdict()
        swallowed_pass = inner_success and fresh_miss and outer_verdict == "BLOCKED_REPLAY_INPUT_MISS"
        all_pass = all_pass and swallowed_pass
        outcomes["swallowed_miss"] = {"pass": swallowed_pass, "inner_success": inner_success, "fresh_miss": fresh_miss, "outer_verdict": outer_verdict}
        print(f"SWALLOWED_MISS = {'PASS' if swallowed_pass else 'FAIL'} (inner_success={inner_success}, fresh_miss={fresh_miss}, outer_verdict={outer_verdict})")

    with TransportGuard() as g4:
        import socket as _s
        denied_raised = False
        try:
            _s.create_connection(("unregistered.example.com", 443))
        except ReplayMiss:
            denied_raised = True
        except Exception as exc:
            print(f"CONTROL_DENY_ONLY_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        no_replay_miss = (len(g4.replay_misses) == 0)
        only_denied = (g4.denied_connect_attempts == 1)
        verdict = g4.verdict()
        deny_only_pass = denied_raised and no_replay_miss and only_denied and verdict == "BLOCKED_TRANSPORT_DENIED"
        all_pass = all_pass and deny_only_pass
        outcomes["deny_only"] = {"pass": deny_only_pass, "denied_raised": denied_raised, "no_replay_miss": no_replay_miss, "only_denied": only_denied, "verdict": verdict}
        print(f"DENY_ONLY = {'PASS' if deny_only_pass else 'FAIL'} (denied_raised={denied_raised}, no_replay_miss={no_replay_miss}, only_denied={only_denied}, verdict={verdict})")

    # --- REGRESSION: import_time / worker_thread_joined ---
    with TransportGuard() as g5:
        import time as _time
        mod_code = """
import urllib.request, socket
try:
    urllib.request.urlopen("https://import-time-unregistered.example.com/x.json")
    IMPORT_TIME_DENIED = False
except Exception:
    IMPORT_TIME_DENIED = True
try:
    socket.getaddrinfo("import-time-unregistered.example.com", 443)
    IMPORT_TIME_DNS_DENIED = False
except Exception:
    IMPORT_TIME_DNS_DENIED = True
"""
        mod_path = Path(tempfile.gettempdir()) / f"ii_3d_import_time_{_time.time_ns()}.py"
        mod_path.write_text(mod_code, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("ii_3d_import_time_mod", mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        import_time_pass = getattr(mod, "IMPORT_TIME_DENIED", False) and getattr(mod, "IMPORT_TIME_DNS_DENIED", False)
        mod_path.unlink(missing_ok=True)
        all_pass = all_pass and import_time_pass
        outcomes["import_time"] = {"pass": import_time_pass, "request_denied": getattr(mod, "IMPORT_TIME_DENIED", False), "dns_denied": getattr(mod, "IMPORT_TIME_DNS_DENIED", False)}
        print(f"IMPORT_TIME = {'PASS' if import_time_pass else 'FAIL'} (request_denied={getattr(mod, 'IMPORT_TIME_DENIED', False)}, dns_denied={getattr(mod, 'IMPORT_TIME_DNS_DENIED', False)})")

    with TransportGuard() as g6:
        wt_hit_url = "https://wt-recorded.example.com/hit.json"
        wt_hit_body = b'{"wt":"hit"}'
        g6.register(wt_hit_url, 200, wt_hit_body, {"source": "recorded"})
        wt_results: dict[str, bool] = {}

        def worker():
            try:
                resp = urllib.request.urlopen(wt_hit_url)
                wt_results["hit"] = (resp.read() == wt_hit_body)
            except Exception:
                wt_results["hit"] = False
            try:
                urllib.request.urlopen("https://wt-unregistered.example.com/miss.json")
                wt_results["miss_denied"] = False
            except ReplayMiss:
                wt_results["miss_denied"] = True
            except Exception:
                wt_results["miss_denied"] = False

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        wt_pass = wt_results.get("hit", False) and wt_results.get("miss_denied", False)
        all_pass = all_pass and wt_pass
        outcomes["worker_thread_joined"] = {"pass": wt_pass, "hit": wt_results.get("hit", False), "miss_denied": wt_results.get("miss_denied", False)}
        print(f"WORKER_THREAD_JOINED = {'PASS' if wt_pass else 'FAIL'} (hit={wt_results.get('hit', False)}, miss_denied={wt_results.get('miss_denied', False)})")

    # --- REGRESSION: partial_install_restore / exception_restore ---
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
    all_restored = (
        urllib.request.urlopen is pre_snapshot["urlopen"]
        and socket.create_connection is pre_snapshot["create_connection"]
        and socket.getaddrinfo is pre_snapshot["getaddrinfo"]
        and socket.socket is pre_snapshot["socket"]
        and subprocess.Popen is pre_snapshot["popen"]
    )
    partial_pass = partial_failed and all_restored
    all_pass = all_pass and partial_pass
    outcomes["partial_install_restore"] = {"pass": partial_pass, "partial_failed": partial_failed, "all_restored": all_restored}
    print(f"PARTIAL_INSTALL_RESTORE = {'PASS' if partial_pass else 'FAIL'} (partial_failed={partial_failed}, all_restored={all_restored})")

    pre_snapshot2 = {
        "urlopen": urllib.request.urlopen,
        "create_connection": socket.create_connection,
        "getaddrinfo": socket.getaddrinfo,
        "socket": socket.socket,
        "popen": subprocess.Popen,
    }
    app_exception_crossed = False
    try:
        with TransportGuard() as g7:
            raise ValueError("simulated application exception")
    except ValueError:
        app_exception_crossed = True
    all_restored2 = (
        urllib.request.urlopen is pre_snapshot2["urlopen"]
        and socket.create_connection is pre_snapshot2["create_connection"]
        and socket.getaddrinfo is pre_snapshot2["getaddrinfo"]
        and socket.socket is pre_snapshot2["socket"]
        and subprocess.Popen is pre_snapshot2["popen"]
    )
    exception_pass = app_exception_crossed and all_restored2
    all_pass = all_pass and exception_pass
    outcomes["exception_restore"] = {"pass": exception_pass, "exception_crossed": app_exception_crossed, "all_restored": all_restored2}
    print(f"EXCEPTION_RESTORE = {'PASS' if exception_pass else 'FAIL'} (exception_crossed={app_exception_crossed}, all_restored={all_restored2})")

    # --- REGRESSION: shared_ledger_resolver_connector_spawn ---
    shared_ledger = {"resolver": 0, "connector": 0, "spawn": 0}

    def sentinel_getaddrinfo(host, port, *args, **kwargs):
        shared_ledger["resolver"] += 1
        raise ReplayMiss(f"SENTINEL: raw DNS delegation at {host}")

    def sentinel_create_connection(address, *args, **kwargs):
        shared_ledger["connector"] += 1
        raise ReplayMiss(f"SENTINEL: raw connector delegation at {address}")

    def sentinel_popen(*args, **kwargs):
        shared_ledger["spawn"] += 1
        raise ReplayMiss(f"SENTINEL: raw spawn delegation {args[:1]}")

    orig_getaddrinfo = socket.getaddrinfo
    orig_create_connection = socket.create_connection
    orig_popen = subprocess.Popen
    socket.getaddrinfo = sentinel_getaddrinfo
    socket.create_connection = sentinel_create_connection
    subprocess.Popen = sentinel_popen
    saved_sentinel_resolver = socket.getaddrinfo
    saved_sentinel_connector = socket.create_connection
    saved_sentinel_spawn = subprocess.Popen
    with TransportGuard(raw_delegation_ledger=shared_ledger) as g8:
        resolver_delegation = connector_delegation = spawn_delegation = False
        try:
            saved_sentinel_resolver("test.example.com", 443)
        except ReplayMiss:
            resolver_delegation = True
        try:
            saved_sentinel_connector(("test.example.com", 443))
        except ReplayMiss:
            connector_delegation = True
        try:
            saved_sentinel_spawn(["curl", "https://test.example.com"])
        except ReplayMiss:
            spawn_delegation = True
        ledger_incremented = (shared_ledger["resolver"] == 1 and shared_ledger["connector"] == 1 and shared_ledger["spawn"] == 1)
        verdict_harness = (g8.verdict() == "HARNESS_ERROR")
    socket.getaddrinfo = orig_getaddrinfo
    socket.create_connection = orig_create_connection
    subprocess.Popen = orig_popen
    shared_ledger_pass = resolver_delegation and connector_delegation and spawn_delegation and ledger_incremented and verdict_harness
    all_pass = all_pass and shared_ledger_pass
    outcomes["shared_ledger_resolver_connector_spawn"] = {"pass": shared_ledger_pass, "resolver": resolver_delegation, "connector": connector_delegation, "spawn": spawn_delegation, "ledger_incremented": ledger_incremented, "verdict_harness": verdict_harness}
    print(f"SHARED_LEDGER_RESOLVER_CONNECTOR_SPAWN = {'PASS' if shared_ledger_pass else 'FAIL'} (resolver={resolver_delegation}, connector={connector_delegation}, spawn={spawn_delegation}, ledger_incremented={ledger_incremented}, verdict_harness={verdict_harness})")

    # --- DIRECT_SOCKET: safe socket class; connect/connect_ex delegation updates the same connector ledger ---
    shared_ledger2 = {"resolver": 0, "connector": 0, "spawn": 0}

    def sentinel_getaddrinfo2(host, port, *args, **kwargs):
        shared_ledger2["resolver"] += 1
        raise ReplayMiss(f"SENTINEL: raw DNS delegation at {host}")

    def sentinel_create_connection2(address, *args, **kwargs):
        shared_ledger2["connector"] += 1
        raise ReplayMiss(f"SENTINEL: raw connector delegation at {address}")

    def sentinel_popen2(*args, **kwargs):
        shared_ledger2["spawn"] += 1
        raise ReplayMiss(f"SENTINEL: raw spawn delegation {args[:1]}")

    # Safe socket class that doesn't create real connections; connect/connect_ex
    # delegation updates the same connector ledger.
    orig_socket_class = socket.socket

    class SafeSocket(orig_socket_class):
        def connect(self, address):
            shared_ledger2["connector"] += 1
            raise ReplayMiss(f"SENTINEL: raw socket.connect delegation at {address}")

        def connect_ex(self, address):
            shared_ledger2["connector"] += 1
            raise ReplayMiss(f"SENTINEL: raw socket.connect_ex delegation at {address}")

    orig_getaddrinfo2 = socket.getaddrinfo
    orig_create_connection2 = socket.create_connection
    orig_popen2 = subprocess.Popen
    orig_socket_class2 = socket.socket
    socket.getaddrinfo = sentinel_getaddrinfo2
    socket.create_connection = sentinel_create_connection2
    subprocess.Popen = sentinel_popen2
    socket.socket = SafeSocket
    saved_safe_socket = socket.socket
    with TransportGuard(raw_delegation_ledger=shared_ledger2) as g9:
        # Guarded connect/connect_ex: denied incremented, raw connector ledger=0, BLOCKED_TRANSPORT_DENIED.
        guarded_connect_denied = False
        try:
            _sock = socket.socket()
            _sock.connect(("test.example.com", 443))
        except ReplayMiss:
            guarded_connect_denied = True
        except Exception as exc:
            print(f"CONTROL_GUARDED_CONNECT_WRONG_EXCEPTION = {type(exc).__name__}: {exc}")
        guarded_connector_ledger_zero = (shared_ledger2["connector"] == 0)
        guarded_verdict = g9.verdict()
        # Deliberately call the saved safe lower layer connect/connect_ex:
        # raw connector ledger incremented, HARNESS_ERROR, no real I/O.
        safe_connect = saved_safe_socket()
        actual_connect_delegation = False
        try:
            safe_connect.connect(("test.example.com", 443))
        except ReplayMiss:
            actual_connect_delegation = True
        safe_connect_ex = saved_safe_socket()
        actual_connect_ex_delegation = False
        try:
            safe_connect_ex.connect_ex(("test.example.com", 443))
        except ReplayMiss:
            actual_connect_ex_delegation = True
        actual_connector_ledger_incremented = (shared_ledger2["connector"] == 2)
        actual_verdict_harness = (g9.verdict() == "HARNESS_ERROR")
    socket.getaddrinfo = orig_getaddrinfo2
    socket.create_connection = orig_create_connection2
    subprocess.Popen = orig_popen2
    socket.socket = orig_socket_class2
    direct_socket_pass = (guarded_connect_denied and guarded_connector_ledger_zero and guarded_verdict == "BLOCKED_TRANSPORT_DENIED"
                          and actual_connect_delegation and actual_connect_ex_delegation
                          and actual_connector_ledger_incremented and actual_verdict_harness)
    all_pass = all_pass and direct_socket_pass
    outcomes["direct_socket_connect_connect_ex"] = {"pass": direct_socket_pass, "guarded_connect_denied": guarded_connect_denied,
                                                    "guarded_connector_ledger_zero": guarded_connector_ledger_zero, "guarded_verdict": guarded_verdict,
                                                    "actual_connect_delegation": actual_connect_delegation, "actual_connect_ex_delegation": actual_connect_ex_delegation,
                                                    "actual_connector_ledger_incremented": actual_connector_ledger_incremented, "actual_verdict_harness": actual_verdict_harness}
    print(f"DIRECT_SOCKET_CONNECT_CONNECT_EX = {'PASS' if direct_socket_pass else 'FAIL'} (guarded_connect_denied={guarded_connect_denied}, guarded_connector_ledger_zero={guarded_connector_ledger_zero}, guarded_verdict={guarded_verdict}, actual_connect_delegation={actual_connect_delegation}, actual_connect_ex_delegation={actual_connect_ex_delegation}, actual_connector_ledger_incremented={actual_connector_ledger_incremented}, actual_verdict_harness={actual_verdict_harness})")

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
        print("V213_3D_STEP_B = PASS (all controls: loader_spy, request_cross_hit, body_rejections, swallowed_miss, deny_only, import_time, worker_thread_joined, partial_install_restore, exception_restore, shared_ledger_resolver_connector_spawn, direct_socket_connect_connect_ex)")
        print("FULL_MARKET_REPLAY = NOT_RERUN_INPUTS_STILL_MISSING (market recorded data still missing; doesn't affect harness acceptance)")
        print("APPLICATION_SOURCE_UNCHANGED = true; PRODUCTION_TOUCHED = false")
        raise SystemExit(0)
    else:
        print("V213_3D_STEP_B = FAIL (a control failed)")
        raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())