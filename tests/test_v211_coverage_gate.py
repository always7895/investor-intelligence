from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v211_serenity_top20_coverage_gate as gate


class SerenityCoverageGateTests(unittest.TestCase):
    def test_authoritative_name_lane_is_ticker_agnostic(self) -> None:
        material = (ROOT / "scripts" / "v211_serenity_top20_coverage_gate.py").read_text(
            encoding="utf-8"
        ).upper()
        # The coverage lane must be generic and must not be an owner-specific
        # ticker inclusion list.
        for forbidden in ("AAOI", "SIVE"):
            self.assertNotIn(forbidden, material)

    def test_optoelectronics_official_name_is_recognized(self) -> None:
        self.assertGreater(gate.authoritative_name_theme_hits("Applied Optoelectronics, Inc."), 0)
        self.assertGreater(gate.authoritative_name_theme_hits("Example Photonics Corporation"), 0)
        self.assertEqual(gate.authoritative_name_theme_hits("Generic Software Corporation"), 0)

    def test_sec_name_seed_is_added_without_owner_watchlist(self) -> None:
        seeds = [
            {
                "ticker": "BASE",
                "screen_weight": 1.0,
                "screeners": ["generic"],
                "theme_hits": 0,
                "theme_terms": [],
                "market": {"longName": "Base Company"},
            }
        ]
        reference = {
            "ZZOP": {
                "ticker": "ZZOP",
                "cik": "0000000001",
                "name": "Example Optoelectronics Corporation",
                "exchange": "Nasdaq",
            }
        }
        augmented = gate.augment_authoritative_name_seeds(seeds, reference)
        injected = next(item for item in augmented if item["ticker"] == "ZZOP")
        self.assertGreaterEqual(injected["theme_hits"], gate.AUTHORITATIVE_NAME_PRIORITY)
        self.assertEqual(injected["screen_weight"], 0.0)
        self.assertIn("sec_official_name_optical_photonics", injected["theme_terms"])

    def test_optoelectronics_lexical_normalization_matches_existing_chokepoint_class(self) -> None:
        self.assertIn("optoelectronics", gate.base.AI_WORDS)
        self.assertIn("optoelectronics", gate.base.CHOKE_WORDS)
        self.assertIn("optoelectronics", gate.base.DOMAIN_C)


if __name__ == "__main__":
    unittest.main()
