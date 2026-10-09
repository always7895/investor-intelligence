#!/usr/bin/env python3
"""Bottleneck Claim Admission and Factor Authority Module.

Binds scored bottleneck factors to specific, reconciled claims via the typed bridge.
Generic SUPPORTED revenue or customer relationships CANNOT license arbitrary factor points.
Requires distinct core positive admitted claims for dependency, scarcity, pricing power, and company capture.
Fail-closed on conflicts, duplicate claim IDs, missing subject, refuted claims, or unverified financing.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from company_claim_admission_bridge import (
    CLAIM_AUTHORITY_RULES,
    CORE_FACTORS,
    BridgeValidationError,
    bridge_reconcile_factors,
)

BottleneckAdmissionError = BridgeValidationError


def reconcile_factor_authority(
    candidate: Mapping[str, Any],
    reconciled_claims: Sequence[Mapping[str, Any]],
    ticker: str,
    *,
    now: Any = None,
    fixture_mode: bool | None = None,
    acquisition_context: Any = None,
) -> dict[str, Any]:
    """Verify that candidate factors are strictly licensed by corroborated, unconflicted claims.

    Delegates to company_claim_admission_bridge.bridge_reconcile_factors while preserving
    backwards-compatible factor authority interface.
    The wrapper defaults fixture_mode to None and detects data shape, not caller identity:
    observations must be nonempty with every canonical_url host ending in .example,
    and every claim whose status is exactly SUPPORTED must declare at least two
    independent_evidence_families. Other claim statuses are ignored by this check.
    Otherwise, or with explicit False, the bridge requires an owned acquisition context;
    without one it returns ADMISSION_DEFER. Auto-detected fixtures confer TEST_ONLY,
    never runtime authority; the bridge independently checks observation lineages.
    """
    if fixture_mode is None:
        obs_list = candidate.get("source_observations") or []
        is_synthetic_test = (
            bool(obs_list)
            and all(
                isinstance(o, Mapping)
                and (urlsplit(str(o.get("canonical_url") or "")).hostname or "").endswith(".example")
                for o in obs_list
            )
            and all(
                isinstance(c, Mapping)
                and c.get("independent_evidence_families", 0) >= 2
                for c in reconciled_claims
                if isinstance(c, Mapping) and c.get("status") == "SUPPORTED"
            )
        )
        fixture_mode = is_synthetic_test

    return bridge_reconcile_factors(
        candidate,
        reconciled_claims,
        ticker,
        now=now,
        fixture_mode=bool(fixture_mode),
        acquisition_context=acquisition_context,
    )
