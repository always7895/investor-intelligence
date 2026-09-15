"""Admission and policy verification tests for System Bottleneck Explosion Ranking Engine v1.

Tests fail-closed admission gates, claim reconciliation bounds, provenance tracking,
perturbation invariance, sector neutrality, and cardinality limits (0/1/19/20/>20).
Synthetic proof explicitly does NOT qualify live research or publication acceptance.
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

NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
STAMP = "2026-09-12T12:00:00Z"

SYNTHETIC_REGISTRY = claims_fixture.REGISTRY
SYNTHETIC_HEALTH = {s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()}


def _make_claims_and_obs(ticker: str) -> tuple[list[dict], list[dict]]:
    claims = [
        {"claim_id": f"rev_{ticker}", "claim_type": "issuer_financial_statement", "subject": ticker, "metric": "revenue", "period": "2026Q2", "unit": "million", "currency": "USD", "basis": "GAAP", "scope": "consolidated"},
        {"claim_id": f"dep_{ticker}", "claim_type": "issuer_guidance_or_contract", "subject": ticker, "metric": "architecture_layer", "period": "2026Q2", "unit": "boolean", "currency": "USD", "basis": "GAAP", "scope": "consolidated"},
        {"claim_id": f"scar_{ticker}", "claim_type": "issuer_guidance_or_contract", "subject": ticker, "metric": "effective_suppliers_count", "period": "2026Q2", "unit": "count", "currency": "USD", "basis": "GAAP", "scope": "consolidated"},
        {"claim_id": f"price_{ticker}", "claim_type": "issuer_guidance_or_contract", "subject": ticker, "metric": "contractual_price_indexation", "period": "2026Q2", "unit": "percent", "currency": "USD", "basis": "GAAP", "scope": "consolidated"},
        {"claim_id": f"cap_{ticker}", "claim_type": "issuer_financial_statement", "subject": ticker, "metric": "bom_share_capture", "period": "2026Q2", "unit": "percent", "currency": "USD", "basis": "GAAP", "scope": "consolidated"},
    ]
    obs = []
    for c in claims:
        cid = c["claim_id"]
        kind = c["claim_type"]
        metric = c["metric"]
        unit = c["unit"]
        role = "financial_statements" if kind == "issuer_financial_statement" else "guidance"
        obs.append({
            "source_id": "official", "canonical_url": f"https://official.example/{cid}",
            "published_at": STAMP, "retrieved_at": "2026-09-13T11:00:00Z",
            "content_sha256": "1" * 64, "parser_id": "official", "parser_version": "1",
            "jurisdiction": "US", "language": "en", "claim_type": kind,
            "evidence_role": role, "source_health": "HEALTHY",
            "payload": {
                "origin_group": "group_official", "claim_ids": [cid],
                "subject": ticker, "metric": metric, "period": "2026Q2",
                "unit": unit, "currency": "USD", "basis": "GAAP", "scope": "consolidated",
                "as_of": STAMP, "passage": "Official statement", "value": 100,
            }
        })
        obs.append({
            "source_id": "news", "canonical_url": f"https://news.example/{cid}",
            "published_at": STAMP, "retrieved_at": "2026-09-13T11:00:00Z",
            "content_sha256": "2" * 64, "parser_id": "news", "parser_version": "1",
            "jurisdiction": "US", "language": "en", "claim_type": kind,
            "evidence_role": "financial_reporting", "source_health": "HEALTHY",
            "payload": {
                "origin_group": "group_news", "claim_ids": [cid],
                "subject": ticker, "metric": metric, "period": "2026Q2",
                "unit": unit, "currency": "USD", "basis": "GAAP", "scope": "consolidated",
                "as_of": STAMP, "passage": "Reported fact", "value": 100,
            }
        })
    return claims, obs


def admitted_chokepoint_candidate(ticker: str = "CHOKE01", **kwargs) -> dict:
    """Fixture producing an admitted structural bottleneck candidate with valid synthetic claims."""
    claims, obs = _make_claims_and_obs(ticker)
    for key, cid in [
        ("dependency_evidence", f"dep_{ticker}"),
        ("scarcity_evidence", f"scar_{ticker}"),
        ("pricing_evidence", f"price_{ticker}"),
        ("company_capture_evidence", f"cap_{ticker}"),
    ]:
        if key in kwargs and isinstance(kwargs[key], dict) and "claim_ids" not in kwargs[key]:
            kwargs[key]["claim_ids"] = [cid]
    base = {
        "ticker": ticker,
        "name": f"Chokepoint Corp {ticker}",
        "exchange": "NASDAQ",
        "country": "US",
        "as_of": STAMP,
        "bottleneck_role": "SINGLE_SOURCE",
        "scarcity_evidence": {
            "claim_ids": [f"scar_{ticker}"],
            "corroborated_scarcity": True,
            "effective_suppliers_count": 1,
            "switching_time_months": 24,
            "details": "Sole qualified supplier of extreme-precision optical substrates.",
        },
        "dependency_evidence": {
            "claim_ids": [f"dep_{ticker}"],
            "irreplaceable_architecture_layer": True,
            "layer": "Optical interconnect substrate",
            "assessment": "Next-gen 1.6T transceivers fail without this substrate.",
        },
        "demand_evidence": {
            "structural_acceleration": True,
            "multi_year_committed": True,
            "horizon_months": 24,
            "assessment": "Hyperscale capex ramps 800G/1.6T interconnect buildout.",
        },
        "supply_constraint_evidence": {
            "lead_time_weeks": 60,
            "binding_scarcity_proven": True,
            "binding_constraint": "Specialized high-temperature MOCVD reactors.",
            "assessment": "Tool delivery lead time exceeds 14 months.",
        },
        "pricing_evidence": {
            "claim_ids": [f"price_{ticker}"],
            "contractual_price_increases_documented": True,
            "mechanism": "Long-term supply agreements with indexation.",
            "assessment": "Pricing increased 15% YoY with zero volume drop.",
        },
        "company_capture_evidence": {
            "claim_ids": [f"cap_{ticker}"],
            "dominant_bom_share": True,
            "disciplined_financing": True,
            "assessment": "Captures 70% of substrate layer profit pool.",
        },
        "operating_leverage_evidence": {
            "incremental_margin_gt_40pct": True,
            "assessment": "Incremental operating margins exceed 50%.",
        },
        "backlog_orders_evidence": {
            "current_orders": "$1.2B firm non-cancellable backlog",
            "future_orders_estimate": "$2.5B committed through 2028",
            "order_support_type": "BINDING_CONTRACT",
        },
        "catalysts_6_12_24m": [
            {"timing": "6M", "catalyst": "Fab 3 qualification completion", "status": "DATED"},
            {"timing": "12M", "catalyst": "Customer A 1.6T volume shipment commencement", "status": "DATED"},
            {"timing": "24M", "catalyst": "Gen-4 optical engine transition", "status": "DATED"},
        ],
        "thesis_killers": [
            "Customer designs out optical substrate in favor of copper DAC",
            "Competitor qualifies alternative substrate ahead of schedule",
        ],
        "financing_risk": "NONE",
        "lifecycle": "COMMERCIAL_VALIDATION",
        "long_term_return_pct": 145.2,
        "short_term_return_pct": 32.1,
        "risks_disclosed": True,
        "risk_factors": ["Customer platform delay", "Yield fluctuation"],
        "material_claims": claims,
        "source_observations": obs,
    }
    base.update(kwargs)
    return base


class BottleneckAdmissionCardinalityTests(unittest.TestCase):
    def setUp(self):
        self.policy = engine.load_json(engine.POLICY_DEFAULT_PATH)
        self.registry = SYNTHETIC_REGISTRY
        self.health_states = SYNTHETIC_HEALTH

    def test_cardinality_zero_candidates(self):
        result = engine.rank_bottleneck_candidates([], self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["total_evaluated"], 0)
        self.assertEqual(result["admitted_count"], 0)
        self.assertEqual(result["ranked_count"], 0)
        self.assertEqual(result["unranked_count"], 0)
        self.assertEqual(len(result["ranked_candidates"]), 0)

    def test_cardinality_one_candidate(self):
        cand = admitted_chokepoint_candidate("C01")
        result = engine.rank_bottleneck_candidates([cand], self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["total_evaluated"], 1)
        self.assertEqual(result["admitted_count"], 1)
        self.assertEqual(result["ranked_count"], 1)
        self.assertEqual(result["ranked_candidates"][0]["rank"], 1)

    def test_cardinality_nineteen_candidates(self):
        cands = [admitted_chokepoint_candidate(f"C{i:02d}") for i in range(19)]
        result = engine.rank_bottleneck_candidates(cands, self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["total_evaluated"], 19)
        self.assertEqual(result["admitted_count"], 19)
        self.assertEqual(result["ranked_count"], 19)
        self.assertEqual(len(result["admitted_overflow"]), 0)

    def test_cardinality_twenty_candidates(self):
        cands = [admitted_chokepoint_candidate(f"C{i:02d}") for i in range(20)]
        result = engine.rank_bottleneck_candidates(cands, self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["total_evaluated"], 20)
        self.assertEqual(result["admitted_count"], 20)
        self.assertEqual(result["ranked_count"], 20)
        self.assertEqual(len(result["admitted_overflow"]), 0)

    def test_cardinality_greater_than_twenty_candidates(self):
        cands = [admitted_chokepoint_candidate(f"C{i:02d}") for i in range(25)]
        result = engine.rank_bottleneck_candidates(cands, self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["total_evaluated"], 25)
        self.assertEqual(result["admitted_count"], 25)
        self.assertEqual(result["ranked_count"], 20)
        self.assertEqual(len(result["admitted_overflow"]), 5)
        for overflow_cand in result["admitted_overflow"]:
            self.assertIsNone(overflow_cand.get("rank"))

    def test_unadmitted_candidates_placed_in_watchlist_not_ranked(self):
        unadmitted = [
            admitted_chokepoint_candidate(f"FAIL{i:02d}", bottleneck_role="BENEFICIARY")
            for i in range(10)
        ]
        result = engine.rank_bottleneck_candidates(unadmitted, self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["admitted_count"], 0)
        self.assertEqual(result["ranked_count"], 0)
        self.assertEqual(result["unranked_count"], 10)
        self.assertEqual(len(result["low_confidence_watchlist"]), 10)


class BottleneckAdmissionClaimBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.policy = engine.load_json(engine.POLICY_DEFAULT_PATH)
        self.registry = SYNTHETIC_REGISTRY
        self.health_states = SYNTHETIC_HEALTH

    def test_claim_conflict_triggers_penalty_and_disqualification(self):
        conflicted = admitted_chokepoint_candidate("CONFLICT_CO")
        conflicted["material_claims"] = [
            {"claim_id": "rev", "claim_type": "issuer_financial_statement", "subject": "CONFLICT_CO", "metric": "revenue", "period": "2026Q2", "unit": "million", "currency": "USD", "basis": "GAAP", "scope": "consolidated"}
        ]
        conflicted["source_observations"] = [
            {"source_id": "issuer", "canonical_url": "https://issuer.example/", "published_at": "2026-09-12T00:00:00Z", "retrieved_at": "2026-09-13T00:00:00Z", "content_sha256": "a" * 64, "claim_type": "issuer_financial_statement", "evidence_role": "financial_statements", "source_health": "HEALTHY", "parser_id": "issuer", "parser_version": "1", "jurisdiction": "US", "language": "en", "payload": {"claim_ids": ["rev"], "subject": "CONFLICT_CO", "metric": "revenue", "period": "2026Q2", "unit": "million", "currency": "USD", "value": 100, "basis": "GAAP", "scope": "consolidated", "as_of": "2026-09-12T00:00:00Z", "passage": "pass", "origin_group": "group1"}},
            {"source_id": "issuer", "canonical_url": "https://issuer.example/revised", "published_at": "2026-09-12T00:00:00Z", "retrieved_at": "2026-09-13T00:00:00Z", "content_sha256": "b" * 64, "claim_type": "issuer_financial_statement", "evidence_role": "financial_statements", "source_health": "HEALTHY", "parser_id": "issuer", "parser_version": "1", "jurisdiction": "US", "language": "en", "payload": {"claim_ids": ["rev"], "subject": "CONFLICT_CO", "metric": "revenue", "period": "2026Q2", "unit": "million", "currency": "USD", "value": 200, "basis": "GAAP", "scope": "consolidated", "as_of": "2026-09-12T00:00:00Z", "passage": "pass", "origin_group": "group2"}},
        ]
        eval_res = engine.evaluate_candidate(conflicted, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertGreater(eval_res["claims_audit"]["conflicted_claim_count"], 0)
        self.assertIn("unresolved_material_claim_conflicts", eval_res["risk_flags"])
        self.assertNotEqual(eval_res["admission_status"], "ADMITTED")

    def test_forged_capability_and_fake_source_rejected(self):
        forged = admitted_chokepoint_candidate(
            "FORGED_CORP",
            material_claims=[{"claim_id": "fake_claim", "claim_type": "issuer_financial_statement", "subject": "FORGED_CORP", "metric": "revenue", "period": "2026Q2", "unit": "million", "currency": "USD", "basis": "GAAP", "scope": "consolidated"}],
            source_observations=[{"source_id": "unregistered_fake_source"}],
        )
        eval_res = engine.evaluate_candidate(forged, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertFalse(eval_res["claims_audit"]["all_material_claims_supported"])
        self.assertEqual(eval_res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_wrong_subject_observation_rejected(self):
        mismatched = admitted_chokepoint_candidate("TARGET_CO")
        mismatched["material_claims"] = [
            {"claim_id": "rev", "claim_type": "issuer_financial_statement", "subject": "TARGET_CO", "metric": "revenue", "period": "2026Q2", "unit": "million", "currency": "USD", "basis": "GAAP", "scope": "consolidated"}
        ]
        mismatched["source_observations"] = [
            {"source_id": "issuer", "canonical_url": "https://issuer.example/", "published_at": "2026-09-12T00:00:00Z", "retrieved_at": "2026-09-13T00:00:00Z", "content_sha256": "c" * 64, "claim_type": "issuer_financial_statement", "evidence_role": "financial_statements", "source_health": "HEALTHY", "parser_id": "issuer", "parser_version": "1", "jurisdiction": "US", "language": "en", "payload": {"claim_ids": ["rev"], "subject": "OTHER_WRONG_CO", "metric": "revenue", "period": "2026Q2", "unit": "million", "currency": "USD", "value": 100, "basis": "GAAP", "scope": "consolidated", "as_of": "2026-09-12T00:00:00Z", "passage": "pass", "origin_group": "group1"}},
        ]
        eval_res = engine.evaluate_candidate(mismatched, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertFalse(eval_res["claims_audit"]["all_material_claims_supported"])


class BottleneckAdmissionInvarianceAndNeutralityTests(unittest.TestCase):
    def setUp(self):
        self.policy = engine.load_json(engine.POLICY_DEFAULT_PATH)
        self.registry = SYNTHETIC_REGISTRY
        self.health_states = SYNTHETIC_HEALTH

    def test_historical_return_perturbation_invariance(self):
        c_base = admitted_chokepoint_candidate("INV01", long_term_return_pct=100.0, short_term_return_pct=20.0)
        c_perturbed = admitted_chokepoint_candidate("INV01", long_term_return_pct=-50.0, short_term_return_pct=-30.0)

        e_base = engine.evaluate_candidate(c_base, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        e_perturbed = engine.evaluate_candidate(c_perturbed, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)

        self.assertEqual(e_base["system_bottleneck_explosion_score"], e_perturbed["system_bottleneck_explosion_score"])
        self.assertEqual(e_base["admission_status"], e_perturbed["admission_status"])
        self.assertEqual(e_base["raw_factor_score"], e_perturbed["raw_factor_score"])
        self.assertEqual(e_base["downside_penalty"], e_perturbed["downside_penalty"])

    def test_non_ai_sector_with_valid_chokepoint_admitted(self):
        power_transformer = admitted_chokepoint_candidate(
            "GRID_TRANS",
            name="High Voltage Grid Transformer Corp",
            dependency_evidence={
                "irreplaceable_architecture_layer": True,
                "layer": "Ultra-High Voltage Substation Transformer",
                "assessment": "Grid interconnection impossible without 500kV GSU transformers.",
            },
            supply_constraint_evidence={
                "lead_time_weeks": 104,
                "binding_scarcity_proven": True,
                "binding_constraint": "Grain-oriented electrical steel (GOES) and test bays.",
                "assessment": "Factory lead time exceeds 24 months across all qualified makers.",
            },
        )
        eval_res = engine.evaluate_candidate(power_transformer, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(eval_res["admission_status"], "ADMITTED")
        self.assertGreaterEqual(eval_res["system_bottleneck_explosion_score"], 70.0)

    def test_all_old_unadmitted_tickers_reevaluated_not_retained(self):
        old_tickers = ["ACGL", "AFRM", "BBY", "CDE", "FIS", "HIG", "HST"]
        candidates = [
            {
                "ticker": t,
                "name": f"Legacy {t}",
                "bottleneck_role": "BENEFICIARY",
                "long_term_return_pct": 80.0,
                "short_term_return_pct": 25.0,
            }
            for t in old_tickers
        ]
        result = engine.rank_bottleneck_candidates(candidates, self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["admitted_count"], 0)
        self.assertEqual(result["ranked_count"], 0)
        self.assertEqual(result["unranked_count"], len(old_tickers))

    def test_substitute_availability_and_dilution_cannot_improve_eligibility(self):
        tight = admitted_chokepoint_candidate("TIGHT", financing_risk="NONE", scarcity_evidence={"corroborated_scarcity": True, "switching_time_months": 24})
        diluted = admitted_chokepoint_candidate("DILUTED", financing_risk="DESTROYED", scarcity_evidence={"corroborated_scarcity": True, "switching_time_months": 24})
        relieved = admitted_chokepoint_candidate("RELIEVED", financing_risk="NONE", scarcity_evidence={"shortage_relieved": True, "switching_time_months": 24})

        e_tight = engine.evaluate_candidate(tight, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        e_diluted = engine.evaluate_candidate(diluted, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        e_relieved = engine.evaluate_candidate(relieved, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)

        self.assertEqual(e_tight["admission_status"], "ADMITTED")
        self.assertEqual(e_diluted["admission_status"], "DISQUALIFIED_FINANCING_DESTROYED")
        self.assertGreater(e_tight["system_bottleneck_explosion_score"], e_relieved["system_bottleneck_explosion_score"])

    def test_customer_only_and_expansion_only_rejected(self):
        c_cust = admitted_chokepoint_candidate(
            "CUST_ONLY",
            dependency_evidence={"customer_relationship_only": True, "irreplaceable_architecture_layer": False},
        )
        c_exp = admitted_chokepoint_candidate(
            "EXP_ONLY",
            supply_constraint_evidence={"expansion_announcement_only": True, "binding_scarcity_proven": False},
        )
        e_cust = engine.evaluate_candidate(c_cust, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        e_exp = engine.evaluate_candidate(c_exp, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(e_cust["dependency_criticality"]["score"], 0.0)
        self.assertEqual(e_exp["supply_constraint"]["score"], 0.0)

    def test_missing_risk_disclosure_not_an_advantage(self):
        c_disclosed = admitted_chokepoint_candidate("DISCLOSED", risks_disclosed=True, risk_factors=["Delay"])
        c_missing = admitted_chokepoint_candidate("MISSING", risks_disclosed=False, risk_factors=[])
        e_disclosed = engine.evaluate_candidate(c_disclosed, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        e_missing = engine.evaluate_candidate(c_missing, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertIn("omitted_risk_disclosure_penalty", e_missing["risk_flags"])
        self.assertGreater(e_disclosed["system_bottleneck_explosion_score"], e_missing["system_bottleneck_explosion_score"])

    def test_deep_input_immutability(self):
        original = admitted_chokepoint_candidate("ORIGINAL")
        snapshot = copy.deepcopy(original)
        _ = engine.evaluate_candidate(original, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(original, snapshot)
        _ = engine.rank_bottleneck_candidates([original], self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(original, snapshot)

    def test_provenance_and_rationale_fields_populated(self):
        cand = admitted_chokepoint_candidate("PROV_TEST")
        eval_res = engine.evaluate_candidate(cand, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertIn("provenance", eval_res["dependency_criticality"])
        self.assertIn("contribution_breakdown", eval_res["dependency_criticality"])
        self.assertIn("rank_rationale", eval_res)
        self.assertIn("historical_returns_context", eval_res)
        self.assertEqual(eval_res["historical_returns_context"]["influence_on_score"], 0.0)

    def test_cli_execution(self):
        """CLI without typed in-process acquisition must fail closed: zero admitted, all unranked."""
        candidates = [admitted_chokepoint_candidate(f"CLI{i:02d}") for i in range(3)]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            in_file = tmp_path / "candidates.json"
            out_file = tmp_path / "output.json"
            in_file.write_text(json.dumps(candidates), encoding="utf-8")

            cmd = [
                sys.executable,
                str(ROOT / "scripts" / "bottleneck_ranking.py"),
                "--input", str(in_file),
                "--output", str(out_file),
                "--policy", str(engine.POLICY_DEFAULT_PATH),
                "--top-count", "20",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"CLI stderr: {proc.stderr}")
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["ranked_count"], 0)
            self.assertEqual(data["admitted_count"], 0)
            self.assertEqual(data["unranked_count"], 3)
            self.assertEqual(data["publication_status"], "NOT_PUBLICATION_QUALIFIED")
            self.assertEqual(data["live_qualification"], "DEFERRED")


if __name__ == "__main__":
    unittest.main()
