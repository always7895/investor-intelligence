"""Offline real publisher/seal/blob-reuse/sync transactions, never a quota-only simulator."""
from __future__ import annotations

import contextlib
import copy
import json
import subprocess
import sys
from collections import defaultdict
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
            bodies["v213:top20-report:latest"] = json.dumps(report, separators=(",", ":"))
            run = now.strftime("%Y%m%dT%H%M%SZ") + "-" + publisher._sha(bodies["v213:top20-report:latest"])[:12]
            return bodies, {"run_id": run, "transaction_id": "0" * 32, "report": report, "top20": report}

        identities = {f"v213:identity:v2:sym:X{index}": json.dumps({"synthetic_identity": index})
                      for index in range(self.identity_count)}
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
        self.assertEqual(uploaded.record["objects_reused"], 24)
        self.assertEqual(uploaded.record["writes_reserved"], (15 + 1 + 1) * 3)
        self.assertEqual(uploaded.record["objects_verified"], 40)
        self.assertEqual(self.kv.puts[-1][0], POINTER_KEY)

    def test_whole_plan_budget_stop_has_zero_puts_and_resumes_at_utc_reset(self):
        first, _ = self.publish(START)
        budget = policy.DailyWriteBudget(self.budget_path)
        self.assertTrue(budget.reserve(400 - 123 - 50, START))
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
        self.assertEqual(retried.record["writes_attempted"], 18)
        self.assertEqual(retried.record["writes_reserved"], 51)
        self.assertEqual(json.loads(self.budget_path.read_text())["reserved"], 174)
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
        self.identity_count = 140
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

    def test_thirty_days_hourly_real_seals_keep_top20_and_daily_writes_bounded(self):
        attempted = defaultdict(int)
        reserved = defaultdict(int)
        retained = 0
        resets = 0
        for hour in range(30 * 24):
            now = START + timedelta(hours=hour)
            # Ordinary changes about every nine hours; several busy market days
            # also change hourly in the evening and exercise actual budget stops.
            generation = hour // 9 + (hour % 24 if hour // 24 % 5 == 0 and hour % 24 >= 18 else 0)
            shift = generation % 20
            symbols = self.symbols[shift:] + self.symbols[:shift]
            before = len(self.kv.puts)
            summary, result = self.publish(now, symbols)
            attempted[now.date()] += len(self.kv.puts) - before
            if result is not None:
                reserved[now.date()] += result.record["writes_reserved"]
                self.assertLessEqual(result.record["writes_attempted"], result.record["writes_reserved"])
            else:
                retained += 1
                self.assertEqual(summary["pointer_state"], "NOT_ATTEMPTED")
            body, pointer = self.serving()
            self.assertTrue(body)
            self.assertEqual(json.loads(self.kv.store[f"snapshot:{pointer['run_id']}:{publisher.SEAL_KEY}"])["run_id"], pointer["run_id"])
            self.assertLessEqual(attempted[now.date()], 400)
            self.assertLessEqual(reserved[now.date()], 400)
            if hour and hour % 24 == 0:
                resets += 1
                self.assertNotEqual(summary.get("retention_reason"), "WRITE_BUDGET")  # automatic reset, even if not yet due
        self.assertEqual((len(attempted), resets), (30, 29))
        self.assertGreater(retained, 500)
        self.assertEqual(len(reserved), 30)
        print("RANKING_KV_30_DAY_EVIDENCE " + json.dumps({
            "served_hours": 30 * 24, "utc_resets": resets, "retained_hours": retained,
            "days": [{"utc_day": day.isoformat(), "put_attempts": attempted[day], "reserved_worst_case": reserved[day]}
                     for day in sorted(attempted)]}, separators=(",", ":")))
