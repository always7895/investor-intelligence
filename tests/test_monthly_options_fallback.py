"""Offline monthly expiry fallback regressions through the existing producer APIs."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_market_quotes_options as builder
import option_recommendation_rules as rules
import fetch_options
import fetch_options_ibkr
from validate_v213_market_products import MarketProductValidationError, validate_covered_call_cycle

TODAY = date(2026, 11, 2)
STAMP = "2026-11-02T12:00:00Z"


def nordic_row(days, *, bid="0.30", ask="0.32", **changes):
    expiry = TODAY + timedelta(days=days)
    months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    row = {"assetClass": "OPTIONS", "fullName": f"SIVE {expiry.day:02d}{months[expiry.month - 1]}{expiry.year % 100:02d} 120C",
           "symbol": f"SIVE{expiry.year % 10}{'ABCDEFGHIJKL'[expiry.month - 1]}120", "expirationDate": expiry.isoformat(),
           "strikePrice": "120", "contractSize": "100", "currency": "SEK", "bidPrice": bid, "askPrice": ask,
           "openInterest": "10", "volume": "1"}
    row.update(changes)
    return row


def produce(days=(18, 46), **changes):
    rows = [nordic_row(day, **changes) for day in days]
    with patch.object(builder, "http_json", return_value={"data": {"instrumentListing": {"rows": rows}}}):
        return builder.nordic_options("SIVE.ST", "SIVE", 100.0, TODAY, STAMP, "synthetic", spot_currency="SEK")


WINDOW_ADMISSION_CASES = json.loads((Path(__file__).parent / "fixtures" / "options_window_cases.json").read_text(encoding="utf-8"))


def window_observations(cases):
    """Exercise production admission with actual collector output and independent, otherwise-valid boundary probes."""
    seed = produce((18,), bid="0.60", ask="0.62")["monthly"]
    collected = {day: produce((day,), bid="0.60", ask="0.62") for day in {case["dte"] for case in cases}}

    def admitted(cycle, period):
        try:
            validate_covered_call_cycle(cycle, STAMP, STAMP, period)
        except MarketProductValidationError:
            return False
        return True

    observations = []
    for case in cases:
        day, period = case["dte"], case["period"]
        probe = copy.deepcopy(seed)
        probe.update(dte=day, expiry=(TODAY + timedelta(days=day)).isoformat())
        for suggestion in probe["suggestions"]:
            suggestion["annualized_yield"] = suggestion["period_yield"] * 365 / max(day, 1)
        produced = collected[day][period]
        available = "unavailable" not in produced
        observations.append({"producer_available": available, "validator_available": admitted(probe, period),
                             "produced_validated": admitted(produced, period) if available else None,
                             "produced": produced, "probe": probe})
    return observations


class MonthlyProducerTests(unittest.TestCase):
    def test_sive_18_and_46_days_uses_existing_nordic_api(self):
        cycle = produce()["monthly"]
        self.assertNotIn("unavailable", cycle, "Listed SIVE 18/46 DTE needs the monthly fallback")
        self.assertEqual((cycle["expiry"], cycle["dte"]), ("2026-11-20", 18))
        validate_covered_call_cycle(cycle, STAMP, STAMP, "monthly")

    def test_preferred_wins_even_when_fallback_is_nearer(self):
        self.assertEqual(produce((20, 45))["monthly"]["dte"], 45)

    def test_inclusive_outer_boundaries(self):
        for day in (14, 60):
            with self.subTest(day=day):
                self.assertEqual(produce((day,), bid="0.60", ask="0.62")["monthly"]["dte"], day)

    def test_empty_outside_and_missing_quotes_stay_unavailable(self):
        for days, changes in (((), {}), ((13, 61), {}), ((18, 46), {"bid": "", "ask": ""}),
                              ((18, 46), {"currency": "USD"}), ((18, 46), {"contractSize": "10"})):
            with self.subTest(days=days, changes=changes):
                self.assertIn("unavailable", produce(days, **changes)["monthly"])

    def test_no_quote_on_preferred_does_not_choose_fallback(self):
        rows = [nordic_row(30, bid="", ask=""), nordic_row(18)]
        with patch.object(builder, "http_json", return_value={"data": {"instrumentListing": {"rows": rows}}}):
            result = builder.nordic_options("SIVE.ST", "SIVE", 100.0, TODAY, STAMP, "synthetic", spot_currency="SEK")
        self.assertIn("unavailable", result["monthly"])
        self.assertEqual(next(item for item in result.health if item["cycle"] == "monthly")["expiry"], "2026-12-02")

    def test_weekly_rule_is_unchanged(self):
        self.assertIn("unavailable", produce()["weekly"])
        self.assertEqual(produce((4, 18))["weekly"]["dte"], 4)

    def test_validator_retains_negative_gates(self):
        cycle = produce()["monthly"]
        for field, value in (("dte", 13), ("dte", 61), ("dte", True), ("dte", 19),
                             ("multiplier", 10), ("currency", "EUR"), ("timestamp", "2026-11-01T12:00:00Z"),
                             ("source", ""), ("provenance", "invalid")):
            with self.subTest(field=field, value=value):
                invalid = copy.deepcopy(cycle)
                invalid[field] = value
                with self.assertRaises(MarketProductValidationError):
                    validate_covered_call_cycle(invalid, STAMP, STAMP, "monthly")

    def test_nasdaq_fetch_window_reaches_sixty_days(self):
        def listed_window(url):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(url).query)
            expiry = date(2026, 12, 18)
            in_window = date.fromisoformat(query["fromdate"][0]) <= expiry <= date.fromisoformat(query["todate"][0])
            rows = [{"expirygroup": "December 18, 2026"},
                    {"strike": "120", "c_Bid": "0.60", "c_Ask": "0.62", "c_Openinterest": "10", "c_Volume": "1"}] if in_window else []
            return {"data": {"lastTrade": "LAST TRADE: $100.00 (AS OF NOV 2, 2026)", "table": {"rows": rows}}}
        with patch.object(builder, "http_json", side_effect=listed_window):
            result = builder.nasdaq_us_options("TEST", 100.0, TODAY, STAMP)
        self.assertEqual(result["monthly"]["dte"], 46)

    def test_yahoo_lists_and_fetches_the_selected_fallback_only(self):
        call = SimpleNamespace(strike=120.0, bid=0.30, ask=0.32, impliedVolatility=None,
                               openInterest=10, volume=1, contractSize="REGULAR", currency="USD")
        ticker = SimpleNamespace(options=["2026-11-20", "2026-12-18"])
        chain = SimpleNamespace(calls=SimpleNamespace(itertuples=lambda: iter([call])))
        with patch.dict(sys.modules, {"yfinance": SimpleNamespace(Ticker=lambda _: ticker)}):
            with patch.object(ticker, "option_chain", create=True, side_effect=lambda expiry: {"2026-11-20": chain}[expiry]):
                result = builder.us_options("TEST", 100.0, TODAY, STAMP)
        self.assertEqual((result["monthly"]["expiry"], result["monthly"]["dte"]), ("2026-11-20", 18))


class MonthlyRuleTests(unittest.TestCase):
    def test_preferred_fallback_tie_and_empty(self):
        for days, expected in (((18, 46), 18), ((20, 45), 45), ((21, 45), 21), ((14,), 14), ((60,), 60),
                               ((13, 61), None), ((), None), ((25, 35), 25)):
            with self.subTest(days=days):
                expiry = rules.select_monthly_expiry((TODAY + timedelta(days=day) for day in days), TODAY)
                self.assertEqual((expiry - TODAY).days if expiry else None, expected)

    def test_local_collectors_use_shared_selection_and_fetch_bounds(self):
        policy = {"target_dte": 30, "minimum_dte": 21, "maximum_dte": 45}
        expiries = ["2026-11-20", "2026-12-18"]
        self.assertEqual(fetch_options.select_expiration(expiries, policy, TODAY), (expiries[0], 18, "OK"))
        self.assertEqual(fetch_options_ibkr._strict_expiration(expiries, policy, today=TODAY), (expiries[0], 18, "OK"))
        self.assertEqual(fetch_options_ibkr._period_months(policy, TODAY), ["NOV26", "DEC26", "JAN27"])


if __name__ == "__main__":
    unittest.main()
