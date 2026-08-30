from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v21_serenity_top20 as v21


class SerenityEngineV21Tests(unittest.TestCase):
    def test_synthetic_exact_top20_and_99_source_plan(self) -> None:
        output = v21.run(synthetic=True)
        self.assertEqual(output["top20_count"], 20)
        self.assertEqual(output["catalog_count"], 99)
        top = json.loads(v21.TOP20_PATH.read_text(encoding="utf-8"))
        self.assertEqual([item["rank"] for item in top], list(range(1, 21)))
        self.assertEqual(
            top,
            sorted(
                top,
                key=lambda item: (
                    -item["serenity_score"],
                    -item["data_quality"],
                    item["ticker"],
                ),
            ),
        )

    def test_seven_factors_total_100_and_aschenbrenner_is_separate(self) -> None:
        policy, _ = v21.validate_policy()
        self.assertEqual(sum(policy["factor_weights"].values()), 100)
        output = v21.run(synthetic=True)
        top = json.loads(v21.TOP20_PATH.read_text(encoding="utf-8"))
        self.assertTrue(
            all(
                item["aschenbrenner_overlay"]["included_in_serenity_score"] is False
                for item in top
            )
        )
        self.assertTrue(
            all(len(item["serenity_factors"]) == 7 for item in top)
        )

    def test_yfinance_is_discovery_only_and_all_99_sources_are_planned(self) -> None:
        policy, activation = v21.validate_policy()
        plan = v21.source_plan(policy, activation)
        self.assertEqual(len(plan["members"]), 99)
        states = {item["source_id"]: item["v21_state"] for item in plan["members"]}
        self.assertEqual(states["sec_edgar"], "v21_reviewed_live_overlay")
        self.assertEqual(states["world_bank_indicators"], "v21_reviewed_live_overlay")
        self.assertEqual(states["yahoo_finance_public_unofficial"], "t3_local_discovery_only")
        self.assertEqual(
            sum(state == "deferred_catalog_member" for state in states.values()),
            96,
        )

    def test_public_top20_contains_no_private_fields(self) -> None:
        v21.run(synthetic=True)
        serialized = v21.TOP20_PATH.read_text(encoding="utf-8").casefold()
        for marker in (
            '"account"',
            '"portfolio"',
            '"position"',
            '"holding"',
            '"cost_basis"',
            '"pnl"',
            '"line_user_id"',
            '"tenant_id"',
            '"messages"',
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, serialized)


if __name__ == "__main__":
    unittest.main()
