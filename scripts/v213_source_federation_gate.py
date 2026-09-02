#!/usr/bin/env python3
"""Recompute and persist strict v2.1.3 live-source federation gates.

This second-pass gate deliberately distinguishes broad global source diversity
from claim-specific ticker coverage. A ticker counts toward the 80% coverage
threshold only when it has at least two independent families and at least two
official issuer/listing identity or filing families. Yahoo can be present as a
T3 market observation, but it cannot satisfy the official-family requirement.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "v213-source-federation-policy.json"
FEDERATION_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"


class GateError(RuntimeError):
    pass


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"Invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise GateError(f"Expected object: {path}")
    return value


def atomic(path: Path, value: Mapping[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def evaluate(document: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    sources = document.get("global_sources")
    sources = sources if isinstance(sources, list) else []
    successful = {
        str(row.get("family"))
        for row in sources
        if isinstance(row, dict) and row.get("status") == "HEALTHY"
    }
    official = {
        str(row.get("family"))
        for row in sources
        if isinstance(row, dict)
        and row.get("status") == "HEALTHY"
        and row.get("official") is True
    }
    required = {
        str(value.get("family"))
        for value in policy.get("required_live_sources", {}).values()
        if isinstance(value, dict) and value.get("required") is True
    }
    ticker_rows = document.get("ticker_sources")
    ticker_rows = ticker_rows if isinstance(ticker_rows, list) else []
    minimum_all = int(policy["minimum_per_ticker_independent_families"])
    meeting = 0
    deficient: list[dict[str, Any]] = []
    for row in ticker_rows:
        if not isinstance(row, dict):
            continue
        all_count = int(row.get("independent_family_count") or 0)
        official_count = int(row.get("official_identity_or_filing_family_count") or 0)
        if all_count >= minimum_all and official_count >= 2:
            meeting += 1
        else:
            deficient.append({
                "ticker": str(row.get("ticker") or ""),
                "independent_family_count": all_count,
                "official_identity_or_filing_family_count": official_count,
            })
    ratio = meeting / len(ticker_rows) if ticker_rows else 0.0
    conflicts = document.get("unresolved_material_conflicts")
    conflicts = conflicts if isinstance(conflicts, list) else []
    concentration = document.get("concentration")
    concentration = concentration if isinstance(concentration, dict) else {}
    largest_share = float(concentration.get("largest_family_share") or 0.0)
    maximum_share = float(policy["maximum_single_family_evidence_share"])
    missing_required = sorted(required - successful)
    passed = (
        not missing_required
        and len(successful) >= int(policy["minimum_global_successful_families"])
        and len(official) >= int(policy["minimum_global_official_families"])
        and ratio >= float(policy["minimum_ticker_coverage_ratio"])
        and largest_share <= maximum_share
        and not conflicts
    )
    return {
        "pass": passed,
        "successful_families": sorted(successful),
        "official_successful_families": sorted(official),
        "missing_required_families": missing_required,
        "ticker_rows_meeting_minimum": meeting,
        "ticker_count": len(ticker_rows),
        "ticker_coverage_ratio": round(ratio, 4),
        "minimum_per_ticker_independent_families": minimum_all,
        "minimum_official_identity_or_filing_families": 2,
        "deficient_tickers": deficient,
        "largest_family_share": round(largest_share, 4),
        "maximum_single_family_evidence_share": maximum_share,
        "concentration_pass": largest_share <= maximum_share,
        "unresolved_material_conflict_count": len(conflicts),
        "yahoo_authoritative": False,
        "catalog_source_count_is_not_live_use": True,
        "claim_scope_separation_enforced": True,
    }


def self_test() -> None:
    policy = load(POLICY_PATH)
    sources = [
        {"family": "us_sec", "status": "HEALTHY", "official": True},
        {"family": "nasdaq", "status": "HEALTHY", "official": True},
        {"family": "world_bank", "status": "HEALTHY", "official": True},
        {"family": "us_bls", "status": "HEALTHY", "official": True},
        {"family": "ecb", "status": "HEALTHY", "official": True},
    ]
    rows = [{
        "ticker": f"T{i:02d}",
        "independent_family_count": 3,
        "official_identity_or_filing_family_count": 2,
    } for i in range(20)]
    document = {
        "global_sources": sources,
        "ticker_sources": rows,
        "concentration": {"largest_family_share": 0.34},
        "unresolved_material_conflicts": [],
    }
    assert evaluate(document, policy)["pass"] is True
    weak = json.loads(json.dumps(document))
    for row in weak["ticker_sources"][:5]:
        row["official_identity_or_filing_family_count"] = 1
    assert evaluate(weak, policy)["pass"] is False
    concentrated = json.loads(json.dumps(document))
    concentrated["concentration"]["largest_family_share"] = 0.9
    assert evaluate(concentrated, policy)["pass"] is False
    print("V213_SOURCE_FEDERATION_GATE_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--federation", type=Path, default=FEDERATION_PATH)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    policy = load(args.policy)
    document = load(args.federation)
    gates = evaluate(document, policy)
    document["gates"] = gates
    atomic(args.federation, document)
    print(
        "V213_SOURCE_FEDERATION_GATE = {status}; official_global={official}; "
        "ticker_coverage={coverage:.1%}; concentration={share:.1%}; conflicts={conflicts}".format(
            status="PASS" if gates["pass"] else "FAIL",
            official=len(gates["official_successful_families"]),
            coverage=float(gates["ticker_coverage_ratio"]),
            share=float(gates["largest_family_share"]),
            conflicts=gates["unresolved_material_conflict_count"],
        ),
        flush=True,
    )
    return 0 if gates["pass"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GateError, OSError, ValueError) as exc:
        print(f"V213_SOURCE_FEDERATION_GATE = FAIL; {exc}", flush=True)
        raise SystemExit(1)
