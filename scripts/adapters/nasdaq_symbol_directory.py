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


def _truth(value: str) -> bool:
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
        exchange = str(row.get("Listing Exchange") or row.get("Market Category") or "NASDAQ").strip()
        result.append(
            ListingIdentity(
                symbol=symbol,
                security_name=name,
                exchange=exchange,
                source_url=source_url,
                test_issue=_truth(str(row.get("Test Issue") or "N")),
                etf=_truth(str(row.get("ETF") or "N")),
            )
        )
    return result


def merge_directories(documents: Iterable[tuple[str, str]]) -> dict[str, ListingIdentity]:
    result: dict[str, ListingIdentity] = {}
    for source_url, text in documents:
        for item in parse_directory(text, source_url):
            if item.test_issue:
                continue
            result.setdefault(item.symbol, item)
    return result


def self_test() -> None:
    nasdaq = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nNVDA|NVIDIA Corporation|Q|N|N|100|N|N\nFile Creation Time: 010120260000|\n"
    other = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nIBM|International Business Machines|N|IBM|N|100|N|IBM\n"
    merged = merge_directories(((NASDAQ_LISTED_URL, nasdaq), (OTHER_LISTED_URL, other)))
    assert set(merged) == {"NVDA", "IBM"}
    assert merged["NVDA"].exchange == "Q"
    assert merged["IBM"].source_url == OTHER_LISTED_URL
    print("NASDAQ_SYMBOL_DIRECTORY_ADAPTER_SELF_TEST = PASS")


if __name__ == "__main__":
    self_test()
