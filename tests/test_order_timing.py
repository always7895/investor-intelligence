from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import order_timing as ot  # noqa: E402

# Phrasings observed in 2026 10-Q filings, shortened; values are the filings' own percentages.
PAIR = ("The Company expects to recognize approximately 77 % of remaining performance obligations as revenue in the next "
        "twelve months , approximately 14 % in the following twelve months , and the remainder thereafter.")
SEGMENTS = ("Remaining Performance Obligation (RPO) . We expect to recognize revenue as follows: (1) Equipment-related RPO of "
            "$ 87,821 million of which 36 % , 65 % , and 97 % is expected to be recognized within 1 , 2 , and 5 years , "
            "respectively. (2) Services-related RPO of $ 88,463 million of which 16 % , 54 % , 79 % , and 92 % is expected "
            "to be recognized within 1 , 5 , 10 , and 15 years , respectively.")
INITIAL = ("the Company had $ 103.7 billion of unsatisfied RPO, of which 41 % was expected to be recognized over the initial "
           "24 months ending June 30, 2028, 39 % between months 25 and 48.")
AMOUNT = "remaining performance obligations was $ 315 million, of which $ 201 million is expected to be recognized in the next 12 months."
NOT_TIMING = ("remaining performance obligations was approximately $ 5 billion, of which $ 422 million has been recognized as "
              "contract liabilities.")
# Micron 10-Q (2026-06-25) and Nebius 6-K exhibit 99.2 (2026-08-12), verbatim.
FRACTION = ("As of May 28, 2026, the transaction price allocated to our remaining performance obligations was approximately $ 5 "
            "billion, of which $ 422 million has been recognized as contract liabilities. As of August 28, 2025, our remaining "
            "performance obligations were not material. Approximately one-third of the remaining performance obligations as of "
            "May 28, 2026 are expected to be recognized as revenue over the next twelve months.")
DURING = ("As of June 30, 2026, the amount of unsatisfied RPO was $37,490.6, of which 36% is expected to be recognized as revenue "
          "during the 24 months ending June 30, 2028, 40% between months 25 and 48, and the remainder recognized thereafter.")


class OrderTimingTests(unittest.TestCase):
    def test_percent_pair_gives_one_and_two_years(self):
        timing = ot.extract_timing(PAIR)
        self.assertEqual(timing["horizons"], {12: 77.0, 24: 91.0})
        plan = ot.weighted_schedule(timing)
        # Nothing before the first disclosed horizon: a line from zero would give 6M the same coverage as 1Y.
        self.assertEqual((plan["m6"], plan["m12"], plan["m24"]), (None, 77.0, 91.0))
        self.assertFalse(any("0–" in p for p in plan["premises"]))

    def test_segments_are_scheduled_separately_then_weighted_by_amount(self):
        plan = ot.weighted_schedule(ot.extract_timing(SEGMENTS))
        self.assertEqual((plan["m6"], plan["m12"], plan["m24"]), (None, 25.96, 45.18))  # 2Y: services 1–5 years
        self.assertIn("多段 RPO 依各段金額加權", plan["premises"])

    def test_single_window_interpolates_inside_never_beyond(self):
        plan = ot.weighted_schedule(ot.extract_timing(INITIAL))
        # CRWV: only "41% over the initial 24 months" is stated, so 6M and 1Y are not derived (they used to equal 2Y).
        self.assertEqual((plan["m6"], plan["m12"], plan["m24"]), (None, None, 41.0))
        only_year = ot.weighted_schedule(ot.extract_timing(AMOUNT))
        self.assertEqual(only_year["m12"], 63.81)
        self.assertIsNone(only_year["m24"])  # no disclosed horizon beyond 12 months

    def test_amounts_that_are_not_timing_are_ignored(self):
        self.assertIsNone(ot.extract_timing(NOT_TIMING))
        self.assertIsNone(ot.extract_timing("Revenue grew 40% over the next quarter without any backlog statement."))
        # A fraction that is a calendar period, not a share of the RPO, is not a timing.
        self.assertIsNone(ot.extract_timing("Our RPO will ramp in the second half of fiscal 2027 as capacity arrives over the next 12 months."))

    def test_word_fractions_and_during_are_timings(self):
        micron = ot.extract_timing(FRACTION)
        self.assertEqual(micron["horizons"], {12: 33.33})
        self.assertIn("one-third", micron["passages"][0])
        self.assertEqual(ot.weighted_schedule(micron)["m12"], 33.33)
        self.assertEqual(ot.extract_timing(DURING)["horizons"], {24: 36.0})

    def test_latest_periodic_filing(self):
        submissions = {"filings": {"recent": {"form": ["8-K", "10-Q", "10-K"], "filingDate": ["2026-09-01", "2026-08-01", "2026-02-01"],
                                              "accessionNumber": ["a", "0000000001-26-000002", "c"], "primaryDocument": ["x", "q.htm", "k.htm"]}}}
        filing = ot.latest_periodic_filing(submissions, "0000000001")
        self.assertEqual((filing["form"], filing["url"]), ("10-Q", "https://www.sec.gov/Archives/edgar/data/1/000000000126000002/q.htm"))


if __name__ == "__main__":
    unittest.main()
