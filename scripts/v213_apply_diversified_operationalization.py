#!/usr/bin/env python3
"""Apply v2.1.3 claim-scoped, multi-source System operationalization.

Legacy ``serenity_score`` and ``serenity_factors`` machine keys remain for API
compatibility only. The public label is System operationalization score. This
module does not claim an official Serenity formula, endorsement or reproduction
of a private process.

Evidence Standard v3 removes positive points that were previously created from
proxies or source availability:
* endpoint health and generic macro context do not create demand-wave points;
* keywords, sectors, margins and named customers do not create bottleneck points;
* margins alone do not create pricing-power or replacement-friction points;
* revenue growth alone contributes at most 40% of TAM-capture points;
* one market provider caps valuation at 25% of that factor;
* listing identity improves provenance but cannot corroborate revenue or orders;
* source-family and claim-scope weaknesses become explicit penalties/flags;
* conflicting material primary values fail closed in the upstream federation.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
TOP20_PATH = ROOT / "data" / "cache" / "top20_public_latest.json"
V212_PATH = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
V213_PATH = ROOT / "data" / "cache" / "v213_top20_report_public_latest.json"
FEDERATION_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
PLAN_PATH = ROOT / "data" / "cache" / "source_plan_public_latest.json"
REPORT_PATH = ROOT / "reports" / "public_briefing_latest.md"
STANDARD_PATH = ROOT / "config" / "v213-serenity-evidence-standard-v3.json"
SCORING_VERSION = "system-operationalization-v2.1.3-diversified"
EVIDENCE_STANDARD = "serenity-public-logic-evidence-standard-v3"
CATALOG_COUNT = 101


class OperationalizationError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperationalizationError(f"Invalid JSON: {path}") from exc


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    temporary.replace(path)


def finite(value: Any, fallback: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return fallback
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if math.isfinite(parsed) else fallback


def metric(text: Any, label: str) -> float | None:
    match = re.search(re.escape(label) + r"\s*([+-]?\d+(?:\.\d+)?)%", str(text or ""))
    return float(match.group(1)) if match else None


def report_map(document: Any, version: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not isinstance(document, dict) or document.get("product_version") != version:
        raise OperationalizationError(f"Expected report product_version={version}")
    rows = document.get("records")
    if not isinstance(rows, list) or len(rows) != 20:
        raise OperationalizationError(f"{version} report must contain exactly 20 rows")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise OperationalizationError(f"{version} report row must be an object")
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or ticker in result:
            raise OperationalizationError(f"{version} report ticker contract failed")
        result[ticker] = row
    return document, result


def reorder_report(document: dict[str, Any], order: list[str]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    mapping = {
        str(row.get("ticker") or "").upper(): dict(row)
        for row in result.get("records", [])
        if isinstance(row, dict)
    }
    if set(mapping) != set(order):
        raise OperationalizationError("Report membership does not match final Top20")
    rows: list[dict[str, Any]] = []
    for rank, ticker in enumerate(order, 1):
        row = mapping[ticker]
        row["rank"] = rank
        rows.append(row)
    result["records"] = rows
    return result


def normalized_evidence(rows: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    if not isinstance(rows, list):
        return result
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = {
            "source_id": str(raw.get("source_id") or ""),
            "tier": str(raw.get("tier") or ""),
            "claim_type": str(raw.get("claim_type") or ""),
            "title": str(raw.get("title") or "")[:240],
            "url": str(raw.get("url") or ""),
            "as_of": str(raw.get("as_of") or ""),
        }
        identity = (item["source_id"], item["url"], item["claim_type"])
        if not item["source_id"] or not item["url"] or identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def yahoo_evidence(ticker: str, five: Mapping[str, Any], market_families: set[str]) -> list[dict[str, Any]]:
    if "yahoo_finance" not in market_families:
        return []
    return [{
        "source_id": "yahoo_finance_public_unofficial",
        "tier": "T3",
        "claim_type": "public_market_observation",
        "title": f"Yahoo/yfinance adjusted-close observation for {ticker}",
        "url": f"https://finance.yahoo.com/quote/{ticker}",
        "as_of": str(five.get("retrieved_at") or ""),
    }]


def tam_capture_points(revenue_growth_pct: float | None, order_supported: bool) -> float:
    # Revenue alone is capped at 6/15 = 40%; evidence-bound order visibility may
    # add two provisional points but is not treated as proof of total TAM/share.
    if revenue_growth_pct is None or revenue_growth_pct <= 0:
        revenue = 0.0
    elif revenue_growth_pct < 15:
        revenue = 2.0
    elif revenue_growth_pct < 35:
        revenue = 4.0
    else:
        revenue = 6.0
    return min(8.0, revenue + (2.0 if order_supported else 0.0))


def evidence_quality_points(
    families: set[str],
    official_boundary_families: set[str],
    market_families: set[str],
    issuer_financial_family_count: int,
    order_supported: bool,
    required_global_sources_healthy: bool,
) -> float:
    # Claim-scope separation is deliberate: Nasdaq/GLEIF improve identity
    # provenance; official macro families improve context availability; neither
    # is counted as independent issuer-financial corroboration.
    points = 0.0
    if "us_sec" in families:
        points += 2.0
    if "nasdaq" in official_boundary_families:
        points += 2.0
    if "gleif" in official_boundary_families:
        points += 1.0
    if market_families:
        points += 1.0
    if order_supported:
        points += 1.0
    if required_global_sources_healthy:
        points += 1.0
    if issuer_financial_family_count >= 2:
        points += 4.0
    return min(15.0, points)


def data_quality_score(
    official_boundary_family_count: int,
    issuer_financial_family_count: int,
    market_family_count: int,
    order_supported: bool,
    required_global_sources_healthy: bool,
) -> float:
    issuer = min(1.0, issuer_financial_family_count / 2.0)
    boundary = min(1.0, official_boundary_family_count / 2.0)
    market = 1.0 if market_family_count >= 2 else 0.35 if market_family_count == 1 else 0.0
    return round(
        0.45 * issuer
        + 0.20 * boundary
        + 0.10 * market
        + 0.15 * float(order_supported)
        + 0.10 * float(required_global_sources_healthy),
        4,
    )


def rating(score: float) -> str:
    if score >= 55:
        return "A"
    if score >= 40:
        return "B"
    if score >= 25:
        return "C"
    return "D"


def apply(
    top20: list[dict[str, Any]],
    v212: dict[str, Any],
    v213: dict[str, Any],
    federation: dict[str, Any],
    standard: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if len(top20) != 20:
        raise OperationalizationError("Top20 must contain exactly 20 rows")
    gates = federation.get("gates")
    if not isinstance(gates, dict) or gates.get("pass") is not True:
        raise OperationalizationError("Live source federation gates did not pass")
    if federation.get("unresolved_material_conflicts"):
        raise OperationalizationError("Unresolved material source conflicts are fail-closed")
    if standard.get("standard_id") != EVIDENCE_STANDARD:
        raise OperationalizationError("Serenity public-logic evidence standard v3 is not active")

    _, five_by_ticker = report_map(v212, "2.1.2")
    _, seven_by_ticker = report_map(v213, "2.1.3")
    federation_rows = federation.get("ticker_sources")
    if not isinstance(federation_rows, list) or len(federation_rows) != 20:
        raise OperationalizationError("Source federation requires exactly 20 ticker rows")
    fed_by_ticker = {
        str(row.get("ticker") or "").upper(): row
        for row in federation_rows
        if isinstance(row, dict)
    }
    required_global_sources_healthy = not gates.get("missing_required_families")
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    results: list[dict[str, Any]] = []

    for raw in top20:
        ticker = str(raw.get("ticker") or "").upper()
        five = five_by_ticker.get(ticker)
        seven = seven_by_ticker.get(ticker)
        fed = fed_by_ticker.get(ticker)
        if not five or not seven or not fed:
            raise OperationalizationError(f"Missing report/federation row: {ticker}")

        summary = str(five.get("profit_summary") or "")
        revenue = metric(summary, "營收年增")
        net = metric(summary, "淨利率")
        order_supported = str(seven.get("orders_confidence") or "") not in {"", "UNAVAILABLE"}
        families = {str(value) for value in fed.get("independent_families") or [] if str(value)}
        official_boundary = {
            str(value)
            for value in fed.get("official_identity_or_filing_families") or []
            if str(value)
        }
        market_families = {
            str(value)
            for value in fed.get("market_observation_families") or []
            if str(value)
        }
        issuer_financial_count = int(fed.get("issuer_financial_claim_family_count") or 0)

        old_factors = raw.get("serenity_factors") if isinstance(raw.get("serenity_factors"), dict) else {}
        old_valuation = max(0.0, finite(old_factors.get("valuation_expectations")))
        valuation = old_valuation if len(market_families) >= 2 else min(old_valuation, 3.75)
        factors = {
            "demand_wave": 0.0,
            "chokepoint": 0.0,
            "pricing_power": 0.0,
            "replacement_friction": 0.0,
            "tam_capture": round(tam_capture_points(revenue, order_supported), 2),
            "valuation_expectations": round(min(15.0, valuation), 2),
            "evidence_quality": round(
                evidence_quality_points(
                    families,
                    official_boundary,
                    market_families,
                    issuer_financial_count,
                    order_supported,
                    required_global_sources_healthy,
                ),
                2,
            ),
        }

        risks = {
            "architecture_and_demand_wave_unproven_without_claim_specific_evidence",
            "bottleneck_unproven_without_evidence_bound_graph",
            "pricing_power_unproven_without_contract_or_price_evidence",
            "replacement_friction_unproven_without_switching_or_qualification_evidence",
            "global_macro_sources_are_context_not_company_corroboration",
        }
        penalty = 0.0
        if len(market_families) < 2:
            risks.add("single_market_provider_degraded")
            penalty += 2.0
        if issuer_financial_count < 2:
            risks.add("issuer_financial_claim_has_single_primary_family")
            penalty += 3.0
        if len(families) < int(standard["claim_thresholds"]["dependency_or_bottleneck"]["minimum_primary_or_corroborating_families"]):
            risks.add("independent_source_family_coverage_below_two")
            penalty += 3.0
        if not order_supported:
            risks.add("order_visibility_unavailable")
            penalty += 1.0
        if revenue is not None and revenue < 0:
            risks.add("negative_revenue_growth")
            penalty += 4.0
        if net is not None and net < 0:
            risks.add("negative_net_margin")
            penalty += 4.0

        evidence = normalized_evidence(
            list(raw.get("evidence") or [])
            + list(fed.get("evidence_additions") or [])
            + yahoo_evidence(ticker, five, market_families)
        )
        source_ids = {item["source_id"] for item in evidence}
        raw_score = sum(float(value) for value in factors.values())
        score = max(0.0, min(100.0, raw_score - penalty))

        result = copy.deepcopy(raw)
        result.update({
            "ticker": ticker,
            "serenity_score": round(score, 2),
            "serenity_raw_score": round(raw_score, 2),
            "risk_penalty": round(penalty, 2),
            "data_quality": data_quality_score(
                len(official_boundary),
                issuer_financial_count,
                len(market_families),
                order_supported,
                required_global_sources_healthy,
            ),
            "rating": rating(score),
            "serenity_factors": factors,
            "risk_flags": sorted(risks),
            "evidence": evidence,
            "evidence_count": len(evidence),
            "source_count": len(source_ids),
            "scoring_version": SCORING_VERSION,
            "generated_at": generated,
            "as_of": generated,
        })
        results.append(result)

    results.sort(
        key=lambda item: (
            -float(item["serenity_score"]),
            -float(item["data_quality"]),
            str(item["ticker"]),
        )
    )
    for rank, item in enumerate(results, 1):
        item["rank"] = rank
    order = [str(item["ticker"]) for item in results]
    return results, reorder_report(v212, order), reorder_report(v213, order)


def update_plan(plan: dict[str, Any], federation: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(plan)
    result["catalog_count"] = CATALOG_COUNT
    inventory = result.get("inventory")
    if not isinstance(inventory, dict):
        inventory = {}
        result["inventory"] = inventory
    inventory["source_count"] = CATALOG_COUNT
    gates = federation["gates"]
    result["live_source_federation"] = {
        "schema_version": 1,
        "generated_at": federation["generated_at"],
        "successful_families": gates["successful_families"],
        "official_successful_families": gates["official_successful_families"],
        "ticker_coverage_ratio": gates["ticker_coverage_ratio"],
        "largest_family_share": gates["largest_family_share"],
        "unresolved_material_conflict_count": gates["unresolved_material_conflict_count"],
        "yahoo_authoritative": False,
        "catalog_source_count_is_not_live_use": True,
        "claim_scope_separation_enforced": True,
        "publisher_family_deduplication_enforced": True,
    }
    result["scoring_methodology"] = {
        "machine_key_compatibility": "legacy serenity_* keys retained",
        "display_label": "System operationalization score",
        "scoring_version": SCORING_VERSION,
        "evidence_standard": EVIDENCE_STANDARD,
        "official_serenity_formula_claimed": False,
        "private_process_reproduction_claimed": False,
        "architecture_source_availability_is_not_positive_demand_signal": True,
        "keyword_only_chokepoint_points": 0,
        "margin_only_pricing_power_points": 0,
        "gross_margin_only_replacement_friction_points": 0,
        "revenue_only_tam_capture_cap_fraction": 0.4,
        "single_market_provider_valuation_cap_fraction": 0.25,
        "issuer_financial_single_family_penalty": 3,
    }
    return result


def markdown_report(rows: list[dict[str, Any]], federation: Mapping[str, Any]) -> str:
    gates = federation["gates"]
    lines = [
        "# Investor Intelligence v2.1.3 Public Top 20",
        "",
        "> System operationalization score; not an official Serenity formula, ranking or endorsement.",
        "> Serenity public-logic high-fidelity reconstruction keeps source view, system score and model inference separate.",
        "",
        f"Evidence standard: {EVIDENCE_STANDARD}",
        f"Live source families used: {', '.join(gates['successful_families'])}",
        f"Official source families used: {', '.join(gates['official_successful_families'])}",
        f"Ticker multi-source boundary coverage: {float(gates['ticker_coverage_ratio']):.0%}",
        f"Largest publisher-family share: {float(gates['largest_family_share']):.0%}",
        "Yahoo/yfinance is T3 observation only and cannot independently prove a company, dependency, order or bottleneck claim.",
        "",
        "| Rank | Ticker | System score | Data quality | Rating |",
        "|---:|---|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['rank']} | {row['ticker']} | {row['serenity_score']:.2f} | {float(row['data_quality']):.0%} | {row['rating']} |"
        )
    lines.extend([
        "",
        "## Evidence Standard v3 guardrails",
        "",
        "- Endpoint availability and macro context do not create positive company points.",
        "- Listing/legal identity improves provenance but does not corroborate revenue, orders or bottlenecks.",
        "- Keyword membership, sector, margin or a named customer cannot create bottleneck points.",
        "- Margin alone cannot create pricing-power or replacement-friction points.",
        "- Revenue growth alone contributes at most 40% of TAM-capture points.",
        "- A single market-data family caps valuation confidence.",
        "- Conflicting material primary values fail closed rather than being averaged.",
        "- The reviewed 101-source catalog is inventory; only the live-source list above was used in this run.",
        "",
    ])
    return "\n".join(lines)


def self_test() -> None:
    generated = "2026-09-02T00:00:00Z"
    top20: list[dict[str, Any]] = []
    five_rows: list[dict[str, Any]] = []
    seven_rows: list[dict[str, Any]] = []
    fed_rows: list[dict[str, Any]] = []
    for index in range(20):
        ticker = f"T{index:02d}"
        top20.append({
            "ticker": ticker,
            "name": ticker,
            "serenity_score": 20,
            "serenity_raw_score": 20,
            "risk_penalty": 0,
            "data_quality": 0.5,
            "rating": "PROVISIONAL",
            "category": "Synthetic",
            "serenity_factors": {
                "demand_wave": 0,
                "chokepoint": 0,
                "pricing_power": 0,
                "replacement_friction": 0,
                "tam_capture": 6,
                "valuation_expectations": 3.75,
                "evidence_quality": 4,
            },
            "risk_flags": [],
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
                "title": ticker,
                "url": f"https://www.sec.gov/{ticker}",
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
        })
        common = {
            "rank": index + 1,
            "ticker": ticker,
            "long_term_return_pct": 1.0,
            "short_term_return_pct": 1.0,
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
        five_rows.append({"schema_version": 1, **common})
        seven_rows.append({
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
        fed_rows.append({
            "ticker": ticker,
            "independent_families": ["us_sec", "nasdaq", "yahoo_finance"],
            "official_identity_or_filing_families": ["us_sec", "nasdaq"],
            "market_observation_families": ["yahoo_finance"],
            "issuer_financial_claim_family_count": 1,
            "evidence_additions": [{
                "source_id": "nasdaq_symbol_directory",
                "tier": "T2",
                "claim_type": "regulated_listing_identity",
                "title": ticker,
                "url": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
                "as_of": generated,
            }],
        })
    v212 = {"product_version": "2.1.2", "records": five_rows}
    v213 = {"product_version": "2.1.3", "records": seven_rows}
    federation = {
        "generated_at": generated,
        "ticker_sources": fed_rows,
        "unresolved_material_conflicts": [],
        "gates": {
            "pass": True,
            "successful_families": ["ecb", "nasdaq", "us_bls", "us_sec", "world_bank"],
            "official_successful_families": ["ecb", "nasdaq", "us_bls", "us_sec", "world_bank"],
            "missing_required_families": [],
            "ticker_coverage_ratio": 1.0,
            "largest_family_share": 0.3333,
            "unresolved_material_conflict_count": 0,
        },
    }
    standard = load_json(STANDARD_PATH)
    rows, reordered_v212, reordered_v213 = apply(top20, v212, v213, federation, standard)
    assert len(rows) == 20
    assert all(row["serenity_factors"]["demand_wave"] == 0 for row in rows)
    assert all(row["serenity_factors"]["chokepoint"] == 0 for row in rows)
    assert all(row["serenity_factors"]["pricing_power"] == 0 for row in rows)
    assert all(row["serenity_factors"]["replacement_friction"] == 0 for row in rows)
    assert all(row["serenity_factors"]["tam_capture"] <= 8 for row in rows)
    assert all(row["serenity_factors"]["valuation_expectations"] <= 3.75 for row in rows)
    assert all(row["data_quality"] < 0.7 for row in rows)
    assert all(row["scoring_version"] == SCORING_VERSION for row in rows)
    assert all("yahoo_finance_public_unofficial" in {e["source_id"] for e in row["evidence"]} for row in rows)
    assert [r["ticker"] for r in reordered_v212["records"]] == [r["ticker"] for r in rows]
    assert [r["ticker"] for r in reordered_v213["records"]] == [r["ticker"] for r in rows]
    print("V213_DIVERSIFIED_OPERATIONALIZATION_SELF_TEST = PASS; evidence_standard=v3")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top20", type=Path, default=TOP20_PATH)
    parser.add_argument("--v212", type=Path, default=V212_PATH)
    parser.add_argument("--v213", type=Path, default=V213_PATH)
    parser.add_argument("--federation", type=Path, default=FEDERATION_PATH)
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    top20 = load_json(args.top20)
    v212 = load_json(args.v212)
    v213 = load_json(args.v213)
    federation = load_json(args.federation)
    standard = load_json(STANDARD_PATH)
    if not isinstance(top20, list):
        raise OperationalizationError("Top20 root must be an array")
    rows, v212_new, v213_new = apply(top20, v212, v213, federation, standard)
    plan = update_plan(load_json(args.plan), federation)
    atomic_json(args.top20, rows)
    atomic_json(args.v212, v212_new)
    atomic_json(args.v213, v213_new)
    atomic_json(args.plan, plan)
    atomic_text(args.report, markdown_report(rows, federation) + "\n")
    print(
        f"V213_DIVERSIFIED_OPERATIONALIZATION = PASS; rows=20; top={rows[0]['ticker']}; "
        f"scoring_version={SCORING_VERSION}; evidence_standard={EVIDENCE_STANDARD}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OperationalizationError, OSError, ValueError) as exc:
        print(f"V213_DIVERSIFIED_OPERATIONALIZATION = FAIL; {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
