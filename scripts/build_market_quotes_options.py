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
Per underlying and cycle (weekly = the CURRENT calendar week's expiry, monthly = the NEAREST standard monthly expiry, no minimum DTE):
up to three covered-call sell suggestions for a holder of 100 shares (operator 2026-09-26: collect premium, keep the strike as high as possible so the
shares are not called away; operator 2026-10-11: a middle tier and the current-week weekly):
- HIGH_STRIKE: the highest out-of-the-money strike with a valid two-sided quote and delta <= MAX_HIGH_STRIKE_DELTA; there is no
  annualized-yield floor (operator 2026-11-03), so a strike paying less than 2% a year is still listed and its annualized yield is
  shown; strikes with a spread wider than the mid, or without a delta, are ignored;
- BALANCED: a lower strike nearest delta BALANCED_DELTA (or BALANCED_MONEYNESS without a delta) for more premium;
- MIDDLE (optional cycle key middle_suggestion): a strike strictly between the two, nearest MIDDLE_DELTA (or
  MIDDLE_MONEYNESS); absent when no listed strike lies between. Defined in option_recommendation_rules.py.
Weekly (operator 2026-10-11): the earliest listed expiry from the exchange-local as-of date through that calendar week's
Sunday; only when none remains (weekend, after the week's last weekly, or after the expiry-day close) the earliest expiry of
the next calendar week; never a later one. The as-of date is the exchange-local date (US: New York, Stockholm: Stockholm),
recorded in each cycle as asof_date together with weekly_week (CURRENT or NEXT). Tiny DTE (0-2) annualizes over at least one
day. The rules live in option_recommendation_rules.py (twin: cloud/src/v213/option-recommendation-rules.ts).
Monthly (operator 2026-11-03): the nearest standard monthly expiry on or after the exchange-local as-of date, whatever its DTE: the
listed expiry on the month's third Friday, else (holiday) the latest listed expiry of that Monday-Thursday before it; on the expiry day
itself only before the session close, afterwards (or when the month's monthly is not listed) the earliest later standard monthly within
60 DTE. The branch that applied is recorded in the cycle as the additive monthly_rule (THIRD_FRIDAY, HOLIDAY_SHIFT or LATER_LISTED).
Each carries a sell limit (mid rounded down to the tick, or bid + a quarter of the spread when the spread exceeds 25% of
the mid; never below the bid), premium per contract, period and
annualized yield on the current price, the upside kept up to the strike, delta as the assignment reference, OI, volume
and spread. Delta is Black-Scholes from the quoted implied volatility (a labelled model Greek); a chain without one
(Nasdaq Stockholm, the Nasdaq US fallback) takes the volatility implied by the strike's own bid/ask mid instead
(delta_basis QUOTE_IMPLIED), so every high strike carries the same assignment cap. Prices are never modelled. A cycle
without two-sided quotes stays unavailable with its reason.
V21 (operator 2026-10-19; the annualized-yield floor it set at 2% was removed on 2026-11-03): the same cycle row carries the optional additive
object `strategies` from the same chain's put side (Yahoo option_chain().puts, Nasdaq US p_* fields, Nasdaq Nordic put rows; the same
provider, label and quote_basis): csp (cash-secured put: |delta| in rules.CONSERVATIVE_DELTA_BAND, nearest 0.20 first) and collar (long stock,
protective put |delta| nearest rules.PROTECTIVE_PUT_DELTA, the short call in the same band), each a block with rights_status, provider_id,
quote_basis and timestamp, or {"unavailable": reason} when a leg lacks a valid two-sided quote or a delta. A cycle with no covered call but a
real csp or collar block keeps suggestions == [] and strategies.cc = {"unavailable": reason}. Health stays call-based.

Public admission (operator 2026-10-13): the Yahoo option-chain cycles claim the catalog identity YAHOO_OPTION_IDENTITY (provider_id,
jurisdiction, venue, instrument_kind, publication_scope; quote_basis is the cycle's own). Only the audited catalog admits it
(config/public-options-provider-candidates.json, scripts/public_options_provider_gate.py); the Nasdaq US fallback (operator
2026-10-19, same terms) claims NASDAQ_US_OPTION_IDENTITY with the rights label operator_accepted_unlicensed, its own quote_basis "delayed",
and is shown only when the chain's "AS OF" date is within NASDAQ_US_MAX_ASOF_AGE_DAYS of the run date; it is used only for cycles Yahoo
could not read and is never carried forward. Outside the regular US session Yahoo returns zero bid and ask: a chain READ without any valid two-sided
quote then takes the last valid in-session cycle of the same ticker, period and expiry (quote_basis previous_session_last, the capture's
own timestamp, spot and dte) from the carry-forward state (scripts/options_carry_forward.py; --carry-state or V213_OPTIONS_CARRY_STATE,
by default next to --output). A live valid cycle always wins.
Nasdaq Nordic (Stockholm, operator 2026-10-17, same terms): the cycles claim NORDIC_OPTION_IDENTITY with their own quote_basis "delayed"
and the rights label operator_accepted_unlicensed; they are never carried forward.

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

import option_recommendation_rules as rules
import options_carry_forward as carry_forward

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
_CARRY: list[Any] = [None]  # the run's previous-session carry-forward state (options_carry_forward.CarryForward), set by main
# A run that finished fewer underlyings than this is not published: the previous file stays (the sealer bounds its age).
MIN_COMPLETED_SHARE = 0.5
# weekly: the current-week rule of option_recommendation_rules (the window is only the fetch/validator outer bound, 0-14 DTE);
# monthly: the nearest standard monthly of option_recommendation_rules (the window is only the fetch/validator outer bound, 0-60 DTE)
CYCLES = {"weekly": rules.WEEKLY_DTE_BUCKET, "monthly": rules.MONTHLY_DTE_BUCKET}
RISK_FREE = 0.04
MAX_HIGH_STRIKE_DELTA = 0.20  # the high-strike suggestion keeps the model assignment reference low
MONTHLY_ANNUAL_HURDLE = 0.06
MONTHLY_MIN_DTE = 7
MONTHLY_EXPIRIES_TO_CHECK = 2
BALANCED_DELTA = 0.30
BALANCED_MONEYNESS = 1.05     # when a lower strike has no delta at all, about 5% out of the money
MIDDLE_DELTA = rules.MIDDLE_DELTA          # the middle tier sits between HIGH_STRIKE (<= 0.20) and BALANCED (0.30)
MIDDLE_MONEYNESS = rules.MIDDLE_MONEYNESS  # when the candidates between have no delta
TICK = 0.01
MAX_SPREAD_PCT = 1.0          # a spread wider than the mid is not a tradeable quote
WIDE_SPREAD_PCT = 0.25        # beyond this the limit moves from the mid towards the bid
# The identity a Yahoo US option-chain cycle CLAIMS for public admission (never authority: only the audited catalog admits it; a test pins
# this equal to the catalog's admitted scope). The rights label is the honest one for a provider shown on the operator's decision.
YAHOO_OPTION_IDENTITY = {"provider_id": "yahoo_finance_option_chain", "jurisdiction": "US", "venue": "US_LISTED_OPTIONS",
                         "instrument_kind": "equity_option", "publication_scope": "public_line_quote"}
YAHOO_RIGHTS_LABEL = "operator_accepted_unlicensed"
# The identity a Nasdaq Nordic (Stockholm) option-chain cycle CLAIMS (operator 2026-10-17, same terms as Yahoo; never authority, a test pins
# this equal to the catalog's admitted scope). The cycle keeps its own quote_basis "delayed": Nordic cycles are never carried forward.
NORDIC_OPTION_IDENTITY = {"provider_id": "nasdaq_nordic_option_chain", "jurisdiction": "SE", "venue": "NASDAQ_STOCKHOLM_OPTIONS",
                          "instrument_kind": "equity_option", "publication_scope": "public_line_quote"}
NORDIC_RIGHTS_LABEL = "operator_accepted_unlicensed"
# The identity a Nasdaq US option-chain cycle (the Yahoo fallback) CLAIMS (operator 2026-10-19, same terms as Yahoo and Nordic; never authority,
# a test pins this equal to the catalog's admitted scope). The cycle keeps its own quote_basis "delayed": Nasdaq US cycles are never carried forward.
NASDAQ_US_OPTION_IDENTITY = {"provider_id": "nasdaq_public_option_chain", "jurisdiction": "US", "venue": "US_LISTED_OPTIONS",
                             "instrument_kind": "equity_option", "publication_scope": "public_line_quote"}
NASDAQ_US_RIGHTS_LABEL = "operator_accepted_unlicensed"
# The chain carries no per-quote time (table.asOf is null); data.lastTrade says "(AS OF OCT 15, 2026)". A cycle whose as-of date is absent,
# unparsable, future-dated or older than this many calendar days (weekend plus a holiday) against the run date is not shown.
NASDAQ_US_MAX_ASOF_AGE_DAYS = 4
NASDAQ_US_STALE_TEXT = "Nasdaq 報價日期過舊或無法確認"
# A month is a whole English month name or abbreviation and a year exactly four digits that end the date (then ")", whitespace or the end
# of the text): "OCTOPUS", "20260", "2026JUNK" or "2026-10" is unparsable, never Oct or 2026.
_ASOF_RE = re.compile(r"\bAS OF\s+([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})(?=[\s)]|$)", re.IGNORECASE)
_ASOF_MONTHS = {name: number for number, names in enumerate((
    ("JAN", "JANUARY"), ("FEB", "FEBRUARY"), ("MAR", "MARCH"), ("APR", "APRIL"), ("MAY",), ("JUN", "JUNE"), ("JUL", "JULY"),
    ("AUG", "AUGUST"), ("SEP", "SEPT", "SEPTEMBER"), ("OCT", "OCTOBER"), ("NOV", "NOVEMBER"), ("DEC", "DECEMBER")), start=1) for name in names}
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


def bs_put_price(spot: float, strike: float, years: float, vol: float) -> float:
    d1 = (math.log(spot / strike) + (RISK_FREE + vol * vol / 2) * years) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    return strike * math.exp(-RISK_FREE * years) * cdf(-d2) - spot * cdf(-d1)


def implied_vol_put(price: float, spot: float, strike: float, years: float) -> float | None:
    """The Black-Scholes volatility that reproduces a quoted put price (bisection between 1% and 500%); None outside that range."""
    low, high = 0.01, 5.0
    if price <= 0 or years <= 0 or spot <= 0 or strike <= 0 or not bs_put_price(spot, strike, years, low) < price < bs_put_price(spot, strike, years, high):
        return None
    for _ in range(60):
        mid = (low + high) / 2
        if bs_put_price(spot, strike, years, mid) < price:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def with_put_delta(row: dict[str, Any], spot: float, dte: int) -> dict[str, Any]:
    """The put row with its ABSOLUTE delta (|put delta| = 1 - call delta): Black-Scholes from the quoted implied volatility, else from the
    volatility implied by its own bid/ask mid (QUOTE_IMPLIED). delta_exact keeps full precision for the band check. No delta, no
    delta_basis: the row is then not eligible for any put strategy."""
    years = rules.effective_days(dte) / 365
    if row.get("iv"):
        call = bs_call_delta(spot, row["strike"], years, row["iv"], digits=None)
        if call is not None:
            exact = 1 - call
            return {**row, "delta": round(exact, 3), "delta_exact": exact, "delta_basis": "QUOTED_IV"}
    vol = implied_vol_put((row["bid"] + row["ask"]) / 2, spot, row["strike"], years)
    if vol is None:
        return {**row, "delta": None, "delta_exact": None, "delta_basis": None}
    exact = 1 - bs_call_delta(spot, row["strike"], years, vol, digits=None)
    return {**row, "iv": round(vol, 4), "delta": round(exact, 3), "delta_exact": exact, "delta_basis": "QUOTE_IMPLIED"}


def with_delta(row: dict[str, Any], spot: float, dte: int) -> dict[str, Any]:
    """The row with its assignment reference: the quoted delta, else Black-Scholes from the quoted implied volatility,
    else from the volatility implied by its own bid/ask mid (labelled QUOTE_IMPLIED). delta_exact keeps full precision
    for the limit check (a rounded 0.200 must not admit 0.2003); delta and iv are rounded for display."""
    years = rules.effective_days(dte) / 365  # a same-day expiry is modelled over one day, never zero
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
    days = rules.effective_days(dte)  # annualization never uses fewer than one day (DTE 0 is the expiry day)
    bid, ask = row["bid"], row["ask"]
    mid = round((bid + ask) / 2, 4)
    spread_pct = (ask - bid) / mid if mid > 0 else 0.0
    target = mid if spread_pct <= WIDE_SPREAD_PCT else bid + (ask - bid) / 4
    limit = round(max(bid, math.floor(target / TICK + 1e-9) * TICK), 2)
    period_yield = limit / spot
    return {"role": role, "strike": row["strike"], "bid": bid, "ask": ask, "mid": mid, "limit_price": limit,
            "premium_per_contract": round(limit * 100, 2), "period_yield": round(period_yield, 6),
            "annualized_yield": round(period_yield * 365 / days, 6), "upside_to_strike": round(row["strike"] / spot - 1, 6),
            "delta": row.get("delta"), "delta_basis": row.get("delta_basis"), "iv": row.get("iv") or None, "oi": row.get("oi"), "volume": row.get("volume"),
            "spread_pct": round((ask - bid) / mid, 4) if mid > 0 else None}


def covered_call_tiers(rows: list[dict[str, Any]], spot: float, dte: int, *,
                       cent_exact_only: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """(suggestions, middle): the highest usable strike (HIGH_STRIKE; no yield floor), a balanced strike below it (BALANCED), and
    the optional MIDDLE strike strictly between the two (never padded, never a duplicate strike). Only out-of-the-money
    strikes with a two-sided quote qualify, and the high strike needs a delta (quoted or implied by its quote) within
    MAX_HIGH_STRIKE_DELTA. Only a strike the two-decimal display represents exactly is recommended (cent_exact_only); health
    is computed before and never depends on this fence. DTE 0 (the expiry day) annualizes over one day."""
    if dte < 0:
        return [], None
    days = rules.effective_days(dte)
    usable = [with_delta(row, spot, dte) for row in rows if row.get("strike") and row["strike"] > spot and row.get("bid")
              and row.get("ask") and row["ask"] >= row["bid"] > 0
              and (row["ask"] - row["bid"]) / ((row["ask"] + row["bid"]) / 2) <= MAX_SPREAD_PCT
              and (not cent_exact_only or _cent_exact(row["strike"]))]
    if not usable:
        return [], None
    annual = lambda row: row["bid"] / spot * 365 / days  # noqa: E731 - on the bid: premium that is actually collectable
    high = [row for row in usable if row.get("delta_exact") is not None and row["delta_exact"] <= MAX_HIGH_STRIKE_DELTA]
    if not high:
        return [], None
    first = max(high, key=lambda row: row["strike"])
    suggestions = [_suggestion("HIGH_STRIKE", first, spot, dte)]
    lower = [row for row in usable if row["strike"] < first["strike"] and annual(row) > annual(first)]
    middle: dict[str, Any] | None = None
    if lower:
        if all(row.get("delta") is not None for row in lower):
            second = min(lower, key=lambda row: abs(row["delta"] - BALANCED_DELTA))
        else:
            second = min(lower, key=lambda row: abs(row["strike"] / spot - BALANCED_MONEYNESS))
        suggestions.append(_suggestion("BALANCED", second, spot, dte))
        between = rules.pick_middle(lower, first["strike"], second["strike"], spot)
        if between is not None:
            middle = _suggestion("MIDDLE", between, spot, dte)
    return suggestions, middle


def covered_call_suggestions(rows: list[dict[str, Any]], spot: float, dte: int, *, cent_exact_only: bool = True) -> list[dict[str, Any]]:
    """The HIGH_STRIKE and BALANCED suggestions of covered_call_tiers (the contract of `suggestions`: one or two entries)."""
    return covered_call_tiers(rows, spot, dte, cent_exact_only=cent_exact_only)[0]


# ---- V21 (operator 2026-10-19): cash-secured put and collar beside the covered call, conservative first ----------------------------------

def _quote_usable(row: dict[str, Any]) -> bool:
    """A two-sided quote whose spread is at most the mid (the covered-call rule): the only quote a strategy leg may stand on."""
    bid, ask = row.get("bid"), row.get("ask")
    return (_is_two_sided(bid, ask) and (ask - bid) / ((ask + bid) / 2) <= MAX_SPREAD_PCT)


def _sell_limit(bid: float, ask: float) -> float:
    """The sell limit of a covered call: the mid rounded DOWN to the tick (the bid plus a quarter of a wide spread), never below the bid."""
    mid = round((bid + ask) / 2, 4)
    target = mid if (ask - bid) / mid <= WIDE_SPREAD_PCT else bid + (ask - bid) / 4
    return round(max(bid, math.floor(target / TICK + 1e-9) * TICK), 2)


def _buy_limit(bid: float, ask: float) -> float:
    """The buy limit of a protective put: the mid rounded UP to the tick (the ask minus a quarter of a wide spread), never above the ask."""
    mid = round((bid + ask) / 2, 4)
    target = mid if (ask - bid) / mid <= WIDE_SPREAD_PCT else ask - (ask - bid) / 4
    return round(min(ask, math.ceil(target / TICK - 1e-9) * TICK), 4)


def _leg(row: dict[str, Any], limit: float) -> dict[str, Any]:
    """One quoted leg, kept small (the options object has a hard size cap): strike, bid, ask, limit and the absolute delta with its basis.
    The mid, spread and liquidity are not repeated; a reader derives the mid from bid and ask."""
    return {"strike": row["strike"], "bid": row["bid"], "ask": row["ask"], "limit_price": limit, "delta": row.get("delta"),
            "delta_basis": row.get("delta_basis")}


def _nearest(rows: list[dict[str, Any]], target: float) -> dict[str, Any]:
    return min(rows, key=lambda row: (abs(row["delta_exact"] - target), row["strike"]))


def _in_band(row: dict[str, Any], band: tuple[float, float]) -> bool:
    return row.get("delta_exact") is not None and band[0] - 1e-12 <= row["delta_exact"] <= band[1] + 1e-12


def _otm_puts(puts: list[dict[str, Any]], spot: float, dte: int, cent_exact_only: bool) -> list[dict[str, Any]]:
    rows = [with_put_delta(row, spot, dte) for row in puts if _is_finite_positive(row.get("strike")) and row["strike"] < spot and _quote_usable(row)
            and (not cent_exact_only or _cent_exact(row["strike"]))]
    return [row for row in rows if row.get("delta_exact") is not None]


def _otm_calls(rows: list[dict[str, Any]], spot: float, dte: int, cent_exact_only: bool) -> list[dict[str, Any]]:
    usable = [with_delta(row, spot, dte) for row in rows if _is_finite_positive(row.get("strike")) and row["strike"] > spot and _quote_usable(row)
              and (not cent_exact_only or _cent_exact(row["strike"]))]
    return [row for row in usable if row.get("delta_exact") is not None]


def cash_secured_put_tiers(puts: list[dict[str, Any]], spot: float, dte: int, *,
                           cent_exact_only: bool = True) -> tuple[list[dict[str, Any]], str | None]:
    """(items, reason): out-of-the-money puts with a two-sided quote and an absolute delta inside CONSERVATIVE_DELTA_BAND (there is
    no yield floor); CONSERVATIVE = the delta nearest the band's lower edge, optional BALANCED =
    the delta nearest its upper edge among the higher strikes. Nothing is modelled: with no such strike the reason says which step failed."""
    if dte < 0 or not puts:
        return [], "本次回應無該到期的賣權報價"
    days = rules.effective_days(dte)
    if not any(_quote_usable(row) for row in puts):
        return [], "所選到期賣權無有效雙邊報價（買賣價須為正且不倒掛）"
    usable = _otm_puts(puts, spot, dte, cent_exact_only)
    band = [row for row in usable if _in_band(row, rules.CONSERVATIVE_DELTA_BAND)]
    if not band:
        low, high = rules.CONSERVATIVE_DELTA_BAND
        return [], f"沒有 delta 絕對值介於 {low:.2f}–{high:.2f} 且有雙邊報價的價外賣權"
    first = _nearest(band, rules.CONSERVATIVE_DELTA_BAND[0])
    chosen = [("CONSERVATIVE", first)]
    higher = [row for row in band if row["strike"] > first["strike"]]
    if higher:
        chosen.append(("BALANCED", _nearest(higher, rules.CONSERVATIVE_DELTA_BAND[1])))
    items = []
    for role, row in chosen:
        limit = _sell_limit(row["bid"], row["ask"])
        items.append({"role": role, **_leg(row, limit), "premium_per_contract": round(limit * 100, 2),
                      "cash_required": round(row["strike"] * 100, 2), "annualized_yield": round(limit / row["strike"] * 365 / days, 6),
                      "breakeven": round(row["strike"] - limit, 4), "downside_buffer": round(1 - row["strike"] / spot, 6)})
    return items, None


def collar_tiers(calls: list[dict[str, Any]], puts: list[dict[str, Any]], spot: float, dte: int, *,
                 cent_exact_only: bool = True) -> tuple[dict[str, Any] | None, str | None]:
    """({put, items}, reason): long stock + a protective put (absolute delta nearest PROTECTIVE_PUT_DELTA inside its window; buy limit = mid
    rounded up, never above the ask) + the short call in CONSERVATIVE_DELTA_BAND (the delta nearest the lower edge first, optional
    BALANCED nearest the upper edge). Every leg needs its own two-sided quote and a delta; there is no yield floor on a collar."""
    if dte < 0 or not puts:
        return None, "本次回應無該到期的賣權報價"
    if not any(_quote_usable(row) for row in puts):
        return None, "所選到期賣權無有效雙邊報價（買賣價須為正且不倒掛）"
    window = rules.PROTECTIVE_PUT_DELTA_BAND
    protective = [row for row in _otm_puts(puts, spot, dte, cent_exact_only) if _in_band(row, window)]
    if not protective:
        return None, f"沒有 delta 絕對值約 {rules.PROTECTIVE_PUT_DELTA:.2f}（{window[0]:.2f}–{window[1]:.2f}）且有雙邊報價的價外賣權"
    band = [row for row in _otm_calls(calls, spot, dte, cent_exact_only) if _in_band(row, rules.CONSERVATIVE_DELTA_BAND)]
    if not band:
        low, high = rules.CONSERVATIVE_DELTA_BAND
        return None, f"沒有 delta 介於 {low:.2f}–{high:.2f} 且有雙邊報價的價外買權"
    put_row = _nearest(protective, rules.PROTECTIVE_PUT_DELTA)
    put_leg = _leg(put_row, _buy_limit(put_row["bid"], put_row["ask"]))
    first = _nearest(band, rules.CONSERVATIVE_DELTA_BAND[0])
    chosen = [("CONSERVATIVE", first)]
    lower = [row for row in band if row["strike"] < first["strike"]]
    if lower:
        chosen.append(("BALANCED", _nearest(lower, rules.CONSERVATIVE_DELTA_BAND[1])))
    items = []
    for role, row in chosen:
        call_leg = _leg(row, _sell_limit(row["bid"], row["ask"]))
        net = round(call_leg["limit_price"] - put_leg["limit_price"], 4)
        loss = round(spot - put_leg["strike"] - net, 4)
        gain = round(call_leg["strike"] - spot + net, 4)
        items.append({"role": role, "call": call_leg, "net_premium_per_share": net, "max_loss_per_share": loss, "max_gain_per_share": gain,
                      "break_even": round(spot - net, 4), "worst_case_net_per_share": round(call_leg["bid"] - put_leg["ask"], 4)})
    return {"put": put_leg, "items": items}, None


def strategy_blocks(calls: list[dict[str, Any]], puts: list[dict[str, Any]], spot: float, dte: int, label: dict[str, Any]) -> dict[str, Any]:
    """The additive `strategies` blocks beyond the covered call: csp and collar, each {suggestions|items, label} or {unavailable}."""
    csp, csp_reason = cash_secured_put_tiers(puts, spot, dte)
    collar, collar_reason = collar_tiers(calls, puts, spot, dte)
    return {"csp": {"suggestions": csp, **label} if csp else {"unavailable": _diag(csp_reason or "")},
            "collar": {**collar, **label} if collar else {"unavailable": _diag(collar_reason or "")}}


def _covered_call_unavailable(rows: list[dict[str, Any]], spot: float, dte: int, expiry: str) -> str:
    """Explain a refused call using its actual quote and strategy evidence."""
    if not any(_is_two_sided(row.get("bid"), row.get("ask")) for row in rows):
        return _diag(f"本次回應有 {expiry}（{dte}天）買權，但{carry_forward.NO_TWO_SIDED_REASON}（買賣價須為正且不倒掛）")
    if covered_call_suggestions(rows, spot, dte, cent_exact_only=False):
        return _diag(f"本次回應有 {expiry}（{dte}天）有效雙邊報價，但符合條件之履約價含兩位以上小數，顯示無法如實呈現；不提供建議")
    return f"{expiry} 到期的價外買權中，沒有 Delta 不超過 {MAX_HIGH_STRIKE_DELTA:.2f} 且有雙邊報價的履約價"


def cycle_result(ticker: str, expiry: str, dte: int, spot: float, rows: list[dict[str, Any]], *, currency: str, source: str,
                 provenance: str, rights: str, stamp: str, asof: str | None = None, week: str | None = None,
                 identity: dict[str, str] | None = None, puts: list[dict[str, Any]] | None = None,
                 monthly_rule: str | None = None) -> dict[str, Any]:
    """puts (V21): the same expiry's put rows when the source answered a put side (None: the response carried none, so no `strategies`)."""
    suggestions, middle = covered_call_tiers(rows, spot, dte)
    strategies: dict[str, Any] | None = None
    if puts is not None and identity is not None:
        label = {"rights_status": rights, "provider_id": identity["provider_id"], "quote_basis": "delayed", "timestamp": stamp}
        strategies = strategy_blocks(rows, puts, spot, dte, label)
    cc_reason = ""
    if not suggestions:
        cc_reason = _covered_call_unavailable(rows, spot, dte, expiry)
        if strategies is None or all("unavailable" in block for block in strategies.values()):
            return {"unavailable": cc_reason}
    result = {"ticker": ticker, "strategy": "COVERED_CALL", "expiry": expiry, "dte": dte, "spot": spot, "currency": currency,
              "multiplier": 100, "quote_basis": "delayed", "timestamp": stamp, "source": source, "provenance": provenance,
              "rights_status": rights, "suggestions": suggestions}
    if strategies is not None:  # additive and optional: an older reader ignores it; a cycle without a covered call keeps suggestions == []
        result["strategies"] = {"cc": {"unavailable": cc_reason}, **strategies} if not suggestions else strategies
    if identity is not None:  # the CLAIMED catalog join identity (additive; an older reader ignores it and its catalog does not admit it)
        result.update(identity)
    if middle is not None:  # additive and optional: older readers ignore it and still render the two original tiers
        result["middle_suggestion"] = middle
    if asof is not None:  # the exchange-local as-of date the expiry rule was applied on (YYYY-MM-DD)
        result["asof_date"] = asof
    if week is not None:  # weekly only: CURRENT (this calendar week) or NEXT (this week has no remaining weekly)
        result["weekly_week"] = week
    if monthly_rule is not None:  # monthly only: which branch of the standard-monthly rule chose the expiry (additive; old readers ignore it)
        result["monthly_rule"] = monthly_rule
    return result


def _missing_text(template: str, cycle: str, low: int, high: int) -> str:
    """A 'no listed expiry' reason: the weekly cycle is the calendar week (this one, else next) and the monthly cycle the standard
    monthly (third Friday), not a DTE range."""
    text = template.format(low=low, high=high)
    if cycle == "weekly":
        return text.replace(f" {low}-{high} 天", "本週或下週")
    return text.replace(f" {low}-{high} 天", "標準月選") if cycle == "monthly" else text


def _weekly_choice(expiries: Iterable[str], today: date | None, stamp: str, venue: str) -> "rules.WeeklyChoice | None":
    """The weekly rule on listed expiry dates: today is the exchange-local as-of date; the expiry day counts only before the
    venue's session close at the stamp's instant."""
    if today is None:
        return None
    days: set[date] = set()
    for text in expiries:
        try:
            days.add(date.fromisoformat(str(text)))
        except ValueError:
            continue
    return rules.select_weekly_expiry(days, today, expiry_day_open_now=rules.expiry_day_open(rules.parse_utc_instant(stamp), venue))


def _monthly_choice(expiries: Iterable[str], today: date | None, stamp: str, venue: str) -> "rules.MonthlyChoice | None":
    """Source-listed standard third-Friday/venue shift at >=7 DTE; missing
    listings trigger bounded source-specific lookup and dated nonstandard display."""
    if today is None:
        return None
    days: set[date] = set()
    for text in expiries:
        try:
            days.add(date.fromisoformat(str(text)))
        except ValueError:
            continue
    return rules.select_monthly(days, today, expiry_day_open_now=rules.expiry_day_open(rules.parse_utc_instant(stamp), venue))


def _is_actual_date(text: str) -> bool:
    try:
        return date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def _calendar_standard_monthlies(today: date) -> list[tuple[str, int]]:
    """Bounded targeted fetch candidates; a calendar date is NOT proof a contract is listed.
    Only a typed contract row from the provider can authorize displaying quote fields."""
    choices = []
    for offset in range(4):
        year, month_zero = divmod(today.year * 12 + today.month - 1 + offset, 12)
        third = rules.third_friday(year, month_zero + 1)
        dte = (third - today).days
        if 7 <= dte <= rules.MONTHLY_DTE_BUCKET[1]:
            choices.append((third.isoformat(), dte))
    return choices[:MONTHLY_EXPIRIES_TO_CHECK]


def _monthly_candidates(expiries: Iterable[str], today: date | None, stamp: str, venue: str) -> list["rules.MonthlyChoice"]:
    """Nearest standard monthly with at least seven calendar days and its successor.
    The 60-day maximum remains the existing publisher/Worker validation boundary."""
    if today is None:
        return []
    remaining = sorted(set(text for text in expiries if isinstance(text, str) and
        len(text) == 10 and text >= (today + timedelta(days=MONTHLY_MIN_DTE)).isoformat() and
        text <= (today + timedelta(days=rules.MONTHLY_DTE_BUCKET[1])).isoformat()))
    selected: list["rules.MonthlyChoice"] = []
    for _ in range(MONTHLY_EXPIRIES_TO_CHECK):
        choice = _monthly_choice(remaining, today, stamp, venue)
        if choice is None:
            break
        selected.append(choice)
        remaining = [text for text in remaining if text > choice.expiry.isoformat()]
    return selected


def _monthly_quote_observation(ticker: str, spot: float, choices: list["rules.MonthlyChoice"],
                               calls: list[dict[str, Any]], stamp: str, today: date, *,
                               currency: str, source: str, provenance: str, rights: str,
                               identity: dict[str, str] | None, cc_reason: str,
                               puts: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Observation-only quote when the 6%+ strategy cannot be shown.
    The two-sided bid (not mid) defines annualized collectible premium; without it,
    a LAST quote is purely indicative. Neither lane qualifies as a recommendation."""
    if not _is_finite_positive(spot) or not choices:
        return None
    by_expiry = {choice.expiry.isoformat(): choice for choice in choices}
    available = [row for row in calls if row.get("expiry") in by_expiry and row.get("size") == 100
                 and _cent_exact(row.get("strike")) and row["strike"] > spot
                 and isinstance(row.get("dte"), int) and MONTHLY_MIN_DTE <= row["dte"] <= 60]
    if not available:
        return None
    both = [row for row in available if _is_two_sided(row.get("bid"), row.get("ask"))]
    # The observation is *not* a tradeable tier: even a very wide spread can be shown with the explicit spread caveat.
    # Pick largest bid/spot annualized among the two checked expiries; no delta inference or fake liquidity values.
    best = max(both, key=lambda row: (row["bid"]/spot*365/row["dte"], -row["dte"])) if both else None
    if best is None:
        with_last = [row for row in available if _is_finite_positive(row.get("last"))]
        best = max(with_last, key=lambda row: (row["last"]/spot*365/row["dte"], -row["dte"])) if with_last else min(
            available, key=lambda row: (row["dte"], row["strike"]))
    dte = best["dte"]
    is_both = best in both
    last = best.get("last") if _is_finite_positive(best.get("last")) else None
    annual = (best["bid"] if is_both else last)
    obs = {"kind": "TWO_SIDED" if is_both else "NO_TWO_SIDED",
           "strike": best["strike"],
           "bid": best["bid"] if is_both else None, "ask": best["ask"] if is_both else None,
           "last": last if not is_both else None,
           "annualized_yield": round(annual/spot*365/dte, 6) if annual is not None else None,
           "oi": best.get("oi") if isinstance(best.get("oi"), int) and best["oi"] >= 0 else None,
           "volume": best.get("volume") if isinstance(best.get("volume"), int) and best["volume"] >= 0 else None}
    choice = by_expiry[best["expiry"]]
    result = {"ticker": ticker, "strategy": "COVERED_CALL", "expiry": best["expiry"], "dte": dte,
              "spot": spot, "currency": currency, "multiplier": 100, "quote_basis": "delayed",
              "timestamp": stamp, "source": source, "provenance": provenance, "rights_status": rights,
              "suggestions": [], "quote_observation": obs, "asof_date": today.isoformat(),
              "monthly_rule": choice.rule}
    if identity is not None:
        result.update(identity)
    # A call observation is not an eligible sell tier: preserve whether the cause
    # was missing quotes, strike eligibility, or low premium. Independently valid
    # put strategies from the same expiry retain their own source-backed evidence.
    same_calls = [r for r in calls if r.get("expiry") == best["expiry"]]
    same_puts = [r for r in (puts or []) if r.get("expiry") == best["expiry"] and r.get("size") == 100]
    if identity is not None and puts is not None:
        label = {"rights_status":rights,"provider_id":identity["provider_id"],
                 "quote_basis":"delayed","timestamp":stamp}
        blocks = strategy_blocks(same_calls,same_puts,spot,dte,label)
        if any("unavailable" not in blocks.get(name, {"unavailable":""}) for name in ("csp","collar")):
            result["strategies"] = {"cc": {"unavailable": cc_reason}, **blocks}
    return result


def _nonstandard_monthly_observation(
        calls: list[dict[str, Any]], puts: list[dict[str, Any]] | None, ticker: str, spot: float,
        stamp: str, today: date | None, *, currency: str, source: str, provenance: str,
        rights: str, identity: dict[str, str] | None) -> dict[str, Any] | None:
    """Fallback when neither standard monthly is available in the *actually read* chain.
    The earliest real 7-60DTE expiry is displayed as 非標準月到期, with source time.
    This is strictly OBSERVATION-ONLY: zero invented strikes/premia and zero sell tiers.
    Never overwrite a found standard monthly; the reader independently classifies dates."""
    if today is None or not _is_finite_positive(spot):
        return None
    rows = [row for row in calls if row.get("size") == 100
            and _is_finite_positive(row.get("strike")) and _cent_exact(row["strike"])
            and isinstance(row.get("dte"), int) and 7 <= row["dte"] <= 60
            and isinstance(row.get("expiry"), str) and len(row["expiry"]) == 10]
    # If only the put side is present, still show the actually observed expiry, never a guessed call.
    put_days = [row for row in (puts or []) if row.get("size") == 100
                and isinstance(row.get("dte"), int) and 7 <= row["dte"] <= 60
                and isinstance(row.get("expiry"), str) and len(row["expiry"]) == 10]
    listed = sorted(set(row["expiry"] for row in rows + put_days))
    # A standard expiry with no quote is NOT evidence that the next real
    # non-standard listed contract is a standard month. Classify each date.
    eligible_days: list[date] = []
    for iso in listed:
        try:
            parsed = date.fromisoformat(iso)
            if parsed.isoformat() == iso and parsed != rules.third_friday(parsed.year,parsed.month):
                eligible_days.append(parsed)
        except ValueError:
            continue
    if not eligible_days:
        return None
    day = min(eligible_days)
    expiry = day.isoformat()
    chosen = [row for row in rows if row["expiry"] == expiry and row["strike"] > spot]
    two = [row for row in chosen if _is_two_sided(row.get("bid"), row.get("ask"))]
    last = [row for row in chosen if _is_finite_positive(row.get("last"))]
    best = min(two, key=lambda row: row["strike"]) if two else (
        min(last, key=lambda row: row["strike"]) if last else
        min(chosen, key=lambda row: row["strike"]) if chosen else None)
    dte = (day - today).days
    result = {"ticker": ticker, "strategy": "COVERED_CALL", "expiry": expiry, "dte": dte,
              "spot": spot, "currency": currency, "multiplier": 100,
              "quote_basis": "delayed", "timestamp": stamp, "source": source,
              "provenance": provenance, "rights_status": rights,
              "asof_date": today.isoformat(), "suggestions": [],
              "monthly_nonstandard": True}
    if identity is not None:
        result.update(identity)
    if best is not None:
        has_both = best in two
        price = best["bid"] if has_both else best.get("last") if best in last else None
        result["quote_observation"] = {
            "kind": "TWO_SIDED" if has_both else "NO_TWO_SIDED",
            "strike": best["strike"], "bid": best["bid"] if has_both else None,
            "ask": best["ask"] if has_both else None,
            "last": None if has_both else price,
            "annualized_yield": round(price / spot * 365 / dte, 6) if price is not None else None,
            "oi": best.get("oi") if isinstance(best.get("oi"), int) and best["oi"] >= 0 else None,
            "volume": best.get("volume") if isinstance(best.get("volume"), int) and best["volume"] >= 0 else None}
    return result


def _any_put_two_sided(puts: list[dict[str, Any]] | None) -> bool:
    return bool(puts) and any(_is_two_sided(row.get("bid"), row.get("ask")) for row in puts)


def _cycles_from_calls(calls: list[dict[str, Any]], ticker: str, spot: float, stamp: str, *, currency: str, source: str,
                       provenance: str, rights: str, missing: str, venue: str = "US",
                       underlying: str | None = None,
                       no_window: Callable[[str, int, int], tuple[str, str]] | None = None,
                       today: date | None = None, week_expiries: Iterable[str] | None = None,
                       identity: dict[str, str] | None = None, puts: list[dict[str, Any]] | None = None) -> CyclesResult:
    """Weekly: the current calendar week's earliest listed expiry (the next week's only when this week has none left; see
    option_recommendation_rules); monthly: the nearest standard monthly (shared rule). Standard 100-share contracts only.
    today is the exchange-local as-of date (derived from the rows' expiry and dte when absent); week_expiries lets the caller
    decide the week from every listed expiry, so a contract with refused terms is never silently skipped for the next week. A
    cycle without a qualifying expiry takes its reason and health status from no_window(cycle, low, high) when the caller
    proved more about its source than 'nothing listed'."""
    out: dict[str, Any] = {}
    health_records: list[dict[str, Any]] = []
    und = underlying or ticker
    if today is None and calls:
        today = date.fromisoformat(calls[0]["expiry"]) - timedelta(days=int(calls[0]["dte"]))
    for cycle, (low, high) in CYCLES.items():
        week: str | None = None
        monthly_rule: str | None = None
        if cycle == "weekly":
            choice = _weekly_choice(week_expiries if week_expiries is not None
                                    else [row["expiry"] for row in calls if row["strike"] and row["size"] == 100], today, stamp, venue)
            week = choice.week if choice else None
            window = [row for row in calls if choice and row["expiry"] == choice.expiry.isoformat() and row["strike"] and row["size"] == 100]
        else:
            monthly_choices = _monthly_candidates(
                week_expiries if week_expiries is not None else [row["expiry"] for row in calls], today, stamp, venue)
            monthly = monthly_choices[0] if monthly_choices else None
            monthly_rule = monthly.rule if monthly else None
            window = [row for row in calls if monthly and row["expiry"] == monthly.expiry.isoformat()
                      and row["strike"] and row["size"] == 100]
            # Source-backed maturity FIRST, not highest yield: the nearest standard
            # >=7DTE expiry wins; try the second ONLY when that first expiry is unreadable
            # or lacks both a positive two-sided quote and a positive last quote.
            selected = None
            for choice in monthly_choices:
                candidate = [row for row in calls if row.get("expiry") == choice.expiry.isoformat()
                             and row.get("size") == 100 and _is_finite_positive(row.get("strike"))]
                call_read = any(_is_two_sided(row.get("bid"), row.get("ask"))
                                or _is_finite_positive(row.get("last")) for row in candidate)
                put_read = any(row.get("expiry") == choice.expiry.isoformat()
                               and row.get("size") == 100
                               and _is_two_sided(row.get("bid"), row.get("ask")) for row in (puts or []))
                if call_read or put_read:
                    selected = (candidate,choice)
                    break
            # A listed standard month whose source contains OTM strikes but no
            # usable quote still merits a dated informational line, not "unavailable".
            # A quoted successor has already been preferred above when the nearer
            # expiry has no usable price.
            if selected is None:
                for choice in monthly_choices:
                    candidate = [row for row in calls if row.get("expiry") == choice.expiry.isoformat()
                        and row.get("size") == 100 and _is_finite_positive(row.get("strike"))]
                    if any(row["strike"] > spot for row in candidate):
                        selected = (candidate, choice)
                        break
            if selected is not None:
                window, monthly = selected
                monthly_rule = monthly.rule
                tiers, _ = covered_call_tiers(window, spot, window[0]["dte"]) if window else ([],None)
                if not tiers or not any(tier["annualized_yield"] >= MONTHLY_ANNUAL_HURDLE for tier in tiers):
                    cc_reason = ("低於6%門檻，買權僅作報價觀察；不構成備兌買權建議" if tiers else
                                 _covered_call_unavailable(window, spot, (monthly.expiry - today).days, monthly.expiry.isoformat()))
                    observation = _monthly_quote_observation(
                        ticker, spot, [monthly], calls, stamp, today, currency=currency, source=source,
                        provenance=provenance, rights=rights, identity=identity, cc_reason=cc_reason, puts=puts)
                    if observation is not None:
                        health_records.append({"venue": venue, "underlying": und,
                           "expiry": observation["expiry"], "cycle": "monthly", "status": "READ",
                           "read": True, "two_sided": observation["quote_observation"]["kind"] == "TWO_SIDED"})
                        out["monthly"] = observation
                        continue
            # No usable standard monthly in the returned chain: never discard its
            # nearest listed 7-60DTE expiry. It becomes an explicit nonstandard,
            # no-trade observation, not a mislabelled monthly strategy.
            if selected is None:
                fallback = _nonstandard_monthly_observation(
                    calls, puts, ticker, spot, stamp, today, currency=currency, source=source,
                    provenance=provenance, rights=rights, identity=identity)
                if fallback is not None:
                    health_records.append({"venue": venue, "underlying": und,
                        "expiry": fallback["expiry"], "cycle": "monthly", "status": "READ",
                        "read": True, "two_sided": bool(
                            fallback.get("quote_observation",{}).get("kind") == "TWO_SIDED")})
                    out["monthly"] = fallback
                    continue
        if not window and cycle == "monthly" and monthly is not None and puts is not None:
            put_rows = [row for row in puts if row.get("expiry") == monthly.expiry.isoformat()
                        and row.get("size") == 100]
            if _any_put_two_sided(put_rows):
                only_put = cycle_result(ticker, monthly.expiry.isoformat(),
                    (monthly.expiry-today).days, spot, [], currency=currency, source=source,
                    provenance=provenance, rights=rights, stamp=stamp,
                    asof=today.isoformat(), identity=identity, puts=put_rows,
                    monthly_rule=monthly_rule)
                if "unavailable" not in only_put:
                    out[cycle] = only_put
                    health_records.append({"venue":venue,"underlying":und,"expiry":monthly.expiry.isoformat(),
                        "cycle":cycle,"status":"READ","read":True,"two_sided":True})
                    continue
        if not window:
            message, status = no_window(cycle, low, high) if no_window else (_missing_text(missing, cycle, low, high), "NO_EXPIRY")
            health_records.append({"venue": venue, "underlying": und, "expiry": None, "cycle": cycle,
                                   "status": status, "read": False, "two_sided": False})
            out[cycle] = {"unavailable": _diag(message)}
            continue
        target = window[0]["dte"]
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
        chosen_puts = None if puts is None else [r for r in puts if r.get("expiry") == chosen_expiry and r.get("size") == 100]
        if not two_sided and not _any_put_two_sided(chosen_puts):
            out[cycle] = {"unavailable": _diag(f"本次回應有 {chosen_expiry}（{target}天）標準買權上市，但所選到期無有效雙邊報價（買賣價須為正且不倒掛）")}
        else:
            out[cycle] = cycle_result(ticker, chosen_expiry, target, spot, chosen, currency=currency, source=source,
                                      provenance=provenance, rights=rights, stamp=stamp,
                                      asof=today.isoformat() if today else None, week=week, identity=identity, puts=chosen_puts,
                                      monthly_rule=monthly_rule)
    return CyclesResult(out, health=health_records)


def _nasdaq_us_asof(payload: Any) -> date | None:
    """Source date only: lastTrade text or table.asOf date. NEVER substitute fetch/clock time."""
    try:
        data = payload["data"]
        candidates = (data.get("lastTrade"), (data.get("table") or {}).get("asOf"))
        for text in candidates:
            if not isinstance(text, str) or len(text) > 180:
                continue
            match = _ASOF_RE.search(text)
            if match:
                month = _ASOF_MONTHS.get(match.group(1).upper())
                if month is not None:
                    return date(int(match.group(3)), month, int(match.group(2)))
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
                return date.fromisoformat(text)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return None


def _nasdaq_us_group_date(value: Any) -> date | None:
    if not isinstance(value,str) or not 8 <= len(value.strip()) <= 40:
        return None
    text=value.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:return datetime.strptime(text,fmt).date()
        except ValueError:continue
    return None


def _nasdaq_us_quote(value: Any) -> float | None:
    """Bounded explicit US decimal / quoted dollar strings, not locale-ambiguous guessing."""
    if isinstance(value,str):
        text=value.strip()
        if len(text)>32 or not re.fullmatch(r"\$?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,4})?",text):
            return None
        value=text.lstrip("$").replace(",","")
    return _float(value)


def nasdaq_us_options(symbol: str, spot: float, today: date, stamp: str) -> CyclesResult:
    """Fallback US chain from Nasdaq's public quote-page API: two-sided call quotes without implied volatility, so no
    delta (as for Nasdaq Stockholm). Class shares use a dot there (BRK-B -> brk.b)."""
    low, high = min(window[0] for window in CYCLES.values()), max(window[1] for window in CYCLES.values())
    url = NASDAQ_US_CHAIN.format(symbol=urllib.parse.quote(symbol.replace("-", ".").lower()),
                                 start=(today + timedelta(days=low)).isoformat(), end=(today + timedelta(days=high)).isoformat())
    try:
        payload = http_json(url)
        rows = payload["data"]["table"]["rows"]
        if rows is None:
            rows = []
    except Exception:
        err_health = [{"venue": "US", "underlying": symbol, "expiry": None, "cycle": c,
                       "status": "READ_ERROR", "read": False, "two_sided": False} for c in CYCLES]
        return CyclesResult({cycle: {"unavailable": "Nasdaq 期權鏈讀取失敗"} for cycle in CYCLES}, health=err_health)
    if not rows:
        empty_health = [{"venue": "US", "underlying": symbol, "expiry": None, "cycle": c,
                         "status": "EMPTY_RESPONSE", "read": False, "two_sided": False} for c in CYCLES]
        return CyclesResult({c: {"unavailable": _missing_text("Nasdaq 無 {low}-{high} 天到期的上市期權", c, *CYCLES[c])} for c in CYCLES},
                            health=empty_health)
    asof = _nasdaq_us_asof(payload)
    if asof is None or not 0 <= (today - asof).days <= NASDAQ_US_MAX_ASOF_AGE_DAYS:
        stale_health = [{"venue": "US", "underlying": symbol, "expiry": None, "cycle": c,
                         "status": "STALE_ASOF", "read": False, "two_sided": False} for c in CYCLES]
        return CyclesResult({c: {"unavailable": NASDAQ_US_STALE_TEXT} for c in CYCLES}, health=stale_health)
    calls: list[dict[str, Any]] = []
    puts: list[dict[str, Any]] = []
    saw_put_side = False

    def decode_rows(source_rows: list, expected_expiry: str | None = None) -> None:
        nonlocal saw_put_side
        active: date | None = None
        for row in source_rows:
            if not isinstance(row,dict):
                continue
            if row.get("expirygroup"):
                active = _nasdaq_us_group_date(row["expirygroup"])
                continue
            resolved = _nasdaq_us_group_date(row.get("expirationDate")) or active
            if resolved is None or (expected_expiry is not None and resolved.isoformat() != expected_expiry):
                continue
            strike = _nasdaq_us_quote(row.get("strike"))
            if not _is_finite_positive(strike):
                continue
            calls.append({"expiry": resolved.isoformat(), "dte": (resolved-today).days, "strike": strike,
                          "bid": _nasdaq_us_quote(row.get("c_Bid")), "ask": _nasdaq_us_quote(row.get("c_Ask")),
                          "last": _nasdaq_us_quote(row.get("c_Last")), "iv": None, "delta": None,
                          "oi": _int(row.get("c_Openinterest")), "volume": _int(row.get("c_Volume")), "size": 100})
            if any(key in row for key in ("p_Bid","p_Ask")):
                saw_put_side = True
                puts.append({"expiry": resolved.isoformat(), "dte": (resolved-today).days, "strike":strike,
                             "bid": _nasdaq_us_quote(row.get("p_Bid")), "ask": _nasdaq_us_quote(row.get("p_Ask")),
                             "iv": None, "oi": _int(row.get("p_Openinterest")),
                             "volume": _int(row.get("p_Volume")), "size": 100})
    decode_rows(rows)
    # The broad provider response may omit some dates. Query up to the next two
    # standard monthly dates explicitly, and admit ONLY a correctly dated typed
    # contract with a valid source as-of. Never trust the calendar guess alone.
    if not _monthly_candidates([row["expiry"] for row in calls+puts], today, stamp, "US"):
        for standard_day, _days in _calendar_standard_monthlies(today):
            if any(row["expiry"] == standard_day for row in calls+puts):
                break
            targeted = NASDAQ_US_CHAIN.format(
                symbol=urllib.parse.quote(symbol.replace("-", ".").lower()),
                start=standard_day,end=standard_day)
            try:
                response = http_json(targeted)
                source_rows = response["data"]["table"]["rows"]
                source_asof = _nasdaq_us_asof(response)
                if (not isinstance(source_rows,list) or source_asof is None
                        or not 0 <= (today-source_asof).days <= NASDAQ_US_MAX_ASOF_AGE_DAYS):
                    continue
                decode_rows(source_rows,expected_expiry=standard_day)
            except (ValueError,TypeError,KeyError,AttributeError,OSError):
                continue
            if any(row["expiry"] == standard_day for row in calls+puts):
                break
    if not calls and not puts:
        health = [{"venue":"US","underlying":symbol,"expiry":None,"cycle":c,
                  "status":"SOURCE_ROWS_NOT_TYPED","read":False,"two_sided":False} for c in CYCLES]
        msg = "Nasdaq US 已回應鏈資料，但到期日／履約價／買賣欄位無法解析為經核驗標準契約（非證明未上市）"
        return CyclesResult({c:{"unavailable":msg} for c in CYCLES},health=health)
    return _cycles_from_calls(calls, symbol, spot, stamp, currency="USD",
                              source="Nasdaq US option chain (public quote page API, delayed; Yahoo fallback)",
                              provenance=f"https://www.nasdaq.com/market-activity/stocks/{symbol.replace('-', '.').lower()}/option-chain",
                              rights=NASDAQ_US_RIGHTS_LABEL, missing="Nasdaq 無 {low}-{high} 天到期的上市期權",
                              venue="US", underlying=symbol, today=today, identity=NASDAQ_US_OPTION_IDENTITY,
                              puts=puts if saw_put_side else None)


def _yahoo_unread(value: dict[str, Any] | None) -> bool:
    reason = str((value or {"unavailable": "讀取失敗"}).get("unavailable", ""))
    return ("讀取失敗" in reason or "Yahoo Finance 期權到期日清單" in reason
            or "標準月選鏈無可驗證合約資料" in reason)


def us_cycles(symbol: str, spot: float, today: date, stamp: str) -> CyclesResult:
    """Yahoo first; only unread cycles use Nasdaq's bounded source-specific lookup.
    Preserve the fallback's validated refusal (including stale/unconfirmed as-of);
    combine transport failures only when both providers actually failed to read."""
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
        elif (any(h.get("cycle") == cycle and h.get("status") in ("READ_ERROR", "EXPIRY_LIST_ERROR") for h in yahoo_health)
              and any(h.get("cycle") == cycle and h.get("status") == "READ_ERROR" for h in fallback_health)):
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


def _standard_yahoo_us_contract(row: Any) -> bool:
    """Yahoo REGULAR explicitly denotes the standard US contract; unknown terms never imply 100 USD shares."""
    size, currency = getattr(row, "contractSize", None), getattr(row, "currency", None)
    return isinstance(size, str) and isinstance(currency, str) and size == "REGULAR" and currency == "USD"


def _yahoo_put_rows(option_chain: Any) -> list[dict[str, Any]] | None:
    """The put rows of a Yahoo chain (strike, bid, ask, quoted IV, open interest, volume); None when the chain object has no put table."""
    try:
        table = getattr(option_chain, "puts", None)
        if table is None:
            return None
        out = []
        for row in table.itertuples():
            if not _standard_yahoo_us_contract(row):
                continue
            strike = _float(getattr(row, "strike", None))
            if strike is not None and _is_finite_positive(strike):
                out.append({"strike": float(strike), "bid": _float(getattr(row, "bid", None)), "ask": _float(getattr(row, "ask", None)),
                            "iv": _float(getattr(row, "impliedVolatility", None)), "oi": _int(getattr(row, "openInterest", None)),
                            "volume": _int(getattr(row, "volume", None))})
        return out
    except Exception:
        return None


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
        if expiry_list_error and cycle == "weekly":
            health_records.append({"venue": "US", "underlying": symbol, "expiry": None, "cycle": cycle,
                                   "status": "EXPIRY_LIST_ERROR", "read": False, "two_sided": False})
            out[cycle] = {"unavailable": "Yahoo 週選到期日清單讀取失敗；是否上市尚無法驗證"}
            continue
        if not expiries and cycle == "weekly":
            health_records.append({"venue": "US", "underlying": symbol, "expiry": None, "cycle": cycle,
                                   "status": "EMPTY_RESPONSE", "read": False, "two_sided": False})
            out[cycle] = {"unavailable": _missing_text("無 {low}-{high} 天到期的上市期權（Yahoo Finance 期權到期日清單）", cycle, low, high)}
            continue
        week: str | None = None
        monthly_rule: str | None = None
        candidates = []
        if cycle == "weekly":  # the current calendar week's earliest listed expiry, else next week's (never a later one)
            choice = _weekly_choice(expiries, today, stamp, "US")
            if choice:
                week = choice.week
                candidates = [(choice.expiry.isoformat(), (choice.expiry - today).days)]
        else:
            monthly_choices = _monthly_candidates(expiries, today, stamp, "US")
            candidates = [(selected.expiry.isoformat(), (selected.expiry - today).days) for selected in monthly_choices]
            # If the cached expiry list is only weekly, independently request the
            # nearest standard third Friday and successor. A calendar date is not
            # evidence of a listed contract until Yahoo returns a typed chain.
            for calendar_choice in _calendar_standard_monthlies(today):
                if calendar_choice not in candidates and len(candidates) < 2:
                    candidates.append(calendar_choice)
            if not monthly_choices:
                nearest_like = sorted((row, (date.fromisoformat(row)-today).days)
                    for row in expiries if isinstance(row,str) and len(row)==10
                    and _is_actual_date(row) and 7 <= (date.fromisoformat(row)-today).days <= 60
                    and date.fromisoformat(row)!=rules.third_friday(
                        date.fromisoformat(row).year,date.fromisoformat(row).month))
                if nearest_like:
                    candidates.append(nearest_like[0])
            if monthly_choices:
                monthly_rule = monthly_choices[0].rule
        if not candidates:
            health_records.append({"venue": "US", "underlying": symbol, "expiry": None, "cycle": cycle,
                                   "status": "NO_EXPIRY", "read": False, "two_sided": False})
            out[cycle] = {"unavailable": _missing_text("無 {low}-{high} 天到期的上市期權（Yahoo Finance 期權到期日清單）", cycle, low, high)}
            continue
        if cycle == "monthly":
            # Yahoo supplies each expiry's put and call table separately; the old path only fetched
            # the first month and could neither examine the next standard maturity nor construct
            # the other two strategies from the second month's put side.
            all_calls: list[dict[str, Any]] = []
            all_puts: list[dict[str, Any]] = []
            put_side_seen = False
            read_failures = 0
            for month_expiry, month_dte in candidates:
                try:
                    option_chain = ticker.option_chain(month_expiry)
                    call_table = option_chain.calls
                except Exception:
                    read_failures += 1
                    continue
                for call in call_table.itertuples():
                    if not _standard_yahoo_us_contract(call):
                        continue
                    strike = _float(getattr(call, "strike", None))
                    if not _is_finite_positive(strike):
                        continue
                    iv = _float(getattr(call, "impliedVolatility", None))
                    all_calls.append({"expiry": month_expiry, "dte": month_dte, "strike": strike,
                        "bid": _float(getattr(call, "bid", None)), "ask": _float(getattr(call, "ask", None)),
                        "last": _float(getattr(call, "lastPrice", None)), "iv": iv,
                        "delta": bs_call_delta(spot, strike, rules.effective_days(month_dte)/365, iv),
                        "oi": _int(getattr(call, "openInterest", None)),
                        "volume": _int(getattr(call, "volume", None)), "size": 100})
                puts = _yahoo_put_rows(option_chain)
                if puts is not None:
                    put_side_seen = True
                    all_puts.extend({**row, "expiry":month_expiry,"dte":month_dte,"size":100} for row in puts)
            if not all_calls and not all_puts:
                known_window = any(_is_actual_date(row) and
                    7 <= (date.fromisoformat(row)-today).days <= 60 for row in expiries)
                status = "EXPIRY_LIST_ERROR" if expiry_list_error else (
                    "EMPTY_RESPONSE" if not expiries else "NO_EXPIRY" if not known_window else
                    "READ_ERROR" if read_failures>0 else "EMPTY_RESPONSE")
                health_records.append({"venue":"US","underlying":symbol,
                    "expiry":None if status in ("EXPIRY_LIST_ERROR","NO_EXPIRY") or not expiries
                    else candidates[0][0],
                    "cycle":"monthly","status":status,"read":False,"two_sided":False})
                reason = ("Yahoo 到期日清單讀取失敗；已獨立補查標準月到期日但未取得可核驗合約"
                          if expiry_list_error else
                          "Yahoo 標準月選鏈無可驗證合約資料；已補查標準到期日但來源未回傳可核驗合約（不能推定未上市）")
                out["monthly"] = {"unavailable":reason}
                continue
            monthly_result=_cycles_from_calls(all_calls,symbol,spot,stamp,currency="USD",
                source="Yahoo Finance option chain (unofficial, delayed)",
                provenance=f"https://finance.yahoo.com/quote/{symbol}/options",
                rights=YAHOO_RIGHTS_LABEL,missing="Yahoo 交易所到期清單沒有距到期至少7天的標準月選",
                venue="US",underlying=symbol,today=today,
                week_expiries=sorted({row["expiry"] for row in all_calls + all_puts}),
                identity=YAHOO_OPTION_IDENTITY,puts=all_puts if put_side_seen else None)
            out["monthly"]=monthly_result["monthly"]
            health_records.extend(h for h in monthly_result.health if h.get("cycle")=="monthly")
            continue
        expiry, dte = candidates[0]
        try:
            option_chain = ticker.option_chain(expiry)
            chain = option_chain.calls
        except Exception:
            health_records.append({"venue": "US", "underlying": symbol, "expiry": expiry, "cycle": cycle,
                                   "status": "READ_ERROR", "read": False, "two_sided": False})
            out[cycle] = {"unavailable": "期權鏈讀取失敗"}
            continue
        rows = []
        eligible_rows = []
        for row in chain.itertuples():
            if not _standard_yahoo_us_contract(row):
                continue
            strike = _float(getattr(row, "strike", None))
            bid = _float(getattr(row, "bid", None))
            ask = _float(getattr(row, "ask", None))
            iv = _float(getattr(row, "impliedVolatility", None))
            oi = _int(getattr(row, "openInterest", None))
            vol = _int(getattr(row, "volume", None))
            if strike is not None and _is_finite_positive(strike):
                r_dict = {"strike": float(strike), "bid": bid, "ask": ask, "iv": iv,
                          "delta": bs_call_delta(spot, float(strike), rules.effective_days(dte) / 365, iv), "oi": oi, "volume": vol}
                rows.append(r_dict)
                eligible_rows.append(r_dict)
        put_rows = _yahoo_put_rows(option_chain)
        if not eligible_rows:
            health_records.append({"venue": "US", "underlying": symbol, "expiry": expiry, "cycle": cycle,
                                   "status": "SOURCE_ROWS_NOT_TYPED" if rows else "EMPTY_RESPONSE", "read": False, "two_sided": False})
            out[cycle] = {"unavailable":"Yahoo 本次有鏈回應但買權欄位／標準100股美元合約無法解析（非證明未上市）"}
            continue
        else:
            two_sided = any(_is_two_sided(r["bid"], r["ask"]) for r in eligible_rows)
            health_records.append({"venue": "US", "underlying": symbol, "expiry": expiry, "cycle": cycle,
                                   "status": "READ", "read": True, "two_sided": two_sided, "eligible_rows": len(eligible_rows)})
        if eligible_rows and not two_sided and not _any_put_two_sided(put_rows):  # read chain, no usable quote: say so, not a strategy-yield failure
            out[cycle] = {"unavailable": _diag(f"本次回應有 {expiry}（{dte}天）買權，但{carry_forward.NO_TWO_SIDED_REASON}（買賣價須為正且不倒掛）")}
            continue
        out[cycle] = cycle_result(symbol, expiry, dte, spot, rows, currency="USD",
                                  source="Yahoo Finance option chain (unofficial, delayed)",
                                  provenance=f"https://finance.yahoo.com/quote/{symbol}/options?date={expiry}; delta=Black-Scholes(quoted IV)",
                                  rights=YAHOO_RIGHTS_LABEL, stamp=stamp, asof=today.isoformat(), week=week, identity=YAHOO_OPTION_IDENTITY,
                                  puts=put_rows, monthly_rule=monthly_rule)
    return CyclesResult(out, health=health_records)


SEK = "SEK"
_NO_SEARCH = object()
_NORDIC_PUT_NAME = re.compile(r"^([A-Z0-9]{1,12}) ([0-3][0-9])([A-Z]{3})([0-9]{2}) ([0-9]{1,6}(?:\.[0-9]{1,4})?)P$")
_NORDIC_CALL_NAME = re.compile(r"^([A-Z0-9]{1,12}) ([0-3][0-9])([A-Z]{3})([0-9]{2}) ([0-9]{1,6}(?:\.[0-9]{1,4})?)C$")
_MONTH_NUMBER = {name: number for number, name in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
NORDIC_SOURCE = "Nasdaq Nordic option chain (exchange public web API, delayed)"
# V13: the chain sends every option row with currency "" (retained 2026-10-17, R/v13-evidence-a43bef58). Nasdaq's contract
# specification for options on Swedish shares: the premium "Shall be expressed in Swedish Kronor or Euro depending on the
# underlying shares". A blank (exactly "" or an absent key) contract currency therefore follows the underlying, which
# nordic_options confirms as SEK before any row is read; every other unconfirmed form stays UNKNOWN.
NORDIC_BLANK_CURRENCY = "BLANK_FOLLOWS_UNDERLYING"
_ABSENT = object()


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
_PUT_MONTH_LETTERS = "MNOPQRSTUVWX"  # the put series letter: January .. December
_SUPPORTED_WEEKLY_TAG = "Y"  # the ONLY weekly series tag the retained VOLVB receipt proves; any other tag is unproven, not a free slot
_STRIKE_TEXT = r"(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,4})?"  # bounded strike text shared by call names and native symbols
_NATIVE_SYMBOL_SUFFIX = re.compile(r"([0-9])([A-L])(?:([0-9]{2})" + _SUPPORTED_WEEKLY_TAG + r")?(" + _STRIKE_TEXT + r")")


_NATIVE_PUT_SUFFIX = re.compile(r"([0-9])([M-X])(?:([0-9]{2})" + _SUPPORTED_WEEKLY_TAG + r")?(" + _STRIKE_TEXT + r")")


def _native_symbol_matches(symbol: str, root: str, expiry: date, strike: Decimal, *, put: bool = False) -> bool:
    """The COMPLETE encoded identity of the two source forms the retained receipts prove: ROOT + year digit + call-month
    letter + strike (SIVE6J15.50, SIVE6J16) and the weekly ROOT + year digit + call-month letter + day + tag Y + strike
    (VOLVB6J02Y280). Root, year, month/type, day (weekly) and the EXACT decimal strike (no float tolerance) must ALL agree with
    the row's expiry and strike; a prefix, another contract of the same root, a put letter, any other weekly tag, an unsupported
    encoding or precision is not identity."""
    if not symbol.startswith(root):
        return False
    match = (_NATIVE_PUT_SUFFIX if put else _NATIVE_SYMBOL_SUFFIX).fullmatch(symbol[len(root):])
    if not match:
        return False
    year_digit, month_letter, day, strike_text = match.groups()
    if int(year_digit) != expiry.year % 10 or month_letter != (_PUT_MONTH_LETTERS if put else _CALL_MONTH_LETTERS)[expiry.month - 1]:
        return False
    if day is not None and int(day) != expiry.day:
        return False
    return Decimal(strike_text) == strike


def _nordic_price(value: Any) -> float | None:
    """Stockholm comma decimals; no inferred units/contract currency or rounded strikes."""
    if isinstance(value,str) and "," in value:
        # Nordic comma is a decimal mark, never a US thousands separator.
        # Mixed commas/periods are ambiguous and cannot be used for a financial quote.
        if "." in value or len(value)>24 or not re.fullmatch(r"(?:0|[1-9][0-9]{0,6}),[0-9]{1,4}",value):
            return None
        value=value.replace(",",".")
    return _float(value)


def _nordic_row_evidence(row: Any, root: str, today: date) -> tuple[str, dict[str, Any] | None]:
    """('IGNORE'|'MALFORMED'|'CALL', call). A call is proven only by assetClass OPTIONS and a call name whose underlying
    root, date and strike agree with the row's own expiry and strike fields and with the requested underlying; a trailing
    'C' alone (FUTC, futures, combinations, a missing or unknown class) proves nothing."""
    if not isinstance(row, dict):
        return "MALFORMED", None
    if not isinstance(row.get("assetClass"),str) or row["assetClass"].strip().upper() != "OPTIONS":
        return "IGNORE", None
    raw_name = row.get("fullName")
    if not isinstance(raw_name, str) or len(raw_name)>120:
        return "MALFORMED", None
    name = raw_name
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
        return "MALFORMED", None  # full name, native contract, strike and expiry must still prove SAME identity
    strike = float(strike_exact)
    return "CALL", {"expiry": expiry_text, "dte": (expiry - today).days, "strike": strike,
                    "ccy": _nordic_contract_currency(row.get("currency", _ABSENT)), "size": _typed_size(row.get("contractSize")),
                    "bid": _nordic_price(row.get("bidPrice")), "ask": _nordic_price(row.get("askPrice")),
                    "last": _nordic_price(row.get("lastPrice") or row.get("lastSalePrice")),
                    "oi": _int(row.get("openInterest")), "volume": _int(row.get("volume"))}


def _nordic_put_evidence(row: Any, root: str, today: date) -> str | dict[str, Any]:
    """V21: 'NONE' (not a put row at all), 'MALFORMED' (a put-shaped row whose name, date, strike or native symbol disagree; dropped, it
    never touches the call path) or the put dict. The same proof as a call, with the put name suffix P and the put series letters M..X."""
    if not isinstance(row, dict) or not isinstance(row.get("assetClass"),str) or row["assetClass"].strip().upper() != "OPTIONS":
        return "NONE"
    raw_name = row.get("fullName")
    if not isinstance(raw_name,str) or len(raw_name)>120:
        return "MALFORMED"
    name = raw_name
    if not name.endswith("P") or name.endswith("FUTP"):
        return "NONE"
    match = _NORDIC_PUT_NAME.match(name)
    if not match or match.group(1) != root or match.group(3) not in _MONTH_NUMBER:
        return "MALFORMED"
    raw_strike = row.get("strikePrice")
    if isinstance(raw_strike, bool) or not (isinstance(raw_strike, int) or (isinstance(raw_strike, str) and len(raw_strike) <= 16
                                                                          and _CANONICAL_DECIMAL.fullmatch(raw_strike))):
        return "MALFORMED"
    try:
        name_date = date(2000 + int(match.group(4)), _MONTH_NUMBER[match.group(3)], int(match.group(2)))
        expiry_text = row.get("expirationDate")
        if not isinstance(expiry_text, str) or len(expiry_text) != 10:
            return "MALFORMED"
        expiry = date.fromisoformat(expiry_text)
    except ValueError:
        return "MALFORMED"
    strike_exact = Decimal(raw_strike)
    if expiry != name_date or strike_exact <= 0 or strike_exact != Decimal(match.group(5)):
        return "MALFORMED"
    native_symbol = row.get("symbol")
    if not isinstance(native_symbol, str) or not _native_symbol_matches(native_symbol, root, expiry, strike_exact, put=True):
        return "MALFORMED"
    return {"expiry": expiry_text, "dte": (expiry - today).days, "strike": float(strike_exact),
            "ccy": _nordic_contract_currency(row.get("currency", _ABSENT)), "size": _typed_size(row.get("contractSize")),
            "bid": _nordic_price(row.get("bidPrice")), "ask": _nordic_price(row.get("askPrice")),
            "oi": _int(row.get("openInterest")), "volume": _int(row.get("volume"))}


def _nordic_contract_currency(value: Any) -> str:
    """A contract's own currency: the typed SEK states, or NORDIC_BLANK_CURRENCY for exactly "" or an absent key (the
    exchange rule ties the premium currency to the underlying share). None, whitespace and every other form stay UNKNOWN."""
    if value is _ABSENT or (isinstance(value, str) and value == ""):
        return NORDIC_BLANK_CURRENCY
    return _typed_currency(value)


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
    listed_puts: list[dict[str, Any]] = []
    saw_put_side = False
    malformed = 0
    for row in rows:
        put = _nordic_put_evidence(row, root, today)
        if put != "NONE":
            saw_put_side = True
            if isinstance(put, dict):
                listed_puts.append(put)
            continue  # a put row, valid or not, never counts for the call path
        kind, call = _nordic_row_evidence(row, root, today)
        if kind == "CALL":
            listed.append(call)
        elif kind == "MALFORMED":
            malformed += 1
    if not listed:
        if malformed:
            return _nordic_unavailable(symbol, "MALFORMED_ROWS",
                "Nasdaq Nordic 已回應買權列，但合約名稱／原生代號／履約價與到期日未能同時核驗；未解析者不可推定未上市")
        return _nordic_unavailable(symbol, "NO_EXPIRY", "本次來源回應無可用之買權紀錄；是否上市未確認")
    # This Nordic endpoint lists the whole option chain, not a per-expiry URL.
    # If the first response lacks a standard monthly contract, re-query the
    # source ONCE and inspect specifically the next standard 7-60DTE dates.
    # Never invent an unsupported URL parameter or assert that an absent
    # maturity is listed. On failure the non-standard observation survives.
    standard_targets={iso for iso,_ in _calendar_standard_monthlies(today)}
    if (standard_targets and not _monthly_candidates([x["expiry"] for x in listed],today,stamp,"STOCKHOLM")
            and any(7 <= x["dte"] <= 60 for x in listed)):
        try:
            refreshed = http_json(NORDIC_CHAIN.format(orderbook=orderbook))["data"]["instrumentListing"]["rows"]
            if isinstance(refreshed,list):
                used_calls={(x["expiry"],x["strike"]) for x in listed}
                used_puts={(x["expiry"],x["strike"]) for x in listed_puts}
                for source_row in refreshed:
                    verified_put=_nordic_put_evidence(source_row,root,today)
                    if isinstance(verified_put,dict) and verified_put["expiry"] in standard_targets:
                        key=(verified_put["expiry"],verified_put["strike"])
                        if key not in used_puts:
                            listed_puts.append(verified_put);used_puts.add(key);saw_put_side=True
                        continue
                    kind, verified_call=_nordic_row_evidence(source_row,root,today)
                    if kind=="CALL" and verified_call["expiry"] in standard_targets:
                        key=(verified_call["expiry"],verified_call["strike"])
                        if key not in used_calls:
                            listed.append(verified_call);used_calls.add(key)
        except (TypeError,ValueError,KeyError,AttributeError,OSError):
            pass

    session_open = rules.expiry_day_open(rules.parse_utc_instant(stamp), "STOCKHOLM")

    def no_window(cycle: str, low: int, high: int) -> tuple[str, str]:
        if cycle == "weekly":  # the week is decided from every listed expiry; its contracts then need confirmed terms
            choice = _weekly_choice([call["expiry"] for call in listed], today, stamp, "STOCKHOLM")
            inside = [call for call in listed if choice and call["expiry"] == choice.expiry.isoformat()]
            label = f"{choice.expiry.isoformat()}（{inside[0]['dte']}天）週選" if choice else ""
            low, high = 0, (rules.weekly_window_end(today) - today).days
        else:  # the monthly is decided from every listed expiry, like the weekly; its contracts then need confirmed terms
            choice = _monthly_choice([call["expiry"] for call in listed], today, stamp, "STOCKHOLM")
            inside = [call for call in listed if choice and call["expiry"] == choice.expiry.isoformat()]
            label = f"{choice.expiry.isoformat()}（{inside[0]['dte']}天）標準月選" if choice else ""
        if inside:  # listed in the window, but no contract with confirmed standard terms
            parts = []
            if any(call["size"] == "NONSTANDARD" for call in inside):
                parts.append("合約單位非標準100股")
            if any(call["ccy"] == "CONFLICT" for call in inside):
                parts.append("合約幣別與 SEK 不符")
            if any(call["size"] == "UNKNOWN" or call["ccy"] == "UNKNOWN" for call in inside):
                parts.append("合約單位或幣別來源未確認")
            return f"本次回應有 {label}上市買權；{'、'.join(parts)}，不推薦", "TERMS_REFUSED"
        if malformed:
            return f"本次來源回應含無法解析之列；無法確認{'本週或下週' if cycle == 'weekly' else '標準月選'}是否有買權", "MALFORMED_ROWS"
        upcoming = {call["expiry"]: call["dte"] for call in listed if call["dte"] >= (0 if session_open else 1)}
        nearest = sorted(upcoming.items(), key=lambda item: (min(abs(item[1] - low), abs(item[1] - high)) if cycle == "weekly" else 0, item[1]))[:2]
        context = "、".join(f"{expiry}（{days}天）" for expiry, days in nearest)
        head = "所列到期不在本週或下週策略範圍" if cycle == "weekly" else "所列到期無標準月選（第三個星期五）"
        return f"本次回應有上市買權；{head}" + (f"（最近到期 {context}）" if context else ""), "NO_EXPIRY"

    usable = [{"expiry": call["expiry"], "dte": call["dte"], "strike": call["strike"], "bid": call["bid"], "ask": call["ask"],
               "oi": call["oi"], "volume": call["volume"], "size": 100, "last": call.get("last")}
              for call in listed if call["ccy"] in ("OK", NORDIC_BLANK_CURRENCY) and call["size"] == "OK"]  # underlying SEK confirmed above
    usable_puts = [{"expiry": put["expiry"], "dte": put["dte"], "strike": put["strike"], "bid": put["bid"], "ask": put["ask"],
                    "oi": put["oi"], "volume": put["volume"], "size": 100}
                   for put in listed_puts if put["ccy"] in ("OK", NORDIC_BLANK_CURRENCY) and put["size"] == "OK"]
    return _cycles_from_calls(usable, symbol, spot, stamp, currency=SEK, source=NORDIC_SOURCE,
                              provenance=NORDIC_CHAIN.format(orderbook=orderbook), rights=NORDIC_RIGHTS_LABEL,
                              missing="", venue="STOCKHOLM", underlying=symbol, no_window=no_window, today=today,
                              week_expiries=[call["expiry"] for call in listed], identity=NORDIC_OPTION_IDENTITY,
                              puts=usable_puts if saw_put_side else None)


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
    carry = _CARRY[0]  # set by main for the run (None for a direct call: nothing is carried and nothing is written)
    started = time.monotonic()
    deadline = started + deadline_seconds
    _DEADLINE[0] = deadline
    stamp = iso(now)
    # The as-of date of the expiry rules is the EXCHANGE-LOCAL date (not the UTC date): New York for US listings, Stockholm for .ST.
    today_for = lambda symbol: rules.exchange_date(now, "STOCKHOLM" if symbol.endswith(".ST") else "US")  # noqa: E731
    # Universe discovery on its own daemon thread within the first share of the budget; an overrun uses the cached list.
    found = collect(["universe"], lambda _: broad_universe(now), started + deadline_seconds * DISCOVERY_SHARE)
    broad = found.get("universe") or cached_universe(now)
    orderbooks: dict[str, str] = dict(broad.get("sweden") or {})
    symbols = list(dict.fromkeys(universe() + list(broad.get("us") or []) + list(orderbooks)))
    finished = collect(symbols, lambda symbol: _observe_safely(symbol, today_for(symbol), stamp, orderbooks.get(symbol), deadline), deadline)
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

    # Raw chain health above is measured on the LIVE chains only; carried cycles never count as healthy chains or hide a depleted run.
    if carry is not None:
        try:
            carry.update(options, all_health, now)
        except Exception:  # a carry-forward fault must never break the live observations
            pass

    return {"schema": "v213-market-observations-v2", "generated_at": stamp, "quotes": quotes, "options": options,
            "note": "Delayed public observations; not an order, not a recommendation to trade.",
            "collection": {"underlyings": len(symbols), "unfinished": unfinished, "deadline_seconds": deadline_seconds,
                           "chain_health": chain_health}}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    parser.add_argument("--carry-state", type=Path, default=None,
                        help="previous-session carry-forward state file (default: V213_OPTIONS_CARRY_STATE, else next to --output)")
    parser.add_argument("--no-carry", action="store_true", help="disable the previous-session carry-forward (nothing is carried or written)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    output_path = Path(args.output)
    carry = None if args.no_carry else carry_forward.CarryForward(
        args.carry_state if args.carry_state is not None else carry_forward.default_state_path(output_path))
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
        _CARRY[0] = carry
        document = build(now)
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error": type(error).__name__}))
        return 1
    finally:
        _CARRY[0] = None  # the next run (or a direct call) never inherits this run's state
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
    if carry is not None:
        carry.save(now)  # only a run that was accepted and published updates the carry-forward state
    available = sum(1 for cycles in document["options"].values() for value in cycles.values() if "unavailable" not in value)
    print(json.dumps({"status": "OK", **collection, "quotes": len(document["quotes"]), "option_underlyings": len(document["options"]),
                      "option_observations": available, **({"carry_forward": carry.summary} if carry is not None else {}),
                      "sive": {cycle: ("AVAILABLE" if "unavailable" not in value else str(value["unavailable"])[:160])
                               for cycle, value in (document["options"].get("SIVE.ST") or {}).items() if isinstance(value, dict)}},
                     ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
