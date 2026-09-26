"""Synthetic daily-options tests; network/LINE/Production are never exercised."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from adapters import AdapterError
from adapters.staged_public import parse_source_payload
import fetch_public_source_observations as collector
from public_options_provider_gate import audit_public_options_providers

SOURCE = 'taifex_options_eod'
RETRIEVED = '2026-09-10T00:00:00+00:00'


def fixture(**changes):
    row = {'Date': '20260909', 'Contract': 'TXO', 'ContractMonth(Week)': '202610W2',
           'StrikePrice': '20000', 'CallPut': '買權', 'Open': '100', 'High': '110', 'Low': '90',
           'Close': '105', 'Volume': '12', 'SettlementPrice': '104', 'OpenInterest': '50',
           'BestBid': '104', 'BestAsk': '106', 'HistoricalHigh': '200', 'HistoricalLow': '20',
           'TradingHalt': '', 'TradingSession': '一般'}
    return {**row, **changes}


def parse(rows, retrieved=RETRIEVED):
    return parse_source_payload(SOURCE, json.dumps(rows, ensure_ascii=False).encode(),
                                content_type='application/json', retrieved_at=retrieved)


class TaifexOptionsEodTests(unittest.TestCase):
    def test_actual_collector_accepts_explicit_local_eod_source(self):
        day = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=1)).strftime('%Y%m%d')
        result = collector.collect([SOURCE], transport=lambda url: json.dumps([fixture(Date=day)]).encode())
        self.assertEqual(result['status'], 'OK')
        self.assertFalse(result['publication_eligible'])
        self.assertEqual(result['sources'][0]['record_count'], 1)
        self.assertEqual(result['items'][0]['source_url'], 'https://openapi.taifex.com.tw/v1/DailyMarketReportOpt')
        self.assertEqual(len(result['items'][0]['content_sha256']), 64)

    def test_contract_identity_units_and_untimed_eod_quotes(self):
        row = parse([fixture()]).records[0]
        self.assertEqual(row['venue'], 'TAIFEX')
        self.assertEqual(row['contract_code'], 'TXO')
        self.assertEqual(row['contract_month_week'], '202610W2')
        self.assertEqual(row['option_type'], 'call')
        self.assertEqual(row['strike'], 20000)
        self.assertEqual(row['trade_date'], '2026-09-09')
        self.assertEqual(row['trading_session'], 'REGULAR')
        self.assertEqual(row['volume_contracts'], 12)
        self.assertEqual(row['last_best_bid'], 104)
        self.assertEqual(row['last_best_ask'], 106)
        self.assertEqual(row['quote_status'], 'UNTIMED_EOD_OBSERVATION')
        for key in ('quote_time', 'currency', 'contract_multiplier', 'expiration_date', 'actual_dte', 'delta'):
            self.assertIsNone(row[key])
        for key in ('publication_eligible', 'line_quote_eligible', 'executable_quote'):
            self.assertIs(row[key], False)
        self.assertNotIn('midpoint', row)
        self.assertNotIn('recommended_candidates', row)

    def test_missing_and_crossed_observations_are_not_current_quotes(self):
        missing = parse([fixture(Open='-', High='-', Low='-', Close='-', BestBid='-', BestAsk='0', OpenInterest='-')]).records[0]
        self.assertIsNone(missing['last_trade_price'])
        self.assertIsNone(missing['last_best_bid'])
        self.assertIsNone(missing['open_interest_contracts'])
        self.assertEqual(missing['quote_status'], 'NO_POSITIVE_TWO_SIDED_OBSERVATION')
        crossed = parse([fixture(BestBid='110', BestAsk='90')]).records[0]
        self.assertEqual(crossed['quote_status'], 'CROSSED_EOD_OBSERVATION')
        self.assertFalse(crossed['executable_quote'])

    def test_sessions_and_expiry_series_are_not_merged(self):
        rows = parse([fixture(), fixture(TradingSession='盤後', OpenInterest='-', CallPut='賣權'),
                      fixture(**{'ContractMonth(Week)': '202610F2'})]).records
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]['trading_session'], 'AFTER_HOURS')
        self.assertEqual(rows[1]['option_type'], 'put')
        self.assertIsNone(rows[1]['open_interest_contracts'])
        self.assertTrue(all(r['open_interest_not_additive_across_sessions'] for r in rows))

    def test_duplicate_normalized_identity_rejects_whole_batch(self):
        with self.assertRaisesRegex(AdapterError, 'TAIFEX_EOD_DUPLICATE_CONTRACT_SESSION'):
            parse([fixture(), fixture(StrikePrice='20000.0')])

    def test_date_shape_future_stale_and_mixed_dates_fail_closed(self):
        for day in ('20260909junk', '20260230', '20260911', '20260901'):
            with self.subTest(day=day), self.assertRaises(AdapterError): parse([fixture(Date=day)])
        with self.assertRaisesRegex(AdapterError, 'TAIFEX_EOD_MIXED_DATES'):
            parse([fixture(), fixture(Date='20260908')])

    def test_malformed_numbers_identity_and_schema_fail_closed(self):
        cases = [('StrikePrice', '0'), ('StrikePrice', 'NaN'), ('Volume', '-1'), ('Volume', '1.5'),
                 ('OpenInterest', True), ('BestBid', 'Infinity'), ('Close', '999'),
                 ('Contract', '../../private'), ('ContractMonth(Week)', '202613'), ('ContractMonth(Week)', '202610W9'),
                 ('CallPut', 'unknown'), ('TradingSession', 'unknown'), ('TradingHalt', 'unknown')]
        for key, value in cases:
            with self.subTest(key=key, value=value), self.assertRaises(AdapterError): parse([fixture(**{key: value})])
        for row in (fixture(account='SYNTHETIC_PRIVATE_FIELD'), {k:v for k,v in fixture().items() if k != 'OpenInterest'}):
            with self.assertRaises(AdapterError): parse([row])
        with self.assertRaises(AdapterError): parse([])
        with self.assertRaises(AdapterError): parse([fixture(), fixture(Close='malformed')])

    def test_attribution_is_preserved_in_closed_projection(self):
        row = parse([fixture()]).records[0]
        attribution = row['attribution']
        self.assertEqual(attribution['provider'], '臺灣期貨交易所')
        self.assertEqual(attribution['dataset_url'], 'https://data.gov.tw/dataset/11320')
        self.assertEqual(attribution['license_url'], 'https://data.gov.tw/license')
        self.assertEqual(attribution['data_date'], row['trade_date'])
        self.assertEqual(attribution['source_year'], 2026)
        self.assertIsNone(attribution['dataset_version'])
        self.assertIn('未獲', attribution['notice'])

    def test_actual_cli_uses_explicit_source_without_network_or_disk(self):
        original = collector.collect
        day = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=1)).strftime('%Y%m%d')
        calls = []
        def fake(url):
            calls.append(url)
            return json.dumps([fixture(Date=day)]).encode()
        with patch.object(collector, 'collect', side_effect=lambda sources: original(sources, transport=fake)), \
             patch.object(collector, 'atomic_write_json') as write, \
             patch.object(sys, 'argv', ['collector', '--fetch', '--source', SOURCE, '--output', 'synthetic-local.json']), \
             redirect_stdout(StringIO()):
            self.assertEqual(collector.main(), 0)
        self.assertEqual(calls, ['https://openapi.taifex.com.tw/v1/DailyMarketReportOpt'])
        self.assertFalse(write.call_args.args[1]['items'][0]['line_quote_eligible'])

    def test_existing_default_collection_does_not_implicitly_add_options(self):
        self.assertNotIn(SOURCE, collector.DEFAULT_SOURCES)
        result = {'status': 'OK', 'sources': [], 'items': []}
        with patch.object(collector, 'collect', return_value=result) as collect, \
             patch.object(collector, 'atomic_write_json'), \
             patch.object(sys, 'argv', ['collector', '--fetch', '--output', 'synthetic-local.json']), \
             redirect_stdout(StringIO()):
            self.assertEqual(collector.main(), 0)
        self.assertNotIn(SOURCE, collect.call_args.args[0])

    def test_bad_payload_and_transport_failure_remain_failed_not_carried_forward(self):
        for transport in (lambda _: b'[]', lambda _: b'[{"Date":NaN}]'):
            result = collector.collect([SOURCE], transport=transport)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['items'], [])
            self.assertEqual(result['sources'][0]['failure_kind'], 'INVALID_PAYLOAD')
        def failed(_): raise RuntimeError('SYNTHETIC_ERROR_NOT_FOR_OUTPUT')
        result = collector.collect([SOURCE], transport=failed)
        self.assertEqual(result['status'], 'FAILED')
        self.assertNotIn('SYNTHETIC_ERROR', json.dumps(result))

    def test_candidate_status_and_paid_fallback_cannot_bypass_admission(self):
        import public_options_provider_gate as gate
        real_object = gate._object
        original = real_object(ROOT / 'config/public-options-provider-candidates.json')
        for paid in (False, True):
            document = json.loads(json.dumps(original))
            candidate = next(p for p in document['providers'] if p['id'] == 'taifex_public_options')
            self.assertEqual(candidate['adapter_status'], 'candidate_implemented')
            candidate['runtime_enabled'] = candidate['line_quote_eligible'] = True
            document['paid_fallback'] = paid
            with patch.object(gate, '_object', side_effect=lambda path: document if path.name == 'public-options-provider-candidates.json' else real_object(path)):
                findings, summary = gate.audit_public_options_providers(ROOT)
            self.assertTrue(any('lacks reviewed adapter' in value for value in findings))
            self.assertEqual(summary['fully_eligible_count'], 0)
            if paid: self.assertTrue(any('paid_fallback' in value for value in findings))

    def test_candidate_does_not_enable_runtime_or_line_quotes(self):
        findings, summary = audit_public_options_providers(ROOT)
        self.assertEqual(findings, [])
        self.assertEqual(summary['fully_eligible_count'], 0)
        self.assertEqual(summary['runtime_enabled_count'], 0)
        self.assertEqual(summary['line_quote_eligible_count'], 0)
        self.assertFalse(summary['production_provider_selected'])
        from adapters import ADAPTERS
        self.assertNotIn(SOURCE, ADAPTERS)


if __name__ == '__main__':
    unittest.main()
