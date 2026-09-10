#!/usr/bin/env python3
"""Build the v2.1.2 five-field public Top 20 report.

The LINE presentation intentionally exposes only five fields:
股票 / 長期投資報酬率（近2年年化） / 短期投資報酬率（近6個月） / 行業別 / 獲利簡述

Definitions are kept in the machine payload as well as annotated in the two
return-column labels:
- long_term_return_pct: trailing ~2-year annualized price CAGR from adjusted closes.
- short_term_return_pct: trailing ~6-month adjusted-close price return.
- profit_summary: deterministic SEC-EDGAR companyfacts summary (revenue growth,
  operating margin and net margin when available).

Market-return and industry observations use public yfinance/Yahoo observations;
industry names are normalized to Traditional Chinese for LINE presentation.
Profitability uses SEC EDGAR. No portfolio, account, cost basis or brokerage data
is read or emitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_v21_public_snapshot as snapshot
import v21_serenity_top20 as base
from historical_return_evidence import calculate_return_evidence, legacy_return_pair, ReturnEvidenceError

TOP20_PATH = ROOT / "data" / "cache" / "top20_public_latest.json"
OUTPUT_PATH = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
LONG_TERM_WINDOW_DAYS = 730
SHORT_TERM_WINDOW_DAYS = 183
# Compatibility constants only; selection uses complete calendar-month targets.
MIN_LONG_TERM_ELAPSED_DAYS = 730
MIN_SHORT_TERM_ELAPSED_DAYS = 181
DISPLAY_COLUMNS = [
    "股票",
    "長期投資報酬率（近2年年化）",
    "短期投資報酬率（近6個月）",
    "行業別",
    "獲利簡述",
]

INDUSTRY_ZH_TW = {
    "Semiconductors": "半導體",
    "Semiconductor Equipment & Materials": "半導體設備與材料",
    "Communication Equipment": "通訊設備",
    "Computer Hardware": "電腦硬體",
    "Electronic Components": "電子零組件",
    "Consumer Electronics": "消費電子",
    "Software - Infrastructure": "基礎架構軟體",
    "Software - Application": "應用軟體",
    "Information Technology Services": "資訊科技服務",
    "Internet Content & Information": "網路內容與資訊",
    "Scientific & Technical Instruments": "科學與技術儀器",
    "Specialty Industrial Machinery": "專用工業機械",
    "Electrical Equipment & Parts": "電氣設備與零組件",
    "Data Storage": "資料儲存",
    "Telecom Services": "電信服務",
    "Electronic Gaming & Multimedia": "電子遊戲與多媒體",
    "Diagnostics & Research": "診斷與研究",
    "Biotechnology": "生物科技",
    "Medical Devices": "醫療器材",
    "Financial Data & Stock Exchanges": "金融資料與證券交易所",
    "Credit Services": "信貸服務",
    "Banks - Diversified": "綜合銀行",
    "Asset Management": "資產管理",
    "Capital Markets": "資本市場",
    "Specialty Chemicals": "特用化學品",
    "Aerospace & Defense": "航太與國防",
    "Auto Manufacturers": "汽車製造",
    "Internet Retail": "網路零售",
    "Restaurants": "餐飲",
    "Utilities - Regulated Electric": "受監管電力公用事業",
    "Oil & Gas E&P": "石油與天然氣勘探生產",
    "Farm & Heavy Construction Machinery": "農業與重型工程機械",
    "Industrial Distribution": "工業通路",
    "Consulting Services": "顧問服務",
    "Technology": "科技",
    "Communication Services": "通訊服務",
    "Industrials": "工業",
    "Financial Services": "金融服務",
    "Healthcare": "醫療保健",
    "Consumer Cyclical": "非必需消費",
    "Consumer Defensive": "必需消費",
    "Energy": "能源",
    "Basic Materials": "基礎材料",
    "Utilities": "公用事業",
    "Real Estate": "房地產",
}


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


def translate_industry(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "未分類"
    direct = INDUSTRY_ZH_TW.get(raw)
    if direct:
        return direct
    text = raw.casefold()
    keyword_rules = (
        (("semiconductor",), "半導體"),
        (("communication equipment", "telecom equipment"), "通訊設備"),
        (("computer hardware", "hardware"), "電腦硬體"),
        (("electronic component",), "電子零組件"),
        (("software",), "軟體"),
        (("data storage", "storage"), "資料儲存"),
        (("internet",), "網路服務"),
        (("biotech",), "生物科技"),
        (("medical", "health"), "醫療保健"),
        (("bank",), "銀行"),
        (("financial", "capital market", "asset management"), "金融服務"),
        (("aerospace", "defense"), "航太與國防"),
        (("chemical",), "化學材料"),
        (("energy", "oil", "gas"), "能源"),
        (("utility",), "公用事業"),
        (("real estate",), "房地產"),
        (("restaurant",), "餐飲"),
        (("automotive", "auto manufacturer"), "汽車產業"),
        (("industrial", "machinery"), "工業設備"),
        (("technology",), "科技"),
    )
    for needles, translated in keyword_rules:
        if any(needle in text for needle in needles):
            return translated
    if all(ord(char) < 128 for char in raw):
        return "其他產業"
    return raw[:100]


def _history_return_evidence(history: Any) -> dict[str, Any]:
    if history is None or "Close" not in history:
        return calculate_return_evidence([])
    # Do not drop a missing last price and silently move the observation clock.
    return calculate_return_evidence([(stamp.date(), price) for stamp, price in history["Close"].items()])


def _returns_from_history(history: Any) -> tuple[float | None, float | None]:
    try:
        return legacy_return_pair(_history_return_evidence(history))
    except (ReturnEvidenceError, TypeError, ValueError, AttributeError, OverflowError):
        return None, None


def _market_observation(ticker: str, fallback_industry: str, *, evidence_sink: dict | None = None) -> tuple[float | None, float | None, str]:
    if evidence_sink is not None:
        evidence_sink.update(status="UNAVAILABLE", publication_eligible=False, provider="yfinance", ticker=ticker)
    try:
        import yfinance as yf
    except ImportError as exc:
        raise Top20ReportError("Verified runtime lacks yfinance") from exc
    try:
        obj = yf.Ticker(ticker)
        history = obj.history(period="3y", interval="1d", auto_adjust=True)
        evidence = _history_return_evidence(history)
        long_term, short_term = legacy_return_pair(evidence)
        if evidence_sink is not None:
            evidence_sink.update(evidence)
            evidence_sink.update(
                status=("CALCULATED_NOT_QUALIFIED" if any(w["status"] == "AVAILABLE" for w in evidence["windows"].values()) else "NO_COMPLETE_RETURN_WINDOW"),
                retrieved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                request={"period": "3y", "interval": "1d", "auto_adjust": True},
            )
        industry = ""
        try:
            info = obj.info
            if isinstance(info, dict):
                industry = str(info.get("industry") or info.get("sector") or "").strip()
        except Exception:
            pass
        return long_term, short_term, translate_industry(industry or fallback_industry)
    except Exception:
        return None, None, translate_industry(fallback_industry)


def build(*, top20_path: Path = TOP20_PATH, return_evidence_sink: dict | None = None) -> dict[str, Any]:
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
        if return_evidence_sink is None:
            long_term, short_term, industry = _market_observation(ticker, str(item.get("category") or ""))
        else:
            observation: dict[str, Any] = {}
            long_term, short_term, industry = _market_observation(ticker, str(item.get("category") or ""), evidence_sink=observation)
            return_evidence_sink[ticker] = observation
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
        "display_columns": DISPLAY_COLUMNS,
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
    if translate_industry("Semiconductors") != "半導體":
        raise Top20ReportError("Industry localization fixture failed")
    if translate_industry("Communication Equipment") != "通訊設備":
        raise Top20ReportError("Communication-equipment localization fixture failed")
    if DISPLAY_COLUMNS[1] != "長期投資報酬率（近2年年化）" or DISPLAY_COLUMNS[2] != "短期投資報酬率（近6個月）":
        raise Top20ReportError("Return-window display labels failed")
    print("V212_TOP20_REPORT_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--return-evidence-output", type=Path, help="Local unqualified calculation sidecar; never a publication payload")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return 0
        evidence_output = args.return_evidence_output or args.output.with_name(args.output.stem + ".return-evidence-candidate.json")
        if evidence_output.resolve() == args.output.resolve():
            raise Top20ReportError("Report and return evidence paths must differ")
        observations: dict[str, Any] = {}
        document = build(return_evidence_sink=observations)
        atomic_write(args.output, document)
        atomic_write(evidence_output, {
            "schema_version": 1, "status": "CANDIDATE_NOT_PUBLICATION_QUALIFIED",
            "publication_eligible": False, "provider_scope": "public_only",
            "owner_watchlist_inherited": False, "generated_at": document["generated_at"],
            "report_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            "records": observations,
        })
        print(json.dumps({"status": "PASS", "records": len(document["records"]), "output": str(args.output)}, ensure_ascii=False, indent=2))
        return 0
    except (Top20ReportError, snapshot.SnapshotError, base.PipelineError, OSError, ValueError) as exc:
        print(f"V2.1.2 Top 20 report build failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
