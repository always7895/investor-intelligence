"""Actual SEC-wire/report CLI; synthetic debt parts, not live financing qualification."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_v212_top20_report as builder
import company_financial_products as products
import v213_v21_progress_runner as runner
import test_v212_top20_report as fixtures
import test_financial_liquidity_bridge as liquidity_fixture


class FinancialDebtBridgeTests(unittest.TestCase):
    def facts(self):
        helper = fixtures.V212Top20ReportTests()
        return [helper.fact(tag=tag, value=value, start=None) for tag, value in
                [('LongTermDebtCurrent', 30), ('LongTermDebtNoncurrent', 70), ('LongTermDebt', 100)]]

    def cli(self, folder, facts=None):
        return liquidity_fixture.FinancialLiquidityBridgeTests().cli(folder, self.facts() if facts is None else facts)

    def evidence(self, facts=None):
        return runner.debt_evidence(self.facts() if facts is None else facts,
                                    cik='0000000001', as_of='2026-09-10T00:00:00Z')

    def test_actual_cli_retains_disclosed_debt_parts_and_reported_total_without_adding_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp)
        company = json.loads(basis)['records']['T00']
        self.assertIn('debt_bridge', company, 'ACTUAL_CLI_DROPS_DISCLOSED_LONG_TERM_DEBT_PARTS')
        debt = company['debt_bridge']
        self.assertEqual(debt['metrics']['long_term_components_sum']['value'], 100)
        self.assertEqual(debt['metrics']['current_portion_fraction']['value'], .3)
        self.assertEqual(debt['reported_total_check']['status'], 'MATCHED')
        for item in debt['observations'].values():
            self.assertIsNone(item['operand']['start'])
            self.assertEqual(item['operand']['end'], '2026-06-30')
        products.verify_financial_products(raw, report, basis)

    def test_actual_cli_debt_only_can_support_bounded_narrative_not_fake_total_company_debt(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp)
        values = json.loads(raw)['records'][0]['products']
        self.assertEqual(values['narrative_analysis']['status'], 'AVAILABLE_PARTIAL',
                         'ACTUAL_CLI_WITHHOLDS_ALL_ANALYSIS_DESPITE_COMPARABLE_DEBT_PARTS')
        self.assertIn('debt.long_term_components_sum', values['narrative_analysis']['claim_refs'])
        self.assertIn('不是公司總負債', values['narrative_analysis']['content_utf8'])
        self.assertIn('LongTermDebtNoncurrent', values['data_report']['content_utf8'])
        self.assertEqual(len({v['content_sha256'] for v in values.values()}), 3)
        products.verify_financial_products(raw, report, basis)

    def test_actual_cli_raw_omissions_cannot_drop_latest_window_and_rescue_older_debt(self):
        old = [{**v, 'end': '2025-06-30', 'filed': '2025-07-29'} for v in self.facts()]
        original = fixtures.V212Top20ReportTests().wire_document(old + self.facts())
        for case in ('filed', 'end', 'accn', 'form', 'observation', 'units', 'fact', 'taxonomy'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                doc = copy.deepcopy(original); tags = doc['facts']['us-gaap']
                if case in ('filed', 'end', 'accn', 'form'):
                    for tag in tags.values(): tag['units']['USD'][-1][case] = None
                elif case == 'observation': tags['LongTermDebt']['units']['USD'].append(None)
                elif case == 'units': tags['LongTermDebt']['units']['EUR'] = 'MALFORMED_SYNTHETIC_WINDOW'
                elif case == 'fact': tags['SYNTHETIC_BROKEN_FACT'] = None
                else: doc['facts']['SYNTHETIC_BROKEN_TAXONOMY'] = None
                with patch.object(fixtures.V212Top20ReportTests, 'wire_document', return_value=doc):
                    report, basis, raw = self.cli(tmp, old + self.facts())
                company = json.loads(basis)['records']['T00']
                self.assertEqual(company['status'], 'SOURCE_FETCH_OR_VALIDATION_FAILED',
                                 'RAW_OMISSION_SKIPPED_IN_ACTUAL_CLI_AND_OLDER_DEBT_RESCUED')
                self.assertNotIn('debt_bridge', company)
                self.assertTrue(all(v['status'] == 'UNAVAILABLE' for v in json.loads(raw)['records'][0]['products'].values()))
                products.verify_financial_products(raw, report, basis)
                with self.assertRaisesRegex(builder.base.PipelineError, '^PUBLIC_JSON_SOURCE_SHAPE_INVALID$'):
                    builder.base._public_payload(doc, builder.json_bytes(doc),
                        'https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json', '')

    def test_zero_parts_and_zero_denominator_keep_distinct_meanings(self):
        for current, noncurrent, total, fraction in [(30, 70, 100, .3), (0, 70, 70, 0),
                                                    (30, 0, 30, 1), (0, 0, 0, None)]:
            rows = self.facts()
            for row, value in zip(rows, (current, noncurrent, total)): row['value'] = value
            doc = self.evidence(rows)
            self.assertEqual(doc['metrics']['long_term_components_sum']['value'], total)
            self.assertEqual(doc['metrics']['current_portion_fraction']['value'], fraction)
            self.assertEqual(doc['reported_total_check']['status'], 'MATCHED')
            runner.validate_debt_evidence(doc, cik=doc['cik'], as_of=doc['as_of_cutoff'])
            if fraction is None:
                self.assertEqual(doc['metrics']['current_portion_fraction']['status'], 'WITHHELD_NONPOSITIVE_DENOMINATOR')
                self.assertIn('不等於公司無負債', '\n'.join(products._debt_blocks(doc, 'narrative_analysis')))

    def test_no_reported_total_is_not_verified_and_reported_total_only_cannot_reconstruct_parts(self):
        doc = self.evidence(self.facts()[:2])
        self.assertEqual(doc['reported_total_check']['status'], 'NOT_REPORTED')
        self.assertEqual(doc['metrics']['long_term_components_sum']['value'], 100)
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp, self.facts()[2:])
        values = json.loads(raw)['records'][0]['products']
        self.assertEqual(values['card_summary']['status'], 'AVAILABLE_PARTIAL')
        self.assertEqual(values['narrative_analysis']['status'], 'UNAVAILABLE')
        self.assertIn('LongTermDebt', values['data_report']['content_utf8'])
        self.assertIsNone(json.loads(basis)['records']['T00']['debt_bridge']['metrics']['long_term_components_sum']['value'])
        products.verify_financial_products(raw, report, basis)

    def test_actual_cli_reported_total_conflict_withholds_debt_but_preserves_independent_profit(self):
        rows = self.facts(); rows[2]['value'] = 200
        h = fixtures.V212Top20ReportTests()
        profit = [h.fact(), h.fact(tag='OperatingIncomeLoss', value=12), h.fact(tag='NetIncomeLoss', value=20)]
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp, rows + profit)
        bridge = json.loads(basis)['records']['T00']['debt_bridge']
        self.assertEqual(bridge['reported_total_check']['status'], 'CONFLICT')
        self.assertTrue(all(m['status'] == 'WITHHELD_REPORTED_TOTAL_CONFLICT' and m['value'] is None for m in bridge['metrics'].values()))
        values = json.loads(raw)['records'][0]['products']
        self.assertEqual(values['narrative_analysis']['status'], 'AVAILABLE_PARTIAL')
        self.assertIn('operating_margin', values['narrative_analysis']['claim_refs'])
        self.assertNotIn('debt.long_term_components_sum', values['narrative_analysis']['claim_refs'])
        self.assertIn('WITHHELD_REPORTED_TOTAL_CONFLICT', values['data_report']['content_utf8'])
        self.assertIn('CONFLICT', values['narrative_analysis']['content_utf8'],
                      'ACTUAL_NARRATIVE_HIDES_KNOWN_DEBT_CONFLICT_BEHIND_VALID_PROFIT')
        self.assertIn('debt.reported_total_check', values['narrative_analysis']['claim_refs'])
        for kind, value in values.items():
            self.assertIn('原始披露精度尚未核驗', value['content_utf8'], kind)
            self.assertIn('不能據此認定財報錯誤', value['content_utf8'], kind)
            self.assertIn('不以猜測容差放行', value['content_utf8'], kind)
            self.assertEqual('\n\n'.join(page['text'] for page in value['pages']), value['content_utf8'])
        products.verify_financial_products(raw, report, basis)
        with tempfile.TemporaryDirectory() as tmp:
            _, _, debt_only = self.cli(tmp, rows)
        self.assertEqual(json.loads(debt_only)['records'][0]['products']['narrative_analysis']['status'], 'UNAVAILABLE',
                         'FAILURE_NOTICE_MUST_NOT_QUALIFY_ANALYSIS')

    def test_present_invalid_or_conflicting_total_cannot_be_treated_as_unreported(self):
        for change in ({'value': -1}, {'value': True}, {'unit': None}, {'filed': '9999-01-01'}):
            rows = self.facts(); old = dict(rows[2]); old.update(end='2025-06-30', filed='2025-07-29'); rows[2].update(change)
            doc = self.evidence(rows + [old])
            self.assertEqual(doc['reported_total_check']['status'], 'UNVERIFIED')
            self.assertEqual(doc['metrics']['long_term_components_sum']['status'], 'WITHHELD_REPORTED_TOTAL_UNVERIFIED')
        rows = self.facts(); doc = self.evidence(rows + [{**rows[2], 'value': 999}])
        self.assertEqual(doc['observations']['reported_long_term_debt']['status'], 'CONFLICTING_OPERAND')
        self.assertEqual(doc['reported_total_check']['status'], 'UNVERIFIED')

    def test_instant_values_identity_and_dates_are_strict_no_older_rescue(self):
        changes = [{'value': v} for v in (-1, True, '30', None, float('inf'), float('nan'), 2**53, 10**400)] + [
            {'start': '2025-07-01'}, {'start': ''}, {'start': True}, {'cik': '0000000002'}, {'unit': None}, {'unit': 'shares'},
            {'end': '2026-02-30'}, {'filed': '9999-01-01'}, {'filed': '2026-07-29suffix'}, {'form': '8-K'}, {'fiscal_year': True},
            {'accession_number': 'bad'}, {'record_url': 'https://example.test/SYNTHETIC_PRIVATE_MARKER'}]
        for change in changes:
            with self.subTest(fields=list(change)):
                rows = self.facts(); old = {**rows[0], 'end': '2025-06-30', 'filed': '2025-07-29'}; rows[0].update(change)
                doc = self.evidence(rows + [old])
                self.assertEqual(doc['observations']['current_debt']['status'], 'INVALID_OPERAND')
                self.assertIsNone(doc['metrics']['long_term_components_sum']['value'])
                self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(doc))
        rows = self.facts(); del rows[0]['start']
        self.assertEqual(self.evidence(rows)['observations']['current_debt']['status'], 'INVALID_OPERAND')

    def test_latest_cohort_duplicate_conflict_and_ambiguity_are_order_independent(self):
        rows = self.facts(); self.assertEqual(self.evidence(rows + [dict(rows[0])]), self.evidence(rows))
        for change, expected in [({'value': 31}, 'CONFLICTING_OPERAND'), ({'unit': 'EUR'}, 'AMBIGUOUS_OPERAND'),
                                 ({'accession_number': '0000000001-26-000002'}, 'AMBIGUOUS_OPERAND'), ({'form': '10-Q'}, 'AMBIGUOUS_OPERAND')]:
            other = {**rows[0], **change}
            for selected in (rows + [other], [other] + rows):
                doc = self.evidence(selected)
                self.assertEqual(doc['observations']['current_debt']['status'], expected)
                self.assertIsNone(doc['metrics']['long_term_components_sum']['value'])
        rows = self.facts(); older = dict(rows[1]); rows[1]['filed'] = '2026-08-01'
        self.assertEqual(self.evidence(rows + [older])['metrics']['current_portion_fraction']['status'], 'WITHHELD_NOT_COMPARABLE')

    def test_components_and_present_total_require_same_basis(self):
        for index in (1, 2):
            for change in ({'unit': 'EUR'}, {'end': '2026-03-31'}, {'filed': '2026-08-01'}, {'form': '10-Q'},
                           {'fiscal_year': 2025}, {'accession_number': '0000000001-26-000002'},
                           {'record_url': 'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/'}):
                with self.subTest(index=index, fields=list(change)):
                    rows = self.facts(); rows[index].update(change); doc = self.evidence(rows)
                    self.assertEqual(doc['reported_total_check']['status'], 'NOT_COMPARABLE')
                    self.assertTrue(all(m['status'] == 'WITHHELD_NOT_COMPARABLE' for m in doc['metrics'].values()))

    def test_other_borrowings_liabilities_or_leases_are_not_substitutes_or_extra_addends(self):
        rows = self.facts(); h = fixtures.V212Top20ReportTests()
        extra = [h.fact(tag=t, start=None, value=9999) for t in
                 ('Liabilities', 'LiabilitiesCurrent', 'CommercialPaper', 'ShortTermBorrowings',
                  'LongTermDebtAndCapitalLeaseObligationsCurrent', 'FinanceLeaseLiabilityCurrent')]
        self.assertEqual(self.evidence(rows + extra), self.evidence(rows))
        doc = self.evidence(extra)
        self.assertTrue(all(v['status'] == 'MISSING_OPERAND' for v in doc['observations'].values()))
        self.assertTrue(all(v['value'] is None for v in doc['metrics'].values()))

    def test_unsafe_component_sum_and_nonzero_fraction_underflow_are_withheld(self):
        rows = self.facts()[:2]; rows[0]['value'] = 9007199254740991; rows[1]['value'] = 1
        doc = self.evidence(rows)
        self.assertEqual(doc['reported_total_check']['status'], 'UNSAFE_COMPONENT_SUM')
        self.assertTrue(all(m['status'] == 'WITHHELD_UNSAFE_RESULT' for m in doc['metrics'].values()))
        rows[0]['value'] = 5e-324; rows[1]['value'] = 9007199254740991
        doc = self.evidence(rows)
        self.assertEqual(doc['metrics']['current_portion_fraction']['status'], 'WITHHELD_UNSAFE_RESULT')
        self.assertIsNone(doc['metrics']['current_portion_fraction']['value'])
        json.dumps(doc, allow_nan=False)

    def test_validator_rejects_forged_math_check_identity_and_eligibility(self):
        original = self.evidence()
        changes = [lambda d: d['metrics']['long_term_components_sum'].update(value=200),
                   lambda d: d['metrics']['current_portion_fraction'].update(value=True),
                   lambda d: d['metrics']['long_term_components_sum'].update(operand_refs=['reported_long_term_debt']),
                   lambda d: d['reported_total_check'].update(status='NOT_REPORTED'),
                   lambda d: d.update(schema_version=True), lambda d: d.update(publication_eligible=True),
                   lambda d: d.update(source_refresh_verified=True), lambda d: d.update(cik='0000000002'),
                   lambda d: d.update(source_retrieved_at='2026-09-10T00:00:00Z'),
                   lambda d: d['observations']['current_debt']['operand'].update(owner='SYNTHETIC_PRIVATE_MARKER'),
                   lambda d: d['observations']['current_debt']['operand'].update(value=-1),
                   lambda d: d['observations']['current_debt'].update(status='MISSING_OPERAND')]
        for change in changes:
            doc = copy.deepcopy(original); change(doc)
            with self.assertRaises((runner.engine.PipelineError, ValueError)) as error:
                runner.validate_debt_evidence(doc, cik=original['cik'], as_of=original['as_of_cutoff'])
            self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', str(error.exception))
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp)
        malformed = json.loads(basis); malformed['records']['T00']['debt_bridge']['reported_total_check']['status'] = 'NOT_REPORTED'
        with self.assertRaisesRegex(products.FinancialProductsError, 'FINANCIAL_PRODUCTS_DEBT_INVALID'):
            products.build_financial_products(report, builder.json_bytes(malformed))

    def test_missing_refresh_replaces_debt_content_not_carrying_old_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.cli(tmp)
            report, basis, raw = self.cli(tmp, self.facts()[2:])
        self.assertEqual(json.loads(raw)['records'][0]['products']['narrative_analysis']['status'], 'UNAVAILABLE')
        self.assertIsNone(json.loads(basis)['records']['T00']['debt_bridge']['metrics']['long_term_components_sum']['value'])
        products.verify_financial_products(raw, report, basis)

    def test_incomplete_debt_does_not_erase_supported_cashflow_liquidity_or_profit(self):
        h = fixtures.V212Top20ReportTests()
        supports = [[h.fact(), h.fact(tag='OperatingIncomeLoss', value=12), h.fact(tag='NetIncomeLoss', value=20)],
                    [h.fact(tag='NetCashProvidedByUsedInOperatingActivities', value=40), h.fact(tag='PaymentsToAcquirePropertyPlantAndEquipment', value=60)],
                    liquidity_fixture.FinancialLiquidityBridgeTests().facts()]
        refs = ['operating_margin', 'cashflow.cash_after_ppe', 'liquidity.working_capital']
        for support, ref in zip(supports, refs):
            with self.subTest(ref=ref), tempfile.TemporaryDirectory() as tmp:
                report, basis, raw = self.cli(tmp, self.facts()[2:] + support)
                value = json.loads(raw)['records'][0]['products']['narrative_analysis']
                self.assertEqual(value['status'], 'AVAILABLE_PARTIAL'); self.assertIn(ref, value['claim_refs'])
                self.assertNotIn('debt.long_term_components_sum', value['claim_refs'])
                products.verify_financial_products(raw, report, basis)

    def test_all_twenty_distinct_outputs_keep_complete_pages_identity_and_failed_eligibility(self):
        h = fixtures.V212Top20ReportTests()
        rows = self.facts() + liquidity_fixture.FinancialLiquidityBridgeTests().facts() + [h.fact(),
            h.fact(tag='OperatingIncomeLoss', value=12), h.fact(tag='NetIncomeLoss', value=20),
            h.fact(tag='NetCashProvidedByUsedInOperatingActivities', value=40), h.fact(tag='PaymentsToAcquirePropertyPlantAndEquipment', value=60),
            h.fact(tag='ShareBasedCompensation', value=5), h.fact(tag='WeightedAverageNumberOfSharesOutstandingBasic', value=100, unit='shares'),
            h.fact(tag='WeightedAverageNumberOfDilutedSharesOutstanding', value=110, unit='shares')]
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp, rows)
        for i, record in enumerate(json.loads(raw)['records']):
            self.assertEqual(record['ticker'], f'T{i:02}')
            for kind, value in record['products'].items():
                self.assertEqual(value['output_kind'], kind); self.assertEqual(value['subject']['ticker'], record['ticker'])
                self.assertFalse(value['complete']); self.assertFalse(value['publication_eligible']); self.assertIsNone(value['snapshot_run_id'])
                self.assertEqual('\n\n'.join(p['text'] for p in value['pages']), value['content_utf8'])
                self.assertTrue(0 < len(value['pages']) <= 5)
                self.assertTrue(all(len(p['text'].encode('utf-16-le')) // 2 <= 4400 for p in value['pages']))
                self.assertIn('來源與限制', value['content_utf8'])
            self.assertEqual(len({v['content_sha256'] for v in record['products'].values()}), 3)
        company = json.loads(basis)['records']['T00']
        self.assertEqual(company['schema_version'], 5); self.assertFalse(company['source_refresh_verified'])
        self.assertIsNone(company['debt_bridge']['source_retrieved_at']); self.assertIsNone(company['source_acquisition'])
        products.verify_financial_products(raw, report, basis)

    def test_legacy_company1_to4_do_not_silently_gain_debt_content(self):
        h = fixtures.V212Top20ReportTests()
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, _ = self.cli(tmp, self.facts() + [h.fact(), h.fact(tag='NetIncomeLoss', value=20)])
        for version in (1, 2, 3, 4):
            legacy = json.loads(basis)
            for company in legacy['records'].values():
                company.pop('debt_bridge'); company['schema_version'] = version
                company['limitations'] = list(runner.FINANCIAL_V4_LIMITATIONS if version == 4 else runner.FINANCIAL_V2_LIMITATIONS if version >= 2 else products.LIMITATIONS)
                if version < 4: company.pop('liquidity_bridge')
                if version < 3: company.pop('source_acquisition')
                if version < 2: company.pop('cashflow_bridge')
            data = builder.json_bytes(legacy); content = builder.json_bytes(products.build_financial_products(report, data))
            self.assertNotIn('debt.', content.decode()); products.verify_financial_products(content, report, data)

    def test_rank_rebinding_keeps_debt_evidence_content_and_source_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp)
            returns = (Path(tmp)/'report.return-evidence-candidate.json').read_bytes()
        ranked = json.loads(report); ranked['records'].reverse()
        for i, row in enumerate(ranked['records'], 1): row['rank'] = i
        result = builder.rebind_ranked_candidates(builder.json_bytes(ranked), returns, basis, raw)
        self.assertEqual(json.loads(result[1])['records'], json.loads(basis)['records'])
        before = {v['ticker']: v for v in json.loads(raw)['records']}
        for record in json.loads(result[2])['records']:
            for kind, value in record['products'].items():
                self.assertEqual(value['content_sha256'], before[record['ticker']]['products'][kind]['content_sha256'])
                self.assertEqual(value['content_utf8'], before[record['ticker']]['products'][kind]['content_utf8'])
                self.assertFalse(value['publication_eligible'])


if __name__ == '__main__':
    unittest.main()
