"""fetch_nasdaq unpacks (listings, conflicts) from merge_directories (regression 2026-09-25: the tuple's length, 2,
was compared with the 1000-symbol floor, so every source-tree refresh failed at the live source federation)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v213_source_federation as federation  # noqa: E402

NASDAQ_HEADER = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares"
OTHER_HEADER = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol"


def directories(count: int, conflict: bool = False) -> dict[str, bytes]:
    nasdaq = [NASDAQ_HEADER] + [f"SYN{i:04d}|Synthetic {i} Corp.|Q|N|N|100|N|N" for i in range(count)]
    nasdaq += ["TEST|Synthetic Test Issue|Q|Y|N|100|N|N", "File Creation Time: 0925202600:00|||||||"]
    other = [OTHER_HEADER, "IBM|International Business Machines|N|IBM|N|100|N|IBM"]
    if conflict:
        other.append("SYN0000|Different Name Inc.|N|SYN0000|N|100|N|SYN0000")
    return {federation.NASDAQ_LISTED_URL: "\n".join(nasdaq).encode(), federation.OTHER_LISTED_URL: "\n".join(other).encode()}


class FetchNasdaqTests(unittest.TestCase):
    def run_fetch(self, bodies: dict[str, bytes]):
        original = federation.cached_request
        federation.cached_request = lambda session, method, url, cache_hours, **kw: (bodies[url], url, False)
        try:
            return federation.fetch_nasdaq(None)
        finally:
            federation.cached_request = original

    def test_listings_dict_counts_symbols_not_the_tuple(self):
        listings, observation = self.run_fetch(directories(1200))
        self.assertIsInstance(listings, dict)
        self.assertEqual(len(listings), 1201)  # 1200 synthetic + IBM; the test issue is skipped
        self.assertEqual(listings["IBM"].exchange, "N")
        self.assertEqual(observation["detail"]["symbols"], 1201)
        self.assertEqual(observation["detail"]["quarantined_conflicts"], 0)

    def test_conflicting_listing_is_quarantined(self):
        listings, observation = self.run_fetch(directories(1200, conflict=True))
        self.assertNotIn("SYN0000", listings)
        self.assertEqual(observation["detail"]["quarantined_conflicts"], 1)

    def test_small_directory_still_fails_closed(self):
        with self.assertRaises(federation.FederationError):
            self.run_fetch(directories(10))


if __name__ == "__main__":
    unittest.main()
