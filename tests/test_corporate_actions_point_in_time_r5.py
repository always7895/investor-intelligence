"""Round 5: historical corporate-action cutoff with strict validation."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from corporate_actions import load_actions_bytes, pending_targets, public_notes
from tests.test_corporate_actions_gap_a import seed
from tests.test_corporate_distributions_gap_c import distribution


def registry(*rows):
    return json.dumps({"schema_version": 1, "entries": list(rows)}).encode("utf-8")


class CorporateActionsPointInTimeR5(unittest.TestCase):
    def test_real_installed_lite_is_unknown_before_source_date_and_known_on_and_after(self):
        raw = (ROOT / "config/corporate-actions-v1.json").read_bytes()
        for day, visible in ((date(2026, 11, 1), False),
                             (date(2026, 11, 2), True),
                             (date(2026, 11, 3), True)):
            with self.subTest(day=day):
                doc = load_actions_bytes(raw, today=day)
                self.assertEqual("LITE" in pending_targets(doc), visible)
                self.assertEqual("LITE" in public_notes(doc, asof=day), visible)
                self.assertEqual("MRVL" in public_notes(doc, asof=day), visible)
                self.assertTrue(all(e["source_date"] <= day.isoformat() for e in doc["entries"]))

    def test_distribution_source_cutoff_before_on_after(self):
        event = distribution()
        event["source_date"] = "2026-11-08"
        for day, visible in ((date(2026, 11, 7), False),
                             (date(2026, 11, 8), True),
                             (date(2026, 11, 9), True)):
            with self.subTest(day=day):
                doc = load_actions_bytes(registry(event), today=day)
                self.assertEqual(len(doc["entries"]), int(visible))
                self.assertEqual(bool(public_notes(doc, asof=day)), visible)

    def test_future_entitlement_approval_hides_only_that_distribution(self):
        event = distribution()
        event["entitlement_receipts"] = [{
            "evidence_sha256": "a" * 64,
            "approved_on": "2026-11-12",
            "rights_scope": "PUBLIC_DERIVED_RETURN",
            "primary_documents": [
                {"source_url": f"https://www.sec.gov/Archives/edgar/data/67347/000110465926112870/doc{i}.htm",
                 "sha256": f"{i}" * 64} for i in range(4)
            ],
        }]
        original = seed()["entries"][0]
        for day, count in ((date(2026, 11, 11), 1),
                           (date(2026, 11, 12), 2),
                           (date(2026, 11, 13), 2)):
            with self.subTest(day=day):
                self.assertEqual(len(load_actions_bytes(registry(event, original), today=day)["entries"]), count)

    def test_future_evidence_does_not_hide_malformed_data(self):
        merger = seed()["entries"][0]
        bad = copy.deepcopy(merger)
        bad["exchange_ratio"] = 0
        with self.assertRaisesRegex(ValueError, "CORPORATE_ACTION_RATIO"):
            load_actions_bytes(registry(bad), today=date(2026, 10, 7))
        dist = distribution()
        dist["source_date"] = "2026-11-08"
        dist["shares_per_share"] = -1
        with self.assertRaisesRegex(ValueError, "CORPORATE_ACTION_DISTRIBUTION_RATIO"):
            load_actions_bytes(registry(dist), today=date(2026, 11, 7))
        bad = copy.deepcopy(merger)
        bad["status_on"] = "2026-11-05"
        bad["source_date"] = "2026-11-03"
        with self.assertRaisesRegex(ValueError, "CORPORATE_ACTION_CHRONOLOGY"):
            load_actions_bytes(registry(bad), today=date(2026, 10, 7))


if __name__ == "__main__":
    unittest.main()
