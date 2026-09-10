"""Public synthetic cashflow/SEC caller tests; not fresh-source or release proof."""
import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v213_v21_progress_runner as runner
import company_financial_products as products
import build_v212_top20_report as builder
import test_v212_top20_report as report_fixture


class FinancialCashflowBridgeTests(unittest.TestCase):
    def facts(self):
        helper = report_fixture.V212Top20ReportTests()
        return [helper.fact(tag=runner.CASHFLOW_TAGS[key][0], value=value,
                            unit='shares' if 'shares' in key else 'USD')
                for key, value in [('operating_cashflow', 40), ('ppe_payments', 60),
                                   ('net_income', 20), ('sbc', 5), ('basic_shares', 100), ('diluted_shares', 110)]]

    def evidence(self, facts=None):
        return runner.cashflow_evidence(self.facts() if facts is None else facts,
                                        cik='0000000001', as_of='2026-09-10T00:00:00Z')

    def test_signed_arithmetic_units_operands_and_replay(self):
        value = self.evidence()
        self.assertEqual(value['metrics']['cash_after_ppe']['value'], -20)
        self.assertEqual(value['metrics']['cash_after_ppe']['value_unit'], 'USD')
        self.assertEqual(value['metrics']['cash_conversion']['value'], 2)
        self.assertEqual(value['metrics']['diluted_share_increment']['value'], 0.1)
        self.assertEqual(len(value['observations']), 6)
        self.assertFalse(value['publication_eligible'])
        self.assertFalse(value['source_refresh_verified'])
        self.assertIsNone(value['source_retrieved_at'])
        runner.validate_cashflow_evidence(value, cik=value['cik'], as_of=value['as_of_cutoff'])

    def test_negative_and_zero_cfo_are_observations_not_missing_or_positive(self):
        for cfo in (-10, 0, 60, 80):
            rows = self.facts(); rows[0]['value'] = cfo
            doc = self.evidence(rows)
            self.assertEqual(doc['metrics']['cash_after_ppe']['value'], cfo - 60)
            self.assertEqual(doc['metrics']['cash_conversion']['value'], cfo / 20)
        rows = self.facts(); rows[1]['value'] = 0
        self.assertEqual(self.evidence(rows)['metrics']['cash_after_ppe']['value'], 40)

    def test_invalid_ppe_and_shares_are_not_abs_coerced_or_zero_filled(self):
        for index, values in [(1, (-60, True, '60', None, float('nan'), float('inf'), 2**53)),
                              (4, (-1, 0, True, '100'))]:
            for value in values:
                rows = self.facts(); rows[index]['value'] = value
                doc = self.evidence(rows)
                key = 'ppe_payments' if index == 1 else 'basic_shares'
                self.assertEqual(doc['observations'][key]['status'], 'INVALID_OPERAND')
                self.assertIsNone(doc['observations'][key]['operand'])
                json.dumps(doc, allow_nan=False)

    def test_nonpositive_net_denominator_and_below_basic_diluted_shares_withheld(self):
        for net in (0, -20):
            rows = self.facts(); rows[2]['value'] = net
            doc = self.evidence(rows)
            self.assertEqual(doc['metrics']['cash_conversion']['status'], 'WITHHELD_NONPOSITIVE_DENOMINATOR')
            self.assertIsNone(doc['metrics']['cash_conversion']['value'])
            self.assertEqual(doc['metrics']['cash_after_ppe']['value'], -20)
        rows = self.facts(); rows[5]['value'] = 90
        self.assertEqual(self.evidence(rows)['metrics']['diluted_share_increment']['status'], 'WITHHELD_DILUTED_BELOW_BASIC')

    def test_ytd_anchor_selects_exact_same_cohort_period_not_a_quarter(self):
        rows = self.facts()
        quarter = {**rows[2], 'start': '2026-04-01', 'value': 500}
        for data in (rows + [quarter], [quarter] + rows):
            value = self.evidence(data)
            self.assertEqual(value['metrics']['cash_conversion']['value'], 2)
            self.assertEqual(value['observations']['net_income']['operand']['start'], '2025-07-01')
        rows[2] = quarter
        self.assertEqual(self.evidence(rows)['metrics']['cash_conversion']['status'], 'WITHHELD_NOT_COMPARABLE')

    def test_ambiguous_cfo_and_alias_cohorts_never_depend_on_sort_order(self):
        for changed in ({'start': '2026-01-01'}, {'unit': 'EUR'}, {'accession_number': '0000000001-26-000002'}):
            rows = self.facts(); other = {**rows[0], **changed}
            for data in (rows + [other], [other] + rows):
                self.assertEqual(self.evidence(data)['observations']['operating_cashflow']['status'], 'AMBIGUOUS_OPERAND')
        rows = self.facts(); rows.append({**rows[2], 'tag': 'ProfitLoss'})
        self.assertEqual(self.evidence(rows)['observations']['net_income']['status'], 'AMBIGUOUS_OPERAND')

    def test_duplicate_values_ok_but_conflicting_selected_values_fail_in_both_orders(self):
        rows = self.facts()
        self.assertEqual(self.evidence(rows + [dict(rows[0])]), self.evidence(rows))
        other = {**rows[0], 'value': 999}
        for data in (rows + [other], [other] + rows):
            value = self.evidence(data)
            self.assertEqual(value['observations']['operating_cashflow']['status'], 'CONFLICTING_OPERAND')
            self.assertEqual(value['metrics']['cash_after_ppe']['status'], 'WITHHELD_REQUIRED_OPERAND')

    def test_latest_invalid_never_rescues_an_older_success(self):
        for change in ({'value': True}, {'filed': '9999-01-01'}, {'form': '8-K'}, {'unit': None}):
            rows = self.facts()
            old = {**rows[0], 'end': '2025-06-30', 'start': '2024-07-01', 'filed': '2025-07-29'}
            rows[0].update(change)
            self.assertEqual(self.evidence(rows + [old])['observations']['operating_cashflow']['status'], 'INVALID_OPERAND')

    def test_no_cross_currency_filing_period_or_source_division(self):
        for change in ({'unit': 'EUR'}, {'filed': '2026-08-01'}, {'form': '10-Q'},
                       {'accession_number': '0000000001-26-000002'}, {'start': '2026-01-01'},
                       {'record_url': 'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/'}):
            rows = self.facts(); rows[1].update(change)
            self.assertEqual(self.evidence(rows)['metrics']['cash_after_ppe']['status'], 'WITHHELD_NOT_COMPARABLE')
        rows = self.facts(); rows[5]['start'] = '2026-01-01'
        self.assertEqual(self.evidence(rows)['metrics']['diluted_share_increment']['status'], 'WITHHELD_NOT_COMPARABLE')

    def test_invalid_identity_locator_and_date_never_survive_projection(self):
        for change in ({'cik': '0000000002'}, {'record_url': 'https://www.sec.gov/x?token=SYNTHETIC_PRIVATE_MARKER'},
                       {'accession_number': 'bad'}, {'filed': '2026-07-29suffix'}, {'start': None},
                       {'end': '2026-02-30'}, {'form': ['10-K']}):
            rows = self.facts(); rows[0].update(change)
            value = self.evidence(rows)
            self.assertEqual(value['observations']['operating_cashflow']['status'], 'INVALID_OPERAND')
            self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(value))

    def test_missing_is_explicit_and_never_substitutes_net_investing_cashflow(self):
        rows = self.facts(); rows[1]['tag'] = 'NetCashProvidedByUsedInInvestingActivities'
        doc = self.evidence(rows)
        self.assertEqual(doc['observations']['ppe_payments']['status'], 'MISSING_OPERAND')
        self.assertIsNone(doc['metrics']['cash_after_ppe']['value'])
        self.assertEqual(self.evidence([])['observations']['sbc']['status'], 'MISSING_OPERAND')

    def test_unsafe_derived_values_are_withheld_not_rounded_into_safe_range(self):
        rows = self.facts(); rows[0]['value'] = -9007199254740991; rows[1]['value'] = 9007199254740991
        self.assertEqual(self.evidence(rows)['metrics']['cash_after_ppe']['status'], 'WITHHELD_UNSAFE_RESULT')
        rows = self.facts(); rows[2]['value'] = 1e-310
        doc = self.evidence(rows)
        self.assertEqual(doc['metrics']['cash_conversion']['status'], 'WITHHELD_UNSAFE_RESULT')
        self.assertIsNone(doc['metrics']['cash_conversion']['value'])
        json.dumps(doc, allow_nan=False)

    def test_replay_rejects_forged_results_extensions_or_released_candidate(self):
        original = self.evidence()
        changes = [lambda d: d['metrics']['cash_after_ppe'].update(value=999),
                   lambda d: d['metrics']['cash_conversion'].update(value=True),
                   lambda d: d.update(publication_eligible=True), lambda d: d.update(schema_version=True),
                   lambda d: d.update(cik='0000000002'), lambda d: d.update(as_of_cutoff='2000-01-01T00:00:00Z'),
                   lambda d: d['observations']['sbc']['operand'].update(account='SYNTHETIC_PRIVATE_MARKER'),
                   lambda d: d['observations']['ppe_payments'].update(status='MISSING_OPERAND')]
        for change in changes:
            doc = copy.deepcopy(original); change(doc)
            with self.assertRaises((runner.engine.PipelineError, ValueError)) as error:
                runner.validate_cashflow_evidence(doc, cik='0000000001', as_of=original['as_of_cutoff'])
            self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', str(error.exception))
        rows = self.facts(); rows.append({**rows[0], 'value': 999})
        failed = self.evidence(rows)
        runner.validate_cashflow_evidence(failed, cik=failed['cik'], as_of=failed['as_of_cutoff'])
        self.assertIsNone(failed['metrics']['cash_after_ppe']['value'])

    def test_adapter_metric_boundary_rejects_noncanonical_timestamp_not_clips(self):
        row = self.facts()[0]
        normalized = {**row, **{k: row[k] + 'T00:00:00+00:00' for k in ('start', 'end', 'filed')}}
        for bad in ('2026-06-30T01:00:00+00:00', '2026-06-30T00:00:00+08:00',
                    '2026-06-30T00:00:00Z', '2026-06-30T00:00:00+00:00suffix', '2026-06-30'):
            with patch.object(builder.base, 'parse_source_payload', return_value=SimpleNamespace(records=[{**normalized, 'end': bad}])):
                with self.assertRaisesRegex(builder.base.PipelineError, 'SEC_ADAPTER_METRIC_DATE_INVALID'):
                    builder.base.validate_sec_adapter({}, 'https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json')

    def test_actual_cli_replaces_previous_cashflow_with_missing_and_keeps_whole_pages(self):
        helper = report_fixture.V212Top20ReportTests(); original = builder.build
        rows = [helper.fact(), helper.fact(tag='OperatingIncomeLoss', value=12), *self.facts()]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            for facts in (rows, [r for r in rows if r['tag'] != runner.CASHFLOW_TAGS['ppe_payments'][0]]):
                with patch.object(builder, 'build', side_effect=lambda **kw: helper.actual_report(facts, wire=True, _build=original, **kw)), \
                        patch.object(sys, 'argv', ['build', '--output', str(output)]), redirect_stdout(StringIO()):
                    self.assertEqual(builder.main(), 0)
                doc = json.loads(output.with_name('report.financial-products-candidate.json').read_bytes())
                for value in doc['records'][0]['products'].values():
                    self.assertEqual('\n\n'.join(p['text'] for p in value['pages']), value['content_utf8'])
                    self.assertIn('來源與限制', value['content_utf8'])
                    self.assertFalse(value['publication_eligible'])
                    self.assertTrue(all(len(p['text'].encode('utf-16-le')) // 2 <= 4400 for p in value['pages']))
            basis = json.loads(output.with_name('report.financial-evidence-candidate.json').read_bytes())
            self.assertIsNone(basis['records']['T00']['cashflow_bridge']['metrics']['cash_after_ppe']['value'])
            self.assertIn('MISSING_OPERAND', doc['records'][0]['products']['data_report']['content_utf8'])
            self.assertNotIn('支出高於營業現金流', doc['records'][0]['products']['narrative_analysis']['content_utf8'])

    def test_cashflow_analysis_can_stand_without_margin_inputs_but_does_not_guess_them(self):
        helper = report_fixture.V212Top20ReportTests(); sink = {}
        report = helper.actual_report(self.facts(), wire=True, financial_evidence_sink=sink)
        raw = builder.json_bytes(report)
        basis = dict(schema_version=1, status='CANDIDATE_NOT_PUBLICATION_QUALIFIED', publication_eligible=False,
                     provider_scope='public_only', owner_watchlist_inherited=False, generated_at=report['generated_at'],
                     report_sha256=products.sha256(raw), hash_scope='v212 report UTF-8 bytes, not source HTTP or sealed snapshot', records=sink)
        doc = products.build_financial_products(raw, builder.json_bytes(basis))
        narrative = doc['records'][0]['products']['narrative_analysis']
        self.assertEqual(narrative['status'], 'AVAILABLE_PARTIAL')
        self.assertIn('cashflow.cash_after_ppe', narrative['claim_refs'])
        self.assertIn('支出高於營業現金流', narrative['content_utf8'])
        self.assertNotIn('營益率', narrative['content_utf8'])
        cash = self.evidence()
        text = '\n'.join(products._cash_analysis(cash))
        self.assertIn('支出高於營業現金流', text)
        self.assertNotIn('營益率', text)
        self.assertIn('不是本期新發股比例', text)
        self.assertIn('不機械從CFO再扣一次', text)
        self.assertIn('原報表位置及是否已列入CFO調整須查附註', text)
        for cfo, phrase in ((-10, '正淨利伴隨營業現金淨流出'), (0, '營業現金流小於所選正淨利'),
                            (60, '淨額為零'), (80, '仍為正')):
            rows = self.facts(); rows[0]['value'] = cfo
            self.assertIn(phrase, '\n'.join(products._cash_analysis(self.evidence(rows))))

    def test_legacy_v1_candidate_is_explicitly_readable_not_silently_upgraded(self):
        helper = report_fixture.V212Top20ReportTests(); sink = {}
        report = helper.actual_report([helper.fact(), helper.fact(tag='NetIncomeLoss', value=20)], financial_evidence_sink=sink)
        for company in sink.values():
            company.pop('cashflow_bridge'); company.pop('source_acquisition'); company.pop('liquidity_bridge')
            company.update(schema_version=1, limitations=list(products.LIMITATIONS))
        raw = builder.json_bytes(report)
        basis = dict(schema_version=1, status='CANDIDATE_NOT_PUBLICATION_QUALIFIED', publication_eligible=False,
                     provider_scope='public_only', owner_watchlist_inherited=False, generated_at=report['generated_at'],
                     report_sha256=products.sha256(raw), hash_scope='v212 report UTF-8 bytes, not source HTTP or sealed snapshot', records=sink)
        doc = products.build_financial_products(raw, builder.json_bytes(basis))
        self.assertIn('舊版財務依據未保留現金流組件', doc['records'][0]['products']['data_report']['content_utf8'])
        self.assertEqual(doc['records'][0]['products']['narrative_analysis']['status'], 'UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
