#!/usr/bin/env python3
"""Verify deterministic release ZIP, checksum, manifest and SPDX SBOM.

Verification is fail-closed: duplicate/extra/unsafe ZIP entries, checksum drift,
manifest drift, SBOM drift, symlinks, private paths and extraction traversal all
reject the package before any file is installed or executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from release_package import (
    DEFAULT_POLICY,
    ReleasePackageError,
    _load_object,
    _path_forbidden,
)

CHECKSUM_RE = re.compile(r"^([0-9a-f]{64})  ([^\r\n]+)\n?$")
GENERATED_ENTRIES = {
    "release-manifest.json",
    "release-metadata.json",
    "sbom.spdx.json",
}


class ReleaseVerificationError(ValueError):
    """Raised when a release package fails an integrity or privacy check."""


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _safe_zip_name(name: str) -> None:
    if not name or name.startswith("/") or "\\" in name:
        raise ReleaseVerificationError(f"Unsafe ZIP entry path: {name!r}")
    normalized = PurePosixPath(name).as_posix()
    if normalized != name or any(part in {"", ".", ".."} for part in PurePosixPath(name).parts):
        raise ReleaseVerificationError(f"Non-normalized ZIP entry path: {name!r}")


def _load_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"{label} must be a JSON object")
    return value


def _checksum_record(path: Path) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReleaseVerificationError("Checksum file must be ASCII") from exc
    match = CHECKSUM_RE.fullmatch(text)
    if not match:
        raise ReleaseVerificationError("Checksum file must contain one lowercase SHA-256 record")
    return match.group(1), match.group(2)


def _manifest_file_map(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ReleaseVerificationError("Manifest files must be a non-empty array")
    result: dict[str, dict[str, Any]] = {}
    allowed = {"path", "bytes", "mode", "sha256"}
    for index, value in enumerate(files):
        if not isinstance(value, dict):
            raise ReleaseVerificationError(f"Manifest files[{index}] must be an object")
        unknown = sorted(set(value).difference(allowed))
        missing = sorted(allowed.difference(value))
        if unknown or missing:
            raise ReleaseVerificationError(
                f"Manifest files[{index}] shape mismatch; unknown={unknown}, missing={missing}"
            )
        path = str(value.get("path") or "")
        _safe_zip_name(path)
        if path in GENERATED_ENTRIES:
            raise ReleaseVerificationError(f"Generated metadata cannot be a payload file: {path}")
        if path in result:
            raise ReleaseVerificationError(f"Duplicate manifest path: {path}")
        size = value.get("bytes")
        digest = str(value.get("sha256") or "")
        mode = str(value.get("mode") or "")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ReleaseVerificationError(f"Manifest size is invalid: {path}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ReleaseVerificationError(f"Manifest SHA-256 is invalid: {path}")
        if mode not in {"0644", "0755"}:
            raise ReleaseVerificationError(f"Manifest mode is invalid: {path}")
        result[path] = dict(value)
    return result


def _sbom_file_map(sbom: Mapping[str, Any]) -> dict[str, str]:
    if sbom.get("spdxVersion") != "SPDX-2.3" or sbom.get("SPDXID") != "SPDXRef-DOCUMENT":
        raise ReleaseVerificationError("SBOM is not the required SPDX 2.3 document")
    files = sbom.get("files")
    if not isinstance(files, list):
        raise ReleaseVerificationError("SBOM files must be an array")
    result: dict[str, str] = {}
    for index, value in enumerate(files):
        if not isinstance(value, dict):
            raise ReleaseVerificationError(f"SBOM files[{index}] must be an object")
        path = str(value.get("fileName") or "")
        _safe_zip_name(path)
        checksums = value.get("checksums")
        if not isinstance(checksums, list):
            raise ReleaseVerificationError(f"SBOM file lacks checksums: {path}")
        sha256_values = [
            str(item.get("checksumValue") or "")
            for item in checksums
            if isinstance(item, dict) and item.get("algorithm") == "SHA256"
        ]
        if len(sha256_values) != 1 or not re.fullmatch(r"[0-9a-f]{64}", sha256_values[0]):
            raise ReleaseVerificationError(f"SBOM file lacks one valid SHA-256: {path}")
        if path in result:
            raise ReleaseVerificationError(f"Duplicate SBOM file path: {path}")
        result[path] = sha256_values[0]
    return result


def _extract_verified(
    archive: zipfile.ZipFile,
    entries: Mapping[str, zipfile.ZipInfo],
    target: Path,
) -> None:
    target = target.resolve()
    if target.exists():
        if any(target.iterdir()):
            raise ReleaseVerificationError("Extraction target must be empty")
    else:
        target.mkdir(parents=True)
    for name in sorted(entries):
        info = entries[name]
        destination = (target / Path(*PurePosixPath(name).parts)).resolve()
        try:
            destination.relative_to(target)
        except ValueError as exc:
            raise ReleaseVerificationError(f"ZIP entry escapes extraction root: {name}") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ReleaseVerificationError(f"Extraction would overwrite a path: {name}")
        data = archive.read(info)
        destination.write_bytes(data)
        mode = (info.external_attr >> 16) & 0o777
        if mode:
            os.chmod(destination, mode)


def verify_release_package(
    *,
    archive_path: Path,
    checksum_path: Path,
    manifest_path: Path,
    sbom_path: Path,
    policy_path: Path = DEFAULT_POLICY,
    extract_to: Path | None = None,
) -> dict[str, Any]:
    policy = _load_object(policy_path)
    expected_digest, expected_name = _checksum_record(checksum_path)
    if expected_name != archive_path.name:
        raise ReleaseVerificationError("Checksum filename does not match the archive")
    archive_bytes = archive_path.read_bytes()
    actual_digest = hashlib.sha256(archive_bytes).hexdigest()
    if actual_digest != expected_digest:
        raise ReleaseVerificationError("Archive SHA-256 does not match the checksum file")
    maximum_package = int(policy.get("maximum_package_bytes") or 50_000_000)
    if len(archive_bytes) > maximum_package:
        raise ReleaseVerificationError("Archive exceeds the package size policy")

    external_manifest_bytes = manifest_path.read_bytes()
    external_sbom_bytes = sbom_path.read_bytes()
    manifest = _load_json_bytes(external_manifest_bytes, "External manifest")
    sbom = _load_json_bytes(external_sbom_bytes, "External SBOM")
    manifest_files = _manifest_file_map(manifest)
    sbom_files = _sbom_file_map(sbom)
    if set(sbom_files) != set(manifest_files):
        raise ReleaseVerificationError("SBOM and manifest payload paths differ")
    for path, record in manifest_files.items():
        if sbom_files[path] != record["sha256"]:
            raise ReleaseVerificationError(f"SBOM checksum differs from manifest: {path}")
        reason = _path_forbidden(path, policy)
        if reason:
            raise ReleaseVerificationError(f"Forbidden payload path {path}: {reason}")

    required_paths = {str(item) for item in policy.get("required_paths", [])}
    missing_required = sorted(required_paths.difference(manifest_files))
    if missing_required:
        raise ReleaseVerificationError(
            "Manifest omits required package paths: " + ", ".join(missing_required)
        )

    try:
        archive = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleaseVerificationError("Release archive is not a valid ZIP") from exc
    with archive:
        entries: dict[str, zipfile.ZipInfo] = {}
        total_uncompressed = 0
        for info in archive.infolist():
            name = info.filename
            _safe_zip_name(name)
            if name in entries:
                raise ReleaseVerificationError(f"Duplicate ZIP entry: {name}")
            if info.is_dir():
                raise ReleaseVerificationError(f"Directory entries are forbidden: {name}")
            file_type = (info.external_attr >> 16) & 0o170000
            if file_type == 0o120000:
                raise ReleaseVerificationError(f"Symlink ZIP entry is forbidden: {name}")
            if info.flag_bits & 0x1:
                raise ReleaseVerificationError(f"Encrypted ZIP entry is forbidden: {name}")
            if info.compress_type not in {zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED}:
                raise ReleaseVerificationError(f"Unsupported compression method: {name}")
            total_uncompressed += info.file_size
            entries[name] = info
        expected_entries = set(manifest_files) | GENERATED_ENTRIES
        if set(entries) != expected_entries:
            extra = sorted(set(entries).difference(expected_entries))
            missing = sorted(expected_entries.difference(entries))
            raise ReleaseVerificationError(
                f"ZIP entry set differs from manifest; extra={extra}, missing={missing}"
            )
        if total_uncompressed > maximum_package:
            raise ReleaseVerificationError("Uncompressed package exceeds the package size policy")

        internal_manifest_bytes = archive.read("release-manifest.json")
        internal_sbom_bytes = archive.read("sbom.spdx.json")
        if internal_manifest_bytes != external_manifest_bytes:
            raise ReleaseVerificationError("Internal and external manifests differ")
        if internal_sbom_bytes != external_sbom_bytes:
            raise ReleaseVerificationError("Internal and external SBOMs differ")
        metadata_bytes = archive.read("release-metadata.json")
        metadata = _load_json_bytes(metadata_bytes, "Release metadata")
        if metadata.get("manifest_sha256") != hashlib.sha256(internal_manifest_bytes).hexdigest():
            raise ReleaseVerificationError("Release metadata manifest checksum is invalid")
        if metadata.get("sbom_sha256") != hashlib.sha256(internal_sbom_bytes).hexdigest():
            raise ReleaseVerificationError("Release metadata SBOM checksum is invalid")
        for key in ("package_name", "version", "source_commit", "source_date_epoch", "build_mode"):
            if metadata.get(key) != manifest.get(key):
                raise ReleaseVerificationError(f"Release metadata differs from manifest: {key}")
        if metadata.get("secrets_included") is not False or metadata.get("user_data_included") is not False:
            raise ReleaseVerificationError("Release metadata must attest no secrets or user data")

        maximum_file = int(policy.get("maximum_file_bytes") or 10_000_000)
        for path, record in manifest_files.items():
            info = entries[path]
            if info.file_size != record["bytes"] or info.file_size > maximum_file:
                raise ReleaseVerificationError(f"ZIP size differs from manifest: {path}")
            data = archive.read(info)
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ReleaseVerificationError(f"ZIP checksum differs from manifest: {path}")
            expected_mode = 0o755 if record["mode"] == "0755" else 0o644
            actual_mode = (info.external_attr >> 16) & 0o777
            if actual_mode != expected_mode:
                raise ReleaseVerificationError(f"ZIP mode differs from manifest: {path}")

        if extract_to is not None:
            try:
                _extract_verified(archive, entries, extract_to)
            except Exception:
                if extract_to.exists():
                    shutil.rmtree(extract_to, ignore_errors=True)
                raise

    packages = sbom.get("packages")
    if not isinstance(packages, list) or not any(
        isinstance(value, dict) and value.get("SPDXID") == "SPDXRef-Package-Root"
        for value in packages
    ):
        raise ReleaseVerificationError("SBOM lacks the root package")
    return {
        "valid": True,
        "archive_sha256": actual_digest,
        "package_name": manifest.get("package_name"),
        "version": manifest.get("version"),
        "source_commit": manifest.get("source_commit"),
        "build_mode": manifest.get("build_mode"),
        "payload_file_count": len(manifest_files),
        "sbom_package_count": len(packages),
        "extracted": extract_to is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--extract-to", type=Path)
    args = parser.parse_args()
    try:
        summary = verify_release_package(
            archive_path=args.archive,
            checksum_path=args.checksum,
            manifest_path=args.manifest,
            sbom_path=args.sbom,
            policy_path=args.policy,
            extract_to=args.extract_to,
        )
    except (FileNotFoundError, OSError, ReleasePackageError, ReleaseVerificationError) as exc:
        print(f"RELEASE PACKAGE VERIFICATION FAILED\n- {exc}")
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
