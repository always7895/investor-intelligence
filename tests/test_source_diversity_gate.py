from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_diversity_gate import (  # noqa: E402
    audit_source_diversity,
    load_catalog,
)


class SourceDiversityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog()

    def test_current_catalog_is_broad_independent_and_disabled(self) -> None:
        findings, summary = audit_source_diversity(self.catalog)
        self.assertEqual(findings, [])
        self.assertGreaterEqual(summary["source_count"], 90)
        self.assertGreaterEqual(summary["region_count"], 5)
        self.assertGreaterEqual(summary["jurisdiction_count"], 19)
        self.assertGreaterEqual(summary["topic_count"], 15)
        self.assertGreaterEqual(summary["host_group_count"], 20)
        self.assertEqual(summary["runtime_enabled_count"], 0)
        self.assertIsNone(summary["catalog_source_count_limit"])
        self.assertEqual(
            set(summary["evidence_tiers"]),
            {"T0", "T1", "T2", "T3"},
        )

    def test_catalog_size_is_not_an_activation_signal(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        for source in catalog["sources"]:
            source["runtime_enabled"] = False
        catalog["sources"].extend(
            {
                **copy.deepcopy(catalog["sources"][0]),
                "id": f"synthetic_disabled_{index}",
                "display_name": f"Synthetic disabled source {index}",
                "authority": f"Synthetic authority {index}",
                "host_group": f"synthetic-{index}.example.test",
                "base_urls": [f"https://synthetic-{index}.example.test/api"],
            }
            for index in range(200)
        )
        findings, summary = audit_source_diversity(catalog)
        self.assertEqual(findings, [])
        self.assertGreaterEqual(summary["source_count"], 290)
        self.assertEqual(summary["runtime_enabled_count"], 0)
        self.assertIsNone(summary["catalog_source_count_limit"])

    def test_rejects_enabled_paid_private_or_unsafe_sources(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        source = catalog["sources"][0]
        source["runtime_enabled"] = True
        source["cost"] = "paid"
        source["data_class"] = "tenant_private"
        source["base_urls"] = ["https://user:password@127.0.0.1:8443/private"]
        findings, _summary = audit_source_diversity(catalog)
        self.assertTrue(any("runtime_enabled must remain false" in item for item in findings))
        self.assertTrue(any("cost must be free" in item for item in findings))
        self.assertTrue(any("data_class must be public" in item for item in findings))
        self.assertTrue(any("unsafe base URL" in item for item in findings))

    def test_rejects_duplicate_ids_and_concentrated_catalog(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        seed = copy.deepcopy(catalog["sources"][0])
        concentrated = []
        for index in range(100):
            value = copy.deepcopy(seed)
            value["id"] = "duplicate" if index < 2 else f"concentrated_{index}"
            value["display_name"] = f"Concentrated {index}"
            value["authority"] = "One authority"
            value["host_group"] = "one.example.test"
            value["base_urls"] = ["https://one.example.test/api"]
            concentrated.append(value)
        catalog["sources"] = concentrated
        findings, _summary = audit_source_diversity(catalog)
        self.assertTrue(any("duplicate source id" in item for item in findings))
        self.assertTrue(any("host group" in item for item in findings))
        self.assertTrue(any("authority" in item and "represents" in item for item in findings))
        self.assertTrue(any("regions" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
