#!/usr/bin/env python3
"""Path-stable compatibility entrypoint for the v2.1.3 source gate.

The authoritative implementation is ``v213_source_independence_gate.py``.  This
entrypoint is retained for packaged-runtime and scheduled-task compatibility and
loads the sibling module explicitly from this script's directory.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parent
CORE_PATH = SCRIPT_DIR / "v213_source_independence_gate.py"


def load_core() -> ModuleType:
    if not CORE_PATH.is_file():
        raise RuntimeError(f"Missing source-independence core: {CORE_PATH}")
    spec = importlib.util.spec_from_file_location(
        "investor_intelligence_v213_source_gate",
        CORE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to create import specification: {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = load_core()


def self_test() -> None:
    assert gate.family_for(
        "fred_official_macro",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
    ) == "official_macro"
    assert gate.family_for(
        "sec_edgar",
        "https://www.sec.gov/Archives/edgar/data/1/test.htm",
    ) == "regulator_filing"
    assert gate.family_for(
        "yfinance_adjusted_close",
        "https://finance.yahoo.com/quote/NVDA/history",
    ) == "yahoo_market"
    assert gate.domain_of(
        "https://api.nasdaq.com/api/quote/NVDA/historical"
    ) == "nasdaq.com"
    print("V213_SOURCE_INDEPENDENCE_V2_SELF_TEST = PASS")


if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(gate.main())
