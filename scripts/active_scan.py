#!/usr/bin/env python3
"""Dynamic watchlist entry/exit evaluator.

The active scan is a project-authored system operationalization. It may be
informed by public source themes, but its thresholds, weights, layers and
entry/exit decisions are not official Serenity or Leopold Aschenbrenner rules.

Evaluation is separated from mutation. By default the module produces
candidates without changing an ignored local research-universe file. Passing
``--apply-changes`` atomically applies validated local-only changes.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from local_research_config import DEFAULT_LOCAL_UNIVERSE_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WATCHLIST = DEFAULT_LOCAL_UNIVERSE_PATH
DEFAULT_MARKET = BASE_DIR / "data" / "cache" / "market_latest.json"
DEFAULT_NEWS = BASE_DIR / "data" / "cache" / "news_latest.json"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "cache"
DEFAULT_REPORT = BASE_DIR / "reports" / "active_scan_latest.md"

ENTRY_THRESHOLD = 60
EXIT_THRESHOLD = 40
MIN_EXIT_COMPLETENESS = 0.60

POTENTIAL_CHOKEPOINT_CATEGORIES = {
    "inp substrate",
    "cpo cw laser",
    "hbm memory",
    "advanced foundry",
    "advanced process",
    "optical transceiver",
    "optical communications",
    "optical test equipment",
}
AI_INFRA_KEYWORDS = {
    "gpu",
    "neocloud",
    "hbm",
    "optical",
    "optics",
    "inp",
    "cpo",
    "ai data",
    "ai compute",
    "asic",
    "networking",
    "storage",
    "foundry",
    "process",
    "power",
    "fuel cell",
    "natural gas",
    "data center",
    "fiber",
    "nand",
}
SYSTEM_LAYER_KEYWORDS = {
    "A": {"power", "fuel cell", "natural gas", "data center", "grid", "transformer"},
    "B": {"gpu", "neocloud", "asic", "networking", "ai compute"},
    "C": {"hbm", "optical", "optics", "inp", "cpo", "foundry", "storage", "fiber", "nand"},
}


@dataclass(frozen=True)
class Criterion:
    name: str
    passed: bool
    points: int
    reason: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def text_contains(text: Any, keywords: Iterable[str]) -> bool:
    lowered = str(text or "").casefold()
    return any(keyword.casefold() in lowered for keyword in keywords)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return copy.deepcopy(default)
        raise FileNotFoundError(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def normalize_news_items(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    if isinstance(document, dict):
        for key in ("items", "articles", "news"):
            value = document.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def extract_news_candidates(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for item in items:
        raw_tickers: list[Any] = []
        if isinstance(item.get("tickers"), list):
            raw_tickers.extend(item["tickers"])
        elif item.get("ticker"):
            raw_tickers.append(item["ticker"])

        for raw in raw_tickers:
            ticker = str(raw).strip().upper()
            if not ticker or ticker.endswith((".SS", ".SZ")):
                continue
            candidate = candidates.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "source": "news-scan",
                    "evidence_urls": [],
                    "strong_evidence_count": 0,
                    "medium_evidence_count": 0,
                },
            )
            if item.get("category") and not candidate.get("category"):
                candidate["category"] = str(item["category"])
            if item.get("name") and not candidate.get("name"):
                candidate["name"] = str(item["name"])
            if item.get("url"):
                candidate["evidence_urls"].append(str(item["url"]))

            strength = str(item.get("evidence_strength", "weak")).casefold()
            if strength == "strong":
                candidate["strong_evidence_count"] += 1
            elif strength == "medium":
                candidate["medium_evidence_count"] += 1

            for key in (
                "tam_growth",
                "qualification_months",
                "market_share",
                "technology_moat_years",
                "supply_gap",
                "customer_concentration",
                "china_revenue_share",
                "export_control_exposure",
                "has_diversification_plan",
                "atm_issuance_to_revenue",
                "sbc_to_revenue",
                "consecutive_negative_yoy_quarters",
                "contract_evidence",
                "pricing_power_evidence",
                "demand_evidence",
            ):
                if key in item and key not in candidate:
                    candidate[key] = item[key]
    return candidates


def determine_system_layer(category: Any) -> str | None:
    for layer, keywords in SYSTEM_LAYER_KEYWORDS.items():
        if text_contains(category, keywords):
            return layer
    return None


def evidence_gate(data: dict[str, Any], metadata: dict[str, Any]) -> tuple[bool, int, str]:
    strong = int(
        safe_float(data.get("strong_evidence_count"))
        or safe_float(metadata.get("strong_evidence_count"))
        or 0
    )
    medium = int(
        safe_float(data.get("medium_evidence_count"))
        or safe_float(metadata.get("medium_evidence_count"))
        or 0
    )
    explicit = str(
        data.get("evidence_strength") or metadata.get("evidence_strength") or ""
    ).casefold()

    if strong >= 1 or explicit == "strong":
        return True, 3, "At least one strong primary-source item"
    if medium >= 2 or explicit == "medium-verified":
        return True, 2, "At least two independent medium-strength items"
    if medium == 1 or explicit == "medium":
        return False, 1, "Only one medium-strength item; corroboration required"
    return False, 0, "No qualifying evidence metadata"


def exclusion_checks(data: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    """Project-authored risk gates; not attributed to any external source."""
    exclusions: list[str] = []
    revenue = safe_float(data.get("revenue_ttm"))
    debt = safe_float(data.get("total_debt"))
    atm = safe_float(
        data.get("atm_issuance_to_revenue") or metadata.get("atm_issuance_to_revenue")
    )
    sbc = safe_float(data.get("sbc_to_revenue") or metadata.get("sbc_to_revenue"))
    if atm is not None and atm > 0.10:
        exclusions.append(f"Project risk gate: ATM issuance/revenue {atm:.1%} exceeds 10%")
    if sbc is not None and sbc > 0.15:
        exclusions.append(f"Project risk gate: SBC/revenue {sbc:.1%} exceeds 15%")
    if revenue and debt is not None and debt / revenue > 2 and not metadata.get(
        "debt_repayment_plan"
    ):
        exclusions.append("Project risk gate: debt/revenue exceeds 200% without documented repayment plan")

    concentration = safe_float(
        data.get("customer_concentration") or metadata.get("customer_concentration")
    )
    if (
        concentration is not None
        and concentration > 0.50
        and not metadata.get("customer_aaa_or_take_or_pay")
    ):
        exclusions.append(
            f"Project risk gate: single-customer concentration {concentration:.1%}"
        )

    negative_quarters = int(
        safe_float(
            data.get("consecutive_negative_yoy_quarters")
            or metadata.get("consecutive_negative_yoy_quarters")
        )
        or 0
    )
    if negative_quarters >= 2 and not metadata.get("documented_turnaround_catalyst"):
        exclusions.append("Project risk gate: at least two consecutive negative YoY revenue quarters")

    china_share = safe_float(
        data.get("china_revenue_share") or metadata.get("china_revenue_share")
    )
    export_control = bool(
        data.get("export_control_exposure") or metadata.get("export_control_exposure")
    )
    diversification = bool(
        data.get("has_diversification_plan") or metadata.get("has_diversification_plan")
    )
    if china_share is not None and china_share > 0.50 and export_control and not diversification:
        exclusions.append(
            "Project risk gate: China revenue exposure exceeds 50% with export-control exposure"
        )
    return exclusions


def bottleneck_screen(data: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Project screen for demand/bottleneck themes; not an official author framework."""
    category = str(metadata.get("category") or data.get("category") or "")
    gross_margin = safe_float(data.get("gross_margin"))
    revenue_growth = safe_float(data.get("revenue_growth"))
    market_cap = safe_float(data.get("market_cap"))
    forward_pe = safe_float(data.get("forward_pe"))
    tam_growth = safe_float(data.get("tam_growth") or metadata.get("tam_growth"))
    qualification = safe_float(
        data.get("qualification_months") or metadata.get("qualification_months")
    )
    market_share = safe_float(data.get("market_share") or metadata.get("market_share"))

    demand_pass = text_contains(category, AI_INFRA_KEYWORDS) and (
        bool(data.get("demand_evidence") or metadata.get("demand_evidence"))
        or (revenue_growth is not None and revenue_growth > 0.30)
    )
    chokepoint_pass = (
        category.casefold() in POTENTIAL_CHOKEPOINT_CATEGORIES
        or (market_share is not None and market_share > 0.50)
        or (qualification is not None and qualification > 24)
    )
    pricing_pass = (
        (gross_margin is not None and gross_margin > 0.40)
        or bool(data.get("pricing_power_evidence") or metadata.get("pricing_power_evidence"))
    )
    substitute_pass = (
        category.casefold() in {"inp substrate", "hbm memory", "cpo cw laser"}
        or (qualification is not None and qualification > 18)
    )
    tam_pass = (
        (tam_growth is not None and tam_growth > 0.30)
        or (revenue_growth is not None and revenue_growth > 0.30)
    )
    headroom_pass = (
        (market_cap is not None and 0 < market_cap < 30e9)
        or (
            market_cap is not None
            and market_cap >= 100e9
            and forward_pe is not None
            and 0 < forward_pe < 15
            and revenue_growth is not None
            and revenue_growth > 0.50
        )
    )
    evidence_pass, evidence_points, evidence_reason = evidence_gate(data, metadata)

    criteria = [
        Criterion("demand_wave", demand_pass, 3 if demand_pass else 0, "Project rule: AI demand plus >30% growth or explicit demand evidence"),
        Criterion("chokepoint", chokepoint_pass, 3 if chokepoint_pass else 0, "Project rule: potential chokepoint, market share, or qualification barrier"),
        Criterion("pricing_power", pricing_pass, 3 if pricing_pass else 0, "Project rule: gross margin >40% or explicit pricing evidence"),
        Criterion("replacement_friction", substitute_pass, 3 if substitute_pass else 0, "Project rule: category hypothesis or qualification >18 months"),
        Criterion("tam_expansion", tam_pass, 3 if tam_pass else 0, "Project rule: TAM or revenue growth >30%"),
        Criterion("market_cap_headroom", headroom_pass, 3 if headroom_pass else 0, "Project rule: market-cap headroom or configured large-cap exception"),
        Criterion("evidence_quality", evidence_pass, evidence_points, evidence_reason),
    ]
    exclusions = exclusion_checks(data, metadata)
    raw_points = sum(item.points for item in criteria)
    score = round(raw_points / 21 * 100)
    passed = all(item.passed for item in criteria) and not exclusions
    return {
        "screen_id": "system_bottleneck_screen_v1",
        "attribution": "system_operationalization_not_author_rule",
        "passed": passed,
        "score": score,
        "criteria": [item.__dict__ for item in criteria],
        "exclusions": exclusions,
    }


def infrastructure_screen(data: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Project infrastructure screen; not an official Aschenbrenner stock screen."""
    category = str(metadata.get("category") or data.get("category") or "")
    layer = determine_system_layer(category)
    if layer is None:
        return {
            "screen_id": "system_infrastructure_screen_v1",
            "attribution": "system_operationalization_not_author_rule",
            "passed": False,
            "score": 0,
            "layer": None,
            "criteria": [],
        }

    revenue_growth = safe_float(data.get("revenue_growth"))
    ps_ratio = safe_float(data.get("ps_ratio"))
    market_share = safe_float(data.get("market_share") or metadata.get("market_share"))
    moat_years = safe_float(
        data.get("technology_moat_years") or metadata.get("technology_moat_years")
    )
    supply_gap = safe_float(data.get("supply_gap") or metadata.get("supply_gap"))
    contract = bool(data.get("contract_evidence") or metadata.get("contract_evidence"))
    evidence_pass, _, _ = evidence_gate(data, metadata)

    ps_limit = 15 if layer == "B" else 10
    criteria = [
        Criterion("system_layer_identified", True, 2, f"Project infrastructure domain {layer}"),
        Criterion("supply_gap", supply_gap is not None and supply_gap > 0.20, 2 if supply_gap is not None and supply_gap > 0.20 else 0, "Project rule: supply-demand gap >20%"),
        Criterion("revenue_growth", revenue_growth is not None and revenue_growth > 0.40, 2 if revenue_growth is not None and revenue_growth > 0.40 else 0, "Project rule: revenue-growth proxy >40%"),
        Criterion("market_position", (market_share is not None and market_share > 0.30) or (moat_years is not None and moat_years > 3), 2 if ((market_share is not None and market_share > 0.30) or (moat_years is not None and moat_years > 3)) else 0, "Project rule: market share >30% or moat proxy >3 years"),
        Criterion("valuation", ps_ratio is not None and 0 < ps_ratio < ps_limit, 1 if ps_ratio is not None and 0 < ps_ratio < ps_limit else 0, f"Project rule: P/S proxy below {ps_limit}x"),
        Criterion("contract_and_evidence", contract and evidence_pass, 1 if contract and evidence_pass else 0, "Project rule: named contract plus qualifying evidence"),
    ]
    raw_points = sum(item.points for item in criteria)
    score = raw_points * 10
    passed = raw_points >= 7 and criteria[1].passed and evidence_pass
    return {
        "screen_id": "system_infrastructure_screen_v1",
        "attribution": "system_operationalization_not_author_rule",
        "passed": passed,
        "score": score,
        "layer": layer,
        "criteria": [item.__dict__ for item in criteria],
    }


def completeness(data: dict[str, Any]) -> float:
    fields = (
        "market_cap",
        "revenue_growth",
        "gross_margin",
        "ps_ratio",
        "total_debt",
        "revenue_ttm",
    )
    available = sum(safe_float(data.get(field)) is not None for field in fields)
    return available / len(fields)


def score_candidate(data: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    bottleneck = bottleneck_screen(data, metadata)
    infrastructure = infrastructure_screen(data, metadata)
    applicable_scores = [bottleneck["score"]]
    if infrastructure["layer"] is not None:
        applicable_scores.append(infrastructure["score"])
    system_score = (
        round(sum(applicable_scores) / len(applicable_scores)) if applicable_scores else 0
    )
    if bottleneck["passed"] and infrastructure["passed"]:
        system_score = min(system_score + 3, 100)

    explicit_exclusions = bottleneck["exclusions"]
    return {
        "ticker": str(data.get("ticker") or metadata.get("ticker") or "").upper(),
        "name": str(data.get("name") or metadata.get("name") or data.get("ticker") or ""),
        "category": str(metadata.get("category") or data.get("category") or "Unknown"),
        "score_type": "system_operationalization_not_author_score",
        "system_scan_score": system_score,
        "system_bottleneck_screen": bottleneck,
        "system_infrastructure_screen": infrastructure,
        "attribution": {
            "serenity_endorsement": False,
            "aschenbrenner_endorsement": False,
            "user_holding_horizon_included": False,
        },
        "data_completeness": round(completeness(data), 3),
        "explicit_exclusions": explicit_exclusions,
    }


def evaluate(
    watchlist_document: dict[str, Any],
    market_document: Any,
    news_document: Any,
) -> dict[str, Any]:
    stocks = watchlist_document.get("stocks")
    if not isinstance(stocks, list):
        raise ValueError("Local research universe must contain a stocks array")

    market_items = market_document if isinstance(market_document, list) else []
    market_lookup = {
        str(item.get("ticker", "")).upper(): item
        for item in market_items
        if isinstance(item, dict) and item.get("ticker") and "error" not in item
    }
    news_candidates = extract_news_candidates(normalize_news_items(news_document))
    current_tickers = {str(stock.get("ticker", "")).upper() for stock in stocks}

    evaluations: list[dict[str, Any]] = []
    exit_candidates: list[dict[str, Any]] = []
    unscored_existing: list[dict[str, str]] = []

    for metadata in stocks:
        ticker = str(metadata.get("ticker", "")).upper()
        data = market_lookup.get(ticker)
        if not data:
            unscored_existing.append({"ticker": ticker, "reason": "market data unavailable"})
            continue
        result = score_candidate(copy.deepcopy(data), metadata)
        evaluations.append(result)
        if result["explicit_exclusions"] or (
            result["system_scan_score"] < EXIT_THRESHOLD
            and result["data_completeness"] >= MIN_EXIT_COMPLETENESS
        ):
            exit_candidates.append(
                {
                    "ticker": ticker,
                    "name": metadata.get("name", ticker),
                    "score": result["system_scan_score"],
                    "score_type": "system_operationalization_not_author_score",
                    "action": "exit_candidate",
                    "reasons": result["explicit_exclusions"]
                    or ["Project system-scan score below exit threshold"],
                }
            )

    new_entries: list[dict[str, Any]] = []
    unscored_new: list[dict[str, str]] = []
    for ticker, candidate_metadata in sorted(news_candidates.items()):
        if ticker in current_tickers:
            continue
        data = market_lookup.get(ticker)
        if not data:
            unscored_new.append(
                {"ticker": ticker, "reason": "fundamental market data unavailable"}
            )
            continue
        result = score_candidate(copy.deepcopy(data), candidate_metadata)
        evaluations.append(result)
        system_screen_pass = (
            result["system_bottleneck_screen"]["passed"]
            or result["system_infrastructure_screen"]["passed"]
        )
        if (
            result["system_scan_score"] >= ENTRY_THRESHOLD
            and system_screen_pass
            and not result["explicit_exclusions"]
        ):
            new_entries.append(
                {
                    "ticker": ticker,
                    "name": result["name"],
                    "category": result["category"],
                    "source": "unverified-auto-scan",
                    "score": result["system_scan_score"],
                    "score_type": "system_operationalization_not_author_score",
                    "layer": result["system_infrastructure_screen"]["layer"],
                    "action": "new_entry",
                    "evidence_urls": candidate_metadata.get("evidence_urls", []),
                    "system_screens": {
                        "bottleneck": result["system_bottleneck_screen"]["passed"],
                        "infrastructure": result["system_infrastructure_screen"]["passed"],
                    },
                    "attribution": {
                        "serenity_endorsement": False,
                        "aschenbrenner_endorsement": False,
                    },
                }
            )

    return {
        "schema_version": 3,
        "generated_at": utc_now().isoformat(),
        "score_type": "system_operationalization_not_author_score",
        "attribution": {
            "serenity_framework_claimed": False,
            "aschenbrenner_stock_screen_claimed": False,
            "user_holding_horizon_included": False,
        },
        "thresholds": {
            "entry": ENTRY_THRESHOLD,
            "exit": EXIT_THRESHOLD,
            "minimum_exit_completeness": MIN_EXIT_COMPLETENESS,
            "owner": "project_system",
        },
        "counts": {
            "existing": len(current_tickers),
            "market_records": len(market_lookup),
            "news_candidates": len(news_candidates),
            "evaluated": len(evaluations),
        },
        "evaluations": evaluations,
        "new_entries": new_entries,
        "exit_candidates": exit_candidates,
        "unscored_existing": unscored_existing,
        "unscored_new": unscored_new,
    }


def apply_changes(
    watchlist_document: dict[str, Any], results: dict[str, Any]
) -> dict[str, Any]:
    updated = copy.deepcopy(watchlist_document)
    stocks = updated.setdefault("stocks", [])
    exit_tickers = {item["ticker"] for item in results["exit_candidates"]}
    stocks[:] = [
        stock
        for stock in stocks
        if str(stock.get("ticker", "")).upper() not in exit_tickers
    ]
    existing = {str(stock.get("ticker", "")).upper() for stock in stocks}

    for entry in results["new_entries"]:
        if entry["ticker"] in existing:
            continue
        stocks.append(
            {
                "ticker": entry["ticker"],
                "name": entry["name"],
                "category": entry["category"],
                "source": "unverified-auto-scan",
                "thesis": (
                    "Automatically admitted by an evidence-gated project system "
                    "operationalization. No Serenity or Aschenbrenner endorsement inferred."
                ),
                "last_score": entry["score"],
                "last_score_type": "system_operationalization_not_author_score",
                "last_score_date": utc_now().date().isoformat(),
            }
        )
        existing.add(entry["ticker"])

    updated["updated"] = utc_now().date().isoformat()
    updated["last_active_scan_run"] = results["generated_at"]
    return updated


def write_report(results: dict[str, Any], path: Path) -> None:
    lines = [
        "# Active Scan Report — Project System Operationalization",
        "",
        "> These entry/exit thresholds are project-authored and are not official Serenity or Leopold Aschenbrenner rules or recommendations.",
        "",
        f"Generated: {results['generated_at']}",
        f"Existing: {results['counts']['existing']} | Evaluated: {results['counts']['evaluated']} | "
        f"New entries: {len(results['new_entries'])} | Exit candidates: {len(results['exit_candidates'])}",
        "",
        "## New entries",
    ]
    if results["new_entries"]:
        for item in results["new_entries"]:
            lines.append(
                f"- **{item['ticker']}** — project score {item['score']}; system layer {item['layer'] or 'N/A'}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Exit candidates"])
    if results["exit_candidates"]:
        for item in results["exit_candidates"]:
            lines.append(
                f"- **{item['ticker']}** — project score {item['score']}: {'; '.join(item['reasons'])}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Unscored"])
    unscored = results["unscored_existing"] + results["unscored_new"]
    if unscored:
        for item in unscored:
            lines.append(f"- **{item['ticker']}** — {item['reason']}")
    else:
        lines.append("- None")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_active_scan(
    *,
    watchlist_path: Path = DEFAULT_WATCHLIST,
    market_path: Path = DEFAULT_MARKET,
    news_path: Path = DEFAULT_NEWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_path: Path = DEFAULT_REPORT,
    apply: bool = False,
) -> dict[str, Any]:
    watchlist = load_json(watchlist_path)
    market = load_json(market_path, default=[])
    news = load_json(news_path, default=[])
    results = evaluate(watchlist, market, news)

    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_dir / "active_scan_latest.json", results)
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    atomic_write_json(output_dir / f"active_scan_{timestamp}.json", results)
    write_report(results, report_path)

    if apply:
        updated = apply_changes(watchlist, results)
        atomic_write_json(watchlist_path, updated)
        results["changes_applied"] = True
    else:
        results["changes_applied"] = False

    logger.info(
        "Active scan complete: %d entries, %d exits, applied=%s",
        len(results["new_entries"]),
        len(results["exit_candidates"]),
        apply,
    )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate project-authored dynamic watchlist entry and exit candidates"
    )
    parser.add_argument("--universe", "--watchlist", dest="watchlist", type=Path, default=DEFAULT_WATCHLIST)
    parser.add_argument("--market-data", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--news-data", type=Path, default=DEFAULT_NEWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--apply-changes", action="store_true", help="Atomically update the watchlist"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = run_active_scan(
        watchlist_path=args.watchlist,
        market_path=args.market_data,
        news_path=args.news_data,
        output_dir=args.output_dir,
        report_path=args.report,
        apply=args.apply_changes,
    )
    print(
        json.dumps(
            {
                "new_entries": len(results["new_entries"]),
                "exit_candidates": len(results["exit_candidates"]),
                "unscored": len(results["unscored_existing"])
                + len(results["unscored_new"]),
                "changes_applied": results["changes_applied"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
