#!/usr/bin/env python3
"""Multi-source evidence-independence gate for Investor Intelligence v2.1.3.

This stage does not replace the accepted deterministic calculations. It audits
claim-level source independence, independently corroborates Yahoo/yfinance market
returns with non-Yahoo providers, records conflicts instead of averaging them
away, and produces the public-logic fidelity context consumed by the local LLM.

No API key is required for Stooq, Nasdaq or FRED. Optional Alpha Vantage support
is enabled only when ALPHAVANTAGE_API_KEY is already present in the environment.
Cached public observations may be reused for up to 72 hours so a transient source
outage cannot silently collapse the system back to a single provider.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import os
import re
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOP20 = ROOT / "data" / "cache" / "top20_public_latest.json"
DEFAULT_REPORT = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
DEFAULT_ORDER = ROOT / "data" / "cache" / "v213_order_evidence_runtime.json"
DEFAULT_POLICY = ROOT / "config" / "v213-serenity-public-logic-policy.json"
DEFAULT_CACHE = ROOT / "data" / "cache" / "v213_source_observation_cache.json"
DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_source_independence_latest.json"
USER_AGENT = "InvestorIntelligence/2.1.3 multi-source public-data audit"
CACHE_MAX_AGE_SECONDS = 72 * 3600
PRIMARY_FAMILIES = {"regulator_filing", "issuer_primary", "official_macro", "exchange_sro"}
SENSITIVE_RE = re.compile(
    r"(?:chokepoint|bottleneck|scarcity|dependency|capacity|qualification|"
    r"backlog|remaining performance obligation|\brpo\b|order book|pricing|"
    r"customer concentration|dilution|financing|architecture bypass|competitor)",
    re.I,
)


class SourceGateError(RuntimeError):
    pass


@dataclass
class Observation:
    provider: str
    family: str
    url: str
    status: str
    observed_at: str
    as_of: str = ""
    long_term_return_pct: float | None = None
    short_term_return_pct: float | None = None
    error: str = ""
    cache_age_seconds: int | None = None


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        try:
            return dt.datetime.combine(dt.date.fromisoformat(value[:10]), dt.time(), tzinfo=dt.timezone.utc)
        except ValueError:
            return None


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        if default is not None:
            return default
        raise SourceGateError(f"Missing required JSON: {path}")
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceGateError(f"Unable to parse JSON: {path}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, dict) and isinstance(value.get("records"), list):
        raw = value["records"]
    elif isinstance(value, dict) and isinstance(value.get("top20"), list):
        raw = value["top20"]
    else:
        raise SourceGateError("Top20 document must be a list or contain records/top20")
    result = [dict(item) for item in raw if isinstance(item, dict) and str(item.get("ticker") or "").strip()]
    if len(result) != 20:
        raise SourceGateError(f"Expected 20 Top20 records, found {len(result)}")
    return result


def report_index(value: Any) -> dict[str, dict[str, Any]]:
    raw = value.get("records") if isinstance(value, dict) else None
    if not isinstance(raw, list):
        return {}
    return {
        str(item.get("ticker") or "").upper(): dict(item)
        for item in raw if isinstance(item, dict) and item.get("ticker")
    }


def registrable_domain(host: str) -> str:
    host = host.lower().strip(".")
    labels = host.split(".") if host else []
    if len(labels) <= 2:
        return host or "unknown"
    suffix2 = ".".join(labels[-2:])
    if suffix2 in {"co.uk", "com.au", "co.jp", "com.cn", "com.tw", "co.kr"}:
        return ".".join(labels[-3:])
    return suffix2


def domain_of(url: str) -> str:
    try:
        return registrable_domain(urllib.parse.urlsplit(url).hostname or "")
    except Exception:
        return "unknown"


def normalize_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        query = [
            (key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in {"ref", "source"}
        ]
        return urllib.parse.urlunsplit((
            parsed.scheme.lower(), parsed.netloc.lower(), parsed.path,
            urllib.parse.urlencode(query), "",
        ))
    except Exception:
        return url.strip()


def family_for(source_id: str, url: str) -> str:
    sid = source_id.lower()
    domain = domain_of(url)
    lower_url = url.lower()
    if domain == "sec.gov" or "edgar" in sid or sid.startswith("sec"):
        return "regulator_filing"
    if domain in {"fred.stlouisfed.org", "federalreserve.gov", "bls.gov", "bea.gov", "census.gov", "eia.gov"}:
        return "official_macro"
    if domain in {"finra.org", "cboe.com", "nyse.com"}:
        return "exchange_sro"
    if domain == "nasdaq.com" and "historical" in lower_url:
        return "nasdaq_market"
    if domain == "nasdaq.com":
        return "exchange_sro"
    if domain == "yahoo.com" or "yfinance" in sid or "yahoo" in sid:
        return "yahoo_market"
    if domain == "stooq.com" or "stooq" in sid:
        return "stooq_market"
    if domain == "alphavantage.co" or "alpha_vantage" in sid:
        return "alpha_vantage_market"
    if any(token in sid for token in ("issuer", "company_ir", "press_release", "earnings_release")):
        return "issuer_primary"
    if domain != "unknown" and any(token in lower_url for token in ("investor", "/ir/", "newsroom", "press-release")):
        return "issuer_primary"
    if any(token in sid for token in ("reuters", "ap_news", "bloomberg", "wsj", "financial_times")):
        return "reputable_secondary"
    if "serenity" in sid:
        return "serenity_public_source"
    if any(token in sid for token in ("twitter", "x_post", "reddit", "social")):
        return "author_statement"
    return "secondary_or_other"


def source_record(source_id: str, claim_type: str, title: str, url: str, as_of: str) -> dict[str, Any]:
    normalized = normalize_url(url)
    family = family_for(source_id, normalized)
    return {
        "source_id": source_id or "unknown",
        "claim_type": claim_type or "unknown",
        "title": title[:300],
        "url": normalized,
        "domain": domain_of(normalized),
        "family": family,
        "as_of": as_of,
        "primary": family in PRIMARY_FAMILIES,
    }


def evidence_sources(record: Mapping[str, Any], order: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    evidence = record.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if url.startswith("https://"):
                output.append(source_record(
                    str(item.get("source_id") or "unknown"),
                    str(item.get("claim_type") or "unknown"),
                    str(item.get("title") or ""),
                    url,
                    str(item.get("as_of") or ""),
                ))
    for key, claim in (
        ("current_order_source_urls", "current_orders"),
        ("future_order_source_urls", "future_orders_estimate"),
    ):
        urls = order.get(key)
        if isinstance(urls, list):
            for url in urls:
                text = str(url or "")
                if text.startswith("https://"):
                    output.append(source_record("order_evidence", claim, claim, text, str(order.get("orders_as_of") or "")))
    deduplicated: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in output:
        key = (str(item["domain"]), str(item["family"]), str(item["claim_type"]))
        deduplicated.setdefault(key, item)
    return list(deduplicated.values())


def fetch_text(url: str, timeout: int = 18) -> str:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/csv;q=0.9,*/*;q=0.5",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig", errors="strict")


def nearest(rows_: list[tuple[dt.date, float]], date: dt.date) -> float | None:
    values = [price for observed, price in rows_ if observed <= date]
    return values[-1] if values else None


def calculate_returns(rows_: Iterable[tuple[dt.date, float]]) -> tuple[str, float | None, float | None]:
    clean = sorted(
        (date, price) for date, price in rows_
        if price > 0 and math.isfinite(price)
    )
    if len(clean) < 2:
        return "", None, None
    last_date, last_price = clean[-1]
    price_6m = nearest(clean, last_date - dt.timedelta(days=183))
    price_2y = nearest(clean, last_date - dt.timedelta(days=730))
    short = ((last_price / price_6m) - 1.0) * 100.0 if price_6m else None
    long = (((last_price / price_2y) ** 0.5) - 1.0) * 100.0 if price_2y else None
    return last_date.isoformat(), long, short


def observe_stooq(ticker: str) -> Observation:
    today = dt.date.today()
    symbol = ticker.lower().replace(".", "-") + ".us"
    url = "https://stooq.com/q/d/l/?" + urllib.parse.urlencode({
        "s": symbol,
        "d1": (today - dt.timedelta(days=800)).strftime("%Y%m%d"),
        "d2": today.strftime("%Y%m%d"),
        "i": "d",
    })
    try:
        parsed: list[tuple[dt.date, float]] = []
        for item in csv.DictReader(io.StringIO(fetch_text(url))):
            try:
                parsed.append((dt.date.fromisoformat(str(item.get("Date") or "")), float(item.get("Close") or "nan")))
            except (TypeError, ValueError):
                continue
        as_of, long, short = calculate_returns(parsed)
        if not as_of:
            raise SourceGateError("no usable daily prices")
        return Observation("stooq_daily_csv", "stooq_market", url, "LIVE", iso_now(), as_of, long, short)
    except Exception as exc:
        return Observation("stooq_daily_csv", "stooq_market", url, "UNAVAILABLE", iso_now(), error=str(exc)[:300])


def nasdaq_price(value: Any) -> float:
    return float(re.sub(r"[^0-9.\-]", "", str(value or "")))


def observe_nasdaq(ticker: str) -> Observation:
    today = dt.date.today()
    query = urllib.parse.urlencode({
        "assetclass": "stocks",
        "fromdate": (today - dt.timedelta(days=800)).strftime("%m/%d/%Y"),
        "todate": today.strftime("%m/%d/%Y"),
        "limit": "5000",
    })
    url = f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(ticker)}/historical?{query}"
    try:
        payload = json.loads(fetch_text(url))
        data = payload.get("data") if isinstance(payload, dict) else None
        table = data.get("tradesTable") if isinstance(data, dict) else None
        raw = table.get("rows") if isinstance(table, dict) else None
        parsed: list[tuple[dt.date, float]] = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                try:
                    parsed.append((
                        dt.datetime.strptime(str(item.get("date") or ""), "%m/%d/%Y").date(),
                        nasdaq_price(item.get("close")),
                    ))
                except (TypeError, ValueError):
                    continue
        as_of, long, short = calculate_returns(parsed)
        if not as_of:
            raise SourceGateError("no usable historical prices")
        return Observation("nasdaq_historical_api", "nasdaq_market", url, "LIVE", iso_now(), as_of, long, short)
    except Exception as exc:
        return Observation("nasdaq_historical_api", "nasdaq_market", url, "UNAVAILABLE", iso_now(), error=str(exc)[:300])


def observe_alpha_vantage(ticker: str, key: str) -> Observation:
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode({
        "function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": ticker,
        "outputsize": "full", "apikey": key,
    })
    safe_url = re.sub(r"apikey=[^&]+", "apikey=<redacted>", url)
    try:
        payload = json.loads(fetch_text(url, timeout=30))
        series = payload.get("Time Series (Daily)") if isinstance(payload, dict) else None
        parsed: list[tuple[dt.date, float]] = []
        if isinstance(series, dict):
            for date_text, item in series.items():
                if not isinstance(item, dict):
                    continue
                try:
                    parsed.append((dt.date.fromisoformat(date_text), float(item.get("5. adjusted close") or "nan")))
                except (TypeError, ValueError):
                    continue
        as_of, long, short = calculate_returns(parsed)
        if not as_of:
            raise SourceGateError("no usable adjusted prices")
        return Observation("alpha_vantage_adjusted", "alpha_vantage_market", safe_url, "LIVE", iso_now(), as_of, long, short)
    except Exception as exc:
        return Observation("alpha_vantage_adjusted", "alpha_vantage_market", safe_url, "UNAVAILABLE", iso_now(), error=str(exc)[:300])


def observe_fred() -> dict[str, Any]:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10,FEDFUNDS,CPIAUCSL"
    try:
        text = fetch_text(url, timeout=20)
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            raise SourceGateError("no macro rows")
        return {
            "provider": "fred_official_macro",
            "family": "official_macro",
            "domain": "fred.stlouisfed.org",
            "url": url,
            "status": "LIVE",
            "observed_at": iso_now(),
            "row_count": len(lines) - 1,
        }
    except Exception as exc:
        return {
            "provider": "fred_official_macro", "family": "official_macro",
            "domain": "fred.stlouisfed.org", "url": url,
            "status": "UNAVAILABLE", "observed_at": iso_now(),
            "error": str(exc)[:300],
        }


def cache_key(ticker: str, provider: str) -> str:
    return ticker.upper() + "::" + provider


def from_cache(raw: Mapping[str, Any], ticker: str, provider: str) -> Observation | None:
    item = raw.get(cache_key(ticker, provider))
    if not isinstance(item, dict):
        return None
    observed = parse_time(str(item.get("observed_at") or ""))
    if observed is None:
        return None
    age = int((now_utc() - observed).total_seconds())
    if age < -300 or age > CACHE_MAX_AGE_SECONDS:
        return None
    try:
        result = Observation(**{key: item.get(key) for key in Observation.__dataclass_fields__})
        result.status = "CACHED"
        result.cache_age_seconds = age
        return result
    except TypeError:
        return None


def resolve_observation(live: Observation, cache: Mapping[str, Any], ticker: str) -> Observation:
    if live.status == "LIVE":
        return live
    cached = from_cache(cache, ticker, live.provider)
    return cached or live


def conflict(reference: Any, observed: float | None, tolerance: float) -> bool:
    if reference is None or observed is None:
        return False
    try:
        return abs(float(reference) - observed) > tolerance
    except (TypeError, ValueError):
        return False


def build_record(
    record: Mapping[str, Any], report: Mapping[str, Any], order: Mapping[str, Any],
    observations: list[Observation], policy: Mapping[str, Any], macro: Mapping[str, Any],
) -> dict[str, Any]:
    ticker = str(record.get("ticker") or "").upper()
    sources = evidence_sources(record, order)
    sources.append(source_record(
        "yfinance_adjusted_close", "market_return_calculation", "Adjusted-close calculation source",
        f"https://finance.yahoo.com/quote/{urllib.parse.quote(ticker)}/history",
        str(report.get("retrieved_at") or record.get("as_of") or ""),
    ))
    if macro.get("status") in {"LIVE", "CACHED"}:
        sources.append(source_record(
            "fred_official_macro", "macro_context", "Official macro context",
            str(macro.get("url") or ""), str(macro.get("observed_at") or ""),
        ))
    for observation in observations:
        if observation.status in {"LIVE", "CACHED"}:
            sources.append(source_record(
                observation.provider, "independent_market_corroboration",
                "Independent market-path corroboration", observation.url, observation.as_of,
            ))

    independent_units: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in sources:
        independent_units.setdefault((
            str(item["family"]), str(item["domain"]), str(item["claim_type"]),
        ), item)
    sources = list(independent_units.values())
    families = sorted({str(item["family"]) for item in sources})
    domains = sorted({str(item["domain"]) for item in sources if item["domain"] != "unknown"})
    primary = [item for item in sources if item["primary"]]
    dated_count = sum(1 for item in sources if parse_time(str(item.get("as_of") or ""))) is not None)
    dated_ratio = dated_count / len(sources) if sources else 0.0
    family_counts: dict[str, int] = {}
    for item in sources:
        family = str(item["family"])
        family_counts[family] = family_counts.get(family, 0) + 1
    max_share = max(family_counts.values()) / len(sources) if sources else 1.0

    market_policy = policy.get("market_data") if isinstance(policy.get("market_data"), dict) else {}
    long_tolerance = float(market_policy.get("long_term_absolute_tolerance_percentage_points", 30.0))
    short_tolerance = float(market_policy.get("short_term_absolute_tolerance_percentage_points", 18.0))
    market_rows: list[dict[str, Any]] = []
    conflicting: list[str] = []
    independent_market_count = 0
    for observation in observations:
        long_conflict = conflict(report.get("long_term_return_pct"), observation.long_term_return_pct, long_tolerance)
        short_conflict = conflict(report.get("short_term_return_pct"), observation.short_term_return_pct, short_tolerance)
        if observation.status in {"LIVE", "CACHED"}:
            independent_market_count += 1
            if long_conflict or short_conflict:
                conflicting.append(observation.provider)
        value = asdict(observation)
        value["long_term_conflict"] = long_conflict
        value["short_term_conflict"] = short_conflict
        market_rows.append(value)

    evidence_text = " ".join(
        str(item.get("claim_type") or "") + " " + str(item.get("title") or "")
        for item in record.get("evidence", []) if isinstance(item, dict)
    ) + " " + str(report.get("current_orders") or "") + " " + str(report.get("future_orders_estimate") or "")
    sensitive_claim = bool(SENSITIVE_RE.search(evidence_text))
    independent_inference = len(families) >= 2 and len(primary) >= 1
    high_confidence = independent_inference and independent_market_count >= 1 and not conflicting

    missing: list[str] = []
    if independent_market_count == 0:
        missing.append("NON_YAHOO_MARKET_CORROBORATION")
    if not primary:
        missing.append("PRIMARY_OR_OFFICIAL_SOURCE")
    if len(families) < 2:
        missing.append("INDEPENDENT_SOURCE_FAMILY")
    if dated_ratio < 0.8:
        missing.append("DATED_EVIDENCE_COVERAGE")
    if max_share > 0.7:
        missing.append("SOURCE_FAMILY_CONCENTRATION")
    if conflicting:
        missing.append("MARKET_SOURCE_CONFLICT_REVIEW")

    independence_score = 0.0
    independence_score += min(30.0, len(families) * 10.0)
    independence_score += min(20.0, len(domains) * 5.0)
    independence_score += 20.0 if primary else 0.0
    independence_score += min(20.0, independent_market_count * 10.0)
    independence_score += min(10.0, dated_ratio * 10.0)
    independence_score -= 20.0 if conflicting else 0.0
    independence_score -= 10.0 if max_share > 0.7 else 0.0
    independence_score = round(max(0.0, min(100.0, independence_score)), 1)

    public_logic = {
        "serenity_source_view": "SUPPORTED" if "serenity_public_source" in families else "NOT_ATTACHED",
        "architecture": "EVIDENCE_FORMING" if sensitive_claim and independent_inference else "UNPROVEN",
        "dependency_graph": "EVIDENCE_FORMING" if sensitive_claim and independent_inference else "UNPROVEN",
        "bottleneck_or_expansion": "EVIDENCE_FORMING" if sensitive_claim and independent_inference else "UNPROVEN",
        "company_capture": "EVIDENCE_FORMING" if independent_inference else "UNPROVEN",
        "valuation_expectations": "EVIDENCE_FORMING" if independent_market_count else "LIMITED_SINGLE_MARKET_SOURCE",
        "thesis_killers": "REVIEW_REQUIRED",
        "lifecycle": "EVIDENCE_FORMING" if independent_inference else "UNPROVEN",
        "model_inference_confidence": "HIGH_ELIGIBLE" if high_confidence else "LIMITED",
        "system_operationalization_is_official_serenity_score": False,
        "private_method_reproduction_claimed": False,
    }
    return {
        "rank": record.get("rank"),
        "ticker": ticker,
        "evidence_independence_score": independence_score,
        "source_metrics": {
            "unique_independent_units": len(sources),
            "independent_families": len(families),
            "independent_domains": len(domains),
            "primary_or_official_sources": len(primary),
            "dated_evidence_ratio": round(dated_ratio, 4),
            "maximum_single_family_share": round(max_share, 4),
            "families": families,
            "domains": domains,
        },
        "market_corroboration": {
            "calculation_provider": "yfinance_adjusted_close",
            "calculation_provider_role": "compatibility_calculation_only_not_thesis_evidence",
            "independent_provider_count": independent_market_count,
            "status": "CONFLICT_REVIEW" if conflicting else ("CORROBORATED" if independent_market_count else "UNAVAILABLE"),
            "providers": market_rows,
        },
        "public_logic_state": public_logic,
        "missing_or_review": missing,
        "eligible_for_high_confidence_model_inference": high_confidence,
        "sensitive_claim_present": sensitive_claim,
        "sources": sources,
    }


def build(
    top20: list[dict[str, Any]], reports: Mapping[str, Mapping[str, Any]],
    orders: Mapping[str, Mapping[str, Any]], policy: Mapping[str, Any],
    cache: Mapping[str, Any], offline: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tickers = [str(item.get("ticker") or "").upper() for item in top20]
    alpha_key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
    resolved: dict[str, list[Observation]] = {}
    live_cache: dict[str, Any] = dict(cache)
    macro = {
        "provider": "fred_official_macro", "family": "official_macro",
        "domain": "fred.stlouisfed.org", "url": "https://fred.stlouisfed.org",
        "status": "OFFLINE_TEST" if offline else "UNAVAILABLE", "observed_at": iso_now(),
    } if offline else observe_fred()

    def collect(ticker: str) -> tuple[str, list[Observation]]:
        if offline:
            observations = [
                Observation("stooq_daily_csv", "stooq_market", "https://stooq.com", "CACHED", iso_now(), cache_age_seconds=0),
                Observation("nasdaq_historical_api", "nasdaq_market", "https://api.nasdaq.com", "UNAVAILABLE", iso_now(), error="offline fixture"),
            ]
            return ticker, observations
        live = [observe_stooq(ticker), observe_nasdaq(ticker)]
        if alpha_key:
            live.append(observe_alpha_vantage(ticker, alpha_key))
        return ticker, [resolve_observation(item, cache, ticker) for item in live]

    if offline:
        for ticker in tickers:
            key, observations = collect(ticker)
            resolved[key] = observations
    else:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(collect, ticker): ticker for ticker in tickers}
            for future in as_completed(futures):
                ticker, observations = future.result()
                resolved[ticker] = observations
                print(f"II_PROGRESS source independence {len(resolved)}/20 | {ticker}", flush=True)

    for ticker, observations in resolved.items():
        for observation in observations:
            if observation.status == "LIVE":
                live_cache[cache_key(ticker, observation.provider)] = asdict(observation)

    states = [
        build_record(
            record,
            reports.get(str(record.get("ticker") or "").upper(), {}),
            orders.get(str(record.get("ticker") or "").upper(), {}),
            resolved.get(str(record.get("ticker") or "").upper(), []),
            policy,
            macro,
        )
        for record in top20
    ]
    all_sources = [source for state in states for source in state["sources"]]
    families = sorted({str(source["family"]) for source in all_sources})
    domains = sorted({str(source["domain"]) for source in all_sources if source["domain"] != "unknown"})
    family_counts: dict[str, int] = {}
    for source in all_sources:
        family = str(source["family"])
        family_counts[family] = family_counts.get(family, 0) + 1
    max_share = max(family_counts.values()) / len(all_sources) if all_sources else 1.0
    market_covered = sum(1 for state in states if state["market_corroboration"]["independent_provider_count"] >= 1)
    primary_covered = sum(1 for state in states if state["source_metrics"]["primary_or_official_sources"] >= 1)
    portfolio = {
        "ticker_count": 20,
        "independent_source_families": len(families),
        "independent_domains": len(domains),
        "source_families": families,
        "source_domains": domains,
        "non_yahoo_market_coverage_ratio": round(market_covered / 20.0, 4),
        "primary_or_official_coverage_ratio": round(primary_covered / 20.0, 4),
        "maximum_single_family_share": round(max_share, 4),
        "market_conflict_ticker_count": sum(1 for state in states if state["market_corroboration"]["status"] == "CONFLICT_REVIEW"),
        "high_confidence_model_inference_eligible_count": sum(1 for state in states if state["eligible_for_high_confidence_model_inference"]),
        "fred_macro_status": macro.get("status"),
    }
    minimums = policy.get("minimums") if isinstance(policy.get("minimums"), dict) else {}
    violations: list[str] = []
    if not offline:
        if portfolio["independent_source_families"] < int(minimums.get("portfolio_independent_source_families", 3)):
            violations.append("INSUFFICIENT_SOURCE_FAMILIES")
        if portfolio["independent_domains"] < int(minimums.get("portfolio_independent_domains", 3)):
            violations.append("INSUFFICIENT_SOURCE_DOMAINS")
        if portfolio["non_yahoo_market_coverage_ratio"] < float(minimums.get("non_yahoo_market_coverage_ratio", 0.75)):
            violations.append("INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE")
        if portfolio["maximum_single_family_share"] > float(minimums.get("maximum_single_family_share", 0.70)):
            violations.append("SOURCE_FAMILY_CONCENTRATION")
    result = {
        "schema_version": 2,
        "product_version": "2.1.3",
        "policy_version": str(policy.get("policy_version") or "unknown"),
        "generated_at": iso_now(),
        "status": "PASS" if not violations else "FAIL",
        "offline_self_test": offline,
        "portfolio": portfolio,
        "violations": violations,
        "records": states,
        "methodology_notice": {
            "label": "public-logic high-fidelity reconstruction",
            "official_serenity_formula": False,
            "official_serenity_score": False,
            "private_method_reproduced": False,
            "single_source_inference_allowed": False,
            "source_diversity_is_not_truth_by_itself": True,
            "conflicts_require_review": True,
        },
    }
    return result, live_cache


def self_test(policy: Mapping[str, Any]) -> None:
    stamp = iso_now()
    top20: list[dict[str, Any]] = []
    reports: dict[str, dict[str, Any]] = {}
    orders: dict[str, dict[str, Any]] = {}
    for index in range(20):
        ticker = f"T{index:02d}"
        top20.append({
            "rank": index + 1, "ticker": ticker, "as_of": stamp,
            "evidence": [{
                "source_id": "sec_edgar", "claim_type": "xbrl_fact",
                "title": "Synthetic primary fact",
                "url": f"https://www.sec.gov/Archives/edgar/data/{1000000 + index}/synthetic.htm",
                "as_of": stamp,
            }],
        })
        reports[ticker] = {"long_term_return_pct": 20.0, "short_term_return_pct": 5.0, "retrieved_at": stamp}
        orders[ticker] = {"current_order_source_urls": [], "future_order_source_urls": []}
    result, _ = build(top20, reports, orders, policy, {}, True)
    assert result["status"] == "PASS"
    assert len(result["records"]) == 20
    assert result["records"][0]["source_metrics"]["independent_families"] >= 3
    assert result["methodology_notice"]["single_source_inference_allowed"] is False
    assert result["methodology_notice"]["official_serenity_formula"] is False
    assert family_for("yfinance", "https://finance.yahoo.com/quote/NVDA") == "yahoo_market"
    print("V213_SOURCE_INDEPENDENCE_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top20", type=Path, default=DEFAULT_TOP20)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--order-evidence", type=Path, default=DEFAULT_ORDER)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--enforce", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    policy = read_json(args.policy)
    if args.self_test:
        self_test(policy)
        return 0
    top20 = rows(read_json(args.top20))
    reports = report_index(read_json(args.report, {}))
    orders = report_index(read_json(args.order_evidence, {}))
    cache = read_json(args.cache, {})
    if not isinstance(cache, dict):
        cache = {}
    result, updated_cache = build(top20, reports, orders, policy, cache, args.offline)
    write_json(args.cache, updated_cache)
    write_json(args.output, result)
    portfolio = result["portfolio"]
    print(
        "V213_SOURCE_INDEPENDENCE = " + result["status"] +
        f"; families={portfolio['independent_source_families']}" +
        f"; domains={portfolio['independent_domains']}" +
        f"; non_yahoo_market={portfolio['non_yahoo_market_coverage_ratio']:.1%}" +
        f"; primary_official={portfolio['primary_or_official_coverage_ratio']:.1%}" +
        f"; conflicts={portfolio['market_conflict_ticker_count']}",
        flush=True,
    )
    if args.enforce and result["status"] != "PASS":
        raise SourceGateError("Source-independence policy failed: " + ",".join(result["violations"]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SourceGateError as exc:
        print(f"V213_SOURCE_INDEPENDENCE = FAIL; {exc}", file=sys.stderr)
        raise SystemExit(1)
