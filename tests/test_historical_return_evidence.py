from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_v212_top20_report as builder
from historical_return_evidence import calculate_return_evidence, ReturnEvidenceError


class HistoricalReturnEvidenceTests(unittest.TestCase):
    def history(self):
        return pd.DataFrame({'Close': [80.0, 100.0, 120.0]}, index=pd.to_datetime(['2024-09-09', '2026-03-09', '2026-09-09']))

    def test_actual_endpoint_cumulative_and_annualized_are_separate(self):
        evidence = builder._history_return_evidence(self.history())
        long = evidence['windows']['two_year']
        self.assertEqual(long['actual_start'], '2024-09-09')
        self.assertEqual(long['elapsed_days'], 730)
        self.assertEqual(long['cumulative_return_pct'], 50)
        self.assertAlmostEqual(long['annualized_return_pct'], ((120 / 80) ** (365.25 / 730) - 1) * 100)
        self.assertNotAlmostEqual(long['annualized_return_pct'] * 2, 50)
        self.assertAlmostEqual(evidence['windows']['six_month']['cumulative_return_pct'], 20)
        self.assertFalse(evidence['publication_eligible'])
        self.assertIsNone(evidence['currency'])

    def test_600_days_cannot_be_labelled_two_years(self):
        end = date(2026, 9, 9)
        evidence = calculate_return_evidence([(end - timedelta(days=600), 80), (date(2026, 3, 9), 100), (end, 120)])
        self.assertEqual(evidence['windows']['two_year']['status'], 'INSUFFICIENT_HISTORY')
        self.assertEqual(evidence['windows']['six_month']['status'], 'AVAILABLE')

    def test_120_days_cannot_be_labelled_six_months(self):
        end = date(2026, 9, 9)
        evidence = calculate_return_evidence([(end - timedelta(days=120), 100), (end, 120)])
        self.assertTrue(all(w['status'] == 'INSUFFICIENT_HISTORY' for w in evidence['windows'].values()))

    def test_leap_year_and_month_end_use_calendar_targets(self):
        evidence = calculate_return_evidence([(date(2022, 2, 28), 80), (date(2023, 8, 29), 100), (date(2024, 2, 29), 120)])
        self.assertEqual(evidence['windows']['two_year']['requested_start'], '2022-02-28')
        self.assertEqual(evidence['windows']['two_year']['elapsed_days'], 731)
        self.assertEqual(evidence['windows']['six_month']['requested_start'], '2023-08-29')
        evidence = calculate_return_evidence([(date(2026, 2, 28), 100), (date(2026, 8, 31), 120)])
        self.assertEqual(evidence['windows']['six_month']['requested_start'], '2026-02-28')

    def test_alignment_is_backward_bounded_and_does_not_interpolate(self):
        evidence = calculate_return_evidence([(date(2024, 9, 6), 80), (date(2024, 9, 10), 90), (date(2026, 9, 9), 120)])
        self.assertEqual(evidence['windows']['two_year']['actual_start'], '2024-09-06')
        evidence = calculate_return_evidence([(date(2024, 9, 1), 80), (date(2026, 9, 9), 120)])
        self.assertEqual(evidence['windows']['two_year']['status'], 'START_OBSERVATION_GAP')

    def test_invalid_prices_and_unordered_dates_fail_closed(self):
        for bad in (True, 0, -1, float('nan'), float('inf'), '100'):
            with self.subTest(price=bad), self.assertRaises(ReturnEvidenceError):
                calculate_return_evidence([(date(2024, 9, 9), bad), (date(2026, 9, 9), 120)])
        for history in (self.history().iloc[::-1], pd.concat([self.history(), self.history().iloc[-1:]])):
            self.assertEqual(builder._returns_from_history(history), (None, None))
        history = self.history()
        history.iloc[-1, 0] = float('nan')
        self.assertEqual(builder._returns_from_history(history), (None, None))

    def test_overflow_does_not_emit_non_finite_json(self):
        evidence = calculate_return_evidence([(date(2024, 9, 9), 1e-308), (date(2026, 9, 9), 1e308)])
        self.assertEqual(evidence['windows']['two_year']['status'], 'NON_FINITE_RESULT')
        json.dumps(evidence, allow_nan=False)

    def test_actual_cli_build_market_calculation_and_sidecar(self):
        # Stub only external inputs; exercise build, market caller, calculator,
        # legacy row projection, main and actual atomic output files together.
        rows = [{'ticker': f'T{i:02}', 'rank': i + 1} for i in range(20)]
        ticker = SimpleNamespace(history=lambda **kwargs: self.history(), info={'industry': 'Semiconductors'})
        original_build = builder.build
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            input_path = root / 'input.json'
            input_path.write_text('{}', encoding='utf-8')
            output = root / 'report.json'
            stack.enter_context(patch.dict(sys.modules, {'yfinance': SimpleNamespace(Ticker=lambda symbol: ticker)}))
            stack.enter_context(patch.object(builder.snapshot, 'validate_top20', return_value=rows))
            stack.enter_context(patch.object(builder.base, 'validate_policy', return_value=({}, {})))
            for name, result in (('sec_headers', {}), ('session', None), ('sec_reference', {})):
                stack.enter_context(patch.object(builder.base, name, return_value=result))
            stack.enter_context(patch.object(builder, 'build', side_effect=lambda **kw: original_build(top20_path=input_path, **kw)))
            stack.enter_context(patch.object(sys, 'argv', ['build', '--output', str(output)]))
            with redirect_stdout(StringIO()):
                self.assertEqual(builder.main(), 0)
            report = json.loads(output.read_text(encoding='utf-8'))
            evidence = json.loads((root / 'report.return-evidence-candidate.json').read_text(encoding='utf-8'))
            self.assertEqual(len(evidence['records']), 20)
            self.assertEqual(evidence['report_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertFalse(evidence['publication_eligible'])
            self.assertNotIn('return_evidence', report)  # not an unreviewed public payload
            for row in report['records']:
                observation = evidence['records'][row['ticker']]
                self.assertFalse(observation['publication_eligible'])
                self.assertEqual(row['long_term_return_pct'], round(observation['windows']['two_year']['annualized_return_pct'], 2))
                self.assertEqual(row['short_term_return_pct'], 20)

    def test_empty_market_history_keeps_missing_state(self):
        ticker = SimpleNamespace(history=lambda **kw: pd.DataFrame(), info={})
        sink = {}
        with patch.dict(sys.modules, {'yfinance': SimpleNamespace(Ticker=lambda symbol: ticker)}):
            result = builder._market_observation('TEST', '', evidence_sink=sink)
        self.assertEqual(result[:2], (None, None))
        self.assertEqual(sink['status'], 'NO_COMPLETE_RETURN_WINDOW')
        self.assertFalse(sink['publication_eligible'])
        self.assertTrue(all(w['status'] == 'INSUFFICIENT_HISTORY' for w in sink['windows'].values()))

    def test_overlapping_outputs_rejected_before_build_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            output.write_text('preserve', encoding='utf-8')
            with patch.object(sys, 'argv', ['build', '--output', str(output), '--return-evidence-output', str(output)]), patch.object(builder, 'build') as build, redirect_stdout(StringIO()):
                self.assertEqual(builder.main(), 1)
                build.assert_not_called()
            self.assertEqual(output.read_text(encoding='utf-8'), 'preserve')


if __name__ == '__main__':
    unittest.main()
