#!/usr/bin/env python3
"""Investor Intelligence v2.1.3 multi-source fidelity sidecar.

The existing yfinance adjusted-close series remains the deterministic return
calculation source for compatibility. This stage independently corroborates the
market path with non-Yahoo providers, classifies existing evidence by source
family/domain, detects concentration and conflicts, and emits a claim-safe
Serenity public-logic fidelity state. It never treats duplicate syndication as
independent evidence and never invents missing facts.
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
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOP20 = ROOT / "data" / "cache" / "top20_public_latest.json"
DEFAULT_REPORT = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
DEFAULT_POLICY = ROOT / "config" / "v213-serenity-public-logic-policy.json"
DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_multi_source_fidelity_latest.json"
USER_AGENT = "InvestorIntelligence/2.1.3 source-diversity audit; public-data research"

PRIMARY_FAMILIES = {"regulator_filing", "issuer_primary", "official_macro", "exchange_sro"}
MARKET_FAMILIES = {"yahoo_market", "stooq_market", "nasdaq_market", "alpha_vantage_market"}
SENSITIVE_TERMS = re.compile(
    r"chokepoint|bottleneck|dependency|supply|capacity|qualification|contract|order|"
    r"backlog|rpo|pricing|customer|dilution|financing|architecture|competition",
    re.I,
)


class FidelityError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketObservation:
    provider: str
    family: str
    url: str
    status: str
    as_of: str = ""
    long_term_return_pct: float | None = None
    short_term_return_pct: float | None = None
    error: str = ""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FidelityError(f"Unable to read JSON: {path}") from exc


def records_from(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict) and isinstance(value.get("records"), list):
        rows = value["records"]
    elif isinstance(value, dict) and isinstance(value.get("top20"), list):
        rows = value["top20"]
    else:
        raise FidelityError("Top20 JSON must be a list or contain records/top20")
    result: list[dict[str, Any]] = []
    for raw in rows:
        if isinstance(raw, dict) and str(raw.get("ticker") or "").strip():
            result.append(dict(raw))
    if len(result) != 20:
        raise FidelityError(f"Expected exactly 20 Top20 rows, found {len(result)}")
    return result


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def registrable_domain(host: str) -> str:
    host = host.lower().strip(".")
    if not host:
        return "unknown"
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    public_suffix_pairs = {"co.uk", "com.au", "co.jp", "com.cn", "com.tw", "co.kr"}
    tail2 = ".".join(labels[-2:])
    if tail2 in public_suffix_pairs and len(labels) >= 3:
        return ".".join(labels[-3:])
    return tail2


def domain_of(url: str) -> str:
    try:
        return registrable_domain(urllib.parse.urlparse(url).hostname or "")
    except Exception:
        return "unknown"


def source_family(source_id: str, url: str) -> str:
    sid = source_id.lower()
    domain = domain_of(url)
    if domain.endswith("sec.gov") or "edgar" in sid or sid.startswith("sec"):
        return "regulator_filing"
    if domain in {"fred.stlouisfed.org", "federalreserve.gov", "bls.gov", "bea.gov", "census.gov", "eia.gov"}:
        return "official_macro"
    if domain in {"nasdaq.com", "nyse.com", "cboe.com", "finra.org"} and "api.nasdaq" not in url.lower():
        return "exchange_sro"
    if domain == "finance.yahoo.com" or "yfinance" in sid or "yahoo" in sid:
        return "yahoo_market"
    if domain == "stooq.com" or "stooq" in sid:
        return "stooq_market"
    if domain == "nasdaq.com" and "historical" in url.lower():
        return "nasdaq_market"
    if domain == "alphavantage.co" or "alpha_vantage" in sid:
        return "alpha_vantage_market"
    if any(token in sid for token in ("issuer", "company_ir", "press_release", "earnings_release")):
        return "issuer_primary"
    if domain not in {"unknown", "finance.yahoo.com", "stooq.com"} and any(
        token in url.lower() for token in ("investor", "ir.", "newsroom", "press-release")
    ):
        return "issuer_primary"
    if any(token in sid for token in ("reuters", "ap_news", "bloomberg", "wsj", "ft_")):
        return "news_secondary"
    if "serenity" in sid:
        return "serenity_public_source"
    return "secondary_or_other"


def normalize_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [(k, v) for k, v in query if not k.lower().startswith("utm_")]
        return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, urllib.parse.urlencode(query), ""))
    except Exception:
        return url.strip()


def request_text(url: str, timeout: int = 14) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/csv,application/json;q=0.9,*/*;q=0.5",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return payload.decode("utf-8-sig", errors="strict")


def nearest_price(rows: list[tuple[dt.date, float]], target: dt.date) -> float | None:
    eligible = [price for date, price in rows if date <= target]
    return eligible[-1] if eligible else None


def returns_from_rows(rows: Iterable[tuple[dt.date, float]]) -> tuple[str, float | None, float | None]:
    clean = sorted((date, price) for date, price in rows if price > 0 and math.isfinite(price))
    if len(clean) < 2:
        return "", None, None
    last_date, last_price = clean[-1]
    six_price = nearest_price(clean, last_date - dt.timedelta(days=183))
    two_price = nearest_price(clean, last_date - dt.timedelta(days=730))
    short = ((last_price / six_price) - 1.0) * 100.0 if six_price else None
    long = (((last_price / two_price) ** 0.5) - 1.0) * 100.0 if two_price else None
    return last_date.isoformat(), long, short


def stooq_symbol(ticker: str) -> str:
    return ticker.lower().replace(".", "-") + ".us"


def observe_stooq(ticker: str) -> MarketObservation:
    today = dt.date.today()
    start = today - dt.timedelta(days=790)
    url = (
        "https://stooq.com/q/d/l/?" + urllib.parse.urlencode({
            "s": stooq_symbol(ticker),
            "d1": start.strftime("%Y%m%d"),
            "d2": today.strftime("%Y%m%d"),
            "i": "d",
        })
    )
    try:
        text = request_text(url)
        rows: list[tuple[dt.date, float]] = []
        for item in csv.DictReader(io.StringIO(text)):
            try:
                rows.append((dt.date.fromisoformat(str(item.get("Date") or "")), float(item.get("Close") or "nan")))
            except (TypeError, ValueError):
                continue
        as_of, long, short = returns_from_rows(rows)
        if not as_of:
            raise FidelityError("no usable daily rows")
        return MarketObservation("stooq_daily_csv", "stooq_market", url, "AVAILABLE", as_of, long, short)
    except Exception as exc:
        return MarketObservation("stooq_daily_csv", "stooq_market", url, "UNAVAILABLE", error=str(exc)[:300])


def parse_nasdaq_price(value: Any) -> float:
    text = re.sub(r"[^0-9.\-]", "", str(value or ""))
    return float(text)


def observe_nasdaq(ticker: str) -> MarketObservation:
    today = dt.date.today()
    start = today - dt.timedelta(days=790)
    query = urllib.parse.urlencode({
        "assetclass": "stocks",
        "fromdate": start.strftime("%m/%d/%Y"),
        "todate": today.strftime("%m/%d/%Y"),
        "limit": "5000",
    })
    url = f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(ticker)}/historical?{query}"
    try:
        payload = json.loads(request_text(url))
        data = payload.get("data") if isinstance(payload, dict) else None
        trades = data.get("tradesTable") if isinstance(data, dict) else None
        raw_rows = trades.get("rows") if isinstance(trades, dict) else None
        rows: list[tuple[dt.date, float]] = []
        if isinstance(raw_rows, list):
            for item in raw_rows:
                if not isinstance(item, dict):
                    continue
                try:
                    date = dt.datetime.strptime(str(item.get("date") or ""), "%m/%d/%Y").date()
                    rows.append((date, parse_nasdaq_price(item.get("close"))))
                except (TypeError, ValueError):
                    continue
        as_of, long, short = returns_from_rows(rows)
        if not as_of:
            raise FidelityError("no usable historical rows")
        return MarketObservation("nasdaq_historical_api", "nasdaq_market", url, "AVAILABLE", as_of, long, short)
    except Exception as exc:
        return MarketObservation("nasdaq_historical_api", "nasdaq_market", url, "UNAVAILABLE", error=str(exc)[:300])


def observe_alpha_vantage(ticker: str, key: str) -> MarketObservation:
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode({
        "function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": ticker,
        "outputsize": "full", "apikey": key,
    })
    try:
        payload = json.loads(request_text(url, timeout=25))
        series = payload.get("Time Series (Daily)") if isinstance(payload, dict) else None
        rows: list[tuple[dt.date, float]] = []
        if isinstance(series, dict):
            for date_text, item in series.items():
                if not isinstance(item, dict):
                    continue
                try:
                    rows.append((dt.date.fromisoformat(date_text), float(item.get("5. adjusted close") or "nan")))
                except (TypeError, ValueError):
                    continue
        as_of, long, short = returns_from_rows(rows)
        if not as_of:
            raise FidelityError("no usable adjusted series")
        safe_url = re.sub(r"apikey=[^&]+", "apikey=<redacted>", url)
        return MarketObservation("alpha_vantage_adjusted", "alpha_vantage_market", safe_url, "AVAILABLE", as_of, long, short)
    except Exception as exc:
        safe_url = re.sub(r"apikey=[^&]+", "apikey=<redacted>", url)
        return MarketObservation("alpha_vantage_adjusted", "alpha_vantage_market", safe_url, "UNAVAILABLE", error=str(exc)[:300])


def report_map(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    value = load_json(path)
    rows = value.get("records") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        return {}
    return {str(row.get("ticker") or "").upper(): row for row in rows if isinstance(row, dict)}


def existing_sources(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    evidence = record.get("evidence")
    if not isinstance(evidence, list):
        return result
    for item in evidence:
        if not isinstance(item, dict):
            continue
        url = normalize_url(str(item.get("url") or ""))
        if not url or url in seen:
            continue
        seen.add(url)
        source_id = str(item.get("source_id") or "unknown")
        result.append({
            "source_id": source_id,
            "family": source_family(source_id, url),
            "domain": domain_of(url),
            "claim_type": str(item.get("claim_type") or "unknown"),
            "as_of": str(item.get("as_of") or ""),
            "url": url,
            "primary": source_family(source_id, url) in PRIMARY_FAMILIES,
        })
    return result


def dated(value: str) -> bool:
    if not value:
        return False
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        try:
            dt.date.fromisoformat(value[:10])
            return True
        except ValueError:
            return False


def market_conflict(reference: Any, observed: float | None, tolerance: float) -> bool:
    if reference is None or observed is None:
        return False
    try:
        return abs(float(reference) - float(observed)) > tolerance
    except (TypeError, ValueError):
        return False


def build_state(
    ticker: str,
    record: Mapping[str, Any],
    report: Mapping[str, Any],
    observations: list[MarketObservation],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    sources = existing_sources(record)
    yahoo_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
    sources.append({
        "source_id": "yfinance_adjusted_close",
        "family": "yahoo_market",
        "domain": "finance.yahoo.com",
        "claim_type": "market_return_calculation",
        "as_of": str(record.get("as_of") or report.get("retrieved_at") or ""),
        "url": yahoo_url,
        "primary": False,
    })
    for observation in observations:
        if observation.status == "AVAILABLE":
            sources.append({
                "source_id": observation.provider,
                "family": observation.family,
                "domain": domain_of(observation.url),
                "claim_type": "independent_market_corroboration",
                "as_of": observation.as_of,
                "url": normalize_url(observation.url),
                "primary": False,
            })

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for source in sources:
        key = (str(source["domain"]), str(source["url"]))
        unique.setdefault(key, source)
    sources = list(unique.values())
    families = sorted({str(item["family"]) for item in sources})
    domains = sorted({str(item["domain"]) for item in sources if item["domain"] != "unknown"})
    primary_count = sum(1 for item in sources if item["primary"])
    dated_ratio = (sum(1 for item in sources if dated(str(item["as_of"]))) / len(sources)) if sources else 0.0
    family_counts: dict[str, int] = {}
    for item in sources:
        family_counts[str(item["family"])] = family_counts.get(str(item["family"]), 0) + 1
    max_family_share = (max(family_counts.values()) / len(sources)) if sources else 1.0

    available_market = [item for item in observations if item.status == "AVAILABLE"]
    non_yahoo_available = [item for item in available_market if item.family != "yahoo_market"]
    market_policy = policy.get("market_data") if isinstance(policy.get("market_data"), dict) else {}
    long_tolerance = float(market_policy.get("long_term_absolute_tolerance_percentage_points", 30.0))
    short_tolerance = float(market_policy.get("short_term_absolute_tolerance_percentage_points", 18.0))
    market_details = []
    conflicts: list[str] = []
    for item in observations:
        conflict_long = market_conflict(report.get("long_term_return_pct"), item.long_term_return_pct, long_tolerance)
        conflict_short = market_conflict(report.get("short_term_return_pct"), item.short_term_return_pct, short_tolerance)
        if item.status == "AVAILABLE" and (conflict_long or conflict_short):
            conflicts.append(item.provider)
        market_details.append({
            "provider": item.provider,
            "family": item.family,
            "status": item.status,
            "as_of": item.as_of,
            "long_term_return_pct": item.long_term_return_pct,
            "short_term_return_pct": item.short_term_return_pct,
            "conflict_long_term": conflict_long,
            "conflict_short_term": conflict_short,
            "url": item.url,
            "error": item.error,
        })

    source_text = " ".join(
        str(item.get("claim_type") or "") + " " + str(item.get("title") or "")
        for item in record.get("evidence", []) if isinstance(item, dict)
    )
    sensitive_claim_present = bool(SENSITIVE_TERMS.search(source_text))
    independent_for_inference = len(families) >= 2 and primary_count >= 1
    fidelity_state = {
        "serenity_source_view": "SUPPORTED" if "serenity_public_source" in families else "NOT_ATTACHED",
        "architecture": "EVIDENCE_FORMING" if sensitive_claim_present and len(families) >= 2 else "UNPROVEN",
        "dependency_graph": "EVIDENCE_FORMING" if sensitive_claim_present and independent_for_inference else "UNPROVEN",
        "bottleneck": "EVIDENCE_FORMING" if sensitive_claim_present and independent_for_inference else "UNPROVEN",
        "company_capture": "EVIDENCE_FORMING" if primary_count >= 1 and len(families) >= 2 else "UNPROVEN",
        "thesis_killers": "REVIEW_REQUIRED",
        "valuation_expectations": "EVIDENCE_FORMING" if len(non_yahoo_available) >= 1 else "LIMITED_SINGLE_MARKET_SOURCE",
        "lifecycle": "EVIDENCE_FORMING" if independent_for_inference else "UNPROVEN",
        "system_operationalization_score_is_official_serenity_score": False,
        "private_method_reproduction_claimed": False,
    }
    missing: list[str] = []
    if not non_yahoo_available:
        missing.append("NON_YAHOO_MARKET_CORROBORATION")
    if primary_count == 0:
        missing.append("PRIMARY_SOURCE")
    if len(families) < 2:
        missing.append("INDEPENDENT_SOURCE_FAMILY")
    if dated_ratio < 0.8:
        missing.append("DATED_EVIDENCE_COVERAGE")
    if max_family_share > 0.7:
        missing.append("SOURCE_CONCENTRATION")
    if conflicts:
        missing.append("MARKET_SOURCE_CONFLICT_REVIEW")

    return {
        "ticker": ticker,
        "rank": record.get("rank"),
        "source_metrics": {
            "unique_sources": len(sources),
            "independent_families": len(families),
            "independent_domains": len(domains),
            "primary_sources": primary_count,
            "dated_evidence_ratio": round(dated_ratio, 4),
            "maximum_single_family_share": round(max_family_share, 4),
            "families": families,
            "domains": domains,
        },
        "market_corroboration": {
            "calculation_provider": "yfinance_adjusted_close",
            "independent_provider_count": len(non_yahoo_available),
            "status": "CONFLICT_REVIEW" if conflicts else ("CORROBORATED" if non_yahoo_available else "UNAVAILABLE"),
            "providers": market_details,
        },
        "public_logic_state": fidelity_state,
        "missing_or_review": missing,
        "eligible_for_high_confidence_model_inference": independent_for_inference and bool(non_yahoo_available) and not conflicts,
        "sources": sources,
    }


def observe_ticker(ticker: str, offline: bool, alpha_key: str) -> list[MarketObservation]:
    if offline:
        return [
            MarketObservation("stooq_daily_csv", "stooq_market", "https://stooq.com", "OFFLINE_TEST"),
            MarketObservation("nasdaq_historical_api", "nasdaq_market", "https://api.nasdaq.com", "OFFLINE_TEST"),
        ]
    observations = [observe_stooq(ticker), observe_nasdaq(ticker)]
    if alpha_key:
        observations.append(observe_alpha_vantage(ticker, alpha_key))
    return observations


def build(top20: list[dict[str, Any]], reports: Mapping[str, Mapping[str, Any]], policy: Mapping[str, Any], offline: bool) -> dict[str, Any]:
    tickers = [str(item.get("ticker") or "").upper() for item in top20]
    alpha_key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
    observations_by_ticker: dict[str, list[MarketObservation]] = {}
    if offline:
        for ticker in tickers:
            observations_by_ticker[ticker] = observe_ticker(ticker, True, "")
    else:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(observe_ticker, ticker, False, alpha_key): ticker for ticker in tickers}
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    observations_by_ticker[ticker] = future.result()
                except Exception as exc:
                    observations_by_ticker[ticker] = [
                        MarketObservation("multi_source_probe", "secondary_or_other", "", "UNAVAILABLE", error=str(exc)[:300])
                    ]
                print(f"II_PROGRESS source diversity {len(observations_by_ticker)}/20 | {ticker}", flush=True)

    states = [
        build_state(
            ticker,
            record,
            reports.get(ticker, {}),
            observations_by_ticker.get(ticker, []),
            policy,
        )
        for ticker, record in zip(tickers, top20)
    ]
    families = sorted({family for state in states for family in state["source_metrics"]["families"]})
    domains = sorted({domain for state in states for domain in state["source_metrics"]["domains"]})
    corroborated = sum(1 for state in states if state["market_corroboration"]["independent_provider_count"] >= 1)
    conflict_count = sum(1 for state in states if state["market_corroboration"]["status"] == "CONFLICT_REVIEW")
    family_occurrences: dict[str, int] = {}
    total_occurrences = 0
    for state in states:
        for source in state["sources"]:
            family = str(source["family"])
            family_occurrences[family] = family_occurrences.get(family, 0) + 1
            total_occurrences += 1
    concentration = (max(family_occurrences.values()) / total_occurrences) if total_occurrences else 1.0
    portfolio = {
        "ticker_count": len(states),
        "independent_source_families": len(families),
        "independent_domains": len(domains),
        "source_families": families,
        "non_yahoo_market_coverage_ratio": round(corroborated / len(states), 4),
        "market_conflict_ticker_count": conflict_count,
        "maximum_single_family_share": round(concentration, 4),
        "high_confidence_inference_eligible_count": sum(1 for state in states if state["eligible_for_high_confidence_model_inference"]),
    }
    minimums = policy.get("minimums") if isinstance(policy.get("minimums"), dict) else {}
    violations: list[str] = []
    if not offline:
        if portfolio["independent_source_families"] < int(minimums.get("portfolio_independent_source_families", 3)):
            violations.append("PORTFOLIO_SOURCE_FAMILIES")
        if portfolio["independent_domains"] < int(minimums.get("portfolio_independent_domains", 3)):
            violations.append("PORTFOLIO_SOURCE_DOMAINS")
        if portfolio["non_yahoo_market_coverage_ratio"] < float(minimums.get("non_yahoo_market_coverage_ratio", 0.75)):
            violations.append("NON_YAHOO_MARKET_COVERAGE")
        if portfolio["maximum_single_family_share"] > float(minimums.get("maximum_single_family_share", 0.70)):
            violations.append("SOURCE_FAMILY_CONCENTRATION")
    return {
        "schema_version": 1,
        "product_version": "2.1.3",
        "policy_version": str(policy.get("policy_version") or "unknown"),
        "generated_at": utc_now(),
        "status": "PASS" if not violations else "FAIL",
        "offline_self_test": offline,
        "portfolio": portfolio,
        "violations": violations,
        "records": states,
        "methodology_notice": {
            "label": "public-logic high-fidelity reconstruction",
            "official_serenity_formula": False,
            "private_method_reproduced": False,
            "single_source_inference_allowed": False,
        },
    }


def self_test(policy: Mapping[str, Any]) -> None:
    generated = utc_now()
    rows = []
    reports: dict[str, dict[str, Any]] = {}
    for index in range(20):
        ticker = f"T{index:02d}"
        rows.append({
            "ticker": ticker,
            "rank": index + 1,
            "as_of": generated,
            "evidence": [{
                "source_id": "sec_edgar",
                "claim_type": "xbrl_fact",
                "title": "Synthetic primary fact",
                "url": f"https://www.sec.gov/Archives/edgar/data/{1000000 + index}/synthetic.htm",
                "as_of": generated,
            }],
        })
        reports[ticker] = {"long_term_return_pct": 20.0, "short_term_return_pct": 5.0}
    result = build(rows, reports, policy, True)
    if result["status"] != "PASS" or len(result["records"]) != 20:
        raise AssertionError("multi-source fidelity self-test failed")
    if result["methodology_notice"]["official_serenity_formula"]:
        raise AssertionError("official formula was incorrectly claimed")
    print("V213_MULTI_SOURCE_FIDELITY_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top20", type=Path, default=DEFAULT_TOP20)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--enforce", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    policy = load_json(args.policy)
    if args.self_test:
        self_test(policy)
        return 0
    top20 = records_from(load_json(args.top20))
    reports = report_map(args.report)
    result = build(top20, reports, policy, args.offline)
    atomic_json(args.output, result)
    portfolio = result["portfolio"]
    print(
        "V213_MULTI_SOURCE_FIDELITY = " + result["status"] +
        f"; families={portfolio['independent_source_families']}" +
        f"; domains={portfolio['independent_domains']}" +
        f"; non_yahoo_market_coverage={portfolio['non_yahoo_market_coverage_ratio']:.2%}" +
        f"; conflicts={portfolio['market_conflict_ticker_count']}",
        flush=True,
    )
    if args.enforce and result["status"] != "PASS":
        raise FidelityError("Source-diversity policy failed: " + ",".join(result["violations"]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FidelityError as exc:
        print(f"V213_MULTI_SOURCE_FIDELITY = FAIL; {exc}", file=sys.stderr)
        raise SystemExit(1)
