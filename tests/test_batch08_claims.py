"""BATCH08 synthetic claim-level caller checks; never live source qualification."""
from __future__ import annotations

import copy
import itertools
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

import test_research_v2_claims as research
import test_company_acquisition_bindings as binding
import source_observation as observation


class ClaimLineageCallers(unittest.TestCase):
    def test_transitive_mirrors_are_one_family_in_every_order(self):
        first, second, bridge = (research.evidence(name) for name in ('issuer', 'news', 'news-two'))
        bridge['payload']['origin_group'] = first['payload']['origin_group']
        bridge['content_sha256'] = second['content_sha256']
        for rows in itertools.permutations([first, second, bridge]):
            with self.subTest(order=[r['source_id'] for r in rows]):
                doc = research.document(list(rows))
                before = copy.deepcopy(doc)
                result = research.assess(doc)
                claim = result['claims'][0]
                self.assertEqual((claim['independent_evidence_families'], claim['status']), (1, 'SINGLE_SOURCE'))
                self.assertFalse(claim['high_confidence_eligible'])
                self.assertEqual(len(result['evidence']), 3)
                self.assertEqual(doc, before)
        control = research.assess(research.document([first, second]))['claims'][0]
        self.assertEqual((control['independent_evidence_families'], control['status']), (2, 'SUPPORTED'))

    def test_independent_other_claim_cannot_license_mirrored_claim(self):
        first, second = research.evidence(), research.evidence('news')
        second['payload']['origin_group'] = first['payload']['origin_group']
        rows = [first, second, research.evidence(cid='profit', value=20),
                research.evidence('news', 'profit', value=20)]
        result = research.assess(research.document(rows, [research.claim(), research.claim('profit')]))
        claims = {row['claim_id']: row for row in result['claims']}
        self.assertEqual(claims['revenue']['status'], 'SINGLE_SOURCE')
        self.assertEqual(claims['profit']['status'], 'SUPPORTED')
        self.assertFalse(result['all_material_claims_supported'])
        self.assertEqual(result['stock_score_adjustment'], 0)
        self.assertFalse(result['source_diversity']['expansion_executed'])

    def test_missing_runtime_health_never_uses_saved_healthy_labels(self):
        result = observation.reconcile_research_claims(research.document(), registry=research.REGISTRY,
                                                       now=research.NOW)
        self.assertEqual(result['claims'][0]['status'], 'UNAVAILABLE')
        self.assertFalse(result['all_material_claims_supported'])


class AcquisitionToAdmissionCallers(unittest.TestCase):
    def run_case(self, mirror_factor=None):
        sec_rows, ir_rows = binding._build_test_four_factor_records('SYNB08')
        if mirror_factor:
            for first, second in zip(sec_rows, ir_rows):
                if first['factor_binding']['factor'] == mirror_factor:
                    second['payload']['origin_group'] = first['payload']['origin_group']
        endpoints = {name: f'https://{name}.example/report' for name in ('sec_gov', 'official_ir')}
        adapters = {'sec_gov': binding.FakeBindingAdapter('sec_gov', sec_rows),
                    'official_ir': binding.FakeBindingAdapter('official_ir', ir_rows)}
        registry = binding.Registry(1, (binding.SRC_REGULATOR, binding.SRC_OFFICIAL), ())
        with patch.dict(binding.ENDPOINTS, endpoints), patch.dict(binding.ADAPTERS, adapters):
            run = binding.acquire_runtime_sources(registry=registry,
                transport=lambda url: ('synthetic bytes for ' + url).encode('ascii'), clock=binding.NOW)
        candidate, claims = binding._make_candidate_for_run('SYNB08', run)
        before = copy.deepcopy(candidate)
        result = binding.admission.reconcile_factor_authority(candidate, claims, ticker='SYNB08',
            now=binding.NOW, fixture_mode=False, acquisition_context=run)
        self.assertEqual(candidate, before)
        return run, candidate, claims, result

    def test_owned_factory_to_old_caller_positive_is_test_only(self):
        run, _, _, result = self.run_case()
        self.assertTrue(result['core_admitted'])
        self.assertEqual(result['admission_tier'], 'TEST_ONLY_NONRUNTIME')
        self.assertEqual({b.independent_lineage_count for b in run.company_bindings_for('SYNB08')}, {2})
        self.assertTrue(all(b.is_test_binding for b in run.company_bindings_for('SYNB08')))

    def test_one_mirrored_factor_cannot_borrow_other_factors_families(self):
        for factor in ('dependency', 'scarcity', 'pricing', 'capture'):
            with self.subTest(factor=factor):
                run, _, _, result = self.run_case(factor)
                counts = {b.factor: b.independent_lineage_count for b in run.company_bindings_for('SYNB08')}
                self.assertEqual(counts[factor], 1)
                self.assertEqual({v for k, v in counts.items() if k != factor}, {2})
                self.assertFalse(result[factor + '_licensed'])
                self.assertFalse(result['core_admitted'])

    def test_copying_candidate_without_owned_run_cannot_replay_admission(self):
        _, candidate, claims, _ = self.run_case()
        result = binding.admission.reconcile_factor_authority(candidate, claims, ticker='SYNB08',
            now=binding.NOW, fixture_mode=False)
        self.assertFalse(result['core_admitted'])
        self.assertEqual(result['admission_tier'], 'ADMISSION_DEFER')


if __name__ == '__main__':
    unittest.main()
