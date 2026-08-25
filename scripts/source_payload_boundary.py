#!/usr/bin/env python3
"""Bound and validate authoritative-source payloads before adapter parsing."""
from __future__ import annotations

import gzip
import io
import json
import math
import zlib
from dataclasses import dataclass
from typing import Any, Mapping


class SourcePayloadError(ValueError):
    """Raised when a source payload is unsafe or structurally incompatible."""


@dataclass(frozen=True)
class PayloadLimits:
    maximum_wire_bytes: int = 25_000_000
    maximum_decoded_bytes: int = 100_000_000
    maximum_decompression_ratio: float = 50.0
    maximum_json_depth: int = 64
    maximum_json_nodes: int = 2_000_000


def _bounded_gzip(content: bytes, limits: PayloadLimits) -> bytes:
    if not content:
        raise SourcePayloadError("Compressed payload is empty")
    output = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(content), mode="rb") as handle:
            while True:
                chunk = handle.read(64 * 1024)
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > limits.maximum_decoded_bytes:
                    raise SourcePayloadError("Decoded payload exceeds the byte boundary")
                if len(output) / max(len(content), 1) > limits.maximum_decompression_ratio:
                    raise SourcePayloadError("Payload exceeds the decompression-ratio boundary")
    except (OSError, EOFError, zlib.error) as exc:
        raise SourcePayloadError("Gzip payload is invalid") from exc
    return bytes(output)


def decode_payload(
    content: bytes,
    *,
    content_encoding: str | None,
    limits: PayloadLimits = PayloadLimits(),
) -> bytes:
    if not isinstance(content, bytes) or not content:
        raise SourcePayloadError("Source payload must be non-empty bytes")
    if len(content) > limits.maximum_wire_bytes:
        raise SourcePayloadError("Wire payload exceeds the byte boundary")
    encoding = str(content_encoding or "identity").strip().casefold()
    if encoding in ("", "identity"):
        decoded = content
    elif encoding == "gzip":
        decoded = _bounded_gzip(content, limits)
    else:
        raise SourcePayloadError(f"Unsupported content encoding: {encoding}")
    if len(decoded) > limits.maximum_decoded_bytes:
        raise SourcePayloadError("Decoded payload exceeds the byte boundary")
    return decoded


def _walk_json(
    value: Any,
    *,
    depth: int,
    counters: dict[str, int],
    limits: PayloadLimits,
) -> None:
    if depth > limits.maximum_json_depth:
        raise SourcePayloadError("JSON payload exceeds the nesting-depth boundary")
    counters["nodes"] += 1
    if counters["nodes"] > limits.maximum_json_nodes:
        raise SourcePayloadError("JSON payload exceeds the node-count boundary")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SourcePayloadError("JSON payload contains a non-finite number")
        return
    if isinstance(value, list):
        for item in value:
            _walk_json(item, depth=depth + 1, counters=counters, limits=limits)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SourcePayloadError("JSON object keys must be strings")
            _walk_json(item, depth=depth + 1, counters=counters, limits=limits)
        return
    raise SourcePayloadError("JSON payload contains a non-JSON value")


def parse_bounded_json(
    content: bytes,
    *,
    content_type: str,
    content_encoding: str | None = None,
    limits: PayloadLimits = PayloadLimits(),
) -> Any:
    if "json" not in str(content_type or "").casefold():
        raise SourcePayloadError("JSON parser requires a JSON content type")
    decoded = decode_payload(
        content,
        content_encoding=content_encoding,
        limits=limits,
    )
    try:
        value = json.loads(decoded.decode("utf-8-sig"), parse_constant=lambda value: (_ for _ in ()).throw(SourcePayloadError(f"Invalid JSON constant: {value}")))
    except UnicodeDecodeError as exc:
        raise SourcePayloadError("JSON payload must be UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise SourcePayloadError("JSON payload is invalid") from exc
    _walk_json(value, depth=0, counters={"nodes": 0}, limits=limits)
    return value


def validate_closed_object(
    value: Any,
    *,
    allowed_fields: set[str] | frozenset[str],
    required_fields: set[str] | frozenset[str] = frozenset(),
    label: str = "object",
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SourcePayloadError(f"{label} must be an object")
    unknown = sorted(set(value).difference(allowed_fields))
    missing = sorted(set(required_fields).difference(value))
    if unknown:
        raise SourcePayloadError(f"{label} contains unknown field(s): {', '.join(unknown)}")
    if missing:
        raise SourcePayloadError(f"{label} is missing field(s): {', '.join(missing)}")
    return value
