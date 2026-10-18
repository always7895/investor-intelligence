#!/usr/bin/env python3
"""Premise states for one guidance-versus-reported-baseline pair; no admission.

Contract C1 of docs/FORWARD_COMPARISON_PREMISES_V1.md. Pure and import-inert
apart from stdlib, the accepted T3 diagnostic and the SEC binding type. No CLI,
I/O, clock, environment, conversion, ratio, growth, scoring or consumer
integration. Semantic gaps become premise states; malformed input raises a
fixed, non-data-echoing error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import re

if __package__:
    from .adapters.sec_edgar import SecClaimBinding
    from .v213_forward_comparison_shadow import ForwardComparisonDiagnostic
else:
    from adapters.sec_edgar import SecClaimBinding
    from v213_forward_comparison_shadow import ForwardComparisonDiagnostic

PREMISES = (
    "IDENTITY_ASSOCIATION", "METRIC_UNIT_CURRENCY_ACCOUNTING",
    "PERIOD_ALIGNMENT_BASELINE_VINTAGE", "SHARE_COUNT_DILUTION",
    "FRESHNESS_LINEAGE_RIGHTS_COUNTEREVIDENCE", "CONSUMER_ADMISSION",
)
RESOLVED = "RESOLVED"
UNRESOLVED = "UNRESOLVED"
NOT_COMPARABLE = "NOT_COMPARABLE"
NOT_APPLICABLE = "NOT_APPLICABLE_AGGREGATE_METRIC"
DEFERRED = "DEFERRED_TO_CONSUMER_CONTRACT"
_SATISFIED = frozenset({RESOLVED, NOT_APPLICABLE})

# V1 metric family: consolidated GAAP revenue only (aggregate flow).
_METRIC = "revenue"
_REVENUE_TAGS = frozenset({
    "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
})
# Display scale only; values are shown as disclosed and never converted.
_SCALES = frozenset({"USD", "thousand", "million", "billion"})
_FORWARD_KIND = "issuer_guidance_or_contract"
# Half-open day counts. Annual covers 52/53-week fiscal years (364/371) and
# calendar years (365/366); quarters cover 13/14-week and calendar quarters.
_LENGTH_CLASSES = (("ANNUAL", 364, 371), ("QUARTER", 89, 98))
_CLAIM_KEYS = ("claim_id", "claim_type", "subject", "metric", "period",
               "unit", "currency", "basis", "scope")
_INTERVAL = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})/([0-9]{4}-[0-9]{2}-[0-9]{2})")
_LIMITS = (
    "SIDE_BY_SIDE_DISCLOSURE_ONLY", "NO_RATIO_GROWTH_CONVERSION_OR_SCORE",
    "REDISTRIBUTION_RIGHTS_NOT_ASSESSED_LOCAL_ONLY",
    "COMPANYFACTS_CONTEXT_AND_RESTATEMENT_REVIEW_INCOMPLETE",
    "SYMBOL_ALIAS_TRUST_INHERITED_FROM_SEC_BINDING",
)


class ForwardPremisesError(ValueError):
    """Fixed non-data-echoing input error."""


def _invalid() -> ForwardPremisesError:
    return ForwardPremisesError("FORWARD_PREMISES_INVALID")


def _utc(value: object) -> datetime:
    if type(value) is not str:
        raise _invalid()
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise _invalid() from None
    if parsed.tzinfo is None:
        raise _invalid()
    return parsed.astimezone(timezone.utc)


def _day(value: object) -> date | None:
    """SEC dates arrive as YYYY-MM-DD or as a UTC-midnight timestamp (date precision)."""
    if type(value) is not str:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        stamp = _utc(value)
    except (ValueError, ForwardPremisesError):
        return None
    return stamp.date() if stamp.time() == time.min else None


def _midnight(value: str) -> date | None:
    stamp = _utc(value)
    return stamp.date() if stamp.time() == time.min else None


def _length_class(start: date, end_exclusive: date) -> str | None:
    days = (end_exclusive - start).days
    for name, low, high in _LENGTH_CLASSES:
        if low <= days <= high:
            return name
    return None


def _claim(value: object) -> dict:
    if type(value) is not dict or set(value) != set(_CLAIM_KEYS):
        raise _invalid()
    if any(type(value[key]) is not str or not value[key].strip() for key in _CLAIM_KEYS):
        raise _invalid()
    return value


def _assessment(research: object, claim_id: str) -> tuple[dict, list[dict]]:
    if type(research) is not dict or type(research.get("claims")) is not list \
            or type(research.get("evidence")) is not list:
        raise _invalid()
    matches = [row for row in research["claims"] if type(row) is dict and row.get("claim_id") == claim_id]
    if len(matches) != 1:
        raise _invalid()
    result = matches[0]
    ids = result.get("evidence_ids")
    if type(ids) is not list or type(result.get("reasons")) is not list \
            or type(result.get("conflict_set")) is not list:
        raise _invalid()
    rows = [row for row in research["evidence"] if type(row) is dict and row.get("observation_id") in ids]
    return result, rows


def _baseline_record(binding: SecClaimBinding, diagnostic: ForwardComparisonDiagnostic,
                     cutoff: datetime) -> tuple[dict | None, tuple[str, ...], bool]:
    """Select the SEC duration fact matching the declared half-open baseline period.

    Annual and quarterly facts can share an end date, so the declared start and
    end both bind the record. Only facts whose whole (date-only) filing day
    precedes the cutoff count; the latest wins and conflicts are never averaged.
    """
    start = _midnight(diagnostic.baseline_period_start)
    end_exclusive = _midnight(diagnostic.baseline_period_end)
    if start is None or end_exclusive is None:
        return None, ("BASELINE_PERIOD_NOT_DAY_ALIGNED",), False
    bound = [record for record in binding.projected_records
             if _day((record.get("fact_period") or {}).get("start")) == start
             and _day((record.get("fact_period") or {}).get("end")) == end_exclusive - timedelta(days=1)]
    if not bound:
        return None, ("BASELINE_PERIOD_NOT_BOUND_TO_SEC_FACT",), False
    eligible = []
    for record in bound:
        filed = _day(record.get("filing_time"))
        if filed is not None and datetime.combine(filed + timedelta(days=1), time.min, timezone.utc) <= cutoff:
            eligible.append((filed, record))
    if not eligible:
        return None, ("BASELINE_NOT_FILED_BY_CUTOFF",), False
    latest = max(filed for filed, _ in eligible)
    newest = [record for filed, record in eligible if filed == latest]
    if len({repr(record.get("value")) for record in newest}) != 1:
        return None, ("BASELINE_VINTAGE_CONFLICT",), False
    revised = len({repr(record.get("value")) for _, record in eligible}) > 1
    return dict(newest[0]), (), revised


def _identity(binding: SecClaimBinding, claim: dict, relations: dict) -> tuple[str, tuple[str, ...]]:
    reasons = []
    if relations["company_id"] == "DIFFERENT_DECLARATION":
        reasons.append("CALLER_COMPANY_DECLARATIONS_DIFFER")
    if not binding.resolved_symbol:
        reasons.append("BASELINE_SYMBOL_ALIAS_ABSENT")
    elif binding.resolved_symbol.strip().upper() != claim["subject"].strip().upper():
        reasons.append("SUBJECT_NOT_BOUND_TO_BASELINE_CIK")
    return (UNRESOLVED, tuple(reasons)) if reasons else (RESOLVED, ())


def _metric(record: dict | None, claim: dict, result: dict, relations: dict) -> tuple[str, tuple[str, ...]]:
    if record is None:
        return UNRESOLVED, ("BASELINE_RECORD_UNAVAILABLE",)
    reasons = []
    if record.get("taxonomy") != "us-gaap" or record.get("tag") not in _REVENUE_TAGS:
        reasons.append("BASELINE_TAG_NOT_V1_REVENUE")
    if claim["metric"] != _METRIC:
        reasons.append("FORWARD_METRIC_NOT_V1_REVENUE")
    if claim["currency"] != record.get("currency") or record.get("currency") != "USD":
        reasons.append("CURRENCY_DIFFERS")
    if claim["unit"] not in _SCALES:
        reasons.append("FORWARD_UNIT_SCALE_UNKNOWN")
    if claim["basis"] != "GAAP":
        reasons.append("FORWARD_BASIS_NOT_GAAP")
    if claim["scope"] != "consolidated":
        reasons.append("FORWARD_SCOPE_NOT_CONSOLIDATED")
    for axis in ("economic_scope", "metric_definition", "currency_basis", "accounting_basis"):
        if relations[axis] == "DIFFERENT_DECLARATION":
            reasons.append("CALLER_" + axis.upper() + "_DECLARATIONS_DIFFER")
    if "NOT_COMPARABLE" in result["reasons"]:
        reasons.append("CLAIM_ENGINE_NOT_COMPARABLE")
    return (NOT_COMPARABLE, tuple(reasons)) if reasons else (RESOLVED, ())


def _period(diagnostic: ForwardComparisonDiagnostic, binding: SecClaimBinding, record: dict | None,
            record_reasons: tuple[str, ...], claim: dict, cutoff: datetime) -> tuple[str, tuple[str, ...]]:
    reasons = list(record_reasons)
    if diagnostic.forward_time_role != "FUTURE_START_TOTAL":
        reasons.append("FORWARD_ROLE_NOT_FUTURE_START_TOTAL")
    if diagnostic.declared_interval_relation != "NONOVERLAPPING_TOTALS":
        reasons.append("DECLARED_TOTALS_OVERLAP")
    if _utc(binding.receipt.retrieved_at) < cutoff:
        reasons.append("BASELINE_RETRIEVED_BEFORE_CUTOFF")
    baseline_class = forward_class = None
    if record is not None:  # Already bound to the declared baseline period.
        baseline_class = _length_class(_midnight(diagnostic.baseline_period_start),
                                       _midnight(diagnostic.baseline_period_end))
    forward_start = _midnight(diagnostic.forward_period_start)
    forward_end = _midnight(diagnostic.forward_period_end)
    if forward_start is None or forward_end is None:
        reasons.append("FORWARD_PERIOD_NOT_DAY_ALIGNED")
    else:
        forward_class = _length_class(forward_start, forward_end)
        label = _INTERVAL.fullmatch(claim["period"])
        if not label or _day(label[1]) != forward_start \
                or _day(label[2]) != forward_end - timedelta(days=1):
            reasons.append("FORWARD_PERIOD_LABEL_NOT_BOUND")
    if baseline_class is None or forward_class is None:
        reasons.append("PERIOD_LENGTH_UNCLASSIFIED")
    elif baseline_class != forward_class:
        reasons.append("PERIOD_LENGTH_CLASS_DIFFERS")
    return (UNRESOLVED, tuple(dict.fromkeys(reasons))) if reasons else (RESOLVED, ())


def _dilution(record: dict | None, claim: dict, relations: dict) -> tuple[str, tuple[str, ...]]:
    if record is None:
        return UNRESOLVED, ("BASELINE_RECORD_UNAVAILABLE",)
    if record.get("tag") not in _REVENUE_TAGS or claim["metric"] != _METRIC:
        return UNRESOLVED, ("PER_SHARE_OR_UNKNOWN_METRIC_OUT_OF_V1",)
    if relations["measure_form"] == "DIFFERENT_DECLARATION":
        return UNRESOLVED, ("CALLER_MEASURE_FORM_DECLARATIONS_DIFFER",)
    return NOT_APPLICABLE, ()


def _freshness(claim: dict, result: dict, rows: list[dict], cutoff: datetime) -> tuple[str, tuple[str, ...]]:
    reasons = []
    if claim["claim_type"] != _FORWARD_KIND:
        reasons.append("FORWARD_CLAIM_NOT_GUIDANCE_OR_CONTRACT")
    status = result.get("status")
    families = result.get("independent_evidence_families")
    if status != "SUPPORTED":
        reasons.append("FORWARD_STATUS_" + (status if type(status) is str else "INVALID"))
    elif type(families) is not int or families < 2 or result.get("value") is None or result["conflict_set"]:
        reasons.append("FORWARD_INDEPENDENCE_UNPROVEN")
    if not rows or len(rows) != len(result["evidence_ids"]):
        reasons.append("FORWARD_EVIDENCE_LEDGER_INCOMPLETE")
    elif any(_utc(row.get("published_at")) > cutoff for row in rows):
        reasons.append("FORWARD_EVIDENCE_AFTER_CUTOFF")
    return (UNRESOLVED, tuple(reasons)) if reasons else (RESOLVED, ())


@dataclass(frozen=True, slots=True)
class ForwardPremiseAssessment:
    premise_states: tuple[tuple[str, str, tuple[str, ...]], ...]
    comparison_ready: bool
    baseline_view: tuple[tuple[str, object], ...]
    forward_view: tuple[tuple[str, object], ...]
    baseline_revised_within_document: bool
    scope: str = field(init=False, default="PREMISE_STATE_SHADOW_ONLY")
    qualification: str = field(init=False, default="UNQUALIFIED")
    scoring_eligible: bool = field(init=False, default=False)
    publication_eligible: bool = field(init=False, default=False)
    consumer_admission: bool = field(init=False, default=False)

    @property
    def limitations(self) -> tuple[str, ...]:
        revised = ("BASELINE_REVISED_WITHIN_DOCUMENT",) if self.baseline_revised_within_document else ()
        return _LIMITS + revised

    def to_dict(self) -> dict:
        return {
            "premise_states": [
                {"premise": name, "state": state, "reasons": list(reasons)}
                for name, state, reasons in self.premise_states
            ],
            "comparison_ready": self.comparison_ready,
            "baseline_view": dict(self.baseline_view),
            "forward_view": dict(self.forward_view),
            "scope": self.scope,
            "qualification": self.qualification,
            "scoring_eligible": self.scoring_eligible,
            "publication_eligible": self.publication_eligible,
            "consumer_admission": self.consumer_admission,
            "limitations": list(self.limitations),
        }


def assess_forward_premises(diagnostic: object, baseline: object, forward_claim: object,
                            research: object) -> ForwardPremiseAssessment:
    """Map one T3 pair onto admitted inputs; consumer admission stays deferred."""
    if type(diagnostic) is not ForwardComparisonDiagnostic or type(baseline) is not SecClaimBinding:
        raise _invalid()
    if baseline.claim_kind != "issuer_financial_statement" or not baseline.projected_records:
        raise _invalid()
    claim = _claim(forward_claim)
    result, rows = _assessment(research, claim["claim_id"])
    cutoff = _utc(diagnostic.information_cutoff)
    relations = dict(diagnostic.descriptor_relations)
    record, record_reasons, revised = _baseline_record(baseline, diagnostic, cutoff)
    states = (
        ("IDENTITY_ASSOCIATION",) + _identity(baseline, claim, relations),
        ("METRIC_UNIT_CURRENCY_ACCOUNTING",) + _metric(record, claim, result, relations),
        ("PERIOD_ALIGNMENT_BASELINE_VINTAGE",) + _period(diagnostic, baseline, record, record_reasons, claim, cutoff),
        ("SHARE_COUNT_DILUTION",) + _dilution(record, claim, relations),
        ("FRESHNESS_LINEAGE_RIGHTS_COUNTEREVIDENCE",) + _freshness(claim, result, rows, cutoff),
        ("CONSUMER_ADMISSION", DEFERRED, ()),
    )
    ready = all(state in _SATISFIED for name, state, _ in states if name != "CONSUMER_ADMISSION")
    baseline_view = () if record is None else (
        ("cik", baseline.expected_cik), ("accession", record.get("filing_identifier")),
        ("filed", record.get("filing_time")), ("period_start", (record.get("fact_period") or {}).get("start")),
        ("period_end", (record.get("fact_period") or {}).get("end")), ("tag", record.get("tag")),
        ("value", record.get("value")), ("currency", record.get("currency")),
    )
    forward_view = (
        ("claim_id", claim["claim_id"]), ("subject", claim["subject"]), ("period", claim["period"]),
        ("value", result.get("value")), ("unit", claim["unit"]), ("currency", claim["currency"]),
        ("basis", claim["basis"]), ("scope", claim["scope"]), ("status", result.get("status")),
        ("independent_evidence_families", result.get("independent_evidence_families")),
    )
    return ForwardPremiseAssessment(
        premise_states=states, comparison_ready=ready, baseline_view=baseline_view,
        forward_view=forward_view, baseline_revised_within_document=revised,
    )
