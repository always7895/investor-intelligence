#!/usr/bin/env python3
"""H6 public-logic refinement over an accepted H5 shadow report.

This module does not fetch or modify Production. It reconciles final enriched
state, separates operating-thesis and financing axes, adds multi-axis confidence,
models public-source-view freshness, validates reference identity/lineage, and
adds claim-level grounding metadata.
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
LINEAGE_PATH = ROOT / "config" / "v213-serenity-reference-lineage.json"

HARD_ROLES = {
    "SINGLE_SOURCE",
    "SEMI_MONOPOLY",
    "QUALIFICATION_CONSTRAINED",
    "CAPACITY_BOTTLENECK",
}
FINANCING_KILLERS = {
    "repeated_atm_or_material_dilution",
    "toxic_warrants_or_financing",
    "equity_capture_destroyed_by_financing",
    "balance_sheet_funding_failure",
}
ARCHIVE_LEADS = {
    "AAOI": {"source_id": "x-2076763334930812936", "published_at": "2026-07-13", "kind": "ticker_calibration"},
    "SIVE": {"source_id": "x-2074046947434860971", "published_at": "2026-07-06", "kind": "ticker_conviction"},
    "AXTI": {"source_id": "x-2083088870942642391", "published_at": "2026-07-31", "kind": "capacity_revenue_update"},
    "TSEM": {"source_id": "x-2077039373711970804", "published_at": "2026-07-14", "kind": "capacity_expansion_update"},
    "LITE": {"source_id": "x-2083438823548293140", "published_at": "2026-08-01", "kind": "supply_gap_update"},
}


class H6Error(RuntimeError):
    pass


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _level_from_facts(primary: int, corroborating: int) -> str:
    if primary >= 4 or (primary >= 2 and corroborating >= 1):
        return "HIGH"
    if primary >= 1 or corroborating >= 1:
        return "MEDIUM"
    return "LOW"


def _history_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise H6Error("source history row must be an object")
        rows.append(value)
    return rows


def validate_history_links(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(rows)
    expected = "GENESIS"
    ids: set[str] = set()
    for index, row in enumerate(items):
        source_id = str(row.get("source_id") or "").strip()
        previous_hash = str(row.get("previous_hash") or "").strip()
        record_hash = str(row.get("record_hash") or "").strip()
        if not source_id or source_id in ids:
            raise H6Error(f"duplicate/missing source_id at history row {index + 1}")
        if previous_hash != expected:
            raise H6Error(f"broken previous_hash link at history row {index + 1}")
        if len(record_hash) != 64:
            raise H6Error(f"invalid record_hash at history row {index + 1}")
        if str(row.get("time_precision") or "") != "DATE_ONLY":
            raise H6Error(f"unexpected source-time precision at history row {index + 1}")
        if _parse_date(row.get("published_at")) is None:
            raise H6Error(f"invalid published_at at history row {index + 1}")
        ids.add(source_id)
        expected = record_hash
    return {
        "structural_chain_verified": True,
        "entries": len(items),
        "latest_hash": expected if items else "GENESIS",
        "cross_run_append_only_verified": False,
        "cross_run_reason": "current chain integrity alone cannot prove that no prior history was removed; a prior receipt hash/size checkpoint is required",
    }


def load_lineage(path: Path = LINEAGE_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("target_identity", {}).get("handle") != "@aleabitoreddit":
        raise H6Error("reference lineage target identity mismatch")
    families = value.get("families")
    if not isinstance(families, list):
        raise H6Error("reference lineage families missing")
    wrong = [f for f in families if f.get("identity") == "@stockgodserenity"]
    if not wrong or any(f.get("kind") != "quarantined_wrong_identity" for f in wrong):
        raise H6Error("wrong-identity Serenity corpus is not fail-closed")
    for family in families:
        if family.get("kind") in {"archive_and_methodology_reference", "derived_archive_skill", "independent_methodology_distillation", "public_corpus_semantic_review_method", "secondary_methodology_distillation"}:
            if family.get("can_prove_company_fact") is not False or family.get("can_prove_dependency") is not False:
                raise H6Error(f"methodology/archive family can incorrectly prove facts: {family.get('id')}")
    return value


def source_view_freshness(row: Mapping[str, Any], as_of: date, verified_history: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    views = row.get("serenity_source_views") or []
    ticker = str(row.get("ticker") or "").upper()
    ticker_views: list[dict[str, Any]] = []
    for view in views if isinstance(views, list) else []:
        if not isinstance(view, Mapping):
            continue
        if str(view.get("scope") or "") != "ticker_view":
            continue
        source_id = str(view.get("source_id") or "")
        published = _parse_date(view.get("published_at"))
        direct_verified = source_id in verified_history
        if published:
            ticker_views.append({"source_id": source_id, "published_at": published, "direct_verified": direct_verified})

    latest = max(ticker_views, key=lambda x: x["published_at"]) if ticker_views else None
    if latest is None:
        lifecycle = "NO_VERIFIED_TICKER_VIEW"
        age_days = None
    else:
        age_days = (as_of - latest["published_at"]).days
        if age_days <= 45:
            lifecycle = "ACTIVE"
        elif age_days <= 90:
            lifecycle = "AGING"
        else:
            lifecycle = "STALE"

    archive_lead = ARCHIVE_LEADS.get(ticker)
    if archive_lead:
        lead_date = _parse_date(archive_lead["published_at"])
        latest_date = latest["published_at"] if latest else date.min
        if lead_date and lead_date > latest_date:
            lifecycle = "STALE_WITH_NEWER_ARCHIVE_LEAD" if latest else "ARCHIVE_LEAD_ONLY"

    return {
        "lifecycle": lifecycle,
        "latest_direct_verified_ticker_view": None if latest is None else {
            "source_id": latest["source_id"],
            "published_at": latest["published_at"].isoformat(),
            "age_days": age_days,
        },
        "newer_archive_lead": archive_lead,
        "archive_lead_is_factual_proof": False,
        "rule": "archive/Skill records discover candidate original posts but never count as company or dependency proof",
    }


def reconcile_warnings(row: Mapping[str, Any]) -> list[str]:
    warnings = list(row.get("warnings") or [])
    pf = row.get("public_logic_fidelity") or {}
    has_views = bool(row.get("serenity_source_views"))
    architecture_bound = pf.get("architecture_evidence_bound") is True
    graph = pf.get("supply_chain_graph") or []
    graph_touches = pf.get("graph_touches_focal_company") is True
    cleaned: list[str] = []
    for warning in warnings:
        text = str(warning)
        lower = text.casefold()
        if has_views and "no validated serenity source view is attached" in lower:
            continue
        if architecture_bound and "architecture/supercycle" in lower and ("lacks" in lower or "missing" in lower):
            continue
        if graph and graph_touches and "supply-chain graph has no evidence-bound edges" in lower:
            continue
        cleaned.append(text)
    return sorted(set(cleaned))


def financing_overlay(row: Mapping[str, Any]) -> dict[str, Any]:
    pf = row.get("public_logic_fidelity") or {}
    killers = set(pf.get("thesis_killers") or [])
    thesis_class = str(pf.get("thesis_class") or "UNPROVEN")
    supported = row.get("supported_signals") or {}
    commercial = bool(supported.get("commercial_validation"))

    if "equity_capture_destroyed_by_financing" in killers:
        severity = "DESTROYED"
    elif "toxic_warrants_or_financing" in killers or "balance_sheet_funding_failure" in killers:
        severity = "STRUCTURAL_DISQUALIFIER"
    elif "repeated_atm_or_material_dilution" in killers:
        severity = "MATERIAL_OVERHANG"
    else:
        h5_sive = row.get("h5_financing_capacity") or {}
        severity = "MATERIAL_OVERHANG" if h5_sive.get("equity_capture_pressure") == "MATERIAL" else "NONE"

    non_financing_killers = killers - FINANCING_KILLERS
    if "equity_capture_destroyed_by_financing" in killers or non_financing_killers:
        operating_state = str(pf.get("thesis_state") or "INSUFFICIENT_EVIDENCE")
    elif thesis_class == "UNPROVEN":
        operating_state = "INSUFFICIENT_EVIDENCE"
    elif commercial:
        operating_state = "COMMERCIAL_VALIDATION"
    else:
        operating_state = "DISCOVERY"

    if severity == "DESTROYED":
        combined = "BROKEN_BY_EQUITY_CAPTURE"
    elif severity == "STRUCTURAL_DISQUALIFIER":
        combined = "OPERATING_THESIS_SEPARATE_FROM_STRUCTURAL_FINANCING_RISK"
    elif severity == "MATERIAL_OVERHANG":
        combined = "OPERATING_THESIS_WITH_MATERIAL_FINANCING_OVERHANG"
    else:
        combined = "OPERATING_THESIS_NO_MATERIAL_FINANCING_OVERHANG"

    return {
        "operating_thesis_state": operating_state,
        "financing_severity": severity,
        "combined_research_state": combined,
        "severe_break_requires": "evidence-bound equity_capture_destroyed_by_financing or another non-financing severe break",
        "financing_and_operating_thesis_are_separate_axes": True,
    }


def multi_axis_confidence(row: Mapping[str, Any], freshness: Mapping[str, Any]) -> dict[str, Any]:
    evidence = row.get("evidence_summary") or {}
    primary = int(evidence.get("primary") or 0)
    corroborating = int(evidence.get("corroborating") or 0)
    pf = row.get("public_logic_fidelity") or {}
    role = str(pf.get("dependency_role") or "UNPROVEN")
    graph_touches = pf.get("graph_touches_focal_company") is True
    graph = pf.get("supply_chain_graph") or []
    capture = pf.get("company_capture") or {}
    identity = row.get("identity_verification") or {}
    timing = pf.get("timing") or {}

    if role in HARD_ROLES and graph_touches and graph:
        dep_conf = "MEDIUM"
    elif role == "BENEFICIARY" and graph_touches and graph:
        dep_conf = "MEDIUM_LINKAGE_ONLY"
    else:
        dep_conf = "LOW_UNPROVEN"

    capture_state = str(capture.get("state") or "UNPROVEN")
    capture_conf = "HIGH" if capture_state != "UNPROVEN" and bool(capture.get("evidence_urls")) else "LOW"
    identity_conf = "NOT_APPLICABLE" if identity.get("applicable") is False else ("HIGH" if identity.get("identity_status") == "PASS" else "LOW")
    known_timing = sum(1 for v in timing.values() if str(v or "").strip().casefold() not in {"", "unknown", "none"})
    timing_conf = "HIGH" if known_timing >= 3 else ("MEDIUM" if known_timing >= 1 else "LOW")

    return {
        "factual_evidence_confidence": _level_from_facts(primary, corroborating),
        "dependency_confidence": dep_conf,
        "company_capture_confidence": capture_conf,
        "identity_confidence": identity_conf,
        "source_view_freshness": str(freshness.get("lifecycle") or "UNKNOWN"),
        "timing_confidence": timing_conf,
        "note": "high factual confidence does not imply high bottleneck/dependency confidence",
    }


def claim_grounding(row: Mapping[str, Any]) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    ticker = str(row.get("ticker") or "")
    order = (row.get("h5_qualified_substitute_capacity") or {}).get("order_outlook")
    if isinstance(order, Mapping):
        urls = [str(x) for x in order.get("evidence_urls") or [] if str(x).startswith("https://")]
        current = str(order.get("current_orders_summary") or "").strip()
        future = str(order.get("future_orders_estimate") or "").strip()
        claims.append({
            "claim": "current_orders_summary",
            "classification": "SUPPORTED" if current and urls else "UNSUPPORTED",
            "evidence_urls": urls,
        })
        claims.append({
            "claim": "future_orders_estimate",
            "classification": "INFERENCE" if future and urls and order.get("numeric_total_order_estimate_prohibited") is True else "UNSUPPORTED",
            "evidence_urls": urls,
            "premise": "signed/fixed/minimum/capacity commitments support visibility but not an invented total revenue/order number",
        })
    else:
        claims.append({"claim": "top20_order_outlook", "classification": "PENDING_H6_FULL_POPULATION", "ticker": ticker})
    return {"material_claims": claims, "unsupported_claims_blocked": True}


def refine_report(source: Mapping[str, Any], history_rows: list[dict[str, Any]], lineage: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(source))
    generated = _parse_date(result.get("generated_at")) or date.today()
    history_by_id = {str(row.get("source_id")): row for row in history_rows}
    history_attestation = validate_history_links(history_rows)

    rows = result.get("results")
    if not isinstance(rows, list):
        raise H6Error("H5 results missing")

    stale_count = 0
    archive_lead_count = 0
    for row in rows:
        if not isinstance(row, dict):
            raise H6Error("ticker result must be an object")
        freshness = source_view_freshness(row, generated, history_by_id)
        if freshness["lifecycle"] in {"STALE", "STALE_WITH_NEWER_ARCHIVE_LEAD", "ARCHIVE_LEAD_ONLY", "NO_VERIFIED_TICKER_VIEW"}:
            stale_count += 1
        if freshness.get("newer_archive_lead"):
            archive_lead_count += 1
        cleaned_warnings = reconcile_warnings(row)
        overlay = financing_overlay(row)
        axes = multi_axis_confidence(row, freshness)
        grounding = claim_grounding(row)

        row["warnings"] = cleaned_warnings
        row["h6_logic_refinement"] = {
            "source_view_lifecycle": freshness,
            "confidence_axes": axes,
            "financing_operating_split": overlay,
            "claim_grounding": grounding,
            "source_history_attestation": history_attestation,
            "reference_lineage_policy_applied": True,
            "wrong_identity_quarantine": "PASS",
        }

    result["h6_public_logic_refinement_shadow_only"] = True
    result["h6_reference_lineage"] = {
        "target_identity": lineage.get("target_identity"),
        "wrong_identity_quarantine": "PASS",
        "archive_and_skill_factual_corroboration_weight": 0,
    }
    result["h6_source_history_attestation"] = history_attestation
    result.setdefault("summary", {}).update({
        "h6_public_logic_refinement_applied": True,
        "h6_multi_axis_confidence": True,
        "h6_financing_operating_split": True,
        "h6_claim_grounding": True,
        "h6_source_view_lifecycle": True,
        "h6_stale_or_missing_ticker_view_count": stale_count,
        "h6_newer_archive_lead_count": archive_lead_count,
        "hard_dependency_count": sum(1 for row in rows if (row.get("public_logic_fidelity") or {}).get("dependency_role") in HARD_ROLES),
        "production_ranking_changed": False,
    })
    return result


def self_test() -> None:
    lineage = load_lineage()
    assert any(f.get("kind") == "quarantined_wrong_identity" for f in lineage["families"])
    history = [
        {"source_id": "x-1", "published_at": "2026-03-17", "time_precision": "DATE_ONLY", "previous_hash": "GENESIS", "record_hash": "a" * 64},
    ]
    att = validate_history_links(history)
    assert att["structural_chain_verified"] is True
    row = {
        "ticker": "AAOI",
        "evidence_summary": {"primary": 7, "corroborating": 0},
        "serenity_source_views": [{"scope": "ticker_view", "source_id": "x-1", "published_at": "2026-03-17"}],
        "warnings": ["No validated Serenity source view is attached; public-logic analysis is not a claim that Serenity discussed this ticker"],
        "supported_signals": {"commercial_validation": []},
        "public_logic_fidelity": {
            "architecture_evidence_bound": True,
            "supply_chain_graph": [],
            "graph_touches_focal_company": False,
            "dependency_role": "UNPROVEN",
            "thesis_class": "EXPANSION_THESIS",
            "thesis_state": "THESIS_WEAKENING",
            "company_capture": {"state": "MIXED", "evidence_urls": ["https://example.com/filing"]},
            "thesis_killers": ["repeated_atm_or_material_dilution"],
            "timing": {"entry_context": "unknown", "architecture_ramp_window": "unknown", "operating_thesis_horizon": "unknown", "valuation_expectation_context": "unknown"},
        },
        "identity_verification": {"applicable": False},
    }
    freshness = source_view_freshness(row, date(2026, 9, 1), {"x-1": history[0]})
    assert freshness["lifecycle"] == "STALE_WITH_NEWER_ARCHIVE_LEAD"
    assert not any("No validated Serenity" in x for x in reconcile_warnings(row))
    overlay = financing_overlay(row)
    assert overlay["operating_thesis_state"] == "DISCOVERY"
    assert overlay["financing_severity"] == "MATERIAL_OVERHANG"
    axes = multi_axis_confidence(row, freshness)
    assert axes["factual_evidence_confidence"] == "HIGH"
    assert axes["dependency_confidence"] == "LOW_UNPROVEN"
    print("V213_H6_PUBLIC_LOGIC_REFINEMENT_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.input or not args.history or not args.output:
        parser.error("--input, --history and --output are required")
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    history = _history_rows(args.history)
    lineage = load_lineage()
    refined = refine_report(source, history, lineage)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pending = args.output.with_name(args.output.name + ".pending")
    pending.write_text(json.dumps(refined, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pending.replace(args.output)
    print(json.dumps({
        "status": "PASS",
        "output": str(args.output),
        "hard_dependency_count": refined["summary"]["hard_dependency_count"],
        "stale_or_missing_ticker_views": refined["summary"]["h6_stale_or_missing_ticker_view_count"],
        "newer_archive_leads": refined["summary"]["h6_newer_archive_lead_count"],
        "production_ranking_changed": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
