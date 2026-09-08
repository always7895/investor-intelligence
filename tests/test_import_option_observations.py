from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_option_observations import normalize

NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


def daily():
    return {"Date": "20260907", "Contract": "TXO", "ContractMonth(Week)": "202609W2",
            "StrikePrice": "20000", "CallPut": "買權", "TradingSession": "一般",
            "BestBid": "10", "BestAsk": "12", "Volume": "-", "OpenInterest": "25"}


def indicative():
    return {"quotes": {"TEST260918C00100000": {"bp": 1.0, "ap": 1.2, "t": "2026-09-08T11:59:00Z"}}}


class ImportOptionObservationsTests(unittest.TestCase):
    def test_taifex_eod_preserves_unknowns_and_session(self):
        result = normalize("taifex_eod", [daily()], now=NOW)
        self.assertEqual(result["status"], "OK")
        row = result["observations"][0]
        self.assertEqual(row["feed_type"], "END_OF_DAY")
        self.assertIsNone(row["expiry"])
        self.assertIsNone(row["quote_time"])
        self.assertIsNone(row["volume"])
        self.assertIsNone(row["retrieved_at"])
        self.assertFalse(row["publication_eligible"])
        self.assertFalse(row["executable_quote"])

    def test_taifex_trade_date_uses_taipei_not_utc_calendar(self):
        row = daily()
        row["Date"] = "20260908"
        before_utc_midnight = datetime(2026, 9, 7, 17, tzinfo=timezone.utc)
        self.assertEqual(normalize("taifex_eod", [row], now=before_utc_midnight)["status"], "OK")
        row["Date"] = "20260909"
        self.assertEqual(normalize("taifex_eod", [row], now=before_utc_midnight)["status"], "FAILED")

    def test_alpaca_indicative_is_not_independent_opra_or_nbbo(self):
        row = normalize("alpaca_indicative", indicative(), now=NOW)["observations"][0]
        self.assertEqual(row["strike"], 100)
        self.assertEqual(row["expiry"], "2026-09-18")
        self.assertEqual(row["origin"], "OPRA_DERIVED")
        self.assertEqual(row["feed_type"], "INDICATIVE_NOT_NBBO")
        self.assertIsNone(row["multiplier"])
        self.assertFalse(row["executable_quote"])

    def test_invalid_quote_values_fail_closed(self):
        for field, value in (("bp", float("nan")), ("bp", True), ("ap", -1), ("bp", 2),
                             ("t", "2026-09-09T00:00:00Z"), ("t", "2026-09-08T11:00:00")):
            with self.subTest(field=field, value=value):
                payload = indicative()
                next(iter(payload["quotes"].values()))[field] = value
                result = normalize("alpaca_indicative", payload, now=NOW)
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["observations"], [])

    def test_stale_is_not_refreshed_by_import_time(self):
        payload = indicative()
        next(iter(payload["quotes"].values()))["t"] = "2026-09-01T00:00:00Z"
        row = normalize("alpaca_indicative", payload, now=NOW)["observations"][0]
        self.assertEqual(row["freshness"], "STALE")
        self.assertTrue(row["quote_time"].startswith("2026-09-01"))

    def test_invalid_daily_fields_duplicates_and_partial_failure(self):
        for field, value in (("Volume", "1.5"), ("Date", "20260230"), ("Date", "20260909"),
                             ("CallPut", "invalid"), ("TradingSession", "unknown")):
            row = daily()
            row[field] = value
            result = normalize("taifex_eod", [daily(), row], now=NOW)
            self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(normalize("taifex_eod", [daily(), daily()], now=NOW)["status"], "PARTIAL")

    def test_unknown_metadata_is_not_copied(self):
        row = daily()
        row["account_id"] = "synthetic-private-value"
        self.assertNotIn("synthetic-private-value", json.dumps(normalize("taifex_eod", [row], now=NOW)))

    def test_real_cli_caller_and_failure_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.json"
            path.write_text(json.dumps([daily()]), encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts/import_option_observations.py"),
                       "--source", "taifex_eod", "--input", str(path)]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["mode"], "LOCAL_IMPORT_ONLY")
            path.write_text("[]")
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "NO_DATA")
            path.write_text('{"quotes": {}, "quotes": {}}')
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["error"], "INVALID_PROVIDER_EXPORT")


if __name__ == "__main__":
    unittest.main()
