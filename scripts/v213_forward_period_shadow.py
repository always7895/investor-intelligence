#!/usr/bin/env python3
"""T2 caller-declared forward-period semantics ONLY — bounded stdlib-only shadow module.

Import-inert: no CLI, files, network, process, current-clock, env, or model access.
Parses caller-declared forward-period declarations and returns a frozen, non-authoritative
representation. Does NOT compute quantities, growth, scores, or admission.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Tuple

_DECL_INVALID = "FORWARD_PERIOD_DECLARATION_INVALID"
_NOT_FORWARD = "FORWARD_PERIOD_NOT_FORWARD"

_EVIDENCE_KINDS = frozenset({
    "CALLER_CLAIMED_COMMITMENT",
    "CALLER_CLAIMED_MANAGEMENT_GUIDANCE",
    "CALLER_ANALYTICAL_INFERENCE",
})

_REQUIRED_KEYS = frozenset({
    "information_cutoff",
    "period_start",
    "period_end",
    "declared_evidence_kind",
})

_PERIOD_SCOPE = "DECLARED_TOTAL_PERIOD"
_ROLE_FUTURE_START = "FUTURE_START_TOTAL"
_ROLE_STRADDLING = "STRADDLING_TOTAL"

_LIMIT_STRADDLING_NOT_REMAINDER = "STRADDLING_TOTAL_NOT_FUTURE_REMAINDER"
_LIMIT_FUTURE_NOT_REALIZATION = "FUTURE_PERIOD_NOT_REALIZATION_PROOF"
_LIMIT_NOT_ADMITTED = "CALLER_DECLARATION_NOT_ADMITTED"
_LIMIT_NO_QUANTITY = "NO_QUANTITY_OR_GROWTH_COMPUTED"

_TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


class ForwardPeriodError(ValueError):
    """Fixed non-data-echoing error for forward-period declaration parsing."""


def _decl_invalid() -> ForwardPeriodError:
    return ForwardPeriodError(_DECL_INVALID)


def _not_forward() -> ForwardPeriodError:
    return ForwardPeriodError(_NOT_FORWARD)


def _validate_str(value: Any) -> str:
    if type(value) is not str:
        raise _decl_invalid()
    return value


def _validate_timestamp(value: str) -> datetime:
    if len(value) != 20:
        raise _decl_invalid()
    if not _TS_RE.fullmatch(value):
        raise _decl_invalid()
    try:
        return datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError:
        raise _decl_invalid() from None


_MAX_EVIDENCE_KIND_LEN = max(map(len, _EVIDENCE_KINDS))


def _validate_evidence_kind(value: str) -> str:
    if len(value) > _MAX_EVIDENCE_KIND_LEN:
        raise _decl_invalid()
    if value not in _EVIDENCE_KINDS:
        raise _decl_invalid()
    return value


def _compute_time_role(cutoff: datetime, start: datetime, end: datetime) -> str:
    if end <= cutoff:
        raise _not_forward()
    if start >= cutoff:
        return _ROLE_FUTURE_START
    return _ROLE_STRADDLING


def _compute_limitations(time_role: str) -> Tuple[str, ...]:
    if time_role == _ROLE_STRADDLING:
        return (
            _LIMIT_STRADDLING_NOT_REMAINDER,
            _LIMIT_NOT_ADMITTED,
            _LIMIT_NO_QUANTITY,
        )
    return (
        _LIMIT_FUTURE_NOT_REALIZATION,
        _LIMIT_NOT_ADMITTED,
        _LIMIT_NO_QUANTITY,
    )


@dataclass(frozen=True, slots=True)
class ForwardPeriodDeclaration:
    information_cutoff: str
    period_start: str
    period_end: str
    declared_evidence_kind: str
    time_role: str
    period_scope: str
    limitations: Tuple[str, ...]
    independently_verified: bool = field(init=False, default=False)
    comparability_qualified: bool = field(init=False, default=False)
    scoring_eligible: bool = field(init=False, default=False)
    publication_eligible: bool = field(init=False, default=False)
    consumer_admission: bool = field(init=False, default=False)

    def to_dict(self) -> dict:
        return {
            "information_cutoff": self.information_cutoff,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "declared_evidence_kind": self.declared_evidence_kind,
            "time_role": self.time_role,
            "period_scope": self.period_scope,
            "limitations": list(self.limitations),
            "independently_verified": self.independently_verified,
            "comparability_qualified": self.comparability_qualified,
            "scoring_eligible": self.scoring_eligible,
            "publication_eligible": self.publication_eligible,
            "consumer_admission": self.consumer_admission,
        }


def parse_forward_period_declaration(raw: object) -> ForwardPeriodDeclaration:
    if type(raw) is not dict:
        raise _decl_invalid()
    if len(raw) != 4:
        raise _decl_invalid()
    for key in raw.keys():
        if type(key) is not str:
            raise _decl_invalid()
    if set(raw.keys()) != _REQUIRED_KEYS:
        raise _decl_invalid()
    cutoff_str = _validate_str(raw["information_cutoff"])
    start_str = _validate_str(raw["period_start"])
    end_str = _validate_str(raw["period_end"])
    kind_str = _validate_str(raw["declared_evidence_kind"])
    cutoff = _validate_timestamp(cutoff_str)
    start = _validate_timestamp(start_str)
    end = _validate_timestamp(end_str)
    _validate_evidence_kind(kind_str)
    if start >= end:
        raise _decl_invalid()
    time_role = _compute_time_role(cutoff, start, end)
    limitations = _compute_limitations(time_role)
    return ForwardPeriodDeclaration(
        information_cutoff=cutoff_str,
        period_start=start_str,
        period_end=end_str,
        declared_evidence_kind=kind_str,
        time_role=time_role,
        period_scope=_PERIOD_SCOPE,
        limitations=limitations,
    )