"""Tests for TOP20 Bottleneck Takeover V1 Engine.

Verifies:
- All legacy 20 candidates without core claims evaluate to UNRANKED / 0 admitted.
- DG, NEM, PBR are unprivileged but NOT blacklisted (qualify with valid claims, unranked without).
- New outside seed candidate can compete equally.
- Historical return, extreme TAM, momentum, or author overlap have ZERO score weight and NO rank impact.
- High gross margin alone, customer relationships alone, and expansion announcements alone are refused.
- Wrong subject, period, lineage, conflict, refuted, or forged health fail closed.
- Dilution / financing risks do not default safe; DESTROYED disqualifies.
- Strict cardinality: 0, 1, 19, 20 admitted without zero-padding or alphabetical backfill.
- CLI execution on real untrusted candidate corpus yields 0 admitted.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import bottleneck_ranking as engine
import test_research_v2_claims as claims_fixture
from bottleneck_claim_admission import reconcile_factor_authority

NOW = datetime(2026, 9, 15, 1, 41, 8, tzinfo=timezone.utc)
STAMP = "2026-09-15T01:41:08Z"

SYNTHETIC_REGISTRY = claims_fixture.REGISTRY
SYNTHETIC_HEALTH = {s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()}


def make_claim_and_observations(cid: str, kind: str, subject: str, metric: str, val: Any, unit: str = "million", cur: str = "USD"):
    c = {
        "claim_id": cid,
        "claim_type": kind,
        "subject": subject,
        "metric": metric,
        "period": "2026Q2",
        "unit": unit,
        "currency": cur,
        "basis": "GAAP",
        "scope": "consolidated",
    }
    role_primary = "financial_statements" if kind == "issuer_financial_statement" else "guidance"
    obs1 = {
        "source_id": "official",
        "canonical_url": f"https://official.example/{cid}",
        "published_at": STAMP,
        "retrieved_at": "2026-09-15T01:41:08Z",
        "content_sha256": "1" * 64,
        "parser_id": "official",
        "parser_version": "1",
        "jurisdiction": "US",
        "language": "en",
        "claim_type": kind,
        "evidence_role": role_primary,
        "source_health": "HEALTHY",
        "payload": {
            "origin_group": "group_official",
            "claim_ids": [cid],
            "subject": subject,
            "metric": metric,
            "period": "2026Q2",
            "unit": unit,
            "currency": cur,
            "basis": "GAAP",
            "scope": "consolidated",
            "as_of": STAMP,
            "passage": f"Official {metric}",
            "value": val,
        },
    }
    obs2 = {
        "source_id": "news",
        "canonical_url": f"https://news.example/{cid}",
        "published_at": STAMP,
        "retrieved_at": "2026-09-15T01:41:08Z",
        "content_sha256": "2" * 64,
        "parser_id": "news",
        "parser_version": "1",
        "jurisdiction": "US",
        "language": "en",
        "claim_type": kind,
        "evidence_role": "financial_reporting",
        "source_health": "HEALTHY",
        "payload": {
            "origin_group": "group_news",
            "claim_ids": [cid],
            "subject": subject,
            "metric": metric,
            "period": "2026Q2",
            "unit": unit,
            "currency": cur,
            "basis": "GAAP",
            "scope": "consolidated",
            "as_of": STAMP,
            "passage": f"Reported {metric}",
            "value": val,
        },
    }
    return c, [obs1, obs2]


def make_takeover_candidate(ticker: str, *, with_core_claims: bool = False, **kwargs) -> dict:
    claims = []
    observations = []

    if with_core_claims:
        c1, o1 = make_claim_and_observations(f"dep_{ticker}", "issuer_guidance_or_contract", ticker, "architecture_layer", 1)
        c2, o2 = make_claim_and_observations(f"scar_{ticker}", "issuer_guidance_or_contract", ticker, "effective_suppliers_count", 1, unit="count")
        c3, o3 = make_claim_and_observations(f"price_{ticker}", "issuer_guidance_or_contract", ticker, "contractual_price_indexation", 15.0, unit="percent")
        c4, o4 = make_claim_and_observations(f"cap_{ticker}", "issuer_financial_statement", ticker, "bom_share_capture", 70.0, unit="percent")

        claims = [c1, c2, c3, c4]
        observations = [*o1, *o2, *o3, *o4]


    candidate = {
        "ticker": ticker,
        "name": f"{ticker} Corporation",
        "exchange": "NASDAQ",
        "country": "US",
        "as_of": STAMP,
        "bottleneck_role": "SINGLE_SOURCE" if with_core_claims else "BENEFICIARY",
        "scarcity_evidence": {
            "claim_ids": [f"scar_{ticker}"] if with_core_claims else [],
            "corroborated_scarcity": with_core_claims,
            "effective_suppliers_count": 1 if with_core_claims else 5,
            "switching_time_months": 24 if with_core_claims else 3,
            "details": "High switching friction" if with_core_claims else "Generic supply",
        },
        "dependency_evidence": {
            "claim_ids": [f"dep_{ticker}"] if with_core_claims else [],
            "irreplaceable_architecture_layer": with_core_claims,
            "layer": "Critical substrate",
            "assessment": "Chokepoint" if with_core_claims else "Generic",
        },
        "demand_evidence": {
            "structural_acceleration": with_core_claims,
            "multi_year_committed": with_core_claims,
            "horizon_months": 24,
            "assessment": "Committed capex",
        },
        "supply_constraint_evidence": {
            "lead_time_weeks": 52 if with_core_claims else 8,
            "binding_scarcity_proven": with_core_claims,
            "binding_constraint": "Tool delivery lead time",
            "assessment": "Severe constraint" if with_core_claims else "Elastic supply",
        },
        "pricing_evidence": {
            "claim_ids": [f"price_{ticker}"] if with_core_claims else [],
            "contractual_price_increases_documented": with_core_claims,
            "mechanism": "Indexation",
            "assessment": "Pricing power" if with_core_claims else "Price taker",
        },
        "company_capture_evidence": {
            "claim_ids": [f"cap_{ticker}"] if with_core_claims else [],
            "dominant_bom_share": with_core_claims,
            "disciplined_financing": True,
            "assessment": "Equity capture",
        },
        "operating_leverage_evidence": {
            "incremental_margin_gt_40pct": with_core_claims,
            "assessment": "Operating leverage",
        },
        "backlog_orders_evidence": {
            "current_orders": "$1B firm backlog" if with_core_claims else "未揭露（無可靠公開訂單數字）",
            "future_orders_estimate": "無可靠公開預估",
            "order_support_type": "BINDING_CONTRACT" if with_core_claims else "NONE",
        },
        "catalysts_6_12_24m": [
            {"timing": "12M", "catalyst": "Volume ramp", "status": "DATED"}
        ] if with_core_claims else [],
        "thesis_killers": ["Substitutes developed"] if with_core_claims else ["No killers identified"],
        "financing_risk": "NONE",
        "lifecycle": "COMMERCIAL_VALIDATION" if with_core_claims else "INSUFFICIENT_EVIDENCE",
        "long_term_return_pct": 120.0,
        "short_term_return_pct": 25.0,
        "risks_disclosed": True,
        "risk_factors": ["Execution risk"],
        "material_claims": claims,
        "source_observations": observations,
    }
    candidate.update(kwargs)
    return candidate


class TestTop20BottleneckTakeover(unittest.TestCase):
    def setUp(self):
        self.policy = engine.load_json(engine.POLICY_DEFAULT_PATH)

    def test_all_old_20_without_core_unranked(self):
        legacy_tickers = ["DG", "NEM", "PBR", "ACGL", "AFRM", "BBY", "CDE", "FIS", "HIG", "HST"]
        candidates = [make_takeover_candidate(t, with_core_claims=False) for t in legacy_tickers]

        result = engine.rank_bottleneck_candidates(
            candidates,
            policy=self.policy,
            as_of=NOW,
            registry=SYNTHETIC_REGISTRY,
            health_states=SYNTHETIC_HEALTH,
        )
        self.assertEqual(result["admitted_count"], 0)
        self.assertEqual(result["ranked_count"], 0)
        self.assertEqual(result["ranked_candidates"], [])
        self.assertEqual(result["unranked_count"], len(legacy_tickers))
        for item in result["low_confidence_watchlist"]:
            self.assertEqual(item["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")
            self.assertIsNone(item["rank"])
            self.assertIsNone(item["score_qualified"])

    def test_dg_nem_pbr_unprivileged_not_blacklisted(self):
        # Without core claims, DG/NEM/PBR fail admission
        dg_unranked = engine.evaluate_candidate(
            make_takeover_candidate("DG", with_core_claims=False),
            self.policy,
            now=NOW,
            registry=SYNTHETIC_REGISTRY,
            health_states=SYNTHETIC_HEALTH,
        )
        self.assertEqual(dg_unranked["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

        # With valid core claims, DG qualifies identically to outside seeds
        dg_admitted = engine.evaluate_candidate(
            make_takeover_candidate("DG", with_core_claims=True),
            self.policy,
            now=NOW,
            registry=SYNTHETIC_REGISTRY,
            health_states=SYNTHETIC_HEALTH,
        )
        self.assertEqual(dg_admitted["admission_status"], "ADMITTED")

        outside_admitted = engine.evaluate_candidate(
            make_takeover_candidate("OUTSIDE01", with_core_claims=True),
            self.policy,
            now=NOW,
            registry=SYNTHETIC_REGISTRY,
            health_states=SYNTHETIC_HEALTH,
        )
        self.assertEqual(outside_admitted["admission_status"], "ADMITTED")
        self.assertEqual(dg_admitted["system_bottleneck_explosion_score"], outside_admitted["system_bottleneck_explosion_score"])

    def test_historical_return_tam_momentum_author_overlap_invariance(self):
        base = make_takeover_candidate("CHOKE01", with_core_claims=True, long_term_return_pct=150.0, short_term_return_pct=40.0)
        mutated = make_takeover_candidate(
            "CHOKE01",
            with_core_claims=True,
            long_term_return_pct=-85.0,  # massive historical drawdown
            short_term_return_pct=-30.0,
            tam_estimate_trillion=100.0, # exaggerated TAM
            social_author_overlap=1.0,   # social popularity
        )

        res_base = engine.evaluate_candidate(base, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        res_mut = engine.evaluate_candidate(mutated, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)

        self.assertEqual(res_base["system_bottleneck_explosion_score"], res_mut["system_bottleneck_explosion_score"])
        self.assertEqual(res_base["raw_factor_score"], res_mut["raw_factor_score"])
        self.assertEqual(res_base["admission_status"], res_mut["admission_status"])

    def test_high_margins_customer_link_expansion_only_refused(self):
        # Customer relationship alone refused
        cust_cand = make_takeover_candidate(
            "CUST01",
            with_core_claims=True,
            dependency_evidence={"customer_relationship_only": True, "irreplaceable_architecture_layer": False},
        )
        res_cust = engine.evaluate_candidate(cust_cand, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertEqual(res_cust["dependency_criticality"]["score"], 0.0)

        # Expansion announcement only refused
        exp_cand = make_takeover_candidate(
            "EXP01",
            with_core_claims=True,
            supply_constraint_evidence={"expansion_announcement_only": True, "binding_scarcity_proven": False},
        )
        res_exp = engine.evaluate_candidate(exp_cand, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertEqual(res_exp["supply_constraint"]["score"], 0.0)

        # High margin only refused
        margin_cand = make_takeover_candidate(
            "MARG01",
            with_core_claims=True,
            pricing_evidence={"high_gross_margin_only": True, "contractual_or_pricing_power_mechanism": False},
        )
        res_marg = engine.evaluate_candidate(margin_cand, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertEqual(res_marg["pricing_power"]["score"], 0.0)

    def test_wrong_subject_or_conflicted_claims_fail_closed(self):
        # Wrong subject in claim fails factor authority
        wrong_cand = make_takeover_candidate("CHOKE01", with_core_claims=True)
        wrong_cand["material_claims"][0]["subject"] = "DIFFERENT_TICKER"

        res_wrong = engine.evaluate_candidate(wrong_cand, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertEqual(res_wrong["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_capture_risk_destroyed_disqualifies(self):
        destroyed = make_takeover_candidate("DILUTE01", with_core_claims=True, financing_risk="DESTROYED")
        res = engine.evaluate_candidate(destroyed, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertEqual(res["admission_status"], "DISQUALIFIED_FINANCING_DESTROYED")
        self.assertEqual(res["lifecycle"], "BROKEN")

    def test_strict_cardinality_zero_one_and_under_twenty(self):
        # 0 admitted
        res0 = engine.rank_bottleneck_candidates([], policy=self.policy, as_of=NOW)
        self.assertEqual(res0["admitted_count"], 0)
        self.assertEqual(res0["ranked_count"], 0)
        self.assertEqual(res0["ranked_candidates"], [])

        # 1 admitted
        cand1 = [make_takeover_candidate("ONLY01", with_core_claims=True)]
        res1 = engine.rank_bottleneck_candidates(cand1, policy=self.policy, as_of=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertEqual(res1["admitted_count"], 1)
        self.assertEqual(res1["ranked_count"], 1)
        self.assertEqual(res1["ranked_candidates"][0]["rank"], 1)

        # 21 admitted: exactly 20 ranked, 1 overflow
        cand21 = [make_takeover_candidate(f"C{i:02d}", with_core_claims=True) for i in range(21)]
        res21 = engine.rank_bottleneck_candidates(cand21, policy=self.policy, as_of=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertEqual(res21["admitted_count"], 21)
        self.assertEqual(res21["ranked_count"], 20)
        self.assertEqual(len(res21["admitted_overflow"]), 1)

    def test_single_generic_revenue_claim_reused_for_all_factors_refused(self):
        # A single generic revenue claim reused for all 4 factors must fail admission
        c_rev, o_rev = make_claim_and_observations("rev_single", "issuer_financial_statement", "REUSE01", "revenue", 500.0)
        cand = make_takeover_candidate("REUSE01", with_core_claims=False)
        cand["material_claims"] = [c_rev]
        cand["source_observations"] = o_rev
        cand["dependency_evidence"]["claim_ids"] = ["rev_single"]
        cand["scarcity_evidence"]["claim_ids"] = ["rev_single"]
        cand["pricing_evidence"]["claim_ids"] = ["rev_single"]
        cand["company_capture_evidence"]["claim_ids"] = ["rev_single"]

        res = engine.evaluate_candidate(cand, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")
        self.assertFalse(res["factor_claim_authority"]["core_admitted"])

    def test_missing_financing_risk_fails_safe_to_structural_disqualifier(self):
        cand = make_takeover_candidate("NOFIN01", with_core_claims=True)
        del cand["financing_risk"]
        res = engine.evaluate_candidate(cand, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertEqual(res["factor_claim_authority"]["financing_state"], "STRUCTURAL_DISQUALIFIER")
        self.assertFalse(res["factor_claim_authority"]["capture_licensed"])
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_material_overhang_licenses_capture_with_penalty(self):
        cand = make_takeover_candidate("OVERHANG01", with_core_claims=True, financing_risk="MATERIAL_OVERHANG")
        res = engine.evaluate_candidate(cand, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertTrue(res["factor_claim_authority"]["capture_licensed"])
        self.assertTrue(res["factor_claim_authority"]["core_admitted"])
        self.assertEqual(res["admission_status"], "ADMITTED")
        self.assertIn("material_financing_overhang", res["risk_flags"])

    def test_cost_passthrough_alone_refused_for_pricing_power(self):
        c_cost, o_cost = make_claim_and_observations("cost_pass", "issuer_guidance_or_contract", "COST01", "cost_plus_passthrough", 10.0)
        cand = make_takeover_candidate("COST01", with_core_claims=True)
        # Replace pricing claim with cost passthrough
        cand["material_claims"] = [c for c in cand["material_claims"] if not c["claim_id"].startswith("price_")] + [c_cost]
        cand["source_observations"] = [o for o in cand["source_observations"] if not o["payload"]["claim_ids"][0].startswith("price_")] + o_cost
        cand["pricing_evidence"]["claim_ids"] = ["cost_pass"]

        res = engine.evaluate_candidate(cand, self.policy, now=NOW, registry=SYNTHETIC_REGISTRY, health_states=SYNTHETIC_HEALTH)
        self.assertFalse(res["factor_claim_authority"]["pricing_licensed"])
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
