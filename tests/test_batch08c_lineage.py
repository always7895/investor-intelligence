"""Identity guards, graph parity and real acquisition/reconciliation callers."""
import copy
import itertools
import unittest

from tests import batch08c_fixtures as f
import company_claim_admission_bridge as bridge
import test_company_claim_admission_bridge as bridge_fixtures


class IdentityGuards(unittest.TestCase):
    def test_direct_copies_ignore_keyless_and_nonstring_identity(self):
        first = {'origin_group': 'g1', 'content_sha256': '1' * 64}
        variants = [{}, {'origin_group': 7}, {'independence_group': ['x'], 'content_sha256': 12345},
                    {'origin_group': None, 'content_sha256': '  '},
                    {'payload': {'origin_group': ' g1 '}}]
        for second in variants:
            for module in (bridge, f.observation):
                with self.subTest(second=second, module=module.__name__):
                    self.assertEqual(module.compute_independent_lineages([first, second]), 1)

    def test_bridge_caller_cannot_count_empty_or_coerced_second_witness(self):
        for mode in ('control', 'keyless', 'typed'):
            candidate = bridge_fixtures._make_valid_test_candidate('SYNB08C')
            claims = [{'claim_id': c['claim_id'], 'status': 'SUPPORTED'} for c in candidate['material_claims']]
            second = candidate['source_observations'][1]
            if mode != 'control':
                second.pop('content_sha256', None)
                second['payload'].pop('origin_group', None)
            if mode == 'typed':
                second.update(content_sha256=12345, independence_group=['x'])
                second['payload']['origin_group'] = 7
            before = copy.deepcopy(candidate)
            result = bridge.bridge_reconcile_factors(candidate, claims, 'SYNB08C', now=f.NOW, fixture_mode=True)
            self.assertEqual(result['dependency_licensed'], mode == 'control')
            self.assertEqual(result['core_admitted'], mode == 'control')
            if mode != 'control':
                self.assertTrue(any('collapse to 1 family' in d for d in result['diagnostics']))
            self.assertEqual(candidate, before)

    def test_nonempty_graph_components_are_equivalent_in_all_three_copies(self):
        # All five equality partitions of three vertices, independently for each edge kind.
        partitions = ((0, 0, 0), (0, 0, 1), (0, 1, 0), (0, 1, 1), (0, 1, 2))
        fields = ('independence_group', 'origin_group', 'content_sha256')
        for labels in itertools.product(partitions, repeat=3):
            rows = [{field: str(labels[k][i]) for k, field in enumerate(fields)} for i in range(3)]
            # Independent graph reachability oracle, not one production copy as the oracle.
            remaining, expected = set(range(3)), 0
            while remaining:
                frontier = [remaining.pop()]
                expected += 1
                while frontier:
                    vertex = frontier.pop()
                    linked = {j for j in remaining if any(rows[vertex][key] == rows[j][key] for key in fields)}
                    remaining -= linked
                    frontier.extend(linked)
            for order in itertools.permutations(rows):
                self.assertEqual(f.observation._research_families(list(order)), expected)
                self.assertEqual(bridge.compute_independent_lineages(order), expected)
                self.assertEqual(f.observation.compute_independent_lineages(order), expected)
        # Publisher-only final link makes this chain one component, not two.
        rows = [{'independence_group': 'p0', 'origin_group': 'a', 'content_sha256': '0'},
                {'independence_group': 'p1', 'origin_group': 'a', 'content_sha256': '1'},
                {'independence_group': 'p1', 'origin_group': 'b', 'content_sha256': '2'}]
        for order in itertools.permutations(rows):
            self.assertEqual(f.observation._research_families(list(order)), 1)


class AcquisitionLineageCallers(unittest.TestCase):
    def test_distinct_sources_control(self):
        for mode, count in (('control', 2), ('three', 3)):
            run = f.research_run(mode)
            direct, gate = f.research_callers(run)
            for audit in (direct, gate['claim_evidence_audit']):
                self.assertEqual(audit['claims'][0]['independent_evidence_families'], count)
                self.assertEqual(audit['claims'][0]['status'], 'SUPPORTED')
                self.assertTrue(audit['all_material_claims_supported'])
            self.assertNotIn('EXACT_CLAIM_CORROBORATION_REQUIRED', gate['missing_or_review'])

    def test_mirror_rows_cannot_borrow_a_different_caller_ticker(self):
        direct, gate = f.research_callers(f.research_run('origin'), ticker='OTHER')
        for audit in (direct, gate['claim_evidence_audit']):
            self.assertEqual(audit['claims'][0]['status'], 'UNAVAILABLE')
            self.assertEqual(len(audit['evidence']), 2)
            self.assertTrue(all(row['source_health'] == 'DEGRADED' for row in audit['evidence']))
            self.assertFalse(audit['all_material_claims_supported'])


def mirrored_case(mode):
    def test(self):
        for reverse in (False, True):
            with self.subTest(mode=mode, reverse=reverse):
                run = f.research_run(mode, reverse)
                direct, gate = f.research_callers(run)
                expected_count = 3 if mode in ('chain', 'publisher') else 2
                for audit in (direct, gate['claim_evidence_audit']):
                    self.assertEqual(len(audit['evidence']), expected_count)
                    self.assertTrue(all(row['source_health'] == 'HEALTHY' for row in audit['evidence']))
                    claim = audit['claims'][0]
                    self.assertEqual((claim['independent_evidence_families'], claim['status']), (1, 'SINGLE_SOURCE'))
                    self.assertFalse(claim['high_confidence_eligible'])
                    self.assertFalse(audit['all_material_claims_supported'])
                self.assertIn('EXACT_CLAIM_CORROBORATION_REQUIRED', gate['missing_or_review'])
    return test


for _mode in ('origin', 'hash', 'chain', 'publisher'):
    setattr(AcquisitionLineageCallers, 'test_acquired_' + _mode + '_merges', mirrored_case(_mode))


if __name__ == '__main__':
    unittest.main()
