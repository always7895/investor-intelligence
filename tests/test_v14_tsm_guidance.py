"""Lane V14 (TSM revenue-guidance registry entry): TSMC's 3Q26 earnings release and its 1Q26 and 3Q26 quarterly management
reports (exact bytes kept in _archive/lane-v14-guidance/sources) give TSM four reported USD quarters and its 4Q26 revenue guidance.

TSMC's IR and press sites answer automated requests with a bot challenge (2026-10-17), so the record names no release channel at
all: the release check never fetches for it, the company-guidance path stays FRESHNESS_UNVERIFIED / IR_COVERAGE_MISSING (Astra W1
ruling: no guidance projection without official IR coverage), and the sealed evidence carries what the Worker's HISTORY_YOY_V1
estimate needs (four reviewed actuals, four forward intervals, the sealed approval, no channel fault)."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import order_forecast as ofc  # noqa: E402
import revenue_guidance as rg  # noqa: E402
import revenue_guidance_release_check as checker  # noqa: E402

REGISTRY_PATH = ROOT / "config" / "revenue-guidance-v1.json"
APPROVAL_PATH = ROOT / "config" / "revenue-guidance-approval-v1.json"
CLAIMS = {"status": "EMPTY", "sha256": "0" * 64, "issuers": {}}
# id -> (sha256 of the public bytes, byte size, published date); the files are in _archive/lane-v14-guidance/sources.
DOCUMENTS = {
    "TSM-3Q26-ER": ("c56119b240c1f7ba728c58228b14cb51d3a756d808af41e7d4b53b46ba29734a", 171803, "2026-10-15"),
    "TSM-3Q26-MR": ("27b5b92d05207bf662756edfbe72494c5f34a007a79306ae040d957886b411d2", 468113, "2026-10-15"),
    "TSM-1Q26-MR": ("4878487acab931ea06635a8bb97cbb9dcf14e2140d4c480667298ca1c43e8bdc", 4653875, "2026-04-16"),
}
# Net revenue in US$ (summary tables of the management reports), oldest first.
ACTUALS = (("4Q25", "2025-10-01", "2025-12-31", 33.73e9, "TSM-1Q26-MR"), ("1Q26", "2026-01-01", "2026-03-31", 35.90e9, "TSM-1Q26-MR"),
           ("2Q26", "2026-04-01", "2026-06-30", 40.20e9, "TSM-3Q26-MR"), ("3Q26", "2026-07-01", "2026-09-30", 46.72e9, "TSM-3Q26-MR"))
INTERVALS = (("2026-10-01", "2026-12-31"), ("2027-01-01", "2027-03-31"), ("2027-04-01", "2027-06-30"), ("2027-07-01", "2027-09-30"))


def utc(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def never(_url):
    raise AssertionError("the release check fetched for a record that names no channel")


class TsmGuidanceRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = rg.parse_registry(REGISTRY_PATH.read_bytes())
        cls.approval = rg.parse_approval(APPROVAL_PATH.read_bytes())
        cls.record = cls.registry["issuers"]["TSM"]
        cls.cutoff = utc(cls.approval["approved_at"]) + timedelta(minutes=30)

    def test_record_validates_and_the_reviewed_profile_binds_it(self):
        self.assertEqual((self.registry["status"], self.approval["status"]), ("OK", "OK"))
        rg.validate_issuer_record(self.record, expected_symbol="TSM")
        self.assertIsNone(rg.check_reviewed_profile("TSM", self.record, self.approval, self.registry["sha256"], self.cutoff))
        kinds = sorted(d["kind"] for d in self.approval["records"]["TSM"]["decisions"])
        self.assertEqual(kinds, ["ACTUAL"] * 4 + ["CALENDAR", "CLAIM", "ROUTING"])

    def test_documents_are_the_archived_issuer_bytes(self):
        docs = {d["id"]: d for d in self.record["documents"]}
        self.assertEqual(set(docs), set(DOCUMENTS))
        for doc_id, (sha, size, published) in DOCUMENTS.items():
            doc = docs[doc_id]
            self.assertEqual((doc["sha256"], doc["byte_size"], doc["published_date"]), (sha, size, published), doc_id)
            self.assertEqual(doc["source_kind"], "ISSUER_EARNINGS_RELEASE", doc_id)
            self.assertTrue(doc["url"].startswith(self.record["url_prefixes"][0]), doc_id)
        self.assertEqual(self.record["url_prefixes"], ["https://investor.tsmc.com/english/"])

    def test_actuals_and_guidance_are_the_published_figures(self):
        quarters = self.record["reported_quarters"]
        self.assertEqual([(q["fiscal_label"], q["start"], q["end"], q["revenue"], q["document_id"]) for q in quarters], list(ACTUALS))
        for q in quarters:
            self.assertEqual((q["currency"], q["scope"], q["accounting_basis"]), ("USD", "COMPANY", "IFRS"), q["fiscal_label"])
        for prev, cur in zip(quarters, quarters[1:]):
            self.assertEqual(date.fromisoformat(cur["start"]), date.fromisoformat(prev["end"]) + timedelta(days=1))
        (claim,) = self.record["claims"]
        self.assertEqual((claim["low"], claim["high"], claim["currency"], claim["period_start"], claim["period_end"]),
                         (52.3e9, 54.3e9, "USD", "2026-10-01", "2026-12-31"))
        self.assertIn("between US$52.3 billion and US$54.3 billion", claim["passage"])
        self.assertEqual([(i["start"], i["end"]) for i in self.record["forward_intervals"]], list(INTERVALS))

    def test_no_release_channel_is_named_so_the_check_never_fetches(self):
        self.assertEqual((self.record["status"], self.record["release_channels"]), ("GUIDANCE", {}))
        self.assertIsNone(checker.receipt_for(self.record, self.cutoff, never, never, never))

    def test_guidance_stays_unavailable_and_the_history_inputs_are_sealed(self):
        cache = rg.parse_release_checks_cache(json.dumps(
            {"schema": checker.SCHEMA, "generated_at": checker.stamp(self.cutoff), "issuers": {}}).encode("utf-8"))
        v3 = ofc.build_v3("TSM", None, None, self.cutoff.date(), self.cutoff, CLAIMS, revenue_registry=self.registry,
                          release_checks_cache=cache, revenue_approval=self.approval)
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_diagnostic"]),
                         ("UNAVAILABLE", "FRESHNESS_UNVERIFIED", "IR_COVERAGE_MISSING"))
        self.assertNotEqual(v3["m6"]["status"], "AVAILABLE")
        self.assertEqual([q["revenue"] for q in v3["reported_quarters"]], [a[3] for a in ACTUALS])
        ev = v3["evidence"]
        self.assertEqual([(i["start"], i["end"]) for i in ev["forward_intervals"]], list(INTERVALS))
        self.assertIsInstance(ev["approval_sha256"], str)
        self.assertIsNotNone(ev["approval_approved_at"])
        self.assertTrue(ev["approval_decisions"])
        self.assertIsNone(ev["release_check_fault"])
        self.assertIsNone(ev["consensus_fault"])


if __name__ == "__main__":
    unittest.main()
