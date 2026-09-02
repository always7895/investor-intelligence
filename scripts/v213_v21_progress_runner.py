#!/usr/bin/env python3
"""Progress wrapper and v2.1.3 source-policy bridge for the candidate engine.

The underlying v2.1.0 engine still provides the deterministic candidate seed and
SEC extraction. Its proxy-heavy score is never published directly: later
v2.1.3 stages build a live source federation and replace the score with the
claim-gated diversified System operationalization.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests
import v21_serenity_top20 as engine

REQUIRED_LIVE_SOURCES = {
    "sec_edgar",
    "world_bank_indicators",
    "bls_public_data",
    "ecb_sdmx",
    "gleif_lei",
    "nasdaq_symbol_directory",
}


def validate_v213_policy() -> tuple[dict[str, Any], dict[str, Any]]:
    policy = engine.load_object(engine.POLICY_PATH)
    activation = engine.load_object(engine.ACTIVATION_PATH)
    weights = policy.get("factor_weights")
    expected = {
        "demand_wave", "chokepoint", "pricing_power", "replacement_friction",
        "tam_capture", "valuation_expectations", "evidence_quality",
    }
    if not isinstance(weights, dict) or set(weights) != expected or sum(int(v) for v in weights.values()) != 100:
        raise engine.PipelineError("System operationalization policy must contain seven factors totaling 100")
    if policy.get("official_serenity_formula_claimed") is not False:
        raise engine.PipelineError("The project must not claim an official Serenity formula")
    if policy.get("methodology") != "system-operationalization-v2.1.3-diversified":
        raise engine.PipelineError("v2.1.3 diversified operationalization policy is not active")
    if (
        activation.get("automatic_activation") is not False
        or activation.get("free_only") is not True
        or activation.get("public_data_only") is not True
    ):
        raise engine.PipelineError("Source activation policy is not fail-closed")
    selected = activation.get("selected_sources")
    if not isinstance(selected, dict) or set(selected) != REQUIRED_LIVE_SOURCES:
        raise engine.PipelineError(
            "Reviewed v2.1.3 live federation must include SEC, World Bank, BLS, ECB, GLEIF and Nasdaq symbol identity"
        )
    for source_id, row in selected.items():
        if (
            not isinstance(row, dict)
            or row.get("runtime_enabled") is not True
            or not str(row.get("rights_status") or "").startswith("reviewed_public_access")
            or row.get("adapter_status") != "adapter_reviewed"
            or not isinstance(row.get("gates"), dict)
            or not all(row["gates"].values())
        ):
            raise engine.PipelineError(f"Incomplete reviewed activation: {source_id}")
    yahoo = activation.get("discovery_only_sources", {}).get("yahoo_finance_public_unofficial")
    if (
        not isinstance(yahoo, dict)
        or yahoo.get("runtime_enabled") is not True
        or yahoo.get("authoritative") is not False
        or yahoo.get("raw_payload_redistribution") is not False
    ):
        raise engine.PipelineError("Yahoo/yfinance must remain T3 non-authoritative observation")
    _manifest, sources, _warnings = engine.load_catalog()
    if len(sources) != int(policy["required_catalog_count"]):
        raise engine.PipelineError(
            f"Catalog count changed: {len(sources)} != {policy['required_catalog_count']}"
        )
    by_id = {source.id for source in sources}
    if not REQUIRED_LIVE_SOURCES.issubset(by_id):
        raise engine.PipelineError("Live federation references source IDs outside the reviewed catalog")
    return policy, activation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()

    original_companyfacts = engine.sec_companyfacts
    original_validate = engine.validate_policy
    counter = {"value": 0}

    def progress_companyfacts(candidate, policy, http, headers):
        counter["value"] += 1
        limit = int(policy.get("sec_candidate_limit", 50))
        ticker = str(candidate.get("ticker") or "?")
        print(
            f"II_PROGRESS Top20 SEC companyfacts {counter['value']}/{limit} | {ticker}",
            flush=True,
        )
        return original_companyfacts(candidate, policy, http, headers)

    engine.sec_companyfacts = progress_companyfacts
    engine.validate_policy = validate_v213_policy
    try:
        print("II_PROGRESS Top20 candidate discovery starting; Yahoo is T3 seed only", flush=True)
        result = engine.run(synthetic=args.synthetic)
        print("II_PROGRESS legacy candidate score produced; diversified postprocessor required", flush=True)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except (engine.PipelineError, OSError, ValueError, requests.RequestException) as exc:
        print(f"V2.1 candidate engine failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        engine.sec_companyfacts = original_companyfacts
        engine.validate_policy = original_validate


if __name__ == "__main__":
    raise SystemExit(main())
