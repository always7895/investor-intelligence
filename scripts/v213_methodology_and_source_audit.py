#!/usr/bin/env python3
"""Fail-closed audit for v2.1.3 methodology and source-diversity contracts."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "config" / "v213-serenity-evidence-standard-v3.json"
FEDERATION = ROOT / "config" / "v213-source-federation-policy.json"
ACTIVATION = ROOT / "config" / "v21-source-activation.json"
CATALOG = ROOT / "config" / "authoritative-source-catalog.json"
SCORER = ROOT / "scripts" / "v213_apply_diversified_operationalization.py"
FEDERATOR = ROOT / "scripts" / "v213_source_federation.py"
GATEWAY = ROOT / "scripts" / "v213_local_llm_gateway.py"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def contains_all(text: str, *tokens: str) -> bool:
    folded = text.casefold()
    return all(token.casefold() in folded for token in tokens)


def contains_any(text: str, *tokens: str) -> bool:
    folded = text.casefold()
    return any(token.casefold() in folded for token in tokens)


def main() -> int:
    standard = load(STANDARD)
    federation = load(FEDERATION)
    activation = load(ACTIVATION)
    catalog = load(CATALOG)
    scorer = SCORER.read_text(encoding="utf-8")
    federator = FEDERATOR.read_text(encoding="utf-8")
    gateway = GATEWAY.read_text(encoding="utf-8")
    findings: list[str] = []

    if standard.get("schema_version") != 3:
        findings.append("Serenity evidence standard schema must be 3")
    if standard.get("official_formula_claimed") is not False:
        findings.append("Official Serenity formula must not be claimed")
    if standard.get("private_process_reproduction_claimed") is not False:
        findings.append("Private process reproduction must not be claimed")
    independence = standard.get("publisher_independence", {})
    for key in (
        "different_urls_same_publisher_count_once",
        "different_issuers_hosted_on_sec_may_be_independent_publishers",
        "counterparty_filing_may_corroborate_focal_issuer",
        "syndicated_or_same_content_hash_counts_once",
    ):
        if independence.get(key) is not True:
            findings.append(f"Publisher independence rule missing: {key}")
    claims = standard.get("claim_thresholds", {})
    dependency = claims.get("dependency_or_bottleneck", {})
    if dependency.get("minimum_primary_or_corroborating_families", 0) < 2:
        findings.append("Bottleneck requires at least two independent source families")
    if dependency.get("graph_edge_touching_focal_company_required") is not True:
        findings.append("Bottleneck requires an evidence-bound focal graph edge")
    killer = claims.get("severe_thesis_killer", {})
    if killer.get("one_high_quality_primary_source_may_break_thesis") is not True:
        findings.append("Severe high-quality primary killer must be asymmetric")

    required_sources = federation.get("required_live_sources", {})
    required_ids = {
        "sec_edgar", "nasdaq_symbol_directory", "world_bank_indicators",
        "bls_public_data", "ecb_sdmx",
    }
    if not required_ids.issubset(required_sources):
        findings.append("Live federation does not include all required independent official families")
    if not {"gleif_lei", "alpha_vantage", "yahoo_finance_public_unofficial"}.issubset(required_sources):
        findings.append("Optional identity and market-observation families are not declared")
    if federation.get("catalog_source_count_is_not_live_use") is not True:
        findings.append("Catalog/live-use distinction missing")
    if federation.get("yahoo_is_authoritative") is not False:
        findings.append("Yahoo must not be authoritative")
    if federation.get("minimum_global_successful_families", 0) < 5:
        findings.append("Live source family minimum must be at least five")
    if federation.get("minimum_per_ticker_independent_families", 0) < 2:
        findings.append("Per-ticker source family minimum must be at least two")
    if federation.get("maximum_single_family_evidence_share", 1) > 0.65:
        findings.append("Single-family evidence concentration cap is too weak")

    selected = activation.get("selected_sources", {})
    expected = required_ids | {"gleif_lei"}
    if set(selected) != expected:
        findings.append("Source activation does not exactly match the reviewed federation set")
    yahoo = activation.get("discovery_only_sources", {}).get("yahoo_finance_public_unofficial", {})
    if yahoo.get("authoritative") is not False:
        findings.append("Yahoo discovery source boundary is not explicit")
    alpha = activation.get("discovery_only_sources", {}).get("alpha_vantage", {})
    if alpha.get("authoritative") is not False or alpha.get("runtime_enabled") is not False:
        findings.append("Alpha Vantage must remain optional, non-authoritative and key-gated")
    if catalog.get("catalog_source_count_snapshot") != 101:
        findings.append("Reviewed catalog snapshot must contain 101 sources")
    if "config/authoritative-sources/v213-runtime-extensions.json" not in catalog.get("fragment_paths", []):
        findings.append("v2.1.3 catalog extension fragment missing")

    required_scorer_tokens = (
        '"chokepoint": 0.0',
        '"replacement_friction": 0.0',
        "min(old_valuation, 3.75)",
        "issuer_financial_claim_has_single_primary_family",
        "SCORING_VERSION = \"system-operationalization-v2.1.3-diversified\"",
        "CATALOG_COUNT = 101",
    )
    for token in required_scorer_tokens:
        if token not in scorer:
            findings.append(f"Diversified scorer guard missing: {token}")
    for token in (
        "V213_SOURCE_FEDERATION_SELF_TEST",
        "nasdaq_symbol_directory",
        "bls_public_data",
        "ecb_sdmx",
        "gleif_lei",
        "SINGLE_PROVIDER_DEGRADED",
        "catalog_source_count_is_not_live_use",
    ):
        if token not in federator:
            findings.append(f"Source federation implementation missing: {token}")

    # Audit methodology concepts rather than brittle singular/plural wording.
    # Every concept below requires the gateway to instruct the model explicitly;
    # equivalent wording is accepted only when it preserves the same fail-closed
    # semantic boundary.
    if not contains_any(
        gateway,
        "catalog is an inventory",
        "this inventory cannot upgrade a claim",
        "catalog_source_count_is_not_live_use",
    ):
        findings.append("Local-model methodology directive missing: catalog inventory/live-use boundary")
    if not contains_all(
        gateway,
        "count independent publisher families",
        "same corporate source family",
        "do not become independent corroboration by repetition",
    ):
        findings.append("Local-model methodology directive missing: publisher-family deduplication")
    if not contains_all(
        gateway,
        "Yahoo/yfinance remains a compatibility adjusted-close calculation provider",
        "Stooq, Nasdaq, and optional Alpha Vantage independently corroborate the market path",
        "Market data does not prove a bottleneck or company-specific operating fact",
    ):
        findings.append("Local-model methodology directive missing: single-market-family limitation")
    if not contains_all(
        gateway,
        "A severe, evidence-bound primary thesis killer may override positive evidence",
        "asymmetrically",
    ):
        findings.append("Local-model methodology directive missing: severe asymmetric thesis-killer rule")

    if findings:
        print("V213_METHODOLOGY_AND_SOURCE_AUDIT = FAIL")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("V213_METHODOLOGY_AND_SOURCE_AUDIT = PASS; catalog=101; required_live_families=5; per_ticker_minimum=2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
