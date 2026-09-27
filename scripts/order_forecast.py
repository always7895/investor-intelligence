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
Fixed-period figures (a 24-month schedule, annual new-order guidance) are references only. No analyst figure is used.
Every record names its issuer, scope, currency and evidence; cloud/src/v213/order-forecast.ts re-validates all of it.
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
