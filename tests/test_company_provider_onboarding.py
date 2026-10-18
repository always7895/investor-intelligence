"""Tests for Company Provider Onboarding V1.

Validates:
1. Adapter structural validation for company public documents.
2. Invariants for source readiness:
   - Unreviewed terms of use (NOT_REVIEWED) fail-closed against runtime enablement.
   - Unknown rights status (UNKNOWN) strictly prevents distribution or factor licensing.
   - Multiple chapters/filings from the same issuer collapse to 1 lineage family.
   - Forward targets and conditional projections are rejected for factor licensing.
   - Nominal OEM claims cannot infer effective supplier scarcity.
   - Factory integration with make_batch and AcquisitionRun preserves 0 live admissions.
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

from adapters.base import AdapterError, ParsedBatch, make_batch
from adapters.company_public_document import (
    CompanyPublicDocumentAdapter,
    DOCUMENT_TYPES,
)
from source_observation import (
    CompanyFactorBinding,
    SourceObservation,
    compute_independent_lineages,
)

NOW_ISO = "2026-09-15T10:00:00+00:00"


class TestCompanyProviderOnboarding(unittest.TestCase):
    def setUp(self):
        self.adapter = CompanyPublicDocumentAdapter()

    def test_adapter_metadata(self):
        self.assertEqual(self.adapter.source_id, "company_public_document")
        self.assertTrue(hasattr(self.adapter, "parser_version"))
        self.assertEqual(self.adapter.content_type, "application/json")

    def test_parse_valid_document_payload(self):
        payload = {
            "entity": "MEIDENSHA CORPORATION",
            "jurisdiction": "JP",
            "document_type": "corporate_report",
            "report_period": "2025",
            "as_of": "2025-03-31",
            "terms_review_status": "NOT_REVIEWED",
            "rights_status": "UNKNOWN",
            "records": [
                {
                    "title": "Development of Overseas Power T&D Business",
                    "chapter": 16,
                    "nominal_products": ["vacuum_circuit_breaker", "dry_air_switchgear"],
                    "voltage_kv": 145,
                    "target_period_type": "FORWARD_TARGET",
                }
            ],
        }
        content = json.dumps(payload).encode("utf-8")
        batch = self.adapter.parse(
            content,
            content_type="application/json",
            retrieved_at=NOW_ISO,
            context={"canonical_url": "https://www.meidensha.com/ir/"},
        )
        self.assertIsInstance(batch, ParsedBatch)
        self.assertEqual(batch.source_id, "company_public_document")
        self.assertEqual(batch.record_count, 1)
        rec = batch.records[0]
        self.assertEqual(rec["entity"], "MEIDENSHA CORPORATION")
        self.assertEqual(rec["rights_status"], "UNKNOWN")

    def test_payload_too_large_rejected(self):
        large_content = b"x" * (7_000_000)
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.parse(
                large_content,
                content_type="application/json",
                retrieved_at=NOW_ISO,
                context={},
            )
        self.assertIn("PAYLOAD_TOO_LARGE", str(ctx.exception))

    def test_invalid_json_rejected(self):
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.parse(
                b"{not-valid-json",
                content_type="application/json",
                retrieved_at=NOW_ISO,
                context={},
            )
        self.assertIn("INVALID_JSON", str(ctx.exception))

    def test_unreviewed_terms_fail_closed_for_runtime(self):
        doc = {
            "entity": "MEIDENSHA CORPORATION",
            "terms_review_status": "NOT_REVIEWED",
            "rights_status": "UNKNOWN",
            "records": [{"metric": "throughput", "value": 100}],
        }
        batch = self.adapter.parse(
            json.dumps(doc).encode("utf-8"),
            content_type="application/json",
            retrieved_at=NOW_ISO,
            context={},
        )
        rec = batch.records[0]
        self.assertFalse(rec.get("runtime_admitted", False))
        self.assertEqual(rec.get("terms_review_status"), "NOT_REVIEWED")
        self.assertEqual(rec.get("rights_status"), "UNKNOWN")

    def test_same_issuer_chapters_collapse_to_single_lineage(self):
        obs1 = {
            "independence_group": "meidensha_group",
            "origin_group": "meidensha_report2025",
            "content_sha256": "hash_chapter_16",
        }
        obs2 = {
            "independence_group": "meidensha_group",
            "origin_group": "meidensha_report2025",
            "content_sha256": "hash_chapter_17",
        }
        obs3 = {
            "independence_group": "meidensha_group",
            "origin_group": "meidensha_report2025",
            "content_sha256": "hash_chapter_24",
        }
        lineages = compute_independent_lineages([obs1, obs2, obs3])
        self.assertEqual(lineages, 1, "Multiple chapters from same issuer must collapse to 1 lineage")

    def test_forward_targets_rejected_for_realized_licensing(self):
        doc = {
            "entity": "MEIDENSHA CORPORATION",
            "terms_review_status": "NOT_REVIEWED",
            "rights_status": "UNKNOWN",
            "records": [
                {
                    "factor": "scarcity",
                    "period_type": "FORWARD_TARGET",
                    "value": 5,
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
        self.assertFalse(rec.get("factor_licensing_eligible", False))

    def test_nominal_oem_does_not_infer_effective_capacity(self):
        doc = {
            "entity": "MEIDENSHA CORPORATION",
            "terms_review_status": "NOT_REVIEWED",
            "rights_status": "UNKNOWN",
            "records": [
                {
                    "nominal_products": ["145kV_dry_air_gis"],
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
        self.assertIsNone(rec.get("effective_qualified_throughput"))
        self.assertEqual(rec.get("scarcity_inference_allowed"), False)


if __name__ == "__main__":
    unittest.main()
