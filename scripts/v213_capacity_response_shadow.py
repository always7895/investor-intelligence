"""V12 R3A declared usable-capacity headroom shadow (offline, pure, stdlib only).

Compares two caller-claimed PERIOD_TOTAL quantities only. Does NOT authenticate
identity/source/qualification/currentness, prove substitutes/scarcity, derive
usable capacity from nameplate, model scenario factors, score/rank, or authorize
publication. NOT native, NOT production, NOT research authority.
"""
import re
from datetime import date

PROFILE = "R3_DECLARED_USABLE_HEADROOM_V1"
INVALID_ERROR = "INVALID_CAPACITY_SHADOW_INPUT"

PAYLOAD_KEYS = frozenset({"as_of", "demand", "capacity"})
MEASURE_KEYS = frozenset({
    "claim_id", "lineage_id", "node_id", "spec_id", "customer_id", "unit",
    "measure_kind", "period_start", "period_end", "state_as_of", "kind", "quantity",
})
DEMAND_KINDS = frozenset({"CURRENT_REQUIRED", "FORECAST", "UNKNOWN"})
CAPACITY_KINDS = frozenset({"CURRENT_QUALIFIED_USABLE", "NAMEPLATE", "ANNOUNCED", "MODELED", "UNKNOWN"})

ID_REGEX = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
QUANTITY_REGEX = re.compile(r"(?:0|[1-9][0-9]{0,12})(?:\.[0-9]{1,6})?")
QUANTITY_MAX = 1000000000000


def _validate_id(value):
    if type(value) is not str:
        raise ValueError(INVALID_ERROR)
    if not ID_REGEX.fullmatch(value):
        raise ValueError(INVALID_ERROR)
    return value


def _validate_date(value):
    if type(value) is not str:
        raise ValueError(INVALID_ERROR)
    if len(value) != 10:
        raise ValueError(INVALID_ERROR)
    if value[4] != "-" or value[7] != "-":
        raise ValueError(INVALID_ERROR)
    if not all(ch in "0123456789-" for ch in value):
        raise ValueError(INVALID_ERROR)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(INVALID_ERROR)
    if parsed.year < 1 or parsed.year > 9999:
        raise ValueError(INVALID_ERROR)
    if parsed.isoformat() != value:
        raise ValueError(INVALID_ERROR)
    return parsed


def _validate_quantity(value):
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(INVALID_ERROR)
    if len(value) > 20:
        raise ValueError(INVALID_ERROR)
    if not QUANTITY_REGEX.fullmatch(value):
        raise ValueError(INVALID_ERROR)
    if "." in value:
        int_part, frac_part = value.split(".")
        frac_part = frac_part.ljust(6, "0")[:6]
    else:
        int_part = value
        frac_part = "000000"
    int_millionths = int(int_part) * 10**6 + int(frac_part)
    if int_millionths > QUANTITY_MAX * 10**6:
        raise ValueError(INVALID_ERROR)
    return int_millionths


def _validate_measure(measure, kind_set):
    if type(measure) is not dict:
        raise ValueError(INVALID_ERROR)
    for key in measure.keys():
        if type(key) is not str:
            raise ValueError(INVALID_ERROR)
    if set(measure.keys()) != MEASURE_KEYS:
        raise ValueError(INVALID_ERROR)
    claim_id = _validate_id(measure["claim_id"])
    lineage_id = _validate_id(measure["lineage_id"])
    node_id = _validate_id(measure["node_id"])
    spec_id = _validate_id(measure["spec_id"])
    customer_id = _validate_id(measure["customer_id"])
    unit = _validate_id(measure["unit"])
    measure_kind = measure["measure_kind"]
    if type(measure_kind) is not str or measure_kind != "PERIOD_TOTAL":
        raise ValueError(INVALID_ERROR)
    period_start = _validate_date(measure["period_start"])
    period_end = _validate_date(measure["period_end"])
    if not (period_start < period_end):
        raise ValueError(INVALID_ERROR)
    state_as_of = _validate_date(measure["state_as_of"])
    kind = measure["kind"]
    if type(kind) is not str or kind not in kind_set:
        raise ValueError(INVALID_ERROR)
    quantity = _validate_quantity(measure["quantity"])
    return {
        "claim_id": claim_id,
        "lineage_id": lineage_id,
        "node_id": node_id,
        "spec_id": spec_id,
        "customer_id": customer_id,
        "unit": unit,
        "measure_kind": measure_kind,
        "period_start": period_start,
        "period_end": period_end,
        "state_as_of": state_as_of,
        "kind": kind,
        "quantity": quantity,
    }


def _format_millionths(value):
    if value == 0:
        return "0"
    negative = value < 0
    value = abs(value)
    int_part = value // 10**6
    frac_part = value % 10**6
    if frac_part == 0:
        result = str(int_part)
    else:
        frac_str = str(frac_part).zfill(6).rstrip("0")
        result = f"{int_part}.{frac_str}"
    if negative:
        result = "-" + result
    return result


def evaluate_capacity_headroom(payload):
    if type(payload) is not dict:
        raise ValueError(INVALID_ERROR)
    for key in payload.keys():
        if type(key) is not str:
            raise ValueError(INVALID_ERROR)
    if set(payload.keys()) != PAYLOAD_KEYS:
        raise ValueError(INVALID_ERROR)
    as_of = _validate_date(payload["as_of"])
    demand = _validate_measure(payload["demand"], DEMAND_KINDS)
    capacity = _validate_measure(payload["capacity"], CAPACITY_KINDS)
    if demand["claim_id"] == capacity["claim_id"]:
        raise ValueError(INVALID_ERROR)
    reasons = []
    if capacity["kind"] != "CURRENT_QUALIFIED_USABLE":
        reasons.append("CAPACITY_NOT_CURRENT_QUALIFIED_USABLE")
    if demand["kind"] != "CURRENT_REQUIRED":
        reasons.append("DEMAND_NOT_CURRENT_REQUIRED")
    if demand["quantity"] is None or capacity["quantity"] is None:
        reasons.append("MISSING_QUANTITY")
    if (demand["node_id"] != capacity["node_id"]
            or demand["spec_id"] != capacity["spec_id"]
            or demand["customer_id"] != capacity["customer_id"]):
        reasons.append("SCOPE_MISMATCH")
    if demand["unit"] != capacity["unit"]:
        reasons.append("UNIT_MISMATCH")
    if (demand["period_start"] != capacity["period_start"]
            or demand["period_end"] != capacity["period_end"]):
        reasons.append("PERIOD_MISMATCH")
    if demand["state_as_of"] != as_of or capacity["state_as_of"] != as_of:
        reasons.append("STATE_AS_OF_MISMATCH")
    if not (demand["period_start"] <= as_of < demand["period_end"]
            and capacity["period_start"] <= as_of < capacity["period_end"]):
        reasons.append("OUTSIDE_PERIOD")
    if reasons:
        status = "UNKNOWN"
        headroom = None
    else:
        diff = capacity["quantity"] - demand["quantity"]
        if diff > 0:
            status = "CLAIMED_SURPLUS"
        elif diff == 0:
            status = "CLAIMED_BALANCED"
        else:
            status = "CLAIMED_SHORTFALL"
        headroom = _format_millionths(diff)
    return {
        "profile": PROFILE,
        "as_of": payload["as_of"],
        "status": status,
        "reasons": reasons,
        "headroom": headroom,
        "demand_claim_id": demand["claim_id"],
        "capacity_claim_id": capacity["claim_id"],
        "demand_lineage_id": demand["lineage_id"],
        "capacity_lineage_id": capacity["lineage_id"],
        "shadow_only": True,
        "source_authenticated": False,
        "comparability_authenticated": False,
        "independence_assessed": False,
        "production_authorized": False,
    }