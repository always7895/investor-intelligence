#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6b1_metric_semantic_guard as guard


class H6B1MetricSemanticGuardTests(unittest.TestCase):
    def test_crdo_rpo_binds_31_8m_not_unrelated_104367(self) -> None:
        text = (
            "Remaining Performance Obligations. The contracted but unsatisfied performance obligations as of January 31, 2026 "
            "were approximately $31.8 million which the Company expects to recognize over the next 12 months. "
            "An unrelated later table reports $104,367."
        )
        metric = guard._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        self.assertEqual(metric["amount"], "$31.8 million")

    def test_amd_rpo_binds_222m_and_next12_144m(self) -> None:
        text = (
            "Revenue allocated to remaining performance obligations includes product revenue. As of June 27, 2026, "
            "the aggregate transaction price allocated to remaining performance obligations under contracts with an original expected duration "
            "of more than one year was $222 million, of which $144 million is expected to be recognized in the next 12 months. "
            "Another note reports $946."
        )
        metric = guard._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        self.assertEqual(metric["amount"], "$222 million")
        future, classification = guard._future_from_context(metric)
        self.assertEqual(classification, "INFERENCE")
        self.assertIn("$144 million", future)

    def test_aph_acquired_backlog_amortization_is_not_current_backlog(self) -> None:
        text = (
            "During the quarter the Company incurred $23.5 of acquisition-related expense from non-cash amortization "
            "related to the value associated with acquired backlog resulting from the CommScope acquisition."
        )
        self.assertIsNone(guard._extract_strict_metric(text))

    def test_nvda_rpo_scope_and_recognition_schedule(self) -> None:
        text = (
            "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length "
            "was $3.2 billion. Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months."
        )
        metric = guard._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        self.assertEqual(metric["metric_type"], "RPO")
        future, classification = guard._future_from_context(metric)
        self.assertEqual(classification, "INFERENCE")
        self.assertIn("39%", future)

    def test_unitless_amount_is_fail_closed(self) -> None:
        self.assertIsNone(guard._extract_strict_metric("remaining performance obligations were $946"))

    def test_semantic_recent_filings_keeps_latest_periodic_forms(self) -> None:
        rows = {
            "filings": {
                "recent": {
                    "form": ["8-K", "8-K", "8-K", "8-K", "8-K", "10-Q", "10-K"],
                    "accessionNumber": ["1-1", "1-2", "1-3", "1-4", "1-5", "1-6", "1-7"],
                    "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm", "e.htm", "q.htm", "k.htm"],
                    "filingDate": ["2026-08-30", "2026-08-29", "2026-08-28", "2026-08-27", "2026-08-26", "2026-08-05", "2026-06-15"],
                }
            }
        }

        def fake_fetch(_: str) -> str:
            import json
            return json.dumps(rows)

        selected = guard.recent_filing_urls_semantic("TEST", "0000000001", fetcher=fake_fetch)
        forms = [row[2] for row in selected]
        self.assertIn("10-Q", forms)
        self.assertIn("10-K", forms)
        self.assertLessEqual(forms.count("8-K"), 3)


if __name__ == "__main__":
    unittest.main()
