"""V12 I1 identity/LINE normalization shadow component (offline, pure, stdlib only).

Reusable offline shadow caller; NOT live LINE integration and NOT complete
identity/name coverage. Records are caller-injected, not asserted facts.
"""
import json
import sys
import unicodedata

MAX_QUERY_LENGTH = 256


def _has_category_c(text):
    return any(unicodedata.category(ch).startswith("C") for ch in text)


def normalize_query(text):
    if type(text) is not str:
        raise ValueError("query must be a builtin str")
    if text == "" or len(text) > MAX_QUERY_LENGTH:
        raise ValueError("query empty or exceeds raw length cap")
    if _has_category_c(text):
        raise ValueError("query contains control/format/bidi/undefined character")
    folded = unicodedata.normalize("NFKC", text).casefold()
    collapsed = " ".join(folded.split())
    if collapsed == "" or len(collapsed) > MAX_QUERY_LENGTH:
        raise ValueError("query empty or exceeds normalized length cap")
    if _has_category_c(collapsed):
        raise ValueError("normalized query contains control/format/bidi/undefined character")
    return collapsed


MAX_RECORDS = 1024
MAX_ALIASES = 32
MAX_SOURCE_LENGTH = 2048

REQUIRED_KEYS = frozenset({
    "company_id", "security_id", "exchange", "ticker",
    "canonical_name_zh_tw", "aliases", "name_authority", "name_source",
})

ALLOWED_AUTHORITIES = frozenset({
    "official_issuer_exchange_government_zh_tw",
    "official_issuer_chinese",
    "established_tw_hk_usage",
    "reviewed_curated_transliteration",
})


def _validate_opaque_id(value, field):
    if type(value) is not str:
        raise ValueError(f"{field} must be a builtin str")
    if value == "" or value != value.strip() or len(value) > MAX_QUERY_LENGTH:
        raise ValueError(f"{field} empty, padded, or exceeds length cap")
    if _has_category_c(value):
        raise ValueError(f"{field} contains control/format/bidi/undefined character")
    return value


def _validate_record(record):
    if type(record) is not dict:
        raise ValueError("record must be a builtin dict")
    if set(record.keys()) != REQUIRED_KEYS:
        raise ValueError("record keys must exactly match the closed schema")
    company_id = _validate_opaque_id(record["company_id"], "company_id")
    security_id = _validate_opaque_id(record["security_id"], "security_id")
    display_exchange = record["exchange"]
    display_ticker = record["ticker"]
    exchange = normalize_query(record["exchange"])
    ticker = normalize_query(record["ticker"])
    aliases_raw = record["aliases"]
    if type(aliases_raw) is not list:
        raise ValueError("aliases must be a builtin list")
    if len(aliases_raw) > MAX_ALIASES:
        raise ValueError("aliases exceeds cap")
    aliases = [normalize_query(a) for a in aliases_raw]
    canonical = record["canonical_name_zh_tw"]
    authority = record["name_authority"]
    source = record["name_source"]
    if canonical is None:
        if authority is not None or source is not None:
            raise ValueError("canonical absent requires null authority and source")
        normalized_canonical = None
    else:
        if type(canonical) is not str:
            raise ValueError("canonical_name_zh_tw must be a builtin str or null")
        normalized_canonical = normalize_query(canonical)
        if type(authority) is not str or authority not in ALLOWED_AUTHORITIES:
            raise ValueError("canonical present requires an allowed explicit authority")
        if type(source) is not str or source == "" or source.strip() == "" or len(source) > MAX_SOURCE_LENGTH:
            raise ValueError("canonical present requires a nonempty source within cap")
        if _has_category_c(source):
            raise ValueError("source reference contains control/format/bidi/undefined character")
    return {
        "company_id": company_id,
        "security_id": security_id,
        "exchange": exchange,
        "ticker": ticker,
        "canonical_name_zh_tw": normalized_canonical,
        "aliases": aliases,
        "display_exchange": display_exchange,
        "display_ticker": display_ticker,
        "display_name": canonical,
    }


def _candidate_dict(rec):
    return {
        "company_id": rec["company_id"],
        "security_id": rec["security_id"],
        "exchange": rec["display_exchange"],
        "ticker": rec["display_ticker"],
        "name": rec["display_name"],
    }


def resolve_query(query, records, exchange=None):
    normalized_query = normalize_query(query)
    if type(records) is not list:
        raise ValueError("records must be a builtin list")
    if len(records) > MAX_RECORDS:
        raise ValueError("records exceeds cap")
    validated = [_validate_record(r) for r in records]
    seen_security = set()
    seen_key = set()
    for rec in validated:
        if rec["security_id"] in seen_security:
            raise ValueError("duplicate security_id")
        seen_security.add(rec["security_id"])
        key = (rec["exchange"], rec["ticker"])
        if key in seen_key:
            raise ValueError("conflicting normalized exchange+ticker key")
        seen_key.add(key)
    if exchange is not None:
        normalized_exchange = normalize_query(exchange)
    else:
        normalized_exchange = None
    matches = []
    for rec in validated:
        if normalized_exchange is not None and rec["exchange"] != normalized_exchange:
            continue
        searchable = {rec["ticker"]}
        searchable.update(rec["aliases"])
        if rec["canonical_name_zh_tw"] is not None:
            searchable.add(rec["canonical_name_zh_tw"])
        if normalized_query in searchable:
            matches.append(rec)
    if len(matches) == 1:
        status = "MATCH"
    elif len(matches) > 1:
        status = "AMBIGUOUS"
    else:
        status = "NOT_FOUND"
    ordered = sorted(matches, key=lambda r: (r["security_id"], r["exchange"], r["ticker"]))
    return {
        "status": status,
        "AMBIGUOUS": status == "AMBIGUOUS",
        "candidates": [_candidate_dict(r) for r in ordered],
        "shadow_only": True,
        "production_authorized": False,
    }


MAX_INPUT_BYTES = 8 * 1024 * 1024

INVALID_RESULT = {
    "status": "INVALID",
    "AMBIGUOUS": False,
    "candidates": [],
    "shadow_only": True,
    "production_authorized": False,
}


def _reject_duplicate_keys(pairs):
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise ValueError("duplicate JSON object key")
        seen.add(key)
    return dict(pairs)


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
            data = handle.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            return _emit_invalid()
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        if type(payload) is not dict:
            return _emit_invalid()
        if not set(payload.keys()) <= {"query", "records", "exchange"}:
            return _emit_invalid()
        if "query" not in payload or "records" not in payload:
            return _emit_invalid()
        result = resolve_query(payload["query"], payload["records"], payload.get("exchange"))
    except (ValueError, TypeError, OSError, RecursionError):
        return _emit_invalid()
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())