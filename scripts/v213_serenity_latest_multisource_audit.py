#!/usr/bin/env python3
"""Normalize and audit the final v2.1.3 Serenity public-logic snapshot.

This is a post-source-gate publication barrier.  It enforces per-ticker source
independence, publication-time freshness, two comparable non-Yahoo market
providers for high-confidence inference, severe thesis-killer precedence, and
factor-to-evidence consistency.  It may only reduce confidence or positive
factor values; it never invents a fact, source, order total or positive score.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import re
import tempfile
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "v213-serenity-latest-multisource-policy-v5.json"
TOP20_PATH = ROOT / "data" / "cache" / "top20_public_latest.json"
V212_PATH = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
V213_PATH = ROOT / "data" / "cache" / "v213_top20_report_public_latest.json"
FEDERATION_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
SOURCE_AUDIT_PATH = ROOT / "data" / "cache" / "v213_source_independence_latest.json"
SERENITY_SOURCE_PATH = ROOT / "data" / "cache" / "v213_serenity_public_source_latest.json"
LEDGER_PATH = ROOT / "data" / "cache" / "v213_serenity_factor_ledger_latest.json"
AUDIT_PATH = ROOT / "data" / "cache" / "v213_serenity_latest_multisource_audit.json"

PRIMARY_FAMILIES = {"regulator_filing", "issuer_primary"}
MARKET_PROVIDER_BASIS = {
    "hfmarketdata_daily_bars": "split_dividend_adjusted_close",
    "alpha_vantage_adjusted": "split_dividend_adjusted_close",
    "alpha_vantage": "split_dividend_adjusted_close",
    "nasdaq_historical_api": "exchange_close_unadjusted_or_unknown",
    "stooq_daily_csv": "vendor_close_adjustment_unknown",
    "yfinance_adjusted_close": "split_dividend_adjusted_close",
}
MARKET_PROVIDER_FAMILY = {
    "hfmarketdata_daily_bars": "hfmarketdata_market",
    "alpha_vantage_adjusted": "alpha_vantage_market",
    "alpha_vantage": "alpha_vantage_market",
    "nasdaq_historical_api": "nasdaq_market",
    "stooq_daily_csv": "stooq_market",
    "yfinance_adjusted_close": "yahoo_market",
}
YAHOO_PROVIDERS = {"yfinance_adjusted_close", "yahoo_finance", "yfinance"}
SEVERE_MARKERS = {
    "thesis_broken", "architecture_bypass", "dependency_contradicted",
    "qualified_substitute_capacity_verified", "material_customer_loss",
    "volume_qualification_failed", "scarcity_resolved", "pricing_collapse",
    "financing_destroys_equity_capture",
}
FACTOR_KEYS = (
    "demand_wave", "chokepoint", "pricing_power", "replacement_friction",
    "tam_capture", "valuation_expectations", "evidence_quality",
)


class AuditError(RuntimeError):
    pass


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_time(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = dt.datetime.combine(dt.date.fromisoformat(text[:10]), dt.time(), tzinfo=dt.timezone.utc)
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def age_days(value: Any, now: dt.datetime) -> float | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return (now - parsed.astimezone(dt.timezone.utc)).total_seconds() / 86400.0


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"Unable to read JSON: {path}") from exc


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def rows(document: Any, label: str) -> list[dict[str, Any]]:
    raw = document if isinstance(document, list) else document.get("records") if isinstance(document, dict) else None
    if not isinstance(raw, list) or len(raw) != 20:
        raise AuditError(f"{label} must contain exactly 20 rows")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise AuditError(f"{label} row must be an object")
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen or int(item.get("rank") or 0) != index:
            raise AuditError(f"{label} ticker/rank contract failed at rank {index}")
        seen.add(ticker)
        result.append(dict(item))
    return result


def domain_of(url: str) -> str:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower().strip(".")
    except Exception:
        return "unknown"
    if not host:
        return "unknown"
    known = (
        "sec.gov", "nasdaq.com", "stooq.com", "alphavantage.co",
        "hfmarketdata.io", "yahoo.com", "stlouisfed.org", "reuters.com",
        "bloomberg.com", "apnews.com", "wsj.com", "ft.com",
    )
    for suffix in known:
        if host == suffix or host.endswith("." + suffix):
            return suffix
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in {"co.uk", "com.au", "co.jp", "com.cn", "com.tw", "co.kr"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def family_of(source: Mapping[str, Any]) -> str:
    explicit = str(source.get("family") or "").strip()
    if explicit:
        return explicit
    source_id = str(source.get("source_id") or "").casefold()
    domain = domain_of(str(source.get("url") or ""))
    if domain == "sec.gov" or "sec" in source_id or "edgar" in source_id:
        return "regulator_filing"
    if any(token in source_id for token in ("issuer", "company_ir", "press_release", "earnings_release")):
        return "issuer_primary"
    if domain == "nasdaq.com":
        return "exchange_sro"
    if domain == "yahoo.com" or "yahoo" in source_id or "yfinance" in source_id:
        return "yahoo_market"
    if domain == "stooq.com" or "stooq" in source_id:
        return "stooq_market"
    if domain == "alphavantage.co" or "alpha_vantage" in source_id:
        return "alpha_vantage_market"
    if domain == "hfmarketdata.io" or "hfmarketdata" in source_id:
        return "hfmarketdata_market"
    if domain in {"reuters.com", "bloomberg.com", "apnews.com", "wsj.com", "ft.com"}:
        return "reputable_secondary"
    return "secondary_or_other"


def evidence_rows(top: Mapping[str, Any], source_record: Mapping[str, Any], order: Mapping[str, Any]) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for container in (
        top.get("evidence"), source_record.get("sources"),
        source_record.get("evidence_sources"), source_record.get("claim_sources"),
    ):
        if isinstance(container, list):
            combined.extend(dict(item) for item in container if isinstance(item, dict))
    for key, claim_type in (
        ("current_order_source_urls", "current_orders"),
        ("future_order_source_urls", "future_orders_estimate"),
    ):
        for url in order.get(key) or []:
            if isinstance(url, str) and url.startswith("https://"):
                combined.append({
                    "source_id": "order_evidence", "claim_type": claim_type,
                    "title": claim_type, "url": url, "as_of": order.get("orders_as_of") or "",
                })
    dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in combined:
        url = str(item.get("url") or "")
        if not url.startswith("https://"):
            continue
        normalized = dict(item)
        normalized["domain"] = str(item.get("domain") or domain_of(url))
        normalized["family"] = family_of(normalized)
        identity = (normalized["family"], normalized["domain"], str(normalized.get("claim_type") or "unknown"))
        dedup.setdefault(identity, normalized)
    return list(dedup.values())


def provider_rows(source_record: Mapping[str, Any], now: dt.datetime, hard_days: float) -> list[dict[str, Any]]:
    market = source_record.get("market_corroboration")
    raw = market.get("providers") if isinstance(market, dict) else []
    output: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip()
        status = str(item.get("status") or "").upper()
        as_of = str(item.get("as_of") or "")
        age = age_days(as_of, now)
        fresh = status in {"LIVE", "CACHED"} and age is not None and -1 <= age <= hard_days
        output.append({
            **item,
            "provider": provider,
            "family": str(item.get("family") or MARKET_PROVIDER_FAMILY.get(provider, "unknown_market")),
            "metric_basis": str(item.get("metric_basis") or MARKET_PROVIDER_BASIS.get(provider, "unknown")),
            "as_of_age_days": None if age is None else round(age, 4),
            "fresh_for_corroboration": fresh,
            "independent_non_yahoo": provider not in YAHOO_PROVIDERS and "yahoo" not in provider.casefold(),
        })
    return output


def comparable_market_groups(providers: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for item in providers:
        if not item.get("fresh_for_corroboration") or not item.get("independent_non_yahoo"):
            continue
        basis = str(item.get("metric_basis") or "unknown")
        family = str(item.get("family") or item.get("provider") or "unknown")
        if basis == "unknown" or (basis, family) in seen:
            continue
        seen.add((basis, family))
        groups[basis].append(dict(item))
    return groups


def rating(score: float) -> str:
    if score >= 55:
        return "A"
    if score >= 40:
        return "B"
    if score >= 25:
        return "C"
    return "D"


def state_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(item) for item in value.values()).casefold()
    return str(value or "").casefold()


def layer_for(row: Mapping[str, Any], report: Mapping[str, Any]) -> str:
    text = " ".join((str(row.get("category") or ""), str(report.get("industry") or ""))).casefold()
    if any(word in text for word in ("equipment", "material", "industrial", "機械", "設備", "材料", "化工")):
        return "equipment_materials_industrial"
    if any(word in text for word in ("software", "cloud", "軟體")):
        return "software_data_platform"
    if any(word in text for word in ("communication", "network", "hardware", "通訊", "硬體", "零組件")):
        return "systems_connectivity_components"
    if any(word in text for word in ("energy", "utility", "power", "mining", "能源", "電力", "礦")):
        return "power_energy_resources"
    if any(word in text for word in ("semiconductor", "半導體")):
        return "semiconductor_devices"
    return "other_public_equity"


def normalize_and_audit(
    policy: Mapping[str, Any], top_doc: Any, v212: dict[str, Any], v213: dict[str, Any],
    federation: dict[str, Any], source_audit: dict[str, Any], serenity_source: dict[str, Any],
    now: dt.datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    top = rows(top_doc, "Top20")
    five = rows(v212, "v2.1.2 report")
    seven = rows(v213, "v2.1.3 report")
    source_records = rows(source_audit, "source-independence audit")
    fed_raw = federation.get("ticker_sources")
    if not isinstance(fed_raw, list) or len(fed_raw) != 20:
        raise AuditError("Source federation must contain exactly 20 ticker rows")
    fed = [dict(item) for item in fed_raw if isinstance(item, dict)]
    if len(fed) != 20:
        raise AuditError("Source federation ticker row shape is invalid")
    expected = [row["ticker"] for row in top]
    for label, group in (("v212", five), ("v213", seven), ("source", source_records), ("federation", fed)):
        actual = [str(item.get("ticker") or "").upper() for item in group]
        if actual != expected:
            raise AuditError(f"Top20/{label} order mismatch")

    if source_audit.get("status") != "PASS" or source_audit.get("blocking_violations") or source_audit.get("violations"):
        raise AuditError("Source-independence blocking gates are not PASS")
    gates = federation.get("gates") if isinstance(federation.get("gates"), dict) else {}
    if gates.get("pass") is not True or int(gates.get("unresolved_material_conflict_count") or 0) != 0:
        raise AuditError("Live source-federation gates are not PASS")

    freshness = policy["freshness_days"]
    snapshot_days = float(freshness["snapshot"])
    for label, document in (("v212", v212), ("v213", v213), ("federation", federation), ("source_audit", source_audit)):
        age = age_days(document.get("generated_at"), now)
        if age is None or age < -0.01 or age > snapshot_days:
            raise AuditError(f"{label} is outside the two-hour point-in-time window: age_days={age}")
    serenity_age = age_days(serenity_source.get("retrieved_at"), now)
    if serenity_source.get("latest_available_verified") is not True or serenity_age is None or serenity_age < -0.01 or serenity_age > float(freshness["serenity_public_source_retrieval"]):
        raise AuditError("Latest public Serenity source metadata was not verified within 24 hours")
    if serenity_source.get("company_fact_authority") is not False:
        raise AuditError("Serenity public-post metadata is incorrectly treated as company-fact authority")

    per = policy["per_ticker_minimums"]
    severe = {str(value).casefold() for value in policy["severe_thesis_killers"]} | SEVERE_MARKERS
    hard_market_days = float(freshness["market_absolute_maximum"])
    high_market_days = float(freshness["market_high_confidence"])
    provider_gap = float(freshness["market_provider_max_gap"])
    current_days = float(freshness["company_current_state"])
    order_days = float(freshness["order_visibility"])
    valuation_cap = float(policy["market_corroboration"]["uncorroborated_valuation_factor_max"])

    ledger_rows: list[dict[str, Any]] = []
    normalized_top = copy.deepcopy(top)
    normalized_source = copy.deepcopy(source_audit)
    source_by_ticker = {str(row.get("ticker") or "").upper(): row for row in normalized_source["records"]}
    layers: Counter[str] = Counter()
    high_count = 0
    changed_tickers: list[str] = []

    for index, (top_row, five_row, seven_row, source_row) in enumerate(zip(normalized_top, five, seven, source_records)):
        ticker = top_row["ticker"]
        metrics = source_row.get("source_metrics") if isinstance(source_row.get("source_metrics"), dict) else {}
        if int(metrics.get("claim_relevant_independent_families") or 0) < int(per["claim_relevant_independent_families"]):
            raise AuditError(f"{ticker} lacks two claim-relevant independent source families")
        if int(metrics.get("claim_relevant_independent_domains") or 0) < int(per["claim_relevant_independent_domains"]):
            raise AuditError(f"{ticker} lacks two claim-relevant independent domains")
        if int(metrics.get("claim_relevant_primary_sources") or 0) < int(per["claim_relevant_primary_sources"]):
            raise AuditError(f"{ticker} lacks a primary company-claim source")
        if finite(metrics.get("claim_dated_evidence_ratio")) < float(per["claim_dated_evidence_ratio"]):
            raise AuditError(f"{ticker} has insufficient dated claim evidence")

        risks = {str(value).casefold() for value in top_row.get("risk_flags") or []}
        logic = source_row.get("public_logic_state") if isinstance(source_row.get("public_logic_state"), dict) else {}
        logic_text = " ".join(state_text(value) for value in logic.values())
        if any(marker in risks or marker in logic_text for marker in severe):
            raise AuditError(f"{ticker} contains a severe thesis-killer state and cannot remain published")

        evidence = evidence_rows(top_row, source_row, seven_row)
        primary = [item for item in evidence if item.get("family") in PRIMARY_FAMILIES or item.get("primary") is True or item.get("claim_primary") is True]
        fresh_primary = [item for item in primary if (lambda age: age is not None and -1 <= age <= current_days)(age_days(item.get("as_of"), now))]
        independent_corroborators = [item for item in evidence if item.get("family") not in PRIMARY_FAMILIES | {"official_macro", "yahoo_market"}]
        fresh_corroborators = [item for item in independent_corroborators if (lambda age: age is not None and -1 <= age <= current_days)(age_days(item.get("as_of"), now))]
        if not fresh_primary:
            raise AuditError(f"{ticker} lacks latest-available primary company evidence within {current_days:.0f} days")

        order_supported = str(seven_row.get("orders_confidence") or "") not in {"", "UNAVAILABLE", "NO_RELIABLE_PUBLIC_ORDER_NUMBER"}
        order_age = age_days(seven_row.get("orders_as_of"), now)
        fresh_order = order_supported and order_age is not None and -1 <= order_age <= order_days

        providers = provider_rows(source_row, now, hard_market_days)
        groups = comparable_market_groups(providers)
        qualifying_groups: dict[str, list[dict[str, Any]]] = {}
        for basis, items in groups.items():
            ordered = sorted(items, key=lambda item: str(item.get("as_of") or ""), reverse=True)
            if len(ordered) < 2:
                continue
            ages = [finite(item.get("as_of_age_days"), 9999) for item in ordered[:2]]
            dates = [parse_time(item.get("as_of")) for item in ordered[:2]]
            gap = abs((dates[0] - dates[1]).total_seconds()) / 86400 if dates[0] and dates[1] else 9999
            if min(ages) <= high_market_days and gap <= provider_gap:
                qualifying_groups[basis] = ordered
        market = source_row.get("market_corroboration") if isinstance(source_row.get("market_corroboration"), dict) else {}
        no_conflict = not bool(market.get("long_term_conflict") or market.get("short_term_conflict") or market.get("conflicting_providers"))
        market_high = bool(qualifying_groups) and no_conflict

        factors = top_row.get("serenity_factors") if isinstance(top_row.get("serenity_factors"), dict) else {}
        if set(factors) != set(FACTOR_KEYS):
            raise AuditError(f"{ticker} factor schema is invalid")
        original_factors = {key: finite(factors.get(key)) for key in FACTOR_KEYS}
        normalized_factors = dict(original_factors)
        factor_findings: dict[str, Any] = {}

        public_state_requirements = {
            "demand_wave": "architecture",
            "chokepoint": "dependency_graph",
            "pricing_power": "company_capture",
            "replacement_friction": "dependency_graph",
        }
        for factor, state_key in public_state_requirements.items():
            score = normalized_factors[factor]
            state = state_text(logic.get(state_key))
            supported_state = state and not any(token in state for token in ("unproven", "unknown", "unavailable", "limited"))
            supported = bool(fresh_primary and fresh_corroborators and supported_state)
            if score > 0 and not supported:
                normalized_factors[factor] = 0.0
                factor_findings[factor] = "zeroed_missing_fresh_primary_independent_corroborator_or_supported_state"
            else:
                factor_findings[factor] = "supported" if score > 0 else "not_scored_unproven"

        if normalized_factors["tam_capture"] > 0 and not (fresh_primary and (fresh_order or finite(five_row.get("long_term_return_pct"), math.nan) == finite(five_row.get("long_term_return_pct"), math.nan))):
            normalized_factors["tam_capture"] = 0.0
            factor_findings["tam_capture"] = "zeroed_missing_fresh_financial_or_order_evidence"
        else:
            factor_findings["tam_capture"] = "bounded_current_state_evidence" if normalized_factors["tam_capture"] > 0 else "not_scored"

        if normalized_factors["valuation_expectations"] > valuation_cap and not market_high:
            normalized_factors["valuation_expectations"] = valuation_cap
            factor_findings["valuation_expectations"] = "capped_without_two_fresh_comparable_non_yahoo_providers"
        else:
            factor_findings["valuation_expectations"] = "two_provider_supported" if normalized_factors["valuation_expectations"] > valuation_cap else "within_uncorroborated_cap"
        factor_findings["evidence_quality"] = "source_metrics_only_not_company_advantage"

        source_mut = source_by_ticker[ticker]
        missing = [str(value) for value in source_mut.get("missing_or_review") or []]
        if not market_high:
            if "TWO_COMPARABLE_NON_YAHOO_MARKET_PROVIDERS" not in missing:
                missing.append("TWO_COMPARABLE_NON_YAHOO_MARKET_PROVIDERS")
            source_mut["eligible_for_high_confidence_model_inference"] = False
            public_logic = source_mut.get("public_logic_state")
            if isinstance(public_logic, dict):
                public_logic["model_inference_confidence"] = "LIMITED"
        else:
            high_count += int(bool(source_mut.get("eligible_for_high_confidence_model_inference")))
        source_mut["missing_or_review"] = missing

        if normalized_factors != original_factors:
            changed_tickers.append(ticker)
            top_row["serenity_factors"] = normalized_factors
            raw_score = round(sum(normalized_factors.values()), 2)
            penalty = max(0.0, finite(top_row.get("risk_penalty")))
            final_score = round(max(0.0, min(100.0, raw_score - penalty)), 2)
            top_row["serenity_raw_score"] = raw_score
            top_row["serenity_score"] = final_score
            top_row["rating"] = rating(final_score)
            flags = list(dict.fromkeys([str(value) for value in top_row.get("risk_flags") or []] + ["latest_multisource_confidence_reduced"]))
            top_row["risk_flags"] = sorted(flags)

        layers[layer_for(top_row, five_row)] += 1
        ledger_rows.append({
            "rank": index + 1,
            "ticker": ticker,
            "latest_primary_as_of": max((str(item.get("as_of") or "") for item in fresh_primary), default=""),
            "fresh_primary_count": len(fresh_primary),
            "fresh_independent_corroborator_count": len(fresh_corroborators),
            "order_supported": order_supported,
            "order_fresh": fresh_order,
            "order_as_of": str(seven_row.get("orders_as_of") or ""),
            "market_providers": providers,
            "comparable_provider_groups": {key: [item["provider"] for item in value] for key, value in qualifying_groups.items()},
            "two_fresh_comparable_non_yahoo_market_providers": market_high,
            "factor_scores": normalized_factors,
            "factor_findings": factor_findings,
            "source_metrics": metrics,
            "severe_thesis_killer_present": False,
        })

    if len(layers) < 3:
        raise AuditError(f"Final Top20 spans fewer than three value-chain layers: {dict(layers)}")

    normalized_top.sort(key=lambda item: (-finite(item.get("serenity_score")), -finite(item.get("data_quality")), str(item.get("ticker") or "")))
    order = [str(item["ticker"]) for item in normalized_top]
    for rank, item in enumerate(normalized_top, 1):
        item["rank"] = rank
    def reorder(document: dict[str, Any], key: str) -> dict[str, Any]:
        result = copy.deepcopy(document)
        mapping = {str(item.get("ticker") or "").upper(): dict(item) for item in result[key]}
        result[key] = []
        for rank, ticker in enumerate(order, 1):
            item = mapping[ticker]
            item["rank"] = rank
            result[key].append(item)
        return result
    v212_out = reorder(v212, "records")
    v213_out = reorder(v213, "records")
    federation_out = reorder(federation, "ticker_sources")
    source_out = reorder(normalized_source, "records")
    source_out.setdefault("portfolio", {})["high_confidence_model_inference_eligible_count"] = high_count
    source_out["latest_multisource_policy"] = str(policy["policy_id"])
    source_out["latest_multisource_normalized_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    source_out.setdefault("methodology_notice", {}).update({
        "minimum_independent_market_providers_for_high_confidence": 2,
        "same_metric_basis_required_for_market_comparison": True,
        "yahoo_is_not_truth_anchor": True,
        "retrieval_time_is_not_publication_time": True,
        "latest_available_evidence_required": True,
    })

    ledger_by_ticker = {item["ticker"]: item for item in ledger_rows}
    ledger = {
        "schema_version": 1,
        "product_version": "2.1.3",
        "generated_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "policy_id": policy["policy_id"],
        "official_serenity_formula_claimed": False,
        "private_method_reproduced": False,
        "records": [dict(ledger_by_ticker[ticker], rank=rank) for rank, ticker in enumerate(order, 1)],
    }
    portfolio = source_out.get("portfolio") if isinstance(source_out.get("portfolio"), dict) else {}
    audit = {
        "schema_version": 1,
        "product_version": "2.1.3",
        "status": "PASS",
        "generated_at": ledger["generated_at"],
        "policy_id": policy["policy_id"],
        "ticker_count": 20,
        "per_ticker_claim_family_minimum": int(per["claim_relevant_independent_families"]),
        "per_ticker_claim_domain_minimum": int(per["claim_relevant_independent_domains"]),
        "per_ticker_primary_minimum": int(per["claim_relevant_primary_sources"]),
        "market_high_confidence_provider_minimum": 2,
        "market_pairwise_same_basis_required": True,
        "yahoo_truth_anchor": False,
        "source_values_averaged": False,
        "latest_public_serenity_head": serenity_source.get("canonical_head_sha"),
        "latest_public_serenity_retrieved_at": serenity_source.get("retrieved_at"),
        "value_chain_layers": dict(sorted(layers.items())),
        "changed_tickers": changed_tickers,
        "high_confidence_eligible_count": high_count,
        "portfolio_claim_source_families": portfolio.get("claim_source_families"),
        "portfolio_claim_source_domains": portfolio.get("claim_source_domains"),
        "portfolio_claim_primary_coverage_ratio": portfolio.get("claim_primary_coverage_ratio"),
        "unresolved_material_conflicts": 0,
        "factor_ledger_records": 20,
    }
    return normalized_top, v212_out, v213_out, federation_out, source_out, ledger, audit


def self_test() -> None:
    now = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.timezone.utc)
    generated = "2026-09-03T11:30:00Z"
    top, five, seven, source_rows, fed_rows = [], [], [], [], []
    for index in range(20):
        ticker = f"T{index:02d}"
        category = ("Semiconductor" if index % 3 == 0 else "Infrastructure software" if index % 3 == 1 else "Communications hardware")
        top.append({
            "rank": index + 1, "ticker": ticker, "category": category,
            "serenity_score": 12.75, "serenity_raw_score": 14.75,
            "risk_penalty": 2.0, "data_quality": 0.8, "rating": "D",
            "serenity_factors": {"demand_wave": 0.0, "chokepoint": 0.0, "pricing_power": 0.0, "replacement_friction": 0.0, "tam_capture": 6.0, "valuation_expectations": 3.75, "evidence_quality": 5.0},
            "risk_flags": [], "scoring_version": "system-operationalization-v2.1.3-diversified",
            "evidence": [
                {"source_id": "sec_edgar", "claim_type": "xbrl_fact", "url": f"https://www.sec.gov/{ticker}", "as_of": "2026-08-20"},
                {"source_id": "issuer_primary", "claim_type": "earnings_release", "url": f"https://{ticker.lower()}.example.com/investors", "as_of": "2026-08-21"},
                {"source_id": "reuters", "claim_type": "company_context", "url": f"https://www.reuters.com/{ticker}", "as_of": "2026-08-22"},
            ],
        })
        five.append({"rank": index + 1, "ticker": ticker, "industry": category, "long_term_return_pct": 10.0, "generated_at": generated})
        seven.append({"rank": index + 1, "ticker": ticker, "orders_confidence": "UNAVAILABLE", "orders_as_of": "", "current_order_source_urls": [], "future_order_source_urls": []})
        providers = [
            {"provider": "hfmarketdata_daily_bars", "status": "LIVE", "as_of": "2026-09-02", "long_term_return_pct": 10.0, "short_term_return_pct": 5.0},
            {"provider": "alpha_vantage_adjusted", "status": "LIVE", "as_of": "2026-09-01", "long_term_return_pct": 10.5, "short_term_return_pct": 4.5},
        ]
        source_rows.append({
            "rank": index + 1, "ticker": ticker,
            "source_metrics": {"claim_relevant_independent_families": 3, "claim_relevant_independent_domains": 3, "claim_relevant_primary_sources": 2, "claim_dated_evidence_ratio": 1.0},
            "market_corroboration": {"status": "CORROBORATED", "providers": providers},
            "missing_or_review": [], "eligible_for_high_confidence_model_inference": True,
            "public_logic_state": {"architecture": "EVIDENCE_FORMING", "dependency_graph": "UNPROVEN", "company_capture": "EVIDENCE_FORMING", "model_inference_confidence": "HIGH_ELIGIBLE"},
        })
        fed_rows.append({"rank": index + 1, "ticker": ticker})
    documents = (
        top,
        {"product_version": "2.1.2", "generated_at": generated, "records": five},
        {"product_version": "2.1.3", "generated_at": generated, "records": seven},
        {"product_version": "2.1.3", "generated_at": generated, "ticker_sources": fed_rows, "gates": {"pass": True, "unresolved_material_conflict_count": 0}},
        {"product_version": "2.1.3", "generated_at": generated, "status": "PASS", "violations": [], "blocking_violations": [], "portfolio": {"claim_source_families": 3, "claim_source_domains": 3, "claim_primary_coverage_ratio": 1.0}, "records": source_rows},
        {"retrieved_at": generated, "latest_available_verified": True, "company_fact_authority": False, "canonical_head_sha": "a" * 40},
    )
    policy = load(POLICY_PATH)
    result = normalize_and_audit(policy, *documents, now)
    assert len(result[0]) == 20 and result[-1]["status"] == "PASS"
    assert result[-2]["records"][0]["two_fresh_comparable_non_yahoo_market_providers"] is True
    stale = copy.deepcopy(documents)
    stale[4]["records"][0]["market_corroboration"]["providers"][0]["as_of"] = "2026-08-01"
    stale[4]["records"][0]["market_corroboration"]["providers"][1]["as_of"] = "2026-08-01"
    normalized = normalize_and_audit(policy, *stale, now)
    assert normalized[4]["records"][0]["eligible_for_high_confidence_model_inference"] is False
    print("V213_SERENITY_LATEST_MULTISOURCE_AUDIT_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--top20", type=Path, default=TOP20_PATH)
    parser.add_argument("--v212", type=Path, default=V212_PATH)
    parser.add_argument("--v213", type=Path, default=V213_PATH)
    parser.add_argument("--federation", type=Path, default=FEDERATION_PATH)
    parser.add_argument("--source-audit", type=Path, default=SOURCE_AUDIT_PATH)
    parser.add_argument("--serenity-source", type=Path, default=SERENITY_SOURCE_PATH)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--normalize", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    policy = load(args.policy)
    output = normalize_and_audit(
        policy, load(args.top20), load(args.v212), load(args.v213),
        load(args.federation), load(args.source_audit), load(args.serenity_source), now_utc(),
    )
    normalized_top, v212, v213, federation, source_audit, ledger, audit = output
    if args.normalize:
        atomic_json(args.top20, normalized_top)
        atomic_json(args.v212, v212)
        atomic_json(args.v213, v213)
        atomic_json(args.federation, federation)
        atomic_json(args.source_audit, source_audit)
    atomic_json(args.ledger, ledger)
    atomic_json(args.audit, audit)
    digest = hashlib.sha256(json.dumps(audit, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    print(
        "V213_SERENITY_LATEST_MULTISOURCE_AUDIT = PASS; "
        f"tickers=20; layers={len(audit['value_chain_layers'])}; "
        f"high_confidence={audit['high_confidence_eligible_count']}; "
        f"changed={len(audit['changed_tickers'])}; audit_sha256={digest}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print(f"V213_SERENITY_LATEST_MULTISOURCE_AUDIT = FAIL; {exc}", file=__import__('sys').stderr, flush=True)
        raise SystemExit(1)
