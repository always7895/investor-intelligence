#!/usr/bin/env python3
"""Reviewed parser for Nasdaq Trader's public symbol-directory files."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Iterable

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


@dataclass(frozen=True)
class ListingIdentity:
    symbol: str
    security_name: str
    exchange: str
    source_url: str
    test_issue: bool
    etf: bool


def _truth(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().upper() == "Y"


def parse_directory(text: str, source_url: str) -> list[ListingIdentity]:
    rows = list(csv.DictReader(io.StringIO(text), delimiter="|"))
    result: list[ListingIdentity] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("Symbol") or row.get("ACT Symbol") or "").strip().upper()
        if not symbol or symbol.startswith("FILE CREATION TIME"):
            continue
        name = str(row.get("Security Name") or "").strip()
        # Check Exchange (used in otherlisted.txt), Listing Exchange, or Market Category
        exchange = str(
            row.get("Exchange")
            or row.get("Listing Exchange")
            or row.get("Market Category")
            or "NASDAQ"
        ).strip()
        test_val = row.get("Test Issue")
        etf_val = row.get("ETF")
        result.append(
            ListingIdentity(
                symbol=symbol,
                security_name=name,
                exchange=exchange,
                source_url=source_url,
                test_issue=_truth(test_val),
                etf=_truth(etf_val),
            )
        )
    return result


def merge_directories(
    documents: Iterable[tuple[str, str]],
) -> tuple[dict[str, ListingIdentity], dict[str, list[ListingIdentity]]]:
    result: dict[str, ListingIdentity] = {}
    conflicts: dict[str, list[ListingIdentity]] = {}
    for source_url, text in documents:
        for item in parse_directory(text, source_url):
            if item.test_issue:
                continue
            existing = result.get(item.symbol)
            if existing is None:
                result[item.symbol] = item
            else:
                if (
                    existing.security_name == item.security_name
                    and existing.exchange == item.exchange
                    and existing.etf == item.etf
                ):
                    # Duplicate identical record; safe to keep existing
                    continue
                # Different listing details: conflict detected, quarantine
                conflicts.setdefault(item.symbol, [existing]).append(item)
    # Remove conflicting symbols from direct result
    for sym in conflicts:
        result.pop(sym, None)
    return result, conflicts


def self_test() -> None:
    nasdaq = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nNVDA|NVIDIA Corporation|Q|N|N|100|N|N\nFile Creation Time: 010120260000|\n"
    other = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nIBM|International Business Machines|N|IBM|N|100|N|IBM\n"
    merged, conflicts = merge_directories(((NASDAQ_LISTED_URL, nasdaq), (OTHER_LISTED_URL, other)))
    assert set(merged) == {"NVDA", "IBM"}
    assert merged["NVDA"].exchange == "Q"
    assert merged["IBM"].exchange == "N"
    assert merged["IBM"].source_url == OTHER_LISTED_URL
    assert len(conflicts) == 0

    # Test conflict handling
    nasdaq_dup = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nIBM|Conflicting IBM|Q|N|N|100|N|N\n"
    merged_conflict, conflicts2 = merge_directories(((OTHER_LISTED_URL, other), (NASDAQ_LISTED_URL, nasdaq_dup)))
    assert "IBM" not in merged_conflict
    assert "IBM" in conflicts2
    assert len(conflicts2["IBM"]) == 2
    print("NASDAQ_SYMBOL_DIRECTORY_ADAPTER_SELF_TEST = PASS")


if __name__ == "__main__":
    self_test()
