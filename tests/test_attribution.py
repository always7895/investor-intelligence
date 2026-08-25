from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AttributionTests(unittest.TestCase):
    def test_attribution_policy_and_user_overlay_are_explicit(self) -> None:
        policy = (ROOT / "docs" / "METHODOLOGY_ATTRIBUTION.md").read_text(encoding="utf-8")
        serenity = (ROOT / "skills" / "serenity-bottleneck.md").read_text(encoding="utf-8")
        aschenbrenner = (ROOT / "skills" / "aschenbrenner-infra.md").read_text(encoding="utf-8")
        overlay = (ROOT / "skills" / "user-long-term-overlay.md").read_text(encoding="utf-8")

        self.assertIn("Source view", policy)
        self.assertIn("System operationalization", policy)
        self.assertIn("User preference overlay", policy)
        self.assertIn("not a verbatim Serenity framework", serenity)
        self.assertIn("not an Aschenbrenner stock-picking framework", aschenbrenner)
        self.assertIn("not a Serenity view", overlay)
        self.assertIn("not a Leopold Aschenbrenner view", overlay)

    def test_user_horizon_is_not_part_of_methodology_weights(self) -> None:
        weights = json.loads(
            (ROOT / "config" / "scoring-weights.json").read_text(encoding="utf-8")
        )
        preferences = json.loads(
            (ROOT / "config" / "user-preferences.example.json").read_text(encoding="utf-8")
        )

        self.assertNotIn("projected_cagr_2yr", json.dumps(weights))
        self.assertEqual(weights["layers"]["L5_evidence_risk"]["weight"], 20)
        self.assertFalse(weights["attribution"]["user_long_term_overlay_included"])
        self.assertFalse(preferences["long_term_overlay"]["enabled"])
        self.assertEqual(preferences["long_term_overlay"]["owner"], "local_user")
        self.assertEqual(
            preferences["long_term_overlay"]["minimum_holding_years"], 2
        )
        self.assertFalse(
            preferences["long_term_overlay"]["affects_methodology_research_score"]
        )
        self.assertFalse(preferences["long_term_overlay"]["affects_source_view"])


if __name__ == "__main__":
    unittest.main()
