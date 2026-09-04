#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6b1_metric_semantic_guard_v5 as r10


class H6B1R10Tests(unittest.TestCase):
    def _assert_canonical(self, text: str, needle: str) -> None:
        metric = r10.r4._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        assert metric is not None
        future, klass = r10._future_from_context_v5(metric)
        self.assertEqual(klass, "INFERENCE")
        self.assertIn(needle, future)
        self.assertIn("非新增訂單預測", future)
        self.assertNotIn("不等於新增訂單預測", future)

    def test_nvda_canonical_disclaimer(self) -> None:
        self._assert_canonical(
            "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length was $ 3.2 billion. Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months.",
            "39%",
        )

    def test_amd_canonical_disclaimer(self) -> None:
        self._assert_canonical(
            "As of June 27, 2026, the aggregate transaction price allocated to remaining performance obligations under contracts with an original expected duration of more than one year was $ 222 million, of which $ 144 million is expected to be recognized in the next 12 months.",
            "$144 million",
        )

    def test_mu_canonical_disclaimer(self) -> None:
        self._assert_canonical(
            "As of May 28, 2026, the transaction price allocated to our remaining performance obligations was approximately $ 5 billion. Approximately one-third of the remaining performance obligations as of May 28, 2026 are expected to be recognized as revenue over the next twelve months.",
            "三分之一",
        )

    def test_crdo_and_aph_already_canonical(self) -> None:
        self._assert_canonical(
            "The contracted but unsatisfied performance obligation was approximately $ 31.9 million which the Company expects to recognize over the next fiscal year.",
            "下一會計年度",
        )
        self._assert_canonical(
            "The Company estimates that its backlog of unfilled firm orders as of December 31, 2025 was approximately $ 8.9 billion. It is expected that nearly all of the Company's backlog will be filled within the next 12 months.",
            "幾乎全部",
        )

    def test_canonicalizer_changes_wording_only(self) -> None:
        source = "公司預期約39%的該RPO於未來12個月認列；這是既有合約履約節奏，不等於新增訂單預測"
        expected = "公司預期約39%的該RPO於未來12個月認列；這是既有合約履約節奏，非新增訂單預測"
        self.assertEqual(r10._canonicalize_disclaimer(source), expected)


if __name__ == "__main__":
    unittest.main()
