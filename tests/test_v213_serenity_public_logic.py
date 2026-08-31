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
        filing = "https://example.com/filing"
        customer = "https://example.com/customer"
        row = {
            "ticker": "TEST",
            "focal_company_node": "TEST",
            "architecture": {"current": "1.6T", "next": "CPO", "as_of": "2026-01-01", "evidence_urls": [customer]},
            "supply_chain_graph": [
                {"from": "hyperscaler", "to": "module", "relationship": "uses", "evidence_url": customer, "as_of": "2026-01-01"},
                {"from": "module", "to": "TEST", "relationship": "qualified supplier", "evidence_url": customer, "as_of": "2026-01-01"},
            ],
            "dependency_signals": ["semi_monopoly", "qualification_constraint"],
            "beneficiary_signal": True,
            "beneficiary_evidence_urls": [customer],
            "signals": ["qualification", "customer_named_ramp"],
            "signal_evidence": [
                {"signal": "semi_monopoly", "evidence_url": customer, "as_of": "2026-01-01"},
                {"signal": "qualification_constraint", "evidence_url": customer, "as_of": "2026-01-01"},
                {"signal": "qualification", "evidence_url": filing, "as_of": "2026-01-01"},
                {"signal": "customer_named_ramp", "evidence_url": customer, "as_of": "2026-01-01"},
            ],
            "information_gap": {"coverage": "low", "evidence_urls": [customer]},
            "company_capture": {"state": "POSITIVE", "evidence_urls": [filing]},
            "evidence": [
                {"tier": "primary_strong", "url": filing},
                {"tier": "corroborating", "url": customer},
            ],
            "thesis_killers": [],
            "disconfirmation_conditions": ["qualified alternative removes the constraint"],
            "timing": {
                "operating_thesis_horizon": "company-specific",
                "architecture_ramp_window": "source-specific",
            },
            "serenity_source_views": [],
            "source_delta": [],
            "system_operationalization_score": 90,
        }
        row.update(overrides)
        return row

    def test_policy_is_fail_closed_and_severe_signals_are_usable(self) -> None:
        self.assertEqual(self.policy["schema_version"], 2)
        self.assertEqual(self.policy["legacy_quantitative_overlay_label"], "System operationalization score")
        self.assertIn("Serenity score", self.policy["forbid_labels"])
        self.assertTrue(all(self.policy["fail_closed"].values()))
        self.assertTrue(set(self.policy["severe_break_signals"]).issubset(self.policy["thesis_killers"]))
        self.assertNotIn("customer_named_dependency", self.policy["bottleneck_proving_signals"])

    def test_evidence_bound_dependency_can_support_bottleneck(self) -> None:
        result = MODULE.assess_public_logic(self.fixture(), self.policy)
        fidelity = result["public_logic_fidelity"]
        self.assertEqual(fidelity["dependency_role"], "SEMI_MONOPOLY")
        self.assertEqual(fidelity["thesis_class"], "BOTTLENECK_THESIS")
        self.assertEqual(fidelity["thesis_state"], "COMMERCIAL_VALIDATION")
        self.assertEqual(fidelity["company_capture"]["state"], "POSITIVE")
        self.assertTrue(fidelity["architecture_evidence_bound"])
        self.assertTrue(fidelity["graph_touches_focal_company"])

    def test_unbound_dependency_signal_is_not_used_as_proof(self) -> None:
        row = self.fixture(signal_evidence=[])
        result = MODULE.assess_public_logic(row, self.policy)
        fidelity = result["public_logic_fidelity"]
        self.assertEqual(fidelity["dependency_role"], "BENEFICIARY")
        self.assertNotEqual(fidelity["thesis_class"], "BOTTLENECK_THESIS")
        self.assertTrue(any("lacks evidence binding" in warning for warning in result["warnings"]))

    def test_customer_named_dependency_alone_does_not_prove_chokepoint(self) -> None:
        customer = "https://example.com/customer"
        row = self.fixture(
            dependency_signals=["customer_named_dependency"],
            signal_evidence=[
                {"signal": "customer_named_dependency", "evidence_url": customer, "as_of": "2026-01-01"}
            ],
            signals=[],
        )
        result = MODULE.assess_public_logic(row, self.policy)
        fidelity = result["public_logic_fidelity"]
        self.assertEqual(fidelity["dependency_role"], "BENEFICIARY")
        self.assertEqual(fidelity["thesis_class"], "UNPROVEN")

    def test_beneficiary_classification_requires_evidence_binding(self) -> None:
        row = self.fixture(
            dependency_signals=[],
            signals=[],
            signal_evidence=[],
            beneficiary_signal=True,
            beneficiary_evidence_urls=[],
        )
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "UNPROVEN")
        self.assertTrue(any("Beneficiary classification" in warning for warning in result["warnings"]))

    def test_commercial_signal_cannot_validate_an_unproven_thesis(self) -> None:
        filing = "https://example.com/filing"
        row = self.fixture(
            architecture={},
            supply_chain_graph=[],
            dependency_signals=[],
            beneficiary_signal=False,
            beneficiary_evidence_urls=[],
            signals=["qualification"],
            signal_evidence=[{"signal": "qualification", "evidence_url": filing, "as_of": "2026-01-01"}],
        )
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["public_logic_fidelity"]["thesis_class"], "UNPROVEN")
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "INSUFFICIENT_EVIDENCE")

    def test_graph_must_touch_focal_company_to_promote_dependency_role(self) -> None:
        customer = "https://example.com/customer"
        row = self.fixture(
            supply_chain_graph=[
                {"from": "hyperscaler", "to": "module", "relationship": "uses", "evidence_url": customer, "as_of": "2026-01-01"}
            ]
        )
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "BENEFICIARY")
        self.assertTrue(any("focal company" in warning for warning in result["warnings"]))

    def test_architecture_without_bound_evidence_cannot_create_bottleneck(self) -> None:
        row = self.fixture(architecture={"current": "CPO", "as_of": "2026-01-01", "evidence_urls": ["https://example.com/not-in-evidence"]})
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["public_logic_fidelity"]["thesis_class"], "UNPROVEN")
        self.assertFalse(result["public_logic_fidelity"]["architecture_evidence_bound"])

    def test_severe_architecture_killer_requires_evidence_and_overrides_score(self) -> None:
        filing = "https://example.com/filing"
        row = self.fixture(
            thesis_killers=["architecture_bypass"],
            signal_evidence=self.fixture()["signal_evidence"] + [
                {"signal": "architecture_bypass", "evidence_url": filing, "as_of": "2026-01-02"}
            ],
            system_operationalization_score=100,
        )
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "BROKEN")
        self.assertFalse(result["system_score_can_override_broken_thesis"])

    def test_unbound_killer_cannot_break_thesis(self) -> None:
        row = self.fixture(thesis_killers=["architecture_bypass"])
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertNotEqual(result["public_logic_fidelity"]["thesis_state"], "BROKEN")
        self.assertIn("architecture_bypass", result["public_logic_fidelity"]["unproven_thesis_killer_claims"])

    def test_destroyed_company_capture_label_alone_cannot_break_without_supported_killer(self) -> None:
        filing = "https://example.com/filing"
        row = self.fixture(company_capture={"state": "DESTROYED", "evidence_urls": [filing]})
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertNotEqual(result["public_logic_fidelity"]["thesis_state"], "BROKEN")
        self.assertEqual(result["public_logic_fidelity"]["company_capture"]["state"], "DESTROYED")

    def test_financing_destroyed_equity_capture_requires_bound_killer(self) -> None:
        filing = "https://example.com/filing"
        row = self.fixture(
            company_capture={"state": "DESTROYED", "evidence_urls": [filing]},
            thesis_killers=["equity_capture_destroyed_by_financing"],
            signal_evidence=self.fixture()["signal_evidence"] + [
                {"signal": "equity_capture_destroyed_by_financing", "evidence_url": filing, "as_of": "2026-01-02"}
            ],
        )
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "BROKEN")

    def test_company_capture_without_evidence_is_downgraded(self) -> None:
        row = self.fixture(company_capture={"state": "STRONG", "evidence_urls": []})
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["public_logic_fidelity"]["company_capture"]["state"], "UNPROVEN")

    def test_lead_only_social_evidence_cannot_prove_company_economics(self) -> None:
        social = "https://x.com/example/status/1"
        row = self.fixture(
            architecture={"current": "CPO", "evidence_urls": [social]},
            supply_chain_graph=[
                {"from": "module", "to": "TEST", "relationship": "claimed supplier", "evidence_url": social, "as_of": "2026-01-01"}
            ],
            dependency_signals=["semi_monopoly"],
            signals=[],
            signal_evidence=[{"signal": "semi_monopoly", "evidence_url": social, "as_of": "2026-01-01"}],
            evidence=[{"tier": "lead_only", "url": social}],
            company_capture={"state": "UNPROVEN"},
            information_gap={"state": "UNKNOWN", "evidence_urls": []},
        )
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["public_logic_fidelity"]["thesis_class"], "UNPROVEN")
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("Lead-only evidence cannot prove company economics", result["warnings"])

    def test_foreign_ticker_is_not_excluded_for_missing_sec_companyfacts(self) -> None:
        result = MODULE.assess_public_logic(self.fixture(ticker="SIVE"), self.policy)
        self.assertEqual(result["ticker"], "SIVE")

    def test_source_delta_is_chronological_and_cross_run_append_only_is_not_overclaimed(self) -> None:
        source_delta = [
            {
                "url": "https://x.com/aleabitoreddit/status/1",
                "published_at": "2026-01-01T00:00:00Z",
                "ticker_or_theme": "TEST",
                "source_view": "initial thesis",
                "stance": "positive",
                "horizon": "company-specific",
                "what_changed_vs_prior_source_view": "initial thesis",
                "retrieval_status": "retrieved",
            },
            {
                "url": "https://x.com/aleabitoreddit/status/2",
                "published_at": "2026-02-01T00:00:00Z",
                "ticker_or_theme": "TEST",
                "source_view": "financing risk increased",
                "stance": "mixed",
                "horizon": "company-specific",
                "what_changed_vs_prior_source_view": "financing risk increased",
                "retrieval_status": "retrieved",
            },
        ]
        result = MODULE.assess_public_logic(self.fixture(source_delta=source_delta), self.policy)
        self.assertEqual(result["public_logic_fidelity"]["source_delta"], source_delta)
        self.assertFalse(result["public_logic_fidelity"]["cross_run_source_delta_append_only_verified"])
        with self.assertRaises(MODULE.FidelityError):
            MODULE.assess_public_logic(self.fixture(source_delta=list(reversed(source_delta))), self.policy)

    def test_retrieved_source_delta_requires_semantic_fields(self) -> None:
        result = MODULE.assess_public_logic(
            self.fixture(source_delta=[{
                "url": "https://x.com/aleabitoreddit/status/1",
                "published_at": "2026-01-01T00:00:00Z",
                "ticker_or_theme": "",
                "source_view": "",
                "stance": "positive",
                "horizon": "",
                "what_changed_vs_prior_source_view": "",
                "retrieval_status": "retrieved",
            }]),
            self.policy,
        )
        self.assertEqual(result["public_logic_fidelity"]["source_delta"], [])

    def test_source_view_is_separate_from_company_fact_evidence(self) -> None:
        row = self.fixture(serenity_source_views=[{
            "url": "https://x.com/aleabitoreddit/status/1",
            "published_at": "2026-01-01T00:00:00Z",
            "source_view": "public market opinion",
            "stance": "positive",
            "horizon": "company-specific",
            "retrieval_status": "retrieved",
        }])
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(len(result["serenity_source_views"]), 1)
        self.assertEqual(result["evidence_summary"]["primary"], 1)

    def test_evidence_without_https_url_does_not_raise_confidence(self) -> None:
        row = self.fixture(
            evidence=[{"tier": "primary_strong", "url": ""}],
            architecture={"current": "CPO", "as_of": "2026-01-01", "evidence_urls": []},
            supply_chain_graph=[],
            signal_evidence=[],
            company_capture={"state": "UNPROVEN"},
            information_gap={"state": "UNKNOWN", "evidence_urls": []},
        )
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["evidence_summary"]["primary"], 0)
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "INSUFFICIENT_EVIDENCE")

    def test_signal_binding_requires_valid_date(self) -> None:
        customer = "https://example.com/customer"
        row = self.fixture(
            dependency_signals=["semi_monopoly"],
            signals=[],
            signal_evidence=[{"signal": "semi_monopoly", "evidence_url": customer, "as_of": "not-a-date"}],
        )
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "BENEFICIARY")

    def test_architecture_requires_valid_date(self) -> None:
        customer = "https://example.com/customer"
        result = MODULE.assess_public_logic(
            self.fixture(architecture={"current": "CPO", "as_of": "unknown", "evidence_urls": [customer]}),
            self.policy,
        )
        self.assertFalse(result["public_logic_fidelity"]["architecture_evidence_bound"])
        self.assertEqual(result["public_logic_fidelity"]["thesis_class"], "UNPROVEN")

    def test_retrieved_serenity_source_view_requires_published_date(self) -> None:
        result = MODULE.assess_public_logic(
            self.fixture(serenity_source_views=[{
                "url": "https://x.com/aleabitoreddit/status/1",
                "published_at": "unknown",
                "source_view": "some view",
                "stance": "positive",
                "horizon": "company-specific",
                "retrieval_status": "retrieved",
            }]),
            self.policy,
        )
        self.assertEqual(result["serenity_source_views"], [])

    def test_consensus_requires_institutional_validation_context(self) -> None:
        customer = "https://example.com/customer"
        row = self.fixture(
            information_gap={"state": "CONSENSUS", "evidence_urls": [customer]},
            signals=["qualification"],
            signal_evidence=self.fixture()["signal_evidence"],
        )
        result = MODULE.assess_public_logic(row, self.policy)
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "COMMERCIAL_VALIDATION")

    def test_disconfirmation_conditions_are_mandatory(self) -> None:
        with self.assertRaises(MODULE.FidelityError):
            MODULE.assess_public_logic(self.fixture(disconfirmation_conditions=[]), self.policy)

    def test_unknown_signal_is_rejected(self) -> None:
        with self.assertRaises(MODULE.FidelityError):
            MODULE.assess_public_logic(self.fixture(signals=["made_up_signal"]), self.policy)

    def test_system_score_is_bounded_and_not_called_serenity_score(self) -> None:
        encoded = json.dumps(self.policy, sort_keys=True).casefold()
        self.assertNotIn("factor_weights", encoded)
        self.assertNotIn("maximum_risk_penalty", encoded)
        self.assertNotIn("minimum_market_cap", encoded)
        self.assertNotIn("minimum_price", encoded)
        with self.assertRaises(MODULE.FidelityError):
            MODULE.assess_public_logic(self.fixture(system_operationalization_score=101), self.policy)


if __name__ == "__main__":
    unittest.main()
