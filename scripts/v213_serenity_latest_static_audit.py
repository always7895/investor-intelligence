#!/usr/bin/env python3
"""Static fail-closed audit for the final Serenity-latest delivery."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "v213-serenity-latest-multisource-policy-v5.json"
LINEAGE = ROOT / "config" / "v213-serenity-methodology-lineage-v1.json"
REFRESH = ROOT / "run-v213-local-serenity-latest.ps1"
ACTIVATION = ROOT / "activate-v213-seven-field-schedule-serenity-latest.ps1"
INSTALLER = ROOT / "install-v213-serenity-latest-runtime.ps1"
AUDIT = ROOT / "scripts" / "v213_serenity_latest_multisource_audit.py"
PUBLIC_SOURCE = ROOT / "scripts" / "v213_refresh_serenity_public_sources.py"
TAM_GUARD = ROOT / "scripts" / "v213_tam_capture_claim_guard.py"
OPERATIONALIZATION = ROOT / "scripts" / "v213_apply_diversified_operationalization.py"
SOURCE_V2 = ROOT / "scripts" / "v213_source_independence_gate_v2.py"
SOURCE_V3 = ROOT / "scripts" / "v213_source_independence_gate_v3.py"
ACTIVATION_CORE = ROOT / "activate-v213-seven-field-schedule-core.ps1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def main() -> int:
    failures: list[str] = []
    policy = json.loads(read(POLICY))
    lineage = json.loads(read(LINEAGE))
    texts = {path.name: read(path) for path in (REFRESH, ACTIVATION, INSTALLER, AUDIT, PUBLIC_SOURCE, TAM_GUARD, OPERATIONALIZATION, SOURCE_V2, SOURCE_V3, ACTIVATION_CORE)}

    if policy.get("schema_version") != 5 or policy.get("official_serenity_formula_claimed") is not False or policy.get("private_method_reproduced") is not False:
        failures.append("Serenity v5 non-claim boundary is invalid")
    per = policy.get("per_ticker_minimums", {})
    if int(per.get("claim_relevant_independent_families", 0)) < 2 or int(per.get("claim_relevant_independent_domains", 0)) < 2 or int(per.get("claim_relevant_primary_sources", 0)) < 1:
        failures.append("Per-ticker claim-source minimums are too weak")
    market = policy.get("market_corroboration", {})
    if market.get("yahoo_role") != "compatibility_calculation_only_not_truth_anchor":
        failures.append("Yahoo truth-anchor prohibition is missing")
    if int(market.get("minimum_independent_providers_for_high_confidence", 0)) < 2:
        failures.append("High-confidence market minimum is below two providers")
    if market.get("same_metric_basis_required_for_pairwise_comparison") is not True or market.get("source_values_must_not_be_averaged") is not True:
        failures.append("Market comparison/anti-averaging contract is missing")
    freshness = policy.get("freshness_days", {})
    if float(freshness.get("market_high_confidence", 99)) > 4 or float(freshness.get("market_absolute_maximum", 99)) > 7 or float(freshness.get("snapshot", 99)) > 0.084:
        failures.append("Freshness limits are weaker than reviewed standard")

    repos = {row.get("repository"): row for row in lineage.get("reviewed_projects", []) if isinstance(row, dict)}
    for repo in ("yan-labs/serenity-aleabitoreddit", "muxuuu/serenity-skill", "quantskills/skill-serenity-research-model"):
        if repo not in repos:
            failures.append(f"Methodology lineage missing: {repo}")
    if repos.get("quantskills/skill-serenity-research-model", {}).get("implementation") != "conceptual_patterns_only_no_gpl_code_copied":
        failures.append("GPL conceptual-only boundary is missing")

    required_by_file = {
        REFRESH.name: (
            "v213_refresh_serenity_public_sources.py", "v213_serenity_latest_multisource_audit.py",
            "v213_tam_capture_claim_guard.py", "v213_source_independence_gate_v3.py",
            "v213_build_v21_public_snapshot.py", "build_v213_activation_bundle_v2.py",
        ),
        ACTIVATION.name: (
            "V213_SERENITY_LATEST_ACTIVATION_PREFLIGHT", "v213_refresh_serenity_public_sources.py",
            "v213_serenity_latest_multisource_audit.py", "activate-v213-seven-field-schedule-core.ps1",
        ),
        AUDIT.name: (
            "minimum_independent_providers_for_high_confidence", "same_metric_basis_required_for_pairwise_comparison",
            "TWO_COMPARABLE_NON_YAHOO_MARKET_PROVIDERS", "severe thesis-killer", "factor_findings",
        ),
        PUBLIC_SOURCE.name: (
            "latest_available_verified", "retrieval_time_is_not_publication_time",
            "company_fact_authority", "raw_posts_redistributed",
        ),
        TAM_GUARD.name: ("tam_capture_zeroed_without_current_revenue_or_order_evidence",),
        SOURCE_V2.name: ("MARKET_OBSERVATION_MAX_AS_OF_AGE_DAYS = 7", "stale_market_data_as_of"),
        SOURCE_V3.name: ("market_corroboration_required_for_high_confidence_model_inference", "uncorroborated_valuation_factor_max"),
        ACTIVATION_CORE.name: ("node_modules\\wrangler\\bin\\wrangler.js", "Get-BalancedJsonDocumentEnd", "multiple deployment JSON documents", "V213_ACTIVATION_POINTER_ROLLBACK = PASS", "V213_ACTIVATION_WORKER_ROLLBACK = PASS"),
    }
    for filename, markers in required_by_file.items():
        text = texts[filename]
        for marker in markers:
            if marker not in text:
                failures.append(f"{filename} missing contract marker: {marker}")

    operationalization = texts[OPERATIONALIZATION.name]
    for marker in ('"demand_wave": 0.0', '"chokepoint": 0.0', '"pricing_power": 0.0', '"replacement_friction": 0.0', 'min(old_valuation, 3.75)'):
        if marker not in operationalization:
            failures.append(f"Operationalization proxy guard missing: {marker}")
    if re.search(r"(?i)(keyword|sector|gross_margin).{0,80}(chokepoint|replacement_friction).{0,30}\+=", operationalization):
        failures.append("Operationalization appears to recreate a prohibited proxy-positive factor")

    refresh = texts[REFRESH.name]
    ordered = (
        "v213_v21_progress_runner.py", "v213_v212_progress_runner.py", "reconcile_v213_order_evidence.py",
        "build_v213_scheduled_top20_report.py", "v213_source_federation.py", "v213_source_federation_gate.py",
        "v213_apply_diversified_operationalization.py", "v213_source_independence_gate_v3.py",
        "v213_serenity_latest_multisource_audit.py", "v213_tam_capture_claim_guard.py",
        "v213_build_v21_public_snapshot.py", "build_v213_activation_bundle_v2.py",
    )
    positions = [refresh.find(item) for item in ordered]
    if any(position < 0 for position in positions) or any(left >= right for left, right in zip(positions, positions[1:])):
        failures.append("Final refresh pipeline order is invalid")
    if "scripts\\build_v21_public_snapshot.py" in refresh:
        failures.append("Legacy snapshot builder remains in final refresh path")

    if failures:
        print("V213_SERENITY_LATEST_STATIC_AUDIT = FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("V213_SERENITY_LATEST_STATIC_AUDIT = PASS; per_ticker_sources=2; market_providers=2; market_max_age=7d; yahoo_truth_anchor=false; severe_killers_override=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
