from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v21_serenity_top20 as v21
import v211_serenity_top20 as v211


class SerenityUniverseV211Tests(unittest.TestCase):
    def test_synthetic_universe_and_public_symbols(self) -> None:
        output = v211.run(synthetic=True)
        self.assertEqual(output["top20_count"], 20)
        self.assertGreaterEqual(output["research_universe_count"], 20)
        universe = json.loads(v211.UNIVERSE_PATH.read_text(encoding="utf-8"))
        symbols = json.loads(v211.GENERATED_SYMBOLS_PATH.read_text(encoding="utf-8"))
        self.assertEqual([item["rank"] for item in universe], list(range(1, len(universe) + 1)))
        self.assertFalse(symbols["owner_watchlist_inheritance"])
        self.assertEqual(
            [item["ticker"] for item in symbols["symbols"]],
            [item["ticker"] for item in universe[: len(symbols["symbols"])]],
        )

    def test_thematic_reserve_reaches_full_scoring_gate(self) -> None:
        policy, _ = v211.v211_policy()
        policy = dict(policy)
        policy["sec_candidate_limit"] = 20
        policy["sec_thematic_reserve"] = 5

        seeds = []
        reference = {}
        for index in range(30):
            ticker = f"GEN{index}"
            seeds.append({
                "ticker": ticker,
                "screen_weight": 6.0,
                "screeners": ["growth_technology_stocks"],
                "theme_hits": 0,
                "theme_terms": [],
                "market": {
                    "regularMarketPrice": 50.0,
                    "marketCap": 5_000_000_000,
                    "averageDailyVolume3Month": 2_000_000,
                },
            })
            reference[ticker] = {"ticker": ticker, "cik": str(index + 1).zfill(10), "name": ticker, "exchange": "Nasdaq"}
        thematic = []
        for index in range(5):
            ticker = f"THM{index}"
            thematic.append(ticker)
            seeds.append({
                "ticker": ticker,
                "screen_weight": 0.0,
                "screeners": [],
                "theme_hits": 2,
                "theme_terms": ["optical networking semiconductor"],
                "market": {
                    "regularMarketPrice": 25.0,
                    "marketCap": 800_000_000,
                    "averageDailyVolume3Month": 400_000,
                },
            })
            reference[ticker] = {"ticker": ticker, "cik": str(index + 101).zfill(10), "name": ticker, "exchange": "Nasdaq"}

        selected = v211.validate_candidates(seeds, reference, policy)
        self.assertEqual(len(selected), 20)
        self.assertTrue(set(thematic).issubset({item["ticker"] for item in selected}))

    def test_theme_membership_never_adds_serenity_points(self) -> None:
        policy, _ = v211.v211_policy()
        market = {
            "industry": "Communication Equipment",
            "forwardPE": 25.0,
            "priceToSalesTrailing12Months": 4.0,
            "beta": 1.2,
            "shortPercentOfFloat": 0.04,
        }
        official = {"name": "Example Corp"}
        metrics = {
            "revenue_growth": 0.30,
            "gross_margin": 0.50,
            "operating_margin": 0.16,
            "net_margin": 0.10,
            "debt_to_equity": 0.5,
        }
        evidence = [
            v21.Evidence(
                "sec_edgar", "T0", "xbrl_fact", "Public fact",
                "https://www.sec.gov/example", "2026-08-31T00:00:00Z",
            )
        ]
        broad = {"ticker": "EXA", "official": official, "market": market, "theme_hits": 0}
        thematic = {"ticker": "EXB", "official": official, "market": market, "theme_hits": 9}
        left = v21.score_candidate(broad, metrics, evidence, policy)
        right = v21.score_candidate(thematic, metrics, evidence, policy)
        self.assertEqual(left["serenity_score"], right["serenity_score"])
        self.assertEqual(left["serenity_factors"], right["serenity_factors"])

    def test_policy_contains_no_owner_specific_tickers(self) -> None:
        text = v211.V211_POLICY_PATH.read_text(encoding="utf-8").upper()
        self.assertNotIn("AAOI", text)
        self.assertNotIn("SIVE", text)


if __name__ == "__main__":
    unittest.main()
