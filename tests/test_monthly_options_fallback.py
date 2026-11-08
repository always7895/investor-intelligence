"""Offline monthly expiry regressions through the existing producer APIs (operator 2026-11-03: the nearest standard monthly, no minimum DTE,
no annualized-yield floor). The file name predates the rule: the former 21-45 / 14-60 fallback no longer exists."""
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
MONTHLY_CASES = json.loads((Path(__file__).parent / "fixtures" / "monthly_expiry_cases.json").read_text(encoding="utf-8"))
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def stamp_of(day: date, hour: int = 12, minute: int = 0) -> str:
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}:00Z"


def nordic_row(expiry: date | int, *, bid="0.30", ask="0.32", **changes):
    expiry = TODAY + timedelta(days=expiry) if isinstance(expiry, int) else expiry
    row = {"assetClass": "OPTIONS", "fullName": f"SIVE {expiry.day:02d}{MONTHS[expiry.month - 1]}{expiry.year % 100:02d} 120C",
           "symbol": f"SIVE{expiry.year % 10}{'ABCDEFGHIJKL'[expiry.month - 1]}120", "expirationDate": expiry.isoformat(),
           "strikePrice": "120", "contractSize": "100", "currency": "SEK", "bidPrice": bid, "askPrice": ask,
           "openInterest": "10", "volume": "1"}
    row.update(changes)
    return row


def produce(expiries=(18, 46), *, today=TODAY, stamp=STAMP, **changes):
    """The Nasdaq Nordic producer on a chain that lists the given expiries (dates, or day offsets from TODAY)."""
    rows = [nordic_row(day, **changes) for day in expiries]
    with patch.object(builder, "http_json", return_value={"data": {"instrumentListing": {"rows": rows}}}):
        return builder.nordic_options("SIVE.ST", "SIVE", 100.0, today, stamp, "synthetic", spot_currency="SEK")


WINDOW_ADMISSION_CASES = json.loads((Path(__file__).parent / "fixtures" / "options_window_cases.json").read_text(encoding="utf-8"))
MONTHLY_PROBE_FRIDAY = date(2026, 12, 18)  # a third Friday: every monthly probe expires here and the as-of date moves


def window_observations(cases):
    """Exercise production admission with actual collector output and independent, otherwise-valid boundary probes. Weekly cases run on
    TODAY; a monthly case at DTE n runs on the as-of date n days before the third Friday 2026-12-18, so the producer's own choice has
    exactly that DTE (a negative or over-60 DTE is then simply not a monthly)."""
    seed = produce((18,), bid="0.60", ask="0.62")["monthly"]
    collected = {}
    for case in cases:
        day, period = case["dte"], case["period"]
        if period == "weekly":
            collected[day, period] = (produce((day,), bid="0.60", ask="0.62")["weekly"], STAMP)
        else:
            today = MONTHLY_PROBE_FRIDAY - timedelta(days=day)
            at = stamp_of(today)
            collected[day, period] = (produce((MONTHLY_PROBE_FRIDAY,), today=today, stamp=at, bid="0.60", ask="0.62")["monthly"], at)

    def admitted(cycle, period, at=STAMP):
        try:
            validate_covered_call_cycle(cycle, at, at, period)
        except MarketProductValidationError:
            return False
        return True

    observations = []
    for case in cases:
        day, period = case["dte"], case["period"]
        probe = copy.deepcopy(seed)
        probe.update(dte=day, expiry=(TODAY + timedelta(days=day)).isoformat())
        probe.pop("monthly_rule", None)  # the seed is a monthly row: its marker describes its own expiry and never rides a weekly probe
        if period == "monthly":  # the bucket alone is under test: the as-of date describes the seed's own expiry
            probe.pop("asof_date", None)
        for suggestion in probe["suggestions"]:
            suggestion["annualized_yield"] = suggestion["period_yield"] * 365 / max(day, 1)
        produced, produced_at = collected[day, period]
        available = "unavailable" not in produced
        observations.append({"producer_available": available, "validator_available": admitted(probe, period),
                             "produced_validated": admitted(produced, period, produced_at) if available else None,
                             "produced": produced, "produced_at": produced_at, "probe": probe})
    return observations


class MonthlyProducerTests(unittest.TestCase):
    def test_sive_lists_the_nearest_monthly_with_no_minimum_dte(self):
        # The operator's case: on 2026-11-03 the SIVE.ST monthly is 2026-11-20 (17 DTE), not 2026-12-18 and not "unavailable".
        today = date(2026, 11, 3)
        cycle = produce((date(2026, 11, 20), date(2026, 12, 18)), today=today, stamp=stamp_of(today))["monthly"]
        self.assertNotIn("unavailable", cycle)
        self.assertEqual((cycle["expiry"], cycle["dte"], cycle["asof_date"], cycle["monthly_rule"]), ("2026-11-20", 17, "2026-11-03", "THIRD_FRIDAY"))
        validate_covered_call_cycle(cycle, stamp_of(today), stamp_of(today), "monthly")
        old = produce()["monthly"]  # 18 and 46 DTE from 2026-11-02 (the old fixtures)
        self.assertEqual((old["expiry"], old["dte"]), ("2026-11-20", 18))
        validate_covered_call_cycle(old, STAMP, STAMP, "monthly")

    def test_a_far_closer_expiry_is_never_replaced_by_a_nearer_30_days(self):
        for today, expected in ((date(2026, 11, 3), "2026-11-20"), (date(2026, 11, 18), "2026-12-18"), (date(2026, 11, 19), "2026-12-18")):
            with self.subTest(today=today):
                cycle = produce((date(2026, 11, 20), date(2026, 12, 18)), today=today, stamp=stamp_of(today))["monthly"]
                self.assertEqual(cycle["expiry"], expected)
                validate_covered_call_cycle(cycle, stamp_of(today), stamp_of(today), "monthly")

    def test_expiry_day_counts_until_the_stockholm_close_then_the_next_monthly(self):
        today = date(2026, 11, 20)
        listed = (date(2026, 11, 20), date(2026, 12, 18))
        before = produce(listed, today=today, stamp=stamp_of(today, 16, 29))["monthly"]  # 17:29 CET: open
        # >=7-day monthly screening now prioritizes the next regular monthly over expiry-day.
        self.assertEqual((before["expiry"], before["dte"]), ("2026-12-18", 28))
        validate_covered_call_cycle(before, stamp_of(today, 16, 29), stamp_of(today, 16, 29), "monthly")
        after = produce(listed, today=today, stamp=stamp_of(today, 16, 31))["monthly"]  # 17:31 CET: closed
        self.assertEqual((after["expiry"], after["dte"], after["monthly_rule"]), ("2026-12-18", 28, "THIRD_FRIDAY"))
        validate_covered_call_cycle(after, stamp_of(today, 16, 31), stamp_of(today, 16, 31), "monthly")

    def test_holiday_shift_and_a_month_without_a_listed_monthly(self):
        today = date(2026, 6, 1)  # the third Friday 2026-06-19 is a holiday: the latest listed expiry of that week is the monthly
        shifted = produce((date(2026, 6, 16), date(2026, 6, 18), date(2026, 7, 17)), today=today, stamp=stamp_of(today))["monthly"]
        self.assertEqual((shifted["expiry"], shifted["monthly_rule"]), ("2026-06-18", "HOLIDAY_SHIFT"))
        validate_covered_call_cycle(shifted, stamp_of(today), stamp_of(today), "monthly")
        today = date(2026, 11, 3)
        later = produce((date(2026, 12, 18),), today=today, stamp=stamp_of(today))["monthly"]
        self.assertEqual((later["expiry"], later["dte"], later["monthly_rule"]), ("2026-12-18", 45, "LATER_LISTED"))
        validate_covered_call_cycle(later, stamp_of(today), stamp_of(today), "monthly")

    def test_only_standard_monthlies_within_sixty_days_qualify(self):
        for expiries in ((), (date(2026, 11, 6), date(2026, 11, 13), date(2026, 11, 27)), (date(2026, 11, 12),), (date(2027, 1, 15),)):
            with self.subTest(expiries=expiries):
                result = produce(expiries)["monthly"]
                self.assertIn("unavailable", result)
        self.assertIn("標準月選", produce((date(2026, 11, 6),))["monthly"]["unavailable"])
        self.assertNotIn("0-60", produce(())["monthly"]["unavailable"])

    def test_empty_unquoted_is_observation_only_wrong_terms_stay_unavailable(self):
        empty = produce((18,46), bid="",ask="")["monthly"]
        self.assertEqual(empty["suggestions"], [])
        self.assertEqual(empty["quote_observation"]["kind"],"NO_TWO_SIDED")
        self.assertIsNone(empty["quote_observation"]["annualized_yield"])
        for changes in ({"currency": "USD"}, {"contractSize": "10"}):
            with self.subTest(changes=changes):
                self.assertIn("unavailable", produce((18, 46), **changes)["monthly"])

    def test_no_quote_on_the_nearest_monthly_does_not_choose_another(self):
        rows = [nordic_row(date(2026, 11, 20), bid="", ask=""), nordic_row(date(2026, 12, 18))]
        with patch.object(builder, "http_json", return_value={"data": {"instrumentListing": {"rows": rows}}}):
            result = builder.nordic_options("SIVE.ST", "SIVE", 100.0, TODAY, STAMP, "synthetic", spot_currency="SEK")
        # Next standard monthly is explicitly inspected instead of withholding the whole line.
        self.assertEqual(result["monthly"]["expiry"], "2026-12-18")
        self.assertEqual(result["monthly"]["quote_observation"]["kind"], "TWO_SIDED")
        self.assertEqual(result["monthly"]["suggestions"], [])
        self.assertEqual(next(item for item in result.health if item["cycle"] == "monthly")["expiry"], "2026-12-18")

    def test_no_annualized_yield_floor(self):
        # A real low premium remains visible as an observation, never as a 6%-qualified sell tier.
        cycle = produce((18,), bid="0.05", ask="0.06")["monthly"]
        self.assertNotIn("unavailable", cycle)
        self.assertEqual(cycle["suggestions"], [])
        item = cycle["quote_observation"]
        self.assertEqual(item["kind"], "TWO_SIDED")
        self.assertLess(item["annualized_yield"], 0.06)
        validate_covered_call_cycle(cycle, STAMP, STAMP, "monthly")

    def test_weekly_rule_is_unchanged(self):
        self.assertIn("unavailable", produce()["weekly"])
        self.assertEqual(produce((4, 18))["weekly"]["dte"], 4)

    def test_validator_retains_negative_gates(self):
        cycle = produce()["monthly"]
        for field, value in (("dte", 13), ("dte", 61), ("dte", -1), ("dte", True), ("dte", 19),
                             ("multiplier", 10), ("currency", "EUR"), ("timestamp", "2026-11-01T12:00:00Z"),
                             ("source", ""), ("provenance", "invalid"), ("monthly_rule", "BOGUS"), ("monthly_rule", "HOLIDAY_SHIFT")):
            with self.subTest(field=field, value=value):
                invalid = copy.deepcopy(cycle)
                invalid[field] = value
                with self.assertRaises(MarketProductValidationError):
                    validate_covered_call_cycle(invalid, STAMP, STAMP, "monthly")
        weekly_marker = copy.deepcopy(cycle)
        with self.assertRaises(MarketProductValidationError):
            validate_covered_call_cycle(weekly_marker, STAMP, STAMP, "weekly")  # a monthly_rule never marks a weekly

    def test_validator_accepts_a_row_without_the_marker_and_the_old_fourteen_day_row(self):
        cycle = produce()["monthly"]
        cycle.pop("monthly_rule")  # rows sealed by the previous producer have none
        validate_covered_call_cycle(cycle, STAMP, STAMP, "monthly")
        old_fallback = copy.deepcopy(cycle)  # the old producer's 14 DTE fallback row, with its asof_date
        old_fallback.update(dte=14, expiry="2026-11-16")
        for suggestion in old_fallback["suggestions"]:
            suggestion["annualized_yield"] = suggestion["period_yield"] * 365 / 14
        validate_covered_call_cycle(old_fallback, STAMP, STAMP, "monthly")

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
        self.assertEqual((result["monthly"]["dte"], result["monthly"]["monthly_rule"]), (46, "LATER_LISTED"))

    def test_yahoo_lists_and_fetches_the_selected_monthly_only(self):
        call = SimpleNamespace(strike=120.0, bid=0.30, ask=0.32, impliedVolatility=None,
                               openInterest=10, volume=1, contractSize="REGULAR", currency="USD")
        ticker = SimpleNamespace(options=["2026-11-20", "2026-12-18"])
        chain = SimpleNamespace(calls=SimpleNamespace(itertuples=lambda: iter([call])))
        with patch.dict(sys.modules, {"yfinance": SimpleNamespace(Ticker=lambda _: ticker)}):
            with patch.object(ticker, "option_chain", create=True, side_effect=lambda expiry: {"2026-11-20": chain}[expiry]):
                result = builder.us_options("TEST", 100.0, TODAY, STAMP)
        self.assertEqual((result["monthly"]["expiry"], result["monthly"]["dte"], result["monthly"]["monthly_rule"]), ("2026-11-20", 18, "THIRD_FRIDAY"))

    def test_yahoo_us_expiry_day_after_the_new_york_close_takes_the_next_monthly(self):
        call = SimpleNamespace(strike=120.0, bid=0.30, ask=0.32, impliedVolatility=None,
                               openInterest=10, volume=1, contractSize="REGULAR", currency="USD")
        ticker = SimpleNamespace(options=["2026-11-20", "2026-12-18"])
        chain = SimpleNamespace(calls=SimpleNamespace(itertuples=lambda: iter([call])))
        today = date(2026, 11, 20)
        for stamp, expected in ((stamp_of(today, 20, 59), "2026-11-20"), (stamp_of(today, 21, 1), "2026-12-18")):  # 15:59 / 16:01 EST
            with self.subTest(stamp=stamp):
                with patch.dict(sys.modules, {"yfinance": SimpleNamespace(Ticker=lambda _: ticker)}):
                    with patch.object(ticker, "option_chain", create=True, side_effect=lambda expiry: chain):
                        result = builder.us_options("TEST", 100.0, today, stamp)
                self.assertEqual(result["monthly"]["expiry"], expected)


class MonthlyRuleTests(unittest.TestCase):
    def test_shared_cases(self):
        for row in MONTHLY_CASES:
            with self.subTest(row["name"]):
                days = []
                for text in row["expiries"]:
                    try:
                        days.append(date.fromisoformat(text))
                    except ValueError:
                        pass
                choice = rules.select_monthly(days, date.fromisoformat(row["as_of"]), expiry_day_open_now=row.get("expiry_day_open", True))
                self.assertEqual(choice.expiry.isoformat() if choice else None, row["expected"])
                self.assertEqual(choice.rule if choice else None, row["rule"])
                self.assertEqual(rules.select_monthly_expiry(days, date.fromisoformat(row["as_of"]),
                                                              expiry_day_open_now=row.get("expiry_day_open", True)), choice.expiry if choice else None)

    def test_constants_and_the_removed_fallback(self):
        self.assertEqual(rules.MONTHLY_DTE_BUCKET, (0, 60))
        self.assertEqual(rules.WEEKLY_DTE_BUCKET, (0, 14))
        self.assertFalse(hasattr(rules, "MONTHLY_FALLBACK_DTE_BUCKET"))
        self.assertEqual(rules.MONTHLY_RULES, ("THIRD_FRIDAY", "HOLIDAY_SHIFT", "LATER_LISTED"))
        self.assertEqual(rules.third_friday(2026, 11), date(2026, 11, 20))
        self.assertEqual(rules.third_friday(2027, 1), date(2027, 1, 15))

    def test_the_operator_examples(self):
        listed = [date(2026, 11, 20), date(2026, 12, 18)]
        for as_of, open_now, expected in ((date(2026, 11, 3), True, date(2026, 11, 20)), (date(2026, 11, 20), True, date(2026, 11, 20)),
                                           (date(2026, 11, 20), False, date(2026, 12, 18))):
            self.assertEqual(rules.select_monthly_expiry(listed, as_of, expiry_day_open_now=open_now), expected)

    def test_local_collectors_use_shared_selection_and_fetch_bounds(self):
        expiries = ["2026-11-20", "2026-12-18"]
        for policy in ({"selection": "monthly", "target_dte": 30, "minimum_dte": 0, "maximum_dte": 60},
                       {"target_dte": 30, "minimum_dte": 21, "maximum_dte": 45}):  # an older config/options-policy.json is overridden
            self.assertEqual(fetch_options.select_expiration(expiries, policy, TODAY), (expiries[0], 18, "OK"))
            self.assertEqual(fetch_options_ibkr._strict_expiration(expiries, policy, today=TODAY), (expiries[0], 18, "OK"))
            self.assertEqual(fetch_options_ibkr._period_months(policy, TODAY), ["NOV26", "DEC26", "JAN27"])
        self.assertEqual(fetch_options.DEFAULT_POLICY["periods"]["monthly"]["minimum_dte"], 0)
        self.assertEqual(fetch_options.DEFAULT_POLICY["periods"]["monthly"]["maximum_dte"], 60)
        policy = {"selection": "monthly", "target_dte": 30}
        expiry_day = date(2026, 11, 20)
        self.assertEqual(fetch_options_ibkr._strict_expiration(expiries, policy, today=expiry_day, expiry_day_open_now=True), (expiries[0], 0, "OK"))
        self.assertEqual(fetch_options_ibkr._strict_expiration(expiries, policy, today=expiry_day, expiry_day_open_now=False), (expiries[1], 28, "OK"))


if __name__ == "__main__":
    unittest.main()
