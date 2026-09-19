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

    def test_security_flags_require_actual_booleans(self) -> None:
        path = ROOT / "config/sources/americas-authorities.json"
        policy = load_json(DEFAULT_POLICY_PATH)
        for section, field in (("runtime", "enabled"), ("access", "free_access_required"),
                               ("access", "payment_required"), ("provenance", "required"),
                               ("provenance", "correction_tracking")):
            for value in ("false", "true", 0, 1):
                raw = load_json(path)["sources"][0]
                raw[section][field] = value
                with self.subTest(section=section, field=field, value=value), self.assertRaises(SourceRegistryError):
                    _validate_source(raw, catalog_file=path, policy=policy)

    def test_integer_fields_do_not_truncate_or_accept_booleans(self) -> None:
        path = ROOT / "config/sources/americas-authorities.json"
        for value in (True, 1.9, "2"):
            raw = load_json(path)["sources"][0]
            raw["runtime"]["per_host_concurrency"] = value
            with self.assertRaises(SourceRegistryError):
                _validate_source(raw, catalog_file=path, policy=load_json(DEFAULT_POLICY_PATH))

    def test_url_errors_do_not_echo_credentials_and_nonstandard_ports_fail(self) -> None:
        for url in ("https://synthetic-user:synthetic-private@example.test/", "https://example.test:8443/"):
            with self.assertRaises(SourceRegistryError) as error:
                canonicalize_url(url)
            self.assertNotIn("synthetic-private", str(error.exception))

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


class SourceRegistryCoverageCliTests(unittest.TestCase):
    """Actual user-facing caller: `python scripts/source_registry.py coverage`.

    No registry/runtime writes; fixture writes are allowed inside a fresh
    test-owned directory under the untracked .tmp/ scratch root (no network).
    """

    @classmethod
    def setUpClass(cls) -> None:
        import json
        import tempfile

        source_document = load_json(ROOT / "config" / "sources" / "europe-authorities.json")
        fixture_sources = source_document["sources"][:3]
        cls._json = json
        cls.fixture_source_ids = [source["source_id"] for source in fixture_sources]
        # The loader records catalog paths relative to the repo BASE_DIR, so the
        # fixture lives under the untracked .tmp/ scratch root. Create the shared
        # root if absent (clean-checkout CI does not guarantee it); never remove it.
        scratch_root = ROOT / ".tmp"
        scratch_root.mkdir(parents=True, exist_ok=True)
        # The TemporaryDirectory handle owns exactly this fresh directory; register
        # its cleanup immediately so even a later setUpClass failure deletes only
        # this test-owned fixture, never a reused dir/evidence.
        cls._tmp = tempfile.TemporaryDirectory(prefix="source-registry-cli-", dir=scratch_root)
        cls.addClassCleanup(cls._tmp.cleanup)
        root = Path(cls._tmp.name)
        cls.fixture_src = root / "src"
        cls.fixture_src.mkdir()
        (cls.fixture_src / "fixture-catalog.json").write_text(
            json.dumps({"schema_version": 1, "sources": fixture_sources}, ensure_ascii=False),
            encoding="utf-8",
        )
        # Every *.json inside the source dir is a catalog, so the policy lives outside it.
        cls.fixture_policy = root / "registry-policy.json"
        cls.fixture_policy.write_bytes(DEFAULT_POLICY_PATH.read_bytes())
        cls.script = ROOT / "scripts" / "source_registry.py"

    def _run_coverage(self, source_dir: Path) -> "subprocess.CompletedProcess[str]":
        import subprocess

        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                "coverage",
                "--source-dir",
                str(source_dir),
                "--policy",
                str(self.fixture_policy),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_coverage_cli_matches_in_process_ledger_with_fixture_ids_only(self) -> None:
        expected = coverage_ledger(load_registry(self.fixture_src, self.fixture_policy))
        first = self._run_coverage(self.fixture_src)
        second = self._run_coverage(self.fixture_src)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(first.stdout, second.stdout)  # deterministic: two runs
        self.assertEqual(
            self._json.loads(first.stdout),
            self._json.loads(self._json.dumps(expected)),
        )
        ledger_ids = {
            source_id
            for members_by_key in expected.values()
            for members in members_by_key.values()
            for source_id in members["source_ids"]
        }
        self.assertTrue(ledger_ids)
        self.assertEqual(ledger_ids, set(self.fixture_source_ids))  # fixture only, no fabrication

    def test_malformed_fixture_fails_closed_without_success_json(self) -> None:
        bad = Path(self._tmp.name) / "bad"
        bad.mkdir()
        (bad / "broken.json").write_text(
            self._json.dumps({"schema_version": 1, "sources": "not-an-array"}),
            encoding="utf-8",
        )
        result = self._run_coverage(bad)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_REGISTRY_INVALID", result.stdout)
        with self.assertRaises(ValueError):
            self._json.loads(result.stdout)

    def test_missing_fixture_dir_fails_closed(self) -> None:
        result = self._run_coverage(Path(self._tmp.name) / "does-not-exist")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_REGISTRY_INVALID", result.stdout)
        with self.assertRaises(ValueError):
            self._json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()
