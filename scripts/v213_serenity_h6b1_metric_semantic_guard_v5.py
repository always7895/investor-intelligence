#!/usr/bin/env python3
"""H6B1 R10: canonical non-new-order disclaimer wording.

R9's fulfillment-schedule semantics were correct, but several output branches used
"不等於新增訂單預測" while the regression contract required the equivalent phrase
"非新增訂單預測". This wrapper changes only that user-visible disclaimer wording.
It does not change any metric extraction, amount binding, schedule inference,
classification, source selection, ranking, or Production behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h6b1_metric_semantic_guard_v4 as r9

r4 = r9.r4
base = r4.base
_ORIGINAL_FUTURE = r9._future_from_context_v4
CANONICAL_DISCLAIMER = "非新增訂單預測"


def _canonicalize_disclaimer(text: str) -> str:
    value = str(text)
    value = value.replace("不等於新增訂單預測", CANONICAL_DISCLAIMER)
    value = value.replace("不是新增訂單預測", CANONICAL_DISCLAIMER)
    return value


def _future_from_context_v5(metric: Mapping[str, Any]) -> tuple[str, str]:
    future, classification = _ORIGINAL_FUTURE(metric)
    if classification == "INFERENCE":
        future = _canonicalize_disclaimer(future)
        if CANONICAL_DISCLAIMER not in future:
            future = future.rstrip("；。 ") + "；" + CANONICAL_DISCLAIMER
    return future, classification


# Generic SEC adapter references this function dynamically through the R4 module.
r4._future_from_context = _future_from_context_v5


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
        future, klass = _future_from_context_v5(metric)
        assert klass == "INFERENCE", (ticker, future)
        assert needle in future, (ticker, future)
        assert CANONICAL_DISCLAIMER in future, (ticker, future)
        assert "不等於新增訂單預測" not in future, (ticker, future)

    assert _canonicalize_disclaimer("既有履約節奏，不等於新增訂單預測") == "既有履約節奏，非新增訂單預測"
    print("V213_H6B1_R10_CANONICAL_DISCLAIMER = PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    raise SystemExit(base.main())
