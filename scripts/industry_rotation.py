#!/usr/bin/env python3
"""Data-driven industry rotation (operator rule 2026-09-25: nothing hand-written).

The industry universe is defined only by official classifications: SEC SIC codes
(membership read from EDGAR at run time) and BLS Producer Price Index industry
series. For each industry the latest official data give four dated signals:

- PRICE      BLS PPI year-over-year change (independence family ``bls_ppi``)
- BACKLOG    summed remaining performance obligations of member issuers, SEC XBRL frames
- demand     summed quarterly revenue of member issuers (strength and growth only)
- INVENTORY_BUILD  inventories growing faster than revenue (relief)

``thesis_phase`` (industry scope) turns the signals into a phase; a data-derived
strength orders industries inside a phase. Every sentence on the card and in the
deep analysis is generated from these numbers with its source, period and URL;
industries rotate as the data change. No forecast, probability or price target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import thesis_phase  # noqa: E402

CONFIG_PATH = ROOT / "config" / "industry-rotation-v1.json"
OUTPUT_PATH = ROOT / "data" / "cache" / "industry_rotation_latest.json"
MEMBER_CACHE_DIR = ROOT / "data" / "cache" / "v21" / "sic_members"
BLS_CACHE = ROOT / "data" / "cache" / "v21" / "bls_ppi_series.json"
MEMBER_CACHE_DAYS = 30
MAX_BLS_BYTES = 10_000_000
RETRY_PAUSES = (3.0, 8.0, 15.0)  # seconds before each retry of a 503 listing page
PHASE_ZH = {"INSUFFICIENT_EVIDENCE": "資料不足", "DISCOVERY": "初現（單一來源）", "EARLY_VALIDATION": "驗證中（雙來源確認）",
            "RELIEVING": "緩解中", "BROKEN": "已失效", "COMMERCIAL_VALIDATION": "商業驗證", "INSTITUTIONAL_VALIDATION": "法人進場",
            "CONSENSUS": "共識擁擠"}
ADMITTED_PHASES = ("EARLY_VALIDATION", "DISCOVERY")
FAMILY_ZH = {"bls_ppi": "BLS 生產者物價", "sec_xbrl_issuers": "SEC 申報剩餘履約義務", "sec_xbrl_inventory": "SEC 申報存貨",
             "taiwan_monthly_revenue": "臺灣上市櫃同業月營收"}

Fetch = Callable[[str], bytes]
Post = Callable[[str, bytes], bytes]


class RotationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    ids = [row["industry_id"] for row in config.get("industries", [])]
    if config.get("schema_version") != 1 or not ids or len(ids) != len(set(ids)):
        raise RotationError("ROTATION_CONFIG_INVALID")
    for row in config["industries"]:
        if not all(re.fullmatch(r"\d{4}", sic) for sic in row["sic"]) or not all(re.fullmatch(r"PCU[0-9A-Z]{6,14}", s) for s in row["ppi"]):
            raise RotationError("ROTATION_CONFIG_INVALID")
    return config


# --------------------------------------------------------------------------- transport
class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("ROTATION_REDIRECT_REJECTED")


def bls_post() -> Post:
    """BLS public API v1 (no key, no personal data): no proxy, no redirect, verified TLS."""
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(cafile=certifi.where())
    except ImportError:
        pass
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context))

    def post(url: str, body: bytes) -> bytes:
        if not url.startswith("https://api.bls.gov/"):
            raise ValueError("ROTATION_BLS_URL_UNADMITTED")
        request = Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": "InvestorIntelligence-Research/1.0 (public statistics)"})
        with opener.open(request, timeout=60) as response:
            raw = response.read(MAX_BLS_BYTES + 1)
        if len(raw) > MAX_BLS_BYTES:
            raise ValueError("ROTATION_BLS_TOO_LARGE")
        return raw

    return post


def twse_get() -> Fetch:
    """TWSE and TPEx OpenAPI (government open data licence): no proxy, no redirect, verified TLS, generic agent."""
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(cafile=certifi.where())
    except ImportError:
        pass
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context))

    def get(url: str) -> bytes:
        if not url.startswith(("https://openapi.twse.com.tw/", "https://www.tpex.org.tw/openapi/")):
            raise ValueError("ROTATION_TWSE_URL_UNADMITTED")
        with opener.open(Request(url, headers={"User-Agent": "InvestorIntelligence-Research/1.0 (public statistics)"}), timeout=60) as response:
            raw = response.read(MAX_BLS_BYTES + 1)
        if len(raw) > MAX_BLS_BYTES:
            raise ValueError("ROTATION_TWSE_TOO_LARGE")
        return raw

    return get


def twse_monthly_revenue(fetch: Fetch, config: Mapping[str, Any], receipts: list) -> dict[str, Any]:
    """Listed (TWSE) and OTC (TPEx) monthly revenue summed by industry category (same month a year earlier)."""
    rows: list = []
    for url in config["sources"]["taiwan_monthly_revenue"]["endpoints"]:
        try:
            raw = fetch(url)
            batch = json.loads(raw)
        except Exception:
            continue  # one exchange down leaves the other
        receipts.append(_receipt("taiwan_monthly_revenue", url, raw))
        rows.extend(batch if isinstance(batch, list) else [])
    if not rows:
        raise RotationError("ROTATION_TAIWAN_REVENUE_UNAVAILABLE")
    by_category: dict[str, dict[str, float]] = {}
    month = None
    for row in rows:
        try:
            now, prior = float(row["營業收入-當月營收"]), float(row["營業收入-去年當月營收"])
            period = str(row["資料年月"])
        except (KeyError, TypeError, ValueError):
            continue
        if prior <= 0 or not re.fullmatch(r"\d{4,5}", period):
            continue
        roc_year, month_number = int(period[:-2]), int(period[-2:])
        month = max(month or date.min, date(roc_year + 1911, month_number, 1))
        bucket = by_category.setdefault(str(row.get("產業別", "")), {"now": 0.0, "prior": 0.0, "count": 0})
        bucket["now"] += now
        bucket["prior"] += prior
        bucket["count"] += 1
    return {"month": month, "categories": by_category}


def _receipt(source: str, url: str, raw: bytes, **extra: Any) -> dict[str, Any]:
    return {"source": source, "url": url, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "retrieved_at": utc_now(), **extra}


# --------------------------------------------------------------------------- BLS PPI
def bls_series(series_ids: Sequence[str], post: Post, config: Mapping[str, Any], *, start_year: int, end_year: int,
               receipts: list, cache: Path | None = None, today: date | None = None) -> dict[str, list[tuple[date, float]]]:
    """Live BLS series; when the API refuses (daily threshold, outage) a cache up to 35 days old is used.

    PPI is monthly, so a recent cache carries the same months; its receipt says it came from the cache.
    """
    try:
        result = _bls_live(series_ids, post, config, start_year=start_year, end_year=end_year, receipts=receipts)
    except Exception:
        if cache is None:
            raise
        try:
            stored = json.loads(cache.read_text(encoding="utf-8"))
            retrieved = date.fromisoformat(stored["retrieved_on"])
        except (OSError, ValueError, KeyError):
            raise RotationError("ROTATION_BLS_UNAVAILABLE_NO_CACHE") from None
        if (today or date.today()) - retrieved > timedelta(days=35):
            raise RotationError("ROTATION_BLS_UNAVAILABLE_CACHE_STALE") from None
        receipts.append({"source": "bls_ppi_cache", "url": str(config["sources"]["bls_ppi"]["endpoint"]),
                         "retrieved_on": stored["retrieved_on"], "retrieved_at": utc_now()})
        return {sid: [(date.fromisoformat(d), v) for d, v in rows] for sid, rows in stored["series"].items()}
    if cache is not None and result:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"retrieved_on": (today or date.today()).isoformat(),
                                     "series": {sid: [[d.isoformat(), v] for d, v in rows] for sid, rows in result.items()}}),
                         encoding="utf-8")
    return result


def _bls_live(series_ids: Sequence[str], post: Post, config: Mapping[str, Any], *, start_year: int, end_year: int,
              receipts: list) -> dict[str, list[tuple[date, float]]]:
    source = config["sources"]["bls_ppi"]
    size = int(source["max_series_per_request"])
    result: dict[str, list[tuple[date, float]]] = {}
    ids = sorted(set(series_ids))
    for start in range(0, len(ids), size):
        chunk = ids[start:start + size]
        body = json.dumps({"seriesid": chunk, "startyear": str(start_year), "endyear": str(end_year)}).encode("utf-8")
        raw = post(source["endpoint"], body)
        payload = json.loads(raw)
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise RotationError("ROTATION_BLS_REQUEST_FAILED")
        receipts.append(_receipt("bls_ppi", source["endpoint"], raw, series=chunk))
        for series in payload.get("Results", {}).get("series", []):
            points = []
            for row in series.get("data", []):
                period = str(row.get("period", ""))
                if not re.fullmatch(r"M(0[1-9]|1[0-2])", period):
                    continue  # M13 is an annual average
                try:
                    points.append((date(int(row["year"]), int(period[1:]), 1), float(row["value"])))
                except (KeyError, ValueError):
                    continue
            if points:
                result[str(series.get("seriesID"))] = sorted(points)
    return result


def _month_end(day: date) -> date:
    following = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return following - timedelta(days=1)


def yoy_latest(points: Sequence[tuple[date, float]]) -> dict[str, Any] | None:
    """Latest month against the same month one year earlier; None when either is missing."""
    if not points:
        return None
    by_month = dict(points)
    latest, value = max(points)
    prior = by_month.get(date(latest.year - 1, latest.month, 1))
    if not prior:
        return None
    return {"month": latest.strftime("%Y-%m"), "as_of": _month_end(latest).isoformat(), "latest": value,
            "prior": prior, "yoy_pct": round((value / prior - 1) * 100, 2)}


# --------------------------------------------------------------------------- SEC
def sic_members(sic: str, fetch: Fetch, config: Mapping[str, Any], *, today: date, cache_dir: Path | None,
                receipts: list, sleep: Callable[[float], None] = time.sleep) -> list[dict[str, Any]]:
    """Issuers EDGAR lists under one SIC code (cached for 30 days; membership changes slowly)."""
    path = cache_dir / f"SIC{sic}.json" if cache_dir else None
    if path and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if date.fromisoformat(cached["retrieved_on"]) >= today - timedelta(days=MEMBER_CACHE_DAYS):
                return cached["members"]
        except (OSError, ValueError, KeyError):
            pass
    source = config["sources"]["sec_sic_members"]
    members: dict[int, str] = {}
    for page in range(int(source["max_pages"])):
        url = source["endpoint"].format(sic=sic, start=page * int(source["page_size"]))
        for attempt, pause in enumerate(RETRY_PAUSES):
            try:
                raw = fetch(url)
                break
            except Exception as error:
                # EDGAR's company listing answers 503 under load; back off, but never retry a 403/429 fence.
                if getattr(error, "code", None) != 503 or attempt == len(RETRY_PAUSES) - 1:
                    raise
                sleep(pause)
        receipts.append(_receipt("sec_sic_members", url, raw, sic=sic))
        text = raw.decode("utf-8", "ignore")
        # Entries carry attributes; EDGAR's name attribute is unreliable, so names come from XBRL frames.
        entries = re.findall(r"(?s)<entry\b[^>]*>(.*?)</entry>", text)
        for entry in entries:
            cik = re.search(r"<cik>(\d+)</cik>", entry)
            if cik:
                members[int(cik.group(1))] = ""
        if len(entries) < int(source["page_size"]):
            break
    rows = [{"cik": cik, "name": name} for cik, name in sorted(members.items())]
    if path and rows:  # never cache an empty listing
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"sic": sic, "retrieved_on": today.isoformat(), "members": rows}, ensure_ascii=False),
                        encoding="utf-8")
    return rows


def frame(concepts: Sequence[str], period: str, fetch: Fetch, config: Mapping[str, Any], receipts: list,
          cache: dict, unit: str = "USD") -> dict[int, dict[str, Any]]:
    """cik -> {val, end, accn, name} from the first concept that reports it (e.g. two revenue tags)."""
    merged: dict[int, dict[str, Any]] = {}
    for concept in concepts:
        key = (concept, period)
        if key not in cache:
            template = config["sources"]["sec_xbrl_frames"]["endpoint" if unit == "USD" else "endpoint_shares"]
            url = template.format(concept=concept, period=period)
            try:
                raw = fetch(url)
            except Exception:
                cache[key] = {}
                continue
            receipts.append(_receipt("sec_xbrl_frames", url, raw, concept=concept, period=period))
            rows = json.loads(raw).get("data", [])
            cache[key] = {int(r["cik"]): {"val": float(r["val"]), "end": r.get("end"), "accn": r.get("accn"),
                                         "name": r.get("entityName", "")} for r in rows if "cik" in r and "val" in r}
        for cik, row in cache[key].items():
            merged.setdefault(cik, {**row, "concept": concept})
    return merged


def latest_quarter(fetch: Fetch, config: Mapping[str, Any], today: date, receipts: list, cache: dict) -> tuple[int, int]:
    """Most recent calendar quarter whose revenue frame is populated enough to compare."""
    year, quarter = today.year, (today.month - 1) // 3 + 1
    for _ in range(6):
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
        rows = frame(config["concepts"]["revenue"], f"CY{year}Q{quarter}", fetch, config, receipts, cache)
        if len(rows) >= int(config["thresholds"]["min_frame_rows"]):
            return year, quarter
    raise RotationError("ROTATION_NO_POPULATED_QUARTER")


def _matched_sum(members: Iterable[int], now: Mapping[int, Mapping[str, Any]], prior: Mapping[int, Mapping[str, Any]]):
    matched = [cik for cik in members if cik in now and cik in prior and prior[cik]["val"] > 0]
    total_now = sum(now[cik]["val"] for cik in matched)
    total_prior = sum(prior[cik]["val"] for cik in matched)
    yoy = round((total_now / total_prior - 1) * 100, 2) if total_prior > 0 else None
    return {"matched": len(matched), "now": total_now, "prior": total_prior, "yoy_pct": yoy, "ciks": matched}


# --------------------------------------------------------------------------- assembly
def _fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.1f}%"


def _money(value: float) -> str:
    return f"US${value / 1e9:,.2f}B" if value >= 1e8 else f"US${value / 1e6:,.1f}M"


def _direction(value: float | None, up: float, down: float) -> str | None:
    if value is None:
        return None
    return "UP" if value >= up else "DOWN" if value <= down else "FLAT"


def assess_industry(industry: Mapping[str, Any], *, ppi: Mapping[str, list], members: Sequence[Mapping[str, Any]],
                    frames: Mapping[str, Mapping[int, Mapping[str, Any]]], quarter: tuple[int, int],
                    config: Mapping[str, Any], today: date, taiwan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    limits, formula, sources = config["thresholds"], config["strength_formula"], config["sources"]
    year, q = quarter
    period_label = f"{year} Q{q}"
    ciks = [int(m["cik"]) for m in members]
    price_rows = [dict(series=s, **stats) for s in industry["ppi"] if (stats := yoy_latest(ppi.get(s, [])))]
    price_yoy = round(sum(r["yoy_pct"] for r in price_rows) / len(price_rows), 2) if price_rows else None
    revenue = _matched_sum(ciks, frames["revenue_now"], frames["revenue_prior"])
    backlog = _matched_sum(ciks, frames["backlog_now"], frames["backlog_prior"])
    inventory = _matched_sum(ciks, frames["inventory_now"], frames["inventory_prior"])
    minimum = int(limits["min_matched_issuers"])
    # Too few matched issuers make a growth rate noise: the metric becomes missing everywhere downstream.
    for aggregate in (revenue, backlog, inventory):
        if aggregate["matched"] < minimum:
            aggregate["yoy_pct"] = None
    revenue_yoy, backlog_yoy, inventory_yoy = revenue["yoy_pct"], backlog["yoy_pct"], inventory["yoy_pct"]
    quarter_end = _month_end(date(year, q * 3, 1)).isoformat()
    frames_url = sources["sec_xbrl_frames"]["endpoint"]

    signals: list[dict[str, Any]] = []
    price_dir = _direction(price_yoy, limits["ppi_up_yoy_pct"], limits["ppi_down_yoy_pct"])
    if price_dir and price_rows:
        signals.append({"signal_id": f"{industry['industry_id']}:PRICE", "kind": "PRICE", "as_of": max(r["as_of"] for r in price_rows),
                        "direction": price_dir, "value": price_yoy, "evidence_family": "bls_ppi",
                        "source_url": sources["bls_ppi"]["series_page"].format(series=price_rows[0]["series"])})
    backlog_dir = _direction(backlog_yoy, limits["backlog_up_yoy_pct"], limits["backlog_down_yoy_pct"])
    if backlog_dir:
        signals.append({"signal_id": f"{industry['industry_id']}:BACKLOG", "kind": "BACKLOG", "as_of": quarter_end,
                        "direction": backlog_dir, "value": backlog_yoy, "evidence_family": "sec_xbrl_issuers",
                        "source_url": frames_url.format(concept=config["concepts"]["backlog"][0], period=f"CY{year}Q{q}I")})
    gap = round(inventory_yoy - revenue_yoy, 2) if inventory_yoy is not None and revenue_yoy is not None else None
    # Taiwan listed suppliers' monthly revenue: a faster, independent read of demand through the chain.
    tw = {"categories": list(industry.get("tw_industry", [])), "count": 0, "yoy_pct": None, "month": None}
    if taiwan and taiwan.get("month") and tw["categories"]:
        buckets = [taiwan["categories"][c] for c in tw["categories"] if c in taiwan["categories"]]
        now, prior = sum(b["now"] for b in buckets), sum(b["prior"] for b in buckets)
        tw["count"] = sum(b["count"] for b in buckets)
        tw["month"] = taiwan["month"].strftime("%Y-%m")
        if tw["count"] >= minimum and prior > 0:
            tw["yoy_pct"] = round((now / prior - 1) * 100, 2)
            tw_dir = _direction(tw["yoy_pct"], limits["tw_revenue_up_yoy_pct"], limits["tw_revenue_down_yoy_pct"])
            signals.append({"signal_id": f"{industry['industry_id']}:TW_REVENUE", "kind": "SUPPLIER_REVENUE",
                            "as_of": _month_end(taiwan["month"]).isoformat(), "direction": tw_dir, "value": tw["yoy_pct"],
                            "evidence_family": "taiwan_monthly_revenue", "source_url": sources["taiwan_monthly_revenue"]["endpoints"][0]})
    if gap is not None and gap >= limits["inventory_build_gap_pp"]:
        signals.append({"signal_id": f"{industry['industry_id']}:INVENTORY", "kind": "INVENTORY_BUILD", "as_of": quarter_end,
                        "value": gap, "evidence_family": "sec_xbrl_inventory",
                        "source_url": frames_url.format(concept=config["concepts"]["inventory"][0], period=f"CY{year}Q{q}I")})
    phase = thesis_phase.assess_phase(signals, today, scope="industry")

    points = min(max(price_yoy or 0, 0), formula["price_yoy_cap_pct"]) * formula["price_points_per_pct"]
    points += min(max(backlog_yoy or 0, 0), formula["backlog_yoy_cap_pct"]) * formula["backlog_points_per_pct"]
    points += min(max(revenue_yoy or 0, 0), formula["revenue_yoy_cap_pct"]) * formula["revenue_points_per_pct"]
    points += min(max(tw["yoy_pct"] or 0, 0), formula["tw_revenue_yoy_cap_pct"]) * formula["tw_revenue_points_per_pct"]
    points -= min(max(gap or 0, 0), formula["inventory_gap_penalty_cap"])
    strength = int(round(min(max(points, 0), 100)))

    leaders = sorted(revenue["ciks"], key=lambda cik: frames["revenue_now"][cik]["val"], reverse=True)
    top = leaders[:5]
    share = round(sum(frames["revenue_now"][c]["val"] for c in top) / revenue["now"] * 100, 1) if revenue["now"] > 0 and top else None
    available = sum(value is not None for value in (price_yoy, revenue_yoy, backlog_yoy, inventory_yoy, tw["yoy_pct"]))
    return {
        "industry_id": industry["industry_id"], "name_zh": industry["name_zh"], "name_en": industry["name_en"],
        "sic": list(industry["sic"]), "ppi_series": list(industry["ppi"]), "member_count": len(ciks),
        "quarter": period_label, "quarter_end": quarter_end,
        "price": {"yoy_pct": price_yoy, "series": price_rows},
        "revenue": {k: revenue[k] for k in ("matched", "now", "prior", "yoy_pct")},
        "backlog": {k: backlog[k] for k in ("matched", "now", "prior", "yoy_pct")},
        "inventory": {k: inventory[k] for k in ("matched", "now", "prior", "yoy_pct")},
        "inventory_minus_revenue_pp": gap,
        "leaders": [{"cik": c, "name": frames["revenue_now"][c]["name"], "revenue": frames["revenue_now"][c]["val"]} for c in top],
        "top5_revenue_share_pct": share, "data_completeness_pct": available * 20, "taiwan": tw,
        "signals": signals, "phase": phase, "strength": strength,
    }


def _texts(row: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """Every sentence is built from the computed numbers; missing data is said, never filled."""
    price, revenue, backlog, inventory = row["price"], row["revenue"], row["backlog"], row["inventory"]
    phase = row["phase"]
    months = sorted({r["month"] for r in price["series"]})
    price_text = (f"BLS 生產者物價指數年增 {_fmt_pct(price['yoy_pct'])}（{', '.join(r['series'] for r in price['series'])}，{months[-1]}）"
                  if price["yoy_pct"] is not None else "BLS 生產者物價指數無可比較的年增資料")
    revenue_text = (f"{revenue['matched']} 家申報成員季營收年增 {_fmt_pct(revenue['yoy_pct'])}（{_money(revenue['prior'])} → {_money(revenue['now'])}，SEC XBRL {row['quarter']}）"
                    if revenue["yoy_pct"] is not None and revenue["matched"] >= 2 else f"可比營收申報不足（{revenue['matched']} 家）")
    backlog_text = (f"{backlog['matched']} 家申報成員剩餘履約義務（RPO）年增 {_fmt_pct(backlog['yoy_pct'])}（{_money(backlog['prior'])} → {_money(backlog['now'])}，{row['quarter']}）"
                    if backlog["yoy_pct"] is not None and backlog["matched"] >= 2 else f"可比 RPO 申報不足（{backlog['matched']} 家），積壓訂單未量化")
    tw = row.get("taiwan") or {}
    taiwan_text = (f"臺灣上市櫃同業（{'、'.join(tw['categories'])}）{tw['count']} 家 {tw['month']} 營收年增 {_fmt_pct(tw['yoy_pct'])}（證交所與櫃買中心 OpenAPI）"
                   if tw.get("yoy_pct") is not None else "")
    gap = row["inventory_minus_revenue_pp"]
    inventory_text = (f"存貨年增 {_fmt_pct(inventory['yoy_pct'])}，較營收成長{'高' if gap > 0 else '低'} {abs(gap):.1f} 個百分點"
                      if gap is not None else "存貨與營收的可比資料不足")
    thresholds = config["thresholds"]
    killers = [f"PPI 年增降至 {thresholds['ppi_down_yoy_pct']:+.0f}% 以下",
               f"成員 RPO 年增降至 {thresholds['backlog_down_yoy_pct']:+.0f}% 以下",
               f"存貨成長超過營收 {thresholds['inventory_build_gap_pp']:.0f} 個百分點"]
    next_review = phase.get("next_review_at") or "下一次 BLS 或 SEC 資料更新"
    tightening = "、".join(FAMILY_ZH.get(f, f) for f in phase["constraint_families"]) or "無"
    relief = "、".join(FAMILY_ZH.get(f, f) for f in phase["relief_families"]) or "無"
    sic_text = "、".join(row["sic"])
    leaders = [leader["name"] for leader in row["leaders"] if leader["name"]] or ["成員營收資料不足"]
    return {
        "current_state": f"{price_text}；{revenue_text}；{backlog_text}" + (f"；{taiwan_text}" if taiwan_text else "") + "。",
        "outlook": (f"資料階段：{PHASE_ZH.get(phase['phase'], phase['phase'])}（吃緊訊號來源：{tightening}；緩解訊號來源：{relief}）。"
                    f"下次重新檢查：{next_review}。此為官方資料的現況判讀，不是價格或營收預測。"),
        "demand": [revenue_text] + ([taiwan_text] if taiwan_text else []), "supply": inventory_text, "bottleneck": backlog_text, "pricing": price_text,
        "value_chain": (f"SIC {sic_text} 的 EDGAR 申報成員 {row['member_count']} 家"
                        + (f"；營收前五大合計占 {row['top5_revenue_share_pct']:.1f}%" if row["top5_revenue_share_pct"] is not None else "")),
        "leaders": leaders, "killers": killers, "next_review": next_review,
        "risks": ([f"緩解訊號：{inventory_text}"] if gap is not None and gap > 0 else [])
                 + ([f"價格轉弱：{price_text}"] if (price["yoy_pct"] or 0) < 0 else []) or ["目前沒有觸發的緩解訊號；翻轉條件見證偽條件"],
    }


def to_macro_card(row: Mapping[str, Any], rank: int | None, config: Mapping[str, Any]) -> dict[str, Any]:
    text = _texts(row, config)
    revenue = row["revenue"]
    year, q = row["quarter"].split(" Q")
    growth = None
    if revenue["yoy_pct"] is not None and revenue["matched"] >= config["thresholds"]["min_matched_issuers"]:
        growth = {"rate_pct": revenue["yoy_pct"], "units": "% YoY", "period": row["quarter"], "type": "actual",
                  "publisher": config["sources"]["sec_xbrl_frames"]["publisher"], "date": row["quarter_end"],
                  "source_id": "sec-xbrl-frames-revenue",
                  "url": config["sources"]["sec_xbrl_frames"]["endpoint"].format(concept=config["concepts"]["revenue"][0], period=f"CY{year}Q{q}"),
                  "raw_passage": f"Summed quarterly revenue of {revenue['matched']} SIC {'/'.join(row['sic'])} issuers: {revenue['prior']:.0f} -> {revenue['now']:.0f} USD"}
    return {
        "rank": rank, "industry_id": row["industry_id"], "industry_name": f"{row['name_zh']} ({row['name_en']})",
        "current_state": text["current_state"], "outlook_12_36m": text["outlook"], "growth": growth,
        "demand_drivers": text["demand"], "supply_constraint_chokepoint": text["bottleneck"], "pricing": text["pricing"],
        "value_chain_position": text["value_chain"], "beneficiaries_key_suppliers": text["leaders"],
        "catalysts": {"m6": f"下次資料檢查 {text['next_review']}（BLS PPI 每月、SEC 財報每季）",
                      "y1": "每季 10-Q／10-K 的 XBRL 更新後自動重算", "y2": "無已公告的兩年期催化劑（不捏造）"},
        "risks_lifecycle": "；".join(text["risks"]),
        "opportunity_score": row["strength"], "data_strength": row["strength"],
        "confidence": {"data_completeness": row["data_completeness_pct"],
                       "source_independence": 100 if len(set(s["evidence_family"] for s in row["signals"])) >= 2 else 50,
                       "verification_status": "OFFICIAL_DATA_COMPUTED"},
        "phase": row["phase"]["phase"],
    }


def to_deep_analysis(row: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    text = _texts(row, config)
    year, q = row["quarter"].split(" Q")
    frames_url = config["sources"]["sec_xbrl_frames"]["endpoint"]
    references = [{"source": f"BLS PPI {r['series']}", "url": config["sources"]["bls_ppi"]["series_page"].format(series=r["series"]),
                   "period": r["month"], "passage": f"{r['prior']} -> {r['latest']} ({r['yoy_pct']:+.2f}% YoY)"} for r in row["price"]["series"]]
    for label, concept in (("revenue", config["concepts"]["revenue"][0]), ("backlog", config["concepts"]["backlog"][0]),
                           ("inventory", config["concepts"]["inventory"][0])):
        suffix = "" if label == "revenue" else "I"
        references.append({"source": f"SEC XBRL frames {concept}", "url": frames_url.format(concept=concept, period=f"CY{year}Q{q}{suffix}"),
                           "period": row["quarter"], "passage": f"{row[label]['matched']} matched issuers"})
    return {
        "industry_id": row["industry_id"], "industry_name": f"{row['name_zh']} ({row['name_en']})",
        "demand": "；".join(text["demand"]), "supply": text["supply"], "bottleneck": text["bottleneck"], "pricing": text["pricing"],
        "capex": "本資料集未量測買方資本支出；不以推估代替",
        "competition": text["value_chain"], "beneficiaries": text["leaders"],
        "catalysts": {"m6": f"下次資料檢查 {text['next_review']}", "y1": "每季財報 XBRL 更新後自動重算", "y2": "無已公告的兩年期催化劑（不捏造）"},
        "risks": text["risks"], "killers": text["killers"], "source_references": references,
    }


def _capped(value: float | None, cap: float, per: float) -> float:
    return min(max(value or 0.0, 0.0), cap) * per


def rank_companies(rows: Sequence[Mapping[str, Any]], frames: Mapping[str, Mapping[int, Mapping[str, Any]]],
                   config: Mapping[str, Any], today: date, tickers: Mapping[int, str], quarter_end: str) -> list[dict[str, Any]]:
    """Members of admitted industries, ranked by company-scope phase and a published strength formula."""
    rules, limits = config["company_ranking"], config["thresholds"]
    frames_url = config["sources"]["sec_xbrl_frames"]["endpoint"]
    best: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row["phase"]["phase"] not in ADMITTED_PHASES or row["strength"] < int(limits["min_admission_strength"]):
            continue
        industry_signals = [s for s in row["signals"] if s["kind"] in ("PRICE", "SUPPLIER_REVENUE")]
        for cik in row.get("member_ciks", []):
            now, prior = frames["revenue_now"].get(cik), frames["revenue_prior"].get(cik)
            ticker = tickers.get(cik)
            if not now or not prior or prior["val"] <= 0 or not ticker or now["val"] < rules["min_quarter_revenue_usd"]:
                continue
            revenue_yoy = round((now["val"] / prior["val"] - 1) * 100, 2)

            def change(key):
                a, b = frames.get(f"{key}_now", {}).get(cik), frames.get(f"{key}_prior", {}).get(cik)
                return (a["val"], b["val"]) if a and b and b["val"] else (None, None)
            rpo_now, rpo_prior = change("backlog")
            rpo_yoy = round((rpo_now / rpo_prior - 1) * 100, 2) if rpo_now is not None and rpo_prior > 0 else None
            gp_now, gp_prior = change("gross_profit")
            gm_change = round((gp_now / now["val"] - gp_prior / prior["val"]) * 100, 2) if gp_now is not None else None
            op_now, op_prior = change("operating_income")
            om_change = round((op_now / now["val"] - op_prior / prior["val"]) * 100, 2) if op_now is not None else None
            sh_now, sh_prior = change("diluted_shares")
            dilution = round((sh_now / sh_prior - 1) * 100, 2) if sh_now is not None and sh_prior > 0 else None
            inv_now, inv_prior = change("inventory")
            inv_gap = (round((inv_now / inv_prior - 1) * 100 - revenue_yoy, 2)
                       if inv_now is not None and inv_prior > 0 else None)
            url = frames_url.format(concept=config["concepts"]["revenue"][0], period=f"CY{row['quarter'].replace(' Q', 'Q')}")
            signals = [dict(s, signal_id=f"{ticker}:{s['signal_id']}") for s in industry_signals]
            if rpo_yoy is not None:
                signals.append({"signal_id": f"{ticker}:RPO", "kind": "BACKLOG", "as_of": quarter_end, "value": rpo_yoy,
                                "direction": _direction(rpo_yoy, limits["backlog_up_yoy_pct"], limits["backlog_down_yoy_pct"]),
                                "evidence_family": "sec_issuer", "source_url": url})
            if gm_change is not None:
                signals.append({"signal_id": f"{ticker}:MARGIN", "kind": "COMPANY_MARGIN", "as_of": quarter_end, "value": gm_change,
                                "direction": _direction(gm_change, 1.0, -1.0), "evidence_family": "sec_issuer", "source_url": url})
            if dilution is not None and dilution > 0:
                signals.append({"signal_id": f"{ticker}:DILUTION", "kind": "DILUTION", "as_of": quarter_end, "value": dilution,
                                "evidence_family": "sec_issuer", "source_url": url})
            if inv_gap is not None and inv_gap >= limits["inventory_build_gap_pp"]:
                signals.append({"signal_id": f"{ticker}:INVENTORY", "kind": "INVENTORY_BUILD", "as_of": quarter_end, "value": inv_gap,
                                "evidence_family": "sec_issuer_inventory", "source_url": url})
            phase = thesis_phase.assess_phase(signals, today, scope="company")
            points = (_capped(revenue_yoy, rules["revenue_yoy_cap_pct"], rules["revenue_points_per_pct"])
                      + _capped(rpo_yoy, rules["backlog_yoy_cap_pct"], rules["backlog_points_per_pct"])
                      + _capped(gm_change, rules["margin_change_cap_pp"], rules["margin_points_per_pp"])
                      + _capped(om_change, rules["margin_change_cap_pp"], rules["margin_points_per_pp"])
                      - min(max(dilution or 0, 0) * rules["dilution_penalty_per_pct"], rules["dilution_penalty_cap"])
                      - min(max(inv_gap or 0, 0), rules["inventory_gap_penalty_cap"]))
            record = {"ticker": ticker, "cik": f"{cik:010d}", "name": now.get("name", ""), "industry_id": row["industry_id"],
                      "industry_name": row["name_zh"], "industry_phase": row["phase"]["phase"], "quarter": row["quarter"],
                      "revenue": now["val"], "revenue_yoy_pct": revenue_yoy, "rpo_yoy_pct": rpo_yoy,
                      "gross_margin_change_pp": gm_change, "operating_margin_change_pp": om_change,
                      "dilution_yoy_pct": dilution, "inventory_minus_revenue_pp": inv_gap,
                      "phase": phase["phase"], "phase_reasons": phase["reasons"], "next_review_at": phase["next_review_at"],
                      "preference_rank": phase["preference_rank"], "strength": int(round(min(max(points, 0), 100)))}
            key = (-record["strength"], record["preference_rank"])
            if cik not in best or key < (-best[cik]["strength"], best[cik]["preference_rank"]):
                best[cik] = record
    # Phase gates eligibility; confirmed constraints (two or more families) rank before single-family
    # discoveries; the published strength orders each tier; an industry cap keeps one cycle from filling the list.
    eligible = [r for r in best.values() if r["phase"] in rules["eligible_phases"] and r["strength"] >= rules["min_company_strength"]]
    ordered = sorted(eligible, key=lambda r: (r["phase"] not in rules["confirmed_phases"], -r["strength"], r["ticker"]))
    ranked, per_industry = [], {}
    for record in ordered:
        if per_industry.get(record["industry_id"], 0) >= int(rules["max_per_industry"]):
            continue
        per_industry[record["industry_id"]] = per_industry.get(record["industry_id"], 0) + 1
        ranked.append(record)
        if len(ranked) == int(rules["size"]):
            break
    for rank, record in enumerate(ranked, 1):
        record["rank"] = rank
    return ranked


def build_rotation(config: Mapping[str, Any], *, fetch_sec: Fetch, post_bls: Post, today: date,
                   member_cache: Path | None = MEMBER_CACHE_DIR, fetch_twse: Fetch | None = None,
                   tickers: Mapping[int, str] | None = None, bls_cache: Path | None = BLS_CACHE) -> dict[str, Any]:
    receipts: list = []
    cache: dict = {}
    taiwan = None
    if fetch_twse is not None:
        try:
            taiwan = twse_monthly_revenue(fetch_twse, config, receipts)
        except Exception:
            taiwan = None  # one source down never blocks the others
    series = [s for industry in config["industries"] for s in industry["ppi"]]
    ppi = bls_series(series, post_bls, config, start_year=today.year - 2, end_year=today.year, receipts=receipts,
                     cache=bls_cache, today=today)
    year, q = latest_quarter(fetch_sec, config, today, receipts, cache)
    concepts = config["concepts"]
    frames = {
        "revenue_now": frame(concepts["revenue"], f"CY{year}Q{q}", fetch_sec, config, receipts, cache),
        "revenue_prior": frame(concepts["revenue"], f"CY{year - 1}Q{q}", fetch_sec, config, receipts, cache),
        "backlog_now": frame(concepts["backlog"], f"CY{year}Q{q}I", fetch_sec, config, receipts, cache),
        "backlog_prior": frame(concepts["backlog"], f"CY{year - 1}Q{q}I", fetch_sec, config, receipts, cache),
        "inventory_now": frame(concepts["inventory"], f"CY{year}Q{q}I", fetch_sec, config, receipts, cache),
        "inventory_prior": frame(concepts["inventory"], f"CY{year - 1}Q{q}I", fetch_sec, config, receipts, cache),
    }
    if "company_ranking" in config:
        for key in ("gross_profit", "operating_income"):
            frames[f"{key}_now"] = frame(concepts[key], f"CY{year}Q{q}", fetch_sec, config, receipts, cache)
            frames[f"{key}_prior"] = frame(concepts[key], f"CY{year - 1}Q{q}", fetch_sec, config, receipts, cache)
        frames["diluted_shares_now"] = frame(concepts["diluted_shares"], f"CY{year}Q{q}", fetch_sec, config, receipts, cache, unit="shares")
        frames["diluted_shares_prior"] = frame(concepts["diluted_shares"], f"CY{year - 1}Q{q}", fetch_sec, config, receipts, cache, unit="shares")
    rows, unavailable_sic = [], []
    for industry in config["industries"]:
        members: dict[int, dict] = {}
        for sic in industry["sic"]:
            try:
                listed = sic_members(sic, fetch_sec, config, today=today, cache_dir=member_cache, receipts=receipts)
            except Exception:
                unavailable_sic.append(sic)  # that SIC contributes no members this run; recorded, never guessed
                continue
            for member in listed:
                members[int(member["cik"])] = member
        row = assess_industry(industry, ppi=ppi, members=list(members.values()), frames=frames,
                              quarter=(year, q), config=config, today=today, taiwan=taiwan)
        row["member_ciks"] = sorted(members)
        rows.append(row)
    rows.sort(key=lambda r: (r["phase"]["preference_rank"], -r["strength"], r["industry_id"]))
    admitted = [r for r in rows if r["phase"]["phase"] in ADMITTED_PHASES and r["revenue"]["yoy_pct"] is not None
                and r["strength"] >= int(config["thresholds"]["min_admission_strength"])]
    # The TOP5 is ranked by the score the card shows (operator 2026-09-26: a higher opportunity score must never rank
    # lower); the evidence phase is an admission condition and only breaks ties.
    admitted.sort(key=lambda r: (-r["strength"], r["phase"]["preference_rank"], r["industry_id"]))
    cards, deep = [], {}
    for rank, row in enumerate(admitted, 1):
        cards.append({**to_macro_card(row, rank, config), "rotation_rank": rank})
        deep[row["industry_id"]] = to_deep_analysis(row, config)
    companies: list = []
    if "company_ranking" in config and tickers is not None:
        companies = rank_companies(rows, frames, config, today, tickers, _month_end(date(year, q * 3, 1)).isoformat())
    for row in rows:
        row.pop("member_ciks", None)  # large; membership is cached separately
    return {
        "schema_version": 1, "policy_id": config["policy_id"], "generated_at": utc_now(), "as_of": today.isoformat(),
        "company_ranking": companies,
        "quarter": f"{year} Q{q}", "status": "COMPUTED", "publication_eligible": False,
        "method": "BLS PPI + SEC XBRL frames by SIC membership + TWSE/TPEx monthly revenue -> thesis_phase(industry) -> data strength",
        "industries": rows, "macro_candidates": cards, "deep_analyses": deep, "receipts": receipts,
        "unavailable_sic": sorted(set(unavailable_sic)),
    }


def atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def load_rotation(path: Path = OUTPUT_PATH, *, max_age_days: int | None = None, today: date | None = None) -> dict[str, Any] | None:
    """Fresh rotation document or None (callers report a shortfall; nothing falls back to hand-written data)."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    limit = max_age_days if max_age_days is not None else int(load_config()["thresholds"]["rotation_max_age_days"])
    try:
        as_of = date.fromisoformat(document["as_of"])
    except (KeyError, ValueError):
        return None
    if document.get("schema_version") != 1 or (today or date.today()) - as_of > timedelta(days=limit):
        return None
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="read BLS and SEC now (public data, SEC fair access)")
    parser.add_argument("--if-older-than-hours", type=float, help="skip when the current file is newer than this")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    if not args.refresh:
        parser.error("--refresh is required; no implicit network requests")
    config = load_config()
    if args.if_older_than_hours is not None and args.output.exists():
        age_hours = (datetime.now().timestamp() - args.output.stat().st_mtime) / 3600
        if age_hours < args.if_older_than_hours:
            print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age_hours, 1)}))
            return 0
    import company_business_profile as profile
    from sec_contact_headers import sec_identity_headers
    try:
        import company_deep_report
        fetch = profile.sec_fetcher(sec_identity_headers())
        tickers: dict[int, str] = {}
        for ticker, cik in company_deep_report.ticker_ciks(fetch, today=date.today()).items():
            current = tickers.get(int(cik))
            if not re.fullmatch(r"[A-Z]{1,5}", ticker):
                continue  # preferred shares, warrants, units and share-class suffixes are not the common line
            if current is None or (len(ticker), ticker) < (len(current), current):
                tickers[int(cik)] = ticker
        document = build_rotation(config, fetch_sec=fetch, post_bls=bls_post(), today=date.today(), fetch_twse=twse_get(),
                                  tickers=tickers)
    except Exception as error:  # keep the last good file; report the class only
        print(json.dumps({"status": "FAILED", "error": type(error).__name__}))
        return 1
    atomic_write(args.output, document)
    summary = [{"industry_id": r["industry_id"], "phase": r["phase"]["phase"], "strength": r["strength"]}
               for r in document["industries"][:8]]
    print(json.dumps({"status": "OK", "quarter": document["quarter"], "admitted": len(document["macro_candidates"]),
                      "top": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
