"""Synthetic cadence/quota boundaries: no network, secrets, installed or remote writes."""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ranking_write_policy as policy
import bottleneck_top20_v3 as ranking
import revenue_guidance_overlay as overlay
import top20_rotation_provenance as rotation

START = datetime(2026, 11, 9, tzinfo=timezone.utc)
KEY = b"synthetic-policy-boundary-key-not-a-secret-1234"


def candidate(moment=START, *, reverse=False):
    symbols = [f"T{index}" for index in range(10)]
    if reverse:
        symbols.reverse()
    return {"generated_at": moment.isoformat().replace("+00:00", "Z"),
            "top": [{"symbol": symbol, "rank": index + 1, "score": 50, "layer": "test"}
                    for index, symbol in enumerate(symbols)], "industries": [], "excluded": [],
            "candidate_fingerprints": [{"symbol": symbol, **{name: rotation.digest([name, symbol])
                for name in rotation.INPUT_FAMILIES}} for symbol in sorted(symbols)]}


class CadencePolicy(unittest.TestCase):
    def test_digest_accepts_raw_sealed_legacy_and_commits_order_only(self):
        raw = candidate()
        legacy = {"records": [{"ticker": row["symbol"], "score": 1} for row in raw["top"]]}
        self.assertEqual(policy.ordered_rank_digest(raw), policy.ordered_rank_digest(legacy))
        changed = copy.deepcopy(raw)
        changed["top"][0]["score"] = 99
        changed["input_context"] = {"filings": "different"}
        self.assertEqual(policy.ordered_rank_digest(raw), policy.ordered_rank_digest(changed))
        self.assertNotEqual(policy.ordered_rank_digest(raw), policy.ordered_rank_digest(candidate(reverse=True)))
        for rows in (raw["top"][:9], raw["top"] * 2, raw["top"] + raw["top"] + raw["top"][:1]):
            with self.assertRaisesRegex(ValueError, "RANKING_TOP_INVALID"):
                policy.ordered_rank_digest({"top": rows})

    def test_heartbeat_exact_boundary_and_future_clock_rejected(self):
        previous = candidate()
        self.assertEqual(policy.publication_due(None, previous, START), "INITIAL")
        for seconds, expected in ((1, "NO_CHANGE"), (21599, "NO_CHANGE"), (21600, "HEARTBEAT"), (21601, "HEARTBEAT")):
            now = START + timedelta(seconds=seconds)
            self.assertEqual(policy.publication_due(previous, candidate(now), now), expected)
        self.assertEqual(policy.publication_due(previous, candidate(START, reverse=True), START), "CHANGED")
        with self.assertRaisesRegex(ValueError, "RANKING_CLOCK_FUTURE"):
            policy.publication_due(None, candidate(START + timedelta(seconds=1)), START)
        with self.assertRaisesRegex(ValueError, "RANKING_CLOCK_FUTURE"):
            policy.publication_due(candidate(START + timedelta(seconds=1)), candidate(), START)
        with self.assertRaisesRegex(ValueError, "RANKING_CLOCK_INVALID"):
            policy.publication_due(None, candidate(), START.replace(tzinfo=None))

    def test_cli_source_only_evaluation_does_not_touch_cache_or_journal(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "ranking.json"
            previous = candidate()
            original = json.dumps(previous).encode()
            output.write_bytes(original)
            moment = START + timedelta(hours=1)
            evaluated = candidate(moment)
            evaluated["top"][0]["score"] = 75
            evaluated["input_context"] = {"prices": "new-source"}
            with patch.object(ranking, "utc_now", return_value=moment), patch.object(
                    ranking, "sec_fetch_factory", return_value=None), patch.object(
                    ranking, "build", return_value=evaluated), patch.object(
                    rotation, "append_if_configured") as append, redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(ranking.main(["--output", str(output), "--no-news"]), 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "SKIPPED_NO_CHANGE")
            append.assert_not_called()
            self.assertEqual(output.read_bytes(), original)
            self.assertFalse(output.with_name(output.name + ".tmp").exists())

    def test_last_output_uses_admitted_digests_and_keeps_historical_clock(self):
        raw = candidate()
        record = {"schema": "guidance-local-completion-v1", "ranking_sha256": "a" * 64,
                  "output_sha256": "b" * 64, "cutoff": raw["generated_at"]}
        def read(kind, sha):
            return json.dumps(record if kind == "record" else raw if kind == "rank" else {"sealed": True}).encode()
        outputs = SimpleNamespace(_ledger=lambda: {"entries": ["c" * 64]},
            _output_json=overlay.B1Outputs._output_json, read=Mock(side_effect=read))
        self.assertEqual(overlay.B1Outputs.latest_ranking(outputs), raw)
        self.assertEqual(outputs.read.call_args_list[0].args, ("record", "c" * 64))
        self.assertEqual(outputs.read.call_args_list[1].args, ("rank", "a" * 64))
        self.assertEqual(outputs.read.call_args_list[2].args, ("body", "b" * 64))
        outputs._ledger = lambda: {"entries": []}
        outputs.read.reset_mock()
        self.assertIsNone(overlay.B1Outputs.latest_ranking(outputs))
        outputs.read.assert_not_called()

    def test_host_suppression_keeps_pending_and_does_not_create_witness(self):
        import revenue_guidance_host as host
        import publish_sealed_snapshot as publisher
        moment = START + timedelta(hours=1)
        rev = "gir1:" + "a" * 64
        state = {"Intent": None, "StateRequired": True, "InputRevision": rev, "PendingRevision": rev}
        snapshot = SimpleNamespace(symbols=lambda: [row["symbol"] for row in candidate()["top"]])
        old_witness = object()  # A new evaluation must invalidate any historical live proof.
        session = SimpleNamespace(phase="idle", guard=object(), witness=old_witness, machine_enabled=False,
            lease=SimpleNamespace(read_journal=Mock(return_value=SimpleNamespace(state=state))),
            input_revision=Mock(return_value=rev), snapshot=Mock(return_value=snapshot), remaining=Mock())
        outputs = SimpleNamespace(latest_ranking=Mock(return_value=candidate()), publish=Mock())
        captured = Mock()
        captured.collect.return_value = moment.date()
        evaluated = candidate(moment)
        evaluated["input_context"] = {"prices": "new-unconsumed-input"}
        with patch.object(host, "_Capture", return_value=captured), patch.object(host, "now", return_value=moment), patch.object(
                host.overlay, "B1Store"), patch.object(host.overlay, "B1Outputs", return_value=outputs), patch.object(
                host.revision, "compute_input_revision", return_value=rev), patch.object(ranking, "build", return_value=evaluated), patch.object(
                publisher, "ForecastConsumption") as consume, patch.object(rotation, "append_if_configured") as append:
            result = host._Session.rank(session, {"Mode": "Dirty", "Revision": rev})
        self.assertFalse(result["Completed"])
        self.assertTrue(result["PublicationSuppressed"])
        self.assertTrue(result["ServingLastGood"])
        self.assertEqual(state["PendingRevision"], rev)
        self.assertIsNone(session.witness)
        self.assertEqual(session.phase, "idle")
        consume.assert_not_called()
        append.assert_not_called()
        outputs.publish.assert_not_called()


class QuotaPolicy(unittest.TestCase):
    def test_missing_read_only_preflight_does_not_initialize_anything(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "not-created" / "budget.json"
            budget = policy.DailyWriteBudget(path)
            self.assertEqual(budget.allowance, 400)
            self.assertTrue(budget.can_reserve(400, START))
            self.assertFalse(budget.can_reserve(401, START))
            self.assertFalse(path.parent.exists())

    def test_whole_transaction_reservation_daily_reset_and_no_refund(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "budget.json"
            budget = policy.DailyWriteBudget(path)
            self.assertTrue(budget.reserve(396, START))
            original = path.read_bytes()
            self.assertFalse(budget.reserve(8, START + timedelta(hours=23)))
            self.assertEqual(path.read_bytes(), original)
            self.assertTrue(policy.DailyWriteBudget(path).reserve(4, START + timedelta(hours=23)))
            self.assertFalse(budget.reserve(1, START + timedelta(hours=23, minutes=59, seconds=59)))
            self.assertTrue(budget.reserve(400, START + timedelta(days=1)))
            self.assertEqual(json.loads(path.read_bytes())["reserved"], 400)
            self.assertFalse(budget.reserve(1, START))  # Never reset backwards on clock rollback.

    def test_quota_stop_resumes_automatically_at_utc_not_local_midnight(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "budget.json"
            budget = policy.DailyWriteBudget(path)
            self.assertTrue(budget.reserve(8, START))
            budget.stop_until_reset(START)
            restarted = policy.DailyWriteBudget(path)
            self.assertFalse(restarted.can_reserve(1, START + timedelta(hours=23)))
            self.assertFalse(restarted.reserve(1, START + timedelta(hours=23)))
            utc_midnight = datetime(2026, 11, 10, 8, tzinfo=timezone(timedelta(hours=8)))
            self.assertTrue(restarted.reserve(8, utc_midnight))
            self.assertEqual(json.loads(path.read_bytes())["day"], "2026-11-10")

    def test_corrupt_busy_or_failed_durability_never_authorizes_remote_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "budget.json"
            budget = policy.DailyWriteBudget(path)
            self.assertTrue(budget.reserve(8, START))
            original = path.read_bytes()
            with policy._locked(path.with_name(path.name + ".lock")):
                self.assertFalse(budget.can_reserve(8, START))
                self.assertFalse(budget.reserve(8, START))
            self.assertEqual(path.read_bytes(), original)
            with patch.object(budget, "_save", side_effect=OSError("synthetic-disk-failure")):
                self.assertFalse(budget.reserve(8, START))
            path.write_text('{"schema":"unknown"}', encoding="utf-8")
            self.assertFalse(budget.reserve(8, START + timedelta(days=1)))
            self.assertFalse(budget.can_reserve(8, START + timedelta(days=1)))

    def test_thirty_days_hourly_serving_budget_reset_and_bounded_journal(self):
        with tempfile.TemporaryDirectory() as td, patch.object(rotation, "MAX_SEGMENT_BYTES", 32 * 1024):
            journal = Path(td) / "shadow.jsonl"
            budget = policy.DailyWriteBudget(Path(td) / "budget.json")
            last_good = None
            attempts_by_day = {}
            suppressed = 0
            resumed_days = set()
            served = 0
            for hour in range(30 * 24):
                moment = START + timedelta(hours=hour)
                day = moment.date().isoformat()
                attempts_by_day.setdefault(day, 0)
                # Realistic ordered-membership change every 13h; prices change hourly.
                evaluated = candidate(moment, reverse=bool((hour // 13) % 2))
                evaluated["input_context"] = {"prices": hour}
                if hour == 3 * 24:
                    self.assertTrue(budget.reserve(400, moment))
                    attempts_by_day[day] += 400  # Synthetic prior ranking-path attempts.
                if hour == 8 * 24 + 8:
                    budget.stop_until_reset(moment)  # Provider daily quota response, no retry storm.
                due = policy.publication_due(last_good, evaluated, moment)
                if due != "NO_CHANGE":
                    worst_case = 16  # Three immutable puts + pointer, four attempts each.
                    if budget.reserve(worst_case, moment):
                        attempts_by_day[day] += worst_case
                        rotation.append_signed(journal, evaluated, key=KEY, asof=evaluated["generated_at"])
                        last_good = evaluated
                        if hour // 24 in (4, 9):
                            resumed_days.add(hour // 24)
                    else:
                        suppressed += 1
                self.assertIsNotNone(last_good)
                self.assertEqual(len(last_good["top"]), 10)
                self.assertEqual(len({row["symbol"] for row in last_good["top"]}), 10)
                self.assertLessEqual(attempts_by_day[day], 400)
                self.assertLessEqual(len(rotation._segments(journal)), rotation.MAX_RETAINED_SEGMENTS)
                served += 1
            self.assertEqual(served, 720)
            self.assertGreater(suppressed, 0)
            self.assertEqual(resumed_days, {4, 9})
            self.assertEqual(len(attempts_by_day), 30)
            self.assertTrue(journal.with_name(journal.name + ".checkpoint").exists())
            self.assertLessEqual(sum(item.stat().st_size for item in Path(td).iterdir()),
                rotation.MAX_RETAINED_SEGMENTS * rotation.MAX_SEGMENT_BYTES + rotation.MAX_RECORD_BYTES + 16384)


if __name__ == "__main__":
    unittest.main()
