"""Pure common-sigma models for complete, prefiltered option ranking cohorts.

Callers verify contract eligibility and historical identity/clock. This module
never filters a supplied cohort, changes its quotes, or prices a trade.
"""
from __future__ import annotations

import math
from typing import Any

import option_recommendation_rules as rules

_MODEL_KEYS = frozenset(("basis", "sigma", "iv_bid", "iv_ask"))
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


def _model_bounds(value: Any) -> bool:
    if not isinstance(value, dict) or value.keys() != _MODEL_KEYS or value["basis"] not in rules.DELTA_MODEL_BASES:
        return False
    sigma, bid, ask = value["sigma"], value["iv_bid"], value["iv_ask"]
    return (all(_number(number) for number in (sigma, bid, ask))
            and 0 <= bid <= sigma <= ask and sigma > 0 and ask > 0)


def valid_delta_model(value: Any, history: Any) -> bool:
    """Check exact model wire, bounds and arithmetic, not source authentication."""
    if not _model_bounds(value):
        return False
    low, high = value["iv_bid"], value["iv_ask"]
    if value["basis"] == "QUOTE_IMPLIED":
        expected = low / 2 + high / 2
    else:
        sigmas = _history_sigmas(history)
        if sigmas is None:
            return False
        expected = min(high, max(*sigmas, low))
    return abs(value["sigma"] - expected) <= 1e-12


def _quote(leg: Any) -> bool:
    return (isinstance(leg, dict) and all(_positive(leg.get(key)) for key in ("strike", "bid", "ask"))
            and leg["ask"] >= leg["bid"])


def _wide(leg: dict[str, Any]) -> bool:
    return ((leg["ask"] - leg["bid"]) / (leg["bid"] / 2 + leg["ask"] / 2)
            > rules.MAX_QUOTE_IMPLIED_SPREAD_RATIO)


def build_delta_model(calls: Any, puts: Any, spot: float, dte: float, history: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Refuse a whole cohort on mixed reliability or incompatible IV brackets."""
    if (not _positive(spot) or not _number(dte) or dte < 0
            or not isinstance(calls, (list, tuple)) or not isinstance(puts, (list, tuple))
            or not (calls or puts)):
        return None, "共同 Delta 模型輸入無效：須有完整合資格合約、正數現價與有效到期日數"
    legs = [(leg, False) for leg in calls] + [(leg, True) for leg in puts]
    if any(not _quote(leg) for leg, _ in legs):
        return None, "共同 Delta 模型拒絕單邊、非有限、非正數或倒掛報價"
    triggers = {_wide(leg) for leg, _ in legs}
    if len(triggers) != 1:
        return None, "共同 Delta 模型拒絕混合窄價差與寬價差合約，不刪除合資格合約以湊出結果"
    wide = next(iter(triggers))
    sigmas = _history_sigmas(history) if wide else None
    if wide and sigmas is None:
        return None, "寬價差共同 Delta 模型缺少經驗證的 61 筆調整後收盤價 HV20/HV60"
    years = max(dte, 1) / 365
    low, high = 0.0, math.inf
    for leg, put in legs:
        inverse = implied_vol_put if put else implied_vol
        bid = inverse(leg["bid"], spot, leg["strike"], years)
        ask = inverse(leg["ask"], spot, leg["strike"], years)
        if bid is None or ask is None or not 0 <= bid <= ask:
            return None, "共同 Delta 模型缺少有限買賣報價 IV 區間：報價超出 Black-Scholes 理論界限"
        low, high = max(low, bid), min(high, ask)
    if low > high:
        return None, "共同 Delta 模型的報價 IV 交集為空，不刪除合資格合約以湊出結果"
    sigma = min(high, max(*sigmas, low)) if sigmas is not None else low / 2 + high / 2
    model = {"basis": "HISTORICAL_VOL" if wide else "QUOTE_IMPLIED", "sigma": sigma, "iv_bid": low, "iv_ask": high}
    if not valid_delta_model(model, history):
        return None, "共同 Delta 模型無有限且嚴格正數的共同波動率"
    return model, None


def model_leg_consistent(leg: Any, model: Any, spot: float, dte: float, *,
                         put: bool = False, band: tuple[float, float] | None = None) -> bool:
    """Check sealed Greeks against common sigma without changing trade prices."""
    if (not _model_bounds(model) or not _quote(leg) or not _positive(spot)
            or not _number(dte) or dte < 0 or leg.get("delta_basis") != model["basis"]):
        return False
    if _wide(leg) != (model["basis"] == "HISTORICAL_VOL"):
        return False
    years = max(dte, 1) / 365
    price = _price(spot, leg["strike"], years, model["sigma"], _RATE, put)
    call_delta = bs_call_delta(spot, leg["strike"], years, model["sigma"], digits=None)
    if price is None or call_delta is None:
        return False
    tolerance = 1e-10 + max(spot, leg["strike"]) * 1e-12
    if not leg["bid"] - tolerance <= price <= leg["ask"] + tolerance:
        return False
    exact = 1 - call_delta if put else call_delta
    displayed = leg.get("delta")
    if not _number(displayed) or not 0 <= displayed <= 1 or abs(displayed - exact) > 0.0005 + 1e-12:
        return False
    if band is not None:
        if (not isinstance(band, (tuple, list)) or len(band) != 2
                or not all(_number(bound) for bound in band) or not 0 <= band[0] <= band[1] <= 1
                or not band[0] - 1e-12 <= exact <= band[1] + 1e-12):
            return False
    if "iv" in leg:
        if model["basis"] == "HISTORICAL_VOL":
            if leg["iv"] is not None:
                return False
        elif not _number(leg["iv"]) or abs(leg["iv"] - round(model["sigma"], 4)) > 0.00005 + 1e-12:
            return False
    return True
