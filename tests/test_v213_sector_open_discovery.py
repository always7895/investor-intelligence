"""Active discovery controls with synthetic provider IO; no real fetch/publication."""
import copy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('sector_open_runner', ROOT / 'scripts/v213_v21_progress_runner.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
e = m.engine
BROAD = {'undervalued_growth_stocks', 'most_actives', 'day_gainers'}


class SectorOpenDiscoveryTests(unittest.TestCase):
    def policy(self):
        return e.load_object(e.POLICY_PATH)

    def test_active_policy_has_no_permanent_technology_screener(self):
        policy = self.policy()
        self.assertEqual({s['name'] for s in policy['candidate_screeners']}, BROAD)
        self.assertEqual(policy['factor_weights'], {'chokepoint': 15, 'demand_wave': 15, 'evidence_quality': 15,
                         'pricing_power': 15, 'replacement_friction': 10, 'tam_capture': 15, 'valuation_expectations': 15})

    def test_active_policy_validator_rejects_sector_reintroduction_and_malformed_specs(self):
        original = self.policy()
        for spec in ({'name': 'growth_technology_stocks', 'weight': 6}, {'name': 'unknown_screener', 'weight': 1},
                     {'name': 'most_actives', 'weight': True}, {'name': 'most_actives', 'weight': float('nan')},
                     {'name': 'most_actives', 'weight': 0}):
            changed = copy.deepcopy(original)
            changed['candidate_screeners'] = [spec]
            real_load = e.load_object
            with patch.object(e, 'load_object', side_effect=lambda path: changed if path == e.POLICY_PATH else real_load(path)):
                with self.assertRaisesRegex(e.PipelineError, 'V213_DISCOVERY_SCREENER_POLICY_INVALID'):
                    m.validate_v213_policy()
        changed = copy.deepcopy(original)
        changed['candidate_screeners'] = [changed['candidate_screeners'][0]] * 2
        real_load = e.load_object
        with patch.object(e, 'load_object', side_effect=lambda path: changed if path == e.POLICY_PATH else real_load(path)):
            with self.assertRaisesRegex(e.PipelineError, 'V213_DISCOVERY_SCREENER_POLICY_INVALID'):
                m.validate_v213_policy()

    def test_actual_discovery_and_sec_preselection_admit_multiple_industries(self):
        policy, _ = m.validate_v213_policy()
        policy = {**policy, 'candidate_seed_limit': 5, 'sec_candidate_limit': 5, 'top_count': 5}
        industries = {'AGRI': 'Agriculture', 'ENERGY': 'Energy', 'HEALTH': 'Healthcare', 'INDUST': 'Industrials', 'TECH': 'Technology'}
        calls = []
        def screen(name, count):
            calls.append(name)
            self.assertIn(name, BROAD)
            return {'quotes': [{'symbol': symbol, 'industry': industry, 'regularMarketPrice': 20,
                               'marketCap': 1_000_000_000, 'averageDailyVolume3Month': 500_000}
                              for symbol, industry in industries.items()]}
        with patch.dict(sys.modules, {'yfinance': SimpleNamespace(screen=screen)}), patch.object(e, 'atomic_json') as write:
            seeds = e.discover_candidates(policy)
        reference = {symbol: {'ticker': symbol, 'name': 'Synthetic', 'cik': '0000000001', 'exchange': 'Nasdaq'} for symbol in industries}
        candidates = e.validate_candidates(seeds, reference, policy)
        self.assertEqual(set(calls), BROAD)
        self.assertEqual({r['ticker'] for r in candidates}, set(industries))
        self.assertTrue(all(set(r['screeners']) == BROAD for r in candidates))
        write.assert_called_once()
        self.assertNotEqual(write.call_args.args[0].name, 'candidate_seed.json')

    def test_discovery_cache_changes_with_policy_and_not_score_weights(self):
        original = self.policy()
        def path_for(policy):
            with patch.dict(sys.modules, {'yfinance': SimpleNamespace(screen=lambda *a, **k: {'quotes': [{'symbol': 'TEST'}]})}), patch.object(e, 'atomic_json') as write:
                e.discover_candidates(policy)
            return write.call_args.args[0]
        first = path_for(original)
        for change in ({'candidate_seed_limit': original['candidate_seed_limit'] + 1},
                       {'per_screener_count': original['per_screener_count'] + 1},
                       {'candidate_screeners': original['candidate_screeners'][:-1]}):
            self.assertNotEqual(path_for({**original, **change}), first)
        self.assertEqual(path_for({**original, 'factor_weights': {}}), first)

    def test_all_provider_failures_cannot_resurrect_old_unbound_seed_cache(self):
        policy = self.policy()
        old = e.CACHE_ROOT / 'candidate_seed.json'
        def old_cache(path, hours):
            return [{'ticker': 'OLDTECH', 'screen_weight': 6, 'screeners': ['growth_technology_stocks'], 'market': {}}] if path == old else None
        def failed(*args, **kwargs):
            raise RuntimeError('SYNTHETIC_PROVIDER_FAILURE')
        with patch.dict(sys.modules, {'yfinance': SimpleNamespace(screen=failed)}), patch.object(e, 'cached', side_effect=old_cache) as cache, patch.object(e, 'atomic_json') as write:
            with self.assertRaisesRegex(e.PipelineError, 'All T3 candidate screeners failed'):
                e.discover_candidates(policy)
        self.assertNotEqual(cache.call_args.args[0], old)
        write.assert_not_called()

    def test_same_policy_seed_cache_remains_usable(self):
        policy = self.policy()
        cached = [{'ticker': 'TEST', 'screen_weight': 1.0, 'screeners': ['most_actives'], 'market': {}}]
        def failed(*args, **kwargs): raise RuntimeError('SYNTHETIC_PROVIDER_FAILURE')
        with patch.dict(sys.modules, {'yfinance': SimpleNamespace(screen=failed)}), patch.object(e, 'cached', return_value=cached), patch.object(e, 'atomic_json') as write:
            self.assertEqual(e.discover_candidates(policy), cached)
        write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
