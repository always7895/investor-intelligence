#!/usr/bin/env python3
"""Tests for the declared claim taxonomy inventory.

These tests exercise the pure ``inventory`` function and the thin offline CLI. They use only
in-memory fixtures, the two repository config files, and writer-owned temporary files. They
perform no network access, read no real settings, and touch no Production files.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
CONFIG_DIR = REPO_ROOT / "config"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import source_claim_taxonomy_inventory as inventory_module

TAXONOMY_PATH = CONFIG_DIR / "source-claim-taxonomy.json"
POLICY_PATH = CONFIG_DIR / "source-claim-coverage-policy.json"
SCRIPT_PATH = SCRIPTS_DIR / "source_claim_taxonomy_inventory.py"
PRIVATE_ERROR = "taxonomy-inventory: invalid input"

# The 23 declared claim classes in original order (the roadmap explicit list).
DECLARED_IDS = [
    "FILING_FACT", "ACCOUNTING_FACT", "GUIDANCE", "MANAGEMENT_STATEMENT",
    "CORPORATE_ACTION", "PRICE", "VOLUME", "OPTIONS_REFERENCE",
    "OPTIONS_MARKET_ACTIVITY", "SHORT_INTEREST", "INSIDER_ACTIVITY",
    "INSTITUTIONAL_HOLDING", "MACRO", "RATES", "FX", "ENERGY", "COMMODITY",
    "ECONOMIC_ACTIVITY", "REGULATORY_EVENT", "CREDIT_RATING", "NEWS_EVENT",
    "ANALYST_COMMENTARY", "INDUSTRY_DATA",
]

# The 10 live claim families (the coverage policy claim_families keys, in file order).
LEGACY_IDS = [
    "issuer_identity", "issuer_financial_statement", "issuer_guidance_or_contract",
    "macro_indicator", "monetary_policy", "regulatory_or_enforcement_event",
    "market_or_exchange_event", "public_option_quote", "technology_patent_or_grant",
    "energy_grid_or_climate",
]


def load_repo_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
    )


class InventoryPureCurrentTest(unittest.TestCase):
    def test_current_23_10_0_23_false(self):
        taxonomy = load_repo_json(TAXONOMY_PATH)
        policy = load_repo_json(POLICY_PATH)
        result = inventory_module.inventory(taxonomy, policy)
        self.assertEqual(result["declared_claim_count"], 23)
        self.assertEqual(result["declared_claim_ids"], DECLARED_IDS)
        self.assertEqual(result["legacy_family_count"], 10)
        self.assertEqual(result["legacy_family_ids"], LEGACY_IDS)
        self.assertEqual(result["exact_id_matches"], [])
        self.assertEqual(result["unmapped_claim_ids"], DECLARED_IDS)
        self.assertIs(result["publication_eligible"], False)


class InventoryFixtureIntersectionTest(unittest.TestCase):
    def test_exact_id_intersection_positive(self):
        # A declared class that exactly equals a live family id is an exact match.
        # This is a set-intersection check only; it is NOT a routing/qualification claim.
        taxonomy = {"schema_version": 1, "claim_classes": ["issuer_identity", "FILING_FACT"]}
        policy = {"claim_families": {"issuer_identity": {}, "macro_indicator": {}}}
        result = inventory_module.inventory(taxonomy, policy)
        self.assertEqual(result["declared_claim_count"], 2)
        self.assertEqual(result["legacy_family_count"], 2)
        self.assertEqual(result["exact_id_matches"], ["issuer_identity"])
        self.assertEqual(result["unmapped_claim_ids"], ["FILING_FACT"])
        self.assertIs(result["publication_eligible"], False)

    def test_uppercase_not_mapped_to_similar_family(self):
        # MACRO (declared) is semantically similar to macro_indicator (live) but must NOT
        # be mapped; only exact case-sensitive identifier equality counts.
        taxonomy = {"schema_version": 1, "claim_classes": ["MACRO"]}
        policy = {"claim_families": {"macro_indicator": {}}}
        result = inventory_module.inventory(taxonomy, policy)
        self.assertEqual(result["exact_id_matches"], [])
        self.assertEqual(result["unmapped_claim_ids"], ["MACRO"])


class InventoryMalformedTest(unittest.TestCase):
    def assert_rejects(self, taxonomy, policy):
        with self.assertRaises(inventory_module.TaxonomyInventoryError):
            inventory_module.inventory(taxonomy, policy)

    def test_taxonomy_not_object(self):
        self.assert_rejects([1, 2], {"claim_families": {}})

    def test_taxonomy_unknown_key(self):
        self.assert_rejects(
            {"schema_version": 1, "claim_classes": [], "extra": 1},
            {"claim_families": {}},
        )

    def test_taxonomy_missing_key(self):
        self.assert_rejects({"schema_version": 1}, {"claim_families": {}})

    def test_schema_version_bool(self):
        self.assert_rejects(
            {"schema_version": True, "claim_classes": []},
            {"claim_families": {}},
        )

    def test_schema_version_wrong(self):
        self.assert_rejects(
            {"schema_version": 2, "claim_classes": []},
            {"claim_families": {}},
        )

    def test_claim_classes_string(self):
        self.assert_rejects(
            {"schema_version": 1, "claim_classes": "FILING_FACT"},
            {"claim_families": {}},
        )

    def test_claim_classes_object(self):
        self.assert_rejects(
            {"schema_version": 1, "claim_classes": {"a": 1}},
            {"claim_families": {}},
        )

    def test_claim_class_not_string(self):
        self.assert_rejects(
            {"schema_version": 1, "claim_classes": [1]},
            {"claim_families": {}},
        )

    def test_claim_class_invalid_identifier(self):
        for bad in ["1ABC", "ABC DEF", "", "ABC-DEF", "_ABC"]:
            self.assert_rejects(
                {"schema_version": 1, "claim_classes": [bad]},
                {"claim_families": {}},
            )

    def test_duplicate_claim_class(self):
        self.assert_rejects(
            {"schema_version": 1, "claim_classes": ["MACRO", "MACRO"]},
            {"claim_families": {}},
        )

    def test_policy_not_object(self):
        self.assert_rejects({"schema_version": 1, "claim_classes": []}, [1])

    def test_policy_missing_claim_families(self):
        self.assert_rejects({"schema_version": 1, "claim_classes": []}, {})

    def test_claim_families_not_object(self):
        self.assert_rejects(
            {"schema_version": 1, "claim_classes": []},
            {"claim_families": [1]},
        )

    def test_claim_family_invalid_identifier(self):
        self.assert_rejects(
            {"schema_version": 1, "claim_classes": []},
            {"claim_families": {"bad family": {}}},
        )


class InventoryCliDefaultTest(unittest.TestCase):
    def test_cli_default_files(self):
        proc = run_cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["declared_claim_count"], 23)
        self.assertEqual(result["legacy_family_count"], 10)
        self.assertEqual(result["exact_id_matches"], [])
        self.assertEqual(result["unmapped_claim_ids"], DECLARED_IDS)
        self.assertIs(result["publication_eligible"], False)


class InventoryCliFixtureTest(unittest.TestCase):
    def _write(self, directory, name, text):
        path = Path(directory) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_cli_valid_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            taxonomy = self._write(
                directory, "taxonomy.json",
                json.dumps({"schema_version": 1, "claim_classes": ["MACRO", "FX"]}),
            )
            policy = self._write(
                directory, "policy.json",
                json.dumps({"claim_families": {"macro_indicator": {}, "fx": {}}}),
            )
            proc = run_cli("--taxonomy", str(taxonomy), "--policy", str(policy))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["declared_claim_count"], 2)
            self.assertEqual(result["legacy_family_count"], 2)
            self.assertEqual(result["exact_id_matches"], [])
            self.assertEqual(result["unmapped_claim_ids"], ["MACRO", "FX"])

    def test_cli_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            taxonomy = self._write(directory, "taxonomy.json", "{not valid json")
            policy = self._write(
                directory, "policy.json",
                json.dumps({"claim_families": {}}),
            )
            proc = run_cli("--taxonomy", str(taxonomy), "--policy", str(policy))
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr.strip(), PRIVATE_ERROR)
            self.assertNotIn(str(taxonomy), proc.stderr)

    def test_cli_invalid_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            taxonomy = self._write(
                directory, "taxonomy.json",
                json.dumps({"schema_version": 1, "claim_classes": ["BAD VALUE"]}),
            )
            policy = self._write(
                directory, "policy.json",
                json.dumps({"claim_families": {}}),
            )
            proc = run_cli("--taxonomy", str(taxonomy), "--policy", str(policy))
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr.strip(), PRIVATE_ERROR)
            self.assertNotIn("BAD VALUE", proc.stderr)
            self.assertNotIn(str(taxonomy), proc.stderr)

    def test_cli_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            taxonomy = self._write(
                directory, "taxonomy.json",
                '{"schema_version": 1, "schema_version": 2, "claim_classes": []}',
            )
            policy = self._write(
                directory, "policy.json",
                json.dumps({"claim_families": {}}),
            )
            proc = run_cli("--taxonomy", str(taxonomy), "--policy", str(policy))
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr.strip(), PRIVATE_ERROR)

    def test_cli_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "does_not_exist.json"
            policy = self._write(
                directory, "policy.json",
                json.dumps({"claim_families": {}}),
            )
            proc = run_cli("--taxonomy", str(missing), "--policy", str(policy))
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr.strip(), PRIVATE_ERROR)
            self.assertNotIn(str(missing), proc.stderr)


class SchemaValidationRegressions(unittest.TestCase):
    def _write(self, directory, name, text):
        path = Path(directory) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_api_rejects_float_schema_version(self):
        with self.assertRaises(inventory_module.TaxonomyInventoryError):
            inventory_module.inventory(
                {"schema_version": 1.0, "claim_classes": []},
                {"claim_families": {}},
            )

    def test_api_rejects_newline_in_claim_class(self):
        with self.assertRaises(inventory_module.TaxonomyInventoryError):
            inventory_module.inventory(
                {"schema_version": 1, "claim_classes": ["MACRO\n"]},
                {"claim_families": {}},
            )

    def test_api_rejects_newline_in_claim_family(self):
        with self.assertRaises(inventory_module.TaxonomyInventoryError):
            inventory_module.inventory(
                {"schema_version": 1, "claim_classes": []},
                {"claim_families": {"macro_indicator\n": {}}},
            )

    def test_api_rejects_tuple_claim_classes(self):
        with self.assertRaises(inventory_module.TaxonomyInventoryError):
            inventory_module.inventory(
                {"schema_version": 1, "claim_classes": ("MACRO",)},
                {"claim_families": {}},
            )

    def test_cli_rejects_float_schema_version(self):
        with tempfile.TemporaryDirectory() as directory:
            taxonomy = self._write(
                directory, "taxonomy.json",
                json.dumps({"schema_version": 1.0, "claim_classes": []}),
            )
            policy = self._write(
                directory, "policy.json",
                json.dumps({"claim_families": {}}),
            )
            proc = run_cli("--taxonomy", str(taxonomy), "--policy", str(policy))
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr.strip(), PRIVATE_ERROR)

    def test_cli_rejects_newline_in_claim_class(self):
        with tempfile.TemporaryDirectory() as directory:
            taxonomy = self._write(
                directory, "taxonomy.json",
                json.dumps({"schema_version": 1, "claim_classes": ["MACRO\n"]}),
            )
            policy = self._write(
                directory, "policy.json",
                json.dumps({"claim_families": {}}),
            )
            proc = run_cli("--taxonomy", str(taxonomy), "--policy", str(policy))
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr.strip(), PRIVATE_ERROR)

    def test_cli_rejects_newline_in_claim_family(self):
        with tempfile.TemporaryDirectory() as directory:
            taxonomy = self._write(
                directory, "taxonomy.json",
                json.dumps({"schema_version": 1, "claim_classes": []}),
            )
            policy = self._write(
                directory, "policy.json",
                json.dumps({"claim_families": {"macro_indicator\n": {}}}),
            )
            proc = run_cli("--taxonomy", str(taxonomy), "--policy", str(policy))
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr.strip(), PRIVATE_ERROR)


if __name__ == "__main__":
    unittest.main()