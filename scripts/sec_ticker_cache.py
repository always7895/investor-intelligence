"""Local SEC acquisition sidecar; integrity metadata, NOT a signature.

The shared cache stays exact raw SEC bytes for every existing reader. Only a
strict sidecar bound to those bytes supplies acquisition age. Missing/invalid
metadata is legacy UNVERIFIED; reading never attests or rewrites old bytes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ORIGIN = "https://www.sec.gov/files/company_tickers_exchange.json"
SCHEMA = "sec-ticker-acquisition-v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_SIDECAR_BYTES = 4096


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("SEC_CACHE_DUPLICATE_KEY")
        result[key] = value
    return result


def _nonfinite(_):
    raise ValueError("SEC_CACHE_NONFINITE")


def _parse(raw: bytes):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)


def validate_body(body: bytes) -> None:
    """Accept only raw SEC documents, never an embedded-body cache envelope."""
    if len(body) > MAX_BYTES:
        raise ValueError("SEC_CACHE_TOO_LARGE")
    doc = _parse(body)
    if (not isinstance(doc, dict) or "schema" in doc
            or not isinstance(doc.get("fields"), list) or not isinstance(doc.get("data"), list)):
        raise ValueError("SEC_CACHE_BODY_SCHEMA")


def sidecar_path(cache: Path) -> Path:
    return cache.with_suffix(".acquisition.json")


def acquisition_bytes(body: bytes, acquired: datetime) -> bytes:
    """Called only after a new fetch; never attest a legacy file on read."""
    validate_body(body)
    if acquired.tzinfo is None or acquired.utcoffset() is None:
        raise ValueError("SEC_CACHE_ACQUISITION")
    return json.dumps({
        "schema": SCHEMA, "origin_url": ORIGIN,
        "acquired_at": acquired.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body_sha256": hashlib.sha256(body).hexdigest(),
    }, separators=(",", ":")).encode("utf-8")


def acquired_at(body: bytes, cache: Path) -> datetime | None:
    """Strict matching sidecar time, else None (mtime availability only)."""
    validate_body(body)
    try:
        with sidecar_path(cache).open("rb") as handle:
            raw = handle.read(MAX_SIDECAR_BYTES + 1)
        if len(raw) > MAX_SIDECAR_BYTES:
            return None
        doc = _parse(raw)
        if (not isinstance(doc, dict)
                or set(doc) != {"schema", "origin_url", "acquired_at", "body_sha256"}
                or doc["schema"] != SCHEMA or doc["origin_url"] != ORIGIN
                or not isinstance(doc["body_sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", doc["body_sha256"]) is None):
            return None
        if hashlib.sha256(body).hexdigest() != doc["body_sha256"]:
            return None
        stamp = doc["acquired_at"]
        if not isinstance(stamp, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp) is None:
            return None
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None
