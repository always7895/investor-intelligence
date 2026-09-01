#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6b1_metric_semantic_guard_v4 as r9


class H6B1R9Tests(unittest.TestCase):
    def _assert_future(self, text: str, current: str, needle: str) -> None:
        metric = r9.r4._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        assert metric is not None
        self.assertEqual(r9._normalize_amount_v4(metric["amount"]), current)
        future, klass = r9._future_from_context_v4(metric)
        self.assertEqual(klass, "INFERENCE")
        self.assertIn(needle, future)
        self.assertIn("非新增訂單預測", future)

    def test_nvda_39pct(self) -> None:
        self._assert_future(
            "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length was $ 3.2 billion. Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months.",
            "$3.2 billion",
            "39%",
        )

    def test_mu_one_third_without_decimal_invention(self) -> None:
        self._assert_future(
            "As of May 28, 2026, the transaction price allocated to our remaining performance obligations was approximately $ 5 billion. Approximately one-third of the remaining performance obligations as of May 28, 2026 are expected to be recognized as revenue over the next twelve months.",
            "$5 billion",
            "三分之一",
        )

    def test_avgo_30pct(self) -> None:
        self._assert_future(
            "Remaining performance obligations under these contracts as of May 3, 2026 were approximately $ 164.6 billion. We expect approximately 30% of this amount to be recognized as revenue over the next 12 months.",
            "$164.6 billion",
            "30%",
        )

    def test_life360_46pct(self) -> None:
        self._assert_future(
            "Revenue expected to be recognized in connection with remaining performance obligations was $ 186.8 million as of June 30, 2026, of which the Company expects 46% to be recognized over the next twelve months.",
            "$186.8 million",
            "46%",
        )

    def test_net_64pct(self) -> None:
        self._assert_future(
            "As of June 30, 2026, the aggregate amount of the transaction price allocated to remaining performance obligations was $ 2,732.0 million. The Company expected to recognize 64% of its remaining performance obligations as revenue over the next 12 months with the remainder recognized thereafter.",
            "$2,732.0 million",
            "64%",
        )

    def test_smci_60pct(self) -> None:
        self._assert_future(
            "The value of the transaction price allocated to the remaining performance obligations as of June 30, 2026, was approximately $ 2,612.0 million. We expect to recognize approximately 60% of such value in the next 12 months, and the remainder thereafter.",
            "$2,612.0 million",
            "60%",
        )

    def test_pltr_43pct(self) -> None:
        self._assert_future(
            "The Company's remaining performance obligations were $ 4.9 billion as of June 30, 2026, of which the Company expects to recognize approximately 43% as revenue over the next 12 months, 36% as revenue over the subsequent 13 to 36 months, and the remainder thereafter.",
            "$4.9 billion",
            "43%",
        )

    def test_amd_amount_schedule(self) -> None:
        self._assert_future(
            "As of June 27, 2026, the aggregate transaction price allocated to remaining performance obligations under contracts with an original expected duration of more than one year was $ 222 million, of which $ 144 million is expected to be recognized in the next 12 months.",
            "$222 million",
            "$144 million",
        )

    def test_crdo_next_fiscal_year(self) -> None:
        self._assert_future(
            "The contracted but unsatisfied performance obligation was approximately $ 31.9 million which the Company expects to recognize over the next fiscal year.",
            "$31.9 million",
            "下一會計年度",
        )

    def test_aph_nearly_all_backlog(self) -> None:
        self._assert_future(
            "The Company estimates that its backlog of unfilled firm orders as of December 31, 2025 was approximately $ 8.9 billion. It is expected that nearly all of the Company's backlog will be filled within the next 12 months.",
            "$8.9 billion",
            "幾乎全部",
        )

    def test_cf_multi_period_schedule(self) -> None:
        metric = r9.r4._extract_strict_metric(
            "Our remaining performance obligations under these contracts were approximately $ 1.5 billion. We expect to recognize approximately 17% of these performance obligations as revenue in the remainder of 2026, approximately 43% as revenue during 2027-2029, approximately 14% as revenue during 2030-2032, and the remainder as revenue thereafter."
        )
        self.assertIsNotNone(metric)
        assert metric is not None
        future, klass = r9._future_from_context_v4(metric)
        self.assertEqual(klass, "INFERENCE")
        self.assertIn("17%", future)
        self.assertIn("2027–2029", future)
        self.assertIn("14%", future)

    def test_money_spacing_is_canonical(self) -> None:
        self.assertEqual(r9._normalize_amount_v4("$ 31.9 million"), "$31.9 million")
        self.assertEqual(r9._normalize_amount_v4("$ 164.6 billion"), "$164.6 billion")

    def test_r8_clause_and_false_positive_guards_remain(self) -> None:
        text = (
            "inventory increased to support unfulfilled backlog and related new product ramps; "
            "other assets increased by $71.3 million of payment for refundable deposits to suppliers. "
            "The contracted but unsatisfied performance obligation was approximately $31.9 million."
        )
        metric = r9.r4._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        assert metric is not None
        self.assertEqual(metric["metric_type"], "RPO")
        self.assertEqual(r9._normalize_amount_v4(metric["amount"]), "$31.9 million")
        self.assertIsNone(r9.r4._extract_strict_metric("remaining performance obligations were $946"))
        self.assertIsNone(r9.r4._extract_strict_metric("amortization expense included $23.5 related to the amortization of acquired backlog"))


if __name__ == "__main__":
    unittest.main()
