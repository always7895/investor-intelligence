#!/usr/bin/env python3
"""H5 v4: complete fetch/transactional history plus current SIVE financing context.

v4 builds on H5 v3 and adds the two material Sivers equity events that occurred
after the June directed issue: the July convertible-loan conversion and August
warrant exercise, including the 31-Aug-2026 official share count.

The additional facts increase factual equity-capture pressure but still do not,
by themselves, prove a 'toxic financing' characterization or a hard dependency.
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

import v213_serenity_h5_fidelity_deepening_v3 as v3

base = v3.base

SIVE_CONVERSION = "https://www.sivers-semiconductors.com/press/sivers-semiconductors-lender-bootstrap-europe-exercises-conversion-right-under-existing-convertible-loan/"
SIVE_WARRANT = "https://www.sivers-semiconductors.com/press/bootstrap-exercises-warrants-in-sivers-semiconductors/"
SIVE_AUG31_SHARE_COUNT = "https://www.sivers-semiconductors.com/press/change-in-the-total-number-of-shares-and-votes-in-sivers-semiconductors-ab-12/"


def _must(pattern: str, text: str, label: str) -> re.Match[str]:
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        raise ValueError(f"required evidence not found: {label}")
    return match


def sive_financing_and_capacity_v4(april: str, june: str, q1: str, q2: str, aug31: str) -> dict[str, Any]:
    _must(r"8,620,000 ordinary shares.{0,260}SEK 14\.5", april, "SIVE April directed issue")
    _must(r"dilution of approximately 2\.5 percent", april, "SIVE April dilution")
    _must(r"12,280,701 ordinary shares.{0,260}SEK 57 per share", june, "SIVE June directed issue")
    _must(r"discount of approximately 9\.7 percent", june, "SIVE June discount")
    _must(r"dilution of approximately 3\.3 percent", june, "SIVE June dilution")
    _must(r"qual builds and production readiness is on track.{0,180}Q4 2026", q1, "SIVE Q4 2026 production readiness")
    _must(r"multi-year imbalance.{0,220}demand-supply.{0,280}optical networking", q1, "SIVE optical demand-supply imbalance")
    _must(r"Product Revenue Increases 18% Year-Over-Year", q2, "SIVE Q2 product growth")
    _must(r"directed share issues amounting to approximately SEK 825 m", q2, "SIVE Q2 directed capital")

    conversion = v3.fetch_text_complete(SIVE_CONVERSION)
    warrant = v3.fetch_text_complete(SIVE_WARRANT)
    _must(r"convert the convertible loan of \$12M into shares.{0,260}22,847,044 new ordinary shares", conversion, "SIVE Bootstrap conversion")
    _must(r"conversion price of SEK 4\.77 per share", conversion, "SIVE Bootstrap conversion price")
    _must(r"dilution of approximately 6\.4 per\s*cent", conversion, "SIVE Bootstrap conversion dilution")
    _must(r"1,659,015 new ordinary shares", warrant, "SIVE warrant shares")
    _must(r"subscription price of SEK 4\.53 per share", warrant, "SIVE warrant exercise price")
    _must(r"proceeds of approximately SEK 7\.5 million", warrant, "SIVE warrant proceeds")
    _must(r"356,740,332 ordinary shares", aug31, "SIVE August share count")
    _must(r"increased by 1,659,015, from 355,081,317 to 356,740,332", aug31, "SIVE August warrant share-count bridge")

    registered_before_april = 311_333_572
    latest_registered = 356_740_332
    issued_2026_tracked = latest_registered - registered_before_april
    share_growth = round((latest_registered / registered_before_april - 1.0) * 100.0, 2)

    return {
        "financing_events": [
            {
                "as_of": "2026-04-16",
                "type": "directed_institutional_share_issue",
                "gross_sek": 125_000_000,
                "new_shares": 8_620_000,
                "reported_fully_diluted_dilution_pct": 2.5,
                "pricing_context": "1.3% discount to 10-day VWAP and 29.8% premium to 30-day VWAP",
                "source": base.SIVE_APRIL_ISSUE,
            },
            {
                "as_of": "2026-07-01",
                "type": "accelerated_bookbuild_directed_share_issue",
                "gross_sek": 700_000_000,
                "new_shares": 12_280_701,
                "reported_fully_diluted_dilution_pct": 3.3,
                "pricing_context": "9.7% discount to June 30 close; multiple-times oversubscribed institutional bookbuild",
                "source": base.SIVE_JUNE_ISSUE,
            },
            {
                "as_of": "2026-07-03",
                "type": "secured_convertible_loan_full_conversion",
                "principal_usd": 12_000_000,
                "conversion_price_sek_per_share": 4.77,
                "new_shares": 22_847_044,
                "reported_dilution_pct": 6.4,
                "source": SIVE_CONVERSION,
            },
            {
                "as_of": "2026-08-13",
                "type": "lender_warrant_exercise",
                "subscription_price_sek_per_share": 4.53,
                "new_shares": 1_659_015,
                "cash_proceeds_sek_approx": 7_500_000,
                "source": SIVE_WARRANT,
            },
        ],
        "q2_reported_directed_equity_capital_sek": 825_000_000,
        "registered_shares_before_april_2026": registered_before_april,
        "registered_shares_2026_08_31": latest_registered,
        "tracked_new_registered_shares_2026": issued_2026_tracked,
        "registered_share_count_growth_pct": share_growth,
        "equity_capture_pressure": "MATERIAL",
        "toxic_financing_proven": False,
        "toxicity_reason": "multiple material equity events are factual, including a low-strike debt conversion and warrant exercise; however factual dilution alone does not prove the private intent/value-transfer pattern required for a toxic-financing characterization",
        "capacity_series": [
            {
                "as_of": "2026-05-29",
                "event": "LiDAR_qualification_builds_and_Q4_2026_production_readiness_on_track",
                "source": base.SIVE_Q1,
            },
            {
                "as_of": "2026-05-29",
                "event": "management_reports_multi_year_optical_networking_demand_supply_imbalance_and_relevant_manufacturing_capacity_strategy",
                "source": base.SIVE_Q1,
            },
            {
                "as_of": "2026-08-27",
                "event": "product_revenue_up_18pct_yoy_and_customer_production_ramps",
                "source": base.SIVE_Q2,
            },
        ],
        "latest_share_count_source": SIVE_AUG31_SHARE_COUNT,
    }


def apply_h5_v4_transactional(source: dict[str, Any], history_path: Path) -> dict[str, Any]:
    old_sive = base.sive_financing_and_capacity
    old_share_url = base.SIVE_SHARE_COUNT
    pre_entries = len(base.read_history(history_path)) if history_path.exists() else 0
    try:
        base.sive_financing_and_capacity = sive_financing_and_capacity_v4
        base.SIVE_SHARE_COUNT = SIVE_AUG31_SHARE_COUNT
        document = v3.apply_h5_transactional(source, history_path)
    finally:
        base.sive_financing_and_capacity = old_sive
        base.SIVE_SHARE_COUNT = old_share_url

    final_rows = base.read_history(history_path)
    document["source_history"]["appended"] = max(0, len(final_rows) - pre_entries)
    document["source_history"]["entries"] = len(final_rows)
    document["h5_v4_current_sive_financing"] = True
    document.setdefault("summary", {})["h5_v4_current_sive_financing"] = True

    sive = next(row for row in document["results"] if str(row.get("ticker")) == "SIVE")
    sive["h5_source_delta"] = {
        "requires_updated_serenity_view": True,
        "reason": "the March high-upside public view predates two directed issues, the July full convertible-loan conversion, the August warrant exercise, and subsequent customer/GF production-ramp evidence",
        "do_not_infer_current_view": True,
        "delta_direction": "MIXED",
    }
    warnings = list(sive.get("warnings") or [])
    warning = "2026 SIVE equity-capture context includes two directed issues, a $12m convertible-loan conversion and a lender warrant exercise; material dilution is factual but toxicity remains unproven"
    if warning not in warnings:
        warnings.append(warning)
    sive["warnings"] = warnings
    return document


def self_test() -> None:
    v3.self_test()
    april = "8,620,000 ordinary shares at SEK 14.5 per share; dilution of approximately 2.5 percent"
    june = "12,280,701 ordinary shares at SEK 57 per share; discount of approximately 9.7 percent; dilution of approximately 3.3 percent"
    q1 = "qual builds and production readiness is on track for Q4 2026; massive multi-year imbalance in the demand-supply situation for optical networking"
    q2 = "Product Revenue Increases 18% Year-Over-Year; directed share issues amounting to approximately SEK 825 m"
    aug31 = "356,740,332 ordinary shares; increased by 1,659,015, from 355,081,317 to 356,740,332"
    conversion = "convert the convertible loan of $12M into shares and issue 22,847,044 new ordinary shares; conversion price of SEK 4.77 per share; dilution of approximately 6.4 percent"
    warrant = "1,659,015 new ordinary shares at a subscription price of SEK 4.53 per share; proceeds of approximately SEK 7.5 million"
    old_fetch = v3.fetch_text_complete
    try:
        def fake_fetch(url: str, **_: Any) -> str:
            if url == SIVE_CONVERSION:
                return conversion
            if url == SIVE_WARRANT:
                return warrant
            raise AssertionError(url)
        v3.fetch_text_complete = fake_fetch  # type: ignore[assignment]
        result = sive_financing_and_capacity_v4(april, june, q1, q2, aug31)
    finally:
        v3.fetch_text_complete = old_fetch  # type: ignore[assignment]
    assert len(result["financing_events"]) == 4
    assert result["registered_shares_2026_08_31"] == 356_740_332
    assert result["registered_share_count_growth_pct"] > 14
    assert result["equity_capture_pressure"] == "MATERIAL"
    assert result["toxic_financing_proven"] is False
    print("V213_H5_V4_CURRENT_SIVE_FINANCING = PASS")


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
    document = apply_h5_v4_transactional(source, args.history)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pending = args.output.with_name(args.output.name + ".pending")
    pending.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pending.replace(args.output)
    print(json.dumps({
        "status": "PASS",
        "output": str(args.output),
        "source_history": str(args.history),
        "hard_dependency_count": document["summary"]["hard_dependency_count"],
        "complete_sec_fetch": True,
        "transactional_history": True,
        "current_sive_financing": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
