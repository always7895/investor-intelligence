from __future__ import annotations

import importlib.util
import sys
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr
import io
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

    def fact(self):
        return dict(record_type='company_fact', taxonomy='us-gaap', tag='Revenues', form='10-K',
                    start='2025-07-01', end='2026-06-30', filed='2026-07-29', fiscal_year=2026,
                    accession_number='0000000000-26-000001',
                    record_url='https://www.sec.gov/Archives/edgar/data/1/annual.htm', value=100.0)

    def test_actual_metric_caller_rejects_malformed_source_dates(self):
        for field in ('start', 'end', 'filed'):
            for bad in ('2026-06-30junk', '2026-06-30T00:00:00Z', ' 2026-06-30',
                        '20260630', '2026-02-30', ['2026-06-30'], True):
                fact = self.fact(); fact[field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(MODULE.engine.PipelineError):
                    MODULE.publication_aware_metrics([fact])
        fact = self.fact(); fact['end'] = None
        with self.assertRaises(MODULE.engine.PipelineError): MODULE.publication_aware_metrics([fact])

    def test_filing_date_cannot_be_borrowed_from_another_document(self):
        annual = self.fact(); annual['filed'] = ''
        quarterly = {**annual, 'form': '10-Q', 'start': '2026-04-01', 'filed': '2026-07-29',
                     'record_url': 'https://www.sec.gov/Archives/edgar/data/1/quarter.htm',
                     'accession_number': '0000000000-26-000002'}
        metrics, evidence = MODULE.publication_aware_metrics([annual, quarterly])
        self.assertEqual(metrics, MODULE.LEGACY_METRICS([annual, quarterly])[0])
        by_url = {e.url: e for e in evidence}
        self.assertEqual(by_url[annual['record_url']].publication_date, '')
        self.assertEqual(by_url[quarterly['record_url']].publication_date, '2026-07-29')

    def test_actual_cli_propagates_date_failure_and_restores_engine_hooks(self):
        fact = self.fact(); fact['filed'] = '2026-07-29suffix'
        original = MODULE.engine.metrics
        def run(*, synthetic):
            MODULE.engine.metrics([fact])
            self.fail('invalid dates reached publication')
        with patch.object(MODULE.engine, 'run', side_effect=run), patch.object(sys, 'argv', ['progress']), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(MODULE.main(), 1)
        self.assertIs(MODULE.engine.metrics, original)

    def test_conflicting_filing_dates_for_same_document_fact_fail(self):
        first = self.fact(); second = {**first, 'filed': '2026-08-01'}
        for records in ([first, second], [second, first]):
            with self.assertRaises(MODULE.engine.PipelineError): MODULE.publication_aware_metrics(records)
        self.assertEqual(MODULE.publication_aware_metrics([first]), MODULE.publication_aware_metrics([first, first]))

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
