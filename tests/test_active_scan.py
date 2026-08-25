from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from active_scan import apply_changes, evaluate  # noqa: E402


class ActiveScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.watchlist = {
            "updated": "2026-08-23",
            "stocks": [
                {
                    "ticker": "KEEP",
                    "name": "Keep Corp",
                    "category": "AI Networking",
                    "source": "unverified-research-seed",
                }
            ],
        }

    @staticmethod
    def strong_market_record(ticker: str) -> dict:
        return {
            "ticker": ticker,
            "name": f"{ticker} Corp",
            "market_cap": 2_000_000_000,
            "revenue_ttm": 1_000_000_000,
            "revenue_growth": 0.55,
            "gross_margin": 0.52,
            "forward_pe": 12,
            "ps_ratio": 5,
            "total_debt": 100_000_000,
            "supply_gap": 0.30,
            "market_share": 0.60,
            "technology_moat_years": 5,
            "contract_evidence": True,
            "pricing_power_evidence": True,
            "demand_evidence": True,
            "qualification_months": 24,
            "tam_growth": 0.50,
        }

    def strong_news_record(self, ticker: str) -> dict:
        return {
            "ticker": ticker,
            "name": f"{ticker} Corp",
            "category": "InP Substrate",
            "evidence_strength": "strong",
            "url": "https://example.test/filing",
            "supply_gap": 0.30,
            "market_share": 0.60,
            "technology_moat_years": 5,
            "contract_evidence": True,
            "pricing_power_evidence": True,
            "demand_evidence": True,
            "qualification_months": 24,
            "tam_growth": 0.50,
        }

    def test_strong_evidence_candidate_enters(self) -> None:
        market = [self.strong_market_record("NEW")]
        results = evaluate(self.watchlist, market, [self.strong_news_record("NEW")])
        self.assertEqual([item["ticker"] for item in results["new_entries"]], ["NEW"])
        self.assertGreaterEqual(results["new_entries"][0]["score"], 60)

    def test_active_scan_is_explicitly_project_authored_not_author_score(self) -> None:
        market = [self.strong_market_record("NEW")]
        results = evaluate(self.watchlist, market, [self.strong_news_record("NEW")])

        self.assertEqual(results["schema_version"], 3)
        self.assertEqual(
            results["score_type"], "system_operationalization_not_author_score"
        )
        self.assertFalse(results["attribution"]["serenity_framework_claimed"])
        self.assertFalse(results["attribution"]["aschenbrenner_stock_screen_claimed"])
        self.assertFalse(results["attribution"]["user_holding_horizon_included"])

        evaluation = next(item for item in results["evaluations"] if item["ticker"] == "NEW")
        self.assertIn("system_bottleneck_screen", evaluation)
        self.assertIn("system_infrastructure_screen", evaluation)
        self.assertNotIn("serenity", evaluation)
        self.assertNotIn("aschenbrenner", evaluation)
        self.assertFalse(evaluation["attribution"]["serenity_endorsement"])
        self.assertFalse(evaluation["attribution"]["aschenbrenner_endorsement"])

        serialized = json.dumps(results, ensure_ascii=False).casefold()
        self.assertNotIn("serenity_evaluation", serialized)
        self.assertNotIn("aschenbrenner_evaluation", serialized)
        self.assertNotIn("dual-methodology", serialized)
        self.assertNotIn("aschenbrenner layer", serialized)

    def test_weak_evidence_candidate_does_not_enter(self) -> None:
        market = [self.strong_market_record("WEAK")]
        news = [
            {
                **self.strong_news_record("WEAK"),
                "evidence_strength": "weak",
            }
        ]
        results = evaluate(self.watchlist, market, news)
        self.assertEqual(results["new_entries"], [])

    def test_missing_market_data_never_forces_exit(self) -> None:
        results = evaluate(self.watchlist, [], [])
        self.assertEqual(results["exit_candidates"], [])
        self.assertEqual(results["unscored_existing"][0]["ticker"], "KEEP")

    def test_explicit_project_risk_gate_marks_exit_candidate(self) -> None:
        market = [
            {
                **self.strong_market_record("KEEP"),
                "atm_issuance_to_revenue": 0.25,
            }
        ]
        results = evaluate(self.watchlist, market, [])
        self.assertEqual([item["ticker"] for item in results["exit_candidates"]], ["KEEP"])
        self.assertIn("Project risk gate", results["exit_candidates"][0]["reasons"][0])
        self.assertIn("ATM", results["exit_candidates"][0]["reasons"][0])

    def test_apply_changes_is_idempotent_and_does_not_claim_author_endorsement(self) -> None:
        results = {
            "generated_at": "2026-08-23T00:00:00+00:00",
            "exit_candidates": [],
            "new_entries": [
                {
                    "ticker": "NEW",
                    "name": "New Corp",
                    "category": "InP Substrate",
                    "score": 91,
                }
            ],
        }
        first = apply_changes(self.watchlist, results)
        second = apply_changes(first, results)
        new_stock = next(stock for stock in second["stocks"] if stock["ticker"] == "NEW")
        tickers = [stock["ticker"] for stock in second["stocks"]]
        self.assertEqual(tickers.count("NEW"), 1)
        self.assertEqual(new_stock["source"], "unverified-auto-scan")
        self.assertEqual(
            new_stock["last_score_type"], "system_operationalization_not_author_score"
        )
        self.assertIn("No Serenity or Aschenbrenner endorsement inferred", new_stock["thesis"])


if __name__ == "__main__":
    unittest.main()
