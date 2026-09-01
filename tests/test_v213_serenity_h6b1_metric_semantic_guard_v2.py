#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6b1_metric_semantic_guard_v2 as guard


class H6B1MetricSemanticGuardV2Tests(unittest.TestCase):
    def test_nvda_will_be_recognized_percentage(self) -> None:
        text = (
            "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length "
            "was $3.2 billion. Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months."
        )
        metric = guard.r4._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        future, classification = guard.r4._future_from_context(metric)
        self.assertEqual(classification, "INFERENCE")
        self.assertIn("39%", future)

    def test_amd_is_expected_to_be_recognized_amount(self) -> None:
        text = (
            "The aggregate transaction price allocated to remaining performance obligations under contracts with an original expected duration "
            "of more than one year was $222 million, of which $144 million is expected to be recognized in the next 12 months."
        )
        metric = guard.r4._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        future, classification = guard.r4._future_from_context(metric)
        self.assertEqual(classification, "INFERENCE")
        self.assertIn("$144 million", future)

    def test_bare_dollar_rpo_still_fails_closed(self) -> None:
        self.assertIsNone(guard.r4._extract_strict_metric("remaining performance obligations were $946"))

    def test_acquired_backlog_still_fails_closed(self) -> None:
        self.assertIsNone(
            guard.r4._extract_strict_metric(
                "amortization expense included $23.5 related to the amortization of acquired backlog"
            )
        )


if __name__ == "__main__":
    unittest.main()
