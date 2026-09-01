#!/usr/bin/env python3
"""H6B1 R2 wrapper: preserve explicit zero-valued H6A attestations.

The original H6B1 verifier used expressions such as
``int(summary.get("failed") or -1)``.  In Python, integer zero is falsy, so a
valid H6A ``failed: 0`` (and ``hard_dependency_count: 0``) was converted to
``-1`` and rejected.  This wrapper fixes only that verifier boundary and then
runs the original H6B1 builder unchanged.
"""
from __future__ import annotations

import sys
from typing import Any, Mapping

import v213_serenity_h6b_full_top20 as base


def _required_int(mapping: Mapping[str, Any], key: str) -> int:
    if key not in mapping:
        raise base.H6BError(f"H6A baseline missing required integer: {key}")
    value = mapping[key]
    if value is None or isinstance(value, bool):
        raise base.H6BError(f"H6A baseline invalid integer: {key}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise base.H6BError(f"H6A baseline invalid integer: {key}") from exc


def verify_h6a_zero_safe(h6a: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    summary = h6a.get("summary")
    if not isinstance(summary, Mapping):
        raise base.H6BError("H6A baseline summary is missing")

    completed = _required_int(summary, "completed")
    failed = _required_int(summary, "failed")
    hard_dependency_count = _required_int(summary, "hard_dependency_count")
    if completed != 7 or failed != 0:
        raise base.H6BError("H6A baseline is not 7/7 PASS")
    if hard_dependency_count != 0:
        raise base.H6BError("H6A baseline violates hard-dependency guard")
    if summary.get("production_ranking_changed") is not False:
        raise base.H6BError("H6A baseline production-ranking attestation is not explicit false")

    attestation = h6a.get("h6_source_history_attestation")
    if not isinstance(attestation, Mapping):
        raise base.H6BError("H6A source-history attestation is missing")
    checkpoint = policy["h6a_source_history_checkpoint"]
    if (
        _required_int(attestation, "entries") != int(checkpoint["entries"])
        or str(attestation.get("latest_hash") or "") != str(checkpoint["latest_hash"])
        or attestation.get("structural_chain_verified") is not True
    ):
        raise base.H6BError("H6A source-history checkpoint mismatch")

    return {
        "entries": int(attestation["entries"]),
        "latest_hash": str(attestation["latest_hash"]),
        "structural_chain_verified": True,
    }


def self_test_zero_safe() -> None:
    policy = {
        "h6a_source_history_checkpoint": {
            "entries": 4,
            "latest_hash": "abc",
        }
    }
    valid = {
        "summary": {
            "completed": 7,
            "failed": 0,
            "hard_dependency_count": 0,
            "production_ranking_changed": False,
        },
        "h6_source_history_attestation": {
            "entries": 4,
            "latest_hash": "abc",
            "structural_chain_verified": True,
        },
    }
    result = verify_h6a_zero_safe(valid, policy)
    assert result["entries"] == 4

    for key in ("failed", "hard_dependency_count"):
        broken = {
            "summary": dict(valid["summary"]),
            "h6_source_history_attestation": dict(valid["h6_source_history_attestation"]),
        }
        broken["summary"].pop(key)
        try:
            verify_h6a_zero_safe(broken, policy)
        except base.H6BError:
            pass
        else:
            raise AssertionError(f"missing {key} must fail closed")

    print("V213_H6B1_ZERO_SAFE_H6A_GUARD = PASS")


# Patch the original module's global verifier before its main()/build() executes.
base.verify_h6a = verify_h6a_zero_safe


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test_zero_safe()
    raise SystemExit(base.main())
