#!/usr/bin/env python3
"""Build the hardened v2.1.3 atomic activation bundle.

Final candidates use one of two explicit evidence modes:

* ``EVIDENCE_QUALIFIED`` — company/thesis claims have fresh, dated evidence
  from at least two independent claim families and domains, including primary
  evidence. Any positive Serenity advantage additionally requires a fresh
  independently operated non-primary corroborator.
* ``LIMITED_RESEARCH_CANDIDATE`` — all sensitive positive advantages have
  already been withheld. The row may remain as a research-priority candidate
  only when it has at least one latest-available primary company source plus a
  separate, fresh regulated listing/legal-entity provenance origin. It is not a
  validated thesis, cannot be HIGH eligible, and remains explicitly LIMITED.

Market, macro, listing identity and legal-entity identity never prove a company
operating claim or positive Serenity advantage. They are kept in distinct
evidence scopes. All seven payloads must still belong to one fresh coherent run.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import secrets
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
CORE_PATH = SCRIPT_DIR / "build_v213_activation_bundle.py"
FRESHNESS_POLICY_PATH = ROOT / "config" / "v213-serenity-evidence-freshness-policy.json"
LIMITED_POLICY_PATH = ROOT / "config" / "v213-limited-research-candidate-policy.json"

TRANSACTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
EVIDENCE_QUALIFIED = "EVIDENCE_QUALIFIED"
LIMITED_RESEARCH_CANDIDATE = "LIMITED_RESEARCH_CANDIDATE"
LIMITED_MISSING_CODE = "INDEPENDENT_CLAIM_CORROBORATION"
LIMITED_MODE_CODE = "LIMITED_RESEARCH_CANDIDATE"
LIMITED_RISK_FLAG = "positive_advantage_withheld_until_fresh_multisource_support"

NON_CLAIM_TYPES = {
    "market_return_calculation",
    "independent_market_corroboration",
    "macro_context",
    "regulated_listing_identity",
    "legal_entity_reference",
    "live_legal_entity_registry_observation",
    "independent_legal_entity_identity",
}
IDENTITY_PROVENANCE_TYPES = {
    "regulated_listing_identity",
    "legal_entity_reference",
    "live_legal_entity_registry_observation",
    "independent_legal_entity_identity",
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
SEVERE_STATES = {
    "THESIS_BROKEN",
    "BROKEN",
    "THESIS_IMPAIRED",
    "DESTROYED",
}
CLAIM_DRIVEN_LOGIC_FIELDS = (
    "architecture",
    "dependency_graph",
    "bottleneck_or_expansion",
    "company_capture",
    "lifecycle",
)


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
            raise SerenityEvidenceError(
                f"Invalid evidence timestamp: {label}"
            ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(value: Any, label: str, now: datetime, skew_minutes: int) -> float:
    parsed = _timestamp(value, label)
    seconds = (now - parsed).total_seconds()
    if seconds < -(skew_minutes * 60):
        raise SerenityEvidenceError(
            f"Future-dated evidence exceeds clock tolerance: {label}"
        )
    return max(0.0, seconds / 86400.0)


def _read_policy(path: Path = FRESHNESS_POLICY_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        limited_document = json.loads(
            LIMITED_POLICY_PATH.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SerenityEvidenceError(
            "Unable to read Serenity freshness/limited-publication policy"
        ) from exc
    limited = (
        limited_document.get("limited_research_candidate_policy")
        if isinstance(limited_document, dict)
        else None
    )
    if (
        not isinstance(limited_document, dict)
        or limited_document.get("schema_version") != 1
        or limited_document.get("product_version") != "2.1.3"
        or not isinstance(limited, dict)
    ):
        raise SerenityEvidenceError(
            "Limited-research-candidate policy schema is invalid"
        )
    value = {**value, **limited}
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
        "identity_provenance_can_support_positive_advantage",
        "limited_research_candidate_is_validated_thesis",
        "limited_research_candidate_high_confidence_allowed",
    )
    required_true = (
        "limited_research_candidate_publication_allowed",
        "limited_research_candidate_requires_all_sensitive_advantage_factors_zero",
        "limited_research_candidate_requires_latest_available_primary_source",
        "fresh_non_primary_corroborator_required_for_positive_advantage",
        "retrieval_timestamp_cannot_substitute_publication_date",
        "latest_available_evidence_must_be_selected",
    )
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("product_version") != "2.1.3"
        or not str(value.get("policy_id") or "").startswith("v213-serenity-")
        or any(value.get(name) is not False for name in required_false)
        or any(value.get(name) is not True for name in required_true)
        or _integer(value.get("minimum_claim_source_families_per_ticker")) < 2
        or _integer(value.get("minimum_claim_source_domains_per_ticker")) < 2
        or _integer(value.get("minimum_claim_primary_sources_per_ticker")) < 1
        or _number(value.get("minimum_claim_dated_evidence_ratio")) < 0.8
        or _integer(value.get("minimum_limited_candidate_primary_claim_sources")) < 1
        or _integer(value.get("minimum_limited_candidate_provenance_origins")) < 2
        or _integer(value.get("minimum_limited_candidate_provenance_domains")) < 2
        or _number(value.get("limited_candidate_primary_claim_max_age_days")) <= 0
        or _number(value.get("identity_provenance_max_age_days")) <= 0
        or value.get("limited_candidate_missing_evidence_code") != LIMITED_MISSING_CODE
        or _number(value.get("market_observation_max_age_days")) <= 0
        or _number(value.get("current_state_claim_max_age_days")) <= 0
        or _number(value.get("structural_claim_max_age_days")) <= 0
    ):
        raise SerenityEvidenceError(
            "Serenity evidence freshness/publication policy is invalid or weakened"
        )
    return value


def _domain(source: Mapping[str, Any]) -> str:
    declared = str(source.get("domain") or "").strip().lower().strip(".")
    if declared and declared != "unknown":
        return declared
    try:
        host = (
            urllib.parse.urlsplit(str(source.get("url") or "")).hostname or ""
        ).lower().strip(".")
    except ValueError:
        return ""
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def _family(source: Mapping[str, Any]) -> str:
    return str(source.get("family") or "").strip().lower()


def _claim_type(source: Mapping[str, Any]) -> str:
    return str(source.get("claim_type") or "").strip().lower()


def _source_id(source: Mapping[str, Any]) -> str:
    return str(source.get("source_id") or "").strip().lower()


def _is_market_or_macro(source: Mapping[str, Any]) -> bool:
    family = _family(source)
    claim_type = _claim_type(source)
    return bool(
        family in NON_CLAIM_FAMILIES
        or family.endswith("_market")
        or claim_type
        in {
            "market_return_calculation",
            "independent_market_corroboration",
            "macro_context",
        }
    )


def _is_identity_provenance(source: Mapping[str, Any]) -> bool:
    source_id = _source_id(source)
    return bool(
        _claim_type(source) in IDENTITY_PROVENANCE_TYPES
        or source_id.startswith("nasdaq_symbol_directory")
        or source_id.startswith("gleif")
    )


def _is_claim_source(source: Mapping[str, Any]) -> bool:
    family = _family(source)
    claim_type = _claim_type(source)
    return bool(
        family
        and claim_type
        and not _is_market_or_macro(source)
        and not _is_identity_provenance(source)
        and family not in NON_CLAIM_FAMILIES
        and claim_type not in NON_CLAIM_TYPES
    )


def _source_unit(source: Mapping[str, Any]) -> tuple[str, str, str]:
    return _family(source), _domain(source), _claim_type(source)


def _unique_units(
    sources: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    units: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for source in sources:
        unit = _source_unit(source)
        if not all(unit):
            continue
        units.setdefault(unit, source)
    return list(units.values())


def _provenance_origin(source: Mapping[str, Any]) -> str:
    source_id = _source_id(source)
    family = _family(source)
    domain = _domain(source)
    if source_id.startswith("nasdaq_symbol_directory"):
        return "nasdaq_symbol_directory"
    if source_id.startswith("gleif"):
        return "gleif_legal_entity_registry"
    if family == "regulator_filing" or domain == "sec.gov":
        return "sec_regulator_filing"
    if family == "issuer_primary":
        return f"issuer_primary:{domain}"
    if family == "exchange_sro":
        return f"exchange_sro:{domain}"
    return f"{family or source_id}:{domain}"


def _unique_provenance_origins(
    sources: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    units: dict[tuple[str, str], Mapping[str, Any]] = {}
    for source in sources:
        domain = _domain(source)
        origin = _provenance_origin(source)
        if not origin or not domain:
            continue
        units.setdefault((origin, domain), source)
    return list(units.values())


def _positive_advantage_factors(
    row: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[str]:
    factors = row.get("serenity_factors")
    if not isinstance(factors, Mapping):
        return []
    required = [
        str(value)
        for value in policy.get("sensitive_advantage_factors", [])
    ]
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
    maximum_hours = _number(
        policy.get("activation_snapshot_max_age_hours"), 2.0
    )
    dated_values = {
        "envelope.generated_at": envelope.get("generated_at"),
        "envelope.public_data_as_of": envelope.get("public_data_as_of"),
        "v212.generated_at": v212.get("generated_at"),
        "v213.generated_at": v213.get("generated_at"),
        "source_federation.generated_at": federation.get("generated_at"),
        "source_independence.generated_at": source_audit.get("generated_at"),
    }
    ages: dict[str, float] = {}
    timestamps: list[datetime] = []
    for label, value in dated_values.items():
        parsed = _timestamp(value, label)
        timestamps.append(parsed)
        seconds = (now - parsed).total_seconds()
        if seconds < -(skew * 60):
            raise SerenityEvidenceError(
                f"Final activation input is future-dated: {label}"
            )
        age_hours = max(0.0, seconds / 3600.0)
        if age_hours > maximum_hours:
            raise SerenityEvidenceError(
                f"Final activation input is stale: {label}; "
                f"age_hours={age_hours:.2f}; max={maximum_hours:.2f}"
            )
        ages[label] = round(age_hours, 4)
    spread = (max(timestamps) - min(timestamps)).total_seconds() / 3600.0
    if spread > maximum_hours:
        raise SerenityEvidenceError(
            "Final activation inputs do not belong to one fresh run; "
            f"timestamp_spread_hours={spread:.2f}"
        )
    return ages


def _latest_dated_sources(
    sources: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    skew: int,
    max_age_days: float,
    label: str,
) -> list[tuple[Mapping[str, Any], float]]:
    result: list[tuple[Mapping[str, Any], float]] = []
    for index, source in enumerate(sources):
        url = str(source.get("url") or "")
        if not url.startswith("https://"):
            continue
        try:
            age = _age_days(
                source.get("as_of"),
                f"{label}[{index}].as_of",
                now,
                skew,
            )
        except SerenityEvidenceError:
            continue
        if age <= max_age_days:
            result.append((source, age))
    return result


def _validate_market(
    ticker: str,
    top20_row: Mapping[str, Any],
    audit_row: Mapping[str, Any],
    policy: Mapping[str, Any],
    now: datetime,
) -> int:
    skew = _integer(policy.get("clock_skew_tolerance_minutes"), 5)
    market_max = _number(policy.get("market_observation_max_age_days"), 7.0)
    market = audit_row.get("market_corroboration")
    if not isinstance(market, Mapping):
        raise SerenityEvidenceError(
            f"{ticker}: market corroboration object is missing"
        )
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
        provider_name = str(
            provider.get("provider") or f"provider-{index}"
        )
        try:
            age = _age_days(
                provider.get("as_of"),
                f"{ticker}.{provider_name}.as_of",
                now,
                skew,
            )
        except SerenityEvidenceError:
            stale_live.append(provider_name + ":undated")
            continue
        if age > market_max:
            stale_live.append(provider_name + f":{age:.1f}d")
        else:
            fresh_market += 1
    if stale_live:
        raise SerenityEvidenceError(
            f"{ticker}: stale market observations remain LIVE/CACHED: "
            + ",".join(stale_live)
        )
    declared_provider_count = _integer(
        market.get("independent_provider_count")
    )
    if declared_provider_count != fresh_market:
        raise SerenityEvidenceError(
            f"{ticker}: market provider count is not freshness-adjusted; "
            f"declared={declared_provider_count}; fresh={fresh_market}"
        )
    market_status = str(market.get("status") or "")
    if market_status in {
        "CONFLICT_REVIEW",
        "CALCULATION_DIVERGENCE_REVIEW",
    }:
        raise SerenityEvidenceError(
            f"{ticker}: unresolved market-source conflict cannot enter "
            "final activation"
        )
    factors = top20_row.get("serenity_factors")
    valuation = (
        _number(factors.get("valuation_expectations"))
        if isinstance(factors, Mapping)
        else 0.0
    )
    if fresh_market == 0 and valuation > 3.75:
        raise SerenityEvidenceError(
            f"{ticker}: uncorroborated valuation factor exceeds the "
            "3.75 safety cap"
        )
    return fresh_market


def _validate_record_evidence(
    ticker: str,
    top20_row: Mapping[str, Any],
    audit_row: dict[str, Any],
    policy: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    skew = _integer(policy.get("clock_skew_tolerance_minutes"), 5)
    current_max = _number(
        policy.get("current_state_claim_max_age_days"), 135.0
    )
    structural_max = _number(
        policy.get("structural_claim_max_age_days"), 550.0
    )
    identity_max = _number(
        policy.get("identity_provenance_max_age_days"), 7.0
    )
    limited_primary_max = _number(
        policy.get("limited_candidate_primary_claim_max_age_days"),
        structural_max,
    )
    min_families = _integer(
        policy.get("minimum_claim_source_families_per_ticker"), 2
    )
    min_domains = _integer(
        policy.get("minimum_claim_source_domains_per_ticker"), 2
    )
    min_primary = _integer(
        policy.get("minimum_claim_primary_sources_per_ticker"), 1
    )
    min_advantage_units = _integer(
        policy.get("minimum_sensitive_advantage_source_units"), 2
    )
    min_advantage_domains = _integer(
        policy.get("minimum_sensitive_advantage_domains"), 2
    )
    min_dated_ratio = _number(
        policy.get("minimum_claim_dated_evidence_ratio"), 0.8
    )
    limited_min_primary = _integer(
        policy.get("minimum_limited_candidate_primary_claim_sources"), 1
    )
    limited_min_origins = _integer(
        policy.get("minimum_limited_candidate_provenance_origins"), 2
    )
    limited_min_domains = _integer(
        policy.get("minimum_limited_candidate_provenance_domains"), 2
    )

    raw_sources = audit_row.get("sources")
    if not isinstance(raw_sources, list):
        raise SerenityEvidenceError(
            f"{ticker}: source audit does not expose source-level provenance"
        )
    sources = [
        source for source in raw_sources if isinstance(source, Mapping)
    ]
    claim_sources = [source for source in sources if _is_claim_source(source)]
    identity_sources = [
        source for source in sources if _is_identity_provenance(source)
    ]

    all_claim_units = _unique_units(claim_sources)
    dated_claim_pairs = _latest_dated_sources(
        all_claim_units,
        now=now,
        skew=skew,
        max_age_days=structural_max,
        label=f"{ticker}.claim_sources",
    )
    dated_claim_units = _unique_units(
        source for source, _age in dated_claim_pairs
    )
    claim_families = {_family(source) for source in dated_claim_units}
    claim_domains = {
        _domain(source)
        for source in dated_claim_units
        if _domain(source)
    }
    claim_primary = [
        source
        for source in dated_claim_units
        if bool(source.get("primary"))
        or _family(source) in CLAIM_PRIMARY_FAMILIES
    ]
    dated_ratio = (
        len(dated_claim_units) / len(all_claim_units)
        if all_claim_units
        else 0.0
    )

    current_pairs = [
        (source, age)
        for source, age in dated_claim_pairs
        if age <= current_max
    ]
    current_units = _unique_units(source for source, _age in current_pairs)
    current_domains = {
        _domain(source) for source in current_units if _domain(source)
    }
    current_primary = [
        source
        for source in current_units
        if bool(source.get("primary"))
        or _family(source) in CLAIM_PRIMARY_FAMILIES
    ]
    current_non_primary = [
        source
        for source in current_units
        if not (
            bool(source.get("primary"))
            or _family(source) in CLAIM_PRIMARY_FAMILIES
        )
    ]

    identity_pairs = _latest_dated_sources(
        identity_sources,
        now=now,
        skew=skew,
        max_age_days=identity_max,
        label=f"{ticker}.identity_sources",
    )
    provenance_sources = [
        source for source, age in dated_claim_pairs if age <= limited_primary_max
    ] + [source for source, _age in identity_pairs]
    provenance_units = _unique_provenance_origins(provenance_sources)
    provenance_origins = {
        _provenance_origin(source) for source in provenance_units
    }
    provenance_domains = {
        _domain(source)
        for source in provenance_units
        if _domain(source)
    }
    limited_primary = [
        source
        for source, age in dated_claim_pairs
        if age <= limited_primary_max
        and (
            bool(source.get("primary"))
            or _family(source) in CLAIM_PRIMARY_FAMILIES
        )
    ]

    metrics = audit_row.get("source_metrics")
    if not isinstance(metrics, dict):
        raise SerenityEvidenceError(f"{ticker}: source metrics are missing")
    metrics.update(
        {
            "claim_relevant_independent_families": len(claim_families),
            "claim_relevant_independent_domains": len(claim_domains),
            "claim_relevant_primary_sources": len(claim_primary),
            "claim_dated_evidence_ratio": round(dated_ratio, 4),
            "claim_families": sorted(claim_families),
            "claim_domains": sorted(claim_domains),
            "publication_provenance_origin_count": len(provenance_origins),
            "publication_provenance_domain_count": len(provenance_domains),
            "publication_provenance_origins": sorted(provenance_origins),
            "publication_provenance_domains": sorted(provenance_domains),
            "identity_provenance_count": len(
                _unique_provenance_origins(
                    source for source, _age in identity_pairs
                )
            ),
        }
    )

    positive_factors = _positive_advantage_factors(top20_row, policy)
    strict_claim_qualified = bool(
        len(claim_families) >= min_families
        and len(claim_domains) >= min_domains
        and len(claim_primary) >= min_primary
        and dated_ratio >= min_dated_ratio
        and current_units
    )
    positive_support = bool(
        len(current_units) >= min_advantage_units
        and len(current_domains) >= min_advantage_domains
        and current_primary
        and current_non_primary
    )

    logic = audit_row.get("public_logic_state")
    if not isinstance(logic, dict):
        raise SerenityEvidenceError(
            f"{ticker}: public-logic state is missing"
        )
    severe = {
        str(logic.get(name) or "").upper()
        for name in CLAIM_DRIVEN_LOGIC_FIELDS
    } & SEVERE_STATES
    if severe:
        raise SerenityEvidenceError(
            f"{ticker}: severe thesis state cannot be published: "
            + ",".join(sorted(severe))
        )

    if positive_factors:
        if not strict_claim_qualified:
            raise SerenityEvidenceError(
                f"{ticker}: positive Serenity advantages require independently "
                "diverse current company evidence: "
                + ",".join(positive_factors)
            )
        if not positive_support:
            raise SerenityEvidenceError(
                f"{ticker}: positive Serenity advantages lack a fresh primary "
                "source plus an independently operated non-primary "
                "corroborator: "
                + ",".join(positive_factors)
            )
        publication_mode = EVIDENCE_QUALIFIED
    elif strict_claim_qualified:
        publication_mode = EVIDENCE_QUALIFIED
    else:
        if (
            policy.get("limited_research_candidate_publication_allowed")
            is not True
        ):
            raise SerenityEvidenceError(
                f"{ticker}: source-level provenance is not independently diverse"
            )
        if len(limited_primary) < limited_min_primary:
            raise SerenityEvidenceError(
                f"{ticker}: limited research candidate lacks a latest-available "
                f"primary company source within {limited_primary_max:g} days"
            )
        if (
            len(provenance_origins) < limited_min_origins
            or len(provenance_domains) < limited_min_domains
        ):
            raise SerenityEvidenceError(
                f"{ticker}: limited research candidate still depends on one "
                "publication origin; "
                f"origins={len(provenance_origins)}; "
                f"domains={len(provenance_domains)}"
            )
        publication_mode = LIMITED_RESEARCH_CANDIDATE
        audit_row["eligible_for_high_confidence_model_inference"] = False
        logic["model_inference_confidence"] = "LIMITED"
        logic["publication_evidence_mode"] = publication_mode
        logic["identity_provenance_is_company_claim_evidence"] = False
        logic["identity_provenance_can_support_positive_advantage"] = False
        logic["validated_company_thesis"] = False
        for field in CLAIM_DRIVEN_LOGIC_FIELDS:
            logic[field] = "UNPROVEN"
        missing = {
            str(value)
            for value in audit_row.get("missing_or_review", [])
            if str(value) and str(value) != "PORTFOLIO_SOURCE_POLICY"
        }
        missing.add(LIMITED_MISSING_CODE)
        missing.add(LIMITED_MODE_CODE)
        audit_row["missing_or_review"] = sorted(missing)

    fresh_market = _validate_market(
        ticker,
        top20_row,
        audit_row,
        policy,
        now,
    )
    audit_row["publication_evidence_mode"] = publication_mode
    logic["publication_evidence_mode"] = publication_mode
    if publication_mode == EVIDENCE_QUALIFIED:
        logic["validated_company_thesis"] = bool(positive_factors)
        logic["identity_provenance_is_company_claim_evidence"] = False
        logic["identity_provenance_can_support_positive_advantage"] = False

    latest_claim = min(
        (age for _source, age in dated_claim_pairs),
        default=None,
    )
    latest_current = min(
        (age for _source, age in current_pairs),
        default=None,
    )
    latest_primary = min(
        (
            age
            for source, age in dated_claim_pairs
            if bool(source.get("primary"))
            or _family(source) in CLAIM_PRIMARY_FAMILIES
        ),
        default=None,
    )
    return {
        "ticker": ticker,
        "status": "PASS",
        "publication_evidence_mode": publication_mode,
        "validated_company_thesis": bool(
            publication_mode == EVIDENCE_QUALIFIED and positive_factors
        ),
        "claim_source_units": len(dated_claim_units),
        "claim_source_families": len(claim_families),
        "claim_source_domains": len(claim_domains),
        "claim_primary_units": len(claim_primary),
        "fresh_claim_source_units": len(current_units),
        "fresh_claim_source_domains": len(current_domains),
        "fresh_claim_primary_units": len(current_primary),
        "fresh_claim_non_primary_units": len(current_non_primary),
        "publication_provenance_origin_count": len(provenance_origins),
        "publication_provenance_domain_count": len(provenance_domains),
        "identity_provenance_count": metrics[
            "identity_provenance_count"
        ],
        "fresh_market_provider_count": fresh_market,
        "latest_claim_age_days": (
            round(latest_claim, 3)
            if latest_claim is not None
            else None
        ),
        "latest_current_claim_age_days": (
            round(latest_current, 3)
            if latest_current is not None
            else None
        ),
        "latest_primary_claim_age_days": (
            round(latest_primary, 3)
            if latest_primary is not None
            else None
        ),
        "positive_advantage_factors": positive_factors,
        "identity_provenance_can_support_positive_advantage": False,
        "limited_candidate_is_validated_thesis": False,
    }


def final_order(envelope: Mapping[str, Any]) -> list[str]:
    payloads = envelope.get("payloads")
    if not isinstance(payloads, Mapping):
        raise core.ActivationBundleError(
            "Diversified envelope payloads are missing"
        )
    try:
        rows = json.loads(str(payloads.get("top20_json") or ""))
    except json.JSONDecodeError as exc:
        raise core.ActivationBundleError(
            "Diversified Top20 is invalid JSON"
        ) from exc
    return core.ordered_tickers(rows, "Diversified Top20")


def reorder_federation(
    federation: Mapping[str, Any],
    order: list[str],
) -> dict[str, Any]:
    result = copy.deepcopy(dict(federation))
    raw_rows = result.get("ticker_sources")
    if not isinstance(raw_rows, list) or len(raw_rows) != 20:
        raise core.ActivationBundleError(
            "Source federation must contain exactly 20 ticker rows"
        )
    mapping: dict[str, dict[str, Any]] = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise core.ActivationBundleError(
                "Source federation row must be an object"
            )
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not ticker or ticker in mapping:
            raise core.ActivationBundleError(
                "Source federation ticker membership is invalid"
            )
        mapping[ticker] = dict(raw)
    if set(mapping) != set(order):
        raise core.ActivationBundleError(
            "Source federation membership does not match final Top20"
        )
    rows: list[dict[str, Any]] = []
    for rank, ticker in enumerate(order, 1):
        row = mapping[ticker]
        row["rank"] = rank
        rows.append(row)
    result["ticker_sources"] = rows
    return result


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
    try:
        top20 = json.loads(str(payloads.get("top20_json") or ""))
    except json.JSONDecodeError as exc:
        raise SerenityEvidenceError(
            "Diversified Top20 payload is not valid JSON"
        ) from exc
    if not isinstance(top20, list):
        raise SerenityEvidenceError(
            "Diversified Top20 payload is not a list"
        )
    top20_by_ticker = {
        str(row.get("ticker") or "").strip().upper(): row
        for row in top20
        if isinstance(row, Mapping)
    }
    raw_records = normalized.get("records")
    if not isinstance(raw_records, list) or len(raw_records) != 20:
        raise SerenityEvidenceError(
            "Source-independence audit must expose exactly 20 records"
        )
    records_by_ticker: dict[str, dict[str, Any]] = {}
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise SerenityEvidenceError(
                "Source-independence record must be an object"
            )
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not ticker or ticker in records_by_ticker:
            raise SerenityEvidenceError(
                "Source-independence ticker membership is invalid"
            )
        records_by_ticker[ticker] = raw
    if set(records_by_ticker) != set(order) or set(top20_by_ticker) != set(
        order
    ):
        raise SerenityEvidenceError(
            "Freshness audit membership does not match final Top20"
        )

    record_results: list[dict[str, Any]] = []
    ordered_records: list[dict[str, Any]] = []
    for rank, ticker in enumerate(order, 1):
        record = records_by_ticker[ticker]
        record["rank"] = rank
        result = _validate_record_evidence(
            ticker,
            top20_by_ticker[ticker],
            record,
            policy,
            now,
        )
        record["freshness_state"] = result
        record_results.append(result)
        ordered_records.append(record)
    normalized["records"] = ordered_records

    strict_count = sum(
        result["publication_evidence_mode"] == EVIDENCE_QUALIFIED
        for result in record_results
    )
    limited_count = len(record_results) - strict_count
    all_provenance = all(
        _integer(result["publication_provenance_origin_count"]) >= 2
        and _integer(result["publication_provenance_domain_count"]) >= 2
        for result in record_results
    )

    claim_families: set[str] = set()
    claim_domains: set[str] = set()
    primary_covered = 0
    for record in ordered_records:
        metrics = record.get("source_metrics")
        if not isinstance(metrics, Mapping):
            continue
        claim_families.update(
            str(value)
            for value in metrics.get("claim_families", [])
            if str(value)
        )
        claim_domains.update(
            str(value)
            for value in metrics.get("claim_domains", [])
            if str(value)
        )
        if _integer(metrics.get("claim_relevant_primary_sources")) >= 1:
            primary_covered += 1

    portfolio = normalized.get("portfolio")
    if not isinstance(portfolio, dict):
        raise SerenityEvidenceError(
            "Source-independence portfolio summary is missing"
        )
    portfolio.update(
        {
            "claim_source_families": len(claim_families),
            "claim_source_domains": len(claim_domains),
            "claim_source_family_list": sorted(claim_families),
            "claim_source_domain_list": sorted(claim_domains),
            "claim_primary_coverage_ratio": round(
                primary_covered / 20.0, 4
            ),
            "evidence_qualified_candidate_count": strict_count,
            "limited_research_candidate_count": limited_count,
            "all_rows_publication_provenance_multi_source": all_provenance,
            "all_rows_claim_multisource": limited_count == 0,
            "limited_rows_high_confidence_eligible_count": sum(
                1
                for record in ordered_records
                if record.get("publication_evidence_mode")
                == LIMITED_RESEARCH_CANDIDATE
                and record.get(
                    "eligible_for_high_confidence_model_inference"
                )
                is True
            ),
        }
    )
    if not all_provenance:
        raise SerenityEvidenceError(
            "At least one final candidate still has single-origin "
            "publication provenance"
        )
    if portfolio["limited_rows_high_confidence_eligible_count"] != 0:
        raise SerenityEvidenceError(
            "A limited research candidate is incorrectly HIGH eligible"
        )

    notice = normalized.get("methodology_notice")
    if not isinstance(notice, dict):
        notice = {}
        normalized["methodology_notice"] = notice
    notice.update(
        {
            "publication_evidence_policy": (
                "evidence-qualified-or-limited-research-candidate-v1"
            ),
            "positive_advantage_requires_independent_claim_corroboration": True,
            "limited_research_candidate_publication_allowed": True,
            "limited_research_candidate_is_validated_thesis": False,
            "limited_research_candidate_high_confidence_allowed": False,
            "identity_provenance_is_company_claim_evidence": False,
            "identity_provenance_can_support_positive_advantage": False,
            "limited_candidate_requires_primary_plus_independent_provenance": True,
            "latest_available_primary_evidence_required": True,
        }
    )
    normalized["freshness_audit"] = {
        "schema_version": 2,
        "policy_id": policy["policy_id"],
        "evaluated_at": now.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": "PASS",
        "same_run_input_age_hours": ages,
        "ticker_count": 20,
        "all_tickers_multi_source": all_provenance,
        "all_tickers_publication_provenance_multi_source": all_provenance,
        "all_tickers_claim_multisource": limited_count == 0,
        "all_positive_advantages_fresh_multi_source": True,
        "stale_live_market_observation_count": 0,
        "evidence_qualified_candidate_count": strict_count,
        "limited_research_candidate_count": limited_count,
        "records": record_results,
    }
    return normalized


def _validate_inputs(
    envelope: Mapping[str, Any],
    v212: Mapping[str, Any],
    v213: Mapping[str, Any],
    federation: Mapping[str, Any],
    source_audit: Mapping[str, Any],
) -> tuple[str, list[str]]:
    if envelope.get("schema_version") != 1:
        raise core.ActivationBundleError(
            "Diversified v2.1 snapshot envelope schema must be 1"
        )
    run_id = str(envelope.get("run_id") or "")
    if not core.RUN_ID_RE.fullmatch(run_id):
        raise core.ActivationBundleError(
            "Diversified v2.1 run_id is invalid"
        )
    core.timestamp(envelope.get("generated_at"), "envelope.generated_at")
    core.timestamp(
        envelope.get("public_data_as_of"),
        "envelope.public_data_as_of",
    )
    payloads = envelope.get("payloads")
    digests = envelope.get("sha256")
    if not isinstance(payloads, dict) or not isinstance(digests, dict):
        raise core.ActivationBundleError(
            "Diversified v2.1 payload/digest objects are missing"
        )
    if set(payloads) != {
        "top20_json",
        "source_plan_json",
        "report_text",
    }:
        raise core.ActivationBundleError(
            "Diversified v2.1 payload keys are invalid"
        )
    if set(digests) != set(payloads):
        raise core.ActivationBundleError(
            "Diversified v2.1 digest keys are invalid"
        )
    for name, body in payloads.items():
        if not isinstance(body, str):
            raise core.ActivationBundleError(
                f"Diversified payload {name} is not text"
            )
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual != str(digests.get(name) or ""):
            raise core.ActivationBundleError(
                f"Diversified payload digest mismatch: {name}"
            )

    try:
        top20 = json.loads(str(payloads["top20_json"]))
        plan = json.loads(str(payloads["source_plan_json"]))
    except json.JSONDecodeError as exc:
        raise core.ActivationBundleError(
            "Diversified Top20/source plan is invalid JSON"
        ) from exc
    order = core.ordered_tickers(top20, "Diversified Top20")
    if any(
        not isinstance(row, dict)
        or row.get("scoring_version") != core.SCORING_VERSION
        for row in top20
    ):
        raise core.ActivationBundleError(
            "Top20 contains a provisional or legacy scoring row"
        )
    if (
        not isinstance(plan, dict)
        or plan.get("catalog_count") != 101
        or plan.get("provider_scope") != "public_only"
        or plan.get("owner_watchlist_inherited") is not False
    ):
        raise core.ActivationBundleError(
            "Diversified source plan boundary is invalid"
        )

    if v212.get("product_version") != "2.1.2":
        raise core.ActivationBundleError(
            "v2.1.2 report product version is invalid"
        )
    if v213.get("product_version") != "2.1.3":
        raise core.ActivationBundleError(
            "v2.1.3 report product version is invalid"
        )
    if core.ordered_tickers(
        v212.get("records"), "v2.1.2 report"
    ) != order:
        raise core.ActivationBundleError(
            "v2.1.2 report order does not match final Top20"
        )
    if core.ordered_tickers(
        v213.get("records"), "v2.1.3 report"
    ) != order:
        raise core.ActivationBundleError(
            "v2.1.3 report order does not match final Top20"
        )

    gates = federation.get("gates")
    if (
        federation.get("schema_version") != 1
        or federation.get("product_version") != "2.1.3"
        or not isinstance(gates, dict)
        or gates.get("pass") is not True
        or _integer(gates.get("unresolved_material_conflict_count")) != 0
    ):
        raise core.ActivationBundleError(
            "Live source federation is not publishable"
        )
    core.timestamp(
        federation.get("generated_at"),
        "source_federation.generated_at",
    )
    if core.ordered_tickers(
        federation.get("ticker_sources"),
        "source federation",
    ) != order:
        raise core.ActivationBundleError(
            "Source federation order does not match final Top20"
        )

    portfolio = source_audit.get("portfolio")
    violations = source_audit.get("violations")
    blockers = source_audit.get("blocking_violations")
    freshness = source_audit.get("freshness_audit")
    if (
        _integer(source_audit.get("schema_version")) < 3
        or source_audit.get("product_version") != "2.1.3"
        or source_audit.get("status") != "PASS"
        or not isinstance(violations, list)
        or violations
        or not isinstance(blockers, list)
        or blockers
        or not isinstance(portfolio, Mapping)
        or _number(portfolio.get("claim_primary_coverage_ratio")) < 0.75
        or _integer(portfolio.get("claim_source_families")) < 1
        or _integer(portfolio.get("claim_source_domains")) < 1
        or _number(portfolio.get("maximum_single_family_share"), 1.0)
        > 0.70
        or _integer(portfolio.get("market_conflict_ticker_count")) != 0
        or portfolio.get(
            "all_rows_publication_provenance_multi_source"
        )
        is not True
        or _integer(
            portfolio.get("limited_rows_high_confidence_eligible_count")
        )
        != 0
        or not isinstance(freshness, Mapping)
        or freshness.get("status") != "PASS"
        or freshness.get(
            "all_tickers_publication_provenance_multi_source"
        )
        is not True
        or freshness.get(
            "all_positive_advantages_fresh_multi_source"
        )
        is not True
    ):
        raise core.ActivationBundleError(
            "Claim-level/publication-provenance audit contains a "
            "blocking defect"
        )
    core.timestamp(
        source_audit.get("generated_at"),
        "source_independence.generated_at",
    )
    if core.ordered_tickers(
        source_audit.get("records"),
        "source independence",
    ) != order:
        raise core.ActivationBundleError(
            "Source-independence order does not match final Top20"
        )
    return run_id, order


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
    run_id, _ = _validate_inputs(
        envelope,
        v212,
        v213,
        normalized_federation,
        normalized_source_audit,
    )
    original_payloads = envelope["payloads"]
    assert isinstance(original_payloads, Mapping)
    payloads = {
        "top20_json": str(original_payloads["top20_json"]),
        "source_plan_json": str(original_payloads["source_plan_json"]),
        "report_text": str(original_payloads["report_text"]),
        "v212_top20_report_json": core.canonical_json(v212),
        "v213_top20_report_json": core.canonical_json(v213),
        "source_federation_json": core.canonical_json(
            normalized_federation
        ),
        "source_independence_json": core.canonical_json(
            normalized_source_audit
        ),
    }
    digests = {
        name: hashlib.sha256(body.encode("utf-8")).hexdigest()
        for name, body in payloads.items()
    }
    bundle = {
        "schema_version": 4,
        "product_version": "2.1.3",
        "transaction_id": secrets.token_hex(16),
        "run_id": run_id,
        "generated_at": str(envelope["generated_at"]),
        "public_data_as_of": str(envelope["public_data_as_of"]),
        "payloads": payloads,
        "sha256": digests,
    }
    if not TRANSACTION_ID_RE.fullmatch(
        str(bundle["transaction_id"])
    ):
        raise core.ActivationBundleError(
            "Generated activation transaction ID is invalid"
        )
    return bundle


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        json.dump(
            value,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        handle.write("\n")
        pending = Path(handle.name)
    pending.replace(path)


def _synthetic_documents() -> tuple[dict[str, Any], ...]:
    generated = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = generated.isoformat().replace("+00:00", "Z")
    run_id = (
        generated.strftime("%Y%m%dT%H%M%SZ-")
        + "123456789abc"
    )
    rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    federation_rows: list[dict[str, Any]] = []
    for index in range(20):
        ticker = f"T{index:02d}"
        rows.append(
            {
                "rank": index + 1,
                "ticker": ticker,
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
        )
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
                    "status": "UNAVAILABLE",
                    "independent_provider_count": 0,
                    "providers": [],
                },
                "sources": [
                    {
                        "source_id": "sec_edgar",
                        "family": "regulator_filing",
                        "domain": "sec.gov",
                        "claim_type": "xbrl_fact",
                        "title": "Fresh company fact",
                        "url": (
                            "https://www.sec.gov/Archives/edgar/data/"
                            f"{1000000 + index}/fresh.htm"
                        ),
                        "as_of": stamp,
                        "primary": True,
                    },
                    {
                        "source_id": "reuters",
                        "family": "reputable_secondary",
                        "domain": "reuters.com",
                        "claim_type": "industry_context",
                        "title": "Independent company corroboration",
                        "url": (
                            "https://www.reuters.com/technology/"
                            f"fresh-{ticker.lower()}/"
                        ),
                        "as_of": stamp,
                        "primary": False,
                    },
                ],
                "public_logic_state": {
                    "architecture": "EVIDENCE_FORMING",
                    "dependency_graph": "EVIDENCE_FORMING",
                    "bottleneck_or_expansion": "EVIDENCE_FORMING",
                    "company_capture": "EVIDENCE_FORMING",
                    "lifecycle": "EVIDENCE_FORMING",
                    "model_inference_confidence": "LIMITED",
                },
                "missing_or_review": [
                    "NON_YAHOO_MARKET_CORROBORATION"
                ],
                "eligible_for_high_confidence_model_inference": False,
            }
        )
        federation_rows.append(
            {"rank": index + 1, "ticker": ticker}
        )
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
    v212 = {
        "product_version": "2.1.2",
        "generated_at": stamp,
        "records": [
            {"rank": index + 1, "ticker": f"T{index:02d}"}
            for index in range(20)
        ],
    }
    v213 = {
        "product_version": "2.1.3",
        "generated_at": stamp,
        "records": [
            {"rank": index + 1, "ticker": f"T{index:02d}"}
            for index in range(20)
        ],
    }
    federation = {
        "schema_version": 1,
        "product_version": "2.1.3",
        "generated_at": stamp,
        "ticker_sources": list(reversed(federation_rows)),
        "gates": {
            "pass": True,
            "unresolved_material_conflict_count": 0,
        },
    }
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
        "methodology_notice": {},
    }
    return envelope, v212, v213, federation, source


def _replace_top20_payload(
    envelope: dict[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    body = core.canonical_json(rows)
    envelope["payloads"]["top20_json"] = body
    envelope["sha256"]["top20_json"] = hashlib.sha256(
        body.encode("utf-8")
    ).hexdigest()


def self_test() -> None:
    envelope, v212, v213, federation, source = _synthetic_documents()
    first = build_bundle(
        envelope, v212, v213, federation, source
    )
    second = build_bundle(
        envelope, v212, v213, federation, source
    )
    assert first["run_id"] == second["run_id"]
    assert first["transaction_id"] != second["transaction_id"]
    assert TRANSACTION_ID_RE.fullmatch(first["transaction_id"])
    strict_audit = json.loads(
        first["payloads"]["source_independence_json"]
    )
    assert (
        strict_audit["freshness_audit"][
            "evidence_qualified_candidate_count"
        ]
        == 20
    )

    limited_envelope = copy.deepcopy(envelope)
    limited_source = copy.deepcopy(source)
    limited_rows = json.loads(
        limited_envelope["payloads"]["top20_json"]
    )
    for name in (
        "demand_wave",
        "chokepoint",
        "pricing_power",
        "replacement_friction",
        "tam_capture",
    ):
        limited_rows[0]["serenity_factors"][name] = 0.0
    _replace_top20_payload(limited_envelope, limited_rows)
    limited_source["records"][0]["sources"] = [
        limited_source["records"][0]["sources"][0],
        {
            "source_id": "nasdaq_symbol_directory_entity_reference",
            "family": "secondary_or_other",
            "domain": "nasdaqtrader.com",
            "claim_type": "legal_entity_reference",
            "title": "Current regulated listing identity",
            "url": (
                "https://www.nasdaqtrader.com/dynamic/"
                "SymDir/otherlisted.txt"
            ),
            "as_of": limited_envelope["generated_at"],
            "primary": False,
        },
    ]
    limited_source["records"][0]["source_metrics"].update(
        {
            "claim_relevant_independent_families": 1,
            "claim_relevant_independent_domains": 1,
            "claim_relevant_primary_sources": 1,
        }
    )
    limited = build_bundle(
        limited_envelope,
        v212,
        v213,
        federation,
        limited_source,
    )
    limited_audit = json.loads(
        limited["payloads"]["source_independence_json"]
    )
    first_record = limited_audit["records"][0]
    assert (
        first_record["publication_evidence_mode"]
        == LIMITED_RESEARCH_CANDIDATE
    )
    assert (
        first_record["eligible_for_high_confidence_model_inference"]
        is False
    )
    assert (
        first_record["freshness_state"][
            "publication_provenance_origin_count"
        ]
        == 2
    )
    assert (
        limited_audit["portfolio"][
            "limited_research_candidate_count"
        ]
        == 1
    )

    single_origin = copy.deepcopy(limited_source)
    single_origin["records"][0]["sources"] = [
        single_origin["records"][0]["sources"][0]
    ]
    try:
        build_bundle(
            limited_envelope,
            v212,
            v213,
            federation,
            single_origin,
        )
    except SerenityEvidenceError as exc:
        assert "one publication origin" in str(exc)
    else:
        raise AssertionError(
            "Single-origin limited candidate was not rejected"
        )

    positive_single = copy.deepcopy(limited_source)
    positive_envelope = copy.deepcopy(envelope)
    positive_single["records"][0]["sources"] = [
        positive_single["records"][0]["sources"][0]
    ]
    try:
        build_bundle(
            positive_envelope,
            v212,
            v213,
            federation,
            positive_single,
        )
    except SerenityEvidenceError as exc:
        assert "positive Serenity advantages require" in str(exc)
    else:
        raise AssertionError(
            "Single-source positive advantage was not rejected"
        )

    stale_market_source = copy.deepcopy(source)
    stale_market_source["records"][0]["market_corroboration"] = {
        "status": "CORROBORATED",
        "independent_provider_count": 1,
        "providers": [
            {
                "provider": "test_market",
                "status": "LIVE",
                "as_of": "2020-01-01",
            }
        ],
    }
    try:
        build_bundle(
            envelope,
            v212,
            v213,
            federation,
            stale_market_source,
        )
    except SerenityEvidenceError as exc:
        assert "stale market" in str(exc)
    else:
        raise AssertionError(
            "Stale LIVE market observation was not rejected"
        )

    print(
        "V213_ACTIVATION_BUNDLE_V2_SELF_TEST = PASS; "
        "evidence_qualified=true; limited_research_candidate=true; "
        "limited_requires_primary_plus_independent_provenance=true; "
        "limited_high_confidence=false; identity_advantage_support=false; "
        "single_origin_rejected=true; "
        "single_source_advantage_rejected=true; "
        "single_source_positive_advantage_rejected=true; "
        "stale_market_rejected=true"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--v21-envelope",
        type=Path,
        default=core.V21_ENVELOPE_PATH,
    )
    parser.add_argument(
        "--v212-report",
        type=Path,
        default=core.V212_REPORT_PATH,
    )
    parser.add_argument(
        "--v213-report",
        type=Path,
        default=core.V213_REPORT_PATH,
    )
    parser.add_argument(
        "--source-federation",
        type=Path,
        default=core.FEDERATION_PATH,
    )
    parser.add_argument(
        "--source-independence",
        type=Path,
        default=core.SOURCE_AUDIT_PATH,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=core.OUTPUT_PATH,
    )
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
    normalized_source = json.loads(
        bundle["payloads"]["source_independence_json"]
    )
    _atomic_json(args.source_independence, normalized_source)
    core.atomic_write(args.output, bundle)
    portfolio = normalized_source["portfolio"]
    print(
        "V213_ACTIVATION_BUNDLE_V2 = PASS; "
        f"run_id={bundle['run_id']}; "
        f"transaction_id={bundle['transaction_id']}; "
        f"payloads={len(bundle['payloads'])}; "
        "federation_order=final_top20; "
        "fresh_multi_source_serenity_gate=true; "
        f"evidence_qualified={portfolio['evidence_qualified_candidate_count']}; "
        f"limited_research_candidates={portfolio['limited_research_candidate_count']}; "
        "single_source_positive_advantage=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        core.ActivationBundleError,
        SerenityEvidenceError,
        OSError,
        ValueError,
    ) as exc:
        print(
            f"V213_ACTIVATION_BUNDLE_V2 = FAIL; {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)
