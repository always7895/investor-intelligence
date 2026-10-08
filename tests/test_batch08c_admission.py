"""Binding identity and admission-tier regressions through the owned factory/caller."""
import ast
from dataclasses import asdict
import hashlib
import json
import unittest

from tests import batch08c_fixtures as f


class BindingIdentityTests(unittest.TestCase):
    def test_identical_group_is_byte_identical_to_committed_producer(self):
        run = f.binding_run()
        body = json.dumps([asdict(b) for b in run.company_factor_bindings], sort_keys=True, separators=(',', ':'))
        # Captured from HEAD 9a524e4e with this fixed run id, input bytes and clock.
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),
                         '825cb7d063c5434dda1772eee272032751ea57b98ae74d9c1b35805d37689efe')
        result = f.admission_result(run)
        self.assertTrue(result['core_admitted'])
        self.assertEqual(result['admission_tier'], 'TEST_ONLY_NONRUNTIME')

    def test_non_synthetic_owned_factory_is_not_live_admission(self):
        run = f.binding_run(nonsynthetic=True)
        self.assertFalse(run._is_synthetic)
        self.assertTrue(all(not b.is_test_binding for b in run.company_factor_bindings))
        self.assertEqual(len(run.company_factor_bindings), 4)
        result = f.admission_result(run)
        self.assertEqual(result['admission_tier'], 'UNADMITTED')
        self.assertFalse(result['core_admitted'])

    def test_default_fixture_detection_is_test_only_not_a_runtime_claim(self):
        result = f.admission_result(f.binding_run(), default=True)
        self.assertEqual(result['admission_tier'], 'TEST_ONLY')
        self.assertTrue(result['core_admitted'])

    def test_runtime_callers_do_not_forward_acquisition_context(self):
        expected = {'bottleneck_ranking.py', 'evaluate_candidate_admission_readiness.py'}
        found = set()
        for name in expected:
            tree = ast.parse((f.ROOT / 'scripts' / name).read_text(encoding='utf-8'))
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and ((isinstance(node.func, ast.Name) and node.func.id == 'reconcile_factor_authority')
                          or (isinstance(node.func, ast.Attribute) and node.func.attr == 'reconcile_factor_authority'))]
            self.assertEqual(len(calls), 1, name)
            for call in calls:
                self.assertFalse(any(k.arg in (None, 'acquisition_context') for k in call.keywords), name)
                self.assertEqual(len(call.args), 3, name)
            found.add(name)
        self.assertEqual(found, expected)


def identity_case(field):
    def test(self):
        for reverse in (False, True):
            with self.subTest(field=field, reverse=reverse):
                run = f.binding_run(field, reverse)
                self.assertIsNone(run.binding_for_factor('SYNB08C', 'dependency'))
                self.assertEqual({b.factor for b in run.company_factor_bindings}, {'scarcity', 'pricing', 'capture'})
                result = f.admission_result(run)
                self.assertFalse(result['dependency_licensed'])
                self.assertFalse(result['core_admitted'])
                for factor in ('scarcity', 'pricing', 'capture'):
                    self.assertTrue(result[factor + '_licensed'])
    return test


for _field in f.IDENTITY_VARIANTS:
    setattr(BindingIdentityTests, 'test_mixed_' + _field + '_refuses_entire_group', identity_case(_field))


if __name__ == '__main__':
    unittest.main()
