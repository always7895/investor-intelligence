#!/usr/bin/env python3
"""H6B1 R4 semantic guard for SEC order/backlog/RPO extraction.

H6B1 R3 proved that a generic sentence-level amount matcher is too permissive
for the final LINE seven-field report.  It can bind an unrelated dollar amount
from the same long SEC text window to an order label.  Examples observed in the
real R3 preview include CRDO ``$104,367``, AMD ``$946`` and APH ``backlog $23.5``.

This guard patches only the generic SEC order/outlook adapter.  It requires the
metric label and an explicitly unit-bearing amount to be linked by a bounded
semantic pattern, rejects acquired-backlog/amortization contexts, distinguishes
RPO from total customer orders, and only emits a forward outlook when an
explicit recognition schedule is present.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h6b1_zero_safe as zero_safe

base = zero_safe.base

UNIT_AMOUNT = r"(?P<amount>(?:(?:US|USD)\s*)?\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m|b)|(?:USD|US\$)\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m|b))"

METRIC_PATTERNS: list[tuple[int, str, str, re.Pattern[str]]] = [
    (
        0,
        "backlog",
        "BACKLOG",
        re.compile(rf"\bbacklog\b(?!\s+(?:resulting|related|amortization|fair value)).{{0,100}}?(?:was|were|is|are|total(?:ed)?|amounted\s+to|stood\s+at|of)\s+(?:approximately\s+|about\s+)?{UNIT_AMOUNT}", re.I | re.S),
    ),
    (
        0,
        "order book",
        "ORDER_BOOK",
        re.compile(rf"\border\s+book\b.{{0,100}}?(?:was|were|is|are|total(?:ed)?|amounted\s+to|stood\s+at|of)\s+(?:approximately\s+|about\s+)?{UNIT_AMOUNT}", re.I | re.S),
    ),
    (
        0,
        "production order",
        "PRODUCTION_ORDER",
        re.compile(rf"\bproduction\s+orders?\b.{{0,100}}?(?:was|were|is|are|total(?:ed)?|amounted\s+to|of|for)\s+(?:approximately\s+|about\s+)?{UNIT_AMOUNT}", re.I | re.S),
    ),
    (
        1,
        "RPO（剩餘履約義務；非全部客戶訂單）",
        "RPO",
        re.compile(rf"\bremaining\s+performance\s+obligations?\b.{{0,280}}?(?:was|were|is|are|total(?:ed)?|amounted\s+to|of)\s+(?:approximately\s+|about\s+)?{UNIT_AMOUNT}", re.I | re.S),
    ),
    (
        1,
        "RPO（剩餘履約義務；非全部客戶訂單）",
        "RPO",
        re.compile(rf"\bcontracted\s+but\s+unsatisfied\s+performance\s+obligations?\b.{{0,180}}?(?:was|were|is|are)\s+(?:approximately\s+|about\s+)?{UNIT_AMOUNT}", re.I | re.S),
    ),
]

BAD_BACKLOG_CONTEXT = re.compile(
    r"(?:acquired\s+backlog|amortization.{0,120}backlog|backlog.{0,120}amortization|fair\s+value.{0,120}backlog|purchase\s+accounting.{0,120}backlog)",
    re.I | re.S,
)

NEXT12_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "pct",
        re.compile(r"(?:expects?\s+to\s+recognize\s+(?:approximately\s+)?|expects?\s+)(?P<pct>\d+(?:\.\d+)?)%[^.]{0,180}?(?:next|subsequent)\s+(?:twelve|12)\s+months", re.I | re.S),
    ),
    (
        "pct",
        re.compile(r"(?P<pct>\d+(?:\.\d+)?)%[^.]{0,140}?(?:will|is\s+expected\s+to\s+be)\s+recognized[^.]{0,100}?(?:next|subsequent)\s+(?:twelve|12)\s+months", re.I | re.S),
    ),
    (
        "amount",
        re.compile(rf"(?:of\s+which\s+)?(?P<next_amount>(?:(?:US|USD)\s*)?\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m|b))\s+(?:is|are)\s+expected\s+to\s+be\s+recognized[^.]{{0,100}}?(?:next|subsequent)\s+(?:twelve|12)\s+months", re.I | re.S),
    ),
]


def _normalize_amount(value: str) -> str:
    return base.SPACE_RE.sub(" ", value).strip()


def _extract_strict_metric(text: str) -> dict[str, Any] | None:
    best: tuple[int, int, str, str, str, int, int] | None = None
    for priority, label, metric_type, pattern in METRIC_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            context = text[max(0, start - 180) : min(len(text), end + 240)]
            if metric_type == "BACKLOG" and BAD_BACKLOG_CONTEXT.search(context):
                continue
            amount = _normalize_amount(match.group("amount"))
            candidate = (priority, start, label, metric_type, amount, start, end)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    if best is None:
        return None
    _, _, label, metric_type, amount, start, end = best
    context = text[max(0, start - 120) : min(len(text), end + 1000)]
    return {
        "label": label,
        "metric_type": metric_type,
        "amount": amount,
        "context": context,
    }


def _future_from_context(metric: Mapping[str, Any]) -> tuple[str, str]:
    if str(metric.get("metric_type")) != "RPO":
        return base.FUTURE_FALLBACK, "UNAVAILABLE"
    context = str(metric.get("context") or "")
    for kind, pattern in NEXT12_PATTERNS:
        match = pattern.search(context)
        if not match:
            continue
        if kind == "pct":
            pct = match.group("pct")
            return f"公司預期約{pct}%的該RPO於未來12個月認列；這是既有合約履約節奏，不等於新增訂單預測", "INFERENCE"
        next_amount = _normalize_amount(match.group("next_amount"))
        return f"公司預期未來12個月認列約{next_amount}的該RPO；這是既有合約履約節奏，不等於新增訂單預測", "INFERENCE"
    if re.search(r"expect(?:s|ed)?\s+to\s+recognize[^.]{0,140}?(?:next|subsequent)\s+(?:twelve|12)\s+months", context, re.I | re.S):
        return "公司明示該RPO預計於未來12個月認列，但未在同一證據段落提供可安全量化的比例；非新增訂單預測", "INFERENCE"
    return base.FUTURE_FALLBACK, "UNAVAILABLE"


def recent_filing_urls_semantic(ticker: str, cik: str, fetcher=base.fetch_raw) -> list[tuple[str, str, str]]:
    raw = fetcher(f"https://data.sec.gov/submissions/CIK{cik}.json")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return []
    recent = ((doc.get("filings") or {}).get("recent") or {}) if isinstance(doc, Mapping) else {}
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    primary_docs = recent.get("primaryDocument") or []
    dates = recent.get("filingDate") or []
    rows: list[tuple[str, str, str]] = []
    for form, accession, primary, date in zip(forms, accessions, primary_docs, dates):
        form = str(form)
        if form not in base.FORM_PRIORITY:
            continue
        accession_clean = str(accession).replace("-", "")
        primary = str(primary)
        date = str(date)
        if not accession_clean or not primary:
            continue
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{primary}"
        rows.append((url, date, form))
        if len(rows) >= 80:
            break

    chosen: list[tuple[str, str, str]] = []
    for form in ("10-Q", "10-K", "20-F"):
        form_rows = sorted((row for row in rows if row[2] == form), key=lambda row: row[1], reverse=True)
        if form_rows:
            chosen.append(form_rows[0])
    event_rows = sorted((row for row in rows if row[2] in {"8-K", "6-K"}), key=lambda row: row[1], reverse=True)[:3]
    chosen.extend(event_rows)
    dedup: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in sorted(chosen, key=lambda row: row[1], reverse=True):
        if row[0] not in seen:
            dedup.append(row)
            seen.add(row[0])
    return dedup


def generic_sec_outlook_semantic(
    ticker: str,
    cik_map: Mapping[str, str],
    raw_fetcher=base.fetch_raw,
    text_fetcher=base.fetch_text,
) -> dict[str, Any]:
    cik = cik_map.get(ticker.upper())
    if not cik:
        return base.unavailable_outlook()
    candidates = recent_filing_urls_semantic(ticker, cik, fetcher=raw_fetcher)
    best: tuple[int, str, dict[str, Any], str] | None = None
    for url, filing_date, form in candidates:
        try:
            text = text_fetcher(url)
        except base.H6BError:
            continue
        metric = _extract_strict_metric(text)
        if not metric:
            continue
        metric_priority = 1 if metric["metric_type"] == "RPO" else 0
        candidate = (metric_priority, filing_date, metric, url)
        if best is None or candidate[0] < best[0] or (candidate[0] == best[0] and candidate[1] > best[1]):
            best = candidate
    if best is None:
        return base.unavailable_outlook()

    _, filing_date, metric, url = best
    label = str(metric["label"])
    amount = str(metric["amount"])
    metric_type = str(metric["metric_type"])
    if metric_type == "RPO":
        current = f"SEC揭露{label}約{amount}（文件日{filing_date}）；RPO常排除短期合約，不能視為公司全部客戶訂單"
        confidence = "HIGH_SEC_RPO_SEMANTICALLY_SCOPED"
    else:
        current = f"SEC文件明確揭露{label}約{amount}（文件日{filing_date}）；未以其他來源補估總額"
        confidence = "HIGH_SEC_DIRECT_ORDER_METRIC"
    future, future_class = _future_from_context(metric)
    return base._outlook(
        current,
        future,
        current_urls=[url],
        future_urls=[url] if future_class == "INFERENCE" else [],
        confidence=confidence,
        as_of=filing_date,
        current_classification="SUPPORTED",
        future_classification=future_class,
    )


def self_test() -> None:
    crdo = (
        "Remaining Performance Obligations Revenue allocated to remaining performance obligations represents the transaction price. "
        "The contracted but unsatisfied performance obligations as of January 31, 2026 were approximately $31.8 million which the Company expects to recognize over the next 12 months. "
        "Elsewhere an unrelated table contains $104,367."
    )
    metric = _extract_strict_metric(crdo)
    assert metric and metric["amount"] == "$31.8 million"
    future, klass = _future_from_context(metric)
    assert klass == "INFERENCE" and "未來12個月" in future

    amd = (
        "Revenue allocated to remaining performance obligations that are unsatisfied or partially unsatisfied include product revenue. "
        "As of June 27, 2026, the aggregate transaction price allocated to remaining performance obligations under contracts with an original expected duration of more than one year was $222 million, of which $144 million is expected to be recognized in the next 12 months. "
        "Another note contains $946."
    )
    metric = _extract_strict_metric(amd)
    assert metric and metric["amount"] == "$222 million"
    future, klass = _future_from_context(metric)
    assert klass == "INFERENCE" and "$144 million" in future

    aph_false = (
        "During the quarter depreciation and amortization expense included $23.5 related to the amortization of acquired backlog resulting from the CommScope acquisition."
    )
    assert _extract_strict_metric(aph_false) is None

    nvda = (
        "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length was $3.2 billion. "
        "Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months."
    )
    metric = _extract_strict_metric(nvda)
    assert metric and metric["amount"] == "$3.2 billion"
    future, klass = _future_from_context(metric)
    assert klass == "INFERENCE" and "39%" in future

    assert _extract_strict_metric("remaining performance obligations were $946") is None
    print("V213_H6B1_R4_ORDER_METRIC_SEMANTIC_GUARD = PASS")


base.recent_filing_urls = recent_filing_urls_semantic
base.generic_sec_outlook = generic_sec_outlook_semantic


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    raise SystemExit(base.main())
