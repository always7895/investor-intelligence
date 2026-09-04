#!/usr/bin/env python3
"""H6B1 R11: immutable fallback dispatch for fulfillment-schedule semantics.

R10 canonicalized the user-visible disclaimer, but its wrapper stacked on top of
R9's dynamically patched ``r4._future_from_context``.  R9's fallback itself
called that same mutable module attribute.  Once R10 replaced the attribute, an
otherwise-valid RPO that did not match one of R9's explicit schedule patterns
entered a v5 -> v4 -> v5 recursion loop.

R11 collapses the live future-schedule path onto the last stable clause-safe
layer (R8), captures the pre-R11 R6 future parser exactly once, and uses that
immutable function object for fallback.  No fallback calls a mutable dispatch
slot.  It preserves R8 clause-safe current-order binding, all R9 fulfillment
schedule cases, and the R10 canonical disclaimer.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Import the clause-safe layer directly.  This avoids inheriting R9/R10's
# mutable fallback chain while preserving R6 recognition wording and R8 metric
# binding through the shared r4 module.
import v213_serenity_h6b1_metric_semantic_guard_v3 as r8

r4 = r8.r4
base = r4.base
CANONICAL_DISCLAIMER = "非新增訂單預測"


def _stable_pre_r11_future(metric: Mapping[str, Any]) -> tuple[str, str]:
    """R6 fallback copied into an immutable local dispatch slot.

    Earlier wrappers mutate ``r4._future_from_context`` at import time, so
    capturing that module attribute is order-dependent under full discovery.
    """
    if str(metric.get("metric_type")) != "RPO":
        return base.FUTURE_FALLBACK, "UNAVAILABLE"
    context = str(metric.get("context") or "")
    for kind, pattern in r4.NEXT12_PATTERNS:
        match = pattern.search(context)
        if not match:
            continue
        if kind == "pct":
            pct = match.group("pct")
            return (
                f"公司預期約{pct}%的該RPO於未來12個月認列；"
                "這是既有合約履約節奏，不等於新增訂單預測",
                "INFERENCE",
            )
        next_amount = _normalize_amount_v6(match.group("next_amount"))
        return (
            f"公司預期未來12個月認列約{next_amount}的該RPO；"
            "這是既有合約履約節奏，不等於新增訂單預測",
            "INFERENCE",
        )
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


_PRE_R11_FUTURE = _stable_pre_r11_future


def _normalize_amount_v6(value: str) -> str:
    """Canonicalize money spacing without changing value, unit, or magnitude."""
    text = base.SPACE_RE.sub(" ", str(value)).strip()
    text = re.sub(r"(?i)\b(?:USD|US)\s*\$\s*", "US$", text)
    text = re.sub(r"\$\s+", "$", text)
    return text


def _canonicalize_result(future: str, classification: str) -> tuple[str, str]:
    text = str(future)
    if classification != "INFERENCE":
        return text, classification
    text = text.replace("不等於新增訂單預測", CANONICAL_DISCLAIMER)
    text = text.replace("不是新增訂單預測", CANONICAL_DISCLAIMER)
    if CANONICAL_DISCLAIMER not in text:
        text = text.rstrip("；。 ") + "；" + CANONICAL_DISCLAIMER
    return text, classification


def _future_from_context_v6(metric: Mapping[str, Any]) -> tuple[str, str]:
    metric_type = str(metric.get("metric_type") or "")
    context = str(metric.get("context") or "")

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
    amount_pattern = re.compile(
        r"(?:of\s+which\s+)?"
        r"(?P<amount>(?:(?:US|USD)\s*)?\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m|b))"
        r"\s+(?:is|are)\s+expected\s+to\s+be\s+recognized[^.]{0,160}?"
        r"(?:next|following|subsequent)\s+(?:twelve|12)\s+months",
        re.I | re.S,
    )
    match = amount_pattern.search(context)
    if match:
        amount = _normalize_amount_v6(match.group("amount"))
        return (
            f"公司預期未來12個月認列約{amount}的該RPO；"
            "這是既有合約履約節奏，非新增訂單預測",
            "INFERENCE",
        )

    # Numeric-percentage schedules seen in actual issuer filings.
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
                "這是既有合約履約節奏，非新增訂單預測",
                "INFERENCE",
            )

    # Preserve issuer wording for a disclosed fraction instead of inventing a
    # decimal conversion.
    if re.search(
        r"approximately\s+one[-\s]third[^.]{0,220}?remaining\s+performance\s+obligations"
        r"[^.]{0,180}?(?:expected\s+to\s+be|will\s+be)\s+recognized[^.]{0,120}?"
        r"(?:next|following)\s+(?:twelve|12)\s+months",
        context,
        re.I | re.S,
    ):
        return (
            "公司預期約三分之一的該RPO於未來12個月認列；"
            "這是既有合約履約節奏，非新增訂單預測",
            "INFERENCE",
        )

    # CRDO-style fiscal-year precision.
    if re.search(
        r"expect(?:s|ed)?\s+to\s+recognize[^.]{0,160}?over\s+the\s+next\s+fiscal\s+year",
        context,
        re.I | re.S,
    ):
        return (
            "公司預期該RPO於下一會計年度認列；屬既有合約履約節奏，非新增訂單預測",
            "INFERENCE",
        )

    # CF-style explicit multi-period schedule.
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

    # Critical R11 boundary: fallback is an immutable function object captured
    # before this module patches r4._future_from_context.  Never call the
    # mutable r4._future_from_context slot from inside this fallback path.
    future, classification = _PRE_R11_FUTURE(metric)
    return _canonicalize_result(future, classification)


generic_sec_outlook_semantic_v6 = r4.generic_sec_outlook_semantic


# Generic SEC adapter looks this up dynamically.  The implementation above never
# re-enters this mutable slot, so the patch cannot create recursive fallback.
r4._normalize_amount = _normalize_amount_v6
r4._future_from_context = _future_from_context_v6


def self_test() -> None:
    fixtures = [
        (
            "NVDA",
            "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length was $ 3.2 billion. Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months.",
            "39%",
        ),
        (
            "AMD",
            "As of June 27, 2026, the aggregate transaction price allocated to remaining performance obligations under contracts with an original expected duration of more than one year was $ 222 million, of which $ 144 million is expected to be recognized in the next 12 months.",
            "$144 million",
        ),
        (
            "MU",
            "As of May 28, 2026, the transaction price allocated to our remaining performance obligations was approximately $ 5 billion. Approximately one-third of the remaining performance obligations as of May 28, 2026 are expected to be recognized as revenue over the next twelve months.",
            "三分之一",
        ),
        (
            "CRDO",
            "The contracted but unsatisfied performance obligation was approximately $ 31.9 million which the Company expects to recognize over the next fiscal year.",
            "下一會計年度",
        ),
        (
            "APH",
            "The Company estimates that its backlog of unfilled firm orders as of December 31, 2025 was approximately $ 8.9 billion. It is expected that nearly all of the Company's backlog will be filled within the next 12 months.",
            "幾乎全部",
        ),
    ]
    for ticker, text, needle in fixtures:
        metric = r4._extract_strict_metric(text)
        assert metric is not None, ticker
        future, classification = _future_from_context_v6(metric)
        assert classification == "INFERENCE", (ticker, future)
        assert needle in future, (ticker, future)
        assert CANONICAL_DISCLAIMER in future, (ticker, future)
        assert "不等於新增訂單預測" not in future, (ticker, future)

    # This is the path that crashed R10.  It intentionally avoids every R9
    # numeric/fraction/fiscal-year special case, forcing the stable qualitative
    # R6 fallback.  Repeated calls prove that dispatch is non-recursive.
    fallback_text = (
        "Remaining performance obligations were approximately $ 1.2 billion. "
        "The Company expects to recognize revenue associated with these remaining performance obligations over the next twelve months."
    )
    metric = r4._extract_strict_metric(fallback_text)
    assert metric is not None
    for _ in range(64):
        future, classification = _future_from_context_v6(metric)
        assert classification == "INFERENCE"
        assert "未在同一證據段落提供可安全量化的比例" in future
        assert CANONICAL_DISCLAIMER in future
    assert _PRE_R11_FUTURE is not r4._future_from_context

    # R8 fail-closed current-order protections remain intact.
    false_crdo = (
        "inventory increased to support unfulfilled backlog and related new product ramps; "
        "other assets increased by $71.3 million of payment for refundable deposits to suppliers. "
        "The contracted but unsatisfied performance obligation was approximately $31.9 million."
    )
    metric = r4._extract_strict_metric(false_crdo)
    assert metric and metric["metric_type"] == "RPO"
    assert _normalize_amount_v6(metric["amount"]) == "$31.9 million"
    assert r4._extract_strict_metric("remaining performance obligations were $946") is None
    assert r4._extract_strict_metric(
        "amortization expense included $23.5 related to the amortization of acquired backlog"
    ) is None

    print("V213_H6B1_R11_IMMUTABLE_FALLBACK_DISPATCH = PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    raise SystemExit(base.main())
