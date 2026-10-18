#!/usr/bin/env python3
"""Reviewed authoritative adapter registry.

Imports are static by design: catalog growth may add disabled source metadata,
but executable adapter code enters the runtime only through repository review.
"""
from __future__ import annotations

from typing import Any

from .base import (  # noqa: F401
    ADAPTERS,
    AdapterError,
    ParsedBatch,
    adapter,
    parse_source_payload,
    register_adapter,
)
from . import sec_edgar as _sec_edgar  # noqa: F401
from . import world_bank as _world_bank  # noqa: F401
from . import ecb_fx_reference as _ecb_fx_reference  # noqa: F401
from .ecb_fx_reference import ECBFxReferenceAdapter

register_adapter(ECBFxReferenceAdapter())

EVIDENCE_BUILDERS = {
    "sec_edgar": _sec_edgar.evidence_items,
    "world_bank_indicators": _world_bank.evidence_items,
    "eu_ecb_fx_reference": _ecb_fx_reference.evidence_items,
}


def build_evidence_items(
    batch: ParsedBatch,
    *,
    registry_version: str,
) -> list[dict[str, Any]]:
    try:
        builder = EVIDENCE_BUILDERS[batch.source_id]
    except KeyError as exc:
        raise AdapterError(
            f"No reviewed evidence builder registered for {batch.source_id}"
        ) from exc
    return builder(batch, registry_version=registry_version)
