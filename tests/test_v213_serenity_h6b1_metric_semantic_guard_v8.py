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

import v213_serenity_h6b1_metric_semantic_guard_v8 as r13


class H6B1R13Tests(unittest.TestCase):
    PRIMARY = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm"
    DETAIL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/R14.htm"

    def _raw(self, url: str) -> str:
        if url.endswith("/FilingSummary.xml"):
            return (
                "<FilingSummary><MyReports>"
                "<Report><HtmlFileName>R14.htm</HtmlFileName></Report>"
                "<Report><HtmlFileName>R17.htm</HtmlFileName></Report>"
                "</MyReports></FilingSummary>"
            )
        if "data.sec.gov/submissions" in url:
            return json.dumps({
                "filings": {"recent": {
                    "form": ["10-Q"],
                    "accessionNumber": ["0001045810-26-000075"],
                    "primaryDocument": ["nvda-20260726.htm"],
                    "filingDate": ["2026-08-26"],
                }}
            })
        raise AssertionError(url)

    def _text(self, url: str) -> str:
        if url == self.PRIMARY:
            return "Remaining performance obligations were $ 3.2 billion with no disclosed recognition schedule."
        if url == self.DETAIL:
            return (
                "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length was $ 3.2 billion. "
                "Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months."
            )
        if url.endswith("/R17.htm"):
            return "Future supply and capacity commitments were $279 billion."
        raise AssertionError(url)

    def test_nvda_same_accession_detail_recovers_39pct(self) -> None:
        result = r13.generic_sec_outlook_semantic_v8(
            "NVDA",
            {"NVDA": "1045810"},
            raw_fetcher=self._raw,
            text_fetcher=self._text,
        )
        self.assertEqual(result["claim_grounding"]["current_orders_summary"], "SUPPORTED")
        self.assertEqual(result["claim_grounding"]["future_orders_estimate"], "INFERENCE")
        self.assertIn("39%", result["future_orders_estimate"])
        self.assertEqual(result["current_order_source_urls"], [self.PRIMARY])
        self.assertEqual(result["future_order_source_urls"], [self.DETAIL])

    def test_same_accession_different_amount_cannot_supply_schedule(self) -> None:
        result = {
            "current_orders_summary": "SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$2.6 billion（文件日2026-08-26）；RPO常排除短期合約，不能視為公司全部客戶訂單",
            "future_orders_estimate": r13.base.FUTURE_FALLBACK,
            "current_order_source_urls": [self.PRIMARY],
            "future_order_source_urls": [],
            "claim_grounding": {"current_orders_summary": "SUPPORTED", "future_orders_estimate": "UNAVAILABLE"},
        }
        out = r13._enrich_same_accession_package(result, raw_fetcher=self._raw, text_fetcher=self._text)
        self.assertEqual(out["claim_grounding"]["future_orders_estimate"], "UNAVAILABLE")

    def test_non_sec_source_is_not_package_enriched(self) -> None:
        result = {
            "current_orders_summary": "RPO約$3.2 billion",
            "future_orders_estimate": r13.base.FUTURE_FALLBACK,
            "current_order_source_urls": ["https://example.com/filing.htm"],
            "future_order_source_urls": [],
            "claim_grounding": {"current_orders_summary": "SUPPORTED", "future_orders_estimate": "UNAVAILABLE"},
        }
        out = r13._enrich_same_accession_package(result, raw_fetcher=self._raw, text_fetcher=self._text)
        self.assertEqual(out["claim_grounding"]["future_orders_estimate"], "UNAVAILABLE")

    def test_existing_inference_is_not_replaced(self) -> None:
        result = {
            "current_orders_summary": "RPO約$3.2 billion",
            "future_orders_estimate": "existing inference；非新增訂單預測",
            "current_order_source_urls": [self.PRIMARY],
            "future_order_source_urls": [self.PRIMARY],
            "claim_grounding": {"current_orders_summary": "SUPPORTED", "future_orders_estimate": "INFERENCE"},
        }
        out = r13._enrich_same_accession_package(result, raw_fetcher=self._raw, text_fetcher=self._text)
        self.assertEqual(out, result)

    def test_filing_summary_failure_fails_closed(self) -> None:
        def bad_raw(url: str) -> str:
            if url.endswith("/FilingSummary.xml"):
                raise r13.base.H6BError("unavailable")
            return self._raw(url)

        result = r13.generic_sec_outlook_semantic_v8(
            "NVDA",
            {"NVDA": "1045810"},
            raw_fetcher=bad_raw,
            text_fetcher=self._text,
        )
        self.assertEqual(result["claim_grounding"]["future_orders_estimate"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
