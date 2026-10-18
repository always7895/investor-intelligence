import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from adapters import AdapterError
from adapters.staged_public import parse_source_payload
from fetch_public_source_observations import collect

NOW = '2026-09-09T06:00:00Z'


def row(code='1234', industry='01', stamp='1150908'):
    return {'出表日期': stamp, '公司代號': code, '公司名稱': 'Synthetic Issuer',
            '產業別': industry, 'Telephone': 'NOT_PROJECTED', 'EmailAddress': 'NOT_PROJECTED'}


class IssuerDirectoryTests(unittest.TestCase):
    def parse(self, rows):
        return parse_source_payload('twse_issuer_directory', json.dumps(rows).encode(),
                                    content_type='application/json', retrieved_at=NOW)

    def test_all_industries_admitted_without_scoring_or_contact_projection(self):
        records = self.parse([row('5678', '99'), row()]).records
        self.assertEqual([r['security_code'] for r in records], ['1234', '5678'])
        self.assertEqual({r['industry_code'] for r in records}, {'01', '99'})
        for record in records:
            self.assertFalse(record['publication_eligible'])
            self.assertFalse(record['owner_watchlist_inherited'])
            self.assertEqual(record['reconciliation_state'], 'PRIMARY_ONLY')
            self.assertNotIn('score', record)
            self.assertNotIn('NOT_PROJECTED', json.dumps(record))
            self.assertIn('license_url', record)

    def test_fail_closed_dates_duplicates_and_malformed_rows(self):
        for rows in ([], [row(), row()], [row(stamp='1150910')],
                     [row(stamp='1150904')], [row(stamp='1150230')],
                     [row(), row('5678', stamp='1150907')], [row(industry='')],
                     [dict(row(), 公司代號=1234)], [None]):
            with self.subTest(rows=rows), self.assertRaises(AdapterError):
                self.parse(rows)

    def test_actual_collector_preserves_source_failure(self):
        def transport(url):
            if 'tpex' in url:
                raise OSError('synthetic failure not retained')
            # Bind this test's date to the collector's current retrieval clock.
            from datetime import datetime, timedelta, timezone
            d = datetime.now(timezone(timedelta(hours=8))).date()
            return json.dumps([row(stamp=f'{d.year-1911:03}{d.month:02}{d.day:02}')]).encode()
        result = collect(['twse_issuer_directory', 'tpex_issuer_directory'], transport=transport)
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(len(result['items']), 1)
        self.assertFalse(result['publication_eligible'])
        self.assertEqual(result['sources'][1]['status'], 'FAILED')
        self.assertNotIn('synthetic failure', json.dumps(result))

    def test_tpex_venue_identity_is_not_twse_corroboration(self):
        raw = [{'Date': '1150908', 'SecuritiesCompanyCode': '1234',
                'CompanyName': 'Synthetic Issuer', 'SecuritiesIndustryCode': '02'}]
        record = parse_source_payload('tpex_issuer_directory', json.dumps(raw).encode(),
                    content_type='application/json', retrieved_at=NOW).records[0]
        self.assertEqual(record['venue'], 'TPEX')
        self.assertEqual(record['industry_code_namespace'], 'TPEX')
        self.assertEqual(record['dataset_url'], 'https://data.gov.tw/dataset/25036')


if __name__ == '__main__':
    unittest.main()
