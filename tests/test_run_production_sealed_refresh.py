"""Hourly sealed refresh: native stderr is logged, never fatal; the sync gets exactly the run the publisher printed;
every failure is written to the log (regression 2026-09-25 15:56Z: a stderr line under Windows PowerShell 5.1 with
ErrorActionPreference Stop aborted the run after publish with no log line, and the pointer aged).

Runs a copy of the script against stub publish/sync/lock scripts; the real operation lock is never taken."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_production_sealed_refresh.ps1"
RUN_ID = "20260926T000000Z-0123456789ab"
LOCK_STUB = "function Enter-V213OperationLock { param($Owner, $TimeoutSeconds) $true }\nfunction Exit-V213OperationLock { }\n"
PUBLISH_OK = (f'import sys\nprint("{{")\nprint(\'  "run_id": "{RUN_ID}",\')\nprint("}}")\n'
              'print("SyntheticWarning: noisy stderr line", file=sys.stderr)\n')
PUBLISH_NO_RUN = 'print("{}")\n'
SYNC_OK = 'import sys\nprint("SYNCED " + sys.argv[-1])\nprint("wrangler notice on stderr", file=sys.stderr)\n'
SYNC_FAIL = 'import sys\nprint("Traceback: synthetic failure", file=sys.stderr)\nsys.exit(3)\n'


def shells() -> list[str]:
    return [shell for shell in ("powershell", "pwsh") if shutil.which(shell)]


class HourlyRefreshScriptTests(unittest.TestCase):
    def run_copy(self, shell: str, publish: str, sync: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            shutil.copy(SCRIPT, scripts / SCRIPT.name)
            (scripts / "v213_operation_lock.ps1").write_text(LOCK_STUB, encoding="utf-8")
            (scripts / "run_daily_data_refresh.ps1").write_text("exit 0\n", encoding="utf-8")
            (scripts / "publish_sealed_snapshot.py").write_text(publish, encoding="utf-8")
            (scripts / "sync_sealed_snapshot_kv.py").write_text(sync, encoding="utf-8")
            done = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                   str(scripts / SCRIPT.name)], capture_output=True, timeout=180)
            log = (Path(tmp) / "data" / "cache" / "sealed-refresh.log").read_text(encoding="utf-8", errors="replace")
            return done.returncode, log

    def test_stderr_is_logged_and_the_printed_run_is_synced(self):
        if not shells():
            self.skipTest("PowerShell not available")
        for shell in shells():
            code, log = self.run_copy(shell, PUBLISH_OK, SYNC_OK)
            self.assertEqual(code, 0, (shell, log))
            self.assertIn("SyntheticWarning: noisy stderr line", log)
            self.assertIn(f"SYNCED ", log)
            self.assertIn(RUN_ID, log.split("SYNCED ", 1)[1].splitlines()[0])
            self.assertIn(f"REFRESH OK run={RUN_ID} pointer last", log)

    def test_sync_failure_and_missing_run_id_are_logged(self):
        if not shells():
            self.skipTest("PowerShell not available")
        for shell in shells():
            code, log = self.run_copy(shell, PUBLISH_OK, SYNC_FAIL)
            self.assertEqual(code, 3, (shell, log))
            self.assertIn("Traceback: synthetic failure", log)
            self.assertIn("SYNC FAILED exit=3", log)
            code, log = self.run_copy(shell, PUBLISH_NO_RUN, SYNC_OK)
            self.assertNotEqual(code, 0)
            self.assertIn("GENERATE FAILED run id not printed", log)
            self.assertNotIn("SYNCED", log)

    def test_no_newest_folder_guess(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("Sort-Object LastWriteTime", text)
        self.assertIn("Invoke-LoggedNative", text)


# Carry-forward stubs: every step appends one line to trace.txt at the stub repo root, so the tests can assert order.
TRACE = ("import sys\nfrom pathlib import Path\nroot = Path(__file__).resolve().parents[1]\n"
         "def trace(line):\n    with open(root / 'trace.txt', 'a', encoding='utf-8') as f:\n        f.write(line + '\\n')\n")
CARRY_PUBLISH = TRACE + (
    "args = sys.argv[1:]\n"
    "if '--top20-insufficient' in args:\n    run, state = 'RUN_B', 'INSUFFICIENT'\n"
    "elif '--snapshot-root' in args:\n    run, state = 'RUN_C', 'CARRIED_FORWARD'\n"
    "elif '--identity-shards' in args:\n    run, state = 'RUN_A', 'CARRIED_FORWARD'\n"
    "else:\n    run, state = 'RUN_D', 'CARRIED_FORWARD'\n"
    "trace('PUBLISH ' + run + ' ' + ' '.join(a for a in args if a.startswith('--')))\n"
    "ids = {'RUN_A': '20260926T010000Z-aaaaaaaaaaaa', 'RUN_B': '20260926T010000Z-bbbbbbbbbbbb',"
    " 'RUN_C': '20260926T010000Z-cccccccccccc', 'RUN_D': '20260926T010000Z-dddddddddddd'}\n"
    "print('{')\nprint('  \"run_id\": \"' + ids[run] + '\",')\nprint('  \"top20_state\": \"' + state + '\"')\nprint('}')\n")
CARRY_REPLAY = TRACE + (
    "run = sys.argv[-1]\nfail = (root / ('replay_fail_' + run[-4:])).exists()\n"
    "trace('REPLAY ' + run[-4:] + (' FAIL' if fail else ' PASS'))\nsys.exit(1 if fail else 0)\n")
CARRY_SYNC = TRACE + "trace('SYNC ' + sys.argv[-1][-4:])\nprint('SYNC_ARG ' + sys.argv[-1])\n"
CARRY_LKG = TRACE + (
    "cmd = sys.argv[1]\ntrace('LKG ' + ' '.join(a for a in sys.argv[1:4] if not Path(a).is_absolute()))\n"
    "if cmd == 'due':\n    print('{\"due\": ' + ('false' if (root / 'not_due').exists() else 'true') + '}')\n")
ROTATION_STUB = "Add-Content -Path (Join-Path (Split-Path -Parent $PSScriptRoot) 'trace.txt') -Value 'ROTATION'\nexit 0\n"
REFRESH_STUB = ("param([string]$ProjectRoot, [switch]$NoModelBridge, [switch]$NoTunnel, [switch]$NoSync, [switch]$NoAutoActivation)\n"
                "Add-Content -Path (Join-Path $PSScriptRoot 'trace.txt') -Value ('REFRESH nosync=' + [bool]$NoSync)\n"
                "if (Test-Path (Join-Path $PSScriptRoot 'refresh_hang')) { Start-Sleep -Seconds 120 }\nexit 0\n")


class CarryForwardHourlyTests(unittest.TestCase):
    """-CarryForwardTop20: seal first, replay fallback, refresh only after the pointer, bounded, backoff-gated."""

    def run_carry(self, shell: str, markers: tuple[str, ...] = (), carry: bool = True,
                  extra: tuple[str, ...] = ()) -> tuple[int, list[str], str, float]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy(SCRIPT, scripts / SCRIPT.name)
            (scripts / "v213_operation_lock.ps1").write_text(LOCK_STUB, encoding="utf-8")
            (scripts / "run_daily_data_refresh.ps1").write_text(ROTATION_STUB, encoding="utf-8")
            (scripts / "publish_sealed_snapshot.py").write_text(CARRY_PUBLISH, encoding="utf-8")
            (scripts / "stage_sealed_replay.py").write_text(CARRY_REPLAY, encoding="utf-8")
            (scripts / "sync_sealed_snapshot_kv.py").write_text(CARRY_SYNC, encoding="utf-8")
            (scripts / "top20_carry_forward.py").write_text(CARRY_LKG, encoding="utf-8")
            (root / "run-v213-local.ps1").write_text(REFRESH_STUB, encoding="utf-8")
            for marker in markers:
                (root / marker).write_text("1", encoding="utf-8")
            command = [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(scripts / SCRIPT.name)]
            if carry:
                command += ["-CarryForwardTop20", "-RefreshTimeoutSeconds", "5", "-TabbyUrl", "http://127.0.0.1:9", *extra]
            started = time.monotonic()
            done = subprocess.run(command, capture_output=True, timeout=240)
            elapsed = time.monotonic() - started
            trace_path = root / "trace.txt"
            trace = trace_path.read_text(encoding="utf-8").splitlines() if trace_path.exists() else []
            log = (root / "data" / "cache" / "sealed-refresh.log").read_text(encoding="utf-8", errors="replace")
            return done.returncode, trace, log, elapsed

    def setUp(self):
        if not shells():
            self.skipTest("PowerShell not available")

    def test_seals_before_refresh_and_promotes_a_replayed_candidate(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell)
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace[:3], ["PUBLISH RUN_A --live-clock --top20-bundle --identity-shards", "REPLAY aaaa PASS", "SYNC aaaa"], trace)
            self.assertEqual(trace[3:6], ["ROTATION", "LKG due", "REFRESH nosync=True"], trace)
            self.assertEqual(trace[6], "PUBLISH RUN_C --live-clock --top20-bundle --snapshot-root", trace)
            self.assertEqual(trace[7:], ["REPLAY cccc PASS", "LKG promote --candidate", "LKG record --result ok"], trace)
            self.assertIn("TABBY_MODEL_UNVERIFIED", log)
            self.assertIn("TOP20 CANDIDATE OK", log)

    def test_identity_replay_failure_keeps_the_carried_top20(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("replay_fail_aaaa", "not_due"))
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace[:5], ["PUBLISH RUN_A --live-clock --top20-bundle --identity-shards", "REPLAY aaaa FAIL",
                                         "PUBLISH RUN_D --live-clock --top20-bundle", "REPLAY dddd PASS", "SYNC dddd"], trace)
            self.assertIn("REPLAY FAILED run=20260926T010000Z-aaaaaaaaaaaa tier=OK", log)

    def test_replay_failure_republishes_insufficient_and_still_syncs(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("replay_fail_aaaa", "replay_fail_dddd", "not_due"))
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace[2:7], ["PUBLISH RUN_D --live-clock --top20-bundle", "REPLAY dddd FAIL",
                                          "PUBLISH RUN_B --live-clock --top20-insufficient", "REPLAY bbbb PASS", "SYNC bbbb"], trace)
            self.assertIn("REPLAY FAILED", log)
            self.assertNotIn("REFRESH nosync=True", trace)

    def test_both_replays_failing_leave_the_pointer_untouched(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("replay_fail_aaaa", "replay_fail_dddd", "replay_fail_bbbb"))
            self.assertNotEqual(code, 0)
            self.assertFalse([line for line in trace if line.startswith(("SYNC", "REFRESH", "ROTATION"))], trace)
            self.assertIn("GENERATE FAILED stage=REPLAY", log)

    def test_refresh_timeout_kills_the_tree_after_the_seal_and_records_backoff(self):
        for shell in shells():
            code, trace, log, elapsed = self.run_carry(shell, ("refresh_hang",))
            self.assertEqual(code, 0, (shell, log))
            self.assertLess(trace.index("SYNC aaaa"), trace.index("REFRESH nosync=True"))
            self.assertIn("TOP20_REFRESH TIMEOUT after 5s", log)
            self.assertIn("LKG record --result fail", trace)
            self.assertNotIn("LKG promote --candidate", trace)
            self.assertLess(elapsed, 90)

    def test_backoff_or_fresh_lkg_skips_the_refresh(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("not_due",))
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace[-1], "LKG due", trace)

    def test_a_failed_candidate_replay_never_replaces_the_lkg(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("replay_fail_cccc",))
            self.assertEqual(code, 0, (shell, log))
            self.assertNotIn("LKG promote --candidate", trace)
            self.assertEqual(trace[-1], "LKG record --result fail", trace)

    def test_snapshot_root_moves_sealed_runs_out_of_the_attested_tree(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("not_due",), extra=("-SnapshotRoot", r"data\v213-snapshots"))
            self.assertEqual(code, 0, (shell, log))
            self.assertRegex(log, r"SYNC_ARG .*\\data\\v213-snapshots\\20260926T010000Z-aaaaaaaaaaaa")

    def test_switch_off_keeps_the_default_flow(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, carry=False)
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace, ["ROTATION", "PUBLISH RUN_D --live-clock", "SYNC dddd"])


if __name__ == "__main__":
    unittest.main()
