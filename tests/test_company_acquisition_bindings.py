"""Tests for Canonical Company Acquisition Factor Bindings.

Validates:
1. Compatibility for unrelated macro/ECB/source callers:
   Missing optional company bindings do NOT invalidate ordinary non-company observation runs.
2. Smallest actual factory-to-existing-admission-caller path:
   - Factory origin: AcquisitionRun created via acquire_runtime_sources (sentinel-protected).
   - Typed binding declares: claim_id, subject, entity, security, factor, metric,
     product_or_spec, region, unit, period, period_type, source role, source/event/retrieval clocks,
     underlying lineage IDs, canonical_observation_ids.
   - All bindings must reference existing canonical observations in the SAME owned run.
   - Cross-run ID, dangling/mutated observation IDs, cross-company subject mismatch,
     different period, unreviewed source capability fail closed.
   - Independent role/source count must derive from canonical observations/lineages,
     not caller-declared counts; single-family lineage collapses to 1 (< 2 fails factor licensing).
   - Negative / conflicted research claims and candidate disqualifiers must not yield eligible factors.
   - TEST_ONLY canonical factory-binding transport path proves consumer wiring to
     reconcile_factor_authority / bridge_reconcile_factors.
   - Missing company factor bindings record ARCHITECTURE_BLOCKER fail closed.
   - Zero live qualification from fixtures: tier is strictly TEST_ONLY_NONRUNTIME, never production.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import bottleneck_claim_admission as admission
import company_claim_admission_bridge as bridge
from adapters.base import ADAPTERS, make_batch
from fetch_public_source_observations import ENDPOINTS
from source_acquisition import (
    AcquisitionRun,
    _SENTINEL,
    acquire_runtime_sources,
)
from source_registry import Registry, SourceDefinition
import test_research_v2_claims as claims_fixture

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
STAMP = "2026-09-15T12:00:00+00:00"

def _make_source(name: str, authority: str, tier: str, roles: list[str]) -> SourceDefinition:
    return SourceDefinition(
        source_id=name,
        display_name=name,
        authority_class=authority,
        trust_tier=tier,
        evidence_roles=tuple(roles),
        jurisdictions=("US",),
        languages=("en",),
        canonical_urls=(f"https://{name}.example/report",),
        independence_group=name,
        admission_status="RUNTIME_ENABLED",
        adapter_id=name,
        adapter_status="implemented",
        runtime_enabled=True,
        free_access_required=True,
        payment_required=False,
        terms_review_status="approved",
        priority=1,
        per_host_concurrency=1,
        minimum_request_interval_seconds=0.0,
        maximum_retries=0,
        freshness_seconds=400 * 86400,
        correction_tracking=True,
        provenance_required=True,
        notes="binding test fixture",
        catalog_file="fixture",
    )

SRC_REGULATOR = _make_source("sec_gov", "securities_regulator", "T1_PRIMARY_OFFICIAL", ["financial_statements", "issuer_filings"])
SRC_OFFICIAL = _make_source("official_ir", "official_issuer", "T1_PRIMARY_OFFICIAL", ["financial_statements", "guidance"])
SRC_MACRO = _make_source("macro_stat", "national_statistics_office", "T1_PRIMARY_OFFICIAL", ["economic_data"])

BINDING_REGISTRY = Registry(1, (SRC_REGULATOR, SRC_OFFICIAL, SRC_MACRO), ())


class FakeBindingAdapter:
    def __init__(self, source_id: str, records: list[dict]):
        self.source_id = source_id
        self.adapter_id = source_id
        self.parser_version = "1.0.0"
        self._records = records

    def parse(self, content: bytes, *, content_type: str, retrieved_at: str, context: dict):
        return make_batch(
            source_id=self.source_id,
            parser_version=self.parser_version,
            content=content,
            retrieved_at=retrieved_at,
            records=self._records,
        )


def _build_test_four_factor_records(ticker: str = "BINDCO"):
    """Build paired records for all 4 factors across 2 independent sources."""
    factors = [
        ("dependency", f"dep_{ticker}", "architecture_layer", 1, "count", "issuer_guidance_or_contract", "issuer_filings"),
        ("scarcity", f"scar_{ticker}", "effective_suppliers_count", 1, "count", "issuer_guidance_or_contract", "issuer_filings"),
        ("pricing", f"price_{ticker}", "contractual_price_indexation", 12.5, "percent", "issuer_guidance_or_contract", "issuer_filings"),
        ("capture", f"cap_{ticker}", "bom_share_capture", 65.0, "percent", "issuer_financial_statement", "financial_statements"),
    ]

    sec_records = []
    ir_records = []

    for factor, cid, metric, val, unit, kind, role in factors:
        binding_meta = {
            "factor": factor,
            "claim_id": cid,
            "subject": ticker,
            "entity": f"{ticker} Inc.",
            "security": ticker,
            "metric": metric,
            "product_or_spec": "PROD_SPEC_A",
            "region": "GLOBAL",
            "unit": unit,
            "period": "2026Q2",
            "period_type": "REALIZED",
            "comparability": {"scope": "consolidated", "basis": "GAAP"},
        }
        sec_records.append({
            "canonical_url": f"https://sec_gov.example/report#{cid}",
            "published_at": STAMP,
            "jurisdiction": "US",
            "language": "en",
            "claim_type": kind,
            "evidence_role": role,
            "factor_binding": binding_meta,
            "payload": {
                "claim_ids": [cid],
                "subject": ticker,
                "metric": metric,
                "period": "2026Q2",
                "unit": unit,
                "currency": "USD",
                "value": val,
                "basis": "GAAP",
                "scope": "consolidated",
                "as_of": STAMP,
                "passage": f"Verified SEC disclosure for {metric}",
                "origin_group": "sec_filing_group",
                "product_or_spec": "PROD_SPEC_A",
            },
        })
        ir_records.append({
            "canonical_url": f"https://official_ir.example/report#{cid}",
            "published_at": STAMP,
            "jurisdiction": "US",
            "language": "en",
            "claim_type": kind,
            "evidence_role": "guidance" if role == "issuer_filings" else "financial_statements",
            "factor_binding": binding_meta,
            "payload": {
                "claim_ids": [cid],
                "subject": ticker,
                "metric": metric,
                "period": "2026Q2",
                "unit": unit,
                "currency": "USD",
                "value": val,
                "basis": "GAAP",
                "scope": "consolidated",
                "as_of": STAMP,
                "passage": f"Corroborated IR for {metric}",
                "origin_group": "official_ir_group",
                "product_or_spec": "PROD_SPEC_A",
            },
        })

    return sec_records, ir_records


def _make_candidate_for_run(ticker: str, run: AcquisitionRun) -> tuple[dict, list[dict]]:
    """Build candidate matching observations from the run."""
    c_dep = {
        "claim_id": f"dep_{ticker}",
        "claim_type": "issuer_guidance_or_contract",
        "subject": ticker,
        "metric": "architecture_layer",
        "product_or_spec": "PROD_SPEC_A",
        "period": "2026Q2",
        "unit": "count",
        "currency": "USD",
        "basis": "GAAP",
        "scope": "consolidated",
        "as_of": STAMP,
        "value": 1,
    }
    c_scar = {
        "claim_id": f"scar_{ticker}",
        "claim_type": "issuer_guidance_or_contract",
        "subject": ticker,
        "metric": "effective_suppliers_count",
        "product_or_spec": "PROD_SPEC_A",
        "period": "2026Q2",
        "unit": "count",
        "currency": "USD",
        "basis": "GAAP",
        "scope": "consolidated",
        "as_of": STAMP,
        "value": 1,
    }
    c_price = {
        "claim_id": f"price_{ticker}",
        "claim_type": "issuer_guidance_or_contract",
        "subject": ticker,
        "metric": "contractual_price_indexation",
        "product_or_spec": "PROD_SPEC_A",
        "period": "2026Q2",
        "unit": "percent",
        "currency": "USD",
        "basis": "GAAP",
        "scope": "consolidated",
        "as_of": STAMP,
        "value": 12.5,
    }
    c_cap = {
        "claim_id": f"cap_{ticker}",
        "claim_type": "issuer_financial_statement",
        "subject": ticker,
        "metric": "bom_share_capture",
        "product_or_spec": "PROD_SPEC_A",
        "period": "2026Q2",
        "unit": "percent",
        "currency": "USD",
        "basis": "GAAP",
        "scope": "consolidated",
        "as_of": STAMP,
        "value": 65.0,
    }

    obs = run.candidates_for(ticker)

    candidate = {
        "ticker": ticker,
        "name": f"{ticker} Inc.",
        "financing_risk": "NONE",
        "material_claims": [c_dep, c_scar, c_price, c_cap],
        "source_observations": obs,
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

    reconciled_claims = [
        {"claim_id": f"dep_{ticker}", "status": "SUPPORTED", "independent_evidence_families": 2},
        {"claim_id": f"scar_{ticker}", "status": "SUPPORTED", "independent_evidence_families": 2},
        {"claim_id": f"price_{ticker}", "status": "SUPPORTED", "independent_evidence_families": 2},
        {"claim_id": f"cap_{ticker}", "status": "SUPPORTED", "independent_evidence_families": 2},
    ]

    return candidate, reconciled_claims


class TestCompanyAcquisitionBindings(unittest.TestCase):
    # =========================================================================
    # Section 1: Compatibility for unrelated macro/ECB/source callers
    # =========================================================================
    def test_old_macro_compatibility_unaffected_by_company_bindings(self):
        """Missing optional company bindings must NOT invalidate ordinary non-company observation runs."""
        macro_record = {
            "canonical_url": "https://macro_stat.example/report#gdp",
            "published_at": STAMP,
            "jurisdiction": "US",
            "language": "en",
            "claim_type": "macro_indicator",
            "evidence_role": "economic_data",
            "payload": {
                "claim_ids": ["gdp"],
                "subject": "US",
                "metric": "gdp",
                "period": "2026Q2",
                "unit": "percent",
                "currency": "USD",
                "value": 2.5,
                "basis": "GAAP",
                "scope": "consolidated",
                "as_of": STAMP,
                "passage": "US real GDP growth",
                "origin_group": "macro_feed",
            },
        }
        mock_endpoints = {"macro_stat": "https://macro_stat.example/report"}
        mock_adapters = {"macro_stat": FakeBindingAdapter("macro_stat", [macro_record])}
        macro_registry = Registry(1, (SRC_MACRO,), ())

        with patch.dict(ENDPOINTS, mock_endpoints, clear=False), patch.dict(ADAPTERS, mock_adapters, clear=False):
            run = acquire_runtime_sources(
                registry=macro_registry,
                transport=lambda url: b"{\"dummy\": true}",
                clock=NOW,
            )

        self.assertIsInstance(run, AcquisitionRun)
        self.assertEqual(len(run.candidates_for("US")), 1)
        # Verify company_factor_bindings exists and is empty for ordinary macro runs
        self.assertTrue(hasattr(run, "company_factor_bindings"))
        self.assertEqual(len(run.company_factor_bindings), 0)
        self.assertEqual(len(run.company_bindings_for("US")), 0)

    # =========================================================================
    # Section 2: Real factory creates company factor bindings
    # =========================================================================
    def test_actual_factory_creates_company_factor_bindings(self):
        """acquire_runtime_sources with factor-declaring records creates AcquisitionRun with company_factor_bindings."""
        sec_recs, ir_recs = _build_test_four_factor_records("BINDCO")
        mock_endpoints = {
            "sec_gov": "https://sec_gov.example/report",
            "official_ir": "https://official_ir.example/report",
        }
        mock_adapters = {
            "sec_gov": FakeBindingAdapter("sec_gov", sec_recs),
            "official_ir": FakeBindingAdapter("official_ir", ir_recs),
        }
        test_registry = Registry(1, (SRC_REGULATOR, SRC_OFFICIAL), ())

        with patch.dict(ENDPOINTS, mock_endpoints, clear=False), patch.dict(ADAPTERS, mock_adapters, clear=False):
            run = acquire_runtime_sources(
                registry=test_registry,
                transport=lambda url: f'{{"source": "{url}"}}'.encode("utf-8"),
                clock=NOW,
            )

        self.assertIsInstance(run, AcquisitionRun)
        bindings = run.company_bindings_for("BINDCO")
        self.assertEqual(len(bindings), 4, "Must produce bindings for all 4 core factors")
        factors = {b.factor for b in bindings}
        self.assertEqual(factors, {"dependency", "scarcity", "pricing", "capture"})

        # Each binding must be bound to this exact run_id
        for b in bindings:
            self.assertEqual(b.acquisition_run_id, run.run_id)
            self.assertEqual(b.subject, "BINDCO")
            self.assertGreaterEqual(b.independent_lineage_count, 2)
            self.assertTrue(b.is_test_binding)

    # =========================================================================
    # Section 3: Consumer wiring (TEST_ONLY canonical factory-binding path)
    # =========================================================================
    def test_consumer_wiring_test_only_canonical_factory_binding_path(self):
        """Proves factory-to-admission-caller path wiring without live qualification."""
        sec_recs, ir_recs = _build_test_four_factor_records("WIRECO")
        mock_endpoints = {
            "sec_gov": "https://sec_gov.example/report",
            "official_ir": "https://official_ir.example/report",
        }
        mock_adapters = {
            "sec_gov": FakeBindingAdapter("sec_gov", sec_recs),
            "official_ir": FakeBindingAdapter("official_ir", ir_recs),
        }
        test_registry = Registry(1, (SRC_REGULATOR, SRC_OFFICIAL), ())

        with patch.dict(ENDPOINTS, mock_endpoints, clear=False), patch.dict(ADAPTERS, mock_adapters, clear=False):
            run = acquire_runtime_sources(
                registry=test_registry,
                transport=lambda url: f'{{"source": "{url}"}}'.encode("utf-8"),
                clock=NOW,
            )

        cand, rec_claims = _make_candidate_for_run("WIRECO", run)

        res = admission.reconcile_factor_authority(
            cand,
            rec_claims,
            ticker="WIRECO",
            now=NOW,
            fixture_mode=False,
            acquisition_context=run,
        )

        self.assertTrue(res["core_admitted"], f"Wiring must succeed for bound run: {res.get('diagnostics')}")
        self.assertTrue(res["dependency_licensed"])
        self.assertTrue(res["scarcity_licensed"])
        self.assertTrue(res["pricing_licensed"])
        self.assertTrue(res["capture_licensed"])
        self.assertEqual(res["admission_tier"], "TEST_ONLY_NONRUNTIME")

    # =========================================================================
    # Section 4: Negative / Conflicted Research Claims Fail Closed
    # =========================================================================
    def test_negative_claimed_scored_research_does_not_yield_eligible_factors(self):
        """Conflicted research or disqualifying candidate conditions must NOT yield licensed factors."""
        sec_recs, ir_recs = _build_test_four_factor_records("NEGCO")
        mock_endpoints = {"sec_gov": "https://sec_gov.example/report", "official_ir": "https://official_ir.example/report"}
        mock_adapters = {"sec_gov": FakeBindingAdapter("sec_gov", sec_recs), "official_ir": FakeBindingAdapter("official_ir", ir_recs)}
        test_registry = Registry(1, (SRC_REGULATOR, SRC_OFFICIAL), ())

        with patch.dict(ENDPOINTS, mock_endpoints, clear=False), patch.dict(ADAPTERS, mock_adapters, clear=False):
            run = acquire_runtime_sources(registry=test_registry, transport=lambda url: f'{{"source": "{url}"}}'.encode("utf-8"), clock=NOW)

        cand, rec_claims = _make_candidate_for_run("NEGCO", run)
        # Mark scarcity claim CONFLICTED
        for c in rec_claims:
            if c["claim_id"] == "scar_NEGCO":
                c["status"] = "CONFLICTED"

        res = bridge.bridge_reconcile_factors(
            cand,
            rec_claims,
            ticker="NEGCO",
            now=NOW,
            fixture_mode=False,
            acquisition_context=run,
        )

        self.assertFalse(res["scarcity_licensed"])
        self.assertFalse(res["core_admitted"])
        self.assertIn("scarcity", res["missing_core"])

    # =========================================================================
    # Section 5: Forged / Mutated / Cross-Run / Dangling Bindings Fail Closed
    # =========================================================================
    def test_forged_well_formed_lookalike_run_rejected(self):
        """Caller fabricating an AcquisitionRun lookalike object must be rejected."""
        class FakeRunLookalike:
            run_id = "forged-run-uuid"
            company_factor_bindings = []
            def company_bindings_for(self, subject: str):
                return []

        cand = {"ticker": "FORGECO"}
        with self.assertRaises((bridge.BridgeValidationError, TypeError)):
            bridge.bridge_reconcile_factors(
                cand,
                reconciled_claims=[],
                ticker="FORGECO",
                now=NOW,
                fixture_mode=False,
                acquisition_context=FakeRunLookalike(),
            )

    def test_cross_run_id_mutation_fails_closed(self):
        """Binding carrying mismatched acquisition_run_id fails closed."""
        sec_recs, ir_recs = _build_test_four_factor_records("CROSSRUNCO")
        mock_endpoints = {"sec_gov": "https://sec_gov.example/report", "official_ir": "https://official_ir.example/report"}
        mock_adapters = {"sec_gov": FakeBindingAdapter("sec_gov", sec_recs), "official_ir": FakeBindingAdapter("official_ir", ir_recs)}
        test_registry = Registry(1, (SRC_REGULATOR, SRC_OFFICIAL), ())

        with patch.dict(ENDPOINTS, mock_endpoints, clear=False), patch.dict(ADAPTERS, mock_adapters, clear=False):
            run = acquire_runtime_sources(registry=test_registry, transport=lambda url: f'{{"source": "{url}"}}'.encode("utf-8"), clock=NOW)

        cand, rec_claims = _make_candidate_for_run("CROSSRUNCO", run)

        # Mutate run_id on run
        tampered_bindings = [replace(b, acquisition_run_id="mutated-other-run-id") for b in run.company_factor_bindings]
        run._company_factor_bindings = tuple(tampered_bindings)

        res = bridge.bridge_reconcile_factors(
            cand,
            rec_claims,
            ticker="CROSSRUNCO",
            now=NOW,
            fixture_mode=False,
            acquisition_context=run,
        )
        self.assertFalse(res["core_admitted"])
        self.assertEqual(res["admission_tier"], "ADMISSION_DEFER")

    def test_dangling_or_mutated_canonical_observation_ids_fail_closed(self):
        """Binding referencing observation IDs not in run's candidates fails closed."""
        sec_recs, ir_recs = _build_test_four_factor_records("DANGLINGCO")
        mock_endpoints = {"sec_gov": "https://sec_gov.example/report", "official_ir": "https://official_ir.example/report"}
        mock_adapters = {"sec_gov": FakeBindingAdapter("sec_gov", sec_recs), "official_ir": FakeBindingAdapter("official_ir", ir_recs)}
        test_registry = Registry(1, (SRC_REGULATOR, SRC_OFFICIAL), ())

        with patch.dict(ENDPOINTS, mock_endpoints, clear=False), patch.dict(ADAPTERS, mock_adapters, clear=False):
            run = acquire_runtime_sources(registry=test_registry, transport=lambda url: f'{{"source": "{url}"}}'.encode("utf-8"), clock=NOW)

        cand, rec_claims = _make_candidate_for_run("DANGLINGCO", run)

        # Mutate canonical_observation_ids on dependency binding
        tampered_bindings = []
        for b in run.company_factor_bindings:
            if b.factor == "dependency":
                tampered_bindings.append(replace(b, canonical_observation_ids=("dangling_sha256_not_in_run",)))
            else:
                tampered_bindings.append(b)
        run._company_factor_bindings = tuple(tampered_bindings)

        res = bridge.bridge_reconcile_factors(
            cand,
            rec_claims,
            ticker="DANGLINGCO",
            now=NOW,
            fixture_mode=False,
            acquisition_context=run,
        )
        self.assertFalse(res["dependency_licensed"])
        self.assertFalse(res["core_admitted"])

    def test_cross_company_subject_mismatch_fails_closed(self):
        """Binding for TICKERB cannot license factors for TICKERA candidate."""
        sec_recs, ir_recs = _build_test_four_factor_records("CORPA")
        mock_endpoints = {"sec_gov": "https://sec_gov.example/report", "official_ir": "https://official_ir.example/report"}
        mock_adapters = {"sec_gov": FakeBindingAdapter("sec_gov", sec_recs), "official_ir": FakeBindingAdapter("official_ir", ir_recs)}
        test_registry = Registry(1, (SRC_REGULATOR, SRC_OFFICIAL), ())

        with patch.dict(ENDPOINTS, mock_endpoints, clear=False), patch.dict(ADAPTERS, mock_adapters, clear=False):
            run = acquire_runtime_sources(registry=test_registry, transport=lambda url: f'{{"source": "{url}"}}'.encode("utf-8"), clock=NOW)

        cand, rec_claims = _make_candidate_for_run("CORPA", run)
        # Attempt evaluation under different ticker "CORPB"
        res = bridge.bridge_reconcile_factors(
            cand,
            rec_claims,
            ticker="CORPB",
            now=NOW,
            fixture_mode=False,
            acquisition_context=run,
        )
        self.assertFalse(res["core_admitted"])

    def test_single_family_lineage_collapse_cannot_license_factor(self):
        """Multiple observations sharing origin_group collapse to 1 family (< 2 required) and fail factor licensing."""
        sec_recs, _ = _build_test_four_factor_records("COLLAPSECO")
        # Duplicate SEC records to simulate multi-chapter filing from same issuer
        sec_recs_ch2 = copy.deepcopy(sec_recs)
        for r in sec_recs_ch2:
            r["canonical_url"] = r["canonical_url"] + "_ch2"

        mock_endpoints = {"sec_gov": "https://sec_gov.example/report"}
        mock_adapters = {"sec_gov": FakeBindingAdapter("sec_gov", sec_recs + sec_recs_ch2)}
        test_registry = Registry(1, (SRC_REGULATOR,), ())

        with patch.dict(ENDPOINTS, mock_endpoints, clear=False), patch.dict(ADAPTERS, mock_adapters, clear=False):
            run = acquire_runtime_sources(registry=test_registry, transport=lambda url: b"{}", clock=NOW)

        cand, rec_claims = _make_candidate_for_run("COLLAPSECO", run)

        res = bridge.bridge_reconcile_factors(
            cand,
            rec_claims,
            ticker="COLLAPSECO",
            now=NOW,
            fixture_mode=False,
            acquisition_context=run,
        )
        self.assertFalse(res["core_admitted"])
        self.assertFalse(res["dependency_licensed"])

    def test_unreviewed_source_capability_fails_closed(self):
        """Observations from source lacking capability for factor claim_type fail closed."""
        # National statistics office (macro_stat) lacks authority for issuer guidance/financials
        macro_recs = [
            {
                "canonical_url": "https://macro_stat.example/report#dep_UNAUTHCO",
                "published_at": STAMP,
                "jurisdiction": "US",
                "language": "en",
                "claim_type": "issuer_guidance_or_contract",
                "evidence_role": "economic_data",  # role mismatch for issuer guidance
                "factor_binding": {
                    "factor": "dependency",
                    "claim_id": "dep_UNAUTHCO",
                    "subject": "UNAUTHCO",
                    "metric": "architecture_layer",
                    "product_or_spec": "SPEC_A",
                    "region": "GLOBAL",
                    "unit": "count",
                    "period": "2026Q2",
                    "period_type": "REALIZED",
                    "comparability": {"scope": "consolidated", "basis": "GAAP"},
                },
                "payload": {
                    "claim_ids": ["dep_UNAUTHCO"],
                    "subject": "UNAUTHCO",
                    "metric": "architecture_layer",
                    "period": "2026Q2",
                    "unit": "count",
                    "currency": "USD",
                    "value": 1,
                    "basis": "GAAP",
                    "scope": "consolidated",
                    "as_of": STAMP,
                    "passage": "Unauthorized claim",
                    "origin_group": "macro_origin",
                },
            }
        ]
        mock_endpoints = {"macro_stat": "https://macro_stat.example/report"}
        mock_adapters = {"macro_stat": FakeBindingAdapter("macro_stat", macro_recs)}
        test_registry = Registry(1, (SRC_MACRO,), ())

        with patch.dict(ENDPOINTS, mock_endpoints, clear=False), patch.dict(ADAPTERS, mock_adapters, clear=False):
            run = acquire_runtime_sources(registry=test_registry, transport=lambda url: b"{}", clock=NOW)

        cand, rec_claims = _make_candidate_for_run("UNAUTHCO", run)

        res = bridge.bridge_reconcile_factors(
            cand,
            rec_claims,
            ticker="UNAUTHCO",
            now=NOW,
            fixture_mode=False,
            acquisition_context=run,
        )
        self.assertFalse(res["dependency_licensed"])
        self.assertFalse(res["core_admitted"])

    def test_missing_company_bindings_records_architecture_blocker_fail_closed(self):
        """AcquisitionRun with empty company factor bindings must fail closed with ARCHITECTURE_BLOCKER."""
        empty_run = AcquisitionRun(
            _sentinel=_SENTINEL,
            registry=BINDING_REGISTRY,
            run_id="run-without-bindings-123",
            started_at=NOW,
            completed_at=NOW,
            registry_sha256="dummy_sha",
            candidates=[],
            verified_hashes={},
            successful_sources=set(),
            health_states={},
            skipped_counts={},
            skipped_sources={},
            source_failures={},
            attempted_sources=[],
            source_body_hashes={},
            source_schema_hashes={},
            source_parser_versions={},
            source_record_counts={},
            source_parsed_hashes={},
            is_synthetic=True,
            synthetic_clock=True,
        )

        cand, rec_claims = _make_candidate_for_run("NOBINDCO", empty_run)
        res = bridge.bridge_reconcile_factors(
            cand,
            rec_claims,
            ticker="NOBINDCO",
            now=NOW,
            fixture_mode=False,
            acquisition_context=empty_run,
        )
        self.assertFalse(res["core_admitted"])
        self.assertEqual(res["admission_tier"], "ADMISSION_DEFER")
        self.assertTrue(
            any("ARCHITECTURE_BLOCKER" in diag for diag in res.get("diagnostics", [])),
            "Diagnostics must report ARCHITECTURE_BLOCKER when run lacks company factor bindings",
        )


if __name__ == "__main__":
    unittest.main()
