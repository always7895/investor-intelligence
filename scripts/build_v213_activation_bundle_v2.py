#!/usr/bin/env python3
"""Build the hardened v2.1.3 atomic activation bundle.

The live source federation is collected before diversified scoring, while final
Top20 ranking is established by the diversified operationalization step. This
wrapper preserves every federation row and its evidence, reorders the
``ticker_sources`` array to the final Top20 order, assigns a fresh
cryptographically random transaction ID, and enforces the final publication
boundary:

* every final ticker has dated claim evidence from multiple independent source
  families and registrable domains;
* positive Serenity advantage factors cannot be carried by one publisher,
  one domain, undated evidence, or stale evidence;
* stale market observations cannot remain LIVE/CACHED or count as independent
  corroboration;
* all seven payloads belong to one fresh, coherent run before the canonical
  bundle validator is entered.

Market data and official macro data remain context/corroboration only. They never
prove a company claim, dependency, bottleneck, order, pricing power, replacement
friction, TAM capture, or thesis state.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import secrets
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
CORE_PATH = SCRIPT_DIR / "build_v213_activation_bundle.py"
FRESHNESS_POLICY_PATH = ROOT / "config" / "v213-serenity-evidence-freshness-policy.json"
TRANSACTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
NON_CLAIM_TYPES = {
    "market_return_calculation",
    "independent_market_corroboration",
    "macro_context",
    "regulated_listing_identity",
}
NON_CLAIM_FAMILIES = {
    "official_macro",
    "yahoo_market",
    "stooq_market",
    "nasdaq_market",
    "alpha_vantage_market",
    "hfmarketdata_market",
}
CLAIM_PRIMARY_FAMILIES = {
    "regulator_filing",
    "issuer_primary",
    "exchange_sro",
}


class SerenityEvidenceError(RuntimeError):
    """The final public candidate failed the reviewed evidence boundary."""


def load_core() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "investor_intelligence_v213_activation_bundle_core",
        CORE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load activation-bundle core: {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = load_core()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result and abs(result) != float("inf") else default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _timestamp(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise SerenityEvidenceError(f"Missing dated evidence: {label}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        try:
            parsed = datetime.fromisoformat(text[:10] + "T00:00:00+00:00")
        except ValueError:
            raise SerenityEvidenceError(f"Invalid evidence timestamp: {label}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(value: Any, label: str, now: datetime, skew_minutes: int) -> float:
    parsed = _timestamp(value, label)
    seconds = (now - parsed).total_seconds()
    if seconds < -(skew_minutes * 60):
        raise SerenityEvidenceError(f"Future-dated evidence exceeds clock tolerance: {label}")
    return max(0.0, seconds / 86400.0)


def _read_policy(path: Path = FRESHNESS_POLICY_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SerenityEvidenceError(f"Unable to read Serenity freshness policy: {path}") from exc
    required_false = (
        "market_data_is_company_claim_evidence",
        "official_macro_is_company_claim_evidence",
        "same_registrable_domain_is_independent",
        "same_publisher_family_is_independent",
        "syndicated_duplicate_is_independent",
        "conflicting_sources_are_averaged",
        "stale_live_market_observation_is_publishable",
        "undated_sensitive_advantage_is_publishable",
        "single_source_positive_advantage_is_publishable",
    )
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("product_version") != "2.1.3"
        or not str(value.get("policy_id") or "").startswith("v213-serenity-")
        or any(value.get(name) is not False for name in required_false)
        or _integer(value.get("minimum_claim_source_families_per_ticker")) < 2
        or _integer(value.get("minimum_claim_source_domains_per_ticker")) < 2
        or _integer(value.get("minimum_claim_primary_sources_per_ticker")) < 1
        or _number(value.get("minimum_claim_dated_evidence_ratio")) < 0.8
        or _number(value.get("market_observation_max_age_days")) <= 0
        or _number(value.get("current_state_claim_max_age_days")) <= 0
        or _number(value.get("structural_claim_max_age_days")) <= 0
    ):
        raise SerenityEvidenceError("Serenity evidence freshness policy is invalid or weakened")
    return value


def _domain(source: Mapping[str, Any]) -> str:
    declared = str(source.get("domain") or "").strip().lower().strip(".")
    if declared and declared != "unknown":
        return declared
    try:
        return (urllib.parse.urlsplit(str(source.get("url") or "")).hostname or "").lower().strip(".")
    except ValueError:
        return ""


def _family(source: Mapping[str, Any]) -> str:
    return str(source.get("family") or "").strip().lower()


def _claim_type(source: Mapping[str, Any]) -> str:
    return str(source.get("claim_type") or "").strip().lower()


def _is_claim_source(source: Mapping[str, Any]) -> bool:
    family = _family(source)
    claim_type = _claim_type(source)
    return bool(
        family
        and claim_type
        and family not in NON_CLAIM_FAMILIES
        and not family.endswith("_market")
        and claim_type not in NON_CLAIM_TYPES
    )


def _source_unit(source: Mapping[str, Any]) -> tuple[str, str, str]:
    return _family(source), _domain(source), _claim_type(source)


def _unique_units(sources: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    units: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for source in sources:
        unit = _source_unit(source)
        if not all(unit):
            continue
        units.setdefault(unit, source)
    return list(units.values())


def _positive_advantage_factors(row: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    factors = row.get("serenity_factors")
    if not isinstance(factors, Mapping):
        return []
    required = [str(value) for value in policy.get("sensitive_advantage_factors", [])]
    return [name for name in required if _number(factors.get(name)) > 0]


def _validate_same_run_freshness(
    envelope: Mapping[str, Any],
    v212: Mapping[str, Any],
    v213: Mapping[str, Any],
    federation: Mapping[str, Any],
    source_audit: Mapping[str, Any],
    policy: Mapping[str, Any],
    now: datetime,
) -> dict[str, float]:
    skew = _integer(policy.get("clock_skew_tolerance_minutes"), 5)
    maximum_hours = _number(policy.get("activation_snapshot_max_age_hours"), 2.0)
    dated_values = {
        "envelope.generated_at": envelope.get("generated_at"),
        "envelope.public_data_as_of": envelope.get("public_data_as_of"),
        "v212.generated_at": v212.get("generated_at"),
        "v213.generated_at": v213.get("generated_at"),
        "source_federation.generated_at": federation.get("generated_at"),
        "source_independence.generated_at": source_audit.get("generated_at"),
    }
    ages: dict[str, float] = {}
    for label, value in dated_values.items():
        age_days = _age_days(value, label, now, skew)
        age_hours = age_days * 24.0
        if age_hours > maximum_hours:
            raise SerenityEvidenceError(
                f"Final activation input is stale: {label}; age_hours={age_hours:.2f}; max={maximum_hours:.2f}"
            )
        ages[label] = round(age_hours, 4)
    timestamps = [_timestamp(value, label) for label, value in dated_values.items()]
    spread = (max(timestamps) - min(timestamps)).total_seconds() / 3600.0
    if spread > maximum_hours:
        raise SerenityEvidenceError(
            f"Final activation inputs do not belong to one fresh run; timestamp_spread_hours={spread:.2f}"
        )
    return ages


def _validate_record_evidence(
    ticker: str,
    top20_row: Mapping[str, Any],
    audit_row: dict[str, Any],
    policy: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    skew = _integer(policy.get("clock_skew_tolerance_minutes"), 5)
    market_max = _number(policy.get("market_observation_max_age_days"), 7.0)
    current_max = _number(policy.get("current_state_claim_max_age_days"), 210.0)
    structural_max = _number(policy.get("structural_claim_max_age_days"), 550.0)
    min_families = _integer(policy.get("minimum_claim_source_families_per_ticker"), 2)
    min_domains = _integer(policy.get("minimum_claim_source_domains_per_ticker"), 2)
    min_primary = _integer(policy.get("minimum_claim_primary_sources_per_ticker"), 1)
    min_advantage_units = _integer(policy.get("minimum_sensitive_advantage_source_units"), 2)
    min_advantage_domains = _integer(policy.get("minimum_sensitive_advantage_domains"), 2)
    min_dated_ratio = _number(policy.get("minimum_claim_dated_evidence_ratio"), 0.8)

    raw_sources = audit_row.get("sources")
    if not isinstance(raw_sources, list):
        raise SerenityEvidenceError(f"{ticker}: source audit does not expose source-level provenance")
    claim_sources = [source for source in raw_sources if isinstance(source, Mapping) and _is_claim_source(source)]
    dated_claim_sources: list[tuple[Mapping[str, Any], float]] = []
    for index, source in enumerate(claim_sources):
        url = str(source.get("url") or "")
        if not url.startswith("https://"):
            continue
        try:
            age = _age_days(source.get("as_of"), f"{ticker}.sources[{index}].as_of", now, skew)
        except SerenityEvidenceError:
            continue
        if age <= structural_max:
            dated_claim_sources.append((source, age))

    all_units = _unique_units(source for source, _age in dated_claim_sources)
    families = {_family(source) for source in all_units}
    domains = {_domain(source) for source in all_units}
    primary_units = [
        source
        for source in all_units
        if bool(source.get("primary")) or _family(source) in CLAIM_PRIMARY_FAMILIES
    ]
    fresh_pairs = [(source, age) for source, age in dated_claim_sources if age <= current_max]
    fresh_units = _unique_units(source for source, _age in fresh_pairs)
    fresh_domains = {_domain(source) for source in fresh_units}
    fresh_primary = [
        source
        for source in fresh_units
        if bool(source.get("primary")) or _family(source) in CLAIM_PRIMARY_FAMILIES
    ]

    metrics = audit_row.get("source_metrics")
    if not isinstance(metrics, Mapping):
        raise SerenityEvidenceError(f"{ticker}: source metrics are missing")
    if (
        _integer(metrics.get("claim_relevant_independent_families")) < min_families
        or _integer(metrics.get("claim_relevant_independent_domains")) < min_domains
        or _integer(metrics.get("claim_relevant_primary_sources")) < min_primary
        or _number(metrics.get("claim_dated_evidence_ratio")) < min_dated_ratio
    ):
        raise SerenityEvidenceError(f"{ticker}: claim evidence metrics permit a single, undated, or non-primary judgment")
    if len(families) < min_families or len(domains) < min_domains or len(primary_units) < min_primary:
        raise SerenityEvidenceError(f"{ticker}: source-level provenance is not independently diverse")
    if not fresh_units:
        raise SerenityEvidenceError(f"{ticker}: no current claim evidence is within {current_max:g} days")

    market = audit_row.get("market_corroboration")
    if not isinstance(market, Mapping):
        raise SerenityEvidenceError(f"{ticker}: market corroboration object is missing")
    providers = market.get("providers")
    if not isinstance(providers, list):
        providers = []
    fresh_market = 0
    stale_live: list[str] = []
    for index, provider in enumerate(providers):
        if not isinstance(provider, Mapping):
            continue
        status = str(provider.get("status") or "").upper()
        if status not in {"LIVE", "CACHED"}:
            continue
        provider_name = str(provider.get("provider") or f"provider-{index}")
        try:
            age = _age_days(provider.get("as_of"), f"{ticker}.{provider_name}.as_of", now, skew)
        except SerenityEvidenceError:
            stale_live.append(provider_name + ":undated")
            continue
        if age > market_max:
            stale_live.append(provider_name + f":{age:.1f}d")
        else:
            fresh_market += 1
    if stale_live:
        raise SerenityEvidenceError(
            f"{ticker}: stale market observations remain LIVE/CACHED: {','.join(stale_live)}"
        )
    declared_provider_count = _integer(market.get("independent_provider_count"))
    if declared_provider_count != fresh_market:
        raise SerenityEvidenceError(
            f"{ticker}: market provider count is not freshness-adjusted; declared={declared_provider_count}; fresh={fresh_market}"
        )

    positive_factors = _positive_advantage_factors(top20_row, policy)
    if positive_factors and (
        len(fresh_units) < min_advantage_units
        or len(fresh_domains) < min_advantage_domains
        or not fresh_primary
    ):
        raise SerenityEvidenceError(
            f"{ticker}: positive Serenity advantages lack fresh multi-source support: {','.join(positive_factors)}"
        )

    factors = top20_row.get("serenity_factors")
    valuation = _number(factors.get("valuation_expectations")) if isinstance(factors, Mapping) else 0.0
    if fresh_market == 0 and valuation > 3.75:
        raise SerenityEvidenceError(
            f"{ticker}: uncorroborated valuation factor exceeds the 3.75 safety cap"
        )
    if str(market.get("status") or "") == "CONFLICT_REVIEW":
        raise SerenityEvidenceError(f"{ticker}: unresolved market-source conflict cannot enter final activation")

    latest_claim = min((age for _source, age in dated_claim_sources), default=None)
    latest_current = min((age for _source, age in fresh_pairs), default=None)
    return {
        "ticker": ticker,
        "claim_source_units": len(all_units),
        "claim_source_families": len(families),
        "claim_source_domains": len(domains),
        "claim_primary_units": len(primary_units),
        "fresh_claim_source_units": len(fresh_units),
        "fresh_claim_source_domains": len(fresh_domains),
        "fresh_claim_primary_units": len(fresh_primary),
        "fresh_market_provider_count": fresh_market,
        "latest_claim_age_days": round(latest_claim, 3) if latest_claim is not None else None,
        "latest_current_claim_age_days": round(latest_current, 3) if latest_current is not None else None,
        "positive_advantage_factors": positive_factors,
        "status": "PASS",
    }


def normalize_and_validate_source_audit(
    envelope: Mapping[str, Any],
    v212: Mapping[str, Any],
    v213: Mapping[str, Any],
    federation: Mapping[str, Any],
    source_audit: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(source_audit))
    now = datetime.now(timezone.utc)
    ages = _validate_same_run_freshness(
        envelope,
        v212,
        v213,
        federation,
        normalized,
        policy,
        now,
    )
    order = final_order(envelope)
    payloads = envelope.get("payloads")
    assert isinstance(payloads, Mapping)
    top20 = json.loads(str(payloads.get("top20_json") or ""))
    if not isinstance(top20, list):
        raise SerenityEvidenceError("Diversified Top20 payload is not a list")
    top20_by_ticker = {
        str(row.get("ticker") or "").strip().upper(): row
        for row in top20
        if isinstance(row, Mapping)
    }
    raw_records = normalized.get("records")
    if not isinstance(raw_records, list) or len(raw_records) != 20:
        raise SerenityEvidenceError("Source-independence audit must expose exactly 20 records")
    records_by_ticker: dict[str, dict[str, Any]] = {}
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise SerenityEvidenceError("Source-independence record must be an object")
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not ticker or ticker in records_by_ticker:
            raise SerenityEvidenceError("Source-independence ticker membership is invalid")
        records_by_ticker[ticker] = raw
    if set(records_by_ticker) != set(order) or set(top20_by_ticker) != set(order):
        raise SerenityEvidenceError("Freshness audit membership does not match final Top20")

    record_results: list[dict[str, Any]] = []
    for ticker in order:
        result = _validate_record_evidence(
            ticker,
            top20_by_ticker[ticker],
            records_by_ticker[ticker],
            policy,
            now,
        )
        records_by_ticker[ticker]["freshness_state"] = result
        record_results.append(result)

    normalized["freshness_audit"] = {
        "schema_version": 1,
        "policy_id": policy["policy_id"],
        "evaluated_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "PASS",
        "same_run_input_age_hours": ages,
        "ticker_count": 20,
        "all_tickers_multi_source": True,
        "all_positive_advantages_fresh_multi_source": True,
        "stale_live_market_observation_count": 0,
        "records": record_results,
    }
    return normalized


def final_order(envelope: Mapping[str, Any]) -> list[str]:
    payloads = envelope.get("payloads")
    if not isinstance(payloads, Mapping):
        raise core.ActivationBundleError("Diversified envelope payloads are missing")
    try:
        rows = json.loads(str(payloads.get("top20_json") or ""))
    except json.JSONDecodeError as exc:
        raise core.ActivationBundleError("Diversified Top20 is invalid JSON") from exc
    return core.ordered_tickers(rows, "Diversified Top20")


def reorder_federation(
    federation: Mapping[str, Any],
    order: list[str],
) -> dict[str, Any]:
    result = copy.deepcopy(dict(federation))
    raw_rows = result.get("ticker_sources")
    if not isinstance(raw_rows, list) or len(raw_rows) != 20:
        raise core.ActivationBundleError("Source federation must contain exactly 20 ticker rows")
    mapping: dict[str, dict[str, Any]] = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise core.ActivationBundleError("Source federation row must be an object")
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not ticker or ticker in mapping:
            raise core.ActivationBundleError("Source federation ticker membership is invalid")
        mapping[ticker] = dict(raw)
    if set(mapping) != set(order):
        added = sorted(set(mapping) - set(order))
        missing = sorted(set(order) - set(mapping))
        raise core.ActivationBundleError(
            "Source federation membership does not match final Top20; "
            f"extra={','.join(added) or '-'}; missing={','.join(missing) or '-'}"
        )
    rows: list[dict[str, Any]] = []
    for rank, ticker in enumerate(order, 1):
        row = mapping[ticker]
        row["rank"] = rank
        rows.append(row)
    result["ticker_sources"] = rows
    return result


def build_bundle(
    envelope: Mapping[str, Any],
    v212: Mapping[str, Any],
    v213: Mapping[str, Any],
    federation: Mapping[str, Any],
    source_audit: Mapping[str, Any],
) -> dict[str, Any]:
    policy = _read_policy()
    order = final_order(envelope)
    normalized_federation = reorder_federation(federation, order)
    normalized_source_audit = normalize_and_validate_source_audit(
        envelope,
        v212,
        v213,
        normalized_federation,
        source_audit,
        policy,
    )
    bundle = core.build_bundle(
        envelope,
        v212,
        v213,
        normalized_federation,
        normalized_source_audit,
    )
    bundle["transaction_id"] = secrets.token_hex(16)
    if not TRANSACTION_ID_RE.fullmatch(str(bundle["transaction_id"])):
        raise core.ActivationBundleError("Generated activation transaction ID is invalid")
    return bundle


def _synthetic_documents() -> tuple[dict[str, Any], ...]:
    generated = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = generated.isoformat().replace("+00:00", "Z")
    run_id = generated.strftime("%Y%m%dT%H%M%SZ-") + "123456789abc"
    rows = [
        {
            "rank": index + 1,
            "ticker": f"T{index:02d}",
            "scoring_version": core.SCORING_VERSION,
            "serenity_factors": {
                "demand_wave": 1.0,
                "chokepoint": 0.0,
                "pricing_power": 0.0,
                "replacement_friction": 0.0,
                "tam_capture": 1.0,
                "valuation_expectations": 3.75,
            },
        }
        for index in range(20)
    ]
    reversed_federation_rows = [
        {"rank": index + 1, "ticker": row["ticker"]}
        for index, row in enumerate(reversed(rows))
    ]
    plan = {
        "catalog_count": 101,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }
    base_payloads = {
        "top20_json": core.canonical_json(rows),
        "source_plan_json": core.canonical_json(plan),
        "report_text": "x",
    }
    import hashlib

    envelope = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": stamp,
        "public_data_as_of": stamp,
        "payloads": base_payloads,
        "sha256": {
            name: hashlib.sha256(body.encode("utf-8")).hexdigest()
            for name, body in base_payloads.items()
        },
    }
    v212 = {"product_version": "2.1.2", "generated_at": stamp, "records": rows}
    v213 = {"product_version": "2.1.3", "generated_at": stamp, "records": rows}
    federation = {
        "schema_version": 1,
        "product_version": "2.1.3",
        "generated_at": stamp,
        "ticker_sources": reversed_federation_rows,
        "gates": {"pass": True, "unresolved_material_conflict_count": 0},
    }
    audit_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        ticker = row["ticker"]
        audit_rows.append(
            {
                "rank": index + 1,
                "ticker": ticker,
                "source_metrics": {
                    "claim_relevant_independent_families": 2,
                    "claim_relevant_independent_domains": 2,
                    "claim_relevant_primary_sources": 1,
                    "claim_dated_evidence_ratio": 1.0,
                },
                "market_corroboration": {
                    "status": "CORROBORATED",
                    "independent_provider_count": 1,
                    "providers": [
                        {
                            "provider": "nasdaq_historical_api",
                            "status": "LIVE",
                            "as_of": stamp,
                        }
                    ],
                },
                "sources": [
                    {
                        "family": "regulator_filing",
                        "domain": "sec.gov",
                        "claim_type": "xbrl_fact",
                        "title": "Fresh revenue and capacity fact",
                        "url": f"https://www.sec.gov/Archives/edgar/data/{1000000 + index}/fresh.htm",
                        "as_of": stamp,
                        "primary": True,
                    },
                    {
                        "family": "credible_industry_publication",
                        "domain": "reuters.com",
                        "claim_type": "industry_context",
                        "title": "Independent current demand corroboration",
                        "url": f"https://www.reuters.com/technology/fresh-{ticker.lower()}/",
                        "as_of": stamp,
                        "primary": False,
                    },
                ],
            }
        )
    source = {
        "schema_version": 3,
        "product_version": "2.1.3",
        "generated_at": stamp,
        "status": "PASS",
        "violations": [],
        "blocking_violations": [],
        "portfolio": {
            "claim_primary_coverage_ratio": 1.0,
            "claim_source_families": 2,
            "claim_source_domains": 2,
            "maximum_single_family_share": 0.5,
            "market_conflict_ticker_count": 0,
        },
        "records": audit_rows,
    }
    return envelope, v212, v213, federation, source


def self_test() -> None:
    envelope, v212, v213, federation, source = _synthetic_documents()
    first = build_bundle(envelope, v212, v213, federation, source)
    second = build_bundle(envelope, v212, v213, federation, source)
    normalized = json.loads(first["payloads"]["source_federation_json"])
    audit = json.loads(first["payloads"]["source_independence_json"])
    rows = json.loads(envelope["payloads"]["top20_json"])
    assert [row["ticker"] for row in normalized["ticker_sources"]] == [row["ticker"] for row in rows]
    assert [row["rank"] for row in normalized["ticker_sources"]] == list(range(1, 21))
    assert first["run_id"] == second["run_id"] == envelope["run_id"]
    assert first["transaction_id"] != second["transaction_id"]
    assert TRANSACTION_ID_RE.fullmatch(first["transaction_id"])
    assert audit["freshness_audit"]["status"] == "PASS"
    assert audit["freshness_audit"]["all_tickers_multi_source"] is True

    single = copy.deepcopy(source)
    single["records"][0]["source_metrics"]["claim_relevant_independent_families"] = 1
    single["records"][0]["sources"] = single["records"][0]["sources"][:1]
    try:
        build_bundle(envelope, v212, v213, federation, single)
    except SerenityEvidenceError as exc:
        assert "single" in str(exc) or "independently diverse" in str(exc)
    else:
        raise AssertionError("Single-source positive advantage was not rejected")

    stale_market = copy.deepcopy(source)
    stale_market["records"][0]["market_corroboration"]["providers"][0]["as_of"] = "2020-01-01"
    try:
        build_bundle(envelope, v212, v213, federation, stale_market)
    except SerenityEvidenceError as exc:
        assert "stale market" in str(exc)
    else:
        raise AssertionError("Stale LIVE market observation was not rejected")

    stale_claim = copy.deepcopy(source)
    for item in stale_claim["records"][0]["sources"]:
        item["as_of"] = "2020-01-01"
    try:
        build_bundle(envelope, v212, v213, federation, stale_claim)
    except SerenityEvidenceError as exc:
        assert "current claim evidence" in str(exc) or "independently diverse" in str(exc)
    else:
        raise AssertionError("Stale positive-advantage evidence was not rejected")

    print(
        "V213_ACTIVATION_BUNDLE_V2_SELF_TEST = PASS; "
        "federation_reordered=true; unique_transaction_id=true; "
        "fresh_same_run=true; stale_market_rejected=true; "
        "stale_claim_rejected=true; single_source_advantage_rejected=true"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v21-envelope", type=Path, default=core.V21_ENVELOPE_PATH)
    parser.add_argument("--v212-report", type=Path, default=core.V212_REPORT_PATH)
    parser.add_argument("--v213-report", type=Path, default=core.V213_REPORT_PATH)
    parser.add_argument("--source-federation", type=Path, default=core.FEDERATION_PATH)
    parser.add_argument("--source-independence", type=Path, default=core.SOURCE_AUDIT_PATH)
    parser.add_argument("--output", type=Path, default=core.OUTPUT_PATH)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    bundle = build_bundle(
        core.load_json(args.v21_envelope),
        core.load_json(args.v212_report),
        core.load_json(args.v213_report),
        core.load_json(args.source_federation),
        core.load_json(args.source_independence),
    )
    core.atomic_write(args.output, bundle)
    print(
        "V213_ACTIVATION_BUNDLE_V2 = PASS; "
        f"run_id={bundle['run_id']}; transaction_id={bundle['transaction_id']}; "
        f"payloads={len(bundle['payloads'])}; federation_order=final_top20; "
        "fresh_multi_source_serenity_gate=true",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (core.ActivationBundleError, SerenityEvidenceError, OSError, ValueError) as exc:
        print(f"V213_ACTIVATION_BUNDLE_V2 = FAIL; {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
