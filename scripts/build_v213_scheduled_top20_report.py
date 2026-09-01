#!/usr/bin/env python3
"""Build the scheduled v2.1.3 seven-field report from fresh v2.1.2 rows
plus the accepted H6B2/R15R public order-evidence baseline.

This deliberately does not ask a local model to invent order totals. The five
market/profit fields refresh from v2.1.2; the two order fields retain their
evidence-bound text, source URLs and as-of dates until a new H6B evidence pass
accepts replacements.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_V212 = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
DEFAULT_BASELINE = ROOT / "data" / "bootstrap" / "v213-r15r-order-baseline.json"
DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_top20_report_public_latest.json"
DEFAULT_PREVIEW = ROOT / "data" / "cache" / "v213_top20_report_public_latest.txt"

DISPLAY_COLUMNS = [
    "股票",
    "長期投資報酬率（近2年年化）",
    "短期投資報酬率（近6個月）",
    "行業別",
    "獲利簡述",
    "公司現在訂單",
    "未來訂單預估",
]


class V213ScheduledReportError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V213ScheduledReportError(f"Unable to read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise V213ScheduledReportError(f"JSON root must be an object: {path}")
    return value


def _records(doc: Mapping[str, Any], version: str) -> list[dict[str, Any]]:
    if str(doc.get("product_version")) != version:
        raise V213ScheduledReportError(f"Expected product_version={version}")
    rows = doc.get("records")
    if not isinstance(rows, list) or len(rows) != 20:
        raise V213ScheduledReportError("Expected exactly 20 records")
    result: list[dict[str, Any]] = []
    tickers: set[str] = set()
    for index, raw in enumerate(rows, 1):
        if not isinstance(raw, dict):
            raise V213ScheduledReportError("Record must be an object")
        ticker = str(raw.get("ticker") or "").upper()
        if not ticker or ticker in tickers or int(raw.get("rank") or 0) != index:
            raise V213ScheduledReportError("Ticker/rank contract failed")
        tickers.add(ticker)
        result.append(dict(raw))
    return result


def build(v212: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    fresh = _records(v212, "2.1.2")
    accepted = _records(baseline, "2.1.3")
    fresh_order = [row["ticker"] for row in fresh]
    accepted_order = [row["ticker"] for row in accepted]
    if set(fresh_order) != set(accepted_order):
        added = sorted(set(fresh_order) - set(accepted_order))
        missing = sorted(set(accepted_order) - set(fresh_order))
        raise V213ScheduledReportError(
            "Top20 membership changed; H6B evidence rebuild required; "
            f"added={','.join(added) or '-'}; missing={','.join(missing) or '-'}"
        )

    evidence_by_ticker = {row["ticker"]: row for row in accepted}
    rows: list[dict[str, Any]] = []
    for rank, fresh_row in enumerate(fresh, 1):
        ticker = fresh_row["ticker"]
        evidence = evidence_by_ticker[ticker]
        rows.append({
            "schema_version": 2,
            "rank": rank,
            "ticker": ticker,
            "long_term_return_pct": fresh_row.get("long_term_return_pct"),
            "short_term_return_pct": fresh_row.get("short_term_return_pct"),
            "industry": fresh_row.get("industry"),
            "profit_summary": fresh_row.get("profit_summary"),
            "current_orders": evidence.get("current_orders"),
            "future_orders_estimate": evidence.get("future_orders_estimate"),
            "long_term_window": "2y_cagr",
            "short_term_window": "6m_price_return",
            "market_source": "yfinance",
            "profit_source": "sec_edgar",
            "orders_as_of": evidence.get("orders_as_of"),
            "orders_confidence": evidence.get("orders_confidence"),
            "current_order_source_urls": list(evidence.get("current_order_source_urls") or []),
            "future_order_source_urls": list(evidence.get("future_order_source_urls") or []),
            "numeric_total_order_estimate_prohibited": True,
            "retrieved_at": fresh_row.get("retrieved_at") or v212.get("generated_at"),
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        })

    return {
        "schema_version": 2,
        "product_version": "2.1.3",
        "generated_at": v212.get("generated_at"),
        "display_columns": DISPLAY_COLUMNS,
        "long_term_definition": "trailing_2y_adjusted_close_cagr",
        "short_term_definition": "trailing_6m_adjusted_close_price_return",
        "records": rows,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }


def _percent(value: Any) -> str:
    if value is None:
        return "N/A"
    value = float(value)
    return f"{value:+.1f}%"


def preview(report: Mapping[str, Any]) -> str:
    lines = ["｜".join(DISPLAY_COLUMNS)]
    for row in report["records"]:
        lines.append("｜".join([
            str(row["ticker"]),
            _percent(row.get("long_term_return_pct")),
            _percent(row.get("short_term_return_pct")),
            str(row.get("industry") or ""),
            str(row.get("profit_summary") or ""),
            str(row.get("current_orders") or ""),
            str(row.get("future_orders_estimate") or ""),
        ]))
    text = "\n".join(lines)
    if len(lines) != 21 or any(len(line.split("｜")) != 7 for line in lines[1:]):
        raise V213ScheduledReportError("Seven-field preview contract failed")
    if len(text) > 4900:
        raise V213ScheduledReportError(f"LINE preview exceeds one-message limit: {len(text)}")
    return text


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp"
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def self_test() -> None:
    generated = "2026-09-01T12:22:48Z"
    tickers = [f"T{i:02d}" for i in range(20)]
    v212 = {
        "product_version": "2.1.2", "generated_at": generated,
        "records": [{
            "rank": i + 1, "ticker": ticker, "long_term_return_pct": 10 + i,
            "short_term_return_pct": 2 + i, "industry": "半導體",
            "profit_summary": "獲利", "retrieved_at": generated,
        } for i, ticker in enumerate(tickers)]
    }
    baseline = {
        "product_version": "2.1.3",
        "records": [{
            "rank": i + 1, "ticker": ticker,
            "current_orders": "未揭露（無可靠公開訂單數字）",
            "future_orders_estimate": "無可靠公開預估",
            "orders_as_of": "2026-08-31",
            "orders_confidence": "NO_RELIABLE_PUBLIC_ORDER_NUMBER",
            "current_order_source_urls": [], "future_order_source_urls": [],
        } for i, ticker in enumerate(reversed(tickers))]
    }
    result = build(v212, baseline)
    assert [r["ticker"] for r in result["records"]] == tickers
    assert len(preview(result).splitlines()) == 21
    bad = dict(v212)
    bad["records"] = [dict(row) for row in v212["records"]]
    bad["records"][19]["ticker"] = "NEW"
    try:
        build(bad, baseline)
    except V213ScheduledReportError:
        pass
    else:
        raise AssertionError("membership drift did not fail closed")
    print("V213_SCHEDULED_REPORT_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v212-report", type=Path, default=DEFAULT_V212)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    report = build(_load(args.v212_report), _load(args.baseline))
    text = preview(report)
    atomic_text(args.output, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    atomic_text(args.preview, text + "\n")
    print(f"V213_SCHEDULED_REPORT = PASS; rows=20; chars={len(text)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except V213ScheduledReportError as exc:
        print(f"V213_SCHEDULED_REPORT = FAIL; {exc}", file=sys.stderr)
        raise SystemExit(1)
