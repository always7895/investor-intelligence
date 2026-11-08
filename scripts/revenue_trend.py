"""TREND_YOY_V1: the lowest-priority revenue estimate of a Top20 card (lane V33b, operator 2026-11-03).

When no revenue basis applies to an issuer (no reviewed guidance, no consensus, no recognition schedule) the card used to
read 未揭露 / 無法估價. This module derives, from the issuer's own already reported quarters, a trend estimate that is
labelled as an estimate (never 實績, never company guidance) and feeds the existing price scenario arithmetic.

Method (the same arithmetic and constants as the Worker's HISTORY_YOY_V1, cloud/src/v213/revenue-history-model.ts, so the
two never disagree for the same inputs):
- Inputs: the four most recent contiguous reported quarters q1..q4 (oldest first; one positive single-currency series from
  filings or market data) and the sealed fundamentals' year-over-year rates of the anchor quarter (q4) and the quarter
  before it.
- Growth g: the middle value of the available rates (the mean of two), clamped to -50% ... +100% (the clamp is flagged).
  Without a rate, or with |g| > 300% (outside the model), the latest quarter is held flat.
- Forward quarter k = its year-ago reported quarter x (1 + g): 6 months = (q1 + q2)(1 + g), 1 year = (q1 + .. + q4)(1 + g).
- Price scenario: the arithmetic of revenue_guidance.compute_v3_arithmetic: B = q1 + .. + q4,
  change6 = (q3 + q4 + f1 + f2) / B - 1, change12 = (f1 + .. + f4) / B - 1 (P/S and share count unchanged).

The sealed object is an OPTIONAL field of a Top20 entry (`revenue_trend`); the Worker (cloud/src/v213/revenue-trend.ts)
re-validates and recomputes it, and applies it only where no existing basis exists. Nothing here changes a sealed status,
tile, score or rank.
"""
from __future__ import annotations

import calendar
import math
import re
from datetime import date, timedelta
from typing import Any, Mapping

SCHEMA = "revenue-trend-v1"
METHOD = "TREND_YOY_V1"
GROWTH_FLOOR = -0.5
GROWTH_CAP = 1.0
YOY_FAULT = 3.0
MAX_ANCHOR_DAYS = 200
QUARTER_GAP_DAYS = (76, 106)
QUARTERS = 4
CURRENCY = re.compile(r"^[A-Z]{3}$")


def _day(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value and 1990 <= parsed.year <= 2100 else None


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def window_end(anchor: date, months: int) -> date:
    """The last day of a `months` window that starts the day after `anchor`."""
    return _add_months(anchor + timedelta(days=1), months) - timedelta(days=1)


def quarters_of(series: Mapping[Any, Any], latest_end: Any) -> list[dict[str, Any]] | None:
    """The four contiguous quarters ending at `latest_end` (oldest first) from an end-date -> revenue mapping, or None.

    `series` keys are ISO days (str) or date-like objects whose `.isoformat()` gives one; each next quarter end must lie
    76-106 days after the previous one, so a missing quarter never silently stretches the window."""
    values: dict[str, float] = {}
    for key, value in series.items():
        text = key if isinstance(key, str) else getattr(key, "isoformat", lambda: None)()
        text = text[:10] if isinstance(text, str) else None
        amount = _num(value)
        if _day(text) is not None and amount is not None:
            values[text] = amount
    latest = latest_end if isinstance(latest_end, str) else getattr(latest_end, "isoformat", lambda: None)()
    latest = latest[:10] if isinstance(latest, str) else None
    if _day(latest) is None or latest not in values:
        return None
    ends = sorted(end for end in values if end <= latest)[-QUARTERS:]
    if len(ends) != QUARTERS or ends[-1] != latest:
        return None
    for earlier, later in zip(ends, ends[1:]):
        if not QUARTER_GAP_DAYS[0] <= (_day(later) - _day(earlier)).days <= QUARTER_GAP_DAYS[1]:
            return None
    return [{"end": end, "revenue": values[end]} for end in ends]


def _middle(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    return ordered[(n - 1) // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def build(fund: Mapping[str, Any] | None, report_day: date) -> dict[str, Any] | None:
    """The sealed `revenue_trend` object for one entry, or None when the inputs are not all present and valid."""
    if not isinstance(fund, Mapping):
        return None
    raw = fund.get("revenue_quarters")
    currency, anchor_text = fund.get("revenue_unit"), fund.get("quarter_end")
    anchor = _day(anchor_text)
    if not isinstance(raw, list) or len(raw) != QUARTERS or anchor is None or not isinstance(currency, str) or not CURRENCY.match(currency):
        return None
    quarters = []
    for row in raw:
        if not isinstance(row, Mapping) or _day(row.get("end")) is None:
            return None
        revenue = _num(row.get("revenue"))
        if revenue is None or revenue <= 0:
            return None
        quarters.append({"end": row["end"], "revenue": revenue})
    ends = [_day(q["end"]) for q in quarters]
    if ends[-1] != anchor or any(not QUARTER_GAP_DAYS[0] <= (b - a).days <= QUARTER_GAP_DAYS[1] for a, b in zip(ends, ends[1:])):
        return None
    age = (report_day - anchor).days
    if age < 0 or age > MAX_ANCHOR_DAYS:
        return None
    source, source_url = fund.get("source"), fund.get("source_url")
    if not isinstance(source, str) or not source or len(source) > 80 or not isinstance(source_url, str) \
            or not source_url.startswith("https://") or len(source_url) > 400:
        return None
    rates = []
    for label, key in (("latest", "revenue_yoy"), ("previous", "revenue_yoy_prev")):
        rate = _num(fund.get(key))
        if rate is not None:
            rates.append({"label": label, "value": rate})
    growth_raw = growth = capped = tier_b_reason = None
    tier = "B"
    if rates:
        growth_raw = _middle([r["value"] for r in rates])
        if abs(growth_raw) > YOY_FAULT:
            tier_b_reason = "YOY_OUT_OF_RANGE"
        else:
            tier, growth = "A", min(GROWTH_CAP, max(GROWTH_FLOOR, growth_raw))
            capped = "UPPER" if growth_raw > GROWTH_CAP else "LOWER" if growth_raw < GROWTH_FLOOR else None
    else:
        tier_b_reason = "NO_ALIGNED_YOY"
    revenues = [q["revenue"] for q in quarters]
    forward = [revenue * (1 + growth) if tier == "A" else revenues[3] for revenue in revenues]
    baseline = sum(revenues)
    amount6, amount12 = forward[0] + forward[1], sum(forward)
    ttm6 = revenues[2] + revenues[3] + amount6
    if not all(math.isfinite(v) and v > 0 for v in (*forward, baseline, amount6, amount12, ttm6)):
        return None
    start = anchor + timedelta(days=1)
    return {
        "schema": SCHEMA, "method": METHOD, "currency": currency, "anchor": anchor_text, "tier": tier,
        "quarters": quarters, "rates": rates, "growth_raw": growth_raw, "growth": growth, "capped": capped,
        "tier_b_reason": tier_b_reason, "baseline": baseline,
        "m6": {"start": start.isoformat(), "end": window_end(anchor, 6).isoformat(), "amount": amount6, "change": ttm6 / baseline - 1},
        "m12": {"start": start.isoformat(), "end": window_end(anchor, 12).isoformat(), "amount": amount12, "change": amount12 / baseline - 1},
        "source": source, "source_url": source_url,
    }
