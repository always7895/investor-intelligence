#!/usr/bin/env python3
"""H6B1 R15: ASCII unit-boundary repair for quantitative fulfillment detection.

R14 introduced a quantitative detector for already-INFERENCE fulfillment text.
Its dollar-amount branch ended with ``\b`` after ``million|billion|m|b``.
Python's default regular expressions use Unicode word semantics, so a Traditional-
Chinese character immediately following an English unit is also a ``\w``
character.  Therefore a valid string such as ``$144 million於未來12個月認列``
failed the detector even though the amount is explicit and correctly scoped.

R15 changes only that token boundary.  The unit must not be followed by an ASCII
letter, which still rejects glued suffixes such as ``millionUSD`` or ``2.6MB``
while allowing CJK punctuation/text immediately after the unit.

All R14 provenance, same-accession, current-order, ranking and fail-closed rules
remain unchanged.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h6b1_metric_semantic_guard_v9 as r14

base = r14.base

QUANTITATIVE_FUTURE_RE_V10 = re.compile(
    r"(?:\d+(?:\.\d+)?%|\$\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m|b)(?![A-Za-z])|三分之一|幾乎全部|202\d)",
    re.I,
)


def _future_is_quantitative_v10(text: str) -> bool:
    return bool(QUANTITATIVE_FUTURE_RE_V10.search(str(text)))


# r14._quantitative_upgrade_same_accession resolves this module global at call
# time.  Replace only the detector; do not replace selection/enrichment logic.
r14._future_is_quantitative = _future_is_quantitative_v10


def generic_sec_outlook_semantic_v10(*args, **kwargs):
    return r14.generic_sec_outlook_semantic_v9(*args, **kwargs)


base.generic_sec_outlook = generic_sec_outlook_semantic_v10


def self_test() -> None:
    assert _future_is_quantitative_v10("約43%於未來12個月認列；非新增訂單預測")
    assert _future_is_quantitative_v10("約$144 million於未來12個月認列；非新增訂單預測")
    assert _future_is_quantitative_v10("約$2,732.0 million（文件日2026-08-06）")
    assert _future_is_quantitative_v10("約$3.2 billion；39%於未來12個月認列")
    assert _future_is_quantitative_v10("約$2.6M於未來12個月認列")
    assert _future_is_quantitative_v10("約三分之一於未來12個月認列；非新增訂單預測")
    assert not _future_is_quantitative_v10("未來12個月認列，但未提供可安全量化的比例；非新增訂單預測")
    assert not _future_is_quantitative_v10("約$144 millionUSD於未來12個月認列")
    assert not _future_is_quantitative_v10("約$2.6MB於未來12個月認列")

    # R14's full self-test must remain valid under the repaired detector.
    r14.self_test()
    print("V213_H6B1_R15_ASCII_UNIT_BOUNDARY = PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    raise SystemExit(base.main())
