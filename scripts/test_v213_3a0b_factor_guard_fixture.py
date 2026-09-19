#!/usr/bin/env python3
"""TASK0-3A-0B item 4: same positive factors, market-only vs qualified fresh
claim support -> the former is still withheld, the latter is retained.

Standalone diagnostic fixture. Loads the REAL guard logic from
scripts/v213_build_v21_public_snapshot.py (offline; no network) and asserts the
fail-closed factor guard behavior. Exit 0 on pass.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_PATH = SCRIPT_DIR / "v213_build_v21_public_snapshot.py"

spec = importlib.util.spec_from_file_location("ii_v213_3a0b_guard", BUILD_PATH)
if spec is None or spec.loader is None:
    print("FAIL: unable to load guard module", file=sys.stderr)
    raise SystemExit(1)
g = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = g
spec.loader.exec_module(g)

policy = {
    "current_state_claim_max_age_days": 135,
    "sensitive_advantage_factors": [
        "demand_wave", "chokepoint", "pricing_power", "replacement_friction", "tam_capture",
    ],
}

now = datetime.now(timezone.utc)
stamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")

row = {
    "ticker": "T1",
    "serenity_factors": {
        "demand_wave": 10.0, "chokepoint": 0.0, "pricing_power": 10.0,
        "replacement_friction": 0.0, "tam_capture": 10.0,
        "valuation_expectations": 5.0, "evidence_quality": 5.0,
    },
    "risk_flags": [],
    "risk_penalty": 0.0,
    "serenity_score": 45.0,
    "serenity_raw_score": 45.0,
    "rating": "C",
}

# Market-only sources: never company-advantage claim evidence.
market_only_audit = {
    "sources": [
        {
            "family": "yahoo_market",
            "domain": "yahoo.com",
            "claim_type": "market_return_calculation",
            "url": "https://finance.yahoo.com/t1",
            "as_of": stamp,
            "primary": False,
        },
        {
            "family": "nasdaq_market",
            "domain": "nasdaq.com",
            "claim_type": "public_market_observation",
            "url": "https://www.nasdaq.com/t1",
            "as_of": stamp,
            "primary": False,
        },
    ]
}

# Qualified fresh claim support: two independent claim units + two domains + a primary.
qualified_audit = {
    "sources": [
        {
            "family": "regulator_filing",
            "domain": "sec.gov",
            "claim_type": "xbrl_fact",
            "url": "https://www.sec.gov/t1",
            "as_of": stamp,
            "primary": True,
        },
        {
            "family": "issuer_primary",
            "domain": "investor.t1.com",
            "claim_type": "earnings_release",
            "url": "https://investor.t1.com/t1",
            "as_of": stamp,
            "primary": False,
        },
    ]
}

expected_withheld = ["demand_wave", "pricing_power", "tam_capture"]

# Market-only: all positive sensitive factors must be withheld (zeroed).
market_row = copy.deepcopy(row)
removed_market = g._guard_row(market_row, market_only_audit, policy, now)
assert removed_market == expected_withheld, f"market-only should withhold {expected_withheld}, got {removed_market}"
for name in expected_withheld:
    assert market_row["serenity_factors"][name] == 0.0, f"{name} not zeroed under market-only"
assert market_row["serenity_score"] < row["serenity_score"], "market-only score must drop"
assert "positive_advantage_withheld_until_fresh_multisource_support" in market_row["risk_flags"], \
    "market-only must carry the withheld risk flag"

# Qualified fresh: positive factors retained (no withholding).
qualified_row = copy.deepcopy(row)
removed_qual = g._guard_row(qualified_row, qualified_audit, policy, now)
assert removed_qual == [], f"qualified fresh should retain factors, got {removed_qual}"
for name in expected_withheld:
    assert qualified_row["serenity_factors"][name] == row["serenity_factors"][name], \
        f"{name} changed under qualified fresh"
assert qualified_row["serenity_score"] == row["serenity_score"], "qualified fresh score must be unchanged"

print("V213_3A0B_FACTOR_GUARD_FIXTURE = PASS; market_only=withheld; qualified_fresh=retained")
raise SystemExit(0)