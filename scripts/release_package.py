#!/usr/bin/env python3
"""Build a deterministic, privacy-minimized release validation package.

The command is safe by default: it creates only local files in an explicit
output directory, never deploys, never installs secrets and never enables LINE,
IBKR or paid services. ``--synthetic`` permits reproducibility testing while the
repository release status remains fail-closed. A non-synthetic build requires a
fully accepted release-candidate status bound to the exact source commit and
version.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "release-package-policy.json"
DEFAULT_RELEASE_STATUS = ROOT / "config" / "release-candidate-status.json"
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")


class ReleasePackageError(ValueError):
    """Raised when a package cannot be built without weakening a hard gate."""


@dataclass(frozen=True)
class IndexedFile:
    path: str
    mode: int
    data: bytes


@dataclass(frozen=True)
class PackageOutputs:
    archive: Path
    checksum: Path
    manifest: Path
    sbom: Path
    source_commit: str
    version: str
    file_count: int
    archive_sha256: str


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


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ReleasePackageError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleasePackageError(f"Expected a JSON object in {path}")
    return value


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *args],
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        output = getattr(exc, "output", "")
        raise ReleasePackageError(f"Git command failed: {' '.join(args)}; {output}") from exc


def source_identity(root: Path = ROOT) -> tuple[str, int]:
    commit = _git(root, "rev-parse", "HEAD").casefold()
    if not COMMIT_RE.fullmatch(commit):
        raise ReleasePackageError("Git HEAD is not a full SHA-1 commit identifier")
    try:
        epoch = int(_git(root, "show", "-s", "--format=%ct", commit))
    except ValueError as exc:
        raise ReleasePackageError("Git commit timestamp is invalid") from exc
    if epoch <= 0:
        raise ReleasePackageError("Git commit timestamp must be positive")
    return commit, epoch


def _indexed_paths(root: Path) -> list[tuple[str, int]]:
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-s", "-z"],
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleasePackageError("Unable to enumerate tracked files") from exc
    result: list[tuple[str, int]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            mode_text = metadata.split(b" ", 1)[0].decode("ascii")
            path = encoded_path.decode("utf-8")
            mode = int(mode_text, 8)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleasePackageError("Git index contains an unsupported entry") from exc
        if mode == 0o120000:
            raise ReleasePackageError(f"Tracked symlinks are forbidden in a release package: {path}")
        if mode not in {0o100644, 0o100755}:
            raise ReleasePackageError(f"Unsupported tracked file mode {mode_text}: {path}")
        result.append((path, mode))
    return result


def _path_forbidden(path: str, policy: Mapping[str, Any]) -> str | None:
    normalized = PurePosixPath(path).as_posix()
    if normalized != path or path.startswith("/") or "\\" in path:
        return "path is not normalized POSIX relative form"
    parts = PurePosixPath(path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return "path contains an unsafe segment"
    if path in set(str(item) for item in policy.get("forbidden_exact_paths", [])):
        return "path is explicitly forbidden"
    for prefix in policy.get("excluded_prefixes", []):
        if path.startswith(str(prefix)):
            return f"path is under excluded prefix {prefix}"
    forbidden_segments = {str(item).casefold() for item in policy.get("forbidden_path_segments", [])}
    if any(part.casefold() in forbidden_segments for part in parts):
        return "path contains a developer-cache or runner-state segment"
    suffixes = tuple(str(item).casefold() for item in policy.get("forbidden_suffixes", []))
    if suffixes and path.casefold().endswith(suffixes):
        return "path has a forbidden private/runtime suffix"
    return None


def collect_payload_files(
    root: Path,
    policy: Mapping[str, Any],
    *,
    indexed_paths: Sequence[tuple[str, int]] | None = None,
) -> list[IndexedFile]:
    maximum = int(policy.get("maximum_file_bytes") or 10_000_000)
    selected: list[IndexedFile] = []
    for path, mode in indexed_paths if indexed_paths is not None else _indexed_paths(root):
        reason = _path_forbidden(path, policy)
        if reason:
            # Explicitly excluded development/private paths are omitted. Other
            # unsafe forms are rejected below by required-path and verifier gates.
            continue
        file_path = root / Path(*PurePosixPath(path).parts)
        if not file_path.is_file() or file_path.is_symlink():
            raise ReleasePackageError(f"Tracked package input is not a regular file: {path}")
        data = file_path.read_bytes()
        if len(data) > maximum:
            raise ReleasePackageError(f"Package input exceeds {maximum} bytes: {path}")
        selected.append(IndexedFile(path=path, mode=mode, data=data))

    selected.sort(key=lambda item: item.path)
    selected_paths = {item.path for item in selected}
    missing = sorted(
        str(path) for path in policy.get("required_paths", []) if str(path) not in selected_paths
    )
    if missing:
        raise ReleasePackageError("Required package paths are missing: " + ", ".join(missing))
    if len(selected_paths) != len(selected):
        raise ReleasePackageError("Package payload contains duplicate paths")
    if not selected:
        raise ReleasePackageError("Package payload is empty")
    return selected


def _python_dependencies(root: Path) -> list[dict[str, Any]]:
    path = root / "requirements-ci.txt"
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_RE.match(line)
        if not match:
            continue
        name, version = match.group(1), match.group(2)
        identity = (name.casefold(), version)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(
            {
                "ecosystem": "pypi",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{quote(name.casefold(), safe='')}@{quote(version, safe='')}",
            }
        )
    return sorted(result, key=lambda item: (item["name"].casefold(), item["version"]))


def _node_dependencies(root: Path) -> list[dict[str, Any]]:
    path = root / "cloud" / "package-lock.json"
    if not path.is_file():
        return []
    document = _load_object(path)
    packages = document.get("packages")
    if not isinstance(packages, dict):
        raise ReleasePackageError("cloud/package-lock.json lacks packages")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for package_path, value in packages.items():
        if not package_path or not isinstance(value, dict):
            continue
        name = str(value.get("name") or "").strip()
        if not name and str(package_path).startswith("node_modules/"):
            name = str(package_path)[len("node_modules/") :]
        version = str(value.get("version") or "").strip()
        if not name or not version:
            continue
        identity = (name.casefold(), version)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(
            {
                "ecosystem": "npm",
                "name": name,
                "version": version,
                "purl": f"pkg:npm/{quote(name, safe='@/')}@{quote(version, safe='')}",
                "integrity": str(value.get("integrity") or "").strip() or None,
            }
        )
    return sorted(result, key=lambda item: (item["name"].casefold(), item["version"]))


def dependency_inventory(root: Path) -> list[dict[str, Any]]:
    return _python_dependencies(root) + _node_dependencies(root)


def _spdx_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"SPDXRef-{prefix}-{digest}"


def build_manifest(
    files: Sequence[IndexedFile],
    *,
    package_name: str,
    version: str,
    source_commit: str,
    source_epoch: int,
    build_mode: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "package_name": package_name,
        "version": version,
        "source_commit": source_commit,
        "source_date_epoch": source_epoch,
        "build_mode": build_mode,
        "privacy_class": "public_code_no_user_data_no_secrets",
        "files": [
            {
                "path": item.path,
                "bytes": len(item.data),
                "mode": "0755" if item.mode == 0o100755 else "0644",
                "sha256": hashlib.sha256(item.data).hexdigest(),
            }
            for item in files
        ],
    }


def build_sbom(
    manifest: Mapping[str, Any],
    dependencies: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    package_name = str(manifest["package_name"])
    version = str(manifest["version"])
    source_commit = str(manifest["source_commit"])
    created = datetime.fromtimestamp(int(manifest["source_date_epoch"]), timezone.utc).isoformat()
    root_package_id = "SPDXRef-Package-Root"
    file_records: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": root_package_id,
        }
    ]
    for value in manifest["files"]:
        file_id = _spdx_id("File", str(value["path"]))
        file_records.append(
            {
                "SPDXID": file_id,
                "fileName": str(value["path"]),
                "checksums": [
                    {"algorithm": "SHA256", "checksumValue": str(value["sha256"])}
                ],
            }
        )
        relationships.append(
            {
                "spdxElementId": root_package_id,
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": file_id,
            }
        )

    packages: list[dict[str, Any]] = [
        {
            "SPDXID": root_package_id,
            "name": package_name,
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": True,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "supplier": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "OTHER",
                    "referenceType": "source-commit",
                    "referenceLocator": source_commit,
                }
            ],
        }
    ]
    for dependency in dependencies:
        identity = f"{dependency.get('ecosystem')}:{dependency.get('name')}@{dependency.get('version')}"
        dependency_id = _spdx_id("Package", identity)
        package: dict[str, Any] = {
            "SPDXID": dependency_id,
            "name": str(dependency.get("name")),
            "versionInfo": str(dependency.get("version")),
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "supplier": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": str(dependency.get("purl")),
                }
            ],
        }
        if dependency.get("integrity"):
            package["comment"] = f"lockfile integrity: {dependency['integrity']}"
        packages.append(package)
        relationships.append(
            {
                "spdxElementId": root_package_id,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": dependency_id,
            }
        )

    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{package_name}-{version}",
        "documentNamespace": (
            "https://example.invalid/investor-intelligence/spdx/"
            f"{source_commit}/{quote(version, safe='.-')}"
        ),
        "creationInfo": {
            "created": created,
            "creators": ["Tool: investor-intelligence-release-package-v1"],
        },
        "packages": packages,
        "files": file_records,
        "relationships": relationships,
    }


def _zip_datetime(source_epoch: int) -> tuple[int, int, int, int, int, int]:
    value = datetime.fromtimestamp(source_epoch, timezone.utc)
    if value.year < 1980:
        value = datetime(1980, 1, 1, tzinfo=timezone.utc)
    return (value.year, value.month, value.day, value.hour, value.minute, value.second // 2 * 2)


def _write_zip_entry(
    archive: zipfile.ZipFile,
    path: str,
    data: bytes,
    *,
    source_epoch: int,
    executable: bool = False,
) -> None:
    info = zipfile.ZipInfo(path, date_time=_zip_datetime(source_epoch))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = ((0o100755 if executable else 0o100644) & 0xFFFF) << 16
    info.flag_bits |= 0x800
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _validate_release_binding(
    release_status: Mapping[str, Any],
    *,
    source_commit: str,
    version: str,
    synthetic: bool,
) -> None:
    if synthetic:
        return
    if release_status.get("release_ready") is not True:
        raise ReleasePackageError("Final package build requires release_ready=true")
    if release_status.get("candidate_commit") != source_commit:
        raise ReleasePackageError("Final package source commit is not the accepted candidate commit")
    if release_status.get("candidate_version") != version:
        raise ReleasePackageError("Final package version is not the accepted candidate version")
    gates = release_status.get("gates")
    if not isinstance(gates, dict) or any(value != "PASS" for value in gates.values()):
        raise ReleasePackageError("Final package build requires every release gate PASS")


def build_release_package(
    *,
    root: Path = ROOT,
    output_dir: Path,
    version: str,
    synthetic: bool,
    policy_path: Path | None = None,
    release_status_path: Path | None = None,
    indexed_paths: Sequence[tuple[str, int]] | None = None,
) -> PackageOutputs:
    if not VERSION_RE.fullmatch(version):
        raise ReleasePackageError("Version must be a strict SemVer-compatible value")
    policy = _load_object(policy_path or (root / "config" / "release-package-policy.json"))
    if policy.get("schema_version") != 1:
        raise ReleasePackageError("Release package policy schema_version must be 1")
    if policy.get("tracked_files_only") is not True or policy.get("reproducible_zip") is not True:
        raise ReleasePackageError("Release package policy must require tracked deterministic inputs")

    source_commit, source_epoch = source_identity(root)
    release_status = _load_object(
        release_status_path or (root / "config" / "release-candidate-status.json")
    )
    _validate_release_binding(
        release_status,
        source_commit=source_commit,
        version=version,
        synthetic=synthetic,
    )
    files = collect_payload_files(root, policy, indexed_paths=indexed_paths)
    package_name = str(policy.get("package_name") or "investor-intelligence")
    build_mode = "synthetic_validation" if synthetic else "final_release"
    manifest = build_manifest(
        files,
        package_name=package_name,
        version=version,
        source_commit=source_commit,
        source_epoch=source_epoch,
        build_mode=build_mode,
    )
    manifest_bytes = _json_bytes(manifest)
    sbom = build_sbom(manifest, dependency_inventory(root))
    sbom_bytes = _json_bytes(sbom)
    metadata_bytes = _json_bytes(
        {
            "schema_version": 1,
            "package_name": package_name,
            "version": version,
            "source_commit": source_commit,
            "source_date_epoch": source_epoch,
            "build_mode": build_mode,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "sbom_sha256": hashlib.sha256(sbom_bytes).hexdigest(),
            "release_ready_at_build": release_status.get("release_ready") is True,
            "deployed": False,
            "billing_enabled": False,
            "secrets_included": False,
            "user_data_included": False,
        }
    )

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{package_name}-{version}.zip"
    manifest_path = output_dir / f"{package_name}-{version}.manifest.json"
    sbom_path = output_dir / f"{package_name}-{version}.sbom.spdx.json"
    checksum_path = output_dir / f"{package_name}-{version}.sha256"

    with tempfile.NamedTemporaryFile(
        prefix=f".{archive_path.name}.", suffix=".tmp", dir=output_dir, delete=False
    ) as handle:
        temporary_archive = Path(handle.name)
    try:
        with zipfile.ZipFile(
            temporary_archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            for item in files:
                _write_zip_entry(
                    archive,
                    item.path,
                    item.data,
                    source_epoch=source_epoch,
                    executable=item.mode == 0o100755,
                )
            _write_zip_entry(
                archive,
                "release-manifest.json",
                manifest_bytes,
                source_epoch=source_epoch,
            )
            _write_zip_entry(
                archive,
                "release-metadata.json",
                metadata_bytes,
                source_epoch=source_epoch,
            )
            _write_zip_entry(
                archive,
                "sbom.spdx.json",
                sbom_bytes,
                source_epoch=source_epoch,
            )
        archive_size = temporary_archive.stat().st_size
        maximum_package = int(policy.get("maximum_package_bytes") or 50_000_000)
        if archive_size > maximum_package:
            raise ReleasePackageError(
                f"Release archive exceeds {maximum_package} bytes: {archive_size}"
            )
        os.replace(temporary_archive, archive_path)
    finally:
        temporary_archive.unlink(missing_ok=True)

    manifest_path.write_bytes(manifest_bytes)
    sbom_path.write_bytes(sbom_bytes)
    archive_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{archive_sha256}  {archive_path.name}\n", encoding="ascii")
    return PackageOutputs(
        archive=archive_path,
        checksum=checksum_path,
        manifest=manifest_path,
        sbom=sbom_path,
        source_commit=source_commit,
        version=version,
        file_count=len(files),
        archive_sha256=archive_sha256,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version")
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    try:
        commit, _epoch = source_identity(ROOT)
        version = args.version or f"0.0.0-dev.{commit[:12]}"
        outputs = build_release_package(
            output_dir=args.output_dir,
            version=version,
            synthetic=args.synthetic,
        )
    except (FileNotFoundError, ReleasePackageError, OSError, ValueError) as exc:
        print(f"RELEASE PACKAGE BUILD FAILED\n- {exc}")
        return 1
    print(
        json.dumps(
            {
                "archive": str(outputs.archive),
                "checksum": str(outputs.checksum),
                "manifest": str(outputs.manifest),
                "sbom": str(outputs.sbom),
                "source_commit": outputs.source_commit,
                "version": outputs.version,
                "file_count": outputs.file_count,
                "archive_sha256": outputs.archive_sha256,
                "synthetic": args.synthetic,
                "deployment_performed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
