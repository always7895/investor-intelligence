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
- HIGH_STRIKE: the highest out-of-the-money strike whose bid still pays at least MIN_ANNUALIZED_YIELD (and, when a delta
  is available, delta <= MAX_HIGH_STRIKE_DELTA); strikes with a spread wider than the mid are ignored;
- BALANCED: a lower strike nearest delta BALANCED_DELTA (or BALANCED_MONEYNESS without a delta) for more premium.
Each carries a sell limit (mid rounded down to the tick, or bid + a quarter of the spread when the spread exceeds 25% of
the mid; never below the bid), premium per contract, period and
annualized yield on the current price, the upside kept up to the strike, delta as the assignment reference, OI, volume
and spread. Delta is Black-Scholes from the quoted implied volatility (a labelled model Greek); prices are never
modelled. A cycle without two-sided quotes stays unavailable with its reason.

Output: data/cache/market_quotes_options.json. Observation only; nothing here is an order.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "cache" / "market_quotes_options.json"
BROAD = ROOT / "data" / "cache" / "options_universe.json"
V3 = ROOT / "data" / "cache" / "bottleneck_top20_v3.json"
LAYERS = ROOT / "config" / "bottleneck-layers-v3.json"
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
US_LARGEST = 100              # by market cap (floor about $166B on 2026-09-26); share classes each keep their own chain
BROAD_MAX_AGE_HOURS = 24
BROAD_MAX_STALE_DAYS = 7
WORKERS = 4
CYCLES = {"weekly": (3, 14), "monthly": (15, 60)}  # monthly: the expiry nearest 30 days
RISK_FREE = 0.04
MIN_ANNUALIZED_YIELD = 0.06   # premium worth collecting versus cash (annualized, on the current price)
MAX_HIGH_STRIKE_DELTA = 0.20  # the high-strike suggestion keeps the model assignment reference low
BALANCED_DELTA = 0.30
BALANCED_MONEYNESS = 1.05     # without a delta (Nasdaq Stockholm), about 5% out of the money
TICK = 0.01
MAX_SPREAD_PCT = 1.0          # a spread wider than the mid is not a tradeable quote
WIDE_SPREAD_PCT = 0.25        # beyond this the limit moves from the mid towards the bid


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def http_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (InvestorIntelligence public observation)"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed public hosts
        return json.loads(response.read().decode("utf-8"))


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
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(WORKERS) as pool:
        listed = list(pool.map(lambda row: _has_listed_options(row["orderbookId"]), shares))
    if sum(1 for ok in listed if ok is None) * 10 > len(shares):
        raise ValueError("BROAD_OPTION_CHECK_FAILED")  # more than 10% unreadable: keep the previous list instead
    sweden = {str(row["symbol"]).strip().upper().replace(" ", "-") + ".ST": row["orderbookId"] for row, ok in zip(shares, listed) if ok}
    if len(us) < US_LARGEST // 2 or not sweden:
        raise ValueError("BROAD_UNIVERSE_TOO_SMALL")
    return {"schema": "v213-options-universe-v1", "generated_at": iso(now), "us": us, "sweden": sweden,
            "sources": [US_SCREENER, STOCKHOLM_LARGE_CAP, NORDIC_CHAIN]}


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


def bs_call_delta(spot: float, strike: float, years: float, vol: float | None) -> float | None:
    if not vol or vol <= 0 or years <= 0 or spot <= 0 or strike <= 0:
        return None
    d1 = (math.log(spot / strike) + (RISK_FREE + vol * vol / 2) * years) / (vol * math.sqrt(years))
    return round(0.5 * (1 + math.erf(d1 / math.sqrt(2))), 3)


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
            "delta": row.get("delta"), "iv": row.get("iv"), "oi": row.get("oi"), "volume": row.get("volume"),
            "spread_pct": round((ask - bid) / mid, 4) if mid > 0 else None}


def covered_call_suggestions(rows: list[dict[str, Any]], spot: float, dte: int) -> list[dict[str, Any]]:
    """Up to two sell-call suggestions for a holder of 100 shares: the highest strike still worth selling, then a
    balanced strike below it. Only out-of-the-money strikes with a two-sided quote qualify."""
    usable = [row for row in rows if row.get("strike") and row["strike"] > spot and row.get("bid") and row.get("ask")
              and row["ask"] >= row["bid"] > 0 and (row["ask"] - row["bid"]) / ((row["ask"] + row["bid"]) / 2) <= MAX_SPREAD_PCT]
    if not usable or dte <= 0:
        return []
    annual = lambda row: row["bid"] / spot * 365 / dte  # noqa: E731 - on the bid: premium that is actually collectable
    high = [row for row in usable if annual(row) >= MIN_ANNUALIZED_YIELD
            and (row.get("delta") is None or row["delta"] <= MAX_HIGH_STRIKE_DELTA)]
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
        return {"unavailable": f"{expiry} 到期的價外買權中，沒有年化權利金達 {MIN_ANNUALIZED_YIELD:.0%} 且有雙邊報價的履約價"}
    return {"ticker": ticker, "strategy": "COVERED_CALL", "expiry": expiry, "dte": dte, "spot": spot, "currency": currency,
            "multiplier": 100, "quote_basis": "delayed", "timestamp": stamp, "source": source, "provenance": provenance,
            "rights_status": rights, "suggestions": suggestions}


def _cycles_from_calls(calls: list[dict[str, Any]], ticker: str, spot: float, stamp: str, *, currency: str, source: str,
                       provenance: str, rights: str, missing: str) -> dict[str, Any]:
    """Weekly: the nearest expiry in its window; monthly: the expiry nearest 30 days. Standard 100-share contracts only."""
    out: dict[str, Any] = {}
    for cycle, (low, high) in CYCLES.items():
        window = [row for row in calls if low <= row["dte"] <= high and row["strike"] and row["size"] == 100]
        if not window:
            out[cycle] = {"unavailable": missing.format(low=low, high=high)}
            continue
        target = min(row["dte"] for row in window) if cycle == "weekly" else min({row["dte"] for row in window}, key=lambda days: abs(days - 30))
        chosen = [row for row in window if row["dte"] == target]
        out[cycle] = cycle_result(ticker, chosen[0]["expiry"], target, spot, chosen, currency=currency, source=source,
                                  provenance=provenance, rights=rights, stamp=stamp)
    return out


def nasdaq_us_options(symbol: str, spot: float, today: date, stamp: str) -> dict[str, Any]:
    """Fallback US chain from Nasdaq's public quote-page API: two-sided call quotes without implied volatility, so no
    delta (as for Nasdaq Stockholm). Class shares use a dot there (BRK-B -> brk.b)."""
    low, high = min(window[0] for window in CYCLES.values()), max(window[1] for window in CYCLES.values())
    url = NASDAQ_US_CHAIN.format(symbol=urllib.parse.quote(symbol.replace("-", ".").lower()),
                                 start=(today + timedelta(days=low)).isoformat(), end=(today + timedelta(days=high)).isoformat())
    try:
        rows = http_json(url)["data"]["table"]["rows"] or []
    except Exception:
        return {cycle: {"unavailable": "Nasdaq 期權鏈讀取失敗"} for cycle in CYCLES}
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
                              rights="candidate_local_review", missing="Nasdaq 無 {low}-{high} 天到期的上市期權")


def _yahoo_unread(value: dict[str, Any] | None) -> bool:
    reason = str((value or {"unavailable": "讀取失敗"}).get("unavailable", ""))
    return "讀取失敗" in reason or "Yahoo Finance 期權到期日清單" in reason


def us_cycles(symbol: str, spot: float, today: date, stamp: str) -> dict[str, Any]:
    """Yahoo first; only the cycles Yahoo could not read (no expiry list, a failed chain) try the Nasdaq chain once.
    A cycle Yahoo read without a qualifying strike keeps that reason."""
    try:
        out = us_options(symbol, spot, today, stamp)
    except Exception:
        out = {cycle: {"unavailable": "期權鏈讀取失敗"} for cycle in CYCLES}
    retry = [cycle for cycle in CYCLES if _yahoo_unread(out.get(cycle))]
    if not retry:
        return out
    fallback = nasdaq_us_options(symbol, spot, today, stamp)
    for cycle in retry:
        value = fallback.get(cycle) or {"unavailable": ""}
        if "unavailable" not in value:
            out[cycle] = value
        elif "讀取失敗" in str((out.get(cycle) or {}).get("unavailable", "讀取失敗")):
            out[cycle] = {"unavailable": "期權鏈讀取失敗（Yahoo 與 Nasdaq 備援）"}
        else:
            out[cycle] = {"unavailable": str(value["unavailable"])}
    return out


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


def us_options(symbol: str, spot: float, today: date, stamp: str) -> dict[str, Any]:
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    out: dict[str, Any] = {}
    try:
        expiries = list(ticker.options or [])
    except Exception:
        expiries = []
    for cycle, (low, high) in CYCLES.items():
        candidates = [(expiry, (date.fromisoformat(expiry) - today).days) for expiry in expiries]
        candidates = [item for item in candidates if low <= item[1] <= high]
        if not candidates:
            out[cycle] = {"unavailable": f"無 {low}-{high} 天到期的上市期權（Yahoo Finance 期權到期日清單）"}
            continue
        expiry, dte = min(candidates, key=lambda item: item[1]) if cycle == "weekly" else min(candidates, key=lambda item: abs(item[1] - 30))
        try:
            chain = ticker.option_chain(expiry).calls
        except Exception:
            out[cycle] = {"unavailable": "期權鏈讀取失敗"}
            continue
        rows = []
        for row in chain.itertuples():
            iv = _float(row.impliedVolatility)
            rows.append({"strike": float(row.strike), "bid": _float(row.bid), "ask": _float(row.ask), "iv": iv,
                         "delta": bs_call_delta(spot, float(row.strike), dte / 365, iv), "oi": _int(row.openInterest),
                         "volume": _int(row.volume)})
        out[cycle] = cycle_result(symbol, expiry, dte, spot, rows, currency="USD",
                                  source="Yahoo Finance option chain (unofficial, delayed)",
                                  provenance=f"https://finance.yahoo.com/quote/{symbol}/options?date={expiry}; delta=Black-Scholes(quoted IV)",
                                  rights="unadmitted_third_party", stamp=stamp)
    return out


def nordic_options(symbol: str, base: str, spot: float, today: date, stamp: str, orderbook: str | None = None) -> dict[str, Any]:
    native = base.replace("-", " ")  # VOLV-B is listed as "VOLV B"
    try:
        if not orderbook:
            groups = http_json(NORDIC_SEARCH.format(symbol=urllib.parse.quote(native)))["data"] or []
            orderbook = next(item["orderbookId"] for group in groups for item in group["instruments"]
                             if item.get("assetClass") == "SHARES" and item.get("symbol", "").upper() == native.upper())
        rows = http_json(NORDIC_CHAIN.format(orderbook=orderbook))["data"]["instrumentListing"]["rows"]
    except Exception:
        return {cycle: {"unavailable": "Nasdaq Nordic 期權鏈讀取失敗"} for cycle in CYCLES}
    calls = []
    for row in rows:
        name = str(row.get("fullName") or "")
        # Futures ("VOLVB 16OCT26 FUTC") and combinations share the chain; only options are calls here.
        if not name.endswith("C") or row.get("assetClass") not in (None, "", "OPTIONS"):
            continue
        expiry = str(row.get("expirationDate") or "")
        try:
            dte = (date.fromisoformat(expiry) - today).days
        except ValueError:
            continue
        calls.append({"expiry": expiry, "dte": dte, "strike": _float(row.get("strikePrice")), "bid": _float(row.get("bidPrice")),
                      "ask": _float(row.get("askPrice")), "oi": _int(row.get("openInterest")), "volume": _int(row.get("volume")),
                      "size": _int(row.get("contractSize"))})
    return _cycles_from_calls(calls, base, spot, stamp, currency="SEK",
                              source="Nasdaq Nordic option chain (exchange public web API, delayed)",
                              provenance=NORDIC_CHAIN.format(orderbook=orderbook), rights="candidate_local_review",
                              missing="Nasdaq Stockholm 無 {low}-{high} 天到期的上市期權")


def observe(symbol: str, today: date, stamp: str, orderbook: str | None = None) -> tuple[dict[str, Any], str, dict[str, Any]] | None:
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
            return quote, symbol, us_cycles(symbol, price, today, stamp)
        if symbol.endswith(".ST"):
            return quote, symbol, nordic_options(symbol, base, price, today, stamp, orderbook)
    except Exception:  # one malformed chain never aborts the other underlyings
        return quote, symbol, {cycle: {"unavailable": "期權鏈讀取失敗"} for cycle in CYCLES}
    return quote, symbol, {}


def _observe_safely(symbol: str, today: date, stamp: str, orderbook: str | None) -> tuple[dict[str, Any], str, dict[str, Any]] | None:
    try:
        return observe(symbol, today, stamp, orderbook)
    except Exception:
        return None


def build(now: datetime) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor
    stamp = iso(now)
    today = now.date()
    broad = broad_universe(now)
    orderbooks: dict[str, str] = dict(broad.get("sweden") or {})
    symbols = list(dict.fromkeys(universe() + list(broad.get("us") or []) + list(orderbooks)))
    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(lambda symbol: _observe_safely(symbol, today, stamp, orderbooks.get(symbol)), symbols))
    quotes: dict[str, Any] = {}
    options: dict[str, Any] = {}
    for symbol, result in zip(symbols, results):
        if result is None:
            continue
        quote, key, cycles = result
        quotes[symbol] = quote
        if cycles:
            options[key] = cycles
    return {"schema": "v213-market-observations-v2", "generated_at": stamp, "quotes": quotes, "options": options,
            "note": "Delayed public observations; not an order, not a recommendation to trade."}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    now = utc_now()
    if args.if_older_than_hours > 0 and args.output.exists():
        try:
            previous = json.loads(args.output.read_text(encoding="utf-8"))
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
    if len(document["quotes"]) < 10:
        print(json.dumps({"status": "FAILED", "error": "TOO_FEW_QUOTES", "quotes": len(document["quotes"])}))
        return 1
    temp = args.output.with_name(args.output.name + ".tmp")
    temp.write_bytes(json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    temp.replace(args.output)
    available = sum(1 for cycles in document["options"].values() for value in cycles.values() if "unavailable" not in value)
    print(json.dumps({"status": "OK", "quotes": len(document["quotes"]), "option_underlyings": len(document["options"]),
                      "option_observations": available, "sive": document["options"].get("SIVE.ST")}, ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
