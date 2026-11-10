"""Stage1G CI regressions for N1/N2/N3/M2/M3/m1 with real publisher output."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_market_quotes_options as builder
import option_delta_side_model as side
import publish_sealed_snapshot as publisher
from tests.fixtures.stage1g_hv_seal import OUTPUT, produce_bridge
from validate_v213_market_products import validate_covered_call_cycle


class Stage1GTransportTests(unittest.TestCase):
    def test_exact_python_publisher_hv_fixture_and_coverage_parity(self):
        fresh = produce_bridge()
        self.assertEqual(fresh, json.loads(OUTPUT.read_text(encoding="utf-8")))
        body = json.loads(fresh["options_body"])
        paths = body["options"]["AAA"]
        cycle = paths["monthly"]
        self.assertEqual(cycle["historical_volatility"], "@")
        self.assertEqual(len(paths["_hv"]), len(publisher.STAGE1F_HISTORY_KEYS))
        expanded = publisher.expand_sealed_cycle(cycle, paths["_hv"])
        validate_covered_call_cycle(expanded, fresh["clock"], fresh["clock"], "monthly")
        observed = json.loads(fresh["coverage_body"])["observed"]
        self.assertEqual([(x["cycle_count"], x["ticker_key_count"]) for x in observed], [(1, 1)])
        # No shared record is not a missing history silently assumed to exist.
        self.assertEqual(publisher.expand_sealed_cycle(cycle).get("historical_volatility"), "@")

    def test_tick_rule_uses_decimal_and_never_reclamps_to_mid_half_tick(self):
        cases = [(.01, 1.35, 9., .68), (.30, .37, 9., .33),
                 (.31, .36, .335, .33), (.01, 1.24, 10., .62),
                 (.01, 2.5, .0565, .05), (.07, 2.5, .2717, .27)]
        for bid, ask, model, sell in cases:
            with self.subTest(bid=bid, ask=ask, model=model):
                limit = side.decimal_tick_limit(bid, ask, model, buy=False)
                self.assertEqual(limit, sell)
                self.assertEqual(Decimal(str(limit)) % Decimal(".01"), 0)
                max_tick = ((Decimal(str(bid)) + Decimal(str(ask))) / 2
                            / Decimal(".01")).to_integral_value(rounding="ROUND_FLOOR")
                self.assertLessEqual(Decimal(str(limit)) / Decimal(".01"), max_tick)

    def test_valid_empty_nasdaq_monthly_body_is_not_read_error(self):
        today = date(2026, 11, 2)
        stamp = "2026-11-02T15:00:00Z"
        empty = {"data": {"lastTrade": "LAST TRADE: $100.00 (AS OF NOV 2, 2026)",
                          "table": {"rows": None, "asOf": None}},
                 "message": "Options are not available for this symbol"}
        with patch.object(builder, "http_json", side_effect=[empty, empty]):
            result = builder.nasdaq_us_options("BRK-A", 100., today, stamp)
        self.assertIn("monthly", result)
        monthly = result["monthly"]
        self.assertIn("unavailable", monthly)
        self.assertNotIn("補查讀取失敗", monthly["unavailable"])
        self.assertNotIn("READ_ERROR", [row["status"] for row in result.health])
        self.assertIn("無期權鏈", monthly["unavailable"])


if __name__ == "__main__":
    unittest.main()
