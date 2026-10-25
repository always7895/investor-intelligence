"""Tests for System Bottleneck Explosion Ranking Engine v1.

Deterministic, offline regression covering admission gates, rubric scoring,
downside penalties, schema completeness, CLI execution, and input immutability.
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


def valid_chokepoint_candidate(ticker: str = "CHOKE01", **kwargs) -> dict:
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


class BottleneckRankingTests(unittest.TestCase):
    def setUp(self):
        self.policy = engine.load_json(engine.POLICY_DEFAULT_PATH)
        self.registry = claims_fixture.REGISTRY
        self.health_states = {s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()}

    def test_deterministic_cardinality_zero_candidates(self):
        result = engine.rank_bottleneck_candidates([], self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["total_evaluated"], 0)
        self.assertEqual(result["admitted_count"], 0)
        self.assertEqual(result["ranked_count"], 0)
        self.assertEqual(result["unranked_count"], 0)
        self.assertEqual(result["ranked_candidates"], [])

    def test_deterministic_cardinality_one_candidate(self):
        candidates = [valid_chokepoint_candidate("SOLO")]
        result = engine.rank_bottleneck_candidates(candidates, self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["admitted_count"], 1)
        self.assertEqual(result["ranked_count"], 1)
        self.assertEqual(result["ranked_candidates"][0]["ticker"], "SOLO")
        self.assertEqual(result["ranked_candidates"][0]["rank"], 1)

    def test_deterministic_cardinality_nineteen_candidates_no_padding(self):
        candidates = [valid_chokepoint_candidate(f"CK{i:02d}") for i in range(19)]
        result = engine.rank_bottleneck_candidates(candidates, self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["admitted_count"], 19)
        self.assertEqual(result["ranked_count"], 19)
        self.assertEqual(len(result["ranked_candidates"]), 19)
        # Ensure ranks are strictly 1..19 and no zero-padding or lexical backfills exist
        self.assertEqual([r["rank"] for r in result["ranked_candidates"]], list(range(1, 20)))
        self.assertFalse(result["cardinality_rules"]["zero_padding_used"])
        self.assertFalse(result["cardinality_rules"]["lexical_backfill_used"])

    def test_deterministic_cardinality_exact_twenty_candidates(self):
        candidates = [valid_chokepoint_candidate(f"EX{i:02d}") for i in range(20)]
        result = engine.rank_bottleneck_candidates(candidates, self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["admitted_count"], 20)
        self.assertEqual(result["ranked_count"], 20)
        self.assertEqual([r["rank"] for r in result["ranked_candidates"]], list(range(1, 21)))

    def test_deterministic_cardinality_greater_than_twenty_candidates_truncation(self):
        candidates = [valid_chokepoint_candidate(f"GT{i:02d}") for i in range(25)]
        result = engine.rank_bottleneck_candidates(candidates, self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["admitted_count"], 25)
        self.assertEqual(result["ranked_count"], 20)
        self.assertEqual(len(result["admitted_overflow"]), 5)
        self.assertEqual([r["rank"] for r in result["ranked_candidates"]], list(range(1, 21)))

    def test_old_tickers_and_unknown_identities_evaluated_identically_no_whitelist_blacklist(self):
        old_tickers = ["ACGL", "AFRM", "BBY", "CDE", "FIS", "HIG", "HST"]
        candidates = [
            {"ticker": t, "name": f"Old candidate {t}", "bottleneck_role": "BENEFICIARY"}
            for t in old_tickers
        ]
        result = engine.rank_bottleneck_candidates(candidates, self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        # Every one of the old tickers should fail admission due to lack of structural bottleneck evidence
        self.assertEqual(result["ranked_count"], 0)
        self.assertEqual(result["unranked_count"], len(old_tickers))
        for row in result["low_confidence_watchlist"]:
            self.assertEqual(row["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_sector_neutrality_no_favoritism(self):
        # AI candidate and Non-AI (e.g. specialized power / metallurgy) with identical evidenced economics
        ai_cand = valid_chokepoint_candidate("AI01", industry="AI Semiconductor Optics")
        metal_cand = valid_chokepoint_candidate("MET01", industry="Heavy Metallurgy Refractory")
        result = engine.rank_bottleneck_candidates([ai_cand, metal_cand], self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        score_ai = result["ranked_candidates"][0]["system_bottleneck_explosion_score"]
        score_metal = result["ranked_candidates"][1]["system_bottleneck_explosion_score"]
        self.assertEqual(score_ai, score_metal)

    def test_foreign_listing_not_rejected_for_missing_sec(self):
        foreign_cand = valid_chokepoint_candidate(
            "SOITEC",
            exchange="Euronext Paris",
            country="FR",
            name="Soitec SA",
        )
        result = engine.rank_bottleneck_candidates([foreign_cand], self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(result["ranked_count"], 1)
        self.assertEqual(result["ranked_candidates"][0]["country"], "FR")
        self.assertEqual(result["ranked_candidates"][0]["exchange"], "Euronext Paris")

    def test_historical_return_perturbation_invariance(self):
        c1 = valid_chokepoint_candidate("TEST01", long_term_return_pct=500.0, short_term_return_pct=150.0)
        c2 = valid_chokepoint_candidate("TEST01", long_term_return_pct=-85.0, short_term_return_pct=-40.0)
        eval1 = engine.evaluate_candidate(c1, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        eval2 = engine.evaluate_candidate(c2, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(eval1["system_bottleneck_explosion_score"], eval2["system_bottleneck_explosion_score"])
        self.assertEqual(eval1["raw_factor_score"], eval2["raw_factor_score"])
        self.assertEqual(eval1["admission_status"], eval2["admission_status"])
        self.assertEqual(eval1["historical_returns_context"]["influence_on_score"], 0.0)

    def test_ticker_overlap_and_author_social_invariance(self):
        c1 = valid_chokepoint_candidate("BASE01")
        c2 = valid_chokepoint_candidate(
            "BASE01",
            social_overlap_bonus=100,
            serenity_tweet_mention=True,
            aschenbrenner_portfolio_overlap=True,
        )
        eval1 = engine.evaluate_candidate(c1, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        eval2 = engine.evaluate_candidate(c2, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(eval1["system_bottleneck_explosion_score"], eval2["system_bottleneck_explosion_score"])

    def test_sole_source_label_only_without_scarcity_rejected(self):
        c = valid_chokepoint_candidate(
            "LABEL_ONLY",
            scarcity_evidence={
                "corroborated_scarcity": False,
                "effective_suppliers_count": 8,
                "switching_time_months": 2,
            },
        )
        eval_res = engine.evaluate_candidate(c, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(eval_res["bottleneck_role"], "UNPROVEN")
        self.assertEqual(eval_res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_customer_relationship_only_rejected(self):
        c = valid_chokepoint_candidate(
            "PARTNER_ONLY",
            dependency_evidence={
                "customer_relationship_only": True,
                "irreplaceable_architecture_layer": False,
            },
        )
        eval_res = engine.evaluate_candidate(c, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(eval_res["dependency_criticality"]["score"], 0.0)

    def test_high_gross_margin_only_rejected(self):
        c = valid_chokepoint_candidate(
            "MARGIN_ONLY",
            pricing_evidence={
                "high_gross_margin_only": True,
                "contractual_or_pricing_power_mechanism": False,
            },
        )
        eval_res = engine.evaluate_candidate(c, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(eval_res["pricing_power"]["score"], 0.0)

    def test_expansion_only_rejected(self):
        c = valid_chokepoint_candidate(
            "EXPANSION_ONLY",
            supply_constraint_evidence={
                "expansion_announcement_only": True,
                "binding_scarcity_proven": False,
            },
        )
        eval_res = engine.evaluate_candidate(c, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(eval_res["supply_constraint"]["score"], 0.0)

    def test_financing_destroyed_rejected_from_ranking(self):
        c = valid_chokepoint_candidate("DILUTED", financing_risk="DESTROYED")
        eval_res = engine.evaluate_candidate(c, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(eval_res["admission_status"], "DISQUALIFIED_FINANCING_DESTROYED")
        self.assertEqual(eval_res["lifecycle"], "BROKEN")
        ranked = engine.rank_bottleneck_candidates([c], self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(ranked["ranked_count"], 0)
        self.assertEqual(ranked["unranked_count"], 1)

    def test_thesis_broken_rejected_from_ranking(self):
        c = valid_chokepoint_candidate("BROKEN_CO", lifecycle="BROKEN")
        eval_res = engine.evaluate_candidate(c, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(eval_res["admission_status"], "DISQUALIFIED_THESIS_BROKEN")
        ranked = engine.rank_bottleneck_candidates([c], self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(ranked["ranked_count"], 0)

    def test_shortage_relieved_decreases_score(self):
        c_tight = valid_chokepoint_candidate("TIGHT", scarcity_evidence={"corroborated_scarcity": True, "switching_time_months": 24})
        c_relieved = valid_chokepoint_candidate("RELIEVED", scarcity_evidence={"shortage_relieved": True, "switching_time_months": 24})
        e_tight = engine.evaluate_candidate(c_tight, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        e_relieved = engine.evaluate_candidate(c_relieved, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertGreater(e_tight["system_bottleneck_explosion_score"], e_relieved["system_bottleneck_explosion_score"])

    def test_missing_risk_disclosure_not_safer_than_known_risk(self):
        c_disclosed = valid_chokepoint_candidate("DISCLOSED", risks_disclosed=True, risk_factors=["Risk A"])
        c_missing = valid_chokepoint_candidate("MISSING", risks_disclosed=False, risk_factors=[])
        e_disclosed = engine.evaluate_candidate(c_disclosed, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        e_missing = engine.evaluate_candidate(c_missing, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertIn("omitted_risk_disclosure_penalty", e_missing["risk_flags"])
        self.assertGreater(e_disclosed["system_bottleneck_explosion_score"], e_missing["system_bottleneck_explosion_score"])

    def test_raw_json_hand_filled_status_cannot_bypass_reconciliation(self):
        forged = {
            "ticker": "FORGED",
            "name": "Forged Corp",
            "bottleneck_role": "SINGLE_SOURCE",
            "status": "SUPPORTED",
            "health": "HEALTHY",
            "material_claims": [{"claim_id": "c1", "claim_type": "issuer_financial_statement", "subject": "FORGED", "metric": "rev", "period": "2026Q2", "unit": "M", "currency": "USD", "basis": "GAAP", "scope": "consolidated"}],
            "source_observations": [{"source_id": "fake_source"}],
        }
        eval_res = engine.evaluate_candidate(forged, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertFalse(eval_res["claims_audit"]["all_material_claims_supported"])
        self.assertEqual(eval_res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_claim_conflict_triggers_penalty_and_disqualification(self):
        conflicted = valid_chokepoint_candidate("CONFLICT_CO")
        conflicted["material_claims"] = [
            {"claim_id": "rev", "claim_type": "issuer_financial_statement", "subject": "CONFLICT_CO", "metric": "rev", "period": "2026Q2", "unit": "million", "currency": "USD", "basis": "GAAP", "scope": "consolidated"}
        ]
        conflicted["source_observations"] = [
            {"source_id": "issuer", "canonical_url": "https://issuer.example/", "published_at": "2026-09-12T00:00:00Z", "retrieved_at": "2026-09-13T00:00:00Z", "content_sha256": "a" * 64, "claim_type": "issuer_financial_statement", "evidence_role": "financial_statements", "source_health": "HEALTHY", "parser_id": "issuer", "parser_version": "1", "jurisdiction": "US", "language": "en", "payload": {"claim_ids": ["rev"], "subject": "CONFLICT_CO", "metric": "rev", "period": "2026Q2", "unit": "million", "currency": "USD", "value": 100, "basis": "GAAP", "scope": "consolidated", "as_of": "2026-09-12T00:00:00Z", "passage": "pass", "origin_group": "group1"}},
            {"source_id": "issuer", "canonical_url": "https://issuer.example/revised", "published_at": "2026-09-12T00:00:00Z", "retrieved_at": "2026-09-13T00:00:00Z", "content_sha256": "b" * 64, "claim_type": "issuer_financial_statement", "evidence_role": "financial_statements", "source_health": "HEALTHY", "parser_id": "issuer", "parser_version": "1", "jurisdiction": "US", "language": "en", "payload": {"claim_ids": ["rev"], "subject": "CONFLICT_CO", "metric": "rev", "period": "2026Q2", "unit": "million", "currency": "USD", "value": 200, "basis": "GAAP", "scope": "consolidated", "as_of": "2026-09-12T00:00:00Z", "passage": "pass", "origin_group": "group2"}},
        ]
        eval_res = engine.evaluate_candidate(conflicted, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertGreater(eval_res["claims_audit"]["conflicted_claim_count"], 0)
        self.assertIn("unresolved_material_claim_conflicts", eval_res["risk_flags"])
        self.assertNotEqual(eval_res["admission_status"], "ADMITTED")

    def test_output_field_schema_completeness(self):
        c = valid_chokepoint_candidate("SCHEMA_TEST")
        eval_res = engine.evaluate_candidate(c, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        required_fields = [
            "ticker", "company_name", "exchange", "country", "bottleneck_role",
            "dependency_criticality", "effective_vs_qualified_substitutes",
            "substitution_time", "demand_acceleration", "supply_constraint",
            "pricing_power", "company_capture", "backlog_orders",
            "catalysts_6_12_24m", "operating_leverage", "thesis_killers",
            "lifecycle", "evidence_confidence", "system_bottleneck_explosion_score",
            "raw_factor_score", "downside_penalty", "rank_rationale",
            "historical_returns_context", "claims_audit"
        ]
        for field in required_fields:
            self.assertIn(field, eval_res, f"Missing required output field: {field}")

        confidence_axes = [
            "factual_evidence_confidence", "dependency_confidence",
            "company_capture_confidence", "timing_confidence", "identity_confidence"
        ]
        for axis in confidence_axes:
            self.assertIn(axis, eval_res["evidence_confidence"])

    def test_input_immutability(self):
        original = valid_chokepoint_candidate("IMMUTABLE")
        snapshot = copy.deepcopy(original)
        _ = engine.evaluate_candidate(original, self.policy, now=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(original, snapshot)
        _ = engine.rank_bottleneck_candidates([original], self.policy, top_count=20, as_of=NOW, registry=self.registry, health_states=self.health_states)
        self.assertEqual(original, snapshot)

    def test_cli_caller_subprocess_execution(self):
        """CLI without typed acquisition must fail closed: zero admitted, all unranked."""
        candidates = [valid_chokepoint_candidate(f"CLI{i:02d}") for i in range(5)]
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
            self.assertTrue(out_file.exists())
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["ranked_count"], 0)
            self.assertEqual(data["admitted_count"], 0)
            self.assertEqual(data["unranked_count"], 5)
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["publication_status"], "NOT_PUBLICATION_QUALIFIED")
            self.assertEqual(data["live_qualification"], "DEFERRED")


if __name__ == "__main__":
    unittest.main()
