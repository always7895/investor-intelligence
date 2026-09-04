#!/usr/bin/env python3
"""Independently verify an immutable Investor Intelligence v2.1.3 R75 ZIP."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


class R75ArtifactError(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> str:
    if not name or "\\" in name or "\x00" in name:
        raise R75ArtifactError("ZIP contains an empty, NUL, or backslash path")
    path = PurePosixPath(name)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", name):
        raise R75ArtifactError("ZIP contains an absolute path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise R75ArtifactError("ZIP contains an unsafe path segment")
    return path.as_posix().rstrip("/")


def load_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R75ArtifactError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise R75ArtifactError(f"{label} must be an object")
    return value


def parse_outer_checksum(path: Path, archive_name: str) -> str:
    parts = path.read_text(encoding="ascii").strip().split()
    if len(parts) != 2 or parts[1].lstrip("*") != archive_name or not HEX64.fullmatch(parts[0].lower()):
        raise R75ArtifactError("external SHA256 file is malformed or names another archive")
    return parts[0].lower()


def parse_sums(data: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise R75ArtifactError("SHA256SUMS.txt is not ASCII") from exc
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise R75ArtifactError("SHA256SUMS.txt contains a malformed line")
        name = safe_name(match.group(2))
        key = name.casefold()
        if key in result:
            raise R75ArtifactError("SHA256SUMS.txt contains duplicate paths")
        result[key] = match.group(1)
    return result


def verify_receipt(path: Path, *, source_commit: str, run_id: str, label: str) -> dict[str, Any]:
    value = load_json_bytes(path.read_bytes(), label)
    if value.get("status") != "PASS":
        raise R75ArtifactError(f"{label} is not PASS")
    if str(value.get("source_commit") or value.get("commit") or "").lower() != source_commit:
        raise R75ArtifactError(f"{label} source commit mismatch")
    if str(value.get("workflow_run_id")) != run_id:
        raise R75ArtifactError(f"{label} workflow run mismatch")
    mutation = value.get("production_mutation_by_ci", value.get("production_mutation"))
    if mutation is not False or value.get("external_mutation", False) is not False:
        raise R75ArtifactError(f"{label} does not attest no mutation")
    return value


def verify_r75_artifact(
    archive: Path,
    checksum: Path,
    *,
    source_commit: str,
    run_id: str,
    windows_receipt: Path | None = None,
    worker_receipt: Path | None = None,
    delivery_receipt: Path | None = None,
) -> dict[str, Any]:
    source_commit = source_commit.lower()
    if not HEX40.fullmatch(source_commit) or not run_id.isdigit():
        raise R75ArtifactError("expected source commit or workflow run ID is invalid")
    expected_name = f"Investor-Intelligence-v2.1.3-R75-{source_commit}-{run_id}.zip"
    if archive.name != expected_name or "R70" in archive.name.upper():
        raise R75ArtifactError("archive does not use the immutable R75 identity")
    expected_outer = parse_outer_checksum(checksum, archive.name)
    actual_outer = digest(archive.read_bytes())
    if actual_outer != expected_outer:
        raise R75ArtifactError("archive SHA256 mismatch")

    with zipfile.ZipFile(archive, "r") as handle:
        if handle.testzip() is not None:
            raise R75ArtifactError("ZIP CRC verification failed")
        files: dict[str, tuple[str, bytes]] = {}
        seen: set[str] = set()
        for info in handle.infolist():
            name = safe_name(info.filename)
            key = name.casefold()
            if key in seen:
                raise R75ArtifactError("ZIP contains duplicate or case-colliding paths")
            seen.add(key)
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(unix_mode):
                raise R75ArtifactError("ZIP contains a symbolic link")
            if info.is_dir():
                continue
            files[key] = (name, handle.read(info))

    required = {
        "manifest.json",
        "sha256sums.txt",
        "version-refs.json",
        "sbom.spdx.json",
        "investorintelligence.exe",
        "config/v213-r75-publication-mode-v1.json",
        "scripts/v213_r75_activation_preflight.py",
        "cloud/src/v213/publication-mode.ts",
        "cloud/src/v213/activation-v2.ts",
    }
    if not required.issubset(files):
        raise R75ArtifactError("archive is missing required R75 release files")
    if files["investorintelligence.exe"][1][:2] != b"MZ":
        raise R75ArtifactError("packaged launcher lacks a PE MZ header")
    internal_prefixes = (".github/", "delivery/", "skills/", "state/", "tests/")
    if any(name.startswith(internal_prefixes) or name == "implementation_status.md" for name in files):
        raise R75ArtifactError("public archive contains internal CI, test, status, or prior-delivery content")
    sbom = load_json_bytes(files["sbom.spdx.json"][1], "SBOM.spdx.json")
    packages = sbom.get("packages")
    if (
        sbom.get("spdxVersion") != "SPDX-2.3"
        or sbom.get("dataLicense") != "CC0-1.0"
        or sbom.get("SPDXID") != "SPDXRef-DOCUMENT"
        or f"/R75/{source_commit}/{run_id}" not in str(sbom.get("documentNamespace"))
        or not isinstance(packages, list)
        or len(packages) != 1
        or packages[0].get("versionInfo") != "2.1.3-R75"
    ):
        raise R75ArtifactError("SPDX SBOM identity is invalid")

    manifest = load_json_bytes(files["manifest.json"][1], "MANIFEST.json")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("release") != "R75"
        or manifest.get("source_commit") != source_commit
        or str(manifest.get("workflow_run_id")) != run_id
        or manifest.get("production_mutation_by_ci") is not False
    ):
        raise R75ArtifactError("MANIFEST release identity or no-mutation attestation is invalid")
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise R75ArtifactError("MANIFEST files must be an array")
    manifest_files: dict[str, tuple[int, str]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise R75ArtifactError("MANIFEST contains an invalid file row")
        name = safe_name(str(row["path"])); key = name.casefold()
        if key in manifest_files or not isinstance(row["bytes"], int) or not HEX64.fullmatch(str(row["sha256"])):
            raise R75ArtifactError("MANIFEST contains duplicate or malformed metadata")
        manifest_files[key] = (row["bytes"], str(row["sha256"]))
    expected_manifest_paths = set(files) - {"manifest.json", "sha256sums.txt"}
    if set(manifest_files) != expected_manifest_paths:
        raise R75ArtifactError("MANIFEST file set differs from ZIP payload")
    for key, (size, sha) in manifest_files.items():
        data = files[key][1]
        if len(data) != size or digest(data) != sha:
            raise R75ArtifactError("MANIFEST size or digest mismatch")

    sums = parse_sums(files["sha256sums.txt"][1])
    expected_sum_paths = set(files) - {"sha256sums.txt"}
    if set(sums) != expected_sum_paths:
        raise R75ArtifactError("SHA256SUMS file set differs from ZIP")
    for key, sha in sums.items():
        if digest(files[key][1]) != sha:
            raise R75ArtifactError("SHA256SUMS digest mismatch")

    version = load_json_bytes(files["version-refs.json"][1], "VERSION-REFS.json")
    contract_sha = digest(files["config/v213-r75-publication-mode-v1.json"][1])
    if (
        version.get("release") != "R75"
        or version.get("package_version") != "2.1.3"
        or version.get("source_commit") != source_commit
        or str(version.get("workflow_run_id")) != run_id
        or version.get("publication_contract_sha256") != contract_sha
        or version.get("production_mutation_by_ci") is not False
        or version.get("known_p0_count") != 0
        or version.get("public_package_excludes_internal_evidence") is not True
    ):
        raise R75ArtifactError("VERSION-REFS release marker, contract hash, or gate state is invalid")

    receipts: dict[str, Any] = {}
    for label, path in (
        ("windows_receipt", windows_receipt),
        ("worker_receipt", worker_receipt),
        ("delivery_receipt", delivery_receipt),
    ):
        if path is not None:
            receipts[label] = verify_receipt(path, source_commit=source_commit, run_id=run_id, label=label)
    return {
        "status": "PASS",
        "archive": archive.name,
        "archive_sha256": actual_outer,
        "source_commit": source_commit,
        "workflow_run_id": run_id,
        "zip_crc": "PASS",
        "path_safety": "PASS",
        "duplicates": "PASS",
        "symlinks": "PASS",
        "manifest": "PASS",
        "sha256sums": "PASS",
        "pe_marker": "PASS",
        "spdx_sbom": "PASS",
        "public_internal_separation": "PASS",
        "release_marker": "R75",
        "publication_contract_sha256": contract_sha,
        "receipt_count": len(receipts),
        "production_mutation_by_ci": False,
        "known_p0_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--checksum", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--windows-receipt", type=Path)
    parser.add_argument("--worker-receipt", type=Path)
    parser.add_argument("--delivery-receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify_r75_artifact(
            args.archive, args.checksum,
            source_commit=args.source_commit,
            run_id=args.workflow_run_id,
            windows_receipt=args.windows_receipt,
            worker_receipt=args.worker_receipt,
            delivery_receipt=args.delivery_receipt,
        )
    except (OSError, zipfile.BadZipFile, R75ArtifactError) as exc:
        print(f"V213_R75_ARTIFACT_VERIFICATION = FAIL; reason={type(exc).__name__}")
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"V213_R75_ARTIFACT_VERIFICATION = PASS; sha256={result['archive_sha256']}; production_mutation_by_ci=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
