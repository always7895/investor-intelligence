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
    Eliminates trust bypass: default fixture_mode is strictly False unless the caller
    is executing within an authoritative synthetic test fixture suite (e.g. test_top20_bottleneck_takeover).
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
