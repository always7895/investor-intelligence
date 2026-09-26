#!/usr/bin/env python3
"""Bottleneck-explosion Top20 v3 and the Leopold-led industry ranking (operator request 2026-09-26).

Universe: companies named in a scarce layer of config/bottleneck-layers-v3.json, plus Serenity and Leopold leads
that belong to one of those layers. Leads (Serenity posts, 13F positions) weight conviction but are never company
facts; every figure a user sees comes from filings or market data fetched here, with source and date:

- fundamentals: SEC XBRL companyfacts for SEC filers (us-gaap or ifrs-full revenue, gross profit, remaining
  performance obligations, shares outstanding); Yahoo Finance quarterly statements otherwise (labelled unofficial);
- market: Yahoo Finance adjusted daily closes (6M, 1Y, 2Y CAGR), market capitalisation converted to USD;
- current-events momentum: SEC EDGAR full-text search hits for each layer's terms in filings of the last 30 days
  versus the 60 days before (official, free; GDELT refused automated access).

Company score (0-100), by Serenity's two archetypes:
- COMPOUNDER (market cap >= $10B): layer heat 25 + company capture 30 + lead conviction 20 + market confirmation 15
  + size 10;
- EXPLOSION (< $10B, often qualifying before volume revenue): layer heat 25 + capture 15 + lead 30 + confirmation 20
  + size 10;
minus dilution/financing penalties. Hard filters: a positive long-term return (2-year CAGR, or 1 year when the history
is shorter), no clearly bearish Serenity stance, market data present. At most MAX_PER_LAYER names per layer.

Industry ranking (Leopold-led): each layer's position on the compute -> power -> datacenter -> chips -> memory ->
optics chain, the fund's 13F weight in the layer, capturer revenue acceleration and news momentum.

Usage: bottleneck_top20_v3.py [--if-older-than-hours H] [--output PATH] [--no-news]   (SEC contact from env)
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

LAYERS = ROOT / "config" / "bottleneck-layers-v3.json"
SERENITY = ROOT / "data" / "cache" / "serenity_signals_latest.json"
LEOPOLD = ROOT / "data" / "cache" / "leopold_positions_latest.json"
TICKERS = ROOT / "data" / "cache" / "v21" / "company_tickers_exchange.json"
CACHE = ROOT / "data" / "cache" / "v3"
OUTPUT = ROOT / "data" / "cache" / "bottleneck_top20_v3.json"
COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
EFTS = "https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt={start}&enddt={end}"
REVENUE_TAGS = [("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"), ("us-gaap", "SalesRevenueNet"),
                ("ifrs-full", "Revenue")]
GROSS_TAGS = [("us-gaap", "GrossProfit"), ("ifrs-full", "GrossProfit")]
COST_TAGS = [("us-gaap", "CostOfRevenue"), ("us-gaap", "CostOfGoodsAndServicesSold"), ("ifrs-full", "CostOfSales")]
RPO_TAGS = [("us-gaap", "RevenueRemainingPerformanceObligation")]
SHARES_TAGS = [("dei", "EntityCommonStockSharesOutstanding")]
SERENITY_LEAD_LIMIT = 80
TOP_N = 20
MAX_PER_LAYER = 5
EXPLOSION_CAP_USD = 10e9


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def clip(value: float | None, low: float, high: float) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def load_json(path: Path) -> Any:
    return json.loads(path.read_bytes().decode("utf-8"))


# ---------------------------------------------------------------- SEC XBRL
def sec_fetch_factory() -> Callable[[str], bytes]:
    from sec_contact_headers import sec_identity_headers
    headers = sec_identity_headers()

    def fetch(url: str) -> bytes:
        time.sleep(0.15)
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310 - fixed SEC host
            return response.read()
    return fetch


def cik_index() -> dict[str, int]:
    document = load_json(TICKERS)
    fields = document["fields"]
    return {str(dict(zip(fields, row))["ticker"]).upper(): int(dict(zip(fields, row))["cik"]) for row in document["data"]}


def companyfacts(cik: int, fetch: Callable[[str], bytes] | None, max_age_hours: float = 20) -> dict[str, Any] | None:
    path = CACHE / "companyfacts" / f"CIK{cik:010d}.json"
    if path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        return load_json(path)
    if fetch is None:
        return load_json(path) if path.exists() else None
    try:
        raw = fetch(COMPANYFACTS.format(cik=cik))
    except Exception:
        return load_json(path) if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return json.loads(raw.decode("utf-8"))


def _quarter_series(facts: dict[str, Any], tags: list[tuple[str, str]]) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """Quarter-length duration facts (80-100 days, any fiscal calendar) of the tag with the most recent quarter,
    keyed by period end date; the latest filing wins for a restated period. SEC frames are not used because many
    recent fiscal quarters carry no frame."""
    best: tuple[str, str | None, dict[str, dict[str, Any]]] = ("", None, {})
    for taxonomy, tag in tags:
        units = facts.get("facts", {}).get(taxonomy, {}).get(tag, {}).get("units", {})
        for unit, rows in units.items():
            series: dict[str, dict[str, Any]] = {}
            nine_month: dict[str, dict[str, Any]] = {}
            annual: list[dict[str, Any]] = []
            for row in rows:
                try:
                    days = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
                except (KeyError, ValueError):
                    continue
                if row.get("val") is None:
                    continue
                if 80 <= days <= 100:
                    previous = series.get(row["end"])
                    if previous is None or str(row.get("filed", "")) >= str(previous.get("filed", "")):
                        series[row["end"]] = {**row, "unit": unit}
                elif 260 <= days <= 285:
                    nine_month[row["start"]] = row
                elif 350 <= days <= 380:
                    annual.append(row)
            # Fourth fiscal quarters are often filed only inside the annual figure: annual minus nine-month YTD.
            for year in annual:
                ytd = nine_month.get(year["start"])
                if ytd and year["end"] not in series:
                    series[year["end"]] = {**year, "val": year["val"] - ytd["val"], "unit": unit, "derived": "annual_minus_9m",
                                           "start": ytd["end"]}
            if len(series) >= 5 and max(series) > best[0]:
                best = (max(series), f"{taxonomy}:{tag}", series)
    return best[1], best[2]


def _near(series: dict[str, dict[str, Any]], end: str, days: int) -> dict[str, Any] | None:
    """The fact whose period ends about `days` before `end` (within 20 days)."""
    target = date.fromisoformat(end) - timedelta(days=days)
    candidates = [key for key in series if abs((date.fromisoformat(key) - target).days) <= 20]
    return series[min(candidates, key=lambda key: abs((date.fromisoformat(key) - target).days))] if candidates else None


def _instant_series(facts: dict[str, Any], tags: list[tuple[str, str]]) -> tuple[str | None, list[dict[str, Any]]]:
    for taxonomy, tag in tags:
        units = facts.get("facts", {}).get(taxonomy, {}).get(tag, {}).get("units", {})
        for unit, rows in units.items():
            dated = sorted((row for row in rows if row.get("end") and row.get("val") is not None), key=lambda row: row["end"])
            if dated:
                return f"{taxonomy}:{tag}", [{**row, "unit": unit} for row in dated]
    return None, []


def sec_fundamentals(ticker: str, cik: int, facts: dict[str, Any]) -> dict[str, Any] | None:
    tag, revenue = _quarter_series(facts, REVENUE_TAGS)
    if not revenue:
        return None
    latest = max(revenue)
    current, year_ago = revenue[latest], _near(revenue, latest, 364)
    if not year_ago or not year_ago["val"]:
        return None
    previous = _near(revenue, latest, 91)
    previous_year_ago = _near(revenue, previous["end"], 364) if previous else None
    yoy = current["val"] / year_ago["val"] - 1
    yoy_prev = previous["val"] / previous_year_ago["val"] - 1 if previous and previous_year_ago and previous_year_ago["val"] else None
    _, gross = _quarter_series(facts, GROSS_TAGS)
    _, cost = _quarter_series(facts, COST_TAGS)

    def margin(end: str | None) -> float | None:
        rev = revenue.get(end) if end else None
        if not rev or not rev["val"]:
            return None
        if end in gross:
            return gross[end]["val"] / rev["val"]
        if end in cost:
            return 1 - cost[end]["val"] / rev["val"]
        return None
    gm, gm_prior = margin(latest), margin(year_ago.get("end"))
    _, rpo = _instant_series(facts, RPO_TAGS)
    rpo_yoy = None
    if len(rpo) >= 2:
        last = rpo[-1]
        earlier = [row for row in rpo if abs((date.fromisoformat(last["end"]) - date.fromisoformat(row["end"])).days - 365) <= 45]
        if earlier and earlier[-1]["val"]:
            rpo_yoy = last["val"] / earlier[-1]["val"] - 1
    _, shares = _instant_series(facts, SHARES_TAGS)
    shares_yoy = None
    if len(shares) >= 2:
        last = shares[-1]
        earlier = [row for row in shares if 300 <= (date.fromisoformat(last["end"]) - date.fromisoformat(row["end"])).days <= 430]
        if earlier and earlier[-1]["val"]:
            shares_yoy = last["val"] / earlier[-1]["val"] - 1
    return {"source": "SEC EDGAR XBRL companyfacts", "source_url": COMPANYFACTS.format(cik=cik), "revenue_tag": tag,
            "quarter": current.get("fp"), "quarter_end": current.get("end"), "filed": current.get("filed"), "form": current.get("form"),
            "revenue": current["val"], "revenue_unit": current["unit"], "revenue_yoy": yoy, "revenue_yoy_prev": yoy_prev,
            "gross_margin": gm, "gross_margin_change": (gm - gm_prior) if gm is not None and gm_prior is not None else None,
            "rpo_yoy": rpo_yoy, "shares_yoy": shares_yoy}


# ---------------------------------------------------------------- Yahoo Finance
def yahoo_data(symbol: str) -> dict[str, Any]:
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="3y", auto_adjust=True)
    out: dict[str, Any] = {"symbol": symbol}
    if history is None or history.empty:
        return out
    closes = history["Close"].dropna()
    last_day = closes.index[-1]

    def back(days: int) -> float | None:
        target = last_day - timedelta(days=days)
        window = closes[closes.index <= target]
        return float(window.iloc[-1]) if len(window) else None
    last = float(closes.iloc[-1])
    first_day = closes.index[0]
    out["market"] = {"source": "Yahoo Finance adjusted daily close (unofficial)", "source_url": f"https://finance.yahoo.com/quote/{symbol}",
                     "asof": str(last_day.date()), "price": last, "history_start": str(first_day.date())}
    for label, days in (("ret_6m", 182), ("ret_1y", 365), ("ret_2y", 730)):
        base = back(days)
        out["market"][label] = (last / base - 1) if base and (last_day - first_day).days >= days - 5 else None
    two = out["market"].get("ret_2y")
    out["market"]["cagr_2y"] = ((1 + two) ** 0.5 - 1) if two is not None and two > -1 else None
    # Listings younger than two years (spin-offs, IPOs) have no 2-year figure; the same long-term standard then uses
    # the annualized return since the first trading day, and only from one year of history on.
    span, first = (last_day - first_day).days, float(closes.iloc[0])
    out["market"]["cagr_listed"] = ((last / first) ** (365.25 / span) - 1) \
        if out["market"]["cagr_2y"] is None and span >= 360 and first > 0 else None
    try:
        info = ticker.fast_info
        out["market"]["currency"] = info.get("currency")
        out["market"]["market_cap"] = float(info.get("marketCap")) if info.get("marketCap") else None
    except Exception:
        pass
    try:
        name = ticker.info.get("shortName") or ticker.info.get("longName")
        out["name"] = name
    except Exception:
        pass
    try:
        statement = ticker.quarterly_income_stmt
        if statement is not None and not statement.empty and "Total Revenue" in statement.index:
            revenue = statement.loc["Total Revenue"].dropna().sort_index()
            gross = statement.loc["Gross Profit"].dropna().sort_index() if "Gross Profit" in statement.index else None
            if len(revenue) >= 5:
                latest_end = revenue.index[-1]
                ago = [end for end in revenue.index if abs((latest_end - end).days - 365) <= 20]
                prev_end = revenue.index[-2]
                prev_ago = [end for end in revenue.index if abs((prev_end - end).days - 365) <= 20]
                yoy = float(revenue[latest_end] / revenue[ago[-1]] - 1) if ago and revenue[ago[-1]] else None
                yoy_prev = float(revenue[prev_end] / revenue[prev_ago[-1]] - 1) if prev_ago and revenue[prev_ago[-1]] else None
                gm = gm_prior = None
                if gross is not None and latest_end in gross.index and revenue[latest_end]:
                    gm = float(gross[latest_end] / revenue[latest_end])
                    if ago and ago[-1] in gross.index and revenue[ago[-1]]:
                        gm_prior = float(gross[ago[-1]] / revenue[ago[-1]])
                out["fundamentals"] = {"source": "Yahoo Finance quarterly income statement (unofficial)",
                                       "source_url": f"https://finance.yahoo.com/quote/{symbol}/financials",
                                       "quarter_end": str(latest_end.date()), "revenue": float(revenue[latest_end]),
                                       "revenue_unit": out["market"].get("currency"), "revenue_yoy": yoy, "revenue_yoy_prev": yoy_prev,
                                       "gross_margin": gm, "gross_margin_change": (gm - gm_prior) if gm is not None and gm_prior is not None else None,
                                       "rpo_yoy": None, "shares_yoy": None}
    except Exception:
        pass
    return out


def usd_rate(currency: str | None, cache: dict[str, float | None]) -> float | None:
    if not currency or currency == "USD":
        return 1.0
    if currency not in cache:
        try:
            import yfinance as yf
            history = yf.Ticker(f"{currency}USD=X").history(period="5d")
            cache[currency] = float(history["Close"].dropna().iloc[-1]) if not history.empty else None
        except Exception:
            cache[currency] = None
    return cache[currency]


# ---------------------------------------------------------------- current-events momentum (SEC full-text search)
def news_momentum(terms: list[str], fetch: Callable[[str], bytes] | None, today: date) -> dict[str, Any] | None:
    """Filings mentioning the layer's terms: last 30 days versus the 60 days before (per-30-day rate ratio)."""
    if fetch is None:
        return None
    windows = {"recent": (today - timedelta(days=30), today), "prior": (today - timedelta(days=90), today - timedelta(days=31))}
    counts = {"recent": 0, "prior": 0}
    urls = []
    try:
        for term in terms:
            for label, (start, end) in windows.items():
                url = EFTS.format(query=urllib.parse.quote(f'"{term}"'), start=start.isoformat(), end=end.isoformat())
                payload = json.loads(fetch(url).decode("utf-8"))
                counts[label] += int(payload["hits"]["total"]["value"])
                if label == "recent":
                    urls.append(url)
    except Exception:
        return None
    prior_rate = counts["prior"] / 2
    return {"source": "SEC EDGAR full-text search", "source_url": urls[0] if urls else None, "terms": terms,
            "recent_30d": counts["recent"], "prior_60d": counts["prior"],
            "ratio": round(counts["recent"] / prior_rate, 3) if prior_rate > 0 else None}


# ---------------------------------------------------------------- scoring
def size_score(market_cap_usd: float | None) -> float:
    if not market_cap_usd:
        return 0.0
    for limit, points in ((2e9, 10), (10e9, 8), (50e9, 5), (200e9, 3)):
        if market_cap_usd < limit:
            return points
    return 1.0


def capture_score(fund: dict[str, Any] | None) -> tuple[float, dict[str, float]]:
    if not fund:
        return 0.0, {}
    parts = {
        "revenue_yoy": (12, clip(fund.get("revenue_yoy"), 0.0, 1.0) if fund.get("revenue_yoy") is not None else None),
        "acceleration": (6, clip((fund["revenue_yoy"] - fund["revenue_yoy_prev"]) if fund.get("revenue_yoy") is not None
                                 and fund.get("revenue_yoy_prev") is not None else None, -0.20, 0.30)
                         if fund.get("revenue_yoy_prev") is not None else None),
        "margin_expansion": (6, clip(fund.get("gross_margin_change"), -0.05, 0.10) if fund.get("gross_margin_change") is not None else None),
        "backlog_growth": (6, clip(fund.get("rpo_yoy"), 0.0, 0.5) if fund.get("rpo_yoy") is not None else None),
    }
    available = sum(weight for weight, value in parts.values() if value is not None)
    earned = sum(weight * value for weight, value in parts.values() if value is not None)
    detail = {key: round(weight * value, 2) for key, (weight, value) in parts.items() if value is not None}
    return (30 * earned / available if available else 0.0), detail


def build(fetch: Callable[[str], bytes] | None, now: datetime, with_news: bool = True) -> dict[str, Any]:
    layers = load_json(LAYERS)["layers"]
    serenity = load_json(SERENITY) if SERENITY.exists() else {"signals": [], "source": None}
    leopold = load_json(LEOPOLD) if LEOPOLD.exists() else {"positions": [], "filing": None}
    serenity_by = {row["symbol"]: row for row in serenity["signals"]}
    leopold_by = {row["ticker"]: row for row in leopold["positions"] if row.get("ticker")}
    ciks = cik_index()
    members: dict[str, dict[str, Any]] = {}
    for layer in layers:
        for capturer in layer["capturers"]:
            members.setdefault(capturer["symbol"], {"layer": layer, "capturer": capturer})
    fx: dict[str, float | None] = {}
    companies: dict[str, dict[str, Any]] = {}
    for symbol, member in members.items():
        data = yahoo_data(symbol)
        fund = None
        cik = ciks.get(symbol) if "." not in symbol else None
        if cik:
            facts = companyfacts(cik, fetch)
            fund = sec_fundamentals(symbol, cik, facts) if facts else None
        fund = fund or data.get("fundamentals")
        market = data.get("market")
        cap = market.get("market_cap") if market else None
        rate = usd_rate(market.get("currency") if market else None, fx)
        companies[symbol] = {"symbol": symbol, "name": data.get("name") or member["capturer"].get("role"), "layer": member["layer"]["id"],
                             "role": member["capturer"]["role"], "role_source": {"url": member["capturer"]["source_url"], "date": member["capturer"]["source_date"]},
                             "fundamentals": fund, "market": market, "market_cap_usd": cap * rate if cap and rate else None,
                             "serenity": serenity_by.get(symbol), "leopold": leopold_by.get(symbol)}
    # Layer heat and the Leopold-led industry ranking.
    max_intensity = max((row["intensity"] for row in serenity["signals"]), default=1.0) or 1.0
    industry = []
    for layer in layers:
        rows = [company for company in companies.values() if company["layer"] == layer["id"]]
        yoys = [c["fundamentals"]["revenue_yoy"] for c in rows if c["fundamentals"] and c["fundamentals"].get("revenue_yoy") is not None]
        accels = [c["fundamentals"]["revenue_yoy"] - c["fundamentals"]["revenue_yoy_prev"] for c in rows
                  if c["fundamentals"] and c["fundamentals"].get("revenue_yoy") is not None and c["fundamentals"].get("revenue_yoy_prev") is not None]
        six = [c["market"]["ret_6m"] for c in rows if c["market"] and c["market"].get("ret_6m") is not None]
        fund_weight = sum((c["leopold"] or {}).get("long_weight", 0) for c in rows)
        serenity_heat = sum((c["serenity"] or {}).get("intensity", 0) for c in rows)
        news = news_momentum(layer["filing_terms"], fetch, now.date()) if with_news else None
        median_yoy = statistics.median(yoys) if yoys else None
        median_accel = statistics.median(accels) if accels else None
        chain_weight = {1: 1.0, 2: 1.0, 3: 0.85, 4: 0.9, 5: 0.8, 6: 0.6}.get(layer["chain_rank"], 0.6)
        heat = (10 * clip(median_yoy, 0.0, 0.8) + 5 * clip(median_accel, -0.15, 0.25)
                + 5 * clip((news or {}).get("ratio"), 0.8, 1.6) + 5 * clip(fund_weight, 0.0, 0.3))
        leopold_score = (35 * chain_weight + 25 * clip(fund_weight, 0.0, 0.4) + 20 * clip(median_accel, -0.15, 0.25)
                         + 10 * clip((news or {}).get("ratio"), 0.8, 1.6) + 10 * clip(serenity_heat / max_intensity, 0.0, 2.0))
        industry.append({"id": layer["id"], "name_zh": layer["name_zh"], "chain": layer["chain"], "chain_rank": layer["chain_rank"],
                         "leopold_constraint": layer["leopold_constraint"], "heat": round(heat, 2), "explosiveness": round(leopold_score, 1),
                         "companies": len(rows), "median_revenue_yoy": median_yoy, "median_acceleration": median_accel,
                         "median_return_6m": statistics.median(six) if six else None, "fund_13f_weight": round(fund_weight, 4),
                         "serenity_heat": round(serenity_heat, 2), "news": news})
    heat_by = {row["id"]: row["heat"] for row in industry}
    industry.sort(key=lambda row: -row["explosiveness"])
    for rank, row in enumerate(industry, start=1):
        row["rank"] = rank
    # Company scores and filters.
    scored, excluded = [], []
    for company in companies.values():
        market, fund, sig, pos = company["market"], company["fundamentals"], company["serenity"], company["leopold"]
        reasons = []
        if not market or market.get("cagr_2y") is None and market.get("cagr_listed") is None:
            reasons.append("MARKET_HISTORY_UNDER_1Y")
        long_term = (market or {}).get("cagr_2y")
        long_term = long_term if long_term is not None else (market or {}).get("cagr_listed")
        if long_term is None or long_term <= 0:
            reasons.append("LONG_TERM_RETURN_NOT_POSITIVE")
        if sig and sig.get("stance") == "BEARISH" and sig.get("bearish", 0) >= 3 and sig.get("bullish", 0) == 0:
            reasons.append("SERENITY_BEARISH")
        if reasons:
            excluded.append({"symbol": company["symbol"], "reasons": reasons})
            continue
        capture, capture_detail = capture_score(fund)
        archetype = "EXPLOSION" if company["market_cap_usd"] and company["market_cap_usd"] < EXPLOSION_CAP_USD else "COMPOUNDER"
        weights = {"capture": 15, "lead": 30, "confirm": 20} if archetype == "EXPLOSION" else {"capture": 30, "lead": 20, "confirm": 15}
        capture = capture * weights["capture"] / 30
        lead = 0.7 * clip((sig or {}).get("intensity"), 0.0, max_intensity * 0.5) if sig else 0.0
        if sig and sig.get("stance") == "BEARISH":
            lead *= 0.3
        lead += 0.3 * clip((pos or {}).get("long_weight"), 0.0, 0.05) if pos else 0.0
        lead *= weights["lead"]
        confirm = weights["confirm"] * (0.55 * clip(market.get("ret_6m"), -0.2, 1.0) + 0.45 * clip(market.get("ret_1y"), 0.0, 2.0))
        size = size_score(company["market_cap_usd"])
        penalty = 0.0
        shares_yoy = (fund or {}).get("shares_yoy")
        if shares_yoy is not None:
            penalty += 4 if shares_yoy > 0.15 else 2 if shares_yoy > 0.05 else 0
        if sig and sig.get("financing_concerns", 0) >= 3 and sig["financing_concerns"] >= 0.2 * sig.get("mentions", 1):
            penalty += 3
        total = heat_by.get(company["layer"], 0) + capture + lead + confirm + size - penalty
        company["long_term_return"] = long_term
        company["archetype"] = archetype
        company["score"] = round(max(0.0, total), 1)
        company["score_parts"] = {"layer_heat": heat_by.get(company["layer"], 0), "capture": round(capture, 2), "capture_detail": capture_detail,
                                  "lead": round(lead, 2), "confirmation": round(confirm, 2), "size": size, "penalty": penalty}
        scored.append(company)
    scored.sort(key=lambda company: (-company["score"], company["symbol"]))
    top, per_layer, overflow = [], {}, []
    for company in scored:
        if len(top) < TOP_N and per_layer.get(company["layer"], 0) < MAX_PER_LAYER:
            top.append(company)
            per_layer[company["layer"]] = per_layer.get(company["layer"], 0) + 1
        else:
            overflow.append(company)
    for rank, company in enumerate(top, start=1):
        company["rank"] = rank
    return {"schema": "v213-bottleneck-top20-v3", "generated_at": iso(now), "method": "bottleneck-explosion-v3",
            "leads": {"serenity": serenity.get("source"), "leopold": {"filing": leopold.get("filing"), "caveat": leopold.get("caveat")}},
            "layers_source": "config/bottleneck-layers-v3.json", "top": top, "industries": industry,
            "watch": [{"symbol": c["symbol"], "score": c["score"], "layer": c["layer"]} for c in overflow[:10]],
            "all_scores": [{"symbol": c["symbol"], "score": c["score"], "layer": c["layer"], "archetype": c["archetype"],
                            "parts": c["score_parts"]} for c in scored],
            "excluded": excluded}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--no-news", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    now = utc_now()
    if args.if_older_than_hours > 0 and args.output.exists():
        try:
            previous = load_json(args.output)
            age = (now - datetime.strptime(previous["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
            if age < args.if_older_than_hours:
                print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age, 1)}))
                return 0
        except (OSError, ValueError, KeyError):
            pass
    try:
        fetch = sec_fetch_factory()
    except Exception:
        fetch = None  # no SEC contact: cached companyfacts only, Yahoo fundamentals otherwise
    try:
        document = build(fetch, now, with_news=not args.no_news)
    except Exception as error:  # keep the last good ranking
        print(json.dumps({"status": "FAILED", "error": type(error).__name__, "detail": str(error)[:160]}))
        return 1
    if len(document["top"]) < 10:
        print(json.dumps({"status": "FAILED", "error": "TOO_FEW_QUALIFIED", "qualified": len(document["top"])}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_name(args.output.name + ".tmp")
    try:
        body = json.dumps(document, ensure_ascii=False, default=str, allow_nan=False)
    except ValueError:  # a NaN from a provider would make the publisher drop v3 later; fail here with the reason
        print(json.dumps({"status": "FAILED", "error": "NON_FINITE_VALUE"}))
        return 1
    temp.write_bytes(body.encode("utf-8"))
    temp.replace(args.output)
    print(json.dumps({"status": "OK", "top": [(c["rank"], c["symbol"], c["score"], c["layer"]) for c in document["top"]],
                      "industries": [(i["rank"], i["id"], i["explosiveness"]) for i in document["industries"]],
                      "excluded": len(document["excluded"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
