#!/usr/bin/env python3
"""Build an auditable live-source federation snapshot for v2.1.3.

The 100-source catalog is a reviewed inventory, not a claim that every source was
used in a run. This module records the families actually reached in the current
run and keeps claim scopes separate:

* SEC EDGAR: issuer filings and financial facts.
* Nasdaq Trader symbol directory: regulated listing identity.
* GLEIF: independent legal-entity identity when a sufficiently close match exists.
* World Bank, BLS and ECB: independent official macro context.
* Yahoo/yfinance: T3 candidate and market observation only, never authoritative.
* Alpha Vantage: optional independent market observation when a user key exists.

No model is allowed to manufacture evidence, source success or order totals.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from adapters.nasdaq_symbol_directory import (  # noqa: E402
    NASDAQ_LISTED_URL,
    OTHER_LISTED_URL,
    ListingIdentity,
    merge_directories,
)

POLICY_PATH = ROOT / "config" / "v213-source-federation-policy.json"
TOP20_PATH = ROOT / "data" / "cache" / "top20_public_latest.json"
V212_PATH = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
OUTPUT_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
CACHE_ROOT = ROOT / "data" / "cache" / "v213-source-federation"
WORLD_BANK_URL = "https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=5"
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?lastNObservations=5&format=csvdata"
GLEIF_URL = "https://api.gleif.org/api/v1/lei-records"
ALPHA_URL = "https://www.alphavantage.co/query"


class FederationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FederationError(f"Invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise FederationError(f"Expected JSON object: {path}")
    return value


def load_top20(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FederationError(f"Invalid Top20 JSON: {path}") from exc
    if not isinstance(value, list) or len(value) != 20:
        raise FederationError("Top20 must contain exactly 20 records")
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(value, 1):
        if not isinstance(raw, dict):
            raise FederationError("Top20 record must be an object")
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not ticker or int(raw.get("rank") or 0) != index:
            raise FederationError("Top20 ticker/rank contract failed")
        rows.append(dict(raw))
    return rows


def load_v212(path: Path) -> dict[str, dict[str, Any]]:
    document = load_object(path)
    rows = document.get("records")
    if document.get("product_version") != "2.1.2" or not isinstance(rows, list) or len(rows) != 20:
        raise FederationError("v2.1.2 report contract failed")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise FederationError("v2.1.2 row must be an object")
        ticker = str(raw.get("ticker") or "").strip().upper()
        if ticker:
            result[ticker] = dict(raw)
    return result


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp",
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _cache_path(key: str) -> Path:
    return CACHE_ROOT / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".cache")


def cached_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    cache_hours: float,
    json_body: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: tuple[float, float] = (5, 30),
) -> tuple[bytes, str, bool]:
    key = json.dumps(
        {"method": method, "url": url, "json": json_body, "params": params},
        sort_keys=True,
        separators=(",", ":"),
    )
    path = _cache_path(key)
    if path.exists() and time.time() - path.stat().st_mtime <= cache_hours * 3600:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        return bytes.fromhex(str(envelope["body_hex"])), str(envelope["url"]), True
    response = session.request(
        method,
        url,
        json=json_body,
        params=params,
        headers=dict(headers or {}),
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.content
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    atomic_json(path, {"url": response.url, "body_hex": body.hex(), "retrieved_at": utc_now()})
    return body, response.url, False


def observation(
    source_id: str,
    family: str,
    tier: str,
    authority: str,
    role: str,
    status: str,
    url: str,
    *,
    as_of: str = "",
    detail: Mapping[str, Any] | None = None,
    official: bool = True,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "family": family,
        "tier": tier,
        "authority": authority,
        "role": role,
        "status": status,
        "url": url,
        "as_of": as_of,
        "official": official,
        "detail": dict(detail or {}),
    }


def fetch_world_bank(session: requests.Session) -> dict[str, Any]:
    body, final_url, cached = cached_request(session, "GET", WORLD_BANK_URL, cache_hours=24)
    value = json.loads(body.decode("utf-8-sig"))
    rows = value[1] if isinstance(value, list) and len(value) > 1 and isinstance(value[1], list) else []
    latest = next((item for item in rows if isinstance(item, dict) and item.get("value") is not None), None)
    if not latest:
        raise FederationError("World Bank returned no usable GDP observation")
    return observation(
        "world_bank_indicators", "world_bank", "T1", "World Bank",
        "official_macro_context", "HEALTHY", final_url,
        as_of=str(latest.get("date") or ""),
        detail={"series": "NY.GDP.MKTP.KD.ZG", "value": latest.get("value"), "cache_hit": cached},
    )


def fetch_bls(session: requests.Session) -> dict[str, Any]:
    series_ids = ["CUUR0000SA0", "WPUFD4", "CES0000000001"]
    body, final_url, cached = cached_request(
        session, "POST", BLS_URL, cache_hours=12,
        json_body={"seriesid": series_ids},
        headers={"content-type": "application/json"},
    )
    value = json.loads(body.decode("utf-8-sig"))
    status = str(value.get("status") or "") if isinstance(value, dict) else ""
    rows = value.get("Results", {}).get("series", []) if isinstance(value, dict) else []
    if status != "REQUEST_SUCCEEDED" or not isinstance(rows, list) or len(rows) < 2:
        raise FederationError(f"BLS response unusable: status={status}; series={len(rows) if isinstance(rows, list) else 0}")
    latest: dict[str, Any] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        data = item.get("data")
        first = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
        latest[str(item.get("seriesID") or "")] = {
            "year": first.get("year"), "period": first.get("period"), "value": first.get("value")
        }
    return observation(
        "bls_public_data", "us_bls", "T1", "U.S. Bureau of Labor Statistics",
        "official_labor_inflation_context", "HEALTHY", final_url,
        as_of=utc_now(), detail={"series": latest, "cache_hit": cached},
    )


def fetch_ecb(session: requests.Session) -> dict[str, Any]:
    body, final_url, cached = cached_request(
        session, "GET", ECB_URL, cache_hours=6,
        headers={"accept": "text/csv,application/vnd.ecb.data+csv;version=1.0.0"},
    )
    text = body.decode("utf-8-sig", errors="strict")
    rows = list(csv.DictReader(io.StringIO(text)))
    usable = [row for row in rows if isinstance(row, dict) and any(str(v or "").strip() for v in row.values())]
    if not usable:
        raise FederationError("ECB returned no usable CSV observations")
    latest = usable[-1]
    period = str(latest.get("TIME_PERIOD") or latest.get("Time period") or "")
    value = str(latest.get("OBS_VALUE") or latest.get("Observation value") or "")
    return observation(
        "ecb_sdmx", "ecb", "T1", "European Central Bank",
        "official_fx_and_financial_context", "HEALTHY", final_url,
        as_of=period, detail={"series": "EXR/D.USD.EUR.SP00.A", "value": value, "cache_hit": cached},
    )


def fetch_nasdaq(session: requests.Session) -> tuple[dict[str, ListingIdentity], dict[str, Any]]:
    documents: list[tuple[str, str]] = []
    cache_hits = 0
    for url in (NASDAQ_LISTED_URL, OTHER_LISTED_URL):
        body, final_url, cached = cached_request(session, "GET", url, cache_hours=1)
        documents.append((final_url, body.decode("utf-8-sig", errors="strict")))
        cache_hits += int(cached)
    listings = merge_directories(documents)
    if len(listings) < 1000:
        raise FederationError(f"Nasdaq symbol directories unexpectedly small: {len(listings)}")
    return listings, observation(
        "nasdaq_symbol_directory", "nasdaq", "T2", "Nasdaq",
        "regulated_listing_identity", "HEALTHY", NASDAQ_LISTED_URL,
        as_of=utc_now(), detail={"symbols": len(listings), "cache_hits": cache_hits},
    )


def normalize_name(value: Any) -> list[str]:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold())
    stop = {
        "inc", "incorporated", "corp", "corporation", "company", "co", "ltd", "limited",
        "plc", "holdings", "holding", "group", "class", "ordinary", "the",
    }
    return [token for token in text.split() if token and token not in stop]


def name_similarity(left: Any, right: Any) -> float:
    a, b = set(normalize_name(left)), set(normalize_name(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def fetch_gleif(session: requests.Session, company_name: str) -> dict[str, Any] | None:
    params = {"filter[entity.legalName]": company_name, "page[size]": 5}
    body, final_url, cached = cached_request(
        session, "GET", GLEIF_URL, cache_hours=24 * 7, params=params, timeout=(5, 25)
    )
    value = json.loads(body.decode("utf-8-sig"))
    rows = value.get("data") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        attrs = row.get("attributes")
        entity = attrs.get("entity") if isinstance(attrs, dict) else None
        legal_name = entity.get("legalName", {}).get("name") if isinstance(entity, dict) else None
        similarity = name_similarity(company_name, legal_name)
        if best is None or similarity > best[0]:
            best = (similarity, row)
    if best is None or best[0] < 0.45:
        return None
    row = best[1]
    attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
    entity = attrs.get("entity") if isinstance(attrs.get("entity"), dict) else {}
    registration = attrs.get("registration") if isinstance(attrs.get("registration"), dict) else {}
    return {
        "lei": str(attrs.get("lei") or row.get("id") or ""),
        "legal_name": str(entity.get("legalName", {}).get("name") or ""),
        "entity_status": str(entity.get("status") or ""),
        "registration_status": str(registration.get("status") or ""),
        "last_update": str(registration.get("lastUpdateDate") or ""),
        "similarity": round(best[0], 4),
        "url": final_url,
        "cache_hit": cached,
    }


def fetch_alpha_vantage(session: requests.Session, ticker: str, key: str) -> dict[str, Any] | None:
    body, final_url, cached = cached_request(
        session, "GET", ALPHA_URL, cache_hours=12,
        params={"function": "TIME_SERIES_WEEKLY_ADJUSTED", "symbol": ticker, "apikey": key},
        timeout=(5, 40),
    )
    value = json.loads(body.decode("utf-8-sig"))
    series = value.get("Weekly Adjusted Time Series") if isinstance(value, dict) else None
    if not isinstance(series, dict) or len(series) < 20:
        return None
    dates = sorted(series, reverse=True)
    latest = series[dates[0]] if dates else {}
    return {
        "url": final_url,
        "latest_date": dates[0] if dates else "",
        "latest_adjusted_close": latest.get("5. adjusted close") if isinstance(latest, dict) else None,
        "observations": len(series),
        "cache_hit": cached,
    }


def safe_source(callable_: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return callable_()
    except Exception as exc:
        result = dict(fallback)
        result["status"] = "DEGRADED"
        result["detail"] = {"error": f"{type(exc).__name__}: {exc}"[:500]}
        return result


def source_evidence_from_top20(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence = row.get("evidence")
    return [dict(item) for item in evidence if isinstance(item, dict)] if isinstance(evidence, list) else []


def family_ids(evidence: Iterable[Mapping[str, Any]]) -> set[str]:
    mapping = {
        "sec_edgar": "us_sec",
        "nasdaq_symbol_directory": "nasdaq",
        "gleif_lei": "gleif",
        "yahoo_finance_public_unofficial": "yahoo_finance",
        "alpha_vantage": "alpha_vantage",
    }
    return {mapping.get(str(item.get("source_id") or ""), str(item.get("source_id") or "")) for item in evidence if item.get("source_id")}


def evaluate_gates(document: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    sources = document.get("global_sources")
    sources = sources if isinstance(sources, list) else []
    successful = {str(row.get("family")) for row in sources if isinstance(row, dict) and row.get("status") == "HEALTHY"}
    official = {str(row.get("family")) for row in sources if isinstance(row, dict) and row.get("status") == "HEALTHY" and row.get("official") is True}
    required = {
        str(value.get("family"))
        for value in policy.get("required_live_sources", {}).values()
        if isinstance(value, dict) and value.get("required") is True
    }
    ticker_rows = document.get("ticker_sources")
    ticker_rows = ticker_rows if isinstance(ticker_rows, list) else []
    minimum = int(policy["minimum_per_ticker_independent_families"])
    meeting = sum(int(row.get("independent_family_count") or 0) >= minimum for row in ticker_rows if isinstance(row, dict))
    ratio = meeting / len(ticker_rows) if ticker_rows else 0.0
    conflicts = document.get("unresolved_material_conflicts")
    conflicts = conflicts if isinstance(conflicts, list) else []
    missing_required = sorted(required - successful)
    passed = (
        not missing_required
        and len(successful) >= int(policy["minimum_global_successful_families"])
        and len(official) >= int(policy["minimum_global_official_families"])
        and ratio >= float(policy["minimum_ticker_coverage_ratio"])
        and not conflicts
    )
    return {
        "pass": passed,
        "successful_families": sorted(successful),
        "official_successful_families": sorted(official),
        "missing_required_families": missing_required,
        "ticker_rows_meeting_minimum": meeting,
        "ticker_count": len(ticker_rows),
        "ticker_coverage_ratio": round(ratio, 4),
        "minimum_per_ticker_independent_families": minimum,
        "unresolved_material_conflict_count": len(conflicts),
        "yahoo_authoritative": False,
        "catalog_source_count_is_not_live_use": True,
    }


def build_live(top20: list[dict[str, Any]], v212: Mapping[str, Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    generated = utc_now()
    session = requests.Session()
    session.headers.update({
        "user-agent": os.getenv("SEC_CONTACT_EMAIL", "Investor Intelligence public research contact unavailable"),
        "accept-encoding": "gzip, deflate",
    })

    global_sources: list[dict[str, Any]] = []
    sec_coverage = sum(
        any(str(item.get("source_id")) == "sec_edgar" for item in source_evidence_from_top20(row))
        for row in top20
    )
    global_sources.append(observation(
        "sec_edgar", "us_sec", "T0", "U.S. Securities and Exchange Commission",
        "issuer_filings_and_financial_facts", "HEALTHY" if sec_coverage == 20 else "DEGRADED",
        "https://data.sec.gov", as_of=generated, detail={"ticker_coverage": sec_coverage},
    ))

    nasdaq_fallback = observation(
        "nasdaq_symbol_directory", "nasdaq", "T2", "Nasdaq",
        "regulated_listing_identity", "DEGRADED", NASDAQ_LISTED_URL,
    )
    listings: dict[str, ListingIdentity] = {}
    try:
        listings, nasdaq_source = fetch_nasdaq(session)
    except Exception as exc:
        nasdaq_source = dict(nasdaq_fallback)
        nasdaq_source["detail"] = {"error": f"{type(exc).__name__}: {exc}"[:500]}
    global_sources.append(nasdaq_source)

    global_sources.append(safe_source(
        lambda: fetch_world_bank(session),
        observation("world_bank_indicators", "world_bank", "T1", "World Bank", "official_macro_context", "DEGRADED", WORLD_BANK_URL),
    ))
    global_sources.append(safe_source(
        lambda: fetch_bls(session),
        observation("bls_public_data", "us_bls", "T1", "U.S. Bureau of Labor Statistics", "official_labor_inflation_context", "DEGRADED", BLS_URL),
    ))
    global_sources.append(safe_source(
        lambda: fetch_ecb(session),
        observation("ecb_sdmx", "ecb", "T1", "European Central Bank", "official_fx_and_financial_context", "DEGRADED", ECB_URL),
    ))

    alpha_key = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
    ticker_rows: list[dict[str, Any]] = []
    gleif_matches = 0
    nasdaq_matches = 0
    alpha_matches = 0
    all_evidence: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for index, row in enumerate(top20, 1):
        ticker = str(row["ticker"])
        name = str(row.get("name") or ticker)
        print(f"II_PROGRESS source federation {index}/20 | {ticker}", flush=True)
        evidence = source_evidence_from_top20(row)
        listing = listings.get(ticker) or listings.get(ticker.replace("-", "."))
        if listing:
            nasdaq_matches += 1
            evidence.append({
                "source_id": "nasdaq_symbol_directory",
                "tier": "T2",
                "claim_type": "regulated_listing_identity",
                "title": f"{listing.exchange} listing identity for {ticker}: {listing.security_name}"[:240],
                "url": listing.source_url,
                "as_of": generated,
            })

        gleif = None
        try:
            gleif = fetch_gleif(session, name)
        except Exception:
            gleif = None
        if gleif:
            gleif_matches += 1
            evidence.append({
                "source_id": "gleif_lei",
                "tier": "T2",
                "claim_type": "legal_entity_reference",
                "title": f"GLEIF legal entity match: {gleif['legal_name']} ({gleif['lei']})"[:240],
                "url": str(gleif["url"]),
                "as_of": str(gleif.get("last_update") or generated),
            })

        alpha = None
        if alpha_key and index <= 5:
            try:
                alpha = fetch_alpha_vantage(session, ticker, alpha_key)
            except Exception:
                alpha = None
        if alpha:
            alpha_matches += 1
            evidence.append({
                "source_id": "alpha_vantage",
                "tier": "T3",
                "claim_type": "independent_market_observation",
                "title": f"Alpha Vantage adjusted weekly observation for {ticker}",
                "url": str(alpha["url"]),
                "as_of": str(alpha.get("latest_date") or generated),
            })

        if ticker in v212 and str(v212[ticker].get("market_source") or "") == "yfinance":
            evidence.append({
                "source_id": "yahoo_finance_public_unofficial",
                "tier": "T3",
                "claim_type": "public_market_observation",
                "title": f"Yahoo/yfinance adjusted-close observation for {ticker}",
                "url": f"https://finance.yahoo.com/quote/{ticker}",
                "as_of": str(v212[ticker].get("retrieved_at") or generated),
            })

        families = family_ids(evidence)
        official_families = families & {"us_sec", "nasdaq", "gleif"}
        market_families = families & {"yahoo_finance", "alpha_vantage"}
        ticker_rows.append({
            "rank": index,
            "ticker": ticker,
            "name": name,
            "source_ids": sorted({str(item.get("source_id")) for item in evidence if item.get("source_id")}),
            "independent_families": sorted(families),
            "independent_family_count": len(families),
            "official_identity_or_filing_families": sorted(official_families),
            "official_identity_or_filing_family_count": len(official_families),
            "market_observation_families": sorted(market_families),
            "market_provider_confidence": "MULTI_PROVIDER" if len(market_families) >= 2 else "SINGLE_PROVIDER_DEGRADED",
            "issuer_financial_claim_family_count": int("us_sec" in families),
            "evidence_additions": [
                item for item in evidence
                if str(item.get("source_id")) in {"nasdaq_symbol_directory", "gleif_lei", "alpha_vantage"}
            ],
            "gleif_match": gleif,
            "listing_identity": None if listing is None else {
                "security_name": listing.security_name,
                "exchange": listing.exchange,
                "source_url": listing.source_url,
            },
        })
        all_evidence.extend(evidence)

    global_sources.append(observation(
        "gleif_lei", "gleif", "T2", "Global Legal Entity Identifier Foundation",
        "independent_legal_entity_identity", "HEALTHY" if gleif_matches else "DEGRADED",
        GLEIF_URL, as_of=generated, detail={"ticker_matches": gleif_matches, "ticker_count": 20},
    ))
    global_sources.append(observation(
        "yahoo_finance_public_unofficial", "yahoo_finance", "T3", "Yahoo Finance / yfinance",
        "candidate_discovery_and_market_observation_only", "HEALTHY", "https://finance.yahoo.com/",
        as_of=generated, detail={"authoritative": False, "ticker_observations": len(v212)}, official=False,
    ))
    global_sources.append(observation(
        "alpha_vantage", "alpha_vantage", "T3", "Alpha Vantage",
        "optional_independent_market_observation", "HEALTHY" if alpha_matches else "SKIPPED",
        ALPHA_URL, as_of=generated,
        detail={"ticker_matches": alpha_matches, "credential_present": bool(alpha_key)}, official=False,
    ))

    family_counter: Counter[str] = Counter()
    for item in all_evidence:
        for family in family_ids([item]):
            family_counter[family] += 1
    total = sum(family_counter.values()) or 1
    largest_family, largest_count = family_counter.most_common(1)[0] if family_counter else ("", 0)
    document: dict[str, Any] = {
        "schema_version": 1,
        "product_version": "2.1.3",
        "policy_id": str(policy["policy_id"]),
        "generated_at": generated,
        "catalog_source_count_is_not_live_use": True,
        "global_sources": global_sources,
        "ticker_sources": ticker_rows,
        "unresolved_material_conflicts": unresolved,
        "coverage": {
            "nasdaq_listing_matches": nasdaq_matches,
            "gleif_identity_matches": gleif_matches,
            "alpha_vantage_market_matches": alpha_matches,
            "yahoo_market_observations": len(v212),
        },
        "concentration": {
            "family_counts": dict(sorted(family_counter.items())),
            "largest_family": largest_family,
            "largest_family_share": round(largest_count / total, 4),
            "maximum_single_family_evidence_share": float(policy["maximum_single_family_evidence_share"]),
        },
        "disclosures": {
            "yahoo_is_authoritative": False,
            "single_market_provider_is_degraded": True,
            "source_catalog_size_is_not_live_source_count": True,
            "different_claim_scopes_are_not_false_corroboration": True,
            "issuer_financials_remain_sec_primary_until_independent_claim_source_exists": True,
            "local_model_may_not_create_source_success": True,
        },
    }
    document["gates"] = evaluate_gates(document, policy)
    return document


def self_test() -> None:
    policy = load_object(POLICY_PATH)
    generated = "2026-09-02T00:00:00Z"
    global_sources = [
        observation("sec_edgar", "us_sec", "T0", "SEC", "financial", "HEALTHY", "https://data.sec.gov", as_of=generated),
        observation("nasdaq_symbol_directory", "nasdaq", "T2", "Nasdaq", "identity", "HEALTHY", NASDAQ_LISTED_URL, as_of=generated),
        observation("world_bank_indicators", "world_bank", "T1", "World Bank", "macro", "HEALTHY", WORLD_BANK_URL, as_of=generated),
        observation("bls_public_data", "us_bls", "T1", "BLS", "macro", "HEALTHY", BLS_URL, as_of=generated),
        observation("ecb_sdmx", "ecb", "T1", "ECB", "macro", "HEALTHY", ECB_URL, as_of=generated),
    ]
    tickers = [{
        "rank": i + 1,
        "ticker": f"T{i:02d}",
        "independent_family_count": 2,
    } for i in range(20)]
    doc = {
        "global_sources": global_sources,
        "ticker_sources": tickers,
        "unresolved_material_conflicts": [],
    }
    gates = evaluate_gates(doc, policy)
    assert gates["pass"] is True
    duplicate_urls = family_ids([
        {"source_id": "sec_edgar"},
        {"source_id": "sec_edgar"},
        {"source_id": "nasdaq_symbol_directory"},
    ])
    assert duplicate_urls == {"us_sec", "nasdaq"}
    bad = dict(doc)
    bad["ticker_sources"] = [dict(row, independent_family_count=1) for row in tickers]
    assert evaluate_gates(bad, policy)["pass"] is False
    assert name_similarity("NVIDIA Corporation", "NVIDIA CORP") >= 0.99
    print("V213_SOURCE_FEDERATION_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--top20", type=Path, default=TOP20_PATH)
    parser.add_argument("--v212", type=Path, default=V212_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    policy = load_object(args.policy)
    document = build_live(load_top20(args.top20), load_v212(args.v212), policy)
    atomic_json(args.output, document)
    gates = document["gates"]
    print(
        "V213_SOURCE_FEDERATION = {status}; global={global_count}; official={official_count}; "
        "ticker_coverage={coverage:.1%}; missing_required={missing}; conflicts={conflicts}".format(
            status="PASS" if gates["pass"] else "FAIL",
            global_count=len(gates["successful_families"]),
            official_count=len(gates["official_successful_families"]),
            coverage=float(gates["ticker_coverage_ratio"]),
            missing=",".join(gates["missing_required_families"]) or "none",
            conflicts=gates["unresolved_material_conflict_count"],
        ),
        flush=True,
    )
    return 0 if gates["pass"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FederationError, OSError, requests.RequestException, ValueError) as exc:
        print(f"V213_SOURCE_FEDERATION = FAIL; {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
