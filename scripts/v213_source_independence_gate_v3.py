#!/usr/bin/env python3
"""v2.1.3 claim-source gate with explicit market-quality degradation.

This wrapper preserves every blocking company/claim evidence rule from the v2
provider implementation. It changes the reviewed market boundary in four ways:

* temporary unavailability of independent free market-price endpoints is a
  disclosed quality degradation rather than a reason to erase otherwise valid
  company evidence;
* high-confidence model inference requires at least two fresh independently
  operated market providers, not one;
* market conflicts are evaluated pairwise between independent providers rather
  than treating Yahoo as a single authoritative anchor;
* Yahoo remains the compatibility calculation source. If two independent
  providers agree with one another but materially disagree with the published
  Yahoo-based calculation, activation is blocked for calculation reconciliation.

Market observations are never averaged into the published return and never prove
a company fact, order, dependency, bottleneck, pricing power, replacement
friction, TAM capture, company capture, or thesis state.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
V2_PATH = SCRIPT_DIR / "v213_source_independence_gate_v2.py"
DEGRADATION_POLICY_PATH = ROOT / "config" / "v213-market-corroboration-degradation-policy.json"
MARKET_DEGRADATION_CODE = "INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE"
MULTI_PROVIDER_DEGRADATION_CODE = "INSUFFICIENT_MULTI_PROVIDER_MARKET_CORROBORATION"
SINGLE_PROVIDER_DIVERGENCE_CODE = "SINGLE_PROVIDER_CALCULATION_DIVERGENCE"
PAIRWISE_CONFLICT_CODE = "MARKET_SOURCE_CONFLICT_REVIEW"
CALCULATION_DIVERGENCE_CODE = "MARKET_CALCULATION_DIVERGENCE_REVIEW"
CALCULATION_DIVERGENCE_MISSING = "CALCULATION_SOURCE_DIVERGENCE"
ROW_MARKET_MISSING_CODE = "NON_YAHOO_MARKET_CORROBORATION"
ROW_SINGLE_MARKET_CODE = "SINGLE_INDEPENDENT_MARKET_PROVIDER"
PORTFOLIO_FAILURE_CODE = "PORTFOLIO_SOURCE_POLICY"
MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS = 2


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
        or value.get("market_corroboration_required_for_high_confidence_model_inference") is not True
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
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and abs(result) != float("inf") else 0.0


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or abs(result) == float("inf"):
        return None
    return result


def _live_providers(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    market = record.get("market_corroboration")
    if not isinstance(market, Mapping):
        return []
    providers = market.get("providers")
    if not isinstance(providers, list):
        return []
    return [
        provider
        for provider in providers
        if isinstance(provider, Mapping)
        and str(provider.get("status") or "").upper() in {"LIVE", "CACHED"}
    ]


def _pairwise_conflicts(
    providers: list[Mapping[str, Any]],
    core_policy: Mapping[str, Any],
) -> list[str]:
    market_policy = (
        core_policy.get("market_data")
        if isinstance(core_policy.get("market_data"), Mapping)
        else {}
    )
    long_tolerance = _number(
        market_policy.get("long_term_absolute_tolerance_percentage_points", 30.0)
    )
    short_tolerance = _number(
        market_policy.get("short_term_absolute_tolerance_percentage_points", 18.0)
    )
    conflicts: list[str] = []
    for left_index, left in enumerate(providers):
        for right in providers[left_index + 1 :]:
            left_name = str(left.get("provider") or "unknown-left")
            right_name = str(right.get("provider") or "unknown-right")
            long_left = _optional_number(left.get("long_term_return_pct"))
            long_right = _optional_number(right.get("long_term_return_pct"))
            short_left = _optional_number(left.get("short_term_return_pct"))
            short_right = _optional_number(right.get("short_term_return_pct"))
            long_conflict = (
                long_left is not None
                and long_right is not None
                and abs(long_left - long_right) > long_tolerance
            )
            short_conflict = (
                short_left is not None
                and short_right is not None
                and abs(short_left - short_right) > short_tolerance
            )
            if long_conflict or short_conflict:
                conflicts.append(f"{left_name}<->{right_name}")
    return conflicts


def _calculation_divergence(providers: list[Mapping[str, Any]]) -> tuple[bool, bool]:
    """Return (strong_divergence, single_provider_divergence).

    ``long_term_conflict`` and ``short_term_conflict`` are legacy comparisons to
    the Yahoo compatibility calculation. They are not independent-provider
    conflicts. Two or more mutually consistent independent providers disagreeing
    with that calculation is strong evidence that the displayed calculation must
    be reconciled before activation. A lone provider disagreement remains a
    disclosed quality degradation and cannot receive high confidence.
    """
    divergent = [
        provider
        for provider in providers
        if bool(provider.get("long_term_conflict"))
        or bool(provider.get("short_term_conflict"))
    ]
    return len(divergent) >= 2, len(providers) == 1 and len(divergent) == 1


def _reconcile_market_record(
    record: dict[str, Any],
    core_policy: Mapping[str, Any],
) -> dict[str, Any]:
    market = record.get("market_corroboration")
    if not isinstance(market, dict):
        raise gate.SourceGateError("Source-independence market object is missing")
    providers = _live_providers(record)
    declared_count = _integer(market.get("independent_provider_count"))
    if declared_count != len(providers):
        raise gate.SourceGateError(
            "Fresh market provider count does not match the provider observations"
        )
    pairwise = _pairwise_conflicts(providers, core_policy)
    strong_calculation_divergence, single_divergence = _calculation_divergence(providers)

    missing = [
        str(value)
        for value in record.get("missing_or_review", [])
        if str(value)
        and str(value)
        not in {
            PORTFOLIO_FAILURE_CODE,
            ROW_MARKET_MISSING_CODE,
            ROW_SINGLE_MARKET_CODE,
            PAIRWISE_CONFLICT_CODE,
            CALCULATION_DIVERGENCE_MISSING,
        }
    ]
    if declared_count == 0:
        missing.append(ROW_MARKET_MISSING_CODE)
    elif declared_count < MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS:
        missing.append(ROW_SINGLE_MARKET_CODE)
    if pairwise:
        missing.append(PAIRWISE_CONFLICT_CODE)
    if strong_calculation_divergence or single_divergence:
        missing.append(CALCULATION_DIVERGENCE_MISSING)

    if pairwise:
        status = "CONFLICT_REVIEW"
    elif strong_calculation_divergence:
        status = "CALCULATION_DIVERGENCE_REVIEW"
    elif declared_count:
        status = "CORROBORATED"
    else:
        status = "UNAVAILABLE"
    market["status"] = status
    market["minimum_providers_for_high_confidence"] = MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS
    market["pairwise_independent_provider_conflicts"] = pairwise
    market["pairwise_conflict_count"] = len(pairwise)
    market["yahoo_compatibility_calculation_divergence"] = bool(
        strong_calculation_divergence or single_divergence
    )
    market["yahoo_is_authoritative_market_source"] = False
    market["conflict_values_averaged"] = False
    record["missing_or_review"] = sorted(set(missing))
    return {
        "provider_count": declared_count,
        "pairwise_conflict": bool(pairwise),
        "strong_calculation_divergence": strong_calculation_divergence,
        "single_calculation_divergence": single_divergence,
    }


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
        and _integer(market.get("independent_provider_count"))
        >= MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS
        and str(market.get("status") or "") == "CORROBORATED"
        and PAIRWISE_CONFLICT_CODE not in missing
        and CALCULATION_DIVERGENCE_MISSING not in missing
        and "SOURCE_FAMILY_CONCENTRATION" not in missing
        and "CLAIM_SOURCE_FAMILY_CONCENTRATION" not in missing
        and macro_available
    )


def apply_market_quality_policy(
    result: dict[str, Any],
    core_policy: Mapping[str, Any],
    degradation_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply freshness-aware, multi-provider market quality semantics.

    Company/claim family, domain, primary-source, concentration, and material
    conflict violations remain blocking. Provider outages and insufficient
    multi-provider coverage are explicit degradations. No provider status,
    timestamp, coverage ratio, or return is invented or rounded upward.
    """
    original_violations = [
        str(value) for value in result.get("violations", []) if str(value)
    ]
    blocking = [
        value
        for value in original_violations
        if value != MARKET_DEGRADATION_CODE
    ]
    degradations: list[str] = []

    portfolio = result.get("portfolio")
    if not isinstance(portfolio, dict):
        raise gate.SourceGateError("Source-independence portfolio summary is missing")
    records = result.get("records")
    if not isinstance(records, list) or len(records) != 20:
        raise gate.SourceGateError(
            "Source-independence quality policy requires exactly 20 records"
        )

    market_states: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise gate.SourceGateError("Source-independence record must be an object")
        market_states.append(_reconcile_market_record(record, core_policy))

    target = _number(
        degradation_policy.get("target_non_yahoo_market_coverage_ratio", 0.75)
    )
    coverage = sum(1 for state in market_states if state["provider_count"] >= 1) / 20.0
    multi_coverage = sum(
        1
        for state in market_states
        if state["provider_count"] >= MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS
    ) / 20.0
    pairwise_conflicts = sum(1 for state in market_states if state["pairwise_conflict"])
    calculation_divergences = sum(
        1 for state in market_states if state["strong_calculation_divergence"]
    )
    single_divergences = sum(
        1 for state in market_states if state["single_calculation_divergence"]
    )

    if coverage < target:
        degradations.append(MARKET_DEGRADATION_CODE)
    if multi_coverage < target:
        degradations.append(MULTI_PROVIDER_DEGRADATION_CODE)
    if single_divergences:
        degradations.append(SINGLE_PROVIDER_DIVERGENCE_CODE)
    if pairwise_conflicts and PAIRWISE_CONFLICT_CODE not in blocking:
        blocking.append(PAIRWISE_CONFLICT_CODE)
    if calculation_divergences and CALCULATION_DIVERGENCE_CODE not in blocking:
        blocking.append(CALCULATION_DIVERGENCE_CODE)

    portfolio.update(
        {
            "non_yahoo_market_coverage_ratio": round(coverage, 4),
            "non_yahoo_multi_provider_coverage_ratio": round(multi_coverage, 4),
            "non_yahoo_market_coverage_target_ratio": round(target, 4),
            "minimum_market_providers_for_high_confidence": MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS,
            "market_corroboration_status": (
                "BLOCKED_CONFLICT"
                if pairwise_conflicts or calculation_divergences
                else (
                    "DEGRADED"
                    if coverage < target or multi_coverage < target or single_divergences
                    else "CORROBORATED"
                )
            ),
            "market_corroboration_global_blocker": bool(
                pairwise_conflicts or calculation_divergences
            ),
            "market_conflict_ticker_count": pairwise_conflicts,
            "market_calculation_divergence_ticker_count": calculation_divergences,
            "single_provider_calculation_divergence_ticker_count": single_divergences,
            "blocking_violation_count": len(blocking),
            "quality_degradation_count": len(set(degradations)),
        }
    )

    macro_available = str(portfolio.get("fred_macro_status") or "") in {
        "LIVE",
        "CACHED",
    }
    high_count = 0
    for record in records:
        missing = [
            str(value)
            for value in record.get("missing_or_review", [])
            if str(value) and str(value) != PORTFOLIO_FAILURE_CODE
        ]
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
            public_logic["market_corroboration_is_company_claim_evidence"] = False
            public_logic["minimum_market_providers_for_high_confidence"] = (
                MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS
            )
        if eligible:
            high_count += 1
        elif blocking and PORTFOLIO_FAILURE_CODE not in missing:
            missing.append(PORTFOLIO_FAILURE_CODE)
        record["missing_or_review"] = sorted(set(missing))

    portfolio["high_confidence_model_inference_eligible_count"] = high_count
    result["blocking_violations"] = sorted(set(blocking))
    result["degradations"] = sorted(set(degradations))
    result["violations"] = sorted(set(blocking))
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
            "minimum_independent_market_providers_for_high_confidence": (
                MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS
            ),
            "market_conflicts_compared_pairwise_without_yahoo_authority": True,
            "yahoo_role": "compatibility_calculation_only_not_authoritative_corroboration",
            "market_corroboration_required_for_uncapped_valuation_factor": True,
            "uncorroborated_valuation_factor_max": _number(
                degradation_policy.get("uncorroborated_valuation_factor_max", 3.75)
            ),
            "provider_failure_must_be_disclosed": True,
            "provider_failure_must_not_be_silently_relabelled_as_success": True,
            "market_data_is_not_averaged_into_published_returns": True,
            "source_conflicts_are_not_averaged": True,
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
        apply_market_quality_policy(result, core_policy, _read_policy()),
        updated_cache,
    )


gate.build = build_with_market_quality_degradation


def _record(
    provider_rows: list[dict[str, Any]],
    provider_count: int,
) -> dict[str, Any]:
    return {
        "ticker": "TEST",
        "eligible_for_high_confidence_model_inference": True,
        "source_metrics": {
            "claim_relevant_independent_families": 2,
            "claim_relevant_independent_domains": 2,
            "claim_relevant_primary_sources": 1,
            "claim_dated_evidence_ratio": 1.0,
        },
        "market_corroboration": {
            "status": "CORROBORATED" if provider_count else "UNAVAILABLE",
            "independent_provider_count": provider_count,
            "providers": provider_rows,
        },
        "missing_or_review": [PORTFOLIO_FAILURE_CODE],
        "public_logic_state": {"model_inference_confidence": "HIGH_ELIGIBLE"},
    }


def _provider(
    name: str,
    long_return: float,
    short_return: float,
    yahoo_conflict: bool = False,
) -> dict[str, Any]:
    return {
        "provider": name,
        "status": "LIVE",
        "long_term_return_pct": long_return,
        "short_term_return_pct": short_return,
        "long_term_conflict": yahoo_conflict,
        "short_term_conflict": yahoo_conflict,
    }


def _document(records: list[dict[str, Any]], coverage: float) -> dict[str, Any]:
    return {
        "status": "PASS",
        "violations": [],
        "portfolio": {
            "non_yahoo_market_coverage_ratio": coverage,
            "fred_macro_status": "LIVE",
            "high_confidence_model_inference_eligible_count": 0,
        },
        "records": records,
        "methodology_notice": {},
    }


def self_test() -> None:
    policy = _read_policy()
    core_policy = {
        "minimums": {
            "high_confidence_claim_independent_families": 2,
            "high_confidence_claim_independent_domains": 2,
            "high_confidence_claim_primary_sources": 1,
            "high_confidence_claim_dated_ratio": 0.8,
        },
        "market_data": {
            "long_term_absolute_tolerance_percentage_points": 30.0,
            "short_term_absolute_tolerance_percentage_points": 18.0,
        },
    }

    unavailable = _document([_record([], 0) for _ in range(20)], 0.0)
    adjusted = apply_market_quality_policy(unavailable, core_policy, policy)
    assert adjusted["status"] == "PASS"
    assert adjusted["quality_status"] == "PASS_WITH_DEGRADATION"
    assert adjusted["blocking_violations"] == []
    assert MARKET_DEGRADATION_CODE in adjusted["degradations"]
    assert MULTI_PROVIDER_DEGRADATION_CODE in adjusted["degradations"]
    assert adjusted["portfolio"]["high_confidence_model_inference_eligible_count"] == 0
    assert all(
        row["eligible_for_high_confidence_model_inference"] is False
        and row["public_logic_state"]["model_inference_confidence"] == "LIMITED"
        and ROW_MARKET_MISSING_CODE in row["missing_or_review"]
        and PORTFOLIO_FAILURE_CODE not in row["missing_or_review"]
        for row in adjusted["records"]
    )

    one = _provider("provider_one", 20.0, 5.0)
    single = _document([_record([copy.deepcopy(one)], 1) for _ in range(20)], 1.0)
    single_adjusted = apply_market_quality_policy(single, core_policy, policy)
    assert single_adjusted["status"] == "PASS"
    assert single_adjusted["portfolio"]["high_confidence_model_inference_eligible_count"] == 0
    assert MULTI_PROVIDER_DEGRADATION_CODE in single_adjusted["degradations"]
    assert all(ROW_SINGLE_MARKET_CODE in row["missing_or_review"] for row in single_adjusted["records"])

    left = _provider("provider_one", 20.0, 5.0)
    right = _provider("provider_two", 22.0, 6.0)
    corroborated = _document(
        [_record([copy.deepcopy(left), copy.deepcopy(right)], 2) for _ in range(20)],
        1.0,
    )
    corroborated_adjusted = apply_market_quality_policy(corroborated, core_policy, policy)
    assert corroborated_adjusted["status"] == "PASS"
    assert corroborated_adjusted["quality_status"] == "PASS"
    assert corroborated_adjusted["portfolio"]["high_confidence_model_inference_eligible_count"] == 20
    assert all(
        row["market_corroboration"]["status"] == "CORROBORATED"
        and row["eligible_for_high_confidence_model_inference"] is True
        for row in corroborated_adjusted["records"]
    )

    conflict_left = _provider("provider_one", 20.0, 5.0)
    conflict_right = _provider("provider_two", 80.0, 40.0)
    conflict = _document(
        [_record([copy.deepcopy(conflict_left), copy.deepcopy(conflict_right)], 2) for _ in range(20)],
        1.0,
    )
    conflict_adjusted = apply_market_quality_policy(conflict, core_policy, policy)
    assert conflict_adjusted["status"] == "FAIL"
    assert PAIRWISE_CONFLICT_CODE in conflict_adjusted["blocking_violations"]
    assert conflict_adjusted["portfolio"]["market_conflict_ticker_count"] == 20

    yahoo_left = _provider("provider_one", 20.0, 5.0, yahoo_conflict=True)
    yahoo_right = _provider("provider_two", 21.0, 5.5, yahoo_conflict=True)
    calculation = _document(
        [_record([copy.deepcopy(yahoo_left), copy.deepcopy(yahoo_right)], 2) for _ in range(20)],
        1.0,
    )
    calculation_adjusted = apply_market_quality_policy(calculation, core_policy, policy)
    assert calculation_adjusted["status"] == "FAIL"
    assert CALCULATION_DIVERGENCE_CODE in calculation_adjusted["blocking_violations"]
    assert calculation_adjusted["portfolio"]["market_calculation_divergence_ticker_count"] == 20

    blocking_document = _document([_record([], 0) for _ in range(20)], 0.0)
    blocking_document["status"] = "FAIL"
    blocking_document["violations"] = [
        MARKET_DEGRADATION_CODE,
        "INSUFFICIENT_CLAIM_PRIMARY_COVERAGE",
    ]
    blocked = apply_market_quality_policy(blocking_document, core_policy, policy)
    assert blocked["status"] == "FAIL"
    assert "INSUFFICIENT_CLAIM_PRIMARY_COVERAGE" in blocked["violations"]

    print(
        "V213_SOURCE_INDEPENDENCE_V3_SELF_TEST = PASS; "
        "market_unavailability=quality_degradation; "
        "claim_evidence_failures=blocking; "
        "high_confidence_requires_two_market_providers; "
        "independent_market_conflicts=pairwise; "
        "yahoo_authoritative=false; conflicts_not_averaged=true"
    )


if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(gate.main())
