#!/usr/bin/env python3
"""Normalize authorized local provider exports; never fetch, publish or place orders.

TAIFEX daily rows are EOD observations, Alpaca indicative quotes are not NBBO.
Importing data is not a rights review or an admission to the public LINE DTO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Embedded Python ignores the caller's cwd/PYTHONPATH. Admit this script directory only.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from taifex_contract import (TAIFEX_DAILY_URL, TAIFEX_DELTA_ENVELOPE, TAIFEX_DELTA_MAX_BYTES, TAIFEX_DELTA_MAX_OUTPUT_BYTES,
                             TAIFEX_DELTA_URL, daily_identity, delta_reference_records, delta_reference_rows)

SOURCE_URLS = {
    "taifex_eod": TAIFEX_DAILY_URL,
    "alpaca_indicative": "https://data.alpaca.markets/v1beta1/options/quotes/latest",
    "taifex_delta": TAIFEX_DELTA_URL,
}
OCC = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


def number(value: Any, *, integer: bool = False) -> float | int | None:
    if value is None or value in ("", "-", "--"):
        return None
    if isinstance(value, bool):
        raise ValueError("INVALID_NUMBER")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError("INVALID_NUMBER") from None
    if not math.isfinite(result) or result < 0 or (integer and not result.is_integer()):
        raise ValueError("INVALID_NUMBER")
    return int(result) if integer else result


def instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("INVALID_TIMESTAMP")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("INVALID_TIMESTAMP") from None
    if result.tzinfo is None:
        raise ValueError("TIMESTAMP_REQUIRES_OFFSET")
    return result.astimezone(timezone.utc)


def normalize(source: str, payload: Any, *, now: datetime | None = None) -> dict:
    if source not in SOURCE_URLS:
        raise ValueError("UNKNOWN_SOURCE")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("CLOCK_REQUIRES_OFFSET")
    now = now.astimezone(timezone.utc)
    if source == "taifex_delta":
        return normalize_delta(payload, now)
    if source == "taifex_eod":
        if not isinstance(payload, list):
            raise ValueError("EXPECTED_DAILY_ROWS")
        rows = [(None, row) for row in payload]
    else:
        if not isinstance(payload, dict) or not isinstance(payload.get("quotes"), dict):
            raise ValueError("EXPECTED_QUOTES_MAP")
        rows = list(payload["quotes"].items())
    if len(rows) > 50000:
        raise ValueError("TOO_MANY_OBSERVATIONS")
    observations, failures, seen = [], [], set()
    for index, (symbol, row) in enumerate(rows):
        try:
            if not isinstance(row, dict):
                raise ValueError("INVALID_ROW")
            if source == "taifex_eod":
                day, contract, month, right, session = daily_identity(
                    row, taipei_day=now.astimezone(timezone(timedelta(hours=8))).date())
                strike = number(row.get("StrikePrice"))
                bid, ask = number(row.get("BestBid")), number(row.get("BestAsk"))
                item = {"contract": contract, "contract_month": month, "right": right,
                        "strike": strike, "session": session, "trade_date": day.isoformat(),
                        "quote_time": None, "expiry": None, "multiplier": None,
                        "volume": number(row.get("Volume"), integer=True),
                        "open_interest": number(row.get("OpenInterest"), integer=True),
                        "feed_type": "END_OF_DAY", "freshness": "HISTORICAL_DAILY"}
                key = (contract, month, right, strike, session, day)
            else:
                match = OCC.fullmatch(str(symbol))
                if not match:
                    raise ValueError("INVALID_OCC_CONTRACT")
                root, expiration, right, raw_strike = match.groups()
                expiry = date(2000 + int(expiration[:2]), int(expiration[2:4]), int(expiration[4:]))
                timestamp = instant(row.get("t"))
                if timestamp > now:
                    raise ValueError("FUTURE_QUOTE")
                bid, ask = number(row.get("bp")), number(row.get("ap"))
                strike = int(raw_strike) / 1000
                item = {"contract": symbol, "underlying": root, "right": right, "strike": strike,
                        "expiry": expiry.isoformat(), "multiplier": None,
                        "quote_time": timestamp.isoformat(), "volume": None, "open_interest": None,
                        "feed_type": "INDICATIVE_NOT_NBBO",
                        "freshness": "EXPIRED" if expiry < now.date() else "STALE" if (now - timestamp).total_seconds() > 900 else "RECENT_INDICATIVE"}
                key = (symbol, timestamp)
            if strike is None or strike <= 0:
                raise ValueError("INVALID_STRIKE")
            if bid is not None and ask is not None and bid > ask:
                raise ValueError("CROSSED_QUOTE")
            if key in seen:
                raise ValueError("DUPLICATE_OBSERVATION")
            seen.add(key)
            item.update({"bid": bid, "ask": ask, "provider": source,
                         "origin": "TAIFEX" if source == "taifex_eod" else "OPRA_DERIVED",
                         "source_url": SOURCE_URLS[source], "retrieved_at": None,
                         "imported_at": now.isoformat(), "executable_quote": False,
                         "publication_eligible": False})
            observations.append(item)
        except (ValueError, TypeError, OverflowError):
            # Only index/category is emitted: provider rows may contain private metadata.
            failures.append({"row_index": index, "status": "INVALID_OBSERVATION"})
    return {"schema_version": 1, "mode": "LOCAL_IMPORT_ONLY", "provider": source,
            "status": "PARTIAL" if failures and observations else "FAILED" if failures else "OK" if observations else "NO_DATA",
            "publication_eligible": False, "rights_status": "NOT_REVIEWED_BY_IMPORTER",
            "observations": observations, "failures": failures}


def normalize_delta(payload: Any, now: datetime, *, input_sha256: str | None = None) -> dict:
    """LOCAL reference import of a user-supplied export shaped like TAIFEX dataset 11321 (DailyOptionsDelta). It reuses the ONE shared
    reference parser (the bounded raw-bytes decoder lives in main). A manual file stays LOCAL_ONLY with UNVERIFIED origin even if it claims
    TAIFEX, a URL, a receipt or a hash: no transport receipt is minted, accepted or read, and imported_at is the import time only (never a
    retrieval time, quote as-of or Delta as-of). The optional input_sha256 is computed by this importer over the exact bytes it read; it
    identifies those bytes and is NOT an authenticated origin. Nothing here is joined into EOD observations, rights-reviewed or
    published. All-or-nothing: an unsupported export raises."""
    records = delta_reference_records(payload, origin_verification="UNVERIFIED_LOCAL_FILE")
    return {"schema_version": 1, "mode": "LOCAL_REFERENCE_IMPORT_ONLY", "provider": "taifex_delta", "status": "OK",
            "publication_eligible": False, "rights_status": "NOT_REVIEWED_BY_IMPORTER", "origin_verification": "UNVERIFIED_LOCAL_FILE",
            "imported_at": now.isoformat(),
            "input_binding": ({"sha256": input_sha256, "scope": "EXACT_BYTES_READ_BY_THIS_IMPORT", "authenticated_origin": False}
                              if input_sha256 else None),
            "reference_envelope": {**TAIFEX_DELTA_ENVELOPE, "identity_status": "EXPECTED_DATASET_UNVERIFIED_FOR_A_MANUAL_FILE"},
            "reference_rows": records, "failures": []}


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=tuple(SOURCE_URLS), required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.source == "taifex_delta":
            # ONE binary handle and a bounded read (never stat-then-read of a file that may change): an overflow is refused before any
            # decode, and the reported hash binds exactly the bytes read. The origin stays UNVERIFIED_LOCAL_FILE.
            with args.input.open("rb") as handle:
                content = handle.read(TAIFEX_DELTA_MAX_BYTES + 1)
            result = normalize_delta(delta_reference_rows(content), datetime.now(timezone.utc),
                                     input_sha256=hashlib.sha256(content).hexdigest())
        else:
            if args.input.stat().st_size > 20_000_000:
                raise ValueError("INPUT_TOO_LARGE")
            result = normalize(args.source, json.loads(args.input.read_text(encoding="utf-8"), object_pairs_hook=unique_object))
    except (OSError, ValueError):
        print(json.dumps({"status": "FAILED", "error": "INVALID_PROVIDER_EXPORT"}))
        return 1
    rendered = json.dumps(result, ensure_ascii=True, allow_nan=False)
    if args.source == "taifex_delta" and len(rendered) + 2 > TAIFEX_DELTA_MAX_OUTPUT_BYTES:
        # Checked on the in-memory Delta result after it is built and before anything is printed. This CLI prints (it does not write a
        # file): ensure_ascii makes len(rendered) the byte count, +2 covers a CRLF newline. A fixed error only, never a partial Delta
        # rows. Only a Delta result is bounded; other importer sources print exactly as before.
        print(json.dumps({"status": "FAILED", "error": "TAIFEX_DELTA_OUTPUT_TOO_LARGE"}))
        return 1
    print(rendered)
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
