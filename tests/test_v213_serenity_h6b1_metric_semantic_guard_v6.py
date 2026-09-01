#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6b1_metric_semantic_guard_v6 as r11


class H6B1R11Tests(unittest.TestCase):
    def _metric(self, text: str):
        metric = r11.r4._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        return metric

    def test_fallback_dispatch_is_immutable_and_non_recursive(self) -> None:
        metric = self._metric(
            "Remaining performance obligations were approximately $ 1.2 billion. "
            "The Company expects to recognize revenue associated with these remaining performance obligations over the next twelve months."
        )
        self.assertIsNot(r11._PRE_R11_FUTURE, r11.r4._future_from_context)
        for _ in range(128):
            future, klass = r11._future_from_context_v6(metric)
            self.assertEqual(klass, "INFERENCE")
            self.assertIn("未在同一證據段落提供可安全量化的比例", future)
            self.assertIn("非新增訂單預測", future)
            self.assertNotIn("不等於新增訂單預測", future)

    def test_real_generic_sec_adapter_uses_non_recursive_fallback(self) -> None:
        filing_text = (
            "Remaining performance obligations were approximately $ 1.2 billion. "
            "The Company expects to recognize revenue associated with these remaining performance obligations over the next twelve months."
        )

        def raw_fetcher(url: str) -> str:
            self.assertIn("data.sec.gov/submissions", url)
            return json.dumps(
                {
                    "filings": {
                        "recent": {
                            "form": ["10-Q"],
                            "accessionNumber": ["0000000123-26-000001"],
                            "primaryDocument": ["test-20260630.htm"],
                            "filingDate": ["2026-06-30"],
                        }
                    }
                }
            )

        def text_fetcher(url: str) -> str:
            self.assertIn("Archives/edgar/data/123/", url)
            return filing_text

        result = r11.r4.generic_sec_outlook_semantic(
            "TEST",
            {"TEST": "123"},
            raw_fetcher=raw_fetcher,
            text_fetcher=text_fetcher,
        )
        self.assertEqual(result["claim_grounding"]["current_orders_summary"], "SUPPORTED")
        self.assertEqual(result["claim_grounding"]["future_orders_estimate"], "INFERENCE")
        self.assertIn("未在同一證據段落提供可安全量化的比例", result["future_orders_estimate"])
        self.assertIn("非新增訂單預測", result["future_orders_estimate"])

    def test_known_numeric_fulfillment_schedules_remain(self) -> None:
        fixtures = [
            (
                "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length was $ 3.2 billion. Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months.",
                "39%",
            ),
            (
                "As of June 27, 2026, the aggregate transaction price allocated to remaining performance obligations under contracts with an original expected duration of more than one year was $ 222 million, of which $ 144 million is expected to be recognized in the next 12 months.",
                "$144 million",
            ),
            (
                "The Company's remaining performance obligations were $ 4.9 billion as of June 30, 2026, of which the Company expects to recognize approximately 43% as revenue over the next 12 months, 36% over the subsequent 13 to 36 months, and the remainder thereafter.",
                "43%",
            ),
        ]
        for text, needle in fixtures:
            metric = self._metric(text)
            future, klass = r11._future_from_context_v6(metric)
            self.assertEqual(klass, "INFERENCE")
            self.assertIn(needle, future)
            self.assertIn("非新增訂單預測", future)

    def test_worded_and_fiscal_schedules_remain(self) -> None:
        mu = self._metric(
            "As of May 28, 2026, the transaction price allocated to our remaining performance obligations was approximately $ 5 billion. Approximately one-third of the remaining performance obligations as of May 28, 2026 are expected to be recognized as revenue over the next twelve months."
        )
        future, klass = r11._future_from_context_v6(mu)
        self.assertEqual(klass, "INFERENCE")
        self.assertIn("三分之一", future)

        crdo = self._metric(
            "The contracted but unsatisfied performance obligation was approximately $ 31.9 million which the Company expects to recognize over the next fiscal year."
        )
        future, klass = r11._future_from_context_v6(crdo)
        self.assertEqual(klass, "INFERENCE")
        self.assertIn("下一會計年度", future)

    def test_unavailable_future_remains_unavailable(self) -> None:
        metric = self._metric(
            "Remaining performance obligations were approximately $ 900 million with no disclosed recognition schedule."
        )
        future, klass = r11._future_from_context_v6(metric)
        self.assertEqual(klass, "UNAVAILABLE")
        self.assertEqual(future, r11.base.FUTURE_FALLBACK)
        self.assertNotIn("非新增訂單預測", future)

    def test_r8_false_positive_guards_remain(self) -> None:
        text = (
            "inventory increased to support unfulfilled backlog and related new product ramps; "
            "other assets increased by $71.3 million of payment for refundable deposits to suppliers. "
            "The contracted but unsatisfied performance obligation was approximately $31.9 million."
        )
        metric = self._metric(text)
        self.assertEqual(metric["metric_type"], "RPO")
        self.assertEqual(r11._normalize_amount_v6(metric["amount"]), "$31.9 million")
        self.assertIsNone(r11.r4._extract_strict_metric("remaining performance obligations were $946"))
        self.assertIsNone(
            r11.r4._extract_strict_metric(
                "amortization expense included $23.5 related to the amortization of acquired backlog"
            )
        )


if __name__ == "__main__":
    unittest.main()
