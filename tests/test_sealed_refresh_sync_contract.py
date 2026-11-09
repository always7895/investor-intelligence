"""P6, offline: the contract between scripts/run_production_sealed_refresh.ps1 (the hourly caller) and
scripts/sync_sealed_snapshot_kv.py. The PowerShell scripts are read as text and never run.

The caller starts the sync with `--run-dir $runDir --outcome-path $outcomePath` (a fresh sealed-sync-<guid>.json per
run) and trusts only an outcome file that its Read-SafeSyncOutcome accepts. These rows bind both sides: the argv read
from the script is the argv the real SY.main parses here (seam B of tests/sealed_kv_fakes.py: the real retry and CLI
layers over a fake subprocess.run, no process is launched); every outcome file the sync writes is checked by a Python
mirror of Read-SafeSyncOutcome built from the closed value lists read from the script; and every status, phase,
pointer state and error category literal of the sync is inside those lists (the freshness watchdog's lists for
--read-freshness). Running the scripts themselves needs a PowerShell host and stays outside this module. Each row
compares a literal designed from the code; the comment above each row cites the lines it was designed from."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sync_sealed_snapshot_kv as SY  # noqa: E402
from sealed_kv_fakes import (  # noqa: E402
    NOWRITE, OLD_POINTER, POINTER_KEY, Q_OK, RUN, FakeKV, Fixture, KvTestCase, Row, cli_environment, make_cloud,
    run_sy)

REFRESH = (ROOT / "scripts" / "run_production_sealed_refresh.ps1").read_text(encoding="utf-8-sig")
GUID = "0123456789abcdef0123456789abcdef"
VIEW = ("status", "phase", "error_category", "pointer_state")
CALLER_REFUSES = "CALLER_REFUSES"


def quoted(fragment: str) -> tuple:
    return tuple(re.findall(r"'([A-Z_]+)'", fragment))


def refresh_lists() -> dict:
    """The closed value lists of Read-SafeSyncOutcome (refresh ps1 266-283)."""
    block = REFRESH[REFRESH.index("function Read-SafeSyncOutcome"):REFRESH.index("function Invoke-AdmittedLocalMaintenance")]
    return {field: quoted(re.search(r"\$r\." + field + r" -cnotin @\(([^)]*)\)", block).group(1))
            for field in ("status", "pointer_state", "error_category", "phase")}




def read_safe_sync_outcome(path: Path, expected_run: str, lists: dict) -> dict:
    """Python mirror of Read-SafeSyncOutcome (refresh ps1 266-283) over the lists read from the script; raises
    ValueError where the script throws (unavailable, unparseable or invalid outcome)."""
    if not path.is_file() or path.stat().st_size > 8192:
        raise ValueError("SYNC_OUTCOME_UNAVAILABLE")
    record = json.loads(path.read_bytes().decode("utf-8"))

    def integer(value, low, high):  # Test-OutcomeInteger (ps1 261-265): a JSON integer, never a bool or a float
        return type(value) is int and low <= value <= high

    ok = (isinstance(record, dict) and integer(record.get("schema_version"), 1, 1) and record.get("operation") == "SYNC"
          and record.get("run_id") == expected_run and record.get("status") in lists["status"]
          and record.get("pointer_state") in lists["pointer_state"]
          and record.get("error_category") in lists["error_category"] and record.get("phase") in lists["phase"]
          and integer(record.get("cli_attempts_total"), 0, 2147483647) and integer(record.get("last_cli_attempts"), 0, 3)
          and record["last_cli_attempts"] <= record["cli_attempts_total"]
          and all(integer(record.get(name), 0, 2147483647) for name in ("objects_uploaded", "objects_reused", "objects_verified"))
          and (record.get("last_cli_exit_code") is None or integer(record["last_cli_exit_code"], -2147483648, 4294967295)))
    if not ok:
        raise ValueError("SYNC_OUTCOME_INVALID")
    if record["status"] == "RETAINED_LAST_GOOD" and (
            record["pointer_state"] != "NOT_ATTEMPTED" or record["error_category"] != "NONE" or record["phase"] != "COMPLETE"
            or record.get("retention_reason") not in {"NO_CHANGE", "WRITE_BUDGET", "DAILY_KV_LIMIT", "CANDIDATE_UNAVAILABLE"}
            or not isinstance(record.get("retained_run_id"), str)
            or not re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{12}", record["retained_run_id"])):
        raise ValueError("SYNC_OUTCOME_INVALID")
    return record


class RefreshSyncContract(KvTestCase):
    def setUp(self):
        super().setUp()
        self.kv = FakeKV({POINTER_KEY: OLD_POINTER})
        self.ledger = self.tmp / "ledger" / "kv-blob-ledger.json"
        self.logs = self.tmp / "logs"
        self.logs.mkdir()
        self.outcome = self.logs / ("sealed-sync-" + GUID + ".json")
        self.lists = refresh_lists()

    def caller_row(self, fx, **kwargs) -> tuple:
        """One sync started with the caller's argv shape (P6-1) at seam B; the row adds what the caller's reader sees."""
        run_dir = fx.write_to(self.tmp / "runs" / fx.run)
        r = run_sy(SY, self.kv, run_dir, self.ledger, fx.names, seam="B", outcome_path=self.outcome, **kwargs)
        try:
            caller = read_safe_sync_outcome(self.outcome, fx.run, self.lists)
            view = tuple(caller[name] for name in VIEW)
        except ValueError:
            view = CALLER_REFUSES
        return r, Row(("exit", "outcome", "caller_view"), (r.exit, r.outcome, view))

    # P6-1, refresh ps1 403-408: exactly one sync start, `--run-dir $runDir --outcome-path $outcomePath`, with a fresh
    # sealed-sync-<guid>.json under the log dir. Substituted, it is the argv run_sy hands to SY.main (sealed_kv_fakes
    # 366-368), and the caller's reader accepts the outcome of a completed sync with the caller's own verdict fields.
    def test_P6_1_caller_argv_is_parsed_by_the_sync(self):
        starts = re.findall(r"& \$py ['\"]scripts\\sync_sealed_snapshot_kv\.py['\"]([^}\r\n]*)\}", REFRESH)
        self.assertEqual([start.split() for start in starts], [["--run-dir", "$runDir", "--outcome-path", "$outcomePath"]])
        self.assertIn("$outcomePath = Join-Path $logDir ('sealed-sync-' + [guid]::NewGuid().ToString('N') + '.json')",
                      REFRESH)
        run_dir = self.tmp / "runs" / RUN
        argv = [{"$runDir": str(run_dir), "$outcomePath": str(self.outcome)}.get(token, token) for token in starts[0].split()]
        self.assertEqual(argv, ["--run-dir", str(run_dir), "--outcome-path", str(self.outcome)])
        _, row = self.caller_row(Fixture(RUN, "sy"))
        self.assertRow(row, (0, Q_OK, Q_OK))
        self.assertEqual(self.kv.store[POINTER_KEY], Fixture(RUN, "sy").ptr_raw.encode("utf-8"))

    # P6-2a, SY 252-254 (seam B: 'kv put failed' classifies UNKNOWN, SY 115, terminal at 156): the caller reads the
    # same failure, with the pointer NOT_ATTEMPTED.
    def test_P6_2a_object_put_failure_reaches_the_caller(self):
        fx = Fixture(RUN, "sy")
        self.kv.fail_put(fx.key["B2"], 1, NOWRITE)
        _, row = self.caller_row(fx)
        failed = ("FAILED", "OBJECT_PUT", "UNKNOWN", "NOT_ATTEMPTED")
        self.assertRow(row, (1, failed, failed))

    # P6-2b, SY 266-270: a failed pointer put is ATTEMPTED_UNCONFIRMED for the caller too (never "untouched").
    def test_P6_2b_pointer_put_failure_reaches_the_caller(self):
        fx = Fixture(RUN, "sy")
        self.kv.fail_put(POINTER_KEY, 1, NOWRITE)
        _, row = self.caller_row(fx)
        failed = ("FAILED", "POINTER_PUT", "UNKNOWN", "ATTEMPTED_UNCONFIRMED")
        self.assertRow(row, (1, failed, failed))

    # P6-2c, SY 271-275: an altered pointer readback is READBACK_MISMATCH, a category only the sync emits.
    def test_P6_2c_pointer_readback_mismatch_reaches_the_caller(self):
        fx = Fixture(RUN, "sy")
        self.kv.corrupt_get(POINTER_KEY, 1, b"altered-pointer")
        _, row = self.caller_row(fx)
        failed = ("FAILED", "POINTER_READBACK", "READBACK_MISMATCH", "ATTEMPTED_UNCONFIRMED")
        self.assertRow(row, (1, failed, failed))

    # P6-2d, SY 219 then 224-225: the run id is recorded before the trailing-LF refusal, so the caller accepts the
    # INPUT_INVALID outcome for ITS run (an empty run id would be SYNC_OUTCOME_INVALID, ps1 270).
    def test_P6_2d_trailing_lf_input_refusal_reaches_the_caller(self):
        fx = Fixture(RUN, "sy", s1_body='{"slot":"a"}\n')
        r, row = self.caller_row(fx)
        failed = ("FAILED", "INPUT", "INPUT_INVALID", "NOT_ATTEMPTED")
        self.assertRow(row, (1, failed, failed))
        self.assertEqual(r.ops, ())

    # P6-2e, SY 45-62 and 135-137: the real _cli_command over a mismatched synthetic cloud dir (declared 4.0.1 != locked
    # 4.0.0) launches nothing; the caller reads CLI_UNAVAILABLE with a null exit code (ps1 281 accepts null).
    def test_P6_2e_unavailable_cli_reaches_the_caller(self):
        cloud = make_cloud(self.tmp, "4.0.0", declared="4.0.1")
        node = self.tmp / "node-stub"
        node.write_bytes(b"")
        with cli_environment(node), mock.patch.object(SY, "CLOUD_DIR", cloud):
            r, row = self.caller_row(Fixture(RUN, "sy"), real_cli=True)
        failed = ("FAILED", "OBJECT_PUT", "CLI_UNAVAILABLE", "NOT_ATTEMPTED")
        self.assertRow(row, (1, failed, failed))
        self.assertEqual((r.argv_log, r.counters), ([], (0, 0, None)))

    # P6-2f, SY 348-358: an outcome path that already exists (the caller's guid makes it unreachable in practice) stops
    # the sync before any call; the caller would find only the older bytes and refuse them (SYNC_OUTCOME_UNAVAILABLE).
    def test_P6_2f_existing_outcome_path_runs_nothing(self):
        self.outcome.write_bytes(b"older result bytes")
        r, row = self.caller_row(Fixture(RUN, "sy"))
        self.assertRow(row, (1, ("FAILED", "INPUT", "OUTCOME_WRITE_FAILED", "NOT_ATTEMPTED"), CALLER_REFUSES))
        self.assertEqual((r.ops, self.kv.store[POINTER_KEY]), ((), OLD_POINTER))



if __name__ == "__main__":
    unittest.main()
