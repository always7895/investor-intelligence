#!/usr/bin/env python3
"""Delayed daily prices for every listing the stock lookup can resolve (operator 2026-09-26: global lookups such as
川湖 must show information, not only the Top20 universe). Official bulk feeds, one request per market:

- US: Nasdaq stock screener download (Nasdaq, NYSE and NYSE American listings; last sale, change; "asOf" date);
- Taiwan: TWSE STOCK_DAY_ALL and TPEx mainboard daily close quotes (closing price, change, trade date);
- Sweden: Nasdaq Nordic share screener, Stockholm Main Market and First North (last sale, change; no trade date in
  the feed, so the retrieval date is shown as such);
- Euronext: Paris, Amsterdam, Brussels and Milan equities download (closing price and its date).
- Japan and Korea (no free official bulk price file): Yahoo Finance daily closes for the common stocks in the identity
  shards, batched, at most once per --yahoo-every-hours (default 20); labelled unofficial, with each row's own date.

Output data/cache/price_shards_latest.json: {"schema": "v213-price-shard-v1", "generated_at", "shards": {MARKET: {"schema",
"market", "generated_at", "sources": [{id, url, retrieved_at, sha256, rows}], "rows": {KEY: [price, change_pct|null,
asof, currency, source_index]}}}}; KEY is the identity symbol (EUROPE: "VENUE|SYMBOL"). A feed that fails leaves its
market out (the previous file keeps serving until the whole build succeeds); nothing is estimated.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import io
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "cache" / "price_shards_latest.json"
IDENTITY = ROOT / "data" / "cache" / "identity_shards_latest.json"
YAHOO_URL = "https://finance.yahoo.com/"
YAHOO_MARKETS = {"JAPAN": {"TSE": "T"}, "KOREA": {"KRX": "KS", "KOSDAQ": "KQ"}}
YAHOO_MINIMUM = {"JAPAN": 2000, "KOREA": 1200}
YAHOO_BATCH = 400
SCHEMA = "v213-price-shard-v1"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InvestorIntelligence public price directory"
FEEDS = {
    "nasdaq-us-screener": ("US", "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"),
    "twse-day-all": ("TAIWAN", "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"),
    "tpex-daily-close": ("TAIWAN", "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"),
    "nasdaq-stockholm-main": ("SWEDEN", "https://api.nasdaq.com/api/nordic/screener/shares?category=MAIN_MARKET&tableonly=false&market=STO"),
    "nasdaq-stockholm-first-north": ("SWEDEN", "https://api.nasdaq.com/api/nordic/screener/shares?category=FIRST_NORTH&tableonly=false&market=STO"),
    "euronext-equities": ("EUROPE", "https://live.euronext.com/en/pd_es/data/stocks/download?mics=dm_all_stock&initialLetter=&fe_type=csv&fe_decimal_separator=.&fe_date_format=d%2Fm%2FY"),
}
# The download omits its price date; the one-row table call states it ("Last price as of Sep 24, 2026").
US_ASOF_URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=1"
MINIMUM_ROWS = {"nasdaq-us-screener": 3000, "twse-day-all": 800, "tpex-daily-close": 600, "nasdaq-stockholm-main": 250,
                "nasdaq-stockholm-first-north": 150, "euronext-equities": 800}
EURONEXT_VENUES = {"Euronext Paris": "EURONEXT PARIS", "Euronext Growth Paris": "EURONEXT PARIS", "Euronext Amsterdam": "EURONEXT AMSTERDAM",
                   "Euronext Brussels": "EURONEXT BRUSSELS", "Euronext Growth Brussels": "EURONEXT BRUSSELS", "Euronext Milan": "BORSA ITALIANA",
                   "Euronext Growth Milan": "BORSA ITALIANA"}
MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}

Fetch = Callable[[str], bytes]


class PriceShardError(RuntimeError):
    pass


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/csv, */*"})
    for attempt in range(3):  # TPEx sometimes closes a 4 MB response early
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - fixed public HTTPS feeds
                return response.read()
        except http.client.IncompleteRead:
            if attempt == 2:
                raise
            time.sleep(3)
    raise AssertionError("unreachable")


def number(value: Any) -> float | None:
    text = str(value if value is not None else "").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        result = float(text)
    except ValueError:
        return None
    return result if result == result and abs(result) != float("inf") else None


def roc_date(value: str) -> str | None:
    """TWSE/TPEx trade date 1150924 (ROC year 115) -> 2026-09-24."""
    match = re.fullmatch(r"(\d{2,3})(\d{2})(\d{2})", str(value or "").strip())
    return f"{int(match.group(1)) + 1911:04d}-{match.group(2)}-{match.group(3)}" if match else None


def pct_from_change(close: float | None, change: float | None) -> float | None:
    if close is None or change is None or close - change <= 0:
        return None
    return round(change / (close - change) * 100, 3)


def stated_date(text: str) -> str | None:
    match = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})", str(text or ""))
    return f"{match.group(3)}-{MONTHS[match.group(1)]:02d}-{int(match.group(2)):02d}" if match and match.group(1) in MONTHS else None


def parse_feed(feed: str, raw: bytes, retrieved: str, asof_hint: str | None = None) -> dict[str, list[Any]]:
    """{key: [price, change_pct, asof, currency]} for one feed; asof is null when the feed states no price date (the
    reader then shows the retrieval time instead)."""
    rows: dict[str, list[Any]] = {}
    if feed == "nasdaq-us-screener":
        data = json.loads(raw.decode("utf-8"))["data"]
        asof = stated_date(data.get("asOf") or data.get("asof") or "") or asof_hint
        for row in data["rows"]:
            symbol = str(row.get("symbol") or "").strip().upper().replace("/", ".").replace("^", "-")
            price = number(row.get("lastsale"))
            if symbol and price and price > 0:
                rows[symbol] = [price, number(row.get("pctchange")), asof, "USD"]
    elif feed == "twse-day-all":
        for row in json.loads(raw.decode("utf-8")):
            close, change = number(row.get("ClosingPrice")), number(row.get("Change"))
            if row.get("Code") and close and close > 0:
                rows[str(row["Code"]).strip()] = [close, pct_from_change(close, change), roc_date(row.get("Date")), "TWD"]
    elif feed == "tpex-daily-close":
        for row in json.loads(raw.decode("utf-8")):
            close, change = number(row.get("Close")), number(row.get("Change"))
            if row.get("SecuritiesCompanyCode") and close and close > 0:
                rows[str(row["SecuritiesCompanyCode"]).strip()] = [close, pct_from_change(close, change), roc_date(row.get("Date")), "TWD"]
    elif feed.startswith("nasdaq-stockholm"):
        for row in json.loads(raw.decode("utf-8"))["data"]["instrumentListing"]["rows"]:
            symbol, price = str(row.get("symbol") or "").strip().upper(), number(row.get("lastSalePrice"))
            if symbol and price and price > 0 and str(row.get("assetClass") or "SHARES").upper() == "SHARES":
                rows[symbol] = [price, number(row.get("percentageChange")), None, str(row.get("currency") or "SEK")]
    elif feed == "euronext-equities":
        for row in csv.reader(io.StringIO(raw.decode("utf-8-sig", "replace")), delimiter=";"):
            if len(row) < 15 or row[3] not in EURONEXT_VENUES:
                continue
            price = number(row[13]) or number(row[8])
            day = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", row[14].strip()[:10])
            if row[2].strip() and price and price > 0:
                rows[f"{EURONEXT_VENUES[row[3]]}|{row[2].strip().upper()}"] = [
                    price, None, f"{day.group(3)}-{day.group(2)}-{day.group(1)}" if day else None, row[4].strip() or "EUR"]
    return rows


def build(fetch: Fetch = http_get, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    shards: dict[str, dict[str, Any]] = {}
    failed: list[str] = []
    for feed, (market, url) in FEEDS.items():
        try:
            raw = fetch(url)
            hint = None
            if feed == "nasdaq-us-screener":
                try:
                    hint = stated_date(json.loads(fetch(US_ASOF_URL).decode("utf-8"))["data"].get("asof") or "")
                except Exception:  # noqa: BLE001 - without a stated date the reader shows the retrieval time
                    hint = None
            parsed = parse_feed(feed, raw, stamp, hint)
        except Exception as error:  # noqa: BLE001 - one market failing must not remove the others
            failed.append(f"{feed}:{type(error).__name__}")
            continue
        if len(parsed) < MINIMUM_ROWS[feed]:
            failed.append(f"{feed}:TOO_SMALL:{len(parsed)}")
            continue
        shard = shards.setdefault(market, {"schema": SCHEMA, "market": market, "generated_at": stamp, "sources": [], "rows": {}})
        index = len(shard["sources"])
        shard["sources"].append({"id": feed, "url": url, "retrieved_at": stamp, "sha256": hashlib.sha256(raw).hexdigest(), "rows": len(parsed)})
        for key, row in parsed.items():
            shard["rows"].setdefault(key, [*row, index])
    # A market with one of two feeds missing (Taiwan, Sweden) is dropped rather than published half empty.
    for feed in failed:
        market = FEEDS[feed.split(":", 1)[0]][0]
        shards.pop(market, None)
    if not shards:
        raise PriceShardError("PRICE_FEEDS_ALL_FAILED " + ",".join(failed))
    return {"schema": SCHEMA, "generated_at": stamp, "failed": failed, "shards": shards}


def yahoo_symbols(identity: Path = IDENTITY) -> dict[str, dict[str, str]]:
    """{market: {yahoo_symbol: identity_symbol}} for the common stocks of the Yahoo-priced markets."""
    document = json.loads(identity.read_bytes().decode("utf-8"))
    out: dict[str, dict[str, str]] = {market: {} for market in YAHOO_MARKETS}
    for shard in document["symbol_shards"].values():
        for row in shard["rows"]:
            suffix = YAHOO_MARKETS.get(row[2], {}).get(row[1])
            if suffix and row[6] == "COMMON_STOCK":
                out[row[2]][f"{row[0]}.{suffix}"] = row[0]
    return out


def yahoo_shard(market: str, symbols: dict[str, str], now: datetime, download: Callable[..., Any] | None = None) -> dict[str, Any] | None:
    """Daily closes in batches; a row carries its own last trade date and the change from the prior close."""
    if download is None:
        import yfinance as yf
        download = yf.download
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    currency = "JPY" if market == "JAPAN" else "KRW"
    rows: dict[str, list[Any]] = {}
    names = sorted(symbols)
    for start in range(0, len(names), YAHOO_BATCH):
        batch = names[start:start + YAHOO_BATCH]
        try:
            data = download(batch, period="7d", interval="1d", group_by="column", threads=True, progress=False, auto_adjust=False)
            close = data["Close"]
        except Exception:  # noqa: BLE001 - a failed batch leaves those rows out
            continue
        for yahoo in batch:
            if yahoo not in getattr(close, "columns", []):
                continue
            series = close[yahoo].dropna()
            if series.empty or not float(series.iloc[-1]) > 0:
                continue
            last = float(series.iloc[-1])
            prior = float(series.iloc[-2]) if len(series) > 1 else None
            rows[symbols[yahoo]] = [round(last, 4), round((last / prior - 1) * 100, 3) if prior else None,
                                    str(series.index[-1].date()), currency, 0]
    if len(rows) < YAHOO_MINIMUM[market]:
        return None
    return {"schema": SCHEMA, "market": market, "generated_at": stamp,
            "sources": [{"id": "yahoo-daily-close", "url": YAHOO_URL, "retrieved_at": stamp, "sha256": hashlib.sha256(
                json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest(), "rows": len(rows)}], "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    parser.add_argument("--yahoo-every-hours", type=float, default=20.0)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    previous: dict[str, Any] | None = None
    try:
        previous = json.loads(args.output.read_bytes().decode("utf-8"))
        age = (now - datetime.strptime(previous["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
    except (OSError, ValueError, KeyError, TypeError):
        age = None
    if age is not None and age < args.if_older_than_hours:
        print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age, 1)}))
        return 0
    try:
        document = build(now=now)
    except PriceShardError as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}))
        return 1
    # Japan and Korea at most once per --yahoo-every-hours; a younger previous shard is kept as it is.
    try:
        wanted = yahoo_symbols()
    except (OSError, ValueError, KeyError, TypeError):
        wanted = {}
    for market, symbols in wanted.items():
        kept = ((previous or {}).get("shards") or {}).get(market)
        try:
            kept_age = (now - datetime.strptime(kept["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
        except (TypeError, KeyError, ValueError):
            kept_age = None
        if kept_age is not None and kept_age < args.yahoo_every_hours:
            continue
        shard = yahoo_shard(market, symbols, now)
        if shard:
            document["shards"][market] = shard
        else:
            document["failed"].append(f"yahoo-{market.lower()}:TOO_SMALL")
    # A market whose feed failed this run keeps its previous shard (with its own, older generated_at).
    for market, shard in ((previous or {}).get("shards") or {}).items():
        document["shards"].setdefault(market, shard)
    largest = max(len(json.dumps(shard, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) for shard in document["shards"].values())
    if largest > 1_900_000:
        print(json.dumps({"status": "FAILED", "error": f"PRICE_SHARD_TOO_LARGE {largest}"}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_name(args.output.name + ".tmp")
    temp.write_bytes(json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    temp.replace(args.output)
    print(json.dumps({"status": "OK", "markets": {m: len(s["rows"]) for m, s in document["shards"].items()},
                      "failed": document["failed"], "largest_shard_bytes": largest}))
    return 0 if not document["failed"] else 2


if __name__ == "__main__":
    sys.exit(main())
