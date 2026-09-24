from __future__ import annotations

import importlib.util
import sys
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr, ExitStack
import io
import json
import copy
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

    def test_metric_ratios_require_same_period_unit_and_filing(self):
        revenue = {**self.fact(), 'unit': 'USD', 'value': 100.0}
        net = {**revenue, 'tag': 'NetIncomeLoss', 'value': 20.0}
        self.assertEqual(MODULE.publication_aware_metrics([revenue, net])[0]['net_margin'], 0.2)
        for change in ({'start': '2026-01-01'}, {'end': '2025-12-31'}, {'unit': 'EUR'}, {'unit': None},
                       {'record_url': 'https://www.sec.gov/Archives/edgar/data/1/other.htm'},
                       {'accession_number': '0000000000-26-000002'}):
            with self.subTest(change=change):
                self.assertIsNone(MODULE.publication_aware_metrics([revenue, {**net, **change}])[0]['net_margin'])
        for metric, tag in (('gross_margin', 'GrossProfit'), ('operating_margin', 'OperatingIncomeLoss')):
            row = {**net, 'tag': tag}
            self.assertEqual(MODULE.publication_aware_metrics([revenue, row])[0][metric], 0.2)
            self.assertIsNone(MODULE.publication_aware_metrics([revenue, {**row, 'unit': 'EUR'}])[0][metric])
        # Missing unit is not an agreement just because both rows omit it.
        self.assertIsNone(MODULE.publication_aware_metrics([{**revenue, 'unit': None}, {**net, 'unit': None}])[0]['net_margin'])
        equity = {**revenue, 'tag': 'StockholdersEquity', 'start': None, 'value': 50.0}
        debt = {**equity, 'tag': 'LongTermDebt', 'value': 25.0}
        self.assertEqual(MODULE.publication_aware_metrics([equity, debt])[0]['debt_to_equity'], 0.5)
        self.assertIsNone(MODULE.publication_aware_metrics([equity, {**debt, 'end': '2025-12-31'}])[0]['debt_to_equity'])

    def test_growth_requires_comparable_adjacent_annual_periods(self):
        current = {**self.fact(), 'unit': 'USD', 'value': 120.0}
        prior = {**current, 'start': '2024-07-01', 'end': '2025-06-30', 'fiscal_year': 2025,
                 'filed': '2025-07-29', 'accession_number': '0000000000-25-000001',
                 'record_url': 'https://www.sec.gov/Archives/edgar/data/1/prior.htm', 'value': 100.0}
        self.assertAlmostEqual(MODULE.publication_aware_metrics([current, prior])[0]['revenue_growth'], 0.2)
        weekly_current = {**current, 'start': '2025-06-29', 'end': '2026-07-04'}
        weekly_prior = {**prior, 'start': '2024-06-30', 'end': '2025-06-28'}
        self.assertAlmostEqual(MODULE.publication_aware_metrics([weekly_current, weekly_prior])[0]['revenue_growth'], 0.2)
        for change in ({'unit': 'EUR'}, {'start': '2025-01-01'}, {'start': '2024-07-16'}, {'end': '2024-06-30', 'start': '2023-07-01'}, {'unit': None}):
            with self.subTest(change=change):
                self.assertIsNone(MODULE.publication_aware_metrics([current, {**prior, **change}])[0]['revenue_growth'])

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


class V213T1FractionalOrderingRegressionTests(unittest.TestCase):
    def _synthetic_cli(self, records, *, top_count=20):
        by_ticker = {r['ticker']: r for r in records}
        bundles = [({'ticker': r['ticker']}, {}, []) for r in records]
        def scorer(candidate, *args):
            return {**copy.deepcopy(by_ticker[candidate['ticker']]), 'evidence': []}
        original = {n: getattr(MODULE.engine, n) for n in ('score_candidate', 'metrics', 'validate_policy', 'sec_companyfacts')}
        import tempfile
        with tempfile.TemporaryDirectory(prefix='ii-v21-t1-') as temporary:
            outroot = Path(temporary)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with ExitStack() as stack:
                stack.enter_context(patch.object(MODULE, 'validate_v213_policy', return_value=({'top_count': top_count}, {})))
                stack.enter_context(patch.object(MODULE, 'safe_preselection_score', side_effect=scorer))
                stack.enter_context(patch.object(MODULE.engine, 'sec_headers', return_value={}))
                stack.enter_context(patch.object(MODULE.engine, 'session', return_value=object()))
                stack.enter_context(patch.object(MODULE.engine, 'source_plan', return_value={'catalog_count': 0}))
                stack.enter_context(patch.object(MODULE.engine, 'synthetic_candidates', return_value=bundles))
                stack.enter_context(patch.object(MODULE.engine, 'build_report', return_value='SYNTHETIC SORT REGRESSION ONLY\n'))
                provider_probes = []
                for n in ('discover_candidates', 'get_json', 'sec_reference', 'sec_companyfacts', 'world_bank_context'):
                    provider_probes.append(stack.enter_context(patch.object(MODULE.engine, n, side_effect=AssertionError('PROVIDER_CALL_FORBIDDEN'))))
                stack.enter_context(patch.object(sys, 'argv', ['progress', '--synthetic', '--output-root', str(outroot)]))
                stack.enter_context(redirect_stdout(stdout))
                stack.enter_context(redirect_stderr(stderr))
                rc = MODULE.main()
            paths = MODULE.engine.public_output_paths(synthetic=True, output_root=outroot)
            self.assertEqual(rc, 0)
            for probe in provider_probes:
                probe.assert_not_called()
            self.assertTrue(all(path.resolve().is_relative_to(outroot.resolve()) for path in paths.values()))
            self.assertTrue(all(getattr(MODULE.engine, n) is v for n, v in original.items()))
            actual = json.loads(paths['top20'].read_text(encoding='utf-8'))
            return actual, paths

    def test_full_precision_high_survives_cutoff_low_excluded(self) -> None:
        records = [{'ticker': f'SYNTH{i:02d}', 'serenity_score': 9.75, 'data_quality': 0.3} for i in range(19)]
        records += [{'ticker': 'SYNTHLOW', 'serenity_score': 7.0, 'data_quality': 0.65},
                    {'ticker': 'SYNTHHIGH', 'serenity_score': 7.75, 'data_quality': 0.3}]
        expected_order = sorted(records, key=lambda r: (-float(r['serenity_score']), -float(r['data_quality']), r['ticker']))[:20]
        expected_tickers = [r['ticker'] for r in expected_order]
        actual, _ = self._synthetic_cli(records)
        self.assertEqual(len(actual), 20)
        self.assertEqual([r['ticker'] for r in actual], expected_tickers)
        self.assertNotIn('SYNTHLOW', [r['ticker'] for r in actual])
        self.assertEqual([r['rank'] for r in actual], list(range(1, 21)))
        actual_rev, _ = self._synthetic_cli(list(reversed(records)))
        self.assertEqual([r['ticker'] for r in actual_rev], expected_tickers)
        self.assertNotIn('SYNTHLOW', [r['ticker'] for r in actual_rev])
        self.assertEqual([r['rank'] for r in actual_rev], list(range(1, 21)))
        for item, exp in zip(actual, expected_order):
            self.assertEqual(item['serenity_score'], exp['serenity_score'])
            self.assertEqual(item['data_quality'], exp['data_quality'])
        for item, exp in zip(actual_rev, expected_order):
            self.assertEqual(item['serenity_score'], exp['serenity_score'])
            self.assertEqual(item['data_quality'], exp['data_quality'])

    def test_equal_fractional_scores_preserve_quality_desc_ticker_asc(self) -> None:
        records = [{'ticker': f'SYNTH{i:02d}', 'serenity_score': 9.75, 'data_quality': 0.3} for i in range(17)]
        records += [{'ticker': 'AAA', 'serenity_score': 7.75, 'data_quality': 0.8},
                    {'ticker': 'BBB', 'serenity_score': 7.75, 'data_quality': 0.65},
                    {'ticker': 'ZZZ', 'serenity_score': 7.75, 'data_quality': 0.65}]
        actual, _ = self._synthetic_cli(records)
        self.assertEqual(len(actual), 20)
        self.assertEqual([r['ticker'] for r in actual[-3:]], ['AAA', 'BBB', 'ZZZ'])
        actual_rev, _ = self._synthetic_cli(list(reversed(records)))
        self.assertEqual([r['ticker'] for r in actual_rev[-3:]], ['AAA', 'BBB', 'ZZZ'])

    def test_integer_only_controls_preserve_prior_order_and_types(self) -> None:
        scores = [100 - 5 * i for i in range(19)] + [0]
        records = [{'ticker': f'SYNTH{i:02d}', 'serenity_score': scores[i],
                    'data_quality': 0 if i == 0 else 1 if i == 19 else 0.3} for i in range(20)]
        expected_order = sorted(records, key=lambda r: (-int(r['serenity_score']), -float(r['data_quality']), r['ticker']))
        expected_tickers = [r['ticker'] for r in expected_order]
        actual, _ = self._synthetic_cli(records)
        self.assertEqual(len(actual), 20)
        self.assertEqual([r['ticker'] for r in actual], expected_tickers)
        actual_rev, _ = self._synthetic_cli(list(reversed(records)))
        self.assertEqual([r['ticker'] for r in actual_rev], expected_tickers)
        for observed in (actual, actual_rev):
            self.assertEqual([item['rank'] for item in observed], list(range(1, 21)))
            for item, expected in zip(observed, expected_order):
                for field in ('serenity_score', 'data_quality'):
                    self.assertEqual(item[field], expected[field])
                    self.assertIs(type(item[field]), type(expected[field]))

    def test_validate_top20_accepts_full_precision_rejects_truncation_order(self) -> None:
        records = [{'ticker': f'SYNTH{i:02d}', 'serenity_score': 9.75, 'data_quality': 0.3} for i in range(18)]
        records += [{'ticker': 'SYNTHLOW', 'serenity_score': 7.0, 'data_quality': 0.65},
                    {'ticker': 'SYNTHHIGH', 'serenity_score': 7.75, 'data_quality': 0.3}]
        full_order = sorted(records, key=lambda r: (-float(r['serenity_score']), -float(r['data_quality']), r['ticker']))
        for rank, item in enumerate(full_order, start=1):
            item['rank'] = rank
        MODULE.engine.validate_top20(full_order)
        trunc_records = [{'ticker': f'SYNTH{i:02d}', 'serenity_score': 9.75, 'data_quality': 0.3} for i in range(18)]
        trunc_records += [{'ticker': 'SYNTHLOW', 'serenity_score': 7.0, 'data_quality': 0.65},
                          {'ticker': 'SYNTHHIGH', 'serenity_score': 7.75, 'data_quality': 0.3}]
        trunc_order = sorted(trunc_records, key=lambda r: (-int(r['serenity_score']), -float(r['data_quality']), r['ticker']))
        for rank, item in enumerate(trunc_order, start=1):
            item['rank'] = rank
        with self.assertRaises(MODULE.engine.PipelineError):
            MODULE.engine.validate_top20(trunc_order)

    def test_cli_fail_closes_invalid_score_quality_no_output(self) -> None:
        bad_values = [True, False, '9.75', 'abc', None, [9.75], {'score': 9.75}, float('nan'), float('inf'), float('-inf'), -1.0, -0.1, 101.0, 10**1000]
        for field in ('serenity_score', 'data_quality'):
            for bad in bad_values + ([1.1] if field == 'data_quality' else []):
                records = [{'ticker': f'SYNTH{i:02d}', 'serenity_score': 9.75, 'data_quality': 0.3} for i in range(19)]
                rec_bad = {'ticker': 'SYNTHBAD', 'serenity_score': 9.75, 'data_quality': 0.3}
                rec_good = {'ticker': 'SYNTHGOOD', 'serenity_score': 7.75, 'data_quality': 0.3}
                rec_bad[field] = bad
                records += [rec_bad, rec_good]
                by_ticker = {r['ticker']: r for r in records}
                bundles = [({'ticker': r['ticker']}, {}, []) for r in records]
                def scorer(candidate, *args):
                    return {**copy.deepcopy(by_ticker[candidate['ticker']]), 'evidence': []}
                original = {n: getattr(MODULE.engine, n) for n in ('score_candidate', 'metrics', 'validate_policy', 'sec_companyfacts')}
                import tempfile
                with tempfile.TemporaryDirectory(prefix='ii-v21-t1-') as temporary:
                    outroot = Path(temporary)
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with ExitStack() as stack:
                        stack.enter_context(patch.object(MODULE, 'validate_v213_policy', return_value=({'top_count': 20}, {})))
                        stack.enter_context(patch.object(MODULE, 'safe_preselection_score', side_effect=scorer))
                        stack.enter_context(patch.object(MODULE.engine, 'sec_headers', return_value={}))
                        stack.enter_context(patch.object(MODULE.engine, 'session', return_value=object()))
                        stack.enter_context(patch.object(MODULE.engine, 'source_plan', return_value={'catalog_count': 0}))
                        stack.enter_context(patch.object(MODULE.engine, 'synthetic_candidates', return_value=bundles))
                        stack.enter_context(patch.object(MODULE.engine, 'build_report', return_value='SYNTHETIC SORT REGRESSION ONLY\n'))
                        provider_probes = []
                        for n in ('discover_candidates', 'get_json', 'sec_reference', 'sec_companyfacts', 'world_bank_context'):
                            provider_probes.append(stack.enter_context(patch.object(MODULE.engine, n, side_effect=AssertionError('PROVIDER_CALL_FORBIDDEN'))))
                        stack.enter_context(patch.object(sys, 'argv', ['progress', '--synthetic', '--output-root', str(outroot)]))
                        stack.enter_context(redirect_stdout(stdout))
                        stack.enter_context(redirect_stderr(stderr))
                        rc = MODULE.main()
                    self.assertEqual(rc, 1)
                    self.assertEqual(stderr.getvalue(), 'V2.1 candidate engine failed: TOP20_SCORE_OR_QUALITY_INVALID\n')
                    for probe in provider_probes:
                        probe.assert_not_called()
                    self.assertTrue(all(getattr(MODULE.engine, n) is v for n, v in original.items()))
                    paths = MODULE.engine.public_output_paths(synthetic=True, output_root=outroot)
                    for key in ('top20', 'plan', 'metadata', 'report'):
                        self.assertFalse(paths[key].exists())


if __name__ == "__main__":
    unittest.main()
