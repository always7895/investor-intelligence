#!/usr/bin/env python3
"""Validate the Phase 8 synthetic fault-injection matrix.

Default development mode accepts a structurally valid matrix with explicit
pending scenarios. Release mode (``--require-complete``) fails until every
scenario is backed by a retained test and the release-status gate is PASS.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "phase8-fault-injection-policy.json"
DEFAULT_RELEASE_STATUS = ROOT / "config" / "release-candidate-status.json"
PENDING = "PENDING_IMPLEMENTATION"
REQUIRED_SCENARIOS = {
    "source_rate_limit_429",
    "source_schema_change",
    "source_private_ip_redirect",
    "source_payload_too_large",
    "public_snapshot_partial_upload",
    "public_snapshot_unknown_field",
    "public_option_private_field",
    "cross_tenant_job_reference",
    "tenant_delete_during_retry",
    "webhook_duplicate_redelivery",
    "kv_namespace_id_reuse",
    "clock_rollback",
    "missed_schedule_backlog",
    "public_provider_unavailable",
    "local_model_route_redirect",
    "release_partial_pass",
    "clean_install_without_developer_cache",
    "package_checksum_or_sbom_mismatch",
}


class Phase8PolicyError(ValueError):
    """Raised when the fault-injection matrix is malformed."""


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise Phase8PolicyError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Phase8PolicyError(f"Expected an object in {path}")
    return value


def _module_path(root: Path, module: str) -> Path | None:
    if module == PENDING:
        return None
    if module.endswith(".ts"):
        return root / module
    if module.startswith("tests."):
        return root / (module.replace(".", "/") + ".py")
    return root / module


def audit_phase8_matrix(
    policy: Mapping[str, Any],
    release_status: Mapping[str, Any],
    *,
    root: Path = ROOT,
    require_complete: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    findings: list[str] = []
    allowed_top = {
        "schema_version",
        "automatic_production_fault_injection",
        "synthetic_offline_only",
        "destructive_actions_allowed",
        "real_credentials_allowed",
        "real_user_data_allowed",
        "release_requires_every_scenario_pass",
        "scenarios",
    }
    unknown = sorted(set(policy).difference(allowed_top))
    if unknown:
        findings.append("Phase 8 policy contains unknown fields: " + ", ".join(unknown))
    if policy.get("schema_version") != 1:
        findings.append("Phase 8 schema_version must be 1")
    for key in (
        "automatic_production_fault_injection",
        "destructive_actions_allowed",
        "real_credentials_allowed",
        "real_user_data_allowed",
    ):
        if policy.get(key) is not False:
            findings.append(f"Phase 8 requires {key}=false")
    for key in ("synthetic_offline_only", "release_requires_every_scenario_pass"):
        if policy.get(key) is not True:
            findings.append(f"Phase 8 requires {key}=true")

    scenarios = policy.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise Phase8PolicyError("Phase 8 scenarios must be a non-empty array")
    seen: set[str] = set()
    pending: list[str] = []
    categories: set[str] = set()
    allowed_scenario = {"id", "category", "required_outcome", "test_module"}
    for index, scenario in enumerate(scenarios):
        label = f"scenarios[{index}]"
        if not isinstance(scenario, dict):
            findings.append(f"{label} must be an object")
            continue
        unknown_fields = sorted(set(scenario).difference(allowed_scenario))
        missing = sorted(allowed_scenario.difference(scenario))
        if unknown_fields:
            findings.append(f"{label} has unknown fields: {', '.join(unknown_fields)}")
        if missing:
            findings.append(f"{label} is missing fields: {', '.join(missing)}")
        scenario_id = str(scenario.get("id") or "").strip()
        category = str(scenario.get("category") or "").strip()
        outcome = str(scenario.get("required_outcome") or "").strip()
        module = str(scenario.get("test_module") or "").strip()
        if not scenario_id or scenario_id in seen:
            findings.append(f"{label} has missing or duplicate id")
        seen.add(scenario_id)
        if not category:
            findings.append(f"{scenario_id or label}: category is required")
        categories.add(category)
        if not outcome:
            findings.append(f"{scenario_id or label}: required_outcome is required")
        if module == PENDING:
            pending.append(scenario_id)
        else:
            path = _module_path(root, module)
            if path is None or not path.is_file():
                findings.append(
                    f"{scenario_id or label}: retained test module does not exist: {module}"
                )

    missing_scenarios = sorted(REQUIRED_SCENARIOS.difference(seen))
    extra_scenarios = sorted(seen.difference(REQUIRED_SCENARIOS))
    if missing_scenarios:
        findings.append("required Phase 8 scenarios missing: " + ", ".join(missing_scenarios))
    if extra_scenarios:
        findings.append("unknown Phase 8 scenarios: " + ", ".join(extra_scenarios))
    if len(categories) < 8:
        findings.append("Phase 8 matrix lacks category diversity")

    release_gates = release_status.get("gates")
    phase8_state = (
        release_gates.get("phase_8_disaster_recovery")
        if isinstance(release_gates, dict)
        else None
    )
    if pending and phase8_state == "PASS":
        findings.append("release status cannot mark Phase 8 PASS while scenarios are pending")
    if require_complete:
        if pending:
            findings.append("Phase 8 completion requested with pending scenarios: " + ", ".join(pending))
        if phase8_state != "PASS":
            findings.append("Phase 8 completion requires release status gate PASS")

    summary = {
        "scenario_count": len(scenarios),
        "category_count": len(categories),
        "pending_count": len(pending),
        "pending_scenarios": sorted(pending),
        "complete": not pending and phase8_state == "PASS",
        "synthetic_offline_only": True,
        "destructive_actions_allowed": False,
        "release_phase8_state": phase8_state,
    }
    return findings, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        findings, summary = audit_phase8_matrix(
            load_object(DEFAULT_POLICY),
            load_object(DEFAULT_RELEASE_STATUS),
            require_complete=args.require_complete,
        )
    except (FileNotFoundError, Phase8PolicyError, OSError) as exc:
        print(f"PHASE 8 FAULT-INJECTION GATE FAILED\n- {exc}")
        return 1
    if findings:
        print("PHASE 8 FAULT-INJECTION GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("PHASE 8 FAULT-INJECTION MATRIX VALID")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
