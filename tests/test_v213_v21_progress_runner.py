from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "v213_v21_progress_runner",
    SCRIPTS / "v213_v21_progress_runner.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class V213SafePreselectionWrapperTests(unittest.TestCase):
    def test_monkeypatched_engine_calls_original_scorer_without_recursion(self) -> None:
        policy, _activation = MODULE.validate_v213_policy()
        candidate, metrics, evidence = MODULE.engine.synthetic_candidates()[0]
        original_score = MODULE.engine.score_candidate
        try:
            MODULE.engine.score_candidate = MODULE.safe_preselection_score
            result = MODULE.engine.score_candidate(candidate, metrics, evidence, policy)
        finally:
            MODULE.engine.score_candidate = original_score

        self.assertEqual(result["scoring_version"], MODULE.PRESELECTION_VERSION)
        self.assertEqual(result["serenity_factors"]["demand_wave"], 0.0)
        self.assertEqual(result["serenity_factors"]["chokepoint"], 0.0)
        self.assertEqual(result["serenity_factors"]["pricing_power"], 0.0)
        self.assertEqual(result["serenity_factors"]["replacement_friction"], 0.0)
        self.assertLessEqual(result["serenity_factors"]["valuation_expectations"], 3.75)

    def test_sec_evidence_uses_filing_date_not_period_end_or_retrieval_time(self) -> None:
        records = [
            {
                "record_type": "company_fact",
                "taxonomy": "us-gaap",
                "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "form": "10-Q",
                "start": "2026-04-01",
                "end": "2026-06-30",
                "filed": "2026-07-29",
                "retrieved_at": "2026-09-03T10:00:00Z",
                "accession_number": "0000000000-26-000001",
                "record_url": "https://www.sec.gov/Archives/edgar/data/1/filing.htm",
                "value": 100.0,
            }
        ]
        _metrics, evidence = MODULE.publication_aware_metrics(records)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].as_of, "2026-07-29")
        self.assertEqual(evidence[0].publication_date, "2026-07-29")
        self.assertEqual(evidence[0].period_end, "2026-06-30")
        self.assertNotEqual(evidence[0].as_of, "2026-09-03")

    def test_missing_filing_date_fails_closed_to_period_end(self) -> None:
        records = [
            {
                "record_type": "company_fact",
                "taxonomy": "us-gaap",
                "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "form": "10-Q",
                "start": "2025-10-01",
                "end": "2025-12-31",
                "filed": "",
                "retrieved_at": "2026-09-03T10:00:00Z",
                "accession_number": "0000000000-26-000002",
                "record_url": "https://www.sec.gov/Archives/edgar/data/1/stale.htm",
                "value": 90.0,
            }
        ]
        _metrics, evidence = MODULE.publication_aware_metrics(records)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].as_of, "2025-12-31")
        self.assertEqual(evidence[0].publication_date, "")
        self.assertEqual(evidence[0].period_end, "2025-12-31")


if __name__ == "__main__":
    unittest.main()
