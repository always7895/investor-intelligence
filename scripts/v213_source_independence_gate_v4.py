#!/usr/bin/env python3
"""Final v2.1.3 source-independence and market-quality wrapper.

This module preserves all blocking company/claim evidence rules from the existing
v2 provider implementation and hardens the market boundary without granting
market data any company-claim authority.

Reviewed behavior:

* Yahoo is the compatibility calculation source only. It is never an
  authoritative corroboration source.
* A provider is counted only when its market ``as_of`` date is present and no
  more than seven calendar days old.
* High-confidence inference requires at least two independently operated
  providers with comparable metric bases, a freshest observation no more than
  four days old, and no provider lag greater than three days from the freshest
  comparable observation.
* Adjusted-close returns are compared only with other adjusted-close returns.
  Unknown or unadjusted close series cannot manufacture agreement or conflict.
* Independent-provider conflicts are evaluated pairwise and are never averaged.
* Two comparable independent providers that agree with one another but both
  materially disagree with the Yahoo compatibility calculation block activation
  for calculation reconciliation.
* A single provider, a non-comparable provider set, or provider unavailability
  limits confidence but does not erase otherwise valid company evidence.
* Stale, undated or failed providers remain disclosed and cannot count toward
  coverage, valuation confidence, or high-confidence eligibility.

The output remains a public-source reconstruction. It does not claim to reproduce
Serenity's private process, official formula, or official score.
"""
from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
V2_PATH = SCRIPT_DIR / "v213_source_independence_gate_v2.py"
DEGRADATION_POLICY_PATH = ROOT / "config" / "v213-market-corroboration-degradation-policy.json"

MARKET_DEGRADATION_CODE = "INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE"
PAIRWISE_CONFLICT_CODE = "MARKET_SOURCE_CONFLICT_REVIEW"
CALCULATION_DIVERGENCE_CODE = "MARKET_CALCULATION_DIVERGENCE_REVIEW"
CALCULATION_DIVERGENCE_MISSING = "CALCULATION_SOURCE_DIVERGENCE"
ROW_MARKET_MISSING_CODE = "NON_YAHOO_MARKET_CORROBORATION"
ROW_SINGLE_MARKET_CODE = "SINGLE_INDEPENDENT_MARKET_PROVIDER"
ROW_NONCOMPARABLE_MARKET_CODE = "NONCOMPARABLE_MARKET_PROVIDER_BASES"
ROW_STALE_MARKET_CODE = "STALE_MARKET_CORROBORATION"
ROW_MACRO_STALE_CODE = "OFFICIAL_MACRO_CONTEXT_UNAVAILABLE"
PORTFOLIO_FAILURE_CODE = "PORTFOLIO_SOURCE_POLICY"

MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS = 2
MARKET_HARD_MAX_AGE_DAYS = 7.0
MARKET_HIGH_CONFIDENCE_FRESHEST_MAX_AGE_DAYS = 4.0
MARKET_COMPARABLE_PROVIDER_MAX_LAG_DAYS = 3.0
MACRO_MAX_AGE_DAYS = 45.0
ADJUSTED_CLOSE_BASIS = "split_dividend_adjusted_close"

MARKET_FAMILIES = {
    "yahoo_market",
    "stooq_market",
    "nasdaq_market",
    "alpha_vantage_market",
    "hfmarketdata_market",
}


def _load_module() -> ModuleType:
    if not V2_PATH.is_file():
        raise RuntimeError(f"Missing v2 provider wrapper: {V2_PATH}")
    spec = importlib.util.spec_from_file_location(
        "investor_intelligence_v213_source_gate_v2_for_v4",
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


def _date(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _age_days(value: Any, today: dt.date | None = None) -> float | None:
    observed = _date(value)
    if observed is None:
        return None
    current = today or dt.datetime.now(dt.timezone.utc).date()
    age = float((current - observed).days)
    if age < -1:
        return None
    return max(0.0, age)


def _provider_name(provider_row: Mapping[str, Any]) -> str:
    return str(provider_row.get("provider") or "unknown").strip()


def _metric_basis(provider_row: Mapping[str, Any]) -> str:
    declared = str(
        provider_row.get("metric_basis")
        or provider_row.get("adjustment_basis")
        or ""
    ).strip().lower()
    if declared:
        return declared
    name = _provider_name(provider_row).lower()
    if name in {"hfmarketdata_daily_bars", "alpha_vantage_adjusted"}:
        return ADJUSTED_CLOSE_BASIS
    if name == "nasdaq_historical_api":
        return "exchange_close_unadjusted_or_unknown"
    if name == "stooq_daily_csv":
        return "vendor_close_adjustment_unknown"
    return "unknown"


def _sanitize_provider_rows(
    record: dict[str, Any],
    today: dt.date,
) -> tuple[list[dict[str, Any]], list[str]]:
    market = record.get("market_corroboration")
    if not isinstance(market, dict):
        raise gate.SourceGateError("Source-independence market object is missing")
    raw_rows = market.get("providers")
    rows = raw_rows if isinstance(raw_rows, list) else []
    counted: list[dict[str, Any]] = []
    stale_names: list[str] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = raw
        row["metric_basis"] = _metric_basis(row)
        status = str(row.get("status") or "").upper()
        age = _age_days(row.get("as_of"), today)
        row["market_age_days"] = age
        row["fresh_for_coverage"] = bool(
            status in {"LIVE", "CACHED"}
            and age is not None
            and age <= MARKET_HARD_MAX_AGE_DAYS
        )
        row["fresh_for_high_confidence"] = bool(
            row["fresh_for_coverage"]
            and age is not None
            and age <= MARKET_HIGH_CONFIDENCE_FRESHEST_MAX_AGE_DAYS
        )
        if status in {"LIVE", "CACHED"} and not row["fresh_for_coverage"]:
            stale_names.append(_provider_name(row))
            row["status"] = "UNAVAILABLE"
            reason = (
                "missing market as_of"
                if age is None
                else f"stale market as_of; age_days={age:.0f}; max={MARKET_HARD_MAX_AGE_DAYS:.0f}"
            )
            existing = str(row.get("error") or "").strip()
            row["error"] = (existing + "; " + reason).strip("; ")
        if row["fresh_for_coverage"]:
            counted.append(row)

    market["providers"] = rows
    market["independent_provider_count"] = len(counted)

    # A stale observation may have been added to the generic source list by the
    # underlying collector before this freshness pass. Remove only its market
    # corroboration entry; company/claim evidence is untouched.
    if stale_names and isinstance(record.get("sources"), list):
        stale_set = {name.lower() for name in stale_names}
        record["sources"] = [
            source
            for source in record["sources"]
            if not (
                isinstance(source, Mapping)
                and str(source.get("claim_type") or "")
                == "independent_market_corroboration"
                and str(source.get("source_id") or "").lower() in stale_set
            )
        ]
    return counted, stale_names


def _comparable_groups(
    providers: Iterable[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    rows = [provider for provider in providers if bool(provider.get("fresh_for_coverage"))]
    dated = [
        (provider, _date(provider.get("as_of")))
        for provider in rows
        if _date(provider.get("as_of")) is not None
    ]
    if not dated:
        return {}
    freshest = max(date for _provider, date in dated if date is not None)
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for provider, observed in dated:
        assert observed is not None
        age = _age_days(observed)
        lag = float((freshest - observed).days)
        provider["lag_from_freshest_provider_days"] = lag  # type: ignore[index]
        comparable = bool(
            age is not None
            and age <= MARKET_HIGH_CONFIDENCE_FRESHEST_MAX_AGE_DAYS
            and lag <= MARKET_COMPARABLE_PROVIDER_MAX_LAG_DAYS
        )
        provider["comparable_for_high_confidence"] = comparable  # type: ignore[index]
        if comparable:
            groups.setdefault(_metric_basis(provider), []).append(provider)
    return groups


def _largest_comparable_group(
    groups: Mapping[str, list[Mapping[str, Any]]],
) -> tuple[str, list[Mapping[str, Any]]]:
    eligible = [
        (basis, rows)
        for basis, rows in groups.items()
        if basis not in {"", "unknown", "exchange_close_unadjusted_or_unknown", "vendor_close_adjustment_unknown"}
    ]
    if not eligible:
        return "", []
    return max(eligible, key=lambda item: (len(item[1]), item[0]))


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
            if _metric_basis(left) != _metric_basis(right):
                continue
            left_name = _provider_name(left)
            right_name = _provider_name(right)
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


def _calculation_divergence(
    comparable_basis: str,
    providers: list[Mapping[str, Any]],
) -> tuple[bool, bool]:
    if comparable_basis != ADJUSTED_CLOSE_BASIS:
        return False, False
    divergent = [
        provider
        for provider in providers
        if bool(provider.get("long_term_conflict"))
        or bool(provider.get("short_term_conflict"))
    ]
    return len(divergent) >= 2, len(providers) == 1 and len(divergent) == 1


def _fresh_macro_available(record: Mapping[str, Any], today: dt.date) -> bool:
    sources = record.get("sources")
    if not isinstance(sources, list):
        return False
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        if str(source.get("family") or "") != "official_macro":
            continue
        age = _age_days(source.get("as_of"), today)
        if age is not None and age <= MACRO_MAX_AGE_DAYS:
            return True
    return False


def _reconcile_market_record(
    record: dict[str, Any],
    core_policy: Mapping[str, Any],
    today: dt.date,
) -> dict[str, Any]:
    market = record.get("market_corroboration")
    if not isinstance(market, dict):
        raise gate.SourceGateError("Source-independence market object is missing")
    providers, stale_names = _sanitize_provider_rows(record, today)
    groups = _comparable_groups(providers)
    comparable_basis, comparable_rows = _largest_comparable_group(groups)
    pairwise = _pairwise_conflicts(comparable_rows, core_policy)
    strong_divergence, single_divergence = _calculation_divergence(
        comparable_basis,
        comparable_rows,
    )

    missing = [
        str(value)
        for value in record.get("missing_or_review", [])
        if str(value)
        and str(value)
        not in {
            PORTFOLIO_FAILURE_CODE,
            ROW_MARKET_MISSING_CODE,
            ROW_SINGLE_MARKET_CODE,
            ROW_NONCOMPARABLE_MARKET_CODE,
            ROW_STALE_MARKET_CODE,
            PAIRWISE_CONFLICT_CODE,
            CALCULATION_DIVERGENCE_MISSING,
        }
    ]
    provider_count = len(providers)
    comparable_count = len(comparable_rows)
    if provider_count == 0:
        missing.append(ROW_MARKET_MISSING_CODE)
    elif provider_count < MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS:
        missing.append(ROW_SINGLE_MARKET_CODE)
    if provider_count >= MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS and comparable_count < MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS:
        missing.append(ROW_NONCOMPARABLE_MARKET_CODE)
    if stale_names:
        missing.append(ROW_STALE_MARKET_CODE)
    if pairwise:
        missing.append(PAIRWISE_CONFLICT_CODE)
    if strong_divergence or single_divergence:
        missing.append(CALCULATION_DIVERGENCE_MISSING)

    if pairwise:
        status = "CONFLICT_REVIEW"
    elif strong_divergence:
        status = "CALCULATION_DIVERGENCE_REVIEW"
    elif comparable_count >= MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS:
        status = "CORROBORATED"
    elif provider_count:
        status = "LIMITED_SINGLE_PROVIDER_OR_NONCOMPARABLE"
    else:
        status = "UNAVAILABLE"

    market.update(
        {
            "status": status,
            "independent_provider_count": provider_count,
            "comparable_independent_provider_count": comparable_count,
            "comparable_metric_basis": comparable_basis,
            "minimum_providers_for_high_confidence": MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS,
            "hard_max_age_days": MARKET_HARD_MAX_AGE_DAYS,
            "high_confidence_freshest_max_age_days": MARKET_HIGH_CONFIDENCE_FRESHEST_MAX_AGE_DAYS,
            "comparable_provider_max_lag_days": MARKET_COMPARABLE_PROVIDER_MAX_LAG_DAYS,
            "pairwise_independent_provider_conflicts": pairwise,
            "pairwise_conflict_count": len(pairwise),
            "yahoo_compatibility_calculation_divergence": bool(
                strong_divergence or single_divergence
            ),
            "yahoo_is_authoritative_market_source": False,
            "conflict_values_averaged": False,
            "stale_or_undated_provider_count": len(stale_names),
        }
    )
    record["missing_or_review"] = sorted(set(missing))
    return {
        "provider_count": provider_count,
        "comparable_count": comparable_count,
        "pairwise_conflict": bool(pairwise),
        "strong_calculation_divergence": strong_divergence,
        "single_calculation_divergence": single_divergence,
        "stale_provider_count": len(stale_names),
        "macro_fresh": _fresh_macro_available(record, today),
    }


def _row_individually_high_eligible(
    record: Mapping[str, Any],
    state: Mapping[str, Any],
    core_policy: Mapping[str, Any],
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
        and _integer(state.get("comparable_count"))
        >= MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS
        and str(market.get("status") or "") == "CORROBORATED"
        and bool(state.get("macro_fresh"))
        and PAIRWISE_CONFLICT_CODE not in missing
        and CALCULATION_DIVERGENCE_MISSING not in missing
        and "SOURCE_FAMILY_CONCENTRATION" not in missing
        and "CLAIM_SOURCE_FAMILY_CONCENTRATION" not in missing
    )


def apply_market_quality_policy(
    result: dict[str, Any],
    core_policy: Mapping[str, Any],
    degradation_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply Worker-compatible graceful degradation plus stricter row confidence."""
    original_violations = [
        str(value) for value in result.get("violations", []) if str(value)
    ]
    blocking = [
        value
        for value in original_violations
        if value != MARKET_DEGRADATION_CODE
    ]

    portfolio = result.get("portfolio")
    if not isinstance(portfolio, dict):
        raise gate.SourceGateError("Source-independence portfolio summary is missing")
    records = result.get("records")
    if not isinstance(records, list) or len(records) != 20:
        raise gate.SourceGateError(
            "Source-independence quality policy requires exactly 20 records"
        )

    today = dt.datetime.now(dt.timezone.utc).date()
    states: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise gate.SourceGateError("Source-independence record must be an object")
        states.append(_reconcile_market_record(record, core_policy, today))

    target = _number(
        degradation_policy.get("target_non_yahoo_market_coverage_ratio", 0.75)
    )
    coverage = sum(1 for state in states if state["provider_count"] >= 1) / 20.0
    comparable_coverage = sum(
        1
        for state in states
        if state["comparable_count"] >= MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS
    ) / 20.0
    pairwise_conflicts = sum(1 for state in states if state["pairwise_conflict"])
    calculation_divergences = sum(
        1 for state in states if state["strong_calculation_divergence"]
    )
    single_divergences = sum(
        1 for state in states if state["single_calculation_divergence"]
    )
    stale_provider_count = sum(_integer(state["stale_provider_count"]) for state in states)

    if pairwise_conflicts and PAIRWISE_CONFLICT_CODE not in blocking:
        blocking.append(PAIRWISE_CONFLICT_CODE)
    if calculation_divergences and CALCULATION_DIVERGENCE_CODE not in blocking:
        blocking.append(CALCULATION_DIVERGENCE_CODE)

    degraded = coverage < target
    advisories: list[str] = []
    if comparable_coverage < target:
        advisories.append("INSUFFICIENT_COMPARABLE_MULTI_PROVIDER_MARKET_COVERAGE")
    if single_divergences:
        advisories.append("SINGLE_PROVIDER_CALCULATION_DIVERGENCE")
    if stale_provider_count:
        advisories.append("STALE_OR_UNDATED_MARKET_PROVIDER_EXCLUDED")

    portfolio.update(
        {
            "non_yahoo_market_coverage_ratio": round(coverage, 4),
            "non_yahoo_comparable_multi_provider_coverage_ratio": round(
                comparable_coverage,
                4,
            ),
            "non_yahoo_market_coverage_target_ratio": round(target, 4),
            "minimum_market_providers_for_high_confidence": (
                MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS
            ),
            "market_hard_max_age_days": MARKET_HARD_MAX_AGE_DAYS,
            "market_high_confidence_freshest_max_age_days": (
                MARKET_HIGH_CONFIDENCE_FRESHEST_MAX_AGE_DAYS
            ),
            "market_comparable_provider_max_lag_days": (
                MARKET_COMPARABLE_PROVIDER_MAX_LAG_DAYS
            ),
            # Keep this field compatible with the deployed Worker schema: it is
            # DEGRADED exactly when absolute non-Yahoo coverage is below target.
            "market_corroboration_status": (
                "DEGRADED" if degraded else "CORROBORATED"
            ),
            "market_multi_provider_quality_status": (
                "CORROBORATED"
                if comparable_coverage >= target
                else "LIMITED"
            ),
            "market_corroboration_global_blocker": False,
            "market_conflict_ticker_count": pairwise_conflicts,
            "market_calculation_divergence_ticker_count": calculation_divergences,
            "single_provider_calculation_divergence_ticker_count": single_divergences,
            "stale_or_undated_market_provider_count": stale_provider_count,
            "blocking_violation_count": len(set(blocking)),
            "quality_degradation_count": 1 if degraded else 0,
            "market_quality_advisories": sorted(set(advisories)),
        }
    )

    high_count = 0
    for record, state in zip(records, states):
        missing = [
            str(value)
            for value in record.get("missing_or_review", [])
            if str(value) and str(value) != PORTFOLIO_FAILURE_CODE
        ]
        if not bool(state.get("macro_fresh")) and ROW_MACRO_STALE_CODE not in missing:
            missing.append(ROW_MACRO_STALE_CODE)
        individually_eligible = _row_individually_high_eligible(
            record,
            state,
            core_policy,
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
            public_logic["market_metric_basis_must_match"] = True
            public_logic["market_data_latestness_required"] = True
        if eligible:
            high_count += 1
        elif blocking and PORTFOLIO_FAILURE_CODE not in missing:
            missing.append(PORTFOLIO_FAILURE_CODE)
        record["missing_or_review"] = sorted(set(missing))

    portfolio["high_confidence_model_inference_eligible_count"] = high_count
    unique_blocking = sorted(set(blocking))
    result["blocking_violations"] = unique_blocking
    result["violations"] = unique_blocking
    result["degradations"] = [MARKET_DEGRADATION_CODE] if degraded else []
    result["advisories"] = sorted(set(advisories))
    result["status"] = "PASS" if not unique_blocking else "FAIL"
    result["quality_status"] = (
        "FAIL"
        if unique_blocking
        else ("PASS_WITH_DEGRADATION" if degraded else "PASS")
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
            "comparable_metric_basis_required_for_high_confidence": True,
            "market_conflicts_compared_pairwise_without_yahoo_authority": True,
            "yahoo_role": (
                "compatibility_calculation_only_not_authoritative_corroboration"
            ),
            "market_corroboration_required_for_uncapped_valuation_factor": True,
            "uncorroborated_valuation_factor_max": _number(
                degradation_policy.get("uncorroborated_valuation_factor_max", 3.75)
            ),
            "provider_failure_must_be_disclosed": True,
            "provider_failure_must_not_be_silently_relabelled_as_success": True,
            "market_data_is_not_averaged_into_published_returns": True,
            "source_conflicts_are_not_averaged": True,
            "market_hard_max_age_days": MARKET_HARD_MAX_AGE_DAYS,
            "market_high_confidence_freshest_max_age_days": (
                MARKET_HIGH_CONFIDENCE_FRESHEST_MAX_AGE_DAYS
            ),
            "market_comparable_provider_max_lag_days": (
                MARKET_COMPARABLE_PROVIDER_MAX_LAG_DAYS
            ),
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


def _provider(
    name: str,
    long_return: float,
    short_return: float,
    *,
    basis: str = ADJUSTED_CLOSE_BASIS,
    yahoo_conflict: bool = False,
    as_of: str | None = None,
) -> dict[str, Any]:
    return {
        "provider": name,
        "status": "LIVE",
        "as_of": as_of or dt.datetime.now(dt.timezone.utc).date().isoformat(),
        "metric_basis": basis,
        "long_term_return_pct": long_return,
        "short_term_return_pct": short_return,
        "long_term_conflict": yahoo_conflict,
        "short_term_conflict": yahoo_conflict,
    }


def _record(provider_rows: list[dict[str, Any]]) -> dict[str, Any]:
    stamp = dt.datetime.now(dt.timezone.utc).date().isoformat()
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
            "status": "CORROBORATED" if provider_rows else "UNAVAILABLE",
            "independent_provider_count": len(provider_rows),
            "providers": provider_rows,
        },
        "missing_or_review": [PORTFOLIO_FAILURE_CODE],
        "public_logic_state": {"model_inference_confidence": "HIGH_ELIGIBLE"},
        "sources": [
            {
                "source_id": "fred_official_macro",
                "family": "official_macro",
                "claim_type": "macro_context",
                "url": "https://fred.stlouisfed.org",
                "as_of": stamp,
            }
        ],
    }


def _document(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "violations": [],
        "portfolio": {
            "non_yahoo_market_coverage_ratio": 0.0,
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

    unavailable = _document([_record([]) for _ in range(20)])
    adjusted = apply_market_quality_policy(unavailable, core_policy, policy)
    assert adjusted["status"] == "PASS"
    assert adjusted["quality_status"] == "PASS_WITH_DEGRADATION"
    assert adjusted["blocking_violations"] == []
    assert adjusted["degradations"] == [MARKET_DEGRADATION_CODE]
    assert adjusted["portfolio"]["high_confidence_model_inference_eligible_count"] == 0
    assert all(
        row["eligible_for_high_confidence_model_inference"] is False
        and row["public_logic_state"]["model_inference_confidence"] == "LIMITED"
        and ROW_MARKET_MISSING_CODE in row["missing_or_review"]
        and PORTFOLIO_FAILURE_CODE not in row["missing_or_review"]
        for row in adjusted["records"]
    )

    one = _provider("provider_one", 20.0, 5.0)
    single = _document([_record([copy.deepcopy(one)]) for _ in range(20)])
    single_adjusted = apply_market_quality_policy(single, core_policy, policy)
    assert single_adjusted["status"] == "PASS"
    assert single_adjusted["quality_status"] == "PASS"
    assert single_adjusted["portfolio"]["high_confidence_model_inference_eligible_count"] == 0
    assert all(
        ROW_SINGLE_MARKET_CODE in row["missing_or_review"]
        for row in single_adjusted["records"]
    )

    left = _provider("provider_one", 20.0, 5.0)
    right = _provider("provider_two", 22.0, 6.0)
    corroborated = _document(
        [_record([copy.deepcopy(left), copy.deepcopy(right)]) for _ in range(20)]
    )
    corroborated_adjusted = apply_market_quality_policy(
        corroborated,
        core_policy,
        policy,
    )
    assert corroborated_adjusted["status"] == "PASS"
    assert corroborated_adjusted["quality_status"] == "PASS"
    assert corroborated_adjusted["portfolio"]["high_confidence_model_inference_eligible_count"] == 20
    assert all(
        row["market_corroboration"]["status"] == "CORROBORATED"
        and row["eligible_for_high_confidence_model_inference"] is True
        for row in corroborated_adjusted["records"]
    )

    noncomparable = _document(
        [
            _record(
                [
                    _provider("provider_one", 20.0, 5.0),
                    _provider(
                        "provider_two",
                        22.0,
                        6.0,
                        basis="exchange_close_unadjusted_or_unknown",
                    ),
                ]
            )
            for _ in range(20)
        ]
    )
    noncomparable_adjusted = apply_market_quality_policy(
        noncomparable,
        core_policy,
        policy,
    )
    assert noncomparable_adjusted["status"] == "PASS"
    assert noncomparable_adjusted["portfolio"]["high_confidence_model_inference_eligible_count"] == 0
    assert all(
        ROW_NONCOMPARABLE_MARKET_CODE in row["missing_or_review"]
        for row in noncomparable_adjusted["records"]
    )

    conflict_left = _provider("provider_one", 20.0, 5.0)
    conflict_right = _provider("provider_two", 80.0, 40.0)
    conflict = _document(
        [
            _record([copy.deepcopy(conflict_left), copy.deepcopy(conflict_right)])
            for _ in range(20)
        ]
    )
    conflict_adjusted = apply_market_quality_policy(conflict, core_policy, policy)
    assert conflict_adjusted["status"] == "FAIL"
    assert PAIRWISE_CONFLICT_CODE in conflict_adjusted["blocking_violations"]
    assert conflict_adjusted["portfolio"]["market_conflict_ticker_count"] == 20

    yahoo_left = _provider(
        "provider_one",
        20.0,
        5.0,
        yahoo_conflict=True,
    )
    yahoo_right = _provider(
        "provider_two",
        21.0,
        5.5,
        yahoo_conflict=True,
    )
    calculation = _document(
        [_record([copy.deepcopy(yahoo_left), copy.deepcopy(yahoo_right)]) for _ in range(20)]
    )
    calculation_adjusted = apply_market_quality_policy(
        calculation,
        core_policy,
        policy,
    )
    assert calculation_adjusted["status"] == "FAIL"
    assert CALCULATION_DIVERGENCE_CODE in calculation_adjusted["blocking_violations"]
    assert calculation_adjusted["portfolio"]["market_calculation_divergence_ticker_count"] == 20

    stale = _provider(
        "provider_one",
        20.0,
        5.0,
        as_of="2020-01-01",
    )
    stale_document = _document([_record([copy.deepcopy(stale)]) for _ in range(20)])
    stale_adjusted = apply_market_quality_policy(stale_document, core_policy, policy)
    assert stale_adjusted["status"] == "PASS"
    assert stale_adjusted["quality_status"] == "PASS_WITH_DEGRADATION"
    assert stale_adjusted["portfolio"]["non_yahoo_market_coverage_ratio"] == 0.0
    assert stale_adjusted["portfolio"]["stale_or_undated_market_provider_count"] == 20

    print(
        "V213_SOURCE_INDEPENDENCE_V4_SELF_TEST = PASS; "
        "market_unavailability=quality_degradation; "
        "claim_evidence_failures=blocking; "
        "high_confidence_requires_two_fresh_comparable_market_providers; "
        "independent_market_conflicts=pairwise_same_basis; "
        "stale_market_excluded=true; yahoo_authoritative=false; "
        "conflicts_not_averaged=true; worker_degradation_schema_compatible=true"
    )


if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(gate.main())
