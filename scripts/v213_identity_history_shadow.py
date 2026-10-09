"""V12 I3 claimed-validity history shadow component (offline, pure, stdlib only).

Reuses unchanged I1 normalize_query / _validate_record / resolve_query.
Adds caller-claimed validity intervals, strict global ledger constraints,
and as_of selection. NOT verified effective dates, NOT identity authority.
"""
import json
import sys
from datetime import date

if __package__:
    from . import v213_identity_search_shadow as i1
else:
    import v213_identity_search_shadow as i1

HISTORY_PROFILE = "I3_CLAIMED_VALIDITY_V1"

ENTRY_KEYS = frozenset({"record", "valid_from", "valid_to"})


def _validate_date(value, field):
    if type(value) is not str:
        raise ValueError(f"{field} must be a builtin str")
    if len(value) != 10:
        raise ValueError(f"{field} must be canonical YYYY-MM-DD")
    if value[4] != "-" or value[7] != "-":
        raise ValueError(f"{field} must be canonical YYYY-MM-DD")
    if not all(ch in "0123456789-" for ch in value):
        raise ValueError(f"{field} must be ASCII digits and hyphens")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} is not a valid Gregorian date")
    if parsed.year < 1 or parsed.year > 9999:
        raise ValueError(f"{field} year out of range")
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must be canonical YYYY-MM-DD")
    return parsed


def _validate_entry(entry):
    if type(entry) is not dict:
        raise ValueError("entry must be a builtin dict")
    for key in entry.keys():
        if type(key) is not str:
            raise ValueError("entry keys must be builtin str")
    if set(entry.keys()) != ENTRY_KEYS:
        raise ValueError("entry keys must exactly match {record,valid_from,valid_to}")
    record = entry["record"]
    if type(record) is not dict:
        raise ValueError("record must be a builtin dict")
    for key in record.keys():
        if type(key) is not str:
            raise ValueError("record keys must be builtin str")
    validated_record = i1._validate_record(record)
    valid_from = _validate_date(entry["valid_from"], "valid_from")
    valid_to = entry["valid_to"]
    if valid_to is not None:
        valid_to = _validate_date(valid_to, "valid_to")
    if valid_to is not None and valid_to <= valid_from:
        raise ValueError("valid_to must be strictly after valid_from")
    return {
        "record": record,
        "validated_record": validated_record,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


def _intervals_overlap(entry_i, entry_j):
    start_i = entry_i["valid_from"]
    end_i = entry_i["valid_to"]
    start_j = entry_j["valid_from"]
    end_j = entry_j["valid_to"]
    if end_i is None and end_j is None:
        return True
    if end_i is None:
        return start_i < end_j
    if end_j is None:
        return start_j < end_i
    return start_i < end_j and start_j < end_i


def _validate_ledger(validated_entries):
    security_company = {}
    for entry in validated_entries:
        rec = entry["validated_record"]
        sid = rec["security_id"]
        cid = rec["company_id"]
        if sid in security_company:
            if security_company[sid] != cid:
                raise ValueError("security_id binds to multiple company_id")
        else:
            security_company[sid] = cid
    by_security = {}
    for entry in validated_entries:
        sid = entry["validated_record"]["security_id"]
        by_security.setdefault(sid, []).append(entry)
    for sid, entries in by_security.items():
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                if _intervals_overlap(entries[i], entries[j]):
                    raise ValueError("security_id intervals overlap")
    by_key = {}
    for entry in validated_entries:
        rec = entry["validated_record"]
        key = (rec["exchange"], rec["ticker"])
        by_key.setdefault(key, []).append(entry)
    for key, entries in by_key.items():
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                if _intervals_overlap(entries[i], entries[j]):
                    raise ValueError("exchange+ticker intervals overlap")
    by_company = {}
    for entry in validated_entries:
        cid = entry["validated_record"]["company_id"]
        by_company.setdefault(cid, []).append(entry)
    for cid, entries in by_company.items():
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                if _intervals_overlap(entries[i], entries[j]):
                    name_i = entries[i]["record"]["canonical_name_zh_tw"]
                    name_j = entries[j]["record"]["canonical_name_zh_tw"]
                    if name_i is not None and name_j is not None and name_i != name_j:
                        raise ValueError("overlapping company names disagree")


def resolve_history_query(query, entries, as_of, exchange=None):
    as_of_date = _validate_date(as_of, "as_of")
    if type(entries) is not list:
        raise ValueError("entries must be a builtin list")
    if len(entries) > i1.MAX_RECORDS:
        raise ValueError("entries exceeds cap")
    validated_entries = [_validate_entry(e) for e in entries]
    _validate_ledger(validated_entries)
    active_records = []
    for entry in validated_entries:
        start = entry["valid_from"]
        end = entry["valid_to"]
        if as_of_date >= start and (end is None or as_of_date < end):
            active_records.append(entry["record"])
    result = i1.resolve_query(query, active_records, exchange)
    return {
        "status": result["status"],
        "AMBIGUOUS": result["AMBIGUOUS"],
        "candidates": result["candidates"],
        "shadow_only": True,
        "production_authorized": False,
        "as_of": as_of,
        "history_profile": HISTORY_PROFILE,
        "source_authenticated": False,
        "current_identity_authorized": False,
    }


INVALID_RESULT = {
    "status": "INVALID",
    "AMBIGUOUS": False,
    "candidates": [],
    "shadow_only": True,
    "production_authorized": False,
    "as_of": None,
    "history_profile": HISTORY_PROFILE,
    "source_authenticated": False,
    "current_identity_authorized": False,
}


def _emit_invalid():
    print(json.dumps(INVALID_RESULT, ensure_ascii=True))
    return 2


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1 or type(argv[0]) is not str:
        return _emit_invalid()
    try:
        with open(argv[0], "rb") as handle:
            data = handle.read(i1.MAX_INPUT_BYTES + 1)
        if len(data) > i1.MAX_INPUT_BYTES:
            return _emit_invalid()
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=i1._reject_duplicate_keys)
        if type(payload) is not dict:
            return _emit_invalid()
        if any(type(key) is not str for key in payload):
            return _emit_invalid()
        if not set(payload.keys()) <= {"query", "entries", "as_of", "exchange"}:
            return _emit_invalid()
        if "query" not in payload or "entries" not in payload or "as_of" not in payload:
            return _emit_invalid()
        result = resolve_history_query(payload["query"], payload["entries"], payload["as_of"], payload.get("exchange"))
    except (ValueError, TypeError, OSError, RecursionError):
        return _emit_invalid()
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())