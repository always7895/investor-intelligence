#!/usr/bin/env python3
"""Regression audit for optional BLS activation policy alignment."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "v213-source-federation-policy.json"
WRAPPERS = (
    ROOT / "activate-v213-seven-field-schedule.ps1",
    ROOT / "activate-v213-seven-field-schedule-serenity-latest.ps1",
    ROOT / "activate-v213-diversified-schedule.ps1",
)
STALE_REQUIRED = "$required=@('us_sec','nasdaq','world_bank','us_bls','ecb')"
CURRENT_REQUIRED = "$required=@('us_sec','nasdaq','world_bank','ecb')"
THRESHOLDS = (
    "$successful.count-lt5",
    "$official.count-lt4",
    "$missingrequired.count-gt0",
)


def fail(message: str) -> None:
    raise SystemExit(f"V213_OPTIONAL_BLS_ALIGNMENT = FAIL; {message}")


def main() -> int:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8-sig"))
    live_sources = policy.get("required_live_sources", {})
    bls_entries = [
        row
        for row in live_sources.values()
        if isinstance(row, dict) and row.get("family") == "us_bls"
    ]
    if len(bls_entries) != 1:
        fail("policy must define exactly one us_bls source")
    bls = bls_entries[0]
    if bls.get("required") is not False:
        fail("BLS macro context regressed to a required activation source")
    if (
        bls.get("outage_behavior")
        != "explicit_quality_degradation_not_company_claim_blocker"
    ):
        fail("BLS outage behavior no longer preserves explicit quality degradation")
    if bls.get("company_claim_evidence") is not False:
        fail("BLS macro context is incorrectly treated as company-claim evidence")
    if policy.get("temporary_macro_endpoint_unavailability_is_global_blocker") is not False:
        fail("temporary macro endpoint outage is incorrectly a global blocker")
    if policy.get("macro_context_is_company_claim_evidence") is not False:
        fail("macro context is incorrectly treated as company-claim evidence")

    activation_gate = policy.get("activation_gate", {})
    if int(activation_gate.get("minimum_successful_official_families", 0)) < 4:
        fail("activation permits fewer than four successful official families")
    if (
        activation_gate.get("temporary_macro_context_outage_is_quality_degradation")
        is not True
    ):
        fail("temporary macro outage is not explicitly a quality degradation")

    texts = []
    for wrapper in WRAPPERS:
        text = wrapper.read_text(encoding="utf-8-sig")
        texts.append(text)
        compact = "".join(text.split()).casefold()
        if STALE_REQUIRED.casefold() in compact:
            fail(f"{wrapper.name} still hard-requires optional BLS")
        if CURRENT_REQUIRED.casefold() not in compact:
            fail(f"{wrapper.name} lacks the policy-aligned core required families")
        for threshold in THRESHOLDS:
            if threshold not in compact:
                fail(f"{wrapper.name} lost activation threshold: {threshold}")

    if texts[0] != texts[1]:
        fail("canonical activation and Serenity compatibility alias are not identical")

    print(
        "V213_OPTIONAL_BLS_ALIGNMENT = PASS; "
        "bls_required=false; "
        "minimum_total_families=5; "
        "minimum_official_families=4; "
        "canonical_alias_equal=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
