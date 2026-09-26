"""Focused security regressions — MUST be RED on current code.

Targets material holes the existing green suite missed: absolute-deadline
timeout, unbounded slow probe, PRE failure leaking into callback, DURING
owner corruption hardcoding LEASE_HELD, guard close invalidating check,
process_probe=None/birth mutation, _publish overwriting foreign owner,
receipt rehash after structural tamper, retime chain by factor 100,
honest UNQUALIFIED verification, verifier returning caller object.
"""
import copy
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import v213_qa_capacity as qc  # noqa: E402

from tests.test_v213_qa_capacity import (  # noqa: E402
    BINDING, GPU_UUID, SERVICE, make_raw_snapshot,
)


def _root():
    return Path(tempfile.mkdtemp(prefix="qa-sec-"))


def _gpu_xml_extra_process(pid: int, ptype: str = "C+G") -> str:
    """Build XML from good fixture adding one extra process."""
    return (
        '<nvidia_smi_log><gpu id="0">'
        f'<uuid>{GPU_UUID}</uuid>'
        '<driver_model><current_dm>WDDM</current_dm></driver_model>'
        '<processes>'
        f'<process_info><pid>6432</pid><type>C</type></process_info>'
        f'<process_info><pid>{pid}</pid><type>{ptype}</type></process_info>'
        '</processes></gpu></nvidia_smi_log>'
    )


class TestSecurityRegressions(unittest.TestCase):
    def setUp(self):
        self.root = _root()
        self._leases = []

    def tearDown(self):
        for l in self._leases:
            try:
                l.close()
            except Exception:
                pass
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _lease(self, **kw):
        lease = qc.CapacityLease(self.root, BINDING, **kw)
        self._leases.append(lease)
        return lease

    # 1: run_window timeout_s=.08 — old code compares elapsed to absolute,
    #    so work(cancel).wait(1.0) causes >1s wall time before return.
    def test_run_window_timeout_bounded(self):
        lease = self._lease()
        cancel_observed = [False]

        def work(cancel_event):
            cancel_observed[0] = True
            cancel_event.wait(1.0)  # bounded, never infinite

        t0 = time.monotonic()
        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(), work,
            interval_s=0.01, max_gap_s=0.1, timeout_s=0.08)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.5,
                        f"run_window exceeded 0.5s bound: {elapsed:.3f}s")
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")
        self.assertTrue(cancel_observed[0], "cancel callback was not invoked")

    # 2: slow probe (0.8s) with timeout_s=.08 — old code does unbounded join
    #    on the probe thread, exceeding 0.8s before returning.
    def test_slow_probe_bounded_return(self):
        lease = self._lease()
        callback_called = [False]

        def slow_probe():
            time.sleep(0.8)
            return make_raw_snapshot()

        def work(cancel_event):
            callback_called[0] = True
            cancel_event.wait(0.3)

        t0 = time.monotonic()
        receipt = qc.run_window(
            lease, slow_probe, work,
            interval_s=0.01, max_gap_s=0.1, timeout_s=0.08)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.5,
                        f"slow probe caused >0.5s return: {elapsed:.3f}s")
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")
        self.assertFalse(callback_called[0],
                         "callback must NOT be called when PRE probe fails")

    # 3: PRE raw GPU extra C+G => callback NOT called, UNQUALIFIED.
    #    PRE missing clients => callback NOT called, UNQUALIFIED (UNKNOWN reason).
    def test_pre_gpu_extra_cg_no_callback(self):
        lease = self._lease()
        called = [False]
        bad_xml = _gpu_xml_extra_process(8888, "C+G")

        def work(cancel_event):
            called[0] = True

        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(gpu_xml=bad_xml), work,
            interval_s=0.01, max_gap_s=0.1, timeout_s=0.5)
        self.assertFalse(called[0], "work must NOT run when PRE GPU shows C+G")
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    def test_pre_missing_clients_no_callback(self):
        lease = self._lease()
        called = [False]

        def probe():
            raw = make_raw_snapshot()
            del raw["clients"]
            return raw

        def work(cancel_event):
            called[0] = True

        receipt = qc.run_window(
            lease, probe, work,
            interval_s=0.01, max_gap_s=0.1, timeout_s=0.5)
        self.assertFalse(called[0], "work must NOT run when PRE clients missing")
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    # 4: work during monitor corrupts owner.json => LEASE_HELD must be False
    #    (not hardcoded True), UNQUALIFIED, no certified release.
    def test_during_owner_corruption_lease_held_false(self):
        lease = self._lease()
        mp = lease.metadata_path

        def work(cancel_event):
            mp.write_bytes(b"\x00\x01corrupt")
            cancel_event.wait(0.3)

        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(), work,
            interval_s=0.01, max_gap_s=0.1, timeout_s=0.5)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")
        self.assertFalse(receipt["summary"]["LEASE_HELD"],
                         "LEASE_HELD must be False after owner corruption")
        self.assertFalse(receipt["summary"].get("lease_released", False),
                         "no certified release after corruption")

    # 5: Acquire lease, then lease.guard.close(); lease.check(nonce) MUST
    #    raise CapacityError despite intact owner.json.
    def test_guard_close_invalidates_check(self):
        lease = self._lease()
        meta = lease.acquire()
        nonce = meta["nonce"]
        lease.guard.close()
        with self.assertRaises(qc.CapacityError):
            lease.check(nonce)

    # 6: acquire with process_probe returning None must raise (cannot own
    #    with unverified birth).
    def test_acquire_process_probe_none_raises(self):
        lease = self._lease(process_probe=lambda pid: None)
        with self.assertRaises(qc.CapacityError):
            lease.acquire()

    # 7: lease.process_probe changes birth while held -> check raises.
    def test_process_probe_birth_change_check_raises(self):
        original_created = SERVICE["created"]
        birth_state = [original_created]

        def probe(pid):
            return {"alive": True, "created": birth_state[0]}

        lease = self._lease(process_probe=probe)
        meta = lease.acquire()
        nonce = meta["nonce"]
        # Mutate birth while held
        birth_state[0] = "2099-01-01T00:00:00Z"
        with self.assertRaises(qc.CapacityError):
            lease.check(nonce)

    # 8: _publish atomic helper under guard with preexisting foreign
    #    owner.json MUST refuse and preserve foreign bytes.
    def test_publish_refuses_foreign_owner(self):
        foreign_bytes = json.dumps(
            {"nonce": "foreign", "pid": 99999, "created": "2099-01-01T00:00:00Z"}
        ).encode()
        owner_path = self.root / "owner.json"
        owner_path.write_bytes(foreign_bytes)
        lease = self._lease()
        lease.guard.acquire()
        try:
            with self.assertRaises((qc.CapacityError, OSError)):
                lease._publish(b'new-owned-bytes')
        finally:
            lease.guard.close()
        # Foreign bytes preserved
        self.assertEqual(owner_path.read_bytes(), foreign_bytes)

    # 9: Generate clean receipt, then tamper + REHASH outer digest.
    #    Each MUST raise CapacityError (old code accepts several).
    def test_receipt_tamper_rehash_raises(self):
        lease = self._lease()
        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(),
            lambda ce: time.sleep(0.12),
            interval_s=0.02, max_gap_s=0.3, timeout_s=1)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "QUALIFIED")

        # Find the actual release event index
        release_idx = None
        for i, e in enumerate(receipt["events"]):
            if e.get("kind") == "release":
                release_idx = i
                break
        self.assertIsNotNone(release_idx, "no release event found")

        cases = [
            ("work_end_s", lambda r: r.__setitem__(
                "work_end_s", r["config"]["timeout_s"] + 10)),
            ("source_head", lambda r: r["lease"].__setitem__(
                "metadata", dict(r["lease"]["metadata"],
                                 source_head="0" * 40))),
            ("release_nonce", lambda r: r["events"].__setitem__(
                release_idx, dict(r["events"][release_idx], nonce="tampered"))),
            ("LEASE_HELD_toggle", lambda r: r["summary"].__setitem__(
                "LEASE_HELD", not r["summary"]["LEASE_HELD"])),
            ("reasons_invented", lambda r: r["summary"].__setitem__(
                "reasons", ["invented"])),
        ]
        for name, mutate in cases:
            with self.subTest(tamper=name):
                r = copy.deepcopy(receipt)
                mutate(r)
                # REHASH outer digest unconditionally
                body = {k: v for k, v in r.items() if k != "digest"}
                r["digest"] = qc.canonical_hash(body)
                with self.assertRaises(qc.CapacityError):
                    qc.verify_receipt(r, BINDING)

    # 10: Rehash sample chain after retiming all time_s/work times by
    #     factor 100, plus outer digest. Declared timeout/maxgap unchanged
    #     must refuse.
    def test_receipt_retime_factor100_raises(self):
        lease = self._lease()
        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(),
            lambda ce: time.sleep(0.12),
            interval_s=0.02, max_gap_s=0.3, timeout_s=1)
        r = copy.deepcopy(receipt)
        # Scale top-level work times by 100
        if r.get("work_start_s") is not None:
            r["work_start_s"] = r["work_start_s"] * 100
        if r.get("work_end_s") is not None:
            r["work_end_s"] = r["work_end_s"] * 100
        # Scale sample time fields by 100
        for s in r["samples"]:
            for key in list(s.keys()):
                if "time" in key or "work" in key or "started" in key or "ended" in key:
                    if isinstance(s[key], (int, float)):
                        s[key] = s[key] * 100
        # Leave config interval_s/max_gap_s/timeout_s UNCHANGED
        # Recompute EVERY sample chain in order
        prev_hash = None
        for s in r["samples"]:
            s["prev_hash"] = prev_hash
            body = {k: v for k, v in s.items() if k != "hash"}
            s["hash"] = qc.canonical_hash(body)
            prev_hash = s["hash"]
        # Recompute OUTER digest
        body = {k: v for k, v in r.items() if k != "digest"}
        r["digest"] = qc.canonical_hash(body)
        # Assert hashes validate manually
        for i, s in enumerate(r["samples"]):
            check = {k: v for k, v in s.items() if k != "hash"}
            self.assertEqual(qc.canonical_hash(check), s["hash"],
                             f"sample {i} hash invalid after recompute")
            if i > 0:
                self.assertEqual(s["prev_hash"], r["samples"][i - 1]["hash"],
                                 f"sample {i} prev_hash broken")
        # verify must raise: DURING samples no longer fall within scaled work window
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    # 11: Valid honest UNQUALIFIED (probe failure) verifies as UNQUALIFIED,
    #     not structural error. Summary never QUALIFIED.
    def test_honest_unqualified_verifies(self):
        lease = self._lease()

        def bad_probe():
            raise qc.CapacityError("probe timeout")

        receipt = qc.run_window(
            lease, bad_probe, lambda ce: time.sleep(0.1),
            interval_s=0.02, max_gap_s=0.3, timeout_s=1)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")
        # verify_receipt must pass (structurally valid) and return UNQUALIFIED
        result = qc.verify_receipt(receipt, BINDING)
        self.assertEqual(result["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    # 12: Successful clean receipt summary has all required fields;
    #     verifier returns computed equal value but NOT same stored object.
    def test_summary_fields_and_independent_recompute(self):
        lease = self._lease()
        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(),
            lambda ce: time.sleep(0.12),
            interval_s=0.02, max_gap_s=0.3, timeout_s=1)
        summary = receipt["summary"]
        required = [
            "LEASE_HELD", "MODEL_IDENTITY_VERIFIED",
            "SERVICE_IDENTITY_VERIFIED", "GPU_CONFLICT_OBSERVED",
            "TABBY_CONFLICT_OBSERVED", "MONITOR_COMPLETE",
            "CAPACITY_EVIDENCE",
        ]
        for field in required:
            self.assertIn(field, summary, f"missing required field: {field}")
        self.assertIn("lease_released", summary)
        # Verifier returns independent recompute, not caller object
        result = qc.verify_receipt(receipt, BINDING)
        self.assertEqual(result["CAPACITY_EVIDENCE"], "QUALIFIED")
        # result must be a distinct object (not the same summary dict)
        self.assertIsNot(result, summary)
        self.assertIsNot(result, receipt["summary"])


# ---------------------------------------------------------------------------
# Windows collector PS5.1 offline regressions
# ---------------------------------------------------------------------------
import subprocess as _subprocess


def _win_only(fn):
    return unittest.skipUnless(
        sys.platform == "win32",
        "requires Windows (powershell.exe -NoProfile)"
    )(fn)


class TestWindowsCollectorPS51(unittest.TestCase):
    """Invoke REAL _PS_SCRIPT under powershell.exe -NoProfile with prepended
    fixture functions shadowing Get-NetTCPConnection, Get-CimInstance,
    Get-Process.  No Get-FileHash mock: the real _Sha256File function inside
    _PS_SCRIPT hashes actual temporary files.  Tests PS5.1 scalar Count
    semantics, token boundary, TCP call-once, and real SHA256 output.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="qa-ps51-"))
        self._tcp_counter = self.root / "tcp_calls.txt"
        # Create fixture files for real hashing
        self._fixture_root = self.root / "fixture"
        self._exe_dir = self._fixture_root / "venv" / "Scripts"
        self._exe_dir.mkdir(parents=True)
        self._exe_bytes = b"fake-python-executable-bytes-12345"
        self._exe_path = self._exe_dir / "python.exe"
        self._exe_path.write_bytes(self._exe_bytes)
        self._main_bytes = b"print('hello from main.py')"
        self._main_path = self._fixture_root / "main.py"
        self._main_path.write_bytes(self._main_bytes)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _ps_path(self, p):
        """Convert a Path to forward-slash string for PS."""
        return str(p).replace("\\", "/")

    def _build_script(self, *, listener_return, cmd_line_6432, cmd_line_7001):
        """Return full PS script: fixture prefix + real qc._PS_SCRIPT."""
        counter = self._ps_path(self._tcp_counter)
        exe_path = self._ps_path(self._exe_path)
        fixture = (
            "function Get-NetTCPConnection { "
            f"Add-Content -LiteralPath '{counter}' -Value 'x'; "
            f"{listener_return} "
            "} "
            "function Get-CimInstance { param($ClassName,$Filter) "
            "if($Filter -match 'ProcessId=6432'){ "
            f"return [pscustomobject]@{{ProcessId=6432;ParentProcessId=7001;"
            f"ExecutablePath='{exe_path}';"
            f"CommandLine='{cmd_line_6432}'}} "
            "} "
            "if($Filter -match 'ProcessId=7001'){ "
            f"return [pscustomobject]@{{ProcessId=7001;ParentProcessId=0;"
            f"ExecutablePath='{exe_path}';"
            f"CommandLine='{cmd_line_7001}'}} "
            "} "
            "return "
            "} "
            "function Get-Process { param($Id) "
            "return [pscustomobject]@{Id=$Id;"
            "StartTime=[DateTime]::new(2024,1,1,0,0,0,0)} "
            "} "
        )
        return fixture + qc._PS_SCRIPT

    def _run_ps(self, script, timeout=10):
        return _subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )

    def _fixture_cmd(self, main_name="main.py"):
        """Build a command line referencing the fixture executable + main."""
        exe = self._ps_path(self._exe_path)
        main = self._ps_path(self._fixture_root / main_name)
        return f"{exe} {main} --serve"

    @_win_only
    def test_ps51_scalar_listener_emits_valid_json(self):
        """PS5.1: Get-NetTCPConnection returns SINGLE scalar PSCustomObject
        (not array).  Script must detect exactly one listener and emit valid
        JSON with service PID + client list.  TCP probe called exactly once.
        Real SHA256 hashes must match hashlib of known fixture bytes.
        """
        listener_ret = (
            "return [pscustomobject]@{LocalPort=5000;State='Listen';"
            "OwningProcess=6432;RemotePort=0}"
        )
        cmd = self._fixture_cmd()
        script = self._build_script(
            listener_return=listener_ret,
            cmd_line_6432=cmd,
            cmd_line_7001=cmd,
        )
        proc = self._run_ps(script)
        self.assertEqual(
            proc.returncode, 0,
            f"PS failed rc={proc.returncode}: {proc.stderr[:500]}",
        )
        data = json.loads(proc.stdout)
        self.assertIn("service", data)
        self.assertIn("clients", data)
        self.assertEqual(data["service"]["pid"], 6432)
        self.assertEqual(data["service"]["listener_port"], 5000)
        # Real SHA256 assertions against known fixture bytes
        expected_exe_hash = hashlib.sha256(self._exe_bytes).hexdigest()
        expected_main_hash = hashlib.sha256(self._main_bytes).hexdigest()
        self.assertEqual(data["service"]["image_sha256"], expected_exe_hash)
        self.assertEqual(data["service"]["parent_image_sha256"], expected_exe_hash)
        self.assertEqual(data["service"]["main_sha256"], expected_main_hash)
        # TCP probe called exactly once
        self.assertTrue(self._tcp_counter.exists())
        calls = self._tcp_counter.read_text().strip().splitlines()
        self.assertEqual(len(calls), 1,
                         f"Get-NetTCPConnection called {len(calls)} times")

    @_win_only
    def test_ps51_notmain_py_token_rejected(self):
        """Command line contains notmain.py — token regex must reject.
        Script must throw (non-zero exit).
        """
        listener_ret = (
            "return [pscustomobject]@{LocalPort=5000;State='Listen';"
            "OwningProcess=6432;RemotePort=0}"
        )
        # notmain.py does not contain 'main.py' as a standalone token
        exe = self._ps_path(self._exe_path)
        cmd = f"{exe} C:/fixture/notmain.py --serve"
        script = self._build_script(
            listener_return=listener_ret,
            cmd_line_6432=cmd,
            cmd_line_7001=cmd,
        )
        proc = self._run_ps(script)
        self.assertNotEqual(
            proc.returncode, 0,
            "notmain.py must be rejected by token boundary regex",
        )

    @_win_only
    def test_ps51_zero_listener_fails(self):
        """Get-NetTCPConnection returns no listener on port 5000.
        Script must throw (non-zero exit).
        """
        listener_ret = "return"
        cmd = self._fixture_cmd()
        script = self._build_script(
            listener_return=listener_ret,
            cmd_line_6432=cmd,
            cmd_line_7001=cmd,
        )
        proc = self._run_ps(script)
        self.assertNotEqual(
            proc.returncode, 0,
            "zero listener must cause script failure",
        )

    def test_runner_called_process_error_sanitized(self):
        """_default_runner must normalize CalledProcessError to CapacityError
        without exposing raw stderr/command payloads in the raised message.
        """
        if sys.platform != "win32":
            self.skipTest("requires Windows")
        secret_sentinel = "SUPER_SECRET_STDERR_LEAK_9f8e7d6c"

        def fake_run(*args, **kwargs):
            raise _subprocess.CalledProcessError(
                returncode=1,
                cmd=list(args[0]) if args else kwargs.get("args", []),
                output="",
                stderr=f"error: {secret_sentinel} revealed",
            )

        orig_run = _subprocess.run
        _subprocess.run = fake_run
        try:
            with self.assertRaises(qc.CapacityError) as ctx:
                qc._default_runner(
                    ["powershell.exe", "-NoProfile", "-Command", "x"],
                    timeout=5,
                )
        finally:
            _subprocess.run = orig_run
        msg = str(ctx.exception)
        self.assertNotIn(secret_sentinel, msg,
                         "raw stderr leaked into CapacityError message")
        self.assertNotIn("SUPER_SECRET", msg)

    def test_runner_timeout_expired_sanitized(self):
        """_default_runner must normalize TimeoutExpired to CapacityError
        without exposing raw command in the raised message.
        """
        if sys.platform != "win32":
            self.skipTest("requires Windows")
        secret_cmd = "SECRET_COMMAND_PATH_abcdef1234"

        def fake_run(*args, **kwargs):
            raise _subprocess.TimeoutExpired(
                cmd=secret_cmd, timeout=5,
            )

        orig_run = _subprocess.run
        _subprocess.run = fake_run
        try:
            with self.assertRaises(qc.CapacityError) as ctx:
                qc._default_runner(
                    [secret_cmd, "--flag"],
                    timeout=5,
                )
        finally:
            _subprocess.run = orig_run
        msg = str(ctx.exception)
        self.assertNotIn(secret_cmd, msg,
                         "raw command leaked into CapacityError message")


# ---------------------------------------------------------------------------
# Windows-native DEVELOPMENT entry point tests
# ---------------------------------------------------------------------------

class TestNativeDevelopmentEntryPoint(unittest.TestCase):
    """Tests for canonical_lease_root, _native_source_evidence, run_native_window."""

    def setUp(self):
        self._tmpdir = Path(tempfile.mkdtemp(prefix="qa-native-"))
        self._orig_platform = sys.platform
        self._orig_localappdata = os.environ.get("LOCALAPPDATA")
        self._orig_subprocess_run = _subprocess.run

    def tearDown(self):
        sys.platform = self._orig_platform
        if self._orig_localappdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._orig_localappdata
        _subprocess.run = self._orig_subprocess_run
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _win(self):
        sys.platform = "win32"

    def _set_localappdata(self, path):
        os.environ["LOCALAPPDATA"] = str(path)

    def _patch_git(self, *, head=None, diff_rc=0, catfile_rc=0):
        """Patch subprocess.run to return controlled git results."""
        expected_head = head or BINDING["source_head"]
        orig_run = self._orig_subprocess_run

        def fake_run(args, **kwargs):
            if not isinstance(args, list) or args[0] != "git":
                return orig_run(args, **kwargs)
            sub = args[1:]
            if sub[0] == "rev-parse":
                return _subprocess.CompletedProcess(
                    args, 0, stdout=expected_head + "\n", stderr="")
            if sub[0] == "diff":
                return _subprocess.CompletedProcess(
                    args, diff_rc, stdout="", stderr="")
            if sub[0] == "cat-file":
                return _subprocess.CompletedProcess(
                    args, catfile_rc, stdout="", stderr="")
            return _subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        _subprocess.run = fake_run

    # 1: canonical root under patched LOCALAPPDATA
    def test_canonical_root_under_patched_localappdata(self):
        self._win()
        self._set_localappdata(self._tmpdir)
        root = qc.canonical_lease_root()
        expected = self._tmpdir / "InvestorIntelligence" / "qa-capacity-v1"
        self.assertEqual(root, expected)

    # 2: missing LOCALAPPDATA refused
    def test_canonical_root_missing_env(self):
        self._win()
        os.environ.pop("LOCALAPPDATA", None)
        with self.assertRaises(qc.CapacityError):
            qc.canonical_lease_root()

    # 3: relative LOCALAPPDATA refused
    def test_canonical_root_relative_env(self):
        self._win()
        self._set_localappdata("relative/path")
        with self.assertRaises(qc.CapacityError):
            qc.canonical_lease_root()

    # 4: UNC LOCALAPPDATA refused
    def test_canonical_root_unc_env(self):
        self._win()
        self._set_localappdata("\\\\server\\share")
        with self.assertRaises(qc.CapacityError):
            qc.canonical_lease_root()

    # 5: native source HEAD mismatch
    def test_native_source_head_mismatch(self):
        self._patch_git(head="0" * 40)
        with self.assertRaises(qc.CapacityError):
            qc._native_source_evidence(BINDING)

    # 6: native source tracked dirty
    def test_native_source_tracked_dirty(self):
        self._patch_git(diff_rc=1)
        with self.assertRaises(qc.CapacityError):
            qc._native_source_evidence(BINDING)

    # 7: native source module absent
    def test_native_source_module_absent(self):
        self._patch_git(catfile_rc=1)
        with self.assertRaises(qc.CapacityError):
            qc._native_source_evidence(BINDING)

    # 8: native entry rejects before work when source unqualified
    def test_native_entry_rejects_before_work(self):
        self._patch_git(head="0" * 40)
        work_called = [False]

        def work(cancel_event):
            work_called[0] = True

        with self.assertRaises(qc.CapacityError):
            qc.run_native_window(BINDING, work)
        self.assertFalse(work_called[0],
                         "work must NOT be called when source unqualified")

    # 9: no source/endpoint/root override argument accepted
    def test_no_override_args_accepted(self):
        import inspect
        sig = inspect.signature(qc.run_native_window)
        params = set(sig.parameters.keys())
        for forbidden in ("root", "probe", "runner", "endpoint", "http_get"):
            self.assertNotIn(forbidden, params,
                             f"run_native_window must not accept {forbidden!r}")

    # 10: Full Windows fixture — REAL lease/monitor/receipt logic
    @_win_only
    def test_native_window_full_path(self):
        self._set_localappdata(self._tmpdir)
        self._patch_git()  # all git checks pass

        orig_collect = qc.collect_windows_snapshot
        qc.collect_windows_snapshot = lambda b: make_raw_snapshot()
        try:
            receipt = qc.run_native_window(
                BINDING, lambda ce: time.sleep(0.12),
                interval_s=0.02, max_gap_s=0.3, timeout_s=1)
        finally:
            qc.collect_windows_snapshot = orig_collect

        self.assertEqual(receipt["origin"], "WINDOWS_NATIVE_DEVELOPMENT")
        self.assertIn("source_module_sha256", receipt)
        self.assertEqual(len(receipt["source_module_sha256"]), 64)

        result = qc.verify_receipt(receipt, BINDING)
        self.assertIn(result["CAPACITY_EVIDENCE"], ("QUALIFIED", "UNQUALIFIED"))


# ---------------------------------------------------------------------------
# Exact regressions from independently reproduced review findings
# JEV checkpoint REWORK=1: chronology and unknown-liveness are REQUIRED gaps.
# Mapika REWORK_COUNTEREXAMPLES .9936.
# ---------------------------------------------------------------------------


class TestReviewCounterexamples(unittest.TestCase):
    """RED on current code: exact counterexamples from reproduce.py."""

    def setUp(self):
        self.root = _root()
        self._leases = []

    def tearDown(self):
        for l in self._leases:
            try:
                l.close()
            except Exception:
                pass
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _lease(self, **kw):
        lease = qc.CapacityLease(self.root, BINDING, **kw)
        self._leases.append(lease)
        return lease

    def _rehash(self, r, seed=None):
        """Rebuild sample chain hashes and outer digest (excluding digest)."""
        prev = seed
        for i, s in enumerate(r["samples"]):
            s["seq"] = i
            s["prev_hash"] = prev
            s["hash"] = qc.canonical_hash(
                {k: v for k, v in s.items() if k != "hash"})
            prev = s["hash"]
        r["digest"] = qc.canonical_hash(
            {k: v for k, v in r.items() if k != "digest"})

    def _clean_receipt(self):
        """Produce a clean QUALIFIED receipt."""
        lease = self._lease()
        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(),
            lambda ce: time.sleep(0.12),
            interval_s=0.02, max_gap_s=0.3, timeout_s=1)
        self.assertEqual(
            receipt["summary"]["CAPACITY_EVIDENCE"], "QUALIFIED")
        return receipt

    # ── 1: Chronology tampering ──────────────────────────────────────────

    def test_chronology_swap_pre_during_rejects(self):
        """Swap PRE and first DURING, resequence+rehash; MUST reject."""
        receipt = self._clean_receipt()
        r = copy.deepcopy(receipt)
        r["samples"][0], r["samples"][1] = (
            r["samples"][1], r["samples"][0])
        self._rehash(r)
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    def test_chronology_duplicate_pre_rejects(self):
        """Duplicate PRE with recomputed hashes; MUST reject."""
        receipt = self._clean_receipt()
        r = copy.deepcopy(receipt)
        pre_copy = copy.deepcopy(r["samples"][0])
        r["samples"].insert(1, pre_copy)
        self._rehash(r)
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    def test_chronology_nonnull_first_prev_hash_rejects(self):
        """Non-null first prev_hash with recomputed hashes; MUST reject."""
        receipt = self._clean_receipt()
        r = copy.deepcopy(receipt)
        nonnull_seed = "0" * 64
        self._rehash(r, seed=nonnull_seed)
        self.assertIsNotNone(r["samples"][0]["prev_hash"],
                             "first prev_hash must remain nonnull")
        self.assertEqual(r["samples"][0]["prev_hash"], nonnull_seed)
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    # ── 2: Work time tampering ───────────────────────────────────────────

    def test_post_before_work_rejects(self):
        """POST time fields set to 0 (before work); MUST reject."""
        receipt = self._clean_receipt()
        r = copy.deepcopy(receipt)
        for s in r["samples"]:
            if s["phase"] == "POST":
                for key in ("time_s", "started_s", "ended_s"):
                    if key in s:
                        s[key] = 0.0
        self._rehash(r)
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    def test_pre_end_after_work_starts_rejects(self):
        """PRE ended after work starts; MUST reject."""
        receipt = self._clean_receipt()
        r = copy.deepcopy(receipt)
        ws = r["work_start_s"]
        for s in r["samples"]:
            if s["phase"] == "PRE":
                s["ended_s"] = ws + 0.05
                s["time_s"] = ws + 0.05
        self._rehash(r)
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    def test_during_outside_work_interval_rejects(self):
        """DURING sample outside work interval; MUST reject."""
        receipt = self._clean_receipt()
        r = copy.deepcopy(receipt)
        we = r["work_end_s"]
        for s in r["samples"]:
            if s["phase"] == "DURING":
                s["time_s"] = we + 0.05
                s["ended_s"] = we + 0.05
                break
        self._rehash(r)
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    def test_gap_exceeds_max_gap_rejects(self):
        """Gap > declared max_gap within total timeout; MUST reject."""
        receipt = self._clean_receipt()
        r = copy.deepcopy(receipt)
        max_gap = r["config"]["max_gap_s"]
        if len(r["samples"]) >= 3:
            shift = max_gap + 0.1
            s = r["samples"][2]
            s["time_s"] += shift
            s["started_s"] += shift
            s["ended_s"] += shift
        self._rehash(r)
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    # ── 2b: Lease metadata hash linkage (acquire/sample/release) ─────────
    # Finding: altering the release event hash (or the acquire/sample lease
    # hashes) and recomputing the outer digest was still QUALIFIED.  The
    # acquire event hash, each sample BEFORE/AFTER lease hash, and the
    # release event hash must ALL equal the canonical lease metadata hash.

    def _outer_digest(self, r):
        return qc.canonical_hash({k: v for k, v in r.items() if k != "digest"})

    def test_release_hash_altered_rejects(self):
        """Alter release event hash, recompute outer digest; MUST reject."""
        receipt = self._clean_receipt()
        r = copy.deepcopy(receipt)
        release_idx = next(
            i for i, e in enumerate(r["events"]) if e.get("kind") == "release")
        r["events"][release_idx] = dict(
            r["events"][release_idx], hash="0" * 64)
        self._rehash(r)  # rebuild sample chains + outer digest
        # Outer digest is correctly recomputed (not a checksum-only test):
        self.assertEqual(r["digest"], self._outer_digest(r))
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    def test_acquire_and_sample_hashes_consistent_arbitrary_rejects(self):
        """Acquire hash + ALL sample lease hashes set to the SAME arbitrary
        64-hex (matching each other but not the metadata hash), metadata
        unchanged, chains+outer digest rebuilt; MUST reject.  Matching
        arbitrary hashes to each other is insufficient."""
        receipt = self._clean_receipt()
        r = copy.deepcopy(receipt)
        arbitrary = "f" * 64
        # Sanity: arbitrary is not the canonical metadata hash
        self.assertNotEqual(
            arbitrary, qc.canonical_hash(r["lease"]["metadata"]))
        acq_idx = next(
            i for i, e in enumerate(r["events"]) if e.get("kind") == "acquire")
        r["events"][acq_idx] = dict(r["events"][acq_idx], hash=arbitrary)
        for s in r["samples"]:
            s["lease_hash_before"] = arbitrary
            s["lease_hash_after"] = arbitrary
        # Metadata unchanged
        self._rehash(r)  # rebuild sample chains + outer digest
        self.assertEqual(r["digest"], self._outer_digest(r))
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    def test_single_sample_lease_hash_altered_rejects(self):
        """Alter just one sample's lease hashes (kept consistent so
        before==after, so the before/after integrity check alone would NOT
        catch it) to an arbitrary value, rebuild chains; MUST reject."""
        receipt = self._clean_receipt()
        r = copy.deepcopy(receipt)
        arbitrary = "a" * 64
        self.assertNotEqual(
            arbitrary, qc.canonical_hash(r["lease"]["metadata"]))
        # Alter just ONE sample's lease hashes consistently
        r["samples"][0]["lease_hash_before"] = arbitrary
        r["samples"][0]["lease_hash_after"] = arbitrary
        self._rehash(r)  # rebuild sample chains + outer digest
        self.assertEqual(r["digest"], self._outer_digest(r))
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(r, BINDING)

    # ── 3: Lease recovery with invalid probe ─────────────────────────────

    def test_recover_dead_invalid_probe_refuses(self):
        """probe returns object/bool/int/empty-str/dict; MUST refuse."""
        lease = self._lease()
        meta = lease.acquire()
        owner_bytes = lease.metadata_path.read_bytes()
        lease.close()
        nonce = meta["nonce"]
        meta_sha = hashlib.sha256(owner_bytes).hexdigest()
        owner_path = self.root / "owner.json"
        for probe_result in [object(), True, 42, "", {}]:
            with self.subTest(probe=repr(probe_result)):
                with self.assertRaises(qc.CapacityError):
                    qc.recover_dead(
                        self.root, nonce, meta_sha,
                        process_probe=lambda pid: probe_result)
                self.assertEqual(
                    owner_path.read_bytes(), owner_bytes,
                    f"owner bytes altered for probe={probe_result!r}")

    def test_recover_dead_none_still_conclusive_dead(self):
        """None remains conclusive dead; recovery proceeds."""
        lease = self._lease()
        meta = lease.acquire()
        owner_bytes = lease.metadata_path.read_bytes()
        lease.close()
        nonce = meta["nonce"]
        meta_sha = hashlib.sha256(owner_bytes).hexdigest()
        event = qc.recover_dead(
            self.root, nonce, meta_sha,
            process_probe=lambda pid: None)
        self.assertEqual(event["reason"], "conclusively_dead")
        self.assertFalse((self.root / "owner.json").exists())

    # ── 4: Binding missing/malformed fields ──────────────────────────────

    def test_binding_missing_fields_no_keyerror_typeerror(self):
        """Missing binding fields: nonhealthy verdict or CapacityError,
        NEVER KeyError/TypeError."""
        missing_keys = [
            "gpu_uuid", "allowed_clients", "qwen_worker_names",
            "parent_pid", "parent_created", "parent_image_sha256",
            "main_sha256", "model_artifacts",
        ]
        for key in missing_keys:
            with self.subTest(missing=key):
                bad = copy.deepcopy(BINDING)
                if key in ("parent_pid", "parent_created",
                           "parent_image_sha256", "main_sha256"):
                    del bad["service"][key]
                else:
                    del bad[key]
                try:
                    result = qc.evaluate_snapshot(
                        make_raw_snapshot(), bad)
                    self.assertFalse(
                        result["model_identity_verified"]
                        or result["service_identity_verified"],
                        f"expected nonhealthy for missing {key}")
                except (KeyError, TypeError) as e:
                    self.fail(
                        f"evaluate_snapshot raised {type(e).__name__} "
                        f"for missing {key}")
                except qc.CapacityError:
                    pass

    def test_binding_malformed_field_types(self):
        """Malformed client/worker/artifact field types: nonhealthy or
        CapacityError, NEVER KeyError/TypeError."""
        cases = [
            ("allowed_clients", "not-a-list"),
            ("allowed_clients", [{"pid": "not-int", "created": 123}]),
            ("qwen_worker_names", "not-a-list"),
            ("qwen_worker_names", [123]),
            ("model_artifacts", "not-a-dict"),
            ("model_artifacts", {"config_sha256": 123}),
        ]
        for key, bad_value in cases:
            with self.subTest(key=key, value=repr(bad_value)):
                bad = copy.deepcopy(BINDING)
                bad[key] = bad_value
                try:
                    result = qc.evaluate_snapshot(
                        make_raw_snapshot(), bad)
                    self.assertFalse(
                        result["model_identity_verified"]
                        or result["service_identity_verified"],
                        f"expected nonhealthy for malformed {key}")
                except (KeyError, TypeError) as e:
                    self.fail(
                        f"evaluate_snapshot raised {type(e).__name__} "
                        f"for malformed {key}")
                except qc.CapacityError:
                    pass


# ---------------------------------------------------------------------------
# Coverage classification: honest UNQUALIFIED receipts must verify
# ---------------------------------------------------------------------------


class TestCoverageClassificationVerify(unittest.TestCase):
    """Honest-failure replay: PRE-denied, missing-clients, probe-raise,
    and work-timeout receipts must verify as UNQUALIFIED (not raise).
    """

    def setUp(self):
        self.root = _root()
        self._leases = []

    def tearDown(self):
        for l in self._leases:
            try:
                l.close()
            except Exception:
                pass
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _lease(self, **kw):
        lease = qc.CapacityLease(self.root, BINDING, **kw)
        self._leases.append(lease)
        return lease

    # 1: Valid conflict observation at PRE (GPU C+G) => callback never called,
    #    PRE/POST raw samples retained, None worktimes; verify succeeds with
    #    equal fresh UNQUALIFIED summary and all conflict reasons.
    def test_pre_gpu_conflict_verifies_unqualified(self):
        lease = self._lease()
        called = [False]
        bad_xml = _gpu_xml_extra_process(8888, "C+G")

        def work(cancel_event):
            called[0] = True

        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(gpu_xml=bad_xml), work,
            interval_s=0.01, max_gap_s=0.1, timeout_s=0.5)
        self.assertFalse(called[0], "work must NOT run when PRE GPU shows C+G")
        self.assertIsNone(receipt["work_start_s"])
        self.assertIsNone(receipt["work_end_s"])
        # PRE and POST samples retained
        phases = [s["phase"] for s in receipt["samples"]]
        self.assertIn("PRE", phases)
        self.assertIn("POST", phases)
        self.assertNotIn("DURING", phases)
        # verify_receipt must succeed (not raise) and return UNQUALIFIED
        result = qc.verify_receipt(receipt, BINDING)
        self.assertEqual(result["CAPACITY_EVIDENCE"], "UNQUALIFIED")
        self.assertFalse(result["MONITOR_COMPLETE"])
        # Conflict reasons present
        self.assertTrue(
            any("conflict" in r.lower() or "C+G" in r
                for r in result["reasons"]),
            f"expected conflict reason in {result['reasons']}")
        # Result is a fresh dict, not the stored object
        self.assertIsNot(result, receipt["summary"])

    # 2: PRE missing clients similarly verifies; unknown not fabricated conflict.
    def test_pre_missing_clients_verifies_unqualified(self):
        lease = self._lease()
        called = [False]

        def probe():
            raw = make_raw_snapshot()
            del raw["clients"]
            return raw

        def work(cancel_event):
            called[0] = True

        receipt = qc.run_window(
            lease, probe, work,
            interval_s=0.01, max_gap_s=0.1, timeout_s=0.5)
        self.assertFalse(called[0], "work must NOT run when PRE clients missing")
        self.assertIsNone(receipt["work_start_s"])
        self.assertIsNone(receipt["work_end_s"])
        # verify_receipt must succeed and return UNQUALIFIED
        result = qc.verify_receipt(receipt, BINDING)
        self.assertEqual(result["CAPACITY_EVIDENCE"], "UNQUALIFIED")
        self.assertFalse(result["MONITOR_COMPLETE"])
        # Must NOT fabricate a GPU conflict
        self.assertFalse(result["GPU_CONFLICT_OBSERVED"],
                         "GPU conflict must not be fabricated for missing clients")

    # 3: PRE probe raises only on first call, POST healthy => honest ordered
    #    incomplete receipt verifies UNQUALIFIED.
    def test_pre_probe_raise_post_healthy_verifies_unqualified(self):
        lease = self._lease()
        call_count = [0]

        def probe():
            call_count[0] += 1
            if call_count[0] == 1:
                raise qc.CapacityError("probe timeout")
            return make_raw_snapshot()

        called = [False]

        def work(cancel_event):
            called[0] = True

        receipt = qc.run_window(
            lease, probe, work,
            interval_s=0.01, max_gap_s=0.1, timeout_s=0.5)
        self.assertFalse(called[0], "work must NOT run when PRE probe fails")
        self.assertIsNone(receipt["work_start_s"])
        self.assertIsNone(receipt["work_end_s"])
        # Only POST sample should exist (PRE probe failed)
        phases = [s["phase"] for s in receipt["samples"]]
        self.assertNotIn("PRE", phases)
        self.assertIn("POST", phases)
        # verify_receipt must succeed and return UNQUALIFIED
        result = qc.verify_receipt(receipt, BINDING)
        self.assertEqual(result["CAPACITY_EVIDENCE"], "UNQUALIFIED")
        self.assertFalse(result["MONITOR_COMPLETE"])

    # 4: Bounded work timeout with recorded stuck state; never successful
    #    release if still running. Receipt verifies UNQUALIFIED.
    def test_work_stuck_verifies_unqualified(self):
        lease = self._lease()
        called = [False]

        def work(cancel_event):
            called[0] = True
            # Ignore cancel; block past deadline to trigger work_stuck
            cancel_event.wait(5.0)

        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(), work,
            interval_s=0.01, max_gap_s=0.1, timeout_s=0.15)
        self.assertTrue(called[0], "work was called")
        # work_stuck must be recorded
        codes = [e.get("code") for e in receipt["events"]
                 if e.get("kind") == "error"]
        self.assertIn("work_stuck", codes)
        # No successful release when work is stuck
        self.assertFalse(
            any(e.get("kind") == "release" for e in receipt["events"]),
            "no release event when work is stuck")
        # verify_receipt must succeed and return UNQUALIFIED
        result = qc.verify_receipt(receipt, BINDING)
        self.assertEqual(result["CAPACITY_EVIDENCE"], "UNQUALIFIED")
        self.assertFalse(result["MONITOR_COMPLETE"])
        self.assertFalse(result["lease_released"])
        # Retained stuck and timeout budget reasons
        self.assertIn("work_stuck", result["reasons"])
        self.assertTrue(
            any("exceeds timeout_s" in r for r in result["reasons"]),
            f"expected timeout budget reason in {result['reasons']}")


if __name__ == "__main__":
    unittest.main()