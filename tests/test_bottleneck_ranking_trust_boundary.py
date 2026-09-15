"""Trust boundary and fail-closed negative regression tests for System Bottleneck Explosion Ranking Engine v1.

Verifies Review 2 security, provenance, and trust boundary contracts:
- Product code contains NO test fixture imports, NO fixture globals, NO auto-fallback.
- Candidate JSON cannot forge registry, health states, clock, or admission flags.
- Observations missing parser metadata, runtime health, or valid clock fail closed.
- Real registry unknown source IDs fail closed.
- Macro capability (ECB) does NOT qualify company claims.
- Actual CLI / subprocess execution on untrusted candidates always fails closed (0 admitted).
- Deep input immutability, sector neutrality, and perturbation invariance are strictly preserved.
"""
from __future__ import annotations

import copy
import inspect
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
from source_registry import load_registry

NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
STAMP = "2026-09-12T12:00:00Z"


def _make_claims_and_obs(ticker: str) -> tuple[list[dict], list[dict]]:
    claims = [
        {"claim_id": "rev_claim", "claim_type": "issuer_financial_statement", "subject": ticker, "metric": "revenue", "period": "2026Q2", "unit": "million", "currency": "USD", "basis": "GAAP", "scope": "consolidated"},
        {"claim_id": "dep_claim", "claim_type": "issuer_guidance_or_contract", "subject": ticker, "metric": "architecture_layer", "period": "2026Q2", "unit": "boolean", "currency": "USD", "basis": "GAAP", "scope": "consolidated"},
        {"claim_id": "scar_claim", "claim_type": "issuer_guidance_or_contract", "subject": ticker, "metric": "effective_suppliers_count", "period": "2026Q2", "unit": "count", "currency": "USD", "basis": "GAAP", "scope": "consolidated"},
        {"claim_id": "price_claim", "claim_type": "issuer_guidance_or_contract", "subject": ticker, "metric": "contractual_price_indexation", "period": "2026Q2", "unit": "percent", "currency": "USD", "basis": "GAAP", "scope": "consolidated"},
        {"claim_id": "cap_claim", "claim_type": "issuer_financial_statement", "subject": ticker, "metric": "bom_share_capture", "period": "2026Q2", "unit": "percent", "currency": "USD", "basis": "GAAP", "scope": "consolidated"},
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
                "as_of": STAMP, "passage": "Official statement", "value": 150,
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
                "as_of": STAMP, "passage": "Reported fact", "value": 150,
            }
        })
    return claims, obs


def sample_chokepoint_candidate(ticker: str = "TRUST01", **kwargs) -> dict:
    """Produces a structural candidate payload with explicit material claims and observations."""
    claims, obs = _make_claims_and_obs(ticker)
    for key, cid in [
        ("dependency_evidence", "dep_claim"),
        ("scarcity_evidence", "scar_claim"),
        ("pricing_evidence", "price_claim"),
        ("company_capture_evidence", "cap_claim"),
    ]:
        if key in kwargs and isinstance(kwargs[key], dict) and "claim_ids" not in kwargs[key]:
            kwargs[key]["claim_ids"] = [cid]
    base = {
        "ticker": ticker,
        "name": f"Trust Corp {ticker}",
        "exchange": "NASDAQ",
        "country": "US",
        "as_of": STAMP,
        "bottleneck_role": "SINGLE_SOURCE",
        "scarcity_evidence": {
            "claim_ids": ["scar_claim"],
            "corroborated_scarcity": True,
            "effective_suppliers_count": 1,
            "switching_time_months": 24,
            "details": "Sole qualified supplier of extreme-precision optical substrates.",
        },
        "dependency_evidence": {
            "claim_ids": ["dep_claim"],
            "irreplaceable_architecture_layer": True,
            "layer": "Optical interconnect substrate",
            "assessment": "Next-gen transceivers fail without this substrate.",
        },
        "demand_evidence": {
            "structural_acceleration": True,
            "multi_year_committed": True,
            "horizon_months": 24,
            "assessment": "Capex ramps buildout.",
        },
        "supply_constraint_evidence": {
            "lead_time_weeks": 60,
            "binding_scarcity_proven": True,
            "binding_constraint": "Specialized reactors.",
            "assessment": "Lead time exceeds 14 months.",
        },
        "pricing_evidence": {
            "claim_ids": ["price_claim"],
            "contractual_price_increases_documented": True,
            "mechanism": "Long-term supply agreements with indexation.",
            "assessment": "Pricing increased 15% YoY.",
        },
        "company_capture_evidence": {
            "claim_ids": ["cap_claim"],
            "dominant_bom_share": True,
            "disciplined_financing": True,
            "assessment": "Captures 70% of substrate profit pool.",
        },
        "operating_leverage_evidence": {
            "incremental_margin_gt_40pct": True,
            "assessment": "Incremental margins exceed 50%.",
        },
        "backlog_orders_evidence": {
            "current_orders": "$1.2B firm backlog",
            "future_orders_estimate": "$2.5B committed",
            "order_support_type": "BINDING_CONTRACT",
        },
        "catalysts_6_12_24m": [
            {"timing": "6M", "catalyst": "Fab qualification", "status": "DATED"},
            {"timing": "12M", "catalyst": "Volume shipment", "status": "DATED"},
        ],
        "thesis_killers": [
            "Customer designs out optical substrate",
        ],
        "financing_risk": "NONE",
        "lifecycle": "COMMERCIAL_VALIDATION",
        "long_term_return_pct": 120.0,
        "short_term_return_pct": 25.0,
        "risks_disclosed": True,
        "risk_factors": ["Platform delay", "Yield variance"],
        "material_claims": claims,
        "source_observations": obs,
    }
    base.update(kwargs)
    return base


class BottleneckTrustBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.policy = engine.load_json(engine.POLICY_DEFAULT_PATH)

    def test_no_test_module_imports_or_fixture_globals_in_product_module(self):
        """Production module must NOT import test fixtures or define fixture globals."""
        src = Path(engine.__file__).read_text(encoding="utf-8")
        self.assertNotIn("test_research_v2_claims", src, "Production code must not import test_research_v2_claims")
        self.assertNotIn("FIXTURE_REGISTRY", src, "Production code must not define FIXTURE_REGISTRY")
        self.assertFalse(hasattr(engine, "FIXTURE_REGISTRY"), "FIXTURE_REGISTRY attribute must not exist in engine")
        self.assertNotIn("unittest.TestCase", src, "Production code must not inherit from TestCase")

    def test_cli_subprocess_untrusted_candidate_payload_always_fails_closed_zero_admitted(self):
        """CLI without typed process-local acquisition must NEVER admit untrusted candidate JSON."""
        candidates = [sample_chokepoint_candidate(f"CLI{i:02d}") for i in range(3)]
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
            self.assertEqual(data["admitted_count"], 0, "Untrusted CLI candidate input must yield 0 admitted")
            self.assertEqual(data["ranked_count"], 0, "Untrusted CLI candidate input must yield 0 ranked")
            self.assertEqual(data["unranked_count"], 3)
            self.assertEqual(len(data["ranked_candidates"]), 0)
            for row in data["low_confidence_watchlist"]:
                self.assertEqual(row["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")
                self.assertIsNone(row.get("rank"))
                self.assertIsNone(row.get("score_qualified"))

    def test_candidate_owned_registry_in_payload_ignored(self):
        """Candidate attempting to forge authority by supplying registry in JSON must be rejected."""
        cand = sample_chokepoint_candidate(
            "FORGE_REG",
            registry={"sources": [{"source_id": "forged_source"}]},
        )
        res = engine.evaluate_candidate(cand, self.policy, now=NOW)
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")
        self.assertIsNone(res.get("rank"))

    def test_candidate_owned_health_states_in_payload_ignored(self):
        """Candidate attempting to supply caller-owned health states in JSON must be rejected."""
        cand = sample_chokepoint_candidate(
            "FORGE_HEALTH",
            health_states={"issuer": "HEALTHY", "news": "HEALTHY"},
        )
        res = engine.evaluate_candidate(cand, self.policy, now=NOW)
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_missing_and_malformed_clock_fails_closed(self):
        """Missing or malformed clock must fail closed and never default silently to now."""
        # 1. Missing clock on candidate with no now passed
        cand_no_clock = sample_chokepoint_candidate("NO_CLOCK")
        del cand_no_clock["as_of"]
        res1 = engine.evaluate_candidate(cand_no_clock, self.policy, now=None)
        self.assertEqual(res1["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")
        self.assertIn("missing_or_invalid_clock", res1["risk_flags"])

        # 2. Malformed clock string
        cand_bad_clock = sample_chokepoint_candidate("BAD_CLOCK", as_of="not-a-valid-datetime")
        res2 = engine.evaluate_candidate(cand_bad_clock, self.policy, now=None)
        self.assertEqual(res2["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")
        self.assertIn("missing_or_invalid_clock", res2["risk_flags"])

        # 3. parse_clock on empty or invalid must raise error, not return datetime.now()
        with self.assertRaises(engine.BottleneckRankingError):
            engine.parse_clock("")
        with self.assertRaises(engine.BottleneckRankingError):
            engine.parse_clock("invalid-iso")
        with self.assertRaises(engine.BottleneckRankingError):
            engine.parse_clock(None)

    def test_missing_parser_metadata_fails_closed_no_silent_defaulting(self):
        """Observations missing parser metadata or jurisdiction/language must fail closed without silent defaulting."""
        cand = sample_chokepoint_candidate(
            "NO_PARSER",
            source_observations=[
                {
                    "source_id": "issuer",
                    "canonical_url": "https://issuer.example/report",
                    "published_at": STAMP,
                    "retrieved_at": "2026-09-13T11:00:00Z",
                    "content_sha256": "1" * 64,
                    # Missing parser_id, parser_version, jurisdiction, language
                    "claim_type": "issuer_financial_statement",
                    "evidence_role": "financial_statements",
                    "payload": {
                        "claim_ids": ["rev_claim"],
                        "subject": "NO_PARSER",
                        "metric": "revenue",
                        "period": "2026Q2",
                        "unit": "million",
                        "currency": "USD",
                        "value": 150,
                        "basis": "GAAP",
                        "scope": "consolidated",
                        "as_of": STAMP,
                        "passage": "Disclosed revenue",
                        "origin_group": "issuer",
                    },
                }
            ],
        )
        res = engine.evaluate_candidate(
            cand,
            self.policy,
            now=NOW,
            registry=claims_fixture.REGISTRY,
            health_states={s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()},
        )
        self.assertFalse(res["claims_audit"]["all_material_claims_supported"])
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_valid_macro_capability_does_not_qualify_company_candidate(self):
        """Macro observations or macro-only capability cannot qualify company bottleneck candidates."""
        cand = sample_chokepoint_candidate(
            "MACRO_CO",
            material_claims=[
                {
                    "claim_id": "macro_gdp",
                    "claim_type": "macro_indicator",
                    "subject": "MACRO_CO",
                    "metric": "gdp_growth",
                    "period": "2026Q2",
                    "unit": "percent",
                    "currency": "USD",
                    "basis": "GAAP",
                    "scope": "consolidated",
                }
            ],
            source_observations=[
                {
                    "source_id": "macro",
                    "canonical_url": "https://macro.example/report",
                    "published_at": STAMP,
                    "retrieved_at": "2026-09-13T11:00:00Z",
                    "content_sha256": "3" * 64,
                    "parser_id": "macro",
                    "parser_version": "1",
                    "jurisdiction": "US",
                    "language": "en",
                    "claim_type": "macro_indicator",
                    "evidence_role": "economic_data",
                    "source_health": "HEALTHY",
                    "payload": {
                        "claim_ids": ["macro_gdp"],
                        "subject": "MACRO_CO",
                        "metric": "gdp_growth",
                        "period": "2026Q2",
                        "unit": "percent",
                        "currency": "USD",
                        "value": 3.2,
                        "basis": "GAAP",
                        "scope": "consolidated",
                        "as_of": STAMP,
                        "passage": "Disclosed macro",
                        "origin_group": "macro",
                    },
                }
            ],
        )
        res = engine.evaluate_candidate(
            cand,
            self.policy,
            now=NOW,
            registry=claims_fixture.REGISTRY,
            health_states={s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()},
        )
        self.assertFalse(res["claims_audit"]["all_material_claims_supported"])
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_explicit_read_only_registry_metadata_alone_not_admission(self):
        """Passing explicit registry without runtime health or acquisition run does not grant admission."""
        cand = sample_chokepoint_candidate("READONLY_REG")
        res = engine.evaluate_candidate(
            cand,
            self.policy,
            now=NOW,
            registry=load_registry(),
            health_states=None,
            acquisition_run=None,
        )
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_unknown_source_id_rejected(self):
        """Observations with unknown source ID not registered in registry fail closed."""
        cand = sample_chokepoint_candidate("UNKNOWN_SRC")
        cand["source_observations"] = [
            {
                "source_id": "totally_bogus_unregistered_source",
                "canonical_url": "https://bogus.example/data",
                "published_at": STAMP,
                "retrieved_at": "2026-09-13T11:00:00Z",
                "content_sha256": "9" * 64,
                "parser_id": "bogus",
                "parser_version": "1",
                "jurisdiction": "US",
                "language": "en",
                "claim_type": "issuer_financial_statement",
                "evidence_role": "financial_statements",
                "source_health": "HEALTHY",
                "payload": {
                    "claim_ids": ["rev_claim"],
                    "subject": "UNKNOWN_SRC",
                    "metric": "revenue",
                    "period": "2026Q2",
                    "unit": "million",
                    "currency": "USD",
                    "value": 150,
                    "basis": "GAAP",
                    "scope": "consolidated",
                    "as_of": STAMP,
                    "passage": "Disclosed revenue",
                    "origin_group": "bogus",
                },
            }
        ]
        res = engine.evaluate_candidate(
            cand,
            self.policy,
            now=NOW,
            registry=claims_fixture.REGISTRY,
            health_states={s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()},
        )
        self.assertFalse(res["claims_audit"]["all_material_claims_supported"])
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_subject_mismatch_fails_admission(self):
        """Observation for a different ticker fails to support candidate claims."""
        cand = sample_chokepoint_candidate("REAL_TICKER")
        cand["source_observations"][0]["payload"]["subject"] = "DIFFERENT_TICKER"
        res = engine.evaluate_candidate(
            cand,
            self.policy,
            now=NOW,
            registry=claims_fixture.REGISTRY,
            health_states={s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()},
        )
        self.assertFalse(res["claims_audit"]["all_material_claims_supported"])
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")

    def test_forged_scores_and_status_in_candidate_payload_ignored(self):
        """Raw candidate JSON passing forged score or status cannot bypass engine evaluation."""
        forged = sample_chokepoint_candidate(
            "FORGED_SCORE",
            system_bottleneck_explosion_score=99.9,
            admission_status="ADMITTED",
            rank=1,
            score_qualified=True,
        )
        # Without valid claims, it must be UNRANKED
        forged["material_claims"] = []
        forged["source_observations"] = []
        res = engine.evaluate_candidate(forged, self.policy, now=NOW)
        self.assertEqual(res["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")
        self.assertIsNone(res.get("rank"))
        self.assertIsNone(res.get("score_qualified"))

    def test_deep_input_immutability_preserved(self):
        """Original candidate dictionary cannot be mutated during evaluation or ranking."""
        original = sample_chokepoint_candidate("IMMUT_TB")
        snapshot = copy.deepcopy(original)
        _ = engine.evaluate_candidate(original, self.policy, now=NOW)
        self.assertEqual(original, snapshot)
        _ = engine.rank_bottleneck_candidates([original], self.policy, top_count=20, as_of=NOW)
        self.assertEqual(original, snapshot)

    def test_sector_neutrality_and_return_invariance(self):
        """Scores remain sector-neutral and historical returns have zero score influence."""
        cand_ai = sample_chokepoint_candidate(
            "AI_SECTOR",
            industry="AI Infrastructure Optics",
            long_term_return_pct=300.0,
            short_term_return_pct=80.0,
        )
        cand_grid = sample_chokepoint_candidate(
            "GRID_SECTOR",
            industry="Grid High-Voltage Power Transformer",
            long_term_return_pct=-40.0,
            short_term_return_pct=-10.0,
        )
        res_ai = engine.evaluate_candidate(
            cand_ai,
            self.policy,
            now=NOW,
            registry=claims_fixture.REGISTRY,
            health_states={s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()},
        )
        res_grid = engine.evaluate_candidate(
            cand_grid,
            self.policy,
            now=NOW,
            registry=claims_fixture.REGISTRY,
            health_states={s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()},
        )
        self.assertEqual(res_ai["system_bottleneck_explosion_score"], res_grid["system_bottleneck_explosion_score"])
        self.assertEqual(res_ai["admission_status"], "ADMITTED")
        self.assertEqual(res_grid["admission_status"], "ADMITTED")
        self.assertEqual(res_ai["historical_returns_context"]["influence_on_score"], 0.0)
        self.assertEqual(res_grid["historical_returns_context"]["influence_on_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
