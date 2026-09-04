#!/usr/bin/env python3
"""H6B1 R9: canonical money formatting and explicit fulfillment-schedule capture.

R8 fixed clause crossing for current backlog/RPO amounts.  Its real 20-row output
also showed that the future-order column remained too conservative for several
filings whose current RPO/backlog was correctly bound but whose filing explicitly
stated a fulfillment/revenue-recognition schedule.

This wrapper keeps every R8 clause-safe current-order rule and only extends the
future-evidence grammar.  It never turns a recognition schedule into a forecast
of *new* orders.  The user-visible wording explicitly labels these as existing
RPO/backlog fulfillment schedules.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h6b1_metric_semantic_guard_v3 as r8

r4 = r8.r4
base = r4.base


def _normalize_amount_v4(value: str) -> str:
    """Canonicalize money spacing without changing units or magnitude."""
    text = base.SPACE_RE.sub(" ", str(value)).strip()
    text = re.sub(r"(?i)\b(?:USD|US)\s*\$\s*", "US$", text)
    text = re.sub(r"\$\s+", "$", text)
    return text


def _future_from_context_v4(metric: Mapping[str, Any]) -> tuple[str, str]:
    metric_type = str(metric.get("metric_type") or "")
    context = str(metric.get("context") or "")

    # A disclosed backlog fulfillment schedule is useful, but it is not a
    # prediction of newly booked orders.
    if metric_type == "BACKLOG":
        if re.search(
            r"nearly\s+all[^.]{0,140}?backlog[^.]{0,160}?will\s+be\s+filled"
            r"[^.]{0,100}?(?:within|over)\s+(?:the\s+)?next\s+(?:twelve|12)\s+months",
            context,
            re.I | re.S,
        ):
            return (
                "公司預期幾乎全部既有backlog於未來12個月內履行；"
                "屬既有訂單履約節奏，非新增訂單預測",
                "INFERENCE",
            )
        return base.FUTURE_FALLBACK, "UNAVAILABLE"

    if metric_type != "RPO":
        return base.FUTURE_FALLBACK, "UNAVAILABLE"

    # Amount-based next-12-month schedule (AMD-style).
    amount_patterns = [
        re.compile(
            r"(?:of\s+which\s+)?"
            r"(?P<amount>(?:(?:US|USD)\s*)?\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m|b))"
            r"\s+(?:is|are)\s+expected\s+to\s+be\s+recognized[^.]{0,160}?"
            r"(?:next|following|subsequent)\s+(?:twelve|12)\s+months",
            re.I | re.S,
        ),
    ]
    for pattern in amount_patterns:
        match = pattern.search(context)
        if match:
            amount = _normalize_amount_v4(match.group("amount"))
            return (
                f"公司預期未來12個月認列約{amount}的該RPO；"
                "這是既有合約履約節奏，不等於新增訂單預測",
                "INFERENCE",
            )

    # Numeric-percentage schedules.  These variants cover actual SEC grammar:
    #   expects to recognize approximately 43% ... next 12 months
    #   expected to recognize 64% ... next 12 months
    #   expects 46% to be recognized ... next twelve months
    #   approximately 39% ... will be recognized ... next twelve months
    pct_patterns = [
        re.compile(
            r"expect(?:s|ed)?\s+to\s+recognize\s+(?:revenue\s+on\s+)?"
            r"(?:approximately\s+)?(?P<pct>\d+(?:\.\d+)?)%[^.]{0,240}?"
            r"(?:next|following|subsequent)\s+(?:twelve|12)\s+months",
            re.I | re.S,
        ),
        re.compile(
            r"expect(?:s|ed)?\s+(?:approximately\s+)?(?P<pct>\d+(?:\.\d+)?)%"
            r"[^.]{0,220}?(?:to\s+be|will\s+be|is\s+expected\s+to\s+be)\s+recognized"
            r"[^.]{0,160}?(?:next|following|subsequent)\s+(?:twelve|12)\s+months",
            re.I | re.S,
        ),
        re.compile(
            r"(?P<pct>\d+(?:\.\d+)?)%[^.]{0,220}?"
            r"(?:will\s+be|is\s+expected\s+to\s+be|to\s+be)\s+recognized"
            r"[^.]{0,160}?(?:next|following|subsequent)\s+(?:twelve|12)\s+months",
            re.I | re.S,
        ),
    ]
    for pattern in pct_patterns:
        match = pattern.search(context)
        if match:
            pct = match.group("pct")
            return (
                f"公司預期約{pct}%的該RPO於未來12個月認列；"
                "這是既有合約履約節奏，不等於新增訂單預測",
                "INFERENCE",
            )

    # Worded fractions/quantifiers seen in filings.  Do not convert them into a
    # fabricated decimal percentage; preserve the issuer's disclosed wording.
    if re.search(
        r"approximately\s+one[-\s]third[^.]{0,220}?remaining\s+performance\s+obligations"
        r"[^.]{0,180}?(?:expected\s+to\s+be|will\s+be)\s+recognized[^.]{0,120}?"
        r"(?:next|following)\s+(?:twelve|12)\s+months",
        context,
        re.I | re.S,
    ):
        return (
            "公司預期約三分之一的該RPO於未來12個月認列；"
            "這是既有合約履約節奏，不等於新增訂單預測",
            "INFERENCE",
        )

    # CRDO-style disclosure: the whole disclosed RPO is expected over the next
    # fiscal year.  Keep the issuer's fiscal-year precision instead of silently
    # converting it to calendar 12 months.
    if re.search(
        r"expect(?:s|ed)?\s+to\s+recognize[^.]{0,160}?over\s+the\s+next\s+fiscal\s+year",
        context,
        re.I | re.S,
    ):
        return (
            "公司預期該RPO於下一會計年度認列；屬既有合約履約節奏，非新增訂單預測",
            "INFERENCE",
        )

    # CF-style explicit multi-period schedule.  Preserve all disclosed buckets.
    cf = re.search(
        r"recognize\s+approximately\s+(?P<p1>\d+(?:\.\d+)?)%[^.]{0,80}?remainder\s+of\s+(?P<y1>20\d{2})"
        r"[^.]{0,180}?approximately\s+(?P<p2>\d+(?:\.\d+)?)%[^.]{0,80}?(?:during|in)\s+(?P<y2>20\d{2}\s*[-–]\s*20\d{2})"
        r"[^.]{0,180}?approximately\s+(?P<p3>\d+(?:\.\d+)?)%[^.]{0,80}?(?:during|in)\s+(?P<y3>20\d{2}\s*[-–]\s*20\d{2})",
        context,
        re.I | re.S,
    )
    if cf:
        y2 = re.sub(r"\s*[-–]\s*", "–", cf.group("y2"))
        y3 = re.sub(r"\s*[-–]\s*", "–", cf.group("y3"))
        return (
            f"既有RPO履約節奏：{cf.group('y1')}剩餘期間約{cf.group('p1')}%、"
            f"{y2}約{cf.group('p2')}%、{y3}約{cf.group('p3')}%，其餘其後；"
            "非新增訂單預測",
            "INFERENCE",
        )

    # Retain the older safe qualitative fallback without calling the mutable
    # r4 dispatch slot. Later compatibility wrappers patch that slot at import
    # time, and a dynamic call here otherwise becomes order-dependent recursion.
    if re.search(
        r"expect(?:s|ed)?\s+to\s+recognize[^.]{0,140}?"
        r"(?:next|subsequent)\s+(?:twelve|12)\s+months",
        context,
        re.I | re.S,
    ):
        return (
            "公司明示該RPO預計於未來12個月認列，但未在同一證據段落提供"
            "可安全量化的比例；非新增訂單預測",
            "INFERENCE",
        )
    return base.FUTURE_FALLBACK, "UNAVAILABLE"


# Patch the functions referenced dynamically by the existing generic adapter.
r4._normalize_amount = _normalize_amount_v4
r4._future_from_context = _future_from_context_v4


def self_test() -> None:
    cases = [
        (
            "NVDA",
            "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length was $ 3.2 billion. Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months.",
            "$3.2 billion",
            "39%",
        ),
        (
            "AVGO",
            "Remaining performance obligations under these contracts as of May 3, 2026 were approximately $ 164.6 billion. We expect approximately 30% of this amount to be recognized as revenue over the next 12 months.",
            "$164.6 billion",
            "30%",
        ),
        (
            "LIF",
            "Revenue expected to be recognized in connection with remaining performance obligations was $ 186.8 million as of June 30, 2026, of which the Company expects 46% to be recognized over the next twelve months.",
            "$186.8 million",
            "46%",
        ),
        (
            "NET",
            "As of June 30, 2026, the aggregate amount of the transaction price allocated to remaining performance obligations was $ 2,732.0 million. The Company expected to recognize 64% of its remaining performance obligations as revenue over the next 12 months.",
            "$2,732.0 million",
            "64%",
        ),
        (
            "SMCI",
            "The value of the transaction price allocated to the remaining performance obligations as of June 30, 2026, was approximately $ 2,612.0 million. We expect to recognize approximately 60% of such value in the next 12 months, and the remainder thereafter.",
            "$2,612.0 million",
            "60%",
        ),
        (
            "PLTR",
            "The Company's remaining performance obligations were $ 4.9 billion as of June 30, 2026, of which the Company expects to recognize approximately 43% as revenue over the next 12 months, 36% over the subsequent 13 to 36 months, and the remainder thereafter.",
            "$4.9 billion",
            "43%",
        ),
    ]
    for ticker, text, expected_amount, expected_future in cases:
        metric = r4._extract_strict_metric(text)
        assert metric is not None, ticker
        assert _normalize_amount_v4(metric["amount"]) == expected_amount, (ticker, metric)
        future, klass = _future_from_context_v4(metric)
        assert klass == "INFERENCE", (ticker, future)
        assert expected_future in future, (ticker, future)

    mu = (
        "As of May 28, 2026, the transaction price allocated to our remaining performance obligations was approximately $ 5 billion. "
        "Approximately one-third of the remaining performance obligations as of May 28, 2026 are expected to be recognized as revenue over the next twelve months."
    )
    metric = r4._extract_strict_metric(mu)
    assert metric and _normalize_amount_v4(metric["amount"]) == "$5 billion"
    future, klass = _future_from_context_v4(metric)
    assert klass == "INFERENCE" and "三分之一" in future

    amd = (
        "As of June 27, 2026, the aggregate transaction price allocated to remaining performance obligations under contracts with an original expected duration of more than one year was $ 222 million, of which $ 144 million is expected to be recognized in the next 12 months."
    )
    metric = r4._extract_strict_metric(amd)
    future, klass = _future_from_context_v4(metric or {})
    assert metric and _normalize_amount_v4(metric["amount"]) == "$222 million"
    assert klass == "INFERENCE" and "$144 million" in future

    crdo = (
        "The contracted but unsatisfied performance obligation was approximately $ 31.9 million which the Company expects to recognize over the next fiscal year."
    )
    metric = r4._extract_strict_metric(crdo)
    future, klass = _future_from_context_v4(metric or {})
    assert metric and _normalize_amount_v4(metric["amount"]) == "$31.9 million"
    assert klass == "INFERENCE" and "下一會計年度" in future

    aph = (
        "The Company estimates that its backlog of unfilled firm orders as of December 31, 2025 was approximately $ 8.9 billion. "
        "It is expected that nearly all of the Company's backlog will be filled within the next 12 months."
    )
    metric = r4._extract_strict_metric(aph)
    future, klass = _future_from_context_v4(metric or {})
    assert metric and _normalize_amount_v4(metric["amount"]) == "$8.9 billion"
    assert klass == "INFERENCE" and "幾乎全部" in future

    cf = (
        "Our remaining performance obligations under these contracts were approximately $ 1.5 billion. "
        "We expect to recognize approximately 17% of these performance obligations as revenue in the remainder of 2026, approximately 43% as revenue during 2027-2029, approximately 14% as revenue during 2030-2032, and the remainder as revenue thereafter."
    )
    metric = r4._extract_strict_metric(cf)
    future, klass = _future_from_context_v4(metric or {})
    assert metric and _normalize_amount_v4(metric["amount"]) == "$1.5 billion"
    assert klass == "INFERENCE" and "17%" in future and "2027–2029" in future and "14%" in future

    # Preserve the R8 false-positive protections.
    false_crdo = (
        "inventory increased to support unfulfilled backlog and related new product ramps; "
        "other assets increased by $71.3 million of payment for refundable deposits to suppliers. "
        "The contracted but unsatisfied performance obligation was approximately $31.9 million."
    )
    metric = r4._extract_strict_metric(false_crdo)
    assert metric and metric["metric_type"] == "RPO" and _normalize_amount_v4(metric["amount"]) == "$31.9 million"
    assert r4._extract_strict_metric("remaining performance obligations were $946") is None
    assert r4._extract_strict_metric("amortization expense included $23.5 related to the amortization of acquired backlog") is None

    print("V213_H6B1_R9_FULFILLMENT_SCHEDULE_CAPTURE = PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    raise SystemExit(r4.base.main())
