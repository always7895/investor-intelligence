#!/usr/bin/env python3
"""Static, reviewable adapter interface for authoritative public sources."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol


class AdapterError(ValueError):
    """Raised when an official source payload fails structural validation."""


@dataclass(frozen=True)
class ParsedBatch:
    source_id: str
    parser_version: str
    retrieved_at: str
    content_sha256: str
    schema_sha256: str
    record_count: int
    records: tuple[Mapping[str, Any], ...]
    warnings: tuple[str, ...] = ()

    def as_dict(self, *, include_records: bool = True) -> dict[str, Any]:
        value = asdict(self)
        if not include_records:
            value.pop("records", None)
        return value


class SourceAdapter(Protocol):
    source_id: str
    parser_version: str

    def parse(
        self,
        content: bytes,
        *,
        content_type: str,
        retrieved_at: str,
        context: Mapping[str, Any],
    ) -> ParsedBatch: ...


ADAPTERS: dict[str, SourceAdapter] = {}


def utc_iso(value: str | datetime) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise AdapterError("retrieved_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise AdapterError("retrieved_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AdapterError("Adapter output must contain finite JSON values") from exc


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def schema_fingerprint(records: tuple[Mapping[str, Any], ...]) -> str:
    fields: dict[str, set[str]] = {}
    for record in records:
        for key, value in record.items():
            fields.setdefault(str(key), set()).add(_type_name(value))
    document = {
        key: sorted(types)
        for key, types in sorted(fields.items(), key=lambda item: item[0])
    }
    return sha256_bytes(canonical_json(document).encode("utf-8"))


def make_batch(
    *,
    source_id: str,
    parser_version: str,
    content: bytes,
    retrieved_at: str | datetime,
    records: list[Mapping[str, Any]],
    warnings: list[str] | None = None,
) -> ParsedBatch:
    normalized_records = tuple(dict(record) for record in records)
    if not normalized_records:
        raise AdapterError(f"{source_id} payload produced no validated records")
    for record in normalized_records:
        canonical_json(record)
    return ParsedBatch(
        source_id=source_id,
        parser_version=parser_version,
        retrieved_at=utc_iso(retrieved_at),
        content_sha256=sha256_bytes(content),
        schema_sha256=schema_fingerprint(normalized_records),
        record_count=len(normalized_records),
        records=normalized_records,
        warnings=tuple(warnings or []),
    )


def register_adapter(adapter: SourceAdapter) -> SourceAdapter:
    source_id = str(adapter.source_id).strip()
    if not source_id:
        raise AdapterError("Adapter source_id is required")
    if source_id in ADAPTERS:
        raise AdapterError(f"Duplicate adapter registration: {source_id}")
    ADAPTERS[source_id] = adapter
    return adapter


def adapter(source_id: str) -> SourceAdapter:
    try:
        return ADAPTERS[source_id]
    except KeyError as exc:
        raise AdapterError(f"No reviewed adapter registered for {source_id}") from exc


def parse_source_payload(
    source_id: str,
    content: bytes,
    *,
    content_type: str,
    retrieved_at: str | datetime,
    context: Mapping[str, Any] | None = None,
) -> ParsedBatch:
    if not isinstance(content, bytes) or not content:
        raise AdapterError("Authoritative source payload must be non-empty bytes")
    if len(content) > 250_000_000:
        raise AdapterError("Authoritative source payload exceeds the hard 250 MB boundary")
    return adapter(source_id).parse(
        content,
        content_type=str(content_type or "").casefold(),
        retrieved_at=utc_iso(retrieved_at),
        context=dict(context or {}),
    )


def json_document(content: bytes) -> Any:
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError("Official JSON payload is invalid") from exc


def scalar(value: Any, *, allow_none: bool = True) -> Any:
    if value is None and allow_none:
        return None
    if isinstance(value, (str, int, float, bool)):
        canonical_json(value)
        return value
    raise AdapterError("Expected a JSON scalar value")


def build_evidence_item(
    batch: ParsedBatch,
    record: Mapping[str, Any],
    *,
    claim_id: str,
    claim_type: str,
    canonical_url: str,
    field_values: Mapping[str, Any],
    registry_version: str,
    published_at: str | None = None,
    as_of: str | None = None,
    revision_or_vintage: str | None = None,
) -> dict[str, Any]:
    """Build an evidence candidate; provenance performs final admission."""
    if not field_values:
        raise AdapterError("Evidence field_values cannot be empty")
    for value in field_values.values():
        if value is None or isinstance(value, (dict, list, tuple, set)):
            raise AdapterError("Evidence field_values must be non-null scalars")
    return {
        "claim_id": str(claim_id),
        "claim_type": str(claim_type),
        "source_id": batch.source_id,
        "canonical_url": str(canonical_url),
        "published_at": published_at,
        "as_of": as_of,
        "retrieved_at": batch.retrieved_at,
        "content_sha256": batch.content_sha256,
        "parser_version": batch.parser_version,
        "registry_version": str(registry_version),
        "stance": "support",
        "field_values": dict(field_values),
        "material_fields": sorted(field_values),
        "revision_or_vintage": revision_or_vintage,
        "adapter_schema_sha256": batch.schema_sha256,
        "record_sha256": sha256_bytes(canonical_json(record).encode("utf-8")),
    }
