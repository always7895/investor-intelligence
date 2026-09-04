#!/usr/bin/env python3
"""H6B1 R6 recognition-schedule wording repair.

The R4 semantic guard correctly scopes SEC backlog/RPO amounts, but its percentage
recognition pattern accepted ``will recognized`` rather than the actual SEC phrase
``will be recognized``.  This wrapper replaces only the next-12-month recognition
patterns and leaves the strict order/RPO amount binding unchanged.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h6b1_metric_semantic_guard as r4


NEXT12_PATTERNS_V2: list[tuple[str, re.Pattern[str]]] = [
    (
        "pct",
        re.compile(
            r"(?:expects?\s+to\s+recognize\s+(?:approximately\s+)?|expects?\s+)"
            r"(?P<pct>\d+(?:\.\d+)?)%[^.]{0,180}?(?:next|subsequent)\s+(?:twelve|12)\s+months",
            re.I | re.S,
        ),
    ),
    (
        "pct",
        re.compile(
            r"(?P<pct>\d+(?:\.\d+)?)%[^.]{0,180}?"
            r"(?:will\s+be|is\s+expected\s+to\s+be)\s+recognized[^.]{0,120}?"
            r"(?:next|subsequent)\s+(?:twelve|12)\s+months",
            re.I | re.S,
        ),
    ),
    (
        "amount",
        re.compile(
            r"(?:of\s+which\s+)?"
            r"(?P<next_amount>(?:(?:US|USD)\s*)?\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m|b))"
            r"\s+(?:is|are)\s+expected\s+to\s+be\s+recognized[^.]{0,120}?"
            r"(?:next|subsequent)\s+(?:twelve|12)\s+months",
            re.I | re.S,
        ),
    ),
]

# Apply before any build path can evaluate RPO recognition schedules.
r4.NEXT12_PATTERNS = NEXT12_PATTERNS_V2


def self_test() -> None:
    nvda = (
        "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length "
        "was $3.2 billion. Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months."
    )
    metric = r4._extract_strict_metric(nvda)
    assert metric and metric["amount"] == "$3.2 billion"
    future, classification = r4._future_from_context(metric)
    assert classification == "INFERENCE"
    assert "39%" in future

    amd = (
        "Revenue allocated to remaining performance obligations includes product revenue. As of June 27, 2026, "
        "the aggregate transaction price allocated to remaining performance obligations under contracts with an original expected duration "
        "of more than one year was $222 million, of which $144 million is expected to be recognized in the next 12 months."
    )
    metric = r4._extract_strict_metric(amd)
    assert metric and metric["amount"] == "$222 million"
    future, classification = r4._future_from_context(metric)
    assert classification == "INFERENCE"
    assert "$144 million" in future

    # R4 strict amount/backlog protections remain intact.
    assert r4._extract_strict_metric("remaining performance obligations were $946") is None
    assert r4._extract_strict_metric(
        "amortization expense included $23.5 related to the amortization of acquired backlog"
    ) is None
    print("V213_H6B1_R6_RECOGNITION_WORDING = PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    raise SystemExit(r4.base.main())
