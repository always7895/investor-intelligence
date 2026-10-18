"""V12 O1 declared venue/field coverage shadow (offline, pure, stdlib only).

Organizes caller declarations; NEVER qualifies support, rights, identity,
independent lineage, freshness, quotes or runtime admission. Import-inert.
"""
import json
import re
from dataclasses import dataclass
from datetime import datetime

MAX_PAYLOAD_BYTES = 131072
MAX_SCOPES = 32
MAX_EVIDENCE = 16
MAX_EVIDENCE_IDS = 16
MIN_MULTIPLIER = 1
MAX_MULTIPLIER = 1000000
DATA_ORIGIN = "SYNTHETIC_PUBLIC_DECLARATION_ONLY"

IDENTIFIER_REGEX = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
CURRENCY_REGEX = re.compile(r"[A-Z]{3}")
TIMESTAMP_REGEX = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")

SCOPE_KEYS = frozenset({
    "underlying_id", "underlying_exchange", "options_venue", "provider_id",
    "adapter_id", "product_family", "contract_id", "calendar_id",
    "currency", "multiplier", "data_origin", "field_coverage", "evidence",
})
FIELD_COVERAGE_KEYS = frozenset({
    "contract_identity", "expiry", "strike", "option_type", "bid", "ask",
    "last", "volume", "open_interest", "iv", "greeks", "trading_calendar", "quote_delay",
})
EVIDENCE_KEYS = frozenset({
    "evidence_id", "lineage_id", "source_id", "observed_at", "valid_until",
})
FIELD_DECLARATION_KEYS = frozenset({"declared", "evidence_ids"})
ROOT_KEYS = frozenset({"schema_version", "scopes"})
DECLARED_VALUES = frozenset({"AVAILABLE", "UNAVAILABLE", "NOT_DECLARED"})


class VenueMatrixError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    evidence_id: str
    lineage_id: str
    source_id: str
    observed_at: str
    valid_until: str
    temporal_state: str


@dataclass(frozen=True, slots=True)
class FieldResult:
    field_name: str
    declared: str
    derived_state: str
    evidence_ids: tuple


@dataclass(frozen=True, slots=True)
class ScopeResult:
    underlying_id: str
    underlying_exchange: str
    options_venue: str
    provider_id: str
    adapter_id: str
    product_family: str
    contract_id: str
    calendar_id: str
    currency: str
    multiplier: int
    data_origin: str
    field_results: tuple
    evidence_results: tuple
    qualified_support: bool
    runtime_enabled: bool
    admission_authorized: bool
    independent_lineage_verified: bool
    freshness_verified: bool


@dataclass(frozen=True, slots=True)
class MatrixResult:
    schema_version: int
    as_of: str
    scopes: tuple
    qualified_support: bool
    runtime_enabled: bool
    admission_authorized: bool
    independent_lineage_verified: bool
    freshness_verified: bool


def _reject_duplicate_keys(pairs):
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise VenueMatrixError("DUPLICATE_KEY")
        seen.add(key)
    return dict(pairs)


def _reject_nonfinite(_constant):
    raise VenueMatrixError("NONFINITE_CONSTANT")


def _parse_json(payload_json):
    try:
        data = payload_json.encode("utf-8")
    except UnicodeEncodeError:
        raise VenueMatrixError("INVALID_UTF8") from None
    if len(data) > MAX_PAYLOAD_BYTES:
        raise VenueMatrixError("PAYLOAD_TOO_LARGE") from None
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except VenueMatrixError:
        raise
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError, RecursionError):
        raise VenueMatrixError("INVALID_JSON") from None


def _validate_identifier(value):
    if type(value) is not str:
        raise VenueMatrixError("INVALID_IDENTIFIER_TYPE")
    if not IDENTIFIER_REGEX.fullmatch(value):
        raise VenueMatrixError("INVALID_IDENTIFIER")
    return value


def _validate_currency(value):
    if type(value) is not str:
        raise VenueMatrixError("INVALID_CURRENCY_TYPE")
    if not CURRENCY_REGEX.fullmatch(value):
        raise VenueMatrixError("INVALID_CURRENCY")
    return value


def _validate_multiplier(value):
    if type(value) is not int:
        raise VenueMatrixError("INVALID_MULTIPLIER_TYPE")
    if value < MIN_MULTIPLIER or value > MAX_MULTIPLIER:
        raise VenueMatrixError("INVALID_MULTIPLIER_RANGE")
    return value


def _validate_timestamp(value):
    if type(value) is not str:
        raise VenueMatrixError("INVALID_TIMESTAMP_TYPE")
    if len(value) != 20:
        raise VenueMatrixError("INVALID_TIMESTAMP_LENGTH")
    if not TIMESTAMP_REGEX.fullmatch(value):
        raise VenueMatrixError("INVALID_TIMESTAMP_FORMAT")
    try:
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise VenueMatrixError("INVALID_TIMESTAMP_DATE") from None
    if dt.year < 1970 or dt.year > 9999:
        raise VenueMatrixError("INVALID_TIMESTAMP_YEAR")
    return dt


def _derive_temporal_state(as_of_dt, observed_at, valid_until):
    if as_of_dt < observed_at:
        return "DECLARED_FUTURE"
    if as_of_dt >= valid_until:
        return "DECLARED_EXPIRED"
    return "DECLARED_IN_WINDOW_UNVERIFIED"


def _validate_field_declaration(declaration):
    if type(declaration) is not dict:
        raise VenueMatrixError("INVALID_FIELD_DECLARATION_TYPE")
    if set(declaration.keys()) != FIELD_DECLARATION_KEYS:
        raise VenueMatrixError("INVALID_FIELD_DECLARATION_KEYS")
    declared = declaration["declared"]
    if type(declared) is not str or declared not in DECLARED_VALUES:
        raise VenueMatrixError("INVALID_DECLARED")
    evidence_ids = declaration["evidence_ids"]
    if type(evidence_ids) is not list:
        raise VenueMatrixError("INVALID_EVIDENCE_IDS_TYPE")
    if len(evidence_ids) > MAX_EVIDENCE_IDS:
        raise VenueMatrixError("INVALID_EVIDENCE_IDS_COUNT")
    seen = set()
    for eid in evidence_ids:
        if type(eid) is not str:
            raise VenueMatrixError("INVALID_EVIDENCE_ID_TYPE")
        if not IDENTIFIER_REGEX.fullmatch(eid):
            raise VenueMatrixError("INVALID_EVIDENCE_ID")
        if eid in seen:
            raise VenueMatrixError("DUPLICATE_EVIDENCE_ID")
        seen.add(eid)
    if declared == "AVAILABLE" and len(evidence_ids) < 1:
        raise VenueMatrixError("AVAILABLE_REQUIRES_EVIDENCE")
    if declared in ("UNAVAILABLE", "NOT_DECLARED") and len(evidence_ids) > 0:
        raise VenueMatrixError("UNAVAILABLE_REQUIRES_EMPTY")
    return {"declared": declared, "evidence_ids": tuple(evidence_ids)}


def _validate_field_coverage(field_coverage):
    if type(field_coverage) is not dict:
        raise VenueMatrixError("INVALID_FIELD_COVERAGE_TYPE")
    if set(field_coverage.keys()) != FIELD_COVERAGE_KEYS:
        raise VenueMatrixError("INVALID_FIELD_COVERAGE_KEYS")
    result = {}
    for field_name in FIELD_COVERAGE_KEYS:
        result[field_name] = _validate_field_declaration(field_coverage[field_name])
    return result


def _validate_evidence(evidence, as_of_dt):
    if type(evidence) is not list:
        raise VenueMatrixError("INVALID_EVIDENCE_TYPE")
    if len(evidence) > MAX_EVIDENCE:
        raise VenueMatrixError("INVALID_EVIDENCE_COUNT")
    result = []
    seen_ids = set()
    for ev in evidence:
        if type(ev) is not dict:
            raise VenueMatrixError("INVALID_EVIDENCE_DESCRIPTOR_TYPE")
        if set(ev.keys()) != EVIDENCE_KEYS:
            raise VenueMatrixError("INVALID_EVIDENCE_DESCRIPTOR_KEYS")
        evidence_id = _validate_identifier(ev["evidence_id"])
        lineage_id = _validate_identifier(ev["lineage_id"])
        source_id = _validate_identifier(ev["source_id"])
        observed_at = _validate_timestamp(ev["observed_at"])
        valid_until = _validate_timestamp(ev["valid_until"])
        if not (observed_at < valid_until):
            raise VenueMatrixError("CONTRADICTORY_DECLARED_INTERVAL")
        if evidence_id in seen_ids:
            raise VenueMatrixError("DUPLICATE_EVIDENCE_ID")
        seen_ids.add(evidence_id)
        temporal_state = _derive_temporal_state(as_of_dt, observed_at, valid_until)
        result.append({
            "evidence_id": evidence_id,
            "lineage_id": lineage_id,
            "source_id": source_id,
            "observed_at": ev["observed_at"],
            "valid_until": ev["valid_until"],
            "temporal_state": temporal_state,
        })
    return result


def _validate_scope(scope, as_of_dt):
    if type(scope) is not dict:
        raise VenueMatrixError("INVALID_SCOPE_TYPE")
    if set(scope.keys()) != SCOPE_KEYS:
        raise VenueMatrixError("INVALID_SCOPE_KEYS")
    underlying_id = _validate_identifier(scope["underlying_id"])
    underlying_exchange = _validate_identifier(scope["underlying_exchange"])
    options_venue = _validate_identifier(scope["options_venue"])
    provider_id = _validate_identifier(scope["provider_id"])
    adapter_id = _validate_identifier(scope["adapter_id"])
    product_family = _validate_identifier(scope["product_family"])
    contract_id = _validate_identifier(scope["contract_id"])
    calendar_id = _validate_identifier(scope["calendar_id"])
    currency = _validate_currency(scope["currency"])
    multiplier = _validate_multiplier(scope["multiplier"])
    data_origin = scope["data_origin"]
    if type(data_origin) is not str or data_origin != DATA_ORIGIN:
        raise VenueMatrixError("INVALID_DATA_ORIGIN")
    field_coverage = _validate_field_coverage(scope["field_coverage"])
    evidence = _validate_evidence(scope["evidence"], as_of_dt)
    return {
        "underlying_id": underlying_id,
        "underlying_exchange": underlying_exchange,
        "options_venue": options_venue,
        "provider_id": provider_id,
        "adapter_id": adapter_id,
        "product_family": product_family,
        "contract_id": contract_id,
        "calendar_id": calendar_id,
        "currency": currency,
        "multiplier": multiplier,
        "data_origin": data_origin,
        "field_coverage": field_coverage,
        "evidence": evidence,
    }


def _validate_field_references(validated):
    evidence_ids = {ev["evidence_id"] for ev in validated["evidence"]}
    for _field_name, declaration in validated["field_coverage"].items():
        for eid in declaration["evidence_ids"]:
            if eid not in evidence_ids:
                raise VenueMatrixError("UNRESOLVED_EVIDENCE_REFERENCE")


def _scope_base(scope):
    return (
        scope["underlying_id"],
        scope["underlying_exchange"],
        scope["options_venue"],
        scope["provider_id"],
        scope["adapter_id"],
        scope["product_family"],
        scope["contract_id"],
        scope["calendar_id"],
    )


def _validate_scopes(scopes, as_of_dt):
    result = []
    seen_base = {}
    for scope in scopes:
        validated = _validate_scope(scope, as_of_dt)
        base = _scope_base(validated)
        if base in seen_base:
            prev = seen_base[base]
            if prev["currency"] == validated["currency"] and prev["multiplier"] == validated["multiplier"]:
                raise VenueMatrixError("DUPLICATE_SCOPE")
            raise VenueMatrixError("CONFLICTING_DECLARED_TERMS")
        seen_base[base] = validated
        _validate_field_references(validated)
        result.append(validated)
    return result


def _validate_root(payload):
    if type(payload) is not dict:
        raise VenueMatrixError("INVALID_ROOT")
    if set(payload.keys()) != ROOT_KEYS:
        raise VenueMatrixError("INVALID_ROOT_KEYS")
    schema_version = payload["schema_version"]
    if type(schema_version) is not int or schema_version != 1:
        raise VenueMatrixError("INVALID_SCHEMA_VERSION")
    scopes = payload["scopes"]
    if type(scopes) is not list:
        raise VenueMatrixError("INVALID_SCOPES_TYPE")
    if len(scopes) < 1 or len(scopes) > MAX_SCOPES:
        raise VenueMatrixError("INVALID_SCOPES_COUNT")
    return payload


def _build_evidence_result(ev):
    return EvidenceResult(
        evidence_id=ev["evidence_id"],
        lineage_id=ev["lineage_id"],
        source_id=ev["source_id"],
        observed_at=ev["observed_at"],
        valid_until=ev["valid_until"],
        temporal_state=ev["temporal_state"],
    )


def _build_field_result(field_name, declaration, scope):
    declared = declaration["declared"]
    evidence_ids = declaration["evidence_ids"]
    if declared == "NOT_DECLARED":
        derived_state = "NOT_DECLARED_IN_INPUT"
    elif declared == "UNAVAILABLE":
        derived_state = "DECLARED_UNAVAILABLE_UNVERIFIED"
    else:
        in_window = False
        for ev in scope["evidence"]:
            if ev["evidence_id"] in evidence_ids and ev["temporal_state"] == "DECLARED_IN_WINDOW_UNVERIFIED":
                in_window = True
                break
        derived_state = "DECLARED_AVAILABLE_UNVERIFIED" if in_window else "DECLARED_AVAILABLE_NO_CURRENT_REFERENCES"
    return FieldResult(
        field_name=field_name,
        declared=declared,
        derived_state=derived_state,
        evidence_ids=tuple(sorted(evidence_ids)),
    )


def _build_scope_result(scope):
    field_results = tuple(
        _build_field_result(field_name, declaration, scope)
        for field_name, declaration in sorted(scope["field_coverage"].items())
    )
    evidence_results = tuple(
        _build_evidence_result(ev)
        for ev in sorted(scope["evidence"], key=lambda ev: ev["evidence_id"])
    )
    return ScopeResult(
        underlying_id=scope["underlying_id"],
        underlying_exchange=scope["underlying_exchange"],
        options_venue=scope["options_venue"],
        provider_id=scope["provider_id"],
        adapter_id=scope["adapter_id"],
        product_family=scope["product_family"],
        contract_id=scope["contract_id"],
        calendar_id=scope["calendar_id"],
        currency=scope["currency"],
        multiplier=scope["multiplier"],
        data_origin=scope["data_origin"],
        field_results=field_results,
        evidence_results=evidence_results,
        qualified_support=False,
        runtime_enabled=False,
        admission_authorized=False,
        independent_lineage_verified=False,
        freshness_verified=False,
    )


def _build_result(as_of, scopes):
    sorted_scopes = sorted(scopes, key=_scope_base)
    scope_results = tuple(_build_scope_result(scope) for scope in sorted_scopes)
    return MatrixResult(
        schema_version=1,
        as_of=as_of,
        scopes=scope_results,
        qualified_support=False,
        runtime_enabled=False,
        admission_authorized=False,
        independent_lineage_verified=False,
        freshness_verified=False,
    )


def evaluate_declared_venue_matrix(payload_json, *, as_of):
    if type(payload_json) is not str:
        raise VenueMatrixError("INVALID_ARG_TYPE")
    if type(as_of) is not str:
        raise VenueMatrixError("INVALID_ARG_TYPE")
    as_of_dt = _validate_timestamp(as_of)
    payload = _parse_json(payload_json)
    _validate_root(payload)
    scopes = _validate_scopes(payload["scopes"], as_of_dt)
    return _build_result(as_of, scopes)