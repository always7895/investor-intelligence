#!/usr/bin/env python3
"""Validate actual Cloudflare KV namespace IDs without printing secret values.

Repository placeholders prove only configuration shape. Before deployment, the
release transaction must pass ``--require-configured`` with six real IDs in the
environment and this command must confirm that no production or preview
namespace is reused across public, tenant-private or ephemeral-security roles.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Mapping

PRODUCTION_NAMES = (
    "CLOUDFLARE_PUBLIC_KV_NAMESPACE_ID",
    "CLOUDFLARE_TENANT_PRIVATE_KV_NAMESPACE_ID",
    "CLOUDFLARE_EPHEMERAL_SECURITY_KV_NAMESPACE_ID",
)
PREVIEW_NAMES = (
    "CLOUDFLARE_PUBLIC_PREVIEW_KV_NAMESPACE_ID",
    "CLOUDFLARE_TENANT_PRIVATE_PREVIEW_KV_NAMESPACE_ID",
    "CLOUDFLARE_EPHEMERAL_SECURITY_PREVIEW_KV_NAMESPACE_ID",
)
ALL_NAMES = (*PRODUCTION_NAMES, *PREVIEW_NAMES)
PLACEHOLDER_MARKERS = (
    "replace_with",
    "placeholder",
    "example",
    "changeme",
)


@dataclass(frozen=True)
class NamespaceValidation:
    configured: bool
    valid: bool
    missing_labels: tuple[str, ...]
    duplicate_role_groups: tuple[tuple[str, ...], ...]
    placeholder_labels: tuple[str, ...]

    def as_public_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "valid": self.valid,
            "missing_labels": list(self.missing_labels),
            "duplicate_role_groups": [list(group) for group in self.duplicate_role_groups],
            "placeholder_labels": list(self.placeholder_labels),
            "values_exposed": False,
        }


def validate_namespace_ids(environment: Mapping[str, str]) -> NamespaceValidation:
    values = {name: str(environment.get(name, "")).strip() for name in ALL_NAMES}
    missing = tuple(name for name, value in values.items() if not value)
    placeholder = tuple(
        name
        for name, value in values.items()
        if value and any(marker in value.casefold() for marker in PLACEHOLDER_MARKERS)
    )

    reverse: dict[str, list[str]] = {}
    for name, value in values.items():
        if value:
            reverse.setdefault(value, []).append(name)
    duplicates = tuple(
        tuple(sorted(labels))
        for labels in reverse.values()
        if len(labels) > 1
    )

    configured = not missing and not placeholder
    valid = configured and not duplicates
    return NamespaceValidation(
        configured=configured,
        valid=valid,
        missing_labels=missing,
        duplicate_role_groups=tuple(sorted(duplicates)),
        placeholder_labels=placeholder,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-configured",
        action="store_true",
        help="Fail when real production/preview IDs are not all configured",
    )
    args = parser.parse_args()
    result = validate_namespace_ids(os.environ)
    print(json.dumps(result.as_public_dict(), ensure_ascii=False, sort_keys=True))
    if result.duplicate_role_groups or result.placeholder_labels:
        return 1
    if args.require_configured and not result.configured:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
