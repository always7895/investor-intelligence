"""BATCH08 historical four-listing gap shapes; all amounts are synthetic, no vendor calls."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

import bottleneck_top20_v3 as engine
import test_bottleneck_top20_v3 as fixtures

LISTINGS = ('000660.KS', '005930.KS', 'NBIS', 'POET')


class YahooGapCallers(unittest.TestCase):
    def data(self, symbol, six_quarters, shares=True):
        fixture = fixtures.SharesDilutionTests()
        statement = fixture._stmt({'2025-06-30': 100, '2026-06-30': 120} if shares else None)
        if not six_quarters:
            statement = statement.iloc[:, 1:]
        history = fixture._frame(fixtures.daily('2024-01-02', '2026-09-25', lambda day: 12.0))
        currency = 'KRW' if symbol.endswith('.KS') else 'USD'
        class Ticker:
            quarterly_income_stmt = statement
            fast_info = {'currency': currency, 'marketCap': 1000}
            info = {'financialCurrency': currency, 'shortName': 'Synthetic listing'}
            def __init__(self, requested):
                if requested != symbol:
                    raise AssertionError('unexpected symbol')
            def history(self, **kwargs):
                return history
        module = types.ModuleType('yfinance')
        module.Ticker = Ticker
        with patch.dict(sys.modules, {'yfinance': module}):
            return engine.yahoo_data(symbol, as_of=datetime(2026, 9, 28, tzinfo=timezone.utc))

    def test_four_missing_comparators_remain_exact_no_record_with_other_metrics_intact(self):
        for symbol in LISTINGS:
            with self.subTest(symbol=symbol):
                row = self.data(symbol, False)
                fund = row['fundamentals']
                self.assertEqual(fund['quarter_end'], '2026-06-30')
                self.assertEqual(fund['revenue_yoy'], 2.0)
                self.assertIsNone(fund['revenue_yoy_prev'])
                self.assertIsNone(fund['revenue_yoy_prev_basis'])
                self.assertIsNone(fund['revenue_yoy_prev_source'])
                self.assertEqual(fund['revenue_yoy_prev_reason'], 'NO_RECORD')
                self.assertAlmostEqual(fund['shares_yoy'], 0.2)
                self.assertEqual(fund['shares_basis'], 'DILUTED_WEIGHTED_AVERAGE')
                self.assertIn('unofficial', fund['source'])
                self.assertIn('market', row)

    def test_six_quarter_control_uses_yahoo_not_unrelated_official_record(self):
        for symbol in LISTINGS:
            with self.subTest(symbol=symbol):
                fund = self.data(symbol, True)['fundamentals']
                self.assertEqual(fund['revenue_yoy_prev'], 4.0)
                self.assertEqual(fund['revenue_yoy_prev_basis'], 'YAHOO')
                self.assertIsNone(fund['revenue_yoy_prev_source'])
                self.assertAlmostEqual(fund['shares_yoy'], 0.2)

    def test_revenue_comparator_does_not_manufacture_missing_share_counts(self):
        for count in (False, True):
            with self.subTest(six_quarters=count):
                fund = self.data('POET', count, shares=False)['fundamentals']
                self.assertIsNone(fund['shares_yoy'])
                self.assertIsNone(fund['shares_basis'])
                self.assertEqual(fund['revenue_yoy_prev'], 4.0 if count else None)


if __name__ == '__main__':
    unittest.main()
