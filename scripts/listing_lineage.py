"""Listing lineage and the long-term return that respects it (operator 2026-09-27: Sandisk is not a new company; Astra
contract "Top20 price-history lineage").

A company's age, the trading segment of its current security and the vendor's price history are different facts. A
listing whose standalone history is shorter than the three-year request because of a corporate event (spin-off, trading
resumption, IPO, new equity after a reorganisation) is described by a curated record in config/listing-lineage-v1.json,
every field backed by a primary source. Returns use only this security's prices from its first regular-way session (never
when-issued trading, never a parent's or predecessor's shares); no two-year figure is fabricated from a shorter segment.
Without a verified record a late first bar is shown neutrally ("price data from <date>; lineage not verified"), never as a
new company, and is not annualized.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "listing-lineage-v1.json"

KINDS = ("SPINOFF", "RESUMPTION", "IPO", "NEW_EQUITY")
BASES = ("TWO_YEAR", "SINCE_REGULAR_WAY", "UNAVAILABLE")
CLAIMS = ("kind", "event_date", "regular_way_start", "related_entity")
REQUIRED_CLAIMS = ("kind", "event_date", "regular_way_start")
MAX_EVENT_TO_TRADING_DAYS = 60     # legal event to first regular-way session (a spin-off's distribution, an IPO's pricing)
SESSION_TOLERANCE_DAYS = 7         # a first bar this late after the request start is still an ordinary session start
MIN_ANNUALIZE_DAYS = 365           # shorter segments are never annualized
TWO_YEARS_DAYS = 730
MAX_SOURCES = 4
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")


def parse_date(value: Any) -> date | None:
    """A real ASCII YYYY-MM-DD date, else None."""
    if not isinstance(value, str) or not _DATE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _text(value: Any, low: int, high: int) -> str | None:
    return value if isinstance(value, str) and low <= len(value.strip()) <= high else None


def clean_record(raw: Any) -> dict[str, Any] | None:
    """The allowlisted lineage record, or None when anything is malformed, inconsistent or not covered by a source."""
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    event, start = parse_date(raw.get("event_date")), parse_date(raw.get("regular_way_start"))
    if event is None or start is None or not timedelta(0) <= start - event <= timedelta(days=MAX_EVENT_TO_TRADING_DAYS):
        return None
    related = raw.get("related_entity")
    if raw["kind"] == "IPO":
        if related is not None:  # an IPO has no parent or predecessor security to name
            return None
        entity = None
    else:
        if not isinstance(related, dict) or not _text(related.get("name"), 1, 80):
            return None
        symbol = related.get("symbol")
        if symbol is not None and not (isinstance(symbol, str) and _SYMBOL.match(symbol)):
            return None
        entity = {"name": related["name"].strip(), "symbol": symbol}
    sources = raw.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
        return None
    clean_sources, covered = [], set()
    for source in sources:
        if not isinstance(source, dict):
            return None
        url, published = source.get("url"), parse_date(source.get("published_at"))
        claims, evidence = source.get("claims"), _text(source.get("evidence"), 10, 400)
        if not (isinstance(url, str) and url.startswith("https://") and len(url) <= 400) or published is None or not evidence \
                or not isinstance(claims, list) or not claims or any(claim not in CLAIMS for claim in claims):
            return None
        covered.update(claims)
        clean_sources.append({"url": url, "published_at": source["published_at"], "claims": sorted(set(claims), key=CLAIMS.index),
                              "evidence": evidence.strip()})
    if not set(REQUIRED_CLAIMS) <= covered or (entity is not None and "related_entity" not in covered):
        return None
    return {"kind": raw["kind"], "event_date": raw["event_date"], "regular_way_start": raw["regular_way_start"],
            "related_entity": entity, "sources": clean_sources}


def load(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """The curated records by Yahoo symbol. The file is hand-curated: a malformed record raises instead of being skipped."""
    document = json.loads((path or CONFIG).read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not isinstance(document.get("listings"), dict):
        raise ValueError("LISTING_LINEAGE_SCHEMA")
    records = {}
    for symbol, raw in document["listings"].items():
        record = clean_record(raw)
        if record is None:
            raise ValueError(f"LISTING_LINEAGE_RECORD {symbol}")
        records[symbol] = record
    return records


def request_start(asof: date, years: int = 3) -> date:
    """The first day of a `years`-year history request ending on `asof` (29 February falls back to the 28th)."""
    try:
        return asof.replace(year=asof.year - years)
    except ValueError:
        return asof.replace(year=asof.year - years, day=28)


def annualize(base: float, end: float, days: int) -> float | None:
    if not (math.isfinite(base) and math.isfinite(end)) or base <= 0 or end <= 0 or days < MIN_ANNUALIZE_DAYS:
        return None
    try:
        value = (end / base) ** (365.25 / days) - 1
    except (OverflowError, ZeroDivisionError):
        return None
    return value if math.isfinite(value) else None


def _finite(value: float | None) -> float | None:
    """A computed return is finite or None: vendor extremes must not leak out as inf, NaN or a crash."""
    return value if value is not None and math.isfinite(value) else None


def long_term_returns(bars: Iterable[tuple[date, float]], lineage: dict[str, Any] | None, requested_from: date) -> dict[str, Any]:
    """Returns over this security's eligible daily closes (date, adjusted close), respecting a verified lineage record.

    ret_6m / ret_1y / cagr_2y as before (the close on or before the horizon, the segment long enough); cagr_listed only for
    a verified record whose first regular-way session is in the data, over at least MIN_ANNUALIZE_DAYS, when no two-year
    figure exists. long_term_basis says which (TWO_YEAR, SINCE_REGULAR_WAY or UNAVAILABLE)."""
    clean = sorted((day, float(close)) for day, close in bars
                   if isinstance(close, (int, float)) and math.isfinite(float(close)) and float(close) > 0)
    start = parse_date(lineage["regular_way_start"]) if lineage else None
    eligible = [(day, close) for day, close in clean if start is None or day >= start]
    out: dict[str, Any] = {"history_start": str(clean[0][0]) if clean else None, "history_request_start": str(requested_from),
                           "lineage": lineage or {"kind": "UNKNOWN"}, "ret_6m": None, "ret_1y": None, "cagr_2y": None,
                           "cagr_listed": None, "cagr_listed_start": None, "cagr_listed_span_days": None,
                           "long_term_basis": "UNAVAILABLE"}
    out["history_truncated"] = truncated(out["history_start"], out["history_request_start"])
    if not eligible:
        return out
    first_day, last_day, last = eligible[0][0], eligible[-1][0], eligible[-1][1]
    out.update(asof=str(last_day), price=last)

    def back(days: int) -> float | None:
        target = last_day - timedelta(days=days)
        window = [close for day, close in eligible if day <= target]
        return window[-1] if window else None
    for label, days in (("ret_6m", 182), ("ret_1y", 365), ("ret_2y", TWO_YEARS_DAYS)):
        base = back(days)
        try:
            out[label] = _finite(last / base - 1) if base and (last_day - first_day).days >= days - 5 else None
        except (OverflowError, ZeroDivisionError):
            out[label] = None
    two = out.pop("ret_2y")
    try:
        out["cagr_2y"] = _finite((1 + two) ** 0.5 - 1) if two is not None and two > -1 else None
    except (OverflowError, ZeroDivisionError):
        out["cagr_2y"] = None
    if out["cagr_2y"] is not None:
        out["long_term_basis"] = "TWO_YEAR"
    elif start is not None and first_day == start:
        span = (last_day - first_day).days
        value = annualize(eligible[0][1], last, span)
        if value is not None:
            out.update(cagr_listed=value, cagr_listed_start=str(first_day), cagr_listed_span_days=span,
                       long_term_basis="SINCE_REGULAR_WAY")
    return out


def truncated(history_start: str | None, requested_from: str | None) -> bool:
    """True when the vendor's first bar is later than an ordinary session start after the request start."""
    first, wanted = parse_date(history_start), parse_date(requested_from)
    return first is not None and wanted is not None and (first - wanted).days > SESSION_TOLERANCE_DAYS


TWO_YEAR_MIN_DAYS = TWO_YEARS_DAYS - 5   # the two-year return needs this much eligible history (long_term_returns)
FUTURE_TOLERANCE_DAYS = 1                 # a market date may be at most this far after the report date


def clean_market_lineage(market: dict[str, Any], report_day: date | None = None) -> dict[str, Any]:
    """The sealed long-term fields of one market object (cagr_2y included): validated, temporally consistent, allowlisted.

    An older producer's object WITHOUT the fields keeps only its two-year value and stays without them on the wire (the
    Worker applies the same legacy rule; resealing is idempotent). PRESENT but malformed or contradictory metadata
    suppresses every long-term figure (no cagr_2y either): UNKNOWN lineage, UNAVAILABLE basis."""
    two = market.get("cagr_2y")
    two = two if isinstance(two, (int, float)) and not isinstance(two, bool) and math.isfinite(two) else None
    empty = {"lineage": {"kind": "UNKNOWN"}, "history_request_start": None, "cagr_listed": None, "cagr_listed_start": None,
             "cagr_listed_span_days": None}
    if "lineage" not in market and "long_term_basis" not in market:
        return {"cagr_2y": two}  # legacy: no since-listing figure, no metadata invented
    invalid = {**empty, "cagr_2y": None, "long_term_basis": "UNAVAILABLE"}
    raw = market.get("lineage")
    lineage = {"kind": "UNKNOWN"} if raw == {"kind": "UNKNOWN"} else clean_record(raw)
    asof, requested = parse_date(market.get("asof")), parse_date(market.get("history_request_start"))
    if lineage is None or asof is None or requested is None or requested > asof \
            or (report_day is not None and asof > report_day + timedelta(days=FUTURE_TOLERANCE_DAYS)):
        return invalid
    known = lineage["kind"] != "UNKNOWN"
    regular = parse_date(lineage["regular_way_start"]) if known else None
    if regular is not None and regular > asof:
        return invalid
    segment_start = regular if known else parse_date(market.get("history_start"))
    basis = market.get("long_term_basis")
    listed, since, span = market.get("cagr_listed"), market.get("cagr_listed_start"), market.get("cagr_listed_span_days")
    nothing_listed = listed is None and since is None and span is None
    if basis == "TWO_YEAR":
        consistent = two is not None and nothing_listed and segment_start is not None \
            and (asof - segment_start).days >= TWO_YEAR_MIN_DAYS
    elif basis == "UNAVAILABLE":
        consistent = two is None and nothing_listed
    elif basis == "SINCE_REGULAR_WAY":
        consistent = (two is None and known and since == lineage["regular_way_start"]
                      and isinstance(listed, (int, float)) and not isinstance(listed, bool) and math.isfinite(listed) and listed > -1
                      and isinstance(span, int) and not isinstance(span, bool) and span >= MIN_ANNUALIZE_DAYS
                      and span == (asof - regular).days)
    else:
        consistent = False
    if not consistent:
        return invalid
    return {"lineage": lineage, "history_request_start": market["history_request_start"], "cagr_2y": two,
            "cagr_listed": listed, "cagr_listed_start": since, "cagr_listed_span_days": span, "long_term_basis": basis}
