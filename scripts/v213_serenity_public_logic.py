#!/usr/bin/env python3
"""Serenity public-logic high-fidelity reconstruction.

This module intentionally does NOT implement or claim an official Serenity score.
It converts evidence-bound public signals into auditable thesis states while
keeping the legacy quantitative ranking separate as a project-authored overlay.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "v213-serenity-public-logic-policy.json"
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")
HTTPS_RE = re.compile(r"^https://", re.I)


class FidelityError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidenceSummary:
    primary: int
    corroborating: int
    lead_only: int
    urls: tuple[str, ...]
    tiers_by_url: Mapping[str, str]


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FidelityError(f"Invalid fidelity policy: {path}") from exc
    if not isinstance(value, dict):
        raise FidelityError("Fidelity policy must be an object")
    if value.get("schema_version") != 2 or value.get("product_version") != "2.1.3":
        raise FidelityError("Unexpected fidelity policy schema/product version")
    if value.get("methodology") != "serenity-public-logic-high-fidelity-reconstruction":
        raise FidelityError("Unexpected fidelity methodology")
    if value.get("attribution_boundary") != "public_source_only_not_private_process":
        raise FidelityError("Attribution boundary is not fail-closed")
    if value.get("legacy_quantitative_overlay_label") != "System operationalization score":
        raise FidelityError("Legacy quantitative overlay is mislabeled")
    fail_closed = value.get("fail_closed")
    if not isinstance(fail_closed, dict) or not fail_closed or not all(fail_closed.values()):
        raise FidelityError("Fidelity fail-closed policy is incomplete")

    killers = set(value.get("thesis_killers") or [])
    severe = set(value.get("severe_break_signals") or [])
    if not severe or not severe.issubset(killers):
        raise FidelityError("Every severe-break signal must also be an allowed thesis killer")
    dependency = set(value.get("dependency_signals") or [])
    bottleneck = set(value.get("bottleneck_proving_signals") or [])
    if not bottleneck or not bottleneck.issubset(dependency):
        raise FidelityError("Bottleneck-proving signals must be a subset of dependency signals")
    if "customer_named_dependency" in bottleneck:
        raise FidelityError("Customer-named dependency alone must not prove a bottleneck")
    return value


def _clean_ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text if TICKER_RE.fullmatch(text) else ""


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _normalize_tier(value: Any) -> str:
    tier = str(value or "").strip().casefold()
    if tier in {"primary", "primary_strong", "t0", "t1"}:
        return "primary_strong"
    if tier in {"corroborating", "secondary", "t2"}:
        return "corroborating"
    return "lead_only"


def _evidence_summary(rows: Any) -> EvidenceSummary:
    primary = 0
    corroborating = 0
    lead_only = 0
    urls: list[str] = []
    tiers: dict[str, str] = {}
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        rows = []
    strength = {"lead_only": 0, "corroborating": 1, "primary_strong": 2}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        tier = _normalize_tier(row.get("tier"))
        if tier == "primary_strong":
            primary += 1
        elif tier == "corroborating":
            corroborating += 1
        else:
            lead_only += 1
        url = str(row.get("url") or "").strip()
        if HTTPS_RE.match(url):
            if url not in urls:
                urls.append(url)
            current = tiers.get(url)
            if current is None or strength[tier] > strength[current]:
                tiers[url] = tier
    return EvidenceSummary(primary, corroborating, lead_only, tuple(urls), tiers)


def _iso_sort_key(value: str) -> tuple[int, str]:
    text = value.strip()
    if not text:
        return (1, "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (0, parsed.isoformat())
    except ValueError:
        return (1, text)


def _validate_signal_claims(
    record: Mapping[str, Any],
    *,
    allowed: set[str],
    claimed: set[str],
    evidence: EvidenceSummary,
) -> tuple[set[str], set[str], list[str]]:
    unknown = claimed - allowed
    if unknown:
        raise FidelityError("Unknown public-logic signals: " + ", ".join(sorted(unknown)))
    bindings = record.get("signal_evidence")
    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes, bytearray)):
        bindings = []
    supported: set[str] = set()
    lead_only: set[str] = set()
    warnings: list[str] = []
    for signal in sorted(claimed):
        matched = []
        for row in bindings:
            if not isinstance(row, Mapping) or str(row.get("signal") or "").strip() != signal:
                continue
            url = str(row.get("evidence_url") or "").strip()
            if not HTTPS_RE.match(url):
                continue
            if url not in evidence.tiers_by_url:
                continue
            matched.append(evidence.tiers_by_url[url])
        if any(tier in {"primary_strong", "corroborating"} for tier in matched):
            supported.add(signal)
        elif matched:
            lead_only.add(signal)
            warnings.append(f"Signal {signal} has lead-only evidence and is not used as proof")
        else:
            warnings.append(f"Signal {signal} lacks evidence binding and is not used as proof")
    return supported, lead_only, warnings


def _validate_architecture(record: Mapping[str, Any], evidence: EvidenceSummary) -> tuple[dict[str, Any], bool, list[str]]:
    raw = record.get("architecture")
    if not isinstance(raw, Mapping):
        return {}, False, ["Architecture/supercycle map is missing"]
    architecture = dict(raw)
    has_identity = bool(str(architecture.get("current") or architecture.get("cycle") or "").strip())
    urls = architecture.get("evidence_urls")
    if not isinstance(urls, Sequence) or isinstance(urls, (str, bytes, bytearray)):
        urls = []
    bound = [str(url) for url in urls if str(url) in evidence.tiers_by_url]
    strong = any(evidence.tiers_by_url[url] in {"primary_strong", "corroborating"} for url in bound)
    warnings: list[str] = []
    if not has_identity:
        warnings.append("Architecture/supercycle identity is missing")
    if not strong:
        warnings.append("Architecture/supercycle claim lacks primary/corroborating evidence binding")
    return architecture, bool(has_identity and strong), warnings


def _validate_graph(record: Mapping[str, Any], evidence: EvidenceSummary) -> tuple[list[dict[str, Any]], bool, bool, list[str]]:
    raw = record.get("supply_chain_graph")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raw = []
    valid: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, row in enumerate(raw):
        if not isinstance(row, Mapping):
            warnings.append(f"Supply-chain edge {index + 1} is not structured")
            continue
        edge = dict(row)
        source = str(edge.get("from") or "").strip()
        target = str(edge.get("to") or "").strip()
        relationship = str(edge.get("relationship") or "").strip()
        url = str(edge.get("evidence_url") or "").strip()
        as_of = str(edge.get("as_of") or "").strip()
        tier = evidence.tiers_by_url.get(url)
        if not source or not target or not relationship or not as_of or tier not in {"primary_strong", "corroborating"}:
            warnings.append(f"Supply-chain edge {index + 1} is incomplete or lacks bound evidence")
            continue
        valid.append(edge)
    focal = str(record.get("focal_company_node") or record.get("ticker") or "").strip().casefold()
    touches_focal = any(
        focal and focal in {str(edge.get("from") or "").strip().casefold(), str(edge.get("to") or "").strip().casefold()}
        for edge in valid
    )
    if not valid:
        warnings.append("Supply-chain graph has no evidence-bound edges")
    if valid and not touches_focal:
        warnings.append("Supply-chain graph does not contain an evidence-bound edge touching the focal company node")
    return valid, bool(valid), touches_focal, warnings


def _dependency_role(signals: set[str], beneficiary_signal: bool) -> str:
    if "single_source" in signals:
        return "SINGLE_SOURCE"
    if "semi_monopoly" in signals:
        return "SEMI_MONOPOLY"
    if signals & {"qualified_supplier_concentration", "qualification_constraint"}:
        return "QUALIFICATION_CONSTRAINED"
    if "binding_capacity" in signals:
        return "CAPACITY_BOTTLENECK"
    if "unique_process_or_ip" in signals:
        return "QUALIFICATION_CONSTRAINED"
    # A customer-named dependency is useful linkage evidence but does not by
    # itself prove scarcity, qualification friction, or a chokepoint.
    if beneficiary_signal:
        return "BENEFICIARY"
    return "UNPROVEN"


def _information_gap(record: Mapping[str, Any], evidence: EvidenceSummary) -> tuple[str, list[str]]:
    info = record.get("information_gap")
    if not isinstance(info, Mapping):
        return "UNKNOWN", []
    urls = info.get("evidence_urls")
    if not isinstance(urls, Sequence) or isinstance(urls, (str, bytes, bytearray)):
        urls = []
    supported = any(
        evidence.tiers_by_url.get(str(url)) in {"primary_strong", "corroborating"}
        for url in urls
    )
    if not supported:
        return "UNKNOWN", ["Information-gap state lacks primary/corroborating evidence binding"]
    explicit = str(info.get("state") or "").strip().upper()
    allowed = {"UNDISCOVERED", "EARLY_DISCOVERY", "BECOMING_KNOWN", "CONSENSUS", "UNKNOWN"}
    if explicit in allowed:
        return explicit, []
    coverage = str(info.get("coverage") or "").strip().casefold()
    institutional = bool(info.get("institutional_validation"))
    if coverage in {"none", "very_low", "low"} and not institutional:
        return "UNDISCOVERED", []
    if coverage in {"limited"}:
        return "EARLY_DISCOVERY", []
    if institutional or coverage in {"rising", "moderate"}:
        return "BECOMING_KNOWN", []
    if coverage in {"high", "consensus"}:
        return "CONSENSUS", []
    return "UNKNOWN", []


def _company_capture(record: Mapping[str, Any], evidence: EvidenceSummary, policy: Mapping[str, Any]) -> tuple[dict[str, Any], str, list[str]]:
    raw = record.get("company_capture")
    if not isinstance(raw, Mapping):
        return {"state": "UNPROVEN"}, "UNPROVEN", ["Company-capture analysis is missing"]
    capture = dict(raw)
    state = str(capture.get("state") or "UNPROVEN").strip().upper()
    allowed = set(policy["company_capture_states"])
    if state not in allowed:
        raise FidelityError(f"Unknown company-capture state: {state}")
    urls = capture.get("evidence_urls")
    if not isinstance(urls, Sequence) or isinstance(urls, (str, bytes, bytearray)):
        urls = []
    supported = any(
        evidence.tiers_by_url.get(str(url)) in {"primary_strong", "corroborating"}
        for url in urls
    )
    warnings: list[str] = []
    if state != "UNPROVEN" and not supported:
        warnings.append(f"Company-capture state {state} lacks evidence binding and is downgraded to UNPROVEN")
        state = "UNPROVEN"
    capture["state"] = state
    return capture, state, warnings


def _thesis_class(
    dependency_role: str,
    *,
    architecture_valid: bool,
    graph_valid: bool,
    graph_touches_focal: bool,
    expansion_signals: set[str],
) -> str:
    hard_dependency = dependency_role in {
        "SINGLE_SOURCE", "SEMI_MONOPOLY", "QUALIFICATION_CONSTRAINED",
        "CAPACITY_BOTTLENECK",
    }
    bottleneck_ready = hard_dependency and architecture_valid and graph_valid and graph_touches_focal
    expansion = bool(expansion_signals)
    if bottleneck_ready and expansion:
        return "HYBRID"
    if bottleneck_ready:
        return "BOTTLENECK_THESIS"
    if expansion:
        return "EXPANSION_THESIS"
    return "UNPROVEN"


def _thesis_state(
    *,
    dependency_role: str,
    thesis_class: str,
    information_gap: str,
    evidence: EvidenceSummary,
    commercial_signals: set[str],
    institutional_signals: set[str],
    killers: set[str],
    severe_break_signals: set[str],
    capture_state: str,
) -> str:
    if killers & severe_break_signals or capture_state == "DESTROYED":
        return "BROKEN"
    if killers or capture_state == "WEAK":
        return "THESIS_WEAKENING"
    if evidence.primary + evidence.corroborating == 0:
        return "INSUFFICIENT_EVIDENCE"
    commercial = bool(commercial_signals)
    institutional = bool(institutional_signals)
    hard_dependency = dependency_role in {
        "SINGLE_SOURCE", "SEMI_MONOPOLY", "QUALIFICATION_CONSTRAINED",
        "CAPACITY_BOTTLENECK",
    }
    if information_gap == "CONSENSUS" and commercial:
        return "CONSENSUS"
    if commercial and institutional:
        return "INSTITUTIONAL_VALIDATION"
    if commercial:
        return "COMMERCIAL_VALIDATION"
    if hard_dependency and thesis_class in {"BOTTLENECK_THESIS", "HYBRID"}:
        return "EARLY_VALIDATION"
    if thesis_class != "UNPROVEN":
        return "DISCOVERY"
    return "INSUFFICIENT_EVIDENCE"


def _timing(record: Mapping[str, Any]) -> dict[str, str]:
    raw = record.get("timing")
    if not isinstance(raw, Mapping):
        raw = {}
    return {
        "operating_thesis_horizon": str(raw.get("operating_thesis_horizon") or "unknown"),
        "architecture_ramp_window": str(raw.get("architecture_ramp_window") or "unknown"),
        "entry_context": str(raw.get("entry_context") or "unknown"),
        "valuation_expectation_context": str(raw.get("valuation_expectation_context") or "unknown"),
    }


def _validated_source_views(record: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows = record.get("serenity_source_views")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return [], []
    allowed_stance = set(policy["source_delta_stances"])
    allowed_retrieval = set(policy["source_delta_retrieval_states"])
    valid: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            warnings.append(f"Serenity source view {index + 1} is not structured")
            continue
        item = dict(row)
        url = str(item.get("url") or "").strip()
        stance = str(item.get("stance") or "unknown").strip().casefold()
        retrieval = str(item.get("retrieval_status") or "unavailable").strip().casefold()
        if not HTTPS_RE.match(url) or stance not in allowed_stance or retrieval not in allowed_retrieval:
            warnings.append(f"Serenity source view {index + 1} has invalid URL/stance/retrieval state")
            continue
        if retrieval == "retrieved" and not str(item.get("source_view") or "").strip():
            warnings.append(f"Serenity source view {index + 1} is retrieved but has no paraphrased source view")
            continue
        valid.append(item)
    return valid, warnings


def _validated_source_delta(record: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows = record.get("source_delta")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return [], []
    required = set(policy["source_delta_required_fields"])
    allowed_stance = set(policy["source_delta_stances"])
    allowed_retrieval = set(policy["source_delta_retrieval_states"])
    valid: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    previous_key: tuple[int, str] | None = None
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not required.issubset(row.keys()):
            warnings.append(f"Source-delta item {index + 1} is incomplete")
            continue
        item = dict(row)
        url = str(item.get("url") or "").strip()
        published = str(item.get("published_at") or "").strip()
        stance = str(item.get("stance") or "").strip().casefold()
        retrieval = str(item.get("retrieval_status") or "").strip().casefold()
        if not HTTPS_RE.match(url) or stance not in allowed_stance or retrieval not in allowed_retrieval:
            warnings.append(f"Source-delta item {index + 1} has invalid URL/stance/retrieval state")
            continue
        identity = (url, published)
        if identity in seen:
            warnings.append(f"Source-delta item {index + 1} duplicates an earlier source view")
            continue
        seen.add(identity)
        key = _iso_sort_key(published)
        if previous_key is not None and key < previous_key:
            raise FidelityError("Source-delta items must be chronological within a snapshot")
        previous_key = key
        valid.append(item)
    return valid, warnings


def _confidence(*, thesis_class: str, evidence: EvidenceSummary, architecture_valid: bool, graph_valid: bool, graph_touches_focal: bool, warnings: Sequence[str]) -> dict[str, Any]:
    reasons: list[str] = []
    if thesis_class == "UNPROVEN":
        reasons.append("thesis_class_unproven")
    if evidence.primary == 0:
        reasons.append("no_primary_evidence")
    if not architecture_valid:
        reasons.append("architecture_not_evidence_bound")
    if not graph_valid or not graph_touches_focal:
        reasons.append("supply_chain_graph_incomplete")
    if warnings:
        reasons.append("validation_warnings_present")
    if not reasons and evidence.primary >= 2:
        state = "HIGH"
    elif thesis_class != "UNPROVEN" and evidence.primary + evidence.corroborating >= 2 and architecture_valid and graph_valid and graph_touches_focal:
        state = "MEDIUM"
    else:
        state = "LOW"
    return {"state": state, "reasons": reasons}


def assess_public_logic(record: Mapping[str, Any], policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    policy = dict(policy or load_policy())
    ticker = _clean_ticker(record.get("ticker"))
    if not ticker:
        raise FidelityError("A valid ticker/symbol is required")

    warnings: list[str] = []
    evidence = _evidence_summary(record.get("evidence"))
    all_dependency = _string_set(record.get("dependency_signals"))
    all_signals = _string_set(record.get("signals"))
    all_killers = _string_set(record.get("thesis_killers"))

    allowed_dependency = set(policy["dependency_signals"])
    allowed_expansion = set(policy["expansion_signals"])
    allowed_commercial = set(policy["commercial_validation_signals"])
    allowed_institutional = set(policy["institutional_validation_signals"])
    allowed_signals = allowed_expansion | allowed_commercial | allowed_institutional
    allowed_killers = set(policy["thesis_killers"])

    supported_dependency, _, w = _validate_signal_claims(record, allowed=allowed_dependency, claimed=all_dependency, evidence=evidence)
    warnings.extend(w)
    supported_signals, _, w = _validate_signal_claims(record, allowed=allowed_signals, claimed=all_signals, evidence=evidence)
    warnings.extend(w)
    supported_killers, _, w = _validate_signal_claims(record, allowed=allowed_killers, claimed=all_killers, evidence=evidence)
    warnings.extend(w)

    architecture, architecture_valid, w = _validate_architecture(record, evidence)
    warnings.extend(w)
    graph, graph_valid, graph_touches_focal, w = _validate_graph(record, evidence)
    warnings.extend(w)

    effective_dependency = supported_dependency if graph_valid and graph_touches_focal else set()
    beneficiary_signal = bool(record.get("beneficiary_signal"))
    dependency_role = _dependency_role(effective_dependency, beneficiary_signal)

    information_gap, w = _information_gap(record, evidence)
    warnings.extend(w)
    capture, capture_state, w = _company_capture(record, evidence, policy)
    warnings.extend(w)

    expansion_signals = supported_signals & allowed_expansion
    commercial_signals = supported_signals & allowed_commercial
    institutional_signals = supported_signals & allowed_institutional

    thesis_class = _thesis_class(
        dependency_role,
        architecture_valid=architecture_valid,
        graph_valid=graph_valid,
        graph_touches_focal=graph_touches_focal,
        expansion_signals=expansion_signals,
    )
    state = _thesis_state(
        dependency_role=dependency_role,
        thesis_class=thesis_class,
        information_gap=information_gap,
        evidence=evidence,
        commercial_signals=commercial_signals,
        institutional_signals=institutional_signals,
        killers=supported_killers,
        severe_break_signals=set(policy["severe_break_signals"]),
        capture_state=capture_state,
    )

    disconfirmation = record.get("disconfirmation_conditions")
    if not isinstance(disconfirmation, Sequence) or isinstance(disconfirmation, (str, bytes, bytearray)) or not [item for item in disconfirmation if str(item).strip()]:
        raise FidelityError("At least one explicit disconfirmation condition is required")

    source_views, w = _validated_source_views(record, policy)
    warnings.extend(w)
    source_delta, w = _validated_source_delta(record, policy)
    warnings.extend(w)

    system_score = record.get("system_operationalization_score")
    if system_score is not None:
        if isinstance(system_score, bool):
            raise FidelityError("System operationalization score must be numeric or null")
        try:
            score_value = float(system_score)
        except (TypeError, ValueError) as exc:
            raise FidelityError("System operationalization score must be numeric or null") from exc
        if not math.isfinite(score_value) or not 0 <= score_value <= 100:
            raise FidelityError("System operationalization score must be within 0..100")

    if state == "BROKEN" and system_score is not None:
        warnings.append("BROKEN thesis state overrides any positive system operationalization score")
    if evidence.lead_only > 0 and evidence.primary == 0:
        warnings.append("Lead-only evidence cannot prove company economics")
    if not source_views:
        warnings.append("No validated Serenity source view is attached; public-logic analysis is not a claim that Serenity discussed this ticker")

    confidence = _confidence(
        thesis_class=thesis_class,
        evidence=evidence,
        architecture_valid=architecture_valid,
        graph_valid=graph_valid,
        graph_touches_focal=graph_touches_focal,
        warnings=warnings,
    )

    return {
        "schema_version": 2,
        "product_version": "2.1.3",
        "ticker": ticker,
        "methodology_label": "Public-logic high-fidelity reconstruction",
        "private_process_reproduction_claimed": False,
        "source_view_label": "Serenity source view",
        "serenity_source_views": source_views,
        "public_logic_fidelity": {
            "architecture": architecture,
            "architecture_evidence_bound": architecture_valid,
            "supply_chain_graph": graph,
            "graph_touches_focal_company": graph_touches_focal,
            "dependency_role": dependency_role,
            "information_gap": information_gap,
            "thesis_class": thesis_class,
            "company_capture": capture,
            "thesis_state": state,
            "timing": _timing(record),
            "thesis_killers": sorted(supported_killers),
            "unproven_thesis_killer_claims": sorted(all_killers - supported_killers),
            "disconfirmation_conditions": [str(item) for item in disconfirmation if str(item).strip()],
            "source_delta": source_delta,
            "cross_run_source_delta_append_only_verified": False,
        },
        "supported_signals": {
            "dependency": sorted(supported_dependency),
            "expansion": sorted(expansion_signals),
            "commercial_validation": sorted(commercial_signals),
            "institutional_validation_context": sorted(institutional_signals),
        },
        "evidence_summary": {
            "primary": evidence.primary,
            "corroborating": evidence.corroborating,
            "lead_only": evidence.lead_only,
            "urls": list(evidence.urls),
        },
        "fidelity_confidence": confidence,
        "system_operationalization_score": system_score,
        "system_score_can_override_broken_thesis": False,
        "warnings": sorted(set(warnings)),
    }


def _fixture(**overrides: Any) -> dict[str, Any]:
    filing = "https://example.com/filing"
    customer = "https://example.com/customer"
    value: dict[str, Any] = {
        "ticker": "TEST",
        "focal_company_node": "TEST",
        "architecture": {"current": "pluggable optics", "next": "CPO", "evidence_urls": [customer]},
        "supply_chain_graph": [
            {"from": "hyperscaler", "to": "module", "relationship": "uses", "evidence_url": customer, "as_of": "2026-01-01"},
            {"from": "module", "to": "TEST", "relationship": "qualified supplier", "evidence_url": customer, "as_of": "2026-01-01"},
        ],
        "dependency_signals": ["semi_monopoly", "qualification_constraint"],
        "beneficiary_signal": True,
        "signals": ["qualification", "customer_named_ramp"],
        "signal_evidence": [
            {"signal": "semi_monopoly", "evidence_url": customer, "as_of": "2026-01-01"},
            {"signal": "qualification_constraint", "evidence_url": customer, "as_of": "2026-01-01"},
            {"signal": "qualification", "evidence_url": filing, "as_of": "2026-01-01"},
            {"signal": "customer_named_ramp", "evidence_url": customer, "as_of": "2026-01-01"},
        ],
        "information_gap": {"coverage": "low", "evidence_urls": [customer]},
        "company_capture": {"state": "POSITIVE", "evidence_urls": [filing], "financing_durability": "adequate"},
        "evidence": [
            {"tier": "primary_strong", "url": filing},
            {"tier": "corroborating", "url": customer},
        ],
        "thesis_killers": [],
        "disconfirmation_conditions": ["customer qualifies a substitute"],
        "timing": {"architecture_ramp_window": "company-specific; source dated"},
        "serenity_source_views": [],
        "source_delta": [],
        "system_operationalization_score": 93,
    }
    value.update(overrides)
    return value


def self_test() -> None:
    policy = load_policy()
    healthy = assess_public_logic(_fixture(), policy)
    fidelity = healthy["public_logic_fidelity"]
    assert fidelity["dependency_role"] == "SEMI_MONOPOLY"
    assert fidelity["thesis_class"] == "BOTTLENECK_THESIS"
    assert fidelity["thesis_state"] == "COMMERCIAL_VALIDATION"
    assert fidelity["company_capture"]["state"] == "POSITIVE"

    filing = "https://example.com/filing"
    broken = assess_public_logic(
        _fixture(
            thesis_killers=["architecture_bypass"],
            signal_evidence=_fixture()["signal_evidence"] + [
                {"signal": "architecture_bypass", "evidence_url": filing, "as_of": "2026-01-02"}
            ],
            system_operationalization_score=99,
        ),
        policy,
    )
    assert broken["public_logic_fidelity"]["thesis_state"] == "BROKEN"
    assert broken["system_score_can_override_broken_thesis"] is False

    customer = "https://example.com/customer"
    named = assess_public_logic(
        _fixture(
            dependency_signals=["customer_named_dependency"],
            signal_evidence=[
                {"signal": "customer_named_dependency", "evidence_url": customer, "as_of": "2026-01-01"}
            ],
            signals=[],
        ),
        policy,
    )
    assert named["public_logic_fidelity"]["dependency_role"] == "BENEFICIARY"
    assert named["public_logic_fidelity"]["thesis_class"] == "UNPROVEN"

    foreign = assess_public_logic(_fixture(ticker="SIVE", focal_company_node="TEST"), policy)
    assert foreign["ticker"] == "SIVE"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print(json.dumps({"status": "PASS", "methodology": "public-logic high-fidelity reconstruction"}))
        return 0
    if not args.input:
        raise SystemExit("--input is required unless --self-test is used")
    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise SystemExit("input must be a JSON object")
    result = assess_public_logic(payload)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
