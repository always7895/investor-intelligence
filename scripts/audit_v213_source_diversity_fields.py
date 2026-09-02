#!/usr/bin/env python3
"""Fail-closed audits for v2.1.3 source-diversity labels and preselection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_v21_progress_runner as preselection

ROOT = SCRIPTS.parent
LABELS = ROOT / "config" / "v213-source-diversity-field-labels.zh-en.json"
REQUIRED = {
    "status", "offline_self_test", "policy_version", "portfolio", "violations",
    "methodology_notice", "ticker_count", "independent_source_families",
    "independent_domains", "source_families", "source_domains",
    "non_yahoo_market_coverage_ratio", "primary_or_official_coverage_ratio",
    "maximum_single_family_share", "market_conflict_ticker_count",
    "high_confidence_model_inference_eligible_count", "fred_macro_status",
    "evidence_independence_score", "source_metrics", "unique_independent_units",
    "primary_or_official_sources", "dated_evidence_ratio", "families", "domains",
    "market_corroboration", "calculation_provider", "calculation_provider_role",
    "independent_provider_count", "providers", "provider", "family", "observed_at",
    "cache_age_seconds", "long_term_conflict", "short_term_conflict",
    "public_logic_state", "missing_or_review",
    "eligible_for_high_confidence_model_inference", "sensitive_claim_present",
    "serenity_source_view", "architecture", "dependency_graph",
    "bottleneck_or_expansion", "company_capture", "valuation_expectations",
    "thesis_killers", "lifecycle", "model_inference_confidence",
    "system_operationalization_is_official_serenity_score",
    "private_method_reproduction_claimed", "official_serenity_formula",
    "official_serenity_score", "single_source_inference_allowed",
    "source_diversity_is_not_truth_by_itself", "conflicts_require_review", "primary",
}


def audit_safe_preselection_wrapper() -> None:
    """Exercise the exact monkeypatch pattern used by the live Top20 runner."""
    policy, _activation = preselection.validate_v213_policy()
    candidate, metrics, evidence = preselection.engine.synthetic_candidates()[0]
    original_score = preselection.engine.score_candidate
    try:
        preselection.engine.score_candidate = preselection.safe_preselection_score
        result = preselection.engine.score_candidate(candidate, metrics, evidence, policy)
    except RecursionError as exc:
        raise SystemExit(
            "SOURCE_DIVERSITY_PRESELECTION_AUDIT=FAIL; recursive scorer monkeypatch"
        ) from exc
    finally:
        preselection.engine.score_candidate = original_score

    factors = result.get("serenity_factors")
    if result.get("scoring_version") != preselection.PRESELECTION_VERSION or not isinstance(factors, dict):
        raise SystemExit(
            "SOURCE_DIVERSITY_PRESELECTION_AUDIT=FAIL; safe preselection contract missing"
        )
    forbidden_positive = (
        "demand_wave",
        "chokepoint",
        "pricing_power",
        "replacement_friction",
    )
    if any(float(factors.get(name) or 0.0) != 0.0 for name in forbidden_positive):
        raise SystemExit(
            "SOURCE_DIVERSITY_PRESELECTION_AUDIT=FAIL; unsupported thesis factor became positive"
        )
    if float(factors.get("valuation_expectations") or 0.0) > 3.75:
        raise SystemExit(
            "SOURCE_DIVERSITY_PRESELECTION_AUDIT=FAIL; single-market valuation cap exceeded"
        )


def main() -> int:
    document = json.loads(LABELS.read_text(encoding="utf-8-sig"))
    fields = document.get("fields")
    if not isinstance(fields, dict):
        raise SystemExit("SOURCE_DIVERSITY_BILINGUAL_AUDIT=FAIL; fields object missing")
    missing = sorted(REQUIRED - set(fields))
    invalid = []
    for key in sorted(REQUIRED & set(fields)):
        value = fields[key]
        if not isinstance(value, dict) or not str(value.get("zh-TW") or "").strip() or not str(value.get("en") or "").strip():
            invalid.append(key)
    if missing or invalid:
        raise SystemExit(
            "SOURCE_DIVERSITY_BILINGUAL_AUDIT=FAIL; missing=" + ",".join(missing) +
            "; invalid=" + ",".join(invalid)
        )
    audit_safe_preselection_wrapper()
    print(
        f"V213_SOURCE_DIVERSITY_BILINGUAL_AUDIT = PASS; fields={len(REQUIRED)}; "
        "safe_preselection_monkeypatch=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
