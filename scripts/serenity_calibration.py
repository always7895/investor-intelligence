#!/usr/bin/env python3
"""Offline, research-only Serenity thesis calibration; never LINE, phase, scoring or ticker admission.

A price reader is injected; the default uses ONLY on-disk captured Yahoo adjusted-close
bytes and the repo's existing bottleneck_top20_v3._chart_bars parser (no provider calls).
First session on/after post DATE is a descriptive anchor, not an executable entry.
+5/+20/+60 count trading observations, NOT calendar days. Null/unknown is neither hit
nor miss. Validation lag requires separate dated HTTPS non-social evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

import bottleneck_top20_v3 as market_reader
import serenity_signals as serenity

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIGNALS = ROOT / "data/cache/serenity_signals_latest.json"
DEFAULT_CACHE = ROOT / "data/cache"
HORIZONS = (5, 20, 60)


def _day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    if len(value) == 10:
        try:
            day = date.fromisoformat(value)
            return day if day.isoformat() == value else None
        except ValueError:
            return None
    moment = serenity.parse_time(value)
    return moment.date() if moment is not None else None


def cached_price_reader(symbol: str, *, cache_root: Path | None = None, captured: Any = None) -> list[tuple[date, float]]:
    """Existing CapturedPublicationInputs yahoo/chart operand or mirrored on-disk cache. No network."""
    if not isinstance(symbol, str) or not symbol or "/" in symbol or chr(92) in symbol or ".." in symbol:
        return []
    if captured is not None:
        try:
            candidates = [captured.operand("yahoo/chart/" + symbol)]
        except (AttributeError, ValueError, KeyError, OSError):
            return []
    else:
        root = Path(cache_root) if cache_root is not None else DEFAULT_CACHE
        candidates = [root / "yahoo/chart" / symbol, root / "yahoo/chart" / (symbol + ".json"),
                      root / "v3/yahoo/chart" / symbol, root / "v3/yahoo/chart" / (symbol + ".json")]
    for path in candidates:
        try:
            if path.is_file():
                _, bars = market_reader._chart_bars(path.read_bytes())
                return bars
        except (OSError, ValueError, IndexError, KeyError, TypeError, OverflowError):
            continue
    return []


def _verified_points(raw: Any) -> list[tuple[date, float]]:
    """Fail closed on malformed, nonfinite, nonpositive or unordered session prices."""
    if raw is None:
        return []
    try:
        rows = list(raw)
    except (TypeError, ValueError):
        return []
    clean: list[tuple[date, float]] = []
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            return []
        day, amount = row
        if type(day) is not date or type(amount) not in (int, float):
            return []
        try:
            number = float(amount)
        except (TypeError, ValueError, OverflowError):
            return []
        if not math.isfinite(number) or number <= 0 or (clean and day <= clean[-1][0]):
            return []
        clean.append((day, number))
    return clean


def _validation_record(symbol: str, after: date, evidence: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for item in evidence:
        if not isinstance(item, dict) or item.get("symbol") != symbol:
            continue
        day = _day(item.get("published_at"))
        url, family = item.get("source_url"), item.get("evidence_family")
        if (day is None or day < after or not isinstance(url, str) or not url.startswith("https://")
                or not isinstance(family, str) or not family or family.upper() in {"SERENITY", "SOCIAL", "PRICE"}):
            continue
        candidates.append((day, url, family))
    if not candidates:
        return None
    day, url, family = min(candidates)
    return {"published_at": day.isoformat(), "source_url": url, "evidence_family": family}


def build_calibration(signals: dict[str, Any], price_reader: Callable[[str], Any] | None = None, *,
                      evidence_records: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """NEW_THESIS date; forward returns; independent validation event and trading-session lag."""
    if not isinstance(signals, dict) or signals.get("schema_version") != serenity.SCHEMA_VERSION:
        raise ValueError("CURRENT_SERENITY_SCHEMA_REQUIRED")
    observed = serenity.parse_time(signals.get("generated_at"))
    if observed is None or not isinstance(signals.get("post_types"), list) or not isinstance(signals.get("signals"), list):
        raise ValueError("SERENITY_PROVENANCE_REQUIRED")
    reader = price_reader or cached_price_reader
    records = list(evidence_records)
    events: dict[str, set[str]] = {}
    source_kinds: dict[str, set[str]] = {}
    seen_sources: set[tuple[str, str]] = set()
    for item in signals["post_types"]:
        if not isinstance(item, dict) or item.get("post_type") != "NEW_THESIS":
            continue
        created = serenity.parse_time(item.get("created_at"))
        symbol, identity = item.get("symbol"), item.get("post_id")
        if (created is None or created > observed or not isinstance(symbol, str)
                or not isinstance(identity, str) or not identity
                or item.get("source_kind") not in {"ORIGINAL", "REPLY", "QUOTE"}
                or item.get("evidence_family") != "SERENITY_AUTHOR"
                or (symbol, identity) in seen_sources):
            continue
        seen_sources.add((symbol, identity))
        events.setdefault(symbol, set()).add(created.date().isoformat())
        source_kinds.setdefault(symbol, set()).add(item["source_kind"])
    result = []
    for sig in signals.get("signals", []):
        if not isinstance(sig, dict) or not isinstance(sig.get("symbol"), str):
            continue
        symbol = sig["symbol"]
        thesis_dates = sorted(events.get(symbol, set()))
        # Current-schema chronology is authoritative; a loose row timestamp must
        # not resurrect a removed/reposted/unparseable source as a new thesis.
        if not thesis_dates:
            continue
        thesis = date.fromisoformat(thesis_dates[0])
        try:
            points = _verified_points(reader(symbol))
        except (OSError, TypeError, ValueError, KeyError, AttributeError):
            points = []
        anchor = next((i for i, (d, _) in enumerate(points) if d >= thesis), None)
        record = _validation_record(symbol, thesis, records)
        row: dict[str, Any] = {"symbol": symbol, "new_thesis_dates": thesis_dates,
                                "first_thesis_at": thesis.isoformat(),
                                "source_kinds": sorted(source_kinds.get(symbol, set())),
                                "evidence_family": "SERENITY_AUTHOR", "independent_source_count": 1,
                                "source_freshness": sig.get("source_freshness", "UNKNOWN"),
                                "mirror_status": sig.get("mirror_status", "MIRROR_ONLY"),
                                "source_content_sha256": sig.get("latest_content_sha256"),
                                "price_anchor_date": points[anchor][0].isoformat() if anchor is not None else None}
        for horizon in HORIZONS:
            ret = None
            if anchor is not None and anchor + horizon < len(points):
                try:
                    ret = points[anchor + horizon][1] / points[anchor][1] - 1.0
                except (ZeroDivisionError, OverflowError):
                    pass
                if ret is not None and not math.isfinite(ret):
                    ret = None
            row[f"ret_{horizon}d"] = ret
        row["validation_event"] = record
        row["validation_lag_trading_days"] = None
        if anchor is not None and record is not None:
            validated = next((i for i, (d, _) in enumerate(points)
                              if d >= date.fromisoformat(record["published_at"])), None)
            if validated is not None and validated >= anchor:
                row["validation_lag_trading_days"] = validated - anchor
        result.append(row)
    result.sort(key=lambda item: item["symbol"])
    summary = {}
    for horizon in HORIZONS:
        values = [row[f"ret_{horizon}d"] for row in result if row[f"ret_{horizon}d"] is not None]
        known = len(values)
        hits = sum(value > 0 for value in values)
        summary[f"{horizon}d"] = {"count_used": known, "unknown_count": len(result)-known,
                                  "hit_count": hits, "hit_share": hits / known if known else None,
                                  "median": statistics.median(values) if values else None}
    return {"schema_version": 1, "source_schema_version": serenity.SCHEMA_VERSION,
            "research_only": True, "source_authority": "LEAD_ONLY_NOT_COMPANY_FACT",
            "source_freshness": (signals.get("source") or {}).get("source_freshness", "UNKNOWN"),
            "mirror_status": (signals.get("source") or {}).get("mirror_status", "UNKNOWN"),
            "count_new_thesis_symbols": len(result),
            "count_with_dated_validation_event": sum(bool(row["validation_event"]) for row in result),
            "count_known_validation_lag": sum(row["validation_lag_trading_days"] is not None for row in result),
            "summary": summary, "symbols": result,
            "caveats": [
                "Survivorship bias: public-post archive omits or underrepresents failed, removed and revised ideas.",
                "Self-selection bias: author chose thesis publication times and securities, not a random sample.",
                "Reflexivity: posts may move prices; post-date close is not an executable entry price.",
                "No posts or price moves count as issuer evidence or phase validation.",
                "Unknown captured prices and incomplete +5/+20/+60 trading-session histories are null, never misses.",
                "FX, after-hours posting, market calendars and adjusted-close methodology are not independently verified."]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS, help="Current Serenity signal/provenance JSON; read-only")
    parser.add_argument("--archive", type=Path, help="Existing archive JSON; read-only, no refresh")
    parser.add_argument("--evidence", type=Path, help="Independent dated evidence JSON list; read-only")
    parser.add_argument("--capture-root", type=Path, default=DEFAULT_CACHE,
                        help="Existing cached Yahoo chart operands; read-only")
    parser.add_argument("--output", type=Path, help="Optional research JSON destination; NEVER LINE")
    args = parser.parse_args(argv)
    if args.archive:
        archive = json.loads(args.archive.read_text(encoding="utf-8"))
        mapping = json.loads(serenity.TICKER_MAP.read_text(encoding="utf-8"))
        doc = serenity.build_signals(archive, mapping, serenity.us_symbols(), serenity.utc_now())
    else:
        doc = json.loads(args.signals.read_text(encoding="utf-8"))
    evidence = json.loads(args.evidence.read_text(encoding="utf-8")) if args.evidence else []
    report = build_calibration(doc, lambda symbol: cached_price_reader(symbol, cache_root=args.capture_root),
                               evidence_records=evidence)
    body = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(body, encoding="utf-8")
    else:
        print(body, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
