"""Black-Scholes primitives and historical inputs used by the active side model.

Callers verify contract eligibility and historical identity/clock. This module
never selects a cohort, changes its quotes, or prices an order.
"""
from __future__ import annotations

import math
from typing import Any

_RATE = 0.04


def _number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (ValueError, OverflowError):
        return False


def _positive(value: Any) -> bool:
    return _number(value) and value > 0


def _cdf(value: float) -> float:
    return 0.5 * math.erfc(-value / math.sqrt(2))


def _terms(spot: float, strike: float, years: float, vol: float, rate: float) -> tuple[float, float, float] | None:
    if not all(_positive(value) for value in (spot, strike, years, vol)) or not _number(rate):
        return None
    try:
        total = vol * math.sqrt(years)
        discounted = strike * math.exp(-rate * years)
        if not _positive(total) or not _number(discounted):
            return None
        d1 = (math.log(spot) - math.log(strike) + rate * years) / total + total / 2
        d2 = d1 - total
        return (d1, d2, discounted) if not math.isnan(d1) and not math.isnan(d2) else None
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def bs_call_delta(spot: float, strike: float, years: float, vol: float,
                  rate: float = _RATE, digits: int | None = 3) -> float | None:
    """Call delta; digits=None preserves the full-precision selection evidence."""
    terms = _terms(spot, strike, years, vol, rate)
    if terms is None:
        return None
    exact = _cdf(terms[0])
    return exact if digits is None else round(exact, digits)


def _price(spot: float, strike: float, years: float, vol: float, rate: float, put: bool) -> float | None:
    if not all(_positive(value) for value in (spot, strike, years)) or not _number(vol) or vol < 0 or not _number(rate):
        return None
    try:
        if vol == 0:
            discounted = strike * math.exp(-rate * years)
            if not _number(discounted):
                return None
            return max(discounted - spot if put else spot - discounted, 0.0)
        terms = _terms(spot, strike, years, vol, rate)
        if terms is None:
            return None
        d1, d2, discounted = terms
        price = discounted * _cdf(-d2) - spot * _cdf(-d1) if put else spot * _cdf(d1) - discounted * _cdf(d2)
        return max(price, 0.0) if _number(price) else None
    except (ValueError, OverflowError):
        return None


def bs_call_price(spot: float, strike: float, years: float, vol: float, rate: float = _RATE) -> float | None:
    return _price(spot, strike, years, vol, rate, False)


def bs_put_price(spot: float, strike: float, years: float, vol: float, rate: float = _RATE) -> float | None:
    return _price(spot, strike, years, vol, rate, True)


def _invert(price: float, spot: float, strike: float, years: float, put: bool) -> float | None:
    if not _number(price) or price < 0 or not all(_positive(value) for value in (spot, strike, years)):
        return None
    lower_price = _price(spot, strike, years, 0.0, _RATE, put)
    try:
        upper_price = strike * math.exp(-_RATE * years) if put else spot
    except (ValueError, OverflowError):
        return None
    if lower_price is None or not _number(upper_price) or price < lower_price or price >= upper_price:
        return None
    if price == lower_price:
        return 0.0
    low, high = 0.0, 1.0
    while True:
        high_price = _price(spot, strike, years, high, _RATE, put)
        if high_price is None:
            return None
        if high_price >= price:
            break
        low, high = high, high * 2
        if not math.isfinite(high):
            return None
    # Terminate on representable endpoints, not an arbitrary IV ceiling.
    for _ in range(100):
        middle = low / 2 + high / 2
        if middle == low or middle == high:
            break
        middle_price = _price(spot, strike, years, middle, _RATE, put)
        if middle_price is None:
            return None
        if middle_price < price:
            low = middle
        else:
            high = middle
    sigma = low / 2 + high / 2
    return sigma if _positive(sigma) else None


def implied_vol(price: float, spot: float, strike: float, years: float) -> float | None:
    """Finite call IV, including the zero-volatility theoretical endpoint."""
    return _invert(price, spot, strike, years, False)


def implied_vol_put(price: float, spot: float, strike: float, years: float) -> float | None:
    """Finite put IV, with an adaptive rather than fixed upper bracket."""
    return _invert(price, spot, strike, years, True)


def _history_sigmas(history: Any) -> tuple[float, float] | None:
    # Identity, dates, source and hash are separately verified by the caller.
    if not isinstance(history, dict) or not _number(history.get("observations")) or history["observations"] != 61:
        return None
    hv20, hv60 = history.get("hv20"), history.get("hv60")
    if not _number(hv20) or not _number(hv60) or min(hv20, hv60) < 0:
        return None
    return hv20, hv60
