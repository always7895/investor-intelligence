#!/usr/bin/env python3
"""ECB Data Portal SDMX-CSV adapter staged behind fixture review."""
from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

from .base import AdapterError, ParsedBatch, make_batch
from .sdmx_csv import evidence_items as sdmx_evidence_items
from .sdmx_csv import parse_records

ECB_HOST = "data-api.ecb.europa.eu"
ECB_PATH_PREFIX = "/service/data/"


def _request_url(context: Mapping[str, Any]) -> str:
    value = str(context.get("request_url") or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise AdapterError("ECB adapter request_url is invalid") from exc
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != ECB_HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not parsed.path.startswith(ECB_PATH_PREFIX)
    ):
        raise AdapterError("ECB adapter request_url is outside the reviewed API boundary")
    return value


class EcbSdmxAdapter:
    source_id = "ecb_sdmx"
    parser_version = "ecb-data-api-sdmx-csv-v2"

    def parse(
        self,
        content: bytes,
        *,
        content_type: str,
        retrieved_at: str,
        context: Mapping[str, Any],
    ) -> ParsedBatch:
        request_url = _request_url(context)
        dataflow = str(context.get("dataflow") or "").strip() or None
        records, warnings = parse_records(
            content,
            content_type=content_type,
            request_url=request_url,
            dataflow=dataflow,
        )
        return make_batch(
            source_id=self.source_id,
            parser_version=self.parser_version,
            content=content,
            retrieved_at=retrieved_at,
            records=records,
            warnings=warnings,
        )


def evidence_items(batch: ParsedBatch, *, registry_version: str) -> list[dict[str, Any]]:
    return sdmx_evidence_items(
        batch,
        registry_version=registry_version,
        claim_prefix="ecb",
    )


# Deliberately not registered. The route remains adapter_replay_required until
# source-specific fixture, rights and exact-head acceptance are complete.
