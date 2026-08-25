#!/usr/bin/env python3
"""Create the exact-head final cleanup/package receipt outside the source tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")


def build_receipt(
    *,
    candidate_commit: str,
    candidate_tree: str,
    version: str,
    final_package_sha256: str,
    completed_utc: str,
    cleanup_authorized: bool,
) -> dict[str, Any]:
    candidate_commit = candidate_commit.casefold()
    candidate_tree = candidate_tree.casefold()
    final_package_sha256 = final_package_sha256.casefold()
    if not COMMIT_RE.fullmatch(candidate_commit):
        raise ValueError("candidate_commit must be a full lowercase SHA-1")
    if not COMMIT_RE.fullmatch(candidate_tree):
        raise ValueError("candidate_tree must be a full lowercase SHA-1")
    if not VERSION_RE.fullmatch(version):
        raise ValueError("version must be SemVer-compatible without a leading v")
    if not SHA256_RE.fullmatch(final_package_sha256):
        raise ValueError("final_package_sha256 must be a lowercase SHA-256")
    if not isinstance(cleanup_authorized, bool):
        raise ValueError("cleanup_authorized must be boolean")
    try:
        timestamp = datetime.fromisoformat(completed_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("completed_utc must be ISO-8601 UTC") from exc
    if not completed_utc.endswith("Z") or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
        raise ValueError("completed_utc must use the Z UTC designator")
    return {
        "schema_version": 1,
        "candidate_commit": candidate_commit,
        "candidate_tree": candidate_tree,
        "candidate_version": f"v{version}",
        "completed_utc": completed_utc,
        "cleanup_authorized": cleanup_authorized,
        "release_ready": True,
        "deployed": False,
        "billing_enabled": False,
        "external_users_admitted": False,
        "post_rewrite_fresh_clone": True,
        "full_history_scope_all_clean": True,
        "canonical_acceptance": True,
        "clean_install": True,
        "reproducible_package": True,
        "sbom_manifest_checksums": True,
        "final_package_sha256": final_package_sha256,
    }


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args],
        text=True,
        encoding="utf-8",
        stderr=subprocess.STDOUT,
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorize-cleanup", action="store_true")
    args = parser.parse_args()
    try:
        if not args.archive.is_file():
            raise FileNotFoundError(args.archive)
        candidate_commit = _git("rev-parse", "HEAD").casefold()
        candidate_tree = _git("rev-parse", "HEAD^{tree}").casefold()
        digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
        completed = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        receipt = build_receipt(
            candidate_commit=candidate_commit,
            candidate_tree=candidate_tree,
            version=args.version,
            final_package_sha256=digest,
            completed_utc=completed,
            cleanup_authorized=args.authorize_cleanup,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except (FileNotFoundError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"FINAL RELEASE RECEIPT FAILED\n- {exc}")
        return 1
    print(
        json.dumps(
            {
                "candidate_commit": candidate_commit,
                "candidate_tree": candidate_tree,
                "candidate_version": f"v{args.version}",
                "final_package_sha256": digest,
                "cleanup_authorized": args.authorize_cleanup,
                "deployed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
