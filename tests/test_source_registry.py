from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_registry import (  # noqa: E402
    DEFAULT_POLICY_PATH,
    SourceRegistryError,
    _validate_source,
    assess_claim_evidence,
    canonicalize_url,
    coverage_ledger,
    load_json,
    load_registry,
    select_sources,
)


class SourceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_registry()

    def test_registry_has_no_artificial_source_count_limit(self) -> None:
        summary = self.registry.summary()
        self.assertIsNone(summary["artificial_source_count_limit"])
        self.assertGreaterEqual(summary["catalog_file_count"], 6)
        # This is a seed-depth guard, not a maximum. The directory loader may
        # grow to any number of catalog files and sources.
        self.assertGreaterEqual(summary["source_count"], 80)

    def test_every_catalogued_source_is_free_https_and_provenanced(self) -> None:
        for source in self.registry.sources:
            self.assertTrue(source.free_access_required, source.source_id)
            self.assertFalse(source.payment_required, source.source_id)
            self.assertTrue(source.provenance_required, source.source_id)
            self.assertTrue(source.independence_group, source.source_id)
            self.assertTrue(source.canonical_urls, source.source_id)
            for url in source.canonical_urls:
                self.assertTrue(url.startswith("https://"), (source.source_id, url))

    def test_runtime_enabled_sources_have_passed_all_enable_gates(self) -> None:
        for source in self.registry.runtime_sources():
            self.assertEqual(source.admission_status, "RUNTIME_ENABLED")
            self.assertEqual(source.adapter_status, "implemented")
            self.assertEqual(source.terms_review_status, "approved")
            self.assertNotEqual(source.trust_tier, "T4_QUARANTINED")

    def test_default_selection_has_no_implicit_total_limit(self) -> None:
        all_sources = select_sources(self.registry, runtime_only=False)
        self.assertEqual(len(all_sources), len(self.registry.sources))
        first_five = select_sources(
            self.registry, runtime_only=False, operational_limit=5
        )
        self.assertEqual(len(first_five), 5)
        self.assertEqual(first_five, all_sources[:5])

    def test_coverage_ledger_spans_multiple_regions_and_authorities(self) -> None:
        coverage = coverage_ledger(self.registry)
        for jurisdiction in ("GLOBAL", "US", "TW", "JP", "EU", "ZA", "SA"):
            self.assertIn(jurisdiction, coverage["jurisdictions"])
        for authority in (
            "securities_regulator",
            "regulated_exchange",
            "central_bank",
            "national_statistics_office",
            "international_organization",
            "academic_repository",
        ):
            self.assertIn(authority, coverage["authority_classes"])

    def test_direct_official_fact_requires_t1(self) -> None:
        passed = assess_claim_evidence(
            self.registry,
            ["us_sec_edgar"],
            claim_kind="direct_official_fact",
        )
        self.assertTrue(passed["passed"])

        failed = assess_claim_evidence(
            self.registry,
            ["reuters_public"],
            claim_kind="direct_official_fact",
        )
        self.assertFalse(failed["passed"])

    def test_interpretive_claim_requires_independent_corroboration(self) -> None:
        passed = assess_claim_evidence(
            self.registry,
            ["us_sec_edgar", "us_fred"],
            claim_kind="material_interpretive_claim",
        )
        self.assertTrue(passed["passed"])
        self.assertGreaterEqual(len(passed["independence_groups"]), 2)

        failed = assess_claim_evidence(
            self.registry,
            ["us_sec_edgar"],
            claim_kind="material_interpretive_claim",
        )
        self.assertFalse(failed["passed"])

    def test_t3_media_cannot_replace_primary_evidence(self) -> None:
        assessment = assess_claim_evidence(
            self.registry,
            ["reuters_public", "associated_press_public", "bbc_public"],
            claim_kind="material_interpretive_claim",
        )
        self.assertFalse(assessment["passed"])

    def test_runtime_enable_fails_closed_before_all_gates_pass(self) -> None:
        policy = load_json(DEFAULT_POLICY_PATH)
        raw = {
            "source_id": "synthetic.invalid_runtime",
            "display_name": "Synthetic Invalid Runtime Source",
            "authority_class": "government_open_data",
            "trust_tier": "T1_PRIMARY_OFFICIAL",
            "evidence_roles": ["test"],
            "jurisdictions": ["TEST"],
            "languages": ["en"],
            "canonical_urls": ["https://example.test/data"],
            "independence_group": "synthetic_invalid_runtime",
            "admission_status": "IDENTITY_VERIFIED",
            "adapter": {"id": "synthetic", "status": "planned"},
            "access": {
                "free_access_required": True,
                "payment_required": False,
                "terms_review_status": "pending",
            },
            "runtime": {
                "enabled": True,
                "per_host_concurrency": 1,
                "minimum_request_interval_seconds": 1,
                "maximum_retries": 1,
                "freshness_seconds": 3600,
            },
            "provenance": {"required": True, "correction_tracking": True},
            "priority": 1,
        }
        with self.assertRaises(SourceRegistryError):
            _validate_source(
                raw,
                catalog_file=ROOT / "config" / "sources" / "synthetic.json",
                policy=policy,
            )

    def test_url_canonicalization_removes_tracking_and_fragments(self) -> None:
        value = canonicalize_url(
            "https://Example.COM/path/?utm_source=x&series=ABC#fragment"
        )
        self.assertEqual(value, "https://example.com/path?series=ABC")

    def test_unknown_source_is_reported_not_silently_accepted(self) -> None:
        result = assess_claim_evidence(
            self.registry,
            ["us_sec_edgar", "not_registered"],
            claim_kind="direct_official_fact",
        )
        self.assertEqual(result["unknown_source_ids"], ["not_registered"])


if __name__ == "__main__":
    unittest.main()
