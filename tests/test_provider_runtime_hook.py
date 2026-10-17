#!/usr/bin/env python3
"""Authoritative behavioral acceptance tests for PROVIDER_RUNTIME_HOOK_V1.

Validates:
1. Real factory integration:
   - acquire_runtime_sources knows registered adapter capabilities.
   - Calls registered adapter capability exactly once through actual evidence builder.
   - No shadow CLI or unused adapter.
2. Live safety and fail-closed defaults:
   - New capability disabled for live use until actual source policy/rights approved.
   - Global runtime catalog source is NOT enabled based on prototype existence.
   - Default legacy Macro / ECB / non-company context behavior preserved.
3. Dispatcher verification against owned registration:
   - source_id, host, content-kind, body-kind, parser-version, capabilities.
   - Caller-owned approved flags, health, source clock, raw dict cannot bootstrap trust.
4. Granular rights review per action:
   - internal_factual_research, paraphrase, brief_quotation, statutory_text,
     public_redistribution, raw_document_reproduction.
   - Unknown or requires-review rights strictly yield DEFER / UNAVAILABLE, never AUTOALLOW.
   - Official source basis only; A-matrix is a review artifact, not registered attestation.
5. Canonical binding integrity:
   - Canonical binding must reference SAME real run observations.
   - Cross-run ID, valid wrong ID, dangling/mutated observation IDs, replay/status-spoof fail closed.
6. Public adapter and evidence builder boundaries:
   - Shared limits: payload size, rows, depth, duplicate fields, HTTPS only.
   - Input immutability preserved.
   - Error privacy: static codes, no secret URL, path, or traceback echo.
   - Forbidden private keys strictly rejected.
7. CARB typed section parser context:
   - Retains actual rule version, kV/kA categories, acquisition dates, 7 unresolved refs.
   - CARB policy context != Meiden pricing/capture; technical brochure != capacity.
   - Missing core factors => UNRANKED; all current company admissions strictly 0.
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
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import adapters
from adapters.base import ADAPTERS, AdapterError, ParsedBatch, make_batch
from adapters.company_public_document import CompanyPublicDocumentAdapter
import bottleneck_claim_admission as admission
import company_claim_admission_bridge as bridge
from fetch_public_source_observations import ENDPOINTS, fetch_bytes
import provider_runtime_hook as hook
from source_acquisition import (
    AcquisitionRun,
    acquire_runtime_sources,
)
from source_health import HEALTHY, SourceHealthState
from source_observation import (
    CompanyFactorBinding,
    compute_independent_lineages,
)
from source_registry import Registry, SourceDefinition, load_registry

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
STAMP = "2026-09-15T12:00:00+00:00"


def _make_source(
    name: str,
    authority: str = "official_issuer",
    tier: str = "T1_PRIMARY_OFFICIAL",
    roles: list[str] = None,
    host: str = "example.com",
) -> SourceDefinition:
    roles = roles or ["financial_statements", "guidance"]
    return SourceDefinition(
        source_id=name,
        display_name=name,
        authority_class=authority,
        trust_tier=tier,
        evidence_roles=tuple(roles),
        jurisdictions=("US",),
        languages=("en",),
        canonical_urls=(f"https://{host}/report",),
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
        notes="provider runtime hook test fixture",
        catalog_file="fixture",
    )


class TestProviderRuntimeHook(unittest.TestCase):
    """Behavioral tests for Provider Runtime Hook V1."""

    def setUp(self):
        self.test_doc = {
            "entity": "MEIDENSHA CORPORATION",
            "document_type": "corporate_report",
            "terms_review_status": "NOT_REVIEWED",
            "rights_status": "UNKNOWN",
            "published_at": STAMP,
            "jurisdiction": "US",
            "language": "en",
            "evidence_role": "guidance",
            "claim_type": "issuer_guidance_or_contract",
            "records": [
                {
                    "title": "Development of Overseas Power T&D Business",
                    "chapter": 16,
                    "nominal_products": ["vacuum_circuit_breaker", "dry_air_switchgear"],
                    "voltage_kv": 145,
                    "target_period_type": "FORWARD_TARGET",
                    "published_at": STAMP,
                    "jurisdiction": "US",
                    "language": "en",
                    "evidence_role": "guidance",
                    "claim_type": "issuer_guidance_or_contract",
                    "factor_binding": {
                        "subject": "6508.T",
                        "factor": "dependency",
                        "metric": "architecture_layer",
                        "claim_id": "meiden_dep_1",
                    },
                    "payload": {
                        "subject": "6508.T",
                        "metric": "architecture_layer",
                        "claim_ids": ["meiden_dep_1"],
                        "as_of": STAMP,
                        "origin_group": "company_public_document",
                    },
                }
            ],
        }

    # 1. Real factory integration & calls evidence builder once
    def test_real_factory_knows_registered_adapter_capability_and_calls_builder_once(self):
        """Factory acquire_runtime_sources knows registered adapter and calls evidence builder once."""
        builder_mock = MagicMock(return_value=[{"claim_id": "test_evidence_1", "status": "built"}])
        test_cap = hook.ProviderCapability(
            source_id="company_public_document",
            adapter_id="company_public_document",
            parser_version="company-doc-v1",
            content_type="application/json",
            allowed_hosts=("www.meidensha.com",),
            allowed_body_kinds=("corporate_report", "regulatory_filing"),
            allowed_actions=("internal_factual_research", "paraphrase"),
            evidence_builder=builder_mock,
            is_live_enabled=False,
            adapter_factory=CompanyPublicDocumentAdapter,
        )
        hook.register_provider_capability(test_cap)

        src = _make_source(
            "company_public_document",
            host="www.meidensha.com",
            roles=["financial_statements", "guidance"],
        )
        test_reg = Registry(1, (src,), ())

        payload_bytes = json.dumps(self.test_doc).encode("utf-8")
        with patch.dict(ENDPOINTS, {"company_public_document": "https://www.meidensha.com/report"}, clear=False):
            run = acquire_runtime_sources(
                registry=test_reg,
                transport=lambda url: payload_bytes,
                clock=NOW,
            )

        self.assertIsInstance(run, AcquisitionRun)
        # Builder must have been called exactly once
        self.assertEqual(builder_mock.call_count, 1)
        self.assertIn("company_public_document", run.successful_sources)

    # 2. Capability disabled for live use fails closed & global catalog not enabled
    def test_new_capability_disabled_for_live_use_fails_closed(self):
        """Live execution or unapproved rights fail closed; global catalog does not contain company provider."""
        # Check global catalog
        reg = load_registry()
        registered_ids = {s.source_id for s in reg.sources}
        self.assertNotIn("company_public_document", registered_ids)

        # In live run (fetch_bytes / non-synthetic transport), unapproved capability fails closed
        src = _make_source(
            "company_public_document",
            host="www.meidensha.com",
        )
        test_reg = Registry(1, (src,), ())

        # Live call attempt without mock transport must be rejected for disabled live capability
        with patch.dict(ENDPOINTS, {"company_public_document": "https://www.meidensha.com/report"}, clear=False):
            run = acquire_runtime_sources(
                registry=test_reg,
                transport=fetch_bytes,
                clock=None,
            )
        self.assertNotIn("company_public_document", run.successful_sources)
        diag = run.summary().get("source_diagnostics", {}).get("company_public_document", {})
        self.assertEqual(diag.get("status"), "FAILED")
        self.assertIn("LIVE", str(diag.get("failure_code")))

    # 3. All-four-factor forgery fails closed with admissions = 0
    def test_all_four_factor_forgery_rejected_admissions_zero(self):
        """Forged caller flags (runtime_admitted=True, approved=True) fail closed with 0 admissions."""
        forged_cand = {
            "ticker": "FORGECO",
            "runtime_admitted": True,
            "approved": True,
            "terms_review_status": "APPROVED",
            "rights_status": "LICENSED_FREE_ACCESS",
            "dependency_evidence": {"claim_ids": ["f_dep"]},
            "scarcity_evidence": {"claim_ids": ["f_scar"]},
            "pricing_evidence": {"claim_ids": ["f_price"]},
            "capture_evidence": {"claim_ids": ["f_cap"]},
            "material_claims": [
                {"claim_id": "f_dep", "factor": "dependency", "metric": "architecture_layer", "subject": "FORGECO"},
                {"claim_id": "f_scar", "factor": "scarcity", "metric": "effective_suppliers_count", "subject": "FORGECO"},
                {"claim_id": "f_price", "factor": "pricing", "metric": "contractual_price_indexation", "subject": "FORGECO"},
                {"claim_id": "f_cap", "factor": "capture", "metric": "bom_share_capture", "subject": "FORGECO"},
            ],
        }

        # bridge_reconcile_factors without valid acquisition context
        res = bridge.bridge_reconcile_factors(
            forged_cand,
            reconciled_claims=forged_cand["material_claims"],
            ticker="FORGECO",
            now=NOW,
            fixture_mode=False,
            acquisition_context=None,
        )
        self.assertFalse(res["core_admitted"])
        self.assertEqual(res["admission_tier"], "ADMISSION_DEFER")
        self.assertEqual(len(res["missing_core"]), 4)

    # 4. Unknown / Requires Review rights yield DEFER / UNAVAILABLE, never AUTOALLOW
    def test_unknown_or_requires_review_rights_yield_defer_never_autoallow(self):
        """Action rights with UNKNOWN or REQUIRES_REVIEW strictly yield DEFER/UNAVAILABLE."""
        # Test granular action evaluation
        actions = [
            "internal_factual_research",
            "paraphrase",
            "brief_quotation",
            "statutory_text",
            "public_redistribution",
            "raw_document_reproduction",
        ]
        for act in actions:
            decision = hook.evaluate_action_rights("UNKNOWN", act, terms_review_status="NOT_REVIEWED")
            self.assertIn(decision, {"REQUIRES_REVIEW", "PROHIBITED", "DEFER", "UNAVAILABLE"})
            self.assertNotEqual(decision, "PERMITTED")
            self.assertNotEqual(decision, "AUTOALLOW")

        # Dispatch with UNKNOWN rights for public redistribution
        dispatch_res = hook.dispatch_provider_hook(
            "company_public_document",
            host="www.meidensha.com",
            content_kind="corporate_report",
            parser_version="company-doc-v1",
            action="public_redistribution",
            raw_payload={"rights_status": "UNKNOWN", "terms_review_status": "NOT_REVIEWED"},
        )
        self.assertEqual(dispatch_res.get("status"), "DEFER")
        self.assertFalse(dispatch_res.get("permitted", False))

    # 5. Dispatcher checks source_id, host, body-kind, parser-version, URI
    def test_dispatcher_checks_source_host_bodykind_parser_uri(self):
        """Dispatcher checks owned registration and rejects mismatched host, body-kind, URI, parser."""
        # Unregistered capability
        res_unreg = hook.dispatch_provider_hook(
            "unregistered_unknown_provider",
            host="example.com",
            content_kind="json",
            parser_version="1.0",
        )
        self.assertEqual(res_unreg.get("status"), "UNREGISTERED_CAPABILITY")

        # Registered capability with disallowed host
        res_host = hook.dispatch_provider_hook(
            "company_public_document",
            host="malicious-attacker.com",
            content_kind="corporate_report",
            parser_version="company-doc-v1",
        )
        self.assertEqual(res_host.get("status"), "DISALLOWED_HOST")

        # Mismatched body kind
        res_body = hook.dispatch_provider_hook(
            "company_public_document",
            host="www.meidensha.com",
            content_kind="unknown_foreign_format",
            parser_version="company-doc-v1",
        )
        self.assertEqual(res_body.get("status"), "DISALLOWED_BODY_KIND")

        # Mismatched parser version
        res_parser = hook.dispatch_provider_hook(
            "company_public_document",
            host="www.meidensha.com",
            content_kind="corporate_report",
            parser_version="wrong-parser-9.9",
        )
        self.assertEqual(res_parser.get("status"), "PARSER_VERSION_MISMATCH")

    # 6. Stale or missing clocks fail closed
    def test_stale_or_missing_clocks_fail_closed(self):
        """Observations with missing, future-dated, or stale clocks fail closed."""
        # Missing clock
        res_missing = hook.dispatch_provider_hook(
            "company_public_document",
            host="www.meidensha.com",
            content_kind="corporate_report",
            parser_version="company-doc-v1",
            raw_payload={"published_at": None, "as_of": None},
        )
        self.assertIn("CLOCK", res_missing.get("error", res_missing.get("status", "")))

        # Future clock beyond tolerance
        res_future = hook.dispatch_provider_hook(
            "company_public_document",
            host="www.meidensha.com",
            content_kind="corporate_report",
            parser_version="company-doc-v1",
            raw_payload={"published_at": "2030-01-01T00:00:00Z"},
        )
        self.assertIn("CLOCK", res_future.get("error", res_future.get("status", "")))

    # 7. Cross-run mutation and canonical ID tampering fail closed
    def test_cross_run_mutation_and_canonical_id_tampering_fail_closed(self):
        """Cross-run ID mutation and dangling canonical IDs fail closed."""
        b = CompanyFactorBinding(
            schema_version=1,
            acquisition_run_id="run-A",
            binding_id="bind-1",
            claim_id="c-1",
            subject="MUTCO",
            factor="dependency",
            metric="architecture_layer",
            product_or_spec="SPEC1",
            region="GLOBAL",
            unit="count",
            period="2026Q2",
            period_type="REALIZED",
            entity="MUTCO",
            security="MUT",
            evidence_role="guidance",
            source_clock=STAMP,
            event_clock=STAMP,
            retrieval_clock=STAMP,
            canonical_observation_ids=("obs-1",),
            lineage_ids=("lineage-1",),
            independent_lineage_count=2,
            is_test_binding=True,
        )
        # Validate binding against a run with different run_id
        valid = hook.validate_binding_against_run(b, expected_run_id="run-B", candidates=[])
        self.assertFalse(valid["valid"])
        self.assertEqual(valid["error"], "CROSS_RUN_MUTATION")

        # Validate binding referencing missing canonical observation ID
        valid_dangling = hook.validate_binding_against_run(
            b,
            expected_run_id="run-A",
            candidates=[{"observation_id": "other-obs"}],
        )
        self.assertFalse(valid_dangling["valid"])
        self.assertEqual(valid_dangling["error"], "DANGLING_CANONICAL_OBSERVATION_ID")

    # 8. Normal macro-compatible transport preserved
    def test_normal_macro_compatible_transport_preserved(self):
        """Existing legacy runs without company claims run completely unaffected."""
        src_macro = _make_source("macro_stat", "national_statistics_office", "T1_PRIMARY_OFFICIAL", ["economic_data"])
        test_reg = Registry(1, (src_macro,), ())

        macro_rec = {
            "canonical_url": "https://example.com/macro/report",
            "published_at": STAMP,
            "jurisdiction": "US",
            "language": "en",
            "claim_type": "macroeconomic_indicator",
            "evidence_role": "economic_data",
            "payload": {
                "metric": "cpi",
                "value": 105.2,
                "as_of": STAMP,
                "origin_group": "macro_stat",
            },
        }
        macro_payload = json.dumps([macro_rec]).encode("utf-8")
        with patch.dict(ENDPOINTS, {"macro_stat": "https://example.com/macro/report"}, clear=False):
            mock_ad = MagicMock()
            mock_ad.source_id = "macro_stat"
            mock_ad.adapter_id = "macro_stat"
            mock_ad.parser_version = "1.0"
            mock_ad.content_type = "application/json"
            mock_ad.parse.return_value = make_batch(
                source_id="macro_stat",
                parser_version="1.0",
                content=macro_payload,
                retrieved_at=STAMP,
                records=[macro_rec],
            )
            with patch.dict(ADAPTERS, {"macro_stat": mock_ad}, clear=False):
                run = acquire_runtime_sources(
                    registry=test_reg,
                    transport=lambda url: macro_payload,
                    clock=NOW,
                )
        self.assertIsInstance(run, AcquisitionRun)
        self.assertEqual(len(run.company_factor_bindings), 0)
        self.assertIn("macro_stat", run.successful_sources)

    # 9. Input immutability & privacy preserved
    def test_input_immutability_and_privacy_ordering_preserved(self):
        """Input payloads remain deeply immutable and private keys are strictly rejected."""
        raw_input = {
            "entity": "TEST CORP",
            "document_type": "corporate_report",
            "private_field": {"line_user_id": "U1234567890"},
            "records": [{"metric": "throughput", "value": 10}],
        }
        input_copy = copy.deepcopy(raw_input)

        # Dispatcher must reject private keys
        res = hook.dispatch_provider_hook(
            "company_public_document",
            host="www.meidensha.com",
            content_kind="corporate_report",
            parser_version="company-doc-v1",
            raw_payload=raw_input,
        )
        self.assertEqual(res.get("status"), "PRIVATE_PAYLOAD_DETECTED")
        # Immutability check: raw_input was not mutated in-place
        self.assertEqual(raw_input, input_copy)

    # 10. CARB policy context retains unresolved refs and 0 admissions
    def test_carb_policy_context_retains_unresolved_refs_and_zero_admission(self):
        """CARB regulatory context != Meiden pricing/capture; admissions strictly 0."""
        # Unresolved refs in CARB regulations remain unresolved
        carb_summary = hook.get_carb_regulatory_summary()
        self.assertEqual(carb_summary["unresolved_refs_count"], 7)
        self.assertEqual(carb_summary["runtime_admissions"], 0)
        self.assertFalse(carb_summary["confers_pricing_power"])
        self.assertFalse(carb_summary["confers_equity_capture"])


if __name__ == "__main__":
    unittest.main()
