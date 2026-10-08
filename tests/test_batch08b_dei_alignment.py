"""Revenue-quarter aligned SEC cover counts through fundamentals and ranking."""
import copy
import unittest
from datetime import date, timedelta

from tests import batch08b_fixtures as f

REGRESSIONS = {
    "stale": ("DILUTED_WEIGHTED_AVERAGE", 162/80-1),
    "late": ("DILUTED_WEIGHTED_AVERAGE", 162/80-1),
    "before": ("DILUTED_WEIGHTED_AVERAGE", 162/80-1),
    "earliest": ("OUTSTANDING", 0.2),
    "late_ignored": ("OUTSTANDING", 0.2),
    "nearest": ("OUTSTANDING", 0.2),
}


class DeiAlignmentTests(unittest.TestCase):
    def assert_callers(self, facts, expected):
        fund = f.engine.sec_fundamentals("SYN", 1, facts)
        self.assertIsNotNone(fund)
        self.assertEqual(fund["shares_basis"], "OUTSTANDING")
        self.assertIsNotNone(fund.get('shares_yoy'))
        self.assertAlmostEqual(fund["shares_yoy"], expected)
        self.assertEqual(f.rank(facts)["top"][0]["fundamentals"], fund)

    def test_amendments_win_current_and_prior_regardless_of_listing_order(self):
        for reverse in (False, True):
            facts = f.share_facts()
            rows = facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
            originals = copy.deepcopy(rows)
            for row in rows:
                row.update(filed="2026-08-01", form="10-Q")
            rows.extend([{**originals[0], "filed": "2026-08-10", "form": "10-Q/A", "val": 80},
                         {**originals[-1], "filed": "2026-08-10", "form": "10-Q/A", "val": 160}])
            if reverse:
                rows.reverse()
            with self.subTest(reverse=reverse):
                self.assert_callers(facts, 1.0)

    def test_dei_latest_filed_is_form_agnostic_on_current_and_prior(self):
        for form in ('10-K', '20-F', '6-K', '8-K', '', None):
            for reverse in (False, True):
                with self.subTest(form=form, reverse=reverse):
                    facts = f.share_facts()
                    rows = facts['facts']['dei']['EntityCommonStockSharesOutstanding']['units']['shares']
                    originals = copy.deepcopy(rows)
                    for row in rows:
                        row.update(filed='2026-08-01', form='10-Q')
                    latest = [{**originals[0], 'filed': '2026-08-10', 'val': 80},
                              {**originals[-1], 'filed': '2026-08-10', 'val': 160}]
                    for row in latest:
                        row.pop('form', None)
                        if form is not None:
                            row['form'] = form
                    rows.extend(latest)
                    if reverse:
                        rows.reverse()
                    self.assert_callers(facts, 1.0)

    def test_equal_filed_later_listed_wins_on_both_sides(self):
        facts = f.share_facts()
        rows = facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
        for row in rows:
            row["filed"] = "2026-08-10"
        rows.extend([{**rows[0], "val": 80}, {**rows[-1], "val": 160}])
        self.assert_callers(facts, 1.0)

    def test_malformed_and_nonstring_ends_are_skipped_before_sorting(self):
        for end in (None, 17, True, {}, [], "bad", "2026-02-30"):
            with self.subTest(end=end):
                facts = f.share_facts()
                rows = facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
                rows.extend([{"end": end, "val": 500}, {"val": 500}, {"end": "2026-08-01", "val": None}])
                self.assert_callers(facts, .2)

    def test_three_way_nearest_is_neither_first_nor_last(self):
        facts = f.share_facts()
        rows = facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
        end = date.fromisoformat(rows[-1]["end"])
        rows.extend([{"end": (end - timedelta(days=410)).isoformat(), "val": 80},
                     {"end": (end - timedelta(days=320)).isoformat(), "val": 110}])
        self.assert_callers(facts, .2)

    def test_equal_distance_prior_tie_chooses_earlier_end(self):
        facts = f.share_facts()
        rows = facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
        end = date.fromisoformat(rows[-1]["end"])
        rows[:] = [rows[-1], {"end": (end - timedelta(days=355)).isoformat(), "val": 110},
                   {"end": (end - timedelta(days=375)).isoformat(), "val": 100}]
        self.assert_callers(facts, .2)

    def test_nearest_prior_centre_is_365_not_366(self):
        facts = f.share_facts()
        rows = facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
        end = date.fromisoformat(rows[-1]["end"])
        rows[:] = [rows[-1], {"end": (end - timedelta(days=364)).isoformat(), "val": 100},
                   {"end": (end - timedelta(days=367)).isoformat(), "val": 80}]
        self.assert_callers(facts, .2)

    def test_first_valid_unit_wins(self):
        facts = f.share_facts()
        units = facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]
        other = copy.deepcopy(units["shares"])
        other[-1]["val"] = 150
        units["other"] = other
        self.assert_callers(facts, .2)

    def test_current_window_inclusive_and_original_anchor(self):
        for case in ("lower", "upper", "anchor"):
            with self.subTest(case=case):
                fund = f.engine.sec_fundamentals("SYN", 1, f.share_facts(case))
                self.assertEqual(fund["shares_basis"], "OUTSTANDING")
                self.assertIsNotNone(fund.get('shares_yoy'))
                self.assertAlmostEqual(fund["shares_yoy"], 0.2)

    def test_existing_prior_window_and_invalid_value_fallback(self):
        for case in ("prior_lower", "prior_upper", "prior_outside_lower", "prior_outside_upper", "invalid"):
            with self.subTest(case=case):
                valid = case in {"prior_lower", "prior_upper"}
                fund = f.engine.sec_fundamentals("SYN", 1, f.share_facts(case))
                self.assertEqual(fund["shares_basis"], "OUTSTANDING" if valid else "DILUTED_WEIGHTED_AVERAGE")
                self.assertIsNotNone(fund.get('shares_yoy'))
                self.assertAlmostEqual(fund["shares_yoy"], 0.2 if valid else 162/80-1)


def regression(case):
    def test(self):
        facts = f.share_facts(case)
        basis, yoy = REGRESSIONS[case]
        fund = f.engine.sec_fundamentals("SYN", 1, facts)
        self.assertEqual(fund["shares_basis"], basis)
        self.assertIsNotNone(fund.get('shares_yoy'))
        self.assertAlmostEqual(fund["shares_yoy"], yoy)
        ranked = f.rank(facts)["top"][0]
        self.assertEqual(ranked["fundamentals"], fund)
        self.assertEqual(ranked["score_parts"]["penalty"], 4)
        # Score changes are governed by the existing penalty, not a new weight.
        anchor = f.rank(f.share_facts("anchor"))["top"][0]
        self.assertEqual(ranked["score"], anchor["score"])
    return test


for _case in REGRESSIONS:
    setattr(DeiAlignmentTests, "test_regression_" + _case, regression(_case))


if __name__ == "__main__":
    unittest.main()
