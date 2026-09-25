"""Quotes and option observations: contract choice, labelled model delta, validation before sealing. No network."""
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


class ContractChoiceTests(unittest.TestCase):
    def test_nearest_two_sided_out_of_the_money_call(self):
        rows = [{"strike": 95, "bid": 8, "ask": 9}, {"strike": 110, "bid": 1.0, "ask": 1.2}, {"strike": 112, "bid": 0, "ask": 0.9},
                {"strike": 120, "bid": 0.4, "ask": 0.6}]
        self.assertEqual(builder.pick(rows, 100)["strike"], 110)
        self.assertIsNone(builder.pick([{"strike": 110, "bid": None, "ask": 1.0}], 100))

    def test_observation_fields_and_model_delta(self):
        delta = builder.bs_call_delta(100, 110, 30 / 365, 0.6)
        self.assertTrue(0.2 < delta < 0.4)
        self.assertIsNone(builder.bs_call_delta(100, 110, 30 / 365, None))
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        obs = builder.observation("SIVE", (datetime.now(timezone.utc) + timedelta(days=21)).date().isoformat(), 21, 36.0, 0.8, 3.8,
                                  delta=None, iv=None, oi=16, volume=None, currency="SEK", source="Nasdaq Nordic",
                                  provenance="https://api.nasdaq.com/x", rights="candidate_local_review", stamp=stamp)
        self.assertEqual((obs["mid"], obs["spread"], obs["multiplier"]), (2.3, 3.0, 100))
        self.assertIn("130%", obs["liquidity_warning"])


class SealingTests(unittest.TestCase):
    def test_invalid_observations_become_explicit_unavailability(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        good = builder.observation("NVDA", (now + timedelta(days=7)).date().isoformat(), 7, 200.0, 1.0, 1.2, delta=0.3, iv=0.5, oi=10,
                                   volume=5, currency="USD", source="Yahoo", provenance="https://finance.yahoo.com/x",
                                   rights="unadmitted_third_party", stamp=stamp)
        crossed = {**good, "bid": 2.0, "ask": 1.0}
        doc = {"schema": "v213-market-observations-v1", "generated_at": stamp,
               "quotes": {"NVDA": {"symbol": "NVDA", "price": 180.0}},
               "options": {"NVDA": {"weekly": good, "monthly": crossed}, "SIVE": {"weekly": {"unavailable": "無週期權"}}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            bodies = publisher.lazy_market_bodies(path, now)
            options = json.loads(bodies["v213:options:v1"])["options"]
            self.assertEqual(options["NVDA"]["weekly"]["strike"], 200.0)
            self.assertIn("未通過驗證", options["NVDA"]["monthly"]["unavailable"])
            self.assertEqual(options["SIVE"]["weekly"], {"unavailable": "無週期權"})
            self.assertEqual(json.loads(bodies["v213:quotes:v1"])["schema"], "v213-quotes-v1")
            self.assertEqual(publisher.lazy_market_bodies(path, now + timedelta(hours=6)), {})


if __name__ == "__main__":
    unittest.main()
