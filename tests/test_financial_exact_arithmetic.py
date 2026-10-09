"""Retained-number arithmetic through the SEC-wire/report CLI; no precision admission."""
import copy
import json
import sys
import tempfile
import unittest
from decimal import Inexact, Overflow, ROUND_DOWN, Rounded, Underflow, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import company_financial_products as products
import v213_v21_progress_runner as runner
import test_financial_cashflow_bridge as cash_fixture
import test_financial_debt_bridge as debt_fixture
import test_financial_liquidity_bridge as liquidity_fixture
import test_v212_top20_report as fixtures

MAX_SAFE = 9007199254740991


class FinancialExactArithmeticTests(unittest.TestCase):
    def cli(self, folder, facts):
        return liquidity_fixture.FinancialLiquidityBridgeTests().cli(folder, facts)

    def debt(self, current, noncurrent, reported=None):
        rows = debt_fixture.FinancialDebtBridgeTests().facts()
        for row, value in zip(rows, (current, noncurrent, reported)):
            row['value'] = value
        return rows if reported is not None else rows[:2]

    def cash(self, cfo, ppe, net):
        rows = cash_fixture.FinancialCashflowBridgeTests().facts()
        for row, value in zip(rows, (cfo, ppe, net)):
            row['value'] = value
        return rows

    def checked(self, folder, facts):
        report, basis, raw = self.cli(folder, facts)
        products.verify_financial_products(raw, report, basis)
        company = json.loads(basis)['records']['T00']
        values = json.loads(raw)['records'][0]['products']
        for value in values.values():
            self.assertFalse(value['publication_eligible']); self.assertFalse(value['complete'])
            self.assertIsNone(value['snapshot_run_id'])
            if value['status'] == 'UNAVAILABLE':
                self.assertIsNone(value['content_utf8']); self.assertEqual(value['pages'], [])
            else:
                self.assertEqual('\n\n'.join(p['text'] for p in value['pages']), value['content_utf8'])
        self.assertFalse(company['source_refresh_verified'])
        self.assertIsNone(company['source_retrieved_at'])
        return company, values

    def test_actual_cli_small_debt_difference_is_not_decimal_rounded_into_matched(self):
        h = fixtures.V212Top20ReportTests()
        support = [h.fact(), h.fact(tag='OperatingIncomeLoss', value=12), h.fact(tag='NetIncomeLoss', value=20)]
        for small in (1e-30, 5e-324):
            with self.subTest(small=small), tempfile.TemporaryDirectory() as tmp:
                company, values = self.checked(tmp, self.debt(small, 70, 70) + support)
                debt = company['debt_bridge']
                self.assertEqual(debt['observations']['current_debt']['operand']['value'], small)
                self.assertEqual(debt['reported_total_check']['status'], 'CONFLICT',
                                 'ACTUAL_CLI_DECIMAL_ROUNDING_FALSE_MATCH')
                self.assertTrue(all(v['status'] == 'WITHHELD_REPORTED_TOTAL_CONFLICT' and v['value'] is None
                                    for v in debt['metrics'].values()))
                for value in values.values():
                    self.assertIn('CONFLICT', value['content_utf8'])
                    self.assertIn('原始披露精度尚未核驗', value['content_utf8'])
                self.assertIn('operating_margin', values['narrative_analysis']['claim_refs'])
                self.assertNotIn('debt.long_term_components_sum', values['narrative_analysis']['claim_refs'])

    def test_actual_cli_debt_bound_is_checked_before_any_rounding(self):
        for small in (0.25, 1e-30, 5e-324):
            with self.subTest(small=small), tempfile.TemporaryDirectory() as tmp:
                company, _ = self.checked(tmp, self.debt(small, MAX_SAFE))
                debt = company['debt_bridge']
                self.assertEqual(debt['reported_total_check']['status'], 'UNSAFE_COMPONENT_SUM',
                                 'ACTUAL_CLI_DEBT_SUM_ROUNDED_INSIDE_SAFE_BOUND')
                self.assertTrue(all(v['status'] == 'WITHHELD_UNSAFE_RESULT' and v['value'] is None
                                    for v in debt['metrics'].values()))

    def test_actual_cli_cash_subtraction_bound_precedes_float_conversion(self):
        for ppe in (0.25, 1e-30, 5e-324):
            with self.subTest(ppe=ppe), tempfile.TemporaryDirectory() as tmp:
                company, values = self.checked(tmp, self.cash(-MAX_SAFE, ppe, 20))
                metric = company['cashflow_bridge']['metrics']['cash_after_ppe']
                self.assertEqual(metric['status'], 'WITHHELD_UNSAFE_RESULT',
                                 'ACTUAL_CLI_CASH_SUBTRACTION_ROUNDED_INSIDE_SAFE_BOUND')
                self.assertIsNone(metric['value'])
                self.assertNotIn('cashflow.cash_after_ppe', values['narrative_analysis']['claim_refs'])
                self.assertIn('WITHHELD_UNSAFE_RESULT', values['data_report']['content_utf8'])

    def test_actual_cli_nonzero_cash_conversion_cannot_underflow_into_zero(self):
        for cfo in (5e-324, -5e-324):
            with self.subTest(cfo=cfo), tempfile.TemporaryDirectory() as tmp:
                company, values = self.checked(tmp, self.cash(cfo, 0, MAX_SAFE))
                metrics = company['cashflow_bridge']['metrics']
                self.assertEqual(metrics['cash_conversion']['status'], 'WITHHELD_UNSAFE_RESULT',
                                 'ACTUAL_CLI_NONZERO_CASH_RATIO_PUBLISHED_AS_ZERO')
                self.assertIsNone(metrics['cash_conversion']['value'])
                self.assertEqual(metrics['cash_after_ppe']['value'], cfo)
                self.assertNotIn('cashflow.cash_conversion', values['narrative_analysis']['claim_refs'])

    def test_true_zero_small_representable_values_and_decimal_sum_remain_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            company, _ = self.checked(tmp, self.debt(0.1, 0.2, 0.3) + self.cash(0.3, 0.2, 3))
        self.assertEqual(company['debt_bridge']['reported_total_check']['status'], 'MATCHED')
        self.assertEqual(company['debt_bridge']['metrics']['long_term_components_sum']['value'], 0.3)
        self.assertEqual(company['cashflow_bridge']['metrics']['cash_after_ppe']['value'], 0.1)
        self.assertEqual(company['cashflow_bridge']['metrics']['cash_conversion']['value'], 0.1)
        for cfo, expected in ((0, 0), (5e-324, 5e-324), (-5e-324, -5e-324)):
            with self.subTest(cfo=cfo), tempfile.TemporaryDirectory() as tmp:
                company, _ = self.checked(tmp, self.cash(cfo, 0, 1))
                metric = company['cashflow_bridge']['metrics']['cash_conversion']
                self.assertEqual(metric['status'], 'AVAILABLE'); self.assertEqual(metric['value'], expected)

    def test_replay_rejects_old_false_match_unsafe_sum_and_zero_ratio(self):
        cases = [('debt', self.debt(1e-30, 70, 70)),
                 ('debt', self.debt(5e-324, MAX_SAFE)),
                 ('cashflow', self.cash(-MAX_SAFE, 0.25, 20)),
                 ('cashflow', self.cash(5e-324, 0, MAX_SAFE))]
        for index, (bridge, rows) in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                company, _ = self.checked(tmp, rows)
                forged = copy.deepcopy(company[bridge + '_bridge'])
                if index == 0:
                    forged['reported_total_check']['status'] = 'MATCHED'
                    forged['metrics']['long_term_components_sum'].update(status='AVAILABLE', value=70.0)
                    forged['metrics']['current_portion_fraction'].update(status='AVAILABLE', value=float(1e-30 / 70))
                elif index == 1:
                    forged['reported_total_check']['status'] = 'NOT_REPORTED'
                    forged['metrics']['long_term_components_sum'].update(status='AVAILABLE', value=float(MAX_SAFE))
                else:
                    key = 'cash_after_ppe' if index == 2 else 'cash_conversion'
                    forged['metrics'][key].update(status='AVAILABLE', value=-float(MAX_SAFE) if index == 2 else 0.0)
                validator = getattr(runner, 'validate_' + bridge + '_evidence')
                with self.assertRaisesRegex(runner.engine.PipelineError, '^' + bridge.upper() + '_EVIDENCE_INVALID$'):
                    validator(forged, cik=forged['cik'], as_of=forged['as_of_cutoff'])
                basis = json.loads((Path(tmp) / 'report.financial-evidence-candidate.json').read_bytes())
                basis['records']['T00'][bridge + '_bridge'] = forged
                with self.assertRaisesRegex(products.FinancialProductsError, '^FINANCIAL_PRODUCTS_' + bridge.upper() + '_INVALID$'):
                    products.build_financial_products((Path(tmp) / 'report.json').read_bytes(), products.canonical(basis))

    def test_bridge_math_and_replay_do_not_depend_on_ambient_decimal_context(self):
        # Arithmetic/replay only; not certification of every formatter or raw XML precision.
        liquidity = liquidity_fixture.FinancialLiquidityBridgeTests().facts()
        liquidity[1]['value'] = 170  # Nonterminating ratio, not the exact-decimal 120/150 control.
        samples = [
            (runner.debt_evidence, runner.validate_debt_evidence, self.debt(1111, 2222, 3333)),
            (runner.debt_evidence, runner.validate_debt_evidence, self.debt(1e-30, 70, 70)),
            (runner.cashflow_evidence, runner.validate_cashflow_evidence, self.cash(41, 61, 21)),
            (runner.liquidity_evidence, runner.validate_liquidity_evidence, liquidity),
        ]
        for evidence, validate, rows in samples:
            expected = evidence(rows, cik='0000000001', as_of='2026-09-10T00:00:00Z')
            for precision, trap in ((2, False), (4, True), (50, True)):
                with self.subTest(bridge=evidence.__name__, precision=precision), localcontext() as ctx:
                    ctx.prec = precision; ctx.rounding = ROUND_DOWN; ctx.Emin = -2; ctx.Emax = 2
                    for signal in (Inexact, Rounded, Underflow, Overflow): ctx.traps[signal] = trap
                    ctx.clear_flags()
                    actual = evidence(rows, cik='0000000001', as_of='2026-09-10T00:00:00Z')
                    self.assertEqual(actual, expected, 'BRIDGE_MATH_DEPENDS_ON_AMBIENT_DECIMAL_CONTEXT')
                    validate(expected, cik=expected['cik'], as_of=expected['as_of_cutoff'])
                    self.assertFalse(any(ctx.flags.values()), 'BRIDGE_MATH_MUTATES_AMBIENT_DECIMAL_FLAGS')

    def test_extreme_liquidity_and_debt_ratios_refuse_without_overflow_or_false_zero(self):
        for a, b, expected in ((MAX_SAFE, 5e-324, 'WITHHELD_UNSAFE_RESULT'),
                               (5e-324, MAX_SAFE, 'WITHHELD_UNSAFE_RESULT'),
                               (0, MAX_SAFE, 'AVAILABLE')):
            with self.subTest(a=a, b=b), tempfile.TemporaryDirectory() as tmp:
                liquidity = liquidity_fixture.FinancialLiquidityBridgeTests().facts()
                liquidity[0]['value'] = a; liquidity[1]['value'] = b
                company, _ = self.checked(tmp, liquidity)
                metric = company['liquidity_bridge']['metrics']['current_ratio']
                self.assertEqual(metric['status'], expected)
                self.assertEqual(metric['value'], 0 if expected == 'AVAILABLE' else None)
        rows = self.debt(5e-324, 70)
        with tempfile.TemporaryDirectory() as tmp:
            company, _ = self.checked(tmp, rows)
        self.assertEqual(company['debt_bridge']['reported_total_check']['status'], 'NOT_REPORTED')
        self.assertEqual(company['debt_bridge']['metrics']['current_portion_fraction']['status'], 'WITHHELD_UNSAFE_RESULT')
        self.assertIsNone(company['debt_bridge']['metrics']['current_portion_fraction']['value'])


if __name__ == '__main__':
    unittest.main()
