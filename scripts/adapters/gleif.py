#!/usr/bin/env python3
"""GLEIF LEI JSON:API adapter staged behind fixture review."""
from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from .base import (
    AdapterError,
    ParsedBatch,
    build_evidence_item,
    json_document,
    make_batch,
)

LEI_RE = re.compile(r"^[0-9A-Z]{20}$")
GLEIF_HOST = "api.gleif.org"
GLEIF_PATH_PREFIX = "/api/v1/"


def _request_url(context: Mapping[str, Any]) -> str:
    value = str(context.get("request_url") or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise AdapterError("GLEIF adapter request_url is invalid") from exc
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != GLEIF_HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not parsed.path.startswith(GLEIF_PATH_PREFIX)
    ):
        raise AdapterError("GLEIF adapter request_url is outside the reviewed API boundary")
    return value


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _name(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, dict):
        return None, None
    return _text(value.get("name")), _text(value.get("language"))


def _address(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    lines = value.get("addressLines")
    if not isinstance(lines, list):
        lines = []
    clean_lines = [str(item).strip() for item in lines if str(item).strip()]
    result = {
        "language": _text(value.get("language")),
        "address_lines": clean_lines,
        "city": _text(value.get("city")),
        "region": _text(value.get("region")),
        "country": _text(value.get("country")),
        "postal_code": _text(value.get("postalCode")),
    }
    return result if any(item not in (None, [], "") for item in result.values()) else None


def _record(item: Mapping[str, Any], request_url: str) -> dict[str, Any]:
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        raise AdapterError("GLEIF resource lacks attributes")
    lei = str(attributes.get("lei") or item.get("id") or "").strip().upper()
    if not LEI_RE.fullmatch(lei):
        raise AdapterError(f"GLEIF resource has an invalid LEI: {lei!r}")
    entity = attributes.get("entity")
    registration = attributes.get("registration")
    if not isinstance(entity, dict) or not isinstance(registration, dict):
        raise AdapterError(f"GLEIF record {lei} lacks entity or registration")
    legal_name, legal_name_language = _name(entity.get("legalName"))
    if not legal_name:
        raise AdapterError(f"GLEIF record {lei} lacks legal name")
    legal_form = entity.get("legalForm")
    if not isinstance(legal_form, dict):
        legal_form = {}
    return {
        "record_type": "legal_entity_reference",
        "lei": lei,
        "legal_name": legal_name,
        "legal_name_language": legal_name_language,
        "other_names": [
            name
            for value in entity.get("otherNames", [])
            if isinstance(value, dict)
            for name in [_text(value.get("name"))]
            if name
        ]
        if isinstance(entity.get("otherNames"), list)
        else [],
        "legal_address": _address(entity.get("legalAddress")),
        "headquarters_address": _address(entity.get("headquartersAddress")),
        "registered_at": _text(entity.get("registeredAt")),
        "registered_as": _text(entity.get("registeredAs")),
        "legal_jurisdiction": _text(entity.get("legalJurisdiction")),
        "entity_category": _text(entity.get("category")),
        "entity_status": _text(entity.get("status")),
        "entity_creation_date": _text(entity.get("entityCreationDate")),
        "legal_form_id": _text(legal_form.get("id")),
        "legal_form_other": _text(legal_form.get("other")),
        "initial_registration_date": _text(registration.get("initialRegistrationDate")),
        "last_update_date": _text(registration.get("lastUpdateDate")),
        "registration_status": _text(registration.get("status")),
        "next_renewal_date": _text(registration.get("nextRenewalDate")),
        "managing_lou": _text(registration.get("managingLou")),
        "corroboration_level": _text(registration.get("corroborationLevel")),
        "validation_sources": _text(registration.get("validationSources")),
        "record_url": request_url,
    }


class GleifLeiAdapter:
    source_id = "gleif_lei"
    parser_version = "gleif-json-api-v1"

    def parse(
        self,
        content: bytes,
        *,
        content_type: str,
        retrieved_at: str,
        context: Mapping[str, Any],
    ) -> ParsedBatch:
        if "json" not in content_type:
            raise AdapterError("GLEIF adapter requires JSON content")
        request_url = _request_url(context)
        document = json_document(content)
        if not isinstance(document, dict):
            raise AdapterError("GLEIF payload must be a JSON object")
        raw = document.get("data")
        if isinstance(raw, dict):
            resources = [raw]
        elif isinstance(raw, list):
            resources = raw
        else:
            raise AdapterError("GLEIF JSON:API payload lacks data")
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            resource_type = str(resource.get("type") or "").strip()
            if resource_type and resource_type != "lei-records":
                continue
            record = _record(resource, request_url)
            lei = str(record["lei"])
            if lei in seen:
                raise AdapterError(f"GLEIF payload contains duplicate LEI: {lei}")
            seen.add(lei)
            records.append(record)
        return make_batch(
            source_id=self.source_id,
            parser_version=self.parser_version,
            content=content,
            retrieved_at=retrieved_at,
            records=records,
        )


def evidence_items(batch: ParsedBatch, *, registry_version: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in batch.records:
        fields: dict[str, Any] = {
            "lei": record["lei"],
            "legal_name": record["legal_name"],
        }
        for field in (
            "legal_jurisdiction",
            "entity_status",
            "registration_status",
            "last_update_date",
        ):
            if record.get(field) is not None:
                fields[field] = record[field]
        result.append(
            build_evidence_item(
                batch,
                record,
                claim_id=f"gleif:{record['lei']}:legal-entity-reference",
                claim_type="legal_entity_reference",
                canonical_url=str(record["record_url"]),
                field_values=fields,
                registry_version=registry_version,
                published_at=str(record.get("last_update_date") or batch.retrieved_at),
                as_of=str(record.get("last_update_date") or batch.retrieved_at),
                revision_or_vintage=str(record.get("last_update_date") or batch.retrieved_at),
            )
        )
    return result


# Deliberately not registered. The route remains adapter_replay_required until
# source-specific fixture, rights and exact-head acceptance are complete.
