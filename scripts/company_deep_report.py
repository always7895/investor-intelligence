#!/usr/bin/env python3
"""Data-driven company deep report (operator rule 2026-09-25: detailed, nothing hand-written).

Every section is computed from primary data at run time and cites it:

- business      latest 10-K / 20-F business excerpt (English, extractor-selected, SEC-cited); an unverified translation is never public text
- momentum      single-quarter revenue, gross and operating margin versus the same quarter a
                year earlier (SEC XBRL company facts, calendar ``frame`` tags)
- visibility    remaining performance obligations (RPO) now versus a year earlier
- capacity      latest fiscal-year capital expenditure and its share of revenue
- balance sheet cash, long-term debt and diluted-share change (dilution)
- industry      the company's SIC industry signals and phase from the data-driven rotation
- phase         thesis_phase (company scope) from the company's own and industry signals,
                with the next review date and the falsifiers that would flip it
- orders        if the signed orders are delivered on the schedule the latest 10-Q/10-K discloses
                (order_timing): contracted revenue for 6M/1Y/2Y versus the current run rate, and a
                revenue/price growth floor only where that coverage exceeds 100% (stated premises)

Missing facts are reported as missing; no estimate, target price or probability is produced.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import thesis_phase  # noqa: E402
import sec_ticker_cache  # noqa: E402

OUTPUT_PATH = ROOT / "data" / "cache" / "company_deep_reports_latest.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
REVENUE_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")
TAGS = {
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "rpo": ("RevenueRemainingPerformanceObligation",),
    "inventory": ("InventoryNet",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
             "CashAndDueFromBanks"),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations",
                       "LongTermDebtAndFinanceLeasesNoncurrent", "OtherLongTermDebtNoncurrent"),
    "diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsForCapitalImprovements"),
}
Fetch = Callable[[str], bytes]


def _rows(facts: Mapping[str, Any], tags: Sequence[str], unit: str) -> list[dict[str, Any]]:
    """Rows of the tag the company still reports most recently (issuers switch tags over the years)."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    best: list[dict[str, Any]] = []
    for tag in tags:
        rows = [dict(row, tag=tag) for row in ((gaap.get(tag) or {}).get("units") or {}).get(unit, [])
                if isinstance(row.get("val"), (int, float))]
        if rows and (not best or max(r["end"] for r in rows) > max(r["end"] for r in best)):
            best = rows
    return best


def _by_frame(rows: Sequence[Mapping[str, Any]], instant: bool) -> dict[str, dict[str, Any]]:
    pattern = r"CY\d{4}Q[1-4]I" if instant else r"CY\d{4}Q[1-4]"
    frames: dict[str, dict[str, Any]] = {}
    for row in rows:
        frame = row.get("frame")
        if isinstance(frame, str) and re.fullmatch(pattern, frame):
            frames[frame] = dict(row)
    return frames


def _year_ago(frame: str) -> str:
    return f"CY{int(frame[2:6]) - 1}{frame[6:]}"


def _latest_pair(frames: Mapping[str, Mapping[str, Any]]) -> tuple[dict | None, dict | None]:
    if not frames:
        return None, None
    latest_key = max(frames, key=lambda key: (int(key[2:6]), key[7]))
    return dict(frames[latest_key]), (dict(frames[_year_ago(latest_key)]) if _year_ago(latest_key) in frames else None)


def _pct(now: float | None, prior: float | None) -> float | None:
    if now is None or prior is None or prior == 0:
        return None
    return round((now / prior - 1) * 100, 2)


def _fiscal_fourth_quarter(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Fiscal fourth quarter of the latest fiscal year from the same revenue tag. A 10-K files the full year, so the
    last quarter has no calendar frame: latest annual row (350-380 days) minus the nine-month YTD row (260-285 days)
    that starts on the same date. The latest filing wins duplicates; nothing is produced when the inputs are
    missing, non-positive or the result is not positive."""
    dated: list[tuple[Mapping[str, Any], int]] = []
    for row in rows:
        start, end = row.get("start"), row.get("end")
        if isinstance(start, str) and isinstance(end, str):
            try:
                span = (date.fromisoformat(end) - date.fromisoformat(start)).days
            except ValueError:
                continue
            dated.append((row, span))

    def latest(pairs: list[tuple[Mapping[str, Any], int]]) -> Mapping[str, Any]:
        return max(pairs, key=lambda pair: (pair[0]["end"], str(pair[0].get("accn") or "")))[0]

    annuals = [(row, span) for row, span in dated if 350 <= span <= 380 and row["val"] > 0]
    if not annuals:
        return None
    annual = latest(annuals)
    ytd = [(row, span) for row, span in dated if 260 <= span <= 285 and row["start"] == annual["start"] and row["val"] > 0]
    if not ytd:
        return None
    nine_months = latest(ytd)
    value = annual["val"] - nine_months["val"]
    if value <= 0:
        return None
    start = (date.fromisoformat(nine_months["end"]) + timedelta(days=1)).isoformat()  # the day after the nine months
    return {"val": value, "start": start, "end": annual["end"], "accession": annual.get("accn"), "basis": "DERIVED_Q4",
            "derivation": {"annual": annual["val"], "annual_start": annual["start"], "annual_accession": annual.get("accn"),
                           "nine_months": nine_months["val"], "nine_months_end": nine_months["end"],
                           "nine_months_accession": nine_months.get("accn")}}


IFRS_ANNUAL_FORMS = ("20-F", "20-F/A")  # 40-F and 6-K are not claimed: the annual-report parser does not cover them
MAX_IFRS_ROWS = 4000  # per unit list; a longer list is a typed gap, never a truncation
MAX_IFRS_UNITS = 16


def _ifrs_day(value: Any) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _ifrs_units(facts: Mapping[str, Any], concept: str) -> Mapping[str, Any] | None:
    container = facts.get("facts") if isinstance(facts, Mapping) else None
    taxonomy = container.get("ifrs-full") if isinstance(container, Mapping) else None
    entry = taxonomy.get(concept) if isinstance(taxonomy, Mapping) else None
    units = entry.get("units") if isinstance(entry, Mapping) else None
    return units if isinstance(units, Mapping) and units else None


def _ifrs_rows(facts: Mapping[str, Any], concept: str, today: date) -> tuple[list[dict[str, Any]], bool]:
    """Eligible annual 20-F rows of ONE ifrs-full concept in monetary units (three uppercase letters, as the facts name them). A
    row with a missing, future or inconsistent date, a non-annual span or form, an unmappable accession or a non-finite value is
    excluded, never repaired. The flag is True when a list is over the bound (nothing is truncated)."""
    units = _ifrs_units(facts, concept) or {}
    monetary = [unit for unit in units if isinstance(unit, str) and re.fullmatch(r"[A-Z]{3}", unit)]
    if len(monetary) > MAX_IFRS_UNITS:
        return [], True
    rows: list[dict[str, Any]] = []
    for unit in monetary:
        source = units[unit]
        if not isinstance(source, list):
            continue
        if len(source) > MAX_IFRS_ROWS:
            return [], True
        for row in source:
            if not isinstance(row, Mapping):
                continue
            value = row.get("val")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            try:
                number = float(value)
            except OverflowError:
                continue
            if not math.isfinite(number) or abs(number) >= 1e18:
                continue
            start, end, filed = _ifrs_day(row.get("start")), _ifrs_day(row.get("end")), _ifrs_day(row.get("filed"))
            accession = row.get("accn")
            if start is None or end is None or filed is None or filed > today or end > filed or not 350 <= (end - start).days <= 380:
                continue
            if row.get("form") not in IFRS_ANNUAL_FORMS or row.get("fp") not in (None, "FY"):
                continue
            if not isinstance(accession, str) or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
                continue
            rows.append({"unit": unit, "val": number, "start": start, "end": end, "filed": filed, "accession": accession,
                         "form": row["form"]})
    return rows, False


def ifrs_annual(facts: Mapping[str, Any], today: date) -> dict[str, Any] | None:
    """Annual-only IFRS fallback for an issuer WITHOUT any us-gaap USD revenue row (None: no ifrs-full Revenue facts, nothing to
    show). Every value is bound to ONE selected accession, period, reporting unit and taxonomy; a missing, mixed or ambiguous
    context is a typed gap, never a first-row, first-currency or last-write guess. No FX conversion, no quarter inference and no
    concept alias beyond the ifrs-full Revenue / GrossProfit that bottleneck_top20_v3 already recognises."""
    if _ifrs_units(facts, "Revenue") is None:
        return None
    base = {"basis": "ANNUAL_20F", "taxonomy": "ifrs-full", "revenue_concept": "Revenue"}
    revenue, too_large = _ifrs_rows(facts, "Revenue", today)
    if too_large:
        return {**base, "status": "IFRS_INPUT_TOO_LARGE"}
    if not revenue:
        return {**base, "status": "IFRS_NO_ELIGIBLE_ANNUAL"}
    end = max(row["end"] for row in revenue)
    latest = [row for row in revenue if row["end"] == end]
    if len({row["start"] for row in latest}) != 1:
        return {**base, "status": "IFRS_AMBIGUOUS_PERIOD"}
    if len({row["unit"] for row in latest}) != 1:
        return {**base, "status": "IFRS_AMBIGUOUS_UNIT"}
    start, unit = latest[0]["start"], latest[0]["unit"]
    filed = max(row["filed"] for row in latest)
    accessions = {row["accession"] for row in latest if row["filed"] == filed}
    if len(accessions) != 1:
        return {**base, "status": "IFRS_AMBIGUOUS_ACCESSION"}
    accession = next(iter(accessions))
    selected = [row for row in latest if row["accession"] == accession]
    if len({(row["val"], row["form"]) for row in selected}) != 1:
        return {**base, "status": "IFRS_CONFLICTING_DUPLICATE"}
    revenue_value, form = selected[0]["val"], selected[0]["form"]
    if revenue_value < 0:
        return {**base, "status": "IFRS_INVALID_VALUE"}
    gaps: list[str] = []
    # Comparable preceding annual revenue: the SAME accession and unit, starts and ends one year (350-380 days) earlier.
    prior = {(row["start"], row["end"], row["val"]) for row in revenue
             if row["accession"] == accession and row["unit"] == unit
             and 350 <= (end - row["end"]).days <= 380 and 350 <= (start - row["start"]).days <= 380}
    yoy, prior_value, prior_end = None, None, None
    if not prior:
        gaps.append("IFRS_PRIOR_MISSING")
    elif len({(row_start, row_end) for row_start, row_end, _ in prior}) != 1:
        gaps.append("IFRS_PRIOR_AMBIGUOUS")
    elif len({row_value for _, _, row_value in prior}) != 1:
        gaps.append("IFRS_PRIOR_CONFLICTING")
    else:
        _, candidate_end, candidate = next(iter(prior))
        try:
            growth = (revenue_value / candidate - 1) * 100 if candidate > 0 else None
        except (OverflowError, ZeroDivisionError):
            growth = None
        if growth is None or not math.isfinite(growth):
            gaps.append("IFRS_PRIOR_INVALID_DENOMINATOR")
        else:
            yoy, prior_value, prior_end = round(growth, 2), candidate, candidate_end
    gross_rows, gross_too_large = _ifrs_rows(facts, "GrossProfit", today)
    gross_values = {row["val"] for row in gross_rows if row["accession"] == accession and row["unit"] == unit
                    and row["start"] == start and row["end"] == end}
    gross, margin = None, None
    if gross_too_large:
        gaps.append("IFRS_GROSS_TOO_LARGE")
    elif not gross_values:
        gaps.append("IFRS_GROSS_MISSING")
    elif len(gross_values) != 1:
        gaps.append("IFRS_GROSS_CONFLICTING")
    else:
        gross = next(iter(gross_values))
        ratio = gross / revenue_value * 100 if revenue_value > 0 else None
        if ratio is None or not math.isfinite(ratio):
            gaps.append("IFRS_MARGIN_UNAVAILABLE")
        else:
            margin = round(ratio, 2)
    return {**base, "status": "OK", "unit": unit, "form": form, "accession": accession, "filed": filed.isoformat(),
            "period_start": start.isoformat(), "period_end": end.isoformat(), "revenue": revenue_value,
            "revenue_prior": prior_value, "revenue_prior_period_end": prior_end.isoformat() if prior_end else None,
            "revenue_yoy_pct": yoy, "gross_profit": gross, "gross_profit_concept": "GrossProfit" if gross is not None else None,
            "gross_margin_pct": margin, "gaps": gaps}


def extract_metrics(facts: Mapping[str, Any], today: date | None = None) -> dict[str, Any]:
    """Same-quarter comparisons from calendar frames; missing facts stay None. ``annual_context`` is added ONLY when the annual-only
    IFRS fallback produced a result (an issuer without any us-gaap USD revenue row); it never writes a quarterly key, and other us-gaap
    facts the issuer carries (RPO, cash, debt, ...) are computed as before. ``today`` bounds the IFRS filing dates."""
    revenue_frames = _by_frame(_rows(facts, REVENUE_TAGS, "USD"), instant=False)
    revenue, revenue_prior = _latest_pair(revenue_frames)
    frame = revenue["frame"] if revenue else None
    out: dict[str, Any] = {"quarter_frame": frame, "quarter_end": revenue["end"] if revenue else None,
                           "revenue": revenue and revenue["val"], "revenue_prior": revenue_prior and revenue_prior["val"],
                           "revenue_accession": revenue and revenue.get("accn")}
    out["revenue_yoy_pct"] = _pct(out["revenue"], out["revenue_prior"])

    def quarter_value(key: str, when: str | None) -> float | None:
        if not when:
            return None
        row = _by_frame(_rows(facts, TAGS[key], "USD"), instant=False).get(when)
        return row["val"] if row else None

    for key in ("gross_profit", "operating_income", "net_income"):
        out[key] = quarter_value(key, frame)
        out[f"{key}_prior"] = quarter_value(key, _year_ago(frame) if frame else None)
    for margin, key in (("gross_margin", "gross_profit"), ("operating_margin", "operating_income")):
        now = out[key] / out["revenue"] * 100 if out[key] is not None and out["revenue"] else None
        prior = out[f"{key}_prior"] / out["revenue_prior"] * 100 if out[f"{key}_prior"] is not None and out["revenue_prior"] else None
        out[f"{margin}_pct"] = None if now is None else round(now, 2)
        out[f"{margin}_change_pp"] = None if now is None or prior is None else round(now - prior, 2)
    for key in ("rpo", "inventory", "cash", "long_term_debt"):
        latest, prior = _latest_pair(_by_frame(_rows(facts, TAGS[key], "USD"), instant=True))
        out[key] = latest and latest["val"]
        out[f"{key}_tag"] = latest and latest.get("tag")
        out[f"{key}_as_of"] = latest and latest["end"]
        out[f"{key}_yoy_pct"] = _pct(latest and latest["val"], prior and prior["val"])
    # The order run rate needs the quarter that matches the RPO as-of date: the latest frame quarter, or the
    # derived fiscal fourth quarter when it ends later (a fiscal Q4 is filed in the 10-K only as the full year).
    fourth = _fiscal_fourth_quarter(_rows(facts, REVENUE_TAGS, "USD"))
    order_candidates: list[dict[str, Any]] = []
    if out["revenue"] is not None and out["quarter_end"]:
        order_candidates.append({"val": out["revenue"], "start": revenue.get("start") if revenue else None, "end": out["quarter_end"],
                                 "accession": out["revenue_accession"], "basis": "FRAME"})
    if fourth is not None and (out["quarter_end"] is None or fourth["end"] > out["quarter_end"]):
        order_candidates.append(fourth)
    out["order_revenue"], out["order_quarter_end"], out["order_quarter"] = None, None, None
    if order_candidates and out.get("rpo_as_of"):
        chosen = min(order_candidates, key=lambda candidate:
                     abs((date.fromisoformat(candidate["end"]) - date.fromisoformat(out["rpo_as_of"])).days))
        out["order_revenue"], out["order_quarter_end"], out["order_quarter"] = chosen["val"], chosen["end"], chosen
    shares, shares_prior = _latest_pair(_by_frame(_rows(facts, TAGS["diluted_shares"], "shares"), instant=False))
    out["diluted_shares"] = shares and shares["val"]
    out["dilution_yoy_pct"] = _pct(shares and shares["val"], shares_prior and shares_prior["val"])
    annual = [row for row in _rows(facts, TAGS["capex"], "USD") if row.get("fp") == "FY" and row.get("form") in ("10-K", "20-F")]
    capex = max(annual, key=lambda row: row["end"]) if annual else None
    fy_revenue = [row for row in _rows(facts, REVENUE_TAGS, "USD") if capex and row.get("end") == capex["end"] and row.get("fp") == "FY"]
    out["capex_fy"] = capex and capex["val"]
    out["capex_fy_end"] = capex and capex["end"]
    out["capex_share_of_revenue_pct"] = (round(capex["val"] / fy_revenue[0]["val"] * 100, 2)
                                         if capex and fy_revenue and fy_revenue[0]["val"] else None)
    out["inventory_minus_revenue_pp"] = (round(out["inventory_yoy_pct"] - out["revenue_yoy_pct"], 2)
                                         if out["inventory_yoy_pct"] is not None and out["revenue_yoy_pct"] is not None else None)
    # Annual-only IFRS fallback: only without any us-gaap USD revenue row, and the key exists only when there is an IFRS result.
    ifrs_context = None if _rows(facts, REVENUE_TAGS, "USD") else ifrs_annual(facts, today or date.today())
    if ifrs_context is not None:
        out["annual_context"] = ifrs_context
    return out


SEC_ACCESSION_RE = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
CALENDAR_QUARTER_BOUNDS = {1: ("01-01", "03-31"), 2: ("04-01", "06-30"), 3: ("07-01", "09-30"), 4: ("10-01", "12-31")}


def _strict_day(value: Any) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _calendar_dependency(row: Mapping[str, Any] | None, tag_rows: Sequence[Mapping[str, Any]], unit: str,
                         instant: bool) -> dict[str, Any] | None:
    """Knowledge-time provenance of ONE legacy-selected us-gaap row, or None (PRODUCER-CLOCK-03).

    Exact calendar quarters only: a duration row is framed CYyyyyQq and runs exactly from Jan 1/Apr 1/Jul 1/Oct 1 to
    Mar 31/Jun 30/Sep 30/Dec 31 of that year; an instant row is framed CYyyyyQqI, ends on that quarter end and has no
    start. No fiscal or 52/53-week tolerance. The row needs a finite non-bool value, an SEC accession and a filed day on
    or after its end. Another row of the selected tag in the same frame with a different value, filing, accession or
    period makes the legacy last-row selection input-order dependent, so the dependency is unknown.
    """
    if not isinstance(row, Mapping):
        return None
    frame = row.get("frame")
    match = re.fullmatch(r"CY([0-9]{4})Q([1-4])(I?)", frame) if isinstance(frame, str) else None
    if match is None or bool(match.group(3)) != instant:
        return None
    first, last = CALENDAR_QUARTER_BOUNDS[int(match.group(2))]
    end, filed = _strict_day(row.get("end")), _strict_day(row.get("filed"))
    if end is None or filed is None or row["end"] != f"{match.group(1)}-{last}" or end > filed:
        return None
    if instant and row.get("start") is not None:
        return None
    if not instant and (_strict_day(row.get("start")) is None or row["start"] != f"{match.group(1)}-{first}"):
        return None
    value, accession, tag = row.get("val"), row.get("accn"), row.get("tag")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if not isinstance(accession, str) or not SEC_ACCESSION_RE.fullmatch(accession) or not isinstance(tag, str):
        return None
    identities = {tuple(repr(other.get(key)) for key in ("val", "filed", "accn", "start", "end"))
                  for other in tag_rows if other.get("frame") == frame}
    if len(identities) != 1:
        return None
    return {"taxonomy": "us-gaap", "tag": tag, "unit": unit, "frame": frame, "start": row.get("start"), "end": row["end"],
            "value": value, "filed": row["filed"], "accession": accession}


def _calendar_pair(now: Mapping[str, Any] | None, prior: Mapping[str, Any] | None, tag_rows: Sequence[Mapping[str, Any]],
                   unit: str, instant: bool) -> list[dict[str, Any]] | None:
    """Current and year-ago dependencies of one legacy pair: same tag and unit, same quarter of the previous year."""
    current = _calendar_dependency(now, tag_rows, unit, instant)
    previous = _calendar_dependency(prior, tag_rows, unit, instant)
    if current is None or previous is None or current["tag"] != previous["tag"] or previous["frame"] != _year_ago(current["frame"]):
        return None
    return [current, previous]


def _clocked(dependencies: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"announced_at": max(dependency["filed"] for dependency in dependencies),
            "dependencies": [dict(dependency) for dependency in dependencies]}


def signal_provenance(facts: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Private knowledge-time provenance of the four company signals (RPO, MARGIN, DILUTION, INVENTORY).

    Re-binds the EXACT operands extract_metrics selected (the same _rows/_by_frame/_latest_pair calls) and keeps a
    signal's clock only when every dependency is an exact-calendar companyfacts row and the operands reproduce the
    legacy metric. announced_at is the latest dependency filing day, never clipped to the evaluation date; any other
    case is None (the signal stays withheld). Metrics, selection and signal values are unchanged; never public text.
    """
    result: dict[str, Any] = {"RPO": None, "MARGIN": None, "DILUTION": None, "INVENTORY": None}
    revenue_rows = _rows(facts, REVENUE_TAGS, "USD")
    revenue = _calendar_pair(*_latest_pair(_by_frame(revenue_rows, instant=False)), revenue_rows, "USD", False)
    if revenue and (revenue[0]["frame"] != metrics.get("quarter_frame") or revenue[0]["end"] != metrics.get("quarter_end")
                    or revenue[0]["value"] != metrics.get("revenue") or revenue[1]["value"] != metrics.get("revenue_prior")):
        revenue = None

    rpo_rows = _rows(facts, TAGS["rpo"], "USD")
    rpo = _calendar_pair(*_latest_pair(_by_frame(rpo_rows, instant=True)), rpo_rows, "USD", True)
    if (rpo and metrics.get("rpo_yoy_pct") is not None and rpo[0]["end"] == metrics.get("rpo_as_of")
            and rpo[0]["tag"] == metrics.get("rpo_tag") and rpo[0]["value"] == metrics.get("rpo")
            and _pct(rpo[0]["value"], rpo[1]["value"]) == metrics["rpo_yoy_pct"]):
        result["RPO"] = _clocked(rpo)

    if revenue and metrics.get("gross_margin_change_pp") is not None and revenue[0]["value"] and revenue[1]["value"]:
        gross_rows = _rows(facts, TAGS["gross_profit"], "USD")
        gross_frames = _by_frame(gross_rows, instant=False)
        gross = _calendar_pair(gross_frames.get(revenue[0]["frame"]), gross_frames.get(revenue[1]["frame"]), gross_rows, "USD", False)
        if (gross and gross[0]["value"] == metrics.get("gross_profit") and gross[1]["value"] == metrics.get("gross_profit_prior")
                and all(g["start"] == r["start"] and g["end"] == r["end"] for g, r in zip(gross, revenue))
                and round(gross[0]["value"] / revenue[0]["value"] * 100 - gross[1]["value"] / revenue[1]["value"] * 100, 2)
                == metrics["gross_margin_change_pp"]):
            result["MARGIN"] = _clocked(gross + revenue)

    share_rows = _rows(facts, TAGS["diluted_shares"], "shares")
    shares = _calendar_pair(*_latest_pair(_by_frame(share_rows, instant=False)), share_rows, "shares", False)
    if (shares and metrics.get("dilution_yoy_pct") is not None and shares[0]["frame"] == metrics.get("quarter_frame")
            and shares[0]["end"] == metrics.get("quarter_end") and shares[0]["value"] == metrics.get("diluted_shares")
            and _pct(shares[0]["value"], shares[1]["value"]) == metrics["dilution_yoy_pct"]):
        result["DILUTION"] = _clocked(shares)

    inventory_rows = _rows(facts, TAGS["inventory"], "USD")
    inventory = _calendar_pair(*_latest_pair(_by_frame(inventory_rows, instant=True)), inventory_rows, "USD", True)
    if (revenue and inventory and metrics.get("inventory_minus_revenue_pp") is not None
            and inventory[0]["frame"] == revenue[0]["frame"] + "I" and inventory[0]["end"] == revenue[0]["end"]
            and inventory[0]["end"] == metrics.get("inventory_as_of") and inventory[0]["value"] == metrics.get("inventory")):
        inventory_yoy = _pct(inventory[0]["value"], inventory[1]["value"])
        revenue_yoy = _pct(revenue[0]["value"], revenue[1]["value"])
        if (inventory_yoy is not None and revenue_yoy is not None
                and round(inventory_yoy - revenue_yoy, 2) == metrics["inventory_minus_revenue_pp"]):
            result["INVENTORY"] = _clocked(inventory + revenue)
    return result


def _announced(provenance: Mapping[str, Any] | None, key: str) -> dict[str, str]:
    """announced_at only from a complete, well-formed private provenance entry; anything else returns {} (unannounced).

    Re-checks the exact entry and dependency key sets, the signal's dependency count and pair order, allowed tags and
    units, every dependency against the producer's own exact-calendar predicate (_calendar_pair), period alignment
    across pairs, and announced_at == max(dependency filed). This is a structural consistency check, NOT authentication:
    only signal_provenance (the in-process producer) binds the original selected rows, and internally consistent
    forged input cannot be detected here.
    """
    # Complete-provenance contract: per signal, the dependency pairs in producer order, each as (allowed legacy tags,
    # unit, instant); exactly two dependencies per pair (RPO 2, MARGIN 4, DILUTION 2, INVENTORY 4).
    shapes = {
        "RPO": ((TAGS["rpo"], "USD", True),),
        "MARGIN": ((TAGS["gross_profit"], "USD", False), (REVENUE_TAGS, "USD", False)),
        "DILUTION": ((TAGS["diluted_shares"], "shares", False),),
        "INVENTORY": ((TAGS["inventory"], "USD", True), (REVENUE_TAGS, "USD", False)),
    }
    # Closed dependency identity schema written by signal_provenance.
    dependency_keys = {"taxonomy", "tag", "unit", "frame", "start", "end", "value", "filed", "accession"}
    shape = shapes.get(key)
    entry = provenance.get(key) if shape is not None and isinstance(provenance, Mapping) else None
    if not isinstance(entry, Mapping) or set(entry) != {"announced_at", "dependencies"}:
        return {}
    dependencies = entry["dependencies"]
    if not isinstance(dependencies, list) or len(dependencies) != 2 * len(shape):
        return {}
    pairs: list[list[dict[str, Any]]] = []
    for index, (tags, unit, instant) in enumerate(shape):
        claimed = dependencies[2 * index:2 * index + 2]
        rows = []
        for dependency in claimed:
            if not isinstance(dependency, Mapping) or set(dependency) != dependency_keys:
                return {}
            if dependency["taxonomy"] != "us-gaap" or dependency["unit"] != unit or dependency["tag"] not in tags:
                return {}
            rows.append({"frame": dependency["frame"], "start": dependency["start"], "end": dependency["end"],
                         "val": dependency["value"], "filed": dependency["filed"], "accn": dependency["accession"],
                         "tag": dependency["tag"]})
        pair = _calendar_pair(rows[0], rows[1], rows, unit, instant)
        if pair is None or pair != [dict(dependency) for dependency in claimed]:
            return {}
        pairs.append(pair)
    if key == "MARGIN" and any(gross["frame"] != revenue["frame"] or gross["start"] != revenue["start"]
                               or gross["end"] != revenue["end"] for gross, revenue in zip(*pairs)):
        return {}
    if key == "INVENTORY" and any(stock["frame"] != revenue["frame"] + "I" or stock["end"] != revenue["end"]
                                  for stock, revenue in zip(*pairs)):
        return {}
    announced = entry["announced_at"]
    if (not isinstance(announced, str) or _strict_day(announced) is None
            or announced != max(dependency["filed"] for pair in pairs for dependency in pair)):
        return {}
    return {"announced_at": announced}


PHASE_ZH = {"INSUFFICIENT_EVIDENCE": "資料不足", "DISCOVERY": "初現（單一來源）", "EARLY_VALIDATION": "驗證中（雙來源確認）",
            "COMMERCIAL_VALIDATION": "商業驗證（公司開始獲利）", "INSTITUTIONAL_VALIDATION": "法人進場", "CONSENSUS": "共識擁擠",
            "RELIEVING": "緩解中", "BROKEN": "已失效"}
FAMILY_ZH = {"sec_issuer": "SEC 公司申報", "sec_issuer_inventory": "SEC 公司存貨", "bls_ppi": "BLS 生產者物價",
             "taiwan_monthly_revenue": "臺灣上市櫃同業月營收", "sec_xbrl_issuers": "SEC 產業成員申報"}


def _families(values: Sequence[str]) -> str:
    return "、".join(FAMILY_ZH.get(v, v) for v in values) or "無"


def _tag(tag: str | None) -> str:
    return f"（XBRL {tag}）" if tag else ""


def _money(value: float | None) -> str:
    if value is None:
        return "未申報"
    return f"US${value / 1e9:,.2f}B" if abs(value) >= 1e8 else f"US${value / 1e6:,.1f}M"


def _pctx(value: float | None, suffix: str = "%") -> str:
    return "未申報" if value is None else f"{value:+.1f}{suffix}"


def company_signals(ticker: str, metrics: Mapping[str, Any], cik: str, industry: Mapping[str, Any] | None, *,
                    provenance: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Company signals; announced_at only from signal_provenance (without it every company signal stays unannounced)."""
    url = FACTS_URL.format(cik=cik)
    end = metrics.get("quarter_end")
    signals: list[dict[str, Any]] = []
    if metrics.get("rpo_yoy_pct") is not None and metrics.get("rpo_as_of"):
        value = metrics["rpo_yoy_pct"]
        direction = "UP" if value >= 10 else "DOWN" if value <= -10 else "FLAT"
        signals.append({"signal_id": f"{ticker}:RPO", "kind": "BACKLOG", "as_of": metrics["rpo_as_of"], "direction": direction,
                        "value": value, "evidence_family": "sec_issuer", "source_url": url, **_announced(provenance, "RPO")})
    if metrics.get("gross_margin_change_pp") is not None and end:
        value = metrics["gross_margin_change_pp"]
        direction = "UP" if value >= 1 else "DOWN" if value <= -1 else "FLAT"
        signals.append({"signal_id": f"{ticker}:MARGIN", "kind": "COMPANY_MARGIN", "as_of": end, "direction": direction,
                        "value": value, "evidence_family": "sec_issuer", "source_url": url, **_announced(provenance, "MARGIN")})
    if metrics.get("dilution_yoy_pct") is not None and end and metrics["dilution_yoy_pct"] > 0:
        signals.append({"signal_id": f"{ticker}:DILUTION", "kind": "DILUTION", "as_of": end,
                        "value": metrics["dilution_yoy_pct"], "evidence_family": "sec_issuer", "source_url": url,
                        **_announced(provenance, "DILUTION")})
    gap = metrics.get("inventory_minus_revenue_pp")
    if gap is not None and gap >= 10 and metrics.get("inventory_as_of"):
        signals.append({"signal_id": f"{ticker}:INVENTORY", "kind": "INVENTORY_BUILD", "as_of": metrics["inventory_as_of"],
                        "value": gap, "evidence_family": "sec_issuer_inventory", "source_url": url,
                        **_announced(provenance, "INVENTORY")})
    for signal in (industry or {}).get("signals", []):
        if signal["kind"] in ("PRICE", "SUPPLIER_REVENUE"):  # same industry families as the potential ranking
            signals.append(dict(signal, signal_id=f"{ticker}:{signal['signal_id']}"))
    return signals


HORIZONS = ((6, "m6", "6M"), (12, "m12", "1Y"), (24, "m24", "2Y"))
ORDER_PREMISES = ("目前營收水準＝最近一季營收 × 期間季數", "只計已簽約訂單（RPO）依揭露時程認列，未計新接訂單，因此是下限",
                  "股價對應成長假設利潤率、稀釋後股數與本益比不變")


def order_scenario(metrics: Mapping[str, Any], timing: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """If the signed orders are delivered on the disclosed schedule: contracted revenue per horizon versus the
    current run rate. A growth floor exists only where the contracted revenue alone exceeds the run rate. The run
    rate and period check use the order quarter (order_revenue / order_quarter_end) when extract_metrics has one,
    falling back to the latest frame quarter."""
    if not timing:
        return None
    base = {"status": timing.get("status"), "form": timing.get("form"), "filed": timing.get("filed"), "url": timing.get("url")}
    if timing.get("status") != "DISCLOSED":
        return base
    rpo = metrics.get("rpo")
    revenue = metrics.get("order_revenue")
    if revenue is None:
        revenue = metrics.get("revenue")
    rpo_as_of = metrics.get("rpo_as_of")
    quarter_end = metrics.get("order_quarter_end")
    if quarter_end is None:
        quarter_end = metrics.get("quarter_end")
    if not rpo or not revenue or revenue <= 0 or not rpo_as_of or not quarter_end:
        return {**base, "status": "INPUTS_MISSING"}
    if abs((date.fromisoformat(rpo_as_of) - date.fromisoformat(quarter_end)).days) > 45:
        return {**base, "status": "PERIOD_MISMATCH"}
    report_date = timing.get("report_date")
    if report_date and abs((date.fromisoformat(report_date) - date.fromisoformat(rpo_as_of)).days) > 45:
        return {**base, "status": "PERIOD_MISMATCH"}
    # A horizon counts as disclosed only when the schedule says so explicitly; a schedule cached before the "derived" list
    # existed is not qualified evidence (every horizon then reads as derived).
    schedule = timing.get("schedule") or {}
    derived = schedule.get("derived") if isinstance(schedule.get("derived"), list) else None
    quarter = metrics.get("order_quarter") if isinstance(metrics.get("order_quarter"), Mapping) else {}
    horizons: dict[str, Any] = {}
    for months, key, _ in HORIZONS:
        share = (timing.get("schedule") or {}).get(key)
        if share is None:
            horizons[key] = None
            continue
        contracted, run_rate = rpo * share / 100, revenue * months / 3
        coverage = round(contracted / run_rate * 100, 1)
        horizons[key] = {"share_pct": share, "contracted": round(contracted), "run_rate": round(run_rate), "coverage_pct": coverage,
                         "floor_growth_pct": round(coverage - 100, 1) if coverage > 100 else None,
                         # interpolated between two stated horizons (order_timing.schedule), never company-disclosed evidence
                         "derived": derived is None or key in derived}
    passages = timing.get("passages") or []
    return {**base, "rpo": rpo, "rpo_as_of": rpo_as_of, "quarter_revenue": revenue, "quarter_end": quarter_end,
            "quarter_start": quarter.get("start"), "quarter_basis": quarter.get("basis") or "FRAME",
            **({"quarter_derivation": quarter["derivation"]} if quarter.get("derivation") else {}),
            "accession": timing.get("accession"), "passage": str(passages[0])[:300] if passages else None,
            "report_date": timing.get("report_date"), "horizons": horizons,
            "premises": list(ORDER_PREMISES) + list((timing.get("schedule") or {}).get("premises") or [])}


def _coverage(value: float) -> str:
    return f"{value:.1f}%" if value < 10 else f"{value:.0f}%"  # 0.3% must not read as 0%


def order_text(orders: Mapping[str, Any] | None) -> str:
    if not orders:
        return "未取得最新 10-Q／10-K，無訂單實現情境"
    status = orders.get("status")
    if status == "NO_PERIODIC_FILING":
        return "沒有 10-Q／10-K 定期報告，無訂單實現情境"
    if status == "NOT_DISCLOSED":
        return f"最新 {orders.get('form')}（{orders.get('filed')}）未揭露 RPO 認列時程；不推估訂單實現情境"
    if status == "INPUTS_MISSING":
        return f"{orders.get('form')}（{orders.get('filed')}）有認列時程，但 XBRL 缺少 RPO 或同季營收；不推估"
    if status == "PERIOD_MISMATCH":
        return f"{orders.get('form')}（{orders.get('filed')}）的認列時程與 XBRL RPO／營收期間不一致；不混用"
    parts, outcomes = [], []
    for _, key, label in HORIZONS:
        row = orders["horizons"].get(key)
        if row is None:
            outcomes.append(f"{label} 未揭露")
            continue
        parts.append(f"{label} 認列 {row['share_pct']:.1f}% → {_money(row['contracted'])}（目前水準的 {_coverage(row['coverage_pct'])}）")
        outcomes.append(f"{label} 營收與股價成長下限 {row['floor_growth_pct']:+.1f}%" if row["floor_growth_pct"] is not None
                        else f"{label} 已簽約僅支撐 {_coverage(row['coverage_pct'])}，其餘需新訂單")
    interpolation = [p for p in orders["premises"][len(ORDER_PREMISES):]]
    return (f"依 {orders['form']}（{orders['filed']}）揭露的認列時程，RPO {_money(orders['rpo'])}（{orders['rpo_as_of']}）："
            + "；".join(parts) + f"。目前營收水準＝最近一季 {_money(orders['quarter_revenue'])} × 期間季數。若訂單如期實現，"
            + "且利潤率、稀釋後股數與本益比不變：" + "；".join(outcomes) + "。未計新接訂單，屬下限"
            + (f"（{'；'.join(interpolation)}）" if interpolation else ""))


def compact_orders(orders: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Coverage and growth floor per horizon for the potential ranking card; None when not computable."""
    if not orders or orders.get("status") != "DISCLOSED":
        return None
    pick = lambda field: {key: (row or {}).get(field) for key, row in orders["horizons"].items()}
    return {"as_of": orders["rpo_as_of"], "form": orders["form"], "filed": orders["filed"],
            "coverage_pct": pick("coverage_pct"), "floor_growth_pct": pick("floor_growth_pct")}


def load_order_scenarios(path: Path = OUTPUT_PATH, *, tickers: Sequence[str], max_age_days: int = 7,
                         today: date | None = None) -> dict[str, dict[str, Any]]:
    """The full order scenario per ticker (scripts/order_forecast.py input: RPO, schedule shares, revenue quarter,
    filing); the same freshness rule as load_reports."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if (today or date.today()) - date.fromisoformat(document["as_of"]) > timedelta(days=max_age_days):
            return {}
    except (OSError, ValueError, KeyError):
        return {}
    reports = document.get("reports") or {}
    return {ticker: dict(reports[ticker]["orders"]) for ticker in tickers
            if isinstance(reports.get(ticker), dict) and isinstance(reports[ticker].get("orders"), dict)}


def industry_for(sic: str | None, rotation: Mapping[str, Any] | None, config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not sic or not rotation or not config:
        return None
    ids = [row["industry_id"] for row in config.get("industries", []) if sic in row.get("sic", [])]
    for row in rotation.get("industries", []):
        if row["industry_id"] in ids:
            return row
    return None


FRESH_BUSINESS_SOURCE = "FRESH_FETCH_THIS_RUN"  # same literal as company_business_profile.FRESH_SOURCE_FACTS
MAX_SECTION_UNITS = 700  # the Worker's SHORT(section.text, 700) counts UTF-16 code units
BUSINESS_GAP_TEXT = "最新年報業務英文擷取不可用；未驗證的中文翻譯不納入報告"


def business_section_text(business: Mapping[str, Any] | None) -> str:
    """Public 公司業務 text: the FRESH primary English excerpt (up to 600 characters on the Overview path) with its SEC form and
    filing date, or an explicit gap text. An unverified Chinese candidate is never public text. The WHOLE section must fit the
    Worker's 700 UTF-16 units (astral characters count 2): invalid metadata or an oversized section is a gap, never a truncation."""
    if not business or business.get("source_facts") != FRESH_BUSINESS_SOURCE:
        return BUSINESS_GAP_TEXT
    sentence, form, filed = business.get("sentence_en"), business.get("form"), business.get("filed")
    if (not isinstance(sentence, str) or not isinstance(form, str) or not isinstance(filed, str)
            or form not in ("10-K", "20-F") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", filed)
            or len(sentence) < 30 or "\r" in sentence or "\n" in sentence):
        return BUSINESS_GAP_TEXT
    text = f"SEC EDGAR {form} {filed} 年報業務段落英文擷取（自動選取、非逐字、未翻譯）：{sentence}"
    try:
        units = len(text.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return BUSINESS_GAP_TEXT
    return text if units <= MAX_SECTION_UNITS else BUSINESS_GAP_TEXT


IFRS_GAP_ZH = {"IFRS_INPUT_TOO_LARGE": "年度營收資料列數超過處理上限", "IFRS_NO_ELIGIBLE_ANNUAL": "沒有通過期間、申報形式與編號檢查的 20-F 年度營收列",
               "IFRS_AMBIGUOUS_PERIOD": "最新年度期間不唯一", "IFRS_AMBIGUOUS_UNIT": "最新年度營收同時有多種幣別單位",
               "IFRS_AMBIGUOUS_ACCESSION": "最新年度營收的申報編號不唯一", "IFRS_CONFLICTING_DUPLICATE": "同一期間、申報與幣別有互相衝突的重複營收值",
               "IFRS_INVALID_VALUE": "最新年度營收為負值"}
IFRS_LIMIT_TEXT = "本年度路徑未擷取或計算單季營收、毛利率與營業利益率；年度數字不可當作單季資料"  # a limit of this implementation, not a filing claim
IFRS_GAP_TEXT = "年度／IFRS 營收不可用；" + IFRS_LIMIT_TEXT


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _unit_money(value: float, unit: str) -> str:
    """An amount in the issuer's own reported unit: the unit is on every amount, never a dollar sign, never converted."""
    return f"{unit} {value / 1e9:,.2f}B" if abs(value) >= 1e8 else f"{unit} {value / 1e6:,.1f}M"


def annual_section_text(annual: Mapping[str, Any]) -> str:
    """營運動能 for an annual-only IFRS issuer: labelled annual / IFRS / reporting unit / period, with the single-quarter figures stated
    as not extracted by this path. The WHOLE text must fit the Worker's 700 UTF-16 units: invalid fields or an oversized text is a short
    gap, never a truncation. A non-finite numeric field is refused rather than shown as nan or inf (hardening only)."""
    status = annual.get("status")
    if status != "OK":
        reason = IFRS_GAP_ZH.get(status) if isinstance(status, str) else None
        text = f"年度／IFRS 營收不可用（{reason}）；" + IFRS_LIMIT_TEXT if reason else IFRS_GAP_TEXT
    else:
        try:
            unit, revenue, growth = annual["unit"], annual["revenue"], annual.get("revenue_yoy_pct")
            gross, margin = annual.get("gross_profit"), annual.get("gross_margin_pct")
            if not re.fullmatch(r"[A-Z]{3}", unit) or not _finite_number(revenue):
                return IFRS_GAP_TEXT
            if any(value is not None and not _finite_number(value) for value in (growth, gross, margin)):
                return IFRS_GAP_TEXT
            text = (f"年度／IFRS（SEC {annual['form']} {annual['filed']}，申報編號 {annual['accession']}；"
                    f"期間 {annual['period_start']} 至 {annual['period_end']}；幣別 {unit}，為申報單位、未換算匯率）：營收 {_unit_money(revenue, unit)}")
            text += (f"，年增 {_pctx(growth)}（對比同一申報的前一年度 {annual['revenue_prior_period_end']} 止）" if growth is not None
                     else "，年增 無法計算（同一申報缺少可比的前一年度或其值不明確）")
            if gross is None:
                text += "；毛利與毛利率 未申報或不明確"
            else:
                text += f"；毛利 {_unit_money(gross, unit)}（ifrs-full GrossProfit）"
                text += f"，毛利率 {margin:.1f}%" if margin is not None else "，毛利率 無法計算"
            text += "。" + IFRS_LIMIT_TEXT
        except (KeyError, TypeError, ValueError):
            return IFRS_GAP_TEXT
    try:
        units = len(text.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return IFRS_GAP_TEXT
    return text if units <= MAX_SECTION_UNITS and "\r" not in text and "\n" not in text else IFRS_GAP_TEXT


def momentum_section_text(metrics: Mapping[str, Any], frame: str) -> str:
    """營運動能: the single-quarter text (us-gaap, unchanged) or, only for an issuer without any us-gaap USD revenue row that has an
    IFRS result, the labelled annual IFRS text."""
    annual = metrics.get("annual_context")
    if isinstance(annual, Mapping):
        return annual_section_text(annual)
    return (f"{frame} 營收 {_money(metrics['revenue'])}，年增 {_pctx(metrics['revenue_yoy_pct'])}；"
            f"毛利率 {_pctx(metrics['gross_margin_pct'], '%').lstrip('+')}（年變化 {_pctx(metrics['gross_margin_change_pp'], ' 個百分點')}）；"
            f"營業利益率 {_pctx(metrics['operating_margin_pct'], '%').lstrip('+')}（年變化 {_pctx(metrics['operating_margin_change_pp'], ' 個百分點')}）")


def ifrs_annual_reference(metrics: Mapping[str, Any], cik: str) -> dict[str, str] | None:
    """A SEPARATE citation of the annual IFRS Revenue / GrossProfit context: the same SEC company-facts URL, so the same SEC lineage and
    not an independent source. The generic company-facts citation keeps its own period. A field above the limits (source 80 here, period
    40) is omitted, never shortened or relabelled."""
    annual = metrics.get("annual_context")
    if not isinstance(annual, Mapping) or annual.get("status") != "OK":
        return None
    start, end = annual.get("period_start"), annual.get("period_end")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    reference = {"source": "SEC XBRL company facts (ifrs-full annual Revenue/GrossProfit)", "url": FACTS_URL.format(cik=cik),
                 "period": f"ifrs-full 年度 {start}/{end}"}
    return reference if len(reference["source"]) <= 80 and len(reference["period"]) <= 40 else None


def phase_withheld_notice(phase: Any) -> str:
    """Public bounded notice; validate the whole list before exact-id deduplication."""
    withheld = phase.get("withheld_signal_ids") if isinstance(phase, Mapping) else None
    if not isinstance(withheld, list) or any(not isinstance(item, str) or not item.strip() for item in withheld):
        return "；知悉時間覆蓋未確認（不假設零；不代表論點失效）"
    ids = set(withheld)
    if not ids:
        return ""
    shown = str(len(ids)) if len(ids) <= 9999 else "9999+"
    return f"；時間證據提醒：至少 {shown} 筆訊號未確認截至評估日已知，未計入階段（非完整覆蓋；缺口本身不代表論點失效）"


_OPERATING_PHASE_ZH = {**PHASE_ZH, "BROKEN": "營運證偽訊號成立"}
_LEGACY_GATE_ZH = {**PHASE_ZH, "BROKEN": "受阻（可能含融資條件，不等同營運論點失效）"}
# Validated company-scope (financing_status, known_financing_entry_blocked) pairs; anything else reads as unknown.
_FINANCING_ZH = {
    ("ENTRY_BLOCK_OBSERVED", True): "觀察到達准入阻擋門檻的融資條件",
    ("OVERHANG_OBSERVED", False): "觀察到稀釋疑慮；已提供觀察僅未達准入阻擋門檻（非進場許可、非安全證明）",
    ("OVERHANG_OBSERVED", None): "觀察到稀釋疑慮；無法確定是否達准入阻擋門檻",
    ("BELOW_OVERHANG_OBSERVED", False): "僅已提供觀察未達准入阻擋門檻（非進場許可、非安全證明、非完整融資覆蓋）",
}
_FINANCING_UNKNOWN_ZH = "未知或不完整（無法確定是否受阻，不推定無融資風險）"


def _phase_presentation(phase: Any) -> str:
    """資料階段 labels: the legacy admission gate, the operating phase and the financing observation, shown apart.

    Fixed labels only (no raw enums, reasons, signal IDs or provenance). Missing, malformed or inconsistent fields read
    as unknown; an operating conclusion is never derived from the legacy gate. Never raises on malformed input.
    """
    fields = phase if isinstance(phase, Mapping) else {}
    legacy, operating = fields.get("phase"), fields.get("operating_phase")
    reasons, scope = fields.get("operating_reasons"), fields.get("scope")
    status, blocked = fields.get("financing_status"), fields.get("known_financing_entry_blocked")
    legacy_text = _LEGACY_GATE_ZH.get(legacy, "未知") if type(legacy) is str else "未知"
    if type(operating) is str and operating in _OPERATING_PHASE_ZH:
        operating_text = _OPERATING_PHASE_ZH[operating]
    elif (operating is None and "operating_phase" in fields and type(reasons) is list and len(reasons) == 1
          and type(reasons[0]) is str and reasons[0] == "OPERATING_POLICY_THRESHOLD_UNAVAILABLE"):
        operating_text = "未知（政策門檻不可用，未推論）"
    else:
        operating_text = "未知"
    financing_text = _FINANCING_UNKNOWN_ZH
    if (type(scope) is str and scope == "company" and type(status) is str and "known_financing_entry_blocked" in fields
            and (blocked is None or blocked is True or blocked is False)):
        financing_text = _FINANCING_ZH.get((status, blocked), _FINANCING_UNKNOWN_ZH)
    return f"舊版准入狀態：{legacy_text}；營運階段：{operating_text}；融資觀察：{financing_text}"


def build_report(ticker: str, cik: str, *, facts: Mapping[str, Any], submissions: Mapping[str, Any],
                 business: Mapping[str, Any] | None, rotation: Mapping[str, Any] | None,
                 rotation_config: Mapping[str, Any] | None, today: date, timing: Mapping[str, Any] | None = None) -> dict[str, Any]:
    metrics = extract_metrics(facts, today)
    orders = order_scenario(metrics, timing)
    sic = str(submissions.get("sic") or "") or None
    industry = industry_for(sic, rotation, rotation_config)
    provenance = signal_provenance(facts, metrics)
    signals = company_signals(ticker, metrics, cik, industry, provenance=provenance)
    phase = thesis_phase.assess_phase(signals, today, scope="company")
    frame = metrics.get("quarter_frame") or "未知季度"
    name = facts.get("entityName") or submissions.get("name") or ticker
    sections = [
        ("公司業務", business_section_text(business)),
        ("營運動能", momentum_section_text(metrics, frame)),
        ("訂單能見度", (f"剩餘履約義務（RPO）{_money(metrics['rpo'])}（{metrics['rpo_as_of']}），年增 {_pctx(metrics['rpo_yoy_pct'])}"
                    if metrics.get("rpo") is not None else "未申報剩餘履約義務（RPO），訂單能見度無法量化")),
        ("訂單實現情境", order_text(orders)),
        ("產能與資本支出", (f"最近會計年度資本支出 {_money(metrics['capex_fy'])}（年度截至 {metrics['capex_fy_end']}），占營收 {_pctx(metrics['capex_share_of_revenue_pct']).lstrip('+')}"
                       if metrics.get("capex_fy") is not None else "未申報年度資本支出")),
        ("資產負債與稀釋", (f"現金 {_money(metrics['cash'])}{_tag(metrics.get('cash_tag'))}、長期負債 {_money(metrics['long_term_debt'])}{_tag(metrics.get('long_term_debt_tag'))}；"
                       f"稀釋後加權股數年變化 {_pctx(metrics['dilution_yoy_pct'])}；"
                       + (f"存貨年增 {_pctx(metrics['inventory_yoy_pct'])}，較營收成長{'高' if metrics['inventory_minus_revenue_pp'] > 0 else '低'} {abs(metrics['inventory_minus_revenue_pp']):.1f} 個百分點"
                          if metrics.get("inventory_minus_revenue_pp") is not None else "存貨與營收可比資料不足"))),
        ("所屬產業訊號", (f"{industry['name_zh']}：資料階段 {PHASE_ZH.get(industry['phase']['phase'], industry['phase']['phase'])}，BLS PPI 年增 {_pctx(industry['price']['yoy_pct'])}，"
                       f"成員 RPO 年增 {_pctx(industry['backlog']['yoy_pct'])}（{industry['quarter']}）"
                       + (f"，臺灣上市櫃同業 {industry['taiwan']['count']} 家 {industry['taiwan']['month']} 營收年增 {_pctx(industry['taiwan']['yoy_pct'])}"
                          if (industry.get("taiwan") or {}).get("yoy_pct") is not None else "")
                       + (phase_withheld_notice(industry.get("phase")) if industry else "")
                       if industry else f"SIC {sic or '未知'} 不在產業輪替範圍或輪替資料不可用")),
        ("資料階段", (f"{_phase_presentation(phase)}"
                   + ("；舊版稀釋疑慮旗標（與融資觀察分開計算）" if phase["dilution_overhang"] else "")
                   + phase_withheld_notice(phase)
                   + f"；下次檢查 {phase['next_review_at'] or '下一份財報'}"
                   f"；訊號家族（吃緊來源：{_families(phase['constraint_families'])}；"
                   f"公司捕捉：{_families(phase['capture_families'])}；緩解：{_families(phase['relief_families'])}）")),
        ("證偽條件", "營運警示條件：RPO 年增降至 -10% 以下；毛利率年減 1 個百分點以上；存貨成長超過營收 10 個百分點；所屬產業 PPI 年增降至 -3% 以下。"
                 "融資准入阻擋條件（舊版准入狀態）：稀釋後股數年增 20% 以上。以上為觀察條件，不是交易指令"),
    ]
    references = [{"source": "SEC XBRL company facts", "url": FACTS_URL.format(cik=cik), "period": frame},
                  {"source": "SEC EDGAR submissions", "url": SUBMISSIONS_URL.format(cik=cik)}]
    annual_reference = ifrs_annual_reference(metrics, cik)
    if annual_reference:
        references.append(annual_reference)
    if orders and orders.get("url"):
        references.append({"source": f"SEC {orders.get('form')} RPO recognition timing", "url": orders["url"], "period": orders.get("filed")})
    if business and business.get("source_facts") == FRESH_BUSINESS_SOURCE and business.get("url"):
        references.append({"source": f"SEC {business.get('form')} business section", "url": business["url"], "period": business.get("filed")})
    if industry:
        references.extend({"source": f"BLS PPI {row['series']}", "url": f"https://data.bls.gov/timeseries/{row['series']}", "period": row["month"]}
                          for row in industry["price"]["series"])
    return {"schema_version": 1, "ticker": ticker, "cik": cik, "name": name, "sic": sic,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "as_of": today.isoformat(),
            "metrics": metrics, "signals": signals, "signal_provenance": provenance, "phase": phase, "orders": orders,
            "sections": [{"title": title, "text": text} for title, text in sections], "source_references": references,
            "boundary": "官方資料的計算與整理；不是投資建議、價格預測或機率"}


def build_reports(tickers: Mapping[str, str], fetch: Fetch, *, today: date, business_loader: Callable[[str], Mapping | None] | None = None,
                  rotation: Mapping[str, Any] | None = None, rotation_config: Mapping[str, Any] | None = None,
                  timing_loader: Callable[[str, Mapping[str, Any]], Mapping | None] | None = None) -> dict[str, Any]:
    reports, failures = {}, {}
    for ticker, cik in tickers.items():
        try:
            facts = json.loads(fetch(FACTS_URL.format(cik=cik)))
            submissions = json.loads(fetch(SUBMISSIONS_URL.format(cik=cik)))
            business = business_loader(cik) if business_loader else None
            timing = timing_loader(cik, submissions) if timing_loader else None
            reports[ticker] = build_report(ticker, cik, facts=facts, submissions=submissions, business=business,
                                           rotation=rotation, rotation_config=rotation_config, today=today, timing=timing)
        except Exception as error:
            failures[ticker] = type(error).__name__
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "as_of": today.isoformat(), "reports": reports, "failures": failures, "publication_eligible": False}


TICKERS_URL = sec_ticker_cache.ORIGIN
TICKERS_CACHE = ROOT / "data" / "cache" / "v21" / "company_tickers_exchange.json"


def ticker_ciks(fetch: Fetch, *, today: date, cache: Path = TICKERS_CACHE, max_age_days: int = 7) -> dict[str, str]:
    """SEC ticker -> CIK map; matching sidecar age is acquisition-based, else UNVERIFIED."""
    raw = None
    try:
        with cache.open("rb") as handle:
            cached = handle.read(sec_ticker_cache.MAX_BYTES + 1)
        body = cached
        acquired = sec_ticker_cache.acquired_at(body, cache)
        if acquired is not None:
            age = datetime.now(timezone.utc) - acquired
            usable = timedelta(0) <= age <= timedelta(days=max_age_days)
        else:
            # Compatibility only: this time is NOT an authenticated acquisition.
            modified = date.fromtimestamp(cache.stat().st_mtime)
            usable = today - timedelta(days=max_age_days) <= modified <= today
        if usable:
            raw = body
    except (OSError, ValueError, UnicodeError):
        pass
    if raw is None:
        raw = fetch(TICKERS_URL)
        acquisition = sec_ticker_cache.acquisition_bytes(raw, datetime.now(timezone.utc))
        cache.parent.mkdir(parents=True, exist_ok=True)
        sidecar = sec_ticker_cache.sidecar_path(cache)
        sidecar.unlink(missing_ok=True)  # interrupted replacement must not retain an old attestation
        cache.write_bytes(raw)  # shared raw SEC format: body first, acquisition record second
        sidecar.write_bytes(acquisition)
    exchange = json.loads(raw)
    fields = exchange["fields"]
    return {str(row[fields.index("ticker")]).upper(): str(row[fields.index("cik")]).zfill(10) for row in exchange["data"]}


def sealed_tickers(snapshots_dir: Path | None = None) -> list[str]:
    """Tickers ranked in the newest sealed run (the companies LINE can open a deep report for); the snapshot root
    is the publisher's II_SNAPSHOT_ROOT setting."""
    if snapshots_dir is None:
        snapshots_dir = ROOT / (os.environ.get("II_SNAPSHOT_ROOT", "").strip() or "state/v213-snapshots")
    runs = sorted((p for p in snapshots_dir.glob("*/summary.json")), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in runs:
        try:
            return [str(row[1]) for row in json.loads(path.read_text(encoding="utf-8")).get("ranked", [])]
        except (OSError, ValueError, IndexError):
            continue
    return []


def v3_tickers(path: Path = ROOT / "data" / "cache" / "bottleneck_top20_v3.json") -> list[str]:
    """US-listed (SEC filer) symbols of the bottleneck Top20 v3, so its cards open a company data report."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(row["symbol"]) for row in document.get("top", []) if "." not in str(row.get("symbol", ""))]


def load_reports(path: Path = OUTPUT_PATH, *, tickers: Sequence[str], max_age_days: int = 7,
                 today: date | None = None) -> dict[str, dict[str, Any]]:
    """Compact reports for sealing: only fields the Worker renders; stale or missing files give none."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if (today or date.today()) - date.fromisoformat(document["as_of"]) > timedelta(days=max_age_days):
            return {}
    except (OSError, ValueError, KeyError):
        return {}
    compact = {}
    for ticker in tickers:
        report = (document.get("reports") or {}).get(ticker)
        if not report:
            continue
        compact[ticker] = {"ticker": ticker, "name": report["name"], "as_of": report["as_of"], "boundary": report["boundary"],
                           "phase": {"phase": report["phase"]["phase"], "next_review_at": report["phase"].get("next_review_at")},
                           "sections": [{"title": s["title"], "text": s["text"].replace("\n", " ")[:700]} for s in report["sections"]],
                           "source_references": report["source_references"][:20],
                           "kpis": kpis(report.get("metrics") or {}, report.get("orders")),
                           "orders": compact_orders(report.get("orders"))}
    return compact


# Tiles on the LINE report: (label <= 12 chars, metric, signed change?, period field). Values come from the same metrics
# the sections are written from; a missing fact stays null and renders as 未申報.
KPI_FIELDS = (("營收年增", "revenue_yoy_pct", True, "quarter_frame"), ("毛利率", "gross_margin_pct", False, "quarter_frame"),
              ("營業利益率", "operating_margin_pct", False, "quarter_frame"), ("RPO 年增", "rpo_yoy_pct", True, "rpo_as_of"),
              ("稀釋後股數年增", "dilution_yoy_pct", True, "quarter_frame"), ("資本支出/營收", "capex_share_of_revenue_pct", False, "capex_fy_end"))


def kpis(metrics: Mapping[str, Any], orders: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    out = []
    for label, key, signed, period_key in KPI_FIELDS:
        value = metrics.get(key)
        row: dict[str, Any] = {"label": label, "value": round(float(value), 2) if isinstance(value, (int, float)) else None,
                               "unit": "%", "signed": signed}
        if metrics.get(period_key):
            row["period"] = str(metrics[period_key])[:20]
        out.append(row)
    one_year = ((orders or {}).get("horizons") or {}).get("m12") if (orders or {}).get("status") == "DISCLOSED" else None
    if one_year:
        out.append({"label": "1Y 已簽約覆蓋", "value": one_year["coverage_pct"], "unit": "%", "signed": False,
                    "period": str(orders["rpo_as_of"])[:20]})
    return out


def cached_business(cik: str) -> Mapping[str, Any] | None:
    """Audit-only filing identifiers of the cached profile (bounded strict read, no network), marked CACHE_ONLY_NOT_FRESH with no
    sentence and no phrase: build_report never presents it, so a stale or tampered cache cannot become a current SEC fact."""
    import company_business_profile as profile
    return profile.cache_entry(cik)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="read SEC data now (fair access)")
    parser.add_argument("--tickers", help="comma-separated tickers with SEC filings (default: newest sealed ranking)")
    parser.add_argument("--if-older-than-hours", type=float, help="skip when the current file is newer than this")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    if not args.refresh:
        parser.error("--refresh is required; no implicit network requests")
    if args.if_older_than_hours is not None and args.output.exists():
        age_hours = (datetime.now().timestamp() - args.output.stat().st_mtime) / 3600
        if age_hours < args.if_older_than_hours:
            print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age_hours, 1)}))
            return 0
    import company_business_profile as profile
    import industry_rotation
    import order_timing
    from sec_contact_headers import sec_identity_headers
    if args.tickers:
        wanted = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:  # the sealed ranking plus the data-driven potential ranking, in that order, without duplicates
        rotation_doc = industry_rotation.load_rotation() or {}
        wanted = list(dict.fromkeys(sealed_tickers() + v3_tickers() + [r["ticker"] for r in rotation_doc.get("company_ranking", [])]))
    fetch = profile.sec_fetcher(sec_identity_headers())
    ciks = ticker_ciks(fetch, today=date.today())
    translate = None  # BIZ1: a translation would only create a research candidate; no model is activated for final report text

    def timing(cik: str, submissions: Mapping[str, Any]) -> Mapping[str, Any] | None:
        # Per-accession cache: the 10-Q/10-K text is read again only when a new periodic filing appears.
        try:
            return order_timing.resolve_timing(cik, submissions, fetch)
        except Exception:
            return None

    def business(cik: str) -> Mapping[str, Any] | None:
        # Every call re-reads the filing index and the annual document (an extra existing request on a cache hit); the cache only
        # offers an UNVERIFIED phrase candidate that is never public text. A failed fetch shows the explicit gap text (no stale fallback).
        try:
            return profile.resolve_business_profile(cik, fetch, translate)
        except Exception:
            return None

    document = build_reports({t: ciks[t] for t in wanted if t in ciks}, fetch, today=date.today(), business_loader=business,
                             rotation=industry_rotation.load_rotation(), rotation_config=industry_rotation.load_config(),
                             timing_loader=timing)
    document["not_sec_listed"] = [t for t in wanted if t not in ciks]
    industry_rotation.atomic_write(args.output, document)
    print(json.dumps({"status": "OK", "reports": len(document["reports"]), "failures": document["failures"],
                      "not_sec_listed": document["not_sec_listed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
