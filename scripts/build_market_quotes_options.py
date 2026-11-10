#!/usr/bin/env python3
"""Quotes and listed-option observations for the watch universe (LINE stock lookup and options queries).

Universe: the bottleneck Top20 v3 (top and watch), the carried seven-field Top20 and every layer capturer, plus (operator
2026-09-26: more US names and Swedish large caps) the US_LARGEST largest US listings by market cap in the Nasdaq stock
screener and every Nasdaq Stockholm Large Cap share in SEK with listed exchange options. The broad list is rebuilt daily
(data/cache/options_universe.json); a failed rebuild keeps the previous list for up to BROAD_MAX_STALE_DAYS.
- Quotes: Yahoo Finance regular-market price/time (or a price with an explicitly unknown observation clock),
  previous close and currency (unofficial, delayed; labelled). `asof` is the provider observation clock or null;
  `fetched_at` is acquisition time, never a substitute observation. A US listing Yahoo cannot
  quote falls back to Alpha Vantage GLOBAL_QUOTE (operator 2026-09-26) with the free key from the user's DPAPI file,
  at most ALPHA_VANTAGE_DAILY_BUDGET calls a day (the free key allows 25); without a key there is no fallback call.
- US-listed options: Yahoo Finance option chains (unofficial, delayed); a cycle Yahoo cannot read falls back to the
  Nasdaq US option chain (operator 2026-09-26: Nasdaq data stays in use). Alpha Vantage option chains are premium-only.
- Nasdaq Stockholm options (for example SIVE.ST): the exchange's public option-chain API (api.nasdaq.com/api/nordic).
Per underlying and cycle (weekly = the CURRENT calendar week's expiry, monthly = the NEAREST standard monthly expiry, no minimum DTE):
up to three covered-call sell suggestions for a holder of 100 shares (operator 2026-09-26: collect premium, keep the strike as high as possible so the
shares are not called away; operator 2026-10-11: a middle tier and the current-week weekly):
- HIGH_STRIKE: the highest out-of-the-money strike with a valid sell quote and delta <= MAX_HIGH_STRIKE_DELTA; there is no
  annualized-yield floor (operator 2026-11-03), so a strike paying less than 2% a year is still listed and its annualized yield is
  shown; unverifiable delta never bypasses the cap.
- BALANCED: a lower strike nearest delta BALANCED_DELTA (or BALANCED_MONEYNESS without a delta) for more premium;
- MIDDLE (optional cycle key middle_suggestion): a strike strictly between the two, nearest MIDDLE_DELTA (or
  MIDDLE_MONEYNESS); absent when no listed strike lies between. Defined in option_recommendation_rules.py.
Weekly (operator 2026-10-11): the earliest listed expiry from the exchange-local as-of date through that calendar week's
Sunday; only when none remains (weekend, after the week's last weekly, or after the expiry-day close) the earliest expiry of
the next calendar week; never a later one. The as-of date is the exchange-local date (US: New York, Stockholm: Stockholm),
recorded in each cycle as asof_date together with weekly_week (CURRENT or NEXT). Tiny DTE (0-2) annualizes over at least one
day. The rules live in option_recommendation_rules.py (twin: cloud/src/v213/option-recommendation-rules.ts).
Monthly: the nearest standard venue expiry on or after the exchange-local date, including expiry day until close.
Missing standard chains trigger bounded source lookup, never weekly relabelling or a later month chosen for better quotes.
Holiday shifts require verified source-calendar evidence; an absent Friday alone does not establish a holiday.
Each carries a sell LIMIT starting at the midpoint rounded down to the .01 tick, bounded by the real bid and ask.
Buy LIMITs start at midpoint rounded up. With only the required executable side, that side is the reference limit;
the absent opposite side, midpoint and spread remain unknown. Premium and yield use the limit.
Delta is Black-Scholes from the quoted implied volatility (a labelled model Greek); a two-sided chain without one
(Nasdaq Stockholm, the Nasdaq US fallback) takes the volatility implied by the strike's own bid/ask mid instead
(delta_basis QUOTE_IMPLIED), so every high strike carries the same assignment cap. Prices are never modelled.
Wide spreads do not disqualify recommendations; raw two-sided health remains a separate measure.
V21 (operator 2026-10-19; the annualized-yield floor it set at 2% was removed on 2026-11-03): the same cycle row carries the optional additive
object `strategies` from the same chain's put side (Yahoo option_chain().puts, Nasdaq US p_* fields, Nasdaq Nordic put rows; the same
provider, label and quote_basis): csp (cash-secured put: |delta| in rules.CONSERVATIVE_DELTA_BAND, nearest 0.20 first) and collar (long stock,
protective put |delta| nearest rules.PROTECTIVE_PUT_DELTA, the short call in the same band), each a block with rights_status, provider_id,
quote_basis and timestamp, or {"unavailable": reason} when a leg lacks its required quote side or a verifiable delta.
A cycle with no covered call but a real csp or collar block keeps suggestions == [] and strategies.cc = {"unavailable": reason}. Health stays call-based.

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
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import option_recommendation_rules as rules
import option_historical_volatility as history_vol
import option_delta_model as delta_math
import option_delta_side_model as side_math
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
MAX_HIGH_STRIKE_DELTA = 0.20  # the high-strike suggestion keeps the model assignment reference low
BALANCED_DELTA = 0.30
BALANCED_MONEYNESS = 1.05     # when a lower strike has no delta at all, about 5% out of the money
MIDDLE_DELTA = rules.MIDDLE_DELTA          # the middle tier sits between HIGH_STRIKE (<= 0.20) and BALANCED (0.30)
MIDDLE_MONEYNESS = rules.MIDDLE_MONEYNESS  # when the candidates between have no delta
TICK = 0.01
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
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _is_two_sided(bid: Any, ask: Any) -> bool:
    return _is_finite_positive(bid) and _is_finite_positive(ask) and bid <= ask


def _cent_exact(strike: Any) -> bool:
    """True when the strike is exactly representable with two decimals (15.5, 15.50, 15.5000, 0.07 yes; 15.505, 15.5049 no):
    the immutable reader formats money with two decimals, so only such a strike may be RECOMMENDED; nothing is ever rounded."""
    return _is_finite_positive(strike) and strike == round(strike, 2)


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


def _http_bytes(url: str, *, max_bytes: int | None = None, opener: Callable[..., Any] | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (InvestorIntelligence public observation)"})
    until = _request_until()
    with (opener or urllib.request.urlopen)(request, timeout=until - time.monotonic()) as response:  # noqa: S310 - fixed public hosts
        body = bytearray()
        while chunk := response.read(65536):  # a body that trickles is cut at the request's end, not only per read
            body += chunk
            if max_bytes is not None and len(body) > max_bytes:
                raise ValueError("PUBLIC_RESPONSE_SIZE_LIMIT")
            if time.monotonic() > until:
                raise TimeoutError("RESPONSE_BODY_DEADLINE")
        return bytes(body)


def http_json(url: str) -> Any:
    return json.loads(_http_bytes(url).decode("utf-8"))


class _HistoryRedirectDenied(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("PRICE_HISTORY_REDIRECT_DENIED")


def load_historical_volatility(symbol: str, currency: str, stamp: str) -> dict[str, Any] | None:
    """Reuse the existing Yahoo chart cache, else one bounded public daily-chart read.

    Raw bytes, adjusted-close identity and prior completed session dates are bound
    by the pure estimator. Never use an aggregate price-change field as history.
    """
    if currency not in ("USD", "SEK") or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,31}", symbol) or ".." in symbol:
        return None
    try:
        capture = rules.exchange_date(rules.parse_utc_instant(stamp), "STOCKHOLM" if currency == "SEK" else "US")
        source = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        root = ROOT / "data" / "cache"
        # Same four mirrored operand paths as serenity_calibration.cached_price_reader.
        for folder in (root / "yahoo/chart", root / "v3/yahoo/chart"):
            for filename in (symbol, symbol + ".json"):
                path = folder / filename
                try:
                    if any(part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction())
                           for part in (path, *path.parents)):
                        continue
                    if path.is_file() and path.stat().st_size <= 8 * 1024 * 1024:
                        value = history_vol.from_yahoo_chart(path.read_bytes(), symbol, currency, capture, source)
                        if value is not None:
                            return value
                except OSError:
                    continue
        end = int(datetime(capture.year, capture.month, capture.day, tzinfo=timezone.utc).timestamp())
        url = f"{source}?period1={end - 120 * 86400}&period2={end}&interval=1d&events=div%2Csplits&includeAdjustedClose=true"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _HistoryRedirectDenied())
        raw = _http_bytes(url, max_bytes=8 * 1024 * 1024, opener=opener.open)
        return history_vol.from_yahoo_chart(raw, symbol, currency, capture, url)
    except (OSError, ValueError, TypeError, OverflowError, TimeoutError):
        return None


def _checked_history(value: Any, ticker: str, currency: str, stamp: str) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        capture = rules.exchange_date(rules.parse_utc_instant(stamp), "STOCKHOLM" if currency == "SEK" else "US")
        return value if history_vol.valid_historical_volatility(value, ticker, currency, capture) else None
    except (TypeError, ValueError):
        return None


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


def _ranking_rows(rows: list[dict[str, Any]], spot: float, *, put: bool,
                  cent_exact_only: bool = True) -> list[dict[str, Any]]:
    """Contract/OTM/quote eligibility only; never prefilter by a strike-specific Greek."""
    return [row for row in rows if _is_finite_positive(row.get("strike"))
            and (row["strike"] < spot if put else row["strike"] > spot)
            and _is_two_sided(row.get("bid"), row.get("ask"))
            and (not cent_exact_only or _cent_exact(row["strike"]))]


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


def _quote_value(value: Any, parser: Callable[[Any], float | None] = _float) -> Any:
    """Normalize genuine absence, but retain malformed source values so selection cannot mistake them for absence."""
    if value is None or (isinstance(value, str) and value.strip() in ("", "-", "--", "N/A")):
        return None
    parsed = parser(value)
    return (None if parsed == 0 else parsed) if parsed is not None else value



def _suggestion(role: str, row: dict[str, Any], spot: float, dte: int) -> dict[str, Any]:
    days = rules.effective_days(dte)  # annualization never uses fewer than one day (DTE 0 is the expiry day)
    bid, ask = row["bid"], row["ask"]
    mid = (bid + ask) / 2 if ask is not None else None
    limit = side_math.limit_from_computed(row,spot,dte,put=False,buy=False)
    if limit is None:
        limit = _sell_limit(bid, ask)
    period_yield = limit / spot
    return {"role": role, "strike": row["strike"], "bid": bid, "ask": ask, "mid": mid, "limit_price": limit,
            "premium_per_contract": round(limit * 100, 2), "period_yield": round(period_yield, 6),
            "annualized_yield": round(period_yield * 365 / days, 6), "upside_to_strike": round(row["strike"] / spot - 1, 6),
            "delta": row.get("delta"), "delta_basis": row.get("delta_basis"), "iv": row.get("iv") or None, "oi": row.get("oi"), "volume": row.get("volume"),
            "spread_pct": round((ask - bid) / mid, 4) if mid is not None else None}


def covered_call_tiers(rows: list[dict[str, Any]], spot: float, dte: int, *,
                       cent_exact_only: bool = True, model: dict[str, Any] | None = None,
                       prepared: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """(suggestions, middle): the highest usable strike (HIGH_STRIKE; no yield floor), a balanced strike below it (BALANCED), and
    the optional MIDDLE strike strictly between the two (never padded, never a duplicate strike). Only out-of-the-money
    strikes with two-sided quotes qualify, and per-leg evidence supplies each delta.
    MAX_HIGH_STRIKE_DELTA is checked before rounding. Only cent-exact strikes are recommended;
    raw chain health is independent. DTE 0 annualizes over one day."""
    if dte < 0:
        return [], None
    days = rules.effective_days(dte)
    if prepared is not None:
        usable = prepared
    elif model is not None:
        raise ValueError("STAGE1F_PRODUCER_LEGACY_COMMON_SIGMA_MODEL_REJECTED")
    else:
        usable = side_math.calculate_side(rows, spot, dte, None, cent_exact_only=cent_exact_only)["computed"]
    if not usable:
        return [], None
    annual = lambda row: row["bid"] / spot * 365 / days  # noqa: E731 - compare quoted-side premium, not guaranteed proceeds
    high = [row for row in usable if row.get("delta_exact") is not None and row["delta_exact"] <= MAX_HIGH_STRIKE_DELTA]
    if not high:
        return [], None
    first = max(high, key=lambda row: row["strike"])
    suggestions = [_suggestion("HIGH_STRIKE", first, spot, dte)]
    lower = [row for row in usable if row["strike"] < first["strike"] and annual(row) > annual(first)]
    middle: dict[str, Any] | None = None
    if lower:
        second = min(lower, key=lambda row: abs(row["delta_exact"] - BALANCED_DELTA))
        suggestions.append(_suggestion("BALANCED", second, spot, dte))
        between = rules.pick_middle(lower, first["strike"], second["strike"], spot)
        if between is not None:
            middle = _suggestion("MIDDLE", between, spot, dte)
    return suggestions, middle


def covered_call_suggestions(rows: list[dict[str, Any]], spot: float, dte: int, *, cent_exact_only: bool = True,
                             model: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The HIGH_STRIKE and BALANCED suggestions of covered_call_tiers."""
    return covered_call_tiers(rows, spot, dte, cent_exact_only=cent_exact_only, model=model)[0]


# ---- V21 (operator 2026-10-19): cash-secured put and collar beside the covered call, conservative first ----------------------------------



def _sell_limit(bid: float, ask: float | None) -> float:
    """Midpoint rounded down to .01, then bounded without rounding the real quote boundary."""
    if ask is None:
        return bid
    mid = (Decimal(str(bid)) + Decimal(str(ask))) / 2
    rounded = float(mid.quantize(Decimal(str(TICK)), rounding=ROUND_FLOOR))
    return min(ask, max(bid, rounded))


def _buy_limit(bid: float | None, ask: float) -> float:
    """Midpoint rounded up to .01, then bounded without rounding the real quote boundary."""
    if bid is None:
        return ask
    mid = (Decimal(str(bid)) + Decimal(str(ask))) / 2
    rounded = float(mid.quantize(Decimal(str(TICK)), rounding=ROUND_CEILING))
    return max(bid, min(ask, rounded))


def _leg(row: dict[str, Any], limit: float) -> dict[str, Any]:
    """One quoted leg, kept small (the options object has a hard size cap): strike, bid, ask, limit and the absolute delta with its basis.
    The mid, spread and liquidity are not repeated; a reader derives the mid from bid and ask."""
    return {"strike": row["strike"], "bid": row["bid"], "ask": row["ask"], "limit_price": limit, "delta": row.get("delta"),
            "delta_basis": row.get("delta_basis")}


def _nearest(rows: list[dict[str, Any]], target: float) -> dict[str, Any]:
    return min(rows, key=lambda row: (abs(row["delta_exact"] - target), row["strike"]))


def _in_band(row: dict[str, Any], band: tuple[float, float]) -> bool:
    return row.get("delta_exact") is not None and band[0] - 1e-12 <= row["delta_exact"] <= band[1] + 1e-12


def _leg_quote_unavailable(rows: list[dict[str, Any]], spot: float, *, put: bool, buy: bool = False, cent_exact_only: bool = True) -> str | None:
    """Explain the first failed quote gate before testing delta, using only the eligible side of spot."""
    side = "賣權" if put else "買權"
    if not rows:
        return f"本次回應無該到期的{side}報價"
    otm = [row for row in rows if _is_finite_positive(row.get("strike"))
           and (row["strike"] < spot if put else row["strike"] > spot)]
    if not otm:
        return f"所選到期無有效履約價的價外{side}"
    exact = [row for row in otm if not cent_exact_only or _cent_exact(row["strike"])]
    if not exact:
        return f"所選到期價外{side}履約價含超過兩位小數，顯示無法如實呈現；不提供建議"
    if not any(_is_two_sided(row.get("bid"), row.get("ask")) for row in exact):
        if any((_is_finite_positive(row.get("bid")) and row.get("ask") in (None, 0))
               or (_is_finite_positive(row.get("ask")) and row.get("bid") in (None, 0)) for row in exact):
            return f"所選到期價外{side}僅有單邊報價，缺少買賣報價 IV 區間；不提供建議"
    required = "ask" if buy else "bid"
    executable = [row for row in exact if _is_finite_positive(row.get(required))]
    if not executable:
        return f"所選到期價外{side}缺少有效{'買入 Ask' if buy else '賣出 Bid'}（須為有限正數）"
    if not any(_is_two_sided(row.get("bid"), row.get("ask")) for row in executable):
        return f"所選到期價外{side}報價格式無效、非有限值、負值或買賣價倒掛"
    return None


def cash_secured_put_tiers(puts: list[dict[str, Any]], spot: float, dte: int, *,
                           cent_exact_only: bool = True, model: dict[str, Any] | None = None,
                           prepared: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Two-sided OTM puts in the full-precision conservative delta band; premiums remain quote-based."""
    if dte < 0:
        return [], "所選到期已過期，不提供現金擔保賣權建議"
    reason = _leg_quote_unavailable(puts, spot, put=True, cent_exact_only=cent_exact_only)
    if reason:
        return [], reason
    days = rules.effective_days(dte)
    if prepared is not None:
        usable = prepared
    elif model is not None:
        raise ValueError("STAGE1F_PRODUCER_LEGACY_COMMON_SIGMA_MODEL_REJECTED")
    else:
        analysis = side_math.calculate_side(puts, spot, dte, None, put=True)
        usable = analysis["computed"]
        if not usable and analysis["reason"]:
            return [], analysis["reason"]
    band = [row for row in usable if _in_band(row, rules.CONSERVATIVE_DELTA_BAND)]
    if not band:
        low, high = rules.CONSERVATIVE_DELTA_BAND
        return [], f"所選到期價外賣權中，沒有 delta 絕對值介於 {low:.2f}–{high:.2f} 的履約價"
    first = _nearest(band, rules.CONSERVATIVE_DELTA_BAND[0])
    chosen = [("CONSERVATIVE", first)]
    higher = [row for row in band if row["strike"] > first["strike"]]
    if higher:
        chosen.append(("BALANCED", _nearest(higher, rules.CONSERVATIVE_DELTA_BAND[1])))
    items = []
    for role, row in chosen:
        limit = side_math.limit_from_computed(row,spot,dte,put=True,buy=False)
        if limit is None:
            limit = _sell_limit(row["bid"], row["ask"])
        items.append({"role": role, **_leg(row, limit), "premium_per_contract": round(limit * 100, 2),
                      "cash_required": round(row["strike"] * 100, 2), "annualized_yield": round(limit / row["strike"] * 365 / days, 6),
                      "breakeven": round(row["strike"] - limit, 4), "downside_buffer": round(1 - row["strike"] / spot, 6)})
    return items, None


def collar_tiers(calls: list[dict[str, Any]], puts: list[dict[str, Any]], spot: float, dte: int, *,
                 cent_exact_only: bool = True, model: dict[str, Any] | None = None,
                 prepared_calls: list[dict[str, Any]] | None = None,
                 prepared_puts: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """({put, items}, reason): long stock + a protective put (absolute delta nearest PROTECTIVE_PUT_DELTA inside its window; buy limit = mid
    rounded up, never above the ask) + the short call in CONSERVATIVE_DELTA_BAND (the delta nearest the lower edge first, optional
    BALANCED nearest the upper edge). Every leg needs both quote sides and independently verified Delta; no yield floor."""
    if dte < 0:
        return None, "所選到期已過期，不提供領口策略建議"
    reason = _leg_quote_unavailable(puts, spot, put=True, buy=True, cent_exact_only=cent_exact_only)
    if reason:
        return None, reason
    window = rules.PROTECTIVE_PUT_DELTA_BAND
    if prepared_puts is not None:
        usable_puts = prepared_puts
    elif model is not None:
        raise ValueError("STAGE1F_PRODUCER_LEGACY_COMMON_SIGMA_MODEL_REJECTED")
    else:
        usable_puts = side_math.calculate_side(puts, spot, dte, None, put=True)["computed"]
    protective = [row for row in usable_puts if _in_band(row, window)]
    if not protective:
        return None, f"所選到期價外賣權中，沒有 delta 絕對值約 {rules.PROTECTIVE_PUT_DELTA:.2f}（{window[0]:.2f}–{window[1]:.2f}）的履約價"
    reason = _leg_quote_unavailable(calls, spot, put=False, cent_exact_only=cent_exact_only)
    if reason:
        return None, reason
    if prepared_calls is not None:
        usable_calls = prepared_calls
    elif model is not None:
        raise ValueError("STAGE1F_PRODUCER_LEGACY_COMMON_SIGMA_MODEL_REJECTED")
    else:
        usable_calls = side_math.calculate_side(calls, spot, dte, None)["computed"]
    band = [row for row in usable_calls if _in_band(row, rules.CONSERVATIVE_DELTA_BAND)]
    if not band:
        low, high = rules.CONSERVATIVE_DELTA_BAND
        return None, f"所選到期價外買權中，沒有 delta 介於 {low:.2f}–{high:.2f} 的履約價"
    put_row = _nearest(protective, rules.PROTECTIVE_PUT_DELTA)
    put_limit = side_math.limit_from_computed(put_row,spot,dte,put=True,buy=True)
    put_leg = _leg(put_row, put_limit if put_limit is not None else _buy_limit(put_row["bid"],put_row["ask"]))
    first = _nearest(band, rules.CONSERVATIVE_DELTA_BAND[0])
    chosen = [("CONSERVATIVE", first)]
    lower = [row for row in band if row["strike"] < first["strike"]]
    if lower:
        chosen.append(("BALANCED", _nearest(lower, rules.CONSERVATIVE_DELTA_BAND[1])))
    items = []
    for role, row in chosen:
        call_limit = side_math.limit_from_computed(row,spot,dte,put=False,buy=False)
        call_leg = _leg(row, call_limit if call_limit is not None else _sell_limit(row["bid"],row["ask"]))
        net = round(call_leg["limit_price"] - put_leg["limit_price"], 4)
        loss = round(spot - put_leg["strike"] - net, 4)
        gain = round(call_leg["strike"] - spot + net, 4)
        items.append({"role": role, "call": call_leg, "net_premium_per_share": net, "max_loss_per_share": loss, "max_gain_per_share": gain,
                      "break_even": round(spot - net, 4), "worst_case_net_per_share": round(call_leg["bid"] - put_leg["ask"], 4)})
    return {"put": put_leg, "items": items}, None


def strategy_blocks(calls: list[dict[str, Any]], puts: list[dict[str, Any]], spot: float, dte: int, label: dict[str, Any], *,
                    model: dict[str, Any] | None = None,
                    prepared_calls: list[dict[str, Any]] | None = None,
                    prepared_puts: list[dict[str, Any]] | None = None,
                    call_reason: str | None = None, put_reason: str | None = None) -> dict[str, Any]:
    """Stage 1E treats calls/puts independently; no shared IV intersection."""
    csp, csp_reason = cash_secured_put_tiers(puts, spot, dte, model=model, prepared=prepared_puts)
    collar, collar_reason = collar_tiers(calls, puts, spot, dte, model=model,
                                        prepared_calls=prepared_calls, prepared_puts=prepared_puts)
    if not csp and put_reason:
        csp_reason = put_reason
    if not collar and put_reason:
        collar_reason = put_reason
    elif not collar and call_reason and (not prepared_calls):
        collar_reason = call_reason
    return {"csp": {"suggestions": csp, **label} if csp else {"unavailable": _diag(csp_reason or "")},
            "collar": {**collar, **label} if collar else {"unavailable": _diag(collar_reason or "")}}


def _covered_call_unavailable(rows: list[dict[str, Any]], spot: float, dte: int, expiry: str, *,
                              model: dict[str, Any] | None, model_reason: str | None = None) -> str:
    """Explain a refused call using its actual quote and strategy evidence."""
    if dte < 0:
        return f"{expiry} 到期已過期，不提供備兌買權建議"
    if not rows:
        return f"{expiry} 到期未取得可核驗買權報價，不提供備兌買權建議"
    reason = _leg_quote_unavailable(rows, spot, put=False)
    if reason:
        # Keep the explicit quote-absence marker only for genuinely unusable quotes,
        # so carry-forward cannot hide a delta/OTM/contract refusal.
        suffix = (f"；{carry_forward.NO_TWO_SIDED_REASON}"
                  if not any(_is_two_sided(row.get("bid"), row.get("ask")) for row in rows) else "")
        return _diag(f"{expiry}：{reason}{suffix}")
    if model is None:
        return _diag(f"{expiry}：{model_reason or '缺少可核驗的共同 Delta 模型'}；不提供備兌買權建議")
    return f"{expiry} 到期的價外買權中，沒有 Delta 不超過 {MAX_HIGH_STRIKE_DELTA:.2f} 的履約價"


def cycle_result(ticker: str, expiry: str, dte: int, spot: float, rows: list[dict[str, Any]], *, currency: str, source: str,
                 provenance: str, rights: str, stamp: str, asof: str | None = None, week: str | None = None,
                 identity: dict[str, str] | None = None, puts: list[dict[str, Any]] | None = None,
                 monthly_rule: str | None = None, historical_volatility: dict[str, Any] | None = None) -> dict[str, Any]:
    """puts (V21): the same expiry's put rows when the source answered a put side (None: the response carried none, so no `strategies`)."""
    history = _checked_history(historical_volatility, ticker, currency, stamp)
    call_analysis = side_math.calculate_side(rows, spot, dte, history)
    put_analysis = side_math.calculate_side(puts or [], spot, dte, history, put=True)
    suggestions, middle = covered_call_tiers(rows, spot, dte, prepared=call_analysis["computed"])
    strategies: dict[str, Any] | None = None
    if puts is not None and identity is not None:
        label = {"rights_status": rights, "provider_id": identity["provider_id"],
                 "quote_basis": "delayed", "timestamp": stamp}
        strategies = strategy_blocks(
            rows, puts, spot, dte, label,
            prepared_calls=call_analysis["computed"], prepared_puts=put_analysis["computed"],
            call_reason=call_analysis["reason"], put_reason=put_analysis["reason"])
    cc_reason = ""
    if not suggestions:
        if call_analysis["computed"]:
            cc_reason = f"{expiry} 到期的價外買權中，沒有 Delta 不超過 {MAX_HIGH_STRIKE_DELTA:.2f} 的履約價"
        else:
            cc_reason = _covered_call_unavailable(
                rows, spot, dte, expiry, model=None,
                model_reason=call_analysis["reason"] or "本側缺少可核驗的有效雙邊期權腿")
        if strategies is None:
            return {"unavailable": cc_reason}
        if all("unavailable" in block for block in strategies.values()):
            reasons={"cc": _diag(cc_reason),
                     "csp": _diag(strategies["csp"]["unavailable"]),
                     "collar": _diag(strategies["collar"]["unavailable"])}
            # Do not truncate mid-phrase or insert put/collar diagnostics
            # into the CC block. The Worker renders all three exact strings.
            summary = "本到期日三種期權策略均未符合條件；各策略拒絕原因分別列示"
            return {"unavailable": summary, "strategy_reasons": reasons}

    def find_row(analysis: dict[str, Any], quoted: dict[str, Any]) -> dict[str, Any]:
        matches = [row for row in analysis["computed"] if
                   row["strike"] == quoted["strike"] and row["bid"] == quoted["bid"] and row["ask"] == quoted["ask"]]
        if len(matches) != 1:
            raise ValueError("STAGE1E_SELECTED_LEG_HAS_NO_UNIQUE_SOURCE")
        return matches[0]

    selected_calls = [find_row(call_analysis, item) for item in suggestions]
    if middle is not None:
        selected_calls.append(find_row(call_analysis, middle))
    selected_puts: list[dict[str, Any]] = []
    if strategies is not None:
        csp = strategies.get("csp", {})
        collar = strategies.get("collar", {})
        if "suggestions" in csp:
            selected_puts.extend(find_row(put_analysis, item) for item in csp["suggestions"])
        if "items" in collar:
            selected_puts.append(find_row(put_analysis, collar["put"]))
            selected_calls.extend(find_row(call_analysis, item["call"]) for item in collar["items"])
    model = side_math.cycle_model_wire(call_analysis, put_analysis, selected_calls, selected_puts)
    result = {"ticker": ticker, "strategy": "COVERED_CALL", "expiry": expiry, "dte": dte,
              "spot": spot, "currency": currency, "multiplier": 100, "quote_basis": "delayed",
              "timestamp": stamp, "source": source, "provenance": provenance, "rights_status": rights,
              "suggestions": suggestions, "delta_model": model}
    if strategies is not None:
        result["strategies"] = {"cc": {"unavailable": cc_reason}, **strategies} if not suggestions else strategies
    if identity is not None:
        result.update(identity)
    if middle is not None:
        result["middle_suggestion"] = middle
    if asof is not None:
        result["asof_date"] = asof
    if week is not None:
        result["weekly_week"] = week
    if monthly_rule is not None:
        result["monthly_rule"] = monthly_rule
    if history is not None:
        result["historical_volatility"] = history
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


def _monthly_choice(expiries: Iterable[str], today: date | None, stamp: str, venue: str,
                    verified_monthly_expiries: Iterable[date] = ()) -> "rules.MonthlyChoice | None":
    """Nearest standard expiry, with no DTE floor or quote-driven month substitution."""
    if today is None:
        return None
    days: set[date] = set()
    for text in expiries:
        try:
            days.add(date.fromisoformat(str(text)))
        except ValueError:
            continue
    return rules.select_monthly(days, today, expiry_day_open_now=rules.expiry_day_open(rules.parse_utc_instant(stamp), venue),
                                verified_monthly_expiries=verified_monthly_expiries)


def _is_actual_date(text: str) -> bool:
    try:
        return date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def _calendar_standard_monthlies(today: date, stamp: str, venue: str) -> list[tuple[str, int]]:
    """One bounded targeted fetch date; a calendar date alone never proves a listing."""
    for offset in range(4):
        year, month_zero = divmod(today.year * 12 + today.month - 1 + offset, 12)
        third = rules.third_friday(year, month_zero + 1)
        dte = (third - today).days
        if dte > 0 or (dte == 0 and rules.expiry_day_open(rules.parse_utc_instant(stamp), venue)):
            return [(third.isoformat(), dte)] if dte <= rules.MONTHLY_DTE_BUCKET[1] else []
    return []


def _monthly_candidates(expiries: Iterable[str], today: date | None, stamp: str, venue: str,
                        verified_monthly_expiries: Iterable[date] = ()) -> list["rules.MonthlyChoice"]:
    choice = _monthly_choice(expiries, today, stamp, venue, verified_monthly_expiries)
    return [choice] if choice else []


def _missing_monthly_date(today: date | None, stamp: str, venue: str) -> str:
    targets = _calendar_standard_monthlies(today, stamp, venue) if today is not None else []
    return f"最近標準月選 {targets[0][0]} 未取得可核驗合約資料" if targets else "最近標準月選未取得可核驗合約資料"


def _monthly_quote_observation(ticker: str, spot: float, choices: list["rules.MonthlyChoice"],
                               calls: list[dict[str, Any]], stamp: str, today: date, *,
                               currency: str, source: str, provenance: str, rights: str,
                               identity: dict[str, str] | None, cc_reason: str,
                               puts: list[dict[str, Any]] | None = None,
                               historical_volatility: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Observation-only quote when the call fails strike, delta or quote eligibility.
    The two-sided bid (not mid) defines annualized collectible premium; without it,
    a LAST quote is purely indicative. Neither lane qualifies as a recommendation."""
    if not _is_finite_positive(spot) or not choices:
        return None
    by_expiry = {choice.expiry.isoformat(): choice for choice in choices}
    available = [row for row in calls if row.get("expiry") in by_expiry and row.get("size") == 100
                 and _cent_exact(row.get("strike")) and row["strike"] > spot
                 and isinstance(row.get("dte"), int) and 0 <= row["dte"] <= 60]
    if not available:
        return None
    both = [row for row in available if _is_two_sided(row.get("bid"), row.get("ask"))]
    # The observation is *not* a tradeable tier: even a very wide spread can be shown with the explicit spread caveat.
    # Compare strikes only within the nearest standard expiry; never advance the month for a better quote.
    best = max(both, key=lambda row: row["bid"]/spot*365/rules.effective_days(row["dte"])) if both else None
    if best is None:
        with_last = [row for row in available if _is_finite_positive(row.get("last"))]
        best = max(with_last, key=lambda row: row["last"]/spot*365/rules.effective_days(row["dte"])) if with_last else min(
            available, key=lambda row: (row["dte"], row["strike"]))
    dte = best["dte"]
    is_both = best in both
    last = best.get("last") if _is_finite_positive(best.get("last")) else None
    annual = (best["bid"] if is_both else last)
    obs = {"kind": "TWO_SIDED" if is_both else "NO_TWO_SIDED",
           "strike": best["strike"],
           "bid": best["bid"] if is_both else None, "ask": best["ask"] if is_both else None,
           "last": last if not is_both else None,
           "annualized_yield": round(annual/spot*365/rules.effective_days(dte), 6) if annual is not None else None,
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
    # was missing quotes or strike/delta eligibility. Independently valid
    # put strategies from the same expiry retain their own source-backed evidence.
    same_calls = [r for r in calls if r.get("expiry") == best["expiry"] and r.get("size") == 100]
    same_puts = [r for r in (puts or []) if r.get("expiry") == best["expiry"] and r.get("size") == 100]
    if identity is not None and puts is not None:
        label = {"rights_status":rights,"provider_id":identity["provider_id"],
                 "quote_basis":"delayed","timestamp":stamp}
        history = _checked_history(historical_volatility, ticker, currency, stamp)
        # The observation path MUST recover independently valid CSP/collar legs
        # even when there is no eligible covered call. Stage1D incorrectly fed
        # both sides into a single unavailable candidate, losing put cards.
        call_side = side_math.calculate_side(same_calls, spot, dte, history)
        put_side = side_math.calculate_side(same_puts, spot, dte, history, put=True)
        blocks = strategy_blocks(same_calls, same_puts, spot, dte, label,
                                  prepared_calls=call_side["computed"],
                                  prepared_puts=put_side["computed"],
                                  call_reason=call_side["reason"], put_reason=put_side["reason"])
        selected_calls = []
        selected_puts = []
        if "suggestions" in blocks["csp"]:
            for item in blocks["csp"]["suggestions"]:
                selected_puts.extend(row for row in put_side["computed"]
                                     if row["strike"] == item["strike"]
                                     and row["bid"] == item["bid"] and row["ask"] == item["ask"])
        if "items" in blocks["collar"]:
            item_put = blocks["collar"]["put"]
            selected_puts.extend(row for row in put_side["computed"]
                                 if row["strike"] == item_put["strike"]
                                 and row["bid"] == item_put["bid"] and row["ask"] == item_put["ask"])
            for item in blocks["collar"]["items"]:
                cc = item["call"]
                selected_calls.extend(row for row in call_side["computed"]
                                      if row["strike"] == cc["strike"]
                                      and row["bid"] == cc["bid"] and row["ask"] == cc["ask"])
        if selected_calls or selected_puts:
            result["delta_model"] = side_math.cycle_model_wire(call_side, put_side,
                                                               selected_calls, selected_puts)
        if history is not None:
            result["historical_volatility"] = history
    else:
        reason = ("本輪來源未提供可核驗的賣權資料，無法判定賣權鏈是否缺漏" if puts is None
                  else "本輪來源缺少策略報價身分標記，無法核驗賣權策略")
        blocks = {name: {"unavailable": reason} for name in ("csp", "collar")}
    result["strategies"] = {"cc": {"unavailable": cc_reason}, **blocks}
    return result




def _cycles_from_calls(calls: list[dict[str, Any]], ticker: str, spot: float, stamp: str, *, currency: str, source: str,
                       provenance: str, rights: str, missing: str, venue: str = "US",
                       underlying: str | None = None,
                       no_window: Callable[[str, int, int], tuple[str, str]] | None = None,
                       today: date | None = None, week_expiries: Iterable[str] | None = None,
                       identity: dict[str, str] | None = None, puts: list[dict[str, Any]] | None = None,
                       verified_monthly_expiries: Iterable[date] = (),
                       historical_volatility: dict[str, Any] | None = None) -> CyclesResult:
    """Weekly: the current calendar week's earliest listed expiry (the next week's only when this week has none left; see
    option_recommendation_rules); monthly: the nearest standard monthly (shared rule). Standard 100-share contracts only.
    today is the exchange-local as-of date (derived from the rows' expiry and dte when absent); week_expiries lets the caller
    decide the week from every listed expiry, so a contract with refused terms is never silently skipped for the next week. A
    cycle without a qualifying expiry takes its reason and health status from no_window(cycle, low, high) when the caller
    proved more about its source than 'nothing listed'."""
    out: dict[str, Any] = {}
    health_records: list[dict[str, Any]] = []
    und = underlying or ticker
    history = _checked_history(historical_volatility, ticker, currency, stamp)
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
                week_expiries if week_expiries is not None else [row["expiry"] for row in calls + (puts or [])], today, stamp, venue,
                verified_monthly_expiries)
            monthly = monthly_choices[0] if monthly_choices else None
            monthly_rule = monthly.rule if monthly else None
            window = [row for row in calls if monthly and row["expiry"] == monthly.expiry.isoformat()
                      and row["strike"] and row["size"] == 100]
        if not window and cycle == "monthly" and monthly is not None and puts is not None:
            put_rows = [row for row in puts if row.get("expiry") == monthly.expiry.isoformat()
                        and row.get("size") == 100]
            if put_rows:
                only_put = cycle_result(ticker, monthly.expiry.isoformat(),
                    (monthly.expiry-today).days, spot, [], currency=currency, source=source,
                    provenance=provenance, rights=rights, stamp=stamp,
                    asof=today.isoformat(), identity=identity, puts=put_rows,
                    monthly_rule=monthly_rule, historical_volatility=history)
                out[cycle] = only_put
                health_records.append({"venue":venue,"underlying":und,"expiry":monthly.expiry.isoformat(),
                    "cycle":cycle,"status":"READ","read":True,
                    "two_sided":any(_is_two_sided(row.get("bid"), row.get("ask")) for row in put_rows)})
                continue
        if not window:
            message, status = no_window(cycle, low, high) if no_window else (_missing_text(missing, cycle, low, high), "NO_EXPIRY")
            if cycle == "monthly":
                expected = f"最近標準月選 {monthly.expiry.isoformat()} 未取得可核驗合約資料" if monthly else _missing_monthly_date(today, stamp, venue)
                message = f"{expected}；{message}"
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
        out[cycle] = cycle_result(ticker, chosen_expiry, target, spot, chosen, currency=currency, source=source,
                                  provenance=provenance, rights=rights, stamp=stamp,
                                  asof=today.isoformat() if today else None, week=week, identity=identity, puts=chosen_puts,
                                  monthly_rule=monthly_rule, historical_volatility=history)
        if cycle == "monthly" and monthly is not None and not out[cycle].get("suggestions"):
            blocks = out[cycle].get("strategies")
            cc_block = blocks.get("cc") if isinstance(blocks, dict) else None
            cc_reason = (cc_block.get("unavailable") if isinstance(cc_block, dict) else None
                         ) or out[cycle].get("strategy_reasons", {}).get("cc") or out[cycle].get("unavailable")
            observation = _monthly_quote_observation(
                ticker, spot, [monthly], calls, stamp, today, currency=currency, source=source,
                provenance=provenance, rights=rights, identity=identity, cc_reason=cc_reason, puts=puts,
                historical_volatility=history)
            if observation is not None:
                out[cycle] = observation
                health_records[-1]["two_sided"] = observation["quote_observation"]["kind"] == "TWO_SIDED"
    return CyclesResult(out, health=health_records)


def _nasdaq_us_asof(payload: Any) -> date | None:
    """Source-page observation day, not an option-leg clock or the caller's spot clock.
    Multiple supplied clocks must agree; a malformed clock cannot hide behind a valid one."""
    try:
        data = payload["data"]
        candidates = (data.get("lastTrade"), (data.get("table") or {}).get("asOf"))
        days: set[date] = set()
        for index, text in enumerate(candidates):
            if text is None or text == "":
                continue
            if not isinstance(text, str) or len(text) > 180:
                return None
            markers = re.findall(r"\bAS OF\b", text, re.IGNORECASE)
            if index == 0 and not markers and not re.match(r"^\d{4}-", text):
                continue  # A price-only lastTrade has no clock; table.asOf may still provide one.
            matches = list(_ASOF_RE.finditer(text))
            if len(matches) == 1 and len(markers) == 1:
                match = matches[0]
                month = _ASOF_MONTHS.get(match.group(1).upper())
                if month is None:
                    return None
                days.add(date(int(match.group(3)), month, int(match.group(2))))
            elif _is_actual_date(text):
                days.add(date.fromisoformat(text))
            else:
                return None
        return next(iter(days)) if len(days) == 1 else None
    except (KeyError, TypeError, ValueError, AttributeError):
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


def _monthly_refetch_failure(result: CyclesResult, today: date, stamp: str, venue: str) -> CyclesResult:
    """A failed bounded lookup proves neither absence nor a listing."""
    if "unavailable" in result.get("monthly", {}):
        result["monthly"] = {"unavailable": _diag(
            f"{_missing_monthly_date(today, stamp, venue)}；補查讀取失敗；是否上市未確認")}
        for health in result.health:
            if health["cycle"] == "monthly":
                health.update(status="READ_ERROR", read=False, two_sided=False)
    return result


def nasdaq_us_options(symbol: str, spot: float, today: date, stamp: str, *,
                      historical_volatility: dict[str, Any] | None = None) -> CyclesResult:
    """Fallback US chain from Nasdaq's public quote-page API; without quoted IV, only two-sided quotes can imply delta.
    Class shares use a dot there (BRK-B -> brk.b)."""
    low, high = min(window[0] for window in CYCLES.values()), max(window[1] for window in CYCLES.values())
    url = NASDAQ_US_CHAIN.format(symbol=urllib.parse.quote(symbol.replace("-", ".").lower()),
                                 start=(today + timedelta(days=low)).isoformat(), end=(today + timedelta(days=high)).isoformat())
    try:
        payload = http_json(url)
        rows = payload["data"]["table"]["rows"]
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ValueError("UNREADABLE_OPTION_ROWS")
    except Exception:
        err_health = [{"venue": "US", "underlying": symbol, "expiry": None, "cycle": c,
                       "status": "READ_ERROR", "read": False, "two_sided": False} for c in CYCLES]
        return CyclesResult({cycle: {"unavailable": "Nasdaq 期權鏈讀取失敗"} for cycle in CYCLES}, health=err_health)
    asof = _nasdaq_us_asof(payload)
    capture_day = rules.exchange_date(rules.parse_utc_instant(stamp), "US")
    if rows and (asof is None or asof > capture_day or not 0 <= (today - asof).days <= NASDAQ_US_MAX_ASOF_AGE_DAYS):
        stale_health = [{"venue": "US", "underlying": symbol, "expiry": None, "cycle": c,
                         "status": "STALE_ASOF", "read": False, "two_sided": False} for c in CYCLES]
        return CyclesResult({c: {"unavailable": NASDAQ_US_STALE_TEXT} for c in CYCLES}, health=stale_health)
    calls: list[dict[str, Any]] = []
    puts: list[dict[str, Any]] = []
    saw_put_side = False
    saw_source_rows = bool(rows)
    # Bind metadata to decoded contracts, not to whichever HTTP response happened last.
    source_dates: dict[str, str] = {}
    refetch_failed = False

    def decode_rows(source_rows: list, source_day: date | None, expected_expiry: str | None = None) -> None:
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
            if source_day is not None:
                source_dates[resolved.isoformat()] = source_day.isoformat()
            calls.append({"expiry": resolved.isoformat(), "dte": (resolved-today).days, "strike": strike,
                          "bid": _quote_value(row.get("c_Bid"), _nasdaq_us_quote), "ask": _quote_value(row.get("c_Ask"), _nasdaq_us_quote),
                          "last": _nasdaq_us_quote(row.get("c_Last")), "iv": None, "delta": None,
                          "oi": _int(row.get("c_Openinterest")), "volume": _int(row.get("c_Volume")), "size": 100})
            if any(key in row for key in ("p_Bid","p_Ask")):
                saw_put_side = True
                puts.append({"expiry": resolved.isoformat(), "dte": (resolved-today).days, "strike":strike,
                             "bid": _quote_value(row.get("p_Bid"), _nasdaq_us_quote), "ask": _quote_value(row.get("p_Ask"), _nasdaq_us_quote),
                             "iv": None, "oi": _int(row.get("p_Openinterest")),
                             "volume": _int(row.get("p_Volume")), "size": 100})
    decode_rows(rows, asof)
    # A broad response can omit the nearest standard; fetch that exact date once.
    # Only a typed contract with a valid source as-of can establish the listing.
    if not _monthly_candidates([row["expiry"] for row in calls+puts], today, stamp, "US"):
        for standard_day, _days in _calendar_standard_monthlies(today, stamp, "US"):
            if any(row["expiry"] == standard_day for row in calls+puts):
                break
            targeted = NASDAQ_US_CHAIN.format(
                symbol=urllib.parse.quote(symbol.replace("-", ".").lower()),
                start=standard_day,end=standard_day)
            try:
                response = http_json(targeted)
                source_rows = response["data"]["table"]["rows"]
                source_asof = _nasdaq_us_asof(response)
                # A correctly shaped, explicitly empty Nasdaq result is an
                # authoritative no-listing observation, NOT READ_ERROR.
                # Missing table/rows, a malformed scalar or transport errors
                # still raise and preserve the independent read-failure path.
                if source_rows is None:
                    source_rows = []
                if not isinstance(source_rows, list):
                    raise ValueError("UNREADABLE_TARGETED_OPTION_ROWS")
                saw_source_rows = saw_source_rows or bool(source_rows)
                if (source_asof is None or source_asof > capture_day
                        or not 0 <= (today-source_asof).days <= NASDAQ_US_MAX_ASOF_AGE_DAYS):
                    continue
                decode_rows(source_rows, source_asof, expected_expiry=standard_day)
            except (ValueError,TypeError,KeyError,AttributeError,OSError):
                refetch_failed = True
                continue
            if any(row["expiry"] == standard_day for row in calls+puts):
                break
    if not calls and not puts:
        health = [{"venue":"US","underlying":symbol,"expiry":None,"cycle":c,
                  "status":"SOURCE_ROWS_NOT_TYPED" if saw_source_rows else "EMPTY_RESPONSE","read":False,"two_sided":False} for c in CYCLES]
        msg = ("Nasdaq US 已回應鏈資料，但到期日／履約價／買賣欄位無法解析為經核驗標準契約（非證明未上市）"
               if saw_source_rows else "Nasdaq US 本次回應無期權鏈資料；是否上市未確認")
        result = CyclesResult({c:{"unavailable":
            _diag(f"{_missing_monthly_date(today, stamp, 'US')}；{msg}") if c == "monthly"
            else msg
            } for c in CYCLES},health=health)
        return _monthly_refetch_failure(result, today, stamp, "US") if refetch_failed else result
    result = _cycles_from_calls(calls, symbol, spot, stamp, currency="USD",
                              source="Nasdaq US option chain (public quote page API, delayed; Yahoo fallback)",
                              provenance=f"https://www.nasdaq.com/market-activity/stocks/{symbol.replace('-', '.').lower()}/option-chain",
                              rights=NASDAQ_US_RIGHTS_LABEL, missing="Nasdaq 無 {low}-{high} 天到期的上市期權",
                              venue="US", underlying=symbol, today=today, identity=NASDAQ_US_OPTION_IDENTITY,
                              puts=puts if saw_put_side else None, historical_volatility=historical_volatility)
    for cycle in result.values():
        if "unavailable" not in cycle and cycle.get("expiry") in source_dates:
            cycle["source_quote_date"] = source_dates[cycle["expiry"]]
    return _monthly_refetch_failure(result, today, stamp, "US") if refetch_failed else result


def _yahoo_unread(value: dict[str, Any] | None) -> bool:
    reason = str((value or {"unavailable": "讀取失敗"}).get("unavailable", ""))
    return ("讀取失敗" in reason or "Yahoo Finance 期權到期日清單" in reason
            or "標準月選鏈無可驗證合約資料" in reason)


def us_cycles(symbol: str, spot: float, today: date, stamp: str, *,
              historical_volatility: dict[str, Any] | None = None) -> CyclesResult:
    """Yahoo first; only unread cycles use Nasdaq's bounded source-specific lookup.
    Preserve the fallback's validated refusal (including stale/unconfirmed as-of);
    combine transport failures only when both providers actually failed to read."""
    try:
        out = us_options(symbol, spot, today, stamp, historical_volatility=historical_volatility)
    except Exception:
        out = CyclesResult({cycle: {"unavailable": "期權鏈讀取失敗"} for cycle in CYCLES},
                           health=[{"venue": "US", "underlying": symbol, "expiry": None, "cycle": c,
                                    "status": "READ_ERROR", "read": False, "two_sided": False} for c in CYCLES])
    yahoo_health = list(getattr(out, "health", []) or [])
    retry = [cycle for cycle in CYCLES if _yahoo_unread(out.get(cycle))]
    if not retry:
        return out if isinstance(out, CyclesResult) else CyclesResult(out, health=yahoo_health)
    fallback = nasdaq_us_options(symbol, spot, today, stamp, historical_volatility=historical_volatility)
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
    day = row.get("07. latest trading day")
    try:
        if not isinstance(day, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is None:
            return None
        date.fromisoformat(day)
    except ValueError:
        return None
    if not price or price <= 0:
        return None
    return {"symbol": symbol, "display": symbol, "price": price, "previous_close": previous,
            "change_pct": (price / previous - 1) if previous else None, "currency": "USD", "asof": day,
            "fetched_at": iso(utc_now()),
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
                out.append({"strike": float(strike), "bid": _quote_value(getattr(row, "bid", None)), "ask": _quote_value(getattr(row, "ask", None)),
                            "iv": _float(getattr(row, "impliedVolatility", None)), "oi": _int(getattr(row, "openInterest", None)),
                            "volume": _int(getattr(row, "volume", None))})
        return out
    except Exception:
        return None


def us_options(symbol: str, spot: float, today: date, stamp: str, *,
               historical_volatility: dict[str, Any] | None = None) -> CyclesResult:
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
            # Missing nearest standard: fetch only that expiry, never substitute a successor or weekly.
            if not monthly_choices:
                candidates = _calendar_standard_monthlies(today, stamp, "US")
            else:
                monthly_rule = monthly_choices[0].rule
        if not candidates:
            health_records.append({"venue": "US", "underlying": symbol, "expiry": None, "cycle": cycle,
                                   "status": "NO_EXPIRY", "read": False, "two_sided": False})
            out[cycle] = {"unavailable": _missing_text("無 {low}-{high} 天到期的上市期權（Yahoo Finance 期權到期日清單）", cycle, low, high)}
            continue
        if cycle == "monthly":
            # Read both sides of the binding nearest standard expiry.
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
                        "bid": _quote_value(getattr(call, "bid", None)), "ask": _quote_value(getattr(call, "ask", None)),
                        "last": _float(getattr(call, "lastPrice", None)), "iv": iv,
                        "oi": _int(getattr(call, "openInterest", None)),
                        "volume": _int(getattr(call, "volume", None)), "size": 100})
                puts = _yahoo_put_rows(option_chain)
                if puts is not None:
                    put_side_seen = True
                    all_puts.extend({**row, "expiry":month_expiry,"dte":month_dte,"size":100} for row in puts)
            if not all_calls and not all_puts:
                known_window = any(_is_actual_date(row) and
                    0 <= (date.fromisoformat(row)-today).days <= 60 for row in expiries)
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
                out["monthly"] = {"unavailable": f"{_missing_monthly_date(today, stamp, 'US')}；{reason}"}
                continue
            monthly_result=_cycles_from_calls(all_calls,symbol,spot,stamp,currency="USD",
                source="Yahoo Finance option chain (unofficial, delayed)",
                provenance=f"https://finance.yahoo.com/quote/{symbol}/options",
                rights=YAHOO_RIGHTS_LABEL,missing="Yahoo 交易所到期清單沒有最近標準月選",
                venue="US",underlying=symbol,today=today,
                week_expiries=sorted({row["expiry"] for row in all_calls + all_puts}),
                identity=YAHOO_OPTION_IDENTITY,puts=all_puts if put_side_seen else None,
                historical_volatility=historical_volatility)
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
            bid = _quote_value(getattr(row, "bid", None))
            ask = _quote_value(getattr(row, "ask", None))
            iv = _float(getattr(row, "impliedVolatility", None))
            oi = _int(getattr(row, "openInterest", None))
            vol = _int(getattr(row, "volume", None))
            if strike is not None and _is_finite_positive(strike):
                r_dict = {"strike": float(strike), "bid": bid, "ask": ask, "iv": iv,
                          "oi": oi, "volume": vol}
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
        out[cycle] = cycle_result(symbol, expiry, dte, spot, rows, currency="USD",
                                  source="Yahoo Finance option chain (unofficial, delayed)",
                                  provenance=f"https://finance.yahoo.com/quote/{symbol}/options?date={expiry}",
                                  rights=YAHOO_RIGHTS_LABEL, stamp=stamp, asof=today.isoformat(), week=week, identity=YAHOO_OPTION_IDENTITY,
                                  puts=put_rows, monthly_rule=monthly_rule, historical_volatility=historical_volatility)
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
_NORDIC_STRIKE_FIELD = re.compile(r"(?:" + _STRIKE_TEXT + r"|[1-9][0-9]{0,2},[0-9]{3}\.[0-9]{1,4})")
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


def _nordic_strike(value: Any) -> Decimal | None:
    """Exact bounded strike identity, NOT quote-price locale parsing. A grouped strike needs a dot decimal mark:
    1,460.00 is unambiguous; 1,460 alone could be a decimal comma and is refused. No float, rounding or excess precision."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value) if 0 < value < 1_000_000 else None
    if not isinstance(value, str) or len(value) > 12 or not _NORDIC_STRIKE_FIELD.fullmatch(value):
        return None
    strike = Decimal(value.replace(",", ""))
    return strike if strike > 0 else None


def _nordic_contract_identity(row: Any, *, put: bool = False) -> tuple[str, date, Decimal] | None:
    """Prove the row's own root/type/date/exact strike without inferring any root from the equity ticker."""
    if not isinstance(row, dict) or not isinstance(row.get("assetClass"), str) or row["assetClass"].strip().upper() != "OPTIONS":
        return None
    name = row.get("fullName")
    if not isinstance(name, str) or len(name) > 120:
        return None
    match = (_NORDIC_PUT_NAME if put else _NORDIC_CALL_NAME).fullmatch(name)
    if not match or match.group(3) not in _MONTH_NUMBER:
        return None
    strike = _nordic_strike(row.get("strikePrice"))
    if strike is None or strike != Decimal(match.group(5)):
        return None
    expiry_text = row.get("expirationDate")
    if not isinstance(expiry_text, str) or len(expiry_text) != 10:
        return None
    try:
        name_date = date(2000 + int(match.group(4)), _MONTH_NUMBER[match.group(3)], int(match.group(2)))
        expiry = date.fromisoformat(expiry_text)
    except ValueError:
        return None
    native_symbol = row.get("symbol")
    root = match.group(1)
    if expiry != name_date or not isinstance(native_symbol, str) or not _native_symbol_matches(native_symbol, root, expiry, strike, put=put):
        return None
    return root, expiry, strike


def _nordic_chain_root(rows: Iterable[Any]) -> str | None:
    """Return the sole root proven by complete call/put identities, or None for no proof or conflicting roots.
    Rows must come from the verified underlying orderbook; this helper does not establish that external binding.
    Non-options and malformed/unsupported identities (including adjusted -X series) cannot establish a root.
    Currency, size, quotes and expiry windows do not hide an otherwise proven conflicting root; their gates run later.
    Pass all rows from bounded responses together when checking a re-fetch. Never substitute an equity-ticker root."""
    root = None
    for row in rows:
        identity = _nordic_contract_identity(row) or _nordic_contract_identity(row, put=True)
        if identity is None:
            continue
        if root is not None and root != identity[0]:
            return None
        root = identity[0]
    return root


def _nordic_row_evidence(row: Any, root: str | None, today: date) -> tuple[str, dict[str, Any] | None]:
    """('IGNORE'|'MALFORMED'|'CALL', call). Full name, native symbol, date and strike must prove a call of the chain's
    verified root. None refuses every identity; a trailing 'C' alone (FUTC, futures or combinations) proves nothing."""
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
    identity = _nordic_contract_identity(row)
    if identity is None or identity[0] != root:
        return "MALFORMED", None
    _, expiry, strike_exact = identity
    return "CALL", {"expiry": row["expirationDate"], "dte": (expiry - today).days, "strike": float(strike_exact),
                    "ccy": _nordic_contract_currency(row.get("currency", _ABSENT)), "size": _typed_size(row.get("contractSize")),
                    "bid": _quote_value(row.get("bidPrice"), _nordic_price), "ask": _quote_value(row.get("askPrice"), _nordic_price),
                    "last": _nordic_price(row.get("lastPrice") or row.get("lastSalePrice")),
                    "oi": _int(row.get("openInterest")), "volume": _int(row.get("volume"))}


def _nordic_put_evidence(row: Any, root: str | None, today: date) -> str | dict[str, Any]:
    """V21: 'NONE' (not a put row), 'MALFORMED' (unproven identity or chain root), or the put dict.
    The same proof as a call, with the put name suffix P and the put series letters M..X."""
    if not isinstance(row, dict) or not isinstance(row.get("assetClass"),str) or row["assetClass"].strip().upper() != "OPTIONS":
        return "NONE"
    raw_name = row.get("fullName")
    if not isinstance(raw_name,str) or len(raw_name)>120:
        return "MALFORMED"
    name = raw_name
    if not name.endswith("P") or name.endswith("FUTP"):
        return "NONE"
    identity = _nordic_contract_identity(row, put=True)
    if identity is None or identity[0] != root:
        return "MALFORMED"
    _, expiry, strike_exact = identity
    return {"expiry": row["expirationDate"], "dte": (expiry - today).days, "strike": float(strike_exact),
            "ccy": _nordic_contract_currency(row.get("currency", _ABSENT)), "size": _typed_size(row.get("contractSize")),
            "bid": _quote_value(row.get("bidPrice"), _nordic_price), "ask": _quote_value(row.get("askPrice"), _nordic_price),
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


def _nordic_x_refusals(result: CyclesResult, rows: list[Any], listed: list[dict[str, Any]], root: str | None,
                        spot: float, today: date, stamp: str) -> CyclesResult:
    """Diagnose terminal-X calls only; never use stripped identities for root proof or selection."""
    if root is None and any(_nordic_contract_identity(row) or _nordic_contract_identity(row, put=True) for row in rows):
        return result  # Conflicting proved roots retain their identity refusal.
    x_dates: set[str] = set()
    for row in rows:
        native = row.get("symbol") if isinstance(row, dict) else None
        if not isinstance(native, str) or not native.endswith("X"):
            continue
        identity = _nordic_contract_identity({**row, "symbol": native[:-1]})
        if identity is not None and (root is None or identity[0] == root) and float(identity[2]) > spot:
            x_dates.add(identity[1].isoformat())
    x_dates.difference_update(call["expiry"] for call in listed if call["strike"] > spot)
    dates = x_dates | {call["expiry"] for call in listed}
    reason = "價外買權僅有原生代號帶X之系列，未核驗是否為調整後系列；不提供建議"
    for period, cycle in result.items():
        choice = (_weekly_choice(dates, today, stamp, "STOCKHOLM") if period == "weekly"
                  else _monthly_choice(dates, today, stamp, "STOCKHOLM"))
        if choice is None or choice.expiry.isoformat() not in x_dates or cycle.get("suggestions"):
            continue
        if "unavailable" in cycle:
            cycle["unavailable"] = reason
        elif isinstance(cycle.get("strategies"), dict):
            cycle["strategies"]["cc"] = {"unavailable": reason}
            if "unavailable" in cycle["strategies"].get("collar", {}):
                cycle["strategies"]["collar"] = {"unavailable": reason}
    return result


def nordic_options(symbol: str, base: str, spot: float, today: date, stamp: str, orderbook: str | None = None,
                   *, spot_currency: Any = None, historical_volatility: dict[str, Any] | None = None) -> CyclesResult:
    """Stockholm covered calls. Every claim rests on typed source evidence: the underlying's quote currency (spot_currency,
    and the search result's share currency when the search ran) and each CONTRACT's own currency and size must all be the
    canonical SEK / 100 before a strategy is offered; an unknown or conflicting term is a source-scoped unavailable reason,
    never a SEK recommendation that merely ends in .ST."""
    native = base.replace("-", " ")  # VOLV-B is listed as "VOLV B"
    share_currency: Any = _NO_SEARCH
    try:
        if not orderbook:
            groups = http_json(NORDIC_SEARCH.format(symbol=urllib.parse.quote(native)))["data"] or []
            share = next(item for group in groups for item in group["instruments"]
                         if item.get("assetClass") == "SHARES" and item.get("symbol", "").upper() == native.upper())
            orderbook = share["orderbookId"]
            share_currency = share.get("currency")
        response = http_json(NORDIC_CHAIN.format(orderbook=orderbook))
        rows = response["data"]["instrumentListing"]["rows"]
    except StopIteration:
        return _nordic_unavailable(symbol, "UNDERLYING_NOT_FOUND", "Nasdaq Nordic 回應未找到可核驗標的股票商品；是否上市未確認")
    except Exception:
        return _nordic_unavailable(symbol, "READ_ERROR", "Nasdaq Nordic 期權鏈讀取或解析失敗")
    message = response.get("messages")
    if isinstance(message, dict) and message.get("code") == "NO_INST_FOUND":
        if rows is None or rows == []:
            return _nordic_unavailable(symbol, "NO_INST_FOUND", "Nasdaq Nordic 回應查無此標的期權商品；是否上市未確認")
        return _nordic_unavailable(symbol, "READ_ERROR", "Nasdaq Nordic 回應狀態與期權鏈內容矛盾，無法核驗")
    if not isinstance(rows, list):
        return _nordic_unavailable(symbol, "READ_ERROR", "Nasdaq Nordic 期權鏈回應格式無效（讀取或解析失敗）")
    states = [_typed_currency(spot_currency)] + ([] if share_currency is _NO_SEARCH else [_typed_currency(share_currency)])
    if "CONFLICT" in states:
        return _nordic_unavailable(symbol, "UNDERLYING_CURRENCY_CONFLICT", "標的報價或上市幣別與 SEK 不符；不推薦")
    if any(state != "OK" for state in states):
        return _nordic_unavailable(symbol, "UNDERLYING_CURRENCY_UNCONFIRMED", "標的報價或上市幣別未確認為 SEK；不推薦")
    monthly_refetched = False
    refetch_failed = False
    if not rows:
        monthly_refetched = True
        try:
            refreshed_response=http_json(NORDIC_CHAIN.format(orderbook=orderbook))
            refreshed=refreshed_response["data"]["instrumentListing"]["rows"]
            if (refreshed is None and isinstance(refreshed_response.get("messages"),dict)
                    and refreshed_response["messages"].get("code")=="NO_INST_FOUND"):
                refreshed=[]
            if not isinstance(refreshed, list):
                raise ValueError("UNREADABLE_TARGETED_OPTION_ROWS")
            rows = refreshed
        except (TypeError, ValueError, KeyError, AttributeError, OSError):
            refetch_failed = True
        if not rows:
            result = _nordic_unavailable(symbol, "EMPTY_RESPONSE", "本次來源回應無可用之買權紀錄；是否上市未確認")
            result["monthly"]["unavailable"] = _diag(f"{_missing_monthly_date(today, stamp, 'STOCKHOLM')}；{result['monthly']['unavailable']}")
            return _monthly_refetch_failure(result, today, stamp, "STOCKHOLM") if refetch_failed else result
    root = _nordic_chain_root(rows)
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
            result = _nordic_unavailable(symbol, "MALFORMED_ROWS",
                "Nasdaq Nordic 已回應買權列，但合約名稱／原生代號／履約價與到期日未能同時核驗；未解析者不可推定未上市")
            return _nordic_x_refusals(result, rows, listed, root, spot, today, stamp)
        return _nordic_unavailable(symbol, "NO_EXPIRY", "本次來源回應無可用之買權紀錄；是否上市未確認")
    # The Nordic endpoint has no per-expiry parameter. Re-read once for the exact
    # nearest standard date; failure never authorizes a weekly or a later month.
    standard_targets={iso for iso,_ in _calendar_standard_monthlies(today, stamp, "STOCKHOLM")}
    if not monthly_refetched and standard_targets and not _monthly_candidates([x["expiry"] for x in listed],today,stamp,"STOCKHOLM"):
        try:
            refreshed_response=http_json(NORDIC_CHAIN.format(orderbook=orderbook))
            refreshed=refreshed_response["data"]["instrumentListing"]["rows"]
            if (refreshed is None and isinstance(refreshed_response.get("messages"),dict)
                    and refreshed_response["messages"].get("code")=="NO_INST_FOUND"):
                refreshed=[]
            if not isinstance(refreshed, list):
                raise ValueError("UNREADABLE_TARGETED_OPTION_ROWS")
            if _nordic_chain_root(row for batch in (rows, refreshed) for row in batch) != root:
                return _nordic_unavailable(symbol, "MALFORMED_ROWS",
                    "Nasdaq Nordic 有互相衝突之合約根代號；同一標的訂單簿的跨次鏈回應未能同時核驗")
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
            rows = [*rows, *refreshed]
        except (TypeError,ValueError,KeyError,AttributeError,OSError):
            refetch_failed = True

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
    result = _cycles_from_calls(usable, symbol, spot, stamp, currency=SEK, source=NORDIC_SOURCE,
                              provenance=NORDIC_CHAIN.format(orderbook=orderbook), rights=NORDIC_RIGHTS_LABEL,
                              missing="", venue="STOCKHOLM", underlying=symbol, no_window=no_window, today=today,
                              week_expiries=[call["expiry"] for call in listed], identity=NORDIC_OPTION_IDENTITY,
                              puts=usable_puts if saw_put_side else None, historical_volatility=historical_volatility)
    result = _nordic_x_refusals(result, rows, listed, root, spot, today, stamp)
    return _monthly_refetch_failure(result, today, stamp, "STOCKHOLM") if refetch_failed else result


def _yahoo_regular_market_time(value: Any) -> str | None:
    """Yahoo's regularMarketTime is epoch seconds, not a fetch time or a scheduled session boundary."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    try:
        return iso(datetime.fromtimestamp(value, timezone.utc))
    except (ValueError, OverflowError, OSError):
        return None


def observe(symbol: str, today: date, stamp: str, orderbook: str | None = None) -> Observation | None:
    """One underlying: the delayed quote and, for US and Stockholm listings, its covered-call cycles. Options keys never
    collide across markets: US listings by their Yahoo symbol (class shares use "-": BRK-B; dotted symbols are other
    markets such as 2330.TW), Stockholm listings with the suffix (SIVE.ST, VOLV-B.ST, AZN.ST next to the US AZN)."""
    import yfinance as yf
    price = previous = None
    currency = asof = None
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price, previous = _float(info.get("lastPrice")), _float(info.get("previousClose"))
        currency = info.get("currency")
        try:
            # fast_info has no observation clock. Its history metadata carries the regular-market
            # price/time pair; never attach that clock to a different fast_info lastPrice.
            metadata = ticker.get_history_metadata()
            regular_price = _float(metadata.get("regularMarketPrice"))
            if regular_price and regular_price > 0:
                price = regular_price
                currency = metadata.get("currency") or currency
                asof = _yahoo_regular_market_time(metadata.get("regularMarketTime"))
        except Exception:
            pass  # A usable fast_info price survives with an explicitly unknown observation time.
    except Exception:
        price = None
    base = symbol.split(".")[0] if symbol.endswith(".ST") else symbol
    if price:
        quote = {"symbol": symbol, "display": base, "price": price, "previous_close": previous,
                 "change_pct": (price / previous - 1) if previous else None, "currency": currency,
                 "asof": asof, "fetched_at": iso(utc_now()), "source": "Yahoo Finance (unofficial, delayed)",
                 "source_url": f"https://finance.yahoo.com/quote/{symbol}"}
    else:
        fallback = alpha_vantage_quote(symbol, stamp) if "." not in symbol else None  # US listings only
        if not fallback:
            return None
        quote, price = fallback, fallback["price"]
    try:
        if "." not in symbol:
            history = load_historical_volatility(symbol, quote.get("currency"), stamp)
            cycles = us_cycles(symbol, price, today, stamp, historical_volatility=history)
            return Observation(quote, symbol, cycles)
        if symbol.endswith(".ST"):
            history = load_historical_volatility(symbol, quote.get("currency"), stamp)
            cycles = nordic_options(symbol, base, price, today, stamp, orderbook, spot_currency=quote.get("currency"),
                                    historical_volatility=history)
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
