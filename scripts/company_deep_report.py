#!/usr/bin/env python3
"""Data-driven company deep report (operator rule 2026-09-25: detailed, nothing hand-written).

Every section is computed from primary data at run time and cites it:

- business      latest 10-K / 20-F business excerpt and validated phrase (company_business_profile)
- momentum      single-quarter revenue, gross and operating margin versus the same quarter a
                year earlier (SEC XBRL company facts, calendar ``frame`` tags)
- visibility    remaining performance obligations (RPO) now versus a year earlier
- capacity      latest fiscal-year capital expenditure and its share of revenue
- balance sheet cash, long-term debt and diluted-share change (dilution)
- industry      the company's SIC industry signals and phase from the data-driven rotation
- phase         thesis_phase (company scope) from the company's own and industry signals,
                with the next review date and the falsifiers that would flip it
- orders        if the signed orders are delivered on the schedule the latest 10-Q/10-K discloses
                (order_timing): contracted revenue for 6M/1Y/2Y versus the current run rate, and a
                revenue/price growth floor only where that coverage exceeds 100% (stated premises)

Missing facts are reported as missing; no estimate, target price or probability is produced.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import thesis_phase  # noqa: E402

OUTPUT_PATH = ROOT / "data" / "cache" / "company_deep_reports_latest.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
REVENUE_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")
TAGS = {
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "rpo": ("RevenueRemainingPerformanceObligation",),
    "inventory": ("InventoryNet",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
             "CashAndDueFromBanks"),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations",
                       "LongTermDebtAndFinanceLeasesNoncurrent", "OtherLongTermDebtNoncurrent"),
    "diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsForCapitalImprovements"),
}
Fetch = Callable[[str], bytes]


def _rows(facts: Mapping[str, Any], tags: Sequence[str], unit: str) -> list[dict[str, Any]]:
    """Rows of the tag the company still reports most recently (issuers switch tags over the years)."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    best: list[dict[str, Any]] = []
    for tag in tags:
        rows = [dict(row, tag=tag) for row in ((gaap.get(tag) or {}).get("units") or {}).get(unit, [])
                if isinstance(row.get("val"), (int, float))]
        if rows and (not best or max(r["end"] for r in rows) > max(r["end"] for r in best)):
            best = rows
    return best


def _by_frame(rows: Sequence[Mapping[str, Any]], instant: bool) -> dict[str, dict[str, Any]]:
    pattern = r"CY\d{4}Q[1-4]I" if instant else r"CY\d{4}Q[1-4]"
    frames: dict[str, dict[str, Any]] = {}
    for row in rows:
        frame = row.get("frame")
        if isinstance(frame, str) and re.fullmatch(pattern, frame):
            frames[frame] = dict(row)
    return frames


def _year_ago(frame: str) -> str:
    return f"CY{int(frame[2:6]) - 1}{frame[6:]}"


def _latest_pair(frames: Mapping[str, Mapping[str, Any]]) -> tuple[dict | None, dict | None]:
    if not frames:
        return None, None
    latest_key = max(frames, key=lambda key: (int(key[2:6]), key[7]))
    return dict(frames[latest_key]), (dict(frames[_year_ago(latest_key)]) if _year_ago(latest_key) in frames else None)


def _pct(now: float | None, prior: float | None) -> float | None:
    if now is None or prior is None or prior == 0:
        return None
    return round((now / prior - 1) * 100, 2)


def extract_metrics(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Same-quarter comparisons from calendar frames; missing facts stay None."""
    revenue_frames = _by_frame(_rows(facts, REVENUE_TAGS, "USD"), instant=False)
    revenue, revenue_prior = _latest_pair(revenue_frames)
    frame = revenue["frame"] if revenue else None
    out: dict[str, Any] = {"quarter_frame": frame, "quarter_end": revenue["end"] if revenue else None,
                           "revenue": revenue and revenue["val"], "revenue_prior": revenue_prior and revenue_prior["val"],
                           "revenue_accession": revenue and revenue.get("accn")}
    out["revenue_yoy_pct"] = _pct(out["revenue"], out["revenue_prior"])

    def quarter_value(key: str, when: str | None) -> float | None:
        if not when:
            return None
        row = _by_frame(_rows(facts, TAGS[key], "USD"), instant=False).get(when)
        return row["val"] if row else None

    for key in ("gross_profit", "operating_income", "net_income"):
        out[key] = quarter_value(key, frame)
        out[f"{key}_prior"] = quarter_value(key, _year_ago(frame) if frame else None)
    for margin, key in (("gross_margin", "gross_profit"), ("operating_margin", "operating_income")):
        now = out[key] / out["revenue"] * 100 if out[key] is not None and out["revenue"] else None
        prior = out[f"{key}_prior"] / out["revenue_prior"] * 100 if out[f"{key}_prior"] is not None and out["revenue_prior"] else None
        out[f"{margin}_pct"] = None if now is None else round(now, 2)
        out[f"{margin}_change_pp"] = None if now is None or prior is None else round(now - prior, 2)
    for key in ("rpo", "inventory", "cash", "long_term_debt"):
        latest, prior = _latest_pair(_by_frame(_rows(facts, TAGS[key], "USD"), instant=True))
        out[key] = latest and latest["val"]
        out[f"{key}_tag"] = latest and latest.get("tag")
        out[f"{key}_as_of"] = latest and latest["end"]
        out[f"{key}_yoy_pct"] = _pct(latest and latest["val"], prior and prior["val"])
    shares, shares_prior = _latest_pair(_by_frame(_rows(facts, TAGS["diluted_shares"], "shares"), instant=False))
    out["diluted_shares"] = shares and shares["val"]
    out["dilution_yoy_pct"] = _pct(shares and shares["val"], shares_prior and shares_prior["val"])
    annual = [row for row in _rows(facts, TAGS["capex"], "USD") if row.get("fp") == "FY" and row.get("form") in ("10-K", "20-F")]
    capex = max(annual, key=lambda row: row["end"]) if annual else None
    fy_revenue = [row for row in _rows(facts, REVENUE_TAGS, "USD") if capex and row.get("end") == capex["end"] and row.get("fp") == "FY"]
    out["capex_fy"] = capex and capex["val"]
    out["capex_fy_end"] = capex and capex["end"]
    out["capex_share_of_revenue_pct"] = (round(capex["val"] / fy_revenue[0]["val"] * 100, 2)
                                         if capex and fy_revenue and fy_revenue[0]["val"] else None)
    out["inventory_minus_revenue_pp"] = (round(out["inventory_yoy_pct"] - out["revenue_yoy_pct"], 2)
                                         if out["inventory_yoy_pct"] is not None and out["revenue_yoy_pct"] is not None else None)
    return out


PHASE_ZH = {"INSUFFICIENT_EVIDENCE": "資料不足", "DISCOVERY": "初現（單一來源）", "EARLY_VALIDATION": "驗證中（雙來源確認）",
            "COMMERCIAL_VALIDATION": "商業驗證（公司開始獲利）", "INSTITUTIONAL_VALIDATION": "法人進場", "CONSENSUS": "共識擁擠",
            "RELIEVING": "緩解中", "BROKEN": "已失效"}
FAMILY_ZH = {"sec_issuer": "SEC 公司申報", "sec_issuer_inventory": "SEC 公司存貨", "bls_ppi": "BLS 生產者物價",
             "taiwan_monthly_revenue": "臺灣上市櫃同業月營收", "sec_xbrl_issuers": "SEC 產業成員申報"}


def _families(values: Sequence[str]) -> str:
    return "、".join(FAMILY_ZH.get(v, v) for v in values) or "無"


def _tag(tag: str | None) -> str:
    return f"（XBRL {tag}）" if tag else ""


def _money(value: float | None) -> str:
    if value is None:
        return "未申報"
    return f"US${value / 1e9:,.2f}B" if abs(value) >= 1e8 else f"US${value / 1e6:,.1f}M"


def _pctx(value: float | None, suffix: str = "%") -> str:
    return "未申報" if value is None else f"{value:+.1f}{suffix}"


def company_signals(ticker: str, metrics: Mapping[str, Any], cik: str, industry: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    url = FACTS_URL.format(cik=cik)
    end = metrics.get("quarter_end")
    signals: list[dict[str, Any]] = []
    if metrics.get("rpo_yoy_pct") is not None and metrics.get("rpo_as_of"):
        value = metrics["rpo_yoy_pct"]
        direction = "UP" if value >= 10 else "DOWN" if value <= -10 else "FLAT"
        signals.append({"signal_id": f"{ticker}:RPO", "kind": "BACKLOG", "as_of": metrics["rpo_as_of"], "direction": direction,
                        "value": value, "evidence_family": "sec_issuer", "source_url": url})
    if metrics.get("gross_margin_change_pp") is not None and end:
        value = metrics["gross_margin_change_pp"]
        direction = "UP" if value >= 1 else "DOWN" if value <= -1 else "FLAT"
        signals.append({"signal_id": f"{ticker}:MARGIN", "kind": "COMPANY_MARGIN", "as_of": end, "direction": direction,
                        "value": value, "evidence_family": "sec_issuer", "source_url": url})
    if metrics.get("dilution_yoy_pct") is not None and end and metrics["dilution_yoy_pct"] > 0:
        signals.append({"signal_id": f"{ticker}:DILUTION", "kind": "DILUTION", "as_of": end,
                        "value": metrics["dilution_yoy_pct"], "evidence_family": "sec_issuer", "source_url": url})
    gap = metrics.get("inventory_minus_revenue_pp")
    if gap is not None and gap >= 10 and metrics.get("inventory_as_of"):
        signals.append({"signal_id": f"{ticker}:INVENTORY", "kind": "INVENTORY_BUILD", "as_of": metrics["inventory_as_of"],
                        "value": gap, "evidence_family": "sec_issuer_inventory", "source_url": url})
    for signal in (industry or {}).get("signals", []):
        if signal["kind"] in ("PRICE", "SUPPLIER_REVENUE"):  # same industry families as the potential ranking
            signals.append(dict(signal, signal_id=f"{ticker}:{signal['signal_id']}"))
    return signals


HORIZONS = ((6, "m6", "6M"), (12, "m12", "1Y"), (24, "m24", "2Y"))
ORDER_PREMISES = ("目前營收水準＝最近一季營收 × 期間季數", "只計已簽約訂單（RPO）依揭露時程認列，未計新接訂單，因此是下限",
                  "股價對應成長假設利潤率、稀釋後股數與本益比不變")


def order_scenario(metrics: Mapping[str, Any], timing: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """If the signed orders are delivered on the disclosed schedule: contracted revenue per horizon versus the
    current run rate. A growth floor exists only where the contracted revenue alone exceeds the run rate."""
    if not timing:
        return None
    base = {"status": timing.get("status"), "form": timing.get("form"), "filed": timing.get("filed"), "url": timing.get("url")}
    if timing.get("status") != "DISCLOSED":
        return base
    rpo, revenue = metrics.get("rpo"), metrics.get("revenue")
    rpo_as_of, quarter_end = metrics.get("rpo_as_of"), metrics.get("quarter_end")
    if not rpo or not revenue or revenue <= 0 or not rpo_as_of or not quarter_end:
        return {**base, "status": "INPUTS_MISSING"}
    if abs((date.fromisoformat(rpo_as_of) - date.fromisoformat(quarter_end)).days) > 45:
        return {**base, "status": "PERIOD_MISMATCH"}
    report_date = timing.get("report_date")
    if report_date and abs((date.fromisoformat(report_date) - date.fromisoformat(rpo_as_of)).days) > 45:
        return {**base, "status": "PERIOD_MISMATCH"}
    horizons: dict[str, Any] = {}
    for months, key, _ in HORIZONS:
        share = (timing.get("schedule") or {}).get(key)
        if share is None:
            horizons[key] = None
            continue
        contracted, run_rate = rpo * share / 100, revenue * months / 3
        coverage = round(contracted / run_rate * 100, 1)
        horizons[key] = {"share_pct": share, "contracted": round(contracted), "run_rate": round(run_rate), "coverage_pct": coverage,
                         "floor_growth_pct": round(coverage - 100, 1) if coverage > 100 else None}
    return {**base, "rpo": rpo, "rpo_as_of": rpo_as_of, "quarter_revenue": revenue, "horizons": horizons,
            "premises": list(ORDER_PREMISES) + list((timing.get("schedule") or {}).get("premises") or [])}


def _coverage(value: float) -> str:
    return f"{value:.1f}%" if value < 10 else f"{value:.0f}%"  # 0.3% must not read as 0%


def order_text(orders: Mapping[str, Any] | None) -> str:
    if not orders:
        return "未取得最新 10-Q／10-K，無訂單實現情境"
    status = orders.get("status")
    if status == "NO_PERIODIC_FILING":
        return "沒有 10-Q／10-K 定期報告，無訂單實現情境"
    if status == "NOT_DISCLOSED":
        return f"最新 {orders.get('form')}（{orders.get('filed')}）未揭露 RPO 認列時程；不推估訂單實現情境"
    if status == "INPUTS_MISSING":
        return f"{orders.get('form')}（{orders.get('filed')}）有認列時程，但 XBRL 缺少 RPO 或同季營收；不推估"
    if status == "PERIOD_MISMATCH":
        return f"{orders.get('form')}（{orders.get('filed')}）的認列時程與 XBRL RPO／營收期間不一致；不混用"
    parts, outcomes = [], []
    for _, key, label in HORIZONS:
        row = orders["horizons"].get(key)
        if row is None:
            outcomes.append(f"{label} 未揭露")
            continue
        parts.append(f"{label} 認列 {row['share_pct']:.1f}% → {_money(row['contracted'])}（目前水準的 {_coverage(row['coverage_pct'])}）")
        outcomes.append(f"{label} 營收與股價成長下限 {row['floor_growth_pct']:+.1f}%" if row["floor_growth_pct"] is not None
                        else f"{label} 已簽約僅支撐 {_coverage(row['coverage_pct'])}，其餘需新訂單")
    interpolation = [p for p in orders["premises"][len(ORDER_PREMISES):]]
    return (f"依 {orders['form']}（{orders['filed']}）揭露的認列時程，RPO {_money(orders['rpo'])}（{orders['rpo_as_of']}）："
            + "；".join(parts) + f"。目前營收水準＝最近一季 {_money(orders['quarter_revenue'])} × 期間季數。若訂單如期實現，"
            + "且利潤率、稀釋後股數與本益比不變：" + "；".join(outcomes) + "。未計新接訂單，屬下限"
            + (f"（{'；'.join(interpolation)}）" if interpolation else ""))


def compact_orders(orders: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Coverage and growth floor per horizon for the potential ranking card; None when not computable."""
    if not orders or orders.get("status") != "DISCLOSED":
        return None
    pick = lambda field: {key: (row or {}).get(field) for key, row in orders["horizons"].items()}
    return {"as_of": orders["rpo_as_of"], "form": orders["form"], "filed": orders["filed"],
            "coverage_pct": pick("coverage_pct"), "floor_growth_pct": pick("floor_growth_pct")}


def industry_for(sic: str | None, rotation: Mapping[str, Any] | None, config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not sic or not rotation or not config:
        return None
    ids = [row["industry_id"] for row in config.get("industries", []) if sic in row.get("sic", [])]
    for row in rotation.get("industries", []):
        if row["industry_id"] in ids:
            return row
    return None


def build_report(ticker: str, cik: str, *, facts: Mapping[str, Any], submissions: Mapping[str, Any],
                 business: Mapping[str, Any] | None, rotation: Mapping[str, Any] | None,
                 rotation_config: Mapping[str, Any] | None, today: date, timing: Mapping[str, Any] | None = None) -> dict[str, Any]:
    metrics = extract_metrics(facts)
    orders = order_scenario(metrics, timing)
    sic = str(submissions.get("sic") or "") or None
    industry = industry_for(sic, rotation, rotation_config)
    signals = company_signals(ticker, metrics, cik, industry)
    phase = thesis_phase.assess_phase(signals, today, scope="company")
    frame = metrics.get("quarter_frame") or "未知季度"
    name = facts.get("entityName") or submissions.get("name") or ticker
    sections = [
        ("公司業務", (f"{business['phrase_zh']}（{business.get('form')} {business.get('filed')}，SEC EDGAR）"
                   if business and business.get("phrase_zh") else "最新年報業務描述尚未完成翻譯核對")),
        ("營運動能", (f"{frame} 營收 {_money(metrics['revenue'])}，年增 {_pctx(metrics['revenue_yoy_pct'])}；"
                   f"毛利率 {_pctx(metrics['gross_margin_pct'], '%').lstrip('+')}（年變化 {_pctx(metrics['gross_margin_change_pp'], ' 個百分點')}）；"
                   f"營業利益率 {_pctx(metrics['operating_margin_pct'], '%').lstrip('+')}（年變化 {_pctx(metrics['operating_margin_change_pp'], ' 個百分點')}）")),
        ("訂單能見度", (f"剩餘履約義務（RPO）{_money(metrics['rpo'])}（{metrics['rpo_as_of']}），年增 {_pctx(metrics['rpo_yoy_pct'])}"
                    if metrics.get("rpo") is not None else "未申報剩餘履約義務（RPO），訂單能見度無法量化")),
        ("訂單實現情境", order_text(orders)),
        ("產能與資本支出", (f"最近會計年度資本支出 {_money(metrics['capex_fy'])}（年度截至 {metrics['capex_fy_end']}），占營收 {_pctx(metrics['capex_share_of_revenue_pct']).lstrip('+')}"
                       if metrics.get("capex_fy") is not None else "未申報年度資本支出")),
        ("資產負債與稀釋", (f"現金 {_money(metrics['cash'])}{_tag(metrics.get('cash_tag'))}、長期負債 {_money(metrics['long_term_debt'])}{_tag(metrics.get('long_term_debt_tag'))}；"
                       f"稀釋後加權股數年變化 {_pctx(metrics['dilution_yoy_pct'])}；"
                       + (f"存貨年增 {_pctx(metrics['inventory_yoy_pct'])}，較營收成長{'高' if metrics['inventory_minus_revenue_pp'] > 0 else '低'} {abs(metrics['inventory_minus_revenue_pp']):.1f} 個百分點"
                          if metrics.get("inventory_minus_revenue_pp") is not None else "存貨與營收可比資料不足"))),
        ("所屬產業訊號", (f"{industry['name_zh']}：資料階段 {PHASE_ZH.get(industry['phase']['phase'], industry['phase']['phase'])}，BLS PPI 年增 {_pctx(industry['price']['yoy_pct'])}，"
                       f"成員 RPO 年增 {_pctx(industry['backlog']['yoy_pct'])}（{industry['quarter']}）"
                       + (f"，臺灣上市櫃同業 {industry['taiwan']['count']} 家 {industry['taiwan']['month']} 營收年增 {_pctx(industry['taiwan']['yoy_pct'])}"
                          if (industry.get("taiwan") or {}).get("yoy_pct") is not None else "")
                       if industry else f"SIC {sic or '未知'} 不在產業輪替範圍或輪替資料不可用")),
        ("資料階段", (f"{PHASE_ZH.get(phase['phase'], phase['phase'])}（吃緊來源：{_families(phase['constraint_families'])}；"
                   f"公司捕捉：{_families(phase['capture_families'])}；緩解：{_families(phase['relief_families'])}）"
                   f"；下次檢查 {phase['next_review_at'] or '下一份財報'}"
                   + ("；稀釋疑慮" if phase["dilution_overhang"] else ""))),
        ("證偽條件", "RPO 年增降至 -10% 以下；毛利率年減 1 個百分點以上；稀釋後股數年增 20% 以上；存貨成長超過營收 10 個百分點；所屬產業 PPI 年增降至 -3% 以下"),
    ]
    references = [{"source": "SEC XBRL company facts", "url": FACTS_URL.format(cik=cik), "period": frame},
                  {"source": "SEC EDGAR submissions", "url": SUBMISSIONS_URL.format(cik=cik)}]
    if orders and orders.get("url"):
        references.append({"source": f"SEC {orders.get('form')} RPO recognition timing", "url": orders["url"], "period": orders.get("filed")})
    if business and business.get("url"):
        references.append({"source": f"SEC {business.get('form')} business section", "url": business["url"], "period": business.get("filed")})
    if industry:
        references.extend({"source": f"BLS PPI {row['series']}", "url": f"https://data.bls.gov/timeseries/{row['series']}", "period": row["month"]}
                          for row in industry["price"]["series"])
    return {"schema_version": 1, "ticker": ticker, "cik": cik, "name": name, "sic": sic,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "as_of": today.isoformat(),
            "metrics": metrics, "signals": signals, "phase": phase, "orders": orders,
            "sections": [{"title": title, "text": text} for title, text in sections], "source_references": references,
            "boundary": "官方資料的計算與整理；不是投資建議、價格預測或機率"}


def build_reports(tickers: Mapping[str, str], fetch: Fetch, *, today: date, business_loader: Callable[[str], Mapping | None] | None = None,
                  rotation: Mapping[str, Any] | None = None, rotation_config: Mapping[str, Any] | None = None,
                  timing_loader: Callable[[str, Mapping[str, Any]], Mapping | None] | None = None) -> dict[str, Any]:
    reports, failures = {}, {}
    for ticker, cik in tickers.items():
        try:
            facts = json.loads(fetch(FACTS_URL.format(cik=cik)))
            submissions = json.loads(fetch(SUBMISSIONS_URL.format(cik=cik)))
            business = business_loader(cik) if business_loader else None
            timing = timing_loader(cik, submissions) if timing_loader else None
            reports[ticker] = build_report(ticker, cik, facts=facts, submissions=submissions, business=business,
                                           rotation=rotation, rotation_config=rotation_config, today=today, timing=timing)
        except Exception as error:
            failures[ticker] = type(error).__name__
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "as_of": today.isoformat(), "reports": reports, "failures": failures, "publication_eligible": False}


TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
TICKERS_CACHE = ROOT / "data" / "cache" / "v21" / "company_tickers_exchange.json"


def ticker_ciks(fetch: Fetch, *, today: date, cache: Path = TICKERS_CACHE, max_age_days: int = 7) -> dict[str, str]:
    """Official SEC ticker -> CIK map, cached for a week."""
    raw = None
    try:
        if date.fromtimestamp(cache.stat().st_mtime) >= today - timedelta(days=max_age_days):
            raw = cache.read_bytes()
    except OSError:
        pass
    if raw is None:
        raw = fetch(TICKERS_URL)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(raw)
    exchange = json.loads(raw)
    fields = exchange["fields"]
    return {str(row[fields.index("ticker")]).upper(): str(row[fields.index("cik")]).zfill(10) for row in exchange["data"]}


def sealed_tickers(snapshots_dir: Path | None = None) -> list[str]:
    """Tickers ranked in the newest sealed run (the companies LINE can open a deep report for); the snapshot root
    is the publisher's II_SNAPSHOT_ROOT setting."""
    if snapshots_dir is None:
        snapshots_dir = ROOT / (os.environ.get("II_SNAPSHOT_ROOT", "").strip() or "state/v213-snapshots")
    runs = sorted((p for p in snapshots_dir.glob("*/summary.json")), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in runs:
        try:
            return [str(row[1]) for row in json.loads(path.read_text(encoding="utf-8")).get("ranked", [])]
        except (OSError, ValueError, IndexError):
            continue
    return []


def load_reports(path: Path = OUTPUT_PATH, *, tickers: Sequence[str], max_age_days: int = 7,
                 today: date | None = None) -> dict[str, dict[str, Any]]:
    """Compact reports for sealing: only fields the Worker renders; stale or missing files give none."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if (today or date.today()) - date.fromisoformat(document["as_of"]) > timedelta(days=max_age_days):
            return {}
    except (OSError, ValueError, KeyError):
        return {}
    compact = {}
    for ticker in tickers:
        report = (document.get("reports") or {}).get(ticker)
        if not report:
            continue
        compact[ticker] = {"ticker": ticker, "name": report["name"], "as_of": report["as_of"], "boundary": report["boundary"],
                           "phase": {"phase": report["phase"]["phase"], "next_review_at": report["phase"].get("next_review_at")},
                           "sections": [{"title": s["title"], "text": s["text"].replace("\n", " ")[:700]} for s in report["sections"]],
                           "source_references": report["source_references"][:20],
                           "kpis": kpis(report.get("metrics") or {}, report.get("orders")),
                           "orders": compact_orders(report.get("orders"))}
    return compact


# Tiles on the LINE report: (label <= 12 chars, metric, signed change?, period field). Values come from the same metrics
# the sections are written from; a missing fact stays null and renders as 未申報.
KPI_FIELDS = (("營收年增", "revenue_yoy_pct", True, "quarter_frame"), ("毛利率", "gross_margin_pct", False, "quarter_frame"),
              ("營業利益率", "operating_margin_pct", False, "quarter_frame"), ("RPO 年增", "rpo_yoy_pct", True, "rpo_as_of"),
              ("稀釋後股數年增", "dilution_yoy_pct", True, "quarter_frame"), ("資本支出/營收", "capex_share_of_revenue_pct", False, "capex_fy_end"))


def kpis(metrics: Mapping[str, Any], orders: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    out = []
    for label, key, signed, period_key in KPI_FIELDS:
        value = metrics.get(key)
        row: dict[str, Any] = {"label": label, "value": round(float(value), 2) if isinstance(value, (int, float)) else None,
                               "unit": "%", "signed": signed}
        if metrics.get(period_key):
            row["period"] = str(metrics[period_key])[:20]
        out.append(row)
    one_year = ((orders or {}).get("horizons") or {}).get("m12") if (orders or {}).get("status") == "DISCLOSED" else None
    if one_year:
        out.append({"label": "1Y 已簽約覆蓋", "value": one_year["coverage_pct"], "unit": "%", "signed": False,
                    "period": str(orders["rpo_as_of"])[:20]})
    return out


def cached_business(cik: str) -> Mapping[str, Any] | None:
    """Business profile from the per-accession cache written by company_business_profile (no network)."""
    import company_business_profile as profile
    try:
        return json.loads((profile.CACHE_ROOT / f"CIK{cik}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="read SEC data now (fair access)")
    parser.add_argument("--tickers", help="comma-separated tickers with SEC filings (default: newest sealed ranking)")
    parser.add_argument("--if-older-than-hours", type=float, help="skip when the current file is newer than this")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    if not args.refresh:
        parser.error("--refresh is required; no implicit network requests")
    if args.if_older_than_hours is not None and args.output.exists():
        age_hours = (datetime.now().timestamp() - args.output.stat().st_mtime) / 3600
        if age_hours < args.if_older_than_hours:
            print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age_hours, 1)}))
            return 0
    import company_business_profile as profile
    import industry_rotation
    import order_timing
    from sec_contact_headers import sec_identity_headers
    if args.tickers:
        wanted = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:  # the sealed ranking plus the data-driven potential ranking, in that order, without duplicates
        rotation_doc = industry_rotation.load_rotation() or {}
        wanted = list(dict.fromkeys(sealed_tickers() + [r["ticker"] for r in rotation_doc.get("company_ranking", [])]))
    fetch = profile.sec_fetcher(sec_identity_headers())
    ciks = ticker_ciks(fetch, today=date.today())
    try:
        translate = profile.local_translator()
    except (OSError, ValueError, KeyError):
        translate = None

    def timing(cik: str, submissions: Mapping[str, Any]) -> Mapping[str, Any] | None:
        # Per-accession cache: the 10-Q/10-K text is read again only when a new periodic filing appears.
        try:
            return order_timing.resolve_timing(cik, submissions, fetch)
        except Exception:
            return None

    def business(cik: str) -> Mapping[str, Any] | None:
        # Per-accession cache; only a new annual report triggers a (loopback) translation.
        try:
            return profile.resolve_business_profile(cik, fetch, translate)
        except Exception:
            return cached_business(cik)

    document = build_reports({t: ciks[t] for t in wanted if t in ciks}, fetch, today=date.today(), business_loader=business,
                             rotation=industry_rotation.load_rotation(), rotation_config=industry_rotation.load_config(),
                             timing_loader=timing)
    document["not_sec_listed"] = [t for t in wanted if t not in ciks]
    industry_rotation.atomic_write(args.output, document)
    print(json.dumps({"status": "OK", "reports": len(document["reports"]), "failures": document["failures"],
                      "not_sec_listed": document["not_sec_listed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
