#!/usr/bin/env python3
"""Render a pip ``--report`` JSON document as a hash-locked requirements file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_NAME_NORMALIZER = re.compile(r"[-_.]+")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def normalize_name(name: str) -> str:
    return _NAME_NORMALIZER.sub("-", name).lower()


def _extract_sha256(download_info: dict[str, Any]) -> str:
    archive_info = download_info.get("archive_info") or {}
    hashes = archive_info.get("hashes") or {}
    digest = hashes.get("sha256")
    if isinstance(digest, str) and _SHA256.fullmatch(digest):
        return digest.lower()

    legacy = archive_info.get("hash")
    if isinstance(legacy, str) and legacy.lower().startswith("sha256="):
        digest = legacy.split("=", 1)[1]
        if _SHA256.fullmatch(digest):
            return digest.lower()

    raise ValueError("pip report item does not contain a valid SHA-256 archive digest")


def render_lock(report: dict[str, Any], required_names: set[str] | None = None) -> str:
    installations = report.get("install")
    if not isinstance(installations, list) or not installations:
        raise ValueError("pip report contains no resolved install records")

    resolved: dict[str, tuple[str, str]] = {}
    for item in installations:
        if not isinstance(item, dict):
            raise ValueError("pip report install record must be an object")
        metadata = item.get("metadata") or {}
        name = metadata.get("name")
        version = metadata.get("version")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("pip report install record is missing package name")
        if not isinstance(version, str) or not version.strip():
            raise ValueError(f"pip report package {name!r} is missing an exact version")
        normalized = normalize_name(name)
        digest = _extract_sha256(item.get("download_info") or {})
        candidate = (version.strip(), digest)
        previous = resolved.get(normalized)
        if previous is not None and previous != candidate:
            raise ValueError(f"pip report resolves conflicting records for {normalized}")
        resolved[normalized] = candidate

    required = {normalize_name(name) for name in (required_names or set())}
    missing = sorted(required - set(resolved))
    if missing:
        raise ValueError(f"pip report is missing required direct packages: {', '.join(missing)}")

    lines = [
        "# Generated from requirements-ci.in using pip --dry-run --report.",
        "# Do not edit by hand; regenerate on the trusted BARRY runner.",
    ]
    for name in sorted(resolved):
        version, digest = resolved[name]
        lines.append(f"{name}=={version} --hash=sha256:{digest}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        output = render_lock(report, set(args.require))
        args.output.write_text(output, encoding="utf-8", newline="\n")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"DEPENDENCY LOCK RENDER FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote hash-locked Python requirements to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
