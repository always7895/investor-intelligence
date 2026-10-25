"""Operator 2026-10-11: the middle covered-call tier and the current-calendar-week weekly expiry.

Real callers (builder.us_options, builder._cycles_from_calls, builder.cycle_result, validate_covered_call_cycle, the shared rules
module), fake chains only, fixed clocks, no network. The operator's example: as of Wed 2026-10-07 with 2026-10-09 and 2026-10-16
listed the weekly is 2026-10-09 (never 2026-10-16); as of Sat 2026-10-10 it is 2026-10-16.
"""
from __future__ import annotations

import copy
import math
import sys
import types
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import option_recommendation_rules as rules  # noqa: E402
from validate_v213_market_products import MarketProductValidationError, validate_covered_call_cycle  # noqa: E402

D = date
LISTED = [D(2026, 10, 9), D(2026, 10, 16)]


def utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class ExchangeClockTests(unittest.TestCase):
    def test_us_date_follows_new_york_not_utc_across_both_dst_edges(self):
        # The 08:00 Taipei briefing is 00:00 UTC = 20:00 New York of the PREVIOUS day.
        self.assertEqual(rules.exchange_date(utc("2026-10-07T00:30:00Z"), "US"), D(2026, 10, 6))
        self.assertEqual(rules.exchange_date(utc("2026-10-07T14:00:00Z"), "US"), D(2026, 10, 7))
        # spring forward 2026-03-08 07:00 UTC; fall back 2026-11-01 06:00 UTC
        self.assertEqual(rules.exchange_local(utc("2026-03-08T06:59:00Z"), "US").strftime("%H:%M"), "01:59")
        self.assertEqual(rules.exchange_local(utc("2026-03-08T07:00:00Z"), "US").strftime("%H:%M"), "03:00")
        self.assertEqual(rules.exchange_local(utc("2026-11-01T05:59:00Z"), "US").strftime("%H:%M"), "01:59")
        self.assertEqual(rules.exchange_local(utc("2026-11-01T06:00:00Z"), "US").strftime("%H:%M"), "01:00")
        self.assertEqual(rules.exchange_date(utc("2026-11-02T04:59:00Z"), "US"), D(2026, 11, 1))

    def test_stockholm_and_taipei_clocks(self):
        self.assertEqual(rules.exchange_date(utc("2026-10-07T22:30:00Z"), "STOCKHOLM"), D(2026, 10, 8))   # CEST +2
        self.assertEqual(rules.exchange_date(utc("2026-12-01T23:30:00Z"), "STOCKHOLM"), D(2026, 12, 2))   # CET +1
        self.assertEqual(rules.exchange_local(utc("2026-03-29T00:59:00Z"), "STOCKHOLM").strftime("%H:%M"), "01:59")
        self.assertEqual(rules.exchange_local(utc("2026-03-29T01:00:00Z"), "STOCKHOLM").strftime("%H:%M"), "03:00")
        self.assertEqual(rules.exchange_date(utc("2026-10-09T17:00:00Z"), "TAIFEX"), D(2026, 10, 10))
        with self.assertRaises(ValueError):
            rules.exchange_date(utc("2026-10-09T17:00:00Z"), "MOON")
        with self.assertRaises(ValueError):
            rules.exchange_local(datetime(2026, 10, 9, 17, 0), "US")

    def test_expiry_day_is_open_only_before_the_regular_session_close(self):
        for venue, before, at in (("US", "2026-10-09T19:59:00Z", "2026-10-09T20:00:00Z"),
                                  ("STOCKHOLM", "2026-10-09T15:29:00Z", "2026-10-09T15:30:00Z"),
                                  ("TAIFEX", "2026-10-09T05:29:00Z", "2026-10-09T05:30:00Z")):
            self.assertTrue(rules.expiry_day_open(utc(before), venue), venue)
            self.assertFalse(rules.expiry_day_open(utc(at), venue), venue)


class WeeklyRuleTests(unittest.TestCase):
    def pick(self, listed, as_of, open_now=True):
        choice = rules.select_weekly_expiry(listed, as_of, expiry_day_open_now=open_now)
        return None if choice is None else (choice.expiry, choice.week)

    def test_the_operators_example_wednesday_picks_this_fridays_expiry_not_next_weeks(self):
        self.assertEqual(self.pick(LISTED, D(2026, 10, 7)), (D(2026, 10, 9), "CURRENT"))
        self.assertEqual((D(2026, 10, 9) - D(2026, 10, 7)).days, 2)
        self.assertEqual(self.pick(LISTED, D(2026, 10, 8)), (D(2026, 10, 9), "CURRENT"))
        self.assertEqual(self.pick(LISTED, D(2026, 10, 5)), (D(2026, 10, 9), "CURRENT"))  # Monday of the same week

    def test_weekend_and_after_the_last_weekly_use_the_earliest_expiry_of_next_week(self):
        self.assertEqual(self.pick(LISTED, D(2026, 10, 10)), (D(2026, 10, 16), "NEXT"))  # Saturday
        self.assertEqual(self.pick(LISTED, D(2026, 10, 11)), (D(2026, 10, 16), "NEXT"))  # Sunday
        self.assertEqual(self.pick(LISTED, D(2026, 10, 9), open_now=False), (D(2026, 10, 16), "NEXT"))  # Friday after the close

    def test_the_expiry_day_counts_while_the_session_is_open_with_dte_zero(self):
        self.assertEqual(self.pick(LISTED, D(2026, 10, 9), open_now=True), (D(2026, 10, 9), "CURRENT"))

    def test_the_earliest_listed_expiry_wins_so_mon_wed_fri_series_return_the_first_one(self):
        listed = [D(2026, 10, 12), D(2026, 10, 14), D(2026, 10, 16)]
        self.assertEqual(self.pick(listed, D(2026, 10, 12)), (D(2026, 10, 12), "CURRENT"))
        self.assertEqual(self.pick(listed, D(2026, 10, 13)), (D(2026, 10, 14), "CURRENT"))
        self.assertEqual(self.pick(listed, D(2026, 10, 15)), (D(2026, 10, 16), "CURRENT"))

    def test_nothing_beyond_next_week_is_ever_a_weekly_and_the_old_3_to_14_window_is_gone(self):
        self.assertIsNone(self.pick([D(2026, 10, 23)], D(2026, 10, 7)))            # two weeks out
        self.assertIsNone(self.pick([D(2026, 10, 19)], D(2026, 10, 7)))            # Monday of the week after next
        self.assertEqual(self.pick([D(2026, 10, 18)], D(2026, 10, 7)), (D(2026, 10, 18), "NEXT"))  # next Sunday is the last day
        self.assertIsNone(self.pick([D(2026, 10, 6)], D(2026, 10, 7)))             # already expired
        self.assertIsNone(self.pick([], D(2026, 10, 7)))

    def test_taifex_wednesday_and_friday_weeklies_use_only_listed_dates(self):
        listed = [D(2026, 10, 7), D(2026, 10, 9), D(2026, 10, 14), D(2026, 10, 16)]
        self.assertEqual(self.pick(listed, D(2026, 10, 5)), (D(2026, 10, 7), "CURRENT"))   # Monday -> this Wednesday
        self.assertEqual(self.pick(listed, D(2026, 10, 6)), (D(2026, 10, 7), "CURRENT"))
        self.assertEqual(self.pick(listed, D(2026, 10, 8)), (D(2026, 10, 9), "CURRENT"))   # Thursday -> this Friday
        self.assertEqual(self.pick(listed, D(2026, 10, 10)), (D(2026, 10, 14), "NEXT"))    # Saturday -> next Wednesday
        self.assertEqual(self.pick(listed, D(2026, 10, 7), open_now=False), (D(2026, 10, 9), "CURRENT"))  # Wednesday after the close

    def test_week_helpers_and_the_calendar_week_window(self):
        self.assertEqual(rules.week_end(D(2026, 10, 7)), D(2026, 10, 11))
        self.assertEqual(rules.week_end(D(2026, 10, 11)), D(2026, 10, 11))
        self.assertEqual(rules.week_end(D(2026, 10, 12)), D(2026, 10, 18))
        self.assertEqual(rules.weekly_window_end(D(2026, 10, 7)), D(2026, 10, 18))
        for expiry, as_of, expected in ((D(2026, 10, 9), D(2026, 10, 7), "CURRENT"), (D(2026, 10, 16), D(2026, 10, 7), "NEXT"),
                                        (D(2026, 10, 18), D(2026, 10, 7), "NEXT"), (D(2026, 10, 19), D(2026, 10, 7), None),
                                        (D(2026, 10, 6), D(2026, 10, 7), None), (D(2026, 10, 7), D(2026, 10, 7), "CURRENT")):
            self.assertEqual(rules.weekly_week_for(expiry, as_of), expected, (expiry, as_of))

    def test_tiny_dte_annualizes_over_at_least_one_day(self):
        self.assertEqual([rules.effective_days(d) for d in (0, 1, 2, 30)], [1, 1, 2, 30])
        self.assertEqual(rules.SHORT_DTE_NOTICE_MAX, 2)


class MiddleRuleTests(unittest.TestCase):
    def test_pick_middle_is_strictly_between_and_nearest_the_middle_delta(self):
        rows = [{"strike": 110, "delta": 0.12}, {"strike": 108, "delta": 0.27}, {"strike": 107, "delta": 0.24}, {"strike": 106, "delta": 0.28}]
        self.assertEqual(rules.pick_middle(rows, 112, 105, 100.0)["strike"], 107)       # 0.24 is nearest 0.25
        self.assertEqual(rules.pick_middle(rows, 110, 106, 100.0)["strike"], 107)       # the bounds themselves never qualify
        self.assertIsNone(rules.pick_middle(rows, 108, 107, 100.0))                     # no listed strike strictly between
        tie = [{"strike": 108, "delta": 0.125}, {"strike": 109, "delta": 0.375}]  # exactly 0.125 either side of 0.25
        self.assertEqual(rules.pick_middle(tie, 112, 105, 100.0)["strike"], 109)         # ties go to the higher strike

    def test_without_deltas_the_strike_nearest_the_middle_moneyness_wins(self):
        rows = [{"strike": 110, "delta": None}, {"strike": 102.5, "delta": None}, {"strike": 104, "delta": None}]
        self.assertEqual(rules.pick_middle(rows, 112, 101, 100.0)["strike"], 102.5)
        mixed = [{"strike": 110, "delta": 0.1}, {"strike": 103, "delta": None}]
        self.assertEqual(rules.pick_middle(mixed, 112, 101, 100.0)["strike"], 103)       # one missing delta: moneyness for all

    def test_limit_range_middle_is_on_the_tick_and_ordered(self):
        self.assertEqual(rules.round_tick(1.075), 1.08)
        self.assertEqual(rules.limit_middle(1.05, 1.10), 1.08)
        self.assertEqual(rules.limit_middle(2.00, 2.00), 2.00)
        self.assertEqual(rules.limit_middle(1.00, 1.01), 1.01)
        self.assertEqual(rules.limit_middle(3.40, 3.00), 3.20)                           # arguments in either order
        for low, high in ((0.01, 0.02), (4.25, 4.50), (0.37, 0.39), (12.34, 12.36)):
            middle = rules.limit_middle(low, high)
            self.assertTrue(low <= middle <= high, (low, high, middle))
            self.assertEqual(middle, round(middle, 2))
        self.assertEqual(rules.limit_middle(0.10, 0.20, tick=0.05), 0.15)


def q(strike, bid, ask, delta, **extra):
    return {"strike": strike, "bid": bid, "ask": ask, "delta": delta, "iv": None, "oi": 10, "volume": 1, **extra}


# spot 100, DTE 2: HIGH 112 (delta .08), MIDDLE 108 (delta .20, nearest .25 among 110/.12 and 108/.20), BALANCED 106 (.28 nearest .30)
CHAIN = [q(112.0, 0.10, 0.12, 0.08), q(110.0, 0.20, 0.24, 0.12), q(108.0, 0.35, 0.40, 0.20), q(106.0, 0.60, 0.66, 0.28), q(104.0, 1.10, 1.20, 0.40)]


class TierProducerTests(unittest.TestCase):
    def test_three_tiers_high_middle_balanced_with_strictly_descending_strikes(self):
        suggestions, middle = builder.covered_call_tiers(CHAIN, 100.0, 2)
        self.assertEqual([s["role"] for s in suggestions], ["HIGH_STRIKE", "BALANCED"])
        self.assertEqual([s["strike"] for s in suggestions], [112.0, 106.0])
        self.assertEqual((middle["role"], middle["strike"]), ("MIDDLE", 108.0))
        self.assertTrue(suggestions[0]["strike"] > middle["strike"] > suggestions[1]["strike"])
        self.assertEqual(builder.covered_call_suggestions(CHAIN, 100.0, 2), suggestions)  # the `suggestions` contract is unchanged: 1-2 entries
        for tier in (*suggestions, middle):  # the middle follows the same limit rule: on the tick and inside bid..mid
            self.assertTrue(tier["bid"] <= tier["limit_price"] <= tier["mid"], tier)
            self.assertEqual(tier["limit_price"], round(tier["limit_price"], 2))
        self.assertEqual(middle["limit_price"], 0.37)  # mid 0.375, spread 13% <= 25%: mid rounded DOWN to the tick

    def test_no_middle_when_no_strike_lies_between_and_never_a_duplicate_strike(self):
        rows = [q(112.0, 0.10, 0.12, 0.08), q(106.0, 0.60, 0.66, 0.28)]
        suggestions, middle = builder.covered_call_tiers(rows, 100.0, 2)
        self.assertEqual(len(suggestions), 2)
        self.assertIsNone(middle)
        only_high, none = builder.covered_call_tiers([q(112.0, 0.10, 0.12, 0.08)], 100.0, 2)
        self.assertEqual(len(only_high), 1)
        self.assertIsNone(none)
        result = builder.cycle_result("X", "2026-10-09", 2, 100.0, rows, currency="USD", source="s", provenance="https://x.test/", rights="r",
                                      stamp="2026-10-07T14:00:00Z")
        self.assertNotIn("middle_suggestion", result)

    def test_cycle_result_carries_the_optional_middle_asof_and_week_and_validates(self):
        result = builder.cycle_result("X", "2026-10-09", 2, 100.0, CHAIN, currency="USD", source="s", provenance="https://x.test/", rights="r",
                                      stamp="2026-10-07T14:00:00Z", asof="2026-10-07", week="CURRENT")
        self.assertEqual(result["middle_suggestion"]["strike"], 108.0)
        self.assertEqual((result["asof_date"], result["weekly_week"], result["dte"]), ("2026-10-07", "CURRENT", 2))
        validate_covered_call_cycle(result, evaluated_at="2026-10-07T14:05:00Z", document_at="2026-10-07T14:00:00Z", period="weekly")
        plain = builder.cycle_result("X", "2026-10-09", 2, 100.0, CHAIN, currency="USD", source="s", provenance="https://x.test/", rights="r",
                                     stamp="2026-10-07T14:00:00Z")
        self.assertNotIn("asof_date", plain)
        self.assertNotIn("weekly_week", plain)

    def test_expiry_day_dte_zero_annualizes_over_one_day_without_dividing_by_zero(self):
        result = builder.cycle_result("X", "2026-10-09", 0, 100.0, CHAIN, currency="USD", source="s", provenance="https://x.test/", rights="r",
                                      stamp="2026-10-09T15:00:00Z", asof="2026-10-09", week="CURRENT")
        high = result["suggestions"][0]
        self.assertEqual(high["annualized_yield"], round(high["limit_price"] / 100.0 * 365 / 1, 6))
        validate_covered_call_cycle(result, evaluated_at="2026-10-09T15:05:00Z", document_at="2026-10-09T15:00:00Z", period="weekly")
        self.assertEqual(builder.covered_call_tiers(CHAIN, 100.0, -1), ([], None))


def fake_yahoo(expiries, rows=((120.0, 0.20, 0.24),), iv=0.9):
    calls = [types.SimpleNamespace(strike=k, bid=b, ask=a, impliedVolatility=iv, openInterest=5, volume=2) for k, b, a in rows]
    chain = types.SimpleNamespace(calls=types.SimpleNamespace(itertuples=lambda: iter(calls)))
    ticker = types.SimpleNamespace(options=list(expiries), option_chain=lambda expiry: chain)
    return mock.patch.dict(sys.modules, {"yfinance": types.SimpleNamespace(Ticker=lambda symbol: ticker)})


class WeeklyProducerTests(unittest.TestCase):
    EXPIRIES = ["2026-10-09", "2026-10-16", "2026-11-06"]

    def run_us(self, today: date, stamp: str, expiries=None):
        with fake_yahoo(expiries or self.EXPIRIES):
            return builder.us_options("AAA", 100.0, today, stamp)

    def test_wednesday_the_weekly_is_this_fridays_expiry_not_the_16th(self):
        out = self.run_us(D(2026, 10, 7), "2026-10-07T14:00:00Z")
        weekly = out["weekly"]
        self.assertEqual((weekly["expiry"], weekly["dte"]), ("2026-10-09", 2))
        self.assertEqual((weekly["weekly_week"], weekly["asof_date"]), ("CURRENT", "2026-10-07"))
        self.assertEqual({h["cycle"]: h["expiry"] for h in out.health}["weekly"], "2026-10-09")
        validate_covered_call_cycle(weekly, evaluated_at="2026-10-07T14:05:00Z", document_at="2026-10-07T14:00:00Z", period="weekly")

    def test_saturday_the_weekly_is_the_earliest_expiry_of_next_week(self):
        out = self.run_us(D(2026, 10, 10), "2026-10-10T14:00:00Z", ["2026-10-16", "2026-10-23", "2026-11-13"])
        weekly = out["weekly"]
        self.assertEqual((weekly["expiry"], weekly["dte"], weekly["weekly_week"]), ("2026-10-16", 6, "NEXT"))
        validate_covered_call_cycle(weekly, evaluated_at="2026-10-10T14:05:00Z", document_at="2026-10-10T14:00:00Z", period="weekly")

    def test_two_weeks_out_is_never_labelled_weekly(self):
        out = self.run_us(D(2026, 10, 7), "2026-10-07T14:00:00Z", ["2026-10-23", "2026-11-06"])
        self.assertIn("unavailable", out["weekly"])
        self.assertIn("本週或下週", out["weekly"]["unavailable"])
        self.assertNotIn("3-14", out["weekly"]["unavailable"])
        self.assertEqual({h["cycle"]: h["status"] for h in out.health}["weekly"], "NO_EXPIRY")

    def test_expiry_day_is_dte_zero_before_the_close_and_rolls_to_next_week_after_it(self):
        before = self.run_us(D(2026, 10, 9), "2026-10-09T15:00:00Z", ["2026-10-09", "2026-10-16"])["weekly"]  # 11:00 New York
        self.assertEqual((before["expiry"], before["dte"], before["weekly_week"]), ("2026-10-09", 0, "CURRENT"))
        self.assertEqual(before["suggestions"][0]["annualized_yield"], round(before["suggestions"][0]["limit_price"] / 100.0 * 365, 6))
        after = self.run_us(D(2026, 10, 9), "2026-10-09T21:00:00Z", ["2026-10-09", "2026-10-16"])["weekly"]  # 17:00 New York
        self.assertEqual((after["expiry"], after["dte"], after["weekly_week"]), ("2026-10-16", 7, "NEXT"))

    def test_monthly_is_unchanged_nearest_thirty_days_inside_21_to_45(self):
        out = self.run_us(D(2026, 10, 7), "2026-10-07T14:00:00Z", ["2026-10-09", "2026-10-16", "2026-11-06", "2026-11-20"])
        monthly = {h["cycle"]: h for h in out.health}["monthly"]
        self.assertEqual(monthly["expiry"], "2026-11-06")  # DTE 30; 2026-11-20 is DTE 44, 2026-10-16 is DTE 9 (outside 21-45)
        self.assertEqual(builder.CYCLES["monthly"], (21, 45))
        self.assertEqual(builder.CYCLES["weekly"], (0, 14))

    @staticmethod
    def call(expiry: str, dte: int, strike=110.0, bid=0.20, ask=0.24, delta=0.12):
        return {"expiry": expiry, "dte": dte, "strike": strike, "bid": bid, "ask": ask, "iv": None, "delta": delta, "oi": 1, "volume": 1, "size": 100}

    def test_stockholm_weekly_uses_the_same_rule_with_the_stockholm_session_close(self):
        calls = [self.call("2026-10-09", 2), self.call("2026-10-16", 9)]
        out = builder._cycles_from_calls(calls, "VOLV-B.ST", 100.0, "2026-10-07T08:00:00Z", currency="SEK", source="s", provenance="https://x.test/",
                                         rights="r", missing="x {low}-{high}", venue="STOCKHOLM", today=D(2026, 10, 7))
        self.assertEqual((out["weekly"]["expiry"], out["weekly"]["weekly_week"]), ("2026-10-09", "CURRENT"))
        late = [self.call("2026-10-09", 0), self.call("2026-10-16", 7)]  # Friday 17:45 Stockholm (15:45 UTC): after the 17:30 close
        out = builder._cycles_from_calls(late, "VOLV-B.ST", 100.0, "2026-10-09T15:45:00Z", currency="SEK", source="s", provenance="https://x.test/",
                                         rights="r", missing="x", venue="STOCKHOLM", today=D(2026, 10, 9))
        self.assertEqual((out["weekly"]["expiry"], out["weekly"]["weekly_week"]), ("2026-10-16", "NEXT"))

    def test_a_current_week_contract_with_refused_terms_is_never_skipped_for_next_weeks_expiry(self):
        usable_next_week_only = [self.call("2026-10-16", 9)]
        out = builder._cycles_from_calls(usable_next_week_only, "VOLV-B.ST", 100.0, "2026-10-07T08:00:00Z", currency="SEK", source="s",
                                         provenance="https://x.test/", rights="r", missing="Nasdaq 無 {low}-{high} 天到期", venue="STOCKHOLM",
                                         today=D(2026, 10, 7), week_expiries=["2026-10-09", "2026-10-16"])
        self.assertIn("unavailable", out["weekly"])
        self.assertEqual(out["weekly"]["unavailable"], "Nasdaq 無本週或下週到期")  # no expiry rows survive the terms check for 10-09

    def test_the_exchange_local_date_is_the_as_of_date_not_the_utc_date(self):
        # 08:00 Taipei Wednesday 2026-10-07 = 00:00 UTC = Tuesday 2026-10-06 20:00 New York: the US weekly is still this week's Friday.
        now = utc("2026-10-07T00:00:00Z")
        today = rules.exchange_date(now, "US")
        self.assertEqual(today, D(2026, 10, 6))
        choice = rules.select_weekly_expiry(LISTED, today)
        self.assertEqual((choice.expiry, (choice.expiry - today).days), (D(2026, 10, 9), 3))


def tier_item(role, strike, bid, ask, delta, spot, dte):
    mid = round((bid + ask) / 2, 4)
    limit = round(math.floor(mid / 0.01 + 1e-9) * 0.01, 2)
    return {"role": role, "strike": strike, "bid": bid, "ask": ask, "mid": mid, "limit_price": limit, "premium_per_contract": round(limit * 100, 2),
            "period_yield": round(limit / spot, 6), "annualized_yield": round(limit / spot * 365 / max(dte, 1), 6),
            "upside_to_strike": round(strike / spot - 1, 6), "delta": delta, "delta_basis": "QUOTED", "iv": None, "oi": 10, "volume": 1, "spread_pct": 0.1}


def tier_cycle(*, dte=2, expiry="2026-10-09", asof="2026-10-07", week="CURRENT", middle=True, **override):
    cycle = {"ticker": "TSM", "strategy": "COVERED_CALL", "expiry": expiry, "dte": dte, "spot": 100.0, "currency": "USD", "multiplier": 100,
             "quote_basis": "delayed", "timestamp": "2026-10-07T14:00:00Z", "source": "Yahoo Finance (unofficial, delayed)",
             "provenance": "https://finance.yahoo.com/quote/TSM/options", "rights_status": "unadmitted_third_party",
             "suggestions": [tier_item("HIGH_STRIKE", 112.0, 0.10, 0.12, 0.08, 100.0, dte), tier_item("BALANCED", 106.0, 0.60, 0.66, 0.28, 100.0, dte)]}
    if middle:
        cycle["middle_suggestion"] = tier_item("MIDDLE", 108.0, 0.35, 0.40, 0.20, 100.0, dte)
    if asof is not None:
        cycle["asof_date"] = asof
    if week is not None:
        cycle["weekly_week"] = week
    cycle.update(override)
    return cycle


EVAL = {"evaluated_at": "2026-10-07T14:05:00Z", "document_at": "2026-10-07T14:00:00Z"}


class TierValidatorTests(unittest.TestCase):
    def reject(self, cycle, code, period="weekly"):
        with self.assertRaises(MarketProductValidationError) as ctx:
            validate_covered_call_cycle(cycle, period=period, **EVAL)
        self.assertEqual(str(ctx.exception), code)

    def test_a_valid_three_tier_cycle_and_the_older_two_tier_shape_both_pass(self):
        validate_covered_call_cycle(tier_cycle(), period="weekly", **EVAL)
        old = tier_cycle(middle=False, asof=None, week=None)  # an older sealed row has neither middle, asof_date nor weekly_week
        for key in ("middle_suggestion", "asof_date", "weekly_week"):
            self.assertNotIn(key, old)
        validate_covered_call_cycle(old, period="weekly", **EVAL)
        validate_covered_call_cycle(tier_cycle(middle=False), period="weekly", **EVAL)
        validate_covered_call_cycle(tier_cycle(middle_suggestion=None), period="weekly", **EVAL)  # a null marker means no middle tier

    def test_the_middle_must_sit_strictly_between_the_two_strikes(self):
        for strike in (112.0, 106.0, 113.0, 105.0):
            cycle = tier_cycle()
            cycle["middle_suggestion"] = tier_item("MIDDLE", strike, 0.35, 0.40, 0.20, 100.0, 2)
            self.reject(cycle, "COVERED_CALL_MIDDLE_NOT_BETWEEN")

    def test_the_middle_needs_both_neighbours_the_role_middle_and_the_same_item_checks(self):
        one = tier_cycle()
        one["suggestions"] = one["suggestions"][:1]
        self.reject(one, "COVERED_CALL_MIDDLE_NEEDS_TWO_NEIGHBOURS")
        wrong_role = tier_cycle()
        wrong_role["middle_suggestion"]["role"] = "BALANCED"
        self.reject(wrong_role, "COVERED_CALL_MIDDLE_ROLE")
        self.reject(tier_cycle(middle_suggestion="x"), "COVERED_CALL_MIDDLE_SHAPE")
        bad_yield = tier_cycle()
        bad_yield["middle_suggestion"]["annualized_yield"] = 0.5
        self.reject(bad_yield, "COVERED_CALL_DERIVED_MISMATCH: annualized_yield")
        above_mid = tier_cycle()
        above_mid["middle_suggestion"]["limit_price"] = 0.99
        self.reject(above_mid, "COVERED_CALL_PRICES_INCONSISTENT")
        itm = tier_cycle()
        itm["middle_suggestion"] = tier_item("MIDDLE", 99.0, 0.35, 0.40, 0.20, 100.0, 2)
        self.reject(itm, "COVERED_CALL_STRIKE_NOT_OUT_OF_THE_MONEY")
        for key, value in (("delta", 1.5), ("delta_basis", "GUESS"), ("iv", -1), ("oi", -3), ("volume", float("inf"))):
            bad = tier_cycle()
            bad["middle_suggestion"][key] = value
            with self.assertRaises(MarketProductValidationError, msg=key):
                validate_covered_call_cycle(bad, period="weekly", **EVAL)

    def test_the_suggestions_list_stays_capped_at_the_two_original_roles(self):
        three = tier_cycle(middle=False)
        three["suggestions"].insert(1, tier_item("MIDDLE", 108.0, 0.35, 0.40, 0.20, 100.0, 2))
        self.reject(three, "COVERED_CALL_SUGGESTION_COUNT")
        swapped = tier_cycle(middle=False)
        swapped["suggestions"][1]["role"] = "MIDDLE"
        self.reject(swapped, "COVERED_CALL_ROLES")

    def test_dte_zero_is_valid_and_dte_beyond_sixty_is_not(self):
        zero = tier_cycle(dte=0, expiry="2026-10-07", asof="2026-10-07")
        validate_covered_call_cycle(zero, period="weekly", **EVAL)
        self.reject(tier_cycle(dte=61, expiry="2026-12-07", asof="2026-10-07"), "INVALID_DTE", period="monthly")

    def test_a_dte_zero_row_is_rejected_after_the_us_session_close(self):
        def zero(stamp):
            return tier_cycle(dte=0, expiry="2026-10-09", asof="2026-10-09", timestamp=stamp)
        validate_covered_call_cycle(zero("2026-10-09T19:25:00Z"), period="weekly", evaluated_at="2026-10-09T19:30:00Z", document_at="2026-10-09T19:25:00Z")  # 15:30 New York
        with self.assertRaises(MarketProductValidationError) as ctx:
            validate_covered_call_cycle(zero("2026-10-09T20:25:00Z"), period="weekly", evaluated_at="2026-10-09T20:30:00Z", document_at="2026-10-09T20:25:00Z")  # 16:30 New York
        self.assertEqual(str(ctx.exception), "EXPIRY_DAY_SESSION_CLOSED")

    def test_the_calendar_week_rule_with_an_asof_date(self):
        validate_covered_call_cycle(tier_cycle(dte=9, expiry="2026-10-16", asof="2026-10-07", week="NEXT"), period="weekly", **EVAL)
        validate_covered_call_cycle(tier_cycle(dte=11, expiry="2026-10-18", asof="2026-10-07", week="NEXT"), period="weekly", **EVAL)
        self.reject(tier_cycle(dte=12, expiry="2026-10-19", asof="2026-10-07", week="NEXT"), "DTE_OUTSIDE_PERIOD_BUCKET")
        self.reject(tier_cycle(dte=9, expiry="2026-10-16", asof="2026-10-07", week="CURRENT"), "WEEKLY_WEEK_INCONSISTENT")
        self.reject(tier_cycle(dte=2, expiry="2026-10-09", asof="2026-10-07", week="NEXT"), "WEEKLY_WEEK_INCONSISTENT")
        self.reject(tier_cycle(asof="2026-02-30"), "INVALID_ASOF_DATE")
        self.reject(tier_cycle(asof=20261007), "INVALID_ASOF_DATE")
        self.reject(tier_cycle(asof="2026-10-08"), "ASOF_DTE_INCONSISTENT")
        # the same expiry as a monthly request is outside the monthly bucket, with or without the as-of date
        self.reject(tier_cycle(), "DTE_OUTSIDE_PERIOD_BUCKET", period="monthly")

    def test_the_weekly_week_marker_is_weekly_only_and_two_valued(self):
        self.reject(tier_cycle(asof=None, week="LATER"), "INVALID_WEEKLY_WEEK")
        self.reject(tier_cycle(dte=30, expiry="2026-11-06", asof=None, week="CURRENT"), "INVALID_WEEKLY_WEEK", period="monthly")
        validate_covered_call_cycle(tier_cycle(dte=30, expiry="2026-11-06", asof="2026-10-07", week=None), period="monthly", **EVAL)

    def test_the_old_three_to_fourteen_window_no_longer_hides_the_current_weeks_expiry(self):
        for dte in (0, 1, 2):
            expiry = f"2026-10-{7 + dte:02d}"
            validate_covered_call_cycle(tier_cycle(dte=dte, expiry=expiry, asof="2026-10-07"), period="weekly", **EVAL)

    def test_validation_does_not_mutate_its_input(self):
        cycle = tier_cycle()
        before = copy.deepcopy(cycle)
        validate_covered_call_cycle(cycle, period="weekly", **EVAL)
        self.assertEqual(cycle, before)


class TypeScriptParityTests(unittest.TestCase):
    """The Worker twin cloud/src/v213/option-recommendation-rules.ts carries the same constants; drift fails here."""
    SOURCE = (ROOT / "cloud" / "src" / "v213" / "option-recommendation-rules.ts").read_text(encoding="utf-8")

    def number(self, name: str) -> float:
        import re
        match = re.search(rf"export const {name}\b[^=]*= ([0-9.]+);", self.SOURCE)
        self.assertIsNotNone(match, name)
        return float(match.group(1))

    def test_constants_match_the_python_rules(self):
        import re
        for name, expected in (("MIDDLE_DELTA", rules.MIDDLE_DELTA), ("MIDDLE_MONEYNESS", rules.MIDDLE_MONEYNESS),
                               ("SHORT_DTE_NOTICE_MAX", rules.SHORT_DTE_NOTICE_MAX), ("MIN_ANNUALIZATION_DAYS", rules.MIN_ANNUALIZATION_DAYS),
                               ("MONTHLY_TARGET_DTE", rules.MONTHLY_TARGET_DTE)):
            self.assertEqual(self.number(name), expected, name)
        for name, expected in (("WEEKLY_DTE_BUCKET", rules.WEEKLY_DTE_BUCKET), ("MONTHLY_DTE_BUCKET", rules.MONTHLY_DTE_BUCKET)):
            match = re.search(rf"export const {name}[^=]*= \[(\d+), (\d+)\]", self.SOURCE)
            self.assertEqual((int(match.group(1)), int(match.group(2))), tuple(expected), name)
        minutes = re.search(r"EXPIRY_DAY_CLOSE_LOCAL_MINUTES[^=]*= \{ US: ([0-9 *+]+), STOCKHOLM: ([0-9 *+]+), TAIFEX: ([0-9 *+]+) \}", self.SOURCE)
        def arithmetic(text: str) -> int:  # sums of products only, as written in the TypeScript source ("17 * 60 + 30")
            return sum(math.prod(int(factor) for factor in term.split("*")) for term in text.split("+"))
        parsed = {key: arithmetic(text) for key, text in zip(("US", "STOCKHOLM", "TAIFEX"), minutes.groups())}
        self.assertEqual(parsed, rules.EXPIRY_DAY_CLOSE_LOCAL_MINUTES)

    def test_every_consumer_takes_the_windows_from_the_shared_rules_not_a_private_copy(self):
        import validate_v213_market_products as validator
        self.assertEqual(validator.PERIOD_DTE_BUCKETS, {"weekly": rules.WEEKLY_DTE_BUCKET, "monthly": rules.MONTHLY_DTE_BUCKET})
        self.assertEqual(builder.CYCLES, {"weekly": rules.WEEKLY_DTE_BUCKET, "monthly": rules.MONTHLY_DTE_BUCKET})
        for relative in ("cloud/src/v213/covered-call.ts", "cloud/src/v213/market-product-schema.ts", "cloud/src/v213/options-guidance.ts"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("option-recommendation-rules", text, relative)
            self.assertNotIn("[3, 14]", text, relative)
            self.assertNotIn("dte < 3", text, relative)


if __name__ == "__main__":
    unittest.main()
