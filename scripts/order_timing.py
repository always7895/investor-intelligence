#!/usr/bin/env python3
"""Remaining-performance-obligation timing from the latest 10-Q / 10-K text (operator rule 2026-09-25).

Top20 upside needs "if the orders are realised on schedule": how much of the disclosed RPO
becomes revenue within 6, 12 and 24 months. Issuers state cumulative percentages in prose,
for example:

- "approximately 77% ... in the next twelve months, approximately 14% in the following twelve months"
- "Equipment-related RPO of $87,821 million of which 36%, 65%, and 97% is expected to be recognized
  within 1, 2, and 5 years, respectively"
- "$103.7 billion of unsatisfied RPO, of which 41% was expected to be recognized over the initial 24 months"
- "$315 million, of which $201 million is expected to be recognized in the next 12 months"
- "Approximately one-third of the remaining performance obligations ... over the next twelve months" (Micron)
- "of which 36% is expected to be recognized as revenue during the 24 months ending June 30, 2028" (Nebius)

Only explicit statements are used, with passages, filing URL and accession. Horizons that the
filing does not state are derived only by linear interpolation between two disclosed horizons (a
stated premise); nothing is extrapolated beyond the last disclosed horizon, and nothing is drawn
from zero before the first one (operator 2026-09-26: a line from zero made every horizon up to the
first disclosure show the same coverage, e.g. CRWV 6M = 1Y = 2Y).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

Fetch = Callable[[str], bytes]
ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / "data" / "cache" / "v21" / "order_timing"
EXTRACTOR_VERSION = 4  # 3: no interpolation from zero before the first disclosed horizon; 4: word fractions, "during"
QUARTERLY_FORMS = ("10-Q", "10-K")
_KEY = re.compile(r"remaining performance obligations?|\bRPO\b", re.I)
_NUM = r"(\d{1,3}(?:\.\d+)?)"
_PCT = r"(?:approximately|about|roughly|~)?\s*" + _NUM + r"\s*%"
_MONEY = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(billion|million)?"
# A share written as a fraction counts only as "<fraction> of ...", never "the second half of 2027".
_FRACTIONS = {"one-third": 33.33, "one third": 33.33, "two-thirds": 66.67, "two thirds": 66.67, "one-half": 50.0,
              "one half": 50.0, "one-quarter": 25.0, "three-quarters": 75.0}
_SHARE = (r"(?:approximately|about|roughly|~)?\s*(?:" + _NUM + r"\s*%|(" + "|".join(_FRACTIONS) + r")(?=\s+of\b))")
_UNIT_MONTHS = {"month": 1, "months": 1, "year": 12, "years": 12}


def _months(value: str, unit: str) -> int:
    words = {"one": 1, "two": 2, "three": 3, "five": 5, "ten": 10, "twelve": 12, "twenty-four": 24}
    number = words.get(value.lower()) if not value.replace(".", "").isdigit() else float(value)
    return int(round(float(number) * _UNIT_MONTHS[unit.lower()]))


def _amount(number: str, scale: str | None) -> float:
    value = float(number.replace(",", ""))
    return value * (1e9 if (scale or "").lower() == "billion" else 1e6 if (scale or "").lower() == "million" else 1.0)


_PAIR = re.compile(_PCT + r"[^%]{0,220}?next\s+(?:twelve|12)\s+months[^%]{0,60}?" + _PCT
                   + r"[^%]{0,80}?(?:following|subsequent|next)\s+(?:twelve|12)\s+months", re.I)
_LIST = re.compile(r"of which\s+((?:" + _NUM + r"\s*%\s*,?\s*(?:and\s+)?){2,6})[^%]{0,80}?within\s+((?:[\d.]+\s*,?\s*(?:and\s+)?){2,6})\s*(years?|months?)", re.I)
_OVER = re.compile(_SHARE + r"[^%$]{0,140}?(?:over|within|in|during)\s+(?:the\s+)?(?:next|initial|first|coming)?\s*(\w+(?:-\w+)?)\s+(months?|years?)", re.I)
_OF_WHICH = re.compile(_MONEY + r"[^$%]{0,80}?of which\s+" + _MONEY + r"[^.$%]{0,120}?(?:next|coming|within)\s+(?:the\s+next\s+)?(twelve|12|one|1)\s+(months?|years?)", re.I)
_SEGMENT = re.compile(r"RPO\s+of\s+" + _MONEY + r"\s+of which", re.I)


def _cumulative(window: str) -> tuple[dict[int, float], list[str], list[dict]]:
    """Horizon (months) -> cumulative percent, weighted across amount-bearing segments when present."""
    segments = []
    for match in _LIST.finditer(window):
        pcts = [float(x) for x in re.findall(_NUM + r"\s*%", match.group(1))]
        spans = [s for s in re.findall(r"[\d.]+", match.group(3))]
        if len(pcts) != len(spans):
            continue
        horizons = {_months(s, match.group(4)): p for s, p in zip(spans, pcts)}
        head = _SEGMENT.search(window[max(0, match.start() - 120): match.start() + 12])
        amount = _amount(head.group(1), head.group(2)) if head else None
        segments.append({"horizons": horizons, "amount": amount, "passage": match.group(0).strip()[:300]})
    if segments and all(s["amount"] for s in segments) and len(segments) > 1:
        total = sum(s["amount"] for s in segments)
        common = sorted(set.intersection(*(set(s["horizons"]) for s in segments)))
        combined = {m: round(sum(s["horizons"][m] * s["amount"] for s in segments) / total, 2) for m in common}
        return combined, [s["passage"] for s in segments], segments
    if segments:
        return segments[0]["horizons"], [segments[0]["passage"]], segments
    pair = _PAIR.search(window)
    if pair:
        first, second = float(pair.group(1)), float(pair.group(2))
        if 0 < first <= 100 and 0 <= second <= 100 - first:
            return {12: first, 24: round(first + second, 2)}, [pair.group(0).strip()[:300]], []
    of_which = _OF_WHICH.search(window)
    if of_which:
        total, near = _amount(of_which.group(1), of_which.group(2)), _amount(of_which.group(3), of_which.group(4))
        if 0 < near <= total:
            return {12: round(near / total * 100, 2)}, [of_which.group(0).strip()[:300]], []
    over = _OVER.search(window)
    if over:
        try:
            months = _months(over.group(3), over.group(4))
        except (KeyError, TypeError, ValueError):
            months = 0
        value = float(over.group(1)) if over.group(1) else _FRACTIONS[over.group(2).lower()]
        if 0 < value <= 100 and 1 <= months <= 120:
            return {months: value}, [over.group(0).strip()[:300]], []
    return {}, [], []


def extract_timing(text: str) -> dict[str, Any] | None:
    """First explicit recognition schedule near an RPO mention, as cumulative percent by horizon."""
    for match in _KEY.finditer(text):
        window = text[max(0, match.start() - 200): match.end() + 1200]
        horizons, passages, segments = _cumulative(window)
        if horizons:
            return {"horizons": horizons, "passages": passages, "segments": segments}
    return None


def weighted_schedule(timing: Mapping[str, Any]) -> dict[str, Any]:
    """Per-segment schedules weighted by segment amount when every segment states one; else the combined table."""
    segments = timing.get("segments") or []
    if len(segments) > 1 and all(s.get("amount") for s in segments):
        parts = [(s["amount"], schedule(s["horizons"])) for s in segments]
        total = sum(amount for amount, _ in parts)
        out: dict[str, Any] = {"premises": sorted({p for _, sch in parts for p in sch["premises"]})}
        for key in ("m6", "m12", "m24"):
            values = [(amount, sch[key]) for amount, sch in parts]
            out[key] = None if any(v is None for _, v in values) else round(sum(a * v for a, v in values) / total, 2)
        out["premises"].append("多段 RPO 依各段金額加權")
        return out
    return schedule(timing["horizons"])


def schedule(horizons: Mapping[int, float]) -> dict[str, Any]:
    """6/12/24-month cumulative percent; linear only between two disclosed horizons, never before the first or
    beyond the last."""
    points = sorted((int(m), float(p)) for m, p in horizons.items() if 0 < float(p) <= 100)
    out: dict[str, Any] = {"premises": []}
    for target in (6, 12, 24):
        exact = dict(points).get(target)
        if exact is not None:
            out[f"m{target}"] = exact
            continue
        lower = max([(m, p) for m, p in points if m < target], default=None)
        upper = min([(m, p) for m, p in points if m > target], default=None)
        if lower is None or upper is None:
            out[f"m{target}"] = None
            continue
        value = lower[1] + (upper[1] - lower[1]) * (target - lower[0]) / (upper[0] - lower[0])
        out[f"m{target}"] = round(value, 2)
        out["premises"].append(f"{target} 個月以揭露的 {lower[0]}–{upper[0]} 個月區間線性攤提")
    return out


def latest_periodic_filing(submissions: Mapping[str, Any], cik: str) -> dict[str, str] | None:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    for index, form in enumerate(recent.get("form") or []):
        if form in QUARTERLY_FORMS:
            accession = str(recent["accessionNumber"][index])
            report_dates = recent.get("reportDate") or []
            return {"form": form, "filed": str(recent["filingDate"][index]), "accession": accession,
                    "report_date": str(report_dates[index]) if index < len(report_dates) else "",
                    "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{recent['primaryDocument'][index]}"}
    return None


def resolve_timing(cik: str, submissions: Mapping[str, Any], fetch: Fetch, cache_root: Path | None = CACHE_ROOT) -> dict[str, Any]:
    """Recognition schedule of the newest 10-Q/10-K; the document is read again only when a new filing appears."""
    filing = latest_periodic_filing(submissions, cik)
    if filing is None:
        return {"status": "NO_PERIODIC_FILING"}
    path = cache_root / f"CIK{cik}.json" if cache_root else None
    if path:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("accession") == filing["accession"] and cached.get("extractor_version") == EXTRACTOR_VERSION:
                return cached
        except (OSError, ValueError):
            pass
    import company_business_profile as profile
    timing = extract_timing(profile.business_text(fetch(filing["url"])))
    result: dict[str, Any] = {"status": "NOT_DISCLOSED", **filing, "extractor_version": EXTRACTOR_VERSION}
    if timing is not None:
        result.update(status="DISCLOSED", horizons={str(k): v for k, v in timing["horizons"].items()},
                      passages=timing["passages"], segment_count=len(timing["segments"]), schedule=weighted_schedule(timing))
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
    return result


def filing_timing(cik: str, fetch: Fetch) -> dict[str, Any]:
    """Uncached lookup (probes): submissions, then the newest periodic filing."""
    return resolve_timing(cik, json.loads(fetch(f"https://data.sec.gov/submissions/CIK{cik}.json")), fetch, cache_root=None)
