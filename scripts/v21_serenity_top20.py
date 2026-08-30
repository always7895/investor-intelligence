#!/usr/bin/env python3
"""Investor Intelligence v2.1.0 Serenity-first automatic public Top 20.

Design boundaries:
- Load and report the full 99-source authoritative catalog every run.
- Do not claim catalog membership is live activation.
- v2.1 reviewed source overlay: SEC EDGAR + World Bank only.
- yfinance is T3 local candidate discovery / public-market observation only.
- Serenity-first seven-factor score is project-authored operationalization.
- Leopold Aschenbrenner infrastructure context is a separate overlay and is
  never added to the Serenity score.
- Public outputs contain no portfolio, holding, cost, P&L, LINE ID, tenant ID,
  broker, or raw provider payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from adapters import parse_source_payload
from authoritative_source_catalog import inventory, load_catalog

POLICY_PATH = ROOT / "config" / "v21-serenity-policy.json"
ACTIVATION_PATH = ROOT / "config" / "v21-source-activation.json"
CACHE_ROOT = ROOT / "data" / "cache" / "v21"
PUBLIC_ROOT = ROOT / "data" / "cache"
REPORT_ROOT = ROOT / "reports"

TOP20_PATH = PUBLIC_ROOT / "top20_public_latest.json"
PLAN_PATH = PUBLIC_ROOT / "source_plan_public_latest.json"
METADATA_PATH = PUBLIC_ROOT / "public_snapshot_metadata.json"
REPORT_PATH = REPORT_ROOT / "public_briefing_latest.md"

TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,14}$")
AI_WORDS = {
    "artificial intelligence", "ai infrastructure", "data center", "datacenter",
    "gpu", "accelerator", "asic", "semiconductor", "optical", "photonics",
    "laser", "ethernet", "networking", "interconnect", "hbm", "memory",
    "foundry", "wafer", "advanced packaging", "power", "grid", "transformer",
    "switchgear", "cooling", "natural gas", "nuclear", "cloud", "neocloud",
}
CHOKE_WORDS = {
    "optical", "photonics", "laser", "hbm", "memory", "foundry", "wafer",
    "advanced packaging", "substrate", "transformer", "switchgear", "grid",
    "interconnect", "cooling", "power",
}
DOMAIN_A = {"power", "grid", "transformer", "switchgear", "cooling", "energy", "natural gas", "nuclear", "datacenter", "data center"}
DOMAIN_B = {"gpu", "accelerator", "asic", "compute", "cloud", "neocloud", "ethernet", "network", "interconnect"}
DOMAIN_C = {"hbm", "memory", "optical", "photonics", "laser", "fiber", "foundry", "wafer", "packaging", "substrate"}

LOGGER = logging.getLogger("v21-serenity")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class Evidence:
    source_id: str
    tier: str
    claim_type: str
    title: str
    url: str
    as_of: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"Invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temp = Path(handle.name)
    os.replace(temp, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    ) as handle:
        handle.write(value)
        if not value.endswith("\n"):
            handle.write("\n")
        temp = Path(handle.name)
    os.replace(temp, path)


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def ratio(value: Any) -> float | None:
    parsed = finite(value)
    if parsed is None:
        return None
    return parsed / 100.0 if abs(parsed) > 10 else parsed


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not TICKER_RE.fullmatch(text) or ".." in text or text.endswith((".", "-")):
        return ""
    return text


def session() -> requests.Session:
    retry = Retry(
        total=3, connect=3, read=3, status=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    value = requests.Session()
    value.mount("https://", HTTPAdapter(max_retries=retry))
    return value


def cached(path: Path, hours: int) -> Any | None:
    if not path.is_file():
        return None
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    if utc_now() - modified > timedelta(hours=max(0, hours)):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def get_json(
    http: requests.Session,
    url: str,
    *,
    headers: Mapping[str, str],
    cache_path: Path,
    cache_hours: int,
    minimum_delay: float = 0.0,
) -> Any:
    value = cached(cache_path, cache_hours)
    if value is not None:
        return value
    if minimum_delay:
        time.sleep(minimum_delay)
    response = http.get(url, headers=dict(headers), timeout=(10, 45))
    if not 200 <= response.status_code < 300:
        if cache_path.is_file():
            try:
                stale = json.loads(cache_path.read_text(encoding="utf-8"))
                LOGGER.warning("HTTP %s; using stale cache for %s", response.status_code, url)
                return stale
            except (OSError, json.JSONDecodeError):
                pass
        raise PipelineError(f"HTTP {response.status_code}: {url}")
    try:
        value = response.json()
    except ValueError as exc:
        raise PipelineError(f"Non-JSON response: {url}") from exc
    atomic_json(cache_path, value)
    return value


def validate_policy() -> tuple[dict[str, Any], dict[str, Any]]:
    policy = load_object(POLICY_PATH)
    activation = load_object(ACTIVATION_PATH)

    weights = policy.get("factor_weights")
    expected = {
        "demand_wave",
        "chokepoint",
        "pricing_power",
        "replacement_friction",
        "tam_capture",
        "valuation_expectations",
        "evidence_quality",
    }
    if not isinstance(weights, dict) or set(weights) != expected or sum(int(v) for v in weights.values()) != 100:
        raise PipelineError("Serenity factor policy must contain seven factors totaling 100")

    if (
        activation.get("automatic_activation") is not False
        or activation.get("free_only") is not True
        or activation.get("public_data_only") is not True
    ):
        raise PipelineError("Source activation policy is not fail-closed")

    selected = activation.get("selected_sources")
    if not isinstance(selected, dict) or set(selected) != {"sec_edgar", "world_bank_indicators"}:
        raise PipelineError("Reviewed v2.1 source overlay must be SEC EDGAR + World Bank")
    for source_id, row in selected.items():
        if (
            not isinstance(row, dict)
            or row.get("runtime_enabled") is not True
            or row.get("rights_status") != "reviewed_public_access"
            or row.get("adapter_status") != "adapter_reviewed"
            or not isinstance(row.get("gates"), dict)
            or not all(row["gates"].values())
        ):
            raise PipelineError(f"Incomplete reviewed activation: {source_id}")

    yahoo = activation.get("discovery_only_sources", {}).get("yahoo_finance_public_unofficial")
    if (
        not isinstance(yahoo, dict)
        or yahoo.get("runtime_enabled") is not False
        or yahoo.get("authoritative") is not False
        or yahoo.get("raw_payload_redistribution") is not False
    ):
        raise PipelineError("yfinance boundary must remain T3 discovery-only")
    return policy, activation


def source_plan(policy: Mapping[str, Any], activation: Mapping[str, Any]) -> dict[str, Any]:
    _manifest, sources, warnings = load_catalog()
    required = int(policy["required_catalog_count"])
    if len(sources) != required:
        raise PipelineError(f"Catalog count changed: {len(sources)} != {required}")

    by_id = {source.id: source for source in sources}
    selected = set(activation["selected_sources"])
    discovery = set(activation["discovery_only_sources"])
    if not selected.issubset(by_id) or not discovery.issubset(by_id):
        raise PipelineError("Activation references unknown catalog source IDs")

    members = []
    for source in sorted(sources, key=lambda item: item.id):
        if source.id in selected:
            state = "v21_reviewed_live_overlay"
        elif source.id in discovery:
            state = "t3_local_discovery_only"
        else:
            state = "deferred_catalog_member"
        members.append(
            {
                "source_id": source.id,
                "display_name": source.display_name,
                "tier": source.evidence_tier,
                "role": source.evidence_role,
                "topics": list(source.topics),
                "catalog_runtime_enabled": source.runtime_enabled,
                "v21_state": state,
            }
        )
    return {
        "schema_version": 1,
        "catalog_count": len(sources),
        "catalog_source_count_snapshot_is_not_a_limit": True,
        "automatic_activation": False,
        "selected_reviewed_sources": sorted(selected),
        "discovery_only_sources": sorted(discovery),
        "deferred_count": len(sources) - len(selected) - len(discovery),
        "inventory": inventory(sources),
        "warnings": warnings,
        "members": members,
        "line_public_eligible": True,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }


def discover_candidates(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise PipelineError("Verified runtime lacks yfinance") from exc

    merged: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for spec in policy["candidate_screeners"]:
        name = str(spec["name"])
        weight = float(spec["weight"])
        try:
            payload = yf.screen(name, count=int(policy["per_screener_count"]))
            quotes = payload.get("quotes") if isinstance(payload, dict) else None
            if not isinstance(quotes, list):
                raise ValueError("no quotes")
        except Exception as exc:
            failures.append(f"{name}:{type(exc).__name__}")
            continue
        for raw in quotes:
            if not isinstance(raw, dict):
                continue
            symbol = ticker(raw.get("symbol"))
            if not symbol:
                continue
            entry = merged.setdefault(
                symbol,
                {"ticker": symbol, "screen_weight": 0.0, "screeners": [], "market": {}},
            )
            entry["screen_weight"] += weight
            entry["screeners"].append(name)
            if len(raw) > len(entry["market"]):
                entry["market"] = dict(raw)

    if not merged:
        value = cached(CACHE_ROOT / "candidate_seed.json", int(policy["candidate_cache_hours"]))
        if isinstance(value, list) and value:
            return [item for item in value if isinstance(item, dict)]
        raise PipelineError("All T3 candidate screeners failed: " + ", ".join(failures))

    ranked = sorted(
        merged.values(),
        key=lambda item: (-float(item["screen_weight"]), str(item["ticker"])),
    )
    ranked = ranked[: int(policy["candidate_seed_limit"])]
    atomic_json(CACHE_ROOT / "candidate_seed.json", ranked)
    return ranked


def sec_reference(policy: Mapping[str, Any], http: requests.Session, headers: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    url = str(policy["sec_ticker_exchange_url"])
    raw = get_json(
        http,
        url,
        headers=headers,
        cache_path=CACHE_ROOT / "sec_company_tickers_exchange.json",
        cache_hours=24,
        minimum_delay=0.12,
    )
    if not isinstance(raw, dict) or not isinstance(raw.get("fields"), list) or not isinstance(raw.get("data"), list):
        raise PipelineError("SEC ticker exchange JSON shape changed")
    fields = [str(x) for x in raw["fields"]]
    result: dict[str, dict[str, Any]] = {}
    for row in raw["data"]:
        if not isinstance(row, list) or len(row) != len(fields):
            continue
        item = dict(zip(fields, row))
        symbol = ticker(item.get("ticker"))
        if not symbol:
            continue
        result[symbol] = {
            "ticker": symbol,
            "cik": str(item.get("cik") or "").zfill(10),
            "name": str(item.get("name") or symbol).strip(),
            "exchange": str(item.get("exchange") or "").strip(),
        }
    if not result:
        raise PipelineError("SEC ticker reference contains no usable records")
    return result


def market_value(record: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = finite(record.get(name))
        if value is not None:
            return value
    return None


def prelim(seed: Mapping[str, Any]) -> float:
    market = seed.get("market") if isinstance(seed.get("market"), dict) else {}
    cap = market_value(market, "marketCap") or 1.0
    volume = market_value(market, "averageDailyVolume3Month", "regularMarketVolume") or 1.0
    return (
        float(seed.get("screen_weight") or 0.0) * 10
        + clamp(math.log10(cap) - 8, 0, 4) * 3
        + clamp(math.log10(volume) - 5, 0, 3) * 2
    )


def validate_candidates(
    seeds: Sequence[Mapping[str, Any]],
    reference: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    allowed = {str(x).casefold() for x in policy["allowed_exchanges"]}
    result = []
    for seed in seeds:
        symbol = ticker(seed.get("ticker"))
        official = reference.get(symbol)
        if not official or str(official["exchange"]).casefold() not in allowed:
            continue
        market = seed.get("market") if isinstance(seed.get("market"), dict) else {}
        price = market_value(market, "regularMarketPrice", "regularMarketPreviousClose")
        cap = market_value(market, "marketCap")
        volume = market_value(market, "averageDailyVolume3Month", "regularMarketVolume")
        if price is not None and price < float(policy["minimum_price"]):
            continue
        if cap is not None and cap < float(policy["minimum_market_cap"]):
            continue
        if volume is not None and volume < float(policy["minimum_average_volume"]):
            continue
        result.append({**dict(seed), "official": dict(official), "preliminary": prelim(seed)})
    result.sort(key=lambda item: (-float(item["preliminary"]), str(item["ticker"])))
    result = result[: int(policy["sec_candidate_limit"])]
    if len(result) < int(policy["top_count"]):
        raise PipelineError(f"Only {len(result)} SEC-validated candidates remain")
    return result


def validate_sec_adapter(raw: Any, url: str) -> list[dict[str, Any]]:
    payload = (
        json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")
    batch = parse_source_payload(
        "sec_edgar",
        payload,
        content_type="application/json",
        retrieved_at=iso_now(),
        context={"request_url": url},
    )
    return [dict(x) for x in batch.records]


def sec_companyfacts(
    candidate: Mapping[str, Any],
    policy: Mapping[str, Any],
    http: requests.Session,
    headers: Mapping[str, str],
) -> list[dict[str, Any]]:
    cik = str(candidate["official"]["cik"])
    url = str(policy["sec_companyfacts_url"]).format(cik=cik)
    raw = get_json(
        http,
        url,
        headers=headers,
        cache_path=CACHE_ROOT / "companyfacts" / f"CIK{cik}.json",
        cache_hours=24,
        minimum_delay=float(policy["sec_minimum_interval_seconds"]),
    )
    if not isinstance(raw, dict):
        raise PipelineError(f"SEC companyfacts invalid for {candidate['ticker']}")
    return validate_sec_adapter(raw, url)


def latest_records(records: Sequence[Mapping[str, Any]], tag_names: Sequence[str]) -> list[dict[str, Any]]:
    wanted = set(tag_names)
    values = [
        dict(item)
        for item in records
        if item.get("record_type") == "company_fact"
        and item.get("taxonomy") == "us-gaap"
        and item.get("tag") in wanted
        and item.get("form") in {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "40-F"}
    ]
    values.sort(
        key=lambda item: (
            str(item.get("end") or ""),
            str(item.get("filed") or ""),
            str(item.get("accession_number") or ""),
        ),
        reverse=True,
    )
    return values


def latest_value(records: Sequence[Mapping[str, Any]], tags: Sequence[str], *, duration: bool) -> dict[str, Any] | None:
    for item in latest_records(records, tags):
        has_start = bool(item.get("start"))
        if has_start == duration:
            return item
    return None


def annual_values(records: Sequence[Mapping[str, Any]], tags: Sequence[str]) -> list[dict[str, Any]]:
    by_year: dict[int, dict[str, Any]] = {}
    for item in latest_records(records, tags):
        if item.get("form") not in {"10-K", "10-K/A", "20-F", "40-F"}:
            continue
        try:
            year = int(item.get("fiscal_year"))
        except (TypeError, ValueError):
            continue
        prior = by_year.get(year)
        if prior is None or str(item.get("filed") or "") > str(prior.get("filed") or ""):
            by_year[year] = dict(item)
    return [by_year[year] for year in sorted(by_year, reverse=True)]


def metrics(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, float | None], list[Evidence]]:
    revenue_tags = (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    )
    revenue_annual = annual_values(records, revenue_tags)
    revenue_growth = None
    if len(revenue_annual) >= 2:
        current = finite(revenue_annual[0].get("value"))
        previous = finite(revenue_annual[1].get("value"))
        if current is not None and previous is not None and previous > 0:
            revenue_growth = current / previous - 1

    revenue = latest_value(records, revenue_tags, duration=True)
    gross = latest_value(records, ("GrossProfit",), duration=True)
    operating = latest_value(records, ("OperatingIncomeLoss",), duration=True)
    net = latest_value(records, ("NetIncomeLoss", "ProfitLoss"), duration=True)
    equity = latest_value(
        records,
        ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        duration=False,
    )

    revenue_value = finite(revenue.get("value")) if revenue else None
    gross_margin = (
        finite(gross.get("value")) / revenue_value
        if gross and revenue_value and revenue_value > 0 and finite(gross.get("value")) is not None
        else None
    )
    operating_margin = (
        finite(operating.get("value")) / revenue_value
        if operating and revenue_value and revenue_value > 0 and finite(operating.get("value")) is not None
        else None
    )
    net_margin = (
        finite(net.get("value")) / revenue_value
        if net and revenue_value and revenue_value > 0 and finite(net.get("value")) is not None
        else None
    )

    debt_items = latest_records(
        records,
        ("LongTermDebtCurrent", "LongTermDebtNoncurrent", "LongTermDebt"),
    )
    debt = finite(debt_items[0].get("value")) if debt_items else None
    equity_value = finite(equity.get("value")) if equity else None
    debt_to_equity = debt / equity_value if debt is not None and equity_value and equity_value > 0 else None

    evidence: list[Evidence] = []
    seen = set()
    for item in [*(revenue_annual[:2]), revenue, gross, operating, net, equity]:
        if not isinstance(item, dict):
            continue
        identity = (str(item.get("tag")), str(item.get("end")), str(item.get("accession_number")))
        if identity in seen:
            continue
        seen.add(identity)
        evidence.append(
            Evidence(
                source_id="sec_edgar",
                tier="T0",
                claim_type="xbrl_fact",
                title=f"SEC XBRL {item.get('tag')} ({item.get('form')}, {str(item.get('end'))[:10]})",
                url=str(item.get("record_url") or "https://data.sec.gov/api/xbrl/companyfacts/"),
                as_of=str(item.get("end") or iso_now()),
            )
        )
        if len(evidence) >= 5:
            break

    return {
        "revenue_growth": revenue_growth,
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "debt_to_equity": debt_to_equity,
    }, evidence


def keywords(market: Mapping[str, Any]) -> str:
    return " ".join(
        str(market.get(name) or "")
        for name in ("sector", "industry", "shortName", "longName", "displayName")
    ).casefold()


def contains(text: str, words: Iterable[str]) -> bool:
    return any(word.casefold() in text for word in words)


def score_candidate(candidate: Mapping[str, Any], official_metrics: Mapping[str, Any], evidence: Sequence[Evidence], policy: Mapping[str, Any]) -> dict[str, Any]:
    weights = policy["factor_weights"]
    market = candidate.get("market") if isinstance(candidate.get("market"), dict) else {}
    text = keywords(market)

    rev = finite(official_metrics.get("revenue_growth"))
    gross = finite(official_metrics.get("gross_margin"))
    operating = finite(official_metrics.get("operating_margin"))
    net = finite(official_metrics.get("net_margin"))
    debt_equity = finite(official_metrics.get("debt_to_equity"))

    pe = market_value(market, "forwardPE")
    ps = market_value(market, "priceToSalesTrailing12Months")
    beta = market_value(market, "beta")
    short_float = ratio(market.get("shortPercentOfFloat"))

    demand_fraction = (0.25 if contains(text, AI_WORDS) else 0.0)
    if rev is not None:
        demand_fraction += clamp((rev + 0.05) / 0.55, 0, 0.75)
    demand = round(int(weights["demand_wave"]) * clamp(demand_fraction, 0, 1))

    choke_fraction = 0.60 if contains(text, CHOKE_WORDS) else 0.20 if contains(text, AI_WORDS) else 0.0
    if gross is not None:
        choke_fraction += clamp((gross - 0.25) / 0.50, 0, 0.25)
    chokepoint = round(int(weights["chokepoint"]) * clamp(choke_fraction, 0, 1))

    pricing_fraction = 0.0
    if gross is not None:
        pricing_fraction += clamp((gross - 0.15) / 0.55, 0, 0.65)
    if operating is not None:
        pricing_fraction += clamp((operating + 0.05) / 0.40, 0, 0.35)
    pricing = round(int(weights["pricing_power"]) * clamp(pricing_fraction, 0, 1))

    friction_fraction = 0.65 if contains(text, CHOKE_WORDS) else 0.20 if contains(text, AI_WORDS) else 0.0
    if gross is not None and gross > 0.45:
        friction_fraction += 0.20
    if len(evidence) >= 3:
        friction_fraction += 0.15
    friction = round(int(weights["replacement_friction"]) * clamp(friction_fraction, 0, 1))

    capture_fraction = clamp(((rev or -0.05) + 0.05) / 0.55, 0, 1)
    tam = round(int(weights["tam_capture"]) * capture_fraction)

    valuation_fraction = 0.0
    if ps is not None and ps > 0:
        valuation_fraction += 0.5 if ps <= 5 else 0.35 if ps <= 10 else 0.18 if ps <= 15 else 0.05
    if pe is not None and pe > 0:
        valuation_fraction += 0.4 if pe <= 20 else 0.3 if pe <= 35 else 0.15 if pe <= 60 else 0.03
    if rev is not None and rev > 0.30:
        valuation_fraction += 0.10
    valuation = round(int(weights["valuation_expectations"]) * clamp(valuation_fraction, 0, 1))

    completeness = [rev, gross, operating, net, debt_equity, pe, ps, beta, short_float]
    available = sum(value is not None for value in completeness)
    quality = clamp((available / len(completeness)) * 0.65 + min(len(evidence), 4) / 4 * 0.35, 0, 1)
    evidence_score = round(int(weights["evidence_quality"]) * quality)

    factors = {
        "demand_wave": demand,
        "chokepoint": chokepoint,
        "pricing_power": pricing,
        "replacement_friction": friction,
        "tam_capture": tam,
        "valuation_expectations": valuation,
        "evidence_quality": evidence_score,
    }

    risks = []
    penalty = 0
    if rev is not None and rev < 0:
        penalty += 5
        risks.append("negative_revenue_growth")
    if net is not None and net < -0.10:
        penalty += 4
        risks.append("deep_negative_net_margin")
    if debt_equity is not None and debt_equity > 2:
        penalty += 4
        risks.append("high_debt_to_equity")
    if beta is not None and beta > 2.5:
        penalty += 3
        risks.append("high_beta")
    if short_float is not None and short_float > 0.20:
        penalty += 3
        risks.append("high_short_interest")
    penalty = min(int(policy["maximum_risk_penalty"]), penalty)

    raw = sum(factors.values())
    serenity = int(clamp(raw - penalty, 0, 100))

    domains = {
        "A": sum(word in text for word in DOMAIN_A),
        "B": sum(word in text for word in DOMAIN_B),
        "C": sum(word in text for word in DOMAIN_C),
    }
    domain = max(domains, key=lambda key: (domains[key], key)) if any(domains.values()) else None
    overlay = {
        "domain": domain,
        "fit_score": min(100, max(domains.values(), default=0) * 20),
        "included_in_serenity_score": False,
        "attribution": "system_operationalization_not_aschenbrenner_stock_score",
    }

    return {
        "ticker": candidate["ticker"],
        "name": candidate["official"]["name"],
        "serenity_score": serenity,
        "serenity_raw_score": raw,
        "risk_penalty": penalty,
        "data_quality": round(quality, 4),
        "rating": "S" if serenity >= 85 else "A" if serenity >= 75 else "B" if serenity >= 65 else "C" if serenity >= 55 else "D" if serenity >= 45 else "F",
        "category": str(market.get("industry") or market.get("sector") or "Public equity"),
        "serenity_factors": factors,
        "risk_flags": sorted(set(risks)),
        "aschenbrenner_overlay": overlay,
        "evidence": [asdict(x) for x in evidence],
        "evidence_count": len(evidence),
        "source_count": len({x.source_id for x in evidence} | {"yahoo_finance_public_unofficial"}),
        "scoring_version": "serenity-first-v2.1.0",
        "line_public_eligible": True,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }


def synthetic_candidates() -> list[tuple[dict[str, Any], dict[str, Any], list[Evidence]]]:
    result = []
    categories = (
        "Semiconductors optical networking",
        "Grid transformer power infrastructure",
        "Cloud AI compute networking",
        "Advanced packaging memory HBM",
    )
    for index in range(30):
        symbol = f"T{index:02d}"
        market = {
            "industry": categories[index % len(categories)],
            "marketCap": 2_000_000_000 + index * 900_000_000,
            "averageDailyVolume3Month": 900_000 + index * 30_000,
            "forwardPE": 15 + index,
            "priceToSalesTrailing12Months": 2.5 + index * 0.2,
            "beta": 1.0 + index * 0.03,
            "shortPercentOfFloat": 0.03 + index * 0.002,
        }
        candidate = {
            "ticker": symbol,
            "official": {"name": f"Synthetic Company {index}"},
            "market": market,
        }
        metrics_value = {
            "revenue_growth": 0.60 - index * 0.012,
            "gross_margin": 0.50 - (index % 5) * 0.025,
            "operating_margin": 0.18 - (index % 4) * 0.02,
            "net_margin": 0.12 - (index % 4) * 0.015,
            "debt_to_equity": 0.4 + index * 0.02,
        }
        evidence = [
            Evidence(
                "sec_edgar",
                "T0",
                "xbrl_fact",
                f"Synthetic SEC fact {symbol}",
                f"https://www.sec.gov/Archives/edgar/data/{1000000 + index}/synthetic.htm",
                "2026-06-30T00:00:00+00:00",
            )
            for _ in range(4)
        ]
        result.append((candidate, metrics_value, evidence))
    return result


def world_bank_context(policy: Mapping[str, Any], http: requests.Session) -> dict[str, Any]:
    url = str(policy["world_bank_url"])
    try:
        raw = get_json(
            http,
            url,
            headers={"User-Agent": "Investor Intelligence 2.1 public research"},
            cache_path=CACHE_ROOT / "world_bank_gdp_growth.json",
            cache_hours=24,
        )
    except PipelineError:
        return {"source_id": "world_bank_indicators", "status": "DEGRADED"}
    observations = raw[1] if isinstance(raw, list) and len(raw) >= 2 and isinstance(raw[1], list) else []
    latest = next(
        (item for item in observations if isinstance(item, dict) and finite(item.get("value")) is not None),
        None,
    )
    if latest is None:
        return {"source_id": "world_bank_indicators", "status": "DEGRADED"}
    return {
        "source_id": "world_bank_indicators",
        "status": "HEALTHY",
        "period": str(latest.get("date") or ""),
        "value": finite(latest.get("value")),
        "url": url,
    }


def build_report(records: Sequence[Mapping[str, Any]], plan: Mapping[str, Any], macro: Mapping[str, Any], generated: str) -> str:
    lines = [
        "<!-- line-public-eligible: true -->",
        "<!-- provider-scope: public_only -->",
        "<!-- owner-watchlist-inherited: false -->",
        "# Investor Intelligence v2.1.0 — Serenity-first 公開 Top 20",
        "",
        f"生成時間：{generated}",
        "",
        "> 此排名為專案自訂 Serenity-first operationalization，不是 Serenity 本人公布公式、背書、個人化投資建議或報酬保證。Aschenbrenner A/B/C 為獨立 overlay，不加入 Serenity 分數。",
        "",
        f"99-source planner：catalog={plan['catalog_count']}；reviewed live overlay={','.join(plan['selected_reviewed_sources'])}；T3 discovery={','.join(plan['discovery_only_sources'])}；deferred={plan['deferred_count']}。",
        f"World Bank macro context：{macro.get('status', 'DEGRADED')}",
        "",
        "## Top 20",
        "",
    ]
    for item in records:
        f = item["serenity_factors"]
        lines.extend(
            [
                f"{item['rank']}. **{item['ticker']}**｜{item['serenity_score']}/100｜品質 {round(item['data_quality'] * 100)}%｜{item['rating']}",
                f"   - {item['name']}｜{item['category']}",
                f"   - 需求 {f['demand_wave']}｜瓶頸 {f['chokepoint']}｜定價 {f['pricing_power']}｜替代摩擦 {f['replacement_friction']}｜TAM {f['tam_capture']}｜估值 {f['valuation_expectations']}｜證據 {f['evidence_quality']}",
                f"   - 風險扣分 {item['risk_penalty']}｜Aschenbrenner Domain {item['aschenbrenner_overlay']['domain'] or 'N/A'} fit {item['aschenbrenner_overlay']['fit_score']}（不計入主分）",
            ]
        )
    lines.extend(
        [
            "",
            "## Public-only boundary",
            "",
            "- 不讀取持股、成本、損益、券商帳戶、私人訊息或 owner watchlist。",
            "- yfinance 僅為 T3 候選發現／市場觀察，不算 authoritative evidence。",
            "- SEC XBRL 是本輪公司層級主要 evidence；World Bank 提供官方宏觀 context。",
        ]
    )
    return "\n".join(lines) + "\n"


def validate_top20(records: Sequence[Mapping[str, Any]]) -> None:
    if len(records) != 20:
        raise PipelineError(f"Expected exactly 20 records, found {len(records)}")
    if [int(item["rank"]) for item in records] != list(range(1, 21)):
        raise PipelineError("Ranks must be exactly 1..20")
    if len({str(item["ticker"]) for item in records}) != 20:
        raise PipelineError("Duplicate ticker in Top 20")
    expected = sorted(
        records,
        key=lambda item: (
            -int(item["serenity_score"]),
            -float(item["data_quality"]),
            str(item["ticker"]),
        ),
    )
    if list(records) != expected:
        raise PipelineError("Top 20 order is not deterministic")
    serialized = json.dumps(records, ensure_ascii=False).casefold()
    for forbidden in (
        '"account"', '"portfolio"', '"position"', '"holding"', '"cost_basis"',
        '"pnl"', '"line_user_id"', '"tenant_id"', '"messages"',
    ):
        if forbidden in serialized:
            raise PipelineError(f"Forbidden public field: {forbidden}")


def run(*, synthetic: bool) -> dict[str, Any]:
    policy, activation = validate_policy()
    plan = source_plan(policy, activation)
    generated = iso_now()
    http = session()
    macro = {"source_id": "world_bank_indicators", "status": "SYNTHETIC"}

    scored = []
    if synthetic:
        bundles = synthetic_candidates()
    else:
        user_agent = os.getenv(
            "SEC_USER_AGENT",
            "Investor Intelligence 2.1 public research; GitHub owner always7895",
        ).strip()
        if len(user_agent) < 20:
            raise PipelineError("SEC_USER_AGENT must identify the research client")
        headers = {"User-Agent": user_agent, "Accept": "application/json"}
        seeds = discover_candidates(policy)
        reference = sec_reference(policy, http, headers)
        candidates = validate_candidates(seeds, reference, policy)
        bundles = []
        for index, candidate in enumerate(candidates):
            try:
                records = sec_companyfacts(candidate, policy, http, headers)
                metric, evidence = metrics(records)
            except Exception as exc:
                LOGGER.warning("SEC facts failed for %s: %s", candidate["ticker"], type(exc).__name__)
                metric, evidence = {}, [
                    Evidence(
                        "sec_edgar",
                        "T0",
                        "legal_entity_reference",
                        f"SEC ticker reference for {candidate['ticker']}",
                        str(policy["sec_ticker_exchange_url"]),
                        generated,
                    )
                ]
            bundles.append((candidate, metric, evidence))
            if index + 1 >= int(policy["sec_candidate_limit"]):
                break
        macro = world_bank_context(policy, http)

    for candidate, metric, evidence in bundles:
        scored.append(score_candidate(candidate, metric, evidence, policy))

    scored.sort(
        key=lambda item: (
            -int(item["serenity_score"]),
            -float(item["data_quality"]),
            str(item["ticker"]),
        )
    )
    if len(scored) < int(policy["top_count"]):
        raise PipelineError(f"Only {len(scored)} scored candidates; 20 required")
    top20 = scored[: int(policy["top_count"])]
    for rank, item in enumerate(top20, start=1):
        item["rank"] = rank
        item["generated_at"] = generated
        item["as_of"] = max(
            (str(e["as_of"]) for e in item["evidence"]),
            default=generated,
        )
    validate_top20(top20)

    metadata = {
        "schema_version": 1,
        "line_public_eligible": True,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
        "last_successful_pipeline_timestamp": generated,
    }
    report = build_report(top20, plan, macro, generated)

    atomic_json(TOP20_PATH, top20)
    atomic_json(PLAN_PATH, plan)
    atomic_json(METADATA_PATH, metadata)
    atomic_text(REPORT_PATH, report)

    return {
        "top20_count": len(top20),
        "catalog_count": plan["catalog_count"],
        "top20_path": str(TOP20_PATH),
        "source_plan_path": str(PLAN_PATH),
        "report_path": str(REPORT_PATH),
        "macro_status": macro.get("status"),
    }


def self_test() -> None:
    output = run(synthetic=True)
    if output["top20_count"] != 20 or output["catalog_count"] != 99:
        raise PipelineError("Synthetic acceptance failed")
    top = json.loads(TOP20_PATH.read_text(encoding="utf-8"))
    if any(item["aschenbrenner_overlay"]["included_in_serenity_score"] for item in top):
        raise PipelineError("Aschenbrenner overlay leaked into Serenity score")
    print("V21_SERENITY_ENGINE_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        else:
            print(json.dumps(run(synthetic=args.synthetic), ensure_ascii=False, indent=2))
        return 0
    except (PipelineError, OSError, ValueError, requests.RequestException) as exc:
        LOGGER.error("V2.1 Serenity engine failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
