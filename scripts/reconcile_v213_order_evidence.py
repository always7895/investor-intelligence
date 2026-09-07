#!/usr/bin/env python3
"""Reconcile v2.1.3 order evidence to the current v2.1.2 Top20 membership.

Existing R15R evidence is preserved byte-for-field for tickers that remain in the
Top20. Newly admitted tickers are researched deterministically through the same
SEC-only generic order extractor used by H6B1. Removed tickers are dropped.

This is deliberately fail-closed:
- no local model is allowed to invent order totals;
- no numeric total is estimated from guidance or pipeline;
- if no explicit SEC order/backlog/RPO metric is found, the accepted UNAVAILABLE
  fallback is used;
- the resulting runtime baseline is a local reconciliation artifact, not a claim
  that the new ticker rows were part of the historical H6B2 R15R acceptance.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h6b_full_top20 as h6b

DEFAULT_V212 = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
DEFAULT_BASELINE = ROOT / "data" / "bootstrap" / "v213-r15r-order-baseline.json"
DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_order_evidence_runtime.json"
DEFAULT_RECEIPT = ROOT / "data" / "cache" / "v213_order_evidence_reconciliation.json"


class ReconciliationError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"Unable to read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReconciliationError(f"JSON root must be an object: {path}")
    return value


def _records(doc: Mapping[str, Any], version: str) -> list[dict[str, Any]]:
    if str(doc.get("product_version")) != version:
        raise ReconciliationError(f"Expected product_version={version}")
    rows = doc.get("records")
    if not isinstance(rows, list) or len(rows) != 20:
        raise ReconciliationError("Expected exactly 20 records")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise ReconciliationError("Record must be an object")
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker or ticker in seen or int(row.get("rank") or 0) != index:
            raise ReconciliationError("Ticker/rank contract failed")
        seen.add(ticker)
        result.append(dict(row))
    return result


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def _sha(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _baseline_row_from_outlook(rank: int, ticker: str, outlook: Mapping[str, Any]) -> dict[str, Any]:
    current = str(outlook.get("current_orders_summary") or "").strip()
    future = str(outlook.get("future_orders_estimate") or "").strip()
    confidence = str(outlook.get("confidence") or "").strip()
    as_of = str(outlook.get("as_of") or "").strip()
    current_urls = [str(url) for url in outlook.get("current_order_source_urls") or []]
    future_urls = [str(url) for url in outlook.get("future_order_source_urls") or []]
    if not current or not future or not confidence:
        raise ReconciliationError(f"Incomplete order outlook for {ticker}")
    if outlook.get("numeric_total_order_estimate_prohibited") is not True:
        raise ReconciliationError(f"Numeric total-order guard missing for {ticker}")
    return {
        "rank": rank,
        "ticker": ticker,
        "current_orders": current,
        "future_orders_estimate": future,
        "orders_as_of": as_of,
        "orders_confidence": confidence,
        "current_order_source_urls": current_urls,
        "future_order_source_urls": future_urls,
        "reconciliation_source": "automated_h6b_sec_delta",
    }


def reconcile(
    v212: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    resolver: Callable[[str], Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fresh = _records(v212, "2.1.2")
    old = _records(baseline, "2.1.3")
    old_by_ticker = {row["ticker"]: row for row in old}
    fresh_order = [row["ticker"] for row in fresh]
    old_order = [row["ticker"] for row in old]
    added = [ticker for ticker in fresh_order if ticker not in old_by_ticker]
    removed = [ticker for ticker in old_order if ticker not in set(fresh_order)]

    if resolver is None:
        try:
            cik_map = h6b.sec_ticker_map()
        except Exception as exc:
            if added:
                raise ReconciliationError("SEC ticker map unavailable while new Top20 members require order research") from exc
            cik_map = {}

        def resolver(ticker: str) -> Mapping[str, Any]:
            print(f"II_PROGRESS v2.1.3 order evidence research | {ticker}", flush=True)
            return h6b.order_outlook_for_ticker(ticker, {}, cik_map)

    rows: list[dict[str, Any]] = []
    researched: list[str] = []
    supported_new: list[str] = []
    unavailable_new: list[str] = []
    for rank, ticker in enumerate(fresh_order, 1):
        if ticker in old_by_ticker:
            row = copy.deepcopy(old_by_ticker[ticker])
            row["rank"] = rank
            row["ticker"] = ticker
            row["reconciliation_source"] = "accepted_r15r_preserved"
            rows.append(row)
            continue
        print(f"II_PROGRESS v2.1.3 order evidence delta {len(researched)+1}/{len(added)} | {ticker}", flush=True)
        outlook = resolver(ticker)
        row = _baseline_row_from_outlook(rank, ticker, outlook)
        rows.append(row)
        researched.append(ticker)
        if str(outlook.get("evidence_status") or "") == "UNAVAILABLE":
            unavailable_new.append(ticker)
        else:
            supported_new.append(ticker)

    document = {
        "schema_version": 2,
        "product_version": "2.1.3",
        "accepted_from": "R15R_PLUS_AUTOMATED_H6B_SEC_DELTA",
        "parent_baseline_sha256": _sha(baseline),
        "records": rows,
    }
    receipt = {
        "schema_version": 1,
        "product_version": "2.1.3",
        "status": "PASS",
        "mode": "TOP20_MEMBERSHIP_ORDER_EVIDENCE_RECONCILIATION",
        "old_order": old_order,
        "new_order": fresh_order,
        "added": added,
        "removed": removed,
        "preserved_count": 20 - len(added),
        "researched_new": researched,
        "supported_new": supported_new,
        "unavailable_new": unavailable_new,
        "numeric_total_order_estimate_prohibited": True,
        "local_model_used_for_order_totals": False,
        "runtime_baseline_sha256": _sha(document),
    }
    return document, receipt


def self_test() -> None:
    generated = "2026-09-02T00:00:00Z"
    old_order = [f"T{i:02d}" for i in range(20)]
    new_order = old_order[:16] + ["NEW1", "NEW2", "NEW3", "NEW4"]
    v212 = {
        "product_version": "2.1.2",
        "records": [{"rank": i + 1, "ticker": t} for i, t in enumerate(new_order)],
    }
    baseline = {
        "product_version": "2.1.3",
        "records": [{
            "rank": i + 1,
            "ticker": t,
            "current_orders": h6b.CURRENT_FALLBACK,
            "future_orders_estimate": h6b.FUTURE_FALLBACK,
            "orders_as_of": generated,
            "orders_confidence": "UNAVAILABLE",
            "current_order_source_urls": [],
            "future_order_source_urls": [],
        } for i, t in enumerate(old_order)],
    }
    calls: list[str] = []
    def fake_resolver(ticker: str) -> Mapping[str, Any]:
        calls.append(ticker)
        return h6b.unavailable_outlook()
    document, receipt = reconcile(v212, baseline, resolver=fake_resolver)
    assert [row["ticker"] for row in document["records"]] == new_order
    assert calls == ["NEW1", "NEW2", "NEW3", "NEW4"]
    assert receipt["added"] == calls
    assert receipt["removed"] == ["T16", "T17", "T18", "T19"]
    assert receipt["local_model_used_for_order_totals"] is False
    print("V213_ORDER_EVIDENCE_RECONCILIATION_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v212-report", type=Path, default=DEFAULT_V212)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    document, receipt = reconcile(_load(args.v212_report), _load(args.baseline))
    _atomic_json(args.output, document)
    _atomic_json(args.receipt, receipt)
    print(
        "V213_ORDER_EVIDENCE_RECONCILIATION = PASS; "
        f"added={','.join(receipt['added']) or '-'}; removed={','.join(receipt['removed']) or '-'}; "
        f"supported_new={','.join(receipt['supported_new']) or '-'}; "
        f"unavailable_new={','.join(receipt['unavailable_new']) or '-'}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReconciliationError, h6b.H6BError, OSError, ValueError) as exc:
        print(f"V213_ORDER_EVIDENCE_RECONCILIATION = FAIL; {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
