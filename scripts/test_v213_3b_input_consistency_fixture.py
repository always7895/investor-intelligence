#!/usr/bin/env python3
"""TASK0-3B-2: minimal Top20/source-audit mismatch reproduction (isolated fixture).

Positive control: a complete, consistent 20-ticker input set (top20 rows and
source-audit records share the same 20 tickers) -> the REAL
apply_latest_evidence_factor_guard() completes (returns a dict, no raise).

Negative control: the current 11/11 set mismatch (top20 holds 11 tickers the
audit lacks) -> the REAL guard raises SnapshotError("Source-audit row missing
for <first missing ticker>") BEFORE any factor is evaluated. This proves the
mismatch is an INPUT-CONSISTENCY failure at the guard's first per-ticker check,
not an evaluated-but-insufficient-claim result.

Isolated: monkeypatches the module's file paths to synthetic temp files; never
touches the formal data/cache or config. No network. Exit 0 on pass.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_PATH = SCRIPT_DIR / "v213_build_v21_public_snapshot.py"

spec = importlib.util.spec_from_file_location("ii_v213_3b_guard", BUILD_PATH)
if spec is None or spec.loader is None:
    print("FAIL: unable to load guard module", file=sys.stderr)
    raise SystemExit(1)
g = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = g
spec.loader.exec_module(g)
base = g.base  # the loaded build_v21_public_snapshot module

TICKERS_20 = [f"T{i:02d}" for i in range(20)]
# 11 tickers the audit will LACK (the current mismatch shape).
MISSING_FROM_AUDIT = TICKERS_20[:11]


def make_top20(tickers):
    rows = []
    for i, tk in enumerate(tickers):
        rows.append({
            "ticker": tk,
            "rank": i + 1,
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
            "data_quality": 0.9,
        })
    return rows


def make_audit(tickers):
    # Fresh qualified claim support for every provided ticker (2 units, 2 domains, 1 primary).
    now = datetime.now(timezone.utc)
    stamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    records = []
    for i, tk in enumerate(tickers):
        records.append({
            "ticker": tk,
            "rank": i + 1,
            "sources": [
                {"family": "regulator_filing", "domain": "sec.gov", "claim_type": "xbrl_fact",
                 "url": f"https://www.sec.gov/{tk}", "as_of": stamp, "primary": True},
                {"family": "issuer_primary", "domain": f"investor.{tk.lower()}.com",
                 "claim_type": "earnings_release", "url": f"https://investor.{tk.lower()}.com/{tk}",
                 "as_of": stamp, "primary": False},
            ],
        })
    return {"records": records}


def make_federation(tickers):
    # _reorder_records expects document[key] to be a LIST of 20 rows (each with a ticker).
    # markdown_report needs federation["gates"] with specific fields.
    return {
        "ticker_sources": [{"ticker": tk} for tk in tickers],
        "gates": {
            "successful_families": ["regulator_filing", "issuer_primary"],
            "official_successful_families": ["regulator_filing"],
            "ticker_coverage_ratio": 1.0,
            "largest_family_share": 0.5,
        },
    }


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_guard(tmp: Path, top20, audit, federation):
    """Point the guard's file paths at synthetic temp files and run it."""
    p_top20 = tmp / "top20.json"
    p_audit = tmp / "audit.json"
    p_fed = tmp / "federation.json"
    p_policy = tmp / "policy.json"
    p_v212 = tmp / "v212.json"
    p_v213 = tmp / "v213.json"
    p_report = tmp / "report.md"
    write_json(p_top20, top20)
    write_json(p_audit, audit)
    write_json(p_fed, federation)
    write_json(p_policy, {"current_state_claim_max_age_days": 135,
                          "sensitive_advantage_factors": ["demand_wave", "chokepoint", "pricing_power",
                                                          "replacement_friction", "tam_capture"]})
    write_json(p_v212, {"records": top20})
    write_json(p_v213, {"records": top20})
    # Monkeypatch the module's path variables to the synthetic temp files.
    saved = {
        "base.TOP20_PATH": base.TOP20_PATH,
        "g.SOURCE_AUDIT_PATH": g.SOURCE_AUDIT_PATH,
        "g.FEDERATION_PATH": g.FEDERATION_PATH,
        "g.FRESHNESS_POLICY_PATH": g.FRESHNESS_POLICY_PATH,
        "g.V212_PATH": g.V212_PATH,
        "g.V213_PATH": g.V213_PATH,
        "base.REPORT_PATH": base.REPORT_PATH,
    }
    base.TOP20_PATH = p_top20
    g.SOURCE_AUDIT_PATH = p_audit
    g.FEDERATION_PATH = p_fed
    g.FRESHNESS_POLICY_PATH = p_policy
    g.V212_PATH = p_v212
    g.V213_PATH = p_v213
    base.REPORT_PATH = p_report
    try:
        return g.apply_latest_evidence_factor_guard()
    finally:
        base.TOP20_PATH = saved["base.TOP20_PATH"]
        g.SOURCE_AUDIT_PATH = saved["g.SOURCE_AUDIT_PATH"]
        g.FEDERATION_PATH = saved["g.FEDERATION_PATH"]
        g.FRESHNESS_POLICY_PATH = saved["g.FRESHNESS_POLICY_PATH"]
        g.V212_PATH = saved["g.V212_PATH"]
        g.V213_PATH = saved["g.V213_PATH"]
        base.REPORT_PATH = saved["base.REPORT_PATH"]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="v213_3b_") as tmp:
        tmp = Path(tmp)

        # POSITIVE CONTROL: complete consistent 20-ticker input set.
        pos_top20 = make_top20(TICKERS_20)
        pos_audit = make_audit(TICKERS_20)
        pos_fed = make_federation(TICKERS_20)
        result = run_guard(tmp, pos_top20, pos_audit, pos_fed)
        assert isinstance(result, dict), f"positive control should return a dict, got {type(result)}"
        assert "withheld_ticker_count" in result, "positive control result missing withheld_ticker_count"
        # All 20 have qualified fresh support -> 0 withheld.
        assert result["withheld_ticker_count"] == 0, \
            f"positive control: all qualified, expected 0 withheld, got {result['withheld_ticker_count']}"
        print(f"POSITIVE_CONTROL = PASS; consistent 20-ticker input -> guard completed, withheld={result['withheld_ticker_count']}")

        # NEGATIVE CONTROL: current 11/11 set mismatch. The audit has EXACTLY 20
        # rows (so the len==20 check passes), but 11 of them are tickers the top20
        # does NOT have, and 11 top20 tickers are missing from the audit. This is
        # the real mismatch shape: same row count, different membership.
        neg_top20 = make_top20(TICKERS_20)
        mismatched_audit_tickers = TICKERS_20[11:] + [f"X{i:02d}" for i in range(11)]  # 9 match + 11 foreign
        neg_audit = make_audit(mismatched_audit_tickers)
        neg_fed = make_federation(TICKERS_20)
        raised = None
        try:
            run_guard(tmp, neg_top20, neg_audit, neg_fed)
        except base.SnapshotError as exc:
            raised = exc
        assert raised is not None, "negative control: guard should raise SnapshotError on missing audit row"
        msg = str(raised)
        assert "Source-audit row missing" in msg, f"negative control: unexpected message: {msg}"
        first_missing = MISSING_FROM_AUDIT[0]
        assert first_missing in msg, f"negative control: expected first missing ticker {first_missing} in: {msg}"
        print(f"NEGATIVE_CONTROL = PASS; 11/11 membership mismatch (20 rows each) -> guard raised SnapshotError before evaluating any factor: {msg}")

    print("V213_3B_INPUT_CONSISTENCY_FIXTURE = PASS; positive=consistent-completes; negative=mismatch-raises-before-eval")
    raise SystemExit(0)


if __name__ == "__main__":
    raise SystemExit(main())