#!/usr/bin/env python3
"""Validate claim-specific source authority and independence policy."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

# BARRY launches portable CPython in isolated mode. Add only this repository's
# static scripts directory before importing another reviewed source gate. This
# does not permit dynamic adapter/plugin loading.
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from authoritative_source_catalog import (  # noqa: E402
    SourceRecord,
    load_catalog as load_authoritative_catalog,
)

DEFAULT_POLICY = ROOT / "config" / "source-claim-coverage-policy.json"
DEFAULT_CATALOG = ROOT / "config" / "authoritative-source-catalog.json"

KIND_ALIASES: dict[str, set[str]] = {
    "regulator_filing": {"company_filings", "fund_filings", "issuer_filing", "xbrl"},
    "company_registry": {"company_registry", "companies", "legal_entity"},
    "entity_registry": {"entity_resolution", "legal_entity", "legal_entity_reference"},
    "exchange_disclosure": {"issuer_announcements", "issuer_disclosure", "regulated_market"},
    "issuer_ir": {"issuer_announcements", "company_filings"},
    "government_procurement": {"procurement", "contracts", "official_procurement_record"},
    "national_statistics": {"gdp", "labor", "population", "industry", "official_statistical"},
    "central_bank_statistics": {"rates", "banking", "fx", "reserves", "central_bank_policy_record"},
    "intergovernmental_statistics": {"development", "trade", "macro", "official_statistical"},
    "central_bank_policy": {"rates", "monetary_policy", "central_bank_policy_record"},
    "financial_regulator": {"financial_regulation", "enforcement", "regulated_institution_record"},
    "market_regulator": {"regulation", "regulatory", "regulatory_market_record"},
    "government_legal_record": {"enforcement", "regulatory_health_record", "regulatory_record"},
    "regulated_exchange": {"regulated_market", "market", "issuer_announcements"},
    "market_infrastructure": {"clearing", "venues", "regulated_market"},
    "clearing_house": {"clearing", "open_interest", "regulated_market_statistic"},
    "reviewed_public_quote_provider": {"options", "quotes", "public_market_observation"},
    "patent_office": {"patents", "trademarks", "official_ip_record"},
    "research_funding_authority": {"projects", "procurement", "development"},
    "government_science_database": {"technology", "clinical_trials", "cybersecurity"},
    "energy_regulator": {"energy", "regulation", "regulatory_market_record"},
    "grid_operator": {"grid", "electricity", "generation"},
    "official_energy_statistics": {"energy", "power", "oil", "natural_gas"},
    "climate_authority": {"climate", "weather", "emissions", "official_observation"},
}


class ClaimCoverageError(ValueError):
    """Raised when claim coverage policy is malformed."""


def _source_document(source: SourceRecord) -> dict[str, Any]:
    value = asdict(source)
    for key in ("regions", "jurisdictions", "topics", "claim_types", "base_urls"):
        value[key] = list(value[key])
    value["gates"] = dict(source.gates)
    value["rate_limit"] = dict(source.rate_limit)
    return value


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ClaimCoverageError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ClaimCoverageError(f"Expected an object in {path}")
    if "fragment_paths" in value and "sources" not in value:
        try:
            _manifest, records, warnings = load_authoritative_catalog(path)
        except (FileNotFoundError, ValueError) as exc:
            raise ClaimCoverageError(str(exc)) from exc
        return {
            "sources": [_source_document(source) for source in records],
            "warnings": list(warnings),
        }
    return value


def _catalog_terms(sources: list[Any]) -> set[str]:
    terms: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        for field in ("topics", "claim_types"):
            values = source.get(field)
            if isinstance(values, (list, tuple)):
                terms.update(str(value).strip().casefold() for value in values if str(value).strip())
        for field in ("evidence_role", "transport", "adapter_status"):
            value = str(source.get(field) or "").strip().casefold()
            if value:
                terms.add(value)
        authority = str(source.get("authority") or "").strip().casefold()
        if authority:
            terms.update(token for token in authority.replace("/", " ").replace("-", " ").split() if token)
    return terms


def _kind_matches(kind: str, terms: set[str]) -> bool:
    normalized = kind.casefold()
    aliases = KIND_ALIASES.get(normalized, {normalized})
    return any(
        alias == term or alias in term or term in alias
        for alias in aliases
        for term in terms
        if alias and term
    )


def audit_claim_policy(
    policy: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    findings: list[str] = []
    expected_top = {
        "schema_version",
        "automatic_source_activation",
        "model_may_override_authority",
        "editorial_may_be_primary_evidence",
        "material_claim_requires_scalar_evidence",
        "independence_group_deduplication",
        "same_content_hash_counts_once",
        "conflicting_material_values_fail_closed",
        "claim_families",
    }
    unknown = sorted(set(policy).difference(expected_top))
    if unknown:
        findings.append("claim policy contains unknown fields: " + ", ".join(unknown))
    if policy.get("schema_version") != 1:
        findings.append("claim policy schema_version must be 1")
    for key in (
        "automatic_source_activation",
        "model_may_override_authority",
        "editorial_may_be_primary_evidence",
    ):
        if policy.get(key) is not False:
            findings.append(f"claim policy requires {key}=false")
    for key in (
        "material_claim_requires_scalar_evidence",
        "independence_group_deduplication",
        "same_content_hash_counts_once",
        "conflicting_material_values_fail_closed",
    ):
        if policy.get(key) is not True:
            findings.append(f"claim policy requires {key}=true")

    sources = catalog.get("sources")
    if not isinstance(sources, list):
        raise ClaimCoverageError("authoritative source catalog lacks assembled sources")
    catalog_terms = _catalog_terms(sources)

    families = policy.get("claim_families")
    if not isinstance(families, dict) or not families:
        raise ClaimCoverageError("claim_families must be a non-empty object")
    required_family_fields = {
        "minimum_primary_sources",
        "minimum_independent_groups",
        "preferred_source_kinds",
        "required_fields",
    }
    broker_forbidden_families: list[str] = []
    matched_kinds: set[str] = set()
    for name, value in families.items():
        label = f"claim_families.{name}"
        if not isinstance(value, dict):
            findings.append(f"{label} must be an object")
            continue
        allowed = required_family_fields | {"broker_or_account_derived_evidence_allowed"}
        unknown_fields = sorted(set(value).difference(allowed))
        missing = sorted(required_family_fields.difference(value))
        if unknown_fields:
            findings.append(f"{label} contains unknown fields: {', '.join(unknown_fields)}")
        if missing:
            findings.append(f"{label} is missing fields: {', '.join(missing)}")
        primary = value.get("minimum_primary_sources")
        independent = value.get("minimum_independent_groups")
        if not isinstance(primary, int) or isinstance(primary, bool) or primary < 1:
            findings.append(f"{label}.minimum_primary_sources must be at least 1")
        if not isinstance(independent, int) or isinstance(independent, bool) or independent < 1:
            findings.append(f"{label}.minimum_independent_groups must be at least 1")
        kinds = value.get("preferred_source_kinds")
        fields = value.get("required_fields")
        if not isinstance(kinds, list) or not kinds or not all(
            isinstance(item, str) and item.strip() for item in kinds
        ):
            findings.append(f"{label}.preferred_source_kinds must be a non-empty string array")
            kinds = []
        if not isinstance(fields, list) or not fields or not all(
            isinstance(item, str) and item.strip() for item in fields
        ):
            findings.append(f"{label}.required_fields must be a non-empty string array")
        local_matches = {kind for kind in kinds if _kind_matches(kind, catalog_terms)}
        matched_kinds.update(local_matches)
        if kinds and len(local_matches) < max(1, (len(kinds) + 1) // 2):
            findings.append(f"{label} lacks sufficient matching catalog source kinds/topics")
        if value.get("broker_or_account_derived_evidence_allowed") is False:
            broker_forbidden_families.append(str(name))
        elif "option" in str(name).casefold():
            findings.append(f"{label} must explicitly forbid broker/account-derived public evidence")

    required_families = {
        "issuer_identity",
        "issuer_financial_statement",
        "macro_indicator",
        "monetary_policy",
        "regulatory_or_enforcement_event",
        "market_or_exchange_event",
        "public_option_quote",
        "technology_patent_or_grant",
        "energy_grid_or_climate",
    }
    missing_families = sorted(required_families.difference(families))
    if missing_families:
        findings.append("required claim families missing: " + ", ".join(missing_families))

    summary = {
        "claim_family_count": len(families),
        "catalog_source_count": len(sources),
        "catalog_term_count": len(catalog_terms),
        "matched_preferred_kind_count": len(matched_kinds),
        "broker_forbidden_families": sorted(broker_forbidden_families),
        "automatic_source_activation": False,
        "editorial_primary_evidence": False,
        "conflict_behavior": "fail_closed",
    }
    return findings, summary


def main() -> int:
    try:
        findings, summary = audit_claim_policy(
            load_object(DEFAULT_POLICY),
            load_object(DEFAULT_CATALOG),
        )
    except (FileNotFoundError, ClaimCoverageError, OSError) as exc:
        print(f"SOURCE CLAIM COVERAGE GATE FAILED\n- {exc}")
        return 1
    if findings:
        print("SOURCE CLAIM COVERAGE GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("SOURCE CLAIM COVERAGE GATE PASSED")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
