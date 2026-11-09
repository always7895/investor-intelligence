"""Pure, source-bound adjusted-close volatility for option delta estimation.

No quote-derived IV or unadjusted-close fallback is permitted. Invalid evidence
fails closed; metadata validation intentionally does not claim to rehash bytes
that are not supplied to it.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlsplit
import option_recommendation_rules as rules

_KEYS = frozenset((
    "ticker", "currency", "hv20", "hv60", "observations", "start_date_20",
    "start_date_60", "asof_date", "source_url", "source_sha256", "price_basis",
))
_QUERY_KEYS = frozenset((
    "period1", "period2", "interval", "events", "includeAdjustedClose", "range",
))
_ZONES = {"USD": "US", "SEK": "STOCKHOLM"}


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _identity(ticker: Any, currency: Any, capture_date: Any) -> bool:
    return (isinstance(ticker, str) and re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,31}", ticker) is not None
            and ".." not in ticker
            and isinstance(currency, str) and currency in _ZONES
            and type(capture_date) is date)


def _source_url(value: Any, ticker: str) -> bool:
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) == 127 or c.isspace() for c in value):
        return False
    if "\\" in value or "#" in value:
        return False
    if not re.match(r"^https://query1\.finance\.yahoo\.com(?::443)?/", value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https"
                and parsed.netloc in ("query1.finance.yahoo.com", "query1.finance.yahoo.com:443")
                and parsed.path == "/v8/finance/chart/" + ticker
                and all(key in _QUERY_KEYS for key, _ in parse_qsl(parsed.query, keep_blank_values=True)))
    except ValueError:
        return False


def _iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def valid_historical_volatility(value: Any, ticker: str, currency: str, capture_date: date) -> bool:
    """Validate standalone cycle evidence against its identity and capture day."""
    if not _identity(ticker, currency, capture_date) or not isinstance(value, dict) or value.keys() != _KEYS:
        return False
    if value["ticker"] != ticker or value["currency"] != currency:
        return False
    if any(not _finite_number(value[key]) or value[key] < 0 for key in ("hv20", "hv60")):
        return False
    if not _finite_number(value["observations"]) or value["observations"] != 61:
        return False
    if value["price_basis"] != "PROVIDER_ADJUSTED_CLOSE" or not _source_url(value["source_url"], ticker):
        return False
    digest = value["source_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return False
    start20, start60, asof = (_iso_date(value[key]) for key in ("start_date_20", "start_date_60", "asof_date"))
    if any(day is None or day.weekday() >= 5 for day in (start20, start60, asof)):
        return False
    return (start60 < start20 < asof and 1 <= (capture_date - asof).days <= 4
            and 20 <= (asof - start20).days <= 47 and 60 <= (asof - start60).days <= 127)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def from_yahoo_chart(raw: bytes, ticker: str, currency: str, capture_date: date, source_url: str) -> dict[str, Any] | None:
    """Estimate both 20/60-return sample sigmas from 61 completed closes.

    Both windows are mandatory, including a genuine zero realized variance.
    Later-day prices are ignored, but the digest always binds the entire input.
    """
    if (not _identity(ticker, currency, capture_date) or not _source_url(source_url, ticker)
            or not isinstance(raw, bytes) or not raw or len(raw) > 8 * 1024 * 1024):
        return None
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or not isinstance(payload.get("chart"), dict):
            return None
        chart = payload["chart"]
        results = chart.get("result")
        if chart.get("error") is not None or not isinstance(results, list) or len(results) != 1:
            return None
        result = results[0]
        if not isinstance(result, dict) or not isinstance(result.get("meta"), dict):
            return None
        meta = result["meta"]
        if (meta.get("symbol") != ticker or meta.get("currency") != currency
                or meta.get("instrumentType") not in ("EQUITY", "ETF") or meta.get("dataGranularity") != "1d"):
            return None
        indicators = result.get("indicators")
        if not isinstance(indicators, dict):
            return None
        adjusted = indicators.get("adjclose")
        if not isinstance(adjusted, list) or len(adjusted) != 1 or not isinstance(adjusted[0], dict):
            return None
        closes, stamps = adjusted[0].get("adjclose"), result.get("timestamp")
        if (not isinstance(closes, list) or not isinstance(stamps, list)
                or len(stamps) != len(closes) or not 1 <= len(stamps) <= 4096):
            return None
        completed: list[tuple[date, Any]] = []
        previous_stamp: int | float | None = None
        for stamp, close in zip(stamps, closes):
            if not _finite_number(stamp):
                return None
            day = rules.exchange_date(datetime.fromtimestamp(stamp, timezone.utc), _ZONES[currency])
            if day >= capture_date:
                continue
            if (day.weekday() >= 5 or (previous_stamp is not None and stamp <= previous_stamp)
                    or (completed and day <= completed[-1][0])):
                return None
            previous_stamp = stamp
            completed.append((day, close))
        if len(completed) < 61:
            return None
        selected = completed[-61:]
        if any(not _finite_number(close) or close <= 0 for _, close in selected):
            return None
        # Prefer ratios so identical geometric returns retain zero variance.
        # Log differences handle extreme finite price magnitudes.
        prices = [close for _, close in selected]
        returns = []
        for previous, current in zip(prices, prices[1:]):
            ratio = current / previous
            returns.append(math.log(ratio) if math.isfinite(ratio) and ratio > 0
                           else math.log(current) - math.log(previous))
        def annualized(window: int) -> float:
            sample = returns[-window:]
            mean = math.fsum(sample) / window
            return math.sqrt(math.fsum((value - mean) ** 2 for value in sample) / (window - 1)) * math.sqrt(252)
        evidence = {
            "ticker": ticker, "currency": currency, "hv20": annualized(20), "hv60": annualized(60),
            "observations": 61, "start_date_20": selected[-21][0].isoformat(),
            "start_date_60": selected[0][0].isoformat(), "asof_date": selected[-1][0].isoformat(),
            "source_url": source_url, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "price_basis": "PROVIDER_ADJUSTED_CLOSE",
        }
        return evidence if valid_historical_volatility(evidence, ticker, currency, capture_date) else None
    except (ValueError, TypeError, OverflowError, OSError, RecursionError):
        return None
