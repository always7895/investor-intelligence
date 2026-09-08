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
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = BASE_DIR / "config" / "sources"
DEFAULT_POLICY_PATH = DEFAULT_SOURCE_DIR / "registry-policy.json"
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
        "command", choices=("validate", "summary", "coverage", "write-normalized")
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
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
        print(json.dumps(coverage_ledger(registry), ensure_ascii=False, indent=2))
    elif args.command == "write-normalized":
        atomic_write_json(args.output, registry_document(registry))
        print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
