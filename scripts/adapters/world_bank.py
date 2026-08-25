#!/usr/bin/env python3
"""World Bank Indicators API V2 adapter."""
from __future__ import annotations

import re
from typing import Any, Mapping

from .base import (
    AdapterError,
    ParsedBatch,
    build_evidence_item,
    json_document,
    make_batch,
    register_adapter,
    scalar,
)

YEAR_RE = re.compile(r"^\d{4}$")


def _request_url(context: Mapping[str, Any]) -> str:
    value = str(context.get("request_url") or "").strip()
    if not value.startswith("https://"):
        raise AdapterError("World Bank adapter requires an HTTPS request_url")
    return value


def _period_as_of(value: str) -> str | None:
    if YEAR_RE.fullmatch(value):
        return f"{value}-12-31T00:00:00+00:00"
    return None


class WorldBankIndicatorsAdapter:
    source_id = "world_bank_indicators"
    parser_version = "world-bank-indicators-v2-json-v1"

    def parse(
        self,
        content: bytes,
        *,
        content_type: str,
        retrieved_at: str,
        context: Mapping[str, Any],
    ) -> ParsedBatch:
        if "json" not in content_type:
            raise AdapterError("World Bank adapter requires JSON content")
        document = json_document(content)
        if not isinstance(document, list) or len(document) < 2:
            raise AdapterError("World Bank V2 payload must contain metadata and records")
        metadata, observations = document[0], document[1]
        if not isinstance(metadata, dict) or not isinstance(observations, list):
            raise AdapterError("World Bank V2 response structure is invalid")
        request_url = _request_url(context)
        records: list[dict[str, Any]] = []
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            value = observation.get("value")
            if value is None:
                continue
            value = scalar(value, allow_none=False)
            country = observation.get("country")
            indicator = observation.get("indicator")
            if not isinstance(country, dict) or not isinstance(indicator, dict):
                continue
            country_id = str(country.get("id") or observation.get("countryiso3code") or "").strip()
            indicator_id = str(indicator.get("id") or "").strip()
            period = str(observation.get("date") or "").strip()
            if not country_id or not indicator_id or not period:
                continue
            records.append(
                {
                    "record_type": "official_indicator_value",
                    "country_id": country_id,
                    "country_iso3": str(observation.get("countryiso3code") or "").strip() or None,
                    "country_name": str(country.get("value") or "").strip() or None,
                    "indicator_id": indicator_id,
                    "indicator_name": str(indicator.get("value") or "").strip() or None,
                    "period": period,
                    "period_as_of": _period_as_of(period),
                    "value": value,
                    "unit": str(observation.get("unit") or "").strip() or None,
                    "observation_status": str(observation.get("obs_status") or "").strip() or None,
                    "decimal": observation.get("decimal"),
                    "source_id": str(observation.get("source", {}).get("id") or "").strip()
                    if isinstance(observation.get("source"), dict)
                    else None,
                    "source_note": str(observation.get("sourceNote") or "").strip() or None,
                    "record_url": request_url,
                    "api_page": int(metadata.get("page") or 1),
                    "api_pages": int(metadata.get("pages") or 1),
                    "api_total": int(metadata.get("total") or len(observations)),
                    "api_last_updated": str(metadata.get("lastupdated") or "").strip() or None,
                }
            )
        if not records:
            raise AdapterError("World Bank payload contains no non-null observations")
        warnings: list[str] = []
        pages = int(metadata.get("pages") or 1)
        page = int(metadata.get("page") or 1)
        if page < pages:
            warnings.append("PAGINATION_INCOMPLETE")
        return make_batch(
            source_id=self.source_id,
            parser_version=self.parser_version,
            content=content,
            retrieved_at=retrieved_at,
            records=records,
            warnings=warnings,
        )


def evidence_items(batch: ParsedBatch, *, registry_version: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in batch.records:
        as_of = record.get("period_as_of") or batch.retrieved_at
        result.append(
            build_evidence_item(
                batch,
                record,
                claim_id=(
                    "world_bank:"
                    f"{record['indicator_id']}:{record['country_id']}:{record['period']}"
                ),
                claim_type="official_indicator_value",
                canonical_url=str(record["record_url"]),
                field_values={
                    "indicator_id": record["indicator_id"],
                    "country_id": record["country_id"],
                    "period": record["period"],
                    "value": record["value"],
                },
                registry_version=registry_version,
                as_of=str(as_of),
                revision_or_vintage=str(record.get("api_last_updated") or record["period"]),
            )
        )
    return result


register_adapter(WorldBankIndicatorsAdapter())
