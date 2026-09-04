#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6b_full_top20 as h6b


class H6BTests(unittest.TestCase):
    def h6a_fixture(self) -> dict:
        return {
            "summary": {
                "completed": 7,
                "failed": 0,
                "hard_dependency_count": 0,
                "production_ranking_changed": False,
            },
            "h6_source_history_attestation": {
                "entries": 4,
                "latest_hash": "3b1e34fdd385ec3816a4f60a9f803cd1a3f64d2899cdc81c49e4cf5f36ed8102",
                "structural_chain_verified": True,
            },
            "results": [{
                "ticker": "SIVE",
                "supported_signals": {"commercial_validation": ["customer_named_ramp"]},
                "public_logic_fidelity": {
                    "company_capture": {"state": "POSITIVE"},
                    "dependency_role": "BENEFICIARY",
                },
                "independent_graph_edge_count": 1,
                "h6_logic_refinement": {
                    "financing_operating_split": {
                        "operating_thesis_state": "INSUFFICIENT_EVIDENCE",
                        "financing_severity": "MATERIAL_OVERHANG",
                    }
                },
            }],
        }

    def test_sive_operating_axis_reconciles_without_bottleneck(self) -> None:
        result = h6b.reconcile_methodology(self.h6a_fixture())
        row = result["archetype_results"][0]
        self.assertEqual(
            row["h6_logic_refinement"]["financing_operating_split"]["operating_thesis_state"],
            "COMMERCIAL_VALIDATION",
        )
        self.assertEqual(row["public_logic_fidelity"]["dependency_role"], "BENEFICIARY")
        self.assertTrue(row["legacy_fidelity_confidence_deprecated"])

    def test_tsem_contracts_are_supported_and_future_is_not_invented(self) -> None:
        def fake(url: str) -> str:
            if url == h6b.TSEM_CONTRACTS:
                return "$1.3 billion for 2027 revenue; $290 million customer prepayments; larger contractual wafer commitment for 2028"
            if url == h6b.TSEM_EXPANSION:
                return "Silicon Photonics capacity supports accelerating customer demand; full production readiness expected during the fourth quarter of 2027"
            raise AssertionError(url)

        result = h6b.tsem_outlook(fake)
        self.assertEqual(result["claim_grounding"]["current_orders_summary"], "SUPPORTED")
        self.assertTrue(result["numeric_total_order_estimate_prohibited"])
        self.assertIn("US$13億", result["current_orders_summary"])

    def test_cohr_multiyear_purchase_commitment_is_not_dependency_proof(self) -> None:
        def fake(url: str) -> str:
            if url == h6b.COHR_NVIDIA:
                return "multiyear strategic agreement with a multibillion-dollar purchase commitment and future access and capacity rights"
            if url == h6b.COHR_FY26:
                return "exceptional customer demand, expanding production capacity, and multiple new growth platforms beginning to ramp"
            raise AssertionError(url)

        result = h6b.cohr_outlook(fake)
        self.assertEqual(result["claim_grounding"]["current_orders_summary"], "SUPPORTED")
        self.assertEqual(result["claim_grounding"]["future_orders_estimate"], "INFERENCE")
        self.assertTrue(result["numeric_total_order_estimate_prohibited"])

    def test_sive_pipeline_is_explicitly_not_booked_order(self) -> None:
        def fake(url: str) -> str:
            if url == h6b.SIVE_Q2:
                return "Pipeline grows to USD 1.2 billion; USD 8.2 m production order; supporting a 2027 production ramp"
            if url == h6b.SIVE_CEO_Q2:
                return "$8.2M production order; initial $3M production order; initial $3.4M program order; anticipate production orders in H1 2027"
            raise AssertionError(url)

        result = h6b.sive_outlook(fake)
        self.assertIn("pipeline、非已下單", result["current_orders_summary"])
        self.assertEqual(result["claim_grounding"]["future_orders_estimate"], "INFERENCE")

    def test_unavailable_order_data_fails_closed(self) -> None:
        result = h6b.unavailable_outlook()
        self.assertEqual(result["current_orders_summary"], h6b.CURRENT_FALLBACK)
        self.assertEqual(result["future_orders_estimate"], h6b.FUTURE_FALLBACK)
        self.assertTrue(result["numeric_total_order_estimate_prohibited"])
        self.assertEqual(result["evidence_status"], "UNAVAILABLE")

    def test_policy_deprecates_legacy_confidence(self) -> None:
        policy = h6b.load_policy()
        self.assertEqual(
            policy["legacy_fidelity_confidence_status"],
            "deprecated_do_not_use_for_downstream_decisions",
        )
        self.assertTrue(
            policy["dependency_fail_closed"][
                "hard_dependency_requires_independent_scarcity_or_effective_capacity_evidence"
            ]
        )


if __name__ == "__main__":
    unittest.main()
