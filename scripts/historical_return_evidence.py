"""Calendar-window arithmetic for provider-adjusted closes, not a rights gate.

No fetching, price interpolation, currency inference or publication authorization.
"""
from __future__ import annotations

import calendar
import math
from datetime import date, datetime, timedelta, timezone
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


def validate_return_observation(value: dict, *, ticker: str, long_pct, short_pct, completed: str) -> None:
    """Closed local candidate readback. No rights, selection-history or freshness grant."""
    def require(ok):
        if not ok:
            raise ReturnEvidenceError('RETURN_CANDIDATE_INVALID')
    def day(raw):
        require(isinstance(raw, str))
        try:
            parsed = date.fromisoformat(raw)
        except ValueError:
            raise ReturnEvidenceError('RETURN_CANDIDATE_INVALID') from None
        require(parsed.isoformat() == raw)
        return parsed
    require(isinstance(value, dict))
    if not value:  # Explicit no-observation legacy/local fixture, never invented prices.
        require(long_pct is None and short_pct is None)
        return
    minimal = {'status', 'publication_eligible', 'provider', 'ticker'}
    require(value.get('publication_eligible') is False and value.get('provider') == 'yfinance'
            and value.get('ticker') == ticker)
    if set(value) == minimal:
        require(value['status'] == 'UNAVAILABLE' and long_pct is None and short_pct is None)
        return
    template = calculate_return_evidence([])
    require(set(value) == minimal | set(template) | {'observed_at', 'retrieved_at', 'acquisition_status', 'request'})
    require(type(value['schema_version']) is int and value['schema_version'] == 1)
    for key, expected in template.items():
        if key != 'windows':
            require(type(value[key]) is type(expected) and value[key] == expected)
    if value['status'] == 'CALCULATED_NOT_QUALIFIED':
        # Minted local fetch receipt: the moment this exact response was acquired
        # from the provider; equal to observed_at (the bar-age guard gates minting).
        require(value['acquisition_status'] == 'LOCAL_FETCH_RECEIPT'
                and value['retrieved_at'] == value['observed_at'])
    else:
        require(value['retrieved_at'] is None and value['acquisition_status'] == 'UNKNOWN_PROVIDER_ACQUISITION_TIME')
    request = value['request']
    require(isinstance(request, dict) and set(request) == {'period', 'interval', 'auto_adjust'}
            and request['period'] == '3y' and request['interval'] == '1d' and request['auto_adjust'] is True)
    try:
        observed = datetime.fromisoformat(value['observed_at'].replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(completed.replace('Z', '+00:00'))
        require(value['observed_at'].endswith('Z') and observed.tzinfo == timezone.utc
                and observed < end_time + timedelta(seconds=1))  # Completion is stored to UTC seconds.
    except (AttributeError, TypeError, ValueError):
        raise ReturnEvidenceError('RETURN_CANDIDATE_INVALID') from None
    windows = value['windows']
    require(isinstance(windows, dict) and set(windows) == {'two_year', 'six_month'})
    available = False
    for name, months in (('two_year', 24), ('six_month', 6)):
        window = windows[name]; require(isinstance(window, dict))
        status = window.get('status')
        require(status in ('AVAILABLE', 'INSUFFICIENT_HISTORY', 'START_OBSERVATION_GAP', 'NON_FINITE_RESULT'))
        if set(window) == {'status'}:
            require(status == 'INSUFFICIENT_HISTORY')
            continue
        dates = {'status', 'requested_start', 'actual_end'}
        require(dates <= set(window))
        end = day(window['actual_end']); requested = day(window['requested_start'])
        require(end <= observed.date() and requested == _months_before(end, months))
        if status != 'AVAILABLE':
            require(set(window) == dates)  # Retain failure, never repair it from two prices.
            continue
        available = True
        require(set(window) == dates | {'actual_start', 'start_adjusted_close', 'end_adjusted_close',
                                       'elapsed_days', 'cumulative_return_pct', 'annualized_return_pct'})
        require(type(window['elapsed_days']) is int)
        for key in ('start_adjusted_close', 'end_adjusted_close', 'cumulative_return_pct', 'annualized_return_pct'):
            require(type(window[key]) in (int, float) and math.isfinite(window[key]))
        expected = calculate_return_evidence([(day(window['actual_start']), window['start_adjusted_close']),
                                               (end, window['end_adjusted_close'])])['windows'][name]
        require(window == expected)
    require(value['status'] == ('CALCULATED_NOT_QUALIFIED' if available else 'NO_COMPLETE_RETURN_WINDOW'))
    pair = legacy_return_pair(value)
    for actual, ratio in zip((long_pct, short_pct), pair):
        require(actual is None if ratio is None else type(actual) in (int, float) and actual == round(ratio * 100, 2))


def legacy_return_pair(evidence: dict) -> tuple[float | None, float | None]:
    long = evidence['windows']['two_year']
    short = evidence['windows']['six_month']
    return (
        long['annualized_return_pct'] / 100 if long['status'] == 'AVAILABLE' else None,
        short['cumulative_return_pct'] / 100 if short['status'] == 'AVAILABLE' else None,
    )
