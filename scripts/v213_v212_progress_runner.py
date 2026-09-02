#!/usr/bin/env python3
"""Build the v2.1.2 five-field intermediate from an exact provisional Top20.

The provisional shortlist is deliberately not a publishable v2.1 snapshot.  This
wrapper grants it the narrowest possible compatibility bridge: it may be read by
the five-field market/SEC builder so later live-source federation can produce the
final diversified ranking.  The public snapshot validators remain unchanged and
continue to reject provisional rows.
"""
from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_v212_top20_report as report

PROVISIONAL_SCORING_VERSION = "system-operationalization-v2.1.3-safe-preselection"
FACTOR_KEYS = {
    "demand_wave",
    "chokepoint",
    "pricing_power",
    "replacement_friction",
    "tam_capture",
    "valuation_expectations",
    "evidence_quality",
}
OVERLAY_KEYS = {
    "domain",
    "fit_score",
    "included_in_serenity_score",
    "attribution",
}


def _fail(message: str) -> None:
    raise report.Top20ReportError(message)


def _finite(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _timestamp(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 40:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_provisional_top20(records: Any) -> list[dict[str, Any]]:
    """Accept only the exact local intermediate boundary required by Stage 4.

    This validator is installed temporarily into ``build_v212_top20_report`` and
    restored immediately after that builder exits.  It cannot make a provisional
    record eligible for a signed snapshot or Worker promotion.
    """
    if not isinstance(records, list) or len(records) != 20:
        _fail("Provisional Top20 must contain exactly 20 records")

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    expected_keys = report.snapshot.RECORD_KEYS
    for index, raw in enumerate(records, 1):
        if not isinstance(raw, dict) or set(raw) != expected_keys:
            _fail(f"Provisional Top20 record {index} has an invalid closed schema")
        ticker = str(raw.get("ticker") or "").upper()
        if (
            not ticker
            or ticker in seen
            or raw.get("rank") != index
            or raw.get("scoring_version") != PROVISIONAL_SCORING_VERSION
            or raw.get("rating") != "PROVISIONAL"
            or raw.get("line_public_eligible") is not True
            or raw.get("provider_scope") != "public_only"
            or raw.get("owner_watchlist_inherited") is not False
        ):
            _fail(f"Provisional Top20 {ticker or index} boundary is invalid")
        seen.add(ticker)

        for key in (
            "serenity_score",
            "serenity_raw_score",
            "risk_penalty",
            "data_quality",
        ):
            if not _finite(raw.get(key)):
                _fail(f"Provisional Top20 {ticker} has invalid numeric field {key}")
        if not 0 <= float(raw["serenity_score"]) <= 100:
            _fail(f"Provisional Top20 {ticker} score is outside 0..100")
        if not 0 <= float(raw["data_quality"]) <= 1:
            _fail(f"Provisional Top20 {ticker} data quality is outside 0..1")

        factors = raw.get("serenity_factors")
        if (
            not isinstance(factors, dict)
            or set(factors) != FACTOR_KEYS
            or any(not _finite(value) for value in factors.values())
            or float(factors["demand_wave"]) != 0.0
            or float(factors["chokepoint"]) != 0.0
            or float(factors["pricing_power"]) != 0.0
            or float(factors["replacement_friction"]) != 0.0
            or float(factors["tam_capture"]) > 6.0
            or float(factors["valuation_expectations"]) > 3.75
        ):
            _fail(f"Provisional Top20 {ticker} bypassed safe-preselection factor caps")

        overlay = raw.get("aschenbrenner_overlay")
        if (
            not isinstance(overlay, dict)
            or set(overlay) != OVERLAY_KEYS
            or overlay.get("included_in_serenity_score") is not False
            or overlay.get("attribution")
            != "system_operationalization_not_aschenbrenner_stock_score"
        ):
            _fail(f"Provisional Top20 {ticker} overlay boundary is invalid")

        evidence = raw.get("evidence")
        if (
            not isinstance(evidence, list)
            or not evidence
            or raw.get("evidence_count") != len(evidence)
            or not isinstance(raw.get("source_count"), int)
            or int(raw["source_count"]) < 1
            or not isinstance(raw.get("risk_flags"), list)
            or any(not isinstance(flag, str) for flag in raw["risk_flags"])
            or not _timestamp(raw.get("generated_at"))
            or not _timestamp(raw.get("as_of"))
        ):
            _fail(f"Provisional Top20 {ticker} evidence/timestamp boundary is invalid")

        result.append({**raw, "ticker": ticker})

    expected = sorted(
        result,
        key=lambda item: (
            -float(item["serenity_score"]),
            -float(item["data_quality"]),
            str(item["ticker"]),
        ),
    )
    if result != expected:
        _fail("Provisional Top20 ordering is not deterministic")
    report.snapshot.reject_private_keys(result)
    return result


def main() -> int:
    original_market = report._market_observation
    original_validator = report.snapshot.validate_top20
    counter = {"value": 0}

    def progress_market_observation(ticker: str, fallback_industry: str):
        counter["value"] += 1
        print(
            f"II_PROGRESS v2.1.2 market/SEC row {counter['value']}/20 | {ticker}",
            flush=True,
        )
        return original_market(ticker, fallback_industry)

    report._market_observation = progress_market_observation
    report.snapshot.validate_top20 = validate_provisional_top20
    try:
        return report.main()
    finally:
        report._market_observation = original_market
        report.snapshot.validate_top20 = original_validator


if __name__ == "__main__":
    raise SystemExit(main())
