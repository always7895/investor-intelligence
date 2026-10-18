"""BATCH08 report producer and unqualified presentation boundary, synthetic bytes only."""
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
sys.path.insert(0, str(ROOT / 'tests'))

import company_business_profile as profile
import company_deep_report as report
import test_company_business_profile as business_fixture
import test_company_deep_report as report_fixture


class ReportCallerTests(unittest.TestCase):
    def produce(self, facts, business=None):
        calls = []
        def fetch(url):
            calls.append(url)
            if url == report.FACTS_URL.format(cik='0000000001'):
                return json.dumps(facts).encode('utf-8')
            if url == report.SUBMISSIONS_URL.format(cik='0000000001'):
                return json.dumps({'name': 'Synthetic Devices', 'sic': '3674'}).encode('utf-8')
            raise AssertionError('unexpected synthetic transport request')
        with patch.object(profile, 'local_translator', side_effect=AssertionError('model must stay off')):
            document = report.build_reports({'SYN': '0000000001'}, fetch, today=report_fixture.TODAY,
                business_loader=lambda cik: business)
        self.assertEqual(len(calls), 2)
        self.assertEqual(document['failures'], {})
        self.assertFalse(document['publication_eligible'])
        return document['reports']['SYN']

    def test_full_producer_preserves_primary_quarter_and_excludes_chinese_candidate(self):
        business = copy.deepcopy(report_fixture.SYNTHETIC_FRESH_BUSINESS)
        result = self.produce(report_fixture.FACTS, business)
        self.assertEqual(result['metrics']['revenue_yoy_pct'], 25.0)
        text = '\n'.join(row['text'] for row in result['sections'])
        self.assertIn(business['sentence_en'], text)
        self.assertNotIn(business['phrase_zh'], text)
        self.assertIn('SEC EDGAR 10-K 2026-02-01', text)
        self.assertTrue(any(row['url'] == business['url'] for row in result['source_references']))

    def test_cache_only_business_neither_supplies_text_nor_source_reference(self):
        business = dict(report_fixture.SYNTHETIC_FRESH_BUSINESS, source_facts='CACHE_ONLY_NOT_FRESH')
        result = self.produce(report_fixture.FACTS, business)
        self.assertEqual(result['sections'][0]['text'], report.BUSINESS_GAP_TEXT)
        self.assertFalse(any(row['url'] == business['url'] for row in result['source_references']))

    def test_annual_ifrs_producer_does_not_invent_quarter_or_independent_source(self):
        common = {'filed': '2026-03-01', 'form': '20-F', 'fp': 'FY', 'accn': '0000000001-26-000001'}
        rows = [dict(common, start='2025-01-01', end='2025-12-31', val=1200),
                dict(common, start='2024-01-01', end='2024-12-31', val=1000)]
        facts = {'facts': {'ifrs-full': {'Revenue': {'units': {'EUR': rows}}}}}
        result = self.produce(facts)
        metrics = result['metrics']
        self.assertEqual(metrics['annual_context']['revenue_yoy_pct'], 20.0)
        self.assertEqual(metrics['annual_context']['unit'], 'EUR')
        self.assertIsNone(metrics['quarter_end'])
        self.assertIsNone(metrics['revenue'])
        text = result['sections'][1]['text']
        self.assertIn('年度／IFRS', text)
        self.assertIn('不可當作單季資料', text)
        annual = [row for row in result['source_references'] if '(ifrs-full annual' in row['source']]
        self.assertEqual(len(annual), 1)
        self.assertEqual(annual[0]['url'], result['source_references'][0]['url'])
        rows.append(dict(rows[0], val=1300))
        invalid = self.produce(facts)
        self.assertEqual(invalid['metrics']['annual_context']['status'], 'IFRS_CONFLICTING_DUPLICATE')
        self.assertNotIn('EUR', invalid['sections'][1]['text'])
        self.assertIsNone(invalid['metrics']['revenue'])

    def test_fetch_failure_isolated_without_stale_or_exception_text_fallback(self):
        def fetch(url):
            if 'CIK0000000002' in url:
                raise RuntimeError('synthetic transport diagnostic must not be copied')
            return json.dumps(report_fixture.FACTS if 'companyfacts' in url else {}).encode('utf-8')
        document = report.build_reports({'SYN': '0000000001', 'FAILED': '0000000002'}, fetch,
            today=report_fixture.TODAY)
        self.assertEqual(set(document['reports']), {'SYN'})
        self.assertEqual(document['failures'], {'FAILED': 'RuntimeError'})
        self.assertFalse(document['publication_eligible'])


class PresentationProvenanceTests(unittest.TestCase):
    def test_callback_cache_binding_and_policy_never_establish_qualified_translation(self):
        def callback(sentence):
            return business_fixture.PHRASE
        callback.model = 'synthetic-untrusted-assertion'
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            def resolve(translate):
                return profile.resolve_business_profile('0000000001', business_fixture.fake_fetch,
                    translate, cache_root=cache, now=lambda: '2026-09-25T00:00:00Z')
            first = resolve(callback)
            cached = resolve(None)
            for value in (first, cached):
                self.assertEqual(value['translation'], profile.TRANSLATION_UNVERIFIED)
                self.assertEqual(value['derived']['validation'], 'FORMAT_CHECKS_ONLY')
                self.assertEqual(value['derived']['model'], 'UNKNOWN')
                self.assertEqual(value['derived']['review'], 'NONE')
                self.assertNotIn(value['phrase_zh'], report.business_section_text(value))
            self.assertEqual(cached['derived']['method'], 'CACHED_CANDIDATE')
            self.assertEqual(first['source_evidence_sha256'], cached['source_evidence_sha256'])
            self.assertNotEqual(first['derived_evidence_sha256'], cached['derived_evidence_sha256'])
            with patch.object(profile, '_banned_phrases', return_value=(business_fixture.PHRASE,)):
                rejected = resolve(None)
            self.assertIsNone(rejected['phrase_zh'])
            self.assertIsNone(rejected['derived'])
            self.assertEqual(rejected['source_facts'], profile.FRESH_SOURCE_FACTS)
            self.assertEqual(rejected['sentence_en'], first['sentence_en'])

    def test_changed_primary_bytes_break_cached_phrase_binding_without_losing_fresh_english(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            first = profile.resolve_business_profile('0000000001', business_fixture.fake_fetch,
                lambda sentence: business_fixture.PHRASE, cache_root=cache)
            calls = []
            def fetch(url):
                calls.append(url)
                raw = business_fixture.fake_fetch(url)
                return raw + b'<!-- synthetic revision -->' if url.endswith('/k.htm') else raw
            second = profile.resolve_business_profile('0000000001', fetch, None, cache_root=cache)
            self.assertEqual(len(calls), 2)
            self.assertEqual(first['sentence_en'], second['sentence_en'])
            self.assertNotEqual(first['document_sha256'], second['document_sha256'])
            self.assertIsNone(second['phrase_zh'])
            self.assertEqual(second['source_facts'], profile.FRESH_SOURCE_FACTS)
            self.assertIn(second['sentence_en'], report.business_section_text(second))


if __name__ == '__main__':
    unittest.main()
