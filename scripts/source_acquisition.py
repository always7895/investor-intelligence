#!/usr/bin/env python3
"""Process-local public source acquisition run and provenance binding.

AcquisitionRun is an in-process factory-created capability. It admits only
reviewed adapters, registered endpoints and valid normalized observations.
No network requests are issued for non-runtime, payment, or unapproved sources.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from adapters import (
    ADAPTERS,
    AdapterError,
    ParsedBatch,
    adapter,
    parse_source_payload,
)
from adapters.base import canonical_json, schema_fingerprint, utc_iso
from fetch_public_source_observations import (
    ENDPOINTS,
    MAX_BYTES,
    diagnose_transport_exception,
    fetch_bytes,
)
from source_health import (
    CIRCUIT_OPEN,
    DEGRADED,
    ERROR_CODE_PATTERN,
    HALF_OPEN,
    HEALTHY,
    QUARANTINED,
    SourceHealthState,
    probe_allowed,
    record_failure,
    record_success,
)
from source_observation import (
    SourceObservationError,
    _hostname_allowed,
    normalize_observation,
    utc_now,
)
from source_registry import Registry, SourceDefinition, canonicalize_url, load_registry

_SENTINEL = object()
MAX_RECORDS_PER_SOURCE = 100
MAX_RUN_LIFETIME = timedelta(minutes=15)
MAX_RUN_BUDGET_SECONDS = 15.0 * 60.0  # 900.0s run budget
VALID_HEALTH_STATUSES = {HEALTHY, DEGRADED, CIRCUIT_OPEN, QUARANTINED, HALF_OPEN}


def safe_canonical_json(value: Any) -> str | None:
    """Safely serialize value to canonical JSON; returns None on hostile or non-finite values."""
    try:
        return canonical_json(value)
    except Exception:
        return None


def compute_registry_digest(registry: Registry) -> str:
    summary_data = {
        "schema_version": registry.schema_version,
        "sources": [
            (
                s.source_id,
                s.display_name,
                s.authority_class,
                s.trust_tier,
                s.evidence_roles,
                s.jurisdictions,
                s.languages,
                s.canonical_urls,
                s.independence_group,
                s.admission_status,
                s.adapter_id,
                s.adapter_status,
                s.runtime_enabled,
                s.free_access_required,
                s.payment_required,
                s.terms_review_status,
                s.priority,
                s.per_host_concurrency,
                s.minimum_request_interval_seconds,
                s.maximum_retries,
                s.freshness_seconds,
                s.correction_tracking,
                s.provenance_required,
            )
            for s in registry.sources
        ],
    }
    encoded = json.dumps(summary_data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _check_source_eligibility(source: SourceDefinition) -> str | None:
    if not source.runtime_enabled:
        return "NOT_RUNTIME_ENABLED"
    if source.admission_status != "RUNTIME_ENABLED":
        return "ADMISSION_NOT_RUNTIME_ENABLED"
    if source.adapter_status != "implemented":
        return "ADAPTER_NOT_IMPLEMENTED"
    if source.terms_review_status != "approved":
        return "TERMS_NOT_APPROVED"
    if not source.free_access_required:
        return "FREE_ACCESS_NOT_REQUIRED"
    if source.payment_required:
        return "PAYMENT_REQUIRED"
    if not source.provenance_required:
        return "PROVENANCE_NOT_REQUIRED"
    if source.trust_tier == "T4_QUARANTINED":
        return "QUARANTINED_TIER"
    if source.source_id not in ENDPOINTS:
        return "NO_REGISTERED_ENDPOINT"
    endpoint = ENDPOINTS[source.source_id]
    try:
        clean_url = canonicalize_url(endpoint)
    except Exception:
        return "ENDPOINT_INVALID_URL"
    if not _hostname_allowed(source, clean_url):
        return "ENDPOINT_DOMAIN_DISALLOWED"
    try:
        ad = adapter(source.source_id)
    except Exception:
        return "UNREGISTERED_ADAPTER"
    ad_adapter_id = getattr(ad, "adapter_id", ad.source_id)
    if ad_adapter_id != source.adapter_id:
        return "ADAPTER_ID_MISMATCH"
    if ad.source_id != source.source_id:
        return "ADAPTER_SOURCE_ID_MISMATCH"
    return None


class AcquisitionRun:
    """Process-local record of executed acquisition; factory-only construction."""

    def __init__(
        self,
        *,
        _sentinel: Any = None,
        registry: Registry,
        run_id: str,
        started_at: datetime,
        completed_at: datetime,
        registry_sha256: str,
        candidates: list[dict[str, Any]],
        verified_hashes: dict[str, set[str]],
        successful_sources: set[str],
        health_states: dict[str, SourceHealthState],
        skipped_counts: dict[str, int],
        skipped_sources: dict[str, str],
        source_failures: dict[str, str],
        attempted_sources: list[str],
        source_body_hashes: dict[str, str],
        source_schema_hashes: dict[str, str],
        source_parser_versions: dict[str, str],
        source_record_counts: dict[str, int],
        source_parsed_hashes: dict[str, list[str]],
        is_synthetic: bool = False,
        synthetic_clock: bool = False,
    ) -> None:
        if _sentinel is not _SENTINEL:
            raise TypeError(
                "AcquisitionRun cannot be constructed directly; use acquire_runtime_sources"
            )
        self._registry = registry
        self._run_id = run_id
        self._started_at = started_at
        self._completed_at = completed_at
        self._registry_sha256 = registry_sha256
        self._candidates = candidates
        self._verified_hashes = verified_hashes
        self._successful_sources = successful_sources
        self._health_states = health_states
        self._skipped_counts = skipped_counts
        self._skipped_sources = skipped_sources
        self._source_failures = source_failures
        self._attempted_sources = attempted_sources
        self._source_body_hashes = source_body_hashes
        self._source_schema_hashes = source_schema_hashes
        self._source_parser_versions = source_parser_versions
        self._source_record_counts = source_record_counts
        self._source_parsed_hashes = source_parsed_hashes
        self._is_synthetic = is_synthetic
        self._synthetic_clock = synthetic_clock

    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def health_states(self) -> dict[str, SourceHealthState]:
        return dict(self._health_states)

    def candidates_for(self, subject: str) -> list[dict[str, Any]]:
        target = str(subject or "").strip()
        return [
            copy.deepcopy(cand)
            for cand in self._candidates
            if str(cand.get("payload", {}).get("subject") or "").strip() == target
        ]

    def _fallback_health(self, raw: Any, source_id: str | None) -> str:
        prior_status = None
        if source_id and source_id in self._health_states:
            prior_status = self._health_states[source_id].status
        raw_status = None
        if isinstance(raw, Mapping):
            try:
                raw_status = raw.get("source_health")
            except Exception:
                raw_status = None
        for st in (QUARANTINED, CIRCUIT_OPEN):
            if prior_status == st or raw_status == st:
                return st
        return DEGRADED

    def health_for(self, raw: Any, *, now: datetime | None = None) -> str:
        if not isinstance(raw, Mapping):
            return self._fallback_health(raw, None)
        source_id = raw.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            return self._fallback_health(raw, None)

        # Cross-run UUID binding check
        raw_run_id = raw.get("acquisition_run_id")
        if not isinstance(raw_run_id, str) or raw_run_id != self._run_id:
            return self._fallback_health(raw, source_id)

        # Freshness check: only CURRENT freshness is healthy
        if raw.get("freshness_status") != "CURRENT":
            return self._fallback_health(raw, source_id)

        if source_id not in self._successful_sources:
            return self._fallback_health(raw, source_id)
        if compute_registry_digest(self._registry) != self._registry_sha256:
            return self._fallback_health(raw, source_id)

        clock = now if now is not None else utc_now()
        if not isinstance(clock, datetime) or clock.tzinfo is None:
            return self._fallback_health(raw, source_id)
        current = clock.astimezone(timezone.utc)

        if (self._completed_at - self._started_at) > MAX_RUN_LIFETIME:
            return self._fallback_health(raw, source_id)
        if self._completed_at < self._started_at:
            return self._fallback_health(raw, source_id)
        if current < self._completed_at:
            return self._fallback_health(raw, source_id)
        if current > self._started_at + MAX_RUN_LIFETIME:
            return self._fallback_health(raw, source_id)

        raw_canonical = safe_canonical_json(raw)
        if raw_canonical is None:
            return self._fallback_health(raw, source_id)
        raw_hash = hashlib.sha256(raw_canonical.encode("utf-8")).hexdigest()

        if raw_hash not in self._verified_hashes.get(source_id, set()):
            return self._fallback_health(raw, source_id)

        state = self._health_states.get(source_id)
        if state is None or state.status != HEALTHY:
            return self._fallback_health(raw, source_id)
        # No self-initial healthy proof: must have at least one verified success
        if (
            type(state.total_successes) is not int
            or isinstance(state.total_successes, bool)
            or state.total_successes <= 0
        ):
            return self._fallback_health(raw, source_id)

        return HEALTHY

    def summary(self) -> dict[str, Any]:
        transport_mode = (
            "INJECTED_TEST_TRANSPORT"
            if self._is_synthetic
            else "SYSTEM_PLUS_CERTIFI"
        )
        return copy.deepcopy(
            {
                "schema_version": 1,
                "run_id": self._run_id,
                "status": "ACQUIRED" if self._candidates else "UNAVAILABLE",
                "transport_mode": transport_mode,
                "release_qualified": False,
                "live_proof": False,
                "synthetic": self._is_synthetic,
                "synthetic_clock": self._synthetic_clock,
                "started_at": self._started_at.isoformat(),
                "completed_at": self._completed_at.isoformat(),
                "registry_sha256": self._registry_sha256,
                "candidate_count": len(self._candidates),
                "successful_source_count": len(self._successful_sources),
                "skipped_source_counts": dict(self._skipped_counts),
                "skipped_sources": dict(self._skipped_sources),
                "source_diagnostics": {
                    s_id: {
                        "status": "SUCCESS" if s_id in self._successful_sources else "FAILED",
                        "failure_code": self._source_failures.get(s_id),
                        "content_sha256": self._source_body_hashes.get(s_id),
                        "schema_sha256": self._source_schema_hashes.get(s_id),
                        "parser_version": self._source_parser_versions.get(s_id),
                        "record_count": self._source_record_counts.get(s_id, 0),
                        "parsed_record_hashes": list(self._source_parsed_hashes.get(s_id, [])),
                        "record_hashes": list(self._source_parsed_hashes.get(s_id, [])),
                        "normalized_hashes": sorted(self._verified_hashes.get(s_id, set())),
                    }
                    for s_id in self._attempted_sources
                },
            }
        )


def _safe_clock(fn: Callable[[], datetime], last_time: datetime | None = None) -> datetime:
    t = fn()
    if not isinstance(t, datetime):
        raise TypeError("Clock callable must return a datetime instance")
    if t.tzinfo is None:
        raise ValueError("Clock datetime must be timezone-aware")
    t_utc = t.astimezone(timezone.utc)
    if last_time is not None and t_utc < last_time:
        raise ValueError(f"Clock retreated backwards: {t_utc.isoformat()} < {last_time.isoformat()}")
    return t_utc


def acquire_runtime_sources(
    *,
    registry: Registry | None = None,
    transport: Callable[[str], bytes] | None = None,
    prior_states: Mapping[str, SourceHealthState] | None = None,
    clock: datetime | Callable[[], datetime] | None = None,
) -> AcquisitionRun:
    """Acquire and validate public observations for runtime-eligible sources."""
    # Clock type validation
    if clock is not None and not isinstance(clock, datetime) and not callable(clock):
        raise TypeError("clock must be a datetime, callable, or None")
    if isinstance(clock, datetime) and clock.tzinfo is None:
        raise ValueError("clock must be timezone-aware")

    # Prior states validation BEFORE any transport (generic stable codes)
    working_states: dict[str, SourceHealthState] = {}
    if prior_states is not None:
        if not isinstance(prior_states, Mapping):
            raise TypeError("PRIOR_STATES_INVALID_MAPPING")
        for k, v in prior_states.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError("PRIOR_STATE_KEY_INVALID")
            if not isinstance(v, SourceHealthState):
                raise TypeError("PRIOR_STATE_VALUE_INVALID")
            if v.source_id != k:
                raise ValueError("PRIOR_STATE_SOURCE_ID_MISMATCH")
            if v.status not in VALID_HEALTH_STATUSES:
                raise ValueError("PRIOR_STATE_STATUS_INVALID")
            if type(v.total_successes) is not int or isinstance(v.total_successes, bool) or v.total_successes < 0:
                raise ValueError("PRIOR_STATE_TOTAL_SUCCESSES_INVALID")
            if type(v.total_failures) is not int or isinstance(v.total_failures, bool) or v.total_failures < 0:
                raise ValueError("PRIOR_STATE_TOTAL_FAILURES_INVALID")
            if type(v.consecutive_failures) is not int or isinstance(v.consecutive_failures, bool) or v.consecutive_failures < 0:
                raise ValueError("PRIOR_STATE_CONSECUTIVE_FAILURES_INVALID")
            if type(v.consecutive_schema_failures) is not int or isinstance(v.consecutive_schema_failures, bool) or v.consecutive_schema_failures < 0:
                raise ValueError("PRIOR_STATE_CONSECUTIVE_SCHEMA_FAILURES_INVALID")

            for ts_field in ("updated_at", "last_success_at", "last_failure_at", "next_probe_at"):
                ts_val = getattr(v, ts_field, None)
                if ts_val is not None:
                    if not isinstance(ts_val, str):
                        raise ValueError("PRIOR_STATE_TIMESTAMP_INVALID")
                    try:
                        ts_clean = ts_val.replace("Z", "+00:00") if ts_val.endswith("Z") else ts_val
                        dt_parsed = datetime.fromisoformat(ts_clean)
                    except Exception:
                        raise ValueError("PRIOR_STATE_TIMESTAMP_INVALID")
                    if dt_parsed.tzinfo is None:
                        raise ValueError("PRIOR_STATE_TIMEZONE_REQUIRED")

            working_states[k] = v

    is_synthetic = transport is not None and transport is not fetch_bytes
    synthetic_clock = clock is not None

    if clock is None:
        clock_fn: Callable[[], datetime] = utc_now
    elif callable(clock):
        clock_fn = clock
    elif isinstance(clock, datetime):
        if not is_synthetic:
            raise ValueError(
                "Fixed datetime clock is allowed only with injected synthetic transport"
            )
        fixed_dt = clock.astimezone(timezone.utc)
        clock_fn = lambda: fixed_dt

    started_at = _safe_clock(clock_fn)
    current_time = started_at

    reg = registry if registry is not None else load_registry()
    trans = transport if transport is not None else fetch_bytes

    run_id = str(uuid.uuid4())
    reg_sha256 = compute_registry_digest(reg)

    run_start_mono = time.monotonic()
    run_deadline_mono = run_start_mono + MAX_RUN_BUDGET_SECONDS
    host_last_request: dict[str, tuple[float, float]] = {}

    skipped_counts: dict[str, int] = {}
    skipped_sources: dict[str, str] = {}
    source_failures: dict[str, str] = {}
    attempted_sources: list[str] = []
    successful_sources: set[str] = set()
    verified_hashes: dict[str, set[str]] = {}
    all_candidates: list[dict[str, Any]] = []

    source_body_hashes: dict[str, str] = {}
    source_schema_hashes: dict[str, str] = {}
    source_parser_versions: dict[str, str] = {}
    source_record_counts: dict[str, int] = {}
    source_parsed_hashes: dict[str, list[str]] = {}

    for source in reg.sources:
        eligibility_failure = _check_source_eligibility(source)
        if eligibility_failure is not None:
            skipped_sources[source.source_id] = eligibility_failure
            skipped_counts[eligibility_failure] = skipped_counts.get(eligibility_failure, 0) + 1
            continue

        health_state = working_states.get(source.source_id)
        if health_state is None:
            health_state = SourceHealthState.initial(source.source_id, now=current_time)
            working_states[source.source_id] = health_state

        if not probe_allowed(health_state, now=current_time):
            reason = f"PROBE_DISALLOWED_{health_state.status}"
            skipped_sources[source.source_id] = reason
            skipped_counts[reason] = skipped_counts.get(reason, 0) + 1
            continue

        endpoint = ENDPOINTS[source.source_id]
        host = (urlsplit(endpoint).hostname or "").casefold()
        source_interval = float(source.minimum_request_interval_seconds)

        now_mono = time.monotonic()
        sleep_needed = 0.0
        if host in host_last_request:
            last_mono, last_interval = host_last_request[host]
            required_interval = max(last_interval, source_interval)
            elapsed = now_mono - last_mono
            if elapsed < required_interval:
                sleep_needed = required_interval - elapsed

        if (now_mono + sleep_needed) > run_deadline_mono:
            reason = "RUN_BUDGET_EXCEEDED"
            skipped_sources[source.source_id] = reason
            skipped_counts[reason] = skipped_counts.get(reason, 0) + 1
            continue

        if sleep_needed > 0.0:
            time.sleep(sleep_needed)

        attempt_mono = time.monotonic()
        host_last_request[host] = (attempt_mono, source_interval)

        attempted_sources.append(source.source_id)

        # Step 1: Transport
        try:
            raw_bytes = trans(endpoint)
        except Exception as exc:
            diag = diagnose_transport_exception(exc)
            code = diag.failure_code
            if code == "UNKNOWN_ERROR" or not ERROR_CODE_PATTERN.fullmatch(code):
                code = "TRANSPORT_FAILED"
            health_state = record_failure(health_state, error_code=code, now=current_time)
            working_states[source.source_id] = health_state
            source_failures[source.source_id] = code
            continue

        if not isinstance(raw_bytes, bytes) or len(raw_bytes) == 0:
            code = "EMPTY_PAYLOAD"
            health_state = record_failure(health_state, error_code=code, now=current_time)
            working_states[source.source_id] = health_state
            source_failures[source.source_id] = code
            continue

        if len(raw_bytes) > MAX_BYTES:
            code = "PAYLOAD_TOO_LARGE"
            health_state = record_failure(health_state, error_code=code, now=current_time)
            working_states[source.source_id] = health_state
            source_failures[source.source_id] = code
            continue

        # Step 2: Retrieval clock AFTER transport
        current_time = _safe_clock(clock_fn, current_time)
        retrieval_iso = utc_iso(current_time)

        # Step 3: Parser
        content_type = (
            "application/rss+xml"
            if (endpoint.endswith(".rss") or endpoint.endswith(".xml") or "rss" in endpoint)
            else "application/json"
        )
        try:
            batch = parse_source_payload(
                source.source_id,
                raw_bytes,
                content_type=content_type,
                retrieved_at=retrieval_iso,
                context={"request_url": endpoint},
            )
        except Exception as exc:
            diag = diagnose_transport_exception(exc)
            code = diag.failure_code if diag.failure_code != "UNKNOWN_ERROR" else "INVALID_PAYLOAD"
            health_state = record_failure(
                health_state, error_code=code, schema_failure=True, now=current_time
            )
            working_states[source.source_id] = health_state
            source_failures[source.source_id] = code
            continue

        ad = adapter(source.source_id)
        batch_err = None

        # Guard against malformed records BEFORE schema_fingerprint
        try:
            if not isinstance(batch.records, (tuple, list)):
                batch_err = "SCHEMA_VALIDATION_FAILED"
            elif any(type(r) is not dict and not isinstance(r, Mapping) for r in batch.records):
                batch_err = "SCHEMA_VALIDATION_FAILED"
            elif any(safe_canonical_json(r) is None for r in batch.records):
                batch_err = "SCHEMA_VALIDATION_FAILED"
            elif (
                type(batch.record_count) is not int
                or isinstance(batch.record_count, bool)
                or batch.record_count < 0
                or batch.record_count != len(batch.records)
            ):
                batch_err = "RECORD_COUNT_MISMATCH"
            elif batch.source_id != source.source_id:
                batch_err = "BATCH_SOURCE_ID_MISMATCH"
            elif batch.parser_version != ad.parser_version or not batch.parser_version:
                batch_err = "BATCH_PARSER_VERSION_MISMATCH"
            elif batch.content_sha256 != hashlib.sha256(raw_bytes).hexdigest():
                batch_err = "CONTENT_HASH_MISMATCH"
            elif len(batch.records) == 0:
                batch_err = "EMPTY_BATCH_RECORDS"
            elif len(batch.records) > MAX_RECORDS_PER_SOURCE:
                batch_err = "BATCH_OVERFLOW"
            elif bool(batch.warnings):
                batch_err = "BATCH_WARNINGS"
            elif batch.schema_sha256 != schema_fingerprint(batch.records):
                batch_err = "SCHEMA_HASH_MISMATCH"
            elif not isinstance(batch.retrieved_at, str):
                batch_err = "BATCH_RETRIEVAL_TIME_MISMATCH"
            else:
                # Batch retrieved_at must equal exact caller retrieval (normalized ISO)
                try:
                    if utc_iso(batch.retrieved_at) != retrieval_iso:
                        batch_err = "BATCH_RETRIEVAL_TIME_MISMATCH"
                except Exception:
                    batch_err = "BATCH_RETRIEVAL_TIME_MISMATCH"
        except Exception:
            batch_err = "SCHEMA_VALIDATION_FAILED"

        if batch_err is not None:
            health_state = record_failure(
                health_state, error_code=batch_err, schema_failure=True, now=current_time
            )
            working_states[source.source_id] = health_state
            source_failures[source.source_id] = batch_err
            continue

        # Compute parsed record hashes
        parsed_hashes: list[str] = []
        for rec in batch.records:
            rec_can = safe_canonical_json(rec)
            if rec_can is not None:
                parsed_hashes.append(hashlib.sha256(rec_can.encode("utf-8")).hexdigest())

        source_body_hashes[source.source_id] = batch.content_sha256
        source_schema_hashes[source.source_id] = batch.schema_sha256
        source_parser_versions[source.source_id] = batch.parser_version
        source_record_counts[source.source_id] = batch.record_count
        source_parsed_hashes[source.source_id] = parsed_hashes

        candidate_rows: list[dict[str, Any]] = []
        candidate_hashes: list[str] = []
        norm_failed = False
        norm_error_code = "NORMALIZATION_FAILED"

        for record in batch.records:
            candidate_raw = {
                **record,
                "source_id": source.source_id,
                "retrieved_at": batch.retrieved_at,
                "content_sha256": batch.content_sha256,
                "parser_id": source.adapter_id,
                "parser_version": batch.parser_version,
            }
            try:
                obs = normalize_observation(
                    candidate_raw,
                    registry=reg,
                    raw_content=raw_bytes,
                    source_health=HEALTHY,
                    now=current_time,
                    require_runtime_enabled=True,
                )
            except Exception:
                norm_failed = True
                break

            # Freshness status must be CURRENT
            if obs.freshness_status != "CURRENT":
                norm_failed = True
                norm_error_code = (
                    "STALE_OBSERVATION"
                    if obs.freshness_status == "STALE"
                    else obs.freshness_status
                )
                break

            row_dict = obs.as_json()
            # Stamp extra acquisition_run_id into canonical normalized candidates AFTER normalize
            row_dict["acquisition_run_id"] = run_id

            row_canonical = safe_canonical_json(row_dict)
            if row_canonical is None:
                norm_failed = True
                break
            row_hash = hashlib.sha256(row_canonical.encode("utf-8")).hexdigest()
            candidate_rows.append(row_dict)
            candidate_hashes.append(row_hash)

        if norm_failed or not candidate_rows:
            health_state = record_failure(
                health_state,
                error_code=norm_error_code,
                schema_failure=True,
                now=current_time,
            )
            working_states[source.source_id] = health_state
            source_failures[source.source_id] = norm_error_code
            continue

        health_state = record_success(health_state, now=current_time)
        working_states[source.source_id] = health_state
        successful_sources.add(source.source_id)
        verified_hashes[source.source_id] = set(candidate_hashes)
        all_candidates.extend(candidate_rows)

    completed_at = _safe_clock(clock_fn, current_time)

    return AcquisitionRun(
        _sentinel=_SENTINEL,
        registry=reg,
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        registry_sha256=reg_sha256,
        candidates=all_candidates,
        verified_hashes=verified_hashes,
        successful_sources=successful_sources,
        health_states=working_states,
        skipped_counts=skipped_counts,
        skipped_sources=skipped_sources,
        source_failures=source_failures,
        attempted_sources=attempted_sources,
        source_body_hashes=source_body_hashes,
        source_schema_hashes=source_schema_hashes,
        source_parser_versions=source_parser_versions,
        source_record_counts=source_record_counts,
        source_parsed_hashes=source_parsed_hashes,
        is_synthetic=is_synthetic,
        synthetic_clock=synthetic_clock,
    )
