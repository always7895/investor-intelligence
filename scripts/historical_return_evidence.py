"""Calendar-window arithmetic for provider-adjusted closes, not a rights gate.

No fetching, price interpolation, currency inference or publication authorization.
"""
from __future__ import annotations

import calendar
import math
from datetime import date
from numbers import Real
from typing import Iterable


class ReturnEvidenceError(ValueError):
    pass


def _months_before(day: date, months: int) -> date:
    year, month0 = divmod(day.year * 12 + day.month - 1 - months, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def calculate_return_evidence(points: Iterable[tuple[date, float]]) -> dict:
    rows = list(points)
    previous = None
    for day, price in rows:
        if type(day) is not date or (previous is not None and day <= previous):
            raise ReturnEvidenceError('HISTORY_DATES_INVALID_OR_UNORDERED')
        if isinstance(price, bool) or not isinstance(price, Real):
            raise ReturnEvidenceError('HISTORY_PRICE_INVALID')
        try:
            valid_price = math.isfinite(price) and price > 0
        except (OverflowError, ValueError):
            valid_price = False
        if not valid_price:
            raise ReturnEvidenceError('HISTORY_PRICE_INVALID')
        previous = day
    result = {
        'schema_version': 1,
        'publication_eligible': False,
        'definition': 'provider_adjusted_close_proxy',
        'adjustment_method_independently_verified': False,
        'dividend_reinvestment_verified': False,
        'currency': None,
        'fx_adjusted': False,
        'fees_and_taxes_included': False,
        'day_count': 'ACT/365.25',
        'alignment': 'last_available_on_or_before_calendar_target_within_7_days',
        'exchange_calendar_verified': False,
        'windows': {},
    }
    for label, months in (('two_year', 24), ('six_month', 6)):
        window = {'status': 'INSUFFICIENT_HISTORY'}
        result['windows'][label] = window
        if len(rows) < 2:
            continue
        end_day, end_price = rows[-1]
        target = _months_before(end_day, months)
        window.update(requested_start=target.isoformat(), actual_end=end_day.isoformat())
        eligible = [(d, p) for d, p in rows if d <= target]
        if not eligible:
            continue
        start_day, start_price = eligible[-1]
        if (target - start_day).days > 7:
            window['status'] = 'START_OBSERVATION_GAP'
            continue
        elapsed = (end_day - start_day).days
        try:
            ratio = float(end_price) / float(start_price)
            cumulative = (ratio - 1) * 100
            annualized = math.expm1(math.log(ratio) * 365.25 / elapsed) * 100
            if not all(math.isfinite(v) for v in (cumulative, annualized)):
                raise OverflowError
        except (OverflowError, ValueError, ZeroDivisionError):
            window['status'] = 'NON_FINITE_RESULT'
            continue
        window.update(
            status='AVAILABLE', actual_start=start_day.isoformat(),
            start_adjusted_close=float(start_price), end_adjusted_close=float(end_price),
            elapsed_days=elapsed, cumulative_return_pct=cumulative,
            annualized_return_pct=annualized,
        )
    return result


def legacy_return_pair(evidence: dict) -> tuple[float | None, float | None]:
    long = evidence['windows']['two_year']
    short = evidence['windows']['six_month']
    return (
        long['annualized_return_pct'] / 100 if long['status'] == 'AVAILABLE' else None,
        short['cumulative_return_pct'] / 100 if short['status'] == 'AVAILABLE' else None,
    )
