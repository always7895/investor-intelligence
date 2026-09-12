from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import reconcile_v213_order_evidence as r
import v213_serenity_h6b1_metric_semantic_guard_v10 as final_guard


def documents(new=True):
    rows = [dict(rank=i + 1, ticker=f'T{i:02d}', current_orders=r.h6b.CURRENT_FALLBACK,
                 future_orders_estimate=r.h6b.FUTURE_FALLBACK, orders_as_of='', orders_confidence='UNAVAILABLE',
                 current_order_source_urls=[], future_order_source_urls=[]) for i in range(20)]
    baseline = dict(product_version='2.1.3', records=rows)
    fresh = dict(product_version='2.1.2', records=[dict(rank=i + 1, ticker='NEW' if new and i == 0 else row['ticker']) for i, row in enumerate(rows)])
    return fresh, baseline


class ReconcileOrderEvidenceTests(unittest.TestCase):
    def test_same_membership_never_fetches_sec_and_preserves_evidence(self):
        fresh, baseline = documents(False)
        untouched = copy.deepcopy(baseline)
        with patch.object(r.h6b, 'sec_ticker_map', side_effect=AssertionError('UNNEEDED_NETWORK')):
            result, receipt = r.reconcile(fresh, baseline)
        self.assertEqual(receipt['researched_new'], [])
        for old, row in zip(baseline['records'], result['records']):
            self.assertEqual(old, {k: row[k] for k in old})
        self.assertEqual(baseline, untouched)

    def test_cli_uses_final_semantic_extractor_not_first_amount_or_year_hint(self):
        for text, expected_current, expected_future in (
            ('Our revenue was $104 million while backlog increased during 2026.', r.h6b.CURRENT_FALLBACK, r.h6b.FUTURE_FALLBACK),
            ('Remaining performance obligations were $2.0 billion as of August 31, 2026.', '$2.0 billion', r.h6b.FUTURE_FALLBACK),
            ('Remaining performance obligations were $2.0 billion. We expect to recognize approximately 60% of this amount over the next 12 months.', '$2.0 billion', '60%'),
        ):
            with self.subTest(text=text), tempfile.TemporaryDirectory(prefix='ii-order-cli-') as directory:
                root = Path(directory)
                fresh, baseline = documents()
                for name, doc in (('v212.json', fresh), ('baseline.json', baseline)):
                    (root / name).write_text(json.dumps(doc), encoding='utf-8')
                fetched = []
                def raw_fetch(url):
                    fetched.append(url)
                    if url == 'https://data.sec.gov/submissions/CIK0000000001.json':
                        return json.dumps({'filings': {'recent': {'form': ['10-Q'], 'accessionNumber': ['0000000001-26-000001'],
                                                                'primaryDocument': ['main.htm'], 'filingDate': ['2026-08-31']}}})
                    if url == 'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/FilingSummary.xml':
                        return '<FilingSummary/>'
                    raise AssertionError('UNEXPECTED_FETCH')
                def text_fetch(url):
                    self.assertEqual(url, 'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/main.htm')
                    return text
                argv = ['reconcile', '--v212-report', str(root / 'v212.json'), '--baseline', str(root / 'baseline.json'),
                        '--output', str(root / 'output.json'), '--receipt', str(root / 'receipt.json')]
                with patch.object(sys, 'argv', argv), patch.object(r.h6b, 'sec_ticker_map', return_value={'NEW': '0000000001'}), \
                     patch.object(r.h6b, 'fetch_raw', side_effect=raw_fetch), patch.object(r.h6b, 'fetch_text', side_effect=text_fetch), \
                     patch.object(r.h6b, 'generic_sec_outlook', side_effect=AssertionError('RETIRED_EXTRACTOR_USED')):
                    self.assertEqual(r.main(), 0)
                result = json.loads((root / 'output.json').read_text(encoding='utf-8'))
                receipt = json.loads((root / 'receipt.json').read_text(encoding='utf-8'))
                row = result['records'][0]
                self.assertIn(expected_current, row['current_orders'])
                self.assertIn(expected_future, row['future_orders_estimate'])
                self.assertEqual(row['reconciliation_source'], 'automated_r15_quantitative_sec_delta')
                self.assertFalse(receipt['local_model_used_for_order_totals'])
                self.assertTrue(receipt['numeric_total_order_estimate_prohibited'])
                self.assertEqual(json.loads((root / 'baseline.json').read_text()), baseline)
                self.assertGreater(len(fetched), 0)

    def test_year_or_nearly_all_is_not_a_quantified_forward_amount(self):
        for future in ('官方語境延伸至2027', '幾乎全部於未來12個月認列', '未來訂單很多'):
            source = r.h6b._outlook('RPO $2 billion', future, current_urls=['https://www.sec.gov/synthetic'],
                                  future_urls=['https://www.sec.gov/synthetic'], confidence='SUPPORTED', as_of='2026-08-31')
            with patch.object(final_guard, 'generic_sec_outlook_semantic_v10', return_value=source):
                result = r.resolve_quantitative_sec_outlook('NEW', {})
            self.assertEqual(result['future_orders_estimate'], r.h6b.FUTURE_FALLBACK)
            self.assertEqual(result['future_order_source_urls'], [])
            self.assertEqual(result['current_orders_summary'], source['current_orders_summary'])
            self.assertEqual(result['claim_grounding']['future_orders_estimate'], 'UNAVAILABLE')
            self.assertEqual(source['future_orders_estimate'], future)


if __name__ == '__main__':
    unittest.main()
