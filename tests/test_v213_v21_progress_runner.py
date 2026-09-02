from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "v213_v21_progress_runner",
    SCRIPTS / "v213_v21_progress_runner.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class V213SafePreselectionWrapperTests(unittest.TestCase):
    def test_monkeypatched_engine_calls_original_scorer_without_recursion(self) -> None:
        policy, _activation = MODULE.validate_v213_policy()
        candidate, metrics, evidence = MODULE.engine.synthetic_candidates()[0]
        original_score = MODULE.engine.score_candidate
        try:
            MODULE.engine.score_candidate = MODULE.safe_preselection_score
            result = MODULE.engine.score_candidate(candidate, metrics, evidence, policy)
        finally:
            MODULE.engine.score_candidate = original_score

        self.assertEqual(result["scoring_version"], MODULE.PRESELECTION_VERSION)
        self.assertEqual(result["serenity_factors"]["demand_wave"], 0.0)
        self.assertEqual(result["serenity_factors"]["chokepoint"], 0.0)
        self.assertEqual(result["serenity_factors"]["pricing_power"], 0.0)
        self.assertEqual(result["serenity_factors"]["replacement_friction"], 0.0)
        self.assertLessEqual(result["serenity_factors"]["valuation_expectations"], 3.75)


if __name__ == "__main__":
    unittest.main()
