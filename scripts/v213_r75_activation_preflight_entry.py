#!/usr/bin/env python3
"""Compatibility entrypoint for the sealed R75 activation preflight."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

import v213_r75_activation_preflight as core


def validate_freshness(root: Mapping[str, Any], now: datetime) -> dict[str, float]:
    values = {
        "bundle.generated_at": root.get("generated_at"),
        "bundle.public_data_as_of": root.get("public_data_as_of"),
    }
    ages: dict[str, float] = {}
    parsed: dict[str, datetime] = {}
    for label, value in values.items():
        observed = core.timestamp(value, label)
        parsed[label] = observed
        age = (now - observed).total_seconds()
        if age < -core.CLOCK_SKEW_SECONDS:
            raise core.PreflightError(f"{label} is future-dated")
        if age > core.MAX_BUNDLE_AGE_SECONDS:
            raise core.PreflightError(
                f"{label} is stale; age_seconds={round(age)}; "
                f"max={core.MAX_BUNDLE_AGE_SECONDS}"
            )
        ages[label] = round(max(0.0, age), 3)
    if (
        parsed["bundle.public_data_as_of"]
        - parsed["bundle.generated_at"]
    ).total_seconds() > core.CLOCK_SKEW_SECONDS:
        raise core.PreflightError("public_data_as_of is later than generated_at")
    return ages


core.validate_freshness = validate_freshness

if __name__ == "__main__":
    try:
        raise SystemExit(core.main())
    except (core.PreflightError, OSError, ValueError) as exc:
        print(f"V213_R75_ACTIVATION_PREFLIGHT = FAIL; {exc}", flush=True)
        raise SystemExit(1)
