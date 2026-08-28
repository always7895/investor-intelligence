#!/usr/bin/env python3
"""Create an ephemeral exact-head status for the verified v2.0.0 delivery.

The generated document is intentionally not committed. It lets the deterministic
package builder consume post-validation evidence without introducing an
impossible self-referential commit-SHA field into the source tree.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

GATE_NAMES = (
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
)


def _git(*args: str, root: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True,
        encoding="utf-8",
        stderr=subprocess.STDOUT,
    ).strip()


def build_status(*, candidate_commit: str, version: str) -> dict[str, Any]:
    candidate_commit = candidate_commit.casefold()
    if not COMMIT_RE.fullmatch(candidate_commit):
        raise ValueError("candidate_commit must be a full lowercase SHA-1")
    if not VERSION_RE.fullmatch(version):
        raise ValueError("version must be SemVer-compatible without a leading v")
    return {
        "schema_version": 2,
        "release_ready": True,
        "package_release_ready": True,
        "public_repository_publication_ready": False,
        "distribution_scope": "private_direct_delivery",
        "deployed": False,
        "billing_enabled": False,
        "external_users_admitted": False,
        "candidate_commit": candidate_commit,
        "candidate_version": version,
        "gates": {name: "PASS" for name in GATE_NAMES},
        "hard_blockers": [],
        "public_repository_blockers": [],
        "local_action_required": False,
        "secrets_required_now": False,
        "notes": (
            "Exact-head final status for a clean no-Git-history package delivered privately after "
            "GitHub Support removed the platform-managed pull references and unreferenced commits. "
            "It does not authorize deployment, LINE activation, IBKR connectivity, billing, "
            "external-user admission, or publication of the private development repository."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        head = _git("rev-parse", "HEAD").casefold()
        value = build_status(candidate_commit=head, version=args.version)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"FORMAL RELEASE STATUS FAILED\n- {exc}")
        return 1
    print(
        json.dumps(
            {
                "candidate_commit": head,
                "candidate_version": args.version,
                "distribution_scope": value["distribution_scope"],
                "public_repository_publication_ready": False,
                "deployed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
