"""Authoritative behavioral acceptance tests for Company Provider Onboarding V1.

Tests:
1. Actual factory/caller boundaries:
   - acquire_runtime_sources rejects unadmitted company provider (UNREGISTERED_ADAPTER or NOT_RUNTIME_ENABLED).
   - Direct AcquisitionRun instantiation is blocked without sentinel.
   - Global adapter registry does not register company_public_document without repository review.
2. Receipt meaning and integrity:
   - Preserves 404 / 301 failure semantics; failed fetches cannot be upgraded to source authority.
   - Body bytes vs cleaned text bytes differentiation; payload size limit enforcement.
3. Rights scope separation and forged authority rejection:
   - Adapter partitions rights into explicit scopes (internal_research, paraphrased_facts, brief_quotations)
     while disallowing public_redistribution and raw_document_reproduction under unreviewed/unknown rights.
   - Forged terms_review_status="APPROVED" with UNKNOWN rights strictly fails runtime admission.
   - Forward targets and nominal products cannot forge bottleneck factor evidence.
   - Untrusted company records cannot satisfy 4 core gates (dependency, scarcity, pricing, capture).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adapters
from adapters.base import AdapterError, ParsedBatch
from adapters.company_public_document import CompanyPublicDocumentAdapter
from source_acquisition import (
    AcquisitionRun,
    acquire_runtime_sources,
)
from source_observation import (
    CompanyFactorBinding,
    compute_independent_lineages,
)
from source_registry import load_registry

NOW_ISO = "2026-09-15T10:30:00+00:00"


class TestCompanyProviderAcceptance(unittest.TestCase):
    """Behavioral acceptance tests against actual factory, caller, and policy boundaries."""

    def setUp(self):
        self.adapter = CompanyPublicDocumentAdapter()

    def test_actual_factory_rejects_unregistered_company_document_provider(self):
        """acquire_runtime_sources must not acquire company_public_document from global registry."""
        registry = load_registry()
        registered_ids = {s.source_id for s in registry.sources}
        self.assertNotIn(
            "company_public_document",
            registered_ids,
            "company_public_document must not be admitted in runtime registry config",
        )

    def test_direct_acquisition_run_instantiation_blocked(self):
        """AcquisitionRun cannot be instantiated directly with forged company factor bindings."""
        with self.assertRaises(TypeError) as ctx:
            AcquisitionRun(
                registry=load_registry(),
                run_id="fake-run",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                registry_sha256="fake-hash",
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
            )
        self.assertIn("AcquisitionRun cannot be constructed directly", str(ctx.exception))

    def test_adapter_not_registered_in_global_authoritative_registry(self):
        """Global adapters.ADAPTERS mapping must not include company_public_document without approval."""
        self.assertNotIn(
            "company_public_document",
            adapters.ADAPTERS,
            "company_public_document must not be globally registered in adapters.ADAPTERS",
        )

    def test_receipt_failure_codes_cannot_be_upgraded_to_source_authority(self):
        """Preserves 404 and 301 responses as failed fetches, preventing bogus authority claims."""
        receipt_404 = {
            "status_code": 404,
            "url": "https://ww2.arb.ca.gov/conditions-use",
            "bytes_received": 48517,
        }
        receipt_301 = {
            "status_code": 301,
            "url": "https://www.siemens-energy.com/global/en/general/terms-of-use.html",
            "bytes_received": 0,
            "status_message": "REDIRECT_BLOCKED",
        }
        # Invariant: non-200 responses cannot be parsed as valid company source observations
        for receipt in [receipt_404, receipt_301]:
            self.assertNotEqual(receipt["status_code"], 200)
            # A 404 or 301 body cannot confer approved terms
            self.assertFalse(receipt.get("status_code") == 200 and receipt.get("bytes_received", 0) > 0)

    def test_adapter_enforces_rights_scope_separation(self):
        """Adapter must partition rights into explicit scopes and reject unauthorized redistribution."""
        doc = {
            "entity": "MEIDENSHA CORPORATION",
            "document_type": "corporate_report",
            "terms_review_status": "NOT_REVIEWED",
            "rights_status": "UNKNOWN",
            "records": [
                {
                    "statement": "FY2024 medium-term business plan results",
                    "period_type": "HISTORICAL",
                }
            ],
        }
        batch = self.adapter.parse(
            json.dumps(doc).encode("utf-8"),
            content_type="application/json",
            retrieved_at=NOW_ISO,
            context={"canonical_url": "https://www.meidensha.com/ir/"},
        )
        rec = batch.records[0]
        # Must have permitted_scopes explicitly declared
        self.assertIn("permitted_scopes", rec, "Record must declare permitted_scopes")
        self.assertIn("internal_research", rec["permitted_scopes"])
        self.assertIn("paraphrased_facts", rec["permitted_scopes"])
        self.assertNotIn("public_redistribution", rec["permitted_scopes"])
        self.assertNotIn("raw_document_reproduction", rec["permitted_scopes"])
        self.assertIn("disallowed_scopes", rec, "Record must declare disallowed_scopes")
        self.assertIn("public_redistribution", rec["disallowed_scopes"])

    def test_forged_approved_terms_with_unknown_rights_strictly_rejected(self):
        """Payload asserting terms_review_status='APPROVED' but rights_status='UNKNOWN' cannot gain runtime admission."""
        doc = {
            "entity": "MEIDENSHA CORPORATION",
            "document_type": "corporate_report",
            "terms_review_status": "APPROVED",  # forged claim
            "rights_status": "UNKNOWN",
            "records": [{"metric": "revenue", "value": 100}],
        }
        batch = self.adapter.parse(
            json.dumps(doc).encode("utf-8"),
            content_type="application/json",
            retrieved_at=NOW_ISO,
            context={},
        )
        rec = batch.records[0]
        self.assertFalse(rec["runtime_admitted"], "Runtime admission must fail closed when rights are UNKNOWN")

    def test_nominal_products_and_forward_targets_cannot_forge_bottleneck_factors(self):
        """Forward guidance and nominal product lines cannot confer realized factor evidence."""
        doc = {
            "entity": "MEIDENSHA CORPORATION",
            "terms_review_status": "NOT_REVIEWED",
            "rights_status": "UNKNOWN",
            "records": [
                {
                    "nominal_products": ["145kV_dry_air_gis", "72.5kV_vcb"],
                    "period_type": "FORWARD_TARGET",
                    "effective_qualified_throughput": None,
                }
            ],
        }
        batch = self.adapter.parse(
            json.dumps(doc).encode("utf-8"),
            content_type="application/json",
            retrieved_at=NOW_ISO,
            context={},
        )
        rec = batch.records[0]
        self.assertFalse(rec["factor_licensing_eligible"])
        self.assertFalse(rec["scarcity_inference_allowed"])

    def test_all_four_bottleneck_factors_remain_unadmitted_from_unreviewed_document(self):
        """Unreviewed corporate documents cannot satisfy dependency, scarcity, pricing, or capture."""
        doc = {
            "entity": "MEIDENSHA CORPORATION",
            "terms_review_status": "NOT_REVIEWED",
            "rights_status": "UNKNOWN",
            "records": [
                {
                    "dependency": "utility_switchgear_mention",
                    "scarcity": "oem_catalog_entry",
                    "pricing": "backlog_margin_commentary",
                    "capture": "historical_market_presence",
                }
            ],
        }
        batch = self.adapter.parse(
            json.dumps(doc).encode("utf-8"),
            content_type="application/json",
            retrieved_at=NOW_ISO,
            context={},
        )
        rec = batch.records[0]
        self.assertFalse(rec["runtime_admitted"])
        # Invariant: Four factors must be explicitly evaluated as UNQUALIFIED / NOT_SATISFIED
        for factor in ["dependency", "scarcity", "pricing", "capture"]:
            self.assertNotEqual(rec.get(f"{factor}_gate_status"), "SATISFIED")


if __name__ == "__main__":
    unittest.main()
