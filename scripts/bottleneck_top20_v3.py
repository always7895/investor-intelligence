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
import html
import json
import math
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import listing_lineage  # noqa: E402
import official_quarterly_revenue  # noqa: E402

LAYERS = ROOT / "config" / "bottleneck-layers-v3.json"
KOREA_ORDERS = ROOT / "config" / "korea-ir-orders-v1.json"
KOREA_FUNDAMENTALS = ROOT / "config" / "korea-ir-fundamentals-v1.json"
SERENITY = ROOT / "data" / "cache" / "serenity_signals_latest.json"
LEOPOLD = ROOT / "data" / "cache" / "leopold_positions_latest.json"
TICKERS = ROOT / "data" / "cache" / "v21" / "company_tickers_exchange.json"
CACHE = ROOT / "data" / "cache" / "v3"
OUTPUT = ROOT / "data" / "cache" / "bottleneck_top20_v3.json"
CISION_CACHE = ROOT / "data" / "cache" / "cision_interim_revenue.json"
COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
EFTS = "https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt={start}&enddt={end}"
REVENUE_TAGS = [("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"), ("us-gaap", "SalesRevenueNet"),
                ("ifrs-full", "Revenue")]
GROSS_TAGS = [("us-gaap", "GrossProfit"), ("ifrs-full", "GrossProfit")]
COST_TAGS = [("us-gaap", "CostOfRevenue"), ("us-gaap", "CostOfGoodsAndServicesSold"), ("ifrs-full", "CostOfSales")]
RPO_TAGS = [("us-gaap", "RevenueRemainingPerformanceObligation")]
SHARES_TAGS = [("dei", "EntityCommonStockSharesOutstanding")]
DILUTED_SHARES_TAG = ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding")  # fallback, quarterly rows only
DEI_COVER_MAX_LAG_DAYS = 105  # longest 10-K deadline (90 days) plus Rule 12b-25 NT extension (15)
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


def cik_index(captured=None) -> dict[str, int]:
    document = load_json(captured.operand("tickers") if captured else TICKERS)
    fields = document["fields"]
    return {str(dict(zip(fields, row))["ticker"]).upper(): int(dict(zip(fields, row))["cik"]) for row in document["data"]}


def companyfacts(cik: int, fetch: Callable[[str], bytes] | None, max_age_hours: float = 20, *, captured=None) -> dict[str, Any] | None:
    if captured is not None:
        item = captured.operand(f"facts/CIK{cik:010d}")
        return load_json(item) if item.exists() else None  # actual host capture/fetch, never reopen
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


def _shares_yoy(current: Any, prior: Any) -> float | None:
    """Year-on-year share count (the dilution-penalty input): None when a value is missing, not strictly positive,
    non-finite, or the change is outside (-0.5, 5.0) (a data error)."""
    current, prior = _finite(current), _finite(prior)
    if current is None or prior is None or current <= 0 or prior <= 0:
        return None
    yoy = current / prior - 1
    return yoy if math.isfinite(yoy) and -0.5 < yoy < 5.0 else None


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
    rpo_yoy = rpo_prior = None
    if len(rpo) >= 2:
        last = rpo[-1]
        earlier = [row for row in rpo if abs((date.fromisoformat(last["end"]) - date.fromisoformat(row["end"])).days - 365) <= 45]
        if earlier and earlier[-1]["val"]:
            rpo_yoy, rpo_prior = last["val"] / earlier[-1]["val"] - 1, earlier[-1]  # the comparison is kept (order forecast lineage)
    # DEI amendments: latest filed wins per end, ties go to the later listed row.
    # Validate before sorting: malformed/non-string dates must not discard fundamentals.
    shares = []
    for taxonomy, shares_tag in SHARES_TAGS:
        units = facts.get("facts", {}).get(taxonomy, {}).get(shares_tag, {}).get("units", {})
        for unit, rows in units.items():
            by_end: dict[str, dict[str, Any]] = {}
            for row in rows:
                try:
                    date.fromisoformat(row["end"])
                except (KeyError, TypeError, ValueError):
                    continue
                if row.get("val") is None:
                    continue
                previous_share = by_end.get(row["end"])
                if previous_share is None or str(row.get("filed", "")) >= str(previous_share.get("filed", "")):
                    by_end[row["end"]] = {**row, "unit": unit}
            if by_end:
                shares = [by_end[end] for end in sorted(by_end)]
                break
        if shares:
            break
    shares_yoy = None
    cover = [row for row in shares
             if 0 <= (date.fromisoformat(row["end"]) - date.fromisoformat(latest)).days <= DEI_COVER_MAX_LAG_DAYS]
    if cover:
        last = cover[0]  # earliest cover date aligned with this revenue quarter, not a later quarter
        earlier = [row for row in shares if 300 <= (date.fromisoformat(last["end"]) - date.fromisoformat(row["end"])).days <= 430]
        if earlier:
            # Equal-distance priors choose the earlier end (ascending, deduplicated series).
            prior = min(earlier, key=lambda row: abs((date.fromisoformat(last["end"]) - date.fromisoformat(row["end"])).days - 365))
            shares_yoy = _shares_yoy(last["val"], prior["val"])
    shares_basis = "OUTSTANDING" if shares_yoy is not None else None
    if shares_basis is None:
        # No dei share count (dual-class filers such as CRWV report theirs with dimensions): the diluted weighted
        # average, quarterly rows only (year-to-date and annual rows are not a quarter)
        diluted: dict[str, Any] = {}
        taxonomy, diluted_tag = DILUTED_SHARES_TAG
        for unit_rows in facts.get("facts", {}).get(taxonomy, {}).get(diluted_tag, {}).get("units", {}).values():
            for row in unit_rows:
                try:
                    days = (date.fromisoformat(row["end"]) - date.fromisoformat(row.get("start"))).days
                except (KeyError, TypeError, ValueError):
                    continue
                if row.get("val") is None or not 80 <= days <= 100:
                    continue
                earlier = diluted.get(row["end"])  # the same quarter in several filings: the latest filing wins
                if earlier is None or str(row.get("filed", "")) >= str(earlier.get("filed", "")):
                    diluted[row["end"]] = row
        # The figure must belong to the financial quarter it is published with: the current row must end on the
        # revenue quarter's end exactly and the comparison row must end 365 +/- 20 days before it. No fallback to
        # an older quarter (a fourth quarter filed only as annual and nine-month rows has no quarter-length row).
        if latest in diluted:
            target = date.fromisoformat(latest) - timedelta(days=365)
            candidates = [end for end in diluted if end != latest and abs((date.fromisoformat(end) - target).days) <= 20]
            if candidates:
                prior = diluted[min(candidates, key=lambda end: abs((date.fromisoformat(end) - target).days))]
                shares_yoy = _shares_yoy(diluted[latest]["val"], prior["val"])
                shares_basis = "DILUTED_WEIGHTED_AVERAGE" if shares_yoy is not None else None
    return {"source": "SEC EDGAR XBRL companyfacts", "source_url": COMPANYFACTS.format(cik=cik), "revenue_tag": tag,
            "quarter": current.get("fp"), "quarter_end": current.get("end"), "filed": current.get("filed"), "form": current.get("form"),
            "revenue": current["val"], "revenue_unit": current["unit"], "revenue_yoy": yoy, "revenue_yoy_prev": yoy_prev,
            "gross_margin": gm, "gross_margin_change": (gm - gm_prior) if gm is not None and gm_prior is not None else None,
            "rpo_yoy": rpo_yoy, "shares_yoy": shares_yoy, "shares_basis": shares_basis,
            "rpo": rpo[-1]["val"] if rpo else None, "rpo_unit": rpo[-1]["unit"] if rpo else None,
            "rpo_end": rpo[-1]["end"] if rpo else None,
            "rpo_prior": rpo_prior["val"] if rpo_prior else None, "rpo_prior_end": rpo_prior["end"] if rpo_prior else None}


# ---------------------------------------------------------------- order visibility and growth scenarios
def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def yahoo_consensus(ticker: Any, symbol: str, price: float | None, info: dict[str, Any] | None) -> dict[str, Any] | None:
    """Analyst consensus for the current (0y) and next (+1y) fiscal year and the mean target price (Yahoo Finance,
    unofficial). Each figure keeps its analyst count; None when Yahoo has no next-year revenue estimate."""
    def row(frame: Any, period: str) -> tuple[float | None, int | None]:
        if frame is None or getattr(frame, "empty", True) or period not in frame.index:
            return None, None
        count = _finite(frame.loc[period].get("numberOfAnalysts"))
        return _finite(frame.loc[period].get("avg")), int(count) if count else None
    revenue0, _ = row(ticker.revenue_estimate, "0y")
    revenue1, revenue_n = row(ticker.revenue_estimate, "+1y")
    if not revenue0 or not revenue1 or revenue0 <= 0:
        return None
    eps0, _ = row(ticker.earnings_estimate, "0y")
    eps1, eps_n = row(ticker.earnings_estimate, "+1y")
    info = info or {}
    target, target_n = _finite(info.get("targetMeanPrice")), _finite(info.get("numberOfAnalystOpinions"))
    return {"source": "Yahoo Finance analyst estimates (unofficial)", "source_url": f"https://finance.yahoo.com/quote/{symbol}/analysis",
            "asof": utc_now().date().isoformat(), "revenue_fy0": revenue0, "revenue_fy1": revenue1,
            "revenue_growth": revenue1 / revenue0 - 1, "revenue_analysts": revenue_n,
            "eps_fy0": eps0, "eps_fy1": eps1, "eps_analysts": eps_n,
            "eps_growth": eps1 / eps0 - 1 if eps0 and eps1 and eps0 > 0 and eps1 > 0 else None,
            "target_mean": target, "target_analysts": int(target_n) if target_n else None,
            "price": price, "target_upside": target / price - 1 if target and price and price > 0 else None}


NASDAQ_ANALYST = "https://api.nasdaq.com/api/analyst/{symbol}/{kind}"


def nasdaq_consensus(symbol: str, price: float | None, fetch_json: Callable[[str], Any] | None = None) -> dict[str, Any] | None:
    """Second, independent consensus for US listings (operator 2026-09-26: Yahoo alone was too narrow; Nasdaq data is
    accepted): Nasdaq.com's mean price target with the analyst count and the yearly EPS consensus. None when neither
    part is published; shown beside Yahoo, never averaged into it."""
    if "." in symbol:
        return None
    def get(kind: str) -> Any:
        url = NASDAQ_ANALYST.format(symbol=urllib.parse.quote(symbol.replace("-", ".").lower()), kind=kind)
        if fetch_json:
            return fetch_json(url)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (InvestorIntelligence public observation)",
                                                       "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed public host
            return json.loads(response.read().decode("utf-8"))
    out: dict[str, Any] = {"source": "Nasdaq.com analyst estimates", "asof": utc_now().date().isoformat(),
                           "source_url": f"https://www.nasdaq.com/market-activity/stocks/{symbol.replace('-', '.').lower()}/analyst-research"}
    try:
        overview = ((get("targetprice").get("data") or {}).get("consensusOverview") or {})
        target = _finite(overview.get("priceTarget"))
        count = sum(int(overview.get(key) or 0) for key in ("buy", "hold", "sell"))
        if target and target > 0:
            out.update(target_mean=target, target_analysts=count or None,
                       target_upside=target / price - 1 if price and price > 0 else None)
    except Exception:
        pass
    try:
        rows = (((get("earnings-forecast").get("data") or {}).get("yearlyForecast") or {}).get("rows") or [])[:2]
        eps = [(_finite(row.get("consensusEPSForecast")), _finite(row.get("noOfEstimates")), str(row.get("fiscalEnd") or "")) for row in rows]
        if len(eps) == 2 and eps[0][0] and eps[1][0]:
            out.update(eps_fy0=eps[0][0], eps_fy1=eps[1][0], eps_fiscal_end=eps[1][2][:20],
                       eps_analysts=int(eps[1][1]) if eps[1][1] else None,
                       eps_growth=eps[1][0] / eps[0][0] - 1 if eps[0][0] > 0 and eps[1][0] > 0 else None)
    except Exception:
        pass
    return out if ("target_mean" in out or "eps_fy1" in out) else None


def korea_orders(symbol: str, path: Path = KOREA_ORDERS) -> dict[str, Any] | None:
    """Order backlog and guidance from the company's IR deck (config/korea-ir-orders-v1.json), or the stated reason
    why none is available."""
    try:
        document = load_json(path)
    except (OSError, ValueError):
        return None
    entry = document.get("companies", {}).get(symbol)
    if entry:
        backlog, intake, guidance = entry["backlog"], entry.get("intake_quarter"), entry.get("guidance")
        return {"kind": "BACKLOG", "amount": backlog["amount"], "currency": backlog["currency"], "as_of": entry["period_end"],
                "yoy": backlog.get("yoy"), "scope": entry.get("scope"), "source": f"{entry['document']} p.{backlog['page']}",
                # A deck's backlog is a segment unless the config marks it company-wide; its YoY is the company's own statement.
                "scope_kind": "COMPANY" if entry.get("scope_kind") == "COMPANY" else "SEGMENT", "yoy_evidence": backlog.get("evidence"),
                "source_url": entry["source_url"],
                "intake_quarter": None if not intake else {"amount": intake["amount"], "yoy": intake.get("yoy")},
                "guidance": None if not guidance else {"kind": guidance["kind"], "year": guidance["year"], "amount": guidance["amount"],
                                                       "previous": guidance.get("previous")}}
    reason = document.get("unavailable", {}).get(symbol)
    return {"kind": "NOT_DISCLOSED", "reason": reason} if reason else None


def outlook(symbol: str, fund: dict[str, Any] | None, consensus: dict[str, Any] | None,
            second: dict[str, Any] | None = None, *, captured=None) -> dict[str, Any]:
    """Current orders (SEC RPO or a Korean IR backlog), the consensus outlook and the price scenarios if it is realized
    at unchanged valuation multiples (scenario arithmetic, not a forecast)."""
    orders = None
    if fund and fund.get("rpo"):
        # XBRL RevenueRemainingPerformanceObligation without dimensions is the company-wide total; its YoY comes from the
        # same series (the year-ago value and date travel with it).
        orders = {"kind": "RPO", "amount": fund["rpo"], "currency": fund.get("rpo_unit"), "as_of": fund.get("rpo_end"),
                  "yoy": fund.get("rpo_yoy"), "source": fund["source"], "source_url": fund["source_url"], "scope_kind": "COMPANY",
                  "yoy_prior_amount": fund.get("rpo_prior"), "yoy_prior_as_of": fund.get("rpo_prior_end")}
    elif symbol.endswith((".KS", ".KQ")):
        orders = korea_orders(symbol, captured.operand("korea_orders") if captured else KOREA_ORDERS)
    scenarios = []
    if consensus:
        scenarios.append({"kind": "REVENUE_CONSTANT_PS", "change": consensus["revenue_growth"]})
        if consensus.get("eps_growth") is not None:
            scenarios.append({"kind": "EPS_CONSTANT_PE", "change": consensus["eps_growth"]})
        if consensus.get("target_upside") is not None:
            scenarios.append({"kind": "ANALYST_TARGET", "change": consensus["target_upside"]})
    return {"orders": orders, "consensus": consensus, "scenarios": scenarios, "consensus_second": second}


# ---------------------------------------------------------------- Yahoo Finance
def yahoo_data(symbol: str, lineage: dict[str, Any] | None = None, *, config_path: Path | None = None, as_of: datetime | None = None) -> dict[str, Any]:
    import yfinance as yf
    requested_from = listing_lineage.request_start(datetime.now(timezone.utc).date())
    ticker = yf.Ticker(symbol)
    history = ticker.history(start=requested_from.isoformat(), auto_adjust=True)
    out: dict[str, Any] = {"symbol": symbol}
    if history is None or history.empty or "Close" not in history.columns:
        return out
    closes = history["Close"].dropna()
    if closes.empty:  # all-NaN (or the empty frame's) closes: no market object, never an exception
        return out
    # Returns respect the listing's verified lineage (scripts/listing_lineage.py): a spin-off, resumption, IPO or new
    # equity counts from its first regular-way session, never from when-issued trading; no two-year figure is made up.
    returns = listing_lineage.long_term_returns(((stamp.date(), float(close)) for stamp, close in closes.items()), lineage,
                                                requested_from)
    if returns.get("asof") is None:
        return out
    last = returns["price"]
    out["market"] = {"source": "Yahoo Finance adjusted daily close (unofficial)", "source_url": f"https://finance.yahoo.com/quote/{symbol}",
                     **returns}
    try:
        info = ticker.fast_info
        out["market"]["currency"] = info.get("currency")
        out["market"]["market_cap"] = float(info.get("marketCap")) if info.get("marketCap") else None
    except Exception:
        pass
    info = None
    try:
        info = ticker.info
        name = info.get("shortName") or info.get("longName")
        out["name"] = name
    except Exception:
        pass
    try:
        out["consensus"] = yahoo_consensus(ticker, symbol, last, info)
    except Exception:
        out["consensus"] = None
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
                prev_basis, prev_source, prev_reason = "YAHOO", None, None
                if not prev_ago and max(statement.columns) != latest_end:
                    # A later statement column without a value: the record's quarter is no longer Yahoo's latest period.
                    prev_basis, prev_reason = None, "PERIOD_MISMATCH"
                elif not prev_ago:
                    # Only an absent comparator may take the reviewed official pair (scripts/official_quarterly_revenue.py):
                    # no column near a year before, or one whose cell is empty (NaN/None, which is how Yahoo reports a value
                    # it lacks; 5351.TWO 2025-03-31 on 2026-09-27). A zero, negative or other present value keeps Yahoo's
                    # own result above. The financial statement currency, not the quote's, must match.
                    try:
                        currency = info.get("financialCurrency") if isinstance(info, dict) else None
                        curated = official_quarterly_revenue.evaluate(
                            symbol, revenue, currency, yoy, as_of=as_of or datetime.now(timezone.utc), path=config_path)
                    except Exception:  # never lose the Yahoo fundamentals to the supplement
                        curated = official_quarterly_revenue.Result("INVALID_RECORD")
                    if curated.reason is None:
                        yoy_prev, prev_basis, prev_source = curated.revenue_yoy_prev, "OFFICIAL_CURATED", curated.source
                    else:
                        prev_basis, prev_reason = None, curated.reason
                gm = gm_prior = None
                if gross is not None and latest_end in gross.index and revenue[latest_end]:
                    gm = float(gross[latest_end] / revenue[latest_end])
                    if ago and ago[-1] in gross.index and revenue[ago[-1]]:
                        gm_prior = float(gross[ago[-1]] / revenue[ago[-1]])
                shares_yoy = shares_basis = None
                # The figure must belong to the financial quarter it is published with: the current value must sit
                # in the revenue quarter's own column (exact timestamp) and the comparison column 365 +/- 20 days
                # before it. No substitution from an older column.
                if "Diluted Average Shares" in statement.index:
                    diluted = statement.loc["Diluted Average Shares"].dropna().sort_index()
                    if latest_end in diluted.index:
                        target = latest_end - timedelta(days=365)
                        candidates = [end for end in diluted.index if end != latest_end and abs((end - target).days) <= 20]
                        if candidates:
                            prior = min(candidates, key=lambda end: abs((end - target).days))
                            shares_yoy = _shares_yoy(diluted[latest_end], diluted[prior])
                            shares_basis = "DILUTED_WEIGHTED_AVERAGE" if shares_yoy is not None else None
                out["fundamentals"] = {"source": "Yahoo Finance quarterly income statement (unofficial)",
                                       "source_url": f"https://finance.yahoo.com/quote/{symbol}/financials",
                                       "quarter_end": str(latest_end.date()), "revenue": float(revenue[latest_end]),
                                       "revenue_unit": out["market"].get("currency"), "revenue_yoy": yoy, "revenue_yoy_prev": yoy_prev,
                                       "revenue_yoy_prev_basis": prev_basis, "revenue_yoy_prev_source": prev_source,
                                       **({"revenue_yoy_prev_reason": prev_reason} if prev_reason else {}),  # local only
                                       "gross_margin": gm, "gross_margin_change": (gm - gm_prior) if gm is not None and gm_prior is not None else None,
                                       "rpo_yoy": None, "shares_yoy": shares_yoy, "shares_basis": shares_basis}
    except Exception:
        pass
    return out


def _chart_bars(raw):
    doc = json.loads(raw.decode("utf-8"))
    result = doc["chart"]["result"][0]
    times = result["timestamp"]
    closes = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    if closes is None:
        # Never label an unadjusted series as adjusted lineage returns.
        raise ValueError("ADJUSTED_HISTORY_UNAVAILABLE")
    if len(times) != len(closes) or len(times) > 4096:
        raise ValueError("MARKET_HISTORY_BOUND")
    bars = [(datetime.fromtimestamp(t, timezone.utc).date(), float(c)) for t, c in zip(times, closes)
            if type(t) is int and c is not None and _finite(c) is not None and float(c) > 0]
    return result.get("meta") or {}, bars


def captured_yahoo_data(symbol, captured, lineage, as_of):
    """Actual public Yahoo chart/quote/timeseries bytes -> same ranking quantities.

    Stateless HTTPS has no cookie/credential persistence or writable import/cache.
    Refused/unavailable provider data stays missing, never manufactured fundamentals.
    """
    out = {"symbol": symbol}
    chart = captured.operand("yahoo/chart/" + symbol)
    if not chart.exists():
        return out
    try:
        meta, bars = _chart_bars(chart.read_bytes())
        returns = listing_lineage.long_term_returns(bars, lineage, listing_lineage.request_start(as_of.date()))
        if returns.get("asof") is None:
            return out
        summary = captured.operand("yahoo/summary/" + symbol)
        modules = json.loads(summary.read_text())["quoteSummary"]["result"][0] if summary.exists() else {}
        quote = modules.get("price") or {}
        number = lambda value: _finite(value.get("raw")) if isinstance(value, dict) else _finite(value)
        currency = quote.get("currency") or meta.get("currency")
        price = returns["price"]
        out["market"] = {"source": "Yahoo Finance adjusted daily close (unofficial)",
            "source_url": f"https://finance.yahoo.com/quote/{symbol}", **returns,
            "currency": currency, "market_cap": number(quote.get("marketCap"))}
        out["name"] = quote.get("shortName") or quote.get("longName") or meta.get("shortName")
        financial = modules.get("financialData") or {}
        trends = (modules.get("earningsTrend") or {}).get("trend") or []
        fy0 = next((x for x in trends if x.get("period") == "0y"), {})
        fy1 = next((x for x in trends if x.get("period") == "+1y"), {})
        r0, r1 = number((fy0.get("revenueEstimate") or {}).get("avg")), number((fy1.get("revenueEstimate") or {}).get("avg"))
        e0, e1 = number((fy0.get("earningsEstimate") or {}).get("avg")), number((fy1.get("earningsEstimate") or {}).get("avg"))
        target = number(financial.get("targetMeanPrice"))
        if r0 and r0 > 0 and r1 is not None:
            out["consensus"] = {"source": "Yahoo Finance analyst consensus (unofficial)",
                "source_url": f"https://finance.yahoo.com/quote/{symbol}/analysis", "asof": iso(as_of)[:10],
                "revenue_fy0": r0, "revenue_fy1": r1, "revenue_growth": r1 / r0 - 1,
                "revenue_analysts": number((fy1.get("revenueEstimate") or {}).get("numberOfAnalysts")),
                "eps_fy0": e0, "eps_fy1": e1, "eps_growth": e1 / e0 - 1 if e0 and e0 > 0 and e1 is not None else None,
                "eps_analysts": number((fy1.get("earningsEstimate") or {}).get("numberOfAnalysts")),
                "target_mean": target, "target_analysts": number(financial.get("numberOfAnalystOpinions")),
                "price": price, "target_upside": target / price - 1 if target and price else None}
        series = captured.operand("yahoo/financials/" + symbol)
        if series.exists():
            rows = json.loads(series.read_text())["timeseries"]["result"]
            values = {}
            for item in rows:
                kind = (item.get("meta") or {}).get("type", [None])[0]
                if kind in ("quarterlyTotalRevenue", "quarterlyGrossProfit", "quarterlyDilutedAverageShares"):
                    values[kind] = {date.fromisoformat(v["asOfDate"]): number(v["reportedValue"]) for v in item.get(kind, [])}
            revenue = {day: amount for day, amount in values.get("quarterlyTotalRevenue", {}).items() if amount is not None}
            if len(revenue) >= 5:
                ends = sorted(revenue)
                end, previous = ends[-1], ends[-2]
                # Legacy selects the last sorted eligible revenue column, not
                # the nearest share comparator. Empty values are absent; zero
                # and negative PRESENT values must not enable curated fallback.
                eligible = lambda day: [d for d in ends if abs((day - d).days - 365) <= 20]
                ago, prev_ago = eligible(end), eligible(previous)
                year, prev_year = (ago[-1] if ago else None), (prev_ago[-1] if prev_ago else None)
                yoy = revenue[end] / revenue[year] - 1 if year and revenue[year] else None
                prior_yoy = revenue[previous] / revenue[prev_year] - 1 if prev_year and revenue[prev_year] else None
                # Retain ALL statement periods before dropping null cells,
                # including the provider's explicit timestamp columns. A later
                # empty revenue period is the existing PERIOD_MISMATCH veto.
                statement_periods = {d for columns in values.values() for d in columns}
                for item in rows:
                    statement_periods.update(datetime.fromtimestamp(t, timezone.utc).date()
                                             for t in item.get("timestamp", []) if type(t) is int)
                latest_statement = max(statement_periods) if statement_periods else end
                basis, evidence, reason = "YAHOO", None, None
                if prev_year is None and latest_statement != end:
                    basis, reason = None, "PERIOD_MISMATCH"
                elif prev_year is None:
                    try:
                        evaluated = official_quarterly_revenue.evaluate(symbol, revenue, financial.get("financialCurrency"), yoy, as_of=as_of,
                                                                       path=captured.operand("official_quarters"))
                    except Exception:
                        evaluated = official_quarterly_revenue.Result("INVALID_RECORD")
                    if evaluated.reason is None:
                        prior_yoy, basis, evidence = evaluated.revenue_yoy_prev, "OFFICIAL_CURATED", evaluated.source
                    else:
                        basis, reason = None, evaluated.reason
                gross = values.get("quarterlyGrossProfit", {})
                gm = gross[end] / revenue[end] if gross.get(end) is not None and revenue[end] else None
                gm_prior = gross[year] / revenue[year] if year and gross.get(year) is not None and revenue[year] else None
                shares = values.get("quarterlyDilutedAverageShares", {})
                # Independent eligible diluted-share dates, exact current
                # revenue period and nearest prior date (legacy semantics).
                candidates = [d for d in sorted(shares) if shares[d] is not None and d != end
                              and abs((end - d).days - 365) <= 20]
                share_prior = min(candidates, key=lambda d: abs((end - d).days - 365)) if candidates else None
                dilution = _shares_yoy(shares.get(end), shares.get(share_prior)) if share_prior else None
                out["fundamentals"] = {"source": "Yahoo Finance quarterly income statement (unofficial)",
                    "source_url": f"https://finance.yahoo.com/quote/{symbol}/financials", "quarter_end": end.isoformat(),
                    "revenue": revenue[end], "revenue_unit": out["market"].get("currency"), "revenue_yoy": yoy,
                    "revenue_yoy_prev": prior_yoy, "revenue_yoy_prev_basis": basis, "revenue_yoy_prev_source": evidence,
                    **({"revenue_yoy_prev_reason": reason} if reason else {}),
                    "gross_margin": gm, "gross_margin_change": gm - gm_prior if gm is not None and gm_prior is not None else None,
                    "rpo_yoy": None, "shares_yoy": dilution,
                    "shares_basis": "DILUTED_WEIGHTED_AVERAGE" if dilution is not None else None}
    except (KeyError, ValueError, TypeError, IndexError):
        # No substitute rows/numbers; whatever independent admitted channel was
        # obtained remains visible, matching existing graceful Yahoo availability.
        pass
    return out


def captured_usd_rate(currency, captured, cache):
    if not currency or currency == "USD":
        return 1.0
    if currency not in cache:
        item = captured.operand("fx/" + currency)
        try:
            _, bars = _chart_bars(item.read_bytes())
            cache[currency] = bars[-1][1] if bars else None
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            cache[currency] = None
    return cache[currency]


# Official monthly revenue of Taiwan listings (政府資料開放授權條款第1版): the latest reported month, filed by the 10th.
TAIWAN_MONTHLY_REVENUE = {"TW": ("TWSE", "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"),
                          "TWO": ("TPEX", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O")}


def taiwan_monthly_revenue(symbols: Iterable[str], fetch_json: Callable[[str], Any] | None = None) -> dict[str, dict[str, Any]]:
    """Symbol -> the exchange's monthly revenue row for Taiwan listings (operator 2026-09-26: non-US fundamentals were
    Yahoo-only): the month's and the year-to-date year-on-year change. Shown beside the Yahoo quarter (a different
    period), never differenced against or substituted for it; a feed that cannot be read leaves its listings Yahoo-only."""
    wanted: dict[str, dict[str, str]] = {}
    for symbol in symbols:
        code, _, suffix = symbol.partition(".")
        if suffix in TAIWAN_MONTHLY_REVENUE:
            wanted.setdefault(suffix, {})[code] = symbol

    def get(url: str) -> Any:
        if fetch_json:
            return fetch_json(url)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (InvestorIntelligence public observation)",
                                                       "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed public HTTPS feeds
            return json.loads(response.read().decode("utf-8-sig"))

    def change(value: Any) -> float | None:  # the feeds give percent strings such as "525.3153"
        number = _finite(str(value).replace(",", "").strip()) if value not in (None, "") else None
        return round(number / 100, 6) if number is not None else None

    out: dict[str, dict[str, Any]] = {}
    for suffix, codes in wanted.items():
        source_id, url = TAIWAN_MONTHLY_REVENUE[suffix]
        try:
            rows = get(url)
        except Exception:
            continue
        for row in rows if isinstance(rows, list) else []:
            symbol = codes.get(str(row.get("公司代號", "")).strip()) if isinstance(row, dict) else None
            roc = str(row.get("資料年月", "")).strip() if symbol else ""
            if not symbol or not re.fullmatch(r"[0-9]{4,5}", roc) or not 1 <= int(roc[-2:]) <= 12:  # ASCII digits only
                continue
            yoy, cumulative = change(row.get("營業收入-去年同月增減(%)")), change(row.get("累計營業收入-前期比較增減(%)"))
            if yoy is None and cumulative is None:
                continue
            out[symbol] = {"source_id": source_id, "source_url": url, "period": f"{int(roc[:-2]) + 1911}-{int(roc[-2:]):02d}",
                           "revenue_yoy": yoy, "cumulative_yoy": cumulative, "currency": "TWD"}
    return out


# Nasdaq Stockholm issuers publish interim reports (EU MAR) through Cision; news.cision.com's robots.txt allows the release
# RSS and pages. One RSS read a day, the release page only when a new report appears; only the figures and the URL are kept.
CISION_ISSUERS = {"SIVE.ST": "sivers-semiconductors"}
CISION_RSS = "https://news.cision.com/{slug}/rss/releases"
CISION_RSS_MIN_HOURS = 20
CISION_PARSER_VERSION = 5  # 5: blocks come from the markup only (4: the section heading names the quarter); older checks discarded
_REPORT_TITLE = re.compile(r"\binterim report\b|\byear-end report\b|\breports?\s+Q[1-4]\s+20\d{2}\s+results\b", re.I)
_NET_SALES = re.compile(r"Net sales (?:amounted to|of|was|were|totalled|totaled)\s+SEK\s*(\d[\d,]*(?:\.\d+)?)\s*(?:m|million|MSEK)\b\s*\((\d[\d,]*(?:\.\d+)?)\)", re.I)


def _report_period(title: str) -> str | None:
    """Report period from a release title that names its quarter: "Reports Q2 2026 Results" -> 2026-Q2, "Interim Report
    Q1, January - March 2026" -> 2026-Q1. A year-end report without a quarter gives None: its first net-sales figure may
    be the full year."""
    year, quarter = re.search(r"\b(20\d{2})\b", title), re.search(r"\bQ([1-4])\b", title)
    return f"{year.group(1)}-Q{quarter.group(1)}" if year and quarter else None


_ORDINAL = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_MONTH = "(" + "|".join(m.capitalize() for m in _MONTHS) + ")"
# Every period label a report can put on a section or a figure, with or without a year: a named quarter, Q1-Q4, a month
# range, or a cumulative period. Only a label with a year that is exactly one calendar quarter can prove scope.
_PERIOD_LABEL = re.compile(r"\b(first|second|third|fourth) quarter(?: of)?,?(?: (20\d\d))?\b"
                           r"|\bQ([1-4])(?:\s+(20\d\d))?\b"
                           r"|\b" + _MONTH + r"\s*[-\u2013\u2014]\s*" + _MONTH + r"(?:,?\s+(20\d\d))?\b"
                           r"|full[- ]year|twelve months|\b(?:six|nine|12|6|9)[- ]months?\b|first half|year[- ]to[- ]date|\bH1\b|\b9M\b",
                           re.I)
_BLOCK_TAG = re.compile(r"</?(?:h[1-6]|p|li|div|br|tr|td|th|ul|ol|table|section|article|header|footer)\b[^>]*>", re.I)


def _label_quarter(label: re.Match) -> str | None:
    """"2025-Q4" for "fourth quarter of 2025", "Q4 2025" or "October - December 2025"; None for a label without a year, a
    partial or cumulative period."""
    if label.group(1) and label.group(2):
        return f"{label.group(2)}-Q{_ORDINAL[label.group(1).lower()]}"
    if label.group(3) and label.group(4):
        return f"{label.group(4)}-Q{label.group(3)}"
    if label.group(5) and label.group(7):
        first, last = _MONTHS.index(label.group(5).lower()), _MONTHS.index(label.group(6).lower())
        if first % 3 == 0 and last == first + 2:
            return f"{label.group(7)}-Q{first // 3 + 1}"
    return None


def _report_blocks(page: str) -> list[tuple[bool, str]]:
    """The page as (is_heading, text) blocks: h1-h6, or a short line without a closing full stop ("January - December")."""
    body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page)
    body = re.sub(r"\s+", " ", body)  # source line breaks are not blocks; only the markup is
    body = _BLOCK_TAG.sub("\n", re.sub(r"(?i)<h[1-6]\b[^>]*>", "\n\x00", body))
    blocks = []
    for raw in body.split("\n"):
        heading = raw.lstrip().startswith("\x00")
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw.replace("\x00", " ")))).strip()
        if text:
            blocks.append((heading or (len(text) <= 80 and not text.endswith(".")), text))
    return blocks


def _report_check(title: str, link: str, page: str) -> dict[str, Any] | None:
    """The cross-check from one report page, only when its quarterly scope is established: the title names the quarter, net
    sales are stated exactly once, every period label in that statement's own block is the quarter, and the last heading
    before it that carries any period label names exactly that quarter with its year (a later section "January - December",
    "July - September" or "Q3", with or without a year, withholds it). Prose elsewhere never sets scope. Anything else stays
    Yahoo-only."""
    period = _report_period(title)
    blocks = _report_blocks(page)
    figures = [(index, match) for index, (_, text) in enumerate(blocks) for match in _NET_SALES.finditer(text)]
    if not period or len(figures) != 1:
        return None
    index, sales = figures[0]
    own = [_label_quarter(label) for label in _PERIOD_LABEL.finditer(blocks[index][1])]
    if any(quarter != period for quarter in own):
        return None
    headed = [labels for heading, text in blocks[:index] if heading and (labels := list(_PERIOD_LABEL.finditer(text)))]
    scoped = bool(headed) and all(_label_quarter(label) == period for label in headed[-1])
    if not (scoped or own) or (headed and not scoped):
        return None
    current, prior = (float(value.replace(",", "")) for value in sales.groups())
    if prior <= 0:
        return None
    return {"source_id": "CISION", "source_url": link, "period": period, "revenue_yoy": round(current / prior - 1, 6),
            "cumulative_yoy": None, "currency": "SEK"}


def cision_interim_revenue(symbols: Iterable[str], now: datetime, fetch_text: Callable[[str], str] | None = None,
                           cache_path: Path | None = CISION_CACHE, *, captured_cache=None, output_store=None) -> dict[str, dict[str, Any]]:
    """Symbol -> the latest interim report's net sales change from the issuer's own Cision release ("Net sales amounted
    to SEK 53.8 m (61.4)"), beside the Yahoo quarter. The feed is read at most once in CISION_RSS_MIN_HOURS and a new
    report's page at most three times, counted before each request so failures count too; the last good report keeps
    serving meanwhile. Nothing is guessed."""
    def get(url: str) -> str:
        if fetch_text:
            return fetch_text(url)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (InvestorIntelligence public observation)"})
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed public HTTPS host
            return response.read().decode("utf-8-sig", "replace")

    try:
        cache = (json.loads(captured_cache.read_text()) if captured_cache is not None and captured_cache.exists() else
                 json.loads(cache_path.read_text(encoding="utf-8")) if cache_path and cache_path.exists() else {})
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}

    def save() -> None:
        if output_store is not None:
            import revenue_guidance_overlay
            if type(output_store) is not revenue_guidance_overlay.B1Outputs:
                raise ValueError("CISION_OUTPUT_OPERAND")
            output_store.save_cision(json.dumps(cache, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        elif cache_path:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError:
                pass

    out: dict[str, dict[str, Any]] = {}
    for symbol in [s for s in symbols if s in CISION_ISSUERS]:
        entry = dict(cache.get(symbol)) if isinstance(cache.get(symbol), dict) else {}
        if entry.get("parser") != CISION_PARSER_VERSION:
            entry = {"parser": CISION_PARSER_VERSION}  # re-read the feed and the report with the current rules
        cache[symbol] = entry
        try:
            read_at = datetime.strptime(str(entry.get("rss_read_at")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            read_at = None
        if read_at is None or now - read_at >= timedelta(hours=CISION_RSS_MIN_HOURS):
            entry["rss_read_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            save()  # the attempt counts even if the request fails
            try:
                items = ET.fromstring(get(CISION_RSS.format(slug=CISION_ISSUERS[symbol]))).findall("./channel/item")
                reports = [(item.findtext("title") or "", item.findtext("link") or "") for item in items
                           if _REPORT_TITLE.search(item.findtext("title") or "")
                           and not re.search(r"\binvitation\b", item.findtext("title") or "", re.I)]
                title, link = reports[0] if reports else ("", "")  # the feed lists the newest release first
                if link.startswith("https://news.cision.com/") and link != entry.get("link"):
                    if entry.get("pending") != link:
                        entry["pending"], entry["attempts"] = link, 0
                    if entry["attempts"] < 3:
                        entry["attempts"] += 1
                        save()
                        check = _report_check(title, link, get(link))
                        if check:  # a new report replaces the last good one only once it has been read
                            entry.update(link=link, check=check, pending=None, attempts=0)
            except Exception:
                pass  # the last good report, if any, keeps serving
        if isinstance(entry.get("check"), dict):
            out[symbol] = entry["check"]
    save()
    return out


def korea_ir_revenue(symbol: str, quarter_end: str | None, path: Path = KOREA_FUNDAMENTALS) -> dict[str, Any] | None:
    """The company's own IR revenue for the same quarter as the card (config/korea-ir-fundamentals-v1.json), or None when
    the config has no entry for that quarter."""
    try:
        entry = load_json(path).get("companies", {}).get(symbol)
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or not quarter_end or entry.get("period_end") != quarter_end:
        return None
    revenue = entry.get("revenue") or {}
    current, prior = _finite(revenue.get("amount")), _finite(revenue.get("prior"))
    if not current or not prior or prior <= 0 or not str(entry.get("source_url", "")).startswith("https://"):
        return None
    return {"source_id": "COMPANY_IR_KR", "source_url": entry["source_url"], "period": entry["period"],
            "revenue_yoy": round(current / prior - 1, 6), "cumulative_yoy": None, "currency": revenue.get("currency", "KRW")}


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


def long_term_gate(market: dict[str, Any] | None) -> tuple[float | None, list[str]]:
    """The long-term eligibility gate (not a score component): the two-year CAGR, else the verified since-regular-way
    figure; it must be positive. A missing figure is not a negative return: an unverified short history and a verified
    segment under one year are told apart."""
    long_term = (market or {}).get("cagr_2y")
    long_term = long_term if long_term is not None else (market or {}).get("cagr_listed")
    if long_term is None:
        unknown = not market or (market.get("lineage") or {}).get("kind", "UNKNOWN") == "UNKNOWN"
        return None, ["HISTORY_OR_LINEAGE_UNVERIFIED" if unknown else "MARKET_HISTORY_UNDER_1Y"]
    return long_term, (["LONG_TERM_RETURN_NOT_POSITIVE"] if long_term <= 0 else [])


def build(fetch: Callable[[str], bytes] | None, now: datetime, with_news: bool = True, *, captured=None,
          cision_outputs=None) -> dict[str, Any]:
    if captured is not None:
        from publish_sealed_snapshot import CapturedPublicationInputs
        if type(captured) is not CapturedPublicationInputs:
            raise ValueError("RANKING_CAPTURE_OPERAND")
    layers = load_json(captured.operand("layers") if captured else LAYERS)["layers"]
    source_serenity = captured.operand("serenity") if captured else SERENITY
    source_leopold = captured.operand("leopold") if captured else LEOPOLD
    serenity = load_json(source_serenity) if source_serenity.exists() else {"signals": [], "source": None}
    leopold = load_json(source_leopold) if source_leopold.exists() else {"positions": [], "filing": None}
    serenity_by = {row["symbol"]: row for row in serenity["signals"]}
    leopold_by = {row["ticker"]: row for row in leopold["positions"] if row.get("ticker")}
    ciks = cik_index(captured)
    members: dict[str, dict[str, Any]] = {}
    for layer in layers:
        for capturer in layer["capturers"]:
            members.setdefault(capturer["symbol"], {"layer": layer, "capturer": capturer})
    fx: dict[str, float | None] = {}
    companies: dict[str, dict[str, Any]] = {}
    if captured:
        # These are actual captured exchange responses, not a cached ranking.
        exchange_json = lambda url: json.loads(captured.operand("http/" + url).read_bytes().decode("utf-8-sig"))
        official = {**taiwan_monthly_revenue(members, exchange_json),
                    **cision_interim_revenue(members, now,
                       lambda url: fetch(url).decode("utf-8-sig", "replace"), cache_path=None,
                       captured_cache=captured.operand("cision"), output_store=cision_outputs)}
    else:
        official = {**taiwan_monthly_revenue(members), **cision_interim_revenue(members, now)}
    lineages = listing_lineage.load(captured.operand("lineage") if captured else None)
    for symbol, member in members.items():
        data = (captured_yahoo_data(symbol, captured, lineages.get(symbol), now) if captured else
                yahoo_data(symbol, lineages.get(symbol), as_of=now))
        fund = None
        cik = ciks.get(symbol) if "." not in symbol else None
        if cik:
            facts = companyfacts(cik, fetch, captured=captured)
            fund = sec_fundamentals(symbol, cik, facts) if facts else None
        fund = fund or data.get("fundamentals")
        check = official.get(symbol) or (korea_ir_revenue(symbol, fund.get("quarter_end"),
                 captured.operand("korea_fundamentals") if captured else KOREA_FUNDAMENTALS) if fund else None)
        if fund and check:
            fund = {**fund, "cross_check": check}
        market = data.get("market")
        cap = market.get("market_cap") if market else None
        rate = (captured_usd_rate(market.get("currency") if market else None, captured, fx) if captured else
                usd_rate(market.get("currency") if market else None, fx))
        companies[symbol] = {"symbol": symbol, "name": data.get("name") or member["capturer"].get("role"), "layer": member["layer"]["id"],
                             "role": member["capturer"]["role"], "role_zh": member["capturer"].get("role_zh"),
                             "role_source": {"url": member["capturer"]["source_url"], "date": member["capturer"]["source_date"]},
                             "outlook": outlook(symbol, fund, data.get("consensus"),
                                                 nasdaq_consensus(symbol, (data.get("market") or {}).get("price"),
                                                     (lambda url: json.loads(captured.operand("http/" + url).read_text())) if captured else None),
                                                 captured=captured),
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
                         "leopold_constraint": layer["leopold_constraint"], "leopold_constraint_zh": layer.get("leopold_constraint_zh"),
                         "heat": round(heat, 2), "explosiveness": round(leopold_score, 1),
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
        long_term, reasons = long_term_gate(market)
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
