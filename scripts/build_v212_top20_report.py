#!/usr/bin/env python3
"""Build the v2.1.2 five-field public Top 20 report.

The LINE presentation intentionally exposes only:
股票 / 長期投資報酬率 / 短期投資報酬率 / 行業別 / 獲利簡述

Definitions are kept in the machine payload, not printed as extra report columns:
- long_term_return_pct: trailing ~2-year annualized price CAGR from adjusted closes.
- short_term_return_pct: trailing ~6-month adjusted-close price return.
- profit_summary: deterministic SEC-EDGAR companyfacts summary (revenue growth,
  operating margin and net margin when available).

Market-return and industry observations use public yfinance/Yahoo observations;
profitability uses SEC EDGAR. No portfolio, account, cost basis or brokerage data
is read or emitted.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_v21_public_snapshot as snapshot
import v21_serenity_top20 as base

TOP20_PATH = ROOT / "data" / "cache" / "top20_public_latest.json"
OUTPUT_PATH = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
LONG_TERM_WINDOW_DAYS = 730
SHORT_TERM_WINDOW_DAYS = 183
MIN_LONG_TERM_ELAPSED_DAYS = 600
MIN_SHORT_TERM_ELAPSED_DAYS = 120


class Top20ReportError(RuntimeError):
    pass


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _pct(value: float | None) -> str | None:
    return None if value is None else f"{value * 100:+.1f}%"


def profit_summary(metrics: Mapping[str, Any]) -> str:
    revenue = _finite(metrics.get("revenue_growth"))
    operating = _finite(metrics.get("operating_margin"))
    net = _finite(metrics.get("net_margin"))
    parts: list[str] = []
    if revenue is not None:
        parts.append(f"營收年增 {_pct(revenue)}")
    if operating is not None:
        parts.append(f"營益率 {operating * 100:.1f}%")
    if net is not None:
        parts.append(f"淨利率 {net * 100:.1f}%")
    if not parts:
        return "SEC 可用獲利指標不足"
    if net is not None:
        parts.insert(0, "獲利" if net >= 0 else "虧損")
    return "；".join(parts)[:120]


def _returns_from_history(history: Any) -> tuple[float | None, float | None]:
    if history is None or len(getattr(history, "index", [])) < 2 or "Close" not in history:
        return None, None
    closes = history["Close"].dropna()
    if len(closes) < 2:
        return None, None
    latest_price = _finite(closes.iloc[-1])
    if latest_price is None or latest_price <= 0:
        return None, None
    latest_time = closes.index[-1]

    def start_point(days: int) -> tuple[float | None, int]:
        target = latest_time - timedelta(days=days)
        window = closes[closes.index >= target]
        if len(window) < 2:
            return None, 0
        first_price = _finite(window.iloc[0])
        elapsed = int((latest_time - window.index[0]).days)
        return first_price, elapsed

    long_start, long_days = start_point(LONG_TERM_WINDOW_DAYS)
    long_term = None
    if long_start and long_start > 0 and long_days >= MIN_LONG_TERM_ELAPSED_DAYS:
        long_term = (latest_price / long_start) ** (365.25 / long_days) - 1

    short_start, short_days = start_point(SHORT_TERM_WINDOW_DAYS)
    short_term = None
    if short_start and short_start > 0 and short_days >= MIN_SHORT_TERM_ELAPSED_DAYS:
        short_term = latest_price / short_start - 1
    return long_term, short_term


def _market_observation(ticker: str, fallback_industry: str) -> tuple[float | None, float | None, str]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise Top20ReportError("Verified runtime lacks yfinance") from exc
    try:
        obj = yf.Ticker(ticker)
        history = obj.history(period="3y", interval="1d", auto_adjust=True)
        long_term, short_term = _returns_from_history(history)
        industry = ""
        try:
            info = obj.info
            if isinstance(info, dict):
                industry = str(info.get("industry") or info.get("sector") or "").strip()
        except Exception:
            pass
        return long_term, short_term, industry or fallback_industry or "未分類"
    except Exception:
        return None, None, fallback_industry or "未分類"


def build(*, top20_path: Path = TOP20_PATH) -> dict[str, Any]:
    try:
        raw = json.loads(top20_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Top20ReportError(f"Unable to read Top 20: {top20_path}") from exc
    top20 = snapshot.validate_top20(raw)
    policy, _activation = base.validate_policy()
    headers = base.sec_headers()
    http = base.session()
    reference = base.sec_reference(policy, http, headers)
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    rows: list[dict[str, Any]] = []
    for item in top20:
        ticker = str(item["ticker"])
        long_term, short_term, industry = _market_observation(ticker, str(item.get("category") or ""))
        metrics: dict[str, Any] = {}
        official = reference.get(ticker)
        if official:
            try:
                candidate = {"ticker": ticker, "official": dict(official), "market": {}}
                records = base.sec_companyfacts(candidate, policy, http, headers)
                metrics, _evidence = base.metrics(records)
            except Exception:
                metrics = {}
        rows.append({
            "schema_version": 1,
            "rank": int(item["rank"]),
            "ticker": ticker,
            "long_term_return_pct": None if long_term is None else round(long_term * 100, 2),
            "short_term_return_pct": None if short_term is None else round(short_term * 100, 2),
            "industry": industry[:100],
            "profit_summary": profit_summary(metrics),
            "long_term_window": "2y_cagr",
            "short_term_window": "6m_price_return",
            "market_source": "yfinance",
            "profit_source": "sec_edgar",
            "retrieved_at": generated,
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        })
    return {
        "schema_version": 1,
        "product_version": "2.1.2",
        "generated_at": generated,
        "display_columns": ["股票", "長期投資報酬率", "短期投資報酬率", "行業別", "獲利簡述"],
        "long_term_definition": "trailing_2y_adjusted_close_cagr",
        "short_term_definition": "trailing_6m_adjusted_close_price_return",
        "records": rows,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }


def atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False, dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def self_test() -> None:
    positive = profit_summary({"revenue_growth": 0.25, "operating_margin": 0.12, "net_margin": 0.08})
    negative = profit_summary({"revenue_growth": -0.1, "net_margin": -0.05})
    if "營收年增 +25.0%" not in positive or "淨利率 8.0%" not in positive:
        raise Top20ReportError("Profit-summary positive fixture failed")
    if not negative.startswith("虧損；"):
        raise Top20ReportError("Profit-summary loss fixture failed")
    if profit_summary({}) != "SEC 可用獲利指標不足":
        raise Top20ReportError("Profit-summary missing-data fixture failed")
    if LONG_TERM_WINDOW_DAYS != 730 or SHORT_TERM_WINDOW_DAYS != 183:
        raise Top20ReportError("Return-window constants changed")
    print("V212_TOP20_REPORT_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return 0
        document = build()
        atomic_write(args.output, document)
        print(json.dumps({"status": "PASS", "records": len(document["records"]), "output": str(args.output)}, ensure_ascii=False, indent=2))
        return 0
    except (Top20ReportError, snapshot.SnapshotError, base.PipelineError, OSError, ValueError) as exc:
        print(f"V2.1.2 Top 20 report build failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
