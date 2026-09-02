#!/usr/bin/env python3
"""Build the Hotfix5 atomic activation bundle.

The live source federation is collected before diversified scoring, while final
Top20 ranking is established by the diversified operationalization step. This
wrapper preserves every federation row and its evidence but reorders the
``ticker_sources`` array to the final Top20 order before the canonical bundle
validator runs. It also assigns a fresh cryptographically random transaction ID
for every build, preventing a later activation attempt from reusing a finalized
rollback handle.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import secrets
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
CORE_PATH = SCRIPT_DIR / "build_v213_activation_bundle.py"
TRANSACTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def load_core() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "investor_intelligence_v213_activation_bundle_core",
        CORE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load activation-bundle core: {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = load_core()


def final_order(envelope: Mapping[str, Any]) -> list[str]:
    payloads = envelope.get("payloads")
    if not isinstance(payloads, Mapping):
        raise core.ActivationBundleError("Diversified envelope payloads are missing")
    try:
        rows = json.loads(str(payloads.get("top20_json") or ""))
    except json.JSONDecodeError as exc:
        raise core.ActivationBundleError("Diversified Top20 is invalid JSON") from exc
    return core.ordered_tickers(rows, "Diversified Top20")


def reorder_federation(
    federation: Mapping[str, Any],
    order: list[str],
) -> dict[str, Any]:
    result = copy.deepcopy(dict(federation))
    raw_rows = result.get("ticker_sources")
    if not isinstance(raw_rows, list) or len(raw_rows) != 20:
        raise core.ActivationBundleError("Source federation must contain exactly 20 ticker rows")
    mapping: dict[str, dict[str, Any]] = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise core.ActivationBundleError("Source federation row must be an object")
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not ticker or ticker in mapping:
            raise core.ActivationBundleError("Source federation ticker membership is invalid")
        mapping[ticker] = dict(raw)
    if set(mapping) != set(order):
        added = sorted(set(mapping) - set(order))
        missing = sorted(set(order) - set(mapping))
        raise core.ActivationBundleError(
            "Source federation membership does not match final Top20; "
            f"extra={','.join(added) or '-'}; missing={','.join(missing) or '-'}"
        )
    rows: list[dict[str, Any]] = []
    for rank, ticker in enumerate(order, 1):
        row = mapping[ticker]
        row["rank"] = rank
        rows.append(row)
    result["ticker_sources"] = rows
    return result


def build_bundle(
    envelope: Mapping[str, Any],
    v212: Mapping[str, Any],
    v213: Mapping[str, Any],
    federation: Mapping[str, Any],
    source_audit: Mapping[str, Any],
) -> dict[str, Any]:
    order = final_order(envelope)
    normalized_federation = reorder_federation(federation, order)
    bundle = core.build_bundle(
        envelope,
        v212,
        v213,
        normalized_federation,
        source_audit,
    )
    bundle["transaction_id"] = secrets.token_hex(16)
    if not TRANSACTION_ID_RE.fullmatch(str(bundle["transaction_id"])):
        raise core.ActivationBundleError("Generated activation transaction ID is invalid")
    return bundle


def self_test() -> None:
    generated = "2026-09-02T00:00:00Z"
    run_id = "20260902T000000Z-123456789abc"
    rows = [
        {
            "rank": index + 1,
            "ticker": f"T{index:02d}",
            "scoring_version": core.SCORING_VERSION,
        }
        for index in range(20)
    ]
    reversed_federation_rows = [
        {"rank": index + 1, "ticker": row["ticker"]}
        for index, row in enumerate(reversed(rows))
    ]
    plan = {
        "catalog_count": 101,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }
    base_payloads = {
        "top20_json": core.canonical_json(rows),
        "source_plan_json": core.canonical_json(plan),
        "report_text": "x",
    }
    import hashlib

    envelope = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": generated,
        "public_data_as_of": generated,
        "payloads": base_payloads,
        "sha256": {
            name: hashlib.sha256(body.encode("utf-8")).hexdigest()
            for name, body in base_payloads.items()
        },
    }
    v212 = {"product_version": "2.1.2", "records": rows}
    v213 = {"product_version": "2.1.3", "records": rows}
    federation = {
        "schema_version": 1,
        "product_version": "2.1.3",
        "generated_at": generated,
        "ticker_sources": reversed_federation_rows,
        "gates": {"pass": True, "unresolved_material_conflict_count": 0},
    }
    source = {
        "schema_version": 3,
        "product_version": "2.1.3",
        "generated_at": generated,
        "status": "PASS",
        "violations": [],
        "blocking_violations": [],
        "portfolio": {
            "claim_primary_coverage_ratio": 1.0,
            "claim_source_families": 2,
            "claim_source_domains": 2,
            "maximum_single_family_share": 0.5,
            "market_conflict_ticker_count": 0,
        },
        "records": rows,
    }
    first = build_bundle(envelope, v212, v213, federation, source)
    second = build_bundle(envelope, v212, v213, federation, source)
    normalized = json.loads(first["payloads"]["source_federation_json"])
    assert [row["ticker"] for row in normalized["ticker_sources"]] == [row["ticker"] for row in rows]
    assert [row["rank"] for row in normalized["ticker_sources"]] == list(range(1, 21))
    assert first["run_id"] == second["run_id"] == run_id
    assert first["transaction_id"] != second["transaction_id"]
    assert TRANSACTION_ID_RE.fullmatch(first["transaction_id"])
    print(
        "V213_ACTIVATION_BUNDLE_V2_SELF_TEST = PASS; "
        "federation_reordered=true; unique_transaction_id=true"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v21-envelope", type=Path, default=core.V21_ENVELOPE_PATH)
    parser.add_argument("--v212-report", type=Path, default=core.V212_REPORT_PATH)
    parser.add_argument("--v213-report", type=Path, default=core.V213_REPORT_PATH)
    parser.add_argument("--source-federation", type=Path, default=core.FEDERATION_PATH)
    parser.add_argument("--source-independence", type=Path, default=core.SOURCE_AUDIT_PATH)
    parser.add_argument("--output", type=Path, default=core.OUTPUT_PATH)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    bundle = build_bundle(
        core.load_json(args.v21_envelope),
        core.load_json(args.v212_report),
        core.load_json(args.v213_report),
        core.load_json(args.source_federation),
        core.load_json(args.source_independence),
    )
    core.atomic_write(args.output, bundle)
    print(
        "V213_ACTIVATION_BUNDLE_V2 = PASS; "
        f"run_id={bundle['run_id']}; transaction_id={bundle['transaction_id']}; "
        f"payloads={len(bundle['payloads'])}; federation_order=final_top20",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (core.ActivationBundleError, OSError, ValueError) as exc:
        print(f"V213_ACTIVATION_BUNDLE_V2 = FAIL; {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
