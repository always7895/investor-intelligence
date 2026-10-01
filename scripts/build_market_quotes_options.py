#!/usr/bin/env python3
"""Quotes and listed-option observations for the watch universe (LINE stock lookup and options queries).

Universe: the bottleneck Top20 v3 (top and watch), the carried seven-field Top20 and every layer capturer, plus (operator
2026-09-26: more US names and Swedish large caps) the US_LARGEST largest US listings by market cap in the Nasdaq stock
screener and every Nasdaq Stockholm Large Cap share in SEK with listed exchange options. The broad list is rebuilt daily
(data/cache/options_universe.json); a failed rebuild keeps the previous list for up to BROAD_MAX_STALE_DAYS.
- Quotes: Yahoo Finance last price, previous close and currency (unofficial, delayed; labelled). A US listing Yahoo cannot
  quote falls back to Alpha Vantage GLOBAL_QUOTE (operator 2026-09-26) with the free key from the user's DPAPI file,
  at most ALPHA_VANTAGE_DAILY_BUDGET calls a day (the free key allows 25); without a key there is no fallback call.
- US-listed options: Yahoo Finance option chains (unofficial, delayed); a cycle Yahoo cannot read falls back to the
  Nasdaq US option chain (operator 2026-09-26: Nasdaq data stays in use). Alpha Vantage option chains are premium-only.
- Nasdaq Stockholm options (for example SIVE.ST): the exchange's public option-chain API (api.nasdaq.com/api/nordic).
Per underlying and cycle (weekly 3-14 DTE, monthly 21-45 DTE): two covered-call sell suggestions for a holder of 100
shares (operator 2026-09-26: collect premium, keep the strike as high as possible so the shares are not called away):
- HIGH_STRIKE: the highest out-of-the-money strike whose bid still pays at least MIN_ANNUALIZED_YIELD with delta <=
  MAX_HIGH_STRIKE_DELTA; strikes with a spread wider than the mid, or without a delta, are ignored;
- BALANCED: a lower strike nearest delta BALANCED_DELTA (or BALANCED_MONEYNESS without a delta) for more premium.
Each carries a sell limit (mid rounded down to the tick, or bid + a quarter of the spread when the spread exceeds 25% of
the mid; never below the bid), premium per contract, period and
annualized yield on the current price, the upside kept up to the strike, delta as the assignment reference, OI, volume
and spread. Delta is Black-Scholes from the quoted implied volatility (a labelled model Greek); a chain without one
(Nasdaq Stockholm, the Nasdaq US fallback) takes the volatility implied by the strike's own bid/ask mid instead
(delta_basis QUOTE_IMPLIED), so every high strike carries the same assignment cap. Prices are never modelled. A cycle
without two-sided quotes stays unavailable with its reason.

Raw two-sided quote health is measured before strategy filtering per venue (US and STOCKHOLM). When coverage is depleted
(R > 0 and 10*H < R for any venue), the candidate is rejected with OPTION_TWO_SIDED_COVERAGE_LOW and exit code 1 to
preserve the previous observation file without modification.

Output: data/cache/market_quotes_options.json. Observation only; nothing here is an order.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "cache" / "market_quotes_options.json"
BROAD = ROOT / "data" / "cache" / "options_universe.json"
V3 = ROOT / "data" / "cache" / "bottleneck_top20_v3.json"
LAYERS = ROOT / "config" / "bottleneck-layers-v3.json"
ADR_MAP = ROOT / "config" / "option-adr-map-v1.json"  # listings answered with their US ADR's options
TOP20 = ROOT / "data" / "cache" / "top20-lkg"
NORDIC_SEARCH = "https://api.nasdaq.com/api/nordic/search?searchText={symbol}"
NORDIC_CHAIN = "https://api.nasdaq.com/api/nordic/instruments/{orderbook}/option-chain"
US_SCREENER = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"
STOCKHOLM_LARGE_CAP = "https://api.nasdaq.com/api/nordic/screener/shares?category=MAIN_MARKET&tableonly=false&market=STO&segment=LARGE_CAP"
NASDAQ_US_CHAIN = ("https://api.nasdaq.com/api/quote/{symbol}/option-chain?assetclass=stocks&limit=5000&fromdate={start}"
                   "&todate={end}&excode=oprac&callput=callput&money=all&type=all")
ALPHA_VANTAGE_QUOTE = "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}"  # the key is never part of it
ALPHA_VANTAGE_DAILY_BUDGET = 20  # of the free key's 25 a day; a Yahoo outage would otherwise spend it in one run
ALPHA_VANTAGE_BUDGET = ROOT / "data" / "cache" / "alphavantage-budget.json"
ALPHA_VANTAGE_KEY_FILE = "alphavantage-key.local.txt"  # ConvertFrom-SecureString output under the user config root
US_LARGEST = 200              # by market cap (operator 2026-09-27: wider than 100); share classes each keep their own chain
BROAD_MAX_AGE_HOURS = 24
BROAD_MAX_STALE_DAYS = 7
WORKERS = 4
# The whole run must end well inside the hourly refresh (the task starts at :12 and the next seal follows). One absolute
# deadline; universe discovery gets the first DISCOVERY_SHARE of it and falls back to the cached list when it overruns. All
# network work runs on daemon threads the process never waits for; each thread carries its own deadline; no request starts
# after it, a request's timeout never exceeds the time left, and a response body that trickles is cut at the deadline.
COLLECTION_DEADLINE_SECONDS = 20 * 60
DISCOVERY_SHARE = 0.25
REQUEST_TIMEOUT_SECONDS = 20
_DEADLINE = [math.inf]  # the run's deadline (monotonic), for threads that carry none of their own
_LOCAL = threading.local()  # .deadline: the deadline of the work this thread does
# A run that finished fewer underlyings than this is not published: the previous file stays (the sealer bounds its age).
MIN_COMPLETED_SHARE = 0.5
CYCLES = {"weekly": (3, 14), "monthly": (21, 45)}  # monthly: the expiry nearest 30 days within 21-45 DTE
RISK_FREE = 0.04
MIN_ANNUALIZED_YIELD = 0.06   # premium worth collecting versus cash (annualized, on the current price)
MAX_HIGH_STRIKE_DELTA = 0.20  # the high-strike suggestion keeps the model assignment reference low
BALANCED_DELTA = 0.30
BALANCED_MONEYNESS = 1.05     # when a lower strike has no delta at all, about 5% out of the money
TICK = 0.01
MAX_SPREAD_PCT = 1.0          # a spread wider than the mid is not a tradeable quote
WIDE_SPREAD_PCT = 0.25        # beyond this the limit moves from the mid towards the bid
OPTION_TWO_SIDED_COVERAGE_RATIO_NUMERATOR = 1
OPTION_TWO_SIDED_COVERAGE_RATIO_DENOMINATOR = 10
# Policy threshold: strictly below 1/10 (10%) two-sided coverage across read chains triggers guard
OPTION_TWO_SIDED_COVERAGE_THRESHOLD = OPTION_TWO_SIDED_COVERAGE_RATIO_NUMERATOR / OPTION_TWO_SIDED_COVERAGE_RATIO_DENOMINATOR


def _is_finite_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _is_two_sided(bid: Any, ask: Any) -> bool:
    return (isinstance(bid, (int, float)) and not isinstance(bid, bool)
            and isinstance(ask, (int, float)) and not isinstance(ask, bool)
            and math.isfinite(bid) and math.isfinite(ask)
            and 0 < bid <= ask)


def _cent_exact(strike: Any) -> bool:
    """True when the strike is exactly representable with two decimals (15.5, 15.50, 15.5000, 0.07 yes; 15.505, 15.5049 no):
    the immutable reader formats money with two decimals, so only such a strike may be RECOMMENDED; nothing is ever rounded."""
    return (isinstance(strike, (int, float)) and not isinstance(strike, bool) and math.isfinite(strike) and strike == round(strike, 2))


def is_venue_coverage_depleted(read_count: int, healthy_count: int) -> bool:
    """True when read_count > 0 and healthy_count / read_count < 1/10 (strictly below 10%).

    Exact integer ratio comparison avoids floating point imprecision:
    healthy_count * DENOMINATOR < read_count * NUMERATOR.
    1/10 (10/100) -> 1 * 10 < 10 * 1 is False (admitted).
    1/11 -> 1 * 10 < 11 * 1 is True (10 < 11, rejected).
    """
    return (read_count > 0
            and healthy_count * OPTION_TWO_SIDED_COVERAGE_RATIO_DENOMINATOR < read_count * OPTION_TWO_SIDED_COVERAGE_RATIO_NUMERATOR)


class CyclesResult(dict):
    """Cycle observation mapping carrying run-local raw chain health evidence."""
    def __init__(self, *args, health: list[dict[str, Any]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.health: list[dict[str, Any]] = list(health or [])


class Observation(tuple):
    """(quote, symbol, cycles) 3-tuple carrying run-local raw chain health evidence."""
    def __new__(cls, quote: dict[str, Any], symbol: str, cycles: dict[str, Any],
                health: list[dict[str, Any]] | None = None):
        return super().__new__(cls, (quote, symbol, cycles))

    def __init__(self, quote: dict[str, Any], symbol: str, cycles: dict[str, Any],
                 health: list[dict[str, Any]] | None = None):
        self.quote = quote
        self.symbol = symbol
        self.cycles = cycles
        self.health: list[dict[str, Any]] = list(health if health is not None else getattr(cycles, "health", []))


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _request_until() -> float:
    """The absolute end of a request started now: REQUEST_TIMEOUT_SECONDS, never past this thread's deadline; past the
    deadline no request starts."""
    now = time.monotonic()
    until = min(now + REQUEST_TIMEOUT_SECONDS, getattr(_LOCAL, "deadline", _DEADLINE[0]))
    if until <= now:
        raise TimeoutError("COLLECTION_DEADLINE")
    return until


def http_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (InvestorIntelligence public observation)"})
    until = _request_until()
    with urllib.request.urlopen(request, timeout=until - time.monotonic()) as response:  # noqa: S310 - fixed public hosts
        body = bytearray()
        while chunk := response.read(65536):  # a body that trickles is cut at the request's end, not only per read
            body += chunk
            if time.monotonic() > until:
                raise TimeoutError("RESPONSE_BODY_DEADLINE")
        return json.loads(bytes(body).decode("utf-8"))


def universe() -> list[str]:
    symbols: list[str] = []
    try:
        doc = json.loads(V3.read_text(encoding="utf-8"))
        symbols += [row["symbol"] for row in doc["top"]] + [row["symbol"] for row in doc.get("watch", [])]
    except (OSError, ValueError, KeyError):
        pass
    try:
        for layer in json.loads(LAYERS.read_text(encoding="utf-8"))["layers"]:
            symbols += [row["symbol"] for row in layer["capturers"]]
    except (OSError, ValueError, KeyError):
        pass
    try:
        import top20_carry_forward  # the newest LKG by run id (refresh-state.json is not a bundle)
        newest = top20_carry_forward.newest_lkg(TOP20)
        if newest:
            bundle = json.loads(newest.read_text(encoding="utf-8"))
            symbols += [row["ticker"] for row in json.loads(bundle["payloads"]["top20_json"])]
    except (OSError, ValueError, KeyError, IndexError):
        pass
    try:  # the US ADRs that answer option queries for their home listings (TSMC -> TSM)
        symbols += [row["adr"] for row in json.loads(ADR_MAP.read_text(encoding="utf-8"))["listings"].values()]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    seen: dict[str, None] = {}
    for symbol in symbols:
        seen.setdefault(str(symbol).upper(), None)
    return list(seen)


def _market_cap(row: dict[str, Any]) -> float:
    return _float(row.get("marketCap")) or 0.0


def _has_listed_options(orderbook: str) -> bool | None:
    """True or False from the exchange option chain; None when the chain could not be read."""
    try:
        rows = ((http_json(NORDIC_CHAIN.format(orderbook=orderbook)).get("data") or {}).get("instrumentListing") or {}).get("rows") or []
    except Exception:
        return None
    return any(row.get("assetClass") == "OPTIONS" for row in rows)


def build_broad(now: datetime) -> dict[str, Any]:
    """The US_LARGEST US listings by market cap (Yahoo symbols: BRK/B -> BRK-B) and the Stockholm Large Cap shares in SEK
    whose exchange option chain lists options (Yahoo symbol VOLV-B.ST, Nasdaq Nordic order book kept for the chain)."""
    rows = http_json(US_SCREENER)["data"]["rows"]
    largest = sorted((row for row in rows if _market_cap(row) > 0), key=_market_cap, reverse=True)[:US_LARGEST]
    us = [str(row["symbol"]).strip().upper().replace("/", "-") for row in largest]
    shares = http_json(STOCKHOLM_LARGE_CAP)["data"]["instrumentListing"]["rows"]
    shares = [row for row in shares if row.get("assetClass") == "SHARES" and row.get("currency") == "SEK" and row.get("orderbookId")]
    # Daemon workers under this thread's deadline: a check that never finishes counts as unreadable.
    checked = collect([row["orderbookId"] for row in shares], _has_listed_options, getattr(_LOCAL, "deadline", _DEADLINE[0]))
    listed = [checked.get(row["orderbookId"]) for row in shares]
    if sum(1 for ok in listed if ok is None) * 10 > len(shares):
        raise ValueError("BROAD_OPTION_CHECK_FAILED")  # more than 10% unreadable: keep the previous list instead
    sweden = {str(row["symbol"]).strip().upper().replace(" ", "-") + ".ST": row["orderbookId"] for row, ok in zip(shares, listed) if ok}
    if len(us) < US_LARGEST // 2 or not sweden:
        raise ValueError("BROAD_UNIVERSE_TOO_SMALL")
    return {"schema": "v213-options-universe-v1", "generated_at": iso(now), "us": us, "sweden": sweden,
            "sources": [US_SCREENER, STOCKHOLM_LARGE_CAP, NORDIC_CHAIN]}


def cached_universe(now: datetime, path: Path | None = None) -> dict[str, Any]:
    """The cached broad list while it is younger than BROAD_MAX_STALE_DAYS, else an empty list (no network)."""
    try:
        cached = json.loads((path or BROAD).read_text(encoding="utf-8"))
        age = now - datetime.strptime(cached["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if cached.get("schema") == "v213-options-universe-v1" and isinstance(cached.get("us"), list) \
                and isinstance(cached.get("sweden"), dict) and age.days < BROAD_MAX_STALE_DAYS:
            return cached
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"us": [], "sweden": {}}


def broad_universe(now: datetime, path: Path | None = None) -> dict[str, Any]:
    """The cached broad list when younger than BROAD_MAX_AGE_HOURS; otherwise a rebuild, falling back to the cached list
    while it is younger than BROAD_MAX_STALE_DAYS, else an empty list (the watch universe still runs)."""
    path = path or BROAD
    cached: dict[str, Any] | None = None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        age = now - datetime.strptime(cached["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if (cached.get("schema") != "v213-options-universe-v1" or not isinstance(cached.get("us"), list)
                or not isinstance(cached.get("sweden"), dict) or not cached["us"] or not cached["sweden"]):
            cached = None
        elif age.total_seconds() < BROAD_MAX_AGE_HOURS * 3600:
            return cached
        elif age.days >= BROAD_MAX_STALE_DAYS:
            cached = None
    except (OSError, ValueError, KeyError, TypeError):
        cached = None
    try:
        document = build_broad(now)
    except Exception:
        return cached or {"us": [], "sweden": {}}
    try:  # the cache only saves the next rebuild; a write failure never blocks this run
        temp = path.with_name(path.name + ".tmp")
        temp.write_bytes(json.dumps(document, ensure_ascii=False).encode("utf-8"))
        temp.replace(path)
    except OSError:
        pass
    return document


def bs_call_delta(spot: float, strike: float, years: float, vol: float | None, digits: int | None = 3) -> float | None:
    """Black-Scholes call delta, rounded for display; digits=None keeps full precision for limit checks."""
    if not vol or vol <= 0 or years <= 0 or spot <= 0 or strike <= 0:
        return None
    d1 = (math.log(spot / strike) + (RISK_FREE + vol * vol / 2) * years) / (vol * math.sqrt(years))
    delta = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    return round(delta, digits) if digits is not None else delta


def bs_call_price(spot: float, strike: float, years: float, vol: float) -> float:
    d1 = (math.log(spot / strike) + (RISK_FREE + vol * vol / 2) * years) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    return spot * cdf(d1) - strike * math.exp(-RISK_FREE * years) * cdf(d2)


def implied_vol(price: float, spot: float, strike: float, years: float) -> float | None:
    """The Black-Scholes volatility that reproduces a quoted call price (bisection between 1% and 500%); None when the
    quote lies outside that range."""
    low, high = 0.01, 5.0
    if price <= 0 or years <= 0 or spot <= 0 or strike <= 0 or not bs_call_price(spot, strike, years, low) < price < bs_call_price(spot, strike, years, high):
        return None
    for _ in range(60):
        mid = (low + high) / 2
        if bs_call_price(spot, strike, years, mid) < price:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def with_delta(row: dict[str, Any], spot: float, dte: int) -> dict[str, Any]:
    """The row with its assignment reference: the quoted delta, else Black-Scholes from the quoted implied volatility,
    else from the volatility implied by its own bid/ask mid (labelled QUOTE_IMPLIED). delta_exact keeps full precision
    for the limit check (a rounded 0.200 must not admit 0.2003); delta and iv are rounded for display."""
    years = dte / 365
    if row.get("delta") is not None:  # the Yahoo path computes it from the quoted IV when parsing
        exact = bs_call_delta(spot, row["strike"], years, row["iv"], digits=None) if row.get("iv") else row["delta"]
        return {**row, "delta_exact": exact, "delta_basis": "QUOTED_IV" if row.get("iv") else "QUOTED"}
    if row.get("iv"):
        exact = bs_call_delta(spot, row["strike"], years, row["iv"], digits=None)
        return {**row, "delta": round(exact, 3) if exact is not None else None, "delta_exact": exact, "delta_basis": "QUOTED_IV"}
    vol = implied_vol((row["bid"] + row["ask"]) / 2, spot, row["strike"], years)
    if vol is None:
        return {**row, "delta_basis": None}
    exact = bs_call_delta(spot, row["strike"], years, vol, digits=None)
    return {**row, "iv": round(vol, 4), "delta": round(exact, 3), "delta_exact": exact, "delta_basis": "QUOTE_IMPLIED"}


def _int(value: Any) -> int | None:
    try:
        text = str(value).replace(",", "").strip()
        return int(float(text)) if text and math.isfinite(float(text)) else None
    except ValueError:
        return None


def _float(value: Any) -> float | None:
    try:
        text = str(value).replace(",", "").strip()
        number = float(text) if text else None
        return number if number is not None and math.isfinite(number) else None
    except ValueError:
        return None


def _suggestion(role: str, row: dict[str, Any], spot: float, dte: int) -> dict[str, Any]:
    bid, ask = row["bid"], row["ask"]
    mid = round((bid + ask) / 2, 4)
    spread_pct = (ask - bid) / mid if mid > 0 else 0.0
    target = mid if spread_pct <= WIDE_SPREAD_PCT else bid + (ask - bid) / 4
    limit = round(max(bid, math.floor(target / TICK + 1e-9) * TICK), 2)
    period_yield = limit / spot
    return {"role": role, "strike": row["strike"], "bid": bid, "ask": ask, "mid": mid, "limit_price": limit,
            "premium_per_contract": round(limit * 100, 2), "period_yield": round(period_yield, 6),
            "annualized_yield": round(period_yield * 365 / dte, 6), "upside_to_strike": round(row["strike"] / spot - 1, 6),
            "delta": row.get("delta"), "delta_basis": row.get("delta_basis"), "iv": row.get("iv") or None, "oi": row.get("oi"), "volume": row.get("volume"),
            "spread_pct": round((ask - bid) / mid, 4) if mid > 0 else None}


def covered_call_suggestions(rows: list[dict[str, Any]], spot: float, dte: int, *, cent_exact_only: bool = True) -> list[dict[str, Any]]:
    """Up to two sell-call suggestions for a holder of 100 shares: the highest strike still worth selling, then a
    balanced strike below it. Only out-of-the-money strikes with a two-sided quote qualify, and the high strike needs a
    delta (quoted or implied by its quote) within MAX_HIGH_STRIKE_DELTA. Only a strike the two-decimal display represents exactly
    is recommended (cent_exact_only); health is computed before and never depends on this fence."""
    if dte <= 0:
        return []
    usable = [with_delta(row, spot, dte) for row in rows if row.get("strike") and row["strike"] > spot and row.get("bid")
              and row.get("ask") and row["ask"] >= row["bid"] > 0
              and (row["ask"] - row["bid"]) / ((row["ask"] + row["bid"]) / 2) <= MAX_SPREAD_PCT
              and (not cent_exact_only or _cent_exact(row["strike"]))]
    if not usable:
        return []
    annual = lambda row: row["bid"] / spot * 365 / dte  # noqa: E731 - on the bid: premium that is actually collectable
    high = [row for row in usable if annual(row) >= MIN_ANNUALIZED_YIELD
            and row.get("delta_exact") is not None and row["delta_exact"] <= MAX_HIGH_STRIKE_DELTA]
    if not high:
        return []
    first = max(high, key=lambda row: row["strike"])
    suggestions = [_suggestion("HIGH_STRIKE", first, spot, dte)]
    lower = [row for row in usable if row["strike"] < first["strike"] and annual(row) > annual(first)]
    if lower:
        if all(row.get("delta") is not None for row in lower):
            second = min(lower, key=lambda row: abs(row["delta"] - BALANCED_DELTA))
        else:
            second = min(lower, key=lambda row: abs(row["strike"] / spot - BALANCED_MONEYNESS))
        suggestions.append(_suggestion("BALANCED", second, spot, dte))
    return suggestions


def cycle_result(ticker: str, expiry: str, dte: int, spot: float, rows: list[dict[str, Any]], *, currency: str, source: str,
                 provenance: str, rights: str, stamp: str) -> dict[str, Any]:
    suggestions = covered_call_suggestions(rows, spot, dte)
    if not suggestions:
        if covered_call_suggestions(rows, spot, dte, cent_exact_only=False):  # the unchanged filters accept it; only the display precision cannot
            return {"unavailable": _diag(f"本次回應有 {expiry}（{dte}天）有效雙邊報價，但符合條件之履約價含兩位以上小數，顯示無法如實呈現；不提供建議")}
        return {"unavailable": f"{expiry} 到期的價外買權中，沒有年化權利金達 {MIN_ANNUALIZED_YIELD:.0%} 且有雙邊報價的履約價"}
    return {"ticker": ticker, "strategy": "COVERED_CALL", "expiry": expiry, "dte": dte, "spot": spot, "currency": currency,
            "multiplier": 100, "quote_basis": "delayed", "timestamp": stamp, "source": source, "provenance": provenance,
            "rights_status": rights, "suggestions": suggestions}


def _cycles_from_calls(calls: list[dict[str, Any]], ticker: str, spot: float, stamp: str, *, currency: str, source: str,
                       provenance: str, rights: str, missing: str, venue: str = "US",
                       underlying: str | None = None,
                       no_window: Callable[[str, int, int], tuple[str, str]] | None = None) -> CyclesResult:
    """Weekly: the nearest expiry in its window; monthly: the expiry nearest 30 days within 21-45 DTE. Standard 100-share
    contracts only. A cycle without a qualifying expiry takes its reason and health status from no_window(cycle, low,
    high) when the caller proved more about its source than 'nothing listed'."""
    out: dict[str, Any] = {}
    health_records: list[dict[str, Any]] = []
    und = underlying or ticker
    for cycle, (low, high) in CYCLES.items():
        window = [row for row in calls if low <= row["dte"] <= high and row["strike"] and row["size"] == 100]
        if not window:
            message, status = no_window(cycle, low, high) if no_window else (missing.format(low=low, high=high), "NO_EXPIRY")
            health_records.append({"venue": venue, "underlying": und, "expiry": None, "cycle": cycle,
                                   "status": status, "read": False, "two_sided": False})
            out[cycle] = {"unavailable": _diag(message)}
            continue
        target = min(row["dte"] for row in window) if cycle == "weekly" else min({row["dte"] for row in window}, key=lambda days: abs(days - 30))
        chosen = [row for row in window if row["dte"] == target]
        chosen_expiry = chosen[0]["expiry"]
        eligible = [r for r in chosen if _is_finite_positive(r.get("strike")) and r.get("size") == 100]
        if not eligible:
            health_records.append({"venue": venue, "underlying": und, "expiry": chosen_expiry, "cycle": cycle,
                                   "status": "EMPTY", "read": False, "two_sided": False})
            out[cycle] = {"unavailable": _diag(f"{chosen_expiry} 到期之上市買權無有效履約價")}
            continue
        two_sided = any(_is_two_sided(r.get("bid"), r.get("ask")) for r in eligible)
        health_records.append({"venue": venue, "underlying": und, "expiry": chosen_expiry, "cycle": cycle,
                               "status": "READ", "read": True, "two_sided": two_sided, "eligible_rows": len(eligible)})
        if not two_sided:
            out[cycle] = {"unavailable": _diag(f"本次回應有 {chosen_expiry}（{target}天）標準買權上市，但所選到期無有效雙邊報價（買賣價須為正且不倒掛）")}
        else:
            out[cycle] = cycle_result(ticker, chosen_expiry, target, spot, chosen, currency=currency, source=source,
                                      provenance=provenance, rights=rights, stamp=stamp)
    return CyclesResult(out, health=health_records)


def nasdaq_us_options(symbol: str, spot: float, today: date, stamp: str) -> CyclesResult:
    """Fallback US chain from Nasdaq's public quote-page API: two-sided call quotes without implied volatility, so no
    delta (as for Nasdaq Stockholm). Class shares use a dot there (BRK-B -> brk.b)."""
    low, high = min(window[0] for window in CYCLES.values()), max(window[1] for window in CYCLES.values())
    url = NASDAQ_US_CHAIN.format(symbol=urllib.parse.quote(symbol.replace("-", ".").lower()),
                                 start=(today + timedelta(days=low)).isoformat(), end=(today + timedelta(days=high)).isoformat())
    try:
        rows = http_json(url)["data"]["table"]["rows"]
        if rows is None:
            rows = []
    except Exception:
        err_health = [{"venue": "US", "underlying": symbol, "expiry": None, "cycle": c,
                       "status": "READ_ERROR", "read": False, "two_sided": False} for c in CYCLES]
        return CyclesResult({cycle: {"unavailable": "Nasdaq 期權鏈讀取失敗"} for cycle in CYCLES}, health=err_health)
    if not rows:
        empty_health = [{"venue": "US", "underlying": symbol, "expiry": None, "cycle": c,
                         "status": "EMPTY_RESPONSE", "read": False, "two_sided": False} for c in CYCLES]
        return CyclesResult({c: {"unavailable": f"Nasdaq 無 {CYCLES[c][0]}-{CYCLES[c][1]} 天到期的上市期權"} for c in CYCLES},
                            health=empty_health)
    calls: list[dict[str, Any]] = []
    expiry: date | None = None
    for row in rows:
        if row.get("expirygroup"):  # a header row ("October 2, 2026") precedes the strikes of each expiry
            try:
                expiry = datetime.strptime(str(row["expirygroup"]), "%B %d, %Y").date()
            except ValueError:
                expiry = None
            continue
        if expiry is None:
            continue
        calls.append({"expiry": expiry.isoformat(), "dte": (expiry - today).days, "strike": _float(row.get("strike")),
                      "bid": _float(row.get("c_Bid")), "ask": _float(row.get("c_Ask")), "iv": None, "delta": None,
                      "oi": _int(row.get("c_Openinterest")), "volume": _int(row.get("c_Volume")), "size": 100})
    return _cycles_from_calls(calls, symbol, spot, stamp, currency="USD",
                              source="Nasdaq US option chain (public quote page API, delayed; Yahoo fallback)",
                              provenance=f"https://www.nasdaq.com/market-activity/stocks/{symbol.replace('-', '.').lower()}/option-chain",
                              rights="candidate_local_review", missing="Nasdaq 無 {low}-{high} 天到期的上市期權",
                              venue="US", underlying=symbol)


def _yahoo_unread(value: dict[str, Any] | None) -> bool:
    reason = str((value or {"unavailable": "讀取失敗"}).get("unavailable", ""))
    return "讀取失敗" in reason or "Yahoo Finance 期權到期日清單" in reason


def us_cycles(symbol: str, spot: float, today: date, stamp: str) -> CyclesResult:
    """Yahoo first; only the cycles Yahoo could not read (no expiry list, a failed chain) try the Nasdaq chain once.
    A cycle Yahoo read without a qualifying strike keeps that reason."""
    try:
        out = us_options(symbol, spot, today, stamp)
    except Exception:
        out = CyclesResult({cycle: {"unavailable": "期權鏈讀取失敗"} for cycle in CYCLES},
                           health=[{"venue": "US", "underlying": symbol, "expiry": None, "cycle": c,
                                    "status": "READ_ERROR", "read": False, "two_sided": False} for c in CYCLES])
    yahoo_health = list(getattr(out, "health", []) or [])
    retry = [cycle for cycle in CYCLES if _yahoo_unread(out.get(cycle))]
    if not retry:
        return out if isinstance(out, CyclesResult) else CyclesResult(out, health=yahoo_health)
    fallback = nasdaq_us_options(symbol, spot, today, stamp)
    fallback_health = list(getattr(fallback, "health", []) or [])
    combined_health = [h for h in yahoo_health if h.get("cycle") not in retry]
    combined_health += [h for h in fallback_health if h.get("cycle") in retry]
    for cycle in retry:
        value = fallback.get(cycle) or {"unavailable": ""}
        if "unavailable" not in value:
            out[cycle] = value
        elif "讀取失敗" in str((out.get(cycle) or {}).get("unavailable", "讀取失敗")):
            out[cycle] = {"unavailable": "期權鏈讀取失敗（Yahoo 與 Nasdaq 備援）"}
        else:
            out[cycle] = {"unavailable": str(value["unavailable"])}
    return CyclesResult(out, health=combined_health)


def _dpapi_unprotect(blob: bytes) -> str:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buffer = ctypes.create_string_buffer(blob, len(blob))  # kept referenced until the call returns
    source = Blob(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise OSError("DPAPI_UNPROTECT_FAILED")
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-16-le")
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def alpha_vantage_key() -> str | None:
    """ALPHAVANTAGE_API_KEY, else the user's DPAPI file named by install-state.json; decrypted into this process only
    (never printed, logged or written). None when neither exists."""
    explicit = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
    if explicit:
        return explicit
    try:
        state = json.loads(Path(os.environ["LOCALAPPDATA"], "InvestorIntelligence", "install-state.json").read_text(encoding="utf-8-sig"))
        text = (Path(state["user_config_root"]) / ALPHA_VANTAGE_KEY_FILE).read_text(encoding="utf-8-sig").strip()
        return _dpapi_unprotect(bytes.fromhex(text)).strip() or None
    except Exception:
        return None


_BUDGET_LOCK = threading.Lock()


def _alpha_vantage_budget(day: str, exhaust: bool = False) -> bool:
    """Takes one call from today's budget (UTC day); exhaust=True marks the day spent after a rate-limit reply."""
    with _BUDGET_LOCK:
        try:
            state = json.loads(ALPHA_VANTAGE_BUDGET.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        used = int(state.get("calls", 0)) if isinstance(state, dict) and state.get("date") == day else 0
        if not exhaust and used >= ALPHA_VANTAGE_DAILY_BUDGET:
            return False
        ALPHA_VANTAGE_BUDGET.parent.mkdir(parents=True, exist_ok=True)
        calls = ALPHA_VANTAGE_DAILY_BUDGET if exhaust else used + 1
        ALPHA_VANTAGE_BUDGET.write_text(json.dumps({"date": day, "calls": calls}), encoding="utf-8")
        return True


def alpha_vantage_quote(symbol: str, stamp: str) -> dict[str, Any] | None:
    """Fallback US quote (latest trading day's price and previous close). None without a key, beyond the day's budget,
    on a rate-limit or error reply; the key never appears in the output or in an error."""
    key = alpha_vantage_key()
    if not key or not _alpha_vantage_budget(stamp[:10]):
        return None
    public_url = ALPHA_VANTAGE_QUOTE.format(symbol=urllib.parse.quote(symbol))
    try:
        document = http_json(public_url + "&" + urllib.parse.urlencode({"apikey": key}))
    except Exception:
        return None
    if not isinstance(document, dict):
        return None
    if "Information" in document or "Note" in document:  # the free key's daily or per-minute limit
        _alpha_vantage_budget(stamp[:10], exhaust=True)
        return None
    row = document.get("Global Quote") or {}
    price, previous = _float(row.get("05. price")), _float(row.get("08. previous close"))
    day = str(row.get("07. latest trading day") or "")
    if not price or price <= 0 or len(day) != 10:
        return None
    return {"symbol": symbol, "display": symbol, "price": price, "previous_close": previous,
            "change_pct": (price / previous - 1) if previous else None, "currency": "USD", "asof": day,
            "source": "Alpha Vantage GLOBAL_QUOTE（免費金鑰，最近交易日；Yahoo 備援）", "source_url": public_url}


def us_options(symbol: str, spot: float, today: date, stamp: str) -> CyclesResult:
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    out: dict[str, Any] = {}
    health_records: list[dict[str, Any]] = []
    try:
        expiries_raw = ticker.options
        expiries = list(expiries_raw) if expiries_raw is not None else []
        expiry_list_error = False
    except Exception:
        expiries = []
        expiry_list_error = True
    for cycle, (low, high) in CYCLES.items():
        if expiry_list_error:
            health_records.append({"venue": "US", "underlying": symbol, "expiry": None, "cycle": cycle,
                                   "status": "EXPIRY_LIST_ERROR", "read": False, "two_sided": False})
            out[cycle] = {"unavailable": f"無 {low}-{high} 天到期的上市期權（Yahoo Finance 期權到期日清單）"}
            continue
        if not expiries:
            health_records.append({"venue": "US", "underlying": symbol, "expiry": None, "cycle": cycle,
                                   "status": "EMPTY_RESPONSE", "read": False, "two_sided": False})
            out[cycle] = {"unavailable": f"無 {low}-{high} 天到期的上市期權（Yahoo Finance 期權到期日清單）"}
            continue
        candidates = [(expiry, (date.fromisoformat(expiry) - today).days) for expiry in expiries]
        candidates = [item for item in candidates if low <= item[1] <= high]
        if not candidates:
            health_records.append({"venue": "US", "underlying": symbol, "expiry": None, "cycle": cycle,
                                   "status": "NO_EXPIRY", "read": False, "two_sided": False})
            out[cycle] = {"unavailable": f"無 {low}-{high} 天到期的上市期權（Yahoo Finance 期權到期日清單）"}
            continue
        expiry, dte = min(candidates, key=lambda item: item[1]) if cycle == "weekly" else min(candidates, key=lambda item: abs(item[1] - 30))
        try:
            chain = ticker.option_chain(expiry).calls
        except Exception:
            health_records.append({"venue": "US", "underlying": symbol, "expiry": expiry, "cycle": cycle,
                                   "status": "READ_ERROR", "read": False, "two_sided": False})
            out[cycle] = {"unavailable": "期權鏈讀取失敗"}
            continue
        rows = []
        eligible_rows = []
        for row in chain.itertuples():
            strike = _float(getattr(row, "strike", None))
            bid = _float(getattr(row, "bid", None))
            ask = _float(getattr(row, "ask", None))
            iv = _float(getattr(row, "impliedVolatility", None))
            oi = _int(getattr(row, "openInterest", None))
            vol = _int(getattr(row, "volume", None))
            if strike is not None and _is_finite_positive(strike):
                r_dict = {"strike": float(strike), "bid": bid, "ask": ask, "iv": iv,
                          "delta": bs_call_delta(spot, float(strike), dte / 365, iv), "oi": oi, "volume": vol}
                rows.append(r_dict)
                eligible_rows.append(r_dict)
        if not eligible_rows:
            health_records.append({"venue": "US", "underlying": symbol, "expiry": expiry, "cycle": cycle,
                                   "status": "EMPTY", "read": False, "two_sided": False})
        else:
            two_sided = any(_is_two_sided(r["bid"], r["ask"]) for r in eligible_rows)
            health_records.append({"venue": "US", "underlying": symbol, "expiry": expiry, "cycle": cycle,
                                   "status": "READ", "read": True, "two_sided": two_sided, "eligible_rows": len(eligible_rows)})
        if eligible_rows and not two_sided:  # read chain, no usable quote: say so, not a strategy-yield failure
            out[cycle] = {"unavailable": _diag(f"本次回應有 {expiry}（{dte}天）買權，但所選到期無有效雙邊報價（買賣價須為正且不倒掛）")}
            continue
        out[cycle] = cycle_result(symbol, expiry, dte, spot, rows, currency="USD",
                                  source="Yahoo Finance option chain (unofficial, delayed)",
                                  provenance=f"https://finance.yahoo.com/quote/{symbol}/options?date={expiry}; delta=Black-Scholes(quoted IV)",
                                  rights="unadmitted_third_party", stamp=stamp)
    return CyclesResult(out, health=health_records)


SEK = "SEK"
_NO_SEARCH = object()
_NORDIC_CALL_NAME = re.compile(r"^([A-Z0-9]{1,12}) ([0-3][0-9])([A-Z]{3})([0-9]{2}) ([0-9]{1,6}(?:\.[0-9]{1,4})?)C$")
_MONTH_NUMBER = {name: number for number, name in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
NORDIC_SOURCE = "Nasdaq Nordic option chain (exchange public web API, delayed)"


def _diag(text: str) -> str:
    """Generated diagnostics are bounded (the sealer and the Worker both cap strings at 200; the reason stays first)."""
    return text if len(text) <= 180 else text[:180]


def _typed_currency(value: Any) -> str:
    """OK only for the exact canonical SEK string. CONFLICT for another canonical three-letter currency. UNKNOWN for
    everything else: missing, null, empty, whitespace, non-canonical text, bool, number (incl. non-finite), list, dict."""
    if not isinstance(value, str) or not value.strip():
        return "UNKNOWN"
    if value == SEK:
        return "OK"
    return "CONFLICT" if re.fullmatch(r"[A-Z]{3}", value) else "UNKNOWN"


_CANONICAL_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_MAX_DECIMAL_TEXT = 32  # bounded lexical size: a longer decimal is an unsupported precision, refused, never rounded
_HUNDRED = Decimal(100)


def _typed_size(value: Any) -> str:
    """OK only for a validated exact quantity of 100 shares: int 100 (exact integer comparison, never a float conversion), float
    100.0, or canonical bounded decimal text compared EXACTLY as a Decimal ("100", "100.0", "100.00" are 100;
    "100.000000000000000001" is not). NONSTANDARD only for another positive exact quantity in a supported representation (never
    truncated or rounded: 100.5 is not 100). UNKNOWN for a missing, empty, non-canonical ("0100", "1e2", padded, signed), over-long
    (unsupported precision), malformed or non-numeric size: an unsupported encoding is unconfirmed, never a proven share count."""
    if value is None or isinstance(value, bool):
        return "UNKNOWN"
    if isinstance(value, int):
        return "OK" if value == 100 else ("NONSTANDARD" if value > 0 else "UNKNOWN")
    if isinstance(value, float):
        if not math.isfinite(value) or value <= 0:
            return "UNKNOWN"
        return "OK" if value == 100.0 else "NONSTANDARD"
    if isinstance(value, str) and len(value) <= _MAX_DECIMAL_TEXT and _CANONICAL_DECIMAL.fullmatch(value):
        number = Decimal(value)
        if number <= 0:
            return "UNKNOWN"
        return "OK" if number == _HUNDRED else "NONSTANDARD"
    return "UNKNOWN"


_CALL_MONTH_LETTERS = "ABCDEFGHIJKL"  # the source's call series letter: January .. December (puts use M..X)
_SUPPORTED_WEEKLY_TAG = "Y"  # the ONLY weekly series tag the retained VOLVB receipt proves; any other tag is unproven, not a free slot
_STRIKE_TEXT = r"(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,4})?"  # bounded strike text shared by call names and native symbols
_NATIVE_SYMBOL_SUFFIX = re.compile(r"([0-9])([A-L])(?:([0-9]{2})" + _SUPPORTED_WEEKLY_TAG + r")?(" + _STRIKE_TEXT + r")")


def _native_symbol_matches(symbol: str, root: str, expiry: date, strike: Decimal) -> bool:
    """The COMPLETE encoded identity of the two source forms the retained receipts prove: ROOT + year digit + call-month
    letter + strike (SIVE6J15.50, SIVE6J16) and the weekly ROOT + year digit + call-month letter + day + tag Y + strike
    (VOLVB6J02Y280). Root, year, month/type, day (weekly) and the EXACT decimal strike (no float tolerance) must ALL agree with
    the row's expiry and strike; a prefix, another contract of the same root, a put letter, any other weekly tag, an unsupported
    encoding or precision is not identity."""
    if not symbol.startswith(root):
        return False
    match = _NATIVE_SYMBOL_SUFFIX.fullmatch(symbol[len(root):])
    if not match:
        return False
    year_digit, month_letter, day, strike_text = match.groups()
    if int(year_digit) != expiry.year % 10 or month_letter != _CALL_MONTH_LETTERS[expiry.month - 1]:
        return False
    if day is not None and int(day) != expiry.day:
        return False
    return Decimal(strike_text) == strike


def _nordic_row_evidence(row: Any, root: str, today: date) -> tuple[str, dict[str, Any] | None]:
    """('IGNORE'|'MALFORMED'|'CALL', call). A call is proven only by assetClass OPTIONS and a call name whose underlying
    root, date and strike agree with the row's own expiry and strike fields and with the requested underlying; a trailing
    'C' alone (FUTC, futures, combinations, a missing or unknown class) proves nothing."""
    if not isinstance(row, dict):
        return "MALFORMED", None
    if row.get("assetClass") != "OPTIONS":
        return "IGNORE", None
    name = row.get("fullName")
    if not isinstance(name, str):
        return "MALFORMED", None
    if not name.endswith("C") or name.endswith("FUTC"):
        return "IGNORE", None
    match = _NORDIC_CALL_NAME.match(name)
    if not match or match.group(1) != root or match.group(3) not in _MONTH_NUMBER:
        return "MALFORMED", None
    raw_strike = row.get("strikePrice")  # exact decimal text (bounded) or an int; a float has already lost the source's digits
    if isinstance(raw_strike, bool) or not (isinstance(raw_strike, int) or (isinstance(raw_strike, str) and len(raw_strike) <= 16
                                                                          and _CANONICAL_DECIMAL.fullmatch(raw_strike))):
        return "MALFORMED", None
    try:
        name_date = date(2000 + int(match.group(4)), _MONTH_NUMBER[match.group(3)], int(match.group(2)))
        expiry_text = row.get("expirationDate")
        if not isinstance(expiry_text, str) or len(expiry_text) != 10:
            return "MALFORMED", None
        expiry = date.fromisoformat(expiry_text)
    except ValueError:
        return "MALFORMED", None
    strike_exact = Decimal(raw_strike)
    if expiry != name_date or strike_exact <= 0 or strike_exact != Decimal(match.group(5)):
        return "MALFORMED", None
    native_symbol = row.get("symbol")
    if not isinstance(native_symbol, str) or not _native_symbol_matches(native_symbol, root, expiry, strike_exact):
        return "MALFORMED", None  # a missing, unsupported or contradictory native identity proves nothing
    strike = float(strike_exact)
    return "CALL", {"expiry": expiry_text, "dte": (expiry - today).days, "strike": strike,
                    "ccy": _typed_currency(row.get("currency")), "size": _typed_size(row.get("contractSize")),
                    "bid": _float(row.get("bidPrice")), "ask": _float(row.get("askPrice")),
                    "oi": _int(row.get("openInterest")), "volume": _int(row.get("volume"))}


def _nordic_unavailable(symbol: str, status: str, message: str) -> CyclesResult:
    health = [{"venue": "STOCKHOLM", "underlying": symbol, "expiry": None, "cycle": c, "status": status, "read": False,
               "two_sided": False} for c in CYCLES]
    return CyclesResult({cycle: {"unavailable": _diag(message)} for cycle in CYCLES}, health=health)


def nordic_options(symbol: str, base: str, spot: float, today: date, stamp: str, orderbook: str | None = None,
                   *, spot_currency: Any = None) -> CyclesResult:
    """Stockholm covered calls. Every claim rests on typed source evidence: the underlying's quote currency (spot_currency,
    and the search result's share currency when the search ran) and each CONTRACT's own currency and size must all be the
    canonical SEK / 100 before a strategy is offered; an unknown or conflicting term is a source-scoped unavailable reason,
    never a SEK recommendation that merely ends in .ST."""
    native = base.replace("-", " ")  # VOLV-B is listed as "VOLV B"
    root = re.sub(r"[^A-Z0-9]", "", base.upper())
    share_currency: Any = _NO_SEARCH
    try:
        if not orderbook:
            groups = http_json(NORDIC_SEARCH.format(symbol=urllib.parse.quote(native)))["data"] or []
            share = next(item for group in groups for item in group["instruments"]
                         if item.get("assetClass") == "SHARES" and item.get("symbol", "").upper() == native.upper())
            orderbook = share["orderbookId"]
            share_currency = share.get("currency")
        rows = http_json(NORDIC_CHAIN.format(orderbook=orderbook))["data"]["instrumentListing"]["rows"]
    except Exception:
        return _nordic_unavailable(symbol, "READ_ERROR", "Nasdaq Nordic 期權鏈讀取或解析失敗")
    if not isinstance(rows, list):
        return _nordic_unavailable(symbol, "READ_ERROR", "Nasdaq Nordic 期權鏈回應格式無效（讀取或解析失敗）")
    states = [_typed_currency(spot_currency)] + ([] if share_currency is _NO_SEARCH else [_typed_currency(share_currency)])
    if "CONFLICT" in states:
        return _nordic_unavailable(symbol, "UNDERLYING_CURRENCY_CONFLICT", "標的報價或上市幣別與 SEK 不符；不推薦")
    if any(state != "OK" for state in states):
        return _nordic_unavailable(symbol, "UNDERLYING_CURRENCY_UNCONFIRMED", "標的報價或上市幣別未確認為 SEK；不推薦")
    if not rows:
        return _nordic_unavailable(symbol, "EMPTY_RESPONSE", "本次來源回應無可用之買權紀錄；是否上市未確認")
    listed: list[dict[str, Any]] = []
    malformed = 0
    for row in rows:
        kind, call = _nordic_row_evidence(row, root, today)
        if kind == "CALL":
            listed.append(call)
        elif kind == "MALFORMED":
            malformed += 1
    if not listed:
        if malformed:
            return _nordic_unavailable(symbol, "MALFORMED_ROWS", "本次來源回應之買權資料無法解析；不推斷是否上市")
        return _nordic_unavailable(symbol, "NO_EXPIRY", "本次來源回應無可用之買權紀錄；是否上市未確認")

    def no_window(cycle: str, low: int, high: int) -> tuple[str, str]:
        inside = [call for call in listed if low <= call["dte"] <= high]
        if inside:  # listed in the window, but no contract with confirmed standard terms
            parts = []
            if any(call["size"] == "NONSTANDARD" for call in inside):
                parts.append("合約單位非標準100股")
            if any(call["ccy"] == "CONFLICT" for call in inside):
                parts.append("合約幣別與 SEK 不符")
            if any(call["size"] == "UNKNOWN" or call["ccy"] == "UNKNOWN" for call in inside):
                parts.append("合約單位或幣別來源未確認")
            return f"本次回應有 {low}–{high} 天上市買權；{'、'.join(parts)}，不推薦", "TERMS_REFUSED"
        if malformed:
            return f"本次來源回應含無法解析之列；無法確認 {low}–{high} 天是否有買權", "MALFORMED_ROWS"
        upcoming = {call["expiry"]: call["dte"] for call in listed if call["dte"] >= 0}
        nearest = sorted(upcoming.items(), key=lambda item: (min(abs(item[1] - low), abs(item[1] - high)), item[1]))[:2]
        context = "、".join(f"{expiry}（{days}天）" for expiry, days in nearest)
        return f"本次回應有上市買權；所列到期不在{low}–{high}天策略範圍" + (f"（最近到期 {context}）" if context else ""), "NO_EXPIRY"

    usable = [{"expiry": call["expiry"], "dte": call["dte"], "strike": call["strike"], "bid": call["bid"], "ask": call["ask"],
               "oi": call["oi"], "volume": call["volume"], "size": 100}
              for call in listed if call["ccy"] == "OK" and call["size"] == "OK"]
    return _cycles_from_calls(usable, symbol, spot, stamp, currency=SEK, source=NORDIC_SOURCE,
                              provenance=NORDIC_CHAIN.format(orderbook=orderbook), rights="candidate_local_review",
                              missing="", venue="STOCKHOLM", underlying=symbol, no_window=no_window)


def observe(symbol: str, today: date, stamp: str, orderbook: str | None = None) -> Observation | None:
    """One underlying: the delayed quote and, for US and Stockholm listings, its covered-call cycles. Options keys never
    collide across markets: US listings by their Yahoo symbol (class shares use "-": BRK-B; dotted symbols are other
    markets such as 2330.TW), Stockholm listings with the suffix (SIVE.ST, VOLV-B.ST, AZN.ST next to the US AZN)."""
    import yfinance as yf
    try:
        info = yf.Ticker(symbol).fast_info
        price, previous = _float(info.get("lastPrice")), _float(info.get("previousClose"))
        currency = info.get("currency")
    except Exception:
        price = None
    base = symbol.split(".")[0] if symbol.endswith(".ST") else symbol
    if price:
        quote = {"symbol": symbol, "display": base, "price": price, "previous_close": previous,
                 "change_pct": (price / previous - 1) if previous else None, "currency": currency,
                 "asof": stamp, "source": "Yahoo Finance (unofficial, delayed)", "source_url": f"https://finance.yahoo.com/quote/{symbol}"}
    else:
        fallback = alpha_vantage_quote(symbol, stamp) if "." not in symbol else None  # US listings only
        if not fallback:
            return None
        quote, price = fallback, fallback["price"]
    try:
        if "." not in symbol:
            cycles = us_cycles(symbol, price, today, stamp)
            return Observation(quote, symbol, cycles)
        if symbol.endswith(".ST"):
            cycles = nordic_options(symbol, base, price, today, stamp, orderbook, spot_currency=quote.get("currency"))
            return Observation(quote, symbol, cycles)
    except Exception:  # one malformed chain never aborts the other underlyings
        venue = "STOCKHOLM" if symbol.endswith(".ST") else "US"
        err_health = [{"venue": venue, "underlying": symbol, "expiry": None, "cycle": c,
                       "status": "READ_ERROR", "read": False, "two_sided": False} for c in CYCLES]
        return Observation(quote, symbol, CyclesResult({cycle: {"unavailable": "期權鏈讀取失敗"} for cycle in CYCLES}, health=err_health))
    return Observation(quote, symbol, {})


def _observe_safely(symbol: str, today: date, stamp: str, orderbook: str | None,
                    deadline: float = math.inf) -> tuple[dict[str, Any], str, dict[str, Any]] | None:
    if time.monotonic() > deadline:
        return None
    try:
        return observe(symbol, today, stamp, orderbook)
    except Exception:
        return None


def collect(symbols: list[str], work: Callable[[str], Any], deadline: float) -> dict[str, Any]:
    """Runs work(symbol) on WORKERS daemon threads until every symbol is done or the deadline passes, then returns a
    snapshot of the finished results. A worker stuck in a request is abandoned (never joined, never blocks the exit); a
    result arriving after the deadline is discarded, so the snapshot and the unfinished count always agree."""
    pending = list(reversed(symbols))
    results: dict[str, Any] = {}
    lock = threading.Lock()

    def worker() -> None:
        _LOCAL.deadline = deadline
        while True:
            with lock:
                if not pending or time.monotonic() > deadline:
                    return
                symbol = pending.pop()
            result = work(symbol)
            with lock:
                if time.monotonic() <= deadline:
                    results[symbol] = result
    threads = [threading.Thread(target=worker, name=f"observe-{index}", daemon=True) for index in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(None if math.isinf(deadline) else max(0.0, deadline - time.monotonic()))
    with lock:
        return dict(results)


def build(now: datetime, deadline_seconds: float | None = None) -> dict[str, Any]:
    try:
        return _build(now, COLLECTION_DEADLINE_SECONDS if deadline_seconds is None else deadline_seconds)
    finally:
        _DEADLINE[0] = math.inf  # the next run (or a direct call) never inherits this run's deadline


def _build(now: datetime, deadline_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + deadline_seconds
    _DEADLINE[0] = deadline
    stamp = iso(now)
    today = now.date()
    # Universe discovery on its own daemon thread within the first share of the budget; an overrun uses the cached list.
    found = collect(["universe"], lambda _: broad_universe(now), started + deadline_seconds * DISCOVERY_SHARE)
    broad = found.get("universe") or cached_universe(now)
    orderbooks: dict[str, str] = dict(broad.get("sweden") or {})
    symbols = list(dict.fromkeys(universe() + list(broad.get("us") or []) + list(orderbooks)))
    finished = collect(symbols, lambda symbol: _observe_safely(symbol, today, stamp, orderbooks.get(symbol), deadline), deadline)
    results = [finished.get(symbol) for symbol in symbols]
    unfinished = len(symbols) - len(finished)
    quotes: dict[str, Any] = {}
    options: dict[str, Any] = {}
    all_health: list[dict[str, Any]] = []
    for symbol, result in zip(symbols, results):
        if result is None:
            continue
        quote, key, cycles = result[0], result[1], result[2]
        quotes[symbol] = quote
        if cycles:
            options[key] = cycles
        item_health = getattr(result, "health", None)
        if item_health is None:
            item_health = getattr(cycles, "health", None)
        if item_health is None and len(result) >= 4:
            item_health = result[3]
        if item_health:
            all_health.extend(item_health)

    deduped_chains: dict[tuple[str, str, str], bool] = {}
    chain_health = {
        "US": {"read": 0, "healthy": 0, "expiry_list_error": 0, "empty_response": 0, "no_expiry": 0, "read_error": 0, "empty": 0},
        "STOCKHOLM": {"read": 0, "healthy": 0, "expiry_list_error": 0, "empty_response": 0, "no_expiry": 0, "read_error": 0, "empty": 0},
    }
    for item in all_health:
        venue = item.get("venue")
        if venue not in chain_health:
            continue
        status = item.get("status")
        if status == "EXPIRY_LIST_ERROR":
            chain_health[venue]["expiry_list_error"] += 1
        elif status == "EMPTY_RESPONSE":
            chain_health[venue]["empty_response"] += 1
        elif status == "NO_EXPIRY":
            chain_health[venue]["no_expiry"] += 1
        elif status == "READ_ERROR":
            chain_health[venue]["read_error"] += 1
        elif status == "EMPTY":
            chain_health[venue]["empty"] += 1
        if item.get("read") and item.get("expiry"):
            k = (venue, item["underlying"], item["expiry"])
            deduped_chains[k] = deduped_chains.get(k, False) or bool(item.get("two_sided"))

    for (venue, _, _), two_sided in deduped_chains.items():
        chain_health[venue]["read"] += 1
        if two_sided:
            chain_health[venue]["healthy"] += 1

    return {"schema": "v213-market-observations-v2", "generated_at": stamp, "quotes": quotes, "options": options,
            "note": "Delayed public observations; not an order, not a recommendation to trade.",
            "collection": {"underlyings": len(symbols), "unfinished": unfinished, "deadline_seconds": deadline_seconds,
                           "chain_health": chain_health}}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    output_path = Path(args.output)
    now = utc_now()
    if args.if_older_than_hours > 0 and output_path.exists():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8"))
            age = (now - datetime.strptime(previous["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
            if age < args.if_older_than_hours:
                print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age, 1)}))
                return 0
        except (OSError, ValueError, KeyError):
            pass
    try:
        document = build(now)
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error": type(error).__name__}))
        return 1
    collection = document["collection"]
    if collection["underlyings"] and collection["unfinished"] > collection["underlyings"] * (1 - MIN_COMPLETED_SHARE):
        print(json.dumps({"status": "FAILED", "error": "DEADLINE_INCOMPLETE", **collection}))
        return 1
    if len(document["quotes"]) < 10:
        print(json.dumps({"status": "FAILED", "error": "TOO_FEW_QUOTES", "quotes": len(document["quotes"])}))
        return 1
    chain_health = collection.get("chain_health") or {}
    venues_data = {}
    affected_venues = []
    for venue in ("US", "STOCKHOLM"):
        v_data = chain_health.get(venue) or {}
        r = v_data.get("read", 0)
        h = v_data.get("healthy", 0)
        venues_data[venue] = {"read": r, "healthy": h}
        if is_venue_coverage_depleted(r, h):
            affected_venues.append(venue)
    if affected_venues:
        available = sum(1 for cycles in document["options"].values() for value in cycles.values() if "unavailable" not in value)
        print(json.dumps({
            "status": "FAILED",
            "error": "OPTION_TWO_SIDED_COVERAGE_LOW",
            "venues": venues_data,
            "affected_venues": affected_venues,
            "quotes": len(document["quotes"]),
            "available_cycles": available,
            "previous_file_present": output_path.exists(),
        }, ensure_ascii=False))
        return 1
    temp = output_path.with_name(output_path.name + ".tmp")
    temp.write_bytes(json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    temp.replace(output_path)
    available = sum(1 for cycles in document["options"].values() for value in cycles.values() if "unavailable" not in value)
    print(json.dumps({"status": "OK", **collection, "quotes": len(document["quotes"]), "option_underlyings": len(document["options"]),
                      "option_observations": available, "sive": document["options"].get("SIVE.ST")}, ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
