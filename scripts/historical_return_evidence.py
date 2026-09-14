"""Calendar-window arithmetic for provider-adjusted closes, not a rights gate.

No fetching, price interpolation, currency inference or publication authorization.

ARCHITECTURAL RESOLUTION & ADMISSION BOUNDARY:
- Status: Live 2Y numeric return admission is explicitly DEFERRED (DEFER).
- Scope: The helpers `build_two_year_return_evidence` and `validate_two_year_return_evidence_dict`
  are optional candidate arithmetic/schema validation utilities only. They do NOT confer
  authoritative return admission or publication eligibility, and must NOT be automatically
  propagated into legacy closed DTOs or sealed objects.
- Existing qualified filtered stock returns continue using their qualified legacy return
  fields (trailing 2Y CAGR and 6M price return).
- Safe extension requirements for future authoritative 2Y total return admission:
  1. Currency: explicit ISO-4217 currency specification and FX adjustment tracking.
  2. Adjustment method: independently verified dividend reinvestment and split methodology.
  3. Source body hash: SHA-256 digest of original provider payload/body for tamper-proofing.
  4. Role & rights: verified acquisition role identity and publication rights binding.
  5. Quote clocks: bar-level quote timestamp verification against market calendars.
  6. Identity: authoritative security identifier binding (CIK, FIGI, LEI, ISIN) beyond ticker.
  7. Run lineage: shared cryptographic trace linking raw observation receipt to pipeline run.
  8. Shared canonical validator & schema: synchronized multi-runtime verification contracts.
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


def canonical_return_triplet(evidence: dict) -> tuple[float | None, float | None, float | None]:
    """Derives (two_year_total_return_pct, two_year_annualized_cagr_pct, six_month_return_pct).
    Percentages are returned directly in explicit percent units (e.g. 50.0 for 50.0%), NOT fractions.
    Returns None for any unavailable/invalid window.
    """
    if not isinstance(evidence, dict) or 'windows' not in evidence:
        return None, None, None
    windows = evidence.get('windows', {})
    if not isinstance(windows, dict):
        return None, None, None
    long = windows.get('two_year', {})
    short = windows.get('six_month', {})

    def _clean(val):
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val < -100:
            return None
        return round(float(val), 2)

    total_2y = _clean(long.get('cumulative_return_pct')) if long.get('status') == 'AVAILABLE' else None
    cagr_2y = _clean(long.get('annualized_return_pct')) if long.get('status') == 'AVAILABLE' else None
    ret_6m = _clean(short.get('cumulative_return_pct')) if short.get('status') == 'AVAILABLE' else None
    return total_2y, cagr_2y, ret_6m


def build_two_year_return_evidence(ticker: str, evidence: dict) -> dict | None:
    """Builds candidate two-year return evidence envelope with bound ticker, endpoints,
    and dividend/split adjusted semantics. Returns None if unavailable or invalid.

    NOTE: Candidate only. Live 2Y numeric admission is DEFERRED. This object must not
    be treated as independently admitted proof without coordinated producer contract.
    """
    if not isinstance(evidence, dict) or not isinstance(ticker, str) or not ticker:
        return None
    windows = evidence.get('windows', {})
    if not isinstance(windows, dict):
        return None
    two_year = windows.get('two_year', {})
    if not isinstance(two_year, dict) or two_year.get('status') != 'AVAILABLE':
        return None
    try:
        start_price = float(two_year['start_adjusted_close'])
        end_price = float(two_year['end_adjusted_close'])
        cumulative = float(two_year['cumulative_return_pct'])
        actual_start = str(two_year['actual_start'])
        actual_end = str(two_year['actual_end'])
        elapsed = int(two_year['elapsed_days'])
        if not math.isfinite(start_price) or start_price <= 0 or not math.isfinite(end_price) or end_price <= 0:
            return None
        if not math.isfinite(cumulative) or cumulative < -100:
            return None
        calc = ((end_price / start_price) - 1) * 100
        if abs(calc - cumulative) > 0.05:
            return None
        return {
            'ticker': ticker.upper(),
            'window': 'two_year',
            'actual_start': actual_start,
            'actual_end': actual_end,
            'start_adjusted_close': start_price,
            'end_adjusted_close': end_price,
            'elapsed_days': elapsed,
            'total_return_pct': round(cumulative, 2),
            'market_source': 'yfinance',
            'basis': 'adjusted_close',
            'dividend_split_semantics': 'auto_adjusted',
        }
    except (KeyError, TypeError, ValueError):
        return None


def validate_two_year_return_evidence_dict(evidence: Any, ticker: str, retrieved_at: str | None = None) -> bool:
    """Validates candidate two_year_return_evidence dictionary structure, endpoints, dates,
    freshness and math.

    NOTE: Candidate math/schema validation only. Does NOT grant authoritative admission.
    Live 2Y numeric admission remains DEFERRED.
    """
    if not isinstance(evidence, dict):
        return False
    required_keys = {
        'ticker', 'window', 'actual_start', 'actual_end', 'start_adjusted_close',
        'end_adjusted_close', 'elapsed_days', 'total_return_pct', 'market_source',
        'basis', 'dividend_split_semantics'
    }
    optional_keys = {'currency'}
    allowed_keys = required_keys | optional_keys
    evidence_keys = set(evidence.keys())
    if not required_keys.issubset(evidence_keys) or not evidence_keys.issubset(allowed_keys):
        return False
    if evidence.get('ticker') != ticker.upper():
        return False
    if evidence.get('window') != 'two_year':
        return False
    if evidence.get('market_source') != 'yfinance':
        return False
    if evidence.get('basis') != 'adjusted_close':
        return False
    if evidence.get('dividend_split_semantics') != 'auto_adjusted':
        return False
    if 'currency' in evidence and evidence['currency'] != 'USD':
        return False
    try:
        raw_start = evidence['actual_start']
        raw_end = evidence['actual_end']
        if not isinstance(raw_start, str) or not isinstance(raw_end, str):
            return False
        start_d = date.fromisoformat(raw_start)
        end_d = date.fromisoformat(raw_end)
        if start_d.isoformat() != raw_start or end_d.isoformat() != raw_end:
            return False
        if start_d >= end_d:
            return False

        # Exact elapsed days derivation and check
        derived_elapsed = (end_d - start_d).days
        elapsed = evidence.get('elapsed_days')
        if isinstance(elapsed, bool) or not isinstance(elapsed, int) or elapsed != derived_elapsed:
            return False

        # Two-calendar-year target check (24 calendar months before actual_end)
        target_start = _months_before(end_d, 24)
        alignment_gap = (target_start - start_d).days
        if alignment_gap < 0 or alignment_gap > 7:
            return False
        if derived_elapsed < 720 or derived_elapsed > 740:
            return False

        sp = evidence.get('start_adjusted_close')
        ep = evidence.get('end_adjusted_close')
        tot = evidence.get('total_return_pct')
        if isinstance(sp, bool) or isinstance(ep, bool) or isinstance(tot, bool):
            return False
        if not isinstance(sp, (int, float)) or not math.isfinite(sp) or sp <= 0:
            return False
        if not isinstance(ep, (int, float)) or not math.isfinite(ep) or ep <= 0:
            return False
        if not isinstance(tot, (int, float)) or not math.isfinite(tot) or tot < -100:
            return False
        if abs(((ep / sp) - 1) * 100 - tot) > 0.05:
            return False

        if retrieved_at is not None:
            if not isinstance(retrieved_at, str):
                return False
            ret_dt = datetime.fromisoformat(retrieved_at.replace('Z', '+00:00'))
            ret_d = ret_dt.date()
            if end_d > ret_d:
                return False
            # Freshness policy: market observation max age is 7 days
            if (ret_d - end_d).days > 7 or (ret_d - end_d).days < 0:
                return False
        else:
            now_d = datetime.now(timezone.utc).date()
            if end_d > now_d:
                return False
        return True
    except (TypeError, ValueError, KeyError):
        return False
