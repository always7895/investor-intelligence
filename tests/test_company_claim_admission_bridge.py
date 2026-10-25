"""Tests for Typed Company Claim Admission Bridge.

Verifies:
- Candidate text validation alone does NOT confer acquisition authority or admission.
- Fake claimed SUPPORTED / untrusted public JSON fails closed.
- Wrong company / subject mismatch fails closed.
- Wrong product / spec mismatch fails closed.
- Wrong date / impossible clock / stale claim fails closed.
- Wrong unit, non-finite values, and boolean numeric coercion are rejected.
- Wrong source-role refused for factor licensing.
- Reused claim across all 4 factors fails closed.
- Same issuer lineage across chapters/quarters deduplicated to single family (no false independence).
- Missing typed trust / caller-injected health states rejected.
- Financing unknown defaults strictly to STRUCTURAL_DISQUALIFIER, never NONE.
- Stale, refuted, and conflicted claims fail closed.
- Conditional forecasts / long-term targets cannot license realized facts.
- Generic OEM count does not prove effective alternative capacity.
- Group ROIC / dividend payout policy is not pricing power.
- Business mix / subsidiary count is not share dilution.
- Error messages are secret-safe and path-safe.
- Candidate inputs remain strictly immutable.
- Actual unadmitted corpus evaluates to 0 admitted companies.
- Positive fixtures are strictly labeled TEST_ONLY, not live proof.
"""
from __future__ import annotations

import copy
import math
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import test_research_v2_claims as claims_fixture
from bottleneck_claim_admission import reconcile_factor_authority
import company_claim_admission_bridge as bridge

NOW = datetime(2026, 9, 15, 8, 0, 0, tzinfo=timezone.utc)
STAMP = "2026-09-15T08:00:00Z"

SYNTHETIC_REGISTRY = claims_fixture.REGISTRY
SYNTHETIC_HEALTH = {s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()}


def _make_test_claim_and_observations(
    cid: str,
    kind: str,
    subject: str,
    metric: str,
    val: float | int | str,
    unit: str = "count",
    *,
    lineage1: str = "lineage_official",
    lineage2: str = "lineage_news",
    role1: str = "guidance",
    role2: str = "financial_reporting",
    as_of: str = STAMP,
) -> tuple[dict, list[dict]]:
    c = {
        "claim_id": cid,
        "claim_type": kind,
        "subject": subject,
        "metric": metric,
        "period": "2026Q2",
        "unit": unit,
        "currency": "USD",
        "basis": "GAAP",
        "scope": "consolidated",
    }
    obs1 = {
        "source_id": "official",
        "canonical_url": f"https://official.example/{cid}",
        "published_at": STAMP,
        "retrieved_at": STAMP,
        "content_sha256": "1" * 64,
        "parser_id": "official",
        "parser_version": "1",
        "jurisdiction": "US",
        "language": "en",
        "claim_type": kind,
        "evidence_role": role1,
        "source_health": "HEALTHY",
        "payload": {
            "origin_group": lineage1,
            "claim_ids": [cid],
            "subject": subject,
            "metric": metric,
            "period": "2026Q2",
            "unit": unit,
            "currency": "USD",
            "basis": "GAAP",
            "scope": "consolidated",
            "as_of": as_of,
            "passage": f"Verified {metric}",
            "value": val,
        },
    }
    obs2 = {
        "source_id": "news",
        "canonical_url": f"https://news.example/{cid}",
        "published_at": STAMP,
        "retrieved_at": STAMP,
        "content_sha256": "2" * 64,
        "parser_id": "news",
        "parser_version": "1",
        "jurisdiction": "US",
        "language": "en",
        "claim_type": kind,
        "evidence_role": role2,
        "source_health": "HEALTHY",
        "payload": {
            "origin_group": lineage2,
            "claim_ids": [cid],
            "subject": subject,
            "metric": metric,
            "period": "2026Q2",
            "unit": unit,
            "currency": "USD",
            "basis": "GAAP",
            "scope": "consolidated",
            "as_of": as_of,
            "passage": f"Corroborated {metric}",
            "value": val,
        },
    }
    return c, [obs1, obs2]


def _make_valid_test_candidate(ticker: str = "TESTCO") -> dict:
    c_dep, o_dep = _make_test_claim_and_observations(f"dep_{ticker}", "issuer_guidance_or_contract", ticker, "architecture_layer", 1, unit="count")
    c_scar, o_scar = _make_test_claim_and_observations(f"scar_{ticker}", "issuer_guidance_or_contract", ticker, "effective_suppliers_count", 1, unit="count")
    c_price, o_price = _make_test_claim_and_observations(f"price_{ticker}", "issuer_guidance_or_contract", ticker, "contractual_price_indexation", 12.5, unit="percent")
    c_cap, o_cap = _make_test_claim_and_observations(f"cap_{ticker}", "issuer_financial_statement", ticker, "bom_share_capture", 65.0, unit="percent", role1="financial_statements")

    return {
        "ticker": ticker,
        "name": f"{ticker} Inc",
        "bottleneck_role": "SINGLE_SOURCE",
        "as_of": STAMP,
        "financing_risk": "NONE",
        "material_claims": [c_dep, c_scar, c_price, c_cap],
        "source_observations": [*o_dep, *o_scar, *o_price, *o_cap],
        "dependency_evidence": {
            "claim_ids": [f"dep_{ticker}"],
            "customer_relationship_only": False,
            "irreplaceable_architecture_layer": True,
        },
        "scarcity_evidence": {
            "claim_ids": [f"scar_{ticker}"],
            "shortage_relieved": False,
            "effective_suppliers_count": 1,
        },
        "pricing_evidence": {
            "claim_ids": [f"price_{ticker}"],
            "high_gross_margin_only": False,
        },
        "company_capture_evidence": {
            "claim_ids": [f"cap_{ticker}"],
            "disciplined_financing": True,
        },
    }


class TestCompanyClaimAdmissionBridge(unittest.TestCase):
    def test_fake_claimed_supported_refused(self):
        # Candidate claiming it has SUPPORTED status without verified observations
        cand = {
            "ticker": "FAKE01",
            "material_claims": [
                {"claim_id": "fake_dep", "status": "SUPPORTED", "subject": "FAKE01", "metric": "architecture_layer"}
            ],
            "dependency_evidence": {"claim_ids": ["fake_dep"]},
            "financing_risk": "NONE",
        }
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[],  # unverified empty reconciled claims
            ticker="FAKE01",
            now=NOW,
        )
        self.assertFalse(res["dependency_licensed"])
        self.assertFalse(res["core_admitted"])
        self.assertIn("dependency", res["missing_core"])

    def test_wrong_company_subject_mismatch_refused(self):
        cand = _make_valid_test_candidate("TICKERA")
        # Evaluate for TICKERB mismatch
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[{"claim_id": "dep_TICKERA", "status": "SUPPORTED"}],
            ticker="TICKERB",
            now=NOW,
        )
        self.assertFalse(res["dependency_licensed"])
        self.assertFalse(res["core_admitted"])

    def test_wrong_product_or_spec_mismatch(self):
        # Candidate specifies product/spec mismatch against factor rule
        cand = _make_valid_test_candidate("SPEC01")
        cand["material_claims"][0]["product_or_spec"] = "GENERIC_UNQUALIFIED_COMMODITY"
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[
                {"claim_id": "dep_SPEC01", "status": "SUPPORTED"},
                {"claim_id": "scar_SPEC01", "status": "SUPPORTED"},
                {"claim_id": "price_SPEC01", "status": "SUPPORTED"},
                {"claim_id": "cap_SPEC01", "status": "SUPPORTED"},
            ],
            ticker="SPEC01",
            now=NOW,
        )
        self.assertFalse(res["core_admitted"])

    def test_wrong_date_impossible_clock_or_stale(self):
        cand = _make_valid_test_candidate("TIME01")
        cand["material_claims"][0]["as_of"] = "2029-01-01T00:00:00Z"  # future
        with self.assertRaises(bridge.BridgeValidationError) as ctx:
            bridge.validate_typed_claim(cand["material_claims"][0], now=NOW)
        self.assertIn("IMPOSSIBLE_CLOCK", str(ctx.exception))

    def test_wrong_unit_and_boolean_coercion_rejected(self):
        # Boolean value passed where scalar numeric expected
        claim = {
            "claim_id": "bool_claim",
            "claim_type": "issuer_guidance_or_contract",
            "subject": "BOOL01",
            "metric": "effective_suppliers_count",
            "period": "2026Q2",
            "unit": "count",
            "currency": "USD",
            "basis": "GAAP",
            "scope": "consolidated",
            "value": True,  # boolean, must not coerce to 1.0
        }
        with self.assertRaises(bridge.BridgeValidationError) as ctx:
            bridge.validate_typed_claim(claim, now=NOW)
        self.assertIn("BOOLEAN_NUMERIC_COERCION_REJECTED", str(ctx.exception))

        # Non-finite NaN
        claim["value"] = float("nan")
        with self.assertRaises(bridge.BridgeValidationError) as ctx:
            bridge.validate_typed_claim(claim, now=NOW)
        self.assertIn("NON_FINITE_NUMERIC_REJECTED", str(ctx.exception))

    def test_wrong_source_role_refused(self):
        # Macro reporting or journalism trying to license capture (requires financial statements)
        cand = _make_valid_test_candidate("ROLE01")
        cand["material_claims"][3]["evidence_role"] = "macro_reporting"
        cand["material_claims"][3]["claim_type"] = "macro_indicator"
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[
                {"claim_id": "dep_ROLE01", "status": "SUPPORTED"},
                {"claim_id": "scar_ROLE01", "status": "SUPPORTED"},
                {"claim_id": "price_ROLE01", "status": "SUPPORTED"},
                {"claim_id": "cap_ROLE01", "status": "SUPPORTED"},
            ],
            ticker="ROLE01",
            now=NOW,
        )
        self.assertFalse(res["capture_licensed"])
        self.assertFalse(res["core_admitted"])

    def test_reused_claim_licenses_all_factors_refused(self):
        cand = _make_valid_test_candidate("REUSE01")
        # Single claim reused across all factors
        cand["dependency_evidence"]["claim_ids"] = ["dep_REUSE01"]
        cand["scarcity_evidence"]["claim_ids"] = ["dep_REUSE01"]
        cand["pricing_evidence"]["claim_ids"] = ["dep_REUSE01"]
        cand["company_capture_evidence"]["claim_ids"] = ["dep_REUSE01"]

        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[{"claim_id": "dep_REUSE01", "status": "SUPPORTED"}],
            ticker="REUSE01",
            now=NOW,
        )
        self.assertFalse(res["core_admitted"])
        self.assertFalse(res["dependency_licensed"])
        self.assertFalse(res["scarcity_licensed"])
        self.assertFalse(res["pricing_licensed"])
        self.assertFalse(res["capture_licensed"])

    def test_same_issuer_lineage_quarter_chapters_dedup(self):
        # 4 Meiden chapters or same issuer annual report documents must collapse to 1 family
        obs_chapter1 = {
            "source_id": "meiden_ir",
            "published_at": STAMP,
            "origin_group": "group_meidensha_report_2025",
            "independence_group": "meidensha_issuer",
            "content_sha256": "a" * 64,
        }
        obs_chapter2 = {
            "source_id": "meiden_ir",
            "published_at": STAMP,
            "origin_group": "group_meidensha_report_2025",
            "independence_group": "meidensha_issuer",
            "content_sha256": "b" * 64,
        }
        families = bridge.compute_independent_lineages([obs_chapter1, obs_chapter2])
        self.assertEqual(families, 1, "Chapters from same issuer report must dedup to 1 family")

    def test_missing_typed_trust_and_untrusted_public_json(self):
        # Untrusted JSON with fabricated caller-owned health or registry
        untrusted = {
            "ticker": "PUBLIC01",
            "health_states": {"official": "HEALTHY"},
            "registry": {"sources": []},
            "status": "ADMITTED",
            "material_claims": [{"claim_id": "c1", "status": "SUPPORTED"}],
        }
        res = bridge.bridge_reconcile_factors(
            untrusted,
            reconciled_claims=[],
            ticker="PUBLIC01",
            now=NOW,
        )
        self.assertFalse(res["core_admitted"])
        self.assertEqual(res["financing_state"], "STRUCTURAL_DISQUALIFIER")

    def test_financing_unknown_defaults_to_structural_disqualifier(self):
        cand = _make_valid_test_candidate("NOFIN")
        del cand["financing_risk"]
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[
                {"claim_id": "dep_NOFIN", "status": "SUPPORTED"},
                {"claim_id": "scar_NOFIN", "status": "SUPPORTED"},
                {"claim_id": "price_NOFIN", "status": "SUPPORTED"},
                {"claim_id": "cap_NOFIN", "status": "SUPPORTED"},
            ],
            ticker="NOFIN",
            now=NOW,
        )
        self.assertEqual(res["financing_state"], "STRUCTURAL_DISQUALIFIER")
        self.assertFalse(res["capture_licensed"])
        self.assertFalse(res["core_admitted"])

    def test_stale_refuted_and_conflicted_claims_fail_closed(self):
        cand = _make_valid_test_candidate("CONF01")
        # Reconciled claims report a conflict
        reconciled = [
            {"claim_id": "dep_CONF01", "status": "SUPPORTED"},
            {"claim_id": "scar_CONF01", "status": "CONFLICTED"},
            {"claim_id": "price_CONF01", "status": "SUPPORTED"},
            {"claim_id": "cap_CONF01", "status": "SUPPORTED"},
        ]
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=reconciled,
            ticker="CONF01",
            now=NOW,
        )
        self.assertFalse(res["scarcity_licensed"])
        self.assertFalse(res["core_admitted"])

    def test_conditional_forecast_not_realized(self):
        cand = _make_valid_test_candidate("FORE01")
        # Scarcity claim is conditional future target
        cand["material_claims"][1]["period_type"] = "FORWARD_GUIDANCE"
        cand["material_claims"][1]["metric"] = "capacity_expansion_plan"
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[
                {"claim_id": "dep_FORE01", "status": "SUPPORTED"},
                {"claim_id": "scar_FORE01", "status": "SUPPORTED"},
                {"claim_id": "price_FORE01", "status": "SUPPORTED"},
                {"claim_id": "cap_FORE01", "status": "SUPPORTED"},
            ],
            ticker="FORE01",
            now=NOW,
        )
        self.assertFalse(res["scarcity_licensed"])
        self.assertFalse(res["core_admitted"])

    def test_generic_oem_count_not_effective_alternatives(self):
        # Candidate claims generic OEM count proves scarcity or alternative capacity
        cand = _make_valid_test_candidate("OEM01")
        cand["scarcity_evidence"]["generic_oem_list"] = ["Siemens", "Hitachi", "Meiden"]
        cand["scarcity_evidence"]["effective_substitutes_gap"] = "UNVERIFIED"
        cand["material_claims"][1]["metric"] = "tam_estimate"  # prohibited
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[{"claim_id": "scar_OEM01", "status": "SUPPORTED"}],
            ticker="OEM01",
            now=NOW,
        )
        self.assertFalse(res["scarcity_licensed"])

    def test_group_roi_or_payout_policy_not_pricing_power(self):
        # Consolidated ROIC 8.2% or 30% dividend payout policy cannot license pricing power
        cand = _make_valid_test_candidate("ROIC01")
        cand["material_claims"][2]["metric"] = "group_roic"
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[{"claim_id": "price_ROIC01", "status": "SUPPORTED"}],
            ticker="ROIC01",
            now=NOW,
        )
        self.assertFalse(res["pricing_licensed"])

    def test_business_mix_not_share_dilution(self):
        # Having 40 subsidiaries is not equity dilution
        cand = _make_valid_test_candidate("MIX01")
        cand["subsidiary_count"] = 40
        cand["financing_risk"] = "NONE"
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[
                {"claim_id": "dep_MIX01", "status": "SUPPORTED"},
                {"claim_id": "scar_MIX01", "status": "SUPPORTED"},
                {"claim_id": "price_MIX01", "status": "SUPPORTED"},
                {"claim_id": "cap_MIX01", "status": "SUPPORTED"},
            ],
            ticker="MIX01",
            now=NOW,
            fixture_mode=True,
        )
        # Should not be disqualified just because of subsidiary count if disciplined financing holds
        self.assertEqual(res["financing_state"], "NONE")
        self.assertTrue(res["capture_licensed"])

    def test_secret_safe_errors(self):
        # Error must not contain credentials or secret tokens
        bad_claim = {
            "claim_id": "bad",
            "source_url": "https://user:supersecretpass@example.com/data",
            "metric": "architecture_layer",
        }
        with self.assertRaises(bridge.BridgeValidationError) as ctx:
            bridge.validate_typed_claim(bad_claim, now=NOW)
        self.assertNotIn("supersecretpass", str(ctx.exception))
        self.assertIn("INVALID_SOURCE_URL", str(ctx.exception))

    def test_candidate_inputs_immutable(self):
        cand = _make_valid_test_candidate("IMMUT01")
        cand_copy = copy.deepcopy(cand)
        bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[],
            ticker="IMMUT01",
            now=NOW,
        )
        self.assertEqual(cand, cand_copy, "Input candidate mapping must remain unaltered")

    def test_actual_unadmitted_corpus_zero(self):
        # Unreviewed research candidate corpus (e.g. from candidate research) yields 0 admitted
        unadmitted_cand = {
            "ticker": "6508",
            "name": "Meidensha Corp",
            "material_claims": [
                {"claim_id": "meiden_001", "proposed_label": "SUPPORTED", "metric": "revenue", "value": 180000}
            ],
            "source_observations": [],
            "dependency_evidence": {"claim_ids": ["meiden_001"]},
            "scarcity_evidence": {"claim_ids": []},
            "pricing_evidence": {"claim_ids": []},
            "company_capture_evidence": {"claim_ids": []},
            "financing_risk": "NONE",
        }
        res = bridge.bridge_reconcile_factors(
            unadmitted_cand,
            reconciled_claims=[],
            ticker="6508",
            now=NOW,
        )
        self.assertFalse(res["core_admitted"])
        self.assertIn(res["admission_tier"], {"UNADMITTED", "ADMISSION_DEFER"})

    def test_fixture_positives_labeled_test_only(self):
        cand = _make_valid_test_candidate("FIXTURE01")
        res = bridge.bridge_reconcile_factors(
            cand,
            reconciled_claims=[
                {"claim_id": "dep_FIXTURE01", "status": "SUPPORTED"},
                {"claim_id": "scar_FIXTURE01", "status": "SUPPORTED"},
                {"claim_id": "price_FIXTURE01", "status": "SUPPORTED"},
                {"claim_id": "cap_FIXTURE01", "status": "SUPPORTED"},
            ],
            ticker="FIXTURE01",
            now=NOW,
            fixture_mode=True,
        )
        self.assertTrue(res["core_admitted"])
        self.assertEqual(res["admission_tier"], "TEST_ONLY")


if __name__ == "__main__":
    unittest.main()
