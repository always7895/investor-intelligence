#!/usr/bin/env python3
"""End-to-end contract test for provisional-to-diversified Top20 promotion.

The provisional shortlist must never pass either the legacy v2.1 snapshot
boundary or the v2.1.3 diversified boundary. Only rows transformed by the live
source-federated System operationalization may be signed for promotion.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


operationalization = load_module(
    "ii_v213_apply_diversified_operationalization",
    SCRIPT_DIR / "v213_apply_diversified_operationalization.py",
)
snapshot = load_module(
    "ii_v213_build_v21_public_snapshot",
    SCRIPT_DIR / "v213_build_v21_public_snapshot.py",
)
base_snapshot = snapshot.base


def provisional_row(index: int, generated: str) -> dict[str, Any]:
    ticker = f"T{index:02d}"
    return {
        "ticker": ticker,
        "name": f"Synthetic {ticker}",
        "serenity_score": 8.0,
        "serenity_raw_score": 10.0,
        "risk_penalty": 2.0,
        "data_quality": 0.4,
        "rating": "PROVISIONAL",
        "category": "Synthetic",
        "serenity_factors": {
            "demand_wave": 0.0,
            "chokepoint": 0.0,
            "pricing_power": 0.0,
            "replacement_friction": 0.0,
            "tam_capture": 4.0,
            "valuation_expectations": 2.0,
            "evidence_quality": 4.0,
        },
        "risk_flags": ["provisional_not_publicly_promotable"],
        "aschenbrenner_overlay": {
            "domain": "C",
            "fit_score": 20,
            "included_in_serenity_score": False,
            "attribution": "system_operationalization_not_aschenbrenner_stock_score",
        },
        "evidence": [{
            "source_id": "sec_edgar",
            "tier": "T0",
            "claim_type": "xbrl_fact",
            "title": f"Synthetic SEC fact for {ticker}",
            "url": f"https://www.sec.gov/Archives/edgar/data/{1000000 + index}/synthetic.htm",
            "as_of": generated,
        }],
        "evidence_count": 1,
        "source_count": 1,
        "scoring_version": "system-operationalization-v2.1.3-safe-preselection",
        "line_public_eligible": True,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
        "rank": index + 1,
        "generated_at": generated,
        "as_of": generated,
    }


def reports(generated: str) -> tuple[dict[str, Any], dict[str, Any]]:
    five: list[dict[str, Any]] = []
    seven: list[dict[str, Any]] = []
    for index in range(20):
        ticker = f"T{index:02d}"
        common = {
            "rank": index + 1,
            "ticker": ticker,
            "long_term_return_pct": 10.0 + index,
            "short_term_return_pct": 2.0 + index,
            "industry": "半導體",
            "profit_summary": "獲利；營收年增 +40.0%；營益率 20.0%；淨利率 12.0%",
            "long_term_window": "2y_cagr",
            "short_term_window": "6m_price_return",
            "market_source": "yfinance",
            "profit_source": "sec_edgar",
            "retrieved_at": generated,
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        }
        five.append({"schema_version": 1, **common})
        seven.append({
            "schema_version": 2,
            **common,
            "current_orders": "未揭露（無可靠公開訂單數字）",
            "future_orders_estimate": "無可靠公開預估",
            "orders_as_of": "",
            "orders_confidence": "UNAVAILABLE",
            "current_order_source_urls": [],
            "future_order_source_urls": [],
            "numeric_total_order_estimate_prohibited": True,
        })
    return (
        {"product_version": "2.1.2", "records": five},
        {"product_version": "2.1.3", "records": seven},
    )


def federation(generated: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index in range(20):
        ticker = f"T{index:02d}"
        rows.append({
            "rank": index + 1,
            "ticker": ticker,
            "independent_families": ["us_sec", "nasdaq", "yahoo_finance"],
            "official_identity_or_filing_families": ["us_sec", "nasdaq"],
            "market_observation_families": ["yahoo_finance"],
            "issuer_financial_claim_family_count": 1,
            "evidence_additions": [{
                "source_id": "nasdaq_symbol_directory",
                "tier": "T2",
                "claim_type": "regulated_listing_identity",
                "title": f"Synthetic regulated listing identity for {ticker}",
                "url": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
                "as_of": generated,
            }],
        })
    return {
        "generated_at": generated,
        "ticker_sources": rows,
        "unresolved_material_conflicts": [],
        "gates": {
            "pass": True,
            "successful_families": [
                "ecb", "nasdaq", "us_bls", "us_sec", "world_bank",
            ],
            "official_successful_families": [
                "ecb", "nasdaq", "us_bls", "us_sec", "world_bank",
            ],
            "missing_required_families": [],
            "ticker_coverage_ratio": 1.0,
            "largest_family_share": 0.3333,
            "unresolved_material_conflict_count": 0,
        },
    }


def source_plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "catalog_count": 101,
        "automatic_activation": False,
        "owner_watchlist_inherited": False,
        "provider_scope": "public_only",
        "line_public_eligible": True,
        "inventory": {
            "source_count": 101,
            "runtime_enabled_count": 0,
        },
    }


def expect_rejected(function, rows: list[dict[str, Any]], label: str) -> None:
    try:
        function(rows)
    except base_snapshot.SnapshotError:
        return
    raise AssertionError(f"{label} unexpectedly accepted provisional rows")


def main() -> int:
    generated = "2026-09-02T00:00:00Z"
    provisional = [provisional_row(index, generated) for index in range(20)]
    five, seven = reports(generated)
    fed = federation(generated)
    standard = json.loads(
        (ROOT / "config" / "v213-serenity-evidence-standard-v3.json").read_text(
            encoding="utf-8-sig"
        )
    )

    expect_rejected(base_snapshot.validate_top20, provisional, "legacy snapshot")
    expect_rejected(snapshot.validate_top20, provisional, "diversified snapshot")

    final_rows, final_five, final_seven = operationalization.apply(
        provisional,
        five,
        seven,
        fed,
        standard,
    )
    validated = snapshot.validate_top20(final_rows)
    final_plan = operationalization.update_plan(source_plan(), fed)
    snapshot.validate_plan(final_plan)

    order = [row["ticker"] for row in validated]
    assert order == [row["ticker"] for row in final_five["records"]]
    assert order == [row["ticker"] for row in final_seven["records"]]
    assert all(
        row["scoring_version"]
        == "system-operationalization-v2.1.3-diversified"
        for row in validated
    )
    assert all(row["source_count"] >= 2 for row in validated)
    print(
        "V213_PROVISIONAL_TO_DIVERSIFIED_PIPELINE_SELF_TEST = PASS; "
        "provisional_promotion_blocked=true; diversified_snapshot_accepted=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
