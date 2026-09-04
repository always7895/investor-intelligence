#!/usr/bin/env python3
"""Apply the final claim-scoped Serenity public-logic evidence standard v3.

This module tightens the diversified postprocessor rather than inventing missing
architecture or company-capture evidence. Endpoint availability and listing
identity improve provenance/coverage, but never become a positive company
fundamental signal by themselves.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
BASE_PATH = SCRIPT_DIR / "v213_apply_diversified_operationalization.py"
_SPEC = importlib.util.spec_from_file_location("ii_v213_diversified_base", BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load diversified base: {BASE_PATH}")
base = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = base
_SPEC.loader.exec_module(base)

SCORING_VERSION = "system-operationalization-v2.1.3-evidence-v3"


def metric(text: Any, label: str) -> float | None:
    match = re.search(re.escape(label) + r"\s*([+-]?\d+(?:\.\d+)?)%", str(text or ""))
    return float(match.group(1)) if match else None


def evidence_quality(
    families: set[str],
    official_boundary_families: set[str],
    market_families: set[str],
    issuer_financial_family_count: int,
    order_supported: bool,
    required_global_sources_healthy: bool,
) -> float:
    # Claim-scoped scoring: listing identity and macro endpoint health can improve
    # provenance, but cannot masquerade as independent issuer-financial proof.
    points = 0.0
    if "us_sec" in families:
        points += 2.0
    if "nasdaq" in official_boundary_families:
        points += 2.0
    if "gleif" in official_boundary_families:
        points += 1.0
    if market_families:
        points += 1.0
    if order_supported:
        points += 1.0
    if required_global_sources_healthy:
        points += 1.0
    if issuer_financial_family_count >= 2:
        points += 4.0
    return min(15.0, points)


def data_quality(
    official_boundary_family_count: int,
    issuer_financial_family_count: int,
    market_family_count: int,
    order_supported: bool,
    required_global_sources_healthy: bool,
) -> float:
    issuer = min(1.0, issuer_financial_family_count / 2.0)
    boundary = min(1.0, official_boundary_family_count / 2.0)
    market = 1.0 if market_family_count >= 2 else 0.35 if market_family_count == 1 else 0.0
    return round(
        0.45 * issuer
        + 0.20 * boundary
        + 0.10 * market
        + 0.15 * float(order_supported)
        + 0.10 * float(required_global_sources_healthy),
        4,
    )


def conservative_tam(revenue_growth_pct: float | None, order_supported: bool) -> float:
    if revenue_growth_pct is None or revenue_growth_pct <= 0:
        revenue = 0.0
    elif revenue_growth_pct < 15:
        revenue = 2.0
    elif revenue_growth_pct < 35:
        revenue = 4.0
    else:
        revenue = 6.0
    return min(8.0, revenue + (2.0 if order_supported else 0.0))


def rating(score: float) -> str:
    if score >= 55:
        return "A"
    if score >= 40:
        return "B"
    if score >= 25:
        return "C"
    return "D"


def tighten(
    rows: list[dict[str, Any]],
    v212: dict[str, Any],
    v213: dict[str, Any],
    federation: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    five_by_ticker = {
        str(row.get("ticker") or "").upper(): row
        for row in v212.get("records", [])
        if isinstance(row, dict)
    }
    seven_by_ticker = {
        str(row.get("ticker") or "").upper(): row
        for row in v213.get("records", [])
        if isinstance(row, dict)
    }
    fed_by_ticker = {
        str(row.get("ticker") or "").upper(): row
        for row in federation.get("ticker_sources", [])
        if isinstance(row, dict)
    }
    required_global_sources_healthy = not federation.get("gates", {}).get("missing_required_families")
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    tightened: list[dict[str, Any]] = []

    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        five = five_by_ticker.get(ticker)
        seven = seven_by_ticker.get(ticker)
        fed = fed_by_ticker.get(ticker)
        if not five or not seven or not fed:
            raise base.OperationalizationError(f"Evidence-v3 input missing for {ticker}")
        summary = str(five.get("profit_summary") or "")
        revenue = metric(summary, "營收年增")
        net = metric(summary, "淨利率")
        order_supported = str(seven.get("orders_confidence") or "") not in {"", "UNAVAILABLE"}
        families = {str(v) for v in fed.get("independent_families") or [] if str(v)}
        official_boundary = {
            str(v) for v in fed.get("official_identity_or_filing_families") or [] if str(v)
        }
        market_families = {str(v) for v in fed.get("market_observation_families") or [] if str(v)}
        issuer_financial_count = int(fed.get("issuer_financial_claim_family_count") or 0)

        factors = dict(row.get("serenity_factors") or {})
        factors.update({
            "demand_wave": 0.0,
            "chokepoint": 0.0,
            "pricing_power": 0.0,
            "replacement_friction": 0.0,
            "tam_capture": conservative_tam(revenue, order_supported),
            "valuation_expectations": min(3.75, max(0.0, float(factors.get("valuation_expectations") or 0.0)))
                if len(market_families) < 2
                else min(15.0, max(0.0, float(factors.get("valuation_expectations") or 0.0))),
            "evidence_quality": evidence_quality(
                families,
                official_boundary,
                market_families,
                issuer_financial_count,
                order_supported,
                required_global_sources_healthy,
            ),
        })

        risks = {
            "architecture_and_demand_wave_unproven_without_claim_specific_evidence",
            "bottleneck_unproven_without_evidence_bound_graph",
            "pricing_power_unproven_without_contract_or_price_evidence",
            "replacement_friction_unproven_without_switching_or_qualification_evidence",
            "global_macro_sources_are_context_not_company_corroboration",
        }
        penalty = 0.0
        if len(market_families) < 2:
            risks.add("single_market_provider_degraded")
            penalty += 2.0
        if issuer_financial_count < 2:
            risks.add("issuer_financial_claim_has_single_primary_family")
            penalty += 3.0
        if not order_supported:
            risks.add("order_visibility_unavailable")
            penalty += 1.0
        if revenue is not None and revenue < 0:
            risks.add("negative_revenue_growth")
            penalty += 4.0
        if net is not None and net < 0:
            risks.add("negative_net_margin")
            penalty += 4.0

        raw_score = sum(float(v) for v in factors.values())
        score = max(0.0, min(100.0, raw_score - penalty))
        result = dict(row)
        result.update({
            "serenity_score": round(score, 2),
            "serenity_raw_score": round(raw_score, 2),
            "risk_penalty": round(penalty, 2),
            "data_quality": data_quality(
                len(official_boundary),
                issuer_financial_count,
                len(market_families),
                order_supported,
                required_global_sources_healthy,
            ),
            "rating": rating(score),
            "serenity_factors": {key: round(float(value), 2) for key, value in factors.items()},
            "risk_flags": sorted(risks),
            "scoring_version": SCORING_VERSION,
            "generated_at": generated,
            "as_of": generated,
        })
        result["evidence_count"] = len(result.get("evidence") or [])
        result["source_count"] = len({
            str(item.get("source_id") or "")
            for item in result.get("evidence") or []
            if isinstance(item, dict) and item.get("source_id")
        })
        tightened.append(result)

    tightened.sort(
        key=lambda item: (-float(item["serenity_score"]), -float(item["data_quality"]), str(item["ticker"]))
    )
    for rank, item in enumerate(tightened, 1):
        item["rank"] = rank
    order = [str(item["ticker"]) for item in tightened]
    return tightened, base.reorder_report(v212, order), base.reorder_report(v213, order)


def update_plan(plan: dict[str, Any], federation: Mapping[str, Any]) -> dict[str, Any]:
    result = base.update_plan(plan, federation)
    methodology = dict(result.get("scoring_methodology") or {})
    methodology.update({
        "scoring_version": SCORING_VERSION,
        "architecture_source_availability_is_not_positive_demand_signal": True,
        "margin_only_pricing_power_points": 0,
        "keyword_only_chokepoint_points": 0,
        "gross_margin_only_replacement_friction_points": 0,
        "revenue_only_tam_capture_cap_fraction": 0.4,
        "single_market_provider_valuation_cap_fraction": 0.25,
        "issuer_financial_single_family_penalty": 3,
    })
    result["scoring_methodology"] = methodology
    return result


def markdown_report(rows: list[dict[str, Any]], federation: Mapping[str, Any]) -> str:
    text = base.markdown_report(rows, federation)
    return text.replace(
        "## Methodology guardrails",
        "## Evidence Standard v3 guardrails\n\n"
        "- Endpoint availability and macro context do not create positive company points.\n"
        "- Margin alone cannot create pricing-power points.\n"
        "- Listing identity improves provenance but does not corroborate revenue or orders.\n\n"
        "## Methodology guardrails",
    )


def self_test() -> None:
    assert conservative_tam(100.0, True) == 8.0
    assert evidence_quality({"us_sec", "nasdaq", "yahoo_finance"}, {"us_sec", "nasdaq"}, {"yahoo_finance"}, 1, False, True) == 6.0
    assert data_quality(2, 1, 1, False, True) < 0.7
    assert rating(20) == "D"
    print("V213_EVIDENCE_STANDARD_V3_SCORER_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    top20 = base.load_json(base.TOP20_PATH)
    v212 = base.load_json(base.V212_PATH)
    v213 = base.load_json(base.V213_PATH)
    federation = base.load_json(base.FEDERATION_PATH)
    standard = base.load_json(base.STANDARD_PATH)
    if not isinstance(top20, list):
        raise base.OperationalizationError("Top20 root must be an array")
    rows, preliminary_v212, preliminary_v213 = base.apply(top20, v212, v213, federation, standard)
    rows, final_v212, final_v213 = tighten(rows, preliminary_v212, preliminary_v213, federation)
    plan = update_plan(base.load_json(base.PLAN_PATH), federation)
    base.atomic_json(base.TOP20_PATH, rows)
    base.atomic_json(base.V212_PATH, final_v212)
    base.atomic_json(base.V213_PATH, final_v213)
    base.atomic_json(base.PLAN_PATH, plan)
    base.atomic_text(base.REPORT_PATH, markdown_report(rows, federation) + "\n")
    print(
        f"V213_EVIDENCE_STANDARD_V3_SCORER = PASS; rows=20; top={rows[0]['ticker']}; "
        f"scoring_version={SCORING_VERSION}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (base.OperationalizationError, OSError, ValueError) as exc:
        print(f"V213_EVIDENCE_STANDARD_V3_SCORER = FAIL; {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
