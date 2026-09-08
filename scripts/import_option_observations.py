#!/usr/bin/env python3
"""Normalize authorized local provider exports; never fetch, publish or place orders.

TAIFEX daily rows are EOD observations, Alpaca indicative quotes are not NBBO.
Importing data is not a rights review or an admission to the public LINE DTO.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SOURCE_URLS = {
    "taifex_eod": "https://openapi.taifex.com.tw/v1/DailyMarketReportOpt",
    "alpaca_indicative": "https://data.alpaca.markets/v1beta1/options/quotes/latest",
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
                raw_day = str(row.get("Date", ""))
                if not re.fullmatch(r"\d{8}", raw_day):
                    raise ValueError("INVALID_TRADE_DATE")
                day = date(int(raw_day[:4]), int(raw_day[4:6]), int(raw_day[6:]))
                if day > now.date():
                    raise ValueError("FUTURE_TRADE_DATE")
                contract = str(row.get("Contract", ""))
                month = str(row.get("ContractMonth(Week)", ""))
                session = str(row.get("TradingSession", ""))
                right = {"買權": "C", "賣權": "P", "Call": "C", "Put": "P", "C": "C", "P": "P"}.get(row.get("CallPut"))
                if not re.fullmatch(r"[A-Z0-9]{1,12}", contract) or not re.fullmatch(r"\d{6}(?:W[1-5])?", month) or not right:
                    raise ValueError("INVALID_CONTRACT")
                if session not in {"一般", "盤後", "Position", "AfterHours"}:
                    raise ValueError("UNKNOWN_SESSION")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=tuple(SOURCE_URLS), required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.input.stat().st_size > 20_000_000:
            raise ValueError("INPUT_TOO_LARGE")
        result = normalize(args.source, json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        print(json.dumps({"status": "FAILED", "error": "INVALID_PROVIDER_EXPORT"}))
        return 1
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
