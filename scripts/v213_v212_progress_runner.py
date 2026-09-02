#!/usr/bin/env python3
"""Progress-only wrapper for the accepted v2.1.2 five-field report builder."""
from __future__ import annotations

import build_v212_top20_report as report


def main() -> int:
    original = report._market_observation
    counter = {"value": 0}

    def progress_market_observation(ticker: str, fallback_industry: str):
        counter["value"] += 1
        print(
            f"II_PROGRESS v2.1.2 market/SEC row {counter['value']}/20 | {ticker}",
            flush=True,
        )
        return original(ticker, fallback_industry)

    report._market_observation = progress_market_observation
    try:
        return report.main()
    finally:
        report._market_observation = original


if __name__ == "__main__":
    raise SystemExit(main())
