#!/usr/bin/env python3
"""Normalize authoritative public-source observations with strict provenance.

A source document cannot select its own trust tier, tenant, authority or health.
Those attributes come from the validated source registry and runtime health
state. Invalid, future-dated, cross-domain, private or untraceable observations
are rejected before they can enter a report or score.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from source_registry import Registry, SourceDefinition, SourceRegistryError, canonicalize_url

SCHEMA_VERSION = 1
MAX_PUBLIC_PAYLOAD_BYTES = 1_000_000
FUTURE_CLOCK_TOLERANCE = timedelta(minutes=5)
CONTENT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CORRECTION_STATUSES = {
    "NEW",
    "PRELIMINARY",
    "REVISED",
    "CORRECTED",
    "RESTATED",
    "FINAL",
    "SUPERSEDED",
}
HEALTH_STATUSES = {
    "HEALTHY",
    "DEGRADED",
    "CIRCUIT_OPEN",
    "QUARANTINED",
}
FORBIDDEN_PRIVATE_KEYS = {
    "tenant_id",
    "raw_line_id",
    "line_user_id",
    "line_group_id",
    "line_room_id",
    "account_id",
    "accountid",
    "cost_basis",
    "average_price",
    "position_shares",
    "exact_quantity",
    "conversation",
    "message_text",
    "private_prompt",
    "private_portfolio",
}


class SourceObservationError(ValueError):
    """Observation failed provenance, privacy or chronology validation."""


@dataclass(frozen=True)
class SourceObservation:
    schema_version: int
    observation_id: str
    source_id: str
    source_display_name: str
    authority_class: str
    trust_tier: str
    independence_group: str
    canonical_url: str
    jurisdiction: str
    language: str
    published_at: str
    retrieved_at: str
    content_sha256: str
    parser_id: str
    parser_version: str
    claim_type: str
    evidence_role: str
    freshness_status: str
    source_health: str
    correction_status: str
    supersedes_observation_id: str | None
    payload: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise SourceObservationError(f"{field} is required")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        result = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SourceObservationError(f"{field} must be ISO-8601") from exc
    if result.tzinfo is None:
        raise SourceObservationError(f"{field} must include a timezone")
    return result.astimezone(timezone.utc)


def _hostname_allowed(source: SourceDefinition, url: str) -> bool:
    target = (urlsplit(url).hostname or "").casefold()
    if not target:
        return False
    for allowed_url in source.canonical_urls:
        allowed = (urlsplit(allowed_url).hostname or "").casefold()
        if target == allowed or target.endswith(f".{allowed}"):
            return True
    return False


def _private_key_paths(value: Any, prefix: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_private_key_paths(item, f"{prefix}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            path = f"{prefix}.{key}"
            if normalized in FORBIDDEN_PRIVATE_KEYS:
                findings.append(path)
            findings.extend(_private_key_paths(item, path))
    return findings


def _content_hash(raw: dict[str, Any], raw_content: bytes | None) -> str:
    supplied = str(raw.get("content_sha256") or "").strip().casefold()
    if raw_content is not None:
        calculated = hashlib.sha256(raw_content).hexdigest()
        if supplied and supplied != calculated:
            raise SourceObservationError("content_sha256 does not match raw_content")
        return calculated
    if not CONTENT_HASH_PATTERN.fullmatch(supplied):
        raise SourceObservationError(
            "content_sha256 must be a lowercase SHA-256 when raw_content is unavailable"
        )
    return supplied


def _public_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SourceObservationError("payload must be an object")
    findings = _private_key_paths(raw)
    if findings:
        raise SourceObservationError(
            f"Public source payload contains forbidden private fields: {', '.join(findings[:8])}"
        )
    try:
        encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise SourceObservationError("Public payload must contain finite JSON values") from None
    if len(encoded) > MAX_PUBLIC_PAYLOAD_BYTES:
        raise SourceObservationError(
            f"payload exceeds {MAX_PUBLIC_PAYLOAD_BYTES} bytes"
        )
    return json.loads(encoded.decode("utf-8"))


def _source(registry: Registry, source_id: str) -> SourceDefinition:
    try:
        return registry.by_id()[source_id]
    except KeyError as exc:
        raise SourceObservationError(f"Unknown source_id: {source_id}") from exc


def _observation_id(
    *,
    source_id: str,
    canonical_url: str,
    published_at: str,
    content_sha256: str,
    claim_type: str,
) -> str:
    material = "\n".join(
        [source_id, canonical_url, published_at, content_sha256, claim_type]
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def normalize_observation(
    raw: dict[str, Any],
    *,
    registry: Registry,
    raw_content: bytes | None = None,
    source_health: str = "HEALTHY",
    now: datetime | None = None,
    require_runtime_enabled: bool = True,
) -> SourceObservation:
    if not isinstance(raw, dict):
        raise SourceObservationError("observation must be an object")
    source_id = str(raw.get("source_id") or "").strip()
    source = _source(registry, source_id)
    if require_runtime_enabled and not source.runtime_enabled:
        raise SourceObservationError(f"Source is not runtime enabled: {source_id}")
    if source.trust_tier == "T4_QUARANTINED":
        raise SourceObservationError(f"Quarantined source cannot produce observations: {source_id}")

    canonical_url = canonicalize_url(str(raw.get("canonical_url") or ""))
    if not _hostname_allowed(source, canonical_url):
        raise SourceObservationError(
            f"canonical_url is outside the admitted source domain: {source_id}"
        )

    clock = now or utc_now()
    if clock.tzinfo is None:
        raise SourceObservationError("Validation clock must include a timezone")
    current = clock.astimezone(timezone.utc)
    published = parse_timestamp(raw.get("published_at"), "published_at")
    retrieved = parse_timestamp(raw.get("retrieved_at"), "retrieved_at")
    if retrieved > current + FUTURE_CLOCK_TOLERANCE:
        raise SourceObservationError("retrieved_at is implausibly in the future")
    if published > current + FUTURE_CLOCK_TOLERANCE:
        raise SourceObservationError("published_at is implausibly in the future")
    if published > retrieved + FUTURE_CLOCK_TOLERANCE:
        raise SourceObservationError("published_at is later than retrieved_at")

    jurisdiction = str(raw.get("jurisdiction") or "").strip()
    if jurisdiction not in source.jurisdictions:
        raise SourceObservationError(
            f"jurisdiction {jurisdiction!r} is not admitted for {source_id}"
        )
    language = str(raw.get("language") or "").strip()
    if language not in source.languages and "MULTI" not in source.languages:
        raise SourceObservationError(
            f"language {language!r} is not admitted for {source_id}"
        )

    evidence_role = str(raw.get("evidence_role") or "").strip()
    if evidence_role not in source.evidence_roles:
        raise SourceObservationError(
            f"evidence_role {evidence_role!r} is not admitted for {source_id}"
        )
    claim_type = str(raw.get("claim_type") or "").strip()
    if not claim_type:
        raise SourceObservationError("claim_type is required")

    parser_id = str(raw.get("parser_id") or "").strip()
    parser_version = str(raw.get("parser_version") or "").strip()
    if not parser_id or not parser_version:
        raise SourceObservationError("parser_id and parser_version are required")

    if source_health not in HEALTH_STATUSES:
        raise SourceObservationError(f"Unsupported source_health: {source_health}")
    if source_health in {"CIRCUIT_OPEN", "QUARANTINED"}:
        raise SourceObservationError(
            f"Source health {source_health} cannot promote a new observation"
        )

    correction_status = str(raw.get("correction_status") or "NEW").upper()
    if correction_status not in CORRECTION_STATUSES:
        raise SourceObservationError(
            f"Unsupported correction_status: {correction_status}"
        )
    supersedes = str(raw.get("supersedes_observation_id") or "").strip() or None
    if correction_status in {"CORRECTED", "RESTATED", "SUPERSEDED"} and not supersedes:
        raise SourceObservationError(
            f"{correction_status} requires supersedes_observation_id"
        )
    if supersedes and not CONTENT_HASH_PATTERN.fullmatch(supersedes.casefold()):
        raise SourceObservationError(
            "supersedes_observation_id must be a SHA-256 observation identifier"
        )

    content_sha256 = _content_hash(raw, raw_content)
    age_seconds = max(0.0, (current - published).total_seconds())
    if source.freshness_seconds is None:
        freshness_status = "FRESHNESS_POLICY_UNSET"
    elif age_seconds <= source.freshness_seconds:
        freshness_status = "CURRENT"
    else:
        freshness_status = "STALE"

    published_text = published.isoformat()
    retrieved_text = retrieved.isoformat()
    observation_id = _observation_id(
        source_id=source_id,
        canonical_url=canonical_url,
        published_at=published_text,
        content_sha256=content_sha256,
        claim_type=claim_type,
    )

    return SourceObservation(
        schema_version=SCHEMA_VERSION,
        observation_id=observation_id,
        source_id=source.source_id,
        source_display_name=source.display_name,
        authority_class=source.authority_class,
        trust_tier=source.trust_tier,
        independence_group=source.independence_group,
        canonical_url=canonical_url,
        jurisdiction=jurisdiction,
        language=language,
        published_at=published_text,
        retrieved_at=retrieved_text,
        content_sha256=content_sha256,
        parser_id=parser_id,
        parser_version=parser_version,
        claim_type=claim_type,
        evidence_role=evidence_role,
        freshness_status=freshness_status,
        source_health=source_health,
        correction_status=correction_status,
        supersedes_observation_id=supersedes,
        payload=_public_payload(raw.get("payload")),
    )


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def promote_last_known_good(
    observation: SourceObservation,
    *,
    output_root: Path,
) -> tuple[Path, Path]:
    """Persist immutable observation then atomically promote its latest pointer."""

    source_root = output_root / observation.source_id
    immutable_path = source_root / "observations" / f"{observation.observation_id}.json"
    latest_path = source_root / "latest.json"
    if immutable_path.exists():
        existing = json.loads(immutable_path.read_text(encoding="utf-8"))
        if existing != observation.as_json():
            raise SourceObservationError(
                "Observation identifier collision with different normalized content"
            )
    else:
        atomic_write_json(immutable_path, observation.as_json())
    atomic_write_json(
        latest_path,
        {
            "schema_version": SCHEMA_VERSION,
            "source_id": observation.source_id,
            "observation_id": observation.observation_id,
            "promoted_at": utc_now().isoformat(),
            "immutable_path": str(immutable_path),
        },
    )
    return immutable_path, latest_path


def observation_set_hash(observations: Iterable[SourceObservation]) -> str:
    material = "\n".join(
        sorted({observation.observation_id for observation in observations})
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()
