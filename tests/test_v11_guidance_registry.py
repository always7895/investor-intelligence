"""Lane V11 (revenue-guidance registry coverage of the current Top20): the registry, its reviewed profile and the release-check receipts resolve
every Top20 issuer to its expected v3 revenue state through the real producer (release_check.receipt_for + order_forecast.build_v3).

The receipts are rebuilt offline from tests/fixtures/v11-guidance-release-feeds.json (the live SEC, wire and official IR rows of 2026-10-13); the
registry and the approval are the tracked config files, so a changed record without a matching approval fails here."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issuer_ir_feeds  # noqa: E402
import order_forecast as ofc  # noqa: E402
import revenue_guidance as rg  # noqa: E402
import revenue_guidance_release_check as checker  # noqa: E402
from tests import v11_guidance_feeds as fx  # noqa: E402

REGISTRY_PATH = ROOT / "config" / "revenue-guidance-v1.json"
APPROVAL_PATH = ROOT / "config" / "revenue-guidance-approval-v1.json"
FEEDS = fx.load()
CLAIMS = {"status": "EMPTY", "sha256": "0" * 64, "issuers": {}}
GUIDANCE = ("SNDK", "NVDA", "MU", "LITE", "MRVL", "AMD", "AVGO", "MTSI", "CRDO", "AAOI", "ALAB", "BE", "NBIS", "CRWV")
NOT_DISCLOSED = ("000660.KS", "005930.KS", "AXTI", "CORZ", "3006.TW", "SIVE.ST")
# f1 (the first projected quarter, whole currency units) of the issuers this lane added or renewed.
FIRST_QUARTER = {"MU": 61.5e9, "SNDK": 10.55e9, "AVGO": 34.8e9, "MTSI": 0.42e9, "AAOI": 0.2725e9, "ALAB": 0.55e9, "LITE": 1.25e9}


def utc(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def dumps(registry: dict) -> bytes:
    return (json.dumps(registry, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


class Resolution:
    """One registry + approval + the receipts of its GUIDANCE records, evaluated at a build cutoff."""

    def __init__(self, registry_json: dict, approval_json: dict, now: datetime, feeds: dict | None = None):
        self.raw = dumps(registry_json)
        self.registry = rg.parse_registry(self.raw)
        self.approval = rg.parse_approval((json.dumps(approval_json, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        self.now, self.cutoff = now, now + timedelta(minutes=30)
        feeds = feeds or FEEDS
        self.issuers = {}
        for sym, rec in self.registry["issuers"].items():
            if rec.get("status") == "GUIDANCE" and sym in feeds["issuers"]:
                receipt = checker.receipt_for(rec, now, *fx.fetchers(feeds["issuers"][sym]))
                self.issuers[sym] = [receipt] if receipt else []
        self.cache = rg.parse_release_checks_cache(json.dumps({"schema": checker.SCHEMA, "generated_at": checker.stamp(now), "issuers": self.issuers}).encode("utf-8"))

    def v3(self, symbol):
        return ofc.build_v3(symbol, None, None, self.cutoff.date(), self.cutoff, CLAIMS, revenue_registry=self.registry,
                            release_checks_cache=self.cache, revenue_approval=self.approval)

    def receipt(self, symbol):
        return self.issuers[symbol][0]


def reapprove(approval_json: dict, registry_json: dict) -> dict:
    """The approval re-bound to an edited registry: same decisions, new registry and record hashes (what a human re-signing would produce)."""
    approval = copy.deepcopy(approval_json)
    approval["registry_sha256"] = hashlib.sha256(dumps(registry_json)).hexdigest()
    for rec in registry_json["issuers"]:
        if rec["symbol"] in approval["records"]:
            approval["records"][rec["symbol"]]["record_sha256"] = hashlib.sha256(rg.canonical_json(rec).encode("utf-8")).hexdigest()
    return approval


class V11Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry_json = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.approval_json = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
        cls.by_symbol = {r["symbol"]: r for r in cls.registry_json["issuers"]}
        # receipts at the fixture's check time, or at the approval's own time when the registry was re-signed later
        cls.now = max(utc(FEEDS["now"]), utc(cls.approval_json["approved_at"]) + timedelta(minutes=1))
        cls.real = Resolution(cls.registry_json, cls.approval_json, cls.now)

    def edited(self, edit):
        registry = copy.deepcopy(self.registry_json)
        edit({r["symbol"]: r for r in registry["issuers"]})
        return registry


class RegistryShapeTests(V11Base):
    def test_every_top20_issuer_has_its_record_and_expected_status(self):
        for symbol in GUIDANCE:
            self.assertEqual(self.by_symbol[symbol]["status"], "GUIDANCE", symbol)
        for symbol in NOT_DISCLOSED:
            self.assertEqual(self.by_symbol[symbol]["status"], "NOT_DISCLOSED", symbol)
            self.assertEqual(self.by_symbol[symbol]["reason"], "NO_NUMERIC_REVENUE_GUIDANCE", symbol)

    def test_registry_and_every_record_validate(self):
        self.assertEqual(self.real.registry["status"], "OK")
        for symbol, record in self.real.registry["issuers"].items():
            rg.validate_issuer_record(record, expected_symbol=symbol)

    def test_the_reviewed_profile_binds_every_record_at_the_build_cutoff(self):
        for symbol, record in self.real.registry["issuers"].items():
            self.assertIsNone(rg.check_reviewed_profile(symbol, record, self.real.approval, self.real.registry["sha256"], self.real.cutoff), symbol)

    def test_every_guidance_record_names_a_supported_official_ir_channel(self):
        for symbol in GUIDANCE:
            channels = self.by_symbol[symbol]["release_channels"]
            self.assertIn(channels["ir"]["kind"], issuer_ir_feeds.KINDS, symbol)
            self.assertTrue(channels["ir"]["url"].startswith("https://"), symbol)
            self.assertTrue(channels["ir_guidance_release_title"], symbol)

    def test_new_nondisclosure_records_cite_their_evidence_and_carry_four_actuals_and_four_intervals(self):
        for symbol in ("AXTI", "CORZ", "3006.TW", "SIVE.ST"):
            record = self.by_symbol[symbol]
            ids = {d["id"] for d in record["documents"]}
            self.assertEqual(record["claims"], [], symbol)
            self.assertTrue(set(record["nondisclosure_evidence"]["document_ids"]) <= ids, symbol)
            self.assertEqual(len(record["reported_quarters"]), 4, symbol)
            self.assertEqual(len(record["forward_intervals"]), 4, symbol)
            anchor = date.fromisoformat(record["reported_quarters"][-1]["end"])
            self.assertEqual(record["forward_intervals"][0]["start"], str(anchor + timedelta(days=1)), symbol)
            for quarter in record["reported_quarters"]:
                self.assertIn(quarter["document_id"], ids, symbol)

    def test_mu_record_is_the_fiscal_fourth_quarter_2026_release(self):
        record = self.by_symbol["MU"]
        claim = record["claims"][0]
        self.assertEqual((claim["fiscal_label"], claim["low"], claim["stated_point"], claim["high"]), ("FQ1-27", 60e9, 61.5e9, 63e9))
        self.assertEqual((claim["period_start"], claim["period_end"]), ("2026-09-04", "2026-12-03"))
        fq4 = record["reported_quarters"][-1]
        self.assertEqual((fq4["fiscal_label"], fq4["end"], fq4["revenue"]), ("FQ4-26", "2026-09-03", 54229e6))
        self.assertEqual((fq4["derivation"]["longer_value"], fq4["derivation"]["shorter_value"]), (133188e6, 78959e6))
        self.assertEqual([i["start"] for i in record["forward_intervals"]], ["2026-09-04", "2026-12-04", "2027-03-05", "2027-06-04"])
        docs = {d["id"]: d for d in record["documents"]}
        self.assertEqual(docs["MU-GUIDANCE"]["published_date"], "2026-09-30")


class TopTwentyResolutionTests(V11Base):
    def test_every_guidance_issuer_has_a_complete_official_receipt_and_is_available(self):
        for symbol in GUIDANCE:
            receipt = self.real.receipt(symbol)
            self.assertEqual((receipt["status"], receipt["coverage"]), ("OK", "SEC_WIRE_IR"), symbol)
            v3 = self.real.v3(symbol)
            self.assertEqual((v3["revenue_status"], v3["revenue_basis"], v3["revenue_reason"]), ("AVAILABLE", "COMPANY_GUIDANCE", None), symbol)

    def test_first_quarter_amounts_of_the_renewed_issuers(self):
        for symbol, amount in FIRST_QUARTER.items():
            v3 = self.real.v3(symbol)
            self.assertAlmostEqual(v3["forward_quarters"][0]["amount"], amount, delta=1.0, msg=symbol)

    def test_ended_guidance_quarters_inside_the_bridge_carry_the_model_warning(self):
        for symbol in ("LITE", "SNDK"):
            warning = self.real.v3(symbol)["warning"]
            self.assertIsNotNone(warning, symbol)
            self.assertIn("仍為財測／模型，非實績", warning["text"], symbol)

    def test_nondisclosure_issuers_stay_unavailable_with_the_nondisclosure_reason(self):
        for symbol in NOT_DISCLOSED:
            v3 = self.real.v3(symbol)
            self.assertEqual((v3["revenue_status"], v3["revenue_reason"]), ("UNAVAILABLE", "NOT_DISCLOSED"), symbol)
            self.assertIn(v3["revenue_diagnostic"], (None, "CONSENSUS_DEFERRED"), symbol)

    def test_the_renewed_mu_record_is_available_while_its_release_day_items_are_reviewed(self):
        receipt = self.real.receipt("MU")
        later = {d["id"]: d["disposition"] for d in receipt["later_documents"]}
        self.assertEqual(later["0000723125-26-000018"], "REVIEWED_IRRELEVANT")  # the 8-K that furnishes the guidance document
        self.assertNotIn("POSSIBLY_RELEVANT", later.values())
        self.assertNotIn("RESULTS_RELEASE", later.values())  # the 10-K of 2026-10-09 reports the already anchored FQ4-26


class FailClosedTests(V11Base):
    def resolve(self, edit, feeds=None):
        registry = self.edited(edit)
        return Resolution(registry, reapprove(self.approval_json, registry), self.now, feeds)

    def test_a_record_without_an_official_ir_channel_keeps_its_projection_unavailable(self):
        def edit(by):
            del by["AVGO"]["release_channels"]["ir"], by["AVGO"]["release_channels"]["ir_guidance_release_title"]
        res = self.resolve(edit)
        v3 = res.v3("AVGO")
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_diagnostic"]), ("UNAVAILABLE", "FRESHNESS_UNVERIFIED", "IR_COVERAGE_MISSING"))

    def test_a_guidance_title_the_channel_does_not_list_is_an_unverified_freshness_proof(self):
        def edit(by):
            by["MU"]["release_channels"]["ir_guidance_release_title"] = "Micron Technology, Inc. Reports Record Results for the Third Quarter of Fiscal 2026"
        res = self.resolve(edit)
        self.assertFalse(res.receipt("MU")["channels"][2]["complete"])
        v3 = res.v3("MU")
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"]), ("UNAVAILABLE", "FRESHNESS_UNVERIFIED"))

    def test_an_unreviewed_later_release_makes_the_record_stale(self):
        def edit(by):
            by["SNDK"]["reviewed_later_documents"] = [r for r in by["SNDK"]["reviewed_later_documents"] if "investor-day" not in r["id"] and "financial-model" not in r["id"]]
        res = self.resolve(edit)
        self.assertEqual(res.receipt("SNDK")["status"], "REVIEW_REQUIRED")
        v3 = res.v3("SNDK")
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"]), ("UNAVAILABLE", "STALE"))

    def test_a_published_results_release_after_the_guidance_day_makes_the_record_stale(self):
        feeds = copy.deepcopy(FEEDS)
        feeds["issuers"]["AMD"]["sec"]["rows"].insert(0, {"form": "8-K", "filingDate": "2026-10-12", "items": "2.02,9.01", "accessionNumber": "0000002488-26-000999", "reportDate": "2026-10-12"})
        res = Resolution(self.registry_json, self.approval_json, self.now, feeds)
        self.assertEqual(res.receipt("AMD")["status"], "RESULTS_PUBLISHED")
        v3 = res.v3("AMD")
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"]), ("UNAVAILABLE", "STALE"))

    def test_a_record_changed_after_its_review_is_not_admitted(self):
        registry = self.edited(lambda by: by["MU"]["claims"][0].update(high=70e9))
        res = Resolution(registry, self.approval_json, self.now)  # the approval still binds the reviewed bytes
        v3 = res.v3("MU")
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_diagnostic"]), ("UNAVAILABLE", "INVALID", "UNREVIEWED_INPUTS"))

    def test_an_unreachable_official_channel_never_reads_as_no_release(self):
        feeds = copy.deepcopy(FEEDS)
        feeds["issuers"]["ALAB"]["ir"]["url"] = "https://ir.asteralabs.com/elsewhere.xml"  # the channel the registry names is not the one that answers
        res = Resolution(self.registry_json, self.approval_json, self.now, feeds)
        self.assertEqual(res.receipt("ALAB")["status"], "FRESHNESS_UNVERIFIED")
        self.assertEqual(res.v3("ALAB")["revenue_reason"], "FRESHNESS_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
