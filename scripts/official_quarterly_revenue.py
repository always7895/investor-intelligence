#!/usr/bin/env python3
"""Official comparative-quarter revenue records (Astra contract L18-5351-CURATED-01, operator 2026-09-27).

Yahoo's quarterly income statement carries five quarters, so for some listings the preceding quarter has no
same-quarter comparator a year earlier and its YoY stays null. A reviewed record in
config/official-quarterly-revenue-v1.json supplies both operands of that previous-quarter YoY from the issuer's own
CPA-reviewed interim reports. It applies only to one exact symbol and quarter pair, only when Yahoo's financial
statement currency is the record's, and only when all three overlapping Yahoo totals and the current YoY agree with
the official figures (constants below, never per-record knobs). The record is the curated trust input; its
document digests bind the claims to retained evidence, they do not prove accounting truth at run time.

Shared by the builder (scripts/bottleneck_top20_v3.py, evaluate) and the sealer (scripts/publish_sealed_snapshot.py,
seal_evidence); the Worker mirrors the wire checks (cloud/src/v213/bottleneck-v3.ts). Pure: no network access; the
config path and the as-of clock are injectable.
"""
from __future__ import annotations

import hashlib
import json
import math
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "official-quarterly-revenue-v1.json"
SCHEMA = "official-quarterly-revenue-v1"
EVIDENCE_VERSION = "official-quarterly-revenue-evidence-v1"

# One official reporting unit (TWD thousands) per overlapping quarter, and 0.001 percentage point on the current YoY.
MAX_OVERLAP_DELTA = 1000.0
MAX_CURRENT_YOY_DELTA = 0.00001
PREV_YOY_TOLERANCE = 1e-12
PUBLISHER_HOSTS = {"etron.com"}  # official issuer sites admitted in this batch
MAX_AMOUNT = 10 ** 15
REASONS = ("NO_RECORD", "PERIOD_MISMATCH", "CURRENCY_UNVERIFIED", "CROSS_CHECK_MISMATCH", "INVALID_RECORD",
           "AMBIGUOUS_RECORD")

RECORD_KEYS = {"id", "symbol", "status", "issuer", "publisher", "applies_to_quarter_end", "previous_quarter_end",
               "currency", "unit", "unit_multiplier", "scope", "accounting_standard", "metric", "documents",
               "previous_pair", "current_pair", "restatement_check", "review"}
ISSUER_KEYS = {"name_en", "name_zh", "short_name_zh", "ticker", "exchange"}
DOCUMENT_KEYS = {"id", "title", "url", "publisher", "published_date", "retrieved_at", "byte_size", "sha256", "assurance"}
CLAIM_KEYS = {"amount", "start", "end", "period_kind", "document_id", "page_label", "note", "row"}
PAIR_KEYS = {"current", "prior_year"}
RESTATEMENT_KEYS = {"status", "document_id", "half_year_claims", "reconciliations"}
RECONCILIATION_KEYS = {"period", "half_year_amount", "current_quarter_amount", "derived_q1_amount", "q1_claim_amount",
                       "difference"}
REVIEW_KEYS = {"checked_at", "receipt"}
FIXED = {"status": "VERIFIED", "currency": "TWD", "unit": "THOUSANDS", "unit_multiplier": 1000, "scope": "CONSOLIDATED",
         "accounting_standard": "IAS34_TW_FSC", "metric": "TOTAL_REVENUE"}


class RecordError(ValueError):
    """A curated record or its wire evidence is not admissible; reason is one of REASONS."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


def _fail(detail: str, reason: str = "INVALID_RECORD") -> RecordError:
    return RecordError(reason, detail)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail(f"duplicate JSON key {key!r}", "AMBIGUOUS_RECORD")
        result[key] = value
    return result


def _object(value: Any, keys: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _fail(f"{where} must be an object with exactly {sorted(keys)}")
    return value


def _text(value: Any, limit: int, where: str) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(ch) < 32 or 0x7f <= ord(ch) < 0xa0 or 0xd800 <= ord(ch) < 0xe000 for ch in value)):
        raise _fail(f"{where} must be a non-empty single-line string of at most {limit} characters")
    return value


def _date(value: Any, where: str) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise _fail(f"{where} must be YYYY-MM-DD")
    try:
        day = date.fromisoformat(value)
    except ValueError as error:
        raise _fail(f"{where} is not a calendar date") from error
    if not 1990 <= day.year <= 2100:
        raise _fail(f"{where} is out of range")
    return day


def _utc(value: Any, where: str) -> datetime:
    if not isinstance(value, str) or len(value) != 20 or not value.endswith("Z"):
        raise _fail(f"{where} must be YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise _fail(f"{where} is not a UTC timestamp") from error


def _amount(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < MAX_AMOUNT:
        raise _fail(f"{where} must be a positive integer in source units")
    return value


def quarter_end(day: date) -> bool:
    return (day.month, day.day) in ((3, 31), (6, 30), (9, 30), (12, 31))


def quarter_start(end: date) -> date:
    return date(end.year, end.month - 2, 1)


def previous_quarter_end(end: date) -> date:
    return quarter_start(end) - timedelta(days=1)


def year_earlier(end: date) -> date:
    return date(end.year - 1, end.month, end.day)


def quarter_label(end: date) -> str:
    return f"{end.year}Q{(end.month - 1) // 3 + 1}"


def _claim(value: Any, documents: set[str], kind: str, start: date, end: date, where: str) -> int:
    claim = _object(value, CLAIM_KEYS, where)
    if claim["period_kind"] != kind:
        raise _fail(f"{where}.period_kind must be {kind}")
    if _date(claim["start"], f"{where}.start") != start or _date(claim["end"], f"{where}.end") != end:
        raise _fail(f"{where} must cover exactly {start} to {end}")
    if claim["document_id"] not in documents:
        raise _fail(f"{where}.document_id does not resolve within the record")
    for key in ("page_label", "note", "row"):
        _text(claim[key], 60, f"{where}.{key}")
    return _amount(claim["amount"], f"{where}.amount")


def validate_record(record: Any, as_of: datetime) -> dict[str, Any]:
    """Validate one record completely (types, bounds, periods, provenance, restatement arithmetic) or raise."""
    record = _object(record, RECORD_KEYS, "record")
    _text(record["id"], 80, "id")
    _text(record["symbol"], 20, "symbol")
    for key, expected in FIXED.items():
        value = record[key]
        if isinstance(value, bool) or value != expected or type(value) is not type(expected):
            raise _fail(f"{key} must be {expected!r}")
    issuer = _object(record["issuer"], ISSUER_KEYS, "issuer")
    for key in ISSUER_KEYS:
        _text(issuer[key], 120, f"issuer.{key}")
    _text(record["publisher"], 120, "publisher")
    current = _date(record["applies_to_quarter_end"], "applies_to_quarter_end")
    previous = _date(record["previous_quarter_end"], "previous_quarter_end")
    if not quarter_end(current) or previous != previous_quarter_end(current):
        raise _fail("previous_quarter_end must be the calendar quarter immediately before applies_to_quarter_end")
    documents = record["documents"]
    if not isinstance(documents, list) or not 1 <= len(documents) <= 4:
        raise _fail("documents must list one to four source documents")
    ids: set[str] = set()
    retrieved_latest = None
    for index, raw in enumerate(documents):
        where = f"documents[{index}]"
        document = _object(raw, DOCUMENT_KEYS, where)
        identifier = _text(document["id"], 60, f"{where}.id")
        if identifier in ids:
            raise _fail(f"{where}.id is duplicated", "AMBIGUOUS_RECORD")
        ids.add(identifier)
        _text(document["title"], 160, f"{where}.title")
        _text(document["publisher"], 120, f"{where}.publisher")
        url = _text(document["url"], 400, f"{where}.url")
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in PUBLISHER_HOSTS or parts.netloc != parts.hostname
                or parts.fragment or parts.query or not parts.path.startswith("/")
                or any(ch.isspace() or ch in "\\@" for ch in url)):
            raise _fail(f"{where}.url must be an https URL on an admitted issuer host without credentials, port, "
                        "query or fragment")
        sha = document["sha256"]
        if not isinstance(sha, str) or len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise _fail(f"{where}.sha256 must be 64 lowercase hex characters")
        _amount(document["byte_size"], f"{where}.byte_size")
        if document["assurance"] != "CPA_REVIEWED":
            raise _fail(f"{where}.assurance must be CPA_REVIEWED")
        published = _date(document["published_date"], f"{where}.published_date")
        retrieved = _utc(document["retrieved_at"], f"{where}.retrieved_at")
        if published > retrieved.date() or retrieved > as_of:
            raise _fail(f"{where} must be published before retrieval and retrieved before the build clock")
        retrieved_latest = max(retrieved_latest or retrieved, retrieved)
    pairs = {}
    for name, end in (("previous_pair", previous), ("current_pair", current)):
        pair = _object(record[name], PAIR_KEYS, name)
        pairs[name] = (
            _claim(pair["current"], ids, "QUARTER", quarter_start(end), end, f"{name}.current"),
            _claim(pair["prior_year"], ids, "QUARTER", quarter_start(year_earlier(end)), year_earlier(end),
                   f"{name}.prior_year"))
    check = _object(record["restatement_check"], RESTATEMENT_KEYS, "restatement_check")
    if check["status"] != f"MATCHED_THROUGH_{quarter_label(current)}" or check["document_id"] not in ids:
        raise _fail("restatement_check must be MATCHED_THROUGH the applicable quarter with a resolvable document")
    halves = _object(check["half_year_claims"], PAIR_KEYS, "restatement_check.half_year_claims")
    if current.month not in (6, 12):
        raise _fail("the half-year reconciliation needs a second or fourth quarter")
    expected = []
    for role, end in (("current", current), ("prior_year", year_earlier(current))):
        index = 0 if role == "current" else 1
        half = _claim(halves[role], ids, "HALF_YEAR", quarter_start(previous_quarter_end(end)), end,
                      f"restatement_check.half_year_claims.{role}")
        if halves[role]["document_id"] != check["document_id"]:
            raise _fail("the half-year claims must come from the restatement document")
        second, first = pairs["current_pair"][index], pairs["previous_pair"][index]
        if half - second != first:
            raise _fail(f"{role}: half-year {half} minus quarter {second} is not the earlier claim {first}")
        expected.append({"period": quarter_label(previous_quarter_end(end)), "half_year_amount": half,
                         "current_quarter_amount": second, "derived_q1_amount": half - second,
                         "q1_claim_amount": first, "difference": 0})
    reconciliations = check["reconciliations"]
    if not isinstance(reconciliations, list) or len(reconciliations) != 2:
        raise _fail("restatement_check.reconciliations must hold the two reconciliations")
    for index, row in enumerate(reconciliations):
        _object(row, RECONCILIATION_KEYS, f"restatement_check.reconciliations[{index}]")
        if any(isinstance(value, bool) for value in row.values()) or row != expected[index]:
            raise _fail(f"restatement_check.reconciliations[{index}] does not match the claims")
    review = _object(record["review"], REVIEW_KEYS, "review")
    checked = _utc(review["checked_at"], "review.checked_at")
    if (retrieved_latest is not None and checked < retrieved_latest) or checked > as_of:
        raise _fail("review.checked_at must follow retrieval and precede the build clock")
    _text(review["receipt"], 80, "review.receipt")
    return record


def load(path: Path | None = None, as_of: datetime | None = None) -> tuple[list[dict[str, Any]], str]:
    """The validated records and the SHA-256 of the exact config bytes; raises RecordError."""
    clock = as_of or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise _fail("the as-of clock must be timezone-aware")
    try:
        raw = (path or CONFIG).read_bytes()
    except OSError as error:
        raise _fail(f"config unreadable ({type(error).__name__})", "NO_RECORD") from error
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys,
                              parse_constant=lambda token: (_ for _ in ()).throw(_fail(f"non-finite {token}")))
    except RecordError:
        raise
    except (UnicodeDecodeError, ValueError) as error:
        raise _fail("config is not valid UTF-8 JSON") from error
    document = _object(document, {"schema", "records"}, "config")
    if document["schema"] != SCHEMA:
        raise _fail("wrong schema")
    records = document["records"]
    if not isinstance(records, list) or not 1 <= len(records) <= 20:
        raise _fail("records must list one to twenty records")
    seen: set[tuple[str, str]] = set()
    for record in records:
        validate_record(record, clock)
        key = (record["symbol"], record["applies_to_quarter_end"])
        if key in seen:
            raise _fail(f"two records for {key}", "AMBIGUOUS_RECORD")
        seen.add(key)
    return records, hashlib.sha256(raw).hexdigest()


def evidence(record: dict[str, Any], config_sha256: str, observed: Mapping[str, float], current_yoy: float,
             financial_currency: str) -> dict[str, Any]:
    """The allowlisted wire evidence, built only from the validated record and the observed Yahoo figures; raises
    RecordError (CROSS_CHECK_MISMATCH) when an overlap or the current YoY disagrees."""
    multiplier = record["unit_multiplier"]
    current, previous = record["current_pair"], record["previous_pair"]
    overlaps = {}
    for name, claim in (("current_current", current["current"]), ("current_prior_year", current["prior_year"]),
                        ("previous_current", previous["current"])):
        seen = observed.get(claim["end"])
        official = claim["amount"] * multiplier
        if isinstance(seen, bool) or not isinstance(seen, (int, float)) or not math.isfinite(seen) or seen <= 0:
            raise _fail(f"Yahoo total for {claim['end']} missing", "CROSS_CHECK_MISMATCH")
        delta = abs(float(seen) - official)
        if delta > MAX_OVERLAP_DELTA:
            raise _fail(f"Yahoo total for {claim['end']} differs by {delta} TWD", "CROSS_CHECK_MISMATCH")
        overlaps[name] = {"period_end": claim["end"], "official_twd": official, "yahoo_twd": float(seen),
                          "delta_twd": delta}
    official_ratio = current["current"]["amount"] / current["prior_year"]["amount"] - 1
    if isinstance(current_yoy, bool) or not isinstance(current_yoy, (int, float)) or not math.isfinite(current_yoy):
        raise _fail("current YoY missing", "CROSS_CHECK_MISMATCH")
    ratio_delta = abs(float(current_yoy) - official_ratio)
    if ratio_delta > MAX_CURRENT_YOY_DELTA:
        raise _fail(f"current YoY differs by {ratio_delta}", "CROSS_CHECK_MISMATCH")
    check = record["restatement_check"]
    return {
        "version": EVIDENCE_VERSION, "config_sha256": config_sha256, "record_id": record["id"],
        "symbol": record["symbol"], "issuer_short_name_zh": record["issuer"]["short_name_zh"],
        "applies_to_quarter_end": record["applies_to_quarter_end"],
        "previous_quarter_end": record["previous_quarter_end"],
        **{key: record[key] for key in ("currency", "unit", "unit_multiplier", "scope", "accounting_standard", "metric")},
        "documents": [dict(document) for document in record["documents"]],
        "previous_pair": {role: dict(previous[role]) for role in ("current", "prior_year")},
        "current_pair": {role: dict(current[role]) for role in ("current", "prior_year")},
        "restatement_check": {"status": check["status"], "document_id": check["document_id"],
                              "half_year_claims": {role: dict(check["half_year_claims"][role])
                                                   for role in ("current", "prior_year")},
                              "reconciliations": [dict(row) for row in check["reconciliations"]]},
        "cross_check": {"financial_currency": financial_currency, "max_overlap_delta_twd": MAX_OVERLAP_DELTA,
                        "max_current_yoy_ratio_delta": MAX_CURRENT_YOY_DELTA, **overlaps,
                        "current_yoy": {"official_ratio": official_ratio, "yahoo_ratio": float(current_yoy),
                                        "delta_ratio": ratio_delta}},
    }


def previous_yoy(record: dict[str, Any]) -> float:
    pair = record["previous_pair"]
    return pair["current"]["amount"] / pair["prior_year"]["amount"] - 1


@dataclass(frozen=True)
class Result:
    reason: str | None  # None on success, else one of REASONS
    revenue_yoy_prev: float | None = None
    source: dict[str, Any] | None = None


def evaluate(symbol: str, revenue: Mapping[Any, Any], financial_currency: Any, current_yoy: float | None,
             *, as_of: datetime, path: Path | None = None) -> Result:
    """The previous-quarter YoY from the official pair when the one record for this exact symbol and Yahoo quarter pair
    applies and every cross-check passes. The caller runs this only when Yahoo lacks the previous comparator."""
    try:
        records, digest = load(path, as_of)
    except RecordError as error:
        return Result(error.reason)
    matches = [record for record in records if record["symbol"] == symbol]
    if not matches:
        return Result("NO_RECORD")
    observed: dict[str, float] = {}
    for stamp, value in revenue.items():
        day = stamp.date().isoformat() if hasattr(stamp, "date") else str(stamp)[:10]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        observed[day] = float(value)
    ends = sorted(observed)
    if len(ends) < 2:
        return Result("PERIOD_MISMATCH")
    applicable = [record for record in matches
                  if record["applies_to_quarter_end"] == ends[-1] and record["previous_quarter_end"] == ends[-2]]
    if len(applicable) != 1:
        return Result("PERIOD_MISMATCH")
    record = applicable[0]
    if financial_currency != record["currency"]:
        return Result("CURRENCY_UNVERIFIED")
    try:
        source = evidence(record, digest, observed, current_yoy, financial_currency)
    except RecordError as error:
        return Result(error.reason)
    return Result(None, previous_yoy(record), source)


def _projection(value: Any, shape: Any) -> Any:
    """value reduced to the keys of shape (extra keys stripped at every level); lists keep their length."""
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return None
        return {key: _projection(value.get(key), sub) for key, sub in shape.items()}
    if isinstance(shape, list):
        if not isinstance(value, list) or len(value) != len(shape):
            return None
        return [_projection(item, sub) for item, sub in zip(value, shape)]
    return value


def seal_evidence(source: Any, *, symbol: str, quarter: Any, current_yoy: Any, prev_yoy: Any, as_of: datetime,
                  path: Path | None = None) -> dict[str, Any]:
    """Seal boundary: rebuild the evidence from the local config (same digest) and the observed Yahoo figures carried in
    source, require the allowlisted projection of source to equal it and the entry's figures to match; returns the
    rebuilt evidence (unknown fields dropped) or raises RecordError."""
    if not isinstance(source, dict) or source.get("version") != EVIDENCE_VERSION or source.get("symbol") != symbol:
        raise _fail("evidence version or symbol")
    records, digest = load(path, as_of)
    if source.get("config_sha256") != digest:
        raise _fail("evidence was built from a different config")
    matches = [record for record in records if record["symbol"] == symbol and record["applies_to_quarter_end"] == quarter
               and record["id"] == source.get("record_id")]
    if len(matches) != 1:
        raise _fail("no record for the entry's symbol and quarter")
    record = matches[0]
    cross = source.get("cross_check") if isinstance(source.get("cross_check"), dict) else {}
    observed = {}
    for name in ("current_current", "current_prior_year", "previous_current"):
        row = cross.get(name) if isinstance(cross.get(name), dict) else {}
        if isinstance(row.get("period_end"), str):
            observed[row["period_end"]] = row.get("yahoo_twd")
    currency = cross.get("financial_currency")
    if currency != record["currency"]:
        raise _fail("financial currency", "CURRENCY_UNVERIFIED")
    rebuilt = evidence(record, digest, observed, current_yoy, currency)
    if _projection(source, rebuilt) != rebuilt:
        raise _fail("evidence differs from the reviewed record")
    if (isinstance(prev_yoy, bool) or not isinstance(prev_yoy, (int, float)) or not math.isfinite(prev_yoy)
            or abs(prev_yoy - previous_yoy(record)) > PREV_YOY_TOLERANCE):
        raise _fail("previous YoY is not the official pair's")
    return rebuilt
