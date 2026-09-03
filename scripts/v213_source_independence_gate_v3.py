#!/usr/bin/env python3
"""Compatibility entrypoint for the final v2.1.3 source-independence gate.

The implementation lives in ``v213_source_independence_gate_v4.py``. This stable
path is retained because existing launchers, qualification scripts and static
audits invoke or inspect the v3 filename.

The aliases below intentionally preserve the reviewed public compatibility
surface instead of duplicating the implementation. Runtime execution, wrapper
self-tests and imported policy helpers all resolve to the same v4 objects.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

V4_PATH = Path(__file__).resolve().with_name("v213_source_independence_gate_v4.py")
if not V4_PATH.is_file():
    raise RuntimeError(f"Missing final source-independence implementation: {V4_PATH}")
spec = importlib.util.spec_from_file_location(
    "investor_intelligence_v213_source_gate_v4_entrypoint",
    V4_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load final source-independence gate: {V4_PATH}")
v4 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v4
spec.loader.exec_module(v4)

# Stable import surface. These are aliases to the authoritative v4 objects, not
# copies, so downstream callers and audits cannot drift from runtime behavior.
gate = v4.gate
apply_market_quality_policy = v4.apply_market_quality_policy
MARKET_DEGRADATION_CODE = v4.MARKET_DEGRADATION_CODE
INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE = v4.MARKET_DEGRADATION_CODE


def self_test() -> None:
    """Execute the authoritative final-gate wrapper regression."""
    v4.self_test()


# Worker-compatible output and methodology fields that the stable entrypoint
# guarantees through the v4 implementation.
WORKER_COMPATIBILITY_FIELDS = frozenset(
    {
        "blocking_violations",
        "degradations",
        "market_corroboration_global_blocker",
        "market_corroboration_required_for_high_confidence_model_inference",
        "uncorroborated_valuation_factor_max",
        "provider_failure_must_not_be_silently_relabelled_as_success",
        "market_data_is_not_averaged_into_published_returns",
    }
)

__all__ = [
    "gate",
    "self_test",
    "apply_market_quality_policy",
    "MARKET_DEGRADATION_CODE",
    "INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE",
    "WORKER_COMPATIBILITY_FIELDS",
]

if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(v4.gate.main())
