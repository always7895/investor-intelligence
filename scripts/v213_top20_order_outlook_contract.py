#!/usr/bin/env python3
"""Shadow contract for the future seven-field LINE Top 20 presentation.

The accepted v2.1.2 Production report has five display fields.  The user-requested
v2.1.3 target appends two fields at the END:

股票 / 長期投資報酬率（近2年年化） / 短期投資報酬率（近6個月） /
行業別 / 獲利簡述 / 公司現在訂單 / 未來訂單預估

This module is a contract/renderer only.  It does not alter the live Worker or KV.
Order fields must be evidence-bound.  Missing or non-comparable order disclosure
is rendered explicitly rather than guessed.
"""
from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

DISPLAY_COLUMNS = [
    "股票",
    "長期投資報酬率（近2年年化）",
    "短期投資報酬率（近6個月）",
    "行業別",
    "獲利簡述",
    "公司現在訂單",
    "未來訂單預估",
]

NO_CURRENT_ORDERS = "未揭露（無可靠公開訂單數字）"
NO_FUTURE_ESTIMATE = "無可靠公開預估"
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,14}$")


def _clean_text(value: Any, *, fallback: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).replace("｜", "/")
    return (text or fallback)[:limit]


def _pct(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(number):
        return "N/A"
    return f"{number:+.1f}%"


def normalize_order_outlook(outlook: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(outlook or {})
    current = _clean_text(
        source.get("current_orders_summary"), fallback=NO_CURRENT_ORDERS, limit=150,
    )
    future = _clean_text(
        source.get("future_orders_estimate"), fallback=NO_FUTURE_ESTIMATE, limit=170,
    )
    current_urls = [
        str(url).strip() for url in (source.get("current_order_source_urls") or source.get("evidence_urls") or [])
        if str(url).strip().startswith("https://")
    ]
    future_urls = [
        str(url).strip() for url in (source.get("future_order_source_urls") or source.get("evidence_urls") or [])
        if str(url).strip().startswith("https://")
    ]
    confidence = str(source.get("confidence") or ("UNAVAILABLE" if not current_urls and not future_urls else "EVIDENCE_BOUND"))
    as_of = str(source.get("as_of") or "").strip()
    return {
        "current_orders": current,
        "future_orders_estimate": future,
        "orders_as_of": as_of,
        "orders_confidence": confidence[:80],
        "current_order_source_urls": current_urls[:8],
        "future_order_source_urls": future_urls[:8],
        "numeric_total_order_estimate_prohibited": bool(source.get("numeric_total_order_estimate_prohibited", True)),
    }


def seven_field_record(v212_record: Mapping[str, Any], outlook: Mapping[str, Any] | None = None) -> dict[str, Any]:
    ticker = str(v212_record.get("ticker") or "").strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise ValueError("invalid ticker")
    normalized = normalize_order_outlook(outlook)
    return {
        "rank": int(v212_record.get("rank") or 0),
        "ticker": ticker,
        "long_term_return_pct": v212_record.get("long_term_return_pct"),
        "short_term_return_pct": v212_record.get("short_term_return_pct"),
        "industry": _clean_text(v212_record.get("industry"), fallback="未分類", limit=100),
        "profit_summary": _clean_text(v212_record.get("profit_summary"), fallback="獲利資料不足", limit=120),
        **normalized,
    }


def validate_records(records: Sequence[Mapping[str, Any]]) -> None:
    if len(records) != 20:
        raise ValueError("seven-field Top 20 must contain exactly 20 rows")
    seen: set[str] = set()
    for index, row in enumerate(records, start=1):
        if int(row.get("rank") or 0) != index:
            raise ValueError("rank/order mismatch")
        ticker = str(row.get("ticker") or "").upper()
        if not TICKER_RE.fullmatch(ticker) or ticker in seen:
            raise ValueError("ticker invalid/duplicate")
        seen.add(ticker)
        if not str(row.get("current_orders") or "").strip():
            raise ValueError(f"missing current order field for {ticker}")
        if not str(row.get("future_orders_estimate") or "").strip():
            raise ValueError(f"missing future order estimate for {ticker}")
        if row.get("numeric_total_order_estimate_prohibited") is not True:
            raise ValueError(f"order estimate hallucination guard disabled for {ticker}")


def render(records: Sequence[Mapping[str, Any]]) -> str:
    validate_records(records)
    lines = ["｜".join(DISPLAY_COLUMNS)]
    for row in records:
        lines.append("｜".join([
            str(row["ticker"]),
            _pct(row.get("long_term_return_pct")),
            _pct(row.get("short_term_return_pct")),
            str(row["industry"]),
            str(row["profit_summary"]),
            str(row["current_orders"]),
            str(row["future_orders_estimate"]),
        ]))
    return "\n".join(lines)


def self_test() -> None:
    base_rows = []
    for i in range(20):
        base_rows.append(seven_field_record({
            "rank": i + 1,
            "ticker": f"T{i:02d}",
            "long_term_return_pct": 20.0 - i,
            "short_term_return_pct": 5.0 - i / 10,
            "industry": "半導體",
            "profit_summary": "獲利；營收年增 +20.0%",
        }))
    text = render(base_rows)
    assert text.splitlines()[0] == "股票｜長期投資報酬率（近2年年化）｜短期投資報酬率（近6個月）｜行業別｜獲利簡述｜公司現在訂單｜未來訂單預估"
    assert all(len(line.split("｜")) == 7 for line in text.splitlines())
    assert NO_CURRENT_ORDERS in text
    assert NO_FUTURE_ESTIMATE in text

    axti = normalize_order_outlook({
        "current_orders_summary": "Casela 2027 RMB1.73億固定量",
        "future_orders_estimate": "能見度偏高；已簽多年產能承諾",
        "evidence_urls": ["https://www.sec.gov/example"],
        "numeric_total_order_estimate_prohibited": True,
    })
    assert axti["current_orders"].startswith("Casela")
    assert axti["future_orders_estimate"].startswith("能見度偏高")
    print("V213_TOP20_SEVEN_FIELD_ORDER_OUTLOOK_CONTRACT = PASS")


if __name__ == "__main__":
    self_test()
