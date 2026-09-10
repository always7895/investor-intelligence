from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from authoritative_source_catalog import (  # noqa: E402
    CatalogError,
    SourceRecord,
    inventory,
    load_catalog,
    plan_source_run,
    validate_runtime_activation,
)


class AuthoritativeSourceCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest_path = ROOT / "config" / "authoritative-source-catalog.json"
        cls.manifest, cls.sources, cls.warnings = load_catalog(cls.manifest_path)

    def copied_catalog(self) -> tuple[Path, Path]:
        root = Path(tempfile.mkdtemp(dir=self.temp.name))
        (root / "config" / "authoritative-sources").mkdir(parents=True)
        shutil.copy2(self.manifest_path, root / "config" / self.manifest_path.name)
        for source in (ROOT / "config" / "authoritative-sources").glob("*.json"):
            shutil.copy2(source, root / "config" / "authoritative-sources" / source.name)
        return root, root / "config" / self.manifest_path.name

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_catalog_is_large_diverse_unbounded_and_disabled(self) -> None:
        values = inventory(self.sources)
        self.assertEqual(values["source_count"], 101)
        self.assertEqual(values["runtime_enabled_count"], 0)
        self.assertTrue(self.manifest["catalog_policy"]["no_fixed_source_count_limit"])
        self.assertTrue(self.manifest["catalog_source_count_snapshot_is_not_a_limit"])
        self.assertEqual(self.manifest["catalog_source_count_snapshot"], 101)
        self.assertEqual(self.warnings, [])
        self.assertGreaterEqual(values["region_counts"]["ASIA_PACIFIC"], 30)
        self.assertGreaterEqual(values["region_counts"]["AMERICAS"], 25)
        self.assertGreaterEqual(values["region_counts"]["EUROPE"], 15)
        self.assertGreaterEqual(values["region_counts"]["GLOBAL"], 15)
        self.assertGreaterEqual(values["region_counts"]["MIDDLE_EAST_AFRICA"], 8)
        for topic in (
            "company_filings",
            "macro",
            "banking",
            "trade",
            "energy",
            "options",
            "patents",
            "telecommunications",
            "cybersecurity",
            "health",
        ):
            self.assertGreater(values["topic_counts"].get(topic, 0), 0, topic)

    def test_catalog_membership_never_implies_activation(self) -> None:
        self.assertTrue(all(source.cost == "free" for source in self.sources))
        self.assertTrue(all(source.data_class == "public" for source in self.sources))
        self.assertTrue(all(source.runtime_enabled is False for source in self.sources))
        self.assertTrue(all(source.rights_status == "review_before_enable" for source in self.sources))
        for source_id in (
            "sec_edgar",
            "world_bank_indicators",
            "gleif_lei",
            "ecb_sdmx",
        ):
            source = next(item for item in self.sources if item.id == source_id)
            self.assertEqual(source.adapter_status, "adapter_replay_required")
            self.assertIsNotNone(source.adapter_id)

    def test_market_option_candidates_are_not_authoritative_or_enabled(self) -> None:
        for source_id in (
            "yahoo_finance_public_unofficial",
            "cboe_public_market_data",
            "nasdaq_public_options",
        ):
            source = next(item for item in self.sources if item.id == source_id)
            self.assertFalse(source.runtime_enabled)
            self.assertEqual(source.adapter_status, "metadata_only")
            self.assertEqual(source.evidence_role, "public_market_observation")

    def test_public_broker_and_media_candidates_remain_discovery_only(self) -> None:
        manifest, expanded, warnings = load_catalog(ROOT / 'config/authoritative-source-catalog.research-candidate.json')
        self.assertEqual(len(expanded), 116)
        self.assertEqual(manifest['catalog_source_count_snapshot'], 116)
        self.assertEqual(warnings, [])
        # The candidate uses the SAME loader, gates and original source rows;
        # it must not alter the reviewed plan or shadow existing definitions.
        originals = {source.id: source for source in self.sources}
        self.assertEqual({source.id: source for source in expanded if source.id in originals}, originals)
        for key in ('catalog_policy', 'runtime_defaults', 'member_columns', 'source_defaults'):
            self.assertEqual(manifest[key], self.manifest[key])
        self.assertEqual(manifest['fragment_paths'][:-1], self.manifest['fragment_paths'])
        candidates = [source for source in expanded if source.id.endswith('_public_research')]
        self.assertEqual(len(candidates), 15)
        for source in candidates:
            with self.subTest(source=source.id):
                self.assertEqual(source.evidence_tier, 'T3')
                self.assertEqual(source.evidence_role, 'discovery_only')
                self.assertEqual(source.adapter_status, 'metadata_only')
                self.assertIsNone(source.adapter_id)
                self.assertIsNone(source.credential_env)
                self.assertFalse(source.runtime_enabled)
                self.assertFalse(source.gates['rights_reviewed'])
                self.assertFalse(source.gates['free_access_verified'])
                self.assertEqual(source.redistribution_status, 'review_before_enable')
                with self.assertRaises(CatalogError):
                    validate_runtime_activation(replace(source, runtime_enabled=True), credentials={})

    def test_unknown_manifest_or_fragment_fields_fail_closed(self) -> None:
        _root, manifest_path = self.copied_catalog()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["surprise"] = True
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(CatalogError):
            load_catalog(manifest_path)

        root, manifest_path = self.copied_catalog()
        fragment_path = root / "config" / "authoritative-sources" / "global.json"
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
        fragment["auto_enable"] = True
        fragment_path.write_text(json.dumps(fragment), encoding="utf-8")
        with self.assertRaises(CatalogError):
            load_catalog(manifest_path)

    def test_duplicate_source_id_and_unsafe_url_are_rejected(self) -> None:
        root, manifest_path = self.copied_catalog()
        fragment_path = root / "config" / "authoritative-sources" / "global.json"
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
        fragment["members"].append(copy.deepcopy(fragment["members"][0]))
        fragment_path.write_text(json.dumps(fragment), encoding="utf-8")
        with self.assertRaisesRegex(CatalogError, "duplicate source id"):
            load_catalog(manifest_path)

        root, manifest_path = self.copied_catalog()
        fragment_path = root / "config" / "authoritative-sources" / "global.json"
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
        base_url_index = self.manifest["member_columns"].index("base_urls")
        host_index = self.manifest["member_columns"].index("host_group")
        fragment["members"][0][base_url_index] = ["https://127.0.0.1/private"]
        fragment["members"][0][host_index] = "127.0.0.1"
        fragment_path.write_text(json.dumps(fragment), encoding="utf-8")
        with self.assertRaisesRegex(CatalogError, "non-public IP"):
            load_catalog(manifest_path)

    def test_free_credential_metadata_is_consistent(self) -> None:
        for source in self.sources:
            if source.authentication == "none":
                self.assertIsNone(source.credential_env)
            else:
                self.assertIsNotNone(source.credential_env)
                self.assertIn(source.rate_limit["policy"], {"free_key_plan", "documented"})

    def test_activation_requires_all_gates_rights_adapter_and_free_credential(self) -> None:
        base = next(source for source in self.sources if source.id == "sec_edgar")
        enabled = replace(
            base,
            runtime_enabled=True,
            rights_status="reviewed_public_access",
            redistribution_status="public_attribution",
            adapter_status="adapter_reviewed",
            gates={key: True for key in base.gates},
        )
        self.assertEqual(validate_runtime_activation(enabled, credentials={}), (True, "ELIGIBLE"))

        for gate in enabled.gates:
            broken_gates = dict(enabled.gates)
            broken_gates[gate] = False
            with self.subTest(gate=gate), self.assertRaises(CatalogError):
                validate_runtime_activation(replace(enabled, gates=broken_gates), credentials={})

        key_source = next(source for source in self.sources if source.id == "fred_alfred")
        key_enabled = replace(
            key_source,
            runtime_enabled=True,
            rights_status="reviewed_public_access",
            redistribution_status="public_attribution",
            adapter_id="synthetic_reviewed_adapter",
            adapter_status="adapter_reviewed",
            gates={key: True for key in key_source.gates},
        )
        self.assertEqual(
            validate_runtime_activation(key_enabled, credentials={}),
            (False, "FREE_CREDENTIAL_UNAVAILABLE"),
        )
        self.assertEqual(
            validate_runtime_activation(
                key_enabled,
                credentials={key_enabled.credential_env or "": "synthetic-free-token"},
            ),
            (True, "ELIGIBLE"),
        )

    @staticmethod
    def runtime_source(index: int, host: str | None = None) -> SourceRecord:
        host = host or f"source-{index}.example.test"
        return SourceRecord(
            id=f"synthetic_{index:03d}",
            display_name=f"Synthetic source {index}",
            authority=f"Synthetic authority {index}",
            evidence_tier="T1",
            evidence_role="official_statistical",
            regions=("GLOBAL",),
            jurisdictions=("GLOBAL",),
            topics=("macro",),
            claim_types=("official_indicator_value",),
            official_docs_url=f"https://{host}/docs",
            base_urls=(f"https://{host}/api",),
            transport="rest_json",
            authentication="none",
            credential_env=None,
            cost="free",
            rights_status="reviewed_public_access",
            redistribution_status="public_attribution",
            attribution_required=True,
            data_class="public",
            adapter_id="synthetic_reviewed_adapter",
            adapter_status="adapter_reviewed",
            runtime_enabled=True,
            host_group=host,
            freshness_class="daily",
            update_cadence_seconds=86400,
            max_requests_per_run=10,
            estimated_requests_per_cycle=1,
            estimated_response_bytes_per_cycle=1000,
            estimated_wall_seconds_per_cycle=1.0,
            rate_limit={
                "policy": "official_unspecified",
                "requests_per_minute": None,
                "requests_per_day": None,
            },
            gates={
                "authority_reviewed": True,
                "rights_reviewed": True,
                "free_access_verified": True,
                "schema_reviewed": True,
                "privacy_reviewed": True,
                "adapter_tests_passed": True,
                "runtime_health_passed": True,
            },
            notes="Synthetic fixture only.",
        )

    def test_planner_has_no_source_count_cap_but_obeys_runtime_budgets(self) -> None:
        sources = [self.runtime_source(index) for index in range(300)]
        health = {source.id: "HEALTHY" for source in sources}
        budgets = {
            **self.manifest["runtime_defaults"],
            "max_total_requests": 37,
            "max_total_response_bytes": 1_000_000,
            "max_wall_seconds": 1000,
            "max_requests_per_host": 10,
        }
        plan = plan_source_run(
            sources,
            budgets,
            requested_topics=["macro"],
            health=health,
            credentials={},
        )
        self.assertIsNone(plan.source_count_cap)
        self.assertEqual(plan.catalog_count, 300)
        self.assertEqual(plan.runtime_enabled_count, 300)
        self.assertEqual(plan.eligible_count, 300)
        self.assertEqual(len(plan.selected), 37)
        self.assertEqual(plan.planned_requests, 37)
        self.assertEqual(
            sum(item["reason"] == "RUNTIME_BUDGET_DEFERRED" for item in plan.deferred),
            263,
        )

    def test_per_host_budget_prevents_one_provider_family_from_starving_run(self) -> None:
        sources = [self.runtime_source(index, host="shared.example.test") for index in range(20)]
        health = {source.id: "HEALTHY" for source in sources}
        budgets = {
            **self.manifest["runtime_defaults"],
            "max_total_requests": 100,
            "max_requests_per_host": 5,
        }
        plan = plan_source_run(sources, budgets, health=health, credentials={})
        self.assertEqual(len(plan.selected), 5)
        self.assertEqual(plan.host_request_totals["shared.example.test"], 5)
        self.assertEqual(
            sum("per_host_requests" in item.get("budgets", []) for item in plan.deferred),
            15,
        )


if __name__ == "__main__":
    unittest.main()
