#!/usr/bin/env python3
"""Build the v2.1 public snapshot after diversified v2.1.3 scoring."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import build_v21_public_snapshot as base

SCORING_VERSION = "system-operationalization-v2.1.3-diversified"
CATALOG_COUNT = 101


def validate_top20(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list) or len(records) != 20:
        raise base.SnapshotError("Top 20 must contain exactly 20 records")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(records, 1):
        if not isinstance(raw, dict) or set(raw) != base.RECORD_KEYS:
            raise base.SnapshotError(f"Top 20 record {index} has an invalid closed schema")
        ticker = str(raw.get("ticker") or "").upper()
        if not ticker or ticker in seen or raw.get("rank") != index:
            raise base.SnapshotError("Top 20 ticker/rank contract failed")
        seen.add(ticker)
        for key in ("serenity_score", "serenity_raw_score", "risk_penalty", "data_quality"):
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise base.SnapshotError(f"Top 20 {ticker} has invalid numeric field {key}")
        if not 0 <= float(raw["serenity_score"]) <= 100 or not 0 <= float(raw["data_quality"]) <= 1:
            raise base.SnapshotError(f"Top 20 {ticker} score/quality is out of range")
        if (
            raw.get("scoring_version") != SCORING_VERSION
            or raw.get("line_public_eligible") is not True
            or raw.get("provider_scope") != "public_only"
            or raw.get("owner_watchlist_inherited") is not False
        ):
            raise base.SnapshotError(f"Top 20 {ticker} diversified public boundary is invalid")
        overlay = raw.get("aschenbrenner_overlay")
        if not isinstance(overlay, dict) or overlay.get("included_in_serenity_score") is not False:
            raise base.SnapshotError(f"Top 20 {ticker} overlay boundary is invalid")
        evidence = raw.get("evidence")
        source_ids = {
            str(item.get("source_id") or "")
            for item in evidence
            if isinstance(item, dict) and item.get("source_id")
        } if isinstance(evidence, list) else set()
        if (
            not isinstance(evidence, list) or len(evidence) < 2
            or raw.get("evidence_count") != len(evidence)
            or raw.get("source_count") != len(source_ids)
            or len(source_ids) < 2
        ):
            raise base.SnapshotError(f"Top 20 {ticker} lacks genuine multi-source evidence")
        base.iso_timestamp(raw.get("generated_at"), f"{ticker}.generated_at")
        base.iso_timestamp(raw.get("as_of"), f"{ticker}.as_of")
        result.append({**raw, "ticker": ticker})
    expected = sorted(
        result,
        key=lambda item: (-float(item["serenity_score"]), -float(item["data_quality"]), str(item["ticker"])),
    )
    if result != expected:
        raise base.SnapshotError("Top 20 ordering is not deterministic")
    base.reject_private_keys(result)
    return result


def validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise base.SnapshotError("Source plan must be an object")
    inventory = value.get("inventory")
    federation = value.get("live_source_federation")
    scoring = value.get("scoring_methodology")
    if (
        value.get("schema_version") != 1
        or value.get("catalog_count") != CATALOG_COUNT
        or value.get("automatic_activation") is not False
        or value.get("owner_watchlist_inherited") is not False
        or value.get("provider_scope") != "public_only"
        or value.get("line_public_eligible") is not True
        or not isinstance(inventory, dict)
        or inventory.get("source_count") != CATALOG_COUNT
        or inventory.get("runtime_enabled_count") != 0
        or not isinstance(federation, dict)
        or len(federation.get("successful_families") or []) < 5
        or len(federation.get("official_successful_families") or []) < 4
        or float(federation.get("ticker_coverage_ratio") or 0) < 0.8
        or int(federation.get("unresolved_material_conflict_count") or 0) != 0
        or federation.get("yahoo_authoritative") is not False
        or federation.get("catalog_source_count_is_not_live_use") is not True
        or not isinstance(scoring, dict)
        or scoring.get("scoring_version") != SCORING_VERSION
        or scoring.get("official_serenity_formula_claimed") is not False
    ):
        raise base.SnapshotError("Source plan does not preserve the v2.1.3 diversified fail-closed boundary")
    base.reject_private_keys(value)
    return value


def self_test() -> None:
    assert SCORING_VERSION.startswith("system-operationalization-")
    assert CATALOG_COUNT == 101
    print("V213_DIVERSIFIED_PUBLIC_SNAPSHOT_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=base.OUTPUT_PATH)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    base.validate_top20 = validate_top20
    base.validate_plan = validate_plan
    base.REPORT_PREFIX = "\n".join((
        "<!-- line-public-eligible: true -->",
        "<!-- provider-scope: public_only -->",
        "<!-- owner-watchlist-inherited: false -->",
        f"<!-- scoring-version: {SCORING_VERSION} -->",
        "<!-- scoring-display-label: System operationalization score -->",
        "<!-- official-serenity-formula-claimed: false -->",
        "",
    ))
    envelope = base.build_envelope()
    base.atomic_write(args.output, envelope)
    print(json.dumps({
        "status": "PASS",
        "run_id": envelope["run_id"],
        "output": str(args.output),
        "top20_count": 20,
        "catalog_count": CATALOG_COUNT,
        "scoring_version": SCORING_VERSION,
        "provider_scope": "public_only",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
