#!/usr/bin/env python3
"""H6B1 R13: same-accession SEC filing-package fulfillment enrichment.

R12 proved that re-reading only the selected primary SEC HTML is still too
narrow for inline-XBRL filings.  An issuer can expose the selected current RPO in
the primary document while the explicit recognition schedule is rendered in a
same-accession report page (for example an Rxx.htm detail generated from the
same filing package).

R13 preserves the accepted R12 current-order selection.  Only a SUPPORTED current
metric whose future field remains UNAVAILABLE is eligible.  It then inspects
FilingSummary.xml and Rxx.htm pages from the exact same SEC accession directory.
A future schedule may be imported only when the detail page contains the same
metric type and the same normalized unit-bearing amount.  Different accessions,
amounts, metric types, or conflicting schedules fail closed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h6b1_metric_semantic_guard_v7 as r12

r11 = r12.r11
r4 = r12.r4
base = r12.base
_BASE_R12_GENERIC = r12.generic_sec_outlook_semantic_v7

SEC_ARCHIVE_PREFIX = "/Archives/edgar/data/"
REPORT_FILE_RE = re.compile(r"<HtmlFileName>\s*(R\d+\.htm)\s*</HtmlFileName>", re.I)


def _accession_root(url: str) -> str | None:
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"www.sec.gov", "sec.gov"}:
        return None
    path = parsed.path
    if SEC_ARCHIVE_PREFIX not in path:
        return None
    parts = path.rsplit("/", 1)
    if len(parts) != 2 or not parts[0]:
        return None
    return f"https://www.sec.gov{parts[0]}/"


def _same_accession_report_urls(source_url: str, *, raw_fetcher=base.fetch_raw) -> list[str]:
    root = _accession_root(source_url)
    if not root:
        return []
    summary_url = urljoin(root, "FilingSummary.xml")
    try:
        raw = raw_fetcher(summary_url)
    except base.H6BError:
        return []
    names = []
    seen: set[str] = set()
    for match in REPORT_FILE_RE.finditer(raw):
        name = match.group(1)
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
        if len(names) >= 96:
            break
    return [urljoin(root, name) for name in names]


def _enrich_same_accession_package(
    result: Mapping[str, Any],
    *,
    raw_fetcher=base.fetch_raw,
    text_fetcher=base.fetch_text,
) -> dict[str, Any]:
    out = dict(result)
    grounding = dict(out.get("claim_grounding") or {})
    if grounding.get("current_orders_summary") != "SUPPORTED":
        return out
    if grounding.get("future_orders_estimate") != "UNAVAILABLE":
        return out

    current = str(out.get("current_orders_summary") or "")
    metric_type = r12._metric_type_from_current_summary(current)
    amount = r12._amount_from_current_summary(current)
    source_urls = [str(url) for url in out.get("current_order_source_urls") or [] if str(url).startswith("https://")]
    if not metric_type or not amount or len(source_urls) != 1:
        return out

    current_url = source_urls[0]
    root = _accession_root(current_url)
    if not root:
        return out

    candidates = _same_accession_report_urls(current_url, raw_fetcher=raw_fetcher)
    found: list[tuple[str, str]] = []
    for report_url in candidates:
        if _accession_root(report_url) != root:
            continue
        try:
            text = text_fetcher(report_url)
        except base.H6BError:
            continue
        enriched = r12._same_metric_schedule_from_source(
            text,
            metric_type=metric_type,
            amount=amount,
        )
        if enriched is None or enriched[1] != "INFERENCE":
            continue
        future = enriched[0]
        found.append((future, report_url))

    if not found:
        return out

    unique_futures = {future for future, _url in found}
    if len(unique_futures) != 1:
        # Conflicting same-accession schedules are not auto-reconciled.
        return out

    future = next(iter(unique_futures))
    future_urls = list(dict.fromkeys(url for candidate_future, url in found if candidate_future == future))
    out["future_orders_estimate"] = future
    out["future_order_source_urls"] = future_urls
    grounding["future_orders_estimate"] = "INFERENCE"
    out["claim_grounding"] = grounding
    return out


def generic_sec_outlook_semantic_v8(
    ticker: str,
    cik_map: Mapping[str, str],
    raw_fetcher=base.fetch_raw,
    text_fetcher=base.fetch_text,
) -> dict[str, Any]:
    # Preserve R12 current selection and same-primary enrichment exactly.
    result = _BASE_R12_GENERIC(
        ticker,
        cik_map,
        raw_fetcher=raw_fetcher,
        text_fetcher=text_fetcher,
    )
    return _enrich_same_accession_package(
        result,
        raw_fetcher=raw_fetcher,
        text_fetcher=text_fetcher,
    )


r4.generic_sec_outlook_semantic = generic_sec_outlook_semantic_v8
base.generic_sec_outlook = generic_sec_outlook_semantic_v8


def self_test() -> None:
    primary = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm"
    detail = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/R14.htm"
    summary = (
        "<FilingSummary><MyReports>"
        "<Report><HtmlFileName>R14.htm</HtmlFileName></Report>"
        "<Report><HtmlFileName>R17.htm</HtmlFileName></Report>"
        "</MyReports></FilingSummary>"
    )
    primary_text = "Remaining performance obligations were $ 3.2 billion with no disclosed recognition schedule."
    detail_text = (
        "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length was $ 3.2 billion. "
        "Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months."
    )
    other_detail = "Future supply and capacity commitments were $279 billion."

    def raw_fetcher(url: str) -> str:
        if url.endswith("/FilingSummary.xml"):
            return summary
        import json
        if "data.sec.gov/submissions" in url:
            return json.dumps({
                "filings": {"recent": {
                    "form": ["10-Q"],
                    "accessionNumber": ["0001045810-26-000075"],
                    "primaryDocument": ["nvda-20260726.htm"],
                    "filingDate": ["2026-08-26"],
                }}
            })
        raise AssertionError(url)

    def text_fetcher(url: str) -> str:
        if url == primary:
            return primary_text
        if url == detail:
            return detail_text
        if url.endswith("/R17.htm"):
            return other_detail
        raise AssertionError(url)

    result = generic_sec_outlook_semantic_v8(
        "NVDA",
        {"NVDA": "1045810"},
        raw_fetcher=raw_fetcher,
        text_fetcher=text_fetcher,
    )
    assert result["claim_grounding"]["current_orders_summary"] == "SUPPORTED"
    assert result["claim_grounding"]["future_orders_estimate"] == "INFERENCE"
    assert "39%" in result["future_orders_estimate"]
    assert result["current_order_source_urls"] == [primary]
    assert result["future_order_source_urls"] == [detail]
    assert _accession_root(primary) == _accession_root(detail)

    # Same accession but different amount cannot lend its schedule.
    wrong_amount = dict(result)
    wrong_amount["future_orders_estimate"] = base.FUTURE_FALLBACK
    wrong_amount["future_order_source_urls"] = []
    wrong_amount["claim_grounding"] = {
        "current_orders_summary": "SUPPORTED",
        "future_orders_estimate": "UNAVAILABLE",
    }
    wrong_amount["current_orders_summary"] = (
        "SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$2.6 billion（文件日2026-08-26）；"
        "RPO常排除短期合約，不能視為公司全部客戶訂單"
    )
    unchanged = _enrich_same_accession_package(
        wrong_amount,
        raw_fetcher=raw_fetcher,
        text_fetcher=text_fetcher,
    )
    assert unchanged["claim_grounding"]["future_orders_estimate"] == "UNAVAILABLE"

    print("V213_H6B1_R13_SAME_ACCESSION_PACKAGE_ENRICHMENT = PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    raise SystemExit(base.main())
