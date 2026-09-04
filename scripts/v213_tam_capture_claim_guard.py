#!/usr/bin/env python3
"""Fail closed when TAM-capture points lack current company-capture evidence.

Market returns, sector labels and broad TAM narratives cannot support company TAM
capture.  Positive TAM-capture points require a current primary-backed revenue
change in the five-field report or fresh evidence-bound order visibility.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOP20 = ROOT / "data" / "cache" / "top20_public_latest.json"
V212 = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
V213 = ROOT / "data" / "cache" / "v213_top20_report_public_latest.json"
FEDERATION = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
SOURCE_AUDIT = ROOT / "data" / "cache" / "v213_source_independence_latest.json"
REVENUE_PATTERNS = (
    re.compile(r"營收年增\s*([+-]?\d+(?:\.\d+)?)%"),
    re.compile(r"revenue\s+(?:yoy|year[- ]over[- ]year|growth)\s*[:：]?\s*([+-]?\d+(?:\.\d+)?)%", re.I),
)


class GuardError(RuntimeError):
    pass


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"Unable to read JSON: {path}") from exc


def atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False, dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def parse_time(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = dt.datetime.combine(dt.date.fromisoformat(text[:10]), dt.time(), tzinfo=dt.timezone.utc)
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def revenue_growth(summary: Any) -> float | None:
    text = str(summary or "")
    for pattern in REVENUE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                value = float(match.group(1))
                return value if math.isfinite(value) else None
            except ValueError:
                return None
    return None


def rating(score: float) -> str:
    if score >= 55:
        return "A"
    if score >= 40:
        return "B"
    if score >= 25:
        return "C"
    return "D"


def normalize(top20: list[dict[str, Any]], v212: dict[str, Any], v213: dict[str, Any], federation: dict[str, Any], source: dict[str, Any], now: dt.datetime) -> tuple[Any, Any, Any, Any, Any, list[str]]:
    groups = {
        "v212": v212.get("records"), "v213": v213.get("records"),
        "federation": federation.get("ticker_sources"), "source": source.get("records"),
    }
    if len(top20) != 20 or any(not isinstance(value, list) or len(value) != 20 for value in groups.values()):
        raise GuardError("TAM guard requires exactly 20 aligned rows")
    order = [str(row.get("ticker") or "").upper() for row in top20]
    maps = {name: {str(row.get("ticker") or "").upper(): dict(row) for row in rows} for name, rows in groups.items()}
    if any(set(mapping) != set(order) for mapping in maps.values()):
        raise GuardError("TAM guard membership mismatch")
    changed: list[str] = []
    result = copy.deepcopy(top20)
    for row in result:
        ticker = str(row.get("ticker") or "").upper()
        five = maps["v212"][ticker]
        seven = maps["v213"][ticker]
        factors = row.get("serenity_factors")
        if not isinstance(factors, dict):
            raise GuardError(f"{ticker} lacks factor object")
        current_tam = float(factors.get("tam_capture") or 0.0)
        if current_tam <= 0:
            continue
        growth = revenue_growth(five.get("profit_summary"))
        order_confidence = str(seven.get("orders_confidence") or "")
        order_time = parse_time(seven.get("orders_as_of"))
        order_age = (now - order_time.astimezone(dt.timezone.utc)).total_seconds() / 86400 if order_time else None
        fresh_order = order_confidence not in {"", "UNAVAILABLE", "NO_RELIABLE_PUBLIC_ORDER_NUMBER"} and order_age is not None and -1 <= order_age <= 200
        if growth is None and not fresh_order:
            factors["tam_capture"] = 0.0
            row["serenity_raw_score"] = round(sum(float(factors.get(key) or 0.0) for key in factors), 2)
            penalty = max(0.0, float(row.get("risk_penalty") or 0.0))
            row["serenity_score"] = round(max(0.0, min(100.0, row["serenity_raw_score"] - penalty)), 2)
            row["rating"] = rating(float(row["serenity_score"]))
            row["risk_flags"] = sorted(set(str(value) for value in row.get("risk_flags") or []) | {"tam_capture_zeroed_without_current_revenue_or_order_evidence"})
            changed.append(ticker)
    result.sort(key=lambda item: (-float(item.get("serenity_score") or 0), -float(item.get("data_quality") or 0), str(item.get("ticker") or "")))
    final_order = [str(row.get("ticker") or "").upper() for row in result]
    for rank, row in enumerate(result, 1):
        row["rank"] = rank
    def reorder(document: dict[str, Any], key: str, mapping: dict[str, dict[str, Any]]) -> dict[str, Any]:
        out = copy.deepcopy(document)
        out[key] = []
        for rank, ticker in enumerate(final_order, 1):
            row = copy.deepcopy(mapping[ticker])
            row["rank"] = rank
            out[key].append(row)
        return out
    return (
        result,
        reorder(v212, "records", maps["v212"]),
        reorder(v213, "records", maps["v213"]),
        reorder(federation, "ticker_sources", maps["federation"]),
        reorder(source, "records", maps["source"]),
        changed,
    )


def self_test() -> None:
    now = dt.datetime(2026, 9, 3, tzinfo=dt.timezone.utc)
    top = [{"rank": i + 1, "ticker": f"T{i:02d}", "serenity_score": 10.0, "serenity_raw_score": 12.0, "risk_penalty": 2.0, "data_quality": 0.5, "rating": "D", "serenity_factors": {"demand_wave": 0, "chokepoint": 0, "pricing_power": 0, "replacement_friction": 0, "tam_capture": 2, "valuation_expectations": 3.75, "evidence_quality": 6.25}, "risk_flags": []} for i in range(20)]
    five = {"records": [{"rank": i + 1, "ticker": f"T{i:02d}", "profit_summary": "獲利" if i == 0 else "獲利；營收年增 +20.0%"} for i in range(20)]}
    seven = {"records": [{"rank": i + 1, "ticker": f"T{i:02d}", "orders_confidence": "UNAVAILABLE", "orders_as_of": ""} for i in range(20)]}
    federation = {"ticker_sources": [{"rank": i + 1, "ticker": f"T{i:02d}"} for i in range(20)]}
    source = {"records": [{"rank": i + 1, "ticker": f"T{i:02d}"} for i in range(20)]}
    output = normalize(top, five, seven, federation, source, now)
    row = next(item for item in output[0] if item["ticker"] == "T00")
    assert row["serenity_factors"]["tam_capture"] == 0
    assert len(output[-1]) == 1
    print("V213_TAM_CAPTURE_CLAIM_GUARD_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top20", type=Path, default=TOP20)
    parser.add_argument("--v212", type=Path, default=V212)
    parser.add_argument("--v213", type=Path, default=V213)
    parser.add_argument("--federation", type=Path, default=FEDERATION)
    parser.add_argument("--source-audit", type=Path, default=SOURCE_AUDIT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    top = load(args.top20)
    if not isinstance(top, list):
        raise GuardError("Top20 root must be a list")
    output = normalize(top, load(args.v212), load(args.v213), load(args.federation), load(args.source_audit), dt.datetime.now(dt.timezone.utc))
    for path, value in zip((args.top20, args.v212, args.v213, args.federation, args.source_audit), output[:5]):
        atomic(path, value)
    print(f"V213_TAM_CAPTURE_CLAIM_GUARD = PASS; changed={','.join(output[-1]) or '-'}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardError as exc:
        print(f"V213_TAM_CAPTURE_CLAIM_GUARD = FAIL; {exc}", file=__import__('sys').stderr, flush=True)
        raise SystemExit(1)
