"""Offline real publisher/seal/blob-reuse/sync transactions, never a quota-only simulator."""
from __future__ import annotations

import contextlib
import copy
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import publish_sealed_snapshot as publisher
import ranking_write_policy as policy
import sync_sealed_snapshot_kv as sync
import top20_carry_forward as carry
from sealed_kv_fakes import FakeKV, KvTestCase, NETWORK, POINTER_KEY, run_sy

CLOCKS = ("LIVE_NOW", "LIVE_STAMP", "EVALUATED_AT", "GENERATED_AT", "CLAIMED_AT", "PROMOTED_AT", "PUBLISHED_DATA_AS_OF")
START = datetime(2026, 11, 1, tzinfo=timezone.utc)


class Clock(datetime):
    instant = START

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class SealedQuotaIntegration(KvTestCase):
    def setUp(self):
        super().setUp()
        self.snapshots = self.tmp / "snapshots"
        self.ledger = self.tmp / "cache" / "kv-blob-ledger.json"
        self.budget_path = self.ledger.with_name("ranking-kv-write-budget.json")
        self.kv = FakeKV()
        self.symbols = [f"S{index:02d}" for index in range(20)]
        self.identity_count = 24
        for name in CLOCKS:
            self.addCleanup(setattr, publisher, name, getattr(publisher, name))
        for target, name, value in ((publisher, "datetime", Clock), (sync, "datetime", Clock),
                                    (sync, "LEDGER", self.ledger), (sync.time, "time", lambda: Clock.instant.timestamp())):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def evaluate(self, now, symbols=None, *, unavailable=False):
        Clock.instant = now
        symbols = symbols or self.symbols
        rows = [{"rank": index + 1, "ticker": symbol, "system_bottleneck_explosion_score": 90 - index}
                for index, symbol in enumerate(symbols)]
        if unavailable:
            rows = []
        report = {"generated_at": stamp(now), "records": rows, "admitted_count": len(rows), "ranked_count": len(rows)}
        lazy = {"schema": "v213-bottleneck-top20-v3-sealed", "generated_at": stamp(now),
                "top": [{"rank": index + 1, "symbol": symbol} for index, symbol in enumerate(symbols)]}

        def build(_carry=None):
            bodies = {name: json.dumps({"synthetic": name}, separators=(",", ":")) for name in publisher.OBJECT_KEYS}
            bodies[publisher.MACRO_KEY] = '{"synthetic":"macro"}'
            bodies["last_successful_pipeline_timestamp"] = stamp(now)
            bodies["v213:top20-report:latest"] = json.dumps(report, separators=(",", ":"))
            run = now.strftime("%Y%m%dT%H%M%SZ") + "-" + publisher._sha(bodies["v213:top20-report:latest"])[:12]
            return bodies, {"run_id": run, "transaction_id": "0" * 32, "report": report, "top20": report}

        keys = ([f"v213:identity:v2:sym:{bucket}" for bucket in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"]
                + [f"v213:identity:v2:name:{bucket}" for bucket in range(16)]
                + [f"v213:identity:v2:tok:{bucket}" for bucket in range(8)])
        if not 0 <= self.identity_count <= len(keys):
            raise ValueError("SYNTHETIC_IDENTITY_SHAPE_INVALID")
        collected = START + timedelta(hours=20 * int((now - START).total_seconds() // (20 * 3600)))
        identities = {key: json.dumps({"synthetic_identity": index, "generated_at": stamp(collected)})
                      for index, key in enumerate(keys[:self.identity_count])}
        buffer = StringIO()
        with mock.patch.object(publisher, "build_bodies", build), \
                mock.patch.object(publisher, "lazy_identity_bodies", return_value=identities), \
                mock.patch.object(publisher, "lazy_bottleneck_v3_body", return_value={} if unavailable else {
                    publisher.BOTTLENECK_V3_KEY: json.dumps(lazy)}), \
                contextlib.redirect_stdout(buffer):
            publisher.main(["--live-clock", "--identity-shards", "unused", "--bottleneck-v3", "unused",
                            "--snapshot-root", str(self.snapshots)])
        return json.loads(buffer.getvalue())

    def upload(self, summary):
        return run_sy(sync, self.kv, self.snapshots / summary["run_id"], self.ledger, {}, seam="B")

    def publish(self, now, symbols=None):
        summary = self.evaluate(now, symbols)
        result = None if summary.get("status") == "RETAINED_LAST_GOOD" else self.upload(summary)
        if result is not None:
            self.assertEqual(result.exit, 0, result.outcome)
        return summary, result

    def serving(self):
        pointer = json.loads(self.kv.store[POINTER_KEY])
        seal = json.loads(self.kv.store[f"snapshot:{pointer['run_id']}:{publisher.SEAL_KEY}"])
        digest = seal["objects"][publisher.BOTTLENECK_V3_KEY]["sha256"]
        body = self.kv.store["blob:v1:" + digest]
        document = json.loads(body)
        self.assertEqual(len(document["top"]), 20)
        self.assertEqual(policy.ordered_rank_digest(document), policy.ordered_rank_digest({"top": document["top"]}))
        return body, pointer

    def test_unchanged_hour_writes_nothing_and_keeps_exact_as_of(self):
        first, uploaded = self.publish(START)
        self.assertIsNotNone(uploaded)
        self.assertEqual(uploaded.record["writes_reserved"], (15 + 24 + 1 + 1) * 3)
        self.assertEqual(uploaded.record["writes_attempted"], 41)
        original, pointer = self.serving()
        before = {p.relative_to(self.tmp): p.read_bytes() for p in self.tmp.rglob("*") if p.is_file()}
        ops = len(self.kv.log)
        retained, result = self.publish(START + timedelta(hours=1))
        after = {p.relative_to(self.tmp): p.read_bytes() for p in self.tmp.rglob("*") if p.is_file()}
        self.assertIsNone(result)
        self.assertEqual((retained["status"], retained["retention_reason"], retained["pointer_state"]),
                         ("RETAINED_LAST_GOOD", "NO_CHANGE", "NOT_ATTEMPTED"))
        self.assertEqual((before, ops), (after, len(self.kv.log)))
        self.assertEqual(self.serving(), (original, pointer))
        heartbeat, uploaded = self.publish(START + timedelta(hours=6))
        self.assertNotEqual(first["run_id"], heartbeat["run_id"])
        self.assertEqual(uploaded.record["objects_reused"], 13 + 24)
        self.assertEqual((uploaded.record["ranking_writes_reserved"], uploaded.record["market_writes_reserved"]), (12, 0))
        self.assertEqual(uploaded.record["objects_verified"], 40)
        self.assertEqual(self.kv.puts[-1][0], POINTER_KEY)

    def test_whole_plan_budget_stop_has_zero_puts_and_resumes_at_utc_reset(self):
        first, _ = self.publish(START)
        budget = policy.DailyWriteBudget(self.budget_path)
        used = json.loads(self.budget_path.read_text())["reserved"]
        self.assertTrue(budget.reserve(400 - used - 11, START))  # the lean changed ranking needs12, not the whole bundle
        changed = list(reversed(self.symbols))
        retained = self.evaluate(START + timedelta(hours=1), changed)
        self.assertEqual(retained["retention_reason"], "WRITE_BUDGET")
        self.assertEqual(retained["run_id"], first["run_id"])
        before = copy.deepcopy(self.kv.store)
        # Exercise the authoritative sync gate as well, not just publisher's peek:
        with mock.patch.object(policy.DailyWriteBudget, "can_reserve", return_value=True):
            candidate = self.evaluate(START + timedelta(hours=2), changed)
        mark = len(self.kv.puts)
        stopped = self.upload(candidate)
        self.assertEqual((stopped.exit, stopped.record["status"], stopped.record["writes_reserved"]),
                         (0, "RETAINED_LAST_GOOD", 0))
        self.assertEqual((len(self.kv.puts), self.kv.store), (mark, before))
        self.assertFalse((self.snapshots / candidate["run_id"] / ".kv-stage").exists())
        resumed, uploaded = self.publish(START + timedelta(days=1), changed)
        self.assertIsNotNone(uploaded)
        self.assertNotEqual(resumed["run_id"], first["run_id"])
        self.assertLessEqual(json.loads(self.budget_path.read_text())["reserved"], 400)

    def test_retries_are_reserved_once_and_provider_quota_retains_without_ack(self):
        first, _ = self.publish(START)
        changed = list(reversed(self.symbols))
        Clock.instant = START + timedelta(hours=1)
        candidate = self.evaluate(Clock.instant, changed)
        objects = json.loads((self.snapshots / candidate["run_id"] / "objects.json").read_text())
        ledger = sync.load_ledger(self.ledger)
        first_put = next(key for key in sorted(objects) if not key.startswith(sync.BLOB_PREFIX) or key[8:] not in ledger)
        self.kv.fail_put(first_put, 1, NETWORK)
        retried = self.upload(candidate)
        self.assertEqual(retried.exit, 0)
        self.assertEqual(retried.record["writes_attempted"], 5)
        self.assertEqual((retried.record["ranking_writes_reserved"], retried.record["market_writes_reserved"]), (12, 0))
        self.assertEqual(json.loads(self.budget_path.read_text())["reserved"], 63)
        old_body, old_pointer = self.serving()
        quota_candidate = self.evaluate(START + timedelta(hours=2), self.symbols)
        original = self.kv.fake_run
        rejected = False

        def daily_limit(*args, **kwargs):
            nonlocal rejected
            argv = args[0]
            if "put" in argv and not rejected:
                rejected = True
                self.kv.fail_put(argv[argv.index("put") + 1], 1)
                original(*args, **kwargs)  # the rejected PUT is still an attempted write
                return subprocess.CompletedProcess(argv, 1, "", '{"success":false,"errors":[{"code":10048}]}')
            return original(*args, **kwargs)

        with mock.patch.object(self.kv, "fake_run", side_effect=daily_limit):
            stopped = self.upload(quota_candidate)
        self.assertEqual((stopped.exit, stopped.record["status"], stopped.record["retention_reason"],
                          stopped.record["pointer_state"]), (0, "RETAINED_LAST_GOOD", "DAILY_KV_LIMIT", "NOT_ATTEMPTED"))
        self.assertEqual(stopped.record["writes_attempted"], 1)
        self.assertEqual(self.serving(), (old_body, old_pointer))
        self.assertEqual(self.evaluate(START + timedelta(hours=3))["retention_reason"], "WRITE_BUDGET")
        self.kv.clear_hooks()
        _, resumed = self.publish(START + timedelta(days=1))
        self.assertIsNotNone(resumed)

    def test_pointer_quota_rejection_is_never_reported_as_retained_or_confirmed(self):
        self.publish(START)
        candidate = self.evaluate(START + timedelta(hours=1), list(reversed(self.symbols)))
        original = self.kv.fake_run

        def reject_pointer(*args, **kwargs):
            argv = args[0]
            if "put" in argv and argv[argv.index("put") + 1] == POINTER_KEY:
                self.kv.fail_put(POINTER_KEY, 1)
                original(*args, **kwargs)
                return subprocess.CompletedProcess(argv, 1, "", '{"success":false,"errors":[{"code":10048}]}')
            return original(*args, **kwargs)

        with mock.patch.object(self.kv, "fake_run", side_effect=reject_pointer):
            result = self.upload(candidate)
        self.assertEqual((result.exit, result.record["status"], result.record["error_category"],
                          result.record["pointer_state"]), (1, "FAILED", "DAILY_KV_LIMIT", "ATTEMPTED_UNCONFIRMED"))
        self.assertIsNone(result.record["retained_run_id"])
        self.assertLessEqual(result.record["writes_attempted"], result.record["writes_reserved"])

    def test_insufficient_fallback_cannot_replace_a_confirmed_ranking(self):
        self.publish(START)
        before = copy.deepcopy(self.kv.store)
        # A valid seal can honestly state insufficiency, but it is never a
        # replacement for a known historical Top20.
        retained = self.evaluate(START + timedelta(hours=1), unavailable=True)
        self.assertEqual((retained["status"], retained["retention_reason"]),
                         ("RETAINED_LAST_GOOD", "CANDIDATE_UNAVAILABLE"))
        self.assertEqual(self.kv.store, before)

    def test_unaffordable_bootstrap_is_explicit_and_has_no_partial_upload(self):
        self.identity_count = 60
        self.assertTrue(policy.DailyWriteBudget(self.budget_path).reserve(400, START))
        candidate = self.evaluate(START)
        result = self.upload(candidate)
        self.assertEqual((result.exit, result.record["error_category"], result.record["pointer_state"]),
                         (1, "BOOTSTRAP_REQUIRED", "NOT_ATTEMPTED"))
        self.assertEqual(self.kv.puts, [])
        self.assertNotIn(POINTER_KEY, self.kv.store)
        self.assertFalse((self.snapshots / carry.CONFIRMED_NAME).exists())

    def test_no_local_receipt_discovers_only_readback_verified_remote_last_good(self):
        first, _ = self.publish(START)
        (self.snapshots / carry.CONFIRMED_NAME).unlink()
        original, pointer = self.serving()
        candidate = self.evaluate(START + timedelta(hours=1))
        mark = len(self.kv.puts)
        retained = self.upload(candidate)
        self.assertEqual((retained.exit, retained.record["status"], retained.record["retained_run_id"]),
                         (0, "RETAINED_LAST_GOOD", first["run_id"]))
        self.assertEqual(len(self.kv.puts), mark)
        self.assertEqual(self.serving(), (original, pointer))
        self.assertTrue((self.snapshots / carry.CONFIRMED_NAME).exists())

    def test_insufficient_without_local_receipt_preserves_verified_remote_ranking(self):
        first, _ = self.publish(START)
        (self.snapshots / carry.CONFIRMED_NAME).unlink()
        before = copy.deepcopy(self.kv.store)
        candidate = self.evaluate(START + timedelta(hours=1), unavailable=True)
        mark = len(self.kv.puts)
        retained = self.upload(candidate)
        self.assertEqual((retained.exit, retained.record["status"], retained.record["retention_reason"],
                          retained.record["retained_run_id"], retained.record["pointer_state"]),
                         (0, "RETAINED_LAST_GOOD", "CANDIDATE_UNAVAILABLE", first["run_id"], "NOT_ATTEMPTED"))
        self.assertEqual((len(self.kv.puts), self.kv.store), (mark, before))
        self.assertEqual(carry.confirmed_snapshot(self.snapshots)["run_id"], first["run_id"])

    def test_uncertain_remote_discovery_never_bootstraps_insufficiency_over_a_ranking(self):
        self.publish(START)
        (self.snapshots / carry.CONFIRMED_NAME).unlink()
        before = copy.deepcopy(self.kv.store)
        candidate = self.evaluate(START + timedelta(hours=1), unavailable=True)
        self.kv.missing_get(POINTER_KEY, None)  # UNKNOWN is not an observed HTTP 404.
        mark = len(self.kv.puts)
        failed = self.upload(candidate)
        self.assertEqual((failed.exit, failed.record["error_category"], failed.record["pointer_state"],
                          failed.record["writes_reserved"]), (1, "BOOTSTRAP_REQUIRED", "NOT_ATTEMPTED", 0))
        self.assertEqual((len(self.kv.puts), self.kv.store), (mark, before))
        self.assertFalse((self.snapshots / carry.CONFIRMED_NAME).exists())

    def test_explicit_pointer_404_allows_honest_insufficient_bootstrap_without_ranking_receipt(self):
        candidate = self.evaluate(START, unavailable=True)
        original = self.kv.fake_run

        def observed_missing_pointer(*args, **kwargs):
            result = original(*args, **kwargs)
            argv = args[0]
            if "get" in argv and argv[argv.index("get") + 1] == POINTER_KEY and result.returncode:
                return subprocess.CompletedProcess(argv, 1, "",
                    "Failed to fetch https://synthetic.invalid/value - 404: missing")
            return result

        with mock.patch.object(self.kv, "fake_run", side_effect=observed_missing_pointer):
            result = self.upload(candidate)
        self.assertEqual((result.exit, result.record["status"], result.record["pointer_state"]),
                         (0, "SUCCEEDED", "READBACK_CONFIRMED"))
        self.assertIsNone(carry.confirmed_snapshot(self.snapshots))
        self.assertFalse((self.snapshots / carry.CONFIRMED_NAME).exists())
        pointer = json.loads(self.kv.store[POINTER_KEY])
        report = json.loads(self.kv.store[f"snapshot:{pointer['run_id']}:v213:top20-report:latest"])
        self.assertEqual(report["records"], [])

    def test_written_b_failed_readback_then_requested_a_never_uses_stale_a_receipt(self):
        first, _ = self.publish(START)
        receipt = self.snapshots / carry.CONFIRMED_NAME
        receipt_a = receipt.read_bytes()
        first_dir = self.snapshots / first["run_id"]
        historical_a = {name: (first_dir / name).read_bytes() for name in ("objects.json", "pointer.raw.json")}
        candidate_b = self.evaluate(START + timedelta(hours=1), list(reversed(self.symbols)))
        self.kv.missing_get(POINTER_KEY, 1)
        failed = self.upload(candidate_b)
        self.assertEqual((failed.exit, failed.record["status"], failed.record["pointer_state"]),
                         (1, "FAILED", "ATTEMPTED_UNCONFIRMED"))
        self.assertEqual(json.loads(self.kv.store[POINTER_KEY])["run_id"], candidate_b["run_id"])
        self.assertEqual(receipt.read_bytes(), receipt_a)
        self.assertTrue(carry.pointer_ambiguous(self.snapshots))
        self.assertIsNone(carry.confirmed_snapshot(self.snapshots))

        # A pointer alone cannot reconcile custody: every member must read back.
        self.kv.clear_hooks()
        objects_b = json.loads((self.snapshots / candidate_b["run_id"] / "objects.json").read_text())
        member = next(key for key in sorted(objects_b) if key.startswith(sync.BLOB_PREFIX))
        self.kv.corrupt_get(member, None, b"not-the-sealed-member")
        mark = len(self.kv.puts)
        with mock.patch.object(subprocess, "run", self.kv.fake_run), \
                mock.patch.object(sync, "_cli_command", return_value=["synthetic-cli"]):
            self.assertIsNone(sync.reconcile_confirmed_snapshot(self.snapshots))
        self.assertEqual(len(self.kv.puts), mark)
        self.assertEqual(receipt.read_bytes(), receipt_a)
        self.assertTrue(carry.pointer_ambiguous(self.snapshots))

        candidate_a = self.evaluate(START + timedelta(hours=2))
        self.assertNotEqual(candidate_a.get("status"), "RETAINED_LAST_GOOD")  # publisher preflight, not just sync
        self.assertNotEqual(candidate_a["run_id"], first["run_id"])
        self.kv.clear_hooks()
        restored = self.upload(candidate_a)
        self.assertEqual((restored.exit, restored.record["status"], restored.record["pointer_state"]),
                         (0, "SUCCEEDED", "READBACK_CONFIRMED"))
        body, pointer = self.serving()
        self.assertEqual(policy.ordered_rank_digest(json.loads(body)), policy.ordered_rank_digest({"top": self.symbols}))
        self.assertEqual(pointer["run_id"], candidate_a["run_id"])
        self.assertFalse(carry.pointer_ambiguous(self.snapshots))
        confirmed = carry.confirmed_snapshot(self.snapshots)
        self.assertEqual(confirmed["run_id"], candidate_a["run_id"])
        self.assertEqual(confirmed["objects"],
                         json.loads((self.snapshots / candidate_a["run_id"] / "objects.json").read_text()))
        self.assertEqual({name: (first_dir / name).read_bytes() for name in historical_a}, historical_a)
        self.assertEqual(restored.record["objects_verified"], len(confirmed["objects"]))
        self.assertEqual(self.kv.puts[-1][0], POINTER_KEY)

    def test_pending_marker_must_be_durable_before_pointer_launch(self):
        self.publish(START)
        receipt = (self.snapshots / carry.CONFIRMED_NAME).read_bytes()
        old_pointer = self.kv.store[POINTER_KEY]
        candidate = self.evaluate(START + timedelta(hours=1), list(reversed(self.symbols)))
        original = carry.mark_pointer_pending

        def cannot_flush_marker(run_dir):
            with mock.patch.object(carry.os, "fsync", side_effect=OSError("synthetic-flush-failure")):
                original(run_dir)

        mark = len(self.kv.puts)
        with mock.patch.object(carry, "mark_pointer_pending", side_effect=cannot_flush_marker):
            failed = self.upload(candidate)
        self.assertEqual((failed.exit, failed.record["error_category"], failed.record["pointer_state"]),
                         (1, "LOCAL_IO_FAILURE", "NOT_ATTEMPTED"))
        self.assertNotIn(POINTER_KEY, [key for key, _ in self.kv.puts[mark:]])
        self.assertEqual(self.kv.store[POINTER_KEY], old_pointer)
        self.assertEqual((self.snapshots / carry.CONFIRMED_NAME).read_bytes(), receipt)
        self.assertIsNotNone(carry.confirmed_snapshot(self.snapshots))

    def test_midnight_requires_full_remaining_plan_and_resumes_after_next_reset(self):
        self.publish(START)
        candidate = self.evaluate(START + timedelta(days=1, seconds=-1), list(reversed(self.symbols)))
        old_pointer = self.kv.store[POINTER_KEY]
        original = self.kv.fake_run
        launch_days = []
        old_reserved = []
        crossed = False

        def cross_after_first_put(*args, **kwargs):
            nonlocal crossed
            argv = args[0]
            if "put" in argv:
                launch_days.append(Clock.instant.date())
            result = original(*args, **kwargs)
            if "put" in argv and not crossed:
                crossed = True
                old_reserved.append(json.loads(self.budget_path.read_text())["reserved"])
                Clock.instant = START + timedelta(days=1)
                # One PUT fits the new day, but the complete remaining ranking
                # plan does not. Independent market capacity cannot be borrowed.
                self.assertTrue(policy.DailyWriteBudget(self.budget_path).reserve(353, Clock.instant))
            return result

        with mock.patch.object(self.kv, "fake_run", side_effect=cross_after_first_put):
            stopped = self.upload(candidate)
        self.assertEqual((stopped.exit, stopped.record["status"], stopped.record["retention_reason"],
                          stopped.record["pointer_state"]), (0, "RETAINED_LAST_GOOD", "WRITE_BUDGET", "NOT_ATTEMPTED"))
        self.assertEqual((launch_days, old_reserved), ([START.date()], [102]))
        self.assertEqual((stopped.record["writes_attempted"], stopped.record["writes_reserved"]), (1, 51))
        self.assertEqual(json.loads(self.budget_path.read_text())["reserved"], 353)
        self.assertEqual(self.kv.store[POINTER_KEY], old_pointer)
        _, resumed = self.publish(START + timedelta(days=2), list(reversed(self.symbols)))
        self.assertIsNotNone(resumed)
        self.assertEqual(resumed.record["pointer_state"], "READBACK_CONFIRMED")
        self.assertEqual(json.loads(self.budget_path.read_text())["reserved"], 51)

    def test_retry_crossing_midnight_reserves_every_remaining_slot_once_on_new_day(self):
        self.publish(START)
        candidate = self.evaluate(START + timedelta(days=1, seconds=-1), list(reversed(self.symbols)))
        original = self.kv.fake_run
        launch_days = []
        crossed = False

        def retry_on_new_day(*args, **kwargs):
            nonlocal crossed
            argv = args[0]
            if "put" in argv:
                launch_days.append(Clock.instant.date())
            if "put" in argv and not crossed:
                crossed = True
                self.kv.fail_put(argv[argv.index("put") + 1], 1, NETWORK)
                result = original(*args, **kwargs)
                Clock.instant = START + timedelta(days=1)
                remaining = sync.ACTIVE_WRITE_RESERVATION.parts["ranking"].remaining
                self.assertTrue(policy.DailyWriteBudget(self.budget_path).reserve(400 - remaining, Clock.instant))
                return result
            return original(*args, **kwargs)

        with mock.patch.object(self.kv, "fake_run", side_effect=retry_on_new_day):
            result = self.upload(candidate)
        self.assertEqual((result.exit, result.record["status"], result.record["pointer_state"]),
                         (0, "SUCCEEDED", "READBACK_CONFIRMED"))
        self.assertEqual((result.record["writes_attempted"], result.record["writes_reserved"]), (18, 101))
        self.assertEqual(launch_days.count(START.date()), 1)
        self.assertEqual(launch_days.count((START + timedelta(days=1)).date()), 17)
        self.assertEqual(json.loads(self.budget_path.read_text())["reserved"], 400)
        self.assertEqual(self.kv.puts[-1][0], POINTER_KEY)

    def test_discovery_crossing_midnight_reserves_only_the_current_utc_day(self):
        self.publish(START)
        (self.snapshots / carry.CONFIRMED_NAME).unlink()
        candidate = self.evaluate(START + timedelta(days=1, seconds=-1), list(reversed(self.symbols)))
        original = self.kv.fake_run
        crossed = False

        def discover_across_midnight(*args, **kwargs):
            nonlocal crossed
            argv = args[0]
            result = original(*args, **kwargs)
            if "get" in argv and argv[argv.index("get") + 1] == POINTER_KEY and not crossed:
                crossed = True
                Clock.instant = START + timedelta(days=1)
            return result

        with mock.patch.object(self.kv, "fake_run", side_effect=discover_across_midnight):
            result = self.upload(candidate)
        self.assertEqual((result.exit, result.record["writes_reserved"], result.record["writes_attempted"]), (0, 123, 41))
        self.assertEqual((json.loads(self.budget_path.read_text())["day"],
                          json.loads(self.budget_path.read_text())["reserved"]), ("2026-11-02", 51))

    def test_cli_selection_crossing_midnight_stops_before_any_remote_put_launch(self):
        self.publish(START)
        candidate = self.evaluate(START + timedelta(days=1, seconds=-1), list(reversed(self.symbols)))
        old_pointer = self.kv.store[POINTER_KEY]

        def select_cli_on_next_day():
            Clock.instant = START + timedelta(days=1)
            self.assertTrue(policy.DailyWriteBudget(self.budget_path).reserve(400, Clock.instant))
            return ["synthetic-cli"]

        mark = len(self.kv.puts)
        with mock.patch.object(sync, "_cli_command", side_effect=select_cli_on_next_day):
            stopped = run_sy(sync, self.kv, self.snapshots / candidate["run_id"], self.ledger, {},
                             seam="B", real_cli=True)
        self.assertEqual((stopped.exit, stopped.record["status"], stopped.record["retention_reason"]),
                         (0, "RETAINED_LAST_GOOD", "WRITE_BUDGET"))
        self.assertEqual((stopped.record["writes_attempted"], stopped.record["last_cli_attempts"],
                          stopped.record["last_cli_exit_code"]), (0, 0, None))
        self.assertEqual((len(self.kv.puts), self.kv.store[POINTER_KEY]), (mark, old_pointer))

    def test_pointer_rollover_denial_has_no_attempt_or_ack_and_requires_reconciliation(self):
        first, _ = self.publish(START)
        receipt_a = (self.snapshots / carry.CONFIRMED_NAME).read_bytes()
        old_pointer = self.kv.store[POINTER_KEY]
        candidate = self.evaluate(START + timedelta(days=1, seconds=-1), list(reversed(self.symbols)))
        objects = json.loads((self.snapshots / candidate["run_id"] / "objects.json").read_text())
        last_member = sorted(objects)[-1]
        original = self.kv.fake_run
        crossed = False

        def cross_after_object_readback(*args, **kwargs):
            nonlocal crossed
            argv = args[0]
            result = original(*args, **kwargs)
            if "get" in argv and argv[argv.index("get") + 1] == last_member and not crossed:
                crossed = True
                Clock.instant = START + timedelta(days=1)
                self.assertTrue(policy.DailyWriteBudget(self.budget_path).reserve(398, Clock.instant))
            return result

        mark = len(self.kv.puts)
        with mock.patch.object(self.kv, "fake_run", side_effect=cross_after_object_readback):
            stopped = self.upload(candidate)
        self.assertEqual((stopped.exit, stopped.record["status"], stopped.record["error_category"],
                          stopped.record["pointer_state"]), (1, "FAILED", "WRITE_BUDGET_UNAVAILABLE", "NOT_ATTEMPTED"))
        self.assertNotIn(POINTER_KEY, [key for key, _ in self.kv.puts[mark:]])
        self.assertEqual(self.kv.store[POINTER_KEY], old_pointer)
        self.assertEqual((self.snapshots / carry.CONFIRMED_NAME).read_bytes(), receipt_a)
        self.assertTrue(carry.pointer_ambiguous(self.snapshots))
        self.assertIsNone(carry.confirmed_snapshot(self.snapshots))
        mark = len(self.kv.puts)
        with mock.patch.object(subprocess, "run", self.kv.fake_run), \
                mock.patch.object(sync, "_cli_command", return_value=["synthetic-cli"]):
            reconciled = sync.reconcile_confirmed_snapshot(self.snapshots)
        self.assertEqual((reconciled["run_id"], len(self.kv.puts)), (first["run_id"], mark))
        self.assertFalse(carry.pointer_ambiguous(self.snapshots))

    def selected_upload(self, selected):
        pointer = json.loads(selected["pointer"])
        directory = self.snapshots / pointer["run_id"]
        directory.mkdir()
        (directory / "objects.json").write_text(publisher._dumps(selected["objects"]), encoding="utf-8")
        (directory / "pointer.raw.json").write_text(selected["pointer"], encoding="utf-8")
        return self.upload({"run_id": pointer["run_id"]})

    def test_exhausted_ranking_budget_still_publishes_fresh_market_without_candidate_b(self):
        import sealed_product_policy as products
        self.publish(START)
        candidate = self.evaluate(START + timedelta(hours=2), list(reversed(self.symbols)))
        directory = self.snapshots / candidate["run_id"]
        objects = json.loads((directory / "objects.json").read_bytes())
        pointer_text = (directory / "pointer.raw.json").read_text()
        previous = carry.confirmed_snapshot(self.snapshots)
        original_ranking = products.parts(previous["objects"], previous["pointer"])["lazy"][publisher.BOTTLENECK_V3_KEY]
        used = json.loads(self.budget_path.read_text())["reserved"]
        self.assertTrue(policy.DailyWriteBudget(self.budget_path).reserve(400 - used, Clock.instant))
        quote = publisher._dumps({"schema": "v213-quotes-v1", "generated_at": stamp(Clock.instant), "quotes": {}})
        selected = products.prepare_publication(self.snapshots, objects, pointer_text, Clock.instant,
            previous=previous, fresh_products={"v213:quotes:v1": quote})
        detail = products.parts(selected["objects"], json.loads(selected["pointer"]))
        self.assertEqual((selected["ranking_status"], detail["manifest"]["ranking_persisted_at"]), ("REUSED", stamp(START)))
        self.assertEqual(detail["lazy"][publisher.BOTTLENECK_V3_KEY], original_ranking)
        self.assertEqual(detail["lazy"]["v213:quotes:v1"], quote)
        result = self.selected_upload(selected)
        self.assertEqual((result.exit, result.record["pointer_state"]), (0, "READBACK_CONFIRMED"))
        self.assertEqual((result.record["ranking_writes_reserved"], result.record["market_writes_reserved"]), (0, 15))
        self.assertEqual(json.loads(self.budget_path.read_text())["reserved"], 400)
        served, _pointer = self.serving()
        self.assertEqual(served.decode(), original_ranking)

    def test_expired_market_members_are_removed_without_renewing_source_or_product_clock(self):
        import sealed_product_policy as products
        self.publish(START)
        previous = carry.confirmed_snapshot(self.snapshots)
        Clock.instant = START + timedelta(hours=2)
        quote = publisher._dumps({"schema": "v213-quotes-v1", "generated_at": stamp(Clock.instant), "quotes": {}})
        selected = products.prepare_publication(self.snapshots, previous["objects"], json.dumps(previous["pointer"]),
            Clock.instant, previous=previous, fresh_products={"v213:quotes:v1": quote}, confirmed_only=True)
        self.assertEqual(self.selected_upload(selected).exit, 0)
        previous = carry.confirmed_snapshot(self.snapshots)
        before = products.parts(previous["objects"], previous["pointer"])
        Clock.instant = START + timedelta(hours=8, seconds=1)
        selected = products.prepare_publication(self.snapshots, previous["objects"], json.dumps(previous["pointer"]),
            Clock.instant, previous=previous, fresh_products={}, confirmed_only=True)
        detail = products.parts(selected["objects"], json.loads(selected["pointer"]))
        self.assertNotIn("v213:quotes:v1", detail["manifest"]["objects"])
        self.assertNotIn("v213:options-coverage:v1", detail["manifest"]["objects"])
        self.assertEqual(detail["manifest"]["product_persisted_at"]["market"], stamp(START + timedelta(hours=2)))
        self.assertEqual(detail["core_run_id"], before["core_run_id"])
        self.assertEqual(detail["lazy"][publisher.BOTTLENECK_V3_KEY], before["lazy"][publisher.BOTTLENECK_V3_KEY])
        result = self.selected_upload(selected)
        self.assertEqual((result.exit, result.record["market_writes_attempted"]), (0, 0))

    def test_partial_two_partition_authorization_is_charged_even_without_a_put(self):
        market = policy.DailyWriteBudget(self.budget_path.with_name("market-kv-write-budget.json"),
                                        reserve=400)
        self.assertTrue(market.reserve(600, START))
        candidate = self.evaluate(START)
        result = self.upload(candidate)
        self.assertEqual((result.exit, result.record["error_category"], result.record["pointer_state"]),
                         (1, "BOOTSTRAP_REQUIRED", "NOT_ATTEMPTED"))
        self.assertEqual((result.record["ranking_writes_reserved"], result.record["market_writes_reserved"],
                          result.record["writes_reserved"], result.record["writes_attempted"]), (51, 0, 51, 0))
        self.assertEqual(json.loads(self.budget_path.read_bytes())["reserved"], 51)
        self.assertEqual(self.kv.puts, [])
        self.assertNotIn(POINTER_KEY, self.kv.store)
