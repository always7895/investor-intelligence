"""Actual report CLI with synthetic public SEC instants; not source/LINE qualification."""
import copy
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
import build_v212_top20_report as builder
import company_financial_products as products
import v213_v21_progress_runner as runner
import test_v212_top20_report as fixtures


class FinancialLiquidityBridgeTests(unittest.TestCase):
    def facts(self):
        helper = fixtures.V212Top20ReportTests()
        return [helper.fact(tag=tag, value=value, start=None) for tag, value in
                [('AssetsCurrent', 120), ('LiabilitiesCurrent', 150),
                 ('CashAndCashEquivalentsAtCarryingValue', 30)]]

    def cli(self, folder, facts=None):
        helper = fixtures.V212Top20ReportTests(); original = builder.build
        output = Path(folder) / 'report.json'
        with patch.object(builder, 'build', side_effect=lambda **kw: helper.actual_report(
                self.facts() if facts is None else facts, wire=True, _build=original, **kw)), \
                patch.object(sys, 'argv', ['build', '--output', str(output)]), redirect_stdout(StringIO()):
            self.assertEqual(builder.main(), 0)
        report = output.read_bytes()
        basis = output.with_name('report.financial-evidence-candidate.json').read_bytes()
        content = output.with_name('report.financial-products-candidate.json').read_bytes()
        return report, basis, content

    def test_actual_wire_to_cli_retains_instant_operands_not_duration_fiction(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, raw, _ = self.cli(tmp)
        company = json.loads(raw)['records']['T00']
        self.assertIn('liquidity_bridge', company, 'ACTUAL_CLI_DROPS_DISCLOSED_LIQUIDITY_INSTANTS')
        bridge = company['liquidity_bridge']
        self.assertEqual(bridge['metrics']['working_capital']['value'], -30)
        self.assertEqual(bridge['metrics']['current_ratio']['value'], 0.8)
        for value in bridge['observations'].values():
            self.assertIsNone(value['operand']['start'])
            self.assertEqual(value['operand']['end'], '2026-06-30')

    def test_actual_cli_can_explain_liquidity_without_inventing_missing_profit_or_cashflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp)
        products.verify_financial_products(raw, report, basis)
        values = json.loads(raw)['records'][0]['products']
        narrative = values['narrative_analysis']
        self.assertEqual(narrative['status'], 'AVAILABLE_PARTIAL', 'CLI_WITHHOLDS_ALL_ANALYSIS_DESPITE_COMPARABLE_BALANCES')
        self.assertIn('liquidity.working_capital', narrative['claim_refs'])
        self.assertIn('流動負債高於流動資產', narrative['content_utf8'])
        self.assertNotIn('營益率', narrative['content_utf8'])
        self.assertEqual(len({v['content_sha256'] for v in values.values()}), 3)
        for value in values.values():
            self.assertFalse(value['publication_eligible']); self.assertFalse(value['complete'])
            self.assertEqual('\n\n'.join(p['text'] for p in value['pages']), value['content_utf8'])
            self.assertIn('來源與限制', value['content_utf8'])

    def evidence(self, rows=None):
        return runner.liquidity_evidence(self.facts() if rows is None else rows,
                                         cik='0000000001', as_of='2026-09-10T00:00:00Z')

    def test_instant_requires_explicit_mode_and_null_start_not_a_duration_or_absent_key(self):
        row = self.facts()[0]
        self.assertEqual(runner.financial_operand(row, [], cik=row['cik'], cutoff_day='2026-09-10')[1], 'INVALID_OPERAND')
        checked, error = runner.financial_operand(row, [], cik=row['cik'], cutoff_day='2026-09-10', instant=True)
        self.assertIsNone(error); self.assertIsNone(checked['start'])
        for start in ('2025-07-01', '', True, '2026-06-30'):
            rows = self.facts(); rows[0]['start'] = start
            self.assertEqual(self.evidence(rows)['observations']['current_assets']['status'], 'INVALID_OPERAND')
        rows = self.facts(); del rows[0]['start']
        self.assertEqual(self.evidence(rows)['observations']['current_assets']['status'], 'INVALID_OPERAND')

    def test_zero_and_signed_gap_are_not_missing_or_infinite_liquidity(self):
        for assets, liabilities, difference, ratio in [(120, 150, -30, .8), (180, 150, 30, 1.2),
                                                     (150, 150, 0, 1), (0, 150, -150, 0), (0, 0, 0, None)]:
            rows = self.facts(); rows[0]['value'] = assets; rows[1]['value'] = liabilities
            doc = self.evidence(rows)
            self.assertEqual(doc['metrics']['working_capital']['value'], difference)
            self.assertEqual(doc['metrics']['current_ratio']['value'], ratio)
            if ratio is None:
                self.assertEqual(doc['metrics']['current_ratio']['status'], 'WITHHELD_NONPOSITIVE_DENOMINATOR')
            runner.validate_liquidity_evidence(doc, cik=doc['cik'], as_of=doc['as_of_cutoff'])
        self.assertIn('差額為零', '\n'.join(products._liquidity_blocks(self.evidence(rows), 'narrative_analysis')))

    def test_invalid_values_and_identities_never_survive_or_rescue_older_values(self):
        changes = [{'value': v} for v in [-1, True, '120', None, float('nan'), float('inf'), 2**53]] + [
            {'cik': '0000000002'}, {'unit': None}, {'unit': 'shares'}, {'filed': '9999-01-01'},
            {'filed': '2026-07-29suffix'}, {'end': '2026-02-30'}, {'form': '8-K'}, {'fiscal_year': True},
            {'accession_number': 'bad'}, {'record_url': 'https://example.test/SYNTHETIC_PRIVATE_MARKER'}]
        for change in changes:
            with self.subTest(change=change):
                rows = self.facts(); old = {**rows[0], 'end': '2025-06-30', 'filed': '2025-07-29'}; rows[0].update(change)
                doc = self.evidence(rows + [old])
                self.assertEqual(doc['observations']['current_assets']['status'], 'INVALID_OPERAND')
                self.assertIsNone(doc['observations']['current_assets']['operand'])
                self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(doc, allow_nan=False))

    def test_duplicates_and_conflicts_are_order_independent(self):
        rows = self.facts()
        self.assertEqual(self.evidence(rows + [dict(rows[0])]), self.evidence(rows))
        other = {**rows[0], 'value': 999}
        for values in (rows + [other], [other] + rows):
            doc = self.evidence(values)
            self.assertEqual(doc['observations']['current_assets']['status'], 'CONFLICTING_OPERAND')
            self.assertEqual(doc['metrics']['working_capital']['status'], 'WITHHELD_REQUIRED_OPERAND')
            runner.validate_liquidity_evidence(doc, cik=doc['cik'], as_of=doc['as_of_cutoff'])

    def test_latest_cohort_ambiguity_is_not_fixed_by_sort_order_or_an_older_match(self):
        for change in ({'unit': 'EUR'}, {'accession_number': '0000000001-26-000002'}, {'form': '10-Q'}):
            rows = self.facts(); other = {**rows[0], **change}
            for values in (rows + [other], [other] + rows):
                self.assertEqual(self.evidence(values)['observations']['current_assets']['status'], 'AMBIGUOUS_OPERAND')
        rows = self.facts(); old = dict(rows[1]); rows[1]['filed'] = '2026-08-01'
        self.assertEqual(self.evidence(rows + [old])['metrics']['current_ratio']['status'], 'WITHHELD_NOT_COMPARABLE')

    def test_no_cross_currency_instant_filing_form_fiscal_year_or_locator_calculation(self):
        for change in ({'unit': 'EUR'}, {'end': '2026-03-31'}, {'filed': '2026-08-01'}, {'form': '10-Q'},
                       {'fiscal_year': 2025}, {'accession_number': '0000000001-26-000002'},
                       {'record_url': 'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/'}):
            rows = self.facts(); rows[1].update(change)
            doc = self.evidence(rows)
            for value in doc['metrics'].values():
                self.assertEqual(value['status'], 'WITHHELD_NOT_COMPARABLE'); self.assertIsNone(value['value'])

    def test_total_assets_and_restricted_cash_are_not_replacement_tags(self):
        rows = self.facts(); rows[0]['tag'] = 'Assets'; rows[1]['tag'] = 'Liabilities'; rows[2]['tag'] = 'RestrictedCash'
        doc = self.evidence(rows)
        self.assertTrue(all(v['status'] == 'MISSING_OPERAND' for v in doc['observations'].values()))
        self.assertTrue(all(v['value'] is None for v in doc['metrics'].values()))
        self.assertFalse(doc['source_refresh_verified']); self.assertIsNone(doc['source_retrieved_at'])

    def test_ratio_overflow_and_nonzero_underflow_are_withheld_not_zero_or_infinity(self):
        for assets, liabilities in [(120, 1e-310), (5e-324, 9007199254740991)]:
            rows = self.facts(); rows[0]['value'] = assets; rows[1]['value'] = liabilities
            doc = self.evidence(rows)
            self.assertEqual(doc['metrics']['current_ratio']['status'], 'WITHHELD_UNSAFE_RESULT')
            self.assertIsNone(doc['metrics']['current_ratio']['value']); json.dumps(doc, allow_nan=False)

    def test_replay_refuses_changed_math_extensions_flags_and_identity(self):
        original = self.evidence()
        changes = [lambda d: d['metrics']['working_capital'].update(value=30),
                   lambda d: d['metrics']['current_ratio'].update(value=True),
                   lambda d: d['metrics']['current_ratio'].update(value_unit='USD'),
                   lambda d: d.update(schema_version=True), lambda d: d.update(publication_eligible=True),
                   lambda d: d.update(source_refresh_verified=True), lambda d: d.update(cik='0000000002'),
                   lambda d: d.update(source_retrieved_at='2026-09-10T00:00:00Z'),
                   lambda d: d['observations']['cash_equivalents']['operand'].update(owner='SYNTHETIC_PRIVATE_MARKER'),
                   lambda d: d['observations']['current_liabilities']['operand'].update(value=-1),
                   lambda d: d['observations']['current_assets'].update(status='MISSING_OPERAND')]
        for change in changes:
            doc = copy.deepcopy(original); change(doc)
            with self.assertRaises((runner.engine.PipelineError, ValueError)) as error:
                runner.validate_liquidity_evidence(doc, cik=original['cik'], as_of=original['as_of_cutoff'])
            self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', str(error.exception))

    def test_actual_cli_missing_refresh_replaces_previous_liquidity_and_never_keeps_old_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.cli(tmp)
            report, basis, raw = self.cli(tmp, self.facts()[::2])
        doc = json.loads(raw); company = json.loads(basis)['records']['T00']
        self.assertEqual(company['liquidity_bridge']['observations']['current_liabilities']['status'], 'MISSING_OPERAND')
        self.assertEqual(doc['records'][0]['products']['narrative_analysis']['status'], 'UNAVAILABLE')
        self.assertIsNone(doc['records'][0]['products']['narrative_analysis']['content_utf8'])
        products.verify_financial_products(raw, report, basis)

    def test_actual_cli_only_cash_is_an_observation_not_an_invented_ratio_or_narrative(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp, [self.facts()[2]])
        doc = json.loads(raw)['records'][0]['products']
        self.assertEqual(doc['card_summary']['status'], 'AVAILABLE_PARTIAL')
        self.assertIn('現金及約當現金披露', doc['data_report']['content_utf8'])
        self.assertEqual(doc['narrative_analysis']['status'], 'UNAVAILABLE')
        products.verify_financial_products(raw, report, basis)

    def test_actual_cli_partial_liquidity_must_not_discard_comparable_profit_analysis(self):
        helper = fixtures.V212Top20ReportTests()
        profit = [helper.fact(), helper.fact(tag='OperatingIncomeLoss', value=12), helper.fact(tag='NetIncomeLoss', value=20)]
        incompatible = self.facts(); incompatible[1]['unit'] = 'EUR'
        for rows in ([self.facts()[2]], self.facts()[::2], incompatible):
            with self.subTest(tags=[r['tag'] for r in rows]), tempfile.TemporaryDirectory() as tmp:
                report, basis, raw = self.cli(tmp, rows + profit)
                narrative = json.loads(raw)['records'][0]['products']['narrative_analysis']
                self.assertEqual(narrative['status'], 'AVAILABLE_PARTIAL', 'PARTIAL_LIQUIDITY_DISCARDS_COMPARABLE_PROFIT_ANALYSIS')
                self.assertIn('operating_margin', narrative['claim_refs'])
                self.assertIn('營益率', narrative['content_utf8'])
                self.assertNotIn('liquidity.working_capital', narrative['claim_refs'])
                products.verify_financial_products(raw, report, basis)

    def test_all_twenty_products_preserve_pages_dates_identity_and_candidate_flags(self):
        helper = fixtures.V212Top20ReportTests()
        rows = self.facts() + [helper.fact(), helper.fact(tag='OperatingIncomeLoss', value=12), helper.fact(tag='NetIncomeLoss', value=20)]
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp, rows)
        doc = json.loads(raw)
        for i, record in enumerate(doc['records']):
            self.assertEqual(record['ticker'], f'T{i:02}')
            for kind, value in record['products'].items():
                self.assertEqual(value['output_kind'], kind); self.assertEqual(value['subject']['ticker'], record['ticker'])
                self.assertFalse(value['publication_eligible']); self.assertFalse(value['complete']); self.assertIsNone(value['snapshot_run_id'])
                self.assertEqual('\n\n'.join(p['text'] for p in value['pages']), value['content_utf8'])
                self.assertTrue(0 < len(value['pages']) <= 5)
                self.assertTrue(all(len(p['text'].encode('utf-16-le')) // 2 <= 4400 for p in value['pages']))
                self.assertIn('來源與限制', value['content_utf8'])
        products.verify_financial_products(raw, report, basis)
        company = json.loads(basis)['records']['T00']
        self.assertEqual(company['schema_version'], 5); self.assertFalse(company['source_refresh_verified'])
        self.assertIsNone(company['source_acquisition'])
        self.assertEqual(json.loads(report)['records'][0]['source_acquisition']['profit_summary']['status'], 'UNKNOWN')

    def test_company1_2_3_remain_explicit_legacy_without_liquidity_upgrade(self):
        helper = fixtures.V212Top20ReportTests()
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, _ = self.cli(tmp, self.facts() + [helper.fact(), helper.fact(tag='NetIncomeLoss', value=20)])
        for version in (1, 2, 3):
            legacy = json.loads(basis)
            for company in legacy['records'].values():
                company.pop('liquidity_bridge'); company.pop('debt_bridge'); company['schema_version'] = version
                company['limitations'] = list(products.LIMITATIONS if version == 1 else runner.FINANCIAL_V2_LIMITATIONS)
                if version < 3: company.pop('source_acquisition')
                if version < 2: company.pop('cashflow_bridge')
            raw = builder.json_bytes(products.build_financial_products(report, builder.json_bytes(legacy)))
            products.verify_financial_products(raw, report, builder.json_bytes(legacy))
            self.assertNotIn('liquidity.', raw.decode())

    def test_rank_rebinding_preserves_liquidity_content_and_original_clocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, basis, raw = self.cli(tmp)
            returns = (Path(tmp) / 'report.return-evidence-candidate.json').read_bytes()
        ranked = json.loads(report); ranked['records'].reverse()
        for i, row in enumerate(ranked['records'], 1): row['rank'] = i
        result = builder.rebind_ranked_candidates(builder.json_bytes(ranked), returns, basis, raw)
        # Return/basis/product roles are shared with the actual finalizer.
        rebound = json.loads(result[2])
        original = {row['ticker']: row for row in json.loads(raw)['records']}
        self.assertEqual(rebound['records'][0]['ticker'], 'T19')
        for record in rebound['records']:
            for kind, value in record['products'].items():
                previous = original[record['ticker']]['products'][kind]
                self.assertEqual(value['content_sha256'], previous['content_sha256'])
                self.assertEqual(value['content_utf8'], previous['content_utf8'])
                self.assertFalse(value['publication_eligible'])
        rebased_basis = json.loads(result[1])
        self.assertEqual(rebased_basis['records'], json.loads(basis)['records'])


if __name__ == '__main__':
    unittest.main()
