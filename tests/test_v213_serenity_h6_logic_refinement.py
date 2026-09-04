#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6_logic_refinement as h6


class H6LogicRefinementTests(unittest.TestCase):
    def history(self):
        return [
            {
                "source_id": "x-2013947011490615486",
                "published_at": "2026-01-21",
                "time_precision": "DATE_ONLY",
                "previous_hash": "GENESIS",
                "record_hash": "a" * 64,
            },
            {
                "source_id": "x-2033889361801175094",
                "published_at": "2026-03-17",
                "time_precision": "DATE_ONLY",
                "previous_hash": "a" * 64,
                "record_hash": "b" * 64,
            },
        ]

    def aaoi(self):
        return {
            "ticker": "AAOI",
            "evidence_summary": {"primary": 7, "corroborating": 0, "lead_only": 12},
            "serenity_source_views": [
                {
                    "scope": "ticker_view",
                    "source_id": "x-2033889361801175094",
                    "published_at": "2026-03-17",
                    "factual_dependency_proof": False,
                }
            ],
            "warnings": [
                "No validated Serenity source view is attached; public-logic analysis is not a claim that Serenity discussed this ticker",
                "Supply-chain graph has no evidence-bound edges",
            ],
            "supported_signals": {"commercial_validation": [], "expansion": ["capacity_expansion"]},
            "public_logic_fidelity": {
                "architecture_evidence_bound": True,
                "supply_chain_graph": [],
                "graph_touches_focal_company": False,
                "dependency_role": "UNPROVEN",
                "thesis_class": "EXPANSION_THESIS",
                "thesis_state": "THESIS_WEAKENING",
                "company_capture": {"state": "MIXED", "evidence_urls": ["https://sec.example/filing"]},
                "thesis_killers": ["repeated_atm_or_material_dilution"],
                "timing": {
                    "entry_context": "unknown",
                    "architecture_ramp_window": "unknown",
                    "operating_thesis_horizon": "unknown",
                    "valuation_expectation_context": "unknown",
                },
            },
            "identity_verification": {"applicable": False},
        }

    def test_wrong_identity_corpus_is_quarantined(self):
        lineage = h6.load_lineage()
        wrong = [f for f in lineage["families"] if f.get("identity") == "@stockgodserenity"]
        self.assertEqual(len(wrong), 1)
        self.assertEqual(wrong[0]["kind"], "quarantined_wrong_identity")
        self.assertFalse(wrong[0]["can_prove_company_fact"])

    def test_archive_and_skills_have_zero_factual_weight(self):
        lineage = h6.load_lineage()
        for family in lineage["families"]:
            if family.get("kind") in {
                "archive_and_methodology_reference",
                "derived_archive_skill",
                "independent_methodology_distillation",
                "public_corpus_semantic_review_method",
                "secondary_methodology_distillation",
            }:
                self.assertFalse(family["can_prove_company_fact"])
                self.assertFalse(family["can_prove_dependency"])
                self.assertEqual(family["independent_corroboration_weight"], 0)

    def test_history_links_validate_but_do_not_overclaim_cross_run(self):
        att = h6.validate_history_links(self.history())
        self.assertTrue(att["structural_chain_verified"])
        self.assertFalse(att["cross_run_append_only_verified"])
        self.assertEqual(att["latest_hash"], "b" * 64)

    def test_march_aaoi_view_is_stale_with_newer_archive_lead(self):
        hist = {x["source_id"]: x for x in self.history()}
        result = h6.source_view_freshness(self.aaoi(), date(2026, 9, 1), hist)
        self.assertEqual(result["lifecycle"], "STALE_WITH_NEWER_ARCHIVE_LEAD")
        self.assertEqual(result["newer_archive_lead"]["published_at"], "2026-07-13")
        self.assertFalse(result["archive_lead_is_factual_proof"])

    def test_post_enrichment_warning_reconciliation(self):
        row = self.aaoi()
        warnings = h6.reconcile_warnings(row)
        self.assertFalse(any("No validated Serenity source view" in x for x in warnings))
        self.assertTrue(any("Supply-chain graph" in x for x in warnings))

    def test_architecture_warning_is_removed_after_bound_architecture(self):
        row = self.aaoi()
        row["warnings"].extend([
            "Architecture/supercycle claim lacks a valid as_of date",
            "Architecture/supercycle claim lacks primary/corroborating evidence binding",
            "Architecture/supercycle identity is missing",
        ])
        warnings = h6.reconcile_warnings(row)
        self.assertFalse(any("Architecture/supercycle" in x for x in warnings))

    def test_financing_overhang_does_not_erase_operating_thesis(self):
        overlay = h6.financing_overlay(self.aaoi())
        self.assertEqual(overlay["operating_thesis_state"], "DISCOVERY")
        self.assertEqual(overlay["financing_severity"], "MATERIAL_OVERHANG")
        self.assertNotEqual(overlay["combined_research_state"], "BROKEN_BY_EQUITY_CAPTURE")

    def test_equity_capture_destroyed_is_severe(self):
        row = self.aaoi()
        row["public_logic_fidelity"]["thesis_killers"] = ["equity_capture_destroyed_by_financing"]
        overlay = h6.financing_overlay(row)
        self.assertEqual(overlay["financing_severity"], "DESTROYED")
        self.assertEqual(overlay["combined_research_state"], "BROKEN_BY_EQUITY_CAPTURE")

    def test_confidence_is_multi_axis(self):
        hist = {x["source_id"]: x for x in self.history()}
        freshness = h6.source_view_freshness(self.aaoi(), date(2026, 9, 1), hist)
        axes = h6.multi_axis_confidence(self.aaoi(), freshness)
        self.assertEqual(axes["factual_evidence_confidence"], "HIGH")
        self.assertEqual(axes["dependency_confidence"], "LOW_UNPROVEN")
        self.assertEqual(axes["company_capture_confidence"], "HIGH")
        self.assertEqual(axes["timing_confidence"], "LOW")

    def test_order_outlook_is_supported_plus_inference_not_invented_total(self):
        row = self.aaoi()
        row["h5_qualified_substitute_capacity"] = {
            "order_outlook": {
                "current_orders_summary": "signed commitments",
                "future_orders_estimate": "visibility high; total not estimated",
                "numeric_total_order_estimate_prohibited": True,
                "evidence_urls": ["https://sec.example/a", "https://sec.example/b"],
            }
        }
        grounding = h6.claim_grounding(row)["material_claims"]
        self.assertEqual(grounding[0]["classification"], "SUPPORTED")
        self.assertEqual(grounding[1]["classification"], "INFERENCE")

    def test_refine_report_preserves_hard_dependency_zero(self):
        report = {
            "generated_at": "2026-09-01T07:08:43Z",
            "results": [self.aaoi()],
            "summary": {"hard_dependency_count": 0, "production_ranking_changed": False},
        }
        refined = h6.refine_report(report, self.history(), h6.load_lineage())
        self.assertEqual(refined["summary"]["hard_dependency_count"], 0)
        self.assertFalse(refined["summary"]["production_ranking_changed"])
        self.assertTrue(refined["summary"]["h6_public_logic_refinement_applied"])


if __name__ == "__main__":
    unittest.main()
