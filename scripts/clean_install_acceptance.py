#!/usr/bin/env python3
"""Verify and smoke-test a package in a fresh temporary extraction root.

This is an acceptance test, not an installer. It never writes outside the
explicit extraction root, never registers tasks or webhooks, never deploys and
never reads credentials. Repository-only gates that depend on ``.git`` or
``.github`` run before packaging; only package-compatible gates are repeated
after the verified release ZIP is extracted.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Sequence

from clean_install_gate_policy import (
    PACKAGE_COMPATIBLE_GATE_SCRIPTS,
    PACKAGE_COMPATIBLE_TEST_PATTERNS,
    REPOSITORY_ONLY_GATE_SCRIPTS,
)
from verify_release_package import (
    ReleaseVerificationError,
    verify_release_package,
)

FORBIDDEN_INITIAL_SEGMENTS = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".npm-cache",
    "data",
    "reports",
    "state",
}
SENSITIVE_ENV_PREFIXES = (
    "LINE_",
    "CLOUDFLARE_",
    "IBKR_",
    "PORTFOLIO_",
    "TENANT_",
    "LOCAL_LLM_",
)


class CleanInstallError(ValueError):
    """Raised when a fresh extraction depends on developer or private state."""


def _sanitized_env() -> dict[str, str]:
    result = {
        key: value
        for key, value in os.environ.items()
        if not any(key.upper().startswith(prefix) for prefix in SENSITIVE_ENV_PREFIXES)
    }
    result.pop("PYTHONPATH", None)
    result["PYTHONNOUSERSITE"] = "1"
    result["PYTHONUTF8"] = "1"
    result["DELIVERY_ENABLED"] = "false"
    result["LINE_ENABLED"] = "false"
    result["LINE_PUSH_ENABLED"] = "false"
    result["CURRENT_PUBLIC_DATA_ENABLED"] = "false"
    result["CLOUD_INFERENCE_ENABLED"] = "false"
    result["IBKR_READONLY_ENABLED"] = "false"
    result["FREE_ONLY_MODE"] = "true"
    result["MEMORY_FEATURE_AVAILABLE"] = "false"
    return result


def _run(root: Path, arguments: Sequence[str], label: str) -> None:
    completed = subprocess.run(
        list(arguments),
        cwd=root,
        env=_sanitized_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )
    if completed.returncode != 0:
        tail = "\n".join(completed.stdout.splitlines()[-80:])
        raise CleanInstallError(f"{label} failed with exit {completed.returncode}:\n{tail}")


def _validate_initial_tree(root: Path) -> int:
    files = 0
    forbidden = {item.casefold() for item in FORBIDDEN_INITIAL_SEGMENTS}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part.casefold() in forbidden for part in relative.parts):
            raise CleanInstallError(
                f"Package contains developer/private state: {relative.as_posix()}"
            )
        if path.is_symlink():
            raise CleanInstallError(
                f"Package extraction contains a symlink: {relative.as_posix()}"
            )
        if path.is_file():
            files += 1
    if files < 20:
        raise CleanInstallError("Extracted package is unexpectedly small")
    return files


def _validate_documents(root: Path) -> tuple[int, int]:
    json_count = 0
    toml_count = 0
    for path in root.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
        json_count += 1
    for path in root.rglob("*.toml"):
        tomllib.loads(path.read_text(encoding="utf-8"))
        toml_count += 1
    return json_count, toml_count


def _require_package_file(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise CleanInstallError(f"Required package acceptance file is missing: {relative}")
    return path


def clean_install_acceptance(
    *,
    archive: Path,
    checksum: Path,
    manifest: Path,
    sbom: Path,
    policy: Path,
    extraction_root: Path | None = None,
) -> dict[str, object]:
    owned_temporary: tempfile.TemporaryDirectory[str] | None = None
    if extraction_root is None:
        owned_temporary = tempfile.TemporaryDirectory(
            prefix="investor-intelligence-clean-install-"
        )
        extraction_root = Path(owned_temporary.name) / "package"
    try:
        verification = verify_release_package(
            archive_path=archive,
            checksum_path=checksum,
            manifest_path=manifest,
            sbom_path=sbom,
            policy_path=policy,
            extract_to=extraction_root,
        )
        file_count = _validate_initial_tree(extraction_root)
        json_count, toml_count = _validate_documents(extraction_root)

        python = sys.executable
        _run(
            extraction_root,
            [python, "-m", "compileall", "-q", "scripts", "tests"],
            "Python compilation",
        )
        for script in PACKAGE_COMPATIBLE_GATE_SCRIPTS:
            _require_package_file(extraction_root, script)
            _run(extraction_root, [python, script], script)
        for pattern in PACKAGE_COMPATIBLE_TEST_PATTERNS:
            _require_package_file(extraction_root, f"tests/{pattern}")
            _run(
                extraction_root,
                [
                    python,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    pattern,
                    "-v",
                ],
                f"clean-install {pattern}",
            )
        for repository_only_gate in REPOSITORY_ONLY_GATE_SCRIPTS:
            _require_package_file(extraction_root, repository_only_gate)

        return {
            **verification,
            "clean_install": True,
            "initial_file_count": file_count,
            "json_documents": json_count,
            "toml_documents": toml_count,
            "package_compatible_gate_count": len(PACKAGE_COMPATIBLE_GATE_SCRIPTS),
            "package_compatible_test_count": len(PACKAGE_COMPATIBLE_TEST_PATTERNS),
            "repository_only_gates_not_reexecuted_after_extraction": list(
                REPOSITORY_ONLY_GATE_SCRIPTS
            ),
            "developer_cache_used": False,
            "secrets_used": False,
            "deployment_performed": False,
        }
    finally:
        if owned_temporary is not None:
            owned_temporary.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--extract-to", type=Path)
    args = parser.parse_args()
    try:
        summary = clean_install_acceptance(
            archive=args.archive,
            checksum=args.checksum,
            manifest=args.manifest,
            sbom=args.sbom,
            policy=args.policy,
            extraction_root=args.extract_to,
        )
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        subprocess.SubprocessError,
        ReleaseVerificationError,
        CleanInstallError,
    ) as exc:
        print(f"CLEAN INSTALL ACCEPTANCE FAILED\n- {exc}")
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
