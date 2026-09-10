from __future__ import annotations

import sys
import unittest
import json
import tempfile
from contextlib import ExitStack, redirect_stdout
from io import StringIO
import hashlib
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_v212_top20_report as builder
import build_v213_scheduled_top20_report as scheduled

from build_v212_top20_report import (  # noqa: E402
    DISPLAY_COLUMNS,
    LONG_TERM_WINDOW_DAYS,
    MIN_LONG_TERM_ELAPSED_DAYS,
    MIN_SHORT_TERM_ELAPSED_DAYS,
    SHORT_TERM_WINDOW_DAYS,
    profit_summary,
    translate_industry,
)


class V212Top20ReportTests(unittest.TestCase):
    def test_profit_summary_is_deterministic_and_public_metric_only(self) -> None:
        value = profit_summary(
            {
                "revenue_growth": 0.253,
                "operating_margin": 0.121,
                "net_margin": 0.083,
                "debt_to_equity": 0.5,
            }
        )
        self.assertEqual(
            value,
            "獲利；營收年增 +25.3%；營益率 12.1%；淨利率 8.3%",
        )
        self.assertNotIn("debt", value.lower())

    def test_loss_and_missing_metric_text(self) -> None:
        self.assertTrue(
            profit_summary({"revenue_growth": -0.1, "net_margin": -0.05}).startswith(
                "虧損；"
            )
        )
        self.assertEqual(profit_summary({}), "SEC 可用獲利指標不足")

    def test_return_windows_and_display_labels_are_explicit(self) -> None:
        self.assertEqual(LONG_TERM_WINDOW_DAYS, 730)
        self.assertEqual(SHORT_TERM_WINDOW_DAYS, 183)
        self.assertEqual(MIN_LONG_TERM_ELAPSED_DAYS, 730)
        self.assertEqual(MIN_SHORT_TERM_ELAPSED_DAYS, 181)
        self.assertEqual(
            DISPLAY_COLUMNS,
            [
                "股票",
                "長期投資報酬率（近2年年化）",
                "短期投資報酬率（近6個月）",
                "行業別",
                "獲利簡述",
            ],
        )
        module_text = (ROOT / "scripts" / "build_v212_top20_report.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('period="3y"', module_text)
        self.assertIn("legacy_return_pair(_history_return_evidence(history))", module_text)
        self.assertIn('auto_adjust=True', module_text)

    def fact(self, **changes):
        return dict(dict(record_type='company_fact', taxonomy='us-gaap', tag='Revenues', form='10-K',
                    start='2025-07-01', end='2026-06-30', filed='2026-07-29', fiscal_year=2026,
                    accession_number='0000000001-26-000001', cik='0000000001', unit='USD',
                    record_url='https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json', value=100.0), **changes)

    def wire_document(self, facts):
        tags = {}
        for fact in facts:
            units = tags.setdefault(fact['tag'], {'units': {}})['units']
            units.setdefault(fact['unit'], []).append({
                'val': fact['value'], 'start': fact['start'], 'end': fact['end'],
                'filed': fact['filed'], 'accn': fact['accession_number'],
                'form': fact['form'], 'fy': fact['fiscal_year'], 'fp': 'FY'})
        return {'cik': 1, 'entityName': 'Synthetic public issuer', 'facts': {'us-gaap': tags}}

    def actual_report(self, facts, _build=None, wire=False, **kwargs):
        rows = [{'ticker': f'T{i:02}', 'rank': i + 1} for i in range(20)]
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            source = Path(tmp) / 'top20.json'; source.write_text('[]', encoding='utf-8')
            stack.enter_context(patch.object(builder.snapshot, 'validate_top20', return_value=rows))
            policy = {'sec_companyfacts_url': 'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',
                      'sec_minimum_interval_seconds': 0}
            for name, value in [('validate_policy', (policy, {})), ('sec_headers', {}), ('session', None),
                                ('sec_reference', {r['ticker']: {'cik': '0000000001'} for r in rows})]:
                stack.enter_context(patch.object(builder.base, name, return_value=value))
            if wire:
                stack.enter_context(patch.object(builder.base, 'get_json', return_value=self.wire_document(facts)))
            else:
                stack.enter_context(patch.object(builder.base, 'sec_companyfacts', return_value=facts))
            stack.enter_context(patch.object(builder, '_market_observation', return_value=(None, None, '工業設備')))
            return (_build or builder.build)(top20_path=source, **kwargs)

    def test_actual_builder_and_seven_field_caller_do_not_reintroduce_mixed_basis_ratios(self):
        report = self.actual_report([self.fact(), self.fact(tag='NetIncomeLoss', unit='EUR', value=20.0)])
        self.assertEqual(report['records'][0]['profit_summary'], 'SEC 可用獲利指標不足')
        baseline = {'product_version': '2.1.3', 'records': [
            {'rank': row['rank'], 'ticker': row['ticker'], 'current_order_source_urls': [],
             'future_order_source_urls': [], 'current_orders': '未揭露（無可靠公開訂單數字）',
             'future_orders_estimate': '無可靠公開預估', 'orders_confidence': 'UNAVAILABLE', 'orders_as_of': ''}
            for row in report['records']]}
        self.assertIsNone(scheduled.build(report, baseline)['records'][0]['retrieved_at'])
        with self.assertRaises(scheduled.V213ScheduledReportError):
            scheduled.build(report, baseline, require_known_acquisition=True)  # No clock rescue at publication preflight.
        # Synthetic market-clock control only; no real source certification.
        for row in report['records']:
            row['source_acquisition']['industry'] = scheduled.field_clock('industry', row['industry'],
                retrieved_at=report['generated_at'], evidence_sha256='a'*64)
            row['retrieved_at'] = report['generated_at']
        seven = scheduled.build(report, baseline)
        self.assertEqual(seven['records'][0]['profit_summary'], 'SEC 可用獲利指標不足')

    def test_actual_sec_adapter_dates_reach_report_not_only_handwritten_records(self):
        sink = {}
        report = self.actual_report([self.fact(), self.fact(tag='NetIncomeLoss', value=20.0)],
                                    wire=True, financial_evidence_sink=sink)
        self.assertEqual(report['records'][0]['profit_summary'], '獲利；淨利率 20.0%')
        self.assertEqual(sink['T00']['metrics']['net_margin']['numerator']['filed'], '2026-07-29')
        self.assertFalse(sink['T00']['source_refresh_verified'])

    def test_actual_companyfacts_repeated_periods_keep_filing_identity(self):
        old = [self.fact(), self.fact(tag='NetIncomeLoss', value=20)]
        newer = [{**r, 'filed': '2026-08-01', 'accession_number': '0000000001-26-000002'} for r in old]
        sink = {}
        report = self.actual_report(old + newer, wire=True, financial_evidence_sink=sink)
        self.assertEqual(report['records'][0]['profit_summary'], '獲利；淨利率 20.0%')
        selected = sink['T00']['metrics']['net_margin']['numerator']
        self.assertEqual(selected['filed'], '2026-08-01')
        self.assertEqual(selected['record_url'], 'https://www.sec.gov/Archives/edgar/data/1/000000000126000002/')

    def test_actual_builder_preserves_compatible_profit_arithmetic(self):
        sink = {}
        report = self.actual_report([self.fact(), self.fact(tag='OperatingIncomeLoss', value=12.0),
                                     self.fact(tag='NetIncomeLoss', value=8.0)], financial_evidence_sink=sink)
        self.assertEqual(report['records'][0]['profit_summary'], '獲利；營益率 12.0%；淨利率 8.0%')
        self.assertEqual(len(sink), 20)
        record = sink['T00']
        self.assertFalse(record['publication_eligible'])
        self.assertFalse(record['source_refresh_verified'])
        self.assertIsNone(record['source_retrieved_at'])
        for key in ('operating_margin', 'net_margin'):
            metric = record['metrics'][key]
            self.assertEqual(metric['status'], 'AVAILABLE')
            self.assertEqual(metric['value'], metric['numerator']['value'] / metric['denominator']['value'])
            for operand in ('numerator', 'denominator'):
                self.assertEqual(metric[operand]['start'], '2025-07-01')
                self.assertEqual(metric[operand]['filed'], '2026-07-29')
                self.assertEqual(metric[operand]['unit'], 'USD')
        self.assertNotIn('financial_evidence', report)  # unchanged closed public schema

    def test_actual_report_rejects_incompatible_or_untraceable_profit_inputs(self):
        changes = [dict(start='2026-01-01'), dict(unit=None), dict(unit='EUR'),
                   dict(accession_number='0000000001-26-000002'), dict(cik='0000000002'),
                   dict(start='2027-01-01'), dict(filed='9999-01-01'), dict(filed='2026-07-29suffix'),
                   dict(value=True), dict(value='20'), dict(value=float('nan')), dict(value=float('inf')),
                   dict(record_url='https://www.sec.gov/Archives/edgar/data/2/000000000126000001/'),
                   dict(record_url='https://data.sec.gov/api/xbrl/companyfacts/CIK0000000002.json'),
                   dict(record_url='https://www.sec.gov/Archives/edgar/data/1/000000000126000002/'),
                   dict(record_url='https://www.sec.gov/example?access_token=SYNTHETIC_PRIVATE_MARKER')]
        for change in changes:
            with self.subTest(change=change):
                sink = {}
                facts = [self.fact(), self.fact(tag='NetIncomeLoss', value=20.0)]
                facts[1].update(change)
                report = self.actual_report(facts, financial_evidence_sink=sink)
                self.assertEqual(report['records'][0]['profit_summary'], 'SEC 可用獲利指標不足')
                self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(sink, allow_nan=False))

    def test_growth_keeps_both_annual_operands_and_rejects_gaps(self):
        current = self.fact(value=120.0)
        prior = self.fact(start='2024-07-01', end='2025-06-30', filed='2025-07-29', fiscal_year=2025,
                          accession_number='0000000001-25-000001')
        sink = {}
        report = self.actual_report([current, prior], financial_evidence_sink=sink)
        self.assertIn('營收年增 +20.0%', report['records'][0]['profit_summary'])
        metric = sink['T00']['metrics']['revenue_growth']
        self.assertEqual(metric['denominator']['value'], 100.0)
        self.assertEqual(metric['numerator']['value'], 120.0)
        self.assertEqual(metric['formula'], 'numerator / denominator - 1')
        self.assertEqual(metric['value_unit'], 'ratio')
        for change in [dict(unit='EUR'), dict(start='2024-08-01'), dict(end='2024-06-30', start='2023-07-01')]:
            with self.subTest(change=change):
                invalid = dict(prior); invalid.update(change)
                report = self.actual_report([current, invalid])
                self.assertEqual(report['records'][0]['profit_summary'], 'SEC 可用獲利指標不足')

    def test_losses_and_zero_profit_are_not_converted_to_missing_or_positive(self):
        for value, label in [(-20.0, '虧損；淨利率 -20.0%'), (0.0, '損益兩平；淨利率 0.0%')]:
            with self.subTest(value=value):
                report = self.actual_report([self.fact(), self.fact(tag='NetIncomeLoss', value=value)])
                self.assertEqual(report['records'][0]['profit_summary'], label)
        for value in (0, -100):
            report = self.actual_report([self.fact(value=value), self.fact(tag='NetIncomeLoss', value=20.0)])
            self.assertEqual(report['records'][0]['profit_summary'], 'SEC 可用獲利指標不足')

    def test_conflicting_selected_values_fail_in_both_orders(self):
        one = self.fact(tag='NetIncomeLoss', value=20.0)
        two = {**one, 'value': 80.0}
        for rows in ([one, two], [two, one]):
            sink = {}
            report = self.actual_report([self.fact(), *rows], financial_evidence_sink=sink)
            self.assertEqual(report['records'][0]['profit_summary'], 'SEC 可用獲利指標不足')
            self.assertEqual(sink['T00']['metrics']['net_margin']['status'], 'CONFLICTING_OPERAND')
        report = self.actual_report([self.fact(), one, dict(one)])
        self.assertIn('淨利率 20.0%', report['records'][0]['profit_summary'])

    def test_actual_cli_writes_report_bound_operands_and_keeps_failed_state(self):
        original = builder.build
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            with patch.object(builder, 'build', side_effect=lambda **kw: self.actual_report(
                    [self.fact(), self.fact(tag='NetIncomeLoss', value=20.0)], _build=original, **kw)), \
                    patch.object(sys, 'argv', ['build', '--output', str(output)]), redirect_stdout(StringIO()):
                self.assertEqual(builder.main(), 0)
            evidence = output.with_name('report.financial-evidence-candidate.json')
            doc = json.loads(evidence.read_text(encoding='utf-8'))
            self.assertFalse(doc['publication_eligible'])
            self.assertEqual(doc['report_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(doc['records']['T19']['metrics']['net_margin']['value'], 0.2)
            # A failed new observation must replace the previous successful candidate.
            with patch.object(builder, 'build', side_effect=lambda **kw: self.actual_report(
                    [self.fact(filed='bad')], _build=original, **kw)), \
                    patch.object(sys, 'argv', ['build', '--output', str(output)]), redirect_stdout(StringIO()):
                self.assertEqual(builder.main(), 0)
            failed = json.loads(evidence.read_text(encoding='utf-8'))
            self.assertEqual(failed['records']['T00']['status'], 'SOURCE_FETCH_OR_VALIDATION_FAILED')
            self.assertNotIn('metrics', failed['records']['T00'])
            self.assertFalse(failed['publication_eligible'])
            products = json.loads((Path(tmp) / 'report.financial-products-candidate.json').read_text(encoding='utf-8'))
            for product in products['records'][0]['products'].values():
                self.assertEqual(product['status'], 'UNAVAILABLE')
                self.assertIsNone(product['content_utf8'])

    def test_actual_cli_emits_distinct_financial_products_not_only_a_summary(self):
        original = builder.build
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            facts = [self.fact(), self.fact(tag='OperatingIncomeLoss', value=12.0),
                     self.fact(tag='NetIncomeLoss', value=20.0)]
            with patch.object(builder, 'build', side_effect=lambda **kw: self.actual_report(facts, _build=original, **kw)), \
                    patch.object(sys, 'argv', ['build', '--output', str(output)]), redirect_stdout(StringIO()):
                self.assertEqual(builder.main(), 0)
            product_file = Path(tmp) / 'report.financial-products-candidate.json'
            self.assertTrue(product_file.is_file(), 'actual CLI has no separately generated financial products')
            doc = json.loads(product_file.read_text(encoding='utf-8'))
            products = doc['records'][0]['products']
            self.assertEqual(set(products), {'card_summary', 'data_report', 'narrative_analysis'})
            self.assertIn('分子', products['data_report']['content_utf8'])
            self.assertIn('本業', products['narrative_analysis']['content_utf8'])
            self.assertFalse(doc['publication_eligible'])

    def test_actual_cli_keeps_cashflow_and_share_operands_in_distinct_products(self):
        original = builder.build
        facts = [self.fact(), self.fact(tag='OperatingIncomeLoss', value=12),
                 self.fact(tag='NetIncomeLoss', value=20),
                 self.fact(tag='NetCashProvidedByUsedInOperatingActivities', value=40),
                 self.fact(tag='PaymentsToAcquirePropertyPlantAndEquipment', value=60),
                 self.fact(tag='ShareBasedCompensation', value=5),
                 self.fact(tag='WeightedAverageNumberOfSharesOutstandingBasic', unit='shares', value=100),
                 self.fact(tag='WeightedAverageNumberOfDilutedSharesOutstanding', unit='shares', value=110)]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            with patch.object(builder, 'build', side_effect=lambda **kw: self.actual_report(facts, wire=True, _build=original, **kw)), \
                    patch.object(sys, 'argv', ['build', '--output', str(output)]), redirect_stdout(StringIO()):
                self.assertEqual(builder.main(), 0)
            basis = json.loads((Path(tmp) / 'report.financial-evidence-candidate.json').read_bytes())
            self.assertIn('cashflow_bridge', basis['records']['T00'])
            cash = basis['records']['T00']['cashflow_bridge']
            self.assertEqual(cash['metrics']['cash_after_ppe']['value'], -20)
            self.assertEqual(cash['metrics']['cash_conversion']['value'], 2)
            self.assertAlmostEqual(cash['metrics']['diluted_share_increment']['value'], 0.1)
            doc = json.loads((Path(tmp) / 'report.financial-products-candidate.json').read_bytes())
            products = doc['records'][0]['products']
            self.assertIn('PaymentsToAcquirePropertyPlantAndEquipment', products['data_report']['content_utf8'])
            self.assertIn('支出高於營業現金流', products['narrative_analysis']['content_utf8'])
            self.assertIn('不是本期新發股比例', products['narrative_analysis']['content_utf8'])
            self.assertFalse(doc['publication_eligible'])

    def test_financial_candidate_cannot_overwrite_report_or_return_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'; output.write_text('sentinel', encoding='utf-8')
            returns = Path(tmp) / 'return.json'; returns.write_text('return sentinel', encoding='utf-8')
            for other in (output, returns):
                with patch.object(sys, 'argv', ['build', '--output', str(output), '--return-evidence-output', str(returns),
                                               '--financial-evidence-output', str(other)]), \
                        patch.object(builder, 'build') as build, redirect_stdout(StringIO()):
                    self.assertEqual(builder.main(), 1); build.assert_not_called()
                self.assertEqual(output.read_text(encoding='utf-8'), 'sentinel')
                self.assertEqual(returns.read_text(encoding='utf-8'), 'return sentinel')

    def test_industry_is_localized_to_traditional_chinese(self) -> None:
        self.assertEqual(translate_industry("Semiconductors"), "半導體")
        self.assertEqual(translate_industry("Computer Hardware"), "電腦硬體")
        self.assertEqual(translate_industry("Software - Infrastructure"), "基礎架構軟體")
        self.assertEqual(translate_industry("Electronic Components"), "電子零組件")
        self.assertEqual(translate_industry("Communication Equipment"), "通訊設備")
        self.assertEqual(
            translate_industry("Semiconductor Equipment & Materials"),
            "半導體設備與材料",
        )
        self.assertEqual(translate_industry("Unknown English Taxonomy"), "其他產業")


if __name__ == "__main__":
    unittest.main()
