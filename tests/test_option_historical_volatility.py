"""Explicitly synthetic chart bytes; no market claims, files, or network."""
from __future__ import annotations

import hashlib
import json
import math
import sys
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import option_historical_volatility as history  # noqa: E402

CAPTURE = date(2026, 11, 9)
TICKER = "SYNTH"
URL = "https://query1.finance.yahoo.com/v8/finance/chart/SYNTH?interval=1d&includeAdjustedClose=true"
WIRE_KEYS = {
    "ticker", "currency", "hv20", "hv60", "observations", "start_date_20",
    "start_date_60", "asof_date", "source_url", "source_sha256", "price_basis",
}


def synthetic_chart(count: int = 61, *, currency: str = "USD", ticker: str = TICKER,
                    end: date = date(2026, 11, 6)) -> dict[str, Any]:
    days = []
    day = end
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    # Alternating +/- 1% log returns yield an analytic sample sigma.
    prices = [100.0 * math.exp(0.01 if index % 2 else 0.0) for index in range(count)]
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": ticker, "currency": currency, "instrumentType": "EQUITY", "dataGranularity": "1d"},
        "timestamp": [int(datetime.combine(day, time(16), timezone.utc).timestamp()) for day in days],
        "indicators": {"adjclose": [{"adjclose": prices}], "quote": [{"close": [999.0] * count}]},
    }]}}


def result(chart: dict[str, Any]) -> dict[str, Any]:
    return chart["chart"]["result"][0]


def raw_bytes(chart: dict[str, Any]) -> bytes:
    return json.dumps(chart, separators=(",", ":")).encode("utf-8")


def calculate(chart: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None:
    args = {"ticker": TICKER, "currency": "USD", "capture_date": CAPTURE, "source_url": URL}
    args.update(kwargs)
    return history.from_yahoo_chart(raw_bytes(chart), **args)


class HistoricalCalculationTests(unittest.TestCase):
    def evidence(self, count: int = 61) -> dict[str, Any]:
        evidence = calculate(synthetic_chart(count))
        self.assertIsNotNone(evidence)
        assert evidence is not None
        return evidence

    def test_both_analytic_sample_log_sigmas_and_exact_wire_keys(self) -> None:
        evidence = self.evidence()
        self.assertEqual(set(evidence), WIRE_KEYS)
        self.assertEqual(evidence["observations"], 61)
        for window in (20, 60):
            self.assertAlmostEqual(evidence[f"hv{window}"], math.sqrt(window * 0.01 ** 2 / (window - 1) * 252), places=12)
        self.assertEqual(evidence["price_basis"], "PROVIDER_ADJUSTED_CLOSE")
        self.assertLess(evidence["start_date_60"], evidence["start_date_20"])
        self.assertTrue(history.valid_historical_volatility(evidence, TICKER, "USD", CAPTURE))

    def test_sixty_one_closes_required_without_twenty_only_fallback(self) -> None:
        for count in (0, 20, 21, 60):
            self.assertIsNone(calculate(synthetic_chart(count)), count)
        for count in (61, 80):
            self.assertEqual(self.evidence(count)["observations"], 61)
        preferred = synthetic_chart(61)
        result(preferred)["indicators"]["adjclose"][0]["adjclose"][0] = None
        self.assertIsNone(calculate(preferred))  # Never accept just the intact last 21 closes.

    def test_windows_use_their_actual_latest_closes(self) -> None:
        chart = synthetic_chart(61)
        prices = [100.0]
        for index in range(60):
            magnitude = 0.02 if index < 40 else 0.005
            prices.append(prices[-1] * math.exp(magnitude if index % 2 else -magnitude))
        result(chart)["indicators"]["adjclose"][0]["adjclose"] = prices
        actual = calculate(chart)
        assert actual is not None
        self.assertAlmostEqual(actual["hv20"], math.sqrt(20 * 0.005 ** 2 / 19 * 252), places=12)
        self.assertAlmostEqual(actual["hv60"], math.sqrt((40 * 0.02 ** 2 + 20 * 0.005 ** 2) / 59 * 252), places=12)
        stamps = result(chart)["timestamp"]
        self.assertEqual(actual["start_date_20"], datetime.fromtimestamp(stamps[-21], timezone.utc).date().isoformat())
        self.assertEqual(actual["start_date_60"], datetime.fromtimestamp(stamps[-61], timezone.utc).date().isoformat())

    def test_only_selected_prices_are_required_but_not_interpolated(self) -> None:
        chart = synthetic_chart(80)
        prices = result(chart)["indicators"]["adjclose"][0]["adjclose"]
        prices[0] = None
        self.assertIsNotNone(calculate(chart))
        for invalid in (None, True, False, "100", 0, -1, float("inf"), float("nan"), 10 ** 400):
            with self.subTest(invalid=str(invalid)):
                prices[-2] = invalid
                self.assertIsNone(calculate(chart))

    def test_raw_hash_binds_bytes_not_reserialized_json(self) -> None:
        raw = raw_bytes(synthetic_chart())
        padded = b" \n" + raw + b"\n"
        first = history.from_yahoo_chart(raw, TICKER, "USD", CAPTURE, URL)
        second = history.from_yahoo_chart(padded, TICKER, "USD", CAPTURE, URL)
        assert first is not None and second is not None
        self.assertEqual(first["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(second["source_sha256"], hashlib.sha256(padded).hexdigest())
        self.assertNotEqual(first["source_sha256"], second["source_sha256"])
        self.assertEqual((first["hv20"], first["hv60"]), (second["hv20"], second["hv60"]))

    def test_same_day_and_future_prices_do_not_affect_either_window(self) -> None:
        chart = synthetic_chart()
        baseline = calculate(chart)
        assert baseline is not None
        for day, close in ((CAPTURE, None), (CAPTURE + timedelta(days=1), 1e300)):
            result(chart)["timestamp"].append(int(datetime.combine(day, time(16), timezone.utc).timestamp()))
            result(chart)["indicators"]["adjclose"][0]["adjclose"].append(close)
        actual = calculate(chart)
        assert actual is not None
        for key in WIRE_KEYS - {"source_sha256"}:
            self.assertEqual(actual[key], baseline[key], key)
        self.assertNotEqual(actual["source_sha256"], baseline["source_sha256"])
        self.assertIsNone(calculate(synthetic_chart(61, end=date(2027, 3, 8))))
        short = synthetic_chart(60)
        result(short)["timestamp"].append(int(datetime(2026, 11, 9, 16, tzinfo=timezone.utc).timestamp()))
        result(short)["indicators"]["adjclose"][0]["adjclose"].append(100.0)
        self.assertIsNone(calculate(short))

    def test_exchange_local_cutoff_not_utc_date(self) -> None:
        capture = date(2026, 11, 10)
        chart = synthetic_chart(61, end=date(2026, 11, 9))
        result(chart)["timestamp"][-1] = int(datetime(2026, 11, 10, 0, 30, tzinfo=timezone.utc).timestamp())
        usd = calculate(chart, capture_date=capture)
        assert usd is not None
        self.assertEqual(usd["asof_date"], "2026-11-09")
        result(chart)["meta"]["currency"] = "SEK"
        self.assertIsNone(calculate(chart, currency="SEK", capture_date=capture))
        self.assertIsNotNone(calculate(synthetic_chart(currency="SEK"), currency="SEK"))

    def test_adjusted_close_is_mandatory_and_quote_close_irrelevant(self) -> None:
        chart = synthetic_chart()
        baseline = calculate(chart)
        result(chart)["indicators"]["quote"][0]["close"] = [None] * 61
        changed = calculate(chart)
        assert baseline is not None and changed is not None
        self.assertEqual((baseline["hv20"], baseline["hv60"]), (changed["hv20"], changed["hv60"]))
        del result(chart)["indicators"]["adjclose"]
        self.assertIsNone(calculate(chart))

    def test_bad_selected_dates_and_timestamp_arrays_fail_closed(self) -> None:
        for kind in ("duplicate", "same_date", "unsorted", "weekend", "null", "boolean", "huge", "length"):
            with self.subTest(kind=kind):
                chart = synthetic_chart()
                stamps = result(chart)["timestamp"]
                if kind == "duplicate":
                    stamps[-2] = stamps[-3]
                elif kind == "same_date":
                    stamps[-2] = stamps[-3] + 60
                elif kind == "unsorted":
                    stamps[-2], stamps[-3] = stamps[-3], stamps[-2]
                elif kind == "weekend":
                    stamps[-1] = int(datetime(2026, 11, 7, 16, tzinfo=timezone.utc).timestamp())
                elif kind == "null":
                    stamps[-1] = None
                elif kind == "boolean":
                    stamps[-1] = True
                elif kind == "huge":
                    stamps[-1] = 1e100
                else:
                    stamps.pop()
                self.assertIsNone(calculate(chart))

    def test_freshness_span_and_zero_variance_is_real_data(self) -> None:
        for age in (1, 4):
            self.assertIsNotNone(calculate(synthetic_chart(), capture_date=date(2026, 11, 6) + timedelta(days=age)))
        self.assertIsNone(calculate(synthetic_chart(), capture_date=date(2026, 11, 11)))
        sparse = synthetic_chart()
        result(sparse)["timestamp"][0] -= 100 * 86400
        self.assertIsNone(calculate(sparse))
        for prices in ([100.0] * 61, [2.0 ** i for i in range(61)]):
            chart = synthetic_chart()
            result(chart)["indicators"]["adjclose"][0]["adjclose"] = prices
            evidence = calculate(chart)
            assert evidence is not None
            self.assertEqual((evidence["hv20"], evidence["hv60"]), (0.0, 0.0))

    def test_malformed_payloads_and_identity(self) -> None:
        for field, invalid in (("symbol", "OTHER"), ("currency", "EUR"), ("instrumentType", "INDEX"), ("dataGranularity", "1h")):
            chart = synthetic_chart()
            result(chart)["meta"][field] = invalid
            self.assertIsNone(calculate(chart), field)
        for invalid in (b"", b"{", b"null", b"[]", b"\xff", b" " * (8 * 1024 * 1024 + 1), b'{"chart":null,"chart":{}}'):
            self.assertIsNone(history.from_yahoo_chart(invalid, TICKER, "USD", CAPTURE, URL))
        for results in ([], [result(synthetic_chart()), result(synthetic_chart())], [None]):
            self.assertIsNone(calculate({"chart": {"result": results}}))
        chart = synthetic_chart()
        chart["chart"]["error"] = {"code": "Unavailable"}
        self.assertIsNone(calculate(chart))
        self.assertIsNone(calculate(synthetic_chart(4097)))
        for capture in ("2026-11-09", datetime(2026, 11, 9), None):
            self.assertIsNone(calculate(synthetic_chart(), capture_date=capture))
        for ticker in ("", " SYNTH", "synth", "../SYNTH", "A..B", "A" * 33, "SYNTH/OTHER"):
            self.assertIsNone(calculate(synthetic_chart(ticker=ticker), ticker=ticker, source_url=URL.replace(TICKER, ticker)))


class HistoricalMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        evidence = calculate(synthetic_chart())
        assert evidence is not None
        self.evidence = evidence

    def valid(self, value: Any, **kwargs: Any) -> bool:
        args = {"ticker": TICKER, "currency": "USD", "capture_date": CAPTURE}
        args.update(kwargs)
        return history.valid_historical_volatility(value, **args)

    def test_exact_keys_and_identity(self) -> None:
        for key in WIRE_KEYS:
            value = dict(self.evidence)
            del value[key]
            self.assertFalse(self.valid(value), key)
        self.assertFalse(self.valid({**self.evidence, "extra": 1}))
        self.assertFalse(self.valid({**self.evidence, "annualized_volatility": 0.2}))
        for value in (None, [], "", 1, True):
            self.assertFalse(self.valid(value))
        self.assertFalse(self.valid(self.evidence, ticker="OTHER"))
        self.assertFalse(self.valid(self.evidence, currency="SEK"))
        self.assertFalse(self.valid(self.evidence, currency="EUR"))
        self.assertFalse(self.valid(self.evidence, capture_date=datetime(2026, 11, 9)))

    def test_numeric_date_hash_and_basis_guards(self) -> None:
        bad_sigmas = [True, False, -0.2, "0.2", None, float("inf"), float("nan"), 10 ** 400]
        invalids = {
            "hv20": bad_sigmas, "hv60": bad_sigmas,
            "observations": [True, 21, 60, 62, "61", float("inf")],
            "start_date_20": ["2026-02-30", "2026-11-05", "2026-01-01", "2026-10-10", "0000-01-01", "2026-9-14"],
            "start_date_60": ["2026-02-30", "2026-11-05", "2026-01-01", "2026-08-15", "0000-01-01", "2026-8-14"],
            "asof_date": ["2026-11-09", "2026-11-10", "2026-11-04", "2026-11-07", "2026-02-30", None],
            "price_basis": ["CLOSE", "ADJUSTED_CLOSE", None],
            "source_sha256": ["a" * 63, "a" * 65, "A" * 64, "g" * 64, None],
        }
        for key, bad_values in invalids.items():
            for bad in bad_values:
                with self.subTest(key=key, bad=str(bad)):
                    self.assertFalse(self.valid({**self.evidence, key: bad}))
        self.assertTrue(self.valid({**self.evidence, "hv20": 0, "hv60": 0}))
        self.assertFalse(self.valid({**self.evidence, "start_date_60": self.evidence["start_date_20"]}))
        # Standalone validation checks hash syntax; byte verification needs the raw source.
        self.assertTrue(self.valid({**self.evidence, "source_sha256": "a" * 64}))

    def test_source_url_allowlist_guards_both_entrypoints(self) -> None:
        prefix = "https://query1.finance.yahoo.com"
        bad_urls = [
            URL.replace("https:", "http:"), URL.replace("query1", "query2"),
            URL.replace(".com/", ".com.evil/"), URL.replace(".com/", ".com:444/"),
            URL.replace("https://", "https://user@"), URL + "#", URL + "#fragment",
            URL.replace("/SYNTH?", "/OTHER?"), URL + "&token=secret", URL + "&%74oken=secret",
            URL + "&unknown=1", " " + URL, URL + "\n", URL.replace("/v8/", "\\v8/"),
            prefix + "/v8/finance/chart/%53YNTH", prefix + "/v8/finance/chart/../chart/SYNTH",
        ]
        for source_url in bad_urls:
            with self.subTest(source_url=source_url):
                self.assertFalse(self.valid({**self.evidence, "source_url": source_url}))
                self.assertIsNone(calculate(synthetic_chart(), source_url=source_url))
        for source_url in (URL, URL.replace(".com/", ".com:443/"), prefix + "/v8/finance/chart/SYNTH?period1=1&period2=2&range=6mo&events=history"):
            self.assertTrue(self.valid({**self.evidence, "source_url": source_url}))


if __name__ == "__main__":
    unittest.main()
