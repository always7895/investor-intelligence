#!/usr/bin/env python3
"""Caller-declaration diagnostics only; no economic equivalence or admission.

Import-inert apart from stdlib and the accepted T2 declaration module. No CLI,
I/O, clock, environment, quantities, conversions, scoring or consumer integration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re

if __package__:
    from .v213_forward_period_shadow import ForwardPeriodError, parse_forward_period_declaration
else:
    from v213_forward_period_shadow import ForwardPeriodError, parse_forward_period_declaration

_AXES = (
    "company_id", "security_id", "venue", "economic_scope", "metric_definition",
    "measure_form", "unit_scale", "currency_basis", "accounting_basis",
    "share_basis", "dilution_basis", "period_alignment",
)
_UNRESOLVED = (
    "IDENTITY_ASSOCIATION", "METRIC_UNIT_CURRENCY_ACCOUNTING",
    "PERIOD_ALIGNMENT_BASELINE_VINTAGE", "SHARE_COUNT_DILUTION",
    "FRESHNESS_LINEAGE_RIGHTS_COUNTEREVIDENCE", "CONSUMER_ADMISSION",
)
_LIMITS = (
    "SAME_DECLARATION_NOT_SEMANTIC_EQUIVALENCE",
    "DIFFERENT_DECLARATION_NOT_PROVEN_INCOMPATIBILITY",
    "CALLER_DECLARATIONS_NOT_ADMITTED", "NO_QUANTITY_GROWTH_CONVERSION_OR_SCORE",
)
_BASELINE_KIND = "CALLER_CLAIMED_REPORTED_ACTUAL"
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}")


class ForwardComparisonError(ValueError):
    """Fixed non-data-echoing declaration error."""


def _invalid() -> ForwardComparisonError:
    return ForwardComparisonError("FORWARD_COMPARISON_INVALID")


def _mapping(value: object, keys: tuple[str, ...]) -> dict:
    if type(value) is not dict or len(value) != len(keys):
        raise _invalid()
    if any(type(key) is not str for key in value):
        raise _invalid()
    if set(value) != set(keys):
        raise _invalid()
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str or len(value) != 20 or not _TIMESTAMP.fullmatch(value):
        raise _invalid()
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise _invalid() from None
    return value


def _descriptors(value: object) -> dict:
    mapping = _mapping(value, _AXES)
    for axis in _AXES:
        declaration = mapping[axis]
        if declaration is None:
            continue
        if type(declaration) is not str or not 1 <= len(declaration) <= 128:
            raise _invalid()
        if axis == "measure_form":
            if declaration not in ("AGGREGATE_FLOW", "PER_SHARE_FLOW"):
                raise _invalid()
        elif not _TOKEN.fullmatch(declaration):
            raise _invalid()
    return mapping


@dataclass(frozen=True, slots=True)
class ForwardComparisonDiagnostic:
    baseline_period_start: str
    baseline_period_end: str
    baseline_declared_evidence_kind: str
    information_cutoff: str
    forward_period_start: str
    forward_period_end: str
    forward_declared_evidence_kind: str
    forward_time_role: str
    descriptor_relations: tuple[tuple[str, str], ...]
    declared_interval_relation: str
    scope: str = field(init=False, default="CALLER_DECLARATION_DIAGNOSTIC_ONLY")
    qualification: str = field(init=False, default="UNQUALIFIED")
    independently_verified: bool = field(init=False, default=False)
    comparability_qualified: bool = field(init=False, default=False)
    scoring_eligible: bool = field(init=False, default=False)
    publication_eligible: bool = field(init=False, default=False)
    consumer_admission: bool = field(init=False, default=False)
    unresolved_premises: tuple[str, ...] = field(init=False, default=_UNRESOLVED)

    @property
    def limitations(self) -> tuple[str, ...]:
        role_limit = (
            "STRADDLING_TOTAL_NOT_FUTURE_REMAINDER"
            if self.forward_time_role == "STRADDLING_TOTAL"
            else "FUTURE_PERIOD_NOT_REALIZATION_PROOF"
        )
        overlap_limit = (
            ("OVERLAP_NOT_INDEPENDENT_GROWTH_PERIODS",)
            if self.declared_interval_relation == "OVERLAPPING_TOTALS" else ()
        )
        return _LIMITS + (role_limit,) + overlap_limit

    def to_dict(self) -> dict:
        return {
            "baseline_period_start": self.baseline_period_start,
            "baseline_period_end": self.baseline_period_end,
            "baseline_declared_evidence_kind": self.baseline_declared_evidence_kind,
            "information_cutoff": self.information_cutoff,
            "forward_period_start": self.forward_period_start,
            "forward_period_end": self.forward_period_end,
            "forward_declared_evidence_kind": self.forward_declared_evidence_kind,
            "forward_time_role": self.forward_time_role,
            "descriptor_relations": dict(self.descriptor_relations),
            "declared_interval_relation": self.declared_interval_relation,
            "scope": self.scope,
            "qualification": self.qualification,
            "independently_verified": self.independently_verified,
            "comparability_qualified": self.comparability_qualified,
            "scoring_eligible": self.scoring_eligible,
            "publication_eligible": self.publication_eligible,
            "consumer_admission": self.consumer_admission,
            "unresolved_premises": list(self.unresolved_premises),
            "limitations": list(self.limitations),
        }


def diagnose_forward_comparison(raw: object) -> ForwardComparisonDiagnostic:
    """Diagnose one caller pair; even identical declarations stay UNQUALIFIED."""
    top = _mapping(raw, ("baseline", "forward"))
    baseline = _mapping(top["baseline"], (
        "period_start", "period_end", "declared_evidence_kind", "descriptors",
    ))
    forward = _mapping(top["forward"], ("period", "descriptors"))
    kind = baseline["declared_evidence_kind"]
    if type(kind) is not str or kind != _BASELINE_KIND:
        raise _invalid()
    start = _timestamp(baseline["period_start"])
    end = _timestamp(baseline["period_end"])
    if start >= end:
        raise _invalid()
    left = _descriptors(baseline["descriptors"])
    right = _descriptors(forward["descriptors"])
    try:
        period = parse_forward_period_declaration(forward["period"])
    except ForwardPeriodError:
        raise _invalid() from None
    if end > period.information_cutoff:
        raise ForwardComparisonError("BASELINE_PERIOD_NOT_HISTORICAL")
    relations = tuple(
        (axis, "UNSPECIFIED" if left[axis] is None or right[axis] is None
         else "SAME_DECLARATION" if left[axis] == right[axis]
         else "DIFFERENT_DECLARATION")
        for axis in _AXES
    )
    overlap = start < period.period_end and period.period_start < end
    return ForwardComparisonDiagnostic(
        baseline_period_start=start, baseline_period_end=end,
        baseline_declared_evidence_kind=kind,
        information_cutoff=period.information_cutoff,
        forward_period_start=period.period_start,
        forward_period_end=period.period_end,
        forward_declared_evidence_kind=period.declared_evidence_kind,
        forward_time_role=period.time_role,
        descriptor_relations=relations,
        declared_interval_relation="OVERLAPPING_TOTALS" if overlap else "NONOVERLAPPING_TOTALS",
    )
