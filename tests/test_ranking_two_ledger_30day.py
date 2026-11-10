"""CI-run 720-hour real seal/readback over independent ranking and product ledgers.

This uses actual publisher, confirmed-only product builder, sync and pointer-last
FakeKV transport, not a single-ledger policy-only model or live provider writes.
"""
from __future__ import annotations

import json
import unittest
from collections import defaultdict
from datetime import timedelta
from unittest import mock

import publish_sealed_snapshot as publisher
import ranking_confirmed_heartbeat as heartbeat
import ranking_write_policy as budget
import sealed_product_policy as products
import top20_carry_forward as carry
from test_ranking_sealed_quota_integration import Clock, SealedQuotaIntegration, START, stamp


class RealSealedTwoLedgerMonthTests(unittest.TestCase):
    def test_thirty_days_hourly_real_seals_both_ledgers_and_utc_resume(self):
        h = SealedQuotaIntegration()
        h.setUp()
        self.addCleanup(h.doCleanups)
        self.addCleanup(h.tearDown)
        h.identity_count = 60
        first, sent = h.publish(START)
        self.assertEqual(sent.exit, 0)
        self.assertEqual(len(json.loads(h.serving()[0])["top"]), 20)
        market_path = h.budget_path.with_name("market-kv-write-budget.json")
        daily_actual, source_states = defaultdict(int), []
        held_order = None
        total_publications = 1
        for hour in range(1, 720):
            now = START + timedelta(hours=hour)
            Clock.instant = now
            order_offset = 17 if hour in (23, 24) else (hour // 9) % len(h.symbols)
            symbols = h.symbols[order_offset:] + h.symbols[:order_offset]

            # Exhaust ranking only on hour 23. Market can still use its own
            # reserve and the withheld changed order must resume after UTC 00.
            if hour == 23:
                rank_state = json.loads(h.budget_path.read_text(encoding="utf-8"))
                self.assertEqual(rank_state["day"], "2026-11-01")
                room = 400 - rank_state["reserved"]
                self.assertGreaterEqual(room, 0)
                self.assertTrue(budget.DailyWriteBudget(h.budget_path).reserve(room, now))

            candidate = h.evaluate(now, symbols)
            if candidate.get("status") != "RETAINED_LAST_GOOD":
                uploaded = h.upload(candidate)
                self.assertEqual(uploaded.exit, 0, uploaded.outcome)
                daily_actual[now.date().isoformat()] += uploaded.record["writes_attempted"]
                total_publications += int(uploaded.record["status"] == "SUCCEEDED")
            else:
                # Actual confirmed-seal path with synthetically fresh, healthy
                # market/price/identity sources. No new ranking producer.
                at = stamp(now)
                identity = {f"v213:identity:v2:sym:{key}": json.dumps({
                    "generated_at": at, "synthetic": key}, separators=(",", ":"))
                    for key in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"}
                identity.update({f"v213:identity:v2:name:{n}": json.dumps({
                    "generated_at": at, "synthetic": n}, separators=(",", ":")) for n in range(16)})
                identity.update({f"v213:identity:v2:tok:{n}": json.dumps({
                    "generated_at": at, "synthetic": n}, separators=(",", ":")) for n in range(8)})
                price = {f"v213:prices:v1:{market}": json.dumps({
                    "generated_at": at, "market": market}, separators=(",", ":"))
                    for market in ("US", "TAIWAN", "SWEDEN", "EUROPE", "JAPAN", "KOREA")}
                market = {key: json.dumps({"generated_at": at, "synthetic": key}, separators=(",", ":"))
                          for key in ("v213:quotes:v1", "v213:options:v2")}
                coverage = {"v213:options-coverage:v1": json.dumps({
                    "generated_at": at, "synthetic": "coverage"}, separators=(",", ":"))}
                with mock.patch.object(publisher, "lazy_identity_bodies", return_value=identity), \
                        mock.patch.object(publisher, "lazy_price_bodies", return_value=price), \
                        mock.patch.object(publisher, "lazy_market_bodies", return_value=market), \
                        mock.patch.object(publisher, "lazy_options_coverage_body", return_value=coverage):
                    selected = heartbeat.stage(h.snapshots, now, products_only=True,
                                               product_paths={kind: h.tmp / "no-input" / kind
                                                              for kind in ("market", "prices", "identity")})
                if selected.get("status") != "RETAINED_LAST_GOOD":
                    self.assertEqual(selected["ranking_status"], "REUSED")
                    uploaded = h.upload(selected)
                    self.assertEqual(uploaded.exit, 0, uploaded.outcome)
                    self.assertEqual(uploaded.record["ranking_writes_reserved"], 0)
                    daily_actual[now.date().isoformat()] += uploaded.record["writes_attempted"]
                    total_publications += int(uploaded.record["status"] == "SUCCEEDED")

            body, pointer = h.serving()
            document = json.loads(body)
            self.assertEqual(len(document["top"]), 20)
            actual_order = [r["symbol"] for r in document["top"]]
            source_states.append((hour, pointer["run_id"], actual_order, stamp(now)))
            for path, cap in ((h.budget_path, 400), (market_path, 600)):
                if path.exists():
                    rec = json.loads(path.read_text(encoding="utf-8"))
                    if rec["day"] == now.date().isoformat():
                        self.assertLessEqual(rec["reserved"], cap, (hour, path.name, rec))
            if hour == 23:
                self.assertNotEqual(actual_order, symbols)  # changed ranking withheld
                held_order = actual_order
            if hour == 24:
                self.assertIsNotNone(held_order)
                self.assertEqual(actual_order, symbols)  # auto-resume after reset
                self.assertNotEqual(actual_order, held_order)
                self.assertEqual(json.loads(h.budget_path.read_text())["day"], "2026-11-02")
        self.assertEqual(len(source_states) + 1, 720)
        self.assertEqual(len(daily_actual), 30)
        self.assertGreater(total_publications, 30)
        self.assertLessEqual(max(daily_actual.values()), 1000)
        self.assertTrue(all(day in daily_actual for day in
                            ((START + timedelta(days=i)).date().isoformat() for i in range(30))))
        self.assertIn("snapshot:current", h.kv.store)
        self.assertEqual(len(json.loads(h.serving()[0])["top"]), 20)


if __name__ == "__main__":
    unittest.main()
