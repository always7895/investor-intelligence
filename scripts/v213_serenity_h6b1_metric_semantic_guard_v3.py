#!/usr/bin/env python3
"""H6B1 R8 clause-safe order metric binding.

R7 exposed a second-order false positive in Credo's fiscal-2026 10-K.  The filing
said inventory increased to support "unfulfilled backlog" and, after a semicolon,
said other assets increased by $71.3 million for refundable supplier-capacity
deposits.  The R4 bounded-dot backlog regex was allowed to cross that semicolon
and incorrectly labelled the unrelated $71.3 million as backlog.

This wrapper changes only the order-metric grammar: a backlog/order/RPO label may
bind a money amount only inside the same clause (no period, semicolon or newline
between label and amount).  It preserves R6 recognition-schedule wording fixes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h6b1_metric_semantic_guard_v2 as r6

r4 = r6.r4
UNIT_AMOUNT = r4.UNIT_AMOUNT

CLAUSE_120 = r"[^.;\n]{0,120}?"
CLAUSE_180 = r"[^.;\n]{0,180}?"
CLAUSE_280 = r"[^.;\n]{0,280}?"

CLAUSE_SAFE_METRIC_PATTERNS: list[tuple[int, str, str, re.Pattern[str]]] = [
    (
        0,
        "backlog",
        "BACKLOG",
        re.compile(
            rf"\bbacklog\b(?!\s+(?:resulting|related|amortization|fair value))"
            rf"{CLAUSE_120}(?:was|were|is|are|total(?:ed)?|amounted\s+to|stood\s+at|of)\s+"
            rf"(?:approximately\s+|about\s+)?{UNIT_AMOUNT}",
            re.I | re.S,
        ),
    ),
    (
        0,
        "order book",
        "ORDER_BOOK",
        re.compile(
            rf"\border\s+book\b{CLAUSE_120}"
            rf"(?:was|were|is|are|total(?:ed)?|amounted\s+to|stood\s+at|of)\s+"
            rf"(?:approximately\s+|about\s+)?{UNIT_AMOUNT}",
            re.I | re.S,
        ),
    ),
    (
        0,
        "production order",
        "PRODUCTION_ORDER",
        re.compile(
            rf"\bproduction\s+orders?\b{CLAUSE_120}"
            rf"(?:was|were|is|are|total(?:ed)?|amounted\s+to|of|for)\s+"
            rf"(?:approximately\s+|about\s+)?{UNIT_AMOUNT}",
            re.I | re.S,
        ),
    ),
    (
        1,
        "RPO（剩餘履約義務；非全部客戶訂單）",
        "RPO",
        re.compile(
            rf"\bremaining\s+performance\s+obligations?\b{CLAUSE_280}"
            rf"(?:was|were|is|are|total(?:ed)?|amounted\s+to|of)\s+"
            rf"(?:approximately\s+|about\s+)?{UNIT_AMOUNT}",
            re.I | re.S,
        ),
    ),
    (
        1,
        "RPO（剩餘履約義務；非全部客戶訂單）",
        "RPO",
        re.compile(
            rf"\bcontracted\s+but\s+unsatisfied\s+performance\s+obligations?\b{CLAUSE_180}"
            rf"(?:was|were|is|are)\s+(?:approximately\s+|about\s+)?{UNIT_AMOUNT}",
            re.I | re.S,
        ),
    ),
]

# Patch the table used by R4's _extract_strict_metric().
r4.METRIC_PATTERNS = CLAUSE_SAFE_METRIC_PATTERNS


def self_test() -> None:
    crdo_false_then_true = (
        "The cash outflows from working capital were driven by an increase in inventory of $174.0 million "
        "to support unfulfilled backlog and related new product ramps; (c) an increase in other current and "
        "non-current assets of $71.3 million of payment for refundable deposits to suppliers. "
        "Revenue Recognition. Remaining Performance Obligations. The contracted but unsatisfied performance "
        "obligation was approximately $31.9 million which the Company expects to recognize over the next fiscal year."
    )
    metric = r4._extract_strict_metric(crdo_false_then_true)
    assert metric is not None
    assert metric["metric_type"] == "RPO"
    assert metric["amount"] == "$31.9 million"

    # A genuinely quantified backlog in the same clause remains valid.
    real_backlog = "As of July 31, 2026, we had backlog of approximately $5.9 billion."
    metric = r4._extract_strict_metric(real_backlog)
    assert metric is not None
    assert metric["metric_type"] == "BACKLOG"
    assert metric["amount"] == "$5.9 billion"

    # R6 recognition wording behavior must remain intact.
    nvda = (
        "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length "
        "was $3.2 billion. Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months."
    )
    metric = r4._extract_strict_metric(nvda)
    assert metric and metric["amount"] == "$3.2 billion"
    future, classification = r4._future_from_context(metric)
    assert classification == "INFERENCE" and "39%" in future

    assert r4._extract_strict_metric("remaining performance obligations were $946") is None
    assert r4._extract_strict_metric(
        "amortization expense included $23.5 related to the amortization of acquired backlog"
    ) is None
    print("V213_H6B1_R8_CLAUSE_SAFE_METRIC_BINDING = PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    raise SystemExit(r4.base.main())
