"""G4a pure seams only; synthetic NBIS evidence is not admission or qualification."""
from collections import Counter
import copy
import unittest

from tests import nbis_synthetic_sources as f


class InstalledDefaults(unittest.TestCase):
    def test_defaults(self):
        data = f.tracked()
        self.assertEqual(data["enabled_symbols"], ["NVDA", "MU"])
        self.assertEqual(set(f.verify.validate_profiles(data)), {"NVDA", "MU"})
        self.assertIsNone(f.verify.validate_nbis_profile(f.profile()))

    def test_profile_strictness(self):
        rows = [(('cik',), 1513846, 'NBIS_PROFILE_IDENTITY'),
                (('release', 'form'), '8-K', 'NBIS_RELEASE_KEYS'),
                (('guidance', 'scope_rule'), 'X', 'NBIS_GUIDANCE_KEYS'),
                (('actuals', 'precision'), '1', 'NBIS_ACTUALS_KEYS'),
                (('calendar', 'rule'), 'X', 'NBIS_CALENDAR_KEYS'),
                (('ir_host',), 'evil.example.sec.gov', 'NBIS_PAGE_POLICY'),
                (('ir_page_pattern',), '^https://wrong\\.example/[a-z]+$', 'NBIS_PAGE_POLICY'),
                (('wire_page_pattern',), '^https://www\\.nasdaq\\.com/press-release/[a-z]+', 'NBIS_PAGE_POLICY')]
        for keys, value, code in rows:
            with self.subTest(keys=keys, code=code):
                p = f.profile()
                target = p if len(keys) == 1 else p[keys[0]]
                target[keys[-1]] = value
                with self.assertRaises(ValueError) as caught:
                    f.verify.validate_nbis_profile(p)
                self.assertEqual(str(caught.exception), code)


class SyntheticPositives(unittest.TestCase):
    def assert_verified(self, result):
        self.assertEqual(result['outcome'], 'VERIFIED', (result['reason'], result['detail']))
        self.assertIsNone(result['reason'])
        self.assertEqual(result['detail'], '')
        self.assertIsNotNone(result['record'])
        self.assertIsInstance(result['record'], dict)

    def test_z_planner_builds_complete_event(self):
        with f.Scenario() as s:
            f.guidance.validate_issuer_record(s.baseline, 'NBIS')
            self.assertEqual(s.baseline['documents'][0]['url'], f.BASELINE_REFERENCE_URL)
            self.assertEqual(f.updater.reference_accession(s.baseline), '0000000000-31-000305')
            s.plan()
            self.assertEqual(s.transport.requests, s.expected_requests())
            self.assertEqual([p['accession'] for p in s.event['packages']],
                             ['0000000000-32-000105', '0000000000-31-000305',
                              '0000000000-31-000205', '0000000000-31-000105'])
            self.assertEqual(s.event['channel_history'], [{
                'accession': '0000000000-31-000305', 'channel': 'WIRE_PRESS_RELEASES',
                'item': {'id': s.packages[1].wire, 'title': 'Nebius reports third quarter 2031 financial results',
                         'date': '2031-11-13'}, 'capture': 'nbis:0000000000-31-000305:wire_copy'}])
            self.assertEqual(len(s.captures), 20)
            self.assertEqual(len(s.transport.requests), 20)
            self.assertLessEqual(len(s.transport.requests), f.updater.PER_ISSUER_REQUESTS)
            self.assertEqual({v['retrieved_at'] for v in s.loaded().values()}, {s.now})

    def test_z_builder_verified_typed_values(self):
        with f.Scenario() as s:
            s.plan()
            result = s.build()
            self.assert_verified(result)
            record = result['record']
            rows = record['reported_quarters']
            self.assertEqual([r['end'] for r in rows], ['2031-03-31', '2031-06-30', '2031-09-30', '2031-12-31'])
            self.assertEqual([r['revenue'] for r in rows], [1111100000.0, 1222200000.0, 1333300000.0, 1444400000.0])
            self.assertEqual((rows[0]['derivation']['longer_value'], rows[0]['derivation']['shorter_value']),
                             (2333300000.0, 1222200000.0))
            self.assertEqual((rows[3]['derivation']['longer_value'], rows[3]['derivation']['shorter_value']),
                             (5111000000.0, 3666600000.0))
            self.assertEqual([(v['start'], v['end']) for v in record['forward_intervals']],
                             [('2032-01-01', '2032-03-31'), ('2032-04-01', '2032-06-30'),
                              ('2032-07-01', '2032-09-30'), ('2032-10-01', '2032-12-31')])
            self.assertEqual(len(record['claims']), 1)
            claim = record['claims'][0]
            self.assertEqual((claim['period_kind'], claim['low'], claim['high'], claim['period_start'], claim['period_end']),
                             ('FISCAL_YEAR', 7200000000.0, 7600000000.0, '2032-01-01', '2032-12-31'))
            self.assertNotIn('reaffirmed_by', claim)
            self.assertEqual(record['fy_reconciliation'], {'fy_claim_id': 'NBIS-FY2032-GUIDANCE',
                'ytd_start': '2032-01-01', 'ytd_end': '2032-01-01', 'ytd_revenue': 0.0, 'ytd_quarter_ends': []})
            self.assertEqual(Counter(d['kind'] for d in result['decisions']),
                             Counter(MEMBERSHIP=4, ACTUAL=4, CLAIM=1, FY_RECONCILIATION=1, CALENDAR=1, ROUTING=1))
            recon = next(d for d in result['decisions'] if d['kind'] == 'FY_RECONCILIATION')
            self.assertIsNone(recon['operands']['operand'])
            calendar = next(d for d in result['decisions'] if d['kind'] == 'CALENDAR')
            self.assertTrue(calendar['operands']['tagged_proofs'])
            for proof in calendar['operands']['tagged_proofs']:
                self.assertEqual(proof['tagged'], {'present': False, 'policy': 'FOREIGN_TABLE_TAGGED_ABSENCE_V1'})
            self.assertEqual(len(record['documents']), 12)
            membership = next(d for d in result['decisions'] if d['kind'] == 'MEMBERSHIP' and d['ref'] == s.lead['accession'])
            self.assertEqual(sum(p['kind'] == 'LETTER' for p in membership['operands']['basis']['corroboration']), 1)
            self.assertEqual(f.verify.canonical_json(s.build()), f.verify.canonical_json(result))

    def test_z_attempt_validates_and_rederives(self):
        with f.Scenario() as s:
            s.plan()
            result = s.build()
            self.assert_verified(result)
            attempt = f.updater._attempt(s.lead['accession'], s.now, s.baseline, s.event, s.captures, result)
            self.assertIsNone(f.overlay.validate_attempt(attempt))
            again = f.overlay.rederive(s.root, s.profile, s.baseline, attempt, allow_replay=False, baseline=s.baseline)
            self.assertEqual(f.verify.canonical_json(again), f.verify.canonical_json(result))

    def test_r_reaffirmation(self):
        with f.Scenario('R') as s:
            f.guidance.validate_issuer_record(s.baseline, 'NBIS')
            s.plan()
            self.assertEqual(s.transport.requests, s.expected_requests())
            result = s.build()
            self.assert_verified(result)
            rows = [d for d in result['decisions'] if d['kind'] == 'REAFFIRMATION']
            self.assertEqual(len(rows), 1)
            current = s.event['packages'][0]
            self.assertEqual(rows[0]['capture'], current['letter'])
            self.assertEqual(rows[0]['operands']['reference_capture'], current['letter'])
            record = result['record']
            self.assertEqual(record['fy_reconciliation'], {'fy_claim_id': 'NBIS-FY2034-GUIDANCE',
                'ytd_start': '2034-01-01', 'ytd_end': '2034-06-30', 'ytd_revenue': 3533300000.0,
                'ytd_quarter_ends': ['2034-03-31', '2034-06-30']})
            recon = next(d for d in result['decisions'] if d['kind'] == 'FY_RECONCILIATION')
            self.assertIsNotNone(recon['operands']['operand'])
            self.assertEqual(recon['operands']['operand']['value'], '3533300000.0')
            reference = f.guidance.guidance_reference(record)
            self.assertEqual(reference['document_id'], 'NBIS-0000000000-34-000205-tm3400205d1_ex99-2.htm')
            self.assertEqual(record['claims'][0]['reaffirmed_by'][0]['document_id'], reference['document_id'])
            attempt = f.updater._attempt(s.lead['accession'], s.now, s.baseline, s.event, s.captures, result)
            self.assertIsNone(f.overlay.validate_attempt(attempt))
            again = f.overlay.rederive(s.root, s.profile, s.baseline, attempt, allow_replay=False, baseline=s.baseline)
            self.assertEqual(f.verify.canonical_json(again), f.verify.canonical_json(result))


if __name__ == '__main__':
    unittest.main()
