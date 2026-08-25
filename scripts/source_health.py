#!/usr/bin/env python3
"""Deterministic source-health and circuit-breaker state machine.

Source failures never become zero-value observations and never trigger a lower-
trust or paid fallback. The last known good observation remains separate from
health state. Error details are reduced to stable codes before persistence.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
CIRCUIT_OPEN = "CIRCUIT_OPEN"
QUARANTINED = "QUARANTINED"
HALF_OPEN = "HALF_OPEN"
ERROR_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{2,64}$")


class SourceHealthError(ValueError):
    """Invalid health transition or configuration."""


@dataclass(frozen=True)
class HealthPolicy:
    degraded_after_failures: int = 1
    circuit_open_after_failures: int = 3
    base_backoff_seconds: int = 60
    maximum_backoff_seconds: int = 6 * 3600
    quarantine_after_schema_failures: int = 3

    def validate(self) -> None:
        if self.degraded_after_failures < 1:
            raise SourceHealthError("degraded_after_failures must be at least 1")
        if self.circuit_open_after_failures < self.degraded_after_failures:
            raise SourceHealthError(
                "circuit_open_after_failures must be >= degraded_after_failures"
            )
        if self.base_backoff_seconds < 1:
            raise SourceHealthError("base_backoff_seconds must be positive")
        if self.maximum_backoff_seconds < self.base_backoff_seconds:
            raise SourceHealthError(
                "maximum_backoff_seconds must be >= base_backoff_seconds"
            )
        if self.quarantine_after_schema_failures < 1:
            raise SourceHealthError(
                "quarantine_after_schema_failures must be at least 1"
            )


@dataclass(frozen=True)
class SourceHealthState:
    schema_version: int
    source_id: str
    status: str
    consecutive_failures: int
    consecutive_schema_failures: int
    total_successes: int
    total_failures: int
    last_success_at: str | None
    last_failure_at: str | None
    last_error_code: str | None
    next_probe_at: str | None
    updated_at: str

    @staticmethod
    def initial(source_id: str, now: datetime | None = None) -> "SourceHealthState":
        current = _utc(now)
        return SourceHealthState(
            schema_version=1,
            source_id=_source_id(source_id),
            status=HEALTHY,
            consecutive_failures=0,
            consecutive_schema_failures=0,
            total_successes=0,
            total_failures=0,
            last_success_at=None,
            last_failure_at=None,
            last_error_code=None,
            next_probe_at=None,
            updated_at=current.isoformat(),
        )

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def _utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise SourceHealthError("health timestamps must be timezone-aware")
    return result.astimezone(timezone.utc)


def _source_id(value: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise SourceHealthError("source_id is required")
    return result


def _error_code(value: str) -> str:
    result = str(value or "").strip().upper().replace("-", "_")
    if not ERROR_CODE_PATTERN.fullmatch(result):
        raise SourceHealthError(
            "error_code must contain only uppercase letters, digits and underscores"
        )
    return result


def _backoff(policy: HealthPolicy, consecutive_failures: int) -> int:
    exponent = max(0, consecutive_failures - policy.circuit_open_after_failures)
    return min(
        policy.maximum_backoff_seconds,
        policy.base_backoff_seconds * (2**exponent),
    )


def record_success(
    state: SourceHealthState,
    *,
    now: datetime | None = None,
) -> SourceHealthState:
    current = _utc(now)
    return SourceHealthState(
        schema_version=1,
        source_id=state.source_id,
        status=HEALTHY,
        consecutive_failures=0,
        consecutive_schema_failures=0,
        total_successes=state.total_successes + 1,
        total_failures=state.total_failures,
        last_success_at=current.isoformat(),
        last_failure_at=state.last_failure_at,
        last_error_code=None,
        next_probe_at=None,
        updated_at=current.isoformat(),
    )


def record_failure(
    state: SourceHealthState,
    *,
    error_code: str,
    schema_failure: bool = False,
    now: datetime | None = None,
    policy: HealthPolicy = HealthPolicy(),
) -> SourceHealthState:
    policy.validate()
    current = _utc(now)
    failures = state.consecutive_failures + 1
    schema_failures = state.consecutive_schema_failures + (1 if schema_failure else 0)
    code = _error_code(error_code)

    if schema_failures >= policy.quarantine_after_schema_failures:
        status = QUARANTINED
        next_probe_at = None
    elif failures >= policy.circuit_open_after_failures:
        status = CIRCUIT_OPEN
        next_probe_at = (
            current + timedelta(seconds=_backoff(policy, failures))
        ).isoformat()
    elif failures >= policy.degraded_after_failures:
        status = DEGRADED
        next_probe_at = None
    else:
        status = HEALTHY
        next_probe_at = None

    return SourceHealthState(
        schema_version=1,
        source_id=state.source_id,
        status=status,
        consecutive_failures=failures,
        consecutive_schema_failures=schema_failures,
        total_successes=state.total_successes,
        total_failures=state.total_failures + 1,
        last_success_at=state.last_success_at,
        last_failure_at=current.isoformat(),
        last_error_code=code,
        next_probe_at=next_probe_at,
        updated_at=current.isoformat(),
    )


def probe_allowed(
    state: SourceHealthState,
    *,
    now: datetime | None = None,
) -> bool:
    if state.status == QUARANTINED:
        return False
    if state.status != CIRCUIT_OPEN:
        return True
    if not state.next_probe_at:
        return False
    current = _utc(now)
    next_probe = datetime.fromisoformat(state.next_probe_at).astimezone(timezone.utc)
    return current >= next_probe


def half_open_for_probe(
    state: SourceHealthState,
    *,
    now: datetime | None = None,
) -> SourceHealthState:
    current = _utc(now)
    if not probe_allowed(state, now=current):
        raise SourceHealthError("Circuit probe is not yet allowed")
    if state.status not in {CIRCUIT_OPEN, DEGRADED, HEALTHY}:
        raise SourceHealthError(f"Cannot enter HALF_OPEN from {state.status}")
    return SourceHealthState(
        **{
            **state.as_json(),
            "status": HALF_OPEN,
            "next_probe_at": None,
            "updated_at": current.isoformat(),
        }
    )


def manual_quarantine(
    state: SourceHealthState,
    *,
    error_code: str = "MANUAL_QUARANTINE",
    now: datetime | None = None,
) -> SourceHealthState:
    current = _utc(now)
    return SourceHealthState(
        **{
            **state.as_json(),
            "status": QUARANTINED,
            "last_error_code": _error_code(error_code),
            "next_probe_at": None,
            "updated_at": current.isoformat(),
        }
    )


def atomic_write_state(path: Path, state: SourceHealthState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state.as_json(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_state(path: Path, *, expected_source_id: str | None = None) -> SourceHealthState:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SourceHealthError("Health state must be a JSON object")
    state = SourceHealthState(**document)
    if expected_source_id and state.source_id != expected_source_id:
        raise SourceHealthError("Health state source_id mismatch")
    if state.status not in {HEALTHY, DEGRADED, CIRCUIT_OPEN, QUARANTINED, HALF_OPEN}:
        raise SourceHealthError(f"Unsupported stored status: {state.status}")
    return state
