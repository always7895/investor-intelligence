from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "v213_serenity_public_logic.py"
SPEC = importlib.util.spec_from_file_location("v213_serenity_public_logic", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SerenityPublicLogicV213Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = MODULE.load_policy()

    def fixture(self, **overrides):
        row = {
            "ticker": "TEST",
            "architecture": {"current": "1.6T", "next": "CPO"},
            "supply_chain_graph": [
                {"from": "hyperscaler", "to": "module", "evidence_url": "https://example.com/a"},
                {"from": "module", "to": "laser", "evidence_url": "https://example.com/b"},
            ],
            "dependency_signals": ["semi_monopoly", "qualification_constraint"],
            "beneficiary_signal": True,
            "signals": ["qualification", "customer_named_ramp"],
            "information_gap": {"coverage": "low"},
            "evidence": [
                {"tier": "primary_strong", "url": "https://example.com/filing"},
                {"tier": "corroborating", "url": "https://example.com/customer"},
            ],
            "thesis_killers": [],
            "disconfirmation_conditions": ["qualified alternative removes the constraint"],
            "timing": {
                "operating_thesis_horizon": "company-specific",
                "architecture_ramp_window": "source-specific",
            },
            "source_delta": [],
            "system_operationalization_score": 90,
        }
        row.update(overrides)
        return row

    def test_policy_forbids_claiming_official_serenity_score(self) -> None:
        self.assertEqual(self.policy["legacy_quantitative_overlay_label"], "System operationalization score")
        self.assertIn("Serenity score", self.policy["forbid_labels"])
        self.assertTrue(all(self.policy["fail_closed"].values()))

    def test_keyword_or_margin_alone_cannot_create_bottleneck(self) -> None:
        result = MODULE.assess_public_logic(
            self.fixture(
                dependency_signals=[],
                beneficiary_signal=True,
                signals=["revenue_expansion"],
            ),
            self.policy,
        )
        fidelity = result["public_logic_fidelity"]
        self.assertEqual(fidelity["dependency_role"], "BENEFICIARY")
        self.assertEqual(fidelity["thesis_class"], "EXPANSION_THESIS")

    def test_explicit_dependency_and_primary_evidence_can_support_bottleneck(self) -> None:
        result = MODULE.assess_public_logic(self.fixture(), self.policy)
        fidelity = result["public_logic_fidelity"]
        self.assertEqual(fidelity["dependency_role"], "SEMI_MONOPOLY")
        self.assertEqual(fidelity["thesis_class"], "BOTTLENECK_THESIS")
        self.assertEqual(fidelity["thesis_state"], "COMMERCIAL_VALIDATION")

    def test_severe_architecture_killer_overrides_positive_system_score(self) -> None:
        result = MODULE.assess_public_logic(
            self.fixture(
                thesis_killers=["architecture_bypass"],
                system_operationalization_score=100,
            ),
            self.policy,
        )
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "BROKEN")
        self.assertFalse(result["system_score_can_override_broken_thesis"])
        self.assertTrue(result["warnings"])

    def test_material_dilution_weakens_thesis_without_needing_revenue_decline(self) -> None:
        result = MODULE.assess_public_logic(
            self.fixture(thesis_killers=["repeated_atm_or_material_dilution"]),
            self.policy,
        )
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "THESIS_WEAKENING")

    def test_foreign_ticker_is_not_excluded_for_lack_of_sec_companyfacts(self) -> None:
        result = MODULE.assess_public_logic(
            self.fixture(
                ticker="SIVE",
                evidence=[{"tier": "primary_strong", "url": "https://example.se/exchange-announcement"}],
            ),
            self.policy,
        )
        self.assertEqual(result["ticker"], "SIVE")
        self.assertNotEqual(result["public_logic_fidelity"]["thesis_state"], "INSUFFICIENT_EVIDENCE")

    def test_disconfirmation_conditions_are_mandatory(self) -> None:
        with self.assertRaises(MODULE.FidelityError):
            MODULE.assess_public_logic(self.fixture(disconfirmation_conditions=[]), self.policy)

    def test_lead_only_social_evidence_cannot_prove_company_economics(self) -> None:
        result = MODULE.assess_public_logic(
            self.fixture(
                dependency_signals=["semi_monopoly"],
                evidence=[{"tier": "lead_only", "url": "https://x.com/example/status/1"}],
                signals=[],
            ),
            self.policy,
        )
        self.assertEqual(result["public_logic_fidelity"]["thesis_class"], "UNPROVEN")
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("Lead-only evidence cannot prove company economics", result["warnings"])

    def test_source_delta_is_append_only_structured_output(self) -> None:
        source_delta = [
            {
                "url": "https://x.com/aleabitoreddit/status/1",
                "published_at": "2026-01-01T00:00:00Z",
                "stance": "positive",
                "what_changed_vs_prior_source_view": "initial thesis",
            },
            {
                "url": "https://x.com/aleabitoreddit/status/2",
                "published_at": "2026-02-01T00:00:00Z",
                "stance": "mixed",
                "what_changed_vs_prior_source_view": "financing risk increased",
            },
        ]
        result = MODULE.assess_public_logic(self.fixture(source_delta=source_delta), self.policy)
        self.assertEqual(result["public_logic_fidelity"]["source_delta"], source_delta)

    def test_policy_has_no_numeric_serenity_factor_weights(self) -> None:
        encoded = json.dumps(self.policy, sort_keys=True).casefold()
        self.assertNotIn("factor_weights", encoded)
        self.assertNotIn("maximum_risk_penalty", encoded)
        self.assertNotIn("minimum_market_cap", encoded)
        self.assertNotIn("minimum_price", encoded)


if __name__ == "__main__":
    unittest.main()
