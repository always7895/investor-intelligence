#!/usr/bin/env python3
"""System Bottleneck Explosion Ranking Engine v1.

Evaluates listed companies for structural supply-chain chokepoints, pricing power,
and earnings leverage over a 6-36 month architecture transition horizon.

This module is an explicit opt-in research-policy slice and is NOT_PUBLICATION_QUALIFIED.
It does NOT alter legacy production scoring, R75 contracts, or live LINE Worker state.
Live qualification is explicitly DEFERRED until an authorized company collector is operational.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from source_observation import (
        SourceObservationError,
        normalize_observation,
        reconcile_research_claims,
    )
    from source_registry import Registry, SourceDefinition, load_registry
    HAS_SOURCE_OBSERVATION = True
except ImportError:
    HAS_SOURCE_OBSERVATION = False

from bottleneck_claim_admission import reconcile_factor_authority

try:
    from source_acquisition import AcquisitionRun
    HAS_ACQUISITION_RUN = True
except ImportError:
    HAS_ACQUISITION_RUN = False

POLICY_DEFAULT_PATH = ROOT / "config" / "system-bottleneck-explosion-v1.json"


class BottleneckRankingError(RuntimeError):
    """Base error for bottleneck ranking evaluation."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BottleneckRankingError(f"Invalid JSON at {path}: {exc}") from exc


def parse_clock(value: Any) -> datetime:
    """Parse authoritative ISO-8601 clock timestamp. Fails closed on missing or malformed input."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise BottleneckRankingError("Clock datetime must include a timezone")
        return value.astimezone(timezone.utc)
    text = str(value or "").strip()
    if not text:
        raise BottleneckRankingError("Clock timestamp is required and cannot be empty")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BottleneckRankingError(f"Invalid ISO-8601 clock timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        raise BottleneckRankingError(f"Clock timestamp must include a timezone: {value!r}")
    return dt.astimezone(timezone.utc)


def finite(value: Any, fallback: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return fallback
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if math.isfinite(parsed) else fallback


def validate_claim_evidence(
    candidate_data: Mapping[str, Any],
    now: datetime | None,
    *,
    health_states: Mapping[str, str] | None = None,
    registry: Any = None,
    acquisition_run: Any = None,
) -> dict[str, Any]:
    """Validate claim-level evidence using source_observation.reconcile_research_claims.

    Enforces fail-closed trust boundaries:
    - Candidate payload cannot inject registry or health states.
    - No automatic fixture registry substitution.
    - Observations must supply canonical parser and jurisdiction metadata; no silent defaulting.
    - Missing runtime health defaults all sources to degraded.
    - Macro-only capabilities cannot qualify company claims.
    """
    if now is None:
        return {
            "all_supported": False,
            "supported_count": 0,
            "conflict_count": 0,
            "claims_unconflicted": True,
            "has_claims": False,
            "claims": [],
            "reason": "missing_or_invalid_clock",
        }

    if not HAS_SOURCE_OBSERVATION:
        return {
            "all_supported": False,
            "supported_count": 0,
            "conflict_count": 0,
            "claims_unconflicted": True,
            "has_claims": False,
            "claims": [],
            "reason": "source_observation_unavailable",
        }

    raw_claims = candidate_data.get("material_claims")
    raw_obs = candidate_data.get("source_observations")
    if not isinstance(raw_claims, list) or not isinstance(raw_obs, list) or not raw_claims or not raw_obs:
        return {
            "all_supported": False,
            "supported_count": 0,
            "conflict_count": 0,
            "claims_unconflicted": True,
            "has_claims": bool(raw_claims),
            "claims": [],
            "reason": "no_claims_or_observations",
        }

    # Company qualification requires company-level claims (issuer financial statements or guidance/contracts)
    company_claim_types = {"issuer_financial_statement", "issuer_guidance_or_contract"}
    has_company_claim = any(
        isinstance(c, dict) and c.get("claim_type") in company_claim_types
        for c in raw_claims
    )
    if not has_company_claim:
        return {
            "all_supported": False,
            "supported_count": 0,
            "conflict_count": 0,
            "claims_unconflicted": True,
            "has_claims": True,
            "claims": [],
            "reason": "macro_only_cannot_qualify_company_claims",
        }

    # Authoritative registry resolution:
    # Parameter registry -> acquisition_run.registry -> authoritative load_registry()
    # Candidate-provided 'registry' is strictly ignored.
    active_registry = registry
    if active_registry is None:
        if acquisition_run is not None and hasattr(acquisition_run, "registry"):
            active_registry = acquisition_run.registry
        else:
            try:
                active_registry = load_registry()
            except Exception:
                active_registry = None

    # Caller-owned runtime health states:
    # Only explicit caller health_states parameter or acquisition_run is accepted.
    # Candidate-provided 'health_states' is strictly ignored.
    # If health_states is None and acquisition_run is None, active_health remains None,
    # causing reconcile_research_claims to treat all sources as DEGRADED.
    active_health = health_states

    # Raw observations are passed directly without manufactured defaults.
    # Missing parser_id, parser_version, jurisdiction, or language must fail closed.
    doc = {
        "ticker": str(candidate_data.get("ticker") or ""),
        "material_claims": raw_claims,
        "source_observations": raw_obs,
    }
    try:
        reconciliation = reconcile_research_claims(
            doc,
            registry=active_registry,
            now=now,
            health_states=active_health,
            acquisition_run=acquisition_run,
        )
        claims = reconciliation.get("claims", [])
        supported_count = sum(1 for c in claims if c.get("status") == "SUPPORTED")
        conflict_count = sum(1 for c in claims if c.get("status") == "CONFLICTED")
        if reconciliation.get("status") == "CONFLICTED" and conflict_count == 0:
            conflict_count = 1

        all_supported = bool(reconciliation.get("all_material_claims_supported", False))
        claims_unconflicted = (conflict_count == 0 and reconciliation.get("status") != "CONFLICTED")

        return {
            "all_supported": all_supported,
            "supported_count": supported_count,
            "conflict_count": conflict_count,
            "claims": claims,
            "reconciliation": reconciliation,
            "claims_unconflicted": claims_unconflicted,
            "has_claims": True,
        }
    except Exception as exc:
        return {
            "all_supported": False,
            "supported_count": 0,
            "conflict_count": 1,
            "claims_unconflicted": False,
            "has_claims": True,
            "claims": [],
            "error": str(exc),
        }


def evaluate_candidate(
    raw_input: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    now: datetime | None = None,
    health_states: Mapping[str, str] | None = None,
    registry: Any = None,
    acquisition_run: Any = None,
    fixture_mode: bool | None = None,
) -> dict[str, Any]:
    """Evaluate one candidate with strict input immutability and fail-closed gates."""
    # Ensure input immutability: deepcopy
    candidate = copy.deepcopy(dict(raw_input))

    # Clock resolution: fail closed on missing or malformed timestamp
    clock = None
    clock_error = None
    if now is not None:
        if isinstance(now, datetime):
            clock = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        else:
            try:
                clock = parse_clock(now)
            except Exception as exc:
                clock_error = f"malformed_clock: {exc}"
    else:
        raw_as_of = candidate.get("as_of")
        if not raw_as_of:
            clock_error = "missing_clock"
        else:
            try:
                clock = parse_clock(raw_as_of)
            except Exception as exc:
                clock_error = f"malformed_clock: {exc}"

    ticker = str(candidate.get("ticker") or "UNKNOWN").upper().strip()
    company_name = str(candidate.get("name") or candidate.get("company_name") or ticker).strip()
    exchange = str(candidate.get("exchange") or "UNKNOWN").strip()
    country = str(candidate.get("country") or "US").strip()

    rubric_weights = policy.get("rubric_weights", {})
    penalties_cfg = policy.get("downside_penalties", {})

    # 1. Inspect raw evidence and reconciliation
    claims_check = validate_claim_evidence(
        candidate,
        clock,
        health_states=health_states,
        registry=registry,
        acquisition_run=acquisition_run,
    )

    # 2. Extract supply-chain fields
    declared_role = str(candidate.get("bottleneck_role") or "UNPROVEN").upper().strip()
    scarcity_evidence = candidate.get("scarcity_evidence") or {}
    dependency_evidence = candidate.get("dependency_evidence") or {}
    demand_evidence = candidate.get("demand_evidence") or {}
    pricing_evidence = candidate.get("pricing_evidence") or {}
    company_capture_evidence = candidate.get("company_capture_evidence") or {}
    operating_leverage_evidence = candidate.get("operating_leverage_evidence") or {}
    orders_evidence = candidate.get("backlog_orders_evidence") or candidate.get("orders_evidence") or {}
    catalyst_evidence = candidate.get("catalyst_evidence") or candidate.get("catalysts_6_12_24m") or []
    falsifiers = list(candidate.get("thesis_killers") or candidate.get("falsifiers") or [])
    raw_financing = candidate.get("financing_risk") or candidate.get("equity_capture_status")
    if raw_financing is None:
        financing_state = "STRUCTURAL_DISQUALIFIER"
    else:
        financing_state = str(raw_financing).strip().upper()
        if financing_state not in {"NONE", "MATERIAL_OVERHANG", "STRUCTURAL_DISQUALIFIER", "DESTROYED"}:
            financing_state = "STRUCTURAL_DISQUALIFIER"
    lifecycle = str(candidate.get("lifecycle") or "INSUFFICIENT_EVIDENCE").upper()

    # Reject sole-source label without underlying corroborated scarcity/switching evidence
    has_scarcity_proof = bool(
        scarcity_evidence.get("corroborated_scarcity")
        or (scarcity_evidence.get("effective_suppliers_count") is not None and scarcity_evidence.get("effective_suppliers_count") <= 2)
        or scarcity_evidence.get("switching_time_months", 0) >= 12
    )
    if declared_role in {"SINGLE_SOURCE", "SEMI_MONOPOLY"} and not has_scarcity_proof:
        effective_role = "UNPROVEN"
        declared_role = "UNPROVEN"
    else:
        effective_role = declared_role

    # Reject named customer relationship alone
    customer_only = bool(dependency_evidence.get("customer_relationship_only", False))
    if customer_only and not dependency_evidence.get("irreplaceable_architecture_layer", False):
        dependency_criticality_pts = 0.0
    else:
        dep_val = finite(dependency_evidence.get("score"))
        if dep_val > 0:
            dependency_criticality_pts = min(float(rubric_weights.get("dependency_criticality", 12)), dep_val)
        elif dependency_evidence.get("irreplaceable_architecture_layer"):
            dependency_criticality_pts = 12.0
        elif dependency_evidence.get("high_criticality_subsystem"):
            dependency_criticality_pts = 8.0
        else:
            dependency_criticality_pts = 0.0

    # Qualified scarcity and switching time
    effective_suppliers = scarcity_evidence.get("effective_suppliers_count")
    switching_months = scarcity_evidence.get("switching_time_months", 0)
    shortage_relieved = bool(scarcity_evidence.get("shortage_relieved", False))

    if shortage_relieved:
        scarcity_pts = 0.0
    elif effective_role in {"SINGLE_SOURCE", "SEMI_MONOPOLY"} and switching_months >= 18:
        scarcity_pts = 14.0
    elif effective_suppliers is not None and effective_suppliers <= 2 and switching_months >= 12:
        scarcity_pts = 10.0
    elif switching_months >= 6:
        scarcity_pts = 5.0
    else:
        scarcity_pts = min(float(rubric_weights.get("qualified_scarcity_and_switching", 14)), finite(scarcity_evidence.get("score", 0.0)))

    # Demand acceleration
    demand_pts = min(float(rubric_weights.get("demand_acceleration", 10)), finite(demand_evidence.get("score", 0.0)))
    if demand_pts == 0.0 and demand_evidence.get("structural_acceleration"):
        demand_pts = 10.0 if demand_evidence.get("multi_year_committed") else 7.0

    # Supply constraint (expansion-only rejected if no chokepoint)
    supply_evidence = candidate.get("supply_constraint_evidence") or {}
    expansion_only = bool(supply_evidence.get("expansion_announcement_only", False))
    if expansion_only and not supply_evidence.get("binding_scarcity_proven", False):
        supply_pts = 0.0
    else:
        supply_pts = min(float(rubric_weights.get("supply_constraint", 12)), finite(supply_evidence.get("score", 0.0)))
        if supply_pts == 0.0 and supply_evidence.get("lead_time_weeks", 0) >= 52:
            supply_pts = 12.0
        elif supply_pts == 0.0 and supply_evidence.get("lead_time_weeks", 0) >= 24:
            supply_pts = 8.0

    if shortage_relieved:
        supply_pts = min(supply_pts, 4.0)

    # Pricing power (high gross margin alone rejected)
    high_margin_only = bool(pricing_evidence.get("high_gross_margin_only", False))
    if high_margin_only and not pricing_evidence.get("contractual_or_pricing_power_mechanism", False):
        pricing_pts = 0.0
    else:
        pricing_pts = min(float(rubric_weights.get("pricing_power", 12)), finite(pricing_evidence.get("score", 0.0)))
        if pricing_pts == 0.0 and pricing_evidence.get("contractual_price_increases_documented"):
            pricing_pts = 12.0
        elif pricing_pts == 0.0 and pricing_evidence.get("stable_contract_pricing"):
            pricing_pts = 8.0

    # Company capture
    company_capture_pts = min(float(rubric_weights.get("company_capture", 12)), finite(company_capture_evidence.get("score", 0.0)))
    if company_capture_pts == 0.0 and company_capture_evidence.get("dominant_bom_share") and company_capture_evidence.get("disciplined_financing") and financing_state in {"NONE", "MATERIAL_OVERHANG"}:
        company_capture_pts = 12.0
    elif company_capture_pts == 0.0 and company_capture_evidence.get("disciplined_financing") and financing_state in {"NONE", "MATERIAL_OVERHANG"}:
        company_capture_pts = 8.0

    # Operating leverage
    operating_leverage_pts = min(float(rubric_weights.get("operating_leverage", 10)), finite(operating_leverage_evidence.get("score", 0.0)))
    if operating_leverage_pts == 0.0 and operating_leverage_evidence.get("incremental_margin_gt_40pct"):
        operating_leverage_pts = 10.0
    elif operating_leverage_pts == 0.0 and operating_leverage_evidence.get("demonstrated_margin_expansion"):
        operating_leverage_pts = 7.0

    # Catalyst & Timing (6-36M)
    cat_pts = 0.0
    dated_catalysts = []
    if isinstance(catalyst_evidence, list):
        for item in catalyst_evidence:
            if isinstance(item, dict):
                timing = str(item.get("timing") or "")
                desc = str(item.get("catalyst") or item.get("description") or "")
                status = str(item.get("status") or "DATED").upper()
                if desc and timing in {"6M", "12M", "18M", "24M", "36M"}:
                    dated_catalysts.append({"timing": timing, "catalyst": desc, "status": status})
                    if timing in {"6M", "12M", "18M"} and cat_pts < 10.0:
                        cat_pts = 10.0
                    elif timing in {"24M", "36M"} and cat_pts < 7.0:
                        cat_pts = 7.0
    cat_pts = max(cat_pts, min(float(rubric_weights.get("catalyst_and_timing", 10)), finite(candidate.get("catalyst_score", 0.0))))

    # Order & Commitment support
    order_pts = min(float(rubric_weights.get("order_and_commitment_support", 8)), finite(orders_evidence.get("score", 0.0)))
    order_type = str(orders_evidence.get("order_support_type") or "NONE").upper()
    if order_pts == 0.0:
        if order_type in {"BINDING_CONTRACT", "TAKE_OR_PAY", "PREPAYMENT"}:
            order_pts = 8.0
        elif order_type in {"BACKLOG", "CONFIRMED_ORDER_BOOK"}:
            order_pts = 5.0
        elif order_type in {"DESIGN_WIN", "LOI"}:
            order_pts = 2.0

    # Raw factor sum
    factor_authority = reconcile_factor_authority(
        candidate,
        claims_check.get("claims", []),
        ticker,
        fixture_mode=fixture_mode,
    )
    enforce_factor_claims = bool(policy.get("factor_claim_authority", {}).get("enforce_factor_claim_bindings", False))
    if enforce_factor_claims:
        if not factor_authority.get("dependency_licensed"):
            dependency_criticality_pts = 0.0
        if not factor_authority.get("scarcity_licensed"):
            scarcity_pts = 0.0
        if not factor_authority.get("pricing_licensed"):
            pricing_pts = 0.0
        if not factor_authority.get("capture_licensed"):
            company_capture_pts = 0.0

    raw_factor_score = (
        dependency_criticality_pts
        + scarcity_pts
        + demand_pts
        + supply_pts
        + pricing_pts
        + company_capture_pts
        + operating_leverage_pts
        + cat_pts
        + order_pts
    )

    # 3. Downside Penalties
    risks_disclosed = candidate.get("risks_disclosed")
    missing_risk_disclosure = risks_disclosed is False or (
        risks_disclosed is None and not candidate.get("risk_factors") and not candidate.get("disclosed_risks")
    )

    penalty = 0.0
    risk_flags = []

    if clock_error:
        penalty += 20.0
        risk_flags.append("missing_or_invalid_clock")

    # Financing / Dilution penalty
    if financing_state == "DESTROYED":
        penalty += 100.0
        risk_flags.append("financing_equity_capture_destroyed")
    elif financing_state == "STRUCTURAL_DISQUALIFIER":
        penalty += float(penalties_cfg.get("dilution_financing_risk", {}).get("STRUCTURAL_DISQUALIFIER", 10.0))
        risk_flags.append("structural_dilution_risk")
    elif financing_state == "MATERIAL_OVERHANG":
        penalty += float(penalties_cfg.get("dilution_financing_risk", {}).get("MATERIAL_OVERHANG", 5.0))
        risk_flags.append("material_financing_overhang")

    # Unprotected customer concentration
    cust_conc = candidate.get("customer_concentration") or {}
    if cust_conc.get("severe_unprotected"):
        penalty += float(penalties_cfg.get("unprotected_customer_concentration", {}).get("SEVERE_UNPROTECTED_CONCENTRATION", 6.0))
        risk_flags.append("severe_unprotected_customer_concentration")
    elif cust_conc.get("moderate"):
        penalty += float(penalties_cfg.get("unprotected_customer_concentration", {}).get("MODERATE_CONCENTRATION", 3.0))
        risk_flags.append("moderate_customer_concentration")

    # Unexplained revenue deterioration
    if candidate.get("unexplained_revenue_deterioration"):
        penalty += float(penalties_cfg.get("unexplained_revenue_deterioration", {}).get("ORGANIC_DECLINE", 6.0))
        risk_flags.append("unexplained_revenue_deterioration")

    # Export / policy concentration
    if candidate.get("severe_export_policy_risk"):
        penalty += float(penalties_cfg.get("export_or_policy_concentration", {}).get("SEVERE_UNMITIGATED_EXPORT_RISK", 6.0))
        risk_flags.append("severe_unmitigated_export_risk")
    elif candidate.get("moderate_export_policy_risk"):
        penalty += float(penalties_cfg.get("export_or_policy_concentration", {}).get("MODERATE_GEOPOLITICAL_EXPOSURE", 3.0))
        risk_flags.append("moderate_geopolitical_risk")

    # Valuation downside / crowding
    if candidate.get("extreme_valuation_crowding"):
        penalty += float(penalties_cfg.get("valuation_downside_crowding", {}).get("EXTREME_CROWDING_VALUATION", 5.0))
        risk_flags.append("extreme_crowding_valuation")
    elif candidate.get("high_expectations"):
        penalty += float(penalties_cfg.get("valuation_downside_crowding", {}).get("HIGH_EXPECTATIONS", 2.0))
        risk_flags.append("high_valuation_expectations")

    # Missing risk disclosure penalty (missing risk must not mean zero risk)
    if missing_risk_disclosure:
        penalty += float(penalties_cfg.get("missing_risk_disclosure", {}).get("OMITTED_RISK_DISCLOSURE", 5.0))
        risk_flags.append("omitted_risk_disclosure_penalty")

    if claims_check.get("conflict_count", 0) > 0 or not claims_check.get("claims_unconflicted", True):
        penalty += 15.0
        risk_flags.append("unresolved_material_claim_conflicts")

    final_score = max(0.0, min(100.0, raw_factor_score - penalty))

    # 4. Critical Admission Gates
    is_disqualified_financing = financing_state == "DESTROYED"
    is_broken_lifecycle = lifecycle == "BROKEN"
    has_conflicts = claims_check.get("conflict_count", 0) > 0 or not claims_check.get("claims_unconflicted", True)
    has_verified_claims = (
        claims_check.get("has_claims", False)
        and claims_check.get("all_supported", False)
        and claims_check.get("claims_unconflicted", True)
        and claims_check.get("conflict_count", 0) == 0
    )

    has_role = effective_role in {"SINGLE_SOURCE", "SEMI_MONOPOLY", "QUALIFICATION_CONSTRAINED", "CAPACITY_BOTTLENECK"}
    has_scarcity = scarcity_pts > 0.0
    has_demand = demand_pts > 0.0
    has_capture_or_pricing = (pricing_pts > 0.0 or company_capture_pts > 0.0)
    has_catalyst = cat_pts > 0.0
    has_falsifiers = len(falsifiers) > 0

    core_factors_ok = (not enforce_factor_claims) or factor_authority.get("core_admitted", False)

    all_pillars_present = (
        has_verified_claims
        and core_factors_ok
        and has_role
        and has_scarcity
        and has_demand
        and has_capture_or_pricing
        and has_catalyst
        and has_falsifiers
        and not is_disqualified_financing
        and not is_broken_lifecycle
        and not has_conflicts
        and clock_error is None
    )

    if is_disqualified_financing:
        admission_status = "DISQUALIFIED_FINANCING_DESTROYED"
        final_lifecycle = "BROKEN"
    elif is_broken_lifecycle:
        admission_status = "DISQUALIFIED_THESIS_BROKEN"
        final_lifecycle = "BROKEN"
    elif not all_pillars_present:
        admission_status = "UNRANKED_INSUFFICIENT_EVIDENCE"
        final_lifecycle = "INSUFFICIENT_EVIDENCE" if lifecycle not in {"COMMERCIAL_VALIDATION", "EARLY_VALIDATION"} else lifecycle
    else:
        admission_status = "ADMITTED"
        final_lifecycle = lifecycle if lifecycle in {"DISCOVERY", "EARLY_VALIDATION", "COMMERCIAL_VALIDATION", "INSTITUTIONAL_VALIDATION", "CONSENSUS"} else "COMMERCIAL_VALIDATION"

    # Multi-axis evidence confidence
    conf_axes = candidate.get("evidence_confidence") or {}
    confidence = {
        "factual_evidence_confidence": str(conf_axes.get("factual_evidence_confidence") or ("HIGH" if claims_check.get("all_supported") else "MEDIUM" if claims_check.get("supported_count", 0) > 0 else "LOW")),
        "dependency_confidence": str(conf_axes.get("dependency_confidence") or ("HIGH" if has_scarcity and has_role else "LOW")),
        "company_capture_confidence": str(conf_axes.get("company_capture_confidence") or ("HIGH" if company_capture_pts >= 8.0 and not is_disqualified_financing else "LOW")),
        "timing_confidence": str(conf_axes.get("timing_confidence") or ("HIGH" if has_catalyst else "LOW")),
        "identity_confidence": str(conf_axes.get("identity_confidence") or ("HIGH" if exchange != "UNKNOWN" else "MEDIUM")),
    }

    # Data quality calculation
    dq_val = finite(candidate.get("data_quality"))
    if dq_val <= 0.0:
        dq_val = 0.90 if claims_check.get("all_supported") else 0.70 if all_pillars_present else 0.40

    # Historical returns context: strictly DISPLAY / CONTEXT ONLY. 0 positive score influence!
    hist_ctx = candidate.get("historical_returns_context") or {}
    long_term_ret = candidate.get("long_term_return_pct") if candidate.get("long_term_return_pct") is not None else hist_ctx.get("long_term_return_pct")
    short_term_ret = candidate.get("short_term_return_pct") if candidate.get("short_term_return_pct") is not None else hist_ctx.get("short_term_return_pct")

    # Ensure rank rationale provides transparent diagnosis
    rank_rationale = (
        f"{ticker} ({company_name}): role={effective_role}, raw={raw_factor_score:.1f}, "
        f"penalty={penalty:.1f}, score={final_score:.1f}, status={admission_status}, "
        f"lifecycle={final_lifecycle}."
    )

    is_admitted = (admission_status == "ADMITTED")

    evaluation = {
        "ticker": ticker,
        "company_name": company_name,
        "exchange": exchange,
        "country": country,
        "bottleneck_role": effective_role,
        "dependency_criticality": {
            "score": round(dependency_criticality_pts, 2),
            "max_score": int(rubric_weights.get("dependency_criticality", 12)),
            "assessment": str(dependency_evidence.get("assessment") or "Architecture dependency assessment"),
            "layer": str(dependency_evidence.get("layer") or "Unspecified layer"),
            "provenance": "SOURCE_DERIVED_FACT" if dependency_criticality_pts > 0 else "UNKNOWN",
            "contribution_breakdown": f"awarded {dependency_criticality_pts:.1f} / {rubric_weights.get('dependency_criticality', 12)} pts based on layer necessity",
        },
        "effective_vs_qualified_substitutes": {
            "qualified_supplier_count": effective_suppliers if effective_suppliers is not None else 0,
            "effective_supplier_count": effective_suppliers if effective_suppliers is not None else 0,
            "switching_time_months": switching_months,
            "details": str(scarcity_evidence.get("details") or "Substitute availability and friction"),
            "provenance": "SOURCE_DERIVED_FACT" if scarcity_pts > 0 else "UNKNOWN",
        },
        "substitution_time": f"{switching_months} months" if switching_months else "Unknown",
        "demand_acceleration": {
            "score": round(demand_pts, 2),
            "max_score": int(rubric_weights.get("demand_acceleration", 10)),
            "assessment": str(demand_evidence.get("assessment") or "Structural demand acceleration"),
            "horizon_months": int(demand_evidence.get("horizon_months") or 24),
            "provenance": "SOURCE_DERIVED_FACT" if demand_pts > 0 else "UNKNOWN",
            "contribution_breakdown": f"awarded {demand_pts:.1f} / {rubric_weights.get('demand_acceleration', 10)} pts",
        },
        "supply_constraint": {
            "score": round(supply_pts, 2),
            "max_score": int(rubric_weights.get("supply_constraint", 12)),
            "assessment": str(supply_evidence.get("assessment") or "Supply barrier assessment"),
            "binding_constraint": str(supply_evidence.get("binding_constraint") or "Tooling / physical lead times"),
            "provenance": "SOURCE_DERIVED_FACT" if supply_pts > 0 else "UNKNOWN",
            "contribution_breakdown": f"awarded {supply_pts:.1f} / {rubric_weights.get('supply_constraint', 12)} pts",
        },
        "pricing_power": {
            "score": round(pricing_pts, 2),
            "max_score": int(rubric_weights.get("pricing_power", 12)),
            "assessment": str(pricing_evidence.get("assessment") or "Contractual pricing mechanism"),
            "pricing_mechanism": str(pricing_evidence.get("mechanism") or "Contractual / market"),
            "provenance": "SOURCE_DERIVED_FACT" if pricing_pts > 0 else "UNKNOWN",
            "contribution_breakdown": f"awarded {pricing_pts:.1f} / {rubric_weights.get('pricing_power', 12)} pts",
        },
        "company_capture": {
            "score": round(company_capture_pts, 2),
            "max_score": int(rubric_weights.get("company_capture", 12)),
            "assessment": str(company_capture_evidence.get("assessment") or "Shareholder value capture"),
            "equity_capture_status": financing_state if financing_state != "DESTROYED" else "DESTROYED",
            "provenance": "SOURCE_DERIVED_FACT" if company_capture_pts > 0 else "UNKNOWN",
            "contribution_breakdown": f"awarded {company_capture_pts:.1f} / {rubric_weights.get('company_capture', 12)} pts",
        },
        "backlog_orders": {
            "score": round(order_pts, 2),
            "max_score": int(rubric_weights.get("order_and_commitment_support", 8)),
            "current_backlog_or_orders": str(orders_evidence.get("current_orders") or "未揭露（無可靠公開訂單數字）"),
            "future_order_estimate": str(orders_evidence.get("future_orders_estimate") or "無可靠公開預估"),
            "order_support_type": order_type,
            "provenance": "SOURCE_DERIVED_FACT" if order_pts > 0 else "UNKNOWN",
            "contribution_breakdown": f"awarded {order_pts:.1f} / {rubric_weights.get('order_and_commitment_support', 8)} pts",
        },
        "catalysts_6_12_24m": dated_catalysts if dated_catalysts else [{"timing": "12M", "catalyst": "None evidenced", "status": "UNKNOWN"}],
        "operating_leverage": {
            "score": round(operating_leverage_pts, 2),
            "max_score": int(rubric_weights.get("operating_leverage", 10)),
            "assessment": str(operating_leverage_evidence.get("assessment") or "Operating leverage assessment"),
            "provenance": "SOURCE_DERIVED_FACT" if operating_leverage_pts > 0 else "UNKNOWN",
            "contribution_breakdown": f"awarded {operating_leverage_pts:.1f} / {rubric_weights.get('operating_leverage', 10)} pts",
        },
        "thesis_killers": falsifiers if falsifiers else ["None disclosed"],
        "lifecycle": final_lifecycle,
        "evidence_confidence": confidence,
        "system_bottleneck_explosion_score": round(final_score, 2),
        "raw_factor_score": round(raw_factor_score, 2),
        "downside_penalty": round(penalty, 2),
        "data_quality": round(dq_val, 4),
        "admission_status": admission_status,
        "rank": None,
        "score_qualified": True if is_admitted else None,
        "candidate_assessment_mode": "RANKING_QUALIFIED" if is_admitted else "CANDIDATE_ONLY",
        "risk_flags": sorted(set(risk_flags)),
        "rank_rationale": rank_rationale,
        "historical_returns_context": {
            "long_term_return_pct": long_term_ret,
            "short_term_return_pct": short_term_ret,
            "window_long": "2y_cagr",
            "window_short": "6m_price_return",
            "influence_on_score": 0.0,
            "usage": "DISPLAY_AND_RISK_CONTEXT_ONLY",
        },
        "claims_audit": {
            "supported_claim_count": claims_check.get("supported_count", 0),
            "conflicted_claim_count": claims_check.get("conflict_count", 0),
            "all_material_claims_supported": claims_check.get("all_supported", False),
            "claims_unconflicted": claims_check.get("claims_unconflicted", True),
            "has_claims": claims_check.get("has_claims", False),
        },
        "factor_claim_authority": factor_authority,
        "scoring_version": "system-bottleneck-explosion-v1",
        "as_of": clock.replace(microsecond=0).isoformat() if clock is not None else None,
    }
    return evaluation


def rank_bottleneck_candidates(
    candidates: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any] | None = None,
    *,
    top_count: int = 20,
    as_of: datetime | str | None = None,
    health_states: Mapping[str, str] | None = None,
    registry: Any = None,
    acquisition_run: Any = None,
    fixture_mode: bool | None = None,
) -> dict[str, Any]:
    """Rank candidates with deterministic cardinality, fail-closed admission, and no lexical/zero backfill.

    Evidence mode: ``fixture_mode`` is threaded into the claim-admission
    bridge so licensed test-only promotion can be requested explicitly.
    The production path (None) keeps the bridge auto-detect rule and defers
    all real-host candidates with no signed acquisition context.
    """
    active_policy = policy if policy is not None else load_json(POLICY_DEFAULT_PATH)
    clock = None
    if as_of is not None:
        if isinstance(as_of, datetime):
            clock = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=timezone.utc)
        else:
            clock = parse_clock(as_of)

    evaluated = [
        evaluate_candidate(
            c,
            active_policy,
            now=clock,
            health_states=health_states,
            registry=registry,
            acquisition_run=acquisition_run,
            fixture_mode=fixture_mode,
        )
        for c in candidates
    ]

    # Additive runtime-promotion visibility (no gate or score change):
    # every evaluated record exposes whether the candidate is an admitted,
    # runtime-advancing company record under the evidence mode in force.
    for item in evaluated:
        item["runtime_admitted"] = item["admission_status"] == "ADMITTED"

    admitted = [e for e in evaluated if e["admission_status"] == "ADMITTED"]
    unranked = [e for e in evaluated if e["admission_status"] != "ADMITTED"]

    # Ensure unranked candidates explicitly hold null rank and null score_qualified
    for item in unranked:
        item["rank"] = None
        item["score_qualified"] = None
        item["candidate_assessment_mode"] = "CANDIDATE_ONLY"

    # Deterministic tie break applies ONLY after admission
    admitted.sort(
        key=lambda item: (
            -float(item["system_bottleneck_explosion_score"]),
            -float(item["data_quality"]),
            str(item["ticker"]),
        )
    )

    ranked_records = []
    admitted_overflow = []
    for idx, item in enumerate(admitted):
        record = copy.deepcopy(item)
        record["score_qualified"] = True
        record["candidate_assessment_mode"] = "RANKING_QUALIFIED"
        if idx < top_count:
            record["rank"] = idx + 1
            ranked_records.append(record)
        else:
            record["rank"] = None
            admitted_overflow.append(record)

    gen_time = clock.replace(microsecond=0).isoformat() if clock is not None else None

    return {
        "schema_version": 1,
        "policy_id": active_policy.get("policy_id", "system-bottleneck-explosion-v1"),
        "publication_status": "NOT_PUBLICATION_QUALIFIED",
        "live_qualification": "DEFERRED",
        "candidate_assessment": "OFFLINE_NON_PUBLICATION",
        "generated_at": gen_time,
        "total_evaluated": len(evaluated),
        "admitted_count": len(admitted),
        "ranked_count": len(ranked_records),
        "unranked_count": len(unranked),
        "ranked_candidates": ranked_records,
        "low_confidence_watchlist": unranked,
        "admitted_overflow": admitted_overflow,
        "cardinality_rules": {
            "top_count": top_count,
            "zero_padding_used": False,
            "lexical_backfill_used": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="System Bottleneck Explosion Ranking v1")
    parser.add_argument("--input", required=True, help="Path to input candidates JSON")
    parser.add_argument("--policy", default=str(POLICY_DEFAULT_PATH), help="Path to policy JSON")
    parser.add_argument("--output", help="Path to output JSON")
    parser.add_argument("--as-of", help="Evaluation clock timestamp")
    parser.add_argument("--top-count", type=int, default=20, help="Max ranked candidates (default 20)")
    parser.add_argument(
        "--multilineage-bundle", action="store_true",
        help="merge the verified multi-lineage evidence bundle as runtime candidates (test-only evidence mode)")
    args = parser.parse_args()

    input_path = Path(args.input)
    policy_path = Path(args.policy)

    raw_candidates = load_json(input_path)
    if isinstance(raw_candidates, dict):
        raw_candidates = raw_candidates.get("candidates") or raw_candidates.get("records") or [raw_candidates]
    if not isinstance(raw_candidates, list):
        raise BottleneckRankingError("Input JSON must be an array or contain 'candidates'/'records'")

    policy_obj = load_json(policy_path)
    clock = parse_clock(args.as_of) if args.as_of else None

    multilineage = bool(args.multilineage_bundle)
    registry_obj = None
    bundle_health = None
    bundle_candidates: list = []
    if multilineage:
        import multilineage_claim_bundle as mlb
        mlb.verify_corpus_anchors()  # fail closed on corpus drift
        registry_obj = mlb.build_registry()
        bundle_health = mlb.health_for(registry_obj)
        bundle_candidates = list(mlb.bundled_candidates().values())

    result = rank_bottleneck_candidates(
        list(raw_candidates) + bundle_candidates,
        policy=policy_obj,
        top_count=args.top_count,
        as_of=clock,
        registry=registry_obj,
        health_states=bundle_health,
        fixture_mode=True if multilineage else None,
    )
    result["evidence_mode"] = "TEST_ONLY_FIXTURE" if multilineage else "PRODUCTION"
    if multilineage:
        result["multilineage_bundle"] = True
        result["multilineage_bundle_candidates"] = [c["ticker"] for c in bundle_candidates]
        result["promotion_basis"] = "TEST_ONLY_FIXTURE" if result["admitted_count"] else "NONE"

    output_str = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_str, encoding="utf-8")
        print(f"Wrote bottleneck ranking to {out_path} (ranked: {result['ranked_count']}, unranked: {result['unranked_count']})")
    else:
        print(output_str)


if __name__ == "__main__":
    main()
