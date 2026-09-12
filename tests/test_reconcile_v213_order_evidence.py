from __future__ import annotations
import copy
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
                self.assertEqual(row['reconciliation_source'], 'automated_r15_source_clock_sec_delta')
                if expected_current != r.h6b.CURRENT_FALLBACK:
                    self.assertIsNotNone(r.utc_time(row['retrieved_at']))
                else:
                    self.assertIsNone(row['retrieved_at'])
                self.assertFalse(receipt['market_clock_inherited_for_orders'])
                self.assertFalse(receipt['publication_qualified'])
                self.assertFalse(receipt['local_model_used_for_order_totals'])
                self.assertTrue(receipt['numeric_total_order_estimate_prohibited'])
                self.assertEqual(json.loads((root / 'baseline.json').read_text()), baseline)
                self.assertGreater(len(fetched), 0)

    def test_new_member_never_inherits_company_clock_and_keeps_explicit_order_clock(self):
        for clock in (None, '2026-01-01T00:00:00Z'):
            fresh, baseline = documents()
            fresh['records'][0]['retrieved_at'] = '2026-09-12T00:00:00Z'
            outlook = r.h6b._outlook('RPO $2 billion', r.h6b.FUTURE_FALLBACK,
                current_urls=['https://www.sec.gov/synthetic'], confidence='EVIDENCE_BOUND', as_of='2026-07-01')
            if clock is not None: outlook['retrieved_at'] = clock
            result, _ = r.reconcile(fresh, baseline, resolver=lambda _: outlook)
            self.assertEqual(result['records'][0]['retrieved_at'], clock)

    def test_known_unbound_producers_cannot_recycle_their_market_clock(self):
        for producer in r.UNBOUND_CLOCK_PRODUCERS:
            fresh, baseline = documents(False)
            baseline['accepted_from'] = producer
            baseline['records'][0]['retrieved_at'] = '2026-09-12T00:00:00Z'
            original = copy.deepcopy(baseline)
            result, _ = r.reconcile(fresh, baseline)
            self.assertIsNone(result['records'][0]['retrieved_at'])
            self.assertEqual(baseline, original)

    def test_only_successful_cited_source_reads_supply_the_oldest_clock(self):
        url = 'https://www.sec.gov/synthetic'
        missing = 'https://www.sec.gov/not-read'
        failed = 'https://www.sec.gov/failed'
        def transport(target):
            if target == failed: raise r.h6b.H6BError('SYNTHETIC_FETCH_FAILED')
            return 'SYNTHETIC_VISIBLE_TEXT'
        for cited in ([url], [url, missing], [failed]):
            def extractor(*args, **kwargs):
                # Equal seconds with/without a fraction must sort as time, not
                # strings. Repeated retrieval must not advance the first clock.
                kwargs['text_fetcher'](url)
                kwargs['text_fetcher'](url)
                try: kwargs['text_fetcher'](failed)
                except r.h6b.H6BError: pass
                return r.h6b._outlook('RPO $2 billion', r.h6b.FUTURE_FALLBACK,
                    current_urls=cited, confidence='EVIDENCE_BOUND', as_of='2026-07-01')
            with patch.object(final_guard, 'generic_sec_outlook_semantic_v10', side_effect=extractor), \
                 patch.object(r.h6b, 'fetch_text', side_effect=transport), \
                 patch.object(r, '_utc_now', side_effect=['2026-09-12T00:00:00Z', '2026-09-12T00:00:00.100Z', '2026-09-12T00:00:01Z']):
                result = r.resolve_quantitative_sec_outlook('NEW', {})
            self.assertEqual(result['retrieved_at'], '2026-09-12T00:00:00Z' if cited == [url] else None)

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
