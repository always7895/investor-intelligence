from __future__ import annotations

import json
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from score_stocks import (  # noqa: E402
    calculate_long_term_suitability,
    calculate_total_score,
    load_watchlist,
    normalized_debt_to_equity,
)


class ScoringTests(unittest.TestCase):
    def ideal_data(self) -> dict:
        return {
            "ticker": "IDEAL",
            "name": "Ideal Corp",
            "current_price": 100,
            "market_cap": 2_000_000_000,
            "revenue_ttm": 2_000_000_000,
            "revenue_growth": 1.00,
            "forward_pe": 20,
            "ps_ratio": 4,
            "gross_margin": 0.75,
            "operating_margin": 0.20,
            "profit_margin": 0.25,
            "free_cash_flow": 150_000_000,
            "total_cash": 500_000_000,
            "total_debt": 100_000_000,
            "debt_to_equity": 20,
            "beta": 1.2,
            "short_pct_float": 0.05,
            "num_analysts": 3,
            "institutional_pct": 0.20,
            "atm_dilution_pct": 0.01,
            "sbc_revenue_pct": 0.05,
            "largest_customer_revenue_pct": 0.20,
        }

    def ideal_metadata(self) -> dict:
        return {
            "ticker": "IDEAL",
            "category": "InP Substrate",
            "source": "both",
            "demand_primary_evidence": ["demand-1", "demand-2"],
            "implementation_stage": "shipping",
            "bottleneck_evidence_level": "primary_verified",
            "bottleneck_primary_evidence": ["constraint-1", "constraint-2"],
            "pricing_primary_evidence": ["pricing-1"],
            "qualification_months": 24,
            "qualified_substitute_count": 0,
            "dated_catalyst_days": 10,
            "expectation_gap_primary_evidence": ["expectation-1"],
            "primary_evidence": ["filing-1", "contract-1"],
            "corroborating_evidence": [],
            "disconfirmation_conditions": ["loss of contract", "substitute qualified", "margin collapse"],
            "last_verified_at": "2026-08-23T00:00:00Z",
        }

    def test_ideal_record_can_reach_100(self) -> None:
        result = calculate_total_score(self.ideal_data(), self.ideal_metadata())
        self.assertEqual(result["total_score"], 100)
        self.assertEqual(sum(result["layer_scores"].values()), 100)
        self.assertEqual(result["rating"], "S")
        self.assertEqual(result["layer_scores"]["L5_evidence_risk"], 20)

    def test_missing_data_is_not_rewarded(self) -> None:
        result = calculate_total_score(
            {"ticker": "EMPTY", "name": "Empty Corp"},
            {"ticker": "EMPTY", "category": "", "source": "unknown"},
        )
        self.assertLess(result["total_score"], 10)
        self.assertLess(result["data_quality"], 0.10)
        self.assertTrue(result["warnings"])
        self.assertEqual(result["user_long_term_overlay"]["label"], "disabled")

    def test_user_horizon_does_not_change_research_score(self) -> None:
        data = self.ideal_data()
        metadata = self.ideal_metadata()
        two_year = {
            "long_term_overlay": {
                "enabled": True,
                "minimum_holding_years": 2,
                "labels": {
                    "high": "高",
                    "conditional": "中",
                    "event_driven": "低",
                    "insufficient": "不足",
                },
            }
        }
        five_year = {
            "long_term_overlay": {
                "enabled": True,
                "minimum_holding_years": 5,
                "labels": {
                    "high": "高",
                    "conditional": "中",
                    "event_driven": "低",
                    "insufficient": "不足",
                },
            }
        }
        result_2y = calculate_total_score(data, metadata, two_year)
        result_5y = calculate_total_score(data, metadata, five_year)
        self.assertEqual(result_2y["total_score"], result_5y["total_score"])
        self.assertFalse(
            result_2y["user_long_term_overlay"]["affects_methodology_research_score"]
        )
        self.assertEqual(result_2y["user_long_term_overlay"]["minimum_holding_years"], 2)
        self.assertEqual(result_5y["user_long_term_overlay"]["minimum_holding_years"], 5)

    def test_long_term_overlay_is_user_attributed(self) -> None:
        overlay = calculate_long_term_suitability(
            self.ideal_data(),
            self.ideal_metadata(),
        )
        self.assertEqual(overlay["owner"], "local_user")
        self.assertFalse(overlay["affects_source_view"])
        self.assertFalse(overlay["affects_methodology_research_score"])
        self.assertIn("not attributed", overlay["disclaimer"])

    def test_yfinance_debt_to_equity_percentage_is_normalized(self) -> None:
        self.assertAlmostEqual(normalized_debt_to_equity(150), 1.5)
        self.assertAlmostEqual(normalized_debt_to_equity(1.5), 1.5)

    def test_local_research_universe_requires_an_explicit_ignored_file(self) -> None:
        self.assertFalse((ROOT / "config" / "watchlist.json").exists())
        with self.assertRaises(FileNotFoundError):
            load_watchlist()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research-universe.local.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "privacy_class": "local_user_configuration",
                        "stocks": [
                            {
                                "ticker": "test",
                                "name": "Synthetic Company",
                                "category": "Synthetic",
                                "source": "synthetic-fixture",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            records = load_watchlist(path)
        self.assertEqual([item["ticker"] for item in records], ["TEST"])


if __name__ == "__main__":
    unittest.main()
