#!/usr/bin/env python3
"""Replace proxy-heavy legacy ranking factors with evidence-bound v2.1.3 logic.

The historical machine keys ``serenity_score`` and ``serenity_factors`` remain
for backward compatibility. Their meaning is explicitly changed to a project
``System operationalization``; this module does not claim an official Serenity
formula or reproduction of a private process.

Key corrections:
* keywords and gross margins cannot prove a chokepoint;
* gross margins cannot prove replacement friction;
* revenue growth alone can contribute at most 40% of TAM-capture points;
* a single market provider caps valuation confidence;
* evidence quality is based on independent source families and claim coverage,
  not the number of rows returned by one filing host;
* unresolved material source conflicts fail closed.
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
        "w", encoding="utf-8", newline="\n", delete=False, dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp",
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp",
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


def demand_points(revenue_growth_pct: float | None, macro_healthy: bool) -> float:
    if revenue_growth_pct is None:
        base = 0.0
    elif revenue_growth_pct < 0:
        base = 0.0
    elif revenue_growth_pct < 10:
        base = 3.0
    elif revenue_growth_pct < 25:
        base = 6.0
    elif revenue_growth_pct < 50:
        base = 10.0
    elif revenue_growth_pct < 100:
        base = 12.0
    else:
        base = 13.0
    return min(15.0, base + (1.0 if macro_healthy and base > 0 else 0.0))


def pricing_points(operating_margin_pct: float | None, net_margin_pct: float | None) -> float:
    operating = operating_margin_pct if operating_margin_pct is not None else -999.0
    if operating >= 35:
        points = 10.0
    elif operating >= 20:
        points = 8.0
    elif operating >= 10:
        points = 5.0
    elif operating > 0:
        points = 2.0
    else:
        points = 0.0
    net = net_margin_pct if net_margin_pct is not None else -999.0
    if net >= 25:
        points += 3.0
    elif net >= 10:
        points += 2.0
    elif net > 0:
        points += 1.0
    return min(13.0, points)


def tam_points(revenue_growth_pct: float | None, order_supported: bool) -> float:
    # Revenue growth alone is capped at 6/15 (40%). Evidence-bound order
    # visibility can add up to three points, but it is not treated as TAM proof.
    if revenue_growth_pct is None or revenue_growth_pct <= 0:
        revenue = 0.0
    elif revenue_growth_pct < 15:
        revenue = 2.0
    elif revenue_growth_pct < 35:
        revenue = 4.0
    else:
        revenue = 6.0
    return min(9.0, revenue + (3.0 if order_supported else 0.0))


def evidence_points(families: set[str], official_families: set[str], required_sources_healthy: bool) -> float:
    count = len(families)
    if count <= 1:
        points = 2.0
    elif count == 2:
        points = 7.0
    elif count == 3:
        points = 11.0
    else:
        points = 13.0
    if len(official_families) >= 2:
        points += 1.0
    if required_sources_healthy:
        points += 1.0
    return min(15.0, points)


def rating(score: float) -> str:
    if score >= 65:
        return "S"
    if score >= 50:
        return "A"
    if score >= 35:
        return "B"
    return "C"


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
        if not item["source_id"] or identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def report_map(document: Any, version: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not isinstance(document, dict) or document.get("product_version") != version:
        raise OperationalizationError(f"Expected report product_version={version}")
    rows = document.get("records")
    if not isinstance(rows, list) or len(rows) != 20:
        raise OperationalizationError(f"{version} report must contain 20 rows")
    return document, {str(row.get("ticker") or "").upper(): row for row in rows if isinstance(row, dict)}


def reorder_report(document: dict[str, Any], order: list[str]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    mapping = {str(row.get("ticker") or "").upper(): dict(row) for row in result["records"]}
    if set(mapping) != set(order):
        raise OperationalizationError("Report membership does not match final Top20")
    rows: list[dict[str, Any]] = []
    for rank, ticker in enumerate(order, 1):
        row = mapping[ticker]
        row["rank"] = rank
        rows.append(row)
    result["records"] = rows
    return result


def apply(
    top20: list[dict[str, Any]],
    v212: dict[str, Any],
    v213: dict[str, Any],
    federation: dict[str, Any],
    standard: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if len(top20) != 20:
        raise OperationalizationError("Top20 must contain 20 rows")
    if federation.get("gates", {}).get("pass") is not True:
        raise OperationalizationError("Live source federation gates did not pass")
    if federation.get("unresolved_material_conflicts"):
        raise OperationalizationError("Unresolved material source conflicts are fail-closed")
    _, v212_by_ticker = report_map(v212, "2.1.2")
    _, v213_by_ticker = report_map(v213, "2.1.3")
    federation_rows = federation.get("ticker_sources")
    if not isinstance(federation_rows, list) or len(federation_rows) != 20:
        raise OperationalizationError("Source federation requires 20 ticker rows")
    fed_by_ticker = {str(row.get("ticker") or "").upper(): row for row in federation_rows if isinstance(row, dict)}

    successful_global = set(federation["gates"].get("successful_families") or [])
    required_sources_healthy = not federation["gates"].get("missing_required_families")
    macro_healthy = {"world_bank", "us_bls", "ecb"}.issubset(successful_global)
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    results: list[dict[str, Any]] = []

    for raw in top20:
        ticker = str(raw.get("ticker") or "").upper()
        five = v212_by_ticker.get(ticker)
        seven = v213_by_ticker.get(ticker)
        fed = fed_by_ticker.get(ticker)
        if not five or not seven or not fed:
            raise OperationalizationError(f"Missing report/federation row: {ticker}")

        summary = str(five.get("profit_summary") or "")
        revenue = metric(summary, "營收年增")
        operating = metric(summary, "營益率")
        net = metric(summary, "淨利率")
        order_supported = str(seven.get("orders_confidence") or "") not in {"", "UNAVAILABLE"}
        families = {str(value) for value in fed.get("independent_families") or [] if str(value)}
        official_families = {
            str(value) for value in fed.get("official_identity_or_filing_families") or [] if str(value)
        }
        market_families = {str(value) for value in fed.get("market_observation_families") or [] if str(value)}

        old_factors = raw.get("serenity_factors") if isinstance(raw.get("serenity_factors"), dict) else {}
        old_valuation = finite(old_factors.get("valuation_expectations"))
        valuation = old_valuation if len(market_families) >= 2 else min(old_valuation, 3.75)
        factors = {
            "demand_wave": round(demand_points(revenue, macro_healthy), 2),
            "chokepoint": 0.0,
            "pricing_power": round(pricing_points(operating, net), 2),
            "replacement_friction": 0.0,
            "tam_capture": round(tam_points(revenue, order_supported), 2),
            "valuation_expectations": round(max(0.0, min(15.0, valuation)), 2),
            "evidence_quality": round(evidence_points(families, official_families, required_sources_healthy), 2),
        }

        risks = {str(value) for value in raw.get("risk_flags") or [] if str(value)}
        risks.update({
            "bottleneck_unproven_without_evidence_bound_graph",
            "replacement_friction_unproven_without_switching_or_qualification_evidence",
        })
        source_penalty = 0.0
        if len(market_families) < 2:
            risks.add("single_market_provider_degraded")
            source_penalty += 2.0
        if len(families) < int(standard["claim_thresholds"]["dependency_or_bottleneck"]["minimum_primary_or_corroborating_families"]):
            risks.add("independent_source_family_coverage_below_two")
            source_penalty += 3.0
        if int(fed.get("issuer_financial_claim_family_count") or 0) < 2:
            risks.add("issuer_financial_claim_has_single_primary_family")
        if not order_supported:
            risks.add("order_visibility_unavailable")

        raw_score = sum(factors.values())
        old_penalty = max(0.0, finite(raw.get("risk_penalty")))
        penalty = min(30.0, old_penalty + source_penalty)
        score = max(0.0, min(100.0, raw_score - penalty))
        evidence = normalized_evidence(
            list(raw.get("evidence") or []) + list(fed.get("evidence_additions") or [])
        )
        source_ids = {item["source_id"] for item in evidence}
        official_coverage = min(1.0, len(official_families) / 3.0)
        family_coverage = min(1.0, len(families) / 4.0)
        data_quality = round(0.55 * official_coverage + 0.35 * family_coverage + 0.10 * float(required_sources_healthy), 4)

        result = copy.deepcopy(raw)
        result.update({
            "ticker": ticker,
            "serenity_score": round(score, 2),
            "serenity_raw_score": round(raw_score, 2),
            "risk_penalty": round(penalty, 2),
            "data_quality": data_quality,
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

    results.sort(key=lambda row: (-finite(row["serenity_score"]), -finite(row["data_quality"]), row["ticker"]))
    for rank, row in enumerate(results, 1):
        row["rank"] = rank
    order = [row["ticker"] for row in results]
    return results, reorder_report(v212, order), reorder_report(v213, order)


def update_plan(plan: dict[str, Any], federation: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(plan)
    result["catalog_count"] = 100
    inventory = result.get("inventory")
    if not isinstance(inventory, dict):
        inventory = {}
        result["inventory"] = inventory
    inventory["source_count"] = 100
    gates = federation["gates"]
    result["live_source_federation"] = {
        "schema_version": 1,
        "generated_at": federation["generated_at"],
        "successful_families": gates["successful_families"],
        "official_successful_families": gates["official_successful_families"],
        "ticker_coverage_ratio": gates["ticker_coverage_ratio"],
        "unresolved_material_conflict_count": gates["unresolved_material_conflict_count"],
        "yahoo_authoritative": False,
        "catalog_source_count_is_not_live_use": True,
    }
    result["scoring_methodology"] = {
        "machine_key_compatibility": "legacy serenity_* keys retained",
        "display_label": "System operationalization score",
        "scoring_version": SCORING_VERSION,
        "official_serenity_formula_claimed": False,
        "keyword_only_chokepoint_points": 0,
        "gross_margin_only_replacement_friction_points": 0,
        "single_market_provider_valuation_cap_fraction": 0.25,
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
        f"Live source families used: {', '.join(gates['successful_families'])}",
        f"Official source families used: {', '.join(gates['official_successful_families'])}",
        f"Ticker multi-source coverage: {float(gates['ticker_coverage_ratio']):.0%}",
        "Yahoo/yfinance is T3 observation only and cannot independently prove a company, dependency or bottleneck claim.",
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
        "## Methodology guardrails",
        "",
        "- Keyword membership, high gross margin or a named customer does not prove a chokepoint.",
        "- Gross margin alone does not prove replacement friction.",
        "- Revenue growth alone contributes at most 40% of TAM-capture points.",
        "- A single market-data family caps valuation confidence.",
        "- Conflicting primary material values fail closed rather than being averaged.",
        "- The reviewed source catalog is an inventory; only the live-source list above was used in this run.",
        "",
    ])
    return "\n".join(lines)


def self_test() -> None:
    generated = "2026-09-02T00:00:00Z"
    top20: list[dict[str, Any]] = []
    v212_rows: list[dict[str, Any]] = []
    v213_rows: list[dict[str, Any]] = []
    fed_rows: list[dict[str, Any]] = []
    for index in range(20):
        ticker = f"T{index:02d}"
        top20.append({
            "ticker": ticker, "name": ticker, "serenity_score": 90 - index,
            "serenity_raw_score": 90 - index, "risk_penalty": 0, "data_quality": 0.5,
            "rating": "S", "category": "Synthetic",
            "serenity_factors": {
                "demand_wave": 15, "chokepoint": 15, "pricing_power": 15,
                "replacement_friction": 10, "tam_capture": 15,
                "valuation_expectations": 15, "evidence_quality": 15,
            },
            "risk_flags": [],
            "aschenbrenner_overlay": {
                "domain": "C", "fit_score": 20, "included_in_serenity_score": False,
                "attribution": "system_operationalization_not_aschenbrenner_stock_score",
            },
            "evidence": [{
                "source_id": "sec_edgar", "tier": "T0", "claim_type": "xbrl_fact",
                "title": ticker, "url": f"https://www.sec.gov/{ticker}", "as_of": generated,
            }],
            "evidence_count": 1, "source_count": 1,
            "scoring_version": "serenity-first-v2.1.0", "line_public_eligible": True,
            "provider_scope": "public_only", "owner_watchlist_inherited": False,
            "rank": index + 1, "generated_at": generated, "as_of": generated,
        })
        v212_rows.append({
            "schema_version": 1, "rank": index + 1, "ticker": ticker,
            "long_term_return_pct": 1.0, "short_term_return_pct": 1.0,
            "industry": "半導體", "profit_summary": "獲利；營收年增 +40.0%；營益率 20.0%；淨利率 12.0%",
            "long_term_window": "2y_cagr", "short_term_window": "6m_price_return",
            "market_source": "yfinance", "profit_source": "sec_edgar",
            "retrieved_at": generated, "provider_scope": "public_only", "owner_watchlist_inherited": False,
        })
        v213_rows.append({
            **v212_rows[-1], "schema_version": 2,
            "current_orders": "未揭露（無可靠公開訂單數字）",
            "future_orders_estimate": "無可靠公開預估", "orders_as_of": "",
            "orders_confidence": "UNAVAILABLE", "current_order_source_urls": [],
            "future_order_source_urls": [], "numeric_total_order_estimate_prohibited": True,
        })
        fed_rows.append({
            "ticker": ticker,
            "independent_families": ["us_sec", "nasdaq", "yahoo_finance"],
            "official_identity_or_filing_families": ["us_sec", "nasdaq"],
            "market_observation_families": ["yahoo_finance"],
            "issuer_financial_claim_family_count": 1,
            "evidence_additions": [{
                "source_id": "nasdaq_symbol_directory", "tier": "T2",
                "claim_type": "regulated_listing_identity", "title": ticker,
                "url": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", "as_of": generated,
            }],
        })
    v212 = {
        "product_version": "2.1.2", "records": v212_rows,
    }
    v213 = {
        "product_version": "2.1.3", "records": v213_rows,
    }
    federation = {
        "generated_at": generated, "ticker_sources": fed_rows,
        "unresolved_material_conflicts": [],
        "gates": {
            "pass": True, "successful_families": ["ecb", "nasdaq", "us_bls", "us_sec", "world_bank"],
            "official_successful_families": ["ecb", "nasdaq", "us_bls", "us_sec", "world_bank"],
            "missing_required_families": [], "ticker_coverage_ratio": 1.0,
            "unresolved_material_conflict_count": 0,
        },
    }
    standard = load_json(STANDARD_PATH)
    rows, reordered_v212, reordered_v213 = apply(top20, v212, v213, federation, standard)
    assert len(rows) == 20
    assert all(row["serenity_factors"]["chokepoint"] == 0 for row in rows)
    assert all(row["serenity_factors"]["replacement_friction"] == 0 for row in rows)
    assert all(row["serenity_factors"]["valuation_expectations"] <= 3.75 for row in rows)
    assert all(row["scoring_version"] == SCORING_VERSION for row in rows)
    assert [r["ticker"] for r in reordered_v212["records"]] == [r["ticker"] for r in rows]
    assert [r["ticker"] for r in reordered_v213["records"]] == [r["ticker"] for r in rows]
    print("V213_DIVERSIFIED_OPERATIONALIZATION_SELF_TEST = PASS")


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
        f"V213_DIVERSIFIED_OPERATIONALIZATION = PASS; rows=20; "
        f"top={rows[0]['ticker']}; scoring_version={SCORING_VERSION}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OperationalizationError, OSError, ValueError) as exc:
        print(f"V213_DIVERSIFIED_OPERATIONALIZATION = FAIL; {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
