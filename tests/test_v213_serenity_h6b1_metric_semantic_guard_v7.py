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

import v213_serenity_h6b1_metric_semantic_guard_v7 as r12


class H6B1R12Tests(unittest.TestCase):
    @staticmethod
    def _duplicate_nvda() -> str:
        return (
            "Remaining performance obligations were $ 3.2 billion. "
            + ("duplicate-fact-no-schedule " * 70)
            + "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length was $ 3.2 billion. "
            + "Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months."
        )

    def test_duplicate_same_amount_recovers_nvda_schedule(self) -> None:
        text = self._duplicate_nvda()
        metric = r12.r4._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        assert metric is not None
        old_future, old_class = r12.r11._future_from_context_v6(metric)
        self.assertEqual(old_class, "UNAVAILABLE")
        enriched = r12._same_metric_schedule_from_source(text, metric_type="RPO", amount="$3.2 billion")
        self.assertIsNotNone(enriched)
        assert enriched is not None
        self.assertEqual(enriched[1], "INFERENCE")
        self.assertIn("39%", enriched[0])
        self.assertIn("非新增訂單預測", enriched[0])

    def test_different_amount_cannot_supply_schedule(self) -> None:
        text = (
            "Remaining performance obligations were approximately $ 3.2 billion with no disclosed recognition schedule. "
            "A prior-period remaining performance obligations balance was approximately $ 2.6 billion. "
            "Approximately 40% of the $ 2.6 billion prior-period balance will be recognized over the next twelve months."
        )
        self.assertIsNone(r12._same_metric_schedule_from_source(text, metric_type="RPO", amount="$3.2 billion"))

    def test_different_metric_type_cannot_supply_schedule(self) -> None:
        text = (
            "Backlog was approximately $ 3.2 billion. "
            "Remaining performance obligations were approximately $ 3.2 billion. "
            "Approximately 39% of the remaining performance obligations will be recognized over the next twelve months."
        )
        self.assertIsNone(r12._same_metric_schedule_from_source(text, metric_type="BACKLOG", amount="$3.2 billion"))

    def test_existing_inference_is_not_replaced(self) -> None:
        original = {
            "current_orders_summary": "SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$3.2 billion（文件日2026-08-26）；RPO常排除短期合約，不能視為公司全部客戶訂單",
            "future_orders_estimate": "公司預期約39%的該RPO於未來12個月認列；這是既有合約履約節奏，非新增訂單預測",
            "current_order_source_urls": ["https://example.test/nvda"],
            "future_order_source_urls": ["https://example.test/nvda"],
            "claim_grounding": {"current_orders_summary": "SUPPORTED", "future_orders_estimate": "INFERENCE"},
        }
        called = False

        def text_fetcher(url: str) -> str:
            nonlocal called
            called = True
            return self._duplicate_nvda()

        out = r12._enrich_same_selected_source(original, text_fetcher=text_fetcher)
        self.assertFalse(called)
        self.assertEqual(out["future_orders_estimate"], original["future_orders_estimate"])

    def test_real_adapter_enriches_same_selected_source(self) -> None:
        text = self._duplicate_nvda()

        def raw_fetcher(url: str) -> str:
            return json.dumps({
                "filings": {"recent": {
                    "form": ["10-Q"],
                    "accessionNumber": ["0001045810-26-000075"],
                    "primaryDocument": ["nvda-20260726.htm"],
                    "filingDate": ["2026-08-26"],
                }}
            })

        def text_fetcher(url: str) -> str:
            return text

        out = r12.generic_sec_outlook_semantic_v7(
            "NVDA",
            {"NVDA": "1045810"},
            raw_fetcher=raw_fetcher,
            text_fetcher=text_fetcher,
        )
        self.assertEqual(out["claim_grounding"]["current_orders_summary"], "SUPPORTED")
        self.assertEqual(out["claim_grounding"]["future_orders_estimate"], "INFERENCE")
        self.assertIn("39%", out["future_orders_estimate"])
        self.assertEqual(out["future_order_source_urls"], out["current_order_source_urls"])

    def test_unavailable_stays_fail_closed_when_same_amount_has_no_schedule(self) -> None:
        text = "Remaining performance obligations were approximately $ 900 million with no disclosed recognition schedule."

        def raw_fetcher(url: str) -> str:
            return json.dumps({
                "filings": {"recent": {
                    "form": ["10-Q"],
                    "accessionNumber": ["0000000123-26-000001"],
                    "primaryDocument": ["test.htm"],
                    "filingDate": ["2026-06-30"],
                }}
            })

        out = r12.generic_sec_outlook_semantic_v7(
            "TEST",
            {"TEST": "123"},
            raw_fetcher=raw_fetcher,
            text_fetcher=lambda url: text,
        )
        self.assertEqual(out["claim_grounding"]["future_orders_estimate"], "UNAVAILABLE")
        self.assertEqual(out["future_orders_estimate"], r12.base.FUTURE_FALLBACK)


if __name__ == "__main__":
    unittest.main()
