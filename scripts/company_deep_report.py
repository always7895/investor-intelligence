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

Missing facts are reported as missing; no estimate, target price or probability is produced.
"""
from __future__ import annotations

import argparse
import json
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
        if signal["kind"] == "PRICE":  # the industry's BLS price signal is an independent family
            signals.append(dict(signal, signal_id=f"{ticker}:{signal['signal_id']}"))
    return signals


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
                 rotation_config: Mapping[str, Any] | None, today: date) -> dict[str, Any]:
    metrics = extract_metrics(facts)
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
        ("產能與資本支出", (f"最近會計年度資本支出 {_money(metrics['capex_fy'])}（年度截至 {metrics['capex_fy_end']}），占營收 {_pctx(metrics['capex_share_of_revenue_pct']).lstrip('+')}"
                       if metrics.get("capex_fy") is not None else "未申報年度資本支出")),
        ("資產負債與稀釋", (f"現金 {_money(metrics['cash'])}、長期負債 {_money(metrics['long_term_debt'])}；"
                       f"稀釋後加權股數年變化 {_pctx(metrics['dilution_yoy_pct'])}；"
                       + (f"存貨年增 {_pctx(metrics['inventory_yoy_pct'])}，較營收成長{'高' if metrics['inventory_minus_revenue_pp'] > 0 else '低'} {abs(metrics['inventory_minus_revenue_pp']):.1f} 個百分點"
                          if metrics.get("inventory_minus_revenue_pp") is not None else "存貨與營收可比資料不足"))),
        ("所屬產業訊號", (f"{industry['name_zh']}：資料階段 {industry['phase']['phase']}，BLS PPI 年增 {_pctx(industry['price']['yoy_pct'])}，"
                       f"成員 RPO 年增 {_pctx(industry['backlog']['yoy_pct'])}（{industry['quarter']}）"
                       if industry else f"SIC {sic or '未知'} 不在產業輪替範圍或輪替資料不可用")),
        ("資料階段", (f"{phase['phase']}（吃緊來源：{'、'.join(phase['constraint_families']) or '無'}；"
                   f"公司捕捉：{'、'.join(phase['capture_families']) or '無'}；緩解：{'、'.join(phase['relief_families']) or '無'}）"
                   f"；下次檢查 {phase['next_review_at'] or '下一份財報'}"
                   + ("；稀釋疑慮" if phase["dilution_overhang"] else ""))),
        ("證偽條件", "RPO 年增降至 -10% 以下；毛利率年減 1 個百分點以上；稀釋後股數年增 20% 以上；存貨成長超過營收 10 個百分點；所屬產業 PPI 年增降至 -3% 以下"),
    ]
    references = [{"source": "SEC XBRL company facts", "url": FACTS_URL.format(cik=cik), "period": frame},
                  {"source": "SEC EDGAR submissions", "url": SUBMISSIONS_URL.format(cik=cik)}]
    if business and business.get("url"):
        references.append({"source": f"SEC {business.get('form')} business section", "url": business["url"], "period": business.get("filed")})
    if industry:
        references.extend({"source": f"BLS PPI {row['series']}", "url": f"https://data.bls.gov/timeseries/{row['series']}", "period": row["month"]}
                          for row in industry["price"]["series"])
    return {"schema_version": 1, "ticker": ticker, "cik": cik, "name": name, "sic": sic,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "as_of": today.isoformat(),
            "metrics": metrics, "signals": signals, "phase": phase,
            "sections": [{"title": title, "text": text} for title, text in sections], "source_references": references,
            "boundary": "官方資料的計算與整理；不是投資建議、價格預測或機率"}


def build_reports(tickers: Mapping[str, str], fetch: Fetch, *, today: date, business_loader: Callable[[str], Mapping | None] | None = None,
                  rotation: Mapping[str, Any] | None = None, rotation_config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    reports, failures = {}, {}
    for ticker, cik in tickers.items():
        try:
            facts = json.loads(fetch(FACTS_URL.format(cik=cik)))
            submissions = json.loads(fetch(SUBMISSIONS_URL.format(cik=cik)))
            business = business_loader(cik) if business_loader else None
            reports[ticker] = build_report(ticker, cik, facts=facts, submissions=submissions, business=business,
                                           rotation=rotation, rotation_config=rotation_config, today=today)
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


def sealed_tickers(snapshots_dir: Path = ROOT / "state" / "v213-snapshots") -> list[str]:
    """Tickers ranked in the newest sealed run (the companies LINE can open a deep report for)."""
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
                           "source_references": report["source_references"][:20]}
    return compact


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
    from sec_contact_headers import sec_identity_headers
    wanted = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] if args.tickers else sealed_tickers()
    fetch = profile.sec_fetcher(sec_identity_headers())
    ciks = ticker_ciks(fetch, today=date.today())
    try:
        translate = profile.local_translator()
    except (OSError, ValueError, KeyError):
        translate = None

    def business(cik: str) -> Mapping[str, Any] | None:
        # Per-accession cache; only a new annual report triggers a (loopback) translation.
        try:
            return profile.resolve_business_profile(cik, fetch, translate)
        except Exception:
            return cached_business(cik)

    document = build_reports({t: ciks[t] for t in wanted if t in ciks}, fetch, today=date.today(), business_loader=business,
                             rotation=industry_rotation.load_rotation(), rotation_config=industry_rotation.load_config())
    document["not_sec_listed"] = [t for t in wanted if t not in ciks]
    industry_rotation.atomic_write(args.output, document)
    print(json.dumps({"status": "OK", "reports": len(document["reports"]), "failures": document["failures"],
                      "not_sec_listed": document["not_sec_listed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
