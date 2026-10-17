#!/usr/bin/env python3
"""Align every final v2.1.3 rank-coupled document to guarded Top20 order.

The snapshot evidence guard may legitimately change ranking after the Serenity
factor ledger has already been emitted. This finalizer performs a membership-
preserving reorder of the five-field report, seven-field report, federation,
source audit and factor ledger. It changes only array order and ``rank`` fields;
no evidence, factor, market value, source count or eligibility value is changed.
The three local candidate companions are validated against their exact original
report before rank-only rebinding. All inputs validate before any write; actual
bytes are read back. Sequential file replacement is NOT a sealed transaction,
consumer lock, recovery journal or cross-file atomicity/publication guarantee.
"""
from __future__ import annotations

import argparse
import copy
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from build_v212_top20_report import json_bytes, parse_candidate_json, rebind_ranked_candidates
from report_source_acquisition import validate_report_acquisition
from debt_source_precision import read_bundle

ROOT = SCRIPT_DIR.parent
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
    return parse_candidate_json(_read(path))


def _read(path: Path) -> bytes:
    with path.open('rb') as handle:
        body = handle.read(2_097_153)
    if len(body) > 2_097_152:
        raise FinalOrderError('FINAL_ORDER_INPUT_TOO_LARGE')
    return body


def atomic_bytes(path: Path, body: bytes) -> None:
    with tempfile.NamedTemporaryFile('wb', delete=False, dir=path.parent,
                                     prefix=f'.{path.name}.', suffix='.tmp') as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
        pending = Path(handle.name)
    pending.replace(path)


def atomic(path: Path, value: Any) -> None:
    atomic_bytes(path, json_bytes(value))


def _paths(paths: list[Path]) -> list[Path]:
    result = []
    for path in paths:
        if str(path).startswith(('\\\\', '//')):
            raise FinalOrderError('FINAL_ORDER_PATH_UNADMITTED')
        for item in (path, *path.parents):
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise FinalOrderError('FINAL_ORDER_PATH_UNADMITTED')
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise FinalOrderError('FINAL_ORDER_PATH_UNADMITTED')
        resolved = path.resolve(strict=True)
        if resolved in result:
            raise FinalOrderError('FINAL_ORDER_PATH_COLLISION')
        result.append(resolved)
    return result


def _ticker(row: Any) -> str:
    ticker = row.get('ticker') if isinstance(row, dict) else None
    if not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,19}', ticker):
        raise FinalOrderError('FINAL_ORDER_TICKER_INVALID')
    return ticker


def order_from_top20(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) != 20:
        raise FinalOrderError("Guarded Top20 must contain exactly 20 rows")
    order = [_ticker(row) for row in value]
    if len(order) != 20 or any(not ticker for ticker in order) or len(set(order)) != 20:
        raise FinalOrderError("Guarded Top20 ticker membership is invalid")
    for rank, row in enumerate(value, 1):
        if type(row.get('rank')) is not int or row['rank'] != rank:
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
        ticker = _ticker(row)
        if not ticker or ticker in mapping:
            raise FinalOrderError(f"Rank-coupled {key} membership is invalid")
        mapping[ticker] = copy.deepcopy(row)
    if set(mapping) != set(order):
        raise FinalOrderError('FINAL_ORDER_MEMBERSHIP_MISMATCH')
    result = copy.deepcopy(document)
    result[key] = []
    for rank, ticker in enumerate(order, 1):
        row = mapping[ticker]
        row["rank"] = rank
        result[key].append(row)
    return result


def finalize(top20_path: Path = TOP20, *, documents=None, companions=None, precision_path: Path | None = None) -> dict[str, Any]:
    try:
        documents = DOCUMENTS if documents is None else documents
        if len(documents) != 5 or tuple(key for _, key in documents) != ('records', 'records', 'ticker_sources', 'records', 'records'):
            raise FinalOrderError('FINAL_ORDER_DOCUMENT_ROLES_INVALID')
        five = documents[0][0]
        companions = tuple(five.with_name(five.stem + suffix) for suffix in (
            '.return-evidence-candidate.json', '.financial-evidence-candidate.json', '.financial-products-candidate.json')) if companions is None else companions
        if len(companions) != 3:
            raise FinalOrderError('FINAL_ORDER_COMPANION_ROLES_INVALID')
        paths = _paths([top20_path, *(path for path, _ in documents), *companions,
                        *([precision_path] if precision_path is not None else [])])
        precision_raw = None
        if precision_path is not None:
            precision_path = paths.pop()
            precision_raw = read_bundle(precision_path, forbidden=paths)
        inputs = {path: _read(path) for path in paths}
        order = order_from_top20(parse_candidate_json(inputs[paths[0]]))
        changed = []
        outputs = {}
        for path, (_, key) in zip(paths[1:6], documents):
            original = parse_candidate_json(inputs[path])
            if path == paths[1]:
                validate_report_acquisition(original)  # Do not repair malformed source ranks before validation.
            normalized = reorder_document(original, key, order)
            if [row['ticker'] for row in original[key]] != order:
                changed.append(path.name)
            outputs[path] = json_bytes(normalized)
        # Every document and prior product must validate before *any* replacement.
        options = {'precision_bundle':precision_raw} if precision_raw is not None else {}
        candidates = rebind_ranked_candidates(outputs[paths[1]], *(inputs[path] for path in paths[6:]), **options)
        outputs.update(zip(paths[6:], candidates))
        if (any(_read(path) != body for path, body in inputs.items())
                or precision_raw is not None and read_bundle(precision_path, forbidden=paths) != precision_raw):
            raise FinalOrderError('FINAL_ORDER_INPUT_CHANGED')
        for path in (*paths[2:6], *paths[6:], paths[1]):  # Five-field report last; not cross-file atomic.
            if outputs[path] != inputs[path]:
                atomic_bytes(path, outputs[path])
        if (any(_read(path) != body for path, body in outputs.items()) or _read(paths[0]) != inputs[paths[0]]
                or precision_raw is not None and read_bundle(precision_path, forbidden=paths) != precision_raw):
            raise FinalOrderError('FINAL_ORDER_READBACK_FAILED')
        return {'status': 'PASS', 'ticker_count': 20, 'first_ticker': order[0], 'changed': changed,
                'candidates_bound': True, 'publication_qualified': False, 'transaction_atomic': False}
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, FinalOrderError):
            raise
        raise FinalOrderError('FINAL_ORDER_CANDIDATE_OR_IO_INVALID') from None


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
    parser.add_argument('--top20', type=Path, default=TOP20)
    names = ('v212', 'v213', 'federation', 'source-audit', 'ledger')
    for name, (path, _) in zip(names, DOCUMENTS):
        parser.add_argument('--' + name, type=Path, default=path)
    for name in ('return-evidence', 'financial-evidence', 'financial-products'):
        parser.add_argument('--' + name, type=Path, help='Existing companion; default is beside --v212')
    parser.add_argument('--debt-precision-bundle', type=Path, help='Required original input when any companion contains company6 precision; never rewritten')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    documents = tuple((getattr(args, name.replace('-', '_')), key) for name, (_, key) in zip(names, DOCUMENTS))
    five = documents[0][0]
    companions = tuple(getattr(args, name.replace('-', '_')) or five.with_name(five.stem + '.' + name + '-candidate.json')
                       for name in ('return-evidence', 'financial-evidence', 'financial-products'))
    result = finalize(args.top20, documents=documents, companions=companions, precision_path=args.debt_precision_bundle)
    print(
        "V213_FINAL_RANK_COUPLED_ORDER = PASS; "
        f"tickers={result['ticker_count']}; first={result['first_ticker']}; "
        f"documents_reordered={','.join(result['changed']) or '-'}; "
        "values_changed=false; membership_changed=false; candidates_bound=true; "
        "publication_qualified=false; transaction_atomic=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FinalOrderError as exc:
        print(f"V213_FINAL_RANK_COUPLED_ORDER = FAIL; {exc}", file=__import__('sys').stderr, flush=True)
        raise SystemExit(1)
