#!/usr/bin/env python3
"""Path-stable compatibility entrypoint for the v2.1.3 source gate.

The authoritative implementation is ``v213_source_independence_gate.py``. This
entrypoint is retained for packaged-runtime and scheduled-task compatibility,
loads the sibling module explicitly, and emits no-secret provider diagnostics so
a failed non-Yahoo corroboration gate is actionable rather than opaque.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

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


def _safe_error(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"(?i)(?:api[_-]?key|apikey|token)=([^&\s]+)", r"\1=<redacted>", text)
    return " ".join(text.split())[:240] or "none"


_original_collect_observations = gate.collect_observations


def diagnostic_collect_observations(
    ticker: str,
    cache: dict[str, Any],
    api_key: str,
    offline: bool,
):
    resolved_ticker, observations = _original_collect_observations(
        ticker,
        cache,
        api_key,
        offline,
    )
    for observation in observations:
        status = str(getattr(observation, "status", "UNKNOWN"))
        provider = str(getattr(observation, "provider", "unknown"))
        if status in {"LIVE", "CACHED"}:
            print(
                "II_PROGRESS market corroboration "
                f"{resolved_ticker} | {provider} | {status} | "
                f"as_of={getattr(observation, 'as_of', '')}",
                flush=True,
            )
        else:
            print(
                "II_DIAGNOSTIC market corroboration unavailable "
                f"{resolved_ticker} | {provider} | status={status} | "
                f"error={_safe_error(getattr(observation, 'error', ''))}",
                flush=True,
            )
    return resolved_ticker, observations


gate.collect_observations = diagnostic_collect_observations


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
    assert _safe_error("apikey=secret&x=1") == "apikey=<redacted>&x=1"
    print("V213_SOURCE_INDEPENDENCE_V2_SELF_TEST = PASS")


if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(gate.main())
