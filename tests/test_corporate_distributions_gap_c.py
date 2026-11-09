"""GAP-C: completed shareholder distributions and price-history refusal (offline)."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

SEC = "https://www.sec.gov/Archives/edgar/data/67347/000110465926112870/tm2626618d1_8k.htm"
EVENT = "2026-10-01"


def distribution() -> dict:
    return {
        "target_market": "US", "target_symbol": "MOD", "kind": "DISTRIBUTION",
        "status": "CLOSED", "distribution_date": EVENT,
        "related_market": "US", "related_symbol": "THRM",
        "shares_per_share": 0.44619, "source_url": SEC,
        "source_date": EVENT, "review_by": None,
    }


class DistributionRegistryTest(unittest.TestCase):
    def test_seed_is_verified_and_merger_is_unchanged(self):
        import corporate_actions as m
        fixture = json.loads((ROOT / "tests/fixtures/gap-c-mod-sec-8k.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["distribution_record_date"], "2026-09-28")
        self.assertEqual(fixture["distribution_date"], EVENT)
        self.assertTrue(fixture["mod_shareholders_retain_mod_shares"])
        self.assertEqual(fixture["shares_per_mod_share"], 0.44619)
        self.assertEqual(fixture["source_url"], SEC)
        doc = m.load_actions(today=date(2026, 11, 8))
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(len(doc["entries"]), 2)
        mod = next(e for e in doc["entries"] if e["target_symbol"] == "MOD")
        self.assertEqual({k: mod[k] for k in distribution()}, distribution())
        self.assertEqual(mod["flags"], [])
        self.assertNotIn("MOD", m.pending_targets(doc))
        self.assertNotIn("MOD", m.pending_acquirers(doc))
        self.assertEqual(m.pending_targets(doc)["LITE"]["acquirer_symbol"], "MRVL")
        self.assertEqual(m.acquirer_note(m.pending_acquirers(doc)["MRVL"]), {
            "target_symbol": "LITE", "acquirer_symbol": "MRVL", "kind": "ALL_STOCK",
            "exchange_ratio": 4.5, "cash_per_share": None, "currency": None,
            "expected_close": "first half of calendar year 2028",
            "source_url": "https://www.sec.gov/Archives/edgar/data/0001633978/000119312526442758/d163169dex991.htm",
        })

    def test_bad_distribution_fail_closed(self):
        import corporate_actions as m
        def validate(d):
            return m.load_actions_bytes(json.dumps({"schema_version": 1, "entries": [d]}).encode(), today=date(2026, 11, 8))
        self.assertEqual(validate(distribution())["entries"][0]["shares_per_share"], 0.44619)
        for label, updates in (
            ("zero", {"shares_per_share": 0}), ("negative", {"shares_per_share": -0.1}),
            ("bool", {"shares_per_share": True}), ("unbounded", {"shares_per_share": 1e100}),
            ("missing day", {"distribution_date": None}), ("invalid day", {"distribution_date": "2026-10-32"}),
            ("wrong URL", {"source_url": "https://example.com/Archives/x"}),
            ("sec host injection", {"source_url": "https://www.sec.gov.evil.test/Archives/x"}),
            ("pending", {"status": "PENDING"}), ("terminated", {"status": "TERMINATED"}),
            ("wrong market", {"related_market": "JP"}),
            ("bad related", {"related_symbol": "../../X"}),
            ("bad chronology", {"source_date": "2026-09-30"}),
            ("bad review", {"review_by": "2026-09-30"}),
            ("unknown", {"cash_per_share": 10}),
            ("self", {"related_symbol": "MOD"}),
        ):
            with self.subTest(label=label):
                obj = distribution()
                obj.update(updates)
                with self.assertRaises((ValueError, KeyError)):
                    validate(obj)
        obj = distribution()
        del obj["distribution_date"]
        with self.assertRaises((ValueError, KeyError)):
            validate(obj)
        with self.assertRaises(ValueError):
            m.load_actions_bytes(json.dumps({"schema_version": 1, "entries": [distribution(), distribution()]}).encode(), today=date(2026, 11, 8))

    def test_returns_span_event_null_with_explicit_reason_and_after_window_recover(self):
        import bottleneck_top20_v3 as m
        import distribution_adjusted_returns as entitlement
        event = distribution()
        def market(day):
            return {
                "asof": day, "ret_6m": 0.2, "ret_1y": 0.3, "cagr_2y": 0.4,
                "cagr_listed": None, "long_term_basis": "TWO_YEAR",
            }
        crossed = entitlement.suppress_unproven_distribution_returns(market("2026-11-08"), [event])
        for key in ("ret_6m", "ret_1y", "cagr_2y"):
            self.assertIsNone(crossed[key], key)
            self.assertEqual(crossed["return_reasons"][key], "DISTRIBUTION_IN_WINDOW")
        self.assertEqual(crossed["long_term_basis"], "UNAVAILABLE")
        self.assertEqual(m.long_term_gate(crossed), (None, ["DISTRIBUTION_IN_WINDOW"]))
        # Jan 2027 still crosses all three; May 2027 no longer crosses the 182-day window.
        after_six = entitlement.suppress_unproven_distribution_returns(market("2027-05-01"), [event])
        self.assertEqual(after_six["ret_6m"], 0.2)
        self.assertEqual(after_six["return_reasons"], {"ret_1y": "DISTRIBUTION_IN_WINDOW", "cagr_2y": "DISTRIBUTION_IN_WINDOW"})
        self.assertEqual(entitlement.suppress_unproven_distribution_returns(market("2026-09-30"), [event])["cagr_2y"], 0.4)
        self.assertEqual(entitlement.suppress_unproven_distribution_returns(market("2029-01-01"), [event])["cagr_2y"], 0.4)
        self.assertNotIn("return_reasons", entitlement.suppress_unproven_distribution_returns(market("2026-11-08"), []))

    def test_scoring_refuses_mod_but_preserves_pending_lite_and_mrvl(self):
        import bottleneck_top20_v3 as m
        layer = {
            "id": "cooling_power_train", "name_zh": "散熱", "chain": "datacenter", "chain_rank": 3,
            "leopold_constraint": "x", "filing_terms": [],
            "capturers": [{"symbol": t, "role": "x", "source_url": SEC, "source_date": EVENT}
                          for t in ("MOD", "LITE", "MRVL")],
        }
        # No disk/HTTP capture or host writes; mock only data inputs.
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            layers = Path(tmp) / "layers.json"
            layers.write_text(json.dumps({"layers": [layer]}), encoding="utf-8")
            def market(symbol, *args, **kwargs):
                return {"name": symbol, "symbol": symbol,
                        "market": {"source": "Yahoo Finance adjusted daily close (unofficial)",
                                   "source_url": "https://finance.yahoo.com/quote/" + symbol,
                                   "asof": "2026-11-06", "market_cap": 20e9, "currency": "USD",
                                   "ret_6m": 0.8, "ret_1y": 0.3, "cagr_2y": 0.2,
                                   "long_term_basis": "TWO_YEAR", "cagr_listed": None}}
            with patch.multiple(
                    m, LAYERS=layers, SERENITY=Path(tmp) / "nones", LEOPOLD=Path(tmp) / "nonel",
                    yahoo_data=market, cik_index=lambda captured=None: {},
                    taiwan_monthly_revenue=lambda *a: {},
                    cision_interim_revenue=lambda *a, **k: {},
                    nasdaq_consensus=lambda *a, **k: None), \
                 patch.object(m.listing_lineage, "load", return_value={}):
                doc = m.build(None, datetime(2026, 11, 8, tzinfo=timezone.utc), with_news=False)
        excluded = {row["symbol"]: row for row in doc["excluded"]}
        self.assertIn("DISTRIBUTION_IN_WINDOW", excluded["MOD"]["reasons"])
        self.assertIn("DEAL_PENDING_TARGET", excluded["LITE"]["reasons"])
        mrvl = next(row for row in doc["top"] if row["symbol"] == "MRVL")
        self.assertEqual(mrvl["corporate_action"]["exchange_ratio"], 4.5)
        self.assertNotIn("corporate_action", excluded["MOD"])


if __name__ == "__main__":
    unittest.main()
