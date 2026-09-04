#!/usr/bin/env python3
"""Verify an immutable R75 Named Tunnel deployment-hotfix artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
BASE = "536644d22ef3534be1c4b8a9e1ff969df4d580fa"


class VerificationError(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(value: str) -> str:
    if not value or "\\" in value or "\0" in value:
        raise VerificationError("unsafe ZIP path")
    path = PurePosixPath(value)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", value) or any(p in {"", ".", ".."} for p in path.parts):
        raise VerificationError("unsafe ZIP path")
    return path.as_posix().rstrip("/")


def load_json(data: bytes, label: str) -> dict:
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"invalid {label}")
    return value


def verify_receipt(path: Path, commit: str, run_id: str) -> dict:
    value = load_json(path.read_bytes(), path.name)
    if value.get("status") != "PASS" or str(value.get("source_commit", "")).lower() != commit or str(value.get("workflow_run_id")) != run_id:
        raise VerificationError(f"receipt identity mismatch: {path.name}")
    if value.get("production_mutation_by_ci") is not False or value.get("external_mutation", False) is not False:
        raise VerificationError(f"receipt mutation attestation failed: {path.name}")
    return value


def verify(archive: Path, checksum: Path, commit: str, run_id: str, receipts: list[Path]) -> dict:
    commit = commit.lower()
    if not HEX40.fullmatch(commit) or not run_id.isdigit():
        raise VerificationError("invalid immutable identity")
    stem = f"Investor-Intelligence-v2.1.3-R75-Named-Tunnel-Hotfix-{commit}-{run_id}"
    if archive.name != stem + ".zip":
        raise VerificationError("archive name mismatch")
    parts = checksum.read_text(encoding="ascii").strip().split()
    if len(parts) != 2 or parts[1].lstrip("*") != archive.name or not HEX64.fullmatch(parts[0].lower()):
        raise VerificationError("external checksum malformed")
    actual = sha(archive.read_bytes())
    if actual != parts[0].lower():
        raise VerificationError("archive checksum mismatch")

    with zipfile.ZipFile(archive) as handle:
        if handle.testzip() is not None:
            raise VerificationError("ZIP CRC failure")
        files: dict[str, tuple[str, bytes]] = {}
        seen: set[str] = set()
        for info in handle.infolist():
            name = safe_name(info.filename); key = name.casefold()
            if key in seen:
                raise VerificationError("duplicate/case-colliding ZIP path")
            seen.add(key)
            if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
                raise VerificationError("ZIP symlink")
            if not info.is_dir():
                files[key] = (name, handle.read(info))

    required = {
        "investorintelligence.exe", "hotfix-refs.json", "manifest.json", "sha256sums.txt",
        "scripts/setup_v213_named_tunnel.ps1", "scripts/v213_named_tunnel_helpers.ps1",
        "scripts/run_v213_local_llm_bridge_core.ps1", "run-v213-local.ps1",
        "config/v213-r75-publication-mode-v1.json", "scripts/v213_r75_activation_preflight.py",
        "cloud/src/v213/publication-mode.ts", "cloud/src/v213/activation-v2.ts",
    }
    if not required.issubset(files):
        raise VerificationError("required payload missing")
    if files["investorintelligence.exe"][1][:2] != b"MZ":
        raise VerificationError("launcher is not PE")
    if any(name.startswith((".github/", "delivery/", "state/", "tests/", "skills/")) for name in files):
        raise VerificationError("internal content leaked")

    refs = load_json(files["hotfix-refs.json"][1], "HOTFIX-REFS.json")
    if (refs.get("artifact_kind") != "R75_NAMED_TUNNEL_DEPLOYMENT_HOTFIX" or
            refs.get("base_release_commit") != BASE or refs.get("source_commit") != commit or
            str(refs.get("workflow_run_id")) != run_id or refs.get("production_mutation_by_ci") is not False or
            refs.get("protected_release_semantics_unchanged") is not True or refs.get("consecutive_public_health_required") != 3 or
            refs.get("health_schema_version") != 2 or refs.get("normal_production_tunnel_mode") != "named"):
        raise VerificationError("hotfix refs mismatch")
    contract_sha = sha(files["config/v213-r75-publication-mode-v1.json"][1])
    if refs.get("publication_contract_sha256") != contract_sha:
        raise VerificationError("publication contract binding mismatch")

    manifest = load_json(files["manifest.json"][1], "MANIFEST.json")
    if manifest.get("source_commit") != commit or str(manifest.get("workflow_run_id")) != run_id or manifest.get("production_mutation_by_ci") is not False:
        raise VerificationError("manifest identity mismatch")
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise VerificationError("manifest rows invalid")
    indexed = {str(row.get("path", "")).casefold(): row for row in rows if isinstance(row, dict)}
    expected = set(files) - {"manifest.json", "sha256sums.txt"}
    if set(indexed) != expected or len(indexed) != len(rows):
        raise VerificationError("manifest file set mismatch")
    for key, row in indexed.items():
        data = files[key][1]
        if row.get("bytes") != len(data) or row.get("sha256") != sha(data):
            raise VerificationError("manifest digest mismatch")

    sums: dict[str, str] = {}
    for line in files["sha256sums.txt"][1].decode("ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise VerificationError("SHA256SUMS malformed")
        key = safe_name(match.group(2)).casefold()
        if key in sums:
            raise VerificationError("SHA256SUMS duplicate")
        sums[key] = match.group(1)
    if set(sums) != set(files) - {"sha256sums.txt"}:
        raise VerificationError("SHA256SUMS file set mismatch")
    if any(sha(files[key][1]) != value for key, value in sums.items()):
        raise VerificationError("SHA256SUMS digest mismatch")

    verified = [verify_receipt(path, commit, run_id) for path in receipts]
    return {
        "status": "PASS", "artifact_kind": "R75_NAMED_TUNNEL_DEPLOYMENT_HOTFIX",
        "archive": archive.name, "archive_sha256": actual, "source_commit": commit,
        "workflow_run_id": run_id, "base_release_commit": BASE, "zip_crc": "PASS",
        "path_safety": "PASS", "duplicates": "PASS", "symlinks": "PASS",
        "manifest": "PASS", "sha256sums": "PASS", "pe_marker": "PASS",
        "publication_contract_sha256": contract_sha, "receipt_count": len(verified),
        "production_mutation_by_ci": False, "protected_release_semantics_unchanged": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--checksum", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--receipt", action="append", default=[], type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.archive, args.checksum, args.source_commit, args.workflow_run_id, args.receipt)
    except (OSError, UnicodeError, zipfile.BadZipFile, VerificationError) as exc:
        print(f"V213_R75_NAMED_TUNNEL_ARTIFACT_VERIFICATION = FAIL; reason={type(exc).__name__}")
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print("V213_R75_NAMED_TUNNEL_ARTIFACT_VERIFICATION = PASS; production_mutation_by_ci=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
