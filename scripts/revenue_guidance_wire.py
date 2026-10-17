"""B3-WIRE-01: the disabled versioned transport envelope for the existing v3 order forecast
(docs/REVENUE_GUIDANCE_AUTOUPDATE.md, B3-WIRE-01 section).

The envelope is a versioned wrapper around the complete existing build_v3 result - it is not a new
admission mode. ``admission_mode`` is a fixed protocol label, not a permission or enablement flag:
transport-v1 authorizes no machine-admission feature, and an envelope never converts machine evidence
into human-approved evidence. The payload is a detached JSON-compatible copy of the already-built
result: no field is deleted, renamed, synthesized, clipped or recomputed inside it, and
``evidence.auto_update`` travels sealed inside the payload exactly as the producer emitted it.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

TRANSPORT_SCHEMA = "v213-order-forecast-transport-v1"
ADMISSION_MODE = "EXISTING_V3_ONLY"


def envelope_v3_forecast(v3_forecast: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap a complete, already-built build_v3 result in the transport-v1 envelope.

    The payload is a deep detached copy: the caller's mapping is never mutated and later changes to it
    are not visible through the envelope. The input must be a JSON-compatible build_v3 result; nothing
    inside it is validated, re-derived or altered here (the sealed-snapshot hashing covers the emitted
    body, and input/generation digests inside the payload keep only their existing meaning)."""
    if not isinstance(v3_forecast, Mapping):
        raise TypeError("envelope_v3_forecast: the v3 forecast must be a mapping")
    return {"schema": TRANSPORT_SCHEMA, "admission_mode": ADMISSION_MODE,
            "payload": copy.deepcopy(dict(v3_forecast))}
