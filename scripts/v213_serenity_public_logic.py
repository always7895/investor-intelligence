#!/usr/bin/env python3
"""Serenity public-logic high-fidelity reconstruction.

This module intentionally does NOT implement or claim an official Serenity score.
It converts public-evidence signals into auditable thesis states while keeping the
legacy quantitative ranking separate as a project-authored operationalization.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "v213-serenity-public-logic-policy.json"
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")


class FidelityError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidenceSummary:
    primary: int
    corroborating: int
    lead_only: int
    urls: tuple[str, ...]


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FidelityError(f"Invalid fidelity policy: {path}") from exc
    if not isinstance(value, dict):
        raise FidelityError("Fidelity policy must be an object")
    if value.get("product_version") != "2.1.3":
        raise FidelityError("Unexpected fidelity policy product version")
    if value.get("methodology") != "serenity-public-logic-high-fidelity-reconstruction":
        raise FidelityError("Unexpected fidelity methodology")
    if value.get("attribution_boundary") != "public_source_only_not_private_process":
        raise FidelityError("Attribution boundary is not fail-closed")
    if value.get("legacy_quantitative_overlay_label") != "System operationalization score":
        raise FidelityError("Legacy quantitative overlay is mislabeled")
    fail_closed = value.get("fail_closed")
    if not isinstance(fail_closed, dict) or not fail_closed or not all(fail_closed.values()):
        raise FidelityError("Fidelity fail-closed policy is incomplete")
    return value


def _clean_ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text if TICKER_RE.fullmatch(text) else ""


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _evidence_summary(rows: Any) -> EvidenceSummary:
    primary = 0
    corroborating = 0
    lead_only = 0
    urls: list[str] = []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        rows = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        tier = str(row.get("tier") or "").strip().casefold()
        if tier in {"primary", "primary_strong", "t0", "t1"}:
            primary += 1
        elif tier in {"corroborating", "secondary", "t2"}:
            corroborating += 1
        else:
            lead_only += 1
        url = str(row.get("url") or "").strip()
        if url.startswith("https://") and url not in urls:
            urls.append(url)
    return EvidenceSummary(primary, corroborating, lead_only, tuple(urls))


def _dependency_role(signals: set[str], beneficiary_signal: bool) -> str:
    if "single_source" in signals:
        return "SINGLE_SOURCE"
    if "semi_monopoly" in signals:
        return "SEMI_MONOPOLY"
    if signals & {"qualified_supplier_concentration", "qualification_constraint", "unique_process_or_ip"}:
        return "QUALIFICATION_CONSTRAINED"
    if "binding_capacity" in signals:
        return "CAPACITY_BOTTLENECK"
    if beneficiary_signal:
        return "BENEFICIARY"
    return "UNPROVEN"


def _information_gap(record: Mapping[str, Any]) -> str:
    info = record.get("information_gap")
    if isinstance(info, Mapping):
        explicit = str(info.get("state") or "").strip().upper()
        if explicit in {"UNDISCOVERED", "EARLY_DISCOVERY", "BECOMING_KNOWN", "CONSENSUS", "UNKNOWN"}:
            return explicit
        coverage = str(info.get("coverage") or "").strip().casefold()
        institutional = bool(info.get("institutional_validation"))
        if coverage in {"none", "very_low", "low"} and not institutional:
            return "UNDISCOVERED"
        if coverage in {"low", "limited"}:
            return "EARLY_DISCOVERY"
        if institutional or coverage in {"rising", "moderate"}:
            return "BECOMING_KNOWN"
        if coverage in {"high", "consensus"}:
            return "CONSENSUS"
    return "UNKNOWN"


def _thesis_class(
    dependency_role: str,
    evidence: EvidenceSummary,
    signals: set[str],
) -> str:
    hard_dependency = dependency_role in {
        "SINGLE_SOURCE",
        "SEMI_MONOPOLY",
        "QUALIFICATION_CONSTRAINED",
        "CAPACITY_BOTTLENECK",
    }
    expansion = bool(signals & {"revenue_expansion", "capacity_expansion", "market_share_expansion"})
    if hard_dependency and evidence.primary >= 1 and expansion:
        return "HYBRID"
    if hard_dependency and evidence.primary >= 1:
        return "BOTTLENECK_THESIS"
    if expansion and evidence.primary >= 1:
        return "EXPANSION_THESIS"
    return "UNPROVEN"


def _thesis_state(
    *,
    dependency_role: str,
    thesis_class: str,
    information_gap: str,
    evidence: EvidenceSummary,
    signals: set[str],
    killers: set[str],
    severe_break_signals: set[str],
) -> str:
    if killers & severe_break_signals:
        return "BROKEN"
    if killers:
        return "THESIS_WEAKENING"
    if evidence.primary + evidence.corroborating == 0:
        return "INSUFFICIENT_EVIDENCE"

    commercial = bool(
        signals
        & {
            "named_contract",
            "design_win",
            "qualification",
            "capacity_reservation",
            "prepayment",
            "long_term_agreement",
            "realized_revenue",
            "customer_named_ramp",
        }
    )
    institutional = bool(
        signals
        & {
            "institutional_position_after_thesis",
            "credible_industry_validation",
            "sell_side_validation_after_thesis",
        }
    )
    hard_dependency = dependency_role in {
        "SINGLE_SOURCE",
        "SEMI_MONOPOLY",
        "QUALIFICATION_CONSTRAINED",
        "CAPACITY_BOTTLENECK",
    }

    if information_gap == "CONSENSUS" and commercial:
        return "CONSENSUS"
    if commercial and institutional:
        return "INSTITUTIONAL_VALIDATION"
    if commercial:
        return "COMMERCIAL_VALIDATION"
    if hard_dependency and thesis_class in {"BOTTLENECK_THESIS", "HYBRID"} and evidence.primary >= 1:
        return "EARLY_VALIDATION"
    if evidence.primary >= 1 or evidence.corroborating >= 1:
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


def assess_public_logic(record: Mapping[str, Any], policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    policy = dict(policy or load_policy())
    ticker = _clean_ticker(record.get("ticker"))
    if not ticker:
        raise FidelityError("A valid ticker/symbol is required")

    evidence = _evidence_summary(record.get("evidence"))
    signals = _string_set(record.get("signals"))
    killers = _string_set(record.get("thesis_killers"))
    permitted_killers = set(policy["thesis_killers"])
    unknown_killers = killers - permitted_killers
    if unknown_killers:
        raise FidelityError("Unknown thesis-killer signals: " + ", ".join(sorted(unknown_killers)))

    dependency_signals = _string_set(record.get("dependency_signals"))
    permitted_dependency = set(policy["hard_dependency_signals"])
    unknown_dependency = dependency_signals - permitted_dependency
    if unknown_dependency:
        raise FidelityError("Unknown dependency signals: " + ", ".join(sorted(unknown_dependency)))

    beneficiary_signal = bool(record.get("beneficiary_signal"))
    dependency_role = _dependency_role(dependency_signals, beneficiary_signal)
    information_gap = _information_gap(record)
    thesis_class = _thesis_class(dependency_role, evidence, signals)
    severe = set(policy["severe_break_signals"])
    state = _thesis_state(
        dependency_role=dependency_role,
        thesis_class=thesis_class,
        information_gap=information_gap,
        evidence=evidence,
        signals=signals,
        killers=killers,
        severe_break_signals=severe,
    )

    architecture = record.get("architecture") if isinstance(record.get("architecture"), Mapping) else {}
    graph = record.get("supply_chain_graph") if isinstance(record.get("supply_chain_graph"), Sequence) else []
    disconfirmation = record.get("disconfirmation_conditions")
    if not isinstance(disconfirmation, Sequence) or isinstance(disconfirmation, (str, bytes, bytearray)) or not list(disconfirmation):
        raise FidelityError("At least one explicit disconfirmation condition is required")

    source_delta = record.get("source_delta")
    if not isinstance(source_delta, Sequence) or isinstance(source_delta, (str, bytes, bytearray)):
        source_delta = []

    result = {
        "schema_version": 1,
        "product_version": "2.1.3",
        "ticker": ticker,
        "methodology_label": "Public-logic high-fidelity reconstruction",
        "private_process_reproduction_claimed": False,
        "source_view_label": "Serenity source view",
        "public_logic_fidelity": {
            "architecture": dict(architecture),
            "supply_chain_graph": [dict(item) for item in graph if isinstance(item, Mapping)],
            "dependency_role": dependency_role,
            "information_gap": information_gap,
            "thesis_class": thesis_class,
            "thesis_state": state,
            "timing": _timing(record),
            "thesis_killers": sorted(killers),
            "disconfirmation_conditions": [str(item) for item in disconfirmation if str(item).strip()],
            "source_delta": [dict(item) for item in source_delta if isinstance(item, Mapping)],
        },
        "evidence_summary": {
            "primary": evidence.primary,
            "corroborating": evidence.corroborating,
            "lead_only": evidence.lead_only,
            "urls": list(evidence.urls),
        },
        "system_operationalization_score": record.get("system_operationalization_score"),
        "system_score_can_override_broken_thesis": False,
        "warnings": [],
    }

    if dependency_role == "BENEFICIARY" and thesis_class == "BOTTLENECK_THESIS":
        raise FidelityError("Beneficiary cannot be classified as a bottleneck thesis")
    if state == "BROKEN" and result["system_operationalization_score"] is not None:
        result["warnings"].append("BROKEN thesis state overrides any positive system operationalization score")
    if evidence.lead_only > 0 and evidence.primary == 0:
        result["warnings"].append("Lead-only evidence cannot prove company economics")
    if not result["public_logic_fidelity"]["supply_chain_graph"]:
        result["warnings"].append("Supply-chain graph is incomplete")
    return result


def _fixture(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "ticker": "TEST",
        "architecture": {"current": "pluggable optics", "next": "CPO"},
        "supply_chain_graph": [
            {"from": "hyperscaler", "to": "optical module", "evidence_url": "https://example.com/1"},
            {"from": "optical module", "to": "laser", "evidence_url": "https://example.com/2"},
        ],
        "dependency_signals": ["semi_monopoly", "qualification_constraint"],
        "beneficiary_signal": True,
        "signals": ["qualification", "customer_named_ramp"],
        "information_gap": {"coverage": "low"},
        "evidence": [
            {"tier": "primary_strong", "url": "https://example.com/filing"},
            {"tier": "corroborating", "url": "https://example.com/customer"},
        ],
        "thesis_killers": [],
        "disconfirmation_conditions": ["customer qualifies a substitute"],
        "timing": {"architecture_ramp_window": "company-specific; source dated"},
        "source_delta": [],
        "system_operationalization_score": 93,
    }
    value.update(overrides)
    return value


def self_test() -> None:
    policy = load_policy()
    healthy = assess_public_logic(_fixture(), policy)
    assert healthy["public_logic_fidelity"]["dependency_role"] == "SEMI_MONOPOLY"
    assert healthy["public_logic_fidelity"]["thesis_class"] == "BOTTLENECK_THESIS"
    assert healthy["public_logic_fidelity"]["thesis_state"] == "COMMERCIAL_VALIDATION"

    broken = assess_public_logic(
        _fixture(thesis_killers=["architecture_bypass"], system_operationalization_score=99),
        policy,
    )
    assert broken["public_logic_fidelity"]["thesis_state"] == "BROKEN"
    assert broken["system_score_can_override_broken_thesis"] is False
    assert broken["warnings"]

    beneficiary = assess_public_logic(
        _fixture(
            dependency_signals=[],
            beneficiary_signal=True,
            signals=["revenue_expansion"],
            thesis_killers=[],
        ),
        policy,
    )
    assert beneficiary["public_logic_fidelity"]["dependency_role"] == "BENEFICIARY"
    assert beneficiary["public_logic_fidelity"]["thesis_class"] == "EXPANSION_THESIS"

    foreign = assess_public_logic(
        _fixture(ticker="SIVE", evidence=[{"tier": "primary_strong", "url": "https://example.se/filing"}]),
        policy,
    )
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
