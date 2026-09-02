#!/usr/bin/env python3
"""v2.1.3 claim-source gate with explicit market-quality degradation.

This wrapper preserves every blocking company/claim evidence rule from the v2
provider implementation.  It changes exactly one policy boundary: temporary
unavailability of independent free market-price endpoints is disclosed as a
quality degradation rather than pretending otherwise or erasing valid SEC,
issuer, regulated-identity, and official-context evidence.

Non-Yahoo market corroboration remains mandatory for high-confidence model
inference and for valuation confidence above the 3.75/15 single-provider cap.
Market observations are never averaged into the published return and never prove
a company fact, order, dependency, bottleneck, pricing power, or thesis state.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
V2_PATH = SCRIPT_DIR / "v213_source_independence_gate_v2.py"
DEGRADATION_POLICY_PATH = (
    ROOT / "config" / "v213-market-corroboration-degradation-policy.json"
)
MARKET_DEGRADATION_CODE = "INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE"
ROW_MARKET_MISSING_CODE = "NON_YAHOO_MARKET_CORROBORATION"
PORTFOLIO_FAILURE_CODE = "PORTFOLIO_SOURCE_POLICY"


def _load_module() -> ModuleType:
    if not V2_PATH.is_file():
        raise RuntimeError(f"Missing v2 provider wrapper: {V2_PATH}")
    spec = importlib.util.spec_from_file_location(
        "investor_intelligence_v213_source_gate_v2",
        V2_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load v2 provider wrapper: {V2_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


provider = _load_module()
gate = provider.gate


def _read_policy(path: Path = DEGRADATION_POLICY_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise gate.SourceGateError(
            f"Unable to read market corroboration degradation policy: {path}"
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("product_version") != "2.1.3"
        or value.get("degradation_code") != MARKET_DEGRADATION_CODE
        or value.get("market_corroboration_unavailable_is_global_blocker") is not False
        or value.get(
            "market_corroboration_required_for_high_confidence_model_inference"
        )
        is not True
        or value.get("market_data_never_proves_company_claim") is not True
        or value.get("market_data_never_proves_dependency_or_bottleneck") is not True
        or value.get("source_conflicts_are_not_averaged") is not True
    ):
        raise gate.SourceGateError(
            "Market corroboration degradation policy does not preserve the reviewed boundary"
        )
    return value


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _row_individually_high_eligible(
    record: Mapping[str, Any],
    core_policy: Mapping[str, Any],
    macro_available: bool,
) -> bool:
    metrics = record.get("source_metrics")
    market = record.get("market_corroboration")
    missing = {
        str(value)
        for value in record.get("missing_or_review", [])
        if str(value)
    }
    if not isinstance(metrics, Mapping) or not isinstance(market, Mapping):
        return False
    minimums = (
        core_policy.get("minimums")
        if isinstance(core_policy.get("minimums"), Mapping)
        else {}
    )
    return (
        _integer(metrics.get("claim_relevant_independent_families"))
        >= _integer(minimums.get("high_confidence_claim_independent_families", 2))
        and _integer(metrics.get("claim_relevant_independent_domains"))
        >= _integer(minimums.get("high_confidence_claim_independent_domains", 2))
        and _integer(metrics.get("claim_relevant_primary_sources"))
        >= _integer(minimums.get("high_confidence_claim_primary_sources", 1))
        and _number(metrics.get("claim_dated_evidence_ratio"))
        >= _number(minimums.get("high_confidence_claim_dated_ratio", 0.8))
        and _integer(market.get("independent_provider_count")) >= 1
        and str(market.get("status") or "") == "CORROBORATED"
        and "MARKET_SOURCE_CONFLICT_REVIEW" not in missing
        and "SOURCE_FAMILY_CONCENTRATION" not in missing
        and "CLAIM_SOURCE_FAMILY_CONCENTRATION" not in missing
        and macro_available
    )


def apply_market_quality_policy(
    result: dict[str, Any],
    core_policy: Mapping[str, Any],
    degradation_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Reclassify only the reviewed market-availability violation.

    Company/claim family, domain, primary-source, concentration, and material
    conflict violations remain blocking.  No provider status or coverage ratio is
    altered, invented, or rounded upward.
    """
    original_violations = [
        str(value) for value in result.get("violations", []) if str(value)
    ]
    degradations = [
        MARKET_DEGRADATION_CODE
        for _ in (0,)
        if MARKET_DEGRADATION_CODE in original_violations
    ]
    blocking = [
        value
        for value in original_violations
        if value != MARKET_DEGRADATION_CODE
    ]

    portfolio = result.get("portfolio")
    if not isinstance(portfolio, dict):
        raise gate.SourceGateError("Source-independence portfolio summary is missing")
    target = _number(
        degradation_policy.get("target_non_yahoo_market_coverage_ratio", 0.75)
    )
    coverage = _number(portfolio.get("non_yahoo_market_coverage_ratio"))
    degraded = coverage < target
    if degraded and MARKET_DEGRADATION_CODE not in degradations:
        degradations.append(MARKET_DEGRADATION_CODE)
    if not degraded:
        degradations = [
            value for value in degradations if value != MARKET_DEGRADATION_CODE
        ]

    portfolio.update(
        {
            "non_yahoo_market_coverage_target_ratio": round(target, 4),
            "market_corroboration_status": (
                "DEGRADED" if degraded else "CORROBORATED"
            ),
            "market_corroboration_global_blocker": False,
            "blocking_violation_count": len(blocking),
            "quality_degradation_count": len(degradations),
        }
    )

    macro_available = str(portfolio.get("fred_macro_status") or "") in {
        "LIVE",
        "CACHED",
    }
    records = result.get("records")
    if not isinstance(records, list) or len(records) != 20:
        raise gate.SourceGateError(
            "Source-independence quality policy requires exactly 20 records"
        )

    high_count = 0
    for record in records:
        if not isinstance(record, dict):
            raise gate.SourceGateError("Source-independence record must be an object")
        missing = [
            str(value)
            for value in record.get("missing_or_review", [])
            if str(value) and str(value) != PORTFOLIO_FAILURE_CODE
        ]
        market = record.get("market_corroboration")
        provider_count = (
            _integer(market.get("independent_provider_count"))
            if isinstance(market, Mapping)
            else 0
        )
        if provider_count < 1 and ROW_MARKET_MISSING_CODE not in missing:
            missing.append(ROW_MARKET_MISSING_CODE)
        record["missing_or_review"] = missing

        individually_eligible = _row_individually_high_eligible(
            record,
            core_policy,
            macro_available,
        )
        eligible = individually_eligible and not blocking
        record["eligible_for_high_confidence_model_inference"] = eligible
        public_logic = record.get("public_logic_state")
        if isinstance(public_logic, dict):
            public_logic["model_inference_confidence"] = (
                "HIGH_ELIGIBLE" if eligible else "LIMITED"
            )
            public_logic[
                "market_corroboration_is_company_claim_evidence"
            ] = False
        if eligible:
            high_count += 1
        elif blocking and PORTFOLIO_FAILURE_CODE not in missing:
            missing.append(PORTFOLIO_FAILURE_CODE)

    portfolio["high_confidence_model_inference_eligible_count"] = high_count
    result["blocking_violations"] = blocking
    result["degradations"] = sorted(set(degradations))
    result["violations"] = blocking
    result["status"] = "PASS" if not blocking else "FAIL"
    result["quality_status"] = (
        "PASS_WITH_DEGRADATION"
        if not blocking and degradations
        else result["status"]
    )

    notice = result.get("methodology_notice")
    if not isinstance(notice, dict):
        notice = {}
        result["methodology_notice"] = notice
    notice.update(
        {
            "market_corroboration_policy": degradation_policy.get("policy_id"),
            "market_corroboration_unavailable_is_global_blocker": False,
            "market_corroboration_required_for_high_confidence_model_inference": True,
            "market_corroboration_required_for_uncapped_valuation_factor": True,
            "uncorroborated_valuation_factor_max": _number(
                degradation_policy.get(
                    "uncorroborated_valuation_factor_max",
                    3.75,
                )
            ),
            "provider_failure_must_be_disclosed": True,
            "provider_failure_must_not_be_silently_relabelled_as_success": True,
            "market_data_is_not_averaged_into_published_returns": True,
        }
    )
    return result


_original_build = gate.build


def build_with_market_quality_degradation(
    top20: list[dict[str, Any]],
    reports: Mapping[str, Mapping[str, Any]],
    orders: Mapping[str, Mapping[str, Any]],
    core_policy: Mapping[str, Any],
    cache: Mapping[str, Any],
    offline: bool,
):
    result, updated_cache = _original_build(
        top20,
        reports,
        orders,
        core_policy,
        cache,
        offline,
    )
    return (
        apply_market_quality_policy(
            result,
            core_policy,
            _read_policy(),
        ),
        updated_cache,
    )


gate.build = build_with_market_quality_degradation


def self_test() -> None:
    policy = _read_policy()
    core_policy = {
        "minimums": {
            "high_confidence_claim_independent_families": 2,
            "high_confidence_claim_independent_domains": 2,
            "high_confidence_claim_primary_sources": 1,
            "high_confidence_claim_dated_ratio": 0.8,
        }
    }
    record = {
        "ticker": "TEST",
        "eligible_for_high_confidence_model_inference": True,
        "source_metrics": {
            "claim_relevant_independent_families": 2,
            "claim_relevant_independent_domains": 2,
            "claim_relevant_primary_sources": 1,
            "claim_dated_evidence_ratio": 1.0,
        },
        "market_corroboration": {
            "status": "UNAVAILABLE",
            "independent_provider_count": 0,
        },
        "missing_or_review": [PORTFOLIO_FAILURE_CODE],
        "public_logic_state": {
            "model_inference_confidence": "HIGH_ELIGIBLE"
        },
    }
    document = {
        "status": "FAIL",
        "violations": [MARKET_DEGRADATION_CODE],
        "portfolio": {
            "non_yahoo_market_coverage_ratio": 0.0,
            "fred_macro_status": "LIVE",
            "high_confidence_model_inference_eligible_count": 1,
        },
        "records": [dict(record) for _ in range(20)],
        "methodology_notice": {},
    }
    adjusted = apply_market_quality_policy(document, core_policy, policy)
    assert adjusted["status"] == "PASS"
    assert adjusted["quality_status"] == "PASS_WITH_DEGRADATION"
    assert adjusted["violations"] == []
    assert adjusted["blocking_violations"] == []
    assert adjusted["degradations"] == [MARKET_DEGRADATION_CODE]
    assert adjusted["portfolio"]["non_yahoo_market_coverage_ratio"] == 0.0
    assert adjusted["portfolio"]["market_corroboration_status"] == "DEGRADED"
    assert adjusted["portfolio"]["high_confidence_model_inference_eligible_count"] == 0
    assert all(
        row["eligible_for_high_confidence_model_inference"] is False
        and row["public_logic_state"]["model_inference_confidence"] == "LIMITED"
        and ROW_MARKET_MISSING_CODE in row["missing_or_review"]
        and PORTFOLIO_FAILURE_CODE not in row["missing_or_review"]
        for row in adjusted["records"]
    )

    blocking_document = {
        "status": "FAIL",
        "violations": [
            MARKET_DEGRADATION_CODE,
            "INSUFFICIENT_CLAIM_PRIMARY_COVERAGE",
        ],
        "portfolio": {
            "non_yahoo_market_coverage_ratio": 0.0,
            "fred_macro_status": "LIVE",
            "high_confidence_model_inference_eligible_count": 0,
        },
        "records": [dict(record) for _ in range(20)],
        "methodology_notice": {},
    }
    blocked = apply_market_quality_policy(
        blocking_document,
        core_policy,
        policy,
    )
    assert blocked["status"] == "FAIL"
    assert blocked["violations"] == ["INSUFFICIENT_CLAIM_PRIMARY_COVERAGE"]
    print(
        "V213_SOURCE_INDEPENDENCE_V3_SELF_TEST = PASS; "
        "market_unavailability=quality_degradation; "
        "claim_evidence_failures=blocking; "
        "high_confidence_requires_market_corroboration"
    )


if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(gate.main())
