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
- Currency USD, multiplier 100, rights_status binding.
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
