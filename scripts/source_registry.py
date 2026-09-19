#!/usr/bin/env python3
"""Validate and query the authoritative global source federation.

The registry has no artificial source-count ceiling. It recursively loads every
catalog under ``config/sources`` and admits runtime sources only after strict
identity, legal/free-access, adapter, provenance and health gates pass.

This module performs no network access. Source discovery never auto-enables a
provider, and a lower-trust source never silently replaces primary evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from adapters.base import ParsedBatch, canonical_json, schema_fingerprint
from adapters.sec_edgar import (
    SEC_REGISTRY_SOURCE_ID,
    SecClaimBinding,
    project_sec_records,
)

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = BASE_DIR / "config" / "sources"
DEFAULT_POLICY_PATH = DEFAULT_SOURCE_DIR / "registry-policy.json"
DEFAULT_CLAIM_POLICY_PATH = BASE_DIR / "config" / "source-claim-coverage-policy.json"
DEFAULT_FEDERATION_POLICY_PATH = BASE_DIR / "config" / "v213-source-federation-policy.json"
DEFAULT_OUTPUT_PATH = BASE_DIR / "data" / "cache" / "source_registry_latest.json"

SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}
TRUST_RANK = {
    "T1_PRIMARY_OFFICIAL": 1,
    "T2_INSTITUTIONAL_CORROBORATION": 2,
    "T3_REPUTABLE_SECONDARY_LEAD": 3,
    "T4_QUARANTINED": 4,
}
ENABLED_ADMISSION_STATUS = "RUNTIME_ENABLED"


class SourceRegistryError(ValueError):
    """Registry validation failure."""


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    display_name: str
    authority_class: str
    trust_tier: str
    evidence_roles: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    languages: tuple[str, ...]
    canonical_urls: tuple[str, ...]
    independence_group: str
    admission_status: str
    adapter_id: str
    adapter_status: str
    runtime_enabled: bool
    free_access_required: bool
    payment_required: bool
    terms_review_status: str
    priority: int
    per_host_concurrency: int
    minimum_request_interval_seconds: float
    maximum_retries: int
    freshness_seconds: int | None
    correction_tracking: bool
    provenance_required: bool
    notes: str
    catalog_file: str

    @property
    def primary_domain(self) -> str:
        return urlsplit(self.canonical_urls[0]).hostname or ""

    def public_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["primary_domain"] = self.primary_domain
        record["trust_rank"] = TRUST_RANK[self.trust_tier]
        return record


@dataclass(frozen=True)
class Registry:
    schema_version: int
    sources: tuple[SourceDefinition, ...]
    catalog_files: tuple[str, ...]
    artificial_source_count_limit: None = None

    def by_id(self) -> dict[str, SourceDefinition]:
        return {source.source_id: source for source in self.sources}

    def runtime_sources(self) -> tuple[SourceDefinition, ...]:
        return tuple(source for source in self.sources if source.runtime_enabled)

    def summary(self) -> dict[str, Any]:
        by_tier: dict[str, int] = {}
        by_authority: dict[str, int] = {}
        by_jurisdiction: dict[str, int] = {}
        by_admission: dict[str, int] = {}
        for source in self.sources:
            by_tier[source.trust_tier] = by_tier.get(source.trust_tier, 0) + 1
            by_authority[source.authority_class] = (
                by_authority.get(source.authority_class, 0) + 1
            )
            by_admission[source.admission_status] = (
                by_admission.get(source.admission_status, 0) + 1
            )
            for jurisdiction in source.jurisdictions:
                by_jurisdiction[jurisdiction] = by_jurisdiction.get(jurisdiction, 0) + 1
        return {
            "schema_version": self.schema_version,
            "source_count": len(self.sources),
            "runtime_enabled_count": len(self.runtime_sources()),
            "artificial_source_count_limit": None,
            "catalog_file_count": len(self.catalog_files),
            "catalog_files": list(self.catalog_files),
            "by_trust_tier": dict(sorted(by_tier.items())),
            "by_authority_class": dict(sorted(by_authority.items())),
            "by_admission_status": dict(sorted(by_admission.items())),
            "by_jurisdiction": dict(sorted(by_jurisdiction.items())),
        }


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise SourceRegistryError(f"Invalid JSON in {path}: {exc}") from exc


def canonicalize_url(value: str) -> str:
    text = str(value or "").strip()
    parsed = urlsplit(text)
    if parsed.scheme.casefold() != "https":
        raise SourceRegistryError("Source URL must use HTTPS")
    if not parsed.hostname:
        raise SourceRegistryError("Source URL has no hostname")
    if parsed.username or parsed.password:
        raise SourceRegistryError("Credentials are forbidden in source URL")
    try:
        if parsed.port not in (None, 443):
            raise SourceRegistryError("Source URL must use the standard HTTPS port")
    except ValueError:
        raise SourceRegistryError("Invalid source URL port") from None
    filtered_query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_QUERY_KEYS
        and not any(key.casefold().startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
    ]
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (
            "https",
            parsed.netloc.casefold(),
            path,
            urlencode(filtered_query, doseq=True),
            "",
        )
    )


def _nonempty_string(value: Any, field: str, source_id: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise SourceRegistryError(f"{source_id}: {field} must be non-empty")
    return result


def _string_tuple(value: Any, field: str, source_id: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SourceRegistryError(f"{source_id}: {field} must be an array")
    result = tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    if not result:
        raise SourceRegistryError(f"{source_id}: {field} must not be empty")
    return result


def _integer(value: Any, field: str, source_id: str, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise SourceRegistryError(f"{source_id}: {field} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceRegistryError(f"{source_id}: {field} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise SourceRegistryError(
            f"{source_id}: {field} must be between {minimum} and {maximum}"
        )
    return result


def _number(
    value: Any, field: str, source_id: str, minimum: float, maximum: float
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SourceRegistryError(f"{source_id}: {field} must be numeric") from exc
    if not minimum <= result <= maximum:
        raise SourceRegistryError(
            f"{source_id}: {field} must be between {minimum} and {maximum}"
        )
    return result


def _boolean(value: Any, field: str, source_id: str) -> bool:
    if type(value) is not bool:
        raise SourceRegistryError(f"{source_id}: {field} must be a boolean")
    return value


def _validate_source(
    raw: dict[str, Any], *, catalog_file: Path, policy: dict[str, Any]
) -> SourceDefinition:
    source_id = _nonempty_string(raw.get("source_id"), "source_id", "<unknown>")
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise SourceRegistryError(
            f"{source_id}: source_id must match {SOURCE_ID_PATTERN.pattern}"
        )

    allowed_tiers = set(policy.get("allowed_trust_tiers") or [])
    allowed_authorities = set(policy.get("allowed_authority_classes") or [])
    allowed_admission = set(policy.get("allowed_admission_statuses") or [])
    allowed_adapters = set(policy.get("allowed_adapter_statuses") or [])

    trust_tier = _nonempty_string(raw.get("trust_tier"), "trust_tier", source_id)
    if trust_tier not in allowed_tiers or trust_tier not in TRUST_RANK:
        raise SourceRegistryError(f"{source_id}: unsupported trust_tier {trust_tier}")

    authority_class = _nonempty_string(
        raw.get("authority_class"), "authority_class", source_id
    )
    if authority_class not in allowed_authorities:
        raise SourceRegistryError(
            f"{source_id}: unsupported authority_class {authority_class}"
        )

    admission_status = _nonempty_string(
        raw.get("admission_status"), "admission_status", source_id
    )
    if admission_status not in allowed_admission:
        raise SourceRegistryError(
            f"{source_id}: unsupported admission_status {admission_status}"
        )

    adapter = raw.get("adapter")
    if not isinstance(adapter, dict):
        raise SourceRegistryError(f"{source_id}: adapter must be an object")
    adapter_id = _nonempty_string(adapter.get("id"), "adapter.id", source_id)
    adapter_status = _nonempty_string(
        adapter.get("status"), "adapter.status", source_id
    )
    if adapter_status not in allowed_adapters:
        raise SourceRegistryError(
            f"{source_id}: unsupported adapter.status {adapter_status}"
        )

    access = raw.get("access")
    if not isinstance(access, dict):
        raise SourceRegistryError(f"{source_id}: access must be an object")
    free_access_required = _boolean(access.get("free_access_required", True), "access.free_access_required", source_id)
    payment_required = _boolean(access.get("payment_required", False), "access.payment_required", source_id)
    terms_review_status = _nonempty_string(
        access.get("terms_review_status", "pending"),
        "access.terms_review_status",
        source_id,
    )
    if not free_access_required:
        raise SourceRegistryError(
            f"{source_id}: free_access_required must remain true"
        )
    if payment_required:
        raise SourceRegistryError(
            f"{source_id}: payment_required sources are forbidden by policy"
        )

    urls = _string_tuple(raw.get("canonical_urls"), "canonical_urls", source_id)
    canonical_urls = tuple(dict.fromkeys(canonicalize_url(item) for item in urls))

    runtime = raw.get("runtime")
    if not isinstance(runtime, dict):
        raise SourceRegistryError(f"{source_id}: runtime must be an object")
    runtime_enabled = _boolean(runtime.get("enabled", False), "runtime.enabled", source_id)
    per_host_concurrency = _integer(
        runtime.get("per_host_concurrency", 1),
        "runtime.per_host_concurrency",
        source_id,
        1,
        16,
    )
    minimum_request_interval_seconds = _number(
        runtime.get("minimum_request_interval_seconds", 1.0),
        "runtime.minimum_request_interval_seconds",
        source_id,
        0.0,
        86400.0,
    )
    maximum_retries = _integer(
        runtime.get("maximum_retries", 3),
        "runtime.maximum_retries",
        source_id,
        0,
        10,
    )
    freshness_value = runtime.get("freshness_seconds")
    freshness_seconds = (
        None
        if freshness_value is None
        else _integer(
            freshness_value,
            "runtime.freshness_seconds",
            source_id,
            60,
            366 * 86400,
        )
    )

    provenance = raw.get("provenance")
    if not isinstance(provenance, dict):
        raise SourceRegistryError(f"{source_id}: provenance must be an object")
    provenance_required = _boolean(provenance.get("required", True), "provenance.required", source_id)
    correction_tracking = _boolean(provenance.get("correction_tracking", True), "provenance.correction_tracking", source_id)
    if not provenance_required:
        raise SourceRegistryError(f"{source_id}: provenance.required must be true")

    if runtime_enabled:
        failures: list[str] = []
        if admission_status != ENABLED_ADMISSION_STATUS:
            failures.append("admission_status must be RUNTIME_ENABLED")
        if adapter_status != "implemented":
            failures.append("adapter.status must be implemented")
        if terms_review_status != "approved":
            failures.append("access.terms_review_status must be approved")
        if trust_tier == "T4_QUARANTINED":
            failures.append("T4 sources cannot be enabled")
        if failures:
            raise SourceRegistryError(
                f"{source_id}: runtime enable gate failed: {'; '.join(failures)}"
            )

    return SourceDefinition(
        source_id=source_id,
        display_name=_nonempty_string(
            raw.get("display_name"), "display_name", source_id
        ),
        authority_class=authority_class,
        trust_tier=trust_tier,
        evidence_roles=_string_tuple(
            raw.get("evidence_roles"), "evidence_roles", source_id
        ),
        jurisdictions=_string_tuple(
            raw.get("jurisdictions"), "jurisdictions", source_id
        ),
        languages=_string_tuple(raw.get("languages"), "languages", source_id),
        canonical_urls=canonical_urls,
        independence_group=_nonempty_string(
            raw.get("independence_group"), "independence_group", source_id
        ),
        admission_status=admission_status,
        adapter_id=adapter_id,
        adapter_status=adapter_status,
        runtime_enabled=runtime_enabled,
        free_access_required=free_access_required,
        payment_required=payment_required,
        terms_review_status=terms_review_status,
        priority=_integer(raw.get("priority", 50), "priority", source_id, 0, 1000),
        per_host_concurrency=per_host_concurrency,
        minimum_request_interval_seconds=minimum_request_interval_seconds,
        maximum_retries=maximum_retries,
        freshness_seconds=freshness_seconds,
        correction_tracking=correction_tracking,
        provenance_required=provenance_required,
        notes=str(raw.get("notes") or "").strip(),
        catalog_file=str(catalog_file.relative_to(BASE_DIR)),
    )


def iter_catalog_files(source_dir: Path = DEFAULT_SOURCE_DIR) -> Iterator[Path]:
    if not source_dir.is_dir():
        raise FileNotFoundError(source_dir)
    for path in sorted(source_dir.rglob("*.json")):
        if path.resolve() == DEFAULT_POLICY_PATH.resolve():
            continue
        yield path


def load_registry(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    policy_path: Path = DEFAULT_POLICY_PATH,
) -> Registry:
    policy = load_json(policy_path)
    if not isinstance(policy, dict):
        raise SourceRegistryError("registry-policy.json must contain an object")
    count_policy = policy.get("source_count_policy")
    if not isinstance(count_policy, dict):
        raise SourceRegistryError("source_count_policy must be an object")
    if count_policy.get("artificial_total_limit") is not None:
        raise SourceRegistryError("Artificial total source limits are prohibited")
    if bool(count_policy.get("discovery_auto_enable")):
        raise SourceRegistryError("Discovered sources must never auto-enable")

    sources: list[SourceDefinition] = []
    catalog_files: list[str] = []
    for path in iter_catalog_files(source_dir):
        document = load_json(path)
        if not isinstance(document, dict):
            raise SourceRegistryError(f"{path}: catalog must contain an object")
        if int(document.get("schema_version", 0)) != 1:
            raise SourceRegistryError(f"{path}: unsupported schema_version")
        raw_sources = document.get("sources")
        if not isinstance(raw_sources, list):
            raise SourceRegistryError(f"{path}: sources must be an array")
        catalog_files.append(str(path.relative_to(BASE_DIR)))
        for raw in raw_sources:
            if not isinstance(raw, dict):
                raise SourceRegistryError(f"{path}: every source must be an object")
            sources.append(_validate_source(raw, catalog_file=path, policy=policy))

    if not sources:
        raise SourceRegistryError("Source registry contains no sources")

    by_id: dict[str, SourceDefinition] = {}
    for source in sources:
        existing = by_id.get(source.source_id)
        if existing:
            raise SourceRegistryError(
                f"Duplicate source_id {source.source_id}: "
                f"{existing.catalog_file} and {source.catalog_file}"
            )
        by_id[source.source_id] = source

    ordered = tuple(
        sorted(
            sources,
            key=lambda source: (
                TRUST_RANK[source.trust_tier],
                -source.priority,
                source.source_id,
            ),
        )
    )
    return Registry(
        schema_version=1,
        sources=ordered,
        catalog_files=tuple(catalog_files),
    )


def select_sources(
    registry: Registry,
    *,
    evidence_roles: Iterable[str] = (),
    jurisdictions: Iterable[str] = (),
    languages: Iterable[str] = (),
    authority_classes: Iterable[str] = (),
    trust_tiers: Iterable[str] = (),
    runtime_only: bool = True,
    operational_limit: int | None = None,
) -> list[SourceDefinition]:
    """Select every eligible source unless a caller supplies a temporary work limit.

    ``operational_limit`` bounds one execution batch; it is not a registry or
    coverage ceiling and must never be persisted as a total-source limit.
    """

    role_set = {str(value) for value in evidence_roles}
    jurisdiction_set = {str(value) for value in jurisdictions}
    language_set = {str(value) for value in languages}
    authority_set = {str(value) for value in authority_classes}
    tier_set = {str(value) for value in trust_tiers}

    selected: list[SourceDefinition] = []
    for source in registry.sources:
        if runtime_only and not source.runtime_enabled:
            continue
        if role_set and not role_set.intersection(source.evidence_roles):
            continue
        if jurisdiction_set and not jurisdiction_set.intersection(source.jurisdictions):
            continue
        if language_set and not language_set.intersection(source.languages):
            continue
        if authority_set and source.authority_class not in authority_set:
            continue
        if tier_set and source.trust_tier not in tier_set:
            continue
        selected.append(source)

    if operational_limit is not None:
        if operational_limit <= 0:
            raise SourceRegistryError("operational_limit must be positive")
        return selected[:operational_limit]
    return selected


def assess_claim_evidence(
    registry: Registry,
    source_ids: Iterable[str],
    *,
    claim_kind: str,
) -> dict[str, Any]:
    by_id = registry.by_id()
    sources = [by_id[source_id] for source_id in dict.fromkeys(source_ids) if source_id in by_id]
    independent_t1 = {
        source.independence_group
        for source in sources
        if source.trust_tier == "T1_PRIMARY_OFFICIAL"
    }
    independent_t2 = {
        source.independence_group
        for source in sources
        if source.trust_tier == "T2_INSTITUTIONAL_CORROBORATION"
    }
    all_independent = {source.independence_group for source in sources}

    if claim_kind == "direct_official_fact":
        passed = bool(independent_t1)
        reason = (
            "At least one relevant T1 primary source is present"
            if passed
            else "A direct official fact requires a relevant T1 primary source"
        )
    elif claim_kind == "material_interpretive_claim":
        t1_plus_independent = bool(independent_t1) and len(all_independent) >= 2
        two_t2 = len(independent_t2) >= 2
        passed = t1_plus_independent or two_t2
        reason = (
            "Independent corroboration requirement passed"
            if passed
            else "Requires T1 plus independent corroboration or two independent T2 sources"
        )
    else:
        raise SourceRegistryError(f"Unsupported claim_kind: {claim_kind}")

    return {
        "claim_kind": claim_kind,
        "passed": passed,
        "reason": reason,
        "source_ids": [source.source_id for source in sources],
        "independence_groups": sorted(all_independent),
        "t1_groups": sorted(independent_t1),
        "t2_groups": sorted(independent_t2),
        "unknown_source_ids": sorted(set(source_ids) - set(by_id)),
    }


def coverage_ledger(registry: Registry) -> dict[str, Any]:
    coverage: dict[str, dict[str, set[str]]] = {
        "jurisdictions": {},
        "evidence_roles": {},
        "languages": {},
        "authority_classes": {},
    }
    for source in registry.sources:
        for value in source.jurisdictions:
            coverage["jurisdictions"].setdefault(value, set()).add(source.source_id)
        for value in source.evidence_roles:
            coverage["evidence_roles"].setdefault(value, set()).add(source.source_id)
        for value in source.languages:
            coverage["languages"].setdefault(value, set()).add(source.source_id)
        coverage["authority_classes"].setdefault(source.authority_class, set()).add(
            source.source_id
        )
    return {
        group: {
            key: {"count": len(source_ids), "source_ids": sorted(source_ids)}
            for key, source_ids in sorted(values.items())
        }
        for group, values in coverage.items()
    }


# ---------------------------------------------------------------------------
# Semantic core: capability states, claim routing, evidence qualification,
# and derived lane coverage. Pure helpers over the existing registry and
# additive policy descriptors; no new pipeline, no scoring/rank changes.
# ---------------------------------------------------------------------------

CAPABILITY_STATES = (
    "PUBLIC",
    "PUBLIC_LIMITED",
    "OPTIONAL_KEY",
    "AUTH_REQUIRED",
    "PREMIUM_ONLY",
    "RATE_LIMITED",
    "TEMP_UNAVAILABLE",
    "UNSUPPORTED",
)

DECLARED_ACCESS_STATES = ("free", "key", "auth", "premium")
OBSERVED_HEALTH_STATES = (
    "ok",
    "http_429",
    "transport_failure",
    "forbidden",
    "payment_prompted",
)
_FETCHABLE_ADAPTER_STATUSES = {"implemented"}


def _utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SourceRegistryError(f"invalid UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise SourceRegistryError(f"timestamp must carry a UTC offset: {value!r}")
    return parsed.astimezone(timezone.utc)


def classify_capability(
    source: SourceDefinition,
    *,
    declared_access: str | None = None,
    observed_health: str | None = None,
) -> str:
    """Map one source to an exact capability state.

    Declared access (catalog/metadata) and observed health (live signal) are
    separate strict inputs. ``free_access_required`` is an admission policy
    flag, NOT evidence that authentication is required; trust tier is not
    public availability; request budgets are not observed 429s.
    """
    if declared_access is not None and declared_access not in DECLARED_ACCESS_STATES:
        raise SourceRegistryError(f"unknown declared_access state: {declared_access!r}")
    if observed_health is not None and observed_health not in OBSERVED_HEALTH_STATES:
        raise SourceRegistryError(f"unknown observed_health state: {observed_health!r}")
    if observed_health == "http_429":
        return "RATE_LIMITED"
    if observed_health == "transport_failure":
        return "TEMP_UNAVAILABLE"
    if observed_health == "forbidden":
        # Forbidden stays unavailable; never silently downgrade to PUBLIC.
        return "AUTH_REQUIRED"
    if observed_health == "payment_prompted":
        return "PREMIUM_ONLY"
    if source.payment_required:
        return "PREMIUM_ONLY"
    if source.adapter_status not in _FETCHABLE_ADAPTER_STATUSES:
        return "UNSUPPORTED"
    if declared_access == "premium":
        return "PREMIUM_ONLY"
    if declared_access == "auth":
        return "AUTH_REQUIRED"
    if declared_access == "key":
        # Metadata only: never read the key itself.
        return "OPTIONAL_KEY"
    # Free public source: bounded by design when the catalog declares a
    # per-host request budget (declared limit, not an observed 429).
    if source.per_host_concurrency <= 1 or source.minimum_request_interval_seconds > 0:
        return "PUBLIC_LIMITED"
    return "PUBLIC"


def _policy_object(policy: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = policy.get(key)
    if not isinstance(value, dict):
        raise SourceRegistryError(f"policy must define an object for {key!r}")
    return value


def _authority_order(sources: Iterable[SourceDefinition]) -> list[SourceDefinition]:
    return sorted(
        sources,
        key=lambda source: (TRUST_RANK[source.trust_tier], -source.priority, source.source_id),
    )


def _strict_int(value: Any, name: str) -> int:
    # Centralized minima validation: type int (not bool) AND >= 1. Missing
    # fields (None) fail closed; permissive minima are never manufactured.
    if type(value) is not int or value < 1:
        raise SourceRegistryError(f"{name} must be an int >= 1 (bool/float/missing rejected)")
    return value


def route_claim(
    registry: Registry,
    claim_kind: str,
    policy: Mapping[str, Any],
    *,
    runtime_only: bool = True,
    federation_policy: Mapping[str, Any] | None = None,
    capability_facts: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Route one claim kind to candidate sources and requirements.

    Reuses ``select_sources`` and ``TRUST_RANK`` with a deterministic
    source-id tiebreak. Candidate count is evidence coverage, never a
    score/rank boost. Catalog inspection (``runtime_only=False``) lists
    disabled providers but does not qualify them.
    """
    families = _policy_object(policy, "claim_families")
    if claim_kind not in families:
        raise SourceRegistryError(f"unknown claim kind: {claim_kind!r}")
    family = families[claim_kind]
    if not isinstance(family, dict):
        raise SourceRegistryError(f"claim family {claim_kind!r} must be an object")
    semantics_map = _policy_object(policy, "claim_family_semantics")
    semantics = semantics_map.get(claim_kind)
    if not isinstance(semantics, dict):
        raise SourceRegistryError(f"claim family {claim_kind!r} lacks semantic descriptors")
    if not semantics.get("evidence_roles") and not semantics.get("authority_classes"):
        raise SourceRegistryError(
            f"claim family {claim_kind!r} descriptor filters are blank; refusing to match all sources"
        )
    candidates = _authority_order(
        select_sources(
            registry,
            evidence_roles=tuple(semantics.get("evidence_roles") or ()),
            authority_classes=tuple(semantics.get("authority_classes") or ()),
            runtime_only=runtime_only,
        )
    )
    # Declared capability per candidate (metadata only; no live probing, no keys).
    # Optional per-source capability facts (strict declared/observed inputs, same
    # classifier, no string-state bypass) may refine the declared state.
    available: list[str] = []
    unavailable: dict[str, str] = {}
    for source in candidates:
        fact: Mapping[str, str] = {}
        if capability_facts is not None:
            raw_fact = capability_facts.get(source.source_id)
            if raw_fact is not None and not isinstance(raw_fact, Mapping):
                raise SourceRegistryError(f"capability fact for {source.source_id!r} must be a mapping")
            fact = raw_fact if isinstance(raw_fact, Mapping) else {}
        declared = fact.get("declared_access")
        if declared is not None and declared not in DECLARED_ACCESS_STATES:
            raise SourceRegistryError(f"malformed declared_access fact: {declared!r}")
        health = fact.get("observed_health")
        if health is not None and health not in OBSERVED_HEALTH_STATES:
            raise SourceRegistryError(f"malformed observed_health fact: {health!r}")
        state = classify_capability(source, declared_access=declared, observed_health=health)
        if state in ("PUBLIC", "PUBLIC_LIMITED"):
            available.append(source.source_id)
        else:
            unavailable[source.source_id] = state
    retrieval_bounds = [
        value
        for value in (activation_max_age(federation_policy) if federation_policy is not None else None,)
        if value is not None
    ]
    source_bounds = [s.freshness_seconds for s in candidates if s.freshness_seconds is not None]
    applicable = retrieval_bounds + source_bounds
    return {
        "claim_kind": claim_kind,
        "catalog_inspection_only": not runtime_only,
        "candidate_sources": [s.source_id for s in candidates],
        "authority_order": [s.source_id for s in candidates],
        "freshness_requirement": {
            # Retrieval TTL ceiling: the stricter applicable bound (federation
            # activation-gate ceiling vs per-source catalog freshness). This is
            # a retrieval-freshness bound, not the source observation clock or
            # its expected publication period.
            "retrieval_max_age_seconds": min(applicable) if applicable else None,
            "activation_gate_ceiling_seconds": (
                activation_max_age(federation_policy) if federation_policy is not None else None
            ),
            "per_source_freshness_seconds": {
                s.source_id: s.freshness_seconds for s in candidates if s.freshness_seconds is not None
            },
            "source_observation_clock": "catalog freshness_seconds describes source cadence, not a retrieval TTL",
        },
        "minimum_lineages": {
            "minimum_primary_sources": _strict_int(
                family.get("minimum_primary_sources"), "minimum_primary_sources"
            ),
            "minimum_independent_groups": _strict_int(
                family.get("minimum_independent_groups"), "minimum_independent_groups"
            ),
        },
        "fallback_chain": {
            # Derived from healthy route candidates in authority order (not a
            # second hardcoded list); unavailable candidates are reported as
            # diagnostics and excluded.
            "source_ids": available,
            "unavailable_diagnostics": unavailable,
            "governed_by": "v213-source-federation-policy.json required_live_sources",
        },
    }


def activation_max_age(policy: Mapping[str, Any]) -> int | None:
    gate = policy.get("activation_gate")
    if not isinstance(gate, dict):
        return None
    value = gate.get("federation_snapshot_max_age_seconds")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def coverage_lanes(registry: Registry, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the nine advertised lanes from CURRENT registry metadata.

    Inventory projection only: presence here is NOT proof of lane
    availability or publication eligibility.
    """
    lanes = _policy_object(policy, "lane_semantics")
    result: dict[str, Any] = {}
    for lane in sorted(lanes):
        spec = lanes[lane]
        if not isinstance(spec, dict):
            raise SourceRegistryError(f"lane {lane!r} must be an object")
        sources = select_sources(
            registry,
            evidence_roles=tuple(spec.get("evidence_roles") or ()),
            authority_classes=tuple(spec.get("authority_classes") or ()),
            runtime_only=False,
        )
        present = bool(sources)
        result[lane] = {
            "present": present,
            "explicit_missing": not present,
            "source_count": len(sources),
            "source_ids": sorted(s.source_id for s in sources),
        }
    return result


def _finite_value(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return False


def _sec_binding_guard(
    registry: Registry,
    claim_kind: str,
    batch: ParsedBatch,
    expected_subject: Mapping[str, Any],
    sec_binding: Any,
) -> None:
    """SEC-bound observations require a valid typed fetch receipt + binding
    integrity proof even if the caller supplies http_status=200. Generic
    providers are unchanged."""
    if batch.source_id != SEC_REGISTRY_SOURCE_ID:
        if sec_binding is not None:
            raise SourceRegistryError("sec_binding is only valid for SEC-bound observations")
        return
    if not isinstance(sec_binding, SecClaimBinding):
        raise SourceRegistryError("SEC-bound observations require a valid SecClaimBinding")
    if sec_binding.claim_kind != claim_kind:
        raise SourceRegistryError("sec binding claim kind does not match")
    if sec_binding.source_id != batch.source_id:
        raise SourceRegistryError("sec binding source does not match the batch source")
    if sec_binding.raw_content_sha256 != batch.content_sha256:
        raise SourceRegistryError("sec binding raw content hash does not match the batch")
    if sec_binding.receipt.content_sha256 != batch.content_sha256:
        raise SourceRegistryError("sec receipt hash does not match the batch content hash")
    from adapters.base import validate_fetch_receipt

    validate_fetch_receipt(
        sec_binding.receipt,
        source_id=SEC_REGISTRY_SOURCE_ID,
        expected_urls=(sec_binding.canonical_url,),
    )
    by_id = registry.by_id()
    source = by_id.get(SEC_REGISTRY_SOURCE_ID)
    if source is None:
        raise SourceRegistryError("canonical SEC registry source is missing")
    if "US" not in tuple(source.jurisdictions):
        raise SourceRegistryError("canonical SEC registry source jurisdiction is not US")
    if source.adapter_id != "sec_edgar":
        raise SourceRegistryError("canonical SEC registry adapter mapping changed")
    expected_cik = expected_subject.get("entity")
    if sec_binding.expected_cik != expected_cik:
        raise SourceRegistryError("sec binding CIK does not match the expected subject")
    expected_period = expected_subject.get("period")
    if claim_kind == "issuer_financial_statement" and sec_binding.expected_period != expected_period:
        raise SourceRegistryError("sec binding period does not match the expected subject")
    recomputed = project_sec_records(
        batch.records,
        claim_kind=claim_kind,
        expected_cik=sec_binding.expected_cik,
        expected_period=sec_binding.expected_period,
        resolved_symbol_alias=None,
        jurisdiction="US",
    )
    projected = sec_binding.projected_records
    if sec_binding.resolved_symbol is not None:
        projected = tuple({**record, "symbol": sec_binding.resolved_symbol} for record in projected)
    if canonical_json(projected) != sec_binding.projected_record_digest:
        raise SourceRegistryError("sec binding projected record digest does not verify")
    if canonical_json(projected) != canonical_json(recomputed):
        raise SourceRegistryError("sec binding projection does not verify against the raw batch")


def qualify_claim_evidence(
    registry: Registry,
    claim_kind: str,
    policy: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    *,
    now: str,
    expected_subject: Mapping[str, Any] | None = None,
    federation_policy: Mapping[str, Any] | None = None,
    sec_binding: Any = None,
) -> dict[str, Any]:
    """Qualify explicit original observations for one claim kind.

    Accepts validated ``ParsedBatch`` instances (existing adapter contract,
    reused unchanged) plus explicit ``data_origin_lineage`` / ``transport_lineage``
    metadata. Only fully valid origins are counted; mirror equivalence is the
    union of same origin publisher group / same disclosure id / same content
    hash (order-independent); transport is recorded but never counted.
    ``publication_eligible`` is always False.
    """
    if not isinstance(expected_subject, Mapping) or not expected_subject:
        raise SourceRegistryError("expected_subject is mandatory (non-empty mapping)")
    now_dt = _utc_datetime(now)
    families = _policy_object(policy, "claim_families")
    if claim_kind not in families:
        raise SourceRegistryError(f"unknown claim kind: {claim_kind!r}")
    family = families[claim_kind]
    required_fields = tuple(family.get("required_fields") or ())
    if "period" in required_fields and "period" not in expected_subject:
        raise SourceRegistryError("expected_subject must bind the required period")
    semantics_map = _policy_object(policy, "claim_family_semantics")
    semantics = semantics_map.get(claim_kind)
    if not isinstance(semantics, dict):
        raise SourceRegistryError(f"claim family {claim_kind!r} lacks semantic descriptors")
    binding_fields = tuple(semantics.get("subject_binding_fields") or ())
    for binding_field in binding_fields:
        if binding_field not in expected_subject:
            raise SourceRegistryError(
                f"expected_subject must bind the family subject field {binding_field!r}"
            )
    by_id = registry.by_id()
    ceiling = activation_max_age(federation_policy) if federation_policy is not None else None
    route = route_claim(
        registry, claim_kind, policy, runtime_only=True, federation_policy=federation_policy
    )
    candidate_ids = set(route["candidate_sources"])

    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def reject(index: int, reason: str) -> None:
        rejected.append({"observation_index": index, "reason": reason})

    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping):
            reject(index, "observation must be a mapping")
            continue
        batch = observation.get("parsed_batch")
        if not isinstance(batch, ParsedBatch):
            reject(index, "parsed_batch must be a validated ParsedBatch")
            continue
        try:
            _sec_binding_guard(registry, claim_kind, batch, expected_subject, sec_binding)
        except SourceRegistryError as exc:
            reject(index, f"sec binding rejected: {exc}")
            continue
        if not isinstance(batch.records, tuple) or not batch.records or not all(
            isinstance(record, Mapping) for record in batch.records
        ):
            reject(index, "batch records must be a non-empty tuple of mappings")
            continue
        # SEC-bound observations carry raw records; field/subject checks run
        # on the binding's projected records (the guard verified the digest).
        check_records = batch.records
        if batch.source_id == SEC_REGISTRY_SOURCE_ID:
            check_records = sec_binding.projected_records
        if type(batch.record_count) is not int or batch.record_count != len(batch.records):
            reject(index, "batch record_count must be an int matching the record count")
            continue
        if not isinstance(batch.content_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", batch.content_sha256):
            reject(index, "content_sha256 must be a 64-hex hash")
            continue
        if not isinstance(batch.schema_sha256, str) or batch.schema_sha256 != schema_fingerprint(batch.records):
            reject(index, "schema_sha256 does not match the recomputed schema fingerprint")
            continue
        source = by_id.get(batch.source_id)
        if source is None:
            reject(index, "unknown or unregistered source_id")
            continue
        if not source.runtime_enabled:
            reject(index, "source is not runtime-enabled (registration is not success)")
            continue
        if source.source_id not in candidate_ids:
            reject(index, "source is not a route candidate for this claim")
            continue
        origin = observation.get("data_origin_lineage")
        if not isinstance(origin, Mapping):
            reject(index, "missing data_origin_lineage lineage")
            continue
        publisher = origin.get("publisher_identity")
        # The origin publisher IS the batch source; transport describes the
        # fetch path only and never re-attributes origin authority.
        if publisher != batch.source_id:
            reject(index, "origin publisher does not match the batch source")
            continue
        if publisher not in by_id:
            reject(index, "origin publisher does not resolve to a registered source")
            continue
        group = origin.get("independence_group")
        if not isinstance(group, str) or group != by_id[publisher].independence_group:
            reject(index, "origin group contradicts the registered publisher identity")
            continue
        disclosure_id = origin.get("original_disclosure_id")
        if not isinstance(disclosure_id, str) or not disclosure_id.strip():
            reject(index, "missing original disclosure/event id")
            continue
        transport = observation.get("transport_lineage")
        if not isinstance(transport, Mapping):
            reject(index, "missing transport_lineage")
            continue
        if transport.get("fetch_source") != batch.source_id:
            reject(index, "transport fetch_source does not match the batch source")
            continue
        path = transport.get("path")
        if not isinstance(path, str):
            reject(index, "transport path must be a valid HTTPS path")
            continue
        try:
            canonical_path = canonicalize_url(path)
        except SourceRegistryError:
            reject(index, "transport path failed canonical URL validation")
            continue
        if urlsplit(canonical_path).scheme != "https" or not urlsplit(canonical_path).netloc:
            reject(index, "transport path must be a host-bound HTTPS URL")
            continue
        if batch.source_id == SEC_REGISTRY_SOURCE_ID and path != sec_binding.receipt.canonical_url:
            reject(index, "sec transport path must match the receipt canonical URL")
            continue
        http_status = observation.get("http_status")
        if type(http_status) is not int or http_status != 200:
            reject(index, "no actual HTTP 200 (bool or non-200 is not success)")
            continue
        declared_access = observation.get("declared_access")
        if declared_access not in DECLARED_ACCESS_STATES:
            reject(index, f"malformed declared_access state: {declared_access!r}")
            continue
        observed_health = observation.get("observed_health")
        if observed_health is not None and observed_health not in OBSERVED_HEALTH_STATES:
            reject(index, f"malformed observed_health state: {observed_health!r}")
            continue
        capability = classify_capability(
            source, declared_access=declared_access, observed_health=observed_health
        )
        if capability not in ("PUBLIC", "PUBLIC_LIMITED"):
            reject(index, f"capability {capability} does not qualify")
            continue
        records_ok = True
        for record in check_records:
            for field in required_fields:
                if not _finite_value(record.get(field)):
                    reject(index, f"missing or non-finite required field: {field}")
                    records_ok = False
                    break
            if not records_ok:
                break
        if not records_ok:
            continue
        as_of = observation.get("as_of")
        if not isinstance(as_of, str):
            reject(index, "missing as_of clock")
            continue
        try:
            as_of_dt = _utc_datetime(as_of)
        except SourceRegistryError:
            reject(index, "invalid as_of clock (UTC timezone required)")
            continue
        if batch.source_id == SEC_REGISTRY_SOURCE_ID and as_of != sec_binding.evidence_as_of.split("|")[0]:
            reject(index, "sec as_of must equal the bound-derived clock")
            continue
        try:
            retrieved_dt = _utc_datetime(batch.retrieved_at)
        except SourceRegistryError:
            reject(index, "invalid batch.retrieved_at clock (UTC timezone required)")
            continue
        if as_of_dt > now_dt:
            reject(index, "as_of is in the future")
            continue
        if retrieved_dt > now_dt:
            reject(index, "batch.retrieved_at is in the future")
            continue
        bounds = [value for value in (source.freshness_seconds, ceiling) if value is not None]
        if not bounds:
            reject(index, "no applicable TTL bound; refusing unbounded age")
            continue
        ttl = min(bounds)
        if (now_dt - as_of_dt).total_seconds() > ttl:
            reject(index, "as_of is stale beyond the applicable TTL")
            continue
        if (now_dt - retrieved_dt).total_seconds() > ttl:
            reject(index, "batch.retrieved_at is stale beyond the applicable TTL")
            continue
        subject = observation.get("subject")
        if not isinstance(subject, Mapping) or not subject:
            reject(index, "missing subject binding")
            continue
        subject_ok = True
        for key, expected in expected_subject.items():
            if subject.get(key) != expected:
                reject(index, f"subject binding mismatch for {key!r}")
                subject_ok = False
                break
        if not subject_ok:
            continue
        # Every expected binding key must be present in EACH record with the
        # expected value; metadata alone never qualifies. Records must be
        # finite canonical JSON.
        for record in check_records:
            try:
                canonical_json(record)
            except (ValueError, TypeError, RecursionError):
                reject(index, "record is not finite canonical JSON")
                subject_ok = False
                break
            for key, expected in expected_subject.items():
                if key not in record or record[key] != expected:
                    reject(index, f"record does not bind expected subject {key!r}")
                    subject_ok = False
                    break
            if not subject_ok:
                break
        if not subject_ok:
            continue
        valid.append(
            {
                "observation_index": index,
                "source_id": batch.source_id,
                "trust_tier": source.trust_tier,
                "independence_group": group,
                "original_disclosure_id": disclosure_id,
                "content_sha256": batch.content_sha256,
                # Transport describes the fetch source/path only; it is never
                # counted as independence.
                "transport": {"fetch_source": transport.get("fetch_source"), "path": path},
                "records": check_records,
            }
        )

    # Mirror equivalence: union of same origin publisher group / same
    # publisher-qualified disclosure id / same content hash, independent of
    # input order. A bare local disclosure id is never cross-publisher.
    parent = list(range(len(valid)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    for key in ("independence_group", "content_sha256"):
        buckets: dict[Any, list[int]] = {}
        for i, entry in enumerate(valid):
            buckets.setdefault(entry[key], []).append(i)
        for indices in buckets.values():
            for other in indices[1:]:
                union(indices[0], other)
    disclosure_buckets: dict[Any, list[int]] = {}
    for i, entry in enumerate(valid):
        disclosure_buckets.setdefault(
            (entry["independence_group"], entry["original_disclosure_id"]), []
        ).append(i)
    for indices in disclosure_buckets.values():
        for other in indices[1:]:
            union(indices[0], other)

    classes = {find(i) for i in range(len(valid))}
    primary_classes = {
        find(i) for i, entry in enumerate(valid) if entry["trust_tier"] == "T1_PRIMARY_OFFICIAL"
    }
    # Minima use mirror-collapsed classes, not raw group counts; at least one
    # fully valid observation is an explicit invariant (empty evidence denies).
    minimum_primary = _strict_int(family.get("minimum_primary_sources"), "minimum_primary_sources")
    minimum_groups = _strict_int(family.get("minimum_independent_groups"), "minimum_independent_groups")
    conflict = _material_conflict(valid, required_fields)
    qualified = (
        not conflict
        and len(valid) >= 1
        and len(primary_classes) >= minimum_primary
        and len(classes) >= minimum_groups
    )
    return {
        "qualified": qualified,
        "evidence_qualified": qualified,
        "claim_kind": claim_kind,
        "valid_origins": len(classes),
        "primary_origins": len(primary_classes),
        "independent_groups": len(classes),
        "independent_group_ids": sorted({entry["independence_group"] for entry in valid}),
        "material_conflict": conflict,
        "minimum_primary_sources": minimum_primary,
        "minimum_independent_groups": minimum_groups,
        "rejected": rejected,
        "valid": [
            {
                "observation_index": entry["observation_index"],
                "source_id": entry["source_id"],
                "independence_group": entry["independence_group"],
                "original_disclosure_id": entry["original_disclosure_id"],
                "content_sha256": entry["content_sha256"],
                "transport": entry["transport"],
            }
            for entry in valid
        ],
        # Local semantic evidence assessment only; downstream admission gates
        # still apply. Never flip to True here.
        "publication_eligible": False,
    }


def _material_conflict(valid: Sequence[Mapping[str, Any]], required_fields: tuple[str, ...]) -> bool:
    """Any conflicting material scalar values across independent groups in the
    same claim scope conflict; a shared value cannot mask the conflict. One
    group holding multiple values (e.g. multiple periods) is not by itself a
    cross-group conflict."""
    if len(valid) < 2:
        return False
    for field in required_fields:
        value_groups: dict[Any, set[str]] = {}
        for entry in valid:
            for record in entry["records"]:
                value = record.get(field)
                if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                    value_groups.setdefault(value, set()).add(entry["independence_group"])
        if len(value_groups) >= 2 and len(set().union(*value_groups.values())) >= 2:
            return True
    return False


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


def registry_document(registry: Registry) -> dict[str, Any]:
    return {
        **registry.summary(),
        "sources": [source.public_record() for source in registry.sources],
        "coverage": coverage_ledger(registry),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and query the unbounded authoritative source registry"
    )
    parser.add_argument(
        "command", choices=("validate", "summary", "coverage", "route", "write-normalized")
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--claim-kind", default=None)
    parser.add_argument("--include-catalog", action="store_true")
    parser.add_argument("--lanes", action="store_true")
    args = parser.parse_args()

    try:
        registry = load_registry(args.source_dir, args.policy)
    except (FileNotFoundError, SourceRegistryError) as exc:
        print(f"SOURCE_REGISTRY_INVALID: {exc}")
        return 1

    if args.command == "validate":
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "source_count": len(registry.sources),
                    "runtime_enabled_count": len(registry.runtime_sources()),
                    "artificial_source_count_limit": None,
                },
                ensure_ascii=False,
            )
        )
    elif args.command == "summary":
        print(json.dumps(registry.summary(), ensure_ascii=False, indent=2))
    elif args.command == "coverage":
        if args.lanes:
            claim_policy = load_json(DEFAULT_CLAIM_POLICY_PATH)
            print(
                json.dumps(
                    {
                        "ledger": coverage_ledger(registry),
                        "lanes": coverage_lanes(registry, claim_policy),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(json.dumps(coverage_ledger(registry), ensure_ascii=False, indent=2))
    elif args.command == "route":
        if not args.claim_kind:
            print("SOURCE_REGISTRY_INVALID: route requires --claim-kind")
            return 1
        claim_policy = load_json(DEFAULT_CLAIM_POLICY_PATH)
        federation_policy = load_json(DEFAULT_FEDERATION_POLICY_PATH)
        try:
            envelope = route_claim(
                registry,
                args.claim_kind,
                claim_policy,
                runtime_only=not args.include_catalog,
                federation_policy=federation_policy,
            )
        except SourceRegistryError as exc:
            print(f"SOURCE_REGISTRY_INVALID: {exc}")
            return 1
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
    elif args.command == "write-normalized":
        atomic_write_json(args.output, registry_document(registry))
        print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
