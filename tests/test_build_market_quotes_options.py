"""Covered-call suggestions: strike choice (as high as possible while the premium is worth collecting), sell limit,
derived yields, validation before sealing. No network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
from validate_v213_market_products import MarketProductValidationError, validate_covered_call_cycle  # noqa: E402


def row(strike, bid, ask, delta=None):
    return {"strike": strike, "bid": bid, "ask": ask, "delta": delta, "iv": None, "oi": 10, "volume": 1}


class SuggestionTests(unittest.TestCase):
    def test_highest_strike_worth_selling_then_a_balanced_one(self):
        spot, dte = 100.0, 30
        rows = [row(95, 7, 7.2, 0.7), row(105, 2.0, 2.1, 0.33), row(110, 1.0, 1.05, 0.2), row(115, 0.6, 0.65, 0.15),
                row(125, 0.3, 0.35, 0.08), row(140, 0.05, 0.1, 0.02), row(150, 0.4, 5.0, 0.01)]
        suggestions = builder.covered_call_suggestions(rows, spot, dte)
        # 125 pays 0.30 on the bid = 3.65% annualized < 6%; 115 pays 7.3% with delta 0.15 -> highest qualifying strike.
        self.assertEqual([s["role"] for s in suggestions], ["HIGH_STRIKE", "BALANCED"])
        self.assertEqual(suggestions[0]["strike"], 115)
        self.assertEqual(suggestions[1]["strike"], 105)  # delta nearest 0.30 below the first strike
        self.assertEqual(suggestions[0]["limit_price"], 0.62)  # mid 0.625 rounded down to the tick
        self.assertAlmostEqual(suggestions[0]["annualized_yield"], 0.62 / 100 * 365 / 30, places=6)

    def test_wide_spread_moves_the_limit_towards_the_bid_and_untradeable_quotes_are_ignored(self):
        suggestions = builder.covered_call_suggestions([row(120, 1.0, 1.6)], 100.0, 20)
        self.assertEqual(suggestions[0]["limit_price"], 1.15)  # spread 46% of mid -> bid + a quarter of the spread
        self.assertEqual(builder.covered_call_suggestions([row(120, 0.2, 2.0)], 100.0, 20), [])  # spread > mid

    def test_no_qualifying_strike_gives_an_explicit_reason(self):
        result = builder.cycle_result("X", "2026-10-23", 27, 100.0, [row(150, 0.01, 0.02, 0.01)], currency="USD", source="s",
                                      provenance="https://example.com", rights="unadmitted_third_party", stamp="2026-09-26T00:00:00Z")
        self.assertIn("unavailable", result)


class UniverseTests(unittest.TestCase):
    def test_carried_top20_tickers_join_the_universe_despite_the_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            lkg = Path(tmp)
            bundle = {"payloads": {"top20_json": json.dumps([{"ticker": "PATH"}, {"ticker": "AFRM"}])}}
            (lkg / "20260926T010000Z-0123456789ab.json").write_text(json.dumps(bundle), encoding="utf-8")
            (lkg / "refresh-state.json").write_text("{}", encoding="utf-8")
            saved = (builder.TOP20, builder.V3, builder.LAYERS)
            builder.TOP20, builder.V3, builder.LAYERS = lkg, lkg / "absent.json", lkg / "absent.json"
            try:
                self.assertEqual(builder.universe(), ["PATH", "AFRM"])
            finally:
                builder.TOP20, builder.V3, builder.LAYERS = saved


class SealingTests(unittest.TestCase):
    def cycle(self, now):
        expiry = (now + timedelta(days=27)).date().isoformat()
        return builder.cycle_result("NVDA", expiry, 27, 225.0, [row(245, 1.5, 1.55, 0.17), row(235, 3.65, 3.8, 0.33)], currency="USD",
                                    source="Yahoo", provenance="https://finance.yahoo.com/x", rights="unadmitted_third_party",
                                    stamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_validator_and_sealing(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        good = self.cycle(now)
        validate_covered_call_cycle(good, evaluated_at=stamp)
        tampered = json.loads(json.dumps(good))
        tampered["suggestions"][0]["limit_price"] = 9.0
        with self.assertRaises(MarketProductValidationError):
            validate_covered_call_cycle(tampered, evaluated_at=stamp)
        doc = {"schema": "v213-market-observations-v2", "generated_at": stamp, "quotes": {"NVDA": {"symbol": "NVDA", "price": 225.0}},
               "options": {"NVDA": {"monthly": good, "weekly": tampered}, "SIVE": {"weekly": {"unavailable": "無週期權"}}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            bodies = publisher.lazy_market_bodies(path, now)
            options = json.loads(bodies["v213:options:v2"])
            self.assertEqual(options["schema"], "v213-options-v2")
            self.assertEqual(options["options"]["NVDA"]["monthly"]["suggestions"][0]["strike"], 245)
            self.assertIn("未通過驗證", options["options"]["NVDA"]["weekly"]["unavailable"])
            self.assertEqual(publisher.lazy_market_bodies(path, now + timedelta(hours=6)), {})


if __name__ == "__main__":
    unittest.main()
