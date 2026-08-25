#!/usr/bin/env python3
"""Validate the fail-closed final cleanup policy and exact final receipt.

This retained release tool is deliberately read-only.  It never removes files,
backups, Git refs, Actions artifacts or caches.  A separate one-time maintenance
transaction may use its validation result only after final release acceptance.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = ROOT / "config" / "final-cleanup-policy.json"
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

REQUIRED_TRUE_ASSERTIONS = {
    "release_ready",
    "post_rewrite_fresh_clone",
    "full_history_scope_all_clean",
    "canonical_acceptance",
    "clean_install",
    "reproducible_package",
    "sbom_manifest_checksums",
}
REQUIRED_FALSE_ASSERTIONS = {
    "deployed",
    "billing_enabled",
    "external_users_admitted",
}
REQUIRED_REPOSITORY_DIRECTORIES = {
    ".npm-cache",
    "cloud/node_modules",
    "data/cache",
    "data/history",
    "reports",
}
REQUIRED_FORBIDDEN_ROOTS = {
    ".git",
    ".github",
    "cloud/src",
    "cloud/test",
    "config",
    "docs",
    "schemas",
    "scripts",
    "skills",
    "tests",
}
REQUIRED_BACKUP_PREFIXES = {
    "investor-intelligence-pre-rewrite-",
    "investor-intelligence-history-backup-",
}
REQUIRED_EVIDENCE = {
    "final_release_zip",
    "sha256_checksum",
    "release_manifest",
    "spdx_sbom",
    "final_acceptance_receipt",
    "newest_verified_rollback_bundle",
}
RECEIPT_FIELDS = {
    "schema_version",
    "candidate_commit",
    "candidate_tree",
    "candidate_version",
    "completed_utc",
    "cleanup_authorized",
    "release_ready",
    "deployed",
    "billing_enabled",
    "external_users_admitted",
    "post_rewrite_fresh_clone",
    "full_history_scope_all_clean",
    "canonical_acceptance",
    "clean_install",
    "reproducible_package",
    "sbom_manifest_checksums",
    "final_package_sha256",
}


class FinalCleanupPolicyError(ValueError):
    """Raised when cleanup policy or receipt JSON cannot be trusted."""


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise FinalCleanupPolicyError("JSON document is invalid") from exc
    if not isinstance(value, dict):
        raise FinalCleanupPolicyError("JSON document must contain an object")
    return value


def _exact_keys(
    value: Any,
    expected: set[str],
    label: str,
    findings: list[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        findings.append(f"{label} must be an object")
        return {}
    missing = sorted(expected.difference(value))
    unknown = sorted(set(value).difference(expected))
    if missing:
        findings.append(f"{label} is missing required fields")
    if unknown:
        findings.append(f"{label} contains unknown fields")
    return value


def _string_set(value: Any, label: str, findings: list[str]) -> set[str]:
    if not isinstance(value, list) or not value:
        findings.append(f"{label} must be a non-empty string array")
        return set()
    if not all(isinstance(item, str) and item for item in value):
        findings.append(f"{label} must contain only non-empty strings")
        return set()
    if len(value) != len(set(value)):
        findings.append(f"{label} must not contain duplicates")
    return set(value)


def _safe_relative_directory(value: str) -> bool:
    if not value or "\\" in value or value.startswith("/"):
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    return str(path) == value.rstrip("/")


def _safe_name_prefix(value: str) -> bool:
    return bool(value) and value not in {".", ".."} and "/" not in value and "\\" not in value


def audit_policy(document: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    top = _exact_keys(
        document,
        {
            "schema_version",
            "policy_state",
            "automatic_cleanup",
            "destructive_apply_default",
            "receipt",
            "repository_cleanup",
            "backup_cleanup",
            "git_cleanup",
            "preserve_final_evidence",
        },
        "cleanup policy",
        findings,
    )
    if top.get("schema_version") != 1:
        findings.append("cleanup policy schema_version must be 1")
    if top.get("policy_state") != "LOCKED_UNTIL_FINAL_RECEIPT":
        findings.append("cleanup policy must remain locked until a final receipt")
    if top.get("automatic_cleanup") is not False:
        findings.append("automatic cleanup must remain false")
    if top.get("destructive_apply_default") is not False:
        findings.append("destructive apply must remain false by default")

    receipt = _exact_keys(
        top.get("receipt"),
        {
            "schema_version",
            "required",
            "exact_candidate_binding",
            "cleanup_authorized_must_be_true",
            "required_true_assertions",
            "required_false_assertions",
        },
        "receipt policy",
        findings,
    )
    if receipt.get("schema_version") != 1:
        findings.append("receipt policy schema_version must be 1")
    for key in ("required", "exact_candidate_binding", "cleanup_authorized_must_be_true"):
        if receipt.get(key) is not True:
            findings.append(f"receipt policy {key} must be true")
    true_assertions = _string_set(
        receipt.get("required_true_assertions"),
        "receipt required_true_assertions",
        findings,
    )
    false_assertions = _string_set(
        receipt.get("required_false_assertions"),
        "receipt required_false_assertions",
        findings,
    )
    if true_assertions != REQUIRED_TRUE_ASSERTIONS:
        findings.append("receipt true assertions do not match the mandatory final gates")
    if false_assertions != REQUIRED_FALSE_ASSERTIONS:
        findings.append("receipt false assertions do not preserve non-deployment scope")

    repository = _exact_keys(
        top.get("repository_cleanup"),
        {
            "enabled_after_receipt",
            "allowed_relative_directories",
            "allowed_relative_directory_prefixes",
            "forbidden_roots",
        },
        "repository cleanup policy",
        findings,
    )
    if repository.get("enabled_after_receipt") is not True:
        findings.append("repository cleanup may be enabled only after receipt validation")
    directories = _string_set(
        repository.get("allowed_relative_directories"),
        "repository allowed_relative_directories",
        findings,
    )
    if directories != REQUIRED_REPOSITORY_DIRECTORIES:
        findings.append("repository cleanup allowlist changed from the reviewed set")
    for index, value in enumerate(repository.get("allowed_relative_directories") or []):
        if not isinstance(value, str) or not _safe_relative_directory(value):
            findings.append(f"repository cleanup directory at index {index} is unsafe")
    prefixes = _string_set(
        repository.get("allowed_relative_directory_prefixes"),
        "repository allowed_relative_directory_prefixes",
        findings,
    )
    if prefixes != {".venv-"}:
        findings.append("repository cleanup prefix allowlist must contain only .venv-")
    for index, value in enumerate(repository.get("allowed_relative_directory_prefixes") or []):
        if not isinstance(value, str) or not _safe_name_prefix(value):
            findings.append(f"repository cleanup prefix at index {index} is unsafe")
    forbidden = _string_set(repository.get("forbidden_roots"), "repository forbidden_roots", findings)
    if forbidden != REQUIRED_FORBIDDEN_ROOTS:
        findings.append("repository protected roots changed from the reviewed set")
    if directories.intersection(forbidden):
        findings.append("repository cleanup allowlist overlaps protected roots")

    backup = _exact_keys(
        top.get("backup_cleanup"),
        {
            "enabled_after_receipt",
            "explicit_backup_root_required",
            "allowed_directory_prefixes",
            "minimum_verified_backups_to_keep",
            "keep_newest_verified_backup",
            "minimum_cooling_off_days",
            "required_verification_files",
            "delete_unverified_backups_automatically",
        },
        "backup cleanup policy",
        findings,
    )
    for key in ("enabled_after_receipt", "explicit_backup_root_required", "keep_newest_verified_backup"):
        if backup.get(key) is not True:
            findings.append(f"backup cleanup {key} must be true")
    if backup.get("delete_unverified_backups_automatically") is not False:
        findings.append("unverified backups must never be deleted automatically")
    keep = backup.get("minimum_verified_backups_to_keep")
    if not isinstance(keep, int) or isinstance(keep, bool) or keep < 1:
        findings.append("at least one verified backup must be retained")
    cooling = backup.get("minimum_cooling_off_days")
    if not isinstance(cooling, int) or isinstance(cooling, bool) or cooling < 7:
        findings.append("backup cleanup requires a cooling-off period of at least seven days")
    backup_prefixes = _string_set(
        backup.get("allowed_directory_prefixes"),
        "backup allowed_directory_prefixes",
        findings,
    )
    if backup_prefixes != REQUIRED_BACKUP_PREFIXES:
        findings.append("backup cleanup prefixes changed from the reviewed set")
    for index, value in enumerate(backup.get("allowed_directory_prefixes") or []):
        if not isinstance(value, str) or not _safe_name_prefix(value):
            findings.append(f"backup prefix at index {index} is unsafe")
    verification_files = _string_set(
        backup.get("required_verification_files"),
        "backup required_verification_files",
        findings,
    )
    if verification_files != {"backup-manifest.json", "repository-before.bundle"}:
        findings.append("backup verification file set changed from the reviewed set")
    for index, value in enumerate(backup.get("required_verification_files") or []):
        if not isinstance(value, str) or not _safe_name_prefix(value):
            findings.append(f"backup verification file at index {index} is unsafe")

    git_cleanup = _exact_keys(
        top.get("git_cleanup"),
        {
            "enabled_after_receipt",
            "delete_only_explicit_inventory",
            "protected_branches",
            "protected_prefixes",
            "github_managed_pull_refs_are_read_only",
        },
        "Git cleanup policy",
        findings,
    )
    for key in (
        "enabled_after_receipt",
        "delete_only_explicit_inventory",
        "github_managed_pull_refs_are_read_only",
    ):
        if git_cleanup.get(key) is not True:
            findings.append(f"Git cleanup {key} must be true")
    protected_branches = _string_set(
        git_cleanup.get("protected_branches"),
        "Git protected_branches",
        findings,
    )
    if protected_branches != {"main", "integration/final-release-candidate-v3"}:
        findings.append("Git protected branches changed from the reviewed set")
    protected_prefixes = _string_set(
        git_cleanup.get("protected_prefixes"),
        "Git protected_prefixes",
        findings,
    )
    if protected_prefixes != {"release/"}:
        findings.append("Git protected prefixes changed from the reviewed set")

    evidence = _string_set(top.get("preserve_final_evidence"), "preserve_final_evidence", findings)
    if evidence != REQUIRED_EVIDENCE:
        findings.append("final release evidence retention set is incomplete")
    return findings


def _valid_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def audit_receipt(
    receipt: dict[str, Any],
    policy: dict[str, Any],
    *,
    expected_candidate: str | None = None,
) -> list[str]:
    findings: list[str] = []
    value = _exact_keys(receipt, RECEIPT_FIELDS, "final cleanup receipt", findings)
    if value.get("schema_version") != 1:
        findings.append("final cleanup receipt schema_version must be 1")
    candidate = value.get("candidate_commit")
    tree = value.get("candidate_tree")
    version = value.get("candidate_version")
    if not isinstance(candidate, str) or not FULL_SHA_RE.fullmatch(candidate):
        findings.append("final cleanup receipt requires a full candidate commit SHA")
    if not isinstance(tree, str) or not FULL_SHA_RE.fullmatch(tree):
        findings.append("final cleanup receipt requires a full candidate tree SHA")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        findings.append("final cleanup receipt requires a semantic candidate version")
    if not _valid_utc_timestamp(value.get("completed_utc")):
        findings.append("final cleanup receipt requires an explicit UTC completion timestamp")
    if expected_candidate and candidate != expected_candidate:
        findings.append("final cleanup receipt is not bound to the expected candidate")
    if value.get("cleanup_authorized") is not True:
        findings.append("final cleanup receipt must explicitly authorize cleanup")

    receipt_policy = policy.get("receipt") if isinstance(policy.get("receipt"), dict) else {}
    for key in receipt_policy.get("required_true_assertions") or []:
        if value.get(key) is not True:
            findings.append(f"final cleanup receipt assertion {key} must be true")
    for key in receipt_policy.get("required_false_assertions") or []:
        if value.get(key) is not False:
            findings.append(f"final cleanup receipt assertion {key} must be false")
    digest = value.get("final_package_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        findings.append("final cleanup receipt requires a SHA-256 final package digest")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--expected-candidate")
    parser.add_argument(
        "--require-unlocked",
        action="store_true",
        help="Require a valid exact final receipt; validation remains read-only.",
    )
    args = parser.parse_args()
    try:
        policy = load_json_object(args.policy)
        findings = audit_policy(policy)
        receipt: dict[str, Any] | None = None
        if args.receipt is not None:
            receipt = load_json_object(args.receipt)
            findings.extend(
                audit_receipt(
                    receipt,
                    policy,
                    expected_candidate=args.expected_candidate,
                )
            )
        if args.require_unlocked and receipt is None:
            findings.append("a final receipt is required to unlock cleanup")
    except (FileNotFoundError, FinalCleanupPolicyError, OSError):
        print("FINAL CLEANUP GATE FAILED\n- cleanup policy or receipt could not be loaded")
        return 1

    if findings:
        print("FINAL CLEANUP GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    if args.require_unlocked:
        print("FINAL CLEANUP GATE PASSED: exact final receipt authorizes a separate cleanup transaction")
    else:
        print("FINAL CLEANUP GATE PASSED: cleanup remains locked and no deletion was performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
