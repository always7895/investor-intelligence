#!/usr/bin/env python3
"""Validate release truth and refuse premature deployment or packaging."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS_PATH = ROOT / "config" / "release-candidate-status.json"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
VALID_GATE_STATES = {"PENDING", "PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"}
MANDATORY_GATES = {
    "canonical_stack_reconciled",
    "phase_1_2_exact_head",
    "phase_3_catalog_exact_head",
    "phase_3_adapters_exact_head",
    "phase_3_source_diversity",
    "line_broker_separation",
    "line_public_closed_schema",
    "public_options_provider_review",
    "physical_kv_namespace_isolation",
    "cross_tenant_fault_injection",
    "phase_4_reports",
    "phase_7_scheduling_recovery",
    "phase_8_disaster_recovery",
    "full_git_history_privacy_scan",
    "clean_install",
    "reproducible_package",
    "sbom_manifest_checksums",
}


class ReleaseCandidateError(ValueError):
    """Raised when release status is malformed or unsafe."""


def load_status(path: Path = DEFAULT_STATUS_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ReleaseCandidateError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseCandidateError("Release candidate status must be an object")
    return value


def git_head(root: Path = ROOT) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def audit_release_status(
    document: dict[str, Any],
    *,
    expected_head: str | None = None,
    require_ready: bool = False,
) -> list[str]:
    findings: list[str] = []
    allowed_top = {
        "schema_version",
        "release_ready",
        "deployed",
        "billing_enabled",
        "external_users_admitted",
        "candidate_commit",
        "candidate_version",
        "gates",
        "hard_blockers",
        "local_action_required",
        "secrets_required_now",
        "notes",
    }
    unknown = sorted(set(document).difference(allowed_top))
    if unknown:
        findings.append("release status contains unknown fields: " + ", ".join(unknown))
    if document.get("schema_version") != 1:
        findings.append("schema_version must be 1")

    gates = document.get("gates")
    if not isinstance(gates, dict):
        findings.append("gates must be an object")
        gates = {}
    missing = sorted(MANDATORY_GATES.difference(gates))
    extra = sorted(set(gates).difference(MANDATORY_GATES))
    if missing:
        findings.append("mandatory release gates missing: " + ", ".join(missing))
    if extra:
        findings.append("unknown release gates: " + ", ".join(extra))
    for name, state in gates.items():
        if state not in VALID_GATE_STATES:
            findings.append(f"gate {name} has invalid state {state!r}")

    blockers = document.get("hard_blockers")
    if not isinstance(blockers, list) or not all(
        isinstance(value, str) and value.strip() for value in blockers
    ):
        findings.append("hard_blockers must be a string array")
        blockers = []

    release_ready = document.get("release_ready") is True
    all_pass = bool(gates) and all(gates.get(name) == "PASS" for name in MANDATORY_GATES)
    candidate_commit = document.get("candidate_commit")
    candidate_version = document.get("candidate_version")

    if release_ready:
        if not all_pass:
            findings.append("release_ready=true requires every mandatory gate to be PASS")
        if blockers:
            findings.append("release_ready=true requires hard_blockers to be empty")
        if not isinstance(candidate_commit, str) or not COMMIT_RE.fullmatch(candidate_commit):
            findings.append("release_ready=true requires a full candidate_commit SHA")
        if not isinstance(candidate_version, str) or not VERSION_RE.fullmatch(candidate_version):
            findings.append("release_ready=true requires a semantic candidate_version")
        if expected_head and candidate_commit != expected_head:
            findings.append("candidate_commit does not match the exact checked-out head")
    else:
        if document.get("deployed") is True:
            findings.append("deployed=true is forbidden while release_ready=false")
        if document.get("billing_enabled") is True:
            findings.append("billing_enabled=true is forbidden while release_ready=false")
        if document.get("external_users_admitted") is True:
            findings.append("external_users_admitted=true is forbidden while release_ready=false")
        if candidate_commit not in (None, "") and not (
            isinstance(candidate_commit, str) and COMMIT_RE.fullmatch(candidate_commit)
        ):
            findings.append("candidate_commit must be null or a full SHA")
        if candidate_version not in (None, "") and not (
            isinstance(candidate_version, str) and VERSION_RE.fullmatch(candidate_version)
        ):
            findings.append("candidate_version must be null or semantic")

    if document.get("local_action_required") is not False:
        findings.append("local_action_required must remain false until an explicit reviewed handoff")
    if document.get("secrets_required_now") is not False:
        findings.append("secrets_required_now must remain false during development")
    if require_ready and not release_ready:
        findings.append("release was requested but release_ready is false")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Release-only mode: require every gate to be PASS and bind to HEAD",
    )
    args = parser.parse_args()
    try:
        document = load_status()
        findings = audit_release_status(
            document,
            expected_head=git_head() if args.require_ready else None,
            require_ready=args.require_ready,
        )
    except (FileNotFoundError, ReleaseCandidateError, OSError) as exc:
        print(f"RELEASE CANDIDATE GATE FAILED\n- {exc}")
        return 1
    if findings:
        print("RELEASE CANDIDATE GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    if document.get("release_ready") is True:
        print("RELEASE CANDIDATE GATE PASSED: exact candidate is ready")
    else:
        print("RELEASE CANDIDATE GATE PASSED: development remains fail closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
