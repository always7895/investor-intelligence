"""Financial components only; no fresh-source, LINE or release qualification."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import company_financial_products as products
import build_v212_top20_report as builder
import test_v212_top20_report as report_fixture


class CompanyFinancialProductsTests(unittest.TestCase):
    def inputs(self, op=12.0, net=20.0):
        helper = report_fixture.V212Top20ReportTests()
        sink = {}
        facts = [helper.fact()]
        if op is not None:
            facts.append(helper.fact(tag='OperatingIncomeLoss', value=op))
        if net is not None:
            facts.append(helper.fact(tag='NetIncomeLoss', value=net))
        report = helper.actual_report(facts, financial_evidence_sink=sink)
        report_bytes = builder.json_bytes(report)
        basis = dict(schema_version=1, status='CANDIDATE_NOT_PUBLICATION_QUALIFIED',
                     publication_eligible=False, provider_scope='public_only', owner_watchlist_inherited=False,
                     generated_at=report['generated_at'], report_sha256=products.sha256(report_bytes),
                     hash_scope='v212 report UTF-8 bytes, not source HTTP or sealed snapshot', records=sink)
        return report_bytes, builder.json_bytes(basis)

    def candidate(self, **kwargs):
        report, basis = self.inputs(**kwargs)
        return products.build_financial_products(report, basis)

    def test_different_information_tasks_not_three_labels_on_one_text(self):
        doc = self.candidate()
        values = doc['records'][0]['products']
        summary, data, analysis = (values[key]['content_utf8'] for key in products.KINDS)
        self.assertIn('財務摘要', summary)
        self.assertNotIn('| 角色 |', summary)
        self.assertIn('| 分子 | OperatingIncomeLoss | 12.0 | USD |', data)
        self.assertIn('| 分母 | Revenues | 100.0 | USD |', data)
        self.assertIn('numerator / denominator', data)
        self.assertIn('\n\n| 角色 |', data)
        self.assertIn('|\n\n公式：', data)
        self.assertIn('2025-07-01～2026-06-30', data)
        self.assertIn('Filed', data)
        self.assertIn('8.0000 個百分點', analysis)
        for text in ('問題：', '計算觀察', '條件解讀（INFERENCE）', '反方：', '條件結論：', '推翻／更新條件：'):
            self.assertIn(text, analysis)
        self.assertNotIn('| 角色 |', analysis)
        self.assertIn('不能把整個淨利率都歸因於產品定價', analysis)
        self.assertEqual(len({values[k]['content_sha256'] for k in products.KINDS}), 3)
        self.assertFalse(doc['publication_eligible'])
        self.assertFalse(doc['complete'])
        self.assertIsNone(doc['snapshot_run_id'])

    def test_body_and_every_page_bind_same_input_and_subject(self):
        report, basis = self.inputs()
        doc = products.build_financial_products(report, basis)
        for row in doc['records']:
            for kind, value in row['products'].items():
                self.assertEqual(value['scope'], 'financial_evidence_only')
                self.assertFalse(value['complete'])
                self.assertFalse(value['publication_eligible'])
                self.assertEqual(value['subject']['ticker'], row['ticker'])
                self.assertFalse(value['subject']['security_identity_qualified'])
                self.assertEqual(value['source_report_sha256'], hashlib.sha256(report).hexdigest())
                self.assertEqual(value['source_basis_sha256'], hashlib.sha256(basis).hexdigest())
                self.assertEqual(value['content_sha256'], hashlib.sha256(value['content_utf8'].encode()).hexdigest())
                self.assertEqual(value['content_bytes'], len(value['content_utf8'].encode()))
                self.assertEqual('\n\n'.join(p['text'] for p in value['pages']), value['content_utf8'])
                for i, page in enumerate(value['pages'], 1):
                    self.assertEqual(page['index'], i)
                    self.assertEqual(page['count'], len(value['pages']))
                    self.assertEqual(page['output_kind'], kind)
                    self.assertEqual(page['report_id'], value['report_id'])
                    self.assertEqual(page['candidate_snapshot_id'], doc['candidate_snapshot_id'])
                    self.assertEqual(page['subject'], value['subject'])
                    self.assertEqual(page['content_sha256'], value['content_sha256'])
                    self.assertEqual(page['page_sha256'], hashlib.sha256(page['text'].encode()).hexdigest())

    def test_interpretation_changes_with_economic_signs_without_inventing_cause(self):
        for op, net, expected in [(-12, 20, '正淨利不能直接當作本業已獲利'),
                                  (12, -20, '底線卻虧損'), (12, 8, '存在減項的淨影響'),
                                  (12, 12, '不證明沒有利息')]:
            with self.subTest(op=op, net=net):
                body = self.candidate(op=op, net=net)['records'][0]['products']['narrative_analysis']['content_utf8']
                self.assertIn(expected, body)
                self.assertIn('不是已證實歸因', body)
                self.assertIn('不能外推下一期成長或目標價', body)

    def test_missing_analysis_inputs_never_redirect_to_summary(self):
        values = self.candidate(op=None)['records'][0]['products']
        self.assertEqual(values['card_summary']['status'], 'AVAILABLE_PARTIAL')
        self.assertEqual(values['data_report']['status'], 'AVAILABLE_PARTIAL')
        narrative = values['narrative_analysis']
        self.assertEqual(narrative['status'], 'UNAVAILABLE')
        self.assertEqual(narrative['reason'], 'COMPARABLE_OPERATING_AND_NET_REQUIRED')
        self.assertIsNone(narrative['content_utf8'])
        self.assertIsNone(narrative['content_sha256'])
        self.assertEqual(narrative['pages'], [])
        self.assertIn('本項不輸出計算結果', values['data_report']['content_utf8'])

    def test_source_failure_and_no_identity_emit_unavailable_not_previous_content(self):
        report, raw_basis = self.inputs()
        for status in ('NO_OFFICIAL_IDENTITY', 'SOURCE_FETCH_OR_VALIDATION_FAILED'):
            basis = json.loads(raw_basis)
            basis['records']['T00'] = {'status': status, 'publication_eligible': False}
            doc = products.build_financial_products(report, builder.json_bytes(basis))
            for value in doc['records'][0]['products'].values():
                self.assertEqual(value['status'], 'UNAVAILABLE')
                self.assertEqual(value['reason'], status)
                self.assertIsNone(value['content_utf8'])
                self.assertEqual(value['content_bytes'], 0)

    def test_withheld_conflict_cannot_be_promoted_by_recomputation(self):
        report, raw_basis = self.inputs()
        basis = json.loads(raw_basis)
        metric = basis['records']['T00']['metrics']['operating_margin']
        metric['status'] = 'CONFLICTING_OPERAND'; metric['value'] = None
        values = products.build_financial_products(report, builder.json_bytes(basis))['records'][0]['products']
        self.assertIn('CONFLICTING_OPERAND', values['data_report']['content_utf8'])
        self.assertNotIn('營益率：12.0000%', values['card_summary']['content_utf8'])
        self.assertEqual(values['narrative_analysis']['status'], 'UNAVAILABLE')

    def test_forged_calculation_or_formula_is_rejected(self):
        report, raw_basis = self.inputs()
        for field, value in [('value', 99.0), ('formula', 'numerator * denominator'),
                             ('value_unit', 'percent'), ('value', True)]:
            basis = json.loads(raw_basis)
            basis['records']['T00']['metrics']['net_margin'][field] = value
            with self.subTest(field=field), self.assertRaises(products.FinancialProductsError):
                products.build_financial_products(report, builder.json_bytes(basis))

    def test_subject_clock_publication_or_private_extensions_fail_closed(self):
        report, raw_basis = self.inputs()
        for mutation in [lambda b: b.update(publication_eligible=True),
                         lambda b: b.update(schema_version=True),
                         lambda b: b['records'].pop('T19'),
                         lambda b: b['records']['T00'].update(as_of_cutoff='2000-01-01T00:00:00Z'),
                         lambda b: b['records']['T00'].update(cik='0000000002'),
                         lambda b: b['records']['T00'].update(portfolio='SYNTHETIC_PRIVATE_MARKER'),
                         lambda b: b['records']['T00']['metrics']['net_margin']['numerator'].update(unit='EUR'),
                         lambda b: b['records']['T00']['metrics']['net_margin']['numerator'].update(record_url='https://www.sec.gov/x?token=SYNTHETIC_PRIVATE_MARKER')]:
            basis = json.loads(raw_basis); mutation(basis)
            with self.assertRaises(products.FinancialProductsError) as error:
                products.build_financial_products(report, builder.json_bytes(basis))
            self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', str(error.exception))

    def test_duplicate_keys_nonfinite_and_wrong_exact_report_bytes_rejected(self):
        report, basis = self.inputs()
        duplicate = basis.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1', 1)
        bad_number = basis.replace(b'"value": 0.2', b'"value": NaN', 1)
        for body in (duplicate, bad_number):
            with self.assertRaises(products.FinancialProductsError):
                products.build_financial_products(report, body)
        with self.assertRaises(products.FinancialProductsError):
            products.build_financial_products(report + b' ', basis)

    def test_same_timestamp_new_bytes_change_identity_and_old_product_verification_fails(self):
        report, basis = self.inputs()
        doc = products.build_financial_products(report, basis)
        body = builder.json_bytes(doc)
        products.verify_financial_products(body, report, basis)
        changed_basis = basis + b'\n'
        changed = products.build_financial_products(report, changed_basis)
        self.assertNotEqual(doc['candidate_snapshot_id'], changed['candidate_snapshot_id'])
        with self.assertRaises(products.FinancialProductsError):
            products.verify_financial_products(body, report, changed_basis)
        for edit in ('content', 'kind', 'subject', 'page'):
            bad = copy.deepcopy(doc); value = bad['records'][0]['products']['data_report']
            if edit == 'content':
                value['content_utf8'] = 'summary masquerading as data report'
                value['content_sha256'] = hashlib.sha256(value['content_utf8'].encode()).hexdigest()
            elif edit == 'kind':
                value['output_kind'] = 'card_summary'
            elif edit == 'subject':
                value['subject']['ticker'] = 'T19'
            else:
                value['pages'].pop()
            with self.subTest(edit=edit), self.assertRaises(products.FinancialProductsError):
                products.verify_financial_products(builder.json_bytes(bad), report, basis)

    def test_page_capacity_preserves_risk_and_sources_or_refuses_not_clips(self):
        identity = {'subject': {'ticker': 'TEST'}, 'candidate_snapshot_id': 'candidate:synthetic', 'snapshot_run_id': None}
        blocks = ['漢字😀' * 900, '查核' * 900, '尾段風險；https://www.sec.gov/']
        value = products._product('data_report', blocks, [], identity)
        self.assertEqual(len(value['pages']), 2)
        self.assertEqual('\n\n'.join(p['text'] for p in value['pages']), '\n\n'.join(blocks))
        self.assertIn('尾段風險', value['pages'][-1]['text'])
        for page in value['pages']:
            self.assertLessEqual(len(page['text'].encode('utf-16-le')) // 2, 4400)
        for bad in (['😀' * 2201], ['漢' * 4400] * 6):
            with self.assertRaises(products.FinancialProductsError):
                products._product('data_report', bad, [], identity)

    def test_actual_cli_rejects_invalid_products_before_replacing_outputs(self):
        helper = report_fixture.V212Top20ReportTests()
        original = builder.build
        def bad_build(**kwargs):
            report = helper.actual_report([helper.fact(), helper.fact(tag='NetIncomeLoss', value=20.0)], _build=original, **kwargs)
            kwargs['financial_evidence_sink']['T00']['metrics']['net_margin']['value'] = 99.0
            return report
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            output.write_text('KEEP_ORIGINAL', encoding='utf-8')
            with patch.object(builder, 'build', side_effect=bad_build), \
                    patch.object(sys, 'argv', ['build', '--output', str(output)]), redirect_stdout(StringIO()):
                self.assertEqual(builder.main(), 1)
            self.assertEqual(output.read_text(encoding='utf-8'), 'KEEP_ORIGINAL')
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_actual_cli_does_not_report_success_after_changed_product_readback(self):
        helper = report_fixture.V212Top20ReportTests()
        original, write = builder.build, builder.atomic_write
        def changed_write(path, doc):
            write(path, doc)
            if path.name.endswith('.financial-products-candidate.json'):
                changed = json.loads(path.read_text(encoding='utf-8'))
                changed['records'][0]['products']['data_report']['pages'] = []
                path.write_bytes(builder.json_bytes(changed))
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            with patch.object(builder, 'build', side_effect=lambda **kw: helper.actual_report(
                    [helper.fact(), helper.fact(tag='NetIncomeLoss', value=20.0)], _build=original, **kw)), \
                    patch.object(builder, 'atomic_write', side_effect=changed_write), \
                    patch.object(sys, 'argv', ['build', '--output', str(output)]), redirect_stdout(StringIO()) as printed:
                self.assertEqual(builder.main(), 1)
            self.assertIn('FINANCIAL_PRODUCTS_OUTPUT_MISMATCH', printed.getvalue())
            self.assertNotIn('"status": "PASS"', printed.getvalue())

    def test_actual_cli_rejects_products_collision_before_any_build_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / name for name in ('report.json', 'returns.json', 'basis.json')]
            for path in paths:
                path.write_text('sentinel', encoding='utf-8')
            for other in paths:
                args = ['build', '--output', str(paths[0]), '--return-evidence-output', str(paths[1]),
                        '--financial-evidence-output', str(paths[2]), '--financial-products-output', str(other)]
                with patch.object(sys, 'argv', args), patch.object(builder, 'build') as build, redirect_stdout(StringIO()):
                    self.assertEqual(builder.main(), 1); build.assert_not_called()
                self.assertTrue(all(p.read_text(encoding='utf-8') == 'sentinel' for p in paths))


if __name__ == '__main__':
    unittest.main()
