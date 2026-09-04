#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_top20_order_outlook_contract as mod


class SevenFieldTop20ContractTests(unittest.TestCase):
    def records(self):
        return [
            mod.seven_field_record({
                "rank": i + 1,
                "ticker": f"T{i:02d}",
                "long_term_return_pct": 30.0 - i,
                "short_term_return_pct": 8.0 - i / 4,
                "industry": "半導體",
                "profit_summary": "獲利；營收年增 +20.0%",
            })
            for i in range(20)
        ]

    def test_headers_append_order_fields_after_profit(self):
        text = mod.render(self.records())
        self.assertEqual(
            text.splitlines()[0],
            "股票｜長期投資報酬率（近2年年化）｜短期投資報酬率（近6個月）｜行業別｜獲利簡述｜公司現在訂單｜未來訂單預估",
        )
        self.assertTrue(all(len(line.split("｜")) == 7 for line in text.splitlines()))

    def test_missing_order_disclosure_fails_safe_not_hallucinated(self):
        row = self.records()[0]
        self.assertEqual(row["current_orders"], mod.NO_CURRENT_ORDERS)
        self.assertEqual(row["future_orders_estimate"], mod.NO_FUTURE_ESTIMATE)
        self.assertTrue(row["numeric_total_order_estimate_prohibited"])

    def test_evidence_bound_order_outlook_keeps_urls_hidden_from_line_columns(self):
        base = {
            "rank": 1,
            "ticker": "AXTI",
            "long_term_return_pct": 100,
            "short_term_return_pct": 30,
            "industry": "半導體",
            "profit_summary": "獲利",
        }
        row = mod.seven_field_record(base, {
            "current_orders_summary": "Casela 2027 RMB1.73億固定量",
            "future_orders_estimate": "能見度偏高但不估總額",
            "evidence_urls": ["https://www.sec.gov/Archives/edgar/example"],
            "numeric_total_order_estimate_prohibited": True,
        })
        self.assertIn("sec.gov", row["current_order_source_urls"][0])
        self.assertNotIn("https://", "｜".join([
            row["ticker"], row["industry"], row["profit_summary"], row["current_orders"], row["future_orders_estimate"]
        ]))

    def test_delimiter_in_summary_is_sanitized(self):
        row = mod.seven_field_record({
            "rank": 1,
            "ticker": "AXTI",
            "industry": "半導體",
            "profit_summary": "獲利｜測試",
        }, {"current_orders_summary": "A｜B", "future_orders_estimate": "C｜D"})
        self.assertNotIn("｜", row["profit_summary"])
        self.assertNotIn("｜", row["current_orders"])
        self.assertNotIn("｜", row["future_orders_estimate"])


if __name__ == "__main__":
    unittest.main()
