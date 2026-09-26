from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_claim_taxonomy_inventory import (  # noqa: E402
    DEFAULT_TAXONOMY_PATH,
    TaxonomyInventoryError,
    inventory,
    load_json_strict,
)
from source_registry import (  # noqa: E402
    DEFAULT_CLAIM_POLICY_PATH,
    DEFAULT_FEDERATION_POLICY_PATH,
    DEFAULT_POLICY_PATH,
    SourceRegistryError,
    load_registry,
    route_claim,
)
import source_declared_candidates as mod  # noqa: E402
from source_declared_candidates import (  # noqa: E402
    DeclaredCandidatesError,
    route_declared_candidates,
)


def _macro_source(
    source_id,
    *,
    authority_class,
    evidence_roles,
    enabled=True,
    adapter_status="implemented",
    freshness=3600,
):
    return {
        "source_id": source_id,
        "display_name": f"{source_id} display",
        "authority_class": authority_class,
        "trust_tier": "T1_PRIMARY_OFFICIAL",
        "evidence_roles": list(evidence_roles),
        "jurisdictions": ["US"],
        "languages": ["en"],
        "canonical_urls": [f"https://example.invalid/{source_id}"],
        "independence_group": source_id,
        "admission_status": "RUNTIME_ENABLED" if enabled else "IDENTITY_VERIFIED",
        "adapter": {"id": source_id, "status": adapter_status},
        "access": {
            "free_access_required": True,
            "payment_required": False,
            "terms_review_status": "approved",
        },
        "runtime": {
            "enabled": enabled,
            "per_host_concurrency": 2,
            "minimum_request_interval_seconds": 0.0,
            "maximum_retries": 3,
            "freshness_seconds": freshness,
        },
        "provenance": {"required": True, "correction_tracking": True},
        "priority": 100,
        "notes": "fixture macro source",
    }


def _nonmacro_source(source_id):
    return {
        "source_id": source_id,
        "display_name": f"{source_id} display",
        "authority_class": "securities_regulator",
        "trust_tier": "T1_PRIMARY_OFFICIAL",
        "evidence_roles": ["issuer_filings"],
        "jurisdictions": ["US"],
        "languages": ["en"],
        "canonical_urls": [f"https://example.invalid/{source_id}"],
        "independence_group": source_id,
        "admission_status": "RUNTIME_ENABLED",
        "adapter": {"id": source_id, "status": "implemented"},
        "access": {
            "free_access_required": True,
            "payment_required": False,
            "terms_review_status": "approved",
        },
        "runtime": {
            "enabled": True,
            "per_host_concurrency": 2,
            "minimum_request_interval_seconds": 0.0,
            "maximum_retries": 3,
            "freshness_seconds": 3600,
        },
        "provenance": {"required": True, "correction_tracking": True},
        "priority": 100,
        "notes": "fixture non-macro source",
    }


class DeclaredCandidatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scratch_root = ROOT / ".tmp"
        scratch_root.mkdir(parents=True, exist_ok=True)
        cls._tmp = tempfile.TemporaryDirectory(
            prefix="source-declared-candidates-", dir=scratch_root
        )
        cls.addClassCleanup(cls._tmp.cleanup)
        cls._fixture_counter = 0
        root = Path(cls._tmp.name)
        cls.taxonomy = load_json_strict(DEFAULT_TAXONOMY_PATH)
        cls.claim_policy = load_json_strict(DEFAULT_CLAIM_POLICY_PATH)
        cls.federation_policy = load_json_strict(DEFAULT_FEDERATION_POLICY_PATH)
        # Derive a valid macro authority class + evidence roles from the real
        # registry so the owned fixture is guaranteed to pass validation and
        # match the macro_indicator semantics.
        real_registry = load_registry()
        macro_route = route_claim(
            real_registry,
            "macro_indicator",
            cls.claim_policy,
            runtime_only=True,
            federation_policy=cls.federation_policy,
        )
        if macro_route["candidate_sources"]:
            real_macro = real_registry.by_id()[macro_route["candidate_sources"][0]]
            cls._macro_authority = real_macro.authority_class
            cls._macro_roles = real_macro.evidence_roles
        else:
            cls._macro_authority = "national_statistics_office"
            cls._macro_roles = ("gdp", "inflation")
        cls.registry_with_macro = cls._load_fixture_registry(
            root / "with-macro",
            [_macro_source(
                "fixture_macro_gdp",
                authority_class=cls._macro_authority,
                evidence_roles=cls._macro_roles,
            )],
        )
        cls.registry_empty = cls._load_fixture_registry(
            root / "empty", [_nonmacro_source("fixture_nonmacro")]
        )

    @classmethod
    def _load_fixture_registry(cls, root: Path, sources):
        root.mkdir(parents=True)
        (root / "fixture-catalog.json").write_text(
            json.dumps({"schema_version": 1, "sources": sources}, ensure_ascii=False),
            encoding="utf-8",
        )
        return load_registry(root, DEFAULT_POLICY_PATH)

    def _macro_fixture(self, source_id):
        return _macro_source(
            source_id,
            authority_class=self._macro_authority,
            evidence_roles=self._macro_roles,
        )

    def _build_fixture_dir(self, sources) -> Path:
        type(self)._fixture_counter += 1
        root = Path(self._tmp.name) / f"cli-fixture-{type(self)._fixture_counter}"
        root.mkdir(parents=True)
        (root / "fixture-catalog.json").write_text(
            json.dumps({"schema_version": 1, "sources": sources}, ensure_ascii=False),
            encoding="utf-8",
        )
        return root

    def _run_cli(self, args):
        cmd = [sys.executable, str(ROOT / "scripts" / "source_declared_candidates.py")] + args
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), env=env)

    # ------------------------------------------------------------------
    # Direct helper: positive + delegation.
    # ------------------------------------------------------------------
    def test_helper_positive(self):
        envelope = route_declared_candidates(
            self.registry_with_macro,
            self.taxonomy,
            self.claim_policy,
            self.federation_policy,
            claim_class="MACRO",
            profile="statistical-series-v1",
        )
        self.assertEqual(envelope["stage"], "CANDIDATES_ONLY")
        self.assertEqual(envelope["claim_class"], "MACRO")
        self.assertEqual(envelope["profile"], "statistical-series-v1")
        self.assertEqual(envelope["mapped_family"], "macro_indicator")
        self.assertTrue(envelope["route_performed"])
        self.assertFalse(envelope["qualification_performed"])
        self.assertFalse(envelope["subject_binding_performed"])
        self.assertFalse(envelope["geographic_binding_performed"])
        self.assertFalse(envelope["publication_eligible"])
        self.assertIn("fixture_macro_gdp", envelope["route"]["candidate_sources"])
        for label in ("IMPLEMENTED", "QUALIFIED", "LIVE_SUPPORTED"):
            self.assertNotIn(label, json.dumps(envelope))

    def test_delegation_spy(self):
        calls = []
        sentinel = {"claim_kind": "macro_indicator", "sentinel": True}

        def spy(registry, claim_kind, policy, *, runtime_only=True, federation_policy=None, capability_facts=None):
            calls.append(
                {
                    "registry": registry,
                    "claim_kind": claim_kind,
                    "policy": policy,
                    "runtime_only": runtime_only,
                    "federation_policy": federation_policy,
                }
            )
            return sentinel

        original = mod.route_claim
        mod.route_claim = spy
        try:
            envelope = route_declared_candidates(
                self.registry_with_macro,
                self.taxonomy,
                self.claim_policy,
                self.federation_policy,
                claim_class="MACRO",
                profile="statistical-series-v1",
            )
        finally:
            mod.route_claim = original
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0]["registry"], self.registry_with_macro)
        self.assertEqual(calls[0]["claim_kind"], "macro_indicator")
        self.assertIs(calls[0]["policy"], self.claim_policy)
        self.assertTrue(calls[0]["runtime_only"])
        self.assertIs(calls[0]["federation_policy"], self.federation_policy)
        self.assertIs(envelope["route"], sentinel)

    # ------------------------------------------------------------------
    # Actual CLI: default success + owned fixtures.
    # ------------------------------------------------------------------
    def test_default_cli_success(self):
        result = self._run_cli(
            ["--claim-class", "MACRO", "--profile", "statistical-series-v1"]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["stage"], "CANDIDATES_ONLY")
        self.assertEqual(envelope["claim_class"], "MACRO")
        self.assertEqual(envelope["profile"], "statistical-series-v1")
        self.assertEqual(envelope["mapped_family"], "macro_indicator")
        self.assertTrue(envelope["route_performed"])
        self.assertFalse(envelope["publication_eligible"])

    def test_cli_owned_fixture_positive(self):
        fixture_dir = self._build_fixture_dir([self._macro_fixture("fixture_macro_gdp")])
        result = self._run_cli(
            [
                "--claim-class",
                "MACRO",
                "--profile",
                "statistical-series-v1",
                "--catalog-dir",
                str(fixture_dir),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertIn("fixture_macro_gdp", envelope["route"]["candidate_sources"])

    def test_cli_owned_fixture_negative_wrong_profile(self):
        fixture_dir = self._build_fixture_dir([self._macro_fixture("fixture_macro_gdp")])
        result = self._run_cli(
            [
                "--claim-class",
                "MACRO",
                "--profile",
                "wrong-profile",
                "--catalog-dir",
                str(fixture_dir),
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("declared-candidates: invalid input", result.stderr)

    def test_cli_owned_fixture_negative_wrong_claim(self):
        fixture_dir = self._build_fixture_dir([self._macro_fixture("fixture_macro_gdp")])
        result = self._run_cli(
            [
                "--claim-class",
                "WRONG",
                "--profile",
                "statistical-series-v1",
                "--catalog-dir",
                str(fixture_dir),
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("declared-candidates: invalid input", result.stderr)

    # ------------------------------------------------------------------
    # Direct helper: unknown/missing pair, undeclared MACRO, ceiling,
    # malformed config.
    # ------------------------------------------------------------------
    def test_unknown_pair_wrong_claim(self):
        with self.assertRaises(DeclaredCandidatesError):
            route_declared_candidates(
                self.registry_with_macro,
                self.taxonomy,
                self.claim_policy,
                self.federation_policy,
                claim_class="WRONG",
                profile="statistical-series-v1",
            )

    def test_unknown_pair_wrong_profile(self):
        with self.assertRaises(DeclaredCandidatesError):
            route_declared_candidates(
                self.registry_with_macro,
                self.taxonomy,
                self.claim_policy,
                self.federation_policy,
                claim_class="MACRO",
                profile="wrong-profile",
            )

    def test_undeclared_macro(self):
        taxonomy = copy.deepcopy(self.taxonomy)
        taxonomy["claim_classes"] = [c for c in taxonomy["claim_classes"] if c != "MACRO"]
        with self.assertRaises(DeclaredCandidatesError):
            route_declared_candidates(
                self.registry_with_macro,
                taxonomy,
                self.claim_policy,
                self.federation_policy,
                claim_class="MACRO",
                profile="statistical-series-v1",
            )

    def test_missing_ceiling(self):
        federation_policy = copy.deepcopy(self.federation_policy)
        federation_policy["activation_gate"] = {}
        with self.assertRaises(DeclaredCandidatesError):
            route_declared_candidates(
                self.registry_with_macro,
                self.taxonomy,
                self.claim_policy,
                federation_policy,
                claim_class="MACRO",
                profile="statistical-series-v1",
            )

    def test_invalid_ceiling(self):
        federation_policy = copy.deepcopy(self.federation_policy)
        federation_policy["activation_gate"] = {
            "federation_snapshot_max_age_seconds": 0
        }
        with self.assertRaises(DeclaredCandidatesError):
            route_declared_candidates(
                self.registry_with_macro,
                self.taxonomy,
                self.claim_policy,
                federation_policy,
                claim_class="MACRO",
                profile="statistical-series-v1",
            )

    def test_malformed_taxonomy(self):
        with self.assertRaises(TaxonomyInventoryError):
            route_declared_candidates(
                self.registry_with_macro,
                "not a mapping",
                self.claim_policy,
                self.federation_policy,
                claim_class="MACRO",
                profile="statistical-series-v1",
            )

    # ------------------------------------------------------------------
    # Preserved route metadata + empty routes.
    # ------------------------------------------------------------------
    def test_preserved_route_metadata(self):
        envelope = route_declared_candidates(
            self.registry_with_macro,
            self.taxonomy,
            self.claim_policy,
            self.federation_policy,
            claim_class="MACRO",
            profile="statistical-series-v1",
        )
        direct = route_claim(
            self.registry_with_macro,
            "macro_indicator",
            self.claim_policy,
            runtime_only=True,
            federation_policy=self.federation_policy,
        )
        self.assertEqual(envelope["route"], direct)
        self.assertEqual(
            envelope["route"]["freshness_requirement"], direct["freshness_requirement"]
        )
        self.assertEqual(envelope["route"]["minimum_lineages"], direct["minimum_lineages"])
        self.assertEqual(envelope["route"]["fallback_chain"], direct["fallback_chain"])
        self.assertIn("unavailable_diagnostics", envelope["route"]["fallback_chain"])

    def test_empty_route(self):
        envelope = route_declared_candidates(
            self.registry_empty,
            self.taxonomy,
            self.claim_policy,
            self.federation_policy,
            claim_class="MACRO",
            profile="statistical-series-v1",
        )
        self.assertEqual(envelope["route"]["candidate_sources"], [])
        self.assertEqual(envelope["route"]["fallback_chain"]["source_ids"], [])
        self.assertEqual(envelope["route"]["fallback_chain"]["unavailable_diagnostics"], {})

    # ------------------------------------------------------------------
    # Original inputs unchanged.
    # ------------------------------------------------------------------
    def test_original_inputs_unchanged(self):
        registry_before = copy.deepcopy(self.registry_with_macro)
        taxonomy_before = copy.deepcopy(self.taxonomy)
        claim_policy_before = copy.deepcopy(self.claim_policy)
        federation_policy_before = copy.deepcopy(self.federation_policy)
        route_declared_candidates(
            self.registry_with_macro,
            self.taxonomy,
            self.claim_policy,
            self.federation_policy,
            claim_class="MACRO",
            profile="statistical-series-v1",
        )
        self.assertEqual(self.registry_with_macro, registry_before)
        self.assertEqual(self.taxonomy, taxonomy_before)
        self.assertEqual(self.claim_policy, claim_policy_before)
        self.assertEqual(self.federation_policy, federation_policy_before)

    # ------------------------------------------------------------------
    # Legacy behaviour preserved.
    # ------------------------------------------------------------------
    def test_legacy_route_claim_macro_rejects(self):
        with self.assertRaises(SourceRegistryError):
            route_claim(
                self.registry_with_macro,
                "MACRO",
                self.claim_policy,
                runtime_only=True,
                federation_policy=self.federation_policy,
            )

    def test_inventory_counts(self):
        report = inventory(self.taxonomy, self.claim_policy)
        self.assertEqual(report["declared_claim_count"], 23)
        self.assertEqual(report["legacy_family_count"], 10)
        self.assertEqual(report["exact_id_matches"], [])

    # ------------------------------------------------------------------
    # Private-safe CLI argument/path failures.
    # ------------------------------------------------------------------
    def test_cli_unknown_arg_private_safe(self):
        result = self._run_cli(
            [
                "--claim-class",
                "MACRO",
                "--profile",
                "statistical-series-v1",
                "--bogus",
                "secret-value",
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("declared-candidates: invalid input", result.stderr)
        self.assertNotIn("secret-value", result.stderr)
        self.assertNotIn("--bogus", result.stderr)

    def test_cli_missing_required_arg(self):
        result = self._run_cli(["--claim-class", "MACRO"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("declared-candidates: invalid input", result.stderr)

    def test_cli_missing_path(self):
        result = self._run_cli(
            [
                "--claim-class",
                "MACRO",
                "--profile",
                "statistical-series-v1",
                "--catalog-dir",
                str(Path(self._tmp.name) / "nonexistent"),
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("declared-candidates: invalid input", result.stderr)

    def test_cli_malformed_config(self):
        bad_taxonomy = Path(self._tmp.name) / "bad-taxonomy.json"
        bad_taxonomy.write_text("{not valid json", encoding="utf-8")
        result = self._run_cli(
            [
                "--claim-class",
                "MACRO",
                "--profile",
                "statistical-series-v1",
                "--taxonomy",
                str(bad_taxonomy),
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("declared-candidates: invalid input", result.stderr)


if __name__ == "__main__":
    unittest.main()