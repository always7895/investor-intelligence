#!/usr/bin/env python3
"""Source-independent public-logic evidence gate for Investor Intelligence v2.1.3.

The accepted yfinance adjusted-close series remains the compatibility calculation
source.  This gate adds independent public corroboration, classifies evidence by
claim-relevant source family and registrable domain, preserves source conflicts,
and emits a fail-closed sidecar for the local model.

It does not reproduce Serenity's private method, official formula, or official
score.  Source diversity is necessary but is never treated as truth by itself.
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
import sys
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOP20 = ROOT / "data" / "cache" / "top20_public_latest.json"
DEFAULT_REPORT = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
DEFAULT_ORDER = ROOT / "data" / "cache" / "v213_order_evidence_runtime.json"
DEFAULT_POLICY = ROOT / "config" / "v213-serenity-public-logic-policy.json"
DEFAULT_CACHE = ROOT / "data" / "cache" / "v213_source_observation_cache.json"
DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_source_independence_latest.json"

USER_AGENT = "InvestorIntelligence/2.1.3 source-independence audit"
CACHE_MAX_AGE_SECONDS = 72 * 3600

MARKET_FAMILIES = {
    "yahoo_market",
    "stooq_market",
    "nasdaq_market",
    "alpha_vantage_market",
}
PRIMARY_FAMILIES = {
    "regulator_filing",
    "issuer_primary",
    "official_macro",
    "exchange_sro",
}
CLAIM_PRIMARY_FAMILIES = {
    "regulator_filing",
    "issuer_primary",
    "exchange_sro",
}
NON_CLAIM_TYPES = {
    "market_return_calculation",
    "independent_market_corroboration",
    "macro_context",
}
SENSITIVE_RE = re.compile(
    r"(?:chokepoint|bottleneck|scarcity|dependency|capacity|qualification|"
    r"backlog|remaining performance obligation|\brpo\b|order book|pricing|"
    r"customer concentration|dilution|financing|architecture bypass|competitor|"
    r"瓶頸|瓶颈|稀缺|產能|产能|認證|认证|訂單|订单|客戶集中|客户集中|稀釋|稀释)",
    re.I,
)
KNOWN_DOMAIN_SUFFIXES = (
    "sec.gov",
    "yahoo.com",
    "stooq.com",
    "nasdaq.com",
    "alphavantage.co",
    "stlouisfed.org",
    "federalreserve.gov",
    "bls.gov",
    "bea.gov",
    "census.gov",
    "eia.gov",
    "finra.org",
    "cboe.com",
    "nyse.com",
    "reuters.com",
    "apnews.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
)


class SourceGateError(RuntimeError):
    """Expected validation or public-source failure."""


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
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        try:
            return dt.datetime.combine(
                dt.date.fromisoformat(value[:10]),
                dt.time(),
                tzinfo=dt.timezone.utc,
            )
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
    payload = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def extract_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, dict) and isinstance(value.get("records"), list):
        raw = value["records"]
    elif isinstance(value, dict) and isinstance(value.get("top20"), list):
        raw = value["top20"]
    else:
        raise SourceGateError(
            "Top20 document must be a list or contain records/top20"
        )
    result = [
        dict(item)
        for item in raw
        if isinstance(item, dict) and str(item.get("ticker") or "").strip()
    ]
    if len(result) != 20:
        raise SourceGateError(f"Expected 20 Top20 records, found {len(result)}")
    return result


def index_records(value: Any) -> dict[str, dict[str, Any]]:
    raw = value.get("records") if isinstance(value, dict) else None
    if not isinstance(raw, list):
        return {}
    return {
        str(item.get("ticker") or "").upper(): dict(item)
        for item in raw
        if isinstance(item, dict) and str(item.get("ticker") or "").strip()
    }


def registrable_domain(host: str) -> str:
    host = host.lower().strip(".")
    if not host:
        return "unknown"
    for suffix in KNOWN_DOMAIN_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return suffix
    labels = host.split(".")
    if len(labels) <= 2:
        return host
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
            (key, value)
            for key, value in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if not key.lower().startswith("utm_")
            and key.lower() not in {"ref", "source"}
        ]
        return urllib.parse.urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path,
                urllib.parse.urlencode(query),
                "",
            )
        )
    except Exception:
        return url.strip()


def family_for(source_id: str, url: str) -> str:
    source = source_id.lower()
    domain = domain_of(url)
    lowered = url.lower()

    if domain == "sec.gov" or "edgar" in source or source.startswith("sec"):
        return "regulator_filing"
    if domain in {
        "stlouisfed.org",
        "federalreserve.gov",
        "bls.gov",
        "bea.gov",
        "census.gov",
        "eia.gov",
    }:
        return "official_macro"
    if domain in {"finra.org", "cboe.com", "nyse.com"}:
        return "exchange_sro"
    if domain == "nasdaq.com" and "historical" in lowered:
        return "nasdaq_market"
    if domain == "nasdaq.com":
        return "exchange_sro"
    if domain == "yahoo.com" or "yfinance" in source or "yahoo" in source:
        return "yahoo_market"
    if domain == "stooq.com" or "stooq" in source:
        return "stooq_market"
    if domain == "alphavantage.co" or "alpha_vantage" in source:
        return "alpha_vantage_market"
    if any(
        token in source
        for token in (
            "issuer",
            "company_ir",
            "press_release",
            "earnings_release",
            "annual_report",
            "quarterly_report",
        )
    ):
        return "issuer_primary"
    if domain != "unknown" and any(
        token in lowered
        for token in (
            "/investor",
            "investors.",
            "/ir/",
            "newsroom",
            "press-release",
            "earnings-release",
        )
    ):
        return "issuer_primary"
    if domain in {"reuters.com", "apnews.com", "bloomberg.com", "wsj.com", "ft.com"}:
        return "reputable_secondary"
    if any(
        token in source
        for token in (
            "reuters",
            "ap_news",
            "bloomberg",
            "wsj",
            "financial_times",
        )
    ):
        return "reputable_secondary"
    if "serenity" in source:
        return "serenity_public_source"
    if any(
        token in source
        for token in ("twitter", "x_post", "reddit", "social")
    ):
        return "author_statement"
    return "secondary_or_other"


def make_source(
    source_id: str,
    claim_type: str,
    title: str,
    url: str,
    as_of: str,
) -> dict[str, Any]:
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
        "claim_primary": family in CLAIM_PRIMARY_FAMILIES,
    }


def collect_evidence_sources(
    record: Mapping[str, Any],
    order: Mapping[str, Any],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    evidence = record.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url.startswith("https://"):
                continue
            output.append(
                make_source(
                    str(item.get("source_id") or "unknown"),
                    str(item.get("claim_type") or "unknown"),
                    str(item.get("title") or ""),
                    url,
                    str(item.get("as_of") or ""),
                )
            )

    for key, claim_type in (
        ("current_order_source_urls", "current_orders"),
        ("future_order_source_urls", "future_orders_estimate"),
    ):
        urls = order.get(key)
        if not isinstance(urls, list):
            continue
        for raw_url in urls:
            url = str(raw_url or "")
            if not url.startswith("https://"):
                continue
            output.append(
                make_source(
                    "order_evidence",
                    claim_type,
                    claim_type,
                    url,
                    str(order.get("orders_as_of") or ""),
                )
            )

    deduplicated: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in output:
        unit = (
            str(item["domain"]),
            str(item["family"]),
            str(item["claim_type"]),
        )
        deduplicated.setdefault(unit, item)
    return list(deduplicated.values())


def fetch_text(url: str, timeout: int = 18) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/csv;q=0.9,*/*;q=0.5",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig", errors="strict")


def nearest_price(
    price_rows: list[tuple[dt.date, float]],
    target: dt.date,
) -> float | None:
    candidates = [
        price
        for observed_date, price in price_rows
        if observed_date <= target
    ]
    return candidates[-1] if candidates else None


def calculate_returns(
    price_rows: Iterable[tuple[dt.date, float]],
) -> tuple[str, float | None, float | None]:
    clean = sorted(
        (date, price)
        for date, price in price_rows
        if price > 0 and math.isfinite(price)
    )
    if len(clean) < 2:
        return "", None, None

    last_date, last_price = clean[-1]
    price_6m = nearest_price(clean, last_date - dt.timedelta(days=183))
    price_2y = nearest_price(clean, last_date - dt.timedelta(days=730))
    short_term = (
        ((last_price / price_6m) - 1.0) * 100.0
        if price_6m
        else None
    )
    long_term = (
        (((last_price / price_2y) ** 0.5) - 1.0) * 100.0
        if price_2y
        else None
    )
    return last_date.isoformat(), long_term, short_term


def observe_stooq(ticker: str) -> Observation:
    today = dt.date.today()
    symbol = ticker.lower().replace(".", "-") + ".us"
    url = "https://stooq.com/q/d/l/?" + urllib.parse.urlencode(
        {
            "s": symbol,
            "d1": (today - dt.timedelta(days=800)).strftime("%Y%m%d"),
            "d2": today.strftime("%Y%m%d"),
            "i": "d",
        }
    )
    try:
        parsed: list[tuple[dt.date, float]] = []
        for row in csv.DictReader(io.StringIO(fetch_text(url))):
            try:
                parsed.append(
                    (
                        dt.date.fromisoformat(str(row.get("Date") or "")),
                        float(row.get("Close") or "nan"),
                    )
                )
            except (TypeError, ValueError):
                continue
        as_of, long_term, short_term = calculate_returns(parsed)
        if not as_of:
            raise SourceGateError("no usable daily prices")
        return Observation(
            "stooq_daily_csv",
            "stooq_market",
            url,
            "LIVE",
            iso_now(),
            as_of,
            long_term,
            short_term,
        )
    except Exception as exc:
        return Observation(
            "stooq_daily_csv",
            "stooq_market",
            url,
            "UNAVAILABLE",
            iso_now(),
            error=str(exc)[:300],
        )


def parse_nasdaq_price(value: Any) -> float:
    return float(re.sub(r"[^0-9.\-]", "", str(value or "")))


def observe_nasdaq(ticker: str) -> Observation:
    today = dt.date.today()
    query = urllib.parse.urlencode(
        {
            "assetclass": "stocks",
            "fromdate": (today - dt.timedelta(days=800)).strftime("%m/%d/%Y"),
            "todate": today.strftime("%m/%d/%Y"),
            "limit": "5000",
        }
    )
    url = (
        "https://api.nasdaq.com/api/quote/"
        + urllib.parse.quote(ticker)
        + "/historical?"
        + query
    )
    try:
        payload = json.loads(fetch_text(url))
        data = payload.get("data") if isinstance(payload, dict) else None
        table = data.get("tradesTable") if isinstance(data, dict) else None
        raw_rows = table.get("rows") if isinstance(table, dict) else None
        parsed: list[tuple[dt.date, float]] = []
        if isinstance(raw_rows, list):
            for row in raw_rows:
                if not isinstance(row, dict):
                    continue
                try:
                    parsed.append(
                        (
                            dt.datetime.strptime(
                                str(row.get("date") or ""),
                                "%m/%d/%Y",
                            ).date(),
                            parse_nasdaq_price(row.get("close")),
                        )
                    )
                except (TypeError, ValueError):
                    continue
        as_of, long_term, short_term = calculate_returns(parsed)
        if not as_of:
            raise SourceGateError("no usable historical prices")
        return Observation(
            "nasdaq_historical_api",
            "nasdaq_market",
            url,
            "LIVE",
            iso_now(),
            as_of,
            long_term,
            short_term,
        )
    except Exception as exc:
        return Observation(
            "nasdaq_historical_api",
            "nasdaq_market",
            url,
            "UNAVAILABLE",
            iso_now(),
            error=str(exc)[:300],
        )


def observe_alpha_vantage(ticker: str, api_key: str) -> Observation:
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode(
        {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": ticker,
            "outputsize": "full",
            "apikey": api_key,
        }
    )
    safe_url = re.sub(r"apikey=[^&]+", "apikey=<redacted>", url)
    try:
        payload = json.loads(fetch_text(url, timeout=30))
        series = (
            payload.get("Time Series (Daily)")
            if isinstance(payload, dict)
            else None
        )
        parsed: list[tuple[dt.date, float]] = []
        if isinstance(series, dict):
            for date_text, row in series.items():
                if not isinstance(row, dict):
                    continue
                try:
                    parsed.append(
                        (
                            dt.date.fromisoformat(date_text),
                            float(row.get("5. adjusted close") or "nan"),
                        )
                    )
                except (TypeError, ValueError):
                    continue
        as_of, long_term, short_term = calculate_returns(parsed)
        if not as_of:
            raise SourceGateError("no usable adjusted prices")
        return Observation(
            "alpha_vantage_adjusted",
            "alpha_vantage_market",
            safe_url,
            "LIVE",
            iso_now(),
            as_of,
            long_term,
            short_term,
        )
    except Exception as exc:
        return Observation(
            "alpha_vantage_adjusted",
            "alpha_vantage_market",
            safe_url,
            "UNAVAILABLE",
            iso_now(),
            error=str(exc)[:300],
        )


def observe_fred() -> dict[str, Any]:
    url = (
        "https://fred.stlouisfed.org/graph/fredgraph.csv?"
        "id=DGS10,FEDFUNDS,CPIAUCSL"
    )
    try:
        lines = [
            line
            for line in fetch_text(url, timeout=20).splitlines()
            if line.strip()
        ]
        if len(lines) < 2:
            raise SourceGateError("no macro rows")
        return {
            "provider": "fred_official_macro",
            "family": "official_macro",
            "domain": "stlouisfed.org",
            "url": url,
            "status": "LIVE",
            "observed_at": iso_now(),
            "as_of": lines[-1].split(",", 1)[0],
            "row_count": len(lines) - 1,
        }
    except Exception as exc:
        return {
            "provider": "fred_official_macro",
            "family": "official_macro",
            "domain": "stlouisfed.org",
            "url": url,
            "status": "UNAVAILABLE",
            "observed_at": iso_now(),
            "error": str(exc)[:300],
        }


def cache_key(ticker: str, provider: str) -> str:
    return f"{ticker.upper()}::{provider}"


def observation_from_cache(
    cache: Mapping[str, Any],
    ticker: str,
    provider: str,
) -> Observation | None:
    raw = cache.get(cache_key(ticker, provider))
    if not isinstance(raw, dict):
        return None
    observed_at = parse_time(str(raw.get("observed_at") or ""))
    if observed_at is None:
        return None
    age = int((now_utc() - observed_at).total_seconds())
    if age < -300 or age > CACHE_MAX_AGE_SECONDS:
        return None
    try:
        fields = {
            name: raw.get(name)
            for name in Observation.__dataclass_fields__
        }
        result = Observation(**fields)
        result.status = "CACHED"
        result.cache_age_seconds = age
        return result
    except (TypeError, ValueError):
        return None


def resolve_observation(
    live: Observation,
    cache: Mapping[str, Any],
    ticker: str,
) -> Observation:
    if live.status == "LIVE":
        return live
    return observation_from_cache(cache, ticker, live.provider) or live


def macro_from_cache(cache: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = cache.get("__macro__::fred_official_macro")
    if not isinstance(raw, dict):
        return None
    observed_at = parse_time(str(raw.get("observed_at") or ""))
    if observed_at is None:
        return None
    age = int((now_utc() - observed_at).total_seconds())
    if age < -300 or age > CACHE_MAX_AGE_SECONDS:
        return None
    result = dict(raw)
    result["status"] = "CACHED"
    result["cache_age_seconds"] = age
    return result


def resolve_macro(
    live: Mapping[str, Any],
    cache: Mapping[str, Any],
) -> dict[str, Any]:
    if live.get("status") == "LIVE":
        return dict(live)
    return macro_from_cache(cache) or dict(live)


def value_conflict(
    reference: Any,
    observed: float | None,
    tolerance: float,
) -> bool:
    if reference is None or observed is None:
        return False
    try:
        return abs(float(reference) - observed) > tolerance
    except (TypeError, ValueError):
        return False


def source_distribution(
    sources: Iterable[Mapping[str, Any]],
    key: str,
) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for source in sources:
        value = str(source.get(key) or "unknown")
        distribution[value] = distribution.get(value, 0) + 1
    return distribution


def maximum_share(distribution: Mapping[str, int], total: int) -> float:
    return max(distribution.values()) / total if distribution and total else 1.0


def build_record(
    record: Mapping[str, Any],
    report: Mapping[str, Any],
    order: Mapping[str, Any],
    observations: list[Observation],
    policy: Mapping[str, Any],
    macro: Mapping[str, Any],
) -> dict[str, Any]:
    ticker = str(record.get("ticker") or "").upper()
    sources = collect_evidence_sources(record, order)

    sources.append(
        make_source(
            "yfinance_adjusted_close",
            "market_return_calculation",
            "Adjusted-close compatibility calculation source",
            f"https://finance.yahoo.com/quote/{urllib.parse.quote(ticker)}/history",
            str(report.get("retrieved_at") or record.get("as_of") or ""),
        )
    )
    if macro.get("status") in {"LIVE", "CACHED"}:
        sources.append(
            make_source(
                "fred_official_macro",
                "macro_context",
                "Official interest-rate and inflation context",
                str(macro.get("url") or ""),
                str(macro.get("as_of") or macro.get("observed_at") or ""),
            )
        )
    for observation in observations:
        if observation.status not in {"LIVE", "CACHED"}:
            continue
        sources.append(
            make_source(
                observation.provider,
                "independent_market_corroboration",
                "Independent market-path corroboration",
                observation.url,
                observation.as_of,
            )
        )

    units: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source in sources:
        unit = (
            str(source["family"]),
            str(source["domain"]),
            str(source["claim_type"]),
        )
        units.setdefault(unit, source)
    sources = list(units.values())

    families = sorted({str(item["family"]) for item in sources})
    domains = sorted(
        {
            str(item["domain"])
            for item in sources
            if item["domain"] != "unknown"
        }
    )
    all_primary = [item for item in sources if item["primary"]]

    claim_sources = [
        item
        for item in sources
        if item["claim_type"] not in NON_CLAIM_TYPES
        and item["family"] not in MARKET_FAMILIES
        and item["family"] != "official_macro"
    ]
    claim_families = sorted(
        {str(item["family"]) for item in claim_sources}
    )
    claim_domains = sorted(
        {
            str(item["domain"])
            for item in claim_sources
            if item["domain"] != "unknown"
        }
    )
    claim_primary = [
        item
        for item in claim_sources
        if item["family"] in CLAIM_PRIMARY_FAMILIES
    ]

    dated_count = sum(
        1
        for item in sources
        if parse_time(str(item.get("as_of") or "")) is not None
    )
    dated_ratio = dated_count / len(sources) if sources else 0.0
    claim_dated_count = sum(
        1
        for item in claim_sources
        if parse_time(str(item.get("as_of") or "")) is not None
    )
    claim_dated_ratio = (
        claim_dated_count / len(claim_sources)
        if claim_sources
        else 0.0
    )

    family_counts = source_distribution(sources, "family")
    claim_family_counts = source_distribution(claim_sources, "family")
    max_family_share = maximum_share(family_counts, len(sources))
    max_claim_family_share = maximum_share(
        claim_family_counts,
        len(claim_sources),
    )

    market_policy = (
        policy.get("market_data")
        if isinstance(policy.get("market_data"), dict)
        else {}
    )
    long_tolerance = float(
        market_policy.get(
            "long_term_absolute_tolerance_percentage_points",
            30.0,
        )
    )
    short_tolerance = float(
        market_policy.get(
            "short_term_absolute_tolerance_percentage_points",
            18.0,
        )
    )

    market_rows: list[dict[str, Any]] = []
    conflicting: list[str] = []
    independent_market_count = 0
    for observation in observations:
        long_conflict = value_conflict(
            report.get("long_term_return_pct"),
            observation.long_term_return_pct,
            long_tolerance,
        )
        short_conflict = value_conflict(
            report.get("short_term_return_pct"),
            observation.short_term_return_pct,
            short_tolerance,
        )
        if observation.status in {"LIVE", "CACHED"}:
            independent_market_count += 1
            if long_conflict or short_conflict:
                conflicting.append(observation.provider)
        row = asdict(observation)
        row["long_term_conflict"] = long_conflict
        row["short_term_conflict"] = short_conflict
        market_rows.append(row)

    evidence_text = " ".join(
        f"{item.get('claim_type', '')} {item.get('title', '')}"
        for item in record.get("evidence", [])
        if isinstance(item, dict)
    )
    evidence_text += " " + str(report.get("current_orders") or "")
    evidence_text += " " + str(report.get("future_orders_estimate") or "")
    sensitive_claim = bool(SENSITIVE_RE.search(evidence_text))

    minimums = (
        policy.get("minimums")
        if isinstance(policy.get("minimums"), dict)
        else {}
    )
    required_claim_families = int(
        minimums.get("high_confidence_claim_independent_families", 2)
    )
    required_claim_primary = int(
        minimums.get("high_confidence_claim_primary_sources", 1)
    )
    required_claim_dated_ratio = float(
        minimums.get(
            "high_confidence_claim_dated_ratio",
            minimums.get("dated_evidence_ratio", 0.8),
        )
    )

    independent_claim_evidence = (
        len(claim_families) >= required_claim_families
        and len(claim_primary) >= required_claim_primary
    )
    high_confidence = (
        independent_claim_evidence
        and independent_market_count >= 1
        and claim_dated_ratio >= required_claim_dated_ratio
        and not conflicting
    )

    missing: list[str] = []
    if independent_market_count == 0:
        missing.append("NON_YAHOO_MARKET_CORROBORATION")
    if not claim_primary:
        missing.append("CLAIM_RELEVANT_PRIMARY_SOURCE")
    if len(claim_families) < required_claim_families:
        missing.append("INDEPENDENT_CLAIM_SOURCE_FAMILY")
    if claim_sources and claim_dated_ratio < required_claim_dated_ratio:
        missing.append("DATED_CLAIM_EVIDENCE_COVERAGE")
    if not claim_sources:
        missing.append("CLAIM_EVIDENCE")
    if max_family_share > float(
        minimums.get("maximum_single_family_share", 0.70)
    ):
        missing.append("SOURCE_FAMILY_CONCENTRATION")
    if claim_sources and max_claim_family_share > 0.70:
        missing.append("CLAIM_SOURCE_FAMILY_CONCENTRATION")
    if conflicting:
        missing.append("MARKET_SOURCE_CONFLICT_REVIEW")
    if macro.get("status") not in {"LIVE", "CACHED"}:
        missing.append("OFFICIAL_MACRO_CONTEXT_UNAVAILABLE")

    score = 0.0
    score += min(20.0, len(claim_families) * 10.0)
    score += min(15.0, len(claim_domains) * 5.0)
    score += min(20.0, len(claim_primary) * 20.0)
    score += min(15.0, independent_market_count * 7.5)
    score += min(10.0, claim_dated_ratio * 10.0)
    score += min(10.0, len(families) * 2.0)
    score += 10.0 if macro.get("status") in {"LIVE", "CACHED"} else 0.0
    score -= 20.0 if conflicting else 0.0
    score -= 10.0 if claim_sources and max_claim_family_share > 0.70 else 0.0
    evidence_independence_score = round(
        max(0.0, min(100.0, score)),
        1,
    )

    public_logic = {
        "serenity_source_view": (
            "SUPPORTED"
            if "serenity_public_source" in claim_families
            else "NOT_ATTACHED"
        ),
        "architecture": (
            "EVIDENCE_FORMING"
            if sensitive_claim and independent_claim_evidence
            else "UNPROVEN"
        ),
        "dependency_graph": (
            "EVIDENCE_FORMING"
            if sensitive_claim and independent_claim_evidence
            else "UNPROVEN"
        ),
        "bottleneck_or_expansion": (
            "EVIDENCE_FORMING"
            if sensitive_claim and independent_claim_evidence
            else "UNPROVEN"
        ),
        "company_capture": (
            "EVIDENCE_FORMING"
            if independent_claim_evidence
            else "UNPROVEN"
        ),
        "valuation_expectations": (
            "EVIDENCE_FORMING"
            if independent_market_count
            else "LIMITED_SINGLE_MARKET_SOURCE"
        ),
        "thesis_killers": "REVIEW_REQUIRED",
        "lifecycle": (
            "EVIDENCE_FORMING"
            if independent_claim_evidence
            else "UNPROVEN"
        ),
        "model_inference_confidence": (
            "HIGH_ELIGIBLE" if high_confidence else "LIMITED"
        ),
        "system_operationalization_is_official_serenity_score": False,
        "private_method_reproduction_claimed": False,
    }

    return {
        "rank": record.get("rank"),
        "ticker": ticker,
        "evidence_independence_score": evidence_independence_score,
        "source_metrics": {
            "unique_independent_units": len(sources),
            "independent_families": len(families),
            "independent_domains": len(domains),
            "primary_or_official_sources": len(all_primary),
            "claim_relevant_independent_families": len(claim_families),
            "claim_relevant_independent_domains": len(claim_domains),
            "claim_relevant_primary_sources": len(claim_primary),
            "dated_evidence_ratio": round(dated_ratio, 4),
            "claim_dated_evidence_ratio": round(claim_dated_ratio, 4),
            "maximum_single_family_share": round(max_family_share, 4),
            "maximum_claim_family_share": round(max_claim_family_share, 4),
            "families": families,
            "domains": domains,
            "claim_families": claim_families,
            "claim_domains": claim_domains,
        },
        "market_corroboration": {
            "calculation_provider": "yfinance_adjusted_close",
            "calculation_provider_role": (
                "compatibility_calculation_only_not_thesis_evidence"
            ),
            "independent_provider_count": independent_market_count,
            "status": (
                "CONFLICT_REVIEW"
                if conflicting
                else (
                    "CORROBORATED"
                    if independent_market_count
                    else "UNAVAILABLE"
                )
            ),
            "providers": market_rows,
        },
        "public_logic_state": public_logic,
        "missing_or_review": missing,
        "eligible_for_high_confidence_model_inference": high_confidence,
        "sensitive_claim_present": sensitive_claim,
        "sources": sources,
    }


def collect_observations(
    ticker: str,
    cache: Mapping[str, Any],
    api_key: str,
    offline: bool,
) -> tuple[str, list[Observation]]:
    if offline:
        return (
            ticker,
            [
                Observation(
                    "stooq_daily_csv",
                    "stooq_market",
                    "https://stooq.com",
                    "CACHED",
                    iso_now(),
                    as_of=dt.date.today().isoformat(),
                    long_term_return_pct=20.0,
                    short_term_return_pct=5.0,
                    cache_age_seconds=0,
                ),
                Observation(
                    "nasdaq_historical_api",
                    "nasdaq_market",
                    "https://api.nasdaq.com",
                    "UNAVAILABLE",
                    iso_now(),
                    error="offline fixture",
                ),
            ],
        )

    live = [
        observe_stooq(ticker),
        observe_nasdaq(ticker),
    ]
    if api_key:
        live.append(observe_alpha_vantage(ticker, api_key))
    return (
        ticker,
        [
            resolve_observation(observation, cache, ticker)
            for observation in live
        ],
    )


def build(
    top20: list[dict[str, Any]],
    reports: Mapping[str, Mapping[str, Any]],
    orders: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
    cache: Mapping[str, Any],
    offline: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tickers = [
        str(item.get("ticker") or "").upper()
        for item in top20
    ]
    alpha_vantage_key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
    resolved: dict[str, list[Observation]] = {}
    updated_cache: dict[str, Any] = dict(cache)

    if offline:
        macro = {
            "provider": "fred_official_macro",
            "family": "official_macro",
            "domain": "stlouisfed.org",
            "url": "https://fred.stlouisfed.org",
            "status": "OFFLINE_TEST",
            "observed_at": iso_now(),
        }
    else:
        macro = resolve_macro(observe_fred(), cache)

    if offline:
        for ticker in tickers:
            key, observations = collect_observations(
                ticker,
                cache,
                "",
                True,
            )
            resolved[key] = observations
    else:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(
                    collect_observations,
                    ticker,
                    cache,
                    alpha_vantage_key,
                    False,
                ): ticker
                for ticker in tickers
            }
            for future in as_completed(futures):
                ticker, observations = future.result()
                resolved[ticker] = observations
                print(
                    "II_PROGRESS source independence "
                    f"{len(resolved)}/20 | {ticker}",
                    flush=True,
                )

    for ticker, observations in resolved.items():
        for observation in observations:
            if observation.status == "LIVE":
                updated_cache[
                    cache_key(ticker, observation.provider)
                ] = asdict(observation)
    if macro.get("status") == "LIVE":
        updated_cache["__macro__::fred_official_macro"] = dict(macro)

    states = [
        build_record(
            record,
            reports.get(
                str(record.get("ticker") or "").upper(),
                {},
            ),
            orders.get(
                str(record.get("ticker") or "").upper(),
                {},
            ),
            resolved.get(
                str(record.get("ticker") or "").upper(),
                [],
            ),
            policy,
            macro,
        )
        for record in top20
    ]

    all_sources = [
        source
        for state in states
        for source in state["sources"]
    ]
    all_claim_sources = [
        source
        for source in all_sources
        if source["claim_type"] not in NON_CLAIM_TYPES
        and source["family"] not in MARKET_FAMILIES
        and source["family"] != "official_macro"
    ]

    families = sorted(
        {str(source["family"]) for source in all_sources}
    )
    domains = sorted(
        {
            str(source["domain"])
            for source in all_sources
            if source["domain"] != "unknown"
        }
    )
    claim_families = sorted(
        {str(source["family"]) for source in all_claim_sources}
    )
    claim_domains = sorted(
        {
            str(source["domain"])
            for source in all_claim_sources
            if source["domain"] != "unknown"
        }
    )

    family_counts = source_distribution(all_sources, "family")
    max_family_share = maximum_share(
        family_counts,
        len(all_sources),
    )
    market_covered = sum(
        1
        for state in states
        if state["market_corroboration"]["independent_provider_count"] >= 1
    )
    claim_primary_covered = sum(
        1
        for state in states
        if state["source_metrics"]["claim_relevant_primary_sources"] >= 1
    )
    official_context_covered = sum(
        1
        for state in states
        if "official_macro" in state["source_metrics"]["families"]
    )

    portfolio = {
        "ticker_count": 20,
        "independent_source_families": len(families),
        "independent_domains": len(domains),
        "source_families": families,
        "source_domains": domains,
        "claim_source_families": len(claim_families),
        "claim_source_domains": len(claim_domains),
        "claim_source_family_list": claim_families,
        "claim_source_domain_list": claim_domains,
        "non_yahoo_market_coverage_ratio": round(
            market_covered / 20.0,
            4,
        ),
        "primary_or_official_coverage_ratio": round(
            claim_primary_covered / 20.0,
            4,
        ),
        "claim_primary_coverage_ratio": round(
            claim_primary_covered / 20.0,
            4,
        ),
        "official_macro_context_coverage_ratio": round(
            official_context_covered / 20.0,
            4,
        ),
        "maximum_single_family_share": round(
            max_family_share,
            4,
        ),
        "market_conflict_ticker_count": sum(
            1
            for state in states
            if state["market_corroboration"]["status"]
            == "CONFLICT_REVIEW"
        ),
        "high_confidence_model_inference_eligible_count": sum(
            1
            for state in states
            if state["eligible_for_high_confidence_model_inference"]
        ),
        "fred_macro_status": macro.get("status"),
    }

    minimums = (
        policy.get("minimums")
        if isinstance(policy.get("minimums"), dict)
        else {}
    )
    violations: list[str] = []
    if not offline:
        if portfolio["independent_source_families"] < int(
            minimums.get("portfolio_independent_source_families", 3)
        ):
            violations.append("INSUFFICIENT_SOURCE_FAMILIES")
        if portfolio["independent_domains"] < int(
            minimums.get("portfolio_independent_domains", 3)
        ):
            violations.append("INSUFFICIENT_SOURCE_DOMAINS")
        if portfolio["claim_source_families"] < int(
            minimums.get("portfolio_claim_source_families", 2)
        ):
            violations.append("INSUFFICIENT_CLAIM_SOURCE_FAMILIES")
        if portfolio["claim_source_domains"] < int(
            minimums.get("portfolio_claim_source_domains", 2)
        ):
            violations.append("INSUFFICIENT_CLAIM_SOURCE_DOMAINS")
        if portfolio["non_yahoo_market_coverage_ratio"] < float(
            minimums.get("non_yahoo_market_coverage_ratio", 0.75)
        ):
            violations.append("INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE")
        if portfolio["claim_primary_coverage_ratio"] < float(
            minimums.get("portfolio_claim_primary_coverage_ratio", 0.75)
        ):
            violations.append("INSUFFICIENT_CLAIM_PRIMARY_COVERAGE")
        if portfolio["maximum_single_family_share"] > float(
            minimums.get("maximum_single_family_share", 0.70)
        ):
            violations.append("SOURCE_FAMILY_CONCENTRATION")

    if violations:
        for state in states:
            state["eligible_for_high_confidence_model_inference"] = False
            state["public_logic_state"][
                "model_inference_confidence"
            ] = "LIMITED"
            if "PORTFOLIO_SOURCE_POLICY" not in state["missing_or_review"]:
                state["missing_or_review"].append(
                    "PORTFOLIO_SOURCE_POLICY"
                )
        portfolio[
            "high_confidence_model_inference_eligible_count"
        ] = 0

    result = {
        "schema_version": 3,
        "product_version": "2.1.3",
        "policy_version": str(
            policy.get("policy_version") or "unknown"
        ),
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
            "official_macro_is_not_company_claim_evidence": True,
            "market_data_is_not_bottleneck_evidence": True,
        },
    }
    return result, updated_cache


def self_test(policy: Mapping[str, Any]) -> None:
    stamp = iso_now()
    top20: list[dict[str, Any]] = []
    reports: dict[str, dict[str, Any]] = {}
    orders: dict[str, dict[str, Any]] = {}

    for index in range(20):
        ticker = f"T{index:02d}"
        top20.append(
            {
                "rank": index + 1,
                "ticker": ticker,
                "as_of": stamp,
                "evidence": [
                    {
                        "source_id": "sec_edgar",
                        "claim_type": "xbrl_fact",
                        "title": "Synthetic primary capacity fact",
                        "url": (
                            "https://www.sec.gov/Archives/edgar/data/"
                            f"{1000000 + index}/synthetic.htm"
                        ),
                        "as_of": stamp,
                    },
                    {
                        "source_id": "reuters",
                        "claim_type": "industry_context",
                        "title": "Synthetic independent industry context",
                        "url": (
                            "https://www.reuters.com/technology/"
                            f"synthetic-{index}/"
                        ),
                        "as_of": stamp,
                    },
                    {
                        "source_id": "reuters_copy",
                        "claim_type": "industry_context",
                        "title": "Syndicated duplicate",
                        "url": (
                            "https://www.reuters.com/technology/"
                            f"synthetic-{index}?utm_source=copy"
                        ),
                        "as_of": stamp,
                    },
                ],
            }
        )
        reports[ticker] = {
            "long_term_return_pct": 20.0,
            "short_term_return_pct": 5.0,
            "retrieved_at": stamp,
        }
        orders[ticker] = {
            "current_order_source_urls": [],
            "future_order_source_urls": [],
        }

    result, _ = build(
        top20,
        reports,
        orders,
        policy,
        {},
        True,
    )
    assert result["status"] == "PASS"
    assert len(result["records"]) == 20
    first = result["records"][0]
    assert first["source_metrics"]["claim_relevant_independent_families"] == 2
    assert first["source_metrics"]["claim_relevant_primary_sources"] == 1
    assert first["eligible_for_high_confidence_model_inference"] is True
    assert result["methodology_notice"]["single_source_inference_allowed"] is False
    assert result["methodology_notice"]["official_serenity_formula"] is False
    assert family_for(
        "fred_official_macro",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
    ) == "official_macro"
    assert family_for(
        "yfinance",
        "https://finance.yahoo.com/quote/NVDA/history",
    ) == "yahoo_market"
    assert domain_of("https://api.nasdaq.com/api/quote/NVDA/historical") == "nasdaq.com"
    print("V213_SOURCE_INDEPENDENCE_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top20", type=Path, default=DEFAULT_TOP20)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--order-evidence",
        type=Path,
        default=DEFAULT_ORDER,
    )
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

    top20 = extract_rows(read_json(args.top20))
    reports = index_records(read_json(args.report, {}))
    orders = index_records(read_json(args.order_evidence, {}))
    cache = read_json(args.cache, {})
    if not isinstance(cache, dict):
        cache = {}

    result, updated_cache = build(
        top20,
        reports,
        orders,
        policy,
        cache,
        args.offline,
    )
    write_json(args.cache, updated_cache)
    write_json(args.output, result)

    portfolio = result["portfolio"]
    print(
        "V213_SOURCE_INDEPENDENCE = "
        + result["status"]
        + f"; families={portfolio['independent_source_families']}"
        + f"; domains={portfolio['independent_domains']}"
        + f"; claim_families={portfolio['claim_source_families']}"
        + f"; claim_domains={portfolio['claim_source_domains']}"
        + (
            "; non_yahoo_market="
            f"{portfolio['non_yahoo_market_coverage_ratio']:.1%}"
        )
        + (
            "; claim_primary="
            f"{portfolio['claim_primary_coverage_ratio']:.1%}"
        )
        + f"; conflicts={portfolio['market_conflict_ticker_count']}",
        flush=True,
    )
    if args.enforce and result["status"] != "PASS":
        raise SourceGateError(
            "Source-independence policy failed: "
            + ",".join(result["violations"])
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SourceGateError as exc:
        print(
            f"V213_SOURCE_INDEPENDENCE = FAIL; {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
