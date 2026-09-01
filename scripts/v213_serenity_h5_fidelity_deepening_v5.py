#!/usr/bin/env python3
"""H5 v5: repair AXTI agreement ordering and expose evidence-bound order outlook.

H5 v4 reached AXTI and failed because the parser assumed the phrase
"three (3) years" appeared before "6-inch indium phosphide".  The filed Coherent
8-K says the reverse: it first identifies 6-inch InP wafer substrates and later
states the initial three-year term.

This wrapper keeps all H5 v4 safety behavior, replaces only the AXTI
substitute/capacity parser, and adds compact order-outlook evidence that can later
feed the seven-field LINE Top 20 contract.  It does not deploy or change
Production.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h5_fidelity_deepening_v4 as v4

v3 = v4.v3
base = v4.base


def _must(pattern: str, text: str, label: str) -> re.Match[str]:
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        raise ValueError(f"required evidence not found: {label}")
    return match


def axti_substitute_capacity_map_v5(
    text_2024: str,
    text_2026: str,
    coherent: str,
    lumentum: str,
    casela: str,
) -> dict[str, Any]:
    _must(
        r"customer or prospective customer has at least two qualified substrate suppliers",
        text_2024,
        "AXTI typical qualified suppliers",
    )
    _must(r"Sumitomo and JX also compete with us in the InP market", text_2026, "AXTI InP competitors")

    # Coherent filing order is: 6-inch InP product -> three-year term -> capacity
    # commitment/prepayment/minimum-order mechanics.  Do not depend on one phrase
    # appearing before the other inside an arbitrary character window.
    _must(r"6-inch indium phosphide.{0,120}wafer substrates", coherent, "AXTI-Coherent 6-inch InP product")
    _must(r"initial term of three\s*\(3\)\s*years", coherent, "AXTI-Coherent three-year term")
    _must(r"prepayment of\s+US\$22,288,500", coherent, "AXTI-Coherent prepayment")
    _must(r"minimum order quantity requirement", coherent, "AXTI-Coherent minimum order quantity")
    _must(r"increase its manufacturing capacity.{0,180}2026 through 2028", coherent, "AXTI-Coherent capacity expansion")

    _must(r"Capacity Reservation Agreement", lumentum, "AXTI-Lumentum capacity reservation")
    _must(r"minimum annual commitment", lumentum, "AXTI-Lumentum annual commitment")
    _must(r"six\s*\(6\)\s*year period", lumentum, "AXTI-Lumentum six-year reservation")
    _must(r"initial deposit of\s*\$43,500,000", lumentum, "AXTI-Lumentum first deposit")
    _must(r"second deposit of\s*\$43,500,000", lumentum, "AXTI-Lumentum second deposit")

    _must(r"binding commitment to purchase a fixed aggregate quantity", casela, "AXTI-Casela fixed quantity")
    _must(r"January 1, 2027 through December 31, 2027", casela, "AXTI-Casela 2027 term")
    _must(r"total price of RMB\s*173,000,000.{0,80}\$?25\.4 million", casela, "AXTI-Casela purchase value")
    _must(r"purchase at least 80% of the fixed aggregate quantity", casela, "AXTI-Casela minimum take")

    return {
        "known_inp_competitors": ["Sumitomo Electric", "JX"],
        "typical_customer_qualified_supplier_floor": 2,
        "qualified_substitutes_exist": True,
        "effective_capacity_substitutability_at_current_ramp": "UNPROVEN",
        "capacity_tightness_candidate": True,
        "capacity_tightness_reason": (
            "multiple material multi-year/fixed-quantity capacity commitments coexist "
            "with disclosed qualified substitutes"
        ),
        "capacity_series": [
            {
                "as_of": "2024-12-31",
                "event": "customers_typically_have_at_least_two_qualified_substrate_suppliers",
                "source": base.AXTI_2024_10K,
            },
            {
                "as_of": "2026-06-11",
                "event": "Casela_2027_fixed_quantity_InP_purchase_RMB173m_with_80pct_minimum_take",
                "source": base.AXTI_CASELA_8K,
            },
            {
                "as_of": "2026-06-25",
                "event": "Coherent_three_year_6inch_InP_capacity_commitment_with_22.2885m_prepayment",
                "source": base.AXTI_COHERENT_8K,
            },
            {
                "as_of": "2026-07-26",
                "event": "Lumentum_six_year_InP_minimum_annual_capacity_reservation_with_87m_deposits",
                "source": base.AXTI_LUMENTUM_8K,
            },
        ],
        "order_outlook": {
            "current_orders_summary": (
                "已簽多年 InP 採購/產能承諾：Casela 2027 RMB1.73億固定量；"
                "Coherent 3年6吋InP承諾並預付US$2,228.85萬；Lumentum 6年最低年度承諾"
            ),
            "future_orders_estimate": (
                "能見度偏高但不估總額：Casela 2027至少80%固定量；Coherent 2026-2028擴產供應；"
                "Lumentum 6年年度最低承諾，實際追加量仍取決於需求與可用產能"
            ),
            "confidence": "HIGH_FOR_CONTRACTED_VISIBILITY_NOT_TOTAL_REVENUE",
            "evidence_urls": [base.AXTI_CASELA_8K, base.AXTI_COHERENT_8K, base.AXTI_LUMENTUM_8K],
            "numeric_total_order_estimate_prohibited": True,
        },
        "dependency_promotion_allowed": False,
        "reason_not_promoted": (
            "qualified alternatives are disclosed and effective available capacity/qualification "
            "at the current ramp is not independently proven"
        ),
    }


def apply_h5_v5_transactional(source: dict[str, Any], history_path: Path) -> dict[str, Any]:
    old_map = base.axti_substitute_capacity_map
    try:
        base.axti_substitute_capacity_map = axti_substitute_capacity_map_v5
        document = v4.apply_h5_v4_transactional(source, history_path)
    finally:
        base.axti_substitute_capacity_map = old_map

    document["h5_v5_axti_agreement_ordering"] = True
    document.setdefault("summary", {})["h5_v5_axti_agreement_ordering"] = True
    axti = next(row for row in document["results"] if str(row.get("ticker")) == "AXTI")
    outlook = axti.get("h5_qualified_substitute_capacity", {}).get("order_outlook")
    if not isinstance(outlook, dict):
        raise ValueError("AXTI order outlook was not preserved in H5 v5 output")
    return document


def self_test() -> None:
    v4.self_test()
    text_2024 = "Each customer or prospective customer has at least two qualified substrate suppliers."
    text_2026 = "Sumitomo and JX also compete with us in the InP market."
    coherent = " ".join([
        "The Agreement establishes the terms for the mass development and supply of certain agreed-upon specifications for 6-inch indium phosphide wafer substrates.",
        "The Products are supplied for an initial term of three (3) years from the Effective Date.",
        "AXT has agreed to increase its manufacturing capacity of the Products in 2026 through 2028.",
        "The Capacity Commitment is supported by a prepayment of US$22,288,500.",
        "Coherent has a minimum order quantity requirement.",
    ])
    lumentum = " ".join([
        "The parties entered into a Capacity Reservation Agreement.",
        "AXT will reserve a minimum annual commitment for a six (6) year period.",
        "Lumentum will pay an initial deposit of $43,500,000 and a second deposit of $43,500,000.",
    ])
    casela = " ".join([
        "Casela made a binding commitment to purchase a fixed aggregate quantity from January 1, 2027 through December 31, 2027.",
        "The total price of RMB 173,000,000 is approximately US $25.4 million.",
        "Casela is required to purchase at least 80% of the fixed aggregate quantity.",
    ])
    result = axti_substitute_capacity_map_v5(text_2024, text_2026, coherent, lumentum, casela)
    assert result["qualified_substitutes_exist"] is True
    assert result["capacity_tightness_candidate"] is True
    assert result["dependency_promotion_allowed"] is False
    assert result["order_outlook"]["numeric_total_order_estimate_prohibited"] is True
    assert "RMB1.73億" in result["order_outlook"]["current_orders_summary"]
    print("V213_H5_V5_AXTI_AGREEMENT_ORDERING = PASS")
    print("V213_H5_V5_AXTI_ORDER_OUTLOOK = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=base.DEFAULT_OUTPUT)
    parser.add_argument("--history", type=Path, default=base.DEFAULT_HISTORY)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.input is None:
        parser.error("--input is required unless --self-test is used")
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    document = apply_h5_v5_transactional(source, args.history)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pending = args.output.with_name(args.output.name + ".pending")
    pending.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pending.replace(args.output)
    print(json.dumps({
        "status": "PASS",
        "output": str(args.output),
        "source_history": str(args.history),
        "hard_dependency_count": document["summary"]["hard_dependency_count"],
        "axti_agreement_ordering": True,
        "axti_order_outlook": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
