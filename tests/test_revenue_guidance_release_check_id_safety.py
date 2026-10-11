"""BATCH10C F8-N1: the release checker writes every later-document id in the persisted form of
revenue_guidance_overlay.safe_document_id, so a feed link with userinfo ('@'), a query ('?') or a fragment ('#') never
reaches a receipt, the receipt file or the curated path's published `evidence.latest_release_check` verbatim. The
persisted form is a safe id (BATCH10C F8-AMEND1): such a receipt states the status a clean id would give it, exactly as
its recompute does, and bars nothing; a review of the raw id links the persisted form.

Fake feeds and clocks only: no network, no subprocess; every file lives in a TemporaryDirectory.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import order_forecast as ofc  # noqa: E402
import revenue_guidance  # noqa: E402
import revenue_guidance_overlay as overlay  # noqa: E402
import revenue_guidance_release_check as check  # noqa: E402
from tests import test_order_forecast as order_tests  # noqa: E402
from tests import test_revenue_guidance_release_check as check_tests  # noqa: E402

SECRET = "SYNTHETIC_f8n1-s3cret-token"
NOW = check_tests.NOW
CUTOFF = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
IR_TITLE = check_tests.ReleaseCheckIrChannelTests.IR_TITLE
SITE = "https://investor.marvell.com"
RSS_URL = SITE + "/news-events/press-releases/rss"
RSS_ITEM = SITE + "/news-events/press-releases/detail/"
Q4_URL = SITE + "/feed/PressRelease.svc/GetPressReleaseList"
NEWSROOM_URL = SITE + "/newsroom"
# The reviewed guidance release on the reference day, one quiet later item and one item older than the reference day,
# so the IR channel is a complete read and only the ids decide the status.
GUIDANCE_RSS = [("Wed, 27 Aug 2026 08:00:00 -0700", IR_TITLE, RSS_ITEM + "1001/"),
                ("Wed, 09 Sep 2026 08:00:00 -0700", "Marvell to Showcase Optical Demos", RSS_ITEM + "1002/"),
                ("Wed, 01 Jul 2026 08:00:00 -0700", "Marvell Introduces Products", RSS_ITEM + "1000/")]
WIRE_ROWS = [("Sep 23, 2026", "Marvell Names Director", ":" + SECRET + "@attacker.example/press-release/director"),
             ("Sep 22, 2026", "Marvell Opens Design Center", "/press-release/center#" + SECRET),
             ("Sep 21, 2026", "Marvell to Showcase Optical Demos", "/press-release/demos?token=" + SECRET),
             ("Aug 27, 2026", "Marvell Technology, Inc. Reports Second Quarter of Fiscal Year 2027 Financial Results",
              "/press-release/results"),
             ("Aug 3, 2026", "Marvell Technology, Inc. Announces Conference Call to Review Second Quarter Results",
              "/press-release/call")]
WIRE_UNSAFE = ["https://www.nasdaq.com" + url for _, _, url in WIRE_ROWS[:3]]


def wire_feed(rows):
    """rows: (created, title, url path) served as the Nasdaq press-release pages."""
    def fetch(url):
        offset = int(url.rsplit("offset=", 1)[1])
        page = rows[offset:offset + check.WIRE_PAGE]
        return {"data": {"rows": [{"created": d, "title": t, "url": u} for d, t, u in page], "totalrecords": len(rows)}}
    return fetch


def rss_feed(items):
    """items: (pubDate, title, link) served as the IR RSS feed."""
    def fetch(url):
        return ("<rss><channel>" + "".join(f"<item><title>{t}</title><link>{link}</link><pubDate>{p}</pubDate></item>"
                                           for p, t, link in items) + "</channel></rss>").encode("utf-8")
    return fetch


def q4_feed(rows):
    """rows: (PressReleaseDate, Headline, LinkToDetailPage) served as the Q4 press-release list of every year."""
    def fetch(url):
        return json.dumps({"GetPressReleaseListResult": [
            {"PressReleaseDate": d, "Headline": t, "LinkToDetailPage": link} for d, t, link in rows]}).encode("utf-8")
    return fetch


def newsroom_feed(links):
    """links: (href, label ending in the publication day) served as the newsroom page."""
    def fetch(url):
        return ("<html><body>" + "".join(f'<a href="{h}">{label}</a>' for h, label in links) + "</body></html>").encode("utf-8")
    return fetch


def ir_record(kind, url):
    rec = check_tests.record(release_channels={"sec_cik": 1835632, "wire_symbol": "MRVL", "wire_names": ["Marvell"],
                                               "ir": {"kind": kind, "url": url}, "ir_guidance_release_title": IR_TITLE})
    # The BASE_SEC/BASE_WIRE fakes carry same-day items; the writer has reviewed both away (as in the checker tests).
    rec["reviewed_later_documents"] = [
        {"id": "0001-26-1", "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-09-28T09:00:00Z"},
        {"id": "https://www.nasdaq.com/press-release/2", "disposition": "REVIEWED_IRRELEVANT",
         "reviewed_at": "2026-09-28T09:00:00Z"},
    ]
    return rec


def recompute(receipt, rec):
    """The registry reader's recompute of a checker receipt, bound to the record's reviewed wiring."""
    channels = rec["release_channels"]
    ir = channels.get("ir")
    return revenue_guidance.recompute_receipt_status(
        receipt, rec.get("reviewed_later_documents"), cutoff_day=CUTOFF.date(),
        guidance_published_date=date.fromisoformat(receipt["guidance_published_date"]), cutoff_instant=CUTOFF,
        expected_cik=channels["sec_cik"], expected_wire_symbol=channels["wire_symbol"],
        expected_ir_host=urlsplit(ir["url"]).netloc if ir else None)


def base_sec(extra=()):
    return check_tests.sec(list(check_tests.BASE_SEC) + list(extra))


def base_wire():
    return check_tests.wire(check_tests.BASE_WIRE)


class CheckerWritesThePersistedForm(unittest.TestCase):
    def assert_persisted(self, receipt, channel, raws):
        ids = [d["id"] for d in receipt["later_documents"] if d["channel"] == channel]
        text = json.dumps(receipt, ensure_ascii=False)
        for raw in raws:
            safe = overlay.safe_document_id(raw)
            self.assertTrue(revenue_guidance.unsafe_document_id(raw), raw)
            self.assertNotEqual(safe, raw)
            self.assertIn("#sha256:", safe)
            self.assertIn(safe, ids)
            self.assertNotIn(raw, text)
        self.assertNotIn(SECRET, text)
        self.assertTrue(all(isinstance(d["id"], str) for d in receipt["later_documents"]))
        # The persisted form is a safe id (F8-AMEND1): the receipt states its own status and bars nothing.
        self.assertNotEqual(receipt["status"], "FRESHNESS_UNVERIFIED")
        self.assertFalse(revenue_guidance.receipt_has_unsafe_document_id(receipt))
        self.assertFalse(any(revenue_guidance.raw_unsafe_document_id(d["id"]) for d in receipt["later_documents"]))
        self.assertEqual(receipt["digest"], check.canonical_digest(receipt))

    def test_clean_ids_are_written_unchanged_and_the_recompute_agrees(self):
        rec = ir_record("RSS", RSS_URL)
        r = check.receipt_for(rec, NOW, base_sec(), base_wire(), rss_feed(GUIDANCE_RSS))
        self.assertEqual(r["status"], "OK")
        self.assertEqual(recompute(r, rec), "OK")
        ids = [d["id"] for d in r["later_documents"]]
        for item_id in ("0001-26-1", "https://www.nasdaq.com/press-release/2", RSS_ITEM + "1002/"):
            self.assertIn(item_id, ids)
        for item_id in ids:
            self.assertFalse(revenue_guidance.unsafe_document_id(item_id), item_id)
            self.assertEqual(overlay.safe_document_id(item_id), item_id)
        classic = check_tests.record()
        r = check.receipt_for(classic, NOW, base_sec(), base_wire())
        self.assertEqual(r["status"], "REVIEW_REQUIRED")
        self.assertEqual(recompute(r, classic), "REVIEW_REQUIRED")

    def test_rss_ids_with_query_fragment_or_userinfo_are_persisted(self):
        raws = [RSS_ITEM + "1012/?utm_source=" + SECRET, RSS_ITEM + "1013/#" + SECRET,
                "https://reader:" + SECRET + "@investor.marvell.com/news-events/press-releases/detail/1014/"]
        items = GUIDANCE_RSS + [(f"Wed, {day} Sep 2026 08:00:00 -0700", "Marvell to Showcase Optical Demos", raw)
                                for day, raw in zip(("10", "11", "12"), raws)]
        rec = ir_record("RSS", RSS_URL)
        r = check.receipt_for(rec, NOW, base_sec(), base_wire(), rss_feed(items))
        self.assertTrue(all(c["status"] == "OK" and c["complete"] for c in r["channels"]))
        self.assert_persisted(r, "ISSUER_IR", raws)
        self.assertIn(RSS_ITEM + "1002/", [d["id"] for d in r["later_documents"]])  # the clean item stays as it is
        self.assertEqual((r["status"], recompute(r, rec)), ("OK", "OK"))

    def test_q4_ids_with_query_fragment_or_userinfo_are_persisted(self):
        rows = [("08/27/2026 16:05:00", IR_TITLE, "/news-details/2026/guidance/default.aspx"),
                ("09/09/2026 08:00:00", "Marvell to Showcase Optical Demos",
                 "/news-details/2026/demos/default.aspx?token=" + SECRET),
                ("09/10/2026 08:00:00", "Marvell Opens Design Center", "/news-details/2026/center/default.aspx#" + SECRET),
                ("09/11/2026 08:00:00", "Marvell Names Director",
                 "https://reader:" + SECRET + "@investor.marvell.com/news-details/2026/director/"),
                ("09/12/2026 08:00:00", "Marvell Hosts Event", "/news-details/2026/event/default.aspx")]
        raws = [SITE + rows[1][2], SITE + rows[2][2], rows[3][2]]
        rec = ir_record("Q4_PRESS_RELEASES", Q4_URL)
        r = check.receipt_for(rec, NOW, base_sec(), base_wire(), q4_feed(rows))
        self.assertTrue(all(c["status"] == "OK" and c["complete"] for c in r["channels"]))
        self.assert_persisted(r, "ISSUER_IR", raws)
        self.assertIn(SITE + rows[4][2], [d["id"] for d in r["later_documents"]])
        self.assertEqual((r["status"], recompute(r, rec)), ("OK", "OK"))

    def test_newsroom_ids_can_carry_only_userinfo_and_are_persisted(self):
        raw = SITE + "/newsroom/token-" + SECRET + "@demos"
        links = [("/newsroom/guidance", IR_TITLE + " August 27, 2026"),
                 ("/newsroom/token-" + SECRET + "@demos", "Marvell to Showcase Optical Demos September 9, 2026"),
                 ("/newsroom/center?token=" + SECRET, "Marvell Opens Design Center September 10, 2026"),
                 ("/newsroom/director#" + SECRET, "Marvell Names Director September 11, 2026"),
                 ("/newsroom/products", "Marvell Introduces Products July 1, 2026")]
        rec = ir_record("NEWSROOM_HTML", NEWSROOM_URL)
        r = check.receipt_for(rec, NOW, base_sec(), base_wire(), newsroom_feed(links))
        self.assertTrue(all(c["status"] == "OK" and c["complete"] for c in r["channels"]))
        # The newsroom reader never lists a link with a query or a fragment (its href pattern); '@' is the only case.
        self.assertEqual([d["id"] for d in r["later_documents"] if d["channel"] == "ISSUER_IR"], [overlay.safe_document_id(raw)])
        self.assert_persisted(r, "ISSUER_IR", [raw])
        self.assertEqual((r["status"], recompute(r, rec)), ("OK", "OK"))

    def test_wire_ids_with_query_fragment_or_userinfo_are_persisted(self):
        rec = check_tests.record()
        r = check.receipt_for(rec, NOW, base_sec(), wire_feed(WIRE_ROWS))
        self.assertTrue(all(c["status"] == "OK" and c["complete"] for c in r["channels"]))
        self.assert_persisted(r, "WIRE_PRESS_RELEASES", WIRE_UNSAFE)
        self.assertIn("https://www.nasdaq.com/press-release/results", [d["id"] for d in r["later_documents"]])
        # the unreviewed same-day 8-K and wire results release make it a review item, as with clean ids
        self.assertEqual((r["status"], recompute(r, rec)), ("REVIEW_REQUIRED", "REVIEW_REQUIRED"))

    def test_a_reviewed_unsafe_id_is_matched_in_the_persisted_form(self):
        raw = RSS_ITEM + "1015/?token=" + SECRET
        rec = ir_record("RSS", RSS_URL)
        rec["reviewed_later_documents"].append({"id": raw, "disposition": "REVIEWED_IRRELEVANT",
                                                "reviewed_at": "2026-09-28T09:00:00Z"})
        items = GUIDANCE_RSS + [("Thu, 18 Sep 2026 08:00:00 -0700",
                                 "Marvell Reports Third Quarter Fiscal 2027 Financial Results", raw)]
        r = check.receipt_for(rec, NOW, base_sec(), base_wire(), rss_feed(items))
        self.assertEqual([d["disposition"] for d in r["later_documents"] if d["id"] == overlay.safe_document_id(raw)],
                         ["REVIEWED_IRRELEVANT"])
        self.assert_persisted(r, "ISSUER_IR", [raw])
        # F8-AMEND1: the recompute links the raw review to the persisted form, so the receipt is a usable OK
        self.assertEqual((r["status"], recompute(r, rec)), ("OK", "OK"))

    def test_sec_accessions_are_persisted_and_a_non_string_accession_is_a_failed_feed(self):
        rec = check_tests.record()
        raw = "0001-26-7#" + SECRET
        r = check.receipt_for(rec, NOW, base_sec([("8-K", "2026-09-15", "8.01", raw, "")]), base_wire())
        self.assert_persisted(r, "SEC_SUBMISSIONS", [raw])
        self.assertIn("0001-26-1", [d["id"] for d in r["later_documents"]])
        self.assertEqual((r["status"], recompute(r, rec)), ("REVIEW_REQUIRED", "REVIEW_REQUIRED"))
        for bad in (260007, ["0001-26-7"], None):
            with self.subTest(accession=bad):
                r = check.receipt_for(rec, NOW, base_sec([("8-K", "2026-09-15", "8.01", bad, "")]), base_wire())
                sec = r["channels"][0]
                self.assertEqual((sec["kind"], sec["status"], sec["complete"]), ("SEC_SUBMISSIONS", "FAILED", False))
                self.assertEqual([d for d in r["later_documents"] if d["channel"] == "SEC_SUBMISSIONS"], [])
                self.assertTrue(all(isinstance(d["id"], str) for d in r["later_documents"]))
                self.assertEqual(r["status"], "FRESHNESS_UNVERIFIED")
                self.assertEqual(recompute(r, rec), r["status"])

    def test_run_writes_no_original_id_into_the_receipt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg, out = Path(tmp) / "reg.json", Path(tmp) / "out.json"
            reg.write_text(json.dumps({"schema": "revenue-guidance-v1", "version": 1,
                                       "issuers": [check_tests.record(), {"symbol": "X", "status": "NOT_DISCLOSED"}]}),
                           encoding="utf-8")
            result = check.run(reg, out, NOW, base_sec(), wire_feed(WIRE_ROWS), state_root=Path(tmp) / "state")
            raw = out.read_bytes()
            self.assertNotIn(SECRET.encode("utf-8"), raw)
            for unsafe in WIRE_UNSAFE:
                self.assertNotIn(unsafe.encode("utf-8"), raw)
            doc = json.loads(raw.decode("utf-8"))
            self.assertEqual(list(doc["issuers"]), ["MRVL"])
            [receipt] = doc["issuers"]["MRVL"]
            self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
            self.assertEqual(recompute(receipt, check_tests.record()), "REVIEW_REQUIRED")
            ids = [d["id"] for d in receipt["later_documents"]]
            for unsafe in WIRE_UNSAFE:
                self.assertIn(overlay.safe_document_id(unsafe), ids)
            # a verifiable receipt (the persisted form is a safe id, F8-AMEND1): the run is not a failed one
            self.assertEqual((result["status"], result["failed"]), ("OK", []))


class CuratedPathPublishesNoOriginal(unittest.TestCase):
    """The curated path publishes the newest receipt as evidence.latest_release_check (scripts/order_forecast.py
    build_v3): a checker-written receipt carries the persisted form only, and, the persisted form being a safe id
    (BATCH10C F8-AMEND1), the receipt is a usable OK one and the revenue path is available."""

    def test_latest_release_check_carries_the_persisted_form_only(self):
        reg = order_tests.OrderForecastV3Tests._sample_registry(None, stated_point=32.0)
        rec = reg["issuers"]["TEST"]
        rec["release_channels"].update({"sec_cik": 1234567, "wire_symbol": "TEST", "wire_names": ["Test Co"]})
        raw = "https://investor.test.com/news/showcase?utm_source=" + SECRET
        q4 = q4_feed([("08/20/2026 16:05:00", "Test Co Reports Financial Results", "/news/guidance"),
                      ("09/09/2026 08:00:00", "Test Co to Showcase Products", "/news/showcase?utm_source=" + SECRET)])
        receipt = check.receipt_for(rec, datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc),
                                    check_tests.sec([("8-K", "2026-01-10", "5.02", "0001234567-26-000001", "")]),
                                    wire_feed([("Aug 1, 2026", "Test Co Holds Annual Meeting", "/press-release/test-old")]), q4)
        self.assertTrue(all(c["status"] == "OK" and c["complete"] for c in receipt["channels"]))
        self.assertEqual([d["id"] for d in receipt["later_documents"]], [overlay.safe_document_id(raw)])
        self.assertEqual(receipt["status"], "OK")
        cache = {"schema": "revenue-guidance-release-checks-v1", "generated_at": receipt["checked_at"],
                 "issuers": {"TEST": [receipt]}}
        approval = order_tests.make_synthetic_approval(reg["sha256"], reg["issuers"])
        v3 = ofc.build_v3("TEST", None, None, date(2026, 9, 28), CUTOFF, {"status": "EMPTY", "sha256": "0" * 64, "issuers": {}},
                          revenue_registry=reg, release_checks_cache=cache, revenue_approval=approval)
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"]), ("AVAILABLE", None))
        published = v3["evidence"]["latest_release_check"]
        self.assertEqual(published["digest"], receipt["digest"])
        self.assertEqual([d["id"] for d in published["later_documents"]], [overlay.safe_document_id(raw)])
        sealed = json.dumps(v3, ensure_ascii=False, default=str)
        self.assertNotIn(SECRET, sealed)
        self.assertNotIn(raw, sealed)


class ReviewedExit(unittest.TestCase):
    """BATCH10C F8-AMEND1 (acceptance: reviewed exit). An official IR item whose feed link carries a query: a legacy row
    (written before F8-N1) lists the link raw and bars the record, while the updater recorded the document in the
    persisted form. Once that row has aged out, a REVIEWED_IRRELEVANT entry for the raw id accounts the stored
    persisted-form detection and links the persisted form the newest receipt lists, so the record is admitted."""
    CUTOFF = "2026-09-28T12:00:00Z"

    def admission(self, rows, rec, detections):
        cache = {"schema": revenue_guidance.RELEASE_CHECKS_SCHEMA, "issuers": {"MRVL": rows}}
        return overlay.receipt_admission(cache, "MRVL", rec, self.CUTOFF, None, detections)

    def test_a_review_of_the_raw_id_accounts_the_persisted_detection_after_the_raw_row_ages_out(self):
        raw = RSS_ITEM + "1016/?utm_source=feed"
        persisted = overlay.safe_document_id(raw)
        # a reviewed IR item id is admissible in the registry on the record's own IR host (a wire id with '?' is not)
        self.assertTrue(revenue_guidance.URL_RE.match(raw) and urlsplit(raw).netloc == urlsplit(RSS_URL).netloc)
        self.assertIsNone(revenue_guidance.WIRE_ITEM_RE.match("https://www.nasdaq.com/press-release/x?utm_source=feed"))
        items = GUIDANCE_RSS + [("Thu, 18 Sep 2026 08:00:00 -0700", "Marvell Reports Third Quarter Fiscal 2027 Financial Results", raw)]
        rec = ir_record("RSS", RSS_URL)
        before = check.receipt_for(rec, datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc), base_sec(), base_wire(), rss_feed(items))
        self.assertEqual(before["status"], "REVIEW_REQUIRED")
        self.assertEqual([d["disposition"] for d in before["later_documents"] if d["id"] == persisted], ["POSSIBLY_RELEVANT"])
        legacy = json.loads(json.dumps(before))
        for d in legacy["later_documents"]:
            if d["id"] == persisted:
                d["id"] = raw  # what the checker wrote before F8-N1
        legacy["checked_at"] = "2026-09-28T08:00:00Z"
        legacy["digest"] = check.canonical_digest(legacy)
        # what the updater recorded while the legacy row barred the record: the material document, persisted
        detections = [d for d in overlay._material_documents([legacy]) if d["id"] == persisted]
        self.assertEqual([d["disposition"] for d in detections], ["POSSIBLY_RELEVANT"])
        reviewed = ir_record("RSS", RSS_URL)
        reviewed["reviewed_later_documents"].append({"id": raw, "disposition": "REVIEWED_IRRELEVANT",
                                                     "reviewed_at": "2026-09-28T09:30:00Z"})
        after = check.receipt_for(reviewed, NOW, base_sec(), base_wire(), rss_feed(items))
        self.assertEqual([d["disposition"] for d in after["later_documents"] if d["id"] == persisted], ["REVIEWED_IRRELEVANT"])
        self.assertEqual((after["status"], recompute(after, reviewed)), ("OK", "OK"))
        # while the legacy row is retained, the record is barred, review or not
        self.assertEqual(self.admission([legacy, after], reviewed, detections)["decision"], "RECEIPT_DOCUMENT_ID_UNSAFE")
        # aged out, without the review: the persisted detection is unaccounted
        unreviewed = self.admission([before], rec, detections)
        self.assertEqual(unreviewed["decision"], "RECEIPT_REVIEW_REQUIRED")
        self.assertEqual([d["id"] for d in unreviewed["unaccounted"]], [persisted])
        # aged out, with the review of the raw id: accounted and admitted
        admitted = self.admission([after], reviewed, detections)
        self.assertEqual((admitted["decision"], admitted["valid"], admitted["status"], admitted["unaccounted"]), (None, True, "OK", []))
        self.assertNotIn(SECRET, json.dumps(admitted))


if __name__ == "__main__":
    unittest.main()
