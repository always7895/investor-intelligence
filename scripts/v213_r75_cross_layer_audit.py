#!/usr/bin/env python3
"""Static audit for the v2.1.3 R75 cross-layer activation contract."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def require(path: str, markers: tuple[str, ...], failures: list[str]) -> None:
    value = text(path)
    for marker in markers:
        if marker not in value:
            failures.append(f"{path} missing {marker}")


def main() -> int:
    failures: list[str] = []
    require(
        "activate-v213-seven-field-schedule.ps1",
        (
            "v213_r75_activation_preflight_entry.py",
            "V213_ACTIVATION_PREFLIGHT_ONLY",
            "V213_R75_SEALED_BUNDLE_SHA256",
            "publication_mode_aware=true",
        ),
        failures,
    )
    if text("activate-v213-seven-field-schedule.ps1") != text(
        "activate-v213-seven-field-schedule-serenity-latest.ps1"
    ):
        failures.append("canonical activation and Serenity alias differ")
    if text("activate-v213-seven-field-schedule.ps1") != text(
        "activate-v213-diversified-schedule.ps1"
    ):
        failures.append("canonical activation and diversified alias differ")
    require(
        "activate-v213-seven-field-schedule-core.ps1",
        (
            "V213_R75_SEALED_BUNDLE_SHA256",
            "V213_R75_ACTIVATION_LOCK",
            "install-v213-r75-runtime.ps1",
            "V213_BROADCAST_DEDUPE",
            "LOCAL_LLM_TIMEOUT_MS",
        ),
        failures,
    )
    require(
        "scripts/run_v213_local_llm_bridge_core.ps1",
        ("v213_local_llm_gateway_r75.py",),
        failures,
    )
    require(
        "scripts/run_v213_local_llm_bridge_core_v3.ps1",
        (
            "BridgeSource",
            "quick_ephemeral",
            "consecutive_public_health_checks",
            "spaced_or_parenthesized_source_path_supported",
        ),
        failures,
    )
    require(
        "scripts/v213_local_llm_gateway_r75.py",
        (
            "MODEL_PIN_MISMATCH",
            '"model": selected',
            "request_model_substitution_allowed",
        ),
        failures,
    )
    require(
        "cloud/src/v213/activation-v2.ts",
        (
            "validateR75PublicationModes",
            "verifySnapshotObjects",
            "idempotentReplay",
        ),
        failures,
    )
    worker = text("cloud/src/v213/activation-v2.ts")
    if '["us_sec", "nasdaq", "world_bank", "us_bls", "ecb"]' in worker:
        failures.append("Worker still hard-requires optional BLS")
    if "expirationTtl: 259200" in worker:
        failures.append("Worker retains three-day TTL on immutable snapshot data")
    require(
        "cloud/src/v213/publication-mode.ts",
        (
            "LIMITED_RESEARCH_CANDIDATE",
            "publication_provenance_origin_count",
            "positiveSensitiveFactors",
        ),
        failures,
    )
    require(
        "cloud/src/v213/broadcast.ts",
        ("runV213BroadcastOnce", "V213_BROADCAST_DEDUPE"),
        failures,
    )
    require(
        "cloud/src/v213/broadcast-dedupe.ts",
        ("DurableObjectState", 'status: "pending" | "sent"', "runV213BroadcastOnce"),
        failures,
    )
    require(
        "cloud/src/v213/production-worker.ts",
        ("V213BroadcastDedupe",),
        failures,
    )
    require(
        "cloud/src/qa.ts",
        ("LOCAL_LLM_TIMEOUT_MS", "localModelTimeoutMs"),
        failures,
    )
    require(
        "register-v213-refresh-tasks.ps1",
        ("WakeToRun", "RestartCount 3", "run-v213-scheduled-refresh.ps1"),
        failures,
    )
    require(
        "run-v213-scheduled-refresh.ps1",
        ("-NoModelBridge", "-NoTunnel", "-NoSync", "production_mutation=$false"),
        failures,
    )
    require(
        "scripts/v21_serenity_top20.py",
        ("V213_CANDIDATE_SEED_REUSE_SECONDS", "candidate seed reused"),
        failures,
    )
    policy = json.loads(text("R75-SOURCE-HARDENING.json"))
    if (
        policy.get("runtime_profile") != "R75"
        or policy.get("production_mutation_by_ci") is not False
        or policy.get("limited_candidate_positive_sensitive_factors_allowed") is not False
        or policy.get("exact_model_request_substitution_allowed") is not False
    ):
        failures.append("R75 source-hardening receipt is invalid")
    if failures:
        print("V213_R75_CROSS_LAYER_AUDIT = FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(
        "V213_R75_CROSS_LAYER_AUDIT = PASS; "
        "sealed_bundle=true; publication_mode=true; optional_bls=true; "
        "snapshot_readback=true; exact_model_pin=true; safe_path=true; "
        "atomic_line_dedupe=true; scheduled_data_only=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
