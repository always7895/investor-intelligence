#!/usr/bin/env python3
"""Corrected entrypoint for the v2.1.3 source-independence gate.

The base implementation reduces hosts to registrable domains.  FRED therefore
normalizes to ``stlouisfed.org``; this wrapper makes that normalized domain an
explicit official-macro family without changing the accepted audit schema.
"""
from __future__ import annotations

import sys

import v213_source_independence_gate as gate

_ORIGINAL_FAMILY_FOR = gate.family_for


def family_for(source_id: str, url: str) -> str:
    domain = gate.domain_of(url)
    if domain == "stlouisfed.org":
        return "official_macro"
    return _ORIGINAL_FAMILY_FOR(source_id, url)


gate.family_for = family_for


def self_test() -> None:
    assert family_for(
        "fred_official_macro",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
    ) == "official_macro"
    assert family_for(
        "sec_edgar",
        "https://www.sec.gov/Archives/edgar/data/1/test.htm",
    ) == "regulator_filing"
    print("V213_SOURCE_INDEPENDENCE_V2_SELF_TEST = PASS")


if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(gate.main())
