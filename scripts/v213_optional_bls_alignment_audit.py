#!/usr/bin/env python3
"""Regression audit for optional BLS activation policy alignment."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "v213-source-federation-policy.json"
CONTRACT_PATH = ROOT / "config" / "v213-r75-publication-mode-v1.json"
CANONICAL_ACTIVATION = ROOT / "activate-v213-seven-field-schedule.ps1"
COMPATIBILITY_ALIAS = (
    ROOT / "activate-v213-seven-field-schedule-serenity-latest.ps1"
)
FORWARD_TARGET = ROOT / "activate-v213-diversified-schedule.ps1"
STALE_REQUIRED = "$required=@('us_sec','nasdaq','world_bank','us_bls','ecb')"
SHARED_PREFLIGHT_MARKERS = (
    "v213_r75_activation_preflight.py",
    "v213-r75-publication-mode-v1.json",
    "test-sourceindependencedocument",
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

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8-sig"))
    required_policy = {
        row["family"] for row in live_sources.values()
        if isinstance(row, dict) and row.get("required") is True
    }
    required_contract = set(contract.get("required_federation_families", []))
    if required_contract != required_policy or "us_bls" in required_contract:
        fail("shared R75 contract does not match the policy-required non-BLS families")
    thresholds = contract.get("thresholds", {})
    if int(thresholds.get("min_successful_families", 0)) != int(policy.get("minimum_global_successful_families", 0)):
        fail("shared R75 successful-family threshold differs from source policy")
    if int(thresholds.get("min_official_successful_families", 0)) != int(policy.get("minimum_global_official_families", 0)):
        fail("shared R75 official-family threshold differs from source policy")

    texts = {
        wrapper.name: wrapper.read_text(encoding="utf-8-sig")
        for wrapper in (CANONICAL_ACTIVATION, COMPATIBILITY_ALIAS, FORWARD_TARGET)
    }
    for name, raw in texts.items():
        compact = "".join(raw.split()).casefold()
        if STALE_REQUIRED.casefold() in compact:
            fail(f"{name} still hard-requires optional BLS")
    # The two implementation wrappers delegate to the shared preflight
    # directly; the consolidated compatibility alias reaches it through its
    # forward target, so the markers are enforced on both implementations
    # and the alias is pinned to that target with an identical parameter
    # contract (tests/test_compatibility_entrypoints.py owns the runtime
    # forwarding proof).
    for wrapper in (CANONICAL_ACTIVATION, FORWARD_TARGET):
        compact = "".join(texts[wrapper.name].split()).casefold()
        for marker in SHARED_PREFLIGHT_MARKERS:
            if marker.casefold() not in compact:
                fail(f"{wrapper.name} does not delegate to the shared R75 contract/preflight: {marker}")
    alias_raw = texts[COMPATIBILITY_ALIAS.name]
    target_name = FORWARD_TARGET.name
    if target_name not in alias_raw:
        fail(f"{COMPATIBILITY_ALIAS.name} no longer forwards to {target_name}")
    if "@PSBoundParameters" not in alias_raw or "exit $LASTEXITCODE" not in alias_raw:
        fail(
            f"{COMPATIBILITY_ALIAS.name} no longer forwards all bound parameters and exit codes"
        )
    if "param(" not in alias_raw or "param(" not in texts[target_name]:
        fail(f"{COMPATIBILITY_ALIAS.name} or {target_name} lost its parameter block")
    alias_block = alias_raw[: alias_raw.index("\n)\n", alias_raw.index("param(")) + 3]
    target_block = texts[target_name][
        : texts[target_name].index("\n)\n", texts[target_name].index("param(")) + 3
    ]
    if alias_block != target_block:
        fail(f"{COMPATIBILITY_ALIAS.name} parameter contract drifted from {target_name}")

    print(
        "V213_OPTIONAL_BLS_ALIGNMENT = PASS; "
        "bls_required=false; "
        "minimum_total_families=4; "
        "minimum_official_families=4; "
        "alias_forwarding=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
