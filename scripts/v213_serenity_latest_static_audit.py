#!/usr/bin/env python3
"""Static release audit for the final Serenity latest multi-source runtime.

The stable v3 source-gate entrypoint delegates to the authoritative v4
implementation.  This audit therefore checks both the compatibility wrapper and
the implementation that actually enforces market quality, rather than requiring
implementation markers to be duplicated into a thin wrapper.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def document(path: str):
    return json.loads(text(path))


def normalize(value: str) -> str:
    """Case-fold and collapse layout whitespace without weakening semantics."""
    return " ".join(value.casefold().split())


def require(source: str, markers: tuple[str, ...], failures: list[str]) -> None:
    value = normalize(text(source))
    for marker in markers:
        if normalize(marker) not in value:
            failures.append(f"{source} missing: {marker}")


def main() -> int:
    failures: list[str] = []
    policy = document("config/v213-serenity-latest-multisource-policy-v5.json")
    lineage = document("config/v213-serenity-methodology-lineage-v1.json")
    if policy.get("schema_version") != 5:
        failures.append("latest multi-source policy schema is not v5")
    if (
        policy.get("official_serenity_formula_claimed") is not False
        or policy.get("official_serenity_score_claimed") is not False
        or policy.get("private_method_reproduced") is not False
    ):
        failures.append("official/private Serenity non-claim boundary failed")
    per = policy.get("per_ticker_minimums", {})
    if (
        int(per.get("claim_relevant_independent_families", 0)) < 2
        or int(per.get("claim_relevant_independent_domains", 0)) < 2
        or int(per.get("claim_relevant_primary_sources", 0)) < 1
        or float(per.get("claim_dated_evidence_ratio", 0)) < 0.8
    ):
        failures.append("per-ticker claim-source policy is too weak")
    market = policy.get("market_corroboration", {})
    if (
        market.get("yahoo_role") != "compatibility_calculation_only_not_truth_anchor"
        or int(market.get("minimum_independent_providers_for_high_confidence", 0)) < 2
        or market.get("same_metric_basis_required_for_pairwise_comparison") is not True
        or market.get("source_values_must_not_be_averaged") is not True
    ):
        failures.append("market corroboration policy is too weak")
    fresh = policy.get("freshness_days", {})
    if (
        float(fresh.get("snapshot", 99)) > 0.084
        or float(fresh.get("market_high_confidence", 99)) > 4
        or float(fresh.get("market_absolute_maximum", 99)) > 7
        or float(fresh.get("market_provider_max_gap", 99)) > 3
    ):
        failures.append("latest-data limits are too weak")
    repos = {
        row.get("repository"): row
        for row in lineage.get("reviewed_projects", [])
        if isinstance(row, dict)
    }
    for repo in (
        "yan-labs/serenity-aleabitoreddit",
        "muxuuu/serenity-skill",
        "quantskills/skill-serenity-research-model",
    ):
        if repo not in repos:
            failures.append(f"methodology lineage missing {repo}")
    if (
        repos.get("quantskills/skill-serenity-research-model", {}).get("implementation")
        != "conceptual_patterns_only_no_gpl_code_copied"
    ):
        failures.append("GPL conceptual-only boundary missing")

    require(
        "scripts/v213_refresh_serenity_public_sources.py",
        (
            "latest_available_verified",
            "retrieval_time_is_not_publication_time",
            "company_fact_authority",
            "raw_posts_redistributed",
        ),
        failures,
    )
    require(
        "scripts/v213_serenity_latest_multisource_audit.py",
        (
            "minimum_independent_market_providers_for_high_confidence",
            "TWO_COMPARABLE_NON_YAHOO_MARKET_PROVIDERS",
            "same_metric_basis_required_for_market_comparison",
            "yahoo_is_not_truth_anchor",
            "factor_findings",
            "severe thesis-killer",
        ),
        failures,
    )
    require(
        "scripts/v213_tam_capture_claim_guard.py",
        (
            "tam_capture_zeroed_without_current_revenue_or_order_evidence",
            "Market returns, sector labels and broad TAM narratives cannot support company TAM",
        ),
        failures,
    )

    # v2 owns the provider/freshness layer.  Matching is case-insensitive so a
    # docstring capitalization change cannot create a false release failure.
    require(
        "scripts/v213_source_independence_gate_v2.py",
        (
            "MARKET_OBSERVATION_MAX_AS_OF_AGE_DAYS = 7",
            "stale_market_data_as_of",
            "market data remains corroboration",
            "never proves a company fact",
        ),
        failures,
    )
    # v3 is intentionally a stable compatibility entrypoint; v4 is the reviewed
    # implementation.  Audit delegation and implementation semantics separately.
    require(
        "scripts/v213_source_independence_gate_v3.py",
        (
            "v213_source_independence_gate_v4.py",
            "V4_PATH",
            "v4.gate.main()",
        ),
        failures,
    )
    require(
        "scripts/v213_source_independence_gate_v4.py",
        (
            "market_corroboration_required_for_high_confidence_model_inference",
            "uncorroborated_valuation_factor_max",
            "source_conflicts_are_not_averaged",
            "MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS = 2",
            "MARKET_HARD_MAX_AGE_DAYS = 7.0",
            "MARKET_HIGH_CONFIDENCE_FRESHEST_MAX_AGE_DAYS = 4.0",
            "MARKET_COMPARABLE_PROVIDER_MAX_LAG_DAYS = 3.0",
        ),
        failures,
    )
    require(
        "activate-v213-seven-field-schedule-core.ps1",
        (
            "node_modules\\wrangler\\bin\\wrangler.js",
            "Get-BalancedJsonDocumentEnd",
            "multiple deployment JSON documents",
            "V213_ACTIVATION_POINTER_ROLLBACK = PASS",
            "V213_ACTIVATION_WORKER_ROLLBACK = PASS",
        ),
        failures,
    )
    require(
        "activate-v213-seven-field-schedule-serenity-latest.ps1",
        (
            "V213_SERENITY_LATEST_ACTIVATION_PREFLIGHT",
            "v213_refresh_serenity_public_sources.py",
            "v213_serenity_latest_multisource_audit.py",
            "activate-v213-seven-field-schedule-core.ps1",
        ),
        failures,
    )
    require(
        "install-v213-serenity-latest-runtime.ps1",
        (
            "run-v213-local-serenity-latest.ps1",
            "activate-v213-seven-field-schedule-serenity-latest.ps1",
            "per_ticker_claim_source_families_minimum = 2",
            "market_providers_for_high_confidence = 2",
        ),
        failures,
    )

    operationalization = text("scripts/v213_apply_diversified_operationalization.py")
    for marker in (
        '"demand_wave": 0.0',
        '"chokepoint": 0.0',
        '"pricing_power": 0.0',
        '"replacement_friction": 0.0',
        "min(old_valuation, 3.75)",
    ):
        if marker not in operationalization:
            failures.append(f"proxy-positive factor guard missing: {marker}")

    refresh = text("run-v213-local-serenity-latest.ps1")
    pipeline_start = refresh.find(
        "Stage 1 'Verified Python and latest public Serenity source metadata'"
    )
    if pipeline_start < 0:
        failures.append("final refresh pipeline start marker is missing")
    else:
        # Search sequentially only inside the live pipeline.  The same scripts
        # legitimately appear earlier in the SelfTest block and the final audit
        # intentionally runs twice, before and after the TAM guard.
        ordered = (
            "v213_refresh_serenity_public_sources.py",
            "v213_v21_progress_runner.py",
            "v213_v212_progress_runner.py",
            "reconcile_v213_order_evidence.py",
            "build_v213_scheduled_top20_report.py",
            "v213_source_federation.py",
            "v213_source_federation_gate.py",
            "v213_apply_diversified_operationalization.py",
            "v213_source_independence_gate_v3.py",
            "v213_serenity_latest_multisource_audit.py",
            "v213_tam_capture_claim_guard.py",
            "v213_serenity_latest_multisource_audit.py",
            "v213_build_v21_public_snapshot.py",
            "build_v213_activation_bundle_v2.py",
        )
        cursor = pipeline_start
        for marker in ordered:
            position = refresh.find(marker, cursor + 1)
            if position < 0:
                failures.append(f"final refresh pipeline missing or out of order: {marker}")
                break
            cursor = position
    if "scripts\\build_v21_public_snapshot.py" in refresh:
        failures.append("legacy snapshot builder remains in final refresh")

    if failures:
        print("V213_SERENITY_LATEST_STATIC_AUDIT = FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(
        "V213_SERENITY_LATEST_STATIC_AUDIT = PASS; "
        "latest_available=true; per_ticker_sources=2; market_providers=2; "
        "same_basis=true; yahoo_truth_anchor=false; "
        "v3_entrypoint=v4_authoritative; live_pipeline_order=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
