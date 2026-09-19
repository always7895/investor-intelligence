#!/usr/bin/env python3
"""Create an unverified legacy release-status template.

The ephemeral document preserves the legacy schema, not release authority.
No evidence is supplied to build_status: ready flags remain False and gates
UNVERIFIED. Non-synthetic packaging must reject this template; qualification
belongs to the authoritative source-bound release pipeline.
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
        "release_ready": False,
        "package_release_ready": False,
        "public_repository_publication_ready": False,
        "distribution_scope": "private_direct_delivery",
        "deployed": False,
        "billing_enabled": False,
        "external_users_admitted": False,
        "candidate_commit": candidate_commit,
        "candidate_version": version,
        "gates": {name: "UNVERIFIED" for name in GATE_NAMES},
        "hard_blockers": ["SOURCE_BOUND_RELEASE_EVIDENCE_REQUIRED"],
        "public_repository_blockers": [],
        "local_action_required": True,
        "secrets_required_now": False,
        "notes": (
            "Fail-closed exact-head status: build_status receives no source-bound release "
            "evidence, so no ready flag is asserted and every gate remains UNVERIFIED. "
            "It does not authorize deployment, LINE activation, IBKR connectivity, billing, "
            "external-user admission, or publication of the development repository."
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
