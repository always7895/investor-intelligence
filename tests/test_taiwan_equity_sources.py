from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from adapters import AdapterError
from adapters.staged_public import parse_source_payload
from adapters.base import json_document
from fetch_public_source_observations import collect


def twse():
    return {"Date": "1150908", "Code": "2330", "OpeningPrice": "100", "HighestPrice": "102",
            "LowestPrice": "99", "ClosingPrice": "101", "TradeVolume": "1000"}


class TaiwanEquitySourceTests(unittest.TestCase):
    def parse(self, rows, source="twse_equity_eod"):
        return parse_source_payload(source, json.dumps(rows).encode(), content_type="application/json",
                                    retrieved_at="2026-09-08T16:00:00Z")

    def test_twse_trade_date_currency_and_raw_price_semantics(self):
        row = self.parse([twse()]).records[0]
        self.assertEqual(row["trade_date"], "2026-09-08")
        self.assertEqual(row["currency"], "TWD")
        self.assertEqual(row["venue"], "TWSE")
        self.assertEqual(row["price_adjustment"], "UNADJUSTED")
        self.assertIsNone(row["quote_time"])
        self.assertFalse(row["executable_quote"])
        self.assertFalse(row["publication_eligible"])

    def test_tpex_preserves_distinct_security_venue(self):
        row = {"Date": "1150908", "SecuritiesCompanyCode": "6488", "Open": "100",
               "High": "102", "Low": "99", "Close": "101", "TradingShares": "2000"}
        self.assertEqual(self.parse([row], "tpex_equity_eod").records[0]["venue"], "TPEX")

    def test_missing_close_is_not_invented(self):
        row = twse()
        for missing in ("--", " ---", "--- "):
            row["ClosingPrice"] = missing
            observation = self.parse([row]).records[0]
            self.assertIsNone(observation["close"])
            self.assertEqual(observation["quote_status"], "MISSING_CLOSE")

    def test_bad_ohlc_future_dates_and_counts_rejected(self):
        for field, value in (("ClosingPrice", "999"), ("HighestPrice", "90"),
                             ("Date", "1150230"), ("Date", "1150910"),
                             ("TradeVolume", "1.5"), ("ClosingPrice", True)):
            row = twse()
            row[field] = value
            with self.subTest(field=field), self.assertRaises(AdapterError):
                self.parse([row])

    def test_duplicate_rows_do_not_inflate_coverage(self):
        result = self.parse([twse(), twse()])
        self.assertEqual(result.record_count, 1)
        self.assertEqual(result.warnings, ("INVALID_EQUITY_ROW:1",))

    def test_shared_json_parser_rejects_duplicates_and_nonfinite_values(self):
        for body in (b'{"close":1,"close":2}', b'{"close":NaN}', b'{"close":Infinity}'):
            with self.assertRaises(AdapterError):
                json_document(body)

    def test_equity_collector_actual_caller_preserves_origin(self):
        result = collect(["twse_equity_eod"], transport=lambda _: json.dumps([twse()]).encode())
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["items"][0]["origin"], "twse.com.tw")
        self.assertIn("content_sha256", result["items"][0])


if __name__ == "__main__":
    unittest.main()
