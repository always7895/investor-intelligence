from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v212_source_diversity_audit import audit, validate  # noqa: E402


class V212SourceDiversityAuditTests(unittest.TestCase):
    def test_catalog_is_broad_but_not_misrepresented_as_live(self) -> None:
        summary = audit()
        validate(summary, strict_live=False)
        catalog = summary["catalog"]
        self.assertGreaterEqual(catalog["source_count"], 90)
        self.assertGreaterEqual(catalog["region_count"], 5)
        self.assertGreaterEqual(catalog["host_group_count"], 20)
        self.assertTrue(catalog["source_count_is_not_activation_claim"])

    def test_current_live_source_families_are_reported_separately(self) -> None:
        summary = audit()
        live = summary["production_live"]
        self.assertIn("sec_edgar", live["source_families"])
        self.assertIn("world_bank_indicators", live["source_families"])
        self.assertIn("yahoo_finance_public_unofficial", live["source_families"])
        self.assertGreaterEqual(live["source_family_count"], 3)

    def test_extra_sources_do_not_silently_change_serenity(self) -> None:
        summary = audit()
        target = summary["v212_open_qa_target"]
        self.assertTrue(target["serenity_score_unchanged_by_unmapped_sources"])
        self.assertGreaterEqual(target["minimum_successful_source_families"], 3)


if __name__ == "__main__":
    unittest.main()
