#!/usr/bin/env python3
"""H6B1 R12: source-view fulfillment enrichment without changing current-order binding.

R11 removed the mutable-dispatch recursion and successfully built the real 20-row
shadow.  The real run then showed a different failure mode: a supported current
RPO can be selected from an early/duplicate iXBRL-visible occurrence whose
bounded context does not contain the issuer's fulfillment sentence, even though
the same selected SEC document contains another occurrence of the same RPO
amount with the explicit schedule.

R12 does not loosen current-order extraction.  It first runs the accepted R11
semantic adapter unchanged.  Only when that adapter has SUPPORTED current orders
and UNAVAILABLE future orders does R12 re-open the *same selected source view*,
find another clause-safe occurrence with the same metric type and same normalized
amount, and ask the non-recursive R11 fulfillment parser to classify its local
context.  Different amounts, different metric types and different documents
cannot supply the enrichment.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h6b1_metric_semantic_guard_v6 as r11

r4 = r11.r4
base = r11.base
_BASE_GENERIC = r4.generic_sec_outlook_semantic


def _metric_type_from_current_summary(current: str) -> str | None:
    text = str(current)
    if "RPO" in text:
        return "RPO"
    if re.search(r"\bbacklog\b", text, re.I):
        return "BACKLOG"
    if re.search(r"\border\s+book\b", text, re.I):
        return "ORDER_BOOK"
    if re.search(r"\bproduction\s+orders?\b", text, re.I):
        return "PRODUCTION_ORDER"
    return None


def _amount_from_current_summary(current: str) -> str | None:
    match = base.AMOUNT_RE.search(str(current))
    if not match:
        return None
    amount = r11._normalize_amount_v6(match.group(0))
    # Current-order semantic binding always requires a unit-bearing amount.
    if not re.search(r"(?i)\b(?:million|billion|m|b)\b", amount):
        return None
    return amount


def _same_metric_schedule_from_source(
    text: str,
    *,
    metric_type: str,
    amount: str,
) -> tuple[str, str] | None:
    """Return a future schedule only from the same metric+amount in one source.

    This is deliberately narrower than a general document search.  It cannot
    borrow a schedule from another RPO balance or from a backlog/order metric.
    """
    target_amount = r11._normalize_amount_v6(amount)
    for _priority, label, candidate_type, pattern in r4.METRIC_PATTERNS:
        if candidate_type != metric_type:
            continue
        for match in pattern.finditer(text):
            candidate_amount = r11._normalize_amount_v6(match.group("amount"))
            if candidate_amount != target_amount:
                continue
            start, end = match.span()
            context = text[max(0, start - 240) : min(len(text), end + 2400)]
            metric: dict[str, Any] = {
                "label": label,
                "metric_type": candidate_type,
                "amount": candidate_amount,
                "context": context,
            }
            future, classification = r11._future_from_context_v6(metric)
            if classification == "INFERENCE":
                return future, classification
    return None


def _enrich_same_selected_source(
    result: Mapping[str, Any],
    *,
    text_fetcher=base.fetch_text,
) -> dict[str, Any]:
    out = dict(result)
    grounding = dict(out.get("claim_grounding") or {})
    if grounding.get("current_orders_summary") != "SUPPORTED":
        return out
    if grounding.get("future_orders_estimate") != "UNAVAILABLE":
        return out

    current = str(out.get("current_orders_summary") or "")
    metric_type = _metric_type_from_current_summary(current)
    amount = _amount_from_current_summary(current)
    source_urls = [str(url) for url in out.get("current_order_source_urls") or [] if str(url).startswith("https://")]
    if not metric_type or not amount or len(source_urls) != 1:
        return out

    source_url = source_urls[0]
    try:
        text = text_fetcher(source_url)
    except base.H6BError:
        return out

    enriched = _same_metric_schedule_from_source(text, metric_type=metric_type, amount=amount)
    if enriched is None:
        return out
    future, classification = enriched
    if classification != "INFERENCE":
        return out

    out["future_orders_estimate"] = future
    out["future_order_source_urls"] = [source_url]
    grounding["future_orders_estimate"] = "INFERENCE"
    out["claim_grounding"] = grounding
    return out


def generic_sec_outlook_semantic_v7(
    ticker: str,
    cik_map: Mapping[str, str],
    raw_fetcher=base.fetch_raw,
    text_fetcher=base.fetch_text,
) -> dict[str, Any]:
    # Preserve R11 current-order/source selection exactly.
    result = _BASE_GENERIC(
        ticker,
        cik_map,
        raw_fetcher=raw_fetcher,
        text_fetcher=text_fetcher,
    )
    return _enrich_same_selected_source(result, text_fetcher=text_fetcher)


# Both call sites exist in the current H6B stack: tests call the semantic module,
# while the Top20 builder calls base.generic_sec_outlook.  Patch both to the same
# non-recursive wrapper.
r4.generic_sec_outlook_semantic = generic_sec_outlook_semantic_v7
base.generic_sec_outlook = generic_sec_outlook_semantic_v7


def self_test() -> None:
    # Simulate an early/duplicate iXBRL-visible current RPO occurrence whose
    # 1,000-char context misses the schedule, followed by the same amount in the
    # actual visible disclosure with the explicit 39% schedule.
    duplicate_nvda = (
        "Remaining performance obligations were $ 3.2 billion. "
        + ("duplicate-fact-no-schedule " * 70)
        + "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length was $ 3.2 billion. "
        + "Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months."
    )
    metric = r4._extract_strict_metric(duplicate_nvda)
    assert metric is not None and r11._normalize_amount_v6(metric["amount"]) == "$3.2 billion"
    old_future, old_class = r11._future_from_context_v6(metric)
    assert old_class == "UNAVAILABLE", old_future
    enriched = _same_metric_schedule_from_source(duplicate_nvda, metric_type="RPO", amount="$3.2 billion")
    assert enriched is not None and enriched[1] == "INFERENCE" and "39%" in enriched[0]
    assert "非新增訂單預測" in enriched[0]

    # Never borrow a schedule from a different RPO amount.
    mixed_amounts = (
        "Remaining performance obligations were approximately $ 3.2 billion with no disclosed recognition schedule. "
        "A prior-period remaining performance obligations balance was approximately $ 2.6 billion. "
        "Approximately 40% of the $ 2.6 billion prior-period balance will be recognized over the next twelve months."
    )
    assert _same_metric_schedule_from_source(mixed_amounts, metric_type="RPO", amount="$3.2 billion") is None

    # Exercise the real adapter wrapper with the duplicate-source shape.
    def raw_fetcher(url: str) -> str:
        import json
        return json.dumps({
            "filings": {"recent": {
                "form": ["10-Q"],
                "accessionNumber": ["0001045810-26-000075"],
                "primaryDocument": ["nvda-20260726.htm"],
                "filingDate": ["2026-08-26"],
            }}
        })

    def text_fetcher(url: str) -> str:
        return duplicate_nvda

    result = generic_sec_outlook_semantic_v7(
        "NVDA",
        {"NVDA": "1045810"},
        raw_fetcher=raw_fetcher,
        text_fetcher=text_fetcher,
    )
    assert result["claim_grounding"]["current_orders_summary"] == "SUPPORTED"
    assert result["claim_grounding"]["future_orders_estimate"] == "INFERENCE"
    assert "39%" in result["future_orders_estimate"]
    assert result["future_order_source_urls"] == result["current_order_source_urls"]

    print("V213_H6B1_R12_SAME_SOURCE_FULFILLMENT_ENRICHMENT = PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    raise SystemExit(base.main())
