"""Explicit local-only adapters, isolated from the reviewed runtime registry."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .base import AdapterError, ParsedBatch, utc_iso
from .official_rss import RSS_ADAPTERS
from .taiwan_equities import EQUITY_ADAPTERS

STAGED_ADAPTERS = {**RSS_ADAPTERS, **EQUITY_ADAPTERS}


def parse_source_payload(source_id: str, content: bytes, *, content_type: str,
                         retrieved_at: str | datetime, context: Mapping[str, Any] | None = None) -> ParsedBatch:
    if source_id not in STAGED_ADAPTERS:
        raise AdapterError("UNKNOWN_STAGED_SOURCE")
    if not isinstance(content, bytes) or not content or len(content) > 8_000_000:
        raise AdapterError("INVALID_STAGED_PAYLOAD_SIZE")
    return STAGED_ADAPTERS[source_id].parse(content, content_type=content_type.casefold(),
                                          retrieved_at=utc_iso(retrieved_at), context=dict(context or {}))
