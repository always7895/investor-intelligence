"""Hourly sealed refresh: native stderr is logged, never fatal; the sync gets exactly the run the publisher printed;
every failure is written to the log (regression 2026-09-25 15:56Z: a stderr line under Windows PowerShell 5.1 with
ErrorActionPreference Stop aborted the run after publish with no log line, and the pointer aged).

Runs a copy of the script against stub publish/sync/lock scripts; the real operation lock is never taken.

Sync contract (commit 52c7733): the caller starts the sync with `--run-dir <run> --outcome-path <new json>` and trusts only
an outcome file that Read-SafeSyncOutcome accepts for that run. The stub syncs therefore write an outcome of the real
schema (what scripts/sync_sealed_snapshot_kv.py writes), and every row reads what the script emits now: the
SEALED_REFRESH_OUTCOME line (primary_exit, primary_phase, error_category, pointer_state, publication_confirmed,
local_maintenance), not the log lines removed in 52c7733 ('SYNC FAILED exit=', 'REFRESH OK run=... pointer last',
'GENERATE FAILED run id not printed', 'TOP20 CANDIDATE OK', 'POST_SEAL SKIPPED Top20 refresh')."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_production_sealed_refresh.ps1"
RUN_ID = "20260926T000000Z-0123456789ab"
LOCK_STUB = "function Enter-V213OperationLock { param($Owner, $TimeoutSeconds) $true }\nfunction Exit-V213OperationLock { }\n"
PUBLISH_OK = (f'import sys\nprint("{{")\nprint(\'  "run_id": "{RUN_ID}",\')\nprint("}}")\n'
              'print("SyntheticWarning: noisy stderr line", file=sys.stderr)\n')
PUBLISH_NO_RUN = 'print("{}")\n'
PUBLISH_CRASH = 'import sys\nprint("Traceback: synthetic publish crash", file=sys.stderr)\nsys.exit(2)\n'

# The stub sync parses the caller's argv (`--run-dir`, `--outcome-path`) and writes the outcome the real sync writes
# (sync_sealed_snapshot_kv.py _outcome/_finish_call: create-new file, compact JSON); the defaults are a confirmed success.
SYNC_PRELUDE = (
    "import json, sys, time\nfrom pathlib import Path\nargs = sys.argv[1:]\n"
    "run_dir = args[args.index('--run-dir') + 1]\noutcome_path = args[args.index('--outcome-path') + 1]\n"
    "def write_outcome(**override):\n"
    "    record = {'schema_version': 1, 'operation': 'SYNC', 'status': 'SUCCEEDED', 'phase': 'COMPLETE',\n"
    "              'error_category': 'NONE', 'pointer_state': 'READBACK_CONFIRMED', 'run_id': Path(run_dir).name,\n"
    "              'cli_attempts_total': 3, 'last_cli_attempts': 1, 'last_cli_exit_code': 0, 'objects_uploaded': 14,\n"
    "              'objects_reused': 0, 'objects_verified': 14}\n"
    "    record.update(override)\n"
    "    with open(outcome_path, 'x', encoding='utf-8') as stream:\n"
    "        json.dump(record, stream, separators=(',', ':'))\n"
    "    print('SYNC_OUTCOME ' + json.dumps(record, separators=(',', ':')))\n")
FAILED_PUT = dict(status="FAILED", phase="OBJECT_PUT", error_category="UNKNOWN", pointer_state="NOT_ATTEMPTED",
                  cli_attempts_total=3, last_cli_attempts=3, last_cli_exit_code=1, objects_uploaded=0, objects_verified=0)
FAILED_UNCONFIRMED = dict(status="FAILED", phase="POINTER_READBACK", error_category="READBACK_MISMATCH",
                          pointer_state="ATTEMPTED_UNCONFIRMED", last_cli_exit_code=0)


def sync_stub(code: int = 0, overrides: dict | None = None, raw: str | None = None, write: bool = True) -> str:
    """A stub sync: prints what the real one prints, writes the outcome (the overrides over a confirmed success, or the
    raw bytes) unless write is False, then exits with code."""
    body = (SYNC_PRELUDE + "print('SYNCED ' + run_dir)\nprint('SYNC_OUTCOME_PATH ' + outcome_path)\n"
            "print('wrangler notice on stderr', file=sys.stderr)\n")
    if code:
        body += "print('Traceback: synthetic failure', file=sys.stderr)\n"
    if write and raw is not None:
        body += f"open(outcome_path, 'x', encoding='utf-8').write({raw!r})\n"
    elif write:
        body += f"write_outcome(**{overrides or {}!r})\n"
    return body + f"sys.exit({code})\n"


SYNC_OK = sync_stub()
SYNC_FAIL = sync_stub(3, FAILED_PUT)  # exit 3 with a FAILED outcome, pointer not attempted
OUTCOME_LINE = "SEALED_REFRESH_OUTCOME "
OUTCOME_PATH = re.compile(r"SYNC_OUTCOME_PATH .*\\data\\cache\\sealed-sync-[0-9a-f]{32}\.json")


class Run(NamedTuple):
    code: int
    log: str
    stdout: str
    outcome: dict  # the parsed SEALED_REFRESH_OUTCOME line ({} when the script printed none)


def parse_outcome(text: str) -> dict:
    lines = [line for line in text.splitlines() if line.startswith(OUTCOME_LINE)]
    return json.loads(lines[-1][len(OUTCOME_LINE):]) if lines else {}


def run_env() -> dict:
    """The script runs `$env:PROJECT_PYTHON` (else `python` from PATH): pin it to the interpreter running this test."""
    return {**os.environ, "PROJECT_PYTHON": sys.executable}


def read_log(root: Path) -> str:
    path = root / "data" / "cache" / "sealed-refresh.log"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def shells() -> list[str]:
    return [shell for shell in ("powershell", "pwsh") if shutil.which(shell)]


class HourlyRefreshScriptTests(unittest.TestCase):
    def run_copy(self, shell: str, publish: str, sync: str) -> Run:
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            shutil.copy(SCRIPT, scripts / SCRIPT.name)
            (scripts / "v213_operation_lock.ps1").write_text(LOCK_STUB, encoding="utf-8")
            (scripts / "run_daily_data_refresh.ps1").write_text("exit 0\n", encoding="utf-8")
            (scripts / "publish_sealed_snapshot.py").write_text(publish, encoding="utf-8")
            (scripts / "sync_sealed_snapshot_kv.py").write_text(sync, encoding="utf-8")
            done = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                   str(scripts / SCRIPT.name)], capture_output=True, timeout=180, env=run_env())
            log = read_log(Path(tmp))
            stdout = done.stdout.decode("utf-8", errors="replace")
            self.assertEqual(parse_outcome(stdout), parse_outcome(log), (shell, "host line differs from the logged line"))
            self.assertEqual(sum(line.startswith(OUTCOME_LINE) for line in log.splitlines()), 1, (shell, log))
            return Run(done.returncode, log, stdout, parse_outcome(log))

    def test_stderr_is_logged_and_the_printed_run_is_synced(self):
        if not shells():
            self.skipTest("PowerShell not available")
        for shell in shells():
            run = self.run_copy(shell, PUBLISH_OK, SYNC_OK)
            self.assertEqual(run.code, 0, (shell, run.log))
            self.assertIn("SyntheticWarning: noisy stderr line", run.log)
            self.assertIn("wrangler notice on stderr", run.log)
            self.assertIn("SYNCED ", run.log)
            self.assertIn(RUN_ID, run.log.split("SYNCED ", 1)[1].splitlines()[0])
            self.assertRegex(run.log, OUTCOME_PATH)  # the caller hands the sync a fresh sealed-sync-<guid>.json
            # replaces 'REFRESH OK run=<id> pointer last': the confirmed pointer is the only success
            self.assertEqual(run.outcome, {
                "schema_version": 1, "primary_exit": 0, "primary_phase": "COMPLETE", "error_category": "NONE",
                "pointer_state": "READBACK_CONFIRMED", "run_id": RUN_ID, "local_maintenance": None,
                "secondary_log_failure": False, "publication_confirmed": True, "publication_operation_succeeded": True},
                (shell, run.log))

    def test_sync_failure_and_missing_run_id_are_logged(self):
        if not shells():
            self.skipTest("PowerShell not available")
        for shell in shells():
            run = self.run_copy(shell, PUBLISH_OK, SYNC_FAIL)
            self.assertEqual(run.code, 3, (shell, run.log))
            self.assertIn("Traceback: synthetic failure", run.log)
            # replaces 'SYNC FAILED exit=3': the sync's exit code and its FAILED outcome, pointer never attempted
            self.assertEqual(run.outcome["primary_exit"], 3)
            self.assertEqual((run.outcome["primary_phase"], run.outcome["error_category"], run.outcome["pointer_state"]),
                             ("OBJECT_PUT", "UNKNOWN", "NOT_ATTEMPTED"))
            self.assertEqual((run.outcome["publication_confirmed"], run.outcome["publication_operation_succeeded"]), (False, False))
            self.assertEqual(run.outcome["run_id"], RUN_ID)
            run = self.run_copy(shell, PUBLISH_NO_RUN, SYNC_OK)
            self.assertNotEqual(run.code, 0)
            # replaces 'GENERATE FAILED run id not printed': no run id, so the sync never starts
            self.assertEqual((run.outcome["primary_exit"], run.outcome["primary_phase"], run.outcome["error_category"],
                              run.outcome["pointer_state"], run.outcome["run_id"]),
                             (1, "GENERATE", "GENERATED_RUN_UNCONFIRMED", "NOT_ATTEMPTED", None))  # no run id: JSON null
            self.assertFalse(run.outcome["publication_confirmed"])
            self.assertNotIn("SYNCED", run.log)

    def test_a_crashing_publisher_never_reaches_the_sync(self):
        if not shells():
            self.skipTest("PowerShell not available")
        for shell in shells():
            run = self.run_copy(shell, PUBLISH_CRASH, SYNC_OK)
            self.assertEqual(run.code, 2, (shell, run.log))
            self.assertIn("Traceback: synthetic publish crash", run.log)
            self.assertEqual((run.outcome["primary_exit"], run.outcome["error_category"], run.outcome["pointer_state"]),
                             (2, "GENERATION_FAILED", "NOT_ATTEMPTED"))
            self.assertNotIn("SYNCED", run.log)

    def test_no_newest_folder_guess(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("Sort-Object LastWriteTime", text)
        self.assertIn("Invoke-LoggedNative", text)


class SyncOutcomeContractTests(unittest.TestCase):
    """The caller trusts only an outcome file Read-SafeSyncOutcome accepts for ITS run (commit 52c7733): an exit 0 alone
    is never publication, so a missing, malformed or contradicting outcome fails the run and the pointer stays UNKNOWN."""

    run_copy = HourlyRefreshScriptTests.run_copy

    def setUp(self):
        if not shells():
            self.skipTest("PowerShell not available")

    def refused(self, run: Run, shell: str, code: int = 1, phase: str = "SYNC") -> None:
        self.assertEqual(run.code, code, (shell, run.log))
        self.assertEqual(run.outcome["primary_exit"], code)
        self.assertEqual((run.outcome["error_category"], run.outcome["pointer_state"], run.outcome["primary_phase"]),
                         ("SYNC_OUTCOME_UNAVAILABLE", "UNKNOWN", phase), (shell, run.log))
        self.assertEqual((run.outcome["publication_confirmed"], run.outcome["publication_operation_succeeded"]), (False, False))

    def test_exit_zero_without_an_outcome_is_refused(self):
        for shell in shells():
            run = self.run_copy(shell, PUBLISH_OK, sync_stub(0, write=False))
            self.assertIn("SYNCED ", run.log)  # the sync really ran and exited 0
            self.refused(run, shell)

    def test_a_nonzero_exit_without_an_outcome_keeps_its_exit_code(self):
        for shell in shells():
            self.refused(self.run_copy(shell, PUBLISH_OK, sync_stub(5, write=False)), shell, code=5)

    def test_an_outcome_the_reader_rejects_is_refused_even_at_exit_zero(self):
        rejected = {
            "malformed JSON": dict(raw="{not json"),
            "oversize (> 8192 bytes)": dict(raw='{"pad":"' + "x" * 9000 + '"}'),
            "another run id": dict(overrides={"run_id": "20260926T000000Z-ffffffffffff"}),
            "another operation": dict(overrides={"operation": "WATCHDOG"}),
            "schema_version 2": dict(overrides={"schema_version": 2}),
            "unknown pointer_state": dict(overrides={"pointer_state": "MAYBE"}),
            "unknown error_category": dict(overrides={"error_category": "PARSE_FAILED"}),
            "unknown phase": dict(overrides={"phase": "POINTER_READ"}),
            "wrong case": dict(overrides={"status": "succeeded"}),
            "string counter": dict(overrides={"cli_attempts_total": "3"}),
            "last attempts above total": dict(overrides={"cli_attempts_total": 1, "last_cli_attempts": 3}),
        }
        for shell in shells():
            for name, kwargs in rejected.items():
                with self.subTest(shell=shell, outcome=name):
                    self.refused(self.run_copy(shell, PUBLISH_OK, sync_stub(0, **kwargs)), shell)

    def test_exit_zero_with_an_unproven_outcome_is_not_success(self):
        for shell in shells():
            # (name, outcome, pointer observed confirmed): a confirmed pointer with a contradicting category still fails the
            # task (primary_exit 1) but is not undone, so publication_confirmed stays true and the operation did not succeed
            for name, overrides, confirmed in (
                    ("failed status", FAILED_UNCONFIRMED, False),
                    ("pointer only attempted", dict(pointer_state="ATTEMPTED_UNCONFIRMED", phase="POINTER_READBACK"), False),
                    ("category not NONE", dict(error_category="UNKNOWN"), True)):
                with self.subTest(shell=shell, outcome=name):
                    run = self.run_copy(shell, PUBLISH_OK, sync_stub(0, overrides))
                    self.assertEqual(run.code, 1, (shell, run.log))
                    self.assertEqual(run.outcome["error_category"], "SYNC_SUCCESS_UNPROVEN")
                    self.assertEqual(run.outcome["publication_confirmed"], confirmed)
                    self.assertFalse(run.outcome["publication_operation_succeeded"])

    def test_an_unconfirmed_pointer_is_reported_as_unconfirmed(self):
        for shell in shells():
            run = self.run_copy(shell, PUBLISH_OK, sync_stub(1, FAILED_UNCONFIRMED))
            self.assertEqual(run.code, 1, (shell, run.log))
            self.assertEqual((run.outcome["primary_phase"], run.outcome["error_category"], run.outcome["pointer_state"]),
                             ("POINTER_READBACK", "READBACK_MISMATCH", "ATTEMPTED_UNCONFIRMED"))
            self.assertFalse(run.outcome["publication_confirmed"])

    def test_a_failed_exit_with_category_none_is_named_a_process_failure(self):
        for shell in shells():
            run = self.run_copy(shell, PUBLISH_OK, sync_stub(4, dict(status="FAILED", phase="INPUT", pointer_state="NOT_ATTEMPTED")))
            self.assertEqual((run.code, run.outcome["error_category"]), (4, "SYNC_PROCESS_FAILED"), (shell, run.log))

    def test_a_confirmed_pointer_survives_a_later_local_failure(self):
        # Header of the script: post-readback local failure fails the task but does not undo the observed confirmation.
        for shell in shells():
            run = self.run_copy(shell, PUBLISH_OK, sync_stub(4))
            self.assertEqual((run.code, run.outcome["error_category"], run.outcome["pointer_state"]),
                             (4, "SYNC_PROCESS_FAILED", "READBACK_CONFIRMED"), (shell, run.log))
            self.assertEqual((run.outcome["publication_confirmed"], run.outcome["publication_operation_succeeded"]), (True, False))


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
    "if (root / ('publish_fail_' + run)).exists():\n    print('Traceback: synthetic crash', file=sys.stderr)\n    sys.exit(2)\n"
    "ids = {'RUN_A': '20260926T010000Z-aaaaaaaaaaaa', 'RUN_B': '20260926T010000Z-bbbbbbbbbbbb',"
    " 'RUN_C': '20260926T010000Z-cccccccccccc', 'RUN_D': '20260926T010000Z-dddddddddddd'}\n"
    "print('{')\nprint('  \"run_id\": \"' + ids[run] + '\",')\nprint('  \"top20_state\": \"' + state + '\"')\nprint('}')\n")
CARRY_REPLAY = TRACE + (
    "run = sys.argv[-1]\nfail = (root / ('replay_fail_' + run[-4:])).exists()\n"
    "trace('REPLAY ' + run[-4:] + (' FAIL' if fail else ' PASS'))\nsys.exit(1 if fail else 0)\n")
# sync_slow: the sync takes 2.5 s (the run ages past a 1 s post-seal budget); sync_fail: pointer written but unconfirmed.
CARRY_SYNC = TRACE + SYNC_PRELUDE + (
    "trace('SYNC ' + run_dir[-4:])\nprint('SYNC_ARG ' + run_dir)\nprint('SYNC_OUTCOME_PATH ' + outcome_path)\n"
    "if (root / 'sync_slow').exists():\n    time.sleep(2.5)\n"
    f"if (root / 'sync_fail').exists():\n    write_outcome(**{FAILED_UNCONFIRMED!r})\n    sys.exit(1)\n"
    "write_outcome()\n")
CARRY_LKG = TRACE + (
    "cmd = sys.argv[1]\ntrace('LKG ' + ' '.join(a for a in sys.argv[1:4] if not Path(a).is_absolute()))\n"
    "if cmd == 'due':\n    print('{\"due\": ' + ('false' if (root / 'not_due').exists() else 'true') + '}')\n")
ROTATION_STUB = "Add-Content -Path (Join-Path (Split-Path -Parent $PSScriptRoot) 'trace.txt') -Value 'ROTATION'\nexit 0\n"
REFRESH_STUB = ("param([string]$ProjectRoot, [switch]$NoModelBridge, [switch]$NoTunnel, [switch]$NoSync, [switch]$NoAutoActivation)\n"
                "Add-Content -Path (Join-Path $PSScriptRoot 'trace.txt') -Value ('REFRESH nosync=' + [bool]$NoSync)\n"
                "if (Test-Path (Join-Path $PSScriptRoot 'refresh_hang')) { Start-Sleep -Seconds 120 }\nexit 0\n")
FIRST_SEAL = "PUBLISH RUN_A --live-clock --top20-bundle --identity-shards --bottleneck-v3 --market-observations --price-shards"


def without_rotation(trace: list[str]) -> list[str]:
    """Rows that do not test the post-pointer daily data refresh drop its ROTATION line; that refresh has its own row,
    CarryForwardHourlyTests.test_the_daily_data_refresh_runs_after_the_pointer."""
    return [line for line in trace if line != "ROTATION"]


class CarryForwardHourlyTests(unittest.TestCase):
    """-CarryForwardTop20: seal first, replay fallback, refresh only after the pointer, bounded, backoff-gated."""

    def run_carry(self, shell: str, markers: tuple[str, ...] = (), carry: bool = True,
                  extra: tuple[str, ...] = (), run_dirs: tuple[str, ...] = ()) -> tuple[int, list[str], str, float]:
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
            snapshots = root / "data" / "v213-snapshots"
            for name in run_dirs:
                (snapshots / name).mkdir(parents=True)
            command = [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(scripts / SCRIPT.name)]
            if carry:
                command += ["-CarryForwardTop20", "-RefreshTimeoutSeconds", "5", "-TabbyUrl", "http://127.0.0.1:9", *extra]
            started = time.monotonic()
            done = subprocess.run(command, capture_output=True, timeout=240, env=run_env())
            elapsed = time.monotonic() - started
            trace_path = root / "trace.txt"
            trace = trace_path.read_text(encoding="utf-8").splitlines() if trace_path.exists() else []
            log = read_log(root)
            self.stdout = done.stdout.decode("utf-8", errors="replace")
            self.outcome = parse_outcome(log)
            self.assertEqual(parse_outcome(self.stdout), self.outcome, (shell, "host line differs from the logged line"))
            self.remaining = sorted(p.name for p in snapshots.iterdir()) if snapshots.exists() else []
            return done.returncode, trace, log, elapsed

    def setUp(self):
        if not shells():
            self.skipTest("PowerShell not available")

    def maintenance(self) -> dict:
        return self.outcome["local_maintenance"]

    def test_seals_before_refresh_and_promotes_a_replayed_candidate(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell)
            self.assertEqual(code, 0, (shell, log))
            trace = without_rotation(trace)
            self.assertEqual(trace[:3], [FIRST_SEAL, "REPLAY aaaa PASS", "SYNC aaaa"], trace)
            self.assertEqual(trace[3:5], ["LKG due", "REFRESH nosync=True"], trace)
            self.assertEqual(trace[5], "PUBLISH RUN_C --live-clock --top20-bundle --snapshot-root", trace)
            self.assertEqual(trace[6:], ["REPLAY cccc PASS", "LKG promote --candidate", "LKG record --result ok"], trace)
            self.assertIn("LOCAL_MODEL_UNAVAILABLE", log)  # no resolver in the fixture root
            # replaces 'TOP20 CANDIDATE OK': the candidate became the LKG, after a confirmed pointer
            self.assertEqual((self.outcome["primary_exit"], self.outcome["pointer_state"], self.outcome["publication_confirmed"]),
                             (0, "READBACK_CONFIRMED", True))
            self.assertEqual((self.maintenance()["top20_status"], self.maintenance()["top20_exit"]), ("LOCAL_LKG_PROMOTED", 0))
            self.assertEqual(self.maintenance()["prune_status"], "DONE")
            self.assertRegex(log, OUTCOME_PATH)

    # From 52c7733 to FIX-R1 the default (guidance-off) carry-forward run built $dailyArgs as $null, Start-Process refused the
    # null element and the catch recorded data_status LOCAL_EXCEPTION, so this daily data refresh never ran.
    def test_the_daily_data_refresh_runs_after_the_pointer(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("not_due",))
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace[:5], [FIRST_SEAL, "REPLAY aaaa PASS", "SYNC aaaa", "ROTATION", "LKG due"], trace)
            self.assertEqual((self.maintenance()["data_status"], self.maintenance()["data_exit"]), ("LOCAL_REFRESH_COMPLETED", 0))

    def test_identity_replay_failure_keeps_the_carried_top20(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("replay_fail_aaaa", "not_due"))
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace[:5], [FIRST_SEAL, "REPLAY aaaa FAIL",
                                         "PUBLISH RUN_D --live-clock --top20-bundle", "REPLAY dddd PASS", "SYNC dddd"], trace)
            self.assertIn("REPLAY FAILED run=20260926T010000Z-aaaaaaaaaaaa tier=OK", log)
            self.assertEqual((self.outcome["primary_exit"], self.outcome["run_id"], self.outcome["pointer_state"]),
                             (0, "20260926T010000Z-dddddddddddd", "READBACK_CONFIRMED"))

    def test_replay_failure_republishes_insufficient_and_still_syncs(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("replay_fail_aaaa", "replay_fail_dddd", "not_due"))
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace[2:7], ["PUBLISH RUN_D --live-clock --top20-bundle", "REPLAY dddd FAIL",
                                          "PUBLISH RUN_B --live-clock --top20-insufficient", "REPLAY bbbb PASS", "SYNC bbbb"], trace)
            self.assertIn("REPLAY FAILED", log)
            self.assertNotIn("REFRESH nosync=True", trace)
            self.assertEqual((self.outcome["primary_exit"], self.outcome["run_id"]), (0, "20260926T010000Z-bbbbbbbbbbbb"))

    def test_both_replays_failing_leave_the_pointer_untouched(self):
        # 52c7733 intent: local maintenance follows the publication ATTEMPT even on failure (script header), so ROTATION
        # and the Top20 refresh may run now; the guarded invariant is that no sync starts, the pointer is NOT_ATTEMPTED,
        # the run fails, and nothing is pruned against an unconfirmed pointer.
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("replay_fail_aaaa", "replay_fail_dddd", "replay_fail_bbbb"))
            self.assertNotEqual(code, 0)
            self.assertFalse([line for line in trace if line.startswith("SYNC")], trace)
            self.assertEqual(trace[:6], [FIRST_SEAL, "REPLAY aaaa FAIL", "PUBLISH RUN_D --live-clock --top20-bundle",
                                         "REPLAY dddd FAIL", "PUBLISH RUN_B --live-clock --top20-insufficient", "REPLAY bbbb FAIL"], trace)
            # replaces 'GENERATE FAILED stage=REPLAY (pointer untouched)'
            self.assertEqual((self.outcome["primary_exit"], self.outcome["primary_phase"], self.outcome["error_category"],
                              self.outcome["pointer_state"], self.outcome["run_id"]),
                             (code, "REPLAY", "GENERATION_OR_REPLAY_FAILED", "NOT_ATTEMPTED", ""))
            self.assertEqual((self.outcome["publication_confirmed"], self.outcome["publication_operation_succeeded"]), (False, False))
            self.assertEqual(self.maintenance()["prune_status"], "SKIPPED_PUBLICATION_UNCONFIRMED")

    def test_refresh_timeout_kills_the_tree_after_the_seal_and_records_backoff(self):
        for shell in shells():
            code, trace, log, elapsed = self.run_carry(shell, ("refresh_hang",))
            self.assertEqual(code, 0, (shell, log))
            self.assertLess(trace.index("SYNC aaaa"), trace.index("REFRESH nosync=True"))
            self.assertIn("TOP20_REFRESH TIMEOUT after 5s", log)
            self.assertIn("LKG record --result fail", trace)
            self.assertNotIn("LKG promote --candidate", trace)
            self.assertLess(elapsed, 90)
            # the refresh failure (exit 124 = killed) never changes the primary result
            self.assertEqual((self.outcome["primary_exit"], self.maintenance()["top20_status"], self.maintenance()["top20_exit"]),
                             (0, "REFRESH_FAILED", 124))

    def test_backoff_or_fresh_lkg_skips_the_refresh(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("not_due",))
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace[-1], "LKG due", trace)
            self.assertNotIn("REFRESH nosync=True", trace)
            self.assertEqual((self.maintenance()["top20_status"], self.maintenance()["top20_exit"]), ("NOT_DUE_OR_BACKOFF", 0))

    def test_a_failed_candidate_replay_never_replaces_the_lkg(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("replay_fail_cccc",))
            self.assertEqual(code, 0, (shell, log))
            self.assertNotIn("LKG promote --candidate", trace)
            self.assertEqual(trace[-1], "LKG record --result fail", trace)
            self.assertEqual((self.maintenance()["top20_status"], self.maintenance()["top20_exit"]), ("CANDIDATE_FAILED", 1))

    def test_snapshot_root_moves_sealed_runs_out_of_the_attested_tree(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("not_due",), extra=("-SnapshotRoot", r"data\v213-snapshots"))
            self.assertEqual(code, 0, (shell, log))
            self.assertRegex(log, r"SYNC_ARG .*\\data\\v213-snapshots\\20260926T010000Z-aaaaaaaaaaaa")

    def test_a_crashing_lazy_tier_falls_through_to_the_next_tier(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("publish_fail_RUN_A", "not_due"))
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace[1:4], ["PUBLISH RUN_D --live-clock --top20-bundle", "REPLAY dddd PASS", "SYNC dddd"], trace)
            self.assertIn("GENERATE FAILED tier=", log)

    def test_old_runs_under_the_snapshot_root_are_pruned_after_the_seal(self):
        old = ("20260925T010000Z-111111111111", "20260925T020000Z-222222222222", "20260925T030000Z-333333333333", "keep-me")
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("not_due",), extra=("-SnapshotRoot", r"data\v213-snapshots", "-KeepRuns", "2"),
                                                 run_dirs=old + ("20260926T010000Z-aaaaaaaaaaaa",))
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(self.remaining, ["20260925T030000Z-333333333333", "20260926T010000Z-aaaaaaaaaaaa", "keep-me"])
            self.assertEqual(self.maintenance()["prune_status"], "DONE")

    def test_nothing_is_pruned_when_the_pointer_is_unconfirmed(self):
        # New under 52c7733 ("never prune against a guessed current pointer after failed/unconfirmed sync").
        old = ("20260925T010000Z-111111111111", "20260925T020000Z-222222222222", "20260925T030000Z-333333333333", "keep-me")
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("not_due", "sync_fail"),
                                                 extra=("-SnapshotRoot", r"data\v213-snapshots", "-KeepRuns", "2"),
                                                 run_dirs=old + ("20260926T010000Z-aaaaaaaaaaaa",))
            self.assertEqual(code, 1, (shell, log))
            self.assertEqual(self.remaining, sorted(old + ("20260926T010000Z-aaaaaaaaaaaa",)))
            self.assertEqual((self.outcome["primary_phase"], self.outcome["error_category"], self.outcome["pointer_state"]),
                             ("POINTER_READBACK", "READBACK_MISMATCH", "ATTEMPTED_UNCONFIRMED"))
            self.assertEqual(self.maintenance()["prune_status"], "SKIPPED_PUBLICATION_UNCONFIRMED")
            self.assertEqual(trace[-1], "LKG due", trace)  # maintenance still ran, within the same budget

    def test_an_exhausted_post_seal_budget_skips_the_refreshes(self):
        # 52c7733 rejects -PostSealBudgetSeconds 0 (BUDGET_INVALID, see the next row), so the budget is exhausted the way
        # the task meets it: a 1 s budget and a sync that takes 2.5 s.
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, ("sync_slow",), extra=("-PostSealBudgetSeconds", "1"))
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace, [FIRST_SEAL, "REPLAY aaaa PASS", "SYNC aaaa"], trace)
            # replaces 'POST_SEAL SKIPPED Top20 refresh'
            self.assertEqual((self.maintenance()["data_status"], self.maintenance()["top20_status"]), ("SKIPPED_BUDGET", "SKIPPED_BUDGET"))
            self.assertEqual((self.outcome["primary_exit"], self.outcome["publication_confirmed"]), (0, True))

    def test_a_zero_post_seal_budget_is_refused_before_any_work(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, extra=("-PostSealBudgetSeconds", "0"))
            self.assertEqual(code, 1, (shell, self.stdout))
            self.assertIn("SEALED_REFRESH_FAILED phase=ROOT_OR_PREREQUISITE pointer_state=NOT_ATTEMPTED maintenance=NOT_ADMITTED", self.stdout)
            self.assertEqual((trace, log, self.outcome), ([], "", {}))  # no publish, no log, no outcome line

    def test_switch_off_keeps_the_default_flow(self):
        for shell in shells():
            code, trace, log, _ = self.run_carry(shell, carry=False)
            self.assertEqual(code, 0, (shell, log))
            self.assertEqual(trace, ["ROTATION", "PUBLISH RUN_D --live-clock", "SYNC dddd"])
            self.assertEqual((self.outcome["primary_exit"], self.outcome["local_maintenance"]), (0, None))  # no maintenance off-switch


if __name__ == "__main__":
    unittest.main()
