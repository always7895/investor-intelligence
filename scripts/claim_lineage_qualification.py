"""Exact-claim lineage qualification shared by snapshot guard and bundle builder.

Only source_observation owns lineage merging. Counts/labels are not proof.
The guard reserves 30 minutes (the sealed refresh's default 1800-second budget)
on BOTH audit and usable evidence expiry. A builder reached within that interval
cannot lose lineage support due to expiry. Longer/manual runs must re-guard;
the builder never grants grace to an expired audit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from source_observation import compute_independent_lineages

GUARD_VALIDITY_MARGIN = timedelta(minutes=30)


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def claim_lineage_qualified(
    audit_row: Mapping[str, Any], policy: Mapping[str, Any], now: datetime,
    *, validity_margin: timedelta = timedelta(0),
) -> bool:
    """Fail closed; every material claim needs its own bound, agreeing lineages."""
    # Same policy key as the builder's source-family threshold; no silent default.
    minimum = policy.get("minimum_claim_source_families_per_ticker")
    skew = policy.get("clock_skew_tolerance_minutes")
    if (type(minimum) is not int or minimum < 1
            or type(skew) is not int or skew < 0
            or validity_margin < timedelta(0)):
        return False
    audit = audit_row.get("claim_evidence_audit")
    if not isinstance(audit, Mapping) or audit.get("schema_version") != 2:
        return False
    claims, evidence = audit.get("claims"), audit.get("evidence")
    if (audit.get("all_material_claims_supported") is not True
            or not isinstance(claims, list) or not claims
            or not isinstance(evidence, list)):
        return False
    try:
        validated = _timestamp(audit.get("validated_at"))
        expiry = _timestamp(audit.get("valid_until"))
        horizon = now + validity_margin
        if not (validated <= now + timedelta(minutes=skew)
                and validated <= expiry <= validated + timedelta(hours=2)
                and horizon < expiry):
            return False
        seen: set[str] = set()
        for claim in claims:
            if (not isinstance(claim, Mapping)
                    or not isinstance(claim.get("claim_id"), str) or not claim["claim_id"].strip()
                    or claim["claim_id"] in seen
                    or claim.get("status") != "SUPPORTED"
                    or claim.get("high_confidence_eligible") is not True
                    or claim.get("conflict_set")
                    or not isinstance(claim.get("evidence_ids"), list)):
                return False
            seen.add(claim["claim_id"])
            bound = [
                row for row in evidence
                if isinstance(row, Mapping) and row.get("admitted") is True
                and row.get("freshness") == "CURRENT"
                and row.get("observation_id") in claim["evidence_ids"]
                and isinstance(row.get("claim_ids"), list)
                and claim["claim_id"] in row["claim_ids"]
                and horizon < _timestamp(row.get("valid_until"))
            ]
            if (compute_independent_lineages(bound) < minimum
                    or any(row["value"] != claim["value"] for row in bound)):
                return False
        return True
    except (ValueError, OverflowError, KeyError, TypeError, AttributeError):
        return False
