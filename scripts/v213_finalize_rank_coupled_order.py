#!/usr/bin/env python3
"""Align every final v2.1.3 rank-coupled document to guarded Top20 order.

The snapshot evidence guard may legitimately change ranking after the Serenity
factor ledger has already been emitted. This finalizer performs a membership-
preserving reorder of the five-field report, seven-field report, federation,
source audit and factor ledger. It changes only array order and ``rank`` fields;
no evidence, factor, market value, source count or eligibility value is changed.
"""
from __future__ import annotations

import argparse
import copy
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
TOP20 = ROOT / "data" / "cache" / "top20_public_latest.json"
DOCUMENTS = (
    (ROOT / "data" / "cache" / "v212_top20_report_public_latest.json", "records"),
    (ROOT / "data" / "cache" / "v213_top20_report_public_latest.json", "records"),
    (ROOT / "data" / "cache" / "v213_source_federation_latest.json", "ticker_sources"),
    (ROOT / "data" / "cache" / "v213_source_independence_latest.json", "records"),
    (ROOT / "data" / "cache" / "v213_serenity_factor_ledger_latest.json", "records"),
)


class FinalOrderError(RuntimeError):
    pass


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalOrderError(f"Unable to read rank-coupled document: {path}") from exc


def atomic(path: Path, value: Any) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        pending = Path(handle.name)
    pending.replace(path)


def order_from_top20(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) != 20:
        raise FinalOrderError("Guarded Top20 must contain exactly 20 rows")
    order = [str(row.get("ticker") or "").strip().upper() for row in value if isinstance(row, Mapping)]
    if len(order) != 20 or any(not ticker for ticker in order) or len(set(order)) != 20:
        raise FinalOrderError("Guarded Top20 ticker membership is invalid")
    for rank, row in enumerate(value, 1):
        if not isinstance(row, Mapping) or int(row.get("rank") or 0) != rank:
            raise FinalOrderError("Guarded Top20 rank sequence is invalid")
    return order


def reorder_document(document: Any, key: str, order: list[str]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise FinalOrderError(f"Rank-coupled {key} document is not an object")
    rows = document.get(key)
    if not isinstance(rows, list) or len(rows) != 20:
        raise FinalOrderError(f"Rank-coupled {key} document must contain 20 rows")
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise FinalOrderError(f"Rank-coupled {key} row is not an object")
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker in mapping:
            raise FinalOrderError(f"Rank-coupled {key} membership is invalid")
        mapping[ticker] = copy.deepcopy(row)
    if set(mapping) != set(order):
        missing = sorted(set(order) - set(mapping))
        extra = sorted(set(mapping) - set(order))
        raise FinalOrderError(
            f"Rank-coupled {key} membership differs from Top20; "
            f"missing={','.join(missing) or '-'}; extra={','.join(extra) or '-'}"
        )
    result = copy.deepcopy(document)
    result[key] = []
    for rank, ticker in enumerate(order, 1):
        row = mapping[ticker]
        row["rank"] = rank
        result[key].append(row)
    return result


def finalize(top20_path: Path = TOP20) -> dict[str, Any]:
    order = order_from_top20(load(top20_path))
    changed: list[str] = []
    for path, key in DOCUMENTS:
        original = load(path)
        before = [str(row.get("ticker") or "").strip().upper() for row in original.get(key, [])]
        normalized = reorder_document(original, key, order)
        after = [str(row.get("ticker") or "").strip().upper() for row in normalized[key]]
        if before != after:
            changed.append(path.name)
        atomic(path, normalized)
        if after != order:
            raise FinalOrderError(f"Final order readback failed: {path}")
    return {"status": "PASS", "ticker_count": 20, "first_ticker": order[0], "changed": changed}


def self_test() -> None:
    order = [f"T{index:02d}" for index in range(20)]
    document = {"records": [{"rank": index + 1, "ticker": ticker, "value": index} for index, ticker in enumerate(reversed(order))]}
    normalized = reorder_document(document, "records", order)
    assert [row["ticker"] for row in normalized["records"]] == order
    assert [row["rank"] for row in normalized["records"]] == list(range(1, 21))
    original_values = {row["ticker"]: row["value"] for row in document["records"]}
    assert all(original_values[row["ticker"]] == row["value"] for row in normalized["records"])
    print("V213_FINAL_RANK_COUPLED_ORDER_SELF_TEST = PASS; values_changed=false; membership_changed=false")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    result = finalize()
    print(
        "V213_FINAL_RANK_COUPLED_ORDER = PASS; "
        f"tickers={result['ticker_count']}; first={result['first_ticker']}; "
        f"documents_reordered={','.join(result['changed']) or '-'}; "
        "values_changed=false; membership_changed=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FinalOrderError as exc:
        print(f"V213_FINAL_RANK_COUPLED_ORDER = FAIL; {exc}", file=__import__('sys').stderr, flush=True)
        raise SystemExit(1)
