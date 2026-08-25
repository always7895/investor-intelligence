#!/usr/bin/env python3
"""Generate the current attribution-safe audit report.

Phase 4 will replace this with the full Taiwan Traditional Chinese morning and
evening report generator. This implementation enforces a strict separation
between source-derived views, project-authored scoring and the repository
owner's long-term holding preference.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "cache"
REPORTS_DIR = BASE_DIR / "reports"
TAIPEI = ZoneInfo("Asia/Taipei")


def load_json(filename: str, default: Any = None) -> Any:
    path = DATA_DIR / filename
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("Invalid optional JSON %s: %s", path, exc)
        return default


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def fmt_number(value: Any, digits: int = 2) -> str:
    parsed = number(value)
    return "N/A" if parsed is None else f"{parsed:,.{digits}f}"


def fmt_currency(value: Any) -> str:
    parsed = number(value)
    return "N/A" if parsed is None else f"${parsed:,.2f}"


def fmt_percent(value: Any, *, already_percent: bool = False, digits: int = 1) -> str:
    parsed = number(value)
    if parsed is None:
        return "N/A"
    if not already_percent:
        parsed *= 100
    return f"{parsed:.{digits}f}%"


def fmt_compact_currency(value: Any) -> str:
    parsed = number(value)
    if parsed is None:
        return "N/A"
    absolute = abs(parsed)
    if absolute >= 1e12:
        return f"${parsed / 1e12:.2f}T"
    if absolute >= 1e9:
        return f"${parsed / 1e9:.2f}B"
    if absolute >= 1e6:
        return f"${parsed / 1e6:.1f}M"
    return f"${parsed:,.0f}"


def latest_active_scan() -> dict[str, Any]:
    value = load_json("active_scan_latest.json", {})
    return value if isinstance(value, dict) else {}


def source_label(value: Any) -> str:
    normalized = str(value or "unknown").casefold()
    labels = {
        "serenity": "Serenity seed tag",
        "aschenbrenner": "Aschenbrenner seed tag",
        "both": "Both seed tags",
    }
    return labels.get(normalized, "Unverified source tag")


def generate_report(
    indices: dict[str, Any],
    market_data: list[dict[str, Any]],
    scores: list[dict[str, Any]],
    options_data: list[dict[str, Any]],
    movers: list[dict[str, Any]],
    watch_moves: list[dict[str, Any]],
    active_scan: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(TAIPEI)
    report_dir = REPORTS_DIR / now.strftime("%Y-%m-%d")
    report_dir.mkdir(parents=True, exist_ok=True)
    active_scan = active_scan if isinstance(active_scan, dict) else latest_active_scan()

    lines: list[str] = [
        f"# Investor Intelligence Research Briefing — {now:%Y-%m-%d}",
        "",
        f"> Generated {now:%Y-%m-%d %H:%M:%S %Z}. Market data may be delayed or incomplete.",
        "> Source views, system operationalization and user preferences are separate layers.",
        "> The five-layer score is project-authored; it is not an official Serenity or Leopold Aschenbrenner score.",
        "> The long-term suitability annotation is the repository user's preference for a minimum two-year horizon.",
        "> Nothing in this report is a price target, return forecast or trade instruction.",
        "",
    ]

    lines.extend(["## 1. Market overview", "", "| Index | Last | Change |", "|---|---:|---:|"])
    if indices:
        for value in indices.values():
            if not isinstance(value, dict):
                continue
            change = number(value.get("change_1d"))
            change_text = "N/A" if change is None else f"{change:+.2f}%"
            lines.append(
                f"| {value.get('name', 'Unknown')} | {fmt_number(value.get('close'))} | {change_text} |"
            )
    else:
        lines.append("| No verified index data | N/A | N/A |")
    lines.append("")

    lines.extend(
        [
            "## 2. Methodology attribution and source-view status",
            "",
            "### Source-view boundary",
            "",
            "- `Serenity source view` must be a time-stamped, source-linked summary of an identifiable public post.",
            "- `Aschenbrenner source view` must be grounded in the official *Situational Awareness* essay.",
            "- A watchlist `source` tag is only a research-routing seed. It is not evidence that either source endorses the company.",
            "- Numerical thresholds, score weights and entry/exit rules are `System operationalization`.",
            "- The minimum two-year horizon is a `User long-term overlay`, not a source view.",
            "",
        ]
    )
    source_records = load_json("source_views_latest.json", []) or []
    if source_records:
        lines.append("Verified source-view records available:")
        for record in source_records[:20]:
            if not isinstance(record, dict):
                continue
            lines.append(
                f"- **{record.get('author', 'Unknown')}** — {record.get('summary', 'No summary')} "
                f"({record.get('published_at', 'date unavailable')}; {record.get('url', 'URL unavailable')})"
            )
    else:
        lines.append(
            "No structured, verified source-view records are available yet. Phase 3/4 must add provenance before source-specific opinions are presented as current."
        )
    lines.append("")

    lines.extend(
        [
            "## 3. System operationalization — research ranking",
            "",
            "The ranking is ordered by the five-layer project research score. The score does not include the user's holding horizon.",
            "",
            "| Rank | Ticker | Seed tag | Rating | Research score | Data quality | Price | Market cap | Revenue growth | Category |",
            "|---:|---|---|:---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for score in scores or []:
        lines.append(
            "| {rank} | **{ticker}** | {source} | {rating} | {total}/100 | {quality} | {price} | {mcap} | {growth} | {category} |".format(
                rank=score.get("rank", "N/A"),
                ticker=score.get("ticker", "N/A"),
                source=source_label(score.get("source")),
                rating=score.get("rating", "N/A"),
                total=score.get("total_score", "N/A"),
                quality=fmt_percent(score.get("data_quality")),
                price=fmt_currency(score.get("current_price")),
                mcap=fmt_compact_currency(score.get("market_cap")),
                growth=fmt_percent(score.get("revenue_growth")),
                category=score.get("category", "Unknown"),
            )
        )
    if not scores:
        lines.append("| N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | No scores available |")
    lines.append("")

    lines.extend(["## 4. Top system-score review", ""])
    for score in (scores or [])[:5]:
        lines.extend(
            [
                f"### #{score.get('rank', 'N/A')} {score.get('ticker', 'N/A')} — {score.get('total_score', 'N/A')}/100",
                f"- Seed attribution tag: **{source_label(score.get('source'))}**",
                "- Attribution warning: this tag is not an endorsement and the score is project-authored.",
                f"- Data quality: **{fmt_percent(score.get('data_quality'))}**",
                f"- Market cap: {fmt_compact_currency(score.get('market_cap'))}; revenue growth: {fmt_percent(score.get('revenue_growth'))}",
                "- Layer scores: "
                + ", ".join(
                    f"{name}={value}"
                    for name, value in (score.get("layer_scores") or {}).items()
                ),
            ]
        )
        warnings = score.get("warnings") or []
        if warnings:
            lines.append("- Warnings: " + "; ".join(str(item) for item in warnings))
        lines.append("- Main system observations:")
        for reason in (score.get("reasons") or [])[:8]:
            lines.append(f"  - {reason}")
        lines.append("")
    if not scores:
        lines.extend(["No scored companies are available.", ""])

    lines.extend(
        [
            "## 5. User-defined long-term suitability overlay",
            "",
            "> This long-term suitability annotation reflects the repository user's preference for a holding horizon of at least two years. It is not attributed to Serenity or Leopold Aschenbrenner and is not a return forecast or trade instruction.",
            "",
            "| Ticker | Minimum horizon | Suitability label | Overlay score | Data quality | Key reasons |",
            "|---|---:|---|---:|---:|---|",
        ]
    )
    overlay_rows = 0
    for score in scores or []:
        overlay = score.get("user_long_term_overlay")
        if not isinstance(overlay, dict) or not overlay.get("enabled", False):
            continue
        overlay_rows += 1
        reasons = "; ".join(str(item) for item in (overlay.get("reasons") or [])[:3])
        lines.append(
            f"| **{score.get('ticker', 'N/A')}** | {overlay.get('minimum_holding_years', 2)}+ years | "
            f"{overlay.get('label', 'N/A')} | {overlay.get('score', 'N/A')}/100 | "
            f"{fmt_percent(overlay.get('data_quality'))} | {reasons or 'No reasons available'} |"
        )
    if overlay_rows == 0:
        lines.append("| N/A | N/A | No overlay data | N/A | N/A | N/A |")
    lines.append("")

    lines.extend(
        [
            "## 6. Options and movement observations",
            "",
            "> Raw option-chain calculations can be stale, illiquid or distorted. They are observations, not trade instructions and are not attributed to either methodology source.",
            "",
            "| Ticker | Period | Observation | Strike | Expiry | Premium | Annualized arithmetic yield | IV | Delta |",
            "|---|---|---|---:|---|---:|---:|---:|---:|",
        ]
    )
    option_rows = 0
    for option in options_data or []:
        if not isinstance(option, dict) or "error" in option:
            continue
        for period, suggestion in (option.get("suggestions") or {}).items():
            if not isinstance(suggestion, dict):
                continue
            for key, label in (
                ("sell_call", "Covered-call candidate"),
                ("sell_put", "Cash-secured-put candidate"),
            ):
                item = suggestion.get(key)
                if not isinstance(item, dict):
                    continue
                option_rows += 1
                expiry = str(item.get("expiration", "N/A"))[:10]
                lines.append(
                    f"| {option.get('ticker', 'N/A')} | {period} | {label} | {fmt_currency(item.get('strike'))} | {expiry} | "
                    f"{fmt_currency(item.get('premium'))} | {fmt_percent(item.get('annualized_yield_pct'), already_percent=True)} | "
                    f"{fmt_percent(item.get('implied_vol'), already_percent=True)} | {fmt_number(item.get('delta'))} |"
                )
    if option_rows == 0:
        lines.append("| N/A | N/A | No usable options observations | N/A | N/A | N/A | N/A | N/A | N/A |")
    lines.append("")

    if movers:
        lines.extend(["### Abnormal broad-market moves", "", "| Ticker | Change | Volume ratio | Last |", "|---|---:|---:|---:|"])
        for item in movers[:15]:
            lines.append(
                f"| {item.get('ticker', 'N/A')} | {fmt_percent(item.get('change_pct'), already_percent=True)} | "
                f"{fmt_number(item.get('volume_ratio'), 1)}x | {fmt_currency(item.get('close'))} |"
            )
        lines.append("")
    if watch_moves:
        lines.append("### Watchlist moves")
        lines.append("")
        for item in watch_moves:
            lines.append(
                f"- **{item.get('ticker', 'N/A')}**: {fmt_percent(item.get('change_pct'), already_percent=True)} at {fmt_currency(item.get('price'))}"
            )
        lines.append("")

    lines.extend(["## 7. Active scan and data health", ""])
    new_entries = active_scan.get("new_entries") or []
    exit_candidates = active_scan.get("exit_candidates") or []
    if new_entries:
        lines.append("### Evidence-gated entry candidates")
        for item in new_entries:
            lines.append(
                f"- **{item.get('ticker')}** — system score {item.get('score')}; layer {item.get('layer') or 'N/A'}"
            )
    else:
        lines.append("- No evidence-gated entry candidates.")
    if exit_candidates:
        lines.append("### Exit/review candidates")
        for item in exit_candidates:
            lines.append(
                f"- **{item.get('ticker')}** — system score {item.get('score')}; reasons: "
                + "; ".join(str(reason) for reason in item.get("reasons", []))
            )
    else:
        lines.append("- No exit candidates.")
    failed_market = [
        item for item in market_data or [] if isinstance(item, dict) and "error" in item
    ]
    low_quality = [
        item
        for item in scores or []
        if number(item.get("data_quality")) is not None
        and float(item["data_quality"]) < 0.50
    ]
    lines.extend(
        [
            "",
            f"- Market records received: {len(market_data or [])}",
            f"- Market-record failures: {len(failed_market)}",
            f"- Scores with data quality below 50%: {len(low_quality)}",
            "- Eight-source news health is not available until Phase 3.",
            "",
        ]
    )

    lines.extend(["## 8. Summary, contrary evidence and controls", ""])
    if scores:
        lines.append("Highest current project-authored research scores:")
        for index, score in enumerate(scores[:3], start=1):
            overlay = score.get("user_long_term_overlay") or {}
            lines.append(
                f"{index}. **{score.get('ticker')}** — system score {score.get('total_score')}/100, "
                f"data quality {fmt_percent(score.get('data_quality'))}; user overlay: {overlay.get('label', 'N/A')}."
            )
    else:
        lines.append("No ranking summary is available.")
    lines.extend(
        [
            "",
            "Required verification before relying on any thesis:",
            "",
            "- original source URL and publication date;",
            "- filings, named contracts and customer confirmation;",
            "- dilution, debt, customer concentration and jurisdictional exposure;",
            "- substitutes, qualification periods and capacity timing;",
            "- contrary evidence and explicit disconfirmation conditions;",
            "- current market data, currency and corporate-action normalization.",
            "",
            "A source-specific opinion and the user long-term overlay may disagree. Both must be shown without rewriting either one.",
            "",
            "---",
            f"Generated {now:%Y-%m-%d %H:%M:%S %Z}. Research software only; not investment advice.",
        ]
    )

    report = "\n".join(lines) + "\n"
    report_path = report_dir / "briefing.md"
    latest_path = REPORTS_DIR / "briefing_latest.md"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    latest_path.write_text(report, encoding="utf-8")
    logger.info("Report generated: %s", report_path)
    return str(report_path)


def main() -> int:
    indices = load_json("indices_latest.json", {}) or {}
    market_data = load_json("market_latest.json", []) or []
    scores = load_json("scores_latest.json", []) or []
    options_data = load_json("options_latest.json", []) or []
    movers = load_json("movers_latest.json", []) or []
    watch_moves = [
        {
            "ticker": item.get("ticker"),
            "name": item.get("name"),
            "change_pct": item.get("price_change_1d"),
            "price": item.get("current_price"),
        }
        for item in market_data
        if isinstance(item, dict)
        and "error" not in item
        and number(item.get("price_change_1d")) is not None
        and abs(float(item["price_change_1d"])) > 4
    ]
    path = generate_report(
        indices,
        market_data,
        scores,
        options_data,
        movers,
        watch_moves,
    )
    print(f"Report saved to: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
