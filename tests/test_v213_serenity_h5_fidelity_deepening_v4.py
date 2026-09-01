#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h5_fidelity_deepening_v4 as h5v4


class H5V4Tests(unittest.TestCase):
    def test_sive_financing_context_includes_conversion_and_warrants(self) -> None:
        april = "8,620,000 ordinary shares at SEK 14.5 per share; dilution of approximately 2.5 percent"
        june = "12,280,701 ordinary shares at SEK 57 per share; discount of approximately 9.7 percent; dilution of approximately 3.3 percent"
        q1 = "qual builds and production readiness is on track for Q4 2026; massive multi-year imbalance in the demand-supply situation for optical networking"
        q2 = "Product Revenue Increases 18% Year-Over-Year; directed share issues amounting to approximately SEK 825 m"
        aug31 = "356,740,332 ordinary shares; increased by 1,659,015, from 355,081,317 to 356,740,332"
        conversion = "convert the convertible loan of $12M into shares and issue 22,847,044 new ordinary shares; conversion price of SEK 4.77 per share; dilution of approximately 6.4 per cent"
        warrant = "1,659,015 new ordinary shares at a subscription price of SEK 4.53 per share; proceeds of approximately SEK 7.5 million"
        old = h5v4.v3.fetch_text_complete
        try:
            def fake(url: str, **_: Any) -> str:
                if url == h5v4.SIVE_CONVERSION:
                    return conversion
                if url == h5v4.SIVE_WARRANT:
                    return warrant
                raise AssertionError(url)
            h5v4.v3.fetch_text_complete = fake  # type: ignore[assignment]
            result = h5v4.sive_financing_and_capacity_v4(april, june, q1, q2, aug31)
        finally:
            h5v4.v3.fetch_text_complete = old  # type: ignore[assignment]
        self.assertEqual(len(result["financing_events"]), 4)
        self.assertEqual(result["registered_shares_2026_08_31"], 356_740_332)
        self.assertGreater(result["registered_share_count_growth_pct"], 14.0)
        self.assertEqual(result["equity_capture_pressure"], "MATERIAL")
        self.assertFalse(result["toxic_financing_proven"])

    def test_equity_events_are_fact_separated_from_toxicity_judgment(self) -> None:
        self.assertIn("toxic", h5v4.__doc__.lower())
        self.assertIn("do not", h5v4.__doc__.lower())

    def test_latest_share_count_source_is_august_31(self) -> None:
        self.assertTrue(h5v4.SIVE_AUG31_SHARE_COUNT.endswith("-12/"))

    def test_v4_keeps_v3_complete_fetch_and_transactionality(self) -> None:
        self.assertTrue(callable(h5v4.v3.fetch_text_complete))
        self.assertTrue(callable(h5v4.v3.apply_h5_transactional))


if __name__ == "__main__":
    unittest.main()
