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
from typing import Any, Iterable, Mapping
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


@dataclass(frozen=True)
class CompanyFactorBinding:
    schema_version: int
    acquisition_run_id: str
    binding_id: str
    claim_id: str
    subject: str
    factor: str
    metric: str
    product_or_spec: str
    region: str
    unit: str
    period: str
    period_type: str
    entity: str | None
    security: str | None
    evidence_role: str
    source_clock: str
    event_clock: str
    retrieval_clock: str
    canonical_observation_ids: tuple[str, ...]
    lineage_ids: tuple[str, ...]
    independent_lineage_count: int
    is_test_binding: bool = False
    comparability: dict[str, Any] = None

    def as_json(self) -> dict[str, Any]:
        d = asdict(self)
        if self.comparability is None:
            d["comparability"] = {}
        return d


def compute_independent_lineages(observations: Iterable[Mapping[str, Any]]) -> int:
    """Compute connected components of observations to deduplicate same-issuer families.

    Observations sharing origin_group, independence_group, or content_sha256 collapse
    transitively into a single evidence family.
    """
    components: list[set[str]] = []
    for obs in observations:
        if not isinstance(obs, Mapping):
            continue
        indep = str(obs.get("independence_group") or "").strip()
        origin = str(obs.get("origin_group") or (obs.get("payload") or {}).get("origin_group") or "").strip()
        sha = str(obs.get("content_sha256") or "").strip()

        keys: set[str] = set()
        if indep:
            keys.add(f"publisher:{indep}")
        if origin:
            keys.add(f"origin:{origin}")
        if sha:
            keys.add(f"hash:{sha}")

        if not keys:
            keys.add(f"anon:{id(obs)}")

        matched = [comp for comp in components if comp & keys]
        for comp in matched:
            keys.update(comp)
            components.remove(comp)
        components.append(keys)

    return len(components)




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


# Research confidence is stricter than admitting a single attributable fact.
# These are authority kinds, NOT a domain/publisher whitelist. New providers use
# the extensible registry and the same free-access/adapter/provenance gates.
RESEARCH_CLAIM_AUTHORITIES = {
    "issuer_financial_statement": {"securities_regulator", "corporate_issuer", "company_ir", "official_issuer"},
    "issuer_guidance_or_contract": {"securities_regulator", "corporate_issuer", "company_ir", "procurement_authority", "official_issuer"},
    "macro_indicator": {"central_bank", "national_statistics_office", "intergovernmental_organization", "international_organization", "finance_ministry_or_treasury"},
    "market_observation": {"stock_exchange", "regulated_exchange", "market_infrastructure"},
    "regulatory_event": {"securities_regulator", "financial_regulator", "government_legal_authority", "court_or_legal_registry"},
    "industry_event": set(),
}
RESEARCH_CLAIM_ROLES = {
    "issuer_financial_statement": {"financial_statements", "issuer_filings", "financial_reporting"},
    "issuer_guidance_or_contract": {"issuer_filings", "guidance", "contracts", "material_events", "financial_reporting"},
    "macro_indicator": {"economic_data", "macroeconomics", "rates", "employment", "inflation", "gdp", "industry_accounts", "macro_reporting"},
    "market_observation": {"market_data", "quotes", "market_reporting"},
    "regulatory_event": {"regulation", "enforcement", "material_events", "financial_reporting"},
    "industry_event": {"industry_research", "technology", "sector_research", "material_events"},
}
RESEARCH_FACT_MAX_AGE_DAYS = {
    "issuer_financial_statement": 150, "issuer_guidance_or_contract": 180,
    "macro_indicator": 120, "market_observation": 2,
    "regulatory_event": 180, "industry_event": 90,
}
RESEARCH_CLASSES = {"primary_company_regulatory", "market_exchange", "macro_industry", "independent_journalism_research"}
RESEARCH_COMPARABILITY = ("subject", "metric", "period", "unit", "currency", "basis", "scope")


def _research_known_text(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip())
            and value.strip().upper() not in {"UNKNOWN", "UNAVAILABLE", "N/A", "UNSPECIFIED", "NOT_DISCLOSED"})


def _research_class(observation: SourceObservation) -> str:
    authority = observation.authority_class
    if observation.trust_tier not in {"T1_PRIMARY_OFFICIAL", "T2_INSTITUTIONAL_CORROBORATION"}:
        return "discovery_only"
    if authority in {"stock_exchange", "regulated_exchange", "market_infrastructure"}:
        return "market_exchange"
    if authority in {"central_bank", "national_statistics_office", "intergovernmental_organization", "international_organization", "industry_association", "public_sector_industry_body", "finance_ministry_or_treasury"}:
        return "macro_industry"
    if authority in {"securities_regulator", "corporate_issuer", "company_ir", "procurement_authority", "official_issuer", "financial_regulator", "government_legal_authority", "court_or_legal_registry"}:
        return "primary_company_regulatory"
    if authority in {"financial_journalism", "academic_research", "institutional_research", "academic_repository", "reputable_newswire", "reputable_financial_media", "public_service_media"}:
        return "independent_journalism_research"
    return "discovery_only"


def _research_families(rows: list[dict[str, Any]]) -> int:
    # Connected components, not distinct URL/group counts: overlap on ANY
    # publisher, origin lineage, or body hash collapses transitively.
    components: list[set[str]] = []
    for row in rows:
        keys = {"publisher:" + row["independence_group"],
                "origin:" + row["origin_group"], "hash:" + row["content_sha256"]}
        matched = [part for part in components if part & keys]
        for part in matched:
            keys.update(part)
            components.remove(part)
        components.append(keys)
    return len(components)


def reconcile_research_claims(
    record: Mapping[str, Any], *, registry: Registry | None = None,
    now: datetime | None = None, health_states: Mapping[str, str] | None = None,
    acquisition_run: Any = None,
) -> dict[str, Any]:
    """Offline exact-claim control plane using the existing observation boundary.

    Legacy URL lists remain useful discovery but never silently acquire missing
    claim IDs, original lineage, supporting passages, or current-fact timestamps.
    Observation metadata is parser evidence, not proof that a provider was fetched
    in this run. health_states must come from caller-owned runtime health, never
    the document; an absent map is degraded. No provider activation, network calls
    or score changes occur here.
    """
    clock = now or utc_now()
    if clock.tzinfo is None:
        raise SourceObservationError("Validation clock must include a timezone")
    if acquisition_run is not None:
        from source_acquisition import AcquisitionRun, compute_registry_digest
        if type(acquisition_run) is not AcquisitionRun:
            raise SourceObservationError("acquisition_run must be an AcquisitionRun instance")
        if registry is not None:
            if compute_registry_digest(registry) != compute_registry_digest(acquisition_run.registry):
                raise SourceObservationError("Explicit registry does not match acquisition_run registry")
        registry = acquisition_run.registry
    raw_claims = record.get("material_claims")
    raw_rows = record.get("source_observations")
    claims = raw_claims if isinstance(raw_claims, list) else []
    rows = raw_rows if isinstance(raw_rows, list) else []
    overflow = len(claims) > 40 or len(rows) > 100
    invalid_claims = overflow or not claims
    accepted: list[dict[str, Any]] = []
    rejected = 0
    if rows and registry is None:
        from source_registry import load_registry
        try:
            registry = load_registry()
        except (SourceRegistryError, OSError):
            registry = None
    has_caller_ticker = acquisition_run is not None and "ticker" in record
    valid_caller_ticker = False
    canonical_caller_ticker = None
    if has_caller_ticker:
        caller_ticker = record.get("ticker")
        if isinstance(caller_ticker, str) and caller_ticker.strip():
            valid_caller_ticker = True
            canonical_caller_ticker = caller_ticker.strip().upper()
    for raw in rows[:100]:
        try:
            if registry is None:
                raise SourceObservationError("Registry unavailable")
            source_id = raw.get("source_id") if isinstance(raw, dict) else None
            if acquisition_run is not None:
                health = acquisition_run.health_for(raw, now=clock)
                if has_caller_ticker:
                    raw_payload = raw.get("payload") if isinstance(raw, dict) else None
                    raw_subject = raw_payload.get("subject") if isinstance(raw_payload, dict) else None
                    if not (valid_caller_ticker and raw_subject == canonical_caller_ticker):
                        if health == "HEALTHY":
                            health = "DEGRADED"
            else:
                health = (health_states or {}).get(source_id, "DEGRADED")
            # A saved failure can reduce, but never promote, current health.
            recorded_health = (raw.get("source_health") if isinstance(raw, dict) else None) or "DEGRADED"
            severity = {"HEALTHY": 0, "DEGRADED": 1, "CIRCUIT_OPEN": 2, "QUARANTINED": 3}
            if health not in severity or recorded_health not in severity:
                raise SourceObservationError("Invalid runtime health")
            health = max((health, recorded_health), key=severity.__getitem__)
            obs = normalize_observation(raw, registry=registry, now=clock, source_health=health)
            payload = obs.payload
            claim_ids = payload.get("claim_ids")
            if not isinstance(claim_ids, list) or not claim_ids or not all(isinstance(cid, str) and 0 < len(cid) <= 120 for cid in claim_ids):
                raise SourceObservationError("Exact claim IDs required")
            if any(not _research_known_text(payload.get(key)) for key in (*RESEARCH_COMPARABILITY, "passage", "origin_group")):
                raise SourceObservationError("Claim provenance/comparability required")
            value = payload.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float, str)) or value == "":
                raise SourceObservationError("Scalar claim value required")
            fact_time = parse_timestamp(payload.get("as_of"), "fact as_of")
            published = parse_timestamp(obs.published_at, "published_at")
            if fact_time > published + FUTURE_CLOCK_TOLERANCE:
                raise SourceObservationError("Fact as_of cannot be a future scenario")
            limit = RESEARCH_FACT_MAX_AGE_DAYS.get(obs.claim_type)
            current = (obs.freshness_status == "CURRENT" and limit is not None
                       and (clock - fact_time).total_seconds() <= limit * 86400)
            source_class = _research_class(obs)
            primary = (obs.trust_tier == "T1_PRIMARY_OFFICIAL"
                       and obs.authority_class in RESEARCH_CLAIM_AUTHORITIES.get(obs.claim_type, set()))
            admitted = (source_class != "discovery_only"
                        and obs.evidence_role in RESEARCH_CLAIM_ROLES.get(obs.claim_type, set())
                        and obs.source_health == "HEALTHY")
            expires = min(published + timedelta(seconds=registry.by_id()[obs.source_id].freshness_seconds or 0),
                          fact_time + timedelta(days=limit or 0))
            accepted.append({
                "observation_id": obs.observation_id, "source_id": obs.source_id,
                "url": obs.canonical_url,
                "domain": urlsplit(obs.canonical_url).hostname or "", "source_class": source_class,
                "publisher": obs.source_display_name, "published_at": obs.published_at,
                "retrieved_at": obs.retrieved_at, "as_of": fact_time.isoformat(),
                "source_health": obs.source_health,
                "primary": primary, "independence_group": obs.independence_group,
                "origin_group": payload["origin_group"], "claim_ids": list(claim_ids),
                "claim_type": obs.claim_type, "freshness": "CURRENT" if current else "STALE",
                "confidence": (1.0 if primary else 0.6) if admitted and current else 0.0,
                "valid_until": expires.isoformat(),
                "content_sha256": obs.content_sha256, "passage": payload["passage"],
                "value": value, "admitted": admitted,
                "correction_status": obs.correction_status,
                "supersedes_observation_id": obs.supersedes_observation_id,
                **{key: payload[key] for key in RESEARCH_COMPARABILITY},
            })
        except (SourceObservationError, SourceRegistryError, TypeError, ValueError):
            # Never echo a rejected payload, credential-bearing URL, or exception.
            rejected += 1
    # Dedup exact rows, not document IDs: one filing can support multiple claims,
    # and conflicting parses of the same document must remain visible.
    accepted = list({hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(): row for row in accepted}.values())
    results = []
    seen_claims: set[str] = set()
    for claim in claims[:40]:
        valid = (isinstance(claim, dict)
                 and all(_research_known_text(claim.get(key))
                         for key in ("claim_id", "claim_type", *RESEARCH_COMPARABILITY)))
        cid = claim.get("claim_id", "INVALID") if isinstance(claim, dict) else "INVALID"
        kind = claim.get("claim_type") if isinstance(claim, dict) else None
        valid = valid and cid not in seen_claims and kind in RESEARCH_CLAIM_AUTHORITIES
        seen_claims.add(str(cid))
        invalid_claims = invalid_claims or not valid
        bound = [row for row in accepted if valid and cid in row["claim_ids"]
                 and row["claim_type"] == kind and row["admitted"]]
        comparable = [row for row in bound if all(row[key] == claim[key] for key in RESEARCH_COMPARABILITY)]
        live = [row for row in comparable if row["freshness"] == "CURRENT"]
        # Only an explicit, later correction by the same source family may
        # retire its old observation. Keep both rows in the evidence ledger.
        superseded: set[str] = set()
        for row in live:
            for old in live:
                if (row["correction_status"] in {"CORRECTED", "RESTATED", "REVISED"}
                    and row["supersedes_observation_id"] == old["observation_id"]
                    and row["independence_group"] == old["independence_group"]
                    and row["origin_group"] == old["origin_group"]
                    and row["published_at"] > old["published_at"]):
                    superseded.add(old["observation_id"])
        live = [row for row in live if row["observation_id"] not in superseded]
        families = _research_families(live)
        primaries = sorted([row for row in live if row["primary"]], key=lambda row: row["published_at"], reverse=True)
        conflict = bool(live and any(row["value"] != live[0]["value"] for row in live[1:]))
        reasons: list[str] = []
        status = "UNAVAILABLE"
        if not valid:
            reasons.append("INVALID_OR_UNSUPPORTED_CLAIM")
        elif conflict:
            status = "CONFLICTED"
            reasons.append("MATERIAL_VALUE_CONFLICT")
        elif bound and len(comparable) != len(bound):
            reasons.append("NOT_COMPARABLE")
        elif not live:
            status = "STALE" if comparable else "UNAVAILABLE"
            reasons.append("CURRENT_CLAIM_EVIDENCE_REQUIRED")
        elif RESEARCH_CLAIM_AUTHORITIES[kind] and not primaries:
            reasons.append("PRIMARY_AUTHORITY_REQUIRED")
        elif families < 2:
            status = "SINGLE_SOURCE"
            reasons.append("INDEPENDENT_CORROBORATION_REQUIRED")
        else:
            status = "SUPPORTED"
        candidate = primaries[0] if primaries else None
        results.append({
            "claim_id": cid if isinstance(cid, str) else "INVALID", "status": status,
            "independent_evidence_families": families, "primary_source_count": _research_families(primaries),
            "high_confidence_eligible": status == "SUPPORTED",
            "confidence": 1.0 if status == "SUPPORTED" else 0.49 if status == "SINGLE_SOURCE" else 0.0,
            "value": live[0]["value"] if status in {"SUPPORTED", "SINGLE_SOURCE"} else None,
            "authority_candidate": {"observation_id": candidate["observation_id"], "value": candidate["value"]} if candidate else None,
            "conflict_set": [{"observation_id": row["observation_id"], "value": row["value"], "primary": row["primary"]} for row in live] if conflict else [],
            "evidence_ids": [row["observation_id"] for row in live],
            "superseded_observation_ids": sorted(superseded), "reasons": reasons,
        })
    current_rows = [row for row in accepted if row["admitted"] and row["freshness"] == "CURRENT"]
    # Concentration measures documents, not the number of facts extracted from one.
    diversity_rows = list({row["observation_id"]: row for row in current_rows}.values())
    classes = sorted({row["source_class"] for row in diversity_rows})
    missing_classes = sorted(RESEARCH_CLASSES - set(classes))
    secondary_counts: dict[str, int] = {}
    secondary_publishers: dict[str, int] = {}
    for row in diversity_rows:
        if not row["primary"]:
            secondary_counts[row["domain"]] = secondary_counts.get(row["domain"], 0) + 1
            group = row["independence_group"]
            secondary_publishers[group] = secondary_publishers.get(group, 0) + 1
    # Multiple subdomains/APIs cannot evade concentration within one publisher.
    maximum_share = max([0, *secondary_counts.values(), *secondary_publishers.values()]) / max(1, len(diversity_rows))
    concentrated = maximum_share > 0.70
    expansion = [{"source_class": name, "action": "DISCOVER_ORIGINAL_SOURCE", "status": "PENDING_ADMISSION_AND_FETCH"} for name in missing_classes]
    if concentrated:
        expansion.append({"action": "EXPAND_INDEPENDENT_PUBLISHERS", "avoid_domains": sorted(secondary_counts), "status": "PENDING_ADMISSION_AND_FETCH"})
    all_supported = bool(results) and not invalid_claims and all(row["status"] == "SUPPORTED" for row in results)
    full = all_supported and not missing_classes and not concentrated
    overall = "SUPPORTED" if all_supported else "CONFLICTED" if any(row["status"] == "CONFLICTED" for row in results) else "UNAVAILABLE"
    return {
        "schema_version": 2, "status": overall, "claims": results, "evidence": accepted,
        "validated_at": clock.isoformat(),
        "valid_until": min([clock + timedelta(hours=2)] + [parse_timestamp(row["valid_until"], "valid_until") for row in current_rows]).isoformat(),
        "rejected_observation_count": rejected, "input_limit_exceeded": overflow,
        "all_material_claims_supported": all_supported, "full_research_eligible": full,
        "source_diversity": {"source_classes": classes, "source_class_count": len(classes),
                             "missing_source_classes": missing_classes,
                             "maximum_secondary_domain_share": round(maximum_share, 4),
                             "secondary_domain_concentrated": concentrated,
                             "expansion_plan": expansion, "expansion_executed": False},
        "framework": "SERENITY_PRIMARY", "leopold_role": "CONTEXT_ONLY",
        "stock_score_adjustment": 0, "conflict_values_averaged": False,
    }


def research_audit_high_eligible(audit: Any, *, now: datetime | None = None) -> bool:
    """Shared fail-closed consumer check; an old pooled boolean is insufficient."""
    if not isinstance(audit, dict) or audit.get("schema_version") != 2:
        return False
    if audit.get("full_research_eligible") is not True or audit.get("all_material_claims_supported") is not True:
        return False
    claims, evidence = audit.get("claims"), audit.get("evidence")
    if not isinstance(claims, list) or not claims or not isinstance(evidence, list):
        return False
    try:
        clock = now or utc_now()
        current = [row for row in evidence if isinstance(row, dict) and row.get("admitted") is True and row.get("freshness") == "CURRENT"]
        if not RESEARCH_CLASSES.issubset({row["source_class"] for row in current}):
            return False
        seen = set()
        for claim in claims:
            if (not isinstance(claim, dict) or claim.get("status") != "SUPPORTED"
                or claim.get("high_confidence_eligible") is not True or claim.get("conflict_set")
                or claim["claim_id"] in seen):
                return False
            seen.add(claim["claim_id"])
            bound = [row for row in current if row["observation_id"] in claim["evidence_ids"] and claim["claim_id"] in row["claim_ids"]]
            if _research_families(bound) < 2 or any(row["value"] != bound[0]["value"] for row in bound):
                return False
            if any(RESEARCH_CLAIM_AUTHORITIES.get(row["claim_type"]) for row in bound) and not any(row["primary"] for row in bound):
                return False
        validated = parse_timestamp(audit.get("validated_at"), "validated_at")
        expiry = parse_timestamp(audit.get("valid_until"), "valid_until")
        return (validated <= clock + FUTURE_CLOCK_TOLERANCE
                and validated <= expiry <= validated + timedelta(hours=2)
                and clock < expiry
                and all(clock < parse_timestamp(row["valid_until"], "evidence expiry") for row in current))
    except (SourceObservationError, TypeError, KeyError):
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
