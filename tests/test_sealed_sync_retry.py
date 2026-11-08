"""Offline V28 whole-run retry gates; fake child only, no Wrangler or scheduler."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sealed_sync_retry as retry  # noqa: E402

RUN = "20261028T141233Z-aaaaaaaaaaaa"
UTC = timezone.utc
NOW = datetime(2026, 10, 28, 14, 42, 40, tzinfo=UTC)


class SealedSyncRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.cache = self.repo / "data" / "cache"
        self.snap = self.repo / "data" / "v213-snapshots"
        self.cache.mkdir(parents=True)
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "sync_sealed_snapshot_kv.py").write_text("# fake child\n", encoding="utf-8")
        self.make_run(RUN)
        self.set_primary(RUN)
        self.calls = []

    def make_run(self, run=RUN, count=2):
        run_dir = self.snap / run
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "objects.json").write_text(json.dumps({f"k{i}": "{}" for i in range(count)}), encoding="utf-8")
        (run_dir / "pointer.raw.json").write_text(json.dumps({"run_id": run}), encoding="utf-8")
        return run_dir

    def set_primary(self, run, *, status="FAILED", phase="OBJECT_PUT",
                    category="TRANSIENT_HTTP", pointer="NOT_ATTEMPTED", exit_code=1):
        record = {
            "schema_version": 1, "operation": "SYNC", "run_id": run,
            "status": status, "phase": phase, "error_category": category,
            "pointer_state": pointer, "objects_uploaded": 1,
            "objects_reused": 0, "objects_verified": 0,
            "cli_attempts_total": 4, "last_cli_attempts": 3, "last_cli_exit_code": exit_code,
        }
        (self.cache / ("sealed-sync-" + "0" * 32 + ".json")).write_text(
            json.dumps(record), encoding="utf-8")
        summary = {
            "run_id": run, "primary_exit": exit_code, "primary_phase": phase,
            "error_category": category, "pointer_state": pointer,
            "publication_confirmed": False, "publication_operation_succeeded": False,
        }
        (self.cache / "sealed-refresh.log").write_text(
            "SEALED_REFRESH_OUTCOME " + json.dumps(summary) + "\n", encoding="utf-8")
        return record, summary

    def runner(self, script, run_dir, outcome):
        self.calls.append((script, run_dir, outcome))
        data = {
            "schema_version": 1, "operation": "SYNC", "run_id": run_dir.name,
            "status": "SUCCEEDED", "phase": "COMPLETE", "error_category": "NONE",
            "pointer_state": "READBACK_CONFIRMED",
        }
        outcome.write_text(json.dumps(data), encoding="utf-8")
        return 0

    def attempt(self, now=NOW):
        return retry.attempt_once(self.repo, self.snap, now, self.runner)

    def test_eligible_once_has_durable_marker_and_confirmed_readback(self):
        result = self.attempt()
        self.assertEqual((result["status"], result["attempted"], len(self.calls)),
                         ("SUCCEEDED", True, 1))
        self.assertEqual(result["reserved_put_attempts"], 9)
        marker = self.cache / "sealed-sync-retry-markers" / (RUN + ".json")
        recorded = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual((recorded["status"], recorded["result"], recorded["attempts"]),
                         ("COMPLETE", "SUCCEEDED", 1))
        second = self.attempt()
        self.assertEqual((second["status"], second["reason"], len(self.calls)),
                         ("SKIPPED", "ALREADY_ATTEMPTED", 1))

    def test_both_admitted_error_categories_and_pre_pointer_phase(self):
        for category in ("TRANSIENT_HTTP", "AUTHENTICATION_ERROR"):
            with self.subTest(category=category):
                self.set_primary(RUN, category=category)
                self.assertEqual(self.attempt()["status"], "SUCCEEDED")
                self.assertEqual(len(self.calls), 1)
                self.calls.clear()
                (self.cache / "sealed-sync-retry-markers" / (RUN + ".json")).unlink()
                (self.cache / ("sealed-sync-retry-" + RUN + ".json")).unlink()
        # In a real sync, POINTER_PUT has ATTEMPTED_UNCONFIRMED, not NOT_ATTEMPTED.
        # This forged but logically pre-pointer combination must still satisfy the literal gate.
        self.set_primary(RUN, phase="POINTER_PUT")
        self.assertEqual(self.attempt()["status"], "SUCCEEDED")

    def test_ineligible_categories_are_never_launched(self):
        disallowed = ("NONE", "DAILY_KV_LIMIT", "READBACK_MISMATCH", "NETWORK_FAILURE",
                      "TIMEOUT", "UNKNOWN", "INPUT_INVALID", "LOCAL_IO_FAILURE",
                      "CLI_UNAVAILABLE", "OUTCOME_WRITE_FAILED", "PARSE_FAILED")
        for category in disallowed:
            with self.subTest(category=category):
                self.set_primary(RUN, category=category)
                self.assertEqual(self.attempt()["reason"], "INELIGIBLE_SYNC_OUTCOME")
        self.assertEqual(self.calls, [])

    def test_ineligible_phases_are_never_launched(self):
        for phase in ("INPUT", "OBJECT_READBACK", "POINTER_READBACK", "LOCAL_LEDGER", "COMPLETE"):
            with self.subTest(phase=phase):
                self.set_primary(RUN, phase=phase)
                self.assertEqual(self.attempt()["reason"], "INELIGIBLE_SYNC_OUTCOME")
        self.assertEqual(self.calls, [])

    def test_pointer_must_not_have_been_attempted(self):
        for state in ("ATTEMPTED_UNCONFIRMED", "READBACK_CONFIRMED", "UNKNOWN"):
            with self.subTest(state=state):
                self.set_primary(RUN, pointer=state)
                self.assertEqual(self.attempt()["reason"], "INELIGIBLE_SYNC_OUTCOME")
        self.assertEqual(self.calls, [])

    def test_age_minimum_maximum_and_window(self):
        for offset in (timedelta(minutes=19), timedelta(minutes=46)):
            with self.subTest(offset=offset), mock.patch.object(
                    retry, "_stamp", return_value=NOW - offset):
                self.assertEqual(self.attempt()["reason"], "RUN_AGE_INELIGIBLE")
        self.assertEqual(self.attempt(NOW.replace(minute=12))["reason"], "NOT_RETRY_WINDOW")
        self.assertEqual(self.calls, [])

    def test_newer_seal_disqualifies_old_failed_run(self):
        self.make_run("20261028T143000Z-bbbbbbbbbbbb")
        self.assertEqual(self.attempt()["reason"], "RUN_AGE_INELIGIBLE")
        self.assertEqual(self.calls, [])

    def test_last_primary_summary_not_current_or_inconsistent(self):
        record, summary = self.set_primary(RUN)
        summary["run_id"] = "20261028T131200Z-bbbbbbbbbbbb"
        (self.cache / "sealed-refresh.log").write_text(
            "SEALED_REFRESH_OUTCOME " + json.dumps(summary), encoding="utf-8")
        self.assertEqual(self.attempt()["reason"], "NOT_LATEST_FAILED_PRIMARY")
        record, summary = self.set_primary(RUN)
        summary["pointer_state"] = "ATTEMPTED_UNCONFIRMED"
        (self.cache / "sealed-refresh.log").write_text(
            "SEALED_REFRESH_OUTCOME " + json.dumps(summary), encoding="utf-8")
        self.assertEqual(self.attempt()["reason"], "PRIMARY_OUTCOME_MISMATCH")
        self.assertEqual(self.calls, [])

    def test_budget_refuses_before_marker_or_subprocess(self):
        self.make_run(RUN, count=300)
        result = self.attempt()
        self.assertEqual((result["status"], result["reason"]), ("SKIPPED", "DAILY_BUDGET_REFUSED"))
        self.assertFalse((self.cache / "sealed-sync-retry-markers").exists())
        self.assertEqual(self.calls, [])

    def test_prior_retry_marker_reserves_writes_even_if_incomplete(self):
        older = "20261028T121233Z-cccccccccccc"
        self.make_run(older, count=240)
        markers = self.cache / "sealed-sync-retry-markers"
        markers.mkdir()
        (markers / (older + ".json")).write_bytes(b"")  # crash after O_EXCL claim
        self.assertEqual(self.attempt()["reason"], "DAILY_BUDGET_REFUSED")
        self.assertEqual(self.calls, [])

    def test_success_is_never_inferred_from_exit_only(self):
        def bad_runner(script, run_dir, outcome):
            self.calls.append((script, run_dir, outcome))
            outcome.write_text(json.dumps({"schema_version": 1, "operation": "SYNC",
                                           "run_id": run_dir.name, "status": "SUCCEEDED",
                                           "pointer_state": "ATTEMPTED_UNCONFIRMED",
                                           "phase": "POINTER_PUT", "error_category": "NONE"}))
            return 0
        row = retry.attempt_once(self.repo, self.snap, NOW, bad_runner)
        self.assertEqual((row["status"], row["reason"]), ("FAILED", "POINTER_UNCONFIRMED"))
        self.assertEqual(self.attempt()["reason"], "ALREADY_ATTEMPTED")

    def test_exit_zero_without_outcome_fails_closed(self):
        result = retry.attempt_once(self.repo, self.snap, NOW, lambda *_: 0)
        self.assertEqual((result["status"], result["reason"]), ("FAILED", "OUTCOME_UNAVAILABLE"))
        self.assertEqual(self.attempt()["reason"], "ALREADY_ATTEMPTED")

    def test_cli_wiring_is_opt_in_and_uses_same_mutex(self):
        watchdog = (ROOT / "scripts" / "freshness_watchdog.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "register_sealed_freshness_tasks.ps1").read_text(encoding="utf-8")
        self.assertIn("if ($RetryFailedSync -and $null -ne $logPath)", watchdog)
        self.assertIn("Enter-V213OperationLock -Owner 'SEALED_SYNC_RETRY' -TimeoutSeconds 0", watchdog)
        self.assertIn("Exit-V213OperationLock", watchdog)
        self.assertIn("if ($Definition.Name -eq 'InvestorIntelligenceSealedFreshness')", installer)
        self.assertIn("' -RetryFailedSync'", installer)
        self.assertIn("[switch]$EnableSyncRetry", installer)


if __name__ == "__main__":
    unittest.main()
