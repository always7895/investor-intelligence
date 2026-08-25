#!/usr/bin/env python3
"""Fail closed when workflows can silently grow GitHub Actions storage."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "actions-storage-policy.json"
WORKFLOW_DIR = ROOT / ".github" / "workflows"
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)
RETENTION_RE = re.compile(r"(?im)^\s*retention-days:\s*([0-9]+)\s*$")
CACHE_WITH_RE = re.compile(r"(?im)^\s*cache:\s*(?!false\b|['\"]?['\"]?\s*$).+")

EXPECTED_TOP_LEVEL = {
    "schema_version",
    "artifact_and_log_retention_days_target",
    "artifact_upload",
    "dependency_cache",
    "workflow_run_cleanup",
    "safety",
}
EXPECTED_ARTIFACT_UPLOAD = {
    "allowed",
    "maximum_retention_days",
    "required_only_for_final_release_evidence",
    "require_immutable_action_sha",
}
EXPECTED_CACHE = {"allowed", "reason"}
EXPECTED_RUN_CLEANUP = {
    "completed_runs_may_be_deleted",
    "preserve_exact_release_head",
    "preserve_in_progress_runs",
    "preserve_latest_runs_per_workflow",
    "preserve_latest_success_per_workflow",
    "preserve_latest_failure_per_workflow",
    "maximum_deletes_per_transaction",
    "minimum_age_hours",
}
EXPECTED_SAFETY = {
    "local_history_backups_must_not_be_modified",
    "git_refs_must_not_be_modified",
    "deployment_must_not_be_performed",
    "billing_must_not_be_enabled",
    "line_and_ibkr_must_remain_disabled",
}


def _require_closed_object(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing = sorted(expected.difference(value))
    unknown = sorted(set(value).difference(expected))
    if missing:
        raise ValueError(f"{label} is missing field(s): {', '.join(missing)}")
    if unknown:
        raise ValueError(f"{label} has unknown field(s): {', '.join(unknown)}")
    return value


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = _require_closed_object(
        json.loads(path.read_text(encoding="utf-8")), EXPECTED_TOP_LEVEL, "policy"
    )
    if policy["schema_version"] != 1:
        raise ValueError("unsupported Actions storage policy schema")
    target = policy["artifact_and_log_retention_days_target"]
    if not isinstance(target, int) or isinstance(target, bool) or target != 1:
        raise ValueError("artifact/log retention target must be exactly one day")

    upload = _require_closed_object(
        policy["artifact_upload"], EXPECTED_ARTIFACT_UPLOAD, "artifact_upload"
    )
    if upload != {
        "allowed": True,
        "maximum_retention_days": 1,
        "required_only_for_final_release_evidence": True,
        "require_immutable_action_sha": True,
    }:
        raise ValueError("artifact_upload policy is not the reviewed fail-closed value")

    cache = _require_closed_object(policy["dependency_cache"], EXPECTED_CACHE, "dependency_cache")
    if cache["allowed"] is not False or not str(cache["reason"]).strip():
        raise ValueError("Actions dependency caching must remain forbidden with a reason")

    cleanup = _require_closed_object(
        policy["workflow_run_cleanup"], EXPECTED_RUN_CLEANUP, "workflow_run_cleanup"
    )
    required_true = (
        "completed_runs_may_be_deleted",
        "preserve_exact_release_head",
        "preserve_in_progress_runs",
        "preserve_latest_success_per_workflow",
        "preserve_latest_failure_per_workflow",
    )
    if any(cleanup[key] is not True for key in required_true):
        raise ValueError("workflow cleanup safety assertions must remain true")
    if cleanup["preserve_latest_runs_per_workflow"] < 2:
        raise ValueError("at least two recent runs per workflow must be preserved")
    if not 1 <= cleanup["maximum_deletes_per_transaction"] <= 3900:
        raise ValueError("workflow deletion transaction size is outside the reviewed bound")
    if cleanup["minimum_age_hours"] < 2:
        raise ValueError("workflow cleanup may not delete runs younger than two hours")

    safety = _require_closed_object(policy["safety"], EXPECTED_SAFETY, "safety")
    if any(value is not True for value in safety.values()):
        raise ValueError("all Actions cleanup safety assertions must remain true")
    return policy


def workflow_paths(root: Path = ROOT) -> list[Path]:
    directory = root / ".github" / "workflows"
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() in {".yml", ".yaml"}
    )


def audit_workflows(root: Path = ROOT) -> list[str]:
    policy = load_policy(root / "config" / "actions-storage-policy.json")
    maximum_retention = int(policy["artifact_upload"]["maximum_retention_days"])
    findings: list[str] = []

    for path in workflow_paths(root):
        relative = path.relative_to(root)
        text = path.read_text(encoding="utf-8")
        lower = text.casefold()

        for match in USES_RE.finditer(text):
            reference = match.group(1)
            action, _, ref = reference.rpartition("@")
            action_lower = action.casefold()
            line_number = text.count("\n", 0, match.start()) + 1
            if action_lower in {"actions/cache", "actions/cache/restore", "actions/cache/save"}:
                findings.append(f"{relative}:{line_number}: Actions dependency cache is forbidden")
            if action_lower == "actions/upload-artifact":
                if not FULL_SHA_RE.fullmatch(ref):
                    findings.append(
                        f"{relative}:{line_number}: upload-artifact must use an immutable full SHA"
                    )
                nearby = text[match.start() : match.start() + 1200]
                retention = RETENTION_RE.search(nearby)
                if retention is None:
                    findings.append(
                        f"{relative}:{line_number}: upload-artifact lacks retention-days"
                    )
                elif int(retention.group(1)) > maximum_retention:
                    findings.append(
                        f"{relative}:{line_number}: artifact retention exceeds {maximum_retention} day"
                    )
                if "final" not in nearby.casefold() and "release" not in nearby.casefold():
                    findings.append(
                        f"{relative}:{line_number}: artifact upload is not explicitly final-release evidence"
                    )

        if "actions/cache" not in lower and CACHE_WITH_RE.search(text):
            for match in CACHE_WITH_RE.finditer(text):
                line_number = text.count("\n", 0, match.start()) + 1
                findings.append(
                    f"{relative}:{line_number}: setup-action dependency caching is forbidden"
                )

    return findings


def main() -> int:
    try:
        findings = audit_workflows()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ACTIONS STORAGE POLICY GATE FAILED: {exc}")
        return 1
    if findings:
        print("ACTIONS STORAGE POLICY GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(
        "ACTIONS STORAGE POLICY GATE PASSED: one-day artifact/log target, no Actions dependency cache, "
        "and any future final-release artifact must be SHA-pinned with one-day retention"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
