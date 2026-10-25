"""Dated research-artifact consistency, NOT source truth or publication qualification."""
import copy
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def check_receipt(receipt, report_bytes):
    assert receipt['schema_version'] == 1
    assert receipt['status'] == 'RESEARCH_DRAFT_NOT_PUBLICATION_QUALIFIED'
    for key in ('publication_eligible', 'card_route_integrated', 'sealed_snapshot_bound'):
        assert receipt[key] is False, key
    assert receipt['numeric_total_order_estimate_prohibited'] is True
    assert hashlib.sha256(report_bytes).hexdigest() == receipt['report_sha256']
    report = report_bytes.decode('utf-8')
    sources = {source['id']: source for source in receipt['sources']}
    assert len(sources) == len(receipt['sources'])
    for source in sources.values():
        assert source['url'] in report
        assert source['passages']
        assert source['published_date'] is None or source['published_date'] <= source['retrieval_date']
    values = {}
    for key, entry in receipt['financial_inputs_musd'].items():
        assert entry['source'] in sources
        values[key] = Decimal(entry['value'])
        assert values[key].is_finite()
    for metric in receipt['derived_metrics']:
        assert metric['id'] not in values
        a, b = (values[key] for key in metric['inputs'])
        formula = metric['formula']
        if formula == 'subtract':
            result = a - b
        elif formula == 'percent_ratio':
            result = a / b * 100
        elif formula == 'percent_change':
            result = (a / b - 1) * 100
        else:
            raise AssertionError('Unknown calculation')
        expected = Decimal(metric['value'])
        assert expected.is_finite()
        assert result.quantize(Decimal(1).scaleb(expected.as_tuple().exponent), rounding=ROUND_HALF_UP) == expected
        assert metric['report_token'] in report
        # Keep unrounded intermediates: displayed rounding is not an input.
        values[metric['id']] = result


class ResearchDossierReceiptsTests(unittest.TestCase):
    def cases(self):
        paths = sorted((ROOT / 'state/research-dossiers').glob('*.json'))
        self.assertTrue(paths)
        for path in paths:
            receipt = json.loads(path.read_text(encoding='utf-8'))
            report_path = (ROOT / receipt['report_path']).resolve()
            self.assertTrue(report_path.is_relative_to(ROOT / 'docs/research'))
            yield receipt, report_path.read_bytes()

    def test_dated_draft_hash_sources_and_calculations(self):
        for receipt, body in self.cases():
            check_receipt(receipt, body)

    def test_changed_report_rejected(self):
        for receipt, body in self.cases():
            with self.assertRaises(AssertionError):
                check_receipt(receipt, body + b'changed')

    def test_changed_calculation_and_unknown_source_rejected(self):
        for receipt, body in self.cases():
            changed = copy.deepcopy(receipt)
            changed['derived_metrics'][0]['value'] = '9999.0'
            with self.assertRaises(AssertionError):
                check_receipt(changed, body)
            changed = copy.deepcopy(receipt)
            next(iter(changed['financial_inputs_musd'].values()))['source'] = 'UNKNOWN'
            with self.assertRaises(AssertionError):
                check_receipt(changed, body)

    def test_draft_cannot_claim_publication_or_route_acceptance(self):
        for receipt, body in self.cases():
            for key in ('publication_eligible', 'card_route_integrated', 'sealed_snapshot_bound'):
                changed = copy.deepcopy(receipt)
                changed[key] = True
                with self.assertRaises(AssertionError):
                    check_receipt(changed, body)


if __name__ == '__main__':
    unittest.main()
