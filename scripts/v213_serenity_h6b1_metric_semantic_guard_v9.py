#!/usr/bin/env python3
"""H6B1 R14: quantitative-specificity upgrade inside the same SEC accession.

R13 correctly recovered filing-package schedules when the future field was still
UNAVAILABLE.  The real R13 preview exposed a narrower gap: the base parser can
already classify a future schedule as INFERENCE using a qualitative sentence
such as "expected in the next 12 months" while a more specific percentage is
present elsewhere in the same selected filing/accession.  Once classified as
INFERENCE, R13 intentionally stopped and therefore left PLTR/NET/SMCI with less
specific text than their public SEC filings support.

R14 does not change current-order selection and does not turn an unavailable
future into an inference unless R13 already could do so.  It only replaces an
existing qualitative INFERENCE with a more specific quantitative INFERENCE when
all of the following are true:
- current orders are SUPPORTED;
- the current metric type and normalized amount are preserved;
- evidence stays inside the same selected SEC accession package;
- the candidate schedule is produced by the already accepted non-recursive R11
  fulfillment parser; and
- all quantitative candidates agree exactly.

This is a specificity upgrade, not a new-order forecast.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h6b1_metric_semantic_guard_v8 as r13

r12 = r13.r12
r11 = r13.r11
base = r13.base
_BASE_R13_GENERIC = r13.generic_sec_outlook_semantic_v8

QUANTITATIVE_FUTURE_RE = re.compile(
    r"(?:\d+(?:\.\d+)?%|\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m|b)\b|三分之一|幾乎全部|202\d)",
    re.I,
)


def _future_is_quantitative(text: str) -> bool:
    return bool(QUANTITATIVE_FUTURE_RE.search(str(text)))


def _quantitative_upgrade_same_accession(
    result: Mapping[str, Any],
    *,
    raw_fetcher=base.fetch_raw,
    text_fetcher=base.fetch_text,
) -> dict[str, Any]:
    out = dict(result)
    grounding = dict(out.get("claim_grounding") or {})
    if grounding.get("current_orders_summary") != "SUPPORTED":
        return out
    if grounding.get("future_orders_estimate") != "INFERENCE":
        return out

    existing_future = str(out.get("future_orders_estimate") or "")
    if _future_is_quantitative(existing_future):
        return out

    current = str(out.get("current_orders_summary") or "")
    metric_type = r12._metric_type_from_current_summary(current)
    amount = r12._amount_from_current_summary(current)
    current_urls = [
        str(url)
        for url in out.get("current_order_source_urls") or []
        if str(url).startswith("https://")
    ]
    if not metric_type or not amount or len(current_urls) != 1:
        return out

    current_url = current_urls[0]
    root = r13._accession_root(current_url)
    if not root:
        return out

    candidate_urls = [current_url]
    candidate_urls.extend(
        r13._same_accession_report_urls(current_url, raw_fetcher=raw_fetcher)
    )
    seen: set[str] = set()
    found: list[tuple[str, str]] = []

    for url in candidate_urls:
        if url in seen:
            continue
        seen.add(url)
        if r13._accession_root(url) != root:
            continue
        try:
            text = text_fetcher(url)
        except base.H6BError:
            continue
        enriched = r12._same_metric_schedule_from_source(
            text,
            metric_type=metric_type,
            amount=amount,
        )
        if enriched is None or enriched[1] != "INFERENCE":
            continue
        future = str(enriched[0])
        if not _future_is_quantitative(future):
            continue
        found.append((future, url))

    if not found:
        return out

    unique_futures = {future for future, _url in found}
    if len(unique_futures) != 1:
        return out

    future = next(iter(unique_futures))
    urls = list(dict.fromkeys(url for candidate_future, url in found if candidate_future == future))
    out["future_orders_estimate"] = future
    out["future_order_source_urls"] = urls
    grounding["future_orders_estimate"] = "INFERENCE"
    out["claim_grounding"] = grounding
    return out


def generic_sec_outlook_semantic_v9(
    ticker: str,
    cik_map: Mapping[str, str],
    raw_fetcher=base.fetch_raw,
    text_fetcher=base.fetch_text,
) -> dict[str, Any]:
    result = _BASE_R13_GENERIC(
        ticker,
        cik_map,
        raw_fetcher=raw_fetcher,
        text_fetcher=text_fetcher,
    )
    return _quantitative_upgrade_same_accession(
        result,
        raw_fetcher=raw_fetcher,
        text_fetcher=text_fetcher,
    )


r13.r4.generic_sec_outlook_semantic = generic_sec_outlook_semantic_v9
base.generic_sec_outlook = generic_sec_outlook_semantic_v9


def _fixture_result(amount: str, source_url: str) -> dict[str, Any]:
    return base._outlook(
        f"SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約{amount}（文件日2026-08-01）；RPO常排除短期合約，不能視為公司全部客戶訂單",
        "公司明示該RPO預計於未來12個月認列，但未在同一證據段落提供可安全量化的比例；非新增訂單預測",
        current_urls=[source_url],
        future_urls=[source_url],
        confidence="HIGH_SEC_RPO_SEMANTICALLY_SCOPED",
        as_of="2026-08-01",
        current_classification="SUPPORTED",
        future_classification="INFERENCE",
    )


def self_test() -> None:
    primary = "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/company.htm"
    detail = "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/R10.htm"
    summary = "<FilingSummary><Report><HtmlFileName>R10.htm</HtmlFileName></Report></FilingSummary>"

    fixtures = [
        ("$4.9 billion", "43%"),
        ("$2,732.0 million", "64%"),
        ("$2,612.0 million", "60%"),
    ]

    for amount, pct in fixtures:
        result = _fixture_result(amount, primary)

        def raw_fetcher(url: str) -> str:
            if url.endswith("/FilingSummary.xml"):
                return summary
            raise AssertionError(url)

        def text_fetcher(url: str) -> str:
            if url == primary:
                return f"Remaining performance obligations were {amount}."
            if url == detail:
                return (
                    f"Remaining performance obligations were {amount}. "
                    f"The Company expects to recognize approximately {pct} of such value in the next 12 months."
                )
            raise AssertionError(url)

        upgraded = _quantitative_upgrade_same_accession(
            result,
            raw_fetcher=raw_fetcher,
            text_fetcher=text_fetcher,
        )
        assert pct in upgraded["future_orders_estimate"], upgraded
        assert upgraded["claim_grounding"]["future_orders_estimate"] == "INFERENCE"
        assert upgraded["future_order_source_urls"] == [detail]
        assert "非新增訂單預測" in upgraded["future_orders_estimate"]

    # A conflicting quantitative schedule in the same accession must not upgrade.
    result = _fixture_result("$4.9 billion", primary)
    summary_conflict = (
        "<FilingSummary>"
        "<Report><HtmlFileName>R10.htm</HtmlFileName></Report>"
        "<Report><HtmlFileName>R11.htm</HtmlFileName></Report>"
        "</FilingSummary>"
    )

    def raw_conflict(url: str) -> str:
        if url.endswith("/FilingSummary.xml"):
            return summary_conflict
        raise AssertionError(url)

    def text_conflict(url: str) -> str:
        if url == primary:
            return "Remaining performance obligations were $4.9 billion."
        if url.endswith("/R10.htm"):
            return "Remaining performance obligations were $4.9 billion. Approximately 43% will be recognized over the next twelve months."
        if url.endswith("/R11.htm"):
            return "Remaining performance obligations were $4.9 billion. Approximately 44% will be recognized over the next twelve months."
        raise AssertionError(url)

    unchanged = _quantitative_upgrade_same_accession(
        result,
        raw_fetcher=raw_conflict,
        text_fetcher=text_conflict,
    )
    assert "可安全量化" in unchanged["future_orders_estimate"]

    print("V213_H6B1_R14_QUANTITATIVE_SPECIFICITY_UPGRADE = PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    raise SystemExit(base.main())
