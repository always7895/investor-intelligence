"""MACRO-COUNT-01 Python producer parity with the Worker overview validator (synthetic candidates only).

qualified_count is the visible validated admitted count (at most five ranked cards), never the upstream aggregate;
duplicate or blank industry ids anywhere in the qualified pool and a visible card that is not ADMITTED at its exact
1-based rank refuse before anything is published. No network, subprocess or file write.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_v213_macro_industry_research as mb  # noqa: E402


def six_qualified():
    candidates = []
    for i in range(6):
        c = copy.deepcopy(mb.SYNTHETIC_FIVE_QUALIFIED[0])
        c["industry_id"] = f"ind_{i}"
        c["scores"] = {"demand": 10 + i * 2, "chokepoint": 10, "pricing": 10, "value_chain": 5, "catalysts": 5}
        candidates.append(c)
    qualified, _ = mb.evaluate_candidates(candidates)
    return qualified


def refusal(qualified):
    try:
        mb.build_macro_overview_output(qualified, [])
    except ValueError as error:
        return str(error)
    return None


class VisibleCountTests(unittest.TestCase):
    def test_more_than_five_admitted_publishes_the_visible_count(self):
        qualified = six_qualified()
        missing = {"industry_id": "missing_growth_industry", "industry_name": "無公開成長率產業", "growth": None,
                   "scores": {"demand": 20, "chokepoint": 20}}
        _, disqualified = mb.evaluate_candidates([missing])
        deep = {row["industry_id"]: {"industry_id": row["industry_id"]} for row in qualified}
        report = mb.build_macro_overview_output(qualified, disqualified, deep_analyses=deep)
        visible = ["ind_5", "ind_4", "ind_3", "ind_2", "ind_1"]
        self.assertEqual((report["qualified_count"], report["shortfall"], report["status"], report["candidate_pool_size"]),
                         (5, 0, "ADMITTED_TOP5", 7))
        self.assertEqual([row["industry_id"] for row in report["industries"]], visible)
        self.assertEqual(list(report["deep_analyses"]), visible)
        self.assertNotIn("shortfall_report", report)

    def test_duplicate_or_blank_ids_anywhere_in_the_pool_refuse(self):
        rows = [("duplicate-beyond-visible", 5, "ind_5 ", "OVERVIEW_INDUSTRY_ID_DUPLICATE"),
                ("duplicate-visible", 1, "ind_5", "OVERVIEW_INDUSTRY_ID_DUPLICATE"),
                ("blank", 2, "  ", "OVERVIEW_INDUSTRY_ID_INVALID"),
                ("missing", 3, None, "OVERVIEW_INDUSTRY_ID_INVALID"),
                ("non-string", 4, 7, "OVERVIEW_INDUSTRY_ID_INVALID")]
        for name, index, value, code in rows:
            with self.subTest(row=name):
                qualified = six_qualified()
                qualified[index]["industry_id"] = value
                self.assertEqual(refusal(qualified), code)
        qualified = six_qualified()
        qualified[3] = "not-a-row"
        self.assertEqual(refusal(qualified), "OVERVIEW_INDUSTRY_ID_INVALID")

    def test_visible_cards_must_be_admitted_at_their_exact_rank(self):
        def swap(q):
            q[0]["rank"], q[1]["rank"] = q[1]["rank"], q[0]["rank"]
        rows = [("swapped", swap), ("boolean", lambda q: q[0].__setitem__("rank", True)),
                ("float", lambda q: q[2].__setitem__("rank", 3.0)), ("null", lambda q: q[4].__setitem__("rank", None)),
                ("not-admitted", lambda q: q[1].__setitem__("admission_status", "NOT_PUBLICATION_QUALIFIED"))]
        for name, change in rows:
            with self.subTest(row=name):
                qualified = six_qualified()
                change(qualified)
                self.assertEqual(refusal(qualified), "OVERVIEW_VISIBLE_RANK_INVALID")
        qualified = six_qualified()
        qualified[5]["rank"] = 99  # beyond the visible five: never published, so never read
        self.assertIsNone(refusal(qualified))

    def test_shortfall_and_knowledge_carrier_keep_their_order(self):
        qualified = six_qualified()[:1]
        rotation = {"method": "m", "as_of": "2026-09-25", "quarter": "2026 Q2", "receipts": [],
                    "phase_knowledge_withheld": {"affected_industries": 0, "signals": 0}}
        report = mb.build_macro_overview_output(qualified, [], rotation=rotation)
        self.assertEqual((report["qualified_count"], report["shortfall"], report["status"]), (1, 4, "SHORTFALL_NOT_QUALIFIED"))
        self.assertEqual(list(report)[-2:], ["shortfall_report", "phase_knowledge_withheld"])
        self.assertEqual(mb.build_macro_overview_output([], [])["qualified_count"], 0)


if __name__ == "__main__":
    unittest.main()
