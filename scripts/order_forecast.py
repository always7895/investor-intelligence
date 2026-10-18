"""Order-based 6-month and 1-year figures for the Top20 card (operator 2026-09-27: the future estimate is ORDERS with a
stated period, and the price scenario follows from those orders; Astra contract %TEMP%/ii-live/astra-contract-orders.md).

Tile 2, the order figure per horizon, in this order:
1. RECOGNITION: the company's own schedule for its remaining performance obligations (RPO x the share it states it will
   recognize within 6 / 12 months), from the balance-sheet date. Only an explicitly stated horizon counts (an interpolated or
   unqualified share is not evidence); the stated shares must be cumulative (6M <= 12M <= 24M); a window that has already
   ended is not a future estimate. Any failure state of the schedule (PERIOD_MISMATCH, INPUTS_MISSING, INVALID, STALE, an
   unknown status) stays unavailable: only a filing that states no schedule at all lets rule 2 apply.
2. STOCK_EXTRAPOLATION: a disclosed order book with a year-on-year change whose comparison is on record (the year-ago value
   and date of the same series, or the company's own statement), O(t) = O x (1 + g) ** ((t - as_of) / 365 days), at the report
   date + 6 / 12 calendar months. A segment's book is shown as a segment figure and never priced as the whole company.
Tile 3, the price change if those orders are realized (a conditional scenario, never a target):
- RECOGNITION: revenue level R_h = the matching quarter's revenue x h / 3. Coverage C_h / R_h >= 1 gives the change
  coverage - 1 (that revenue level, P/S and share count unchanged, new orders not counted); below 1 no price is estimated
  and the coverage is shown instead.
- STOCK_EXTRAPOLATION (company-wide only): O(end) / O(report date) - 1 (revenue follows the book, P/S and shares unchanged).
Fixed-period figures (a 24-month schedule, annual new-order guidance) are references only. No analyst figure is used in
v1/v2; version 3 (Astra contract ORDERS-V3-01, below) adds a separate total-revenue model from company guidance or a
validated quarterly analyst consensus, kept distinct from orders. Every record names its issuer, scope, currency and
evidence; cloud/src/v213/order-forecast.ts re-validates all of it.
"""
from __future__ import annotations

import calendar
import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Mapping
from urllib.parse import urlparse

VERSION = 1
HORIZONS = (("m6", 6), ("m12", 12))
MAX_AGE_DAYS = 200
MAX_STOCK_GROWTH = 1.0
CURRENCIES = ("USD", "KRW", "TWD", "SEK", "JPY", "EUR", "GBP", "HKD", "CNY")
# Recognition statuses that mean "the filing states no schedule": only these let the stock extrapolation apply.
NO_SCHEDULE = ("NOT_DISCLOSED", "NO_PERIODIC_FILING")
KNOWN_FAILURES = ("PERIOD_MISMATCH", "INPUTS_MISSING", "INVALID", "STALE")
ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
# The authority as written: a DNS name (ASCII labels ending in an alphabetic top-level domain) and an optional 1-5 digit
# port; no user info, no bare numbers or IP shorthand (URL parsers normalize those differently). cloud/src/v213/
# order-forecast.ts applies the same rule; tests/fixtures/v213-order-forecast-urls.json is the shared table.
AUTHORITY = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,63})(?::([0-9]{1,5}))?$", re.ASCII)


def add_months(day: date, months: int) -> date:
    """The same day `months` calendar months later, clamped to the month's last day (2026-08-31 + 6 -> 2027-02-28)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _day(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _positive(*values: float | None) -> bool:
    return all(value is not None and math.isfinite(value) and value > 0 for value in values)


def _https(value: Any) -> str | None:
    """A real https URL whose authority, as written, is a DNS name with an optional valid port; else None (never an
    exception: a malformed URL is invalid evidence)."""
    if not isinstance(value, str) or len(value) > 400 or not value.isascii() or not value.isprintable() or "\\" in value \
            or any(ch.isspace() for ch in value) or value[:8].lower() != "https://":
        return None
    authority = re.split(r"[/?#]", value[8:], maxsplit=1)[0]
    written = AUTHORITY.match(authority)
    if written is None or (written.group(2) is not None and not 0 < int(written.group(2)) < 65536):
        return None
    try:
        parsed = urlparse(value)
        parsed.port  # noqa: B018 - raises on a malformed port
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname != written.group(1).lower() or parsed.username is not None or parsed.password is not None:
        return None
    return value


def _text(value: Any, limit: int) -> str | None:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def _unavailable(reason: str, scenario_reason: str = "NO_ORDER_BASIS") -> dict[str, Any]:
    return {"status": "UNAVAILABLE", "reason": reason, "scenario": {"status": "NO_BASIS", "reason": scenario_reason}}


def top_reason(m6: Mapping[str, Any], m12: Mapping[str, Any]) -> str | None:
    """The forecast-level reason, determined by its horizons: none when one is available; else the 1-year horizon's
    failure, else the 6-month one's, where a real failure outranks an undisclosed or ended horizon."""
    if m6["status"] == "AVAILABLE" or m12["status"] == "AVAILABLE":
        return None
    reasons = [m12["reason"], m6["reason"]]
    real = [reason for reason in reasons if reason not in ("NOT_DISCLOSED_HORIZON", "EXPIRED")]
    return (real or reasons)[0]


def _forecast(issuer: str, m6: dict[str, Any], m12: dict[str, Any], references: list[dict[str, Any]], reason: str | None = None) -> dict[str, Any]:
    available = any(h["status"] == "AVAILABLE" for h in (m6, m12))
    return {"version": VERSION, "issuer": issuer, "status": "AVAILABLE" if available else "UNAVAILABLE",
            "reason": top_reason(m6, m12), "m6": m6, "m12": m12, "references": references}


def _failed(issuer: str, reason: str) -> dict[str, Any]:
    return _forecast(issuer, _unavailable(reason), _unavailable(reason), [], reason)


def from_recognition(issuer: str, orders: Mapping[str, Any] | None, report_day: date) -> dict[str, Any] | None:
    """The forecast from a company deep report's order scenario (company_deep_report.order_scenario), or None only when
    there is no report or the filing states no schedule (the stock extrapolation may then apply)."""
    if orders is None:
        return None
    if not isinstance(orders, Mapping):
        return _failed(issuer, "INVALID")
    status = orders.get("status")
    if status in NO_SCHEDULE:
        return None
    if status != "DISCLOSED":
        return _failed(issuer, status if status in KNOWN_FAILURES else "INVALID")
    rpo, revenue = _number(orders.get("rpo")), _number(orders.get("quarter_revenue"))
    as_of, quarter_end, filed = _day(orders.get("rpo_as_of")), _day(orders.get("quarter_end")), _day(orders.get("filed"))
    quarter_start, report_period = _day(orders.get("quarter_start")), _day(orders.get("report_date"))
    url, horizons = _https(orders.get("url")), orders.get("horizons")
    accession, passage, form = orders.get("accession"), _text(orders.get("passage"), 300), _text(orders.get("form"), 12)
    # SEC RPO is the company-wide total in US dollars: a record saying otherwise is contradictory, never relabelled.
    if orders.get("scope", "COMPANY") != "COMPANY" or orders.get("currency", "USD") != "USD":
        return _failed(issuer, "INVALID")
    if not _positive(rpo, revenue) or as_of is None or quarter_end is None or quarter_start is None or filed is None \
            or report_period is None or url is None or not isinstance(accession, str) or not ACCESSION.match(accession) \
            or passage is None or form not in ("10-Q", "10-K") or not isinstance(horizons, Mapping) \
            or filed < as_of or filed > report_day or abs((report_period - as_of).days) > 45 \
            or not 60 <= (quarter_end - quarter_start).days <= 100:
        return _failed(issuer, "INVALID")
    if abs((as_of - quarter_end).days) > 45:
        return _failed(issuer, "PERIOD_MISMATCH")
    age = (report_day - as_of).days
    if not 0 <= age <= MAX_AGE_DAYS:
        return _failed(issuer, "STALE" if age > MAX_AGE_DAYS else "INVALID")
    basis = orders.get("quarter_basis", "FRAME")
    quarter = {"quarter_revenue": revenue, "quarter_start": str(quarter_start), "quarter_end": str(quarter_end), "quarter_basis": basis}
    if basis == "DERIVED_Q4":
        derivation = orders.get("quarter_derivation")
        checked = _derivation(derivation, revenue, quarter_start, quarter_end)
        if checked is None:
            return _failed(issuer, "INVALID")
        quarter["quarter_derivation"] = checked
    elif basis != "FRAME":
        return _failed(issuer, "INVALID")

    def share(key: str) -> tuple[str, float | None]:
        """("STATED", share) for an explicitly stated horizon, ("ABSENT", None) for one the filing does not state (or only
        interpolates), ("MALFORMED", None) for a stated share that is not a percentage."""
        row = horizons.get(key)
        if not isinstance(row, Mapping) or row.get("derived") is not False:
            return "ABSENT", None
        value = _number(row.get("share_pct"))
        return ("STATED", value) if value is not None and 0 < value <= 100 else ("MALFORMED", None)
    shares = {key: share(key) for key in ("m6", "m12", "m24")}
    if any(kind == "MALFORMED" for kind, _ in shares.values()):
        return _failed(issuer, "INVALID_SHARE")
    present = [value for kind, value in (shares[key] for key in ("m6", "m12", "m24")) if kind == "STATED"]
    if any(later < earlier for earlier, later in zip(present, present[1:])):
        return _failed(issuer, "SCHEDULE_CONTRADICTION")  # a cumulative schedule never shrinks
    evidence = {"source_url": url, "form": form, "filed": str(filed), "accession": accession, "passage": passage,
                "report_period": str(report_period), "explicit": True}

    def horizon(key: str, months: int) -> dict[str, Any]:
        kind, value = shares[key]
        if kind != "STATED":
            return _unavailable("NOT_DISCLOSED_HORIZON")
        end = add_months(as_of, months)
        if end <= report_day:
            return _unavailable("EXPIRED")  # the window has already ended: not a future estimate
        amount = rpo * value / 100
        level = revenue * months / 3
        coverage = amount / level if level > 0 else math.nan
        if not all(math.isfinite(number) and number > 0 for number in (amount, level, coverage)):
            return _unavailable("INVALID")
        scenario = {"status": "AVAILABLE", "coverage": coverage, "change": coverage - 1} if coverage >= 1 \
            else {"status": "INSUFFICIENT_COVERAGE", "coverage": coverage}
        return {"status": "AVAILABLE", "basis": "RECOGNITION", "amount": amount, "currency": "USD", "scope": "COMPANY",
                "start": str(as_of), "end": str(end), "as_of": str(as_of), "rpo": rpo, "share_pct": value, **quarter, **evidence,
                "scenario": scenario}

    references = []
    kind, value = shares["m24"]
    if kind == "STATED":
        end = add_months(as_of, 24)
        amount = rpo * value / 100
        if end > report_day and math.isfinite(amount) and amount > 0:
            references.append({"kind": "RECOGNITION_24M", "amount": amount, "currency": "USD", "start": str(as_of), "end": str(end),
                               "as_of": str(as_of), "rpo": rpo, "share_pct": value, **evidence})
    return _forecast(issuer, horizon("m6", 6), horizon("m12", 12), references)


def _derivation(raw: Any, revenue: float, quarter_start: date, quarter_end: date) -> dict[str, Any] | None:
    """A fiscal fourth quarter = the 10-K's full year - the nine-month year to date of the same fiscal year: both positive,
    same fiscal start, a full year ending on the quarter end, nine months ending the day before the quarter starts, both
    accessions named, and the difference equal to the quarter's revenue."""
    if not isinstance(raw, Mapping):
        return None
    annual, nine = _number(raw.get("annual")), _number(raw.get("nine_months"))
    fiscal_start, nine_end = _day(raw.get("annual_start")), _day(raw.get("nine_months_end"))
    accessions = [raw.get("annual_accession"), raw.get("nine_months_accession")]
    if not _positive(annual, nine) or fiscal_start is None or nine_end is None \
            or not all(isinstance(a, str) and ACCESSION.match(a) for a in accessions) \
            or not 350 <= (quarter_end - fiscal_start).days <= 380 or not 260 <= (nine_end - fiscal_start).days <= 285 \
            or quarter_start != nine_end + timedelta(days=1) or not math.isclose(annual - nine, revenue, rel_tol=1e-9):
        return None
    return {"annual": annual, "annual_start": str(fiscal_start), "annual_accession": accessions[0],
            "nine_months": nine, "nine_months_end": str(nine_end), "nine_months_accession": accessions[1]}


def from_stock(issuer: str, orders: Mapping[str, Any] | None, report_day: date) -> dict[str, Any] | None:
    """The forecast from a disclosed order book with a year-on-year change on record (v3 outlook.orders), or None when
    there is no order book at all."""
    if not isinstance(orders, Mapping) or orders.get("kind") not in ("RPO", "BACKLOG"):
        return None
    amount, growth = _number(orders.get("amount")), _number(orders.get("yoy"))
    as_of, url, currency = _day(orders.get("as_of")), _https(orders.get("source_url")), orders.get("currency")
    if not _positive(amount) or as_of is None or url is None or currency not in CURRENCIES:
        return _failed(issuer, "INVALID")
    age = (report_day - as_of).days
    if not 0 <= age <= MAX_AGE_DAYS:
        return _failed(issuer, "STALE" if age > MAX_AGE_DAYS else "INVALID")
    if growth is None:
        return _failed(issuer, "NO_GROWTH")
    if not -1 < growth <= MAX_STOCK_GROWTH:
        return _failed(issuer, "GROWTH_OUT_OF_RANGE")
    # The comparison behind the growth: the same series a year earlier, or the company's own statement.
    prior, prior_as_of, stated = _number(orders.get("yoy_prior_amount")), _day(orders.get("yoy_prior_as_of")), _text(orders.get("yoy_evidence"), 300)
    if prior is not None and prior_as_of is not None and prior > 0 and 320 <= (as_of - prior_as_of).days <= 410 \
            and math.isclose(amount / prior - 1, growth, rel_tol=1e-9, abs_tol=1e-12):
        lineage = {"lineage": "SERIES", "yoy_prior_amount": prior, "yoy_prior_as_of": str(prior_as_of)}
    elif stated:
        lineage = {"lineage": "COMPANY_STATED", "yoy_evidence": stated}
    else:
        return _failed(issuer, "NO_GROWTH_LINEAGE")
    scope = "COMPANY" if orders.get("scope_kind") == "COMPANY" else "SEGMENT"

    def level(day: date) -> float | None:
        try:
            value = amount * (1 + growth) ** ((day - as_of).days / 365)
        except OverflowError:
            return None
        return value if math.isfinite(value) and value > 0 else None
    baseline = level(report_day)
    tiles = {}
    for key, months in HORIZONS:
        end = add_months(report_day, months)
        value = level(end)
        if baseline is None or value is None or not math.isfinite(value / baseline):
            tiles[key] = _unavailable("INVALID")
            continue
        scenario = {"status": "AVAILABLE", "change": value / baseline - 1} if scope == "COMPANY" \
            else {"status": "NO_BASIS", "reason": "SCOPE_PARTIAL"}
        tiles[key] = {"status": "AVAILABLE", "basis": "STOCK_EXTRAPOLATION", "amount": value, "currency": currency, "scope": scope,
                      "scope_label": _text(orders.get("scope"), 40), "start": str(report_day), "end": str(end), "as_of": str(as_of),
                      "stock": amount, "yoy": growth, "baseline": baseline, "source_url": url, "kind": orders["kind"], **lineage,
                      "scenario": scenario}
    return _forecast(issuer, tiles["m6"], tiles["m12"], [])


def build(issuer: str, stock_orders: Mapping[str, Any] | None, recognition_orders: Mapping[str, Any] | None,
          report_day: date) -> dict[str, Any]:
    """The versioned order forecast for one Top20 entry (sealed as outlook.order_forecast)."""
    forecast = from_recognition(issuer, recognition_orders, report_day) or from_stock(issuer, stock_orders, report_day)
    if forecast is None:
        reason = "NOT_DISCLOSED" if isinstance(stock_orders, Mapping) and stock_orders.get("kind") == "NOT_DISCLOSED" else "NO_ORDERS"
        forecast = _failed(issuer, reason)
    guidance = stock_orders.get("guidance") if isinstance(stock_orders, Mapping) else None
    if isinstance(guidance, Mapping) and guidance.get("kind") == "ANNUAL_NEW_ORDERS" and _positive(_number(guidance.get("amount"))) \
            and isinstance(guidance.get("year"), (int, float)) and not isinstance(guidance.get("year"), bool) \
            and float(guidance["year"]).is_integer() and stock_orders.get("currency") in CURRENCIES:
        forecast["references"].append({"kind": "ANNUAL_NEW_ORDERS_GUIDANCE", "amount": float(guidance["amount"]),
                                       "currency": stock_orders.get("currency"), "year": int(guidance["year"]),
                                       "source_url": _https(stock_orders.get("source_url"))})
    return forecast



# ---------------------------------------------------------------- version 2 (Astra contract ORDERS-V2-01)
# Version 2 adds reviewed, dated issuer claims (scripts/order_claims.py) to the periodic filing. The sealed evidence
# carries the allowlisted periodic input and order book, so cloud/src/v213/order-forecast.ts recomputes every branch:
# - a company US-dollar RPO measured later than the filing (or correcting/cancelling it via FILING:<accession>) is the
#   current stock; with its own schedule it replaces the filing's, without one both horizons have no realization
#   schedule (the filing's schedule stays a dated reference, never multiplied by the new stock); a zero, unquantified or
#   range observation is current too and withholds every calculation (UNQUANTIFIED_STOCK);
# - the same measurement date as the filing with a different figure is a conflict unless the claim corrects the filing;
# - a registry schedule is priced only with the filing's validated quarter (FRAME or derived fourth quarter, within 45
#   days of the stock's measurement date); otherwise its amounts are shown without a price (NO_MATCHING_REVENUE);
# - an order-book extrapolation is a labelled model sensitivity that never feeds the price rows;
# - every other active claim is a dated reference, never added to any figure.
VERSION2 = 2
VERSION3 = 3
HORIZON_CONVENTION_V3 = "FISCAL_2Q_4Q"
FORMULA_V3 = "ORDERS-V3-01"
ASSUMPTIONS_V3 = "條件情境：營收依上述推估實現，P/S與股數不變；以最新已報四季為基準，非目標價、非今日起報酬"
V2_EXTRA_REASONS = ("NO_REALIZATION_SCHEDULE", "CONFLICTING_DISCLOSURES", "EVIDENCE_LIMIT", "UNQUANTIFIED_STOCK", "UNRESOLVED_REVISION")
DOCUMENT_FIELDS = ("id", "issuer", "publisher", "title", "source_kind", "url", "published_date", "published_at", "retrieved_at",
                   "sha256", "byte_size", "lineage_id", "sec")
CLAIM_FIELDS = ("id", "symbol", "document_id", "locator", "passage", "summary", "metric", "assertion_kind", "currency",
                "unit_multiplier", "amount", "null_reason", "bounds", "as_of", "scope", "scope_label", "period_start",
                "period_end", "period_kind", "series_id", "basis", "stock_claim_id", "shares", "revision", "checked_at")
PERIODIC_FIELDS = ("status", "form", "filed", "url", "rpo", "rpo_as_of", "quarter_revenue", "quarter_start", "quarter_end",
                   "quarter_basis", "quarter_derivation", "accession", "passage", "report_date", "horizons", "scope", "currency")
STOCK_FIELDS = ("kind", "amount", "currency", "as_of", "yoy", "yoy_prior_amount", "yoy_prior_as_of", "yoy_evidence", "scope",
                "scope_kind", "source_url", "guidance")
QUARTER_FIELDS = ("quarter_revenue", "quarter_start", "quarter_end", "quarter_basis", "quarter_derivation")


def _project(raw: Mapping[str, Any] | None, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    return {key: raw[key] for key in fields if key in raw}


def _quarter_of(periodic: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The validated quarter of the filing's forecast (an available recognition horizon), else None."""
    for key in ("m12", "m6"):
        horizon = (periodic or {}).get(key) or {}
        if horizon.get("status") == "AVAILABLE" and horizon.get("basis") == "RECOGNITION":
            return {field: horizon[field] for field in QUARTER_FIELDS if field in horizon}
    return None


def _registry_horizon(stock: Mapping[str, Any], schedule: Mapping[str, Any], key: str, months: int, report_day: date,
                      quarter: Mapping[str, Any] | None) -> dict[str, Any]:
    import order_claims
    share = order_claims.number(schedule["shares"].get(key))
    if share is None:
        return _unavailable("NOT_DISCLOSED_HORIZON")
    as_of = date.fromisoformat(stock["as_of"])
    age = (report_day - as_of).days
    if not 0 <= age <= MAX_AGE_DAYS:
        return _unavailable("STALE" if age > MAX_AGE_DAYS else "INVALID")
    end = add_months(as_of, months)
    if end <= report_day:
        return _unavailable("EXPIRED")
    rpo = order_claims.value_of(stock)
    amount = rpo * share / 100
    horizon: dict[str, Any] = {"status": "AVAILABLE", "basis": "RECOGNITION", "source": "REGISTRY", "amount": amount,
                               "currency": "USD", "scope": "COMPANY", "start": str(as_of), "end": str(end), "as_of": str(as_of),
                               "rpo": rpo, "share_pct": share, "stock_claim_id": stock["id"], "schedule_claim_id": schedule["id"]}
    if quarter is None or abs((as_of - date.fromisoformat(quarter["quarter_end"])).days) > 45:
        horizon["scenario"] = {"status": "NO_BASIS", "reason": "NO_MATCHING_REVENUE"}
        return horizon
    coverage = amount / (quarter["quarter_revenue"] * months / 3)
    horizon.update(quarter)
    horizon["scenario"] = {"status": "AVAILABLE", "coverage": coverage, "change": coverage - 1} if coverage >= 1 \
        else {"status": "INSUFFICIENT_COVERAGE", "coverage": coverage}
    return horizon


def _sensitivity(stock_forecast: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The order-book extrapolation as a model sensitivity: amounts and assumptions only, never a price row."""
    if not stock_forecast or not any(stock_forecast[key]["status"] == "AVAILABLE" for key, _ in HORIZONS):
        return None
    out = {}
    for key, _ in HORIZONS:
        horizon = {k: v for k, v in stock_forecast[key].items() if k != "scenario"}
        out[key] = horizon if horizon["status"] == "AVAILABLE" else {"status": "UNAVAILABLE", "reason": horizon["reason"]}
    return out


def filing_of(periodic_input: Mapping[str, Any] | None) -> dict[str, str] | None:
    """The filing a claim may correct or cancel: {"accession", "filed"} of a DISCLOSED periodic input, else None."""
    if not isinstance(periodic_input, Mapping) or periodic_input.get("status") != "DISCLOSED":
        return None
    accession, filed = periodic_input.get("accession"), _day(periodic_input.get("filed"))
    return {"accession": accession, "filed": str(filed)} if isinstance(accession, str) and ACCESSION.match(accession) and filed else None


def _filing_shares(periodic_input: Mapping[str, Any] | None) -> dict[str, float]:
    """The filing's explicitly stated cumulative shares, keyed like a registry schedule."""
    horizons = (periodic_input or {}).get("horizons")
    out = {}
    for key in ("m6", "m12", "m24"):
        row = horizons.get(key) if isinstance(horizons, Mapping) else None
        if isinstance(row, Mapping) and row.get("derived") is False and _number(row.get("share_pct")) is not None:
            out[key] = _number(row["share_pct"])
    return out


def decide(issuer: str, periodic_input: Mapping[str, Any] | None, stock_input: Mapping[str, Any] | None, report_day: date,
           selection: Mapping[str, Any] | None, claims: list[Mapping[str, Any]], limited: bool) -> dict[str, Any]:
    """Every figure of a version-2 forecast from its sealed inputs (the Worker recomputes exactly this)."""
    import order_claims
    periodic = from_recognition(issuer, periodic_input, report_day)
    references = list(periodic["references"]) if periodic else []
    by_id = {c["id"]: c for c in claims}
    stock = by_id.get((selection or {}).get("current_stock"))
    schedule = by_id.get((selection or {}).get("schedule"))
    filing_state = (selection or {}).get("filing")
    filing_as_of = str(_day((periodic_input or {}).get("rpo_as_of"))) if periodic is not None and _day((periodic_input or {}).get("rpo_as_of")) else None
    filing_value = _number((periodic_input or {}).get("rpo")) if periodic is not None else None
    periodic_ok = periodic is not None and filing_state not in ("SUPERSEDED", "CANCELLED")
    same_date = stock is not None and periodic_ok and filing_as_of is not None and stock["as_of"] == filing_as_of
    if limited:
        m6, m12 = _unavailable("EVIDENCE_LIMIT"), _unavailable("EVIDENCE_LIMIT")
    elif (selection or {}).get("status") in ("UNRESOLVED_REVISION", "CONFLICTING_DISCLOSURES"):
        m6, m12 = _unavailable(selection["status"]), _unavailable(selection["status"])
    elif same_date and (order_claims.observation(stock) != order_claims.observation({"amount": filing_value, "unit_multiplier": 1})
                        or schedule is not None and {k: float(v) for k, v in schedule["shares"].items()} != _filing_shares(periodic_input)):
        # The same measurement as the filing: another figure, or another schedule for it, is a contradiction.
        m6, m12 = _unavailable("CONFLICTING_DISCLOSURES"), _unavailable("CONFLICTING_DISCLOSURES")
    elif stock is not None and (not periodic_ok or filing_as_of is None or stock["as_of"] > filing_as_of):
        value = order_claims.value_of(stock)
        if value is None or value <= 0 or stock.get("bounds") is not None:
            m6, m12 = _unavailable("UNQUANTIFIED_STOCK"), _unavailable("UNQUANTIFIED_STOCK")
        elif schedule is not None:
            quarter = _quarter_of(periodic)
            m6 = _registry_horizon(stock, schedule, "m6", 6, report_day, quarter)
            m12 = _registry_horizon(stock, schedule, "m12", 12, report_day, quarter)
            share24 = order_claims.number(schedule["shares"].get("m24"))
            end24 = add_months(date.fromisoformat(stock["as_of"]), 24)
            if share24 is not None and end24 > report_day and 0 <= (report_day - date.fromisoformat(stock["as_of"])).days <= MAX_AGE_DAYS:
                references.append({"kind": "REGISTRY_RECOGNITION_24M", "amount": value * share24 / 100, "currency": "USD",
                                   "start": stock["as_of"], "end": str(end24), "rpo": value, "share_pct": share24,
                                   "stock_claim_id": stock["id"], "schedule_claim_id": schedule["id"]})
        else:
            m6, m12 = _unavailable("NO_REALIZATION_SCHEDULE"), _unavailable("NO_REALIZATION_SCHEDULE")
        if periodic is not None:
            references = [r for r in references if r["kind"] != "RECOGNITION_24M"]
            old = next((periodic[k] for k in ("m12", "m6") if periodic[k]["status"] == "AVAILABLE"), None)
            if old is not None:
                references.append({"kind": "SUPERSEDED_SCHEDULE", "as_of": old["as_of"], "rpo": old["rpo"], "share_pct": old["share_pct"],
                                   "currency": "USD", "start": old["start"], "end": old["end"], "form": old["form"],
                                   "filed": old["filed"], "accession": old["accession"], "source_url": old["source_url"],
                                   "by_claim_id": stock["id"], "filing": filing_state or "ACTIVE"})
    elif periodic_ok:
        m6, m12 = periodic["m6"], periodic["m12"]
    else:
        kind = (stock_input or {}).get("kind")
        reason = "NO_REALIZATION_SCHEDULE" if kind in ("RPO", "BACKLOG") or stock is not None \
            else "NOT_DISCLOSED" if kind == "NOT_DISCLOSED" else "NO_ORDERS"
        m6, m12 = _unavailable(reason), _unavailable(reason)
        references = []
    for horizon in (m6, m12):
        if horizon["status"] == "AVAILABLE" and "source" not in horizon:
            horizon["source"] = "PERIODIC"
    used = {h.get(k) for h in (m6, m12) for k in ("stock_claim_id", "schedule_claim_id")} \
        | {r.get(k) for r in references for k in ("stock_claim_id", "schedule_claim_id")}
    for claim_id in (selection or {}).get("active") or []:
        if claim_id not in used:
            references.append({"kind": "CLAIM", "claim_id": claim_id})
    guidance = (stock_input or {}).get("guidance")
    if isinstance(guidance, Mapping) and guidance.get("kind") == "ANNUAL_NEW_ORDERS" and _positive(_number(guidance.get("amount"))) \
            and isinstance(guidance.get("year"), (int, float)) and not isinstance(guidance.get("year"), bool) \
            and float(guidance["year"]).is_integer() and (stock_input or {}).get("currency") in CURRENCIES:
        references.append({"kind": "ANNUAL_NEW_ORDERS_GUIDANCE", "amount": float(guidance["amount"]),
                           "currency": stock_input.get("currency"), "year": int(guidance["year"]),
                           "source_url": _https(stock_input.get("source_url"))})
    available = any(h["status"] == "AVAILABLE" for h in (m6, m12))
    return {"version": VERSION2, "issuer": issuer, "status": "AVAILABLE" if available else "UNAVAILABLE",
            "reason": top_reason(m6, m12), "m6": m6, "m12": m12,
            "stock_sensitivity": _sensitivity(from_stock(issuer, stock_input, report_day)), "references": references}


def build_v2(issuer: str, stock_orders: Mapping[str, Any] | None, recognition_orders: Mapping[str, Any] | None,
             report_day: date, cutoff: datetime, loaded: Mapping[str, Any]) -> dict[str, Any]:
    """The version-2 order forecast for one Top20 entry at the build cutoff, with the loaded claim registry
    (order_claims.load): the figures (decide) and the evidence the Worker needs to recompute them."""
    import order_claims
    periodic_input = _project(recognition_orders, PERIODIC_FIELDS)
    stock_input = _project(stock_orders, STOCK_FIELDS)
    registry_status = loaded.get("status")
    evidence: dict[str, Any] = {"registry_status": registry_status, "registry_sha256": loaded.get("sha256"),
                                "cutoff": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"), "url_prefixes": [], "documents": [], "claims": [],
                                "selection": None, "periodic": periodic_input, "stock_orders": stock_input}
    claims: list[dict[str, Any]] = []
    limited = False
    if registry_status in ("OK", "EMPTY"):
        documents, claims, prefixes, limit = order_claims.issuer_evidence(loaded, issuer)
        evidence["url_prefixes"] = prefixes
        if limit:
            limited = True
            evidence["selection"] = {"status": limit}
        else:
            evidence.update(documents=[_project(d, DOCUMENT_FIELDS) for d in documents],
                            claims=[_project(c, CLAIM_FIELDS) for c in claims],
                            selection=order_claims.select(documents, claims, cutoff, filing_of(periodic_input)))
    return {**decide(issuer, periodic_input, stock_input, report_day, evidence["selection"] if not limited else None, claims, limited),
            "evidence": evidence}


# ---------------------------------------------------------------- version 3 (Astra contract ORDERS-V3-01)
# Version 3 distinguishes orders from revenue:
# Tile 2: 訂單認列／營收推估 (basis: 公司營收財測＋模型（非訂單） / 非公司揭露、非訂單：分析師季度營收共識＋模型 / 已簽約預計認列)
# Tile 3: 營收實現後股價情境 (TTM constant-P/S formula: TTM6/B - 1, TTM12/B - 1)
# Contracted recognition from v2 is retained independently and never added to guidance or consensus.


def _auto_barrier_reason(disposition: str, reason: str | None) -> str:
    """The v3 unavailable reason of an automatic-lane barrier (the typed disposition travels in evidence.auto_update):
    a newer release awaiting verification or an unaccounted item is STALE, a missing or unverifiable freshness proof
    FRESHNESS_UNVERIFIED, an unadmitted proof INVALID."""
    reason = str(reason or "")
    if disposition == "WAITING":
        return "STALE"
    if disposition == "SUSPENDED":
        if reason.startswith(("RECEIPT_RESULTS_PUBLISHED", "RECEIPT_REVIEW_REQUIRED", "RECEIPT_RECEIPT_AGE_EXCEEDED", "DETECTIONS_")):
            return "STALE"
        if reason.startswith(("RECEIPT_MISSING", "RECEIPTS_", "RECEIPT_CHECKED_AT", "RECEIPT_IR_COVERAGE", "RECEIPT_CHANNELS")):
            return "FRESHNESS_UNVERIFIED"
    return "INVALID"


def build_v3(issuer: str, stock_orders: Mapping[str, Any] | None, recognition_orders: Mapping[str, Any] | None,
             report_day: date, cutoff: datetime, claims: Mapping[str, Any],
             revenue_registry: Mapping[str, Any] | None = None,
             consensus_cache: Mapping[str, Any] | None = None,
             v2_forecast: Mapping[str, Any] | None = None,
             release_checks_cache: Mapping[str, Any] | None = None,
             revenue_approval: Mapping[str, Any] | None = None,
             effective_inputs: Any = None) -> dict[str, Any]:
    """The version-3 revenue and order forecast for one Top20 entry at the build cutoff.
    Reuses the unchanged build_v2 order view and incorporates reviewed revenue guidance / consensus.

    A1 (Astra acceptance r7): the enforced reviewed profile (``revenue_approval``, the schema of
    config/revenue-guidance-approval-v1.json) is the admission boundary: a missing/malformed approval, a changed
    registry or record, a missing decision or a time incoherence suspends the revenue path as UNAVAILABLE / INVALID
    with the distinct UNREVIEWED_INPUTS diagnostic, while the independent order recognition is never affected.
    A3/A6: the registry root's ``consensus_enabled`` gate (missing fails closed to disabled) defers the Korean
    analyst-consensus route for the first rollout: NOT_DISCLOSED records then seal the CONSENSUS_DEFERRED
    diagnostic and build_v3 never routes to the consensus cache, even when a capture exists.

    B1 (ORDERS-V3-AUTOUPDATE-01): ``effective_inputs`` is the one pinned snapshot of every revenue-guidance input at
    this cutoff (revenue_guidance_overlay.load_effective_inputs). Its curated registry, reviewed profile and receipts
    feed the unchanged curated path; for NVDA/MU its per-issuer disposition decides: a machine-admitted record takes
    the separate machine branch (no human approval is claimed for it), a waiting/blocked/suspended issuer has no
    revenue (never the older curated numbers or v2 revenue). Without a snapshot and without explicit curated inputs
    the shared loader is used; explicit curated inputs (the fixture interface) keep the legacy curated path."""
    import revenue_guidance

    if v2_forecast is None:
        v2_forecast = build_v2(issuer, stock_orders, recognition_orders, report_day, cutoff, claims)

    # 0. The effective-input snapshot (B1)
    snapshot = None
    auto_item = None
    if effective_inputs is None and revenue_registry is None and revenue_approval is None and release_checks_cache is None:
        import revenue_guidance_overlay
        effective_inputs = revenue_guidance_overlay.load_effective_inputs(
            cutoff=cutoff, state_root=revenue_guidance_overlay.DEFAULT_STATE_ROOT, symbols=[issuer])
    if effective_inputs is not None:
        import revenue_guidance_overlay
        if revenue_registry is not None or revenue_approval is not None or release_checks_cache is not None:
            raise ValueError("build_v3: an effective-input snapshot or explicit curated inputs, not both")
        snapshot = revenue_guidance_overlay.require_snapshot(effective_inputs, cutoff)
        revenue_registry, revenue_approval, release_checks_cache = snapshot.registry, snapshot.approval, snapshot.release_checks
        auto_item = snapshot.issuer(issuer)
    machine = auto_item is not None and auto_item.admission_kind == "MACHINE_REPLAY" and auto_item.disposition == "AUTO_VERIFIED"
    auto_barrier = auto_item is not None and auto_item.disposition in ("WAITING", "BLOCKED", "SUSPENDED")

    # 1. Inspect reviewed revenue guidance registry
    reg = revenue_registry if revenue_registry is not None else revenue_guidance.load_registry()
    reg_status = reg.get("status")
    reg_sha256 = reg.get("sha256")
    issuers_map = reg.get("issuers", {}) if isinstance(reg, Mapping) else {}
    record = issuers_map.get(issuer) if isinstance(issuers_map, Mapping) else None
    if machine:
        record = auto_item.usable_record  # the source-rederived successor, never a merged or hand-approved record
    elif auto_barrier:
        record = None  # no older curated numbers while a newer event is unresolved or the proof is not admitted
    reported_quarters = record.get("reported_quarters", []) if isinstance(record, Mapping) else []
    anchor_date = None
    start_date = None

    revenue_status = "UNAVAILABLE"
    revenue_basis: str | None = None
    revenue_reason = "INPUTS_MISSING"
    revenue_diagnostic: str | None = None
    rec_status = None
    fw_result: dict[str, Any] | None = None

    # A1: the reviewed profile beside the registry (loaded once by the caller, default the tracked config file).
    approval: Mapping[str, Any] | None = None
    profile_err: str | None = None
    consensus_enabled = False
    if machine and reg_status == "OK":
        # Machine admission replaces the human profile for this record (the snapshot's re-derived producer, its own
        # receipt and typed consumption); the human profile is not consulted and its slots stay empty.
        consensus_enabled = bool(reg.get("consensus_enabled", False))
    elif reg_status == "OK" and record is not None:
        approval = revenue_approval if revenue_approval is not None else revenue_guidance.load_approval()
        profile_err = revenue_guidance.check_reviewed_profile(issuer, record, approval, reg_sha256, cutoff)
        # A3/A6: the explicit registry gate; a missing flag fails closed to disabled (first-rollout deferral).
        consensus_enabled = bool(reg.get("consensus_enabled", False))

    if auto_barrier:
        revenue_status = "UNAVAILABLE"
        revenue_reason = _auto_barrier_reason(auto_item.disposition, auto_item.reason)
    elif machine and reg_status != "OK":
        revenue_reason = "INVALID"
    elif reg_status == "INVALID":
        revenue_reason = "INVALID"
    elif reg_status in ("UNAVAILABLE", "EMPTY") or record is None:
        revenue_reason = "INPUTS_MISSING"
    elif profile_err is not None:
        # A1: the record's inputs are not covered by an enforced reviewed profile (changed registry/record,
        # missing decision, time incoherence, missing approval). The revenue path suspends, orders stay.
        revenue_status = "UNAVAILABLE"
        revenue_reason = "INVALID"
        revenue_diagnostic = "UNREVIEWED_INPUTS"
    else:
        rec_status = record.get("status") if isinstance(record, Mapping) else None
        if rec_status not in revenue_guidance.STATUSES:
            revenue_reason = "INVALID"
        elif rec_status == "NOT_DISCLOSED":
            revenue_reason = "NOT_DISCLOSED"
        elif rec_status in ("WITHDRAWN", "STALE", "CONFLICTING_DISCLOSURES", "UNAVAILABLE"):
            # WITHDRAWN, STALE, and CONFLICTING_DISCLOSURES can NEVER be overridden to NOT_DISCLOSED
            revenue_reason = rec_status
        else:
            try:
                valid_record = revenue_guidance.validate_issuer_record(record, expected_symbol=issuer)
                if machine:
                    fw_result = revenue_guidance.build_forward_quarters(issuer, valid_record, cutoff, effective_inputs=snapshot)
                else:
                    fw_result = revenue_guidance.build_forward_quarters(issuer, valid_record, cutoff, release_checks_cache)
                if fw_result["status"] == "AVAILABLE":
                    revenue_status = "AVAILABLE"
                    revenue_reason = None
                    revenue_basis = fw_result["basis_type"]
                else:
                    revenue_status = "UNAVAILABLE"
                    revenue_reason = fw_result["reason"]
                    # The distinct diagnostic (Astra W1 ruling): a company-guidance path suspended for missing
                    # official-IR coverage is sealed as IR_COVERAGE_MISSING and rendered as 官方IR查核未完成，暫停營收推估.
                    revenue_diagnostic = fw_result.get("diagnostic")
            except revenue_guidance.GuidanceError:
                revenue_status = "UNAVAILABLE"
                revenue_reason = "INVALID"
            except Exception:
                revenue_status = "UNAVAILABLE"
                revenue_reason = "INVALID"

    # 2. If genuinely NOT_DISCLOSED, attempt the quarterly consensus adapter - only while the registry gate allows it.
    # Typed scoped channel faults (Astra r5 item 9): a malformed/missing consensus cache or release-check cache is a
    # channel failure, never equated with a genuine empty/nondisclosed success; the fault travels sealed so the
    # Worker re-derives the same scoped failure without aborting unrelated issuers.
    consensus_fault = consensus_cache.get("__fault__") if isinstance(consensus_cache, Mapping) and "__fault__" in consensus_cache else None
    release_fault = release_checks_cache.get("__fault__") if isinstance(release_checks_cache, Mapping) and "__fault__" in release_checks_cache else None
    consensus_entry = (consensus_cache or {}).get(issuer) if isinstance(consensus_cache, Mapping) else None
    if revenue_status != "AVAILABLE" and rec_status == "NOT_DISCLOSED" and revenue_reason == "NOT_DISCLOSED" and not consensus_enabled:
        # A3/A6 (Astra's authorized first-rollout option): the Korean consensus route and its collector are
        # explicitly off. The genuine nondisclosure stands with the distinct CONSENSUS_DEFERRED diagnostic
        # (rendered 公司未提供營收財測；分析師共識路線本次未啟用 on every surface); a capture, if any, is never routed.
        try:
            revenue_guidance.validate_issuer_record(record, expected_symbol=issuer)
            revenue_diagnostic = "CONSENSUS_DEFERRED"
        except revenue_guidance.GuidanceError:
            revenue_reason = "INVALID"
            revenue_diagnostic = None
    elif revenue_status != "AVAILABLE" and rec_status == "NOT_DISCLOSED" and revenue_reason == "NOT_DISCLOSED" and consensus_fault:
        revenue_status = "UNAVAILABLE"
        revenue_reason = "INVALID"
    elif revenue_status != "AVAILABLE" and rec_status == "NOT_DISCLOSED" and revenue_reason == "NOT_DISCLOSED" and consensus_entry:
        try:
            valid_record = revenue_guidance.validate_issuer_record(record, expected_symbol=issuer)
            # Check all Korean/nondisclosure documents: retrieved at or before cutoff, and a date-only publication is
            # only eligible after the end of its UTC day (Astra r5 item 12: end-of-day eligibility, not <= reportDay).
            cutoff_day = cutoff.date()
            for doc in valid_record.get("documents", []):
                ret_inst = revenue_guidance.parse_instant(doc.get("retrieved_at"))
                if not ret_inst or ret_inst > cutoff:
                    raise revenue_guidance.GuidanceError("FUTURE_DOCUMENT_RETRIEVAL")
                pub_d = revenue_guidance.parse_day(doc.get("published_date"))
                if not pub_d:
                    raise revenue_guidance.GuidanceError("INVALID_DOCUMENT_PUBLISHED_DATE")
                pub_inst = revenue_guidance.parse_instant(doc.get("published_at"))
                if pub_inst is not None:
                    if pub_inst > cutoff or pub_inst > ret_inst or pub_inst.date() != pub_d:
                        raise revenue_guidance.GuidanceError("INVALID_DOCUMENT_PUBLISHED_INSTANT")
                elif pub_d >= cutoff_day:
                    raise revenue_guidance.GuidanceError("FUTURE_DOCUMENT_PUBLISHED")
            # Calendar links on every branch (Astra r5 item 10): the consensus model runs on the record's validated
            # forward intervals, each bound to a calendar document and locator, anchored at the latest actual end.
            intervals = valid_record.get("forward_intervals", [])
            if not isinstance(intervals, list) or len(intervals) != 4:
                raise revenue_guidance.GuidanceError("FORWARD_INTERVALS_MUST_BE_4")
            doc_ids = {d["id"] for d in valid_record.get("documents", []) if isinstance(d, Mapping)}
            prev_end = None
            for intv in intervals:
                if not isinstance(intv, Mapping):
                    raise revenue_guidance.GuidanceError("INVALID_FORWARD_INTERVAL")
                s, e = revenue_guidance.parse_day(intv.get("start")), revenue_guidance.parse_day(intv.get("end"))
                if not s or not e or s > e:
                    raise revenue_guidance.GuidanceError("INVALID_FORWARD_INTERVAL_DATES")
                if prev_end is not None and s != prev_end + timedelta(days=1):
                    raise revenue_guidance.GuidanceError("FORWARD_INTERVAL_GAP_OR_OVERLAP")
                prev_end = e
                cal_doc = intv.get("calendar_document_id")
                if not cal_doc or cal_doc not in doc_ids:
                    raise revenue_guidance.GuidanceError("CALENDAR_DOC_REQUIRED")
                if not revenue_guidance.clean_text(intv.get("calendar_locator"), revenue_guidance.MAX_PASSAGE):
                    raise revenue_guidance.GuidanceError("CALENDAR_LOCATOR_REQUIRED")
            if reported_quarters:
                anchor = revenue_guidance.parse_day(reported_quarters[-1].get("end"))
                if anchor and intervals[0].get("start") != str(anchor + timedelta(days=1)):
                    raise revenue_guidance.GuidanceError("FORWARD_INTERVALS_NOT_ANCHORED")
            c_res = revenue_guidance.build_consensus_forward_quarters(
                issuer, consensus_entry, intervals, cutoff,
                expected_currency=reported_quarters[0].get("currency") if reported_quarters else None)
            if c_res["status"] == "AVAILABLE":
                # Validate actuals against consensus currency and accounting basis
                c_curr = consensus_entry.get("currency")
                for q in reported_quarters:
                    if q.get("currency") != c_curr:
                        raise revenue_guidance.GuidanceError(f"ACTUAL_CURRENCY_MISMATCH {q.get('currency')} != {c_curr}")
                    if q.get("accounting_basis") not in revenue_guidance.ACCOUNTING_BASES:
                        raise revenue_guidance.GuidanceError("INVALID_ACTUAL_BASIS")
                fw_result = c_res
                revenue_status = "AVAILABLE"
                revenue_reason = None
                revenue_diagnostic = None
                revenue_basis = "CONSENSUS"
            else:
                revenue_status = "UNAVAILABLE"
                revenue_reason = c_res["reason"]
        except revenue_guidance.GuidanceError:
            revenue_status = "UNAVAILABLE"
            revenue_reason = "INVALID"
        except Exception:
            revenue_status = "UNAVAILABLE"
            revenue_reason = "INVALID"
    elif revenue_status != "AVAILABLE" and rec_status == "NOT_DISCLOSED" and revenue_reason == "NOT_DISCLOSED" and not consensus_entry:
        # No consensus capture for this issuer: the genuine nondisclosure stands, but only for a fully validated record.
        try:
            revenue_guidance.validate_issuer_record(record, expected_symbol=issuer)
        except revenue_guidance.GuidanceError:
            revenue_reason = "INVALID"

    # 3. Extract order recognition view from v2
    order_m6 = (v2_forecast.get("m6") or {}) if isinstance(v2_forecast.get("m6"), Mapping) else {}
    order_m12 = (v2_forecast.get("m12") or {}) if isinstance(v2_forecast.get("m12"), Mapping) else {}
    has_rec_m6 = order_m6.get("status") == "AVAILABLE" and order_m6.get("basis") == "RECOGNITION"
    has_rec_m12 = order_m12.get("status") == "AVAILABLE" and order_m12.get("basis") == "RECOGNITION"

    contracted_rec = None
    if has_rec_m6 or has_rec_m12:
        contracted_rec = {
            "m6": {
                "amount": order_m6.get("amount"), "currency": order_m6.get("currency"),
                "start": order_m6.get("start"), "end": order_m6.get("end"),
                "as_of": order_m6.get("as_of"), "share_pct": order_m6.get("share_pct"),
                "rpo": order_m6.get("rpo"),
            } if has_rec_m6 else None,
            "m12": {
                "amount": order_m12.get("amount"), "currency": order_m12.get("currency"),
                "start": order_m12.get("start"), "end": order_m12.get("end"),
                "as_of": order_m12.get("as_of"), "share_pct": order_m12.get("share_pct"),
                "rpo": order_m12.get("rpo"),
            } if has_rec_m12 else None,
        }

    # 4. Reported quarters and arithmetic (scoped failure handling)
    tiles: dict[str, Any] = {}
    arith: dict[str, Any] | None = None

    try:
        if isinstance(reported_quarters, list) and len(reported_quarters) >= 4:
            anchor_date = reported_quarters[-1].get("end")
        elif isinstance(record, Mapping) and record.get("anchor_end"):
            anchor_date = record.get("anchor_end")
        elif isinstance(record, Mapping) and record.get("anchor_quarter"):
            anchor_date = record.get("anchor_quarter", {}).get("end")

        if anchor_date:
            start_date = str(date.fromisoformat(anchor_date) + timedelta(days=1))

        if revenue_status == "AVAILABLE" and fw_result is not None:
            f_quarters = fw_result["forward_quarters"]
            if f_quarters:
                start_date = f_quarters[0]["start"]
            f_amts = [fw_result["f1"], fw_result["f2"], fw_result["f3"], fw_result["f4"]]
            actuals = [float(q["revenue"]) for q in reported_quarters if _number(q.get("revenue")) is not None]
            arith = revenue_guidance.compute_v3_arithmetic(actuals, f_amts)

            if arith.get("status") not in ("AVAILABLE", "MISSING_HISTORY"):
                revenue_status = "UNAVAILABLE"
                revenue_reason = "INVALID"
            else:
                if revenue_basis == "CONSENSUS":
                    currency = consensus_entry.get("currency") if consensus_entry else None
                elif record.get("claims") and record["claims"][0].get("currency"):
                    currency = record["claims"][0]["currency"]
                elif reported_quarters and reported_quarters[0].get("currency"):
                    currency = reported_quarters[0]["currency"]
                elif record.get("currency"):
                    currency = record["currency"]
                else:
                    currency = None

                if not currency or currency not in revenue_guidance.CURRENCIES:
                    revenue_status = "UNAVAILABLE"
                    revenue_reason = "INVALID"
                elif any(q.get("currency") != currency for q in reported_quarters):
                    revenue_status = "UNAVAILABLE"
                    revenue_reason = "INVALID"
                else:
                    basis_label = "公司營收財測＋模型（非訂單）" if revenue_basis == "COMPANY_GUIDANCE" else "非公司揭露、非訂單：分析師季度營收共識＋模型"

                    for key, (f_end_idx, amt, ttm_val, chg_val, h_lbl) in (
                        ("m6", (1, arith["amount6"], arith.get("ttm6"), arith.get("change6"), "約6個月（2財季）")),
                        ("m12", (3, arith["amount12"], arith.get("ttm12"), arith.get("change12"), "約1年（4財季）")),
                    ):
                        f_end = f_quarters[f_end_idx]["end"] if len(f_quarters) > f_end_idx else None
                        if chg_val is not None:
                            scenario = {"status": "AVAILABLE", "change": chg_val}
                        else:
                            scenario = {"status": "NO_BASIS", "reason": "NO_REVENUE_HISTORY"}
                        tile_rec = contracted_rec.get(key) if contracted_rec else None

                        tiles[key] = {
                            "status": "AVAILABLE",
                            "basis": revenue_basis,
                            "basis_label": basis_label,
                            "amount": amt,
                            "currency": currency,
                            "start": start_date,
                            "end": f_end,
                            "horizon_label": h_lbl,
                            "qualifier": f"自{start_date}起，非今日起" if start_date else "",
                            "ttm_revenue": ttm_val,
                            "scenario": scenario,
                            "warning": fw_result.get("warning"),
                            "contracted_recognition": tile_rec,
                        }
    except Exception:
        revenue_status = "UNAVAILABLE"
        revenue_reason = "INVALID"

    if revenue_status != "AVAILABLE":
        if has_rec_m6 or has_rec_m12:
            # Fallback to contracted recognition on Tile 2 with no price basis on Tile 3
            for key, (order_h, h_lbl) in (("m6", (order_m6, "半年")), ("m12", (order_m12, "1年"))):
                if order_h.get("status") == "AVAILABLE" and order_h.get("basis") == "RECOGNITION":
                    tiles[key] = {
                        "status": "AVAILABLE",
                        "basis": "RECOGNITION",
                        "basis_label": "已簽約預計認列",
                        "amount": order_h.get("amount"),
                        "currency": order_h.get("currency"),
                        "start": order_h.get("start"),
                        "end": order_h.get("end"),
                        "horizon_label": h_lbl,
                        "qualifier": f"自{order_h.get('start')}起，非今日起",
                        "rpo": order_h.get("rpo"),
                        "share_pct": order_h.get("share_pct"),
                        "scenario": {"status": "NO_BASIS", "reason": "NO_REVENUE_BASIS"},
                        "warning": None,
                    }
                else:
                    # The unretained horizon echoes the top-level revenue reason (the Worker's unavailable state
                    # machine re-derives it on every surface); the order side's own state stays in the order view.
                    tiles[key] = _unavailable(revenue_reason or "NOT_DISCLOSED_HORIZON", "NO_REVENUE_BASIS")
        else:
            reason = revenue_reason or v2_forecast.get("reason") or "NOT_DISCLOSED"
            if reason not in revenue_guidance.REASONS_V3:
                reason = "INVALID"
            tiles["m6"] = _unavailable(reason, "NO_REVENUE_BASIS")
            tiles["m12"] = _unavailable(reason, "NO_REVENUE_BASIS")

    available = any(tiles[k]["status"] == "AVAILABLE" for k in ("m6", "m12"))
    overall_reason = top_reason(tiles["m6"], tiles["m12"]) if not available else None

    ALLOWED_DOC_KEYS = (
        "id", "issuer", "publisher", "title", "source_kind", "url",
        "published_date", "published_at", "retrieved_at", "sha256", "byte_size", "lineage_id"
    )
    raw_docs = record.get("documents", []) if isinstance(record, Mapping) else []
    projected_docs = []
    if isinstance(raw_docs, list):
        for doc in raw_docs:
            if isinstance(doc, dict):
                projected_docs.append({k: doc[k] for k in ALLOWED_DOC_KEYS if k in doc})

    ALLOWED_CLAIM_KEYS = (
        "id", "document_id", "locator", "passage", "quote", "metric", "assertion_kind",
        "currency", "unit_multiplier", "amount", "low", "high", "stated_point",
        "plus_minus_amount", "plus_minus_percent", "original_representation",
        "scope", "scope_label", "fiscal_label", "period_kind", "period_start",
        "period_end", "start", "end", "accounting_basis", "reaffirmed_by", "corroborated_by", "revision", "checked_at"
    )
    raw_claims = record.get("claims", []) if isinstance(record, Mapping) else []
    projected_claims = []
    if isinstance(raw_claims, list):
        for c in raw_claims:
            if isinstance(c, dict):
                projected_claims.append({k: c[k] for k in ALLOWED_CLAIM_KEYS if k in c})

    ALLOWED_ACTUAL_KEYS = (
        "fiscal_label", "start", "end", "revenue", "currency", "scope",
        "accounting_basis", "document_id", "locator", "derivation"
    )
    projected_actuals = []
    if isinstance(reported_quarters, list):
        for q in reported_quarters:
            if isinstance(q, dict):
                projected_actuals.append({k: q[k] for k in ALLOWED_ACTUAL_KEYS if k in q})

    # A4: every outer duplicate travels as the projected, bounded copy - never the raw record fields (an unknown
    # actual field, e.g. a multi-megabyte extra key, must not reach the sealed Top20 object or the evidence).
    ALLOWED_INTERVAL_KEYS = ("fiscal_label", "start", "end", "calendar_document_id", "calendar_locator")
    projected_intervals = []
    raw_intervals = record.get("forward_intervals", []) if isinstance(record, Mapping) else []
    if isinstance(raw_intervals, list):
        for intv in raw_intervals:
            if isinstance(intv, dict):
                projected_intervals.append({k: intv[k] for k in ALLOWED_INTERVAL_KEYS if k in intv})

    ALLOWED_FY_REC_KEYS = ("fy_claim_id", "ytd_start", "ytd_end", "ytd_revenue", "ytd_quarter_ends")
    raw_fy_rec = record.get("fy_reconciliation") if isinstance(record, Mapping) else None
    projected_fy_rec = {k: raw_fy_rec[k] for k in ALLOWED_FY_REC_KEYS if k in raw_fy_rec} if isinstance(raw_fy_rec, dict) else None

    ALLOWED_REVIEWED_KEYS = ("id", "disposition", "reviewed_at", "note")
    raw_reviewed = record.get("reviewed_later_documents") if isinstance(record, Mapping) else None
    projected_reviewed = []
    if isinstance(raw_reviewed, list):
        for rld in raw_reviewed:
            if isinstance(rld, dict):
                projected_reviewed.append({k: rld[k] for k in ALLOWED_REVIEWED_KEYS if k in rld})

    def _consensus_projection(entry: Any) -> dict[str, Any] | None:
        """The bounded consensus capture: the sealed metadata the Worker re-validates (item 15), nothing else."""
        if not isinstance(entry, Mapping):
            return None
        out: dict[str, Any] = {"symbol": entry.get("symbol"), "currency": entry.get("currency")}
        for key in ("scope", "captured_at", "retrieved_at", "source_url"):
            if entry.get(key) is not None:
                out[key] = entry[key]
        quarters = entry.get("quarters")
        if isinstance(quarters, list):
            ALLOWED_CONSENSUS_Q_KEYS = ("period", "scope", "currency", "start", "end", "revenue", "avg", "analysts")
            out["quarters"] = [{k: q[k] for k in ALLOWED_CONSENSUS_Q_KEYS if k in q} for q in quarters if isinstance(q, dict)][:2]
        return out

    def _release_channels_projection(rec: Mapping[str, Any] | None) -> dict[str, Any] | None:
        """The reviewed release-channel wiring (item 2): channel identity the receipt validators bind to.
        Only the validated shapes travel sealed; anything else is not channel wiring."""
        rc = rec.get("release_channels") if isinstance(rec, Mapping) else None
        if not isinstance(rc, Mapping):
            return None
        out: dict[str, Any] = {}
        cik = rc.get("sec_cik")
        if isinstance(cik, int) and not isinstance(cik, bool) and cik > 0:
            out["sec_cik"] = cik
        wire_symbol = rc.get("wire_symbol")
        if isinstance(wire_symbol, str) and wire_symbol:
            out["wire_symbol"] = wire_symbol
        wire_names = rc.get("wire_names")
        if isinstance(wire_names, list) and wire_names and all(isinstance(n, str) for n in wire_names):
            out["wire_names"] = wire_names[:8]
        # The official IR channel (Astra W1 ruling, astra-ir-coverage): the validated kind + https feed URL pair and the
        # reviewed guidance-release title travel sealed, so the Worker binds the receipt's ISSUER_IR channel to the
        # registry's own IR host and derives the IR_COVERAGE_MISSING diagnostic.
        ir = rc.get("ir")
        if isinstance(ir, Mapping) and ir.get("kind") in ("Q4_PRESS_RELEASES", "RSS", "NEWSROOM_HTML") \
                and isinstance(ir.get("url"), str) and ir["url"].startswith("https://") and len(ir["url"]) <= 400:
            out["ir"] = {"kind": ir["kind"], "url": ir["url"]}
        ir_title = rc.get("ir_guidance_release_title")
        if isinstance(ir_title, str) and ir_title and len(ir_title) <= 200:
            out["ir_guidance_release_title"] = ir_title
        return out or None

    # A1: the approval's identity and this record's review decisions seal beside the evidence (the Worker validates
    # their presence, shape and time coherence); they are null exactly when the profile did not admit the record.
    approval_record = None
    if isinstance(approval, Mapping) and isinstance(approval.get("records"), Mapping):
        approval_record = approval["records"].get(issuer)
    profile_sealed = profile_err is None and not machine
    evidence: dict[str, Any] = {
        "revenue_registry_status": reg_status,
        "revenue_registry_sha256": reg_sha256,
        "cutoff": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "formula": FORMULA_V3,
        "horizon_convention": HORIZON_CONVENTION_V3,
        "consensus_enabled": consensus_enabled,
        "url_prefixes": list(record.get("url_prefixes", []))[:8] if isinstance(record, Mapping) else [],
        "documents": projected_docs,
        "claims": projected_claims,
        "reported_quarters": projected_actuals,
        "forward_intervals": projected_intervals,
        "fy_reconciliation": projected_fy_rec,
        "latest_release_check": fw_result.get("receipt") if fw_result else None,
        "reviewed_later_documents": projected_reviewed,
        "consensus": _consensus_projection(fw_result.get("consensus")) if (fw_result and revenue_basis == "CONSENSUS") else None,
        "order_evidence": v2_forecast.get("evidence"),
        "release_channels": _release_channels_projection(record),
        "consensus_fault": consensus_fault,
        "release_check_fault": release_fault if (release_fault and release_checks_cache is not None) else None,
        "approval_sha256": approval.get("sha256") if (profile_sealed and isinstance(approval, Mapping)) else None,
        "approval_approved_at": approval.get("approved_at") if (profile_sealed and isinstance(approval, Mapping)) else None,
        "approval_decisions": (list(approval_record["decisions"]) if isinstance(approval_record, Mapping) else None)
        if profile_sealed else None,
    }
    if auto_item is not None and auto_item.evidence is not None:
        # B1 in-memory AutoAdmissionEvidence (B3 defines the sealed schema and the Worker readers; not published).
        evidence["auto_update"] = {**auto_item.evidence, "cutoff": snapshot.cutoff, "input_digest": snapshot.input_digest,
                                   "generation_sha256": snapshot.generation_sha256}

    # Bounded allowlisted projection on the evidence-limit path (Astra r5 item 20, A4 r7): the scoped failure must
    # stay small. The oversized revenue originals are cleared, and a canonicalization failure is itself the limit
    # signal (never swallowed and continued with unsafe originals). The independently validated sibling order
    # recognition (e.g. NVDA's m12 USD 1,248,000,000) is PRESERVED: its tile keeps its own bounded evidence through
    # the retained order_evidence subtree, so the Worker re-derives exactly that scoped state - never INVALID and
    # never a wiped Top20 entry.
    ev_bytes = 0
    canonicalized = True
    try:
        ev_bytes = len(revenue_guidance.canonical_json(evidence).encode("utf-8"))
    except Exception:
        canonicalized = False
    evidence_limited = (not canonicalized) or ev_bytes > 100_000
    if evidence_limited:
        revenue_status = "UNAVAILABLE"
        revenue_reason = "EVIDENCE_LIMIT"
        revenue_diagnostic = None
        for key, (has_rec, order_h) in (("m6", (has_rec_m6, order_m6)), ("m12", (has_rec_m12, order_m12))):
            if has_rec:
                tiles[key] = {
                    "status": "AVAILABLE",
                    "basis": "RECOGNITION",
                    "basis_label": "已簽約預計認列",
                    "amount": order_h.get("amount"),
                    "currency": order_h.get("currency"),
                    "start": order_h.get("start"),
                    "end": order_h.get("end"),
                    "horizon_label": "半年" if key == "m6" else "1年",
                    "qualifier": f"自{order_h.get('start')}起，非今日起",
                    "rpo": order_h.get("rpo"),
                    "share_pct": order_h.get("share_pct"),
                    "scenario": {"status": "NO_BASIS", "reason": "NO_REVENUE_BASIS"},
                    "warning": None,
                }
            else:
                tiles[key] = _unavailable("EVIDENCE_LIMIT", "NO_REVENUE_BASIS")
        available = any(tiles[k]["status"] == "AVAILABLE" for k in ("m6", "m12"))
        overall_reason = None if available else "EVIDENCE_LIMIT"
        for key in ("documents", "claims", "reported_quarters", "forward_intervals", "consensus",
                    "latest_release_check", "reviewed_later_documents"):
            evidence[key] = [] if key in ("documents", "claims", "reported_quarters", "forward_intervals") else None
        # order_evidence stays sealed (the bounded v2 projection): the preserved recognition re-derives from it.
        evidence["fy_reconciliation"] = None
        evidence["release_channels"] = None
        evidence["approval_sha256"] = None
        evidence["approval_approved_at"] = None
        evidence["approval_decisions"] = None
        fw_result = None
        # contracted_rec stays: it is the bounded projection of the validated sibling v2 recognition, which the
        # Worker re-derives from order_evidence and requires beside it (acceptance r7 A4).

    return {
        "version": VERSION3,
        "issuer": issuer,
        "formula": FORMULA_V3,
        "status": "AVAILABLE" if available else "UNAVAILABLE",
        "reason": overall_reason,
        "revenue_status": revenue_status,
        "revenue_basis": revenue_basis,
        "revenue_reason": revenue_reason,
        "revenue_diagnostic": revenue_diagnostic,
        "horizon_convention": HORIZON_CONVENTION_V3,
        "anchor_date": anchor_date,
        "cutoff": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "m6": tiles["m6"],
        "m12": tiles["m12"],
        "reported_quarters": [] if evidence_limited else projected_actuals,
        "baseline_b": arith.get("baseline_b") if arith else None,
        "forward_quarters": [] if evidence_limited else (fw_result.get("forward_quarters") if fw_result else []),
        "warning": None if evidence_limited else (fw_result.get("warning") if fw_result else None),
        "contracted_recognition": contracted_rec,
        "stock_sensitivity": v2_forecast.get("stock_sensitivity"),
        "order_view": {
            "status": v2_forecast.get("status"),
            "reason": v2_forecast.get("reason"),
            "m6": v2_forecast.get("m6"),
            "m12": v2_forecast.get("m12"),
        },
        "references": v2_forecast.get("references", []),
        "assumptions": ASSUMPTIONS_V3,
        "evidence": evidence,
    }
