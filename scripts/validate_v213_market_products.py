#!/usr/bin/env python3
"""
Validator for v2.1.3 Market Products (Macro Industry & Options).
Verifies evidence integrity, math, schemas, and safety boundaries:
- Strict finite numeric types (no string/bool coercion).
- Calendar dates and period formats.
- Source binding (source_id, URL or substantial passage required).
- Rejection of company-count percentage as market growth.
- Stale and future timestamp rejection.
- Midpoint and spread integrity.
- Prohibition of caller-supplied payoff metrics on bare quotes.
- Currency USD, multiplier 100, rights_status label FORMAT only. These validators are format checks for local
   candidate data: a rights label never admits a row for public display (scripts/public_options_provider_gate.py decides).
- Expiry calendar DTE consistency & expired contract rejection.
"""

import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


class MarketProductValidationError(Exception):
    pass


VALID_PERIOD_RE = re.compile(r"^(?:\d{4}|\d{4}-\d{4}|\d{4}\s*Q[1-4])$", re.IGNORECASE)
VALID_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?$")
ISO_INSTANT_RE = re.compile(
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)


def validate_growth_rate(growth: dict, evaluated_at: str | None = None) -> None:
    if not isinstance(growth, dict):
        raise MarketProductValidationError("GROWTH_RATE_MUST_BE_DICT")

    rate_pct = growth.get("rate_pct")
    if rate_pct is None or isinstance(rate_pct, bool) or not isinstance(rate_pct, (int, float)) or not math.isfinite(rate_pct):
        raise MarketProductValidationError("INVALID_RATE_PCT")

    units = str(growth.get("units", "")).strip()
    if not units:
        raise MarketProductValidationError("MISSING_GROWTH_UNITS")

    period = str(growth.get("period", "")).strip()
    if not period or not VALID_PERIOD_RE.match(period):
        raise MarketProductValidationError("INVALID_GROWTH_PERIOD")

    growth_type = growth.get("type")
    if growth_type not in ("forecast", "actual"):
        raise MarketProductValidationError("GROWTH_TYPE_MUST_BE_FORECAST_OR_ACTUAL")

    publisher = str(growth.get("publisher", "")).strip()
    if not publisher:
        raise MarketProductValidationError("MISSING_GROWTH_PUBLISHER")

    date = str(growth.get("date", "")).strip()
    if not date or not VALID_DATE_RE.match(date):
        raise MarketProductValidationError("INVALID_GROWTH_DATE")

    # Future growth date check
    eval_str = evaluated_at[:10] if evaluated_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    norm_date = f"{date}-12-31" if len(date) == 4 else f"{date}-28" if len(date) == 7 else date
    if norm_date > eval_str:
        raise MarketProductValidationError("FUTURE_GROWTH_DATE_REJECTED")

    # Reject company-count percentage masquerading as market growth
    units_lower = units.lower()
    passage_lower = str(growth.get("raw_passage", "")).lower()
    for forbidden in ["company", "companies", "ticker", "家數", "候選家數", "candidates percentage"]:
        if forbidden in units_lower or forbidden in passage_lower:
            raise MarketProductValidationError(f"COMPANY_COUNT_PERCENTAGE_FORBIDDEN_AS_MARKET_GROWTH: {forbidden}")

    # Require verifiable source_id lineage binding
    source_id = str(growth.get("source_id", "")).strip()
    if not source_id:
        raise MarketProductValidationError("UNADMITTED_GROWTH_SOURCE")

    # Require verifiable source binding (URL or substantial passage)
    url = str(growth.get("url", "")).strip()
    passage = str(growth.get("raw_passage", "")).strip()
    has_valid_url = url.startswith("http://") or url.startswith("https://")
    has_valid_passage = len(passage) >= 10
    if not has_valid_url and not has_valid_passage:
        raise MarketProductValidationError("SOURCE_BINDING_REQUIRED")


def validate_macro_overview(overview: dict) -> None:
    if not isinstance(overview, dict):
        raise MarketProductValidationError("OVERVIEW_MUST_BE_DICT")
    if overview.get("title") != "TOP5產業總覽":
        raise MarketProductValidationError("TITLE_MUST_BE_TOP5產業總覽")
    horizon = overview.get("horizon")
    if not horizon or "12" not in str(horizon):
        raise MarketProductValidationError("HORIZON_MUST_CONTAIN_12_36M")

    industries = overview.get("industries", [])
    if not isinstance(industries, list):
        raise MarketProductValidationError("INDUSTRIES_MUST_BE_LIST")

    qualified_count = overview.get("qualified_count", len(industries))
    shortfall = overview.get("shortfall", max(0, 5 - qualified_count))

    if qualified_count < 5:
        if overview.get("status") == "ADMITTED_TOP5":
            raise MarketProductValidationError("STATUS_CANNOT_BE_ADMITTED_IF_QUALIFIED_LESS_THAN_5")
        if not overview.get("shortfall_report"):
            raise MarketProductValidationError("SHORTFALL_REPORT_REQUIRED_WHEN_UNDER_FIVE")
    else:
        if shortfall != 0:
            raise MarketProductValidationError("SHORTFALL_MUST_BE_ZERO_WHEN_AT_LEAST_FIVE")

    for idx, ind in enumerate(industries):
        rank = ind.get("rank")
        if rank is not None and rank != idx + 1:
            raise MarketProductValidationError(f"INVALID_RANK: expected {idx + 1}, got {rank}")
        score = ind.get("opportunity_score", 0)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not (0 <= score <= 100):
            raise MarketProductValidationError(f"OPPORTUNITY_SCORE_OUT_OF_BOUNDS: {score}")
        growth = ind.get("growth")
        if growth:
            validate_growth_rate(growth)


def validate_educational_strategy(card: dict) -> None:
    if not isinstance(card, dict):
        raise MarketProductValidationError("STRATEGY_CARD_MUST_BE_DICT")
    strat_id = card.get("strategy_id")
    if strat_id not in ("covered_call", "cash_secured_put", "bull_call_spread", "protective_put"):
        raise MarketProductValidationError(f"UNKNOWN_STRATEGY_ID: {strat_id}")
    if card.get("disclaimer") != "教學範例，非推薦":
        raise MarketProductValidationError("MANDATORY_DISCLAIMER_MISSING")
    if card.get("status") != "SYNTHETIC_EDUCATIONAL":
        raise MarketProductValidationError("MANDATORY_SYNTHETIC_MARKER_MISSING")

    # Specific strategy checks
    if strat_id == "protective_put":
        maxprofit = str(card.get("maxprofit", ""))
        if "UNBOUNDED" not in maxprofit:
            raise MarketProductValidationError("PROTECTIVE_PUT_MAXPROFIT_MUST_BE_UNBOUNDED")
    if strat_id == "cash_secured_put":
        collateral = card.get("assumptions", {}).get("collateral", "")
        if "全額現金" not in collateral and "100%" not in collateral and "cash" not in collateral.lower():
            raise MarketProductValidationError("CSP_COLLATERAL_ASSUMPTION_MISSING")
    if strat_id == "covered_call":
        collateral = card.get("assumptions", {}).get("collateral", "")
        if "現股" not in collateral and "underlying" not in collateral.lower():
            raise MarketProductValidationError("COVERED_CALL_COLLATERAL_ASSUMPTION_MISSING")


def validate_option_quote(quote: dict, evaluated_at: str | None = None) -> None:
    if not isinstance(quote, dict):
        raise MarketProductValidationError("QUOTE_MUST_BE_DICT")

    for field in ["strike", "dte", "bid", "ask", "mid"]:
        val = quote.get(field)
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            raise MarketProductValidationError(f"STRICT_FINITE_NUMBER_REQUIRED: {field}")

    bid = quote["bid"]
    ask = quote["ask"]
    mid = quote["mid"]

    if bid < 0 or ask < 0:
        raise MarketProductValidationError("NEGATIVE_BID_OR_ASK_FORBIDDEN")
    if ask < bid:
        raise MarketProductValidationError("CROSSED_QUOTE_BID_EXCEEDS_ASK")
    if abs(mid - (bid + ask) / 2) > 0.001:
        raise MarketProductValidationError(f"MID_MUST_EQUAL_BID_ASK_AVERAGE: expected {(bid+ask)/2}, got {mid}")

    # Finding A: Prohibition of caller-supplied payoff metrics on bare quotes
    if (
        quote.get("breakeven") is not None
        or quote.get("maxprofit") is not None
        or quote.get("maxloss") is not None
        or quote.get("annualized_yield") is not None
    ):
        raise MarketProductValidationError("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED")

    # Finding C: Currency, multiplier, source, provenance, rights_status
    if quote.get("currency") not in ("USD", "SEK"):  # US-listed and Nasdaq Stockholm options
        raise MarketProductValidationError("INVALID_CURRENCY")
    if quote.get("multiplier") != 100:
        raise MarketProductValidationError("INVALID_MULTIPLIER")
    if not str(quote.get("source", "")).strip():
        raise MarketProductValidationError("MISSING_QUOTE_SOURCE")
    if not str(quote.get("provenance", "")).strip():
        raise MarketProductValidationError("MISSING_QUOTE_PROVENANCE")
    if quote.get("rights_status") not in (
        "reviewed_public_access",
        "candidate_local_review",
        "unadmitted_third_party",
        "review_before_enable",
        "automated_access_prohibited",
    ):
        raise MarketProductValidationError("INVALID_RIGHTS_STATUS")

    # Verify missing Greeks and volume are not coerced to zero
    delta = quote.get("delta")
    if delta is not None and (isinstance(delta, bool) or not isinstance(delta, (int, float)) or not (-1.0 <= delta <= 1.0)):
        raise MarketProductValidationError(f"DELTA_OUT_OF_RANGE: {delta}")

    # Timestamp format and freshness
    ts_str = str(quote.get("timestamp", "")).strip()
    if not ts_str or not ISO_INSTANT_RE.match(ts_str):
        raise MarketProductValidationError("INVALID_QUOTE_TIMESTAMP")

    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    eval_dt = (
        datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
        if evaluated_at
        else datetime.now(timezone.utc)
    )
    diff_sec = (dt - eval_dt).total_seconds()
    if diff_sec > 300:
        raise MarketProductValidationError("FUTURE_TIMESTAMP_REJECTED")

    quote_basis = quote.get("quote_basis", "delayed")
    age_sec = (eval_dt - dt).total_seconds()
    if quote_basis == "realtime" and age_sec > 900:
        raise MarketProductValidationError("STALE_TIMESTAMP_REJECTED")
    elif quote_basis == "delayed" and age_sec > 3600:
        raise MarketProductValidationError("STALE_TIMESTAMP_REJECTED")
    elif age_sec > 345600:
        raise MarketProductValidationError("STALE_TIMESTAMP_REJECTED")

    # Calendar DTE & Expired check
    expiry_str = quote.get("expiry")
    if expiry_str:
        exp_dt = datetime.fromisoformat(expiry_str + "T00:00:00+00:00")
        eval_dt_midnight = eval_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if exp_dt < eval_dt_midnight:
            raise MarketProductValidationError("EXPIRED_CONTRACT_REJECTED")
        calendar_dte = round((exp_dt - eval_dt_midnight).total_seconds() / 86400)
        if calendar_dte < 0:
            raise MarketProductValidationError("EXPIRED_CONTRACT_REJECTED")
        if abs(quote["dte"] - calendar_dte) > 1:
            raise MarketProductValidationError("EXPIRY_DTE_INCONSISTENT")


# The high-strike suggestion's assignment cap (scripts/build_market_quotes_options.py MAX_HIGH_STRIKE_DELTA).
MAX_HIGH_STRIKE_DELTA = 0.20
# Producer DTE buckets for the requested cycle window (scripts/build_market_quotes_options.py): a weekly/monthly request
# must carry a DTE inside its own bucket. Not a third-Friday calendar classification.
PERIOD_DTE_BUCKETS = {"weekly": (3, 14), "monthly": (21, 45)}


def validate_covered_call_cycle(cycle: dict, evaluated_at: str | datetime | None = None, document_at: str | datetime | None = None,
                                period: str | None = None) -> None:
    """Covered-call sell suggestions for one underlying and cycle (scripts/build_market_quotes_options.py): out-of-the-money
    strikes with two-sided quotes, a limit between bid and mid, and every derived figure consistent with the prices."""
    def finite(value, name):
        # Strict finite scalar, robust to every out-of-range numeric *representation*, not just one spelling. Reject
        # bool/str/collections up front, then convert to float inside a guard so an out-of-float-range magnitude in
        # either JSON form maps to the per-cycle domain error rather than escaping: an exponent literal (1e309) parses
        # to inf and is caught by math.isfinite below, while a bare big-integer literal (10**309) is a valid Python int
        # whose float() raises OverflowError -- previously an uncaught crash that neither the per-cycle nor the outer
        # publisher handler swallowed. ValueError/TypeError are translated for the same reason; NaN/inf fail isfinite.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MarketProductValidationError(f"STRICT_FINITE_NUMBER_REQUIRED: {name}")
        try:
            number = float(value)
        except (OverflowError, ValueError, TypeError) as error:
            raise MarketProductValidationError(f"STRICT_FINITE_NUMBER_REQUIRED: {name}") from error
        if not math.isfinite(number):
            raise MarketProductValidationError(f"STRICT_FINITE_NUMBER_REQUIRED: {name}")
        return number

    if not isinstance(cycle, dict) or cycle.get("strategy") != "COVERED_CALL":
        raise MarketProductValidationError("COVERED_CALL_CYCLE_INVALID")
    if cycle.get("currency") not in ("USD", "SEK") or cycle.get("multiplier") != 100 or cycle.get("quote_basis") != "delayed":
        raise MarketProductValidationError("COVERED_CALL_CONTRACT_TERMS_INVALID")
    if not str(cycle.get("source", "")).strip() or not str(cycle.get("provenance", "")).startswith("https://"):
        raise MarketProductValidationError("MISSING_QUOTE_PROVENANCE")

    # Row timestamp validation: robust UTC instant, no future, max 5h publisher age, document tolerance
    ts_str = str(cycle.get("timestamp", "")).strip()
    if not ts_str or not ISO_INSTANT_RE.match(ts_str) or not ts_str.endswith("Z"):
        raise MarketProductValidationError("INVALID_QUOTE_TIMESTAMP")
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError as error:
        raise MarketProductValidationError("INVALID_QUOTE_TIMESTAMP") from error

    if isinstance(evaluated_at, datetime):
        eval_dt = evaluated_at if evaluated_at.tzinfo else evaluated_at.replace(tzinfo=timezone.utc)
    elif isinstance(evaluated_at, str):
        try:
            eval_dt = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise MarketProductValidationError("INVALID_EVALUATION_TIMESTAMP") from error
    else:
        eval_dt = datetime.now(timezone.utc)

    # Publisher policy: no future timestamp allowed
    if dt > eval_dt:
        raise MarketProductValidationError("FUTURE_TIMESTAMP_REJECTED")

    # Publisher max observation age: 5 hours
    if (eval_dt - dt).total_seconds() > 5 * 3600:
        raise MarketProductValidationError("STALE_TIMESTAMP_REJECTED")

    # Row time cannot be later than document time beyond 5 min (300s) tolerance
    if document_at is not None:
        if isinstance(document_at, datetime):
            doc_dt = document_at if document_at.tzinfo else document_at.replace(tzinfo=timezone.utc)
        elif isinstance(document_at, str):
            try:
                doc_dt = datetime.fromisoformat(document_at.replace("Z", "+00:00"))
            except ValueError as error:
                raise MarketProductValidationError("INVALID_DOCUMENT_TIMESTAMP") from error
        else:
            doc_dt = None
        if doc_dt and (dt - doc_dt).total_seconds() > 300:
            raise MarketProductValidationError("ROW_TIMESTAMP_LATER_THAN_DOCUMENT")

    dte = cycle.get("dte")
    if not isinstance(dte, int) or isinstance(dte, bool) or not 1 <= dte <= 60:
        raise MarketProductValidationError("INVALID_DTE")
    if period is not None:
        bucket = PERIOD_DTE_BUCKETS.get(period)
        if bucket is not None and not bucket[0] <= dte <= bucket[1]:
            raise MarketProductValidationError("DTE_OUTSIDE_PERIOD_BUCKET")
    try:
        expiry = datetime.strptime(str(cycle.get("expiry")), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise MarketProductValidationError("INVALID_EXPIRY_FORMAT") from error
    if expiry.date() < eval_dt.date():
        raise MarketProductValidationError("EXPIRED_CONTRACT_REJECTED")
    if evaluated_at:
        if abs((expiry.date() - eval_dt.date()).days - dte) > 1:
            raise MarketProductValidationError("EXPIRY_DTE_INCONSISTENT")
    spot = finite(cycle.get("spot"), "spot")
    suggestions = cycle.get("suggestions")
    if not isinstance(suggestions, list) or not 1 <= len(suggestions) <= 2:
        raise MarketProductValidationError("COVERED_CALL_SUGGESTION_COUNT")
    if not all(isinstance(item, dict) for item in suggestions):
        raise MarketProductValidationError("COVERED_CALL_SUGGESTION_SHAPE")
    roles = [item.get("role") for item in suggestions]
    if roles not in (["HIGH_STRIKE"], ["HIGH_STRIKE", "BALANCED"]):
        raise MarketProductValidationError("COVERED_CALL_ROLES")
    for item in suggestions:
        strike, bid, ask, mid, limit = (finite(item.get(key), key) for key in ("strike", "bid", "ask", "mid", "limit_price"))
        if not strike > spot > 0:
            raise MarketProductValidationError("COVERED_CALL_STRIKE_NOT_OUT_OF_THE_MONEY")
        if not 0 < bid <= ask or abs(mid - (bid + ask) / 2) > 0.001 or not bid - 1e-9 <= limit <= mid + 1e-9:
            raise MarketProductValidationError("COVERED_CALL_PRICES_INCONSISTENT")
        checks = {"premium_per_contract": limit * 100, "period_yield": limit / spot,
                  "annualized_yield": limit / spot * 365 / dte, "upside_to_strike": strike / spot - 1}
        for key, expected in checks.items():
            if abs(finite(item.get(key), key) - expected) > max(1e-4, abs(expected) * 1e-3):
                raise MarketProductValidationError(f"COVERED_CALL_DERIVED_MISMATCH: {key}")
        delta = item.get("delta")
        if delta is not None and not 0 <= finite(delta, "delta") <= 1:
            raise MarketProductValidationError("INVALID_DELTA_RANGE")
        if item.get("role") == "HIGH_STRIKE" and (delta is None or finite(delta, "delta") > MAX_HIGH_STRIKE_DELTA):
            raise MarketProductValidationError("COVERED_CALL_HIGH_STRIKE_DELTA_ABOVE_LIMIT")
        if item.get("delta_basis") not in (None, "QUOTED", "QUOTED_IV", "QUOTE_IMPLIED"):
            raise MarketProductValidationError("INVALID_DELTA_BASIS")
        if item.get("iv") is not None and not finite(item["iv"], "iv") > 0:
            raise MarketProductValidationError("INVALID_IMPLIED_VOLATILITY")
        # Optional liquidity/spread fields, when supplied, must be a finite non-negative number (amendment-02): a
        # nonfinite value in any representation (exponent JSON 1e309 -> inf, or a bare big-integer JSON 10**309 that
        # overflows float()), a wrong type (bool/str/collection) or a negative raises the per-cycle domain error here,
        # so publish_sealed_snapshot marks only this cycle unavailable and healthy siblings/quotes survive instead of
        # allow_nan=False collapsing the whole document or an OverflowError crashing it. A legitimate null/missing stays unknown.
        for key in ("oi", "volume", "spread_pct"):
            value = item.get(key)
            if value is not None and finite(value, key) < 0:
                raise MarketProductValidationError(f"INVALID_LIQUIDITY_FIELD: {key}")
    if len(suggestions) == 2 and not suggestions[0]["strike"] > suggestions[1]["strike"]:
        raise MarketProductValidationError("COVERED_CALL_HIGH_STRIKE_NOT_HIGHER")


COVERAGE_SCHEMA = "v213-options-coverage-v1"
COVERAGE_PURPOSE = "SOURCE_COVERAGE_METADATA_ONLY"
COVERAGE_OPTIONS_KEY = "v213:options:v2"
MAX_COVERAGE_BODY_BYTES = 200_000
COVERAGE_NOTES = frozenset({
    "CATALOG_COUNT_IS_NOT_INDEPENDENT_CONFIRMATION", "DECLARED_IS_NOT_COLLECTED_OR_LIVE", "EOD_INDEX_AND_DELTA_NOT_ADMITTED_BY_THIS_VIEW",
    "NO_RAW_QUOTES_IN_THIS_OBJECT", "ORIGIN_LINEAGE_UNKNOWN_NO_CORROBORATION_METRIC", "UNCATALOGUED_JURISDICTIONS_ARE_NOT_COVERAGE",
})
_COVERAGE_RIGHTS = frozenset({"review_before_enable", "reviewed_public_access", "automated_access_prohibited"})
_COVERAGE_ADAPTERS = frozenset({"not_implemented", "candidate_implemented", "adapter_reviewed", "not_permitted"})
_COVERAGE_ID = re.compile(r"[a-z0-9_]{1,64}")
_COVERAGE_CODE = re.compile(r"[A-Z0-9_]{1,12}")
_COVERAGE_VENUE = re.compile(r"[A-Z0-9][A-Z0-9_.-]{0,31}")
_COVERAGE_HEX = re.compile(r"[0-9a-f]{64}")


_COVERAGE_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z")


def coverage_instant(value) -> bool:
    """The G1 canonical UTC instant: seconds or exactly three fractional digits (length 20 or 24), a REAL calendar date and time (no
    February 30, no year 0000: datetime accepts years 1..9999 only). Scoped to the G1 object; older product validators are unchanged."""
    if not isinstance(value, str) or len(value) not in (20, 24) or _COVERAGE_INSTANT.fullmatch(value) is None:
        return False
    try:
        datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def validate_options_coverage_document(doc: dict) -> None:
    """FORMAT validation of the PUBLIC, METADATA-ONLY global options source/gap object (sealed lazy key v213:options-coverage:v1; mirror of
    cloud/src/v213/options-coverage.ts validateOptionsCoverage). Exact closed keys at every level, fixed vocabularies and declared row,
    string and byte bounds; no strike/bid/ask/settlement/Delta/premium or private field can exist because no such key is allowed. This is
    NOT a rights decision and no label in it admits anything: the Worker re-verifies against its own canonical catalog and policy."""
    def fail(code: str):
        raise MarketProductValidationError(code)

    def exact(value, keys, code):
        if not isinstance(value, dict) or set(value) != set(keys):
            fail(code)

    def text(value, maximum):
        return isinstance(value, str) and 1 <= len(value) <= maximum and not any(ord(ch) < 32 for ch in value)

    def pattern_list(value, pattern, low, high, code):
        if not isinstance(value, list) or not low <= len(value) <= high or not all(isinstance(item, str) and pattern.fullmatch(item) for item in value):
            fail(code)
        return value

    def instant(value):
        return coverage_instant(value)

    exact(doc, ("schema", "generated_at", "purpose", "options_link", "catalog_summary", "providers", "jurisdictions", "local_capabilities",
                "observed", "data_completeness", "notes"), "COVERAGE_SCHEMA_INVALID")
    if (doc["schema"] != COVERAGE_SCHEMA or doc["purpose"] != COVERAGE_PURPOSE or doc["data_completeness"] != "NOT_REAUDITED"
            or not instant(doc["generated_at"])):
        fail("COVERAGE_HEADER_INVALID")
    link = doc["options_link"]
    if link is not None:
        exact(link, ("key", "sha256", "utf8_bytes"), "COVERAGE_LINK_INVALID")
        if (link["key"] != COVERAGE_OPTIONS_KEY or not isinstance(link["sha256"], str) or not _COVERAGE_HEX.fullmatch(link["sha256"])
                or type(link["utf8_bytes"]) is not int or not 1 <= link["utf8_bytes"] <= 1_900_000):
            fail("COVERAGE_LINK_INVALID")
    summary = doc["catalog_summary"]
    exact(summary, ("catalog_provider_count", "public_admitted_provider_count", "production_provider_selected"), "COVERAGE_SUMMARY_INVALID")
    for key in ("catalog_provider_count", "public_admitted_provider_count"):
        if type(summary[key]) is not int or not 0 <= summary[key] <= 32:
            fail("COVERAGE_SUMMARY_INVALID")
    if type(summary["production_provider_selected"]) is not bool:
        fail("COVERAGE_SUMMARY_INVALID")
    notes = doc["notes"]
    if not isinstance(notes, list) or len(notes) > 8 or len(set(notes)) != len(notes) or not all(isinstance(note, str) and note in COVERAGE_NOTES for note in notes):
        fail("COVERAGE_NOTES_INVALID")
    for key, limit in (("providers", 32), ("jurisdictions", 32), ("local_capabilities", 8), ("observed", 64)):
        if not isinstance(doc[key], list) or len(doc[key]) > limit:
            fail("COVERAGE_BOUNDS_INVALID")
    provider_ids = []
    for row in doc["providers"]:
        exact(row, ("provider_id", "name", "authority", "jurisdictions", "data_roles", "rights_status", "rights_reviewed_at", "adapter_status",
                    "runtime_enabled", "line_quote_eligible", "public_admission", "declared"), "COVERAGE_PROVIDER_INVALID")
        pattern_list(row["jurisdictions"], _COVERAGE_CODE, 1, 8, "COVERAGE_PROVIDER_INVALID")
        pattern_list(row["data_roles"], _COVERAGE_ID, 1, 8, "COVERAGE_PROVIDER_INVALID")
        reviewed = row["rights_reviewed_at"]
        if reviewed is not None:
            try:
                datetime.strptime(reviewed, "%Y-%m-%d")
            except (TypeError, ValueError):
                fail("COVERAGE_PROVIDER_INVALID")
        if (not isinstance(row["provider_id"], str) or not _COVERAGE_ID.fullmatch(row["provider_id"]) or not text(row["name"], 120)
                or not text(row["authority"], 120) or row["rights_status"] not in _COVERAGE_RIGHTS or row["adapter_status"] not in _COVERAGE_ADAPTERS
                or type(row["runtime_enabled"]) is not bool or type(row["line_quote_eligible"]) is not bool
                or row["public_admission"] not in ("ADMITTED", "NOT_ADMITTED") or row["declared"] != "CATALOG_DECLARED_UNVERIFIED"):
            fail("COVERAGE_PROVIDER_INVALID")
        provider_ids.append(row["provider_id"])
    if len(set(provider_ids)) != len(provider_ids):
        fail("COVERAGE_PROVIDER_INVALID")
    for row in doc["jurisdictions"]:
        exact(row, ("code", "provider_ids", "catalog_provider_count"), "COVERAGE_JURISDICTION_INVALID")
        ids = pattern_list(row["provider_ids"], _COVERAGE_ID, 1, 32, "COVERAGE_JURISDICTION_INVALID")
        if (not isinstance(row["code"], str) or not _COVERAGE_CODE.fullmatch(row["code"]) or row["catalog_provider_count"] != len(ids)
                or type(row["catalog_provider_count"]) is not int):
            fail("COVERAGE_JURISDICTION_INVALID")
    # The jurisdiction -> unique provider-id relation must be exactly the one the provider rows imply (literal codes only, no expansion).
    expected: dict = {}
    for provider in doc["providers"]:
        for code in provider["jurisdictions"]:
            ids = expected.setdefault(code, [])
            if provider["provider_id"] not in ids:
                ids.append(provider["provider_id"])
    if [(row["code"], row["provider_ids"]) for row in doc["jurisdictions"]] != sorted(expected.items()):
        fail("COVERAGE_JURISDICTION_INVALID")
    if summary["catalog_provider_count"] != len(doc["providers"]):
        fail("COVERAGE_SUMMARY_INVALID")
    for row in doc["local_capabilities"]:
        exact(row, ("market", "capability", "status"), "COVERAGE_LOCAL_INVALID")
        if (not isinstance(row["market"], str) or not re.fullmatch(r"[A-Z]{2,12}", row["market"])
                or row["capability"] != "COVERED_CALL_DELAYED_LOCAL_CANDIDATE" or row["status"] != "LOCAL_UNADMITTED_NO_CATALOG_IDENTITY"):
            fail("COVERAGE_LOCAL_INVALID")
    for row in doc["observed"]:
        exact(row, ("provider_id", "jurisdiction", "venue", "instrument_kind", "quote_basis", "publication_scope", "cycle_count",
                    "ticker_key_count", "quote_as_of_max"), "COVERAGE_OBSERVED_INVALID")
        if (not isinstance(row["provider_id"], str) or not _COVERAGE_ID.fullmatch(row["provider_id"]) or not isinstance(row["jurisdiction"], str)
                or not _COVERAGE_CODE.fullmatch(row["jurisdiction"]) or not isinstance(row["venue"], str) or not _COVERAGE_VENUE.fullmatch(row["venue"])
                or row["instrument_kind"] != "equity_option" or row["quote_basis"] != "delayed" or row["publication_scope"] != "public_line_quote"
                or type(row["cycle_count"]) is not int or not 1 <= row["cycle_count"] <= 100000
                or type(row["ticker_key_count"]) is not int or not 1 <= row["ticker_key_count"] <= 100000 or not instant(row["quote_as_of_max"])):
            fail("COVERAGE_OBSERVED_INVALID")


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_v213_market_products.py <path_to_json>")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    try:
        if isinstance(data, dict) and data.get("title") == "TOP5產業總覽":
            validate_macro_overview(data)
            print("Macro overview validation PASSED.")
        elif isinstance(data, list) and len(data) > 0 and "strategy_id" in data[0]:
            for card in data:
                validate_educational_strategy(card)
            print(f"Educational strategies validation PASSED ({len(data)} cards).")
        elif isinstance(data, dict) and "bid" in data and "ask" in data:
            validate_option_quote(data)
            print("Option quote validation PASSED.")
        else:
            print("Unknown product structure; skipping.")
    except MarketProductValidationError as e:
        print(f"Validation FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
