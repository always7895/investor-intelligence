"""Shared option-recommendation rules (operator 2026-10-11): the current-week weekly expiry and the middle strike tier.

Pure functions, no I/O, no network, no third-party dependency (the exchange clock uses explicit DST rules, not tzdata). The
TypeScript twin is cloud/src/v213/option-recommendation-rules.ts; both implement exactly the rules below and a parity test
pins the constants.

WEEKLY (calendar week, exchange local, Monday-Sunday):
- as_of is the exchange-local calendar date of the observation instant (never the UTC date or the operator's date).
- The weekly expiry is the EARLIEST listed expiry e with as_of <= e <= Sunday of the as_of week. Only when the current week has
  no remaining listed expiry (weekend, after the last weekly of the week, or the expiry day after the session close) is it the
  EARLIEST listed expiry of the NEXT calendar week (Monday..Sunday after). Nothing beyond the next week is ever a weekly.
- Expiry day (DTE 0) counts only while the venue's regular session has not closed (EXPIRY_DAY_CLOSE_LOCAL_MINUTES).
- Monthly is unchanged: the expiry nearest 30 days inside MONTHLY_DTE_BUCKET.

ANNUALIZATION for tiny DTE: days = max(dte, 1) (MIN_ANNUALIZATION_DAYS). A same-day or next-day expiry therefore never
divides by zero and is never annualized over less than one day; a cycle with dte <= SHORT_DTE_NOTICE_MAX is labelled on the
card because its annualized figure is strongly amplified.

LIMIT RANGE MIDDLE (a price range shown as low-high, for example the manual calculator): limit_middle = (low + high) / 2 rounded
to the tick and clamped into [low, high], so low <= middle <= high always holds.

MIDDLE TIER: between the HIGH_STRIKE and the BALANCED strike, the candidate whose delta is nearest MIDDLE_DELTA (all candidates
need a delta), else the strike nearest MIDDLE_MONEYNESS; none when no listed strike lies strictly between the two.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

WEEKLY_DTE_BUCKET = (0, 14)      # outer validator tolerance; the exact rule is the calendar-week rule above
MONTHLY_DTE_BUCKET = (21, 45)
MONTHLY_TARGET_DTE = 30
MIN_ANNUALIZATION_DAYS = 1
SHORT_DTE_NOTICE_MAX = 2         # dte 0-2: the annualized yield is labelled as amplified
MIDDLE_DELTA = 0.25
MIDDLE_MONEYNESS = 1.025
# V21 (operator 2026-10-19): the conservative short-leg delta band shared by the cash-secured put and the collar's short call (absolute delta,
# the strike nearest the lower edge first), and the collar's protective put (absolute delta nearest the target inside its window).
CONSERVATIVE_DELTA_BAND = (0.20, 0.30)
PROTECTIVE_PUT_DELTA = 0.15
PROTECTIVE_PUT_DELTA_BAND = (0.05, 0.25)
DELTA_BAND_TOLERANCE = 0.0005    # a displayed delta is rounded to three digits; validators accept the band edge within this
WEEK_CURRENT = "CURRENT"
WEEK_NEXT = "NEXT"
# Regular-session close in exchange-local minutes after midnight (expiry-day cut-off; no holiday calendar is inferred).
EXPIRY_DAY_CLOSE_LOCAL_MINUTES = {"US": 16 * 60, "STOCKHOLM": 17 * 60 + 30, "TAIFEX": 13 * 60 + 30}
# Regular US session: Monday-Friday from this local minute up to the US close above (the previous-session carry-forward rule).
US_SESSION_OPEN_LOCAL_MINUTES = 9 * 60 + 30


def effective_days(dte: int) -> int:
    """Days used to annualize a premium (and as Black-Scholes time): never below one day."""
    return max(int(dte), MIN_ANNUALIZATION_DAYS)


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    """nth (1-based) or last (nth=-1) given weekday (Mon=0) of a month."""
    if nth > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _utc_offset_hours(now_utc: datetime, venue: str) -> int:
    year = now_utc.year
    if venue == "US":    # second Sunday of March 02:00 EST (07:00 UTC) .. first Sunday of November 02:00 EDT (06:00 UTC)
        start = datetime.combine(_nth_weekday(year, 3, 6, 2), datetime.min.time(), timezone.utc) + timedelta(hours=7)
        end = datetime.combine(_nth_weekday(year, 11, 6, 1), datetime.min.time(), timezone.utc) + timedelta(hours=6)
        return -4 if start <= now_utc < end else -5
    if venue == "STOCKHOLM":  # last Sunday of March 01:00 UTC .. last Sunday of October 01:00 UTC
        start = datetime.combine(_nth_weekday(year, 3, 6, -1), datetime.min.time(), timezone.utc) + timedelta(hours=1)
        end = datetime.combine(_nth_weekday(year, 10, 6, -1), datetime.min.time(), timezone.utc) + timedelta(hours=1)
        return 2 if start <= now_utc < end else 1
    if venue == "TAIFEX":
        return 8
    raise ValueError(f"UNKNOWN_VENUE: {venue}")


def exchange_local(now_utc: datetime, venue: str) -> datetime:
    """Naive exchange-local wall-clock time of a timezone-aware instant."""
    if now_utc.tzinfo is None:
        raise ValueError("NAIVE_INSTANT")
    moment = now_utc.astimezone(timezone.utc)
    return (moment + timedelta(hours=_utc_offset_hours(moment, venue))).replace(tzinfo=None)


def exchange_date(now_utc: datetime, venue: str) -> date:
    return exchange_local(now_utc, venue).date()


def parse_utc_instant(stamp: str) -> datetime:
    return datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def expiry_day_open(now_utc: datetime, venue: str) -> bool:
    """True while an option expiring TODAY (exchange local) is still tradable: before the regular-session close."""
    local = exchange_local(now_utc, venue)
    return local.hour * 60 + local.minute < EXPIRY_DAY_CLOSE_LOCAL_MINUTES[venue]


def us_regular_session_open(now_utc: datetime) -> bool:
    """True when the instant lies inside a regular US equity-options session: a New York weekday from 09:30 up to, not
    including, 16:00. Early closes and exchange holidays are NOT inferred (a closed weekday has no two-sided quotes, so no capture
    qualifies there; callers bound the age of whatever they keep)."""
    local = exchange_local(now_utc, "US")
    minutes = local.hour * 60 + local.minute
    return local.weekday() < 5 and US_SESSION_OPEN_LOCAL_MINUTES <= minutes < EXPIRY_DAY_CLOSE_LOCAL_MINUTES["US"]


def week_end(day: date) -> date:
    """Sunday of the Monday-Sunday calendar week containing day."""
    return day + timedelta(days=6 - day.weekday())


def weekly_window_end(as_of: date) -> date:
    """Last date a weekly can have: the Sunday of the next calendar week."""
    return week_end(as_of) + timedelta(days=7)


@dataclass(frozen=True)
class WeeklyChoice:
    expiry: date
    week: str  # WEEK_CURRENT or WEEK_NEXT


def select_weekly_expiry(expiries: Iterable[date], as_of: date, *, expiry_day_open_now: bool = True) -> WeeklyChoice | None:
    """The weekly rule: earliest listed expiry in [as_of, Sunday of this week]; else earliest in the next calendar week; else
    None. Expiry day (as_of itself) counts only while expiry_day_open_now."""
    current_end = week_end(as_of)
    listed = sorted({day for day in expiries if isinstance(day, date)})
    for day in listed:
        if day < as_of or (day == as_of and not expiry_day_open_now):
            continue
        if day <= current_end:
            return WeeklyChoice(day, WEEK_CURRENT)
    for day in listed:
        if current_end < day <= current_end + timedelta(days=7):
            return WeeklyChoice(day, WEEK_NEXT)
    return None


def weekly_week_for(expiry: date, as_of: date) -> str | None:
    """CURRENT or NEXT when expiry lies in [as_of, next Sunday], else None (outside the weekly rule)."""
    if expiry < as_of or expiry > weekly_window_end(as_of):
        return None
    return WEEK_CURRENT if expiry <= week_end(as_of) else WEEK_NEXT


def pick_middle(candidates: Sequence[dict[str, Any]], high_strike: float, balanced_strike: float, spot: float) -> dict[str, Any] | None:
    """The middle-tier row among usable candidate rows (each with strike and optional delta): strictly between the balanced and
    the high strike; delta nearest MIDDLE_DELTA when every candidate has one, else strike nearest MIDDLE_MONEYNESS; ties go to
    the higher strike. None when no strike lies strictly between."""
    between = [row for row in candidates if balanced_strike < row["strike"] < high_strike]
    if not between:
        return None
    if all(row.get("delta") is not None for row in between):
        return min(between, key=lambda row: (abs(row["delta"] - MIDDLE_DELTA), -row["strike"]))
    return min(between, key=lambda row: (abs(row["strike"] / spot - MIDDLE_MONEYNESS), -row["strike"]))


def round_tick(value: float, tick: float = 0.01) -> float:
    """Round half up to the price tick (policy minimum_tick, default 0.01), returned with two decimals."""
    return round(math.floor(value / tick + 0.5 + 1e-9) * tick, 2)


def limit_middle(low: float, high: float, tick: float = 0.01) -> float:
    """Middle of a two-price limit range: (low + high) / 2 on the tick, clamped into [low, high] (low <= middle <= high)."""
    lower, upper = min(low, high), max(low, high)
    return min(max(round_tick((lower + upper) / 2, tick), lower), upper)
