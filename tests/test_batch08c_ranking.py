"""Synthetic captured ranking/B7 caller gaps; no real provider bytes or publication."""
import copy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from tests import batch08c_fixtures as f
import bottleneck_top20_v3 as engine
import publish_sealed_snapshot as publisher
import test_bottleneck_top20_v3 as old
import test_batch08_yahoo as yahoo

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)
PERIODS = ('2025-03-31', '2025-06-30', '2025-09-30', '2025-12-31', '2026-03-31', '2026-06-30')


def encoded(value):
    return json.dumps(value).encode('utf-8')


def captured(symbols=('6857.T',), quarters=5, shares=None, no_shares=False, mismatch=False,
             facts=None, korea_period='2026-06-30'):
    days = old.daily('2024-01-02', '2026-09-25', lambda d: 10 + (d - datetime(2024, 1, 1).date()).days / 100)
    chart = {'chart': {'result': [{'meta': {'currency': 'USD'},
             'timestamp': [int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()) for day, _ in days],
             'indicators': {'adjclose': [{'adjclose': [value for _, value in days]}]}}]}}
    layer = {'id': 'synthetic', 'name_zh': 'synthetic', 'chain': 'chips', 'chain_rank': 1,
             'leopold_constraint': 'synthetic', 'filing_terms': [], 'capturers': [
                 {'symbol': symbol, 'role': 'synthetic', 'source_url': 'https://issuer.example/report',
                  'source_date': '2026-09'} for symbol in symbols]}
    entries = {name: None for name in ('serenity', 'leopold', 'cision', 'official_quarters', 'korea_orders')}
    entries['layers'] = encoded({'layers': [layer]})
    entries['lineage'] = (f.ROOT / 'config/listing-lineage-v1.json').read_bytes()
    entries['tickers'] = encoded({'fields': ['ticker', 'cik'], 'data': [[symbol, i + 1] for i, symbol in enumerate(symbols)]})
    entries['korea_fundamentals'] = encoded({'companies': {symbol: {
        'period_end': korea_period, 'period': '2026Q2', 'source_url': 'https://issuer.example/kr',
        'revenue': {'amount': 200, 'prior': 100, 'currency': 'KRW'}} for symbol in symbols if symbol.endswith('.KS')}})
    revenues = {day: 30e6 * (i + 1) for i, day in enumerate(PERIODS)}
    if quarters < 6:
        revenues = {day: revenues[day] for day in PERIODS[-quarters:]}
    share_values = {'2025-06-30': 100, '2026-06-30': 120} if shares is None else shares
    for i, symbol in enumerate(symbols):
        rows = []
        for kind, values in [('quarterlyTotalRevenue', revenues),
                             ('quarterlyDilutedAverageShares', {} if no_shares else share_values)]:
            rows.append({'meta': {'type': [kind]}, kind: [
                {'asOfDate': day, 'reportedValue': {'raw': amount}} for day, amount in values.items()]})
        if mismatch:
            rows[0]['timestamp'] = [int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp())]
        entries['yahoo/chart/' + symbol] = encoded(chart)
        entries['yahoo/summary/' + symbol] = encoded({'quoteSummary': {'result': [
            {'price': {'currency': 'USD', 'marketCap': {'raw': 1000}}, 'financialData': {'financialCurrency': 'USD'}}]}})
        entries['yahoo/financials/' + symbol] = encoded({'timeseries': {'result': rows}})
        entries[f'facts/CIK{i + 1:010d}'] = encoded(facts[symbol]) if facts and symbol in facts else None
    return publisher.CapturedPublicationInputs(entries)


def rank(inputs):
    with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')), \
            patch.object(engine, 'utc_now', return_value=NOW), \
            patch.object(engine, 'nasdaq_consensus', return_value=None), \
            patch.object(engine, 'yahoo_data', side_effect=AssertionError('captured branch required')):
        return engine.build(None, NOW, with_news=False, captured=inputs)


class CapturedRankingTests(unittest.TestCase):
    def test_five_quarter_minimum_through_real_ranking(self):
        for quarters in (4, 5, 6):
            row = rank(captured(quarters=quarters))['top'][0]
            if quarters == 4:
                self.assertIsNone(row['fundamentals'])
            else:
                self.assertAlmostEqual(row['fundamentals']['shares_yoy'], .2)
                self.assertEqual(row['fundamentals']['shares_basis'], 'DILUTED_WEIGHTED_AVERAGE')
                self.assertEqual(row['score_parts']['penalty'], 4)

    def test_captured_yahoo_no_record_and_period_mismatch_branches(self):
        for quarters, mismatch, basis, reason in ((6, False, 'YAHOO', None), (5, False, None, 'NO_RECORD'),
                                                (5, True, None, 'PERIOD_MISMATCH')):
            with self.subTest(quarters=quarters, mismatch=mismatch):
                fund = rank(captured(quarters=quarters, mismatch=mismatch))['top'][0]['fundamentals']
                self.assertEqual(fund['quarter_end'], '2026-06-30')
                self.assertEqual(fund['revenue_yoy'], 2)
                self.assertEqual(fund['revenue_yoy_prev'], 4 if quarters == 6 else None)
                self.assertEqual(fund['revenue_yoy_prev_basis'], basis)
                self.assertEqual(fund.get('revenue_yoy_prev_reason'), reason)
                self.assertAlmostEqual(fund['shares_yoy'], .2)
                if reason is None:
                    self.assertNotIn('revenue_yoy_prev_reason', fund)

    def test_share_window_nearest_exact_current_and_absent(self):
        cases = [({'2025-06-05': 100, '2026-06-30': 120}, None),
                 ({'2025-06-10': 80, '2025-07-15': 110, '2026-06-30': 120}, 120 / 110 - 1),
                 ({'2025-06-30': 100}, None), ({}, None)]
        for shares, expected in cases:
            with self.subTest(shares=shares):
                fund = rank(captured(shares=shares))['top'][0]['fundamentals']
                self.assertEqual(fund['revenue_yoy'], 2)
                if expected is None:
                    self.assertIsNone(fund['shares_yoy'])
                    self.assertIsNone(fund['shares_basis'])
                else:
                    self.assertAlmostEqual(fund['shares_yoy'], expected)
                    self.assertEqual(fund['shares_basis'], 'DILUTED_WEIGHTED_AVERAGE')

    def test_parity_with_uncaptured_yahoo_producer(self):
        for quarters in (5, 6):
            cap = rank(captured(symbols=('POET',), quarters=quarters))['top'][0]['fundamentals']
            with patch.object(engine, 'utc_now', return_value=NOW), \
                    patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
                live_shape = yahoo.YahooGapCallers().data('POET', quarters == 6)['fundamentals']
            for key in ('revenue_yoy', 'revenue_yoy_prev', 'revenue_yoy_prev_basis', 'revenue_yoy_prev_reason',
                        'shares_yoy', 'shares_basis', 'quarter_end'):
                self.assertEqual(cap.get(key), live_shape.get(key), key)


class ListingGapCallers(unittest.TestCase):
    def test_nbis_poet_sec_first_sparse_then_yahoo_and_sec_control(self):
        annual = {'start': '2025-01-01', 'end': '2025-12-31', 'val': 123, 'filed': '2026-03-01', 'form': '20-F'}
        sparse = {'facts': {'us-gaap': {'Revenues': {'units': {'USD': [annual]}}}}}
        poet = copy.deepcopy(sparse)
        poet['facts']['us-gaap']['Revenues']['units']['USD'].append(
            {'start': '2025-07-01', 'end': '2025-09-30', 'val': 20, 'filed': '2025-11-01', 'form': '6-K'})
        inputs = captured(symbols=('NBIS', 'POET'), facts={'NBIS': sparse, 'POET': poet})
        with patch.object(engine, 'companyfacts', wraps=engine.companyfacts) as spy:
            doc = rank(inputs)
        self.assertEqual([call.args[0] for call in spy.call_args_list], [1, 2])
        self.assertEqual({r['symbol'] for r in doc['top']}, {'NBIS', 'POET'})
        for row in doc['top']:
            self.assertIn('unofficial', row['fundamentals']['source'])
            self.assertEqual(row['fundamentals']['revenue_yoy_prev_reason'], 'NO_RECORD')
            self.assertIsNone(row['fundamentals']['revenue_yoy_prev'])
            self.assertNotIn('acceleration', row['score_parts']['capture_detail'])
        doc = rank(captured(symbols=('NBIS',), facts={'NBIS': old.FACTS}))
        self.assertNotIn('unofficial', doc['top'][0]['fundamentals']['source'])
        self.assertIsNotNone(doc['top'][0]['fundamentals']['revenue_yoy_prev'])

    def test_korean_cross_check_never_supplies_comparator_and_requires_same_period(self):
        symbols = ('000660.KS', '005930.KS')
        for period in ('2026-06-30', '2026-03-31'):
            with patch.object(engine, 'companyfacts', wraps=engine.companyfacts) as spy:
                doc = rank(captured(symbols=symbols, korea_period=period, facts={s: old.FACTS for s in symbols}))
            spy.assert_not_called()
            for row in doc['top']:
                fund = row['fundamentals']
                self.assertEqual(fund['revenue_yoy_prev_reason'], 'NO_RECORD')
                self.assertIsNone(fund['revenue_yoy_prev'])
                self.assertNotIn('acceleration', row['score_parts']['capture_detail'])
                if period == '2026-06-30':
                    self.assertEqual(fund['cross_check']['source_id'], 'COMPANY_IR_KR')
                else:
                    self.assertNotIn('cross_check', fund)


class DilutedFallbackGaps(unittest.TestCase):
    def test_latest_filed_not_last_listed_diluted_pair(self):
        for reverse in (False, True):
            facts = old.SharesDilutionTests()._facts(dei=False)
            rows = facts['facts']['us-gaap'][old.SharesDilutionTests.DILUTED]['units']['shares']
            rows.insert(0, {'start': '2025-03-30', 'end': '2025-06-28', 'val': 81e6, 'filed': '2026-08-15'})
            if reverse:
                rows.reverse()
            fund = engine.sec_fundamentals('SYN', 1, facts)
            self.assertEqual(fund['shares_basis'], 'DILUTED_WEIGHTED_AVERAGE')
            self.assertAlmostEqual(fund['shares_yoy'], 1.0)

    def test_missing_current_quarter_retains_but_refuses_ytd_and_annual(self):
        facts = old.SharesDilutionTests()._facts(dei=False)
        rows = facts['facts']['us-gaap'][old.SharesDilutionTests.DILUTED]['units']['shares']
        rows[:] = [r for r in rows if not (r['start'] == '2026-03-29' and r['end'] == '2026-06-27')]
        self.assertEqual(sum(r['end'] == '2026-06-27' for r in rows), 2)
        fund = engine.sec_fundamentals('SYN', 1, facts)
        self.assertIsNone(fund['shares_yoy'])
        self.assertIsNone(fund['shares_basis'])


if __name__ == '__main__':
    unittest.main()
