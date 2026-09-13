"""Offline regression for the actual provisional Top20 scorer/caller."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v21_serenity_top20 as engine


class ResearchScoreBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.policy, _ = engine.validate_policy()
        self.candidate, self.metrics, self.evidence = copy.deepcopy(engine.synthetic_candidates()[0])
        self.candidate['market'].update(sector='Consumer', industry='Services', longBusinessSummary='Neutral business')

    def score(self, candidate=None, metrics=None, evidence=None):
        return engine.score_candidate(
            self.candidate if candidate is None else candidate,
            self.metrics if metrics is None else metrics,
            self.evidence if evidence is None else evidence, self.policy)

    def test_theme_text_cannot_boost_any_stock_factor(self):
        baseline = self.score()
        for text in ('AI infrastructure', 'power grid semiconductor cooling', 'Leopold compute scaling datacenter'):
            themed = copy.deepcopy(self.candidate)
            themed['market'].update(sector=text, industry=text, longBusinessSummary=text)
            result = self.score(themed)
            for field in ('serenity_factors', 'serenity_raw_score', 'serenity_score', 'risk_penalty'):
                self.assertEqual(result[field], baseline[field], (text, field))
            self.assertFalse(result['aschenbrenner_overlay']['included_in_serenity_score'])

    def test_structural_points_need_more_than_margin_and_url_count(self):
        result = self.score(metrics=dict(self.metrics, gross_margin=0.95), evidence=self.evidence * 12)
        self.assertEqual(result['serenity_factors']['chokepoint'], 0)
        self.assertEqual(result['serenity_factors']['replacement_friction'], 0)

    def test_old_thesis_and_holdings_are_not_current_authority(self):
        candidate = copy.deepcopy(self.candidate)
        candidate['leopold_thesis'] = {'published_at': '2024-06-01', 'stock_score_bonus': 100}
        candidate['leopold_holdings'] = {'published_at': '2024-06-01', 'current': True}
        result = self.score(candidate)
        self.assertEqual(result['serenity_score'], self.score()['serenity_score'])
        overlay = result['aschenbrenner_overlay']
        self.assertEqual(overlay['status'], 'DISCOVERY_ONLY')
        self.assertFalse(overlay['company_fact_authority'])
        self.assertFalse(overlay['current_holdings_verified'])
        self.assertIsNone(overlay['thesis_published_at'])
        self.assertEqual(overlay['scenario_adjustment'], 'UNAVAILABLE')

    def test_fundamentals_still_drive_score_without_retuning_weights(self):
        low = self.score(metrics=dict(self.metrics, revenue_growth=-0.2))
        high = self.score(metrics=dict(self.metrics, revenue_growth=0.4))
        self.assertGreater(high['serenity_score'], low['serenity_score'])
        self.assertEqual(sum(self.policy['factor_weights'].values()), 100)
        self.assertEqual(len(high['serenity_factors']), 7)

    def test_missing_inputs_do_not_invent_structural_facts(self):
        result = self.score(metrics={}, evidence=[])
        self.assertIsInstance(result['serenity_score'], int)
        self.assertEqual(result['serenity_factors']['chokepoint'], 0)
        self.assertEqual(result['serenity_factors']['replacement_friction'], 0)

    def test_actual_synthetic_caller_does_not_lose_neutral_seed_to_theme(self):
        bundles = []
        for index in range(21):
            item = copy.deepcopy(self.candidate)
            item['ticker'] = f'ZZ{index:02d}'
            if index == 20:
                item['market']['industry'] = 'AI power grid semiconductor cooling'
            bundles.append((item, self.metrics, self.evidence))
        with tempfile.TemporaryDirectory() as directory, patch.object(engine, 'synthetic_candidates', return_value=bundles), patch.object(engine.requests.Session, 'request', side_effect=AssertionError('network forbidden')):
            receipt = engine.run(synthetic=True, output_root=Path(directory))
            rows = json.loads(Path(receipt['top20_path']).read_text(encoding='utf-8'))
        self.assertEqual([row['ticker'] for row in rows], [f'ZZ{i:02d}' for i in range(20)])


if __name__ == '__main__':
    unittest.main()
