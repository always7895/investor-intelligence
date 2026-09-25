#!/usr/bin/env python3
"""Quotes and listed-option observations for the watch universe (LINE stock lookup and options queries).

Universe: the bottleneck Top20 v3 (top and watch), the carried seven-field Top20 and every layer capturer.
- Quotes: Yahoo Finance last price, previous close and currency (unofficial, delayed; labelled).
- US-listed options: Yahoo Finance option chains (unofficial, delayed).
- Nasdaq Stockholm options (for example SIVE): the exchange's public option-chain API (api.nasdaq.com/api/nordic).
Per underlying and cycle (weekly 3-14 DTE, monthly 21-45 DTE) one observation: the call nearest 10% out of the
money with a two-sided bid/ask. Delta, when shown, is Black-Scholes from the quoted implied volatility and is labelled
as a model Greek; prices are never modelled. A cycle without a two-sided quote stays unavailable with its reason.

Output: data/cache/market_quotes_options.json. Observation only; nothing here is an order.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "cache" / "market_quotes_options.json"
V3 = ROOT / "data" / "cache" / "bottleneck_top20_v3.json"
LAYERS = ROOT / "config" / "bottleneck-layers-v3.json"
TOP20 = ROOT / "data" / "cache" / "top20-lkg"
NORDIC_SEARCH = "https://api.nasdaq.com/api/nordic/search?searchText={symbol}"
NORDIC_CHAIN = "https://api.nasdaq.com/api/nordic/instruments/{orderbook}/option-chain"
CYCLES = {"weekly": (3, 14), "monthly": (21, 45)}
TARGET_MONEYNESS = 1.10
RISK_FREE = 0.04


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
        newest = sorted(TOP20.glob("*.json"))[-1] if TOP20.exists() else None
        if newest and newest.name != "refresh-state.json":
            bundle = json.loads(newest.read_text(encoding="utf-8"))
            symbols += [row["ticker"] for row in json.loads(bundle["payloads"]["top20_json"])]
    except (OSError, ValueError, KeyError, IndexError):
        pass
    seen: dict[str, None] = {}
    for symbol in symbols:
        seen.setdefault(str(symbol).upper(), None)
    return list(seen)


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


def observation(ticker: str, expiry: str, dte: int, strike: float, bid: float, ask: float, *, delta: float | None, iv: float | None,
                oi: int | None, volume: int | None, currency: str, source: str, provenance: str, rights: str, stamp: str) -> dict[str, Any]:
    mid = round((bid + ask) / 2, 4)
    spread = round(ask - bid, 4)
    return {"ticker": ticker, "expiry": expiry, "dte": dte, "strike": strike, "type": "call", "bid": bid, "mid": mid, "ask": ask,
            "spread": spread, "delta": delta, "iv": iv, "oi": oi, "volume": volume, "breakeven": None, "maxprofit": None,
            "maxloss": None, "annualized_yield": None,
            "assignment_risk": "美式期權可能提前指派；賣出買權者在股價高於履約價時可能被指派。",
            "liquidity_warning": ("買賣價差占中價 {:.0%}，成交可能明顯偏離中價。".format(spread / mid) if mid > 0 and spread / mid > 0.10
                                  else "買賣價差在中價 10% 以內；仍不保證成交。"),
            "timestamp": stamp, "quote_basis": "delayed", "source": source, "provenance": provenance, "currency": currency,
            "multiplier": 100, "rights_status": rights}


def pick(rows: list[dict[str, Any]], spot: float) -> dict[str, Any] | None:
    """The two-sided out-of-the-money call nearest the 10% target."""
    usable = [row for row in rows if row["strike"] >= spot and row["bid"] and row["ask"] and row["ask"] >= row["bid"] > 0]
    return min(usable, key=lambda row: abs(row["strike"] / spot - TARGET_MONEYNESS)) if usable else None


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
        expiry, dte = min(candidates, key=lambda item: item[1]) if cycle == "weekly" else max(candidates, key=lambda item: item[1])
        try:
            chain = ticker.option_chain(expiry).calls
        except Exception:
            out[cycle] = {"unavailable": "期權鏈讀取失敗"}
            continue
        rows = [{"strike": float(row.strike), "bid": _float(row.bid), "ask": _float(row.ask), "iv": _float(row.impliedVolatility),
                 "oi": _int(row.openInterest), "volume": _int(row.volume)} for row in chain.itertuples()]
        best = pick(rows, spot)
        if not best:
            out[cycle] = {"unavailable": "無雙邊報價的價外買權"}
            continue
        out[cycle] = observation(symbol, expiry, dte, best["strike"], best["bid"], best["ask"],
                                 delta=bs_call_delta(spot, best["strike"], dte / 365, best["iv"]), iv=best["iv"], oi=best["oi"],
                                 volume=best["volume"], currency="USD", source="Yahoo Finance option chain (unofficial, delayed)",
                                 provenance=f"https://finance.yahoo.com/quote/{symbol}/options?date={expiry}; delta=Black-Scholes(quoted IV)",
                                 rights="unadmitted_third_party", stamp=stamp)
    return out


def nordic_options(symbol: str, base: str, spot: float, today: date, stamp: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        groups = http_json(NORDIC_SEARCH.format(symbol=base))["data"] or []
        orderbook = next(item["orderbookId"] for group in groups for item in group["instruments"]
                         if item.get("assetClass") == "SHARES" and item.get("symbol", "").upper() == base.upper())
        rows = http_json(NORDIC_CHAIN.format(orderbook=orderbook))["data"]["instrumentListing"]["rows"]
    except Exception:
        return {cycle: {"unavailable": "Nasdaq Nordic 期權鏈讀取失敗"} for cycle in CYCLES}
    calls = []
    for row in rows:
        name = str(row.get("fullName") or "")
        if not name.endswith("C"):
            continue
        expiry = str(row.get("expirationDate") or "")
        try:
            dte = (date.fromisoformat(expiry) - today).days
        except ValueError:
            continue
        calls.append({"expiry": expiry, "dte": dte, "strike": _float(row.get("strikePrice")), "bid": _float(row.get("bidPrice")),
                      "ask": _float(row.get("askPrice")), "oi": _int(row.get("openInterest")), "volume": _int(row.get("volume")),
                      "size": _int(row.get("contractSize"))})
    for cycle, (low, high) in CYCLES.items():
        window = [row for row in calls if low <= row["dte"] <= high and row["strike"] and row["size"] == 100]
        if not window:
            out[cycle] = {"unavailable": f"Nasdaq Stockholm 無 {low}-{high} 天到期的上市期權"}
            continue
        target = min(row["dte"] for row in window) if cycle == "weekly" else max(row["dte"] for row in window)
        best = pick([row for row in window if row["dte"] == target], spot)
        if not best:
            out[cycle] = {"unavailable": "無雙邊報價的價外買權"}
            continue
        out[cycle] = observation(base, best["expiry"], best["dte"], best["strike"], best["bid"], best["ask"], delta=None, iv=None,
                                 oi=best["oi"], volume=best["volume"], currency="SEK",
                                 source="Nasdaq Nordic option chain (exchange public web API, delayed)",
                                 provenance=NORDIC_CHAIN.format(orderbook=orderbook), rights="candidate_local_review", stamp=stamp)
    return out


def build(now: datetime) -> dict[str, Any]:
    import yfinance as yf
    stamp = iso(now)
    today = now.date()
    quotes: dict[str, Any] = {}
    options: dict[str, Any] = {}
    for symbol in universe():
        try:
            info = yf.Ticker(symbol).fast_info
            price, previous = _float(info.get("lastPrice")), _float(info.get("previousClose"))
            currency = info.get("currency")
        except Exception:
            continue
        if not price:
            continue
        base = symbol.split(".")[0] if symbol.endswith(".ST") else symbol
        quotes[symbol] = {"symbol": symbol, "display": base, "price": price, "previous_close": previous,
                          "change_pct": (price / previous - 1) if previous else None, "currency": currency,
                          "asof": stamp, "source": "Yahoo Finance (unofficial, delayed)", "source_url": f"https://finance.yahoo.com/quote/{symbol}"}
        if "." not in symbol:
            options[symbol] = us_options(symbol, price, today, stamp)
        elif symbol.endswith(".ST"):
            options[base] = nordic_options(symbol, base, price, today, stamp)
            time.sleep(1)
    return {"schema": "v213-market-observations-v1", "generated_at": stamp, "quotes": quotes, "options": options,
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
                      "option_observations": available, "sive": document["options"].get("SIVE")}, ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
