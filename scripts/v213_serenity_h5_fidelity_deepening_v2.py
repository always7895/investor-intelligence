#!/usr/bin/env python3
"""H5 v2 entrypoint: preserve date-only precision for public source views.

The direct X search surfaces used during development expose publication dates and
human-readable clock times, but not a trustworthy UTC offset.  H5 must not invent
UTC timestamps.  This wrapper replaces the H5 seed rows with ISO date-only values
and an explicit DATE_ONLY precision marker, then delegates to the validated H5
fidelity-deepening implementation.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h5_fidelity_deepening as base


DATE_ONLY_SEEDS = [
    {
        "source_id": "x-2013947011490615486",
        "source_url": "https://x.com/aleabitoreddit/status/2013947011490615486",
        "published_at": "2026-01-21",
        "time_precision": "DATE_ONLY",
        "scope": "methodology",
        "tickers": [],
        "view_type": "financing_disconfirmation",
        "paraphrase": "Repeated discounted offerings or ATM dilution can destroy retail equity capture; financing structure is a first-class disconfirmation check.",
        "verification": "development_verified_direct_public_x",
    },
    {
        "source_id": "x-2021053268420591653",
        "source_url": "https://x.com/aleabitoreddit/status/2021053268420591653",
        "published_at": "2026-02-10",
        "time_precision": "DATE_ONLY",
        "scope": "methodology",
        "tickers": [],
        "view_type": "short_interest_deemphasized",
        "paraphrase": "Short interest is not a primary thesis input when fundamentals are strong; some reported short interest can reflect convertible hedging.",
        "verification": "development_verified_direct_public_x",
    },
    {
        "source_id": "x-2033889361801175094",
        "source_url": "https://x.com/aleabitoreddit/status/2033889361801175094",
        "published_at": "2026-03-17",
        "time_precision": "DATE_ONLY",
        "scope": "ticker_view",
        "tickers": ["AXTI", "SOI", "TSEM", "COHR", "SIVE", "AAOI"],
        "view_type": "relative_public_view",
        "paraphrase": "Publicly favored semi-monopoly-like substrate exposure in AXTI/SOI; described TSEM/COHR as steady compounders and SIVE as highest-upside, with AAOI and AXTI also high-upside.",
        "verification": "development_verified_direct_public_x",
    },
    {
        "source_id": "x-2034752613246542215",
        "source_url": "https://x.com/aleabitoreddit/status/2034752613246542215",
        "published_at": "2026-03-19",
        "time_precision": "DATE_ONLY",
        "scope": "supercycle",
        "tickers": ["AXTI"],
        "view_type": "photonics_supercycle",
        "paraphrase": "Framed the trade as riding Photonics and Memory supercycles, explicitly including AXTI on the photonics side.",
        "verification": "development_verified_direct_public_x",
    },
]

base.SERENITY_SOURCE_SEEDS = DATE_ONLY_SEEDS


def self_test() -> None:
    for row in DATE_ONLY_SEEDS:
        assert row["time_precision"] == "DATE_ONLY"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["published_at"])
        assert not row["published_at"].endswith("Z")
    base.self_test()
    print("V213_H5_SOURCE_TIME_PRECISION = PASS")


def main() -> int:
    if "--self-test" in sys.argv:
        self_test()
        return 0
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
