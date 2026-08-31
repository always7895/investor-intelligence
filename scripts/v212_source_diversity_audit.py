#!/usr/bin/env python3
"""Audit v2.1.2 source breadth without confusing catalog size with live use.

The repository intentionally keeps the reviewed source catalog fail-closed.  A
large catalog is not evidence that production analysis actually used those
sources.  This audit reports both layers separately and can enforce a minimum
live-source-family count for open-ended local-model research.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_MANIFEST = ROOT / "config" / "authoritative-source-catalog.json"
ACTIVATION_PATH = ROOT / "config" / "v21-source-activation.json"
V212_POLICY_PATH = ROOT / "config" / "v212-source-policy.json"


class SourceAuditError(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise SourceAuditError(f"Expected JSON object: {path}")
    return value


def _fragments(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    columns = [str(value) for value in manifest.get("member_columns", [])]
    if not columns:
        raise SourceAuditError("Catalog member columns are missing")
    defaults = manifest.get("source_defaults")
    if not isinstance(defaults, dict):
        raise SourceAuditError("Catalog source defaults are missing")
    for relative in manifest.get("fragment_paths", []):
        document = _object(ROOT / str(relative))
        for row in document.get("members", []):
            if not isinstance(row, list) or len(row) != len(columns):
                raise SourceAuditError(f"Invalid catalog member row in {relative}")
            item = dict(zip(columns, row, strict=True))
            item.update({
                "cost": defaults.get("cost"),
                "data_class": defaults.get("data_class"),
                "runtime_enabled": defaults.get("runtime_enabled"),
            })
            sources.append(item)
    return sources


def audit() -> dict[str, Any]:
    manifest = _object(CATALOG_MANIFEST)
    activation = _object(ACTIVATION_PATH)
    policy = _object(V212_POLICY_PATH)
    sources = _fragments(manifest)

    source_by_id = {str(item.get("id")): item for item in sources}
    selected = activation.get("selected_sources")
    selected = selected if isinstance(selected, dict) else {}
    live_authoritative = sorted(
        source_id
        for source_id, config in selected.items()
        if isinstance(config, dict) and config.get("runtime_enabled") is True
    )
    discovery = activation.get("discovery_only_sources")
    discovery = discovery if isinstance(discovery, dict) else {}
    live_observation = sorted(
        source_id
        for source_id, config in discovery.items()
        if isinstance(config, dict) and source_id in source_by_id
    )

    regions = {
        str(region)
        for item in sources
        for region in (item.get("regions") or [])
    }
    jurisdictions = {
        str(value)
        for item in sources
        for value in (item.get("jurisdictions") or [])
    }
    topics = {
        str(value)
        for item in sources
        for value in (item.get("topics") or [])
    }
    hosts = {str(item.get("host_group") or "") for item in sources if item.get("host_group")}
    authorities = Counter(str(item.get("authority") or "") for item in sources)

    available_preferred = [
        source_id
        for source_id in policy.get("open_qa_preferred_source_families", [])
        if source_id in source_by_id
    ]
    current_live_families = sorted(set(live_authoritative + live_observation))
    minimum_live = int(policy.get("open_qa_minimum_successful_source_families", 3))

    return {
        "schema_version": 1,
        "product_version": "2.1.2",
        "catalog": {
            "source_count": len(sources),
            "regions": sorted(regions),
            "region_count": len(regions),
            "jurisdiction_count": len(jurisdictions),
            "topic_count": len(topics),
            "host_group_count": len(hosts),
            "authority_count": len(authorities),
            "largest_authority_share": (
                max(authorities.values(), default=0) / len(sources) if sources else 0.0
            ),
            "source_count_is_not_activation_claim": True,
        },
        "production_live": {
            "authoritative_sources": live_authoritative,
            "discovery_or_market_observation_sources": live_observation,
            "source_family_count": len(current_live_families),
            "source_families": current_live_families,
            "meets_open_qa_minimum": len(current_live_families) >= minimum_live,
        },
        "v212_open_qa_target": {
            "minimum_successful_source_families": minimum_live,
            "preferred_available_catalog_sources": available_preferred,
            "serenity_score_unchanged_by_unmapped_sources": bool(
                policy.get("additional_sources_do_not_change_serenity_score_without_explicit_factor_mapping")
            ),
        },
    }


def validate(summary: dict[str, Any], *, strict_live: bool) -> None:
    policy = _object(V212_POLICY_PATH)
    catalog = summary["catalog"]
    if int(catalog["source_count"]) < int(policy["catalog_minimum_sources"]):
        raise SourceAuditError("Catalog source breadth is below policy")
    if int(catalog["region_count"]) < int(policy["catalog_minimum_regions"]):
        raise SourceAuditError("Catalog region breadth is below policy")
    if int(catalog["host_group_count"]) < int(policy["catalog_minimum_host_groups"]):
        raise SourceAuditError("Catalog host diversity is below policy")
    if strict_live and not summary["production_live"]["meets_open_qa_minimum"]:
        raise SourceAuditError(
            "Current production live sources do not meet the v2.1.2 open-QA diversity minimum"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-live", action="store_true")
    args = parser.parse_args()
    try:
        summary = audit()
        validate(summary, strict_live=args.strict_live)
    except (OSError, json.JSONDecodeError, SourceAuditError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "PASS", **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
