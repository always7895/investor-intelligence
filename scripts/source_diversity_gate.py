#!/usr/bin/env python3
"""Audit breadth, independence and fail-closed posture of the source catalog."""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

# BARRY runs the reviewed portable CPython in isolated mode. Add only the
# repository's static scripts directory before importing another reviewed gate;
# this does not permit dynamic plugins or external module discovery.
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from authoritative_source_catalog import (  # noqa: E402
    SourceRecord,
    load_catalog as load_authoritative_catalog,
)

DEFAULT_CATALOG = ROOT / "config" / "authoritative-source-catalog.json"

MINIMUM_SOURCES = 90
MINIMUM_REGIONS = 5
MINIMUM_JURISDICTIONS = 15
MINIMUM_TOPICS = 15
MINIMUM_HOST_GROUPS = 20
REQUIRED_TIERS = {"T0", "T1", "T2", "T3"}
MAX_SINGLE_HOST_SHARE = 0.15
MAX_SINGLE_AUTHORITY_SHARE = 0.10


class SourceDiversityError(ValueError):
    """Raised when the source catalog cannot be audited."""


def _source_document(source: SourceRecord) -> dict[str, Any]:
    value = asdict(source)
    for key in ("regions", "jurisdictions", "topics", "claim_types", "base_urls"):
        value[key] = list(value[key])
    value["gates"] = dict(source.gates)
    value["rate_limit"] = dict(source.rate_limit)
    return value


def load_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    """Return an assembled monolithic view for gates and mutation tests."""
    try:
        manifest, records, warnings = load_authoritative_catalog(path)
    except (FileNotFoundError, ValueError) as exc:
        raise SourceDiversityError(str(exc)) from exc
    return {
        "schema_version": manifest.get("schema_version"),
        "sources": [_source_document(source) for source in records],
        "warnings": list(warnings),
    }


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def audit_source_diversity(document: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    findings: list[str] = []
    sources = document.get("sources")
    if not isinstance(sources, list):
        raise SourceDiversityError("Authoritative source catalog requires an assembled sources array")

    regions: set[str] = set()
    jurisdictions: set[str] = set()
    topics: set[str] = set()
    tiers: Counter[str] = Counter()
    authorities: Counter[str] = Counter()
    host_groups: Counter[str] = Counter()
    authentication: Counter[str] = Counter()
    transports: Counter[str] = Counter()
    unique_ids: set[str] = set()

    for index, source in enumerate(sources):
        label = f"sources[{index}]"
        if not isinstance(source, dict):
            findings.append(f"{label}: source must be an object")
            continue
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            findings.append(f"{label}: id is required")
        elif source_id in unique_ids:
            findings.append(f"{label}: duplicate source id {source_id}")
        else:
            unique_ids.add(source_id)

        regions.update(_strings(source.get("regions")))
        jurisdictions.update(_strings(source.get("jurisdictions")))
        source_topics = _strings(source.get("topics"))
        topics.update(source_topics)
        tier = str(source.get("evidence_tier") or "").strip()
        authority = str(source.get("authority") or "").strip()
        host_group = str(source.get("host_group") or "").strip().casefold()
        tiers[tier] += 1
        authorities[authority] += 1
        host_groups[host_group] += 1
        authentication[str(source.get("authentication") or "")] += 1
        transports[str(source.get("transport") or "")] += 1

        if source.get("runtime_enabled") is not False:
            findings.append(f"{source_id or label}: runtime_enabled must remain false")
        if source.get("cost") != "free":
            findings.append(f"{source_id or label}: cost must be free")
        if source.get("data_class") != "public":
            findings.append(f"{source_id or label}: data_class must be public")
        if not source_topics:
            findings.append(f"{source_id or label}: topics cannot be empty")
        if not authority:
            findings.append(f"{source_id or label}: authority is required")
        if not host_group:
            findings.append(f"{source_id or label}: host_group is required")
        urls = _strings(source.get("base_urls"))
        if not urls:
            findings.append(f"{source_id or label}: at least one base URL is required")
        for raw_url in urls:
            try:
                parsed = urlsplit(raw_url)
                port = parsed.port
            except ValueError:
                findings.append(f"{source_id or label}: invalid base URL {raw_url!r}")
                continue
            if (
                parsed.scheme.casefold() != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or port not in (None, 443)
            ):
                findings.append(f"{source_id or label}: unsafe base URL {raw_url!r}")

        gates = source.get("gates")
        if not isinstance(gates, dict):
            findings.append(f"{source_id or label}: gates must be an object")
        elif source.get("runtime_enabled") is True and not all(value is True for value in gates.values()):
            findings.append(f"{source_id or label}: enabled source lacks complete gates")

    total = len(sources)
    if total < MINIMUM_SOURCES:
        findings.append(f"catalog has {total} sources; at least {MINIMUM_SOURCES} are required")
    if len(regions) < MINIMUM_REGIONS:
        findings.append(f"catalog has {len(regions)} regions; at least {MINIMUM_REGIONS} are required")
    if len(jurisdictions) < MINIMUM_JURISDICTIONS:
        findings.append(
            f"catalog has {len(jurisdictions)} jurisdictions; at least {MINIMUM_JURISDICTIONS} are required"
        )
    if len(topics) < MINIMUM_TOPICS:
        findings.append(f"catalog has {len(topics)} topics; at least {MINIMUM_TOPICS} are required")
    missing_tiers = sorted(REQUIRED_TIERS.difference(tiers))
    if missing_tiers:
        findings.append("catalog lacks required evidence tiers: " + ", ".join(missing_tiers))
    if len(host_groups) < MINIMUM_HOST_GROUPS:
        findings.append(
            f"catalog has {len(host_groups)} host groups; at least {MINIMUM_HOST_GROUPS} are required"
        )

    if total:
        largest_host, largest_host_count = host_groups.most_common(1)[0] if host_groups else ("", 0)
        largest_authority, largest_authority_count = authorities.most_common(1)[0] if authorities else ("", 0)
        if largest_host_count / total > MAX_SINGLE_HOST_SHARE:
            findings.append(f"host group {largest_host!r} represents {largest_host_count}/{total} sources")
        if largest_authority_count / total > MAX_SINGLE_AUTHORITY_SHARE:
            findings.append(
                f"authority {largest_authority!r} represents {largest_authority_count}/{total} sources"
            )

    summary = {
        "source_count": total,
        "unique_source_ids": len(unique_ids),
        "region_count": len(regions),
        "regions": sorted(regions),
        "jurisdiction_count": len(jurisdictions),
        "topic_count": len(topics),
        "topics": sorted(topics),
        "evidence_tiers": dict(sorted(tiers.items())),
        "host_group_count": len(host_groups),
        "authority_count": len(authorities),
        "authentication_modes": dict(sorted(authentication.items())),
        "transport_types": dict(sorted(transports.items())),
        "runtime_enabled_count": sum(
            isinstance(source, dict) and source.get("runtime_enabled") is True
            for source in sources
        ),
        "catalog_source_count_limit": None,
    }
    return findings, summary


def main() -> int:
    try:
        findings, summary = audit_source_diversity(load_catalog())
    except (FileNotFoundError, SourceDiversityError, OSError) as exc:
        print(f"SOURCE DIVERSITY GATE FAILED\n- {exc}")
        return 1
    if findings:
        print("SOURCE DIVERSITY GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("SOURCE DIVERSITY GATE PASSED")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
