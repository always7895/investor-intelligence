import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import revenue_guidance  # noqa: E402
import revenue_guidance_release_check as check  # noqa: E402

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


def record(**overrides):
    base = {"symbol": "MRVL", "status": "GUIDANCE",
            "documents": [{"id": "MRVL-GUIDANCE", "published_date": "2026-08-27"}],
            "reported_quarters": [{"end": "2026-08-01"}],
            "claims": [{"id": "MRVL-Q", "document_id": "MRVL-GUIDANCE", "metric": "REVENUE",
                        "assertion_kind": "COMPANY_GUIDANCE", "period_kind": "QUARTER", "scope": "COMPANY",
                        "stated_point": 2.0, "currency": "USD"}],
            "release_channels": {"sec_cik": 1835632, "wire_symbol": "MRVL", "wire_names": ["Marvell"]}}
    base.update(overrides)
    return base


def sec(rows):
    forms, dates, items, accs, reports = zip(*rows) if rows else ((), (), (), (), ())
    return lambda url: {"filings": {"recent": {"form": list(forms), "filingDate": list(dates), "items": list(items),
                                                "accessionNumber": list(accs), "reportDate": list(reports)}}}


def wire(rows, total=None):
    def fetch(url):
        offset = int(url.rsplit("offset=", 1)[1])
        page = rows[offset:offset + check.WIRE_PAGE]
        return {"data": {"rows": [{"created": d, "title": t, "url": f"/press-release/{i + offset}"} for i, (d, t) in enumerate(page)],
                         "totalrecords": len(rows) if total is None else total}}
    return fetch


BASE_SEC = [("8-K", "2026-08-27", "2.02,9.01", "0001-26-1", ""), ("10-Q", "2026-08-28", "", "0001-26-2", "2026-08-01"),
            ("8-K", "2026-01-10", "5.02", "0001-26-0", "")]
BASE_WIRE = [("Sep 25, 2026", "Marvell Technology, Inc. Declares Quarterly Dividend Payment"),
             ("Sep 21, 2026", "Marvell to Showcase Optical Demos"),
             ("Aug 27, 2026", "Marvell Technology, Inc. Reports Second Quarter of Fiscal Year 2027 Financial Results"),
             ("Aug 3, 2026", "Marvell Technology, Inc. Announces Conference Call to Review Second Quarter Results")]


class ReleaseCheckTests(unittest.TestCase):
    def receipt(self, sec_rows=BASE_SEC, wire_rows=BASE_WIRE, rec=None, ir_fetch=None, **kw):
        return check.receipt_for(rec or record(), NOW, sec(sec_rows), wire(wire_rows, **kw), ir_fetch)

    def test_quiet_period_is_ok_and_digest_binds_the_receipt(self):
        # A filing on the guidance day itself is ambiguous (day-granular feed): it stays in later_documents for review
        # and, once the writer has reviewed it away, the quiet period reads OK (Astra r5 item 2).
        r = self.receipt(rec=record(reviewed_later_documents=[
            {"id": "0001-26-1", "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-09-28T09:00:00Z"},
            {"id": "https://www.nasdaq.com/press-release/2", "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-09-28T09:00:00Z"},
        ]))
        self.assertEqual(r["status"], "OK")
        self.assertEqual([c["complete"] for c in r["channels"]], [True, True])
        self.assertEqual([c["checked_through"] for c in r["channels"]], ["2026-09-28", "2026-09-28"])
        self.assertEqual(r["coverage"], "SEC_AND_WIRE")
        self.assertEqual(r["digest"], check.canonical_digest(r))
        # The same-day filings/releases are preserved for review (never silently dropped), later-day items stay after.
        self.assertTrue(any(d["date"] == "2026-08-27" for d in r["later_documents"]))
        self.assertTrue(all(d["date"] >= "2026-08-27" for d in r["later_documents"]))

    def test_same_day_filings_stay_ambiguous_for_review(self):
        # The unreviewed same-day 2.02 is a review item, never auto-classified as a results release nor dropped.
        r = self.receipt()
        self.assertEqual(r["status"], "REVIEW_REQUIRED")
        same_day = [d for d in r["later_documents"] if d["date"] == "2026-08-27"]
        self.assertTrue(same_day)
        self.assertTrue(all(d["disposition"] == "POSSIBLY_RELEVANT" for d in same_day))
        self.assertFalse(any(d["disposition"] == "RESULTS_RELEASE" for d in same_day))

    def test_ownership_filings_and_irrelevant_item_8ks_are_never_review_items_even_on_the_guidance_day(self):
        # Writer integration (real rebuild 2026-09-28): CRWV files Forms 4 and 144 daily; they carry no revenue statement.
        extra = [("4", "2026-08-27", "", "own-1", ""), ("144", "2026-08-27", "", "own-2", ""), ("SCHEDULE 13G", "2026-08-27", "", "own-3", ""),
                 ("8-K", "2026-08-27", "5.02", "k502", ""), ("4", "2026-09-10", "", "own-4", "")]
        r = self.receipt(sec_rows=BASE_SEC + extra)
        ids = {d["id"]: d["disposition"] for d in r["later_documents"]}
        self.assertNotIn("own-1", ids)
        self.assertNotIn("own-4", ids)
        self.assertEqual(ids["k502"], "IRRELEVANT")
        self.assertEqual(ids["0001-26-1"], "POSSIBLY_RELEVANT")  # the same-day 2.02 stays a review item

    def test_new_results_8k_or_periodic_report_publish_results(self):
        r = self.receipt(sec_rows=BASE_SEC + [("8-K", "2026-11-25", "2.02,9.01", "0001-26-9", "")])
        self.assertEqual(r["status"], "RESULTS_PUBLISHED")
        r = self.receipt(sec_rows=BASE_SEC + [("10-Q", "2026-12-01", "", "0001-26-8", "2026-10-31")])
        self.assertEqual(r["status"], "RESULTS_PUBLISHED")

    def test_irrelevant_items_pass_other_items_need_review_until_reviewed(self):
        # Same-day items (the guidance-day 2.02 filing and the guidance-day wire results release) are ambiguous and
        # must be reviewed away before later items can be read on their own (Astra r5 item 2).
        same_day_ids = ["0001-26-1", "https://www.nasdaq.com/press-release/2"]  # BASE_WIRE alone: Aug 27 is index 2
        same_day_reviews = [{"id": i, "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-09-28T09:00:00Z"} for i in same_day_ids]
        def reviewed(**kw):
            rec_kw = {"reviewed_later_documents": list(same_day_reviews)}
            rec_kw.update(kw)
            return record(**rec_kw)
        self.assertEqual(self.receipt(sec_rows=BASE_SEC + [("8-K", "2026-09-10", "1.01,9.01", "a", "")],
                                     rec=reviewed())["status"], "OK")
        r = self.receipt(sec_rows=BASE_SEC + [("8-K", "2026-09-25", "8.01,9.01", "b", "")], rec=reviewed())
        self.assertEqual(r["status"], "REVIEW_REQUIRED")
        reviewed = record(reviewed_later_documents=same_day_reviews + [{"id": "b", "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-09-28T09:00:00Z"}])
        r = self.receipt(sec_rows=BASE_SEC + [("8-K", "2026-09-25", "8.01,9.01", "b", "")], rec=reviewed)
        self.assertEqual(r["status"], "OK")
        self.assertEqual({d["id"]: d["disposition"] for d in r["later_documents"]}["b"], "REVIEWED_IRRELEVANT")

    def test_wire_results_or_guidance_titles_need_review(self):
        # The same-day (guidance-day) Marvell results release is ambiguous: it must be reviewed away before the
        # other cases can read OK (Astra r5 item 2). The wire item id follows the row position in the fetched list.
        def with_same_day_reviews(rows):
            idx = next(i for i, row in enumerate(rows) if row[0] == "Aug 27, 2026")
            reviews = [
                {"id": "0001-26-1", "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-09-28T09:00:00Z"},
                {"id": f"https://www.nasdaq.com/press-release/{idx}", "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-09-28T09:00:00Z"},
            ]
            return record(reviewed_later_documents=reviews)
        rows = [("Oct 5, 2026", "Marvell Updates Third Quarter Revenue Outlook")] + BASE_WIRE
        self.assertEqual(self.receipt(wire_rows=rows, rec=with_same_day_reviews(rows))["status"], "REVIEW_REQUIRED")
        rows = [("Oct 5, 2026", "Other Company Updates Revenue Outlook")] + BASE_WIRE  # does not name the issuer
        self.assertEqual(self.receipt(wire_rows=rows, rec=with_same_day_reviews(rows))["status"], "OK")
        rows = [("Oct 5, 2026", "Marvell Announces Results of Annual General Meeting of Shareholders")] + BASE_WIRE
        self.assertEqual(self.receipt(wire_rows=rows, rec=with_same_day_reviews(rows))["status"], "OK")

    def test_failed_or_incomplete_channels_are_unverified(self):
        def boom(url):
            raise OSError("down")
        self.assertEqual(check.receipt_for(record(), NOW, boom, wire(BASE_WIRE))["status"], "FRESHNESS_UNVERIFIED")
        self.assertEqual(check.receipt_for(record(), NOW, sec(BASE_SEC), boom)["status"], "FRESHNESS_UNVERIFIED")
        # the SEC feed does not reach back to the guidance date
        self.assertEqual(self.receipt(sec_rows=[("8-K", "2026-09-10", "1.01", "a", "")])["status"], "FRESHNESS_UNVERIFIED")
        # the wire feed stops (more records exist) before reaching the guidance date
        many = [("Sep 25, 2026", f"Marvell news {i}") for i in range(check.WIRE_PAGE * check.WIRE_MAX_PAGES)]
        self.assertEqual(self.receipt(wire_rows=many, total=10_000)["status"], "FRESHNESS_UNVERIFIED")
        # an unparseable wire date is a failed channel, not an empty one
        self.assertEqual(self.receipt(wire_rows=[("yesterday", "Marvell")])["status"], "FRESHNESS_UNVERIFIED")

    def test_records_without_channels_are_not_checked(self):
        self.assertIsNone(check.receipt_for(record(release_channels={}), NOW, sec(BASE_SEC), wire(BASE_WIRE)))

    def test_run_keeps_history_and_a_bad_registry_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg, out = Path(tmp) / "reg.json", Path(tmp) / "out.json"
            reg.write_text(json.dumps({"schema": "revenue-guidance-v1", "version": 1, "issuers": [record(), {"symbol": "X", "status": "NOT_DISCLOSED"}]}))
            for hour in range(10):
                check.run(reg, out, NOW.replace(hour=hour), sec(BASE_SEC), wire(BASE_WIRE))
            doc = json.loads(out.read_text())
            self.assertEqual(list(doc["issuers"]), ["MRVL"])
            self.assertEqual(len(doc["issuers"]["MRVL"]), check.KEEP)
            self.assertEqual(doc["issuers"]["MRVL"][-1]["checked_at"], "2026-09-28T09:00:00Z")
            before = out.read_bytes()
            reg.write_text("{broken")
            with self.assertRaises(ValueError):
                check.run(reg, out, NOW, sec(BASE_SEC), wire(BASE_WIRE))
            self.assertEqual(out.read_bytes(), before)


class ReleaseCheckIrChannelTests(unittest.TestCase):
    """Astra W1 ruling (astra-ir-coverage): the official IR channel is the third release-check channel. The fakes read
    the captured fixtures in tests/fixtures/ir-feeds/ shapes; nothing here touches the network."""

    CUTOFF = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    IR_TITLE = "Marvell Technology, Inc. Reports Second Quarter of Fiscal Year 2027 Financial Results"

    def ir_record(self, **overrides):
        rec = record(release_channels={"sec_cik": 1835632, "wire_symbol": "MRVL", "wire_names": ["Marvell"],
                                       "ir": {"kind": "RSS", "url": "https://investor.marvell.com/news-events/press-releases/rss"},
                                       "ir_guidance_release_title": self.IR_TITLE})
        # The BASE_SEC/BASE_WIRE fakes carry same-day (guidance-day) items, which stay ambiguous for review (Astra r5
        # item 2): the writer has reviewed both away, so the IR-channel cases read on their own merits.
        rec["reviewed_later_documents"] = [
            {"id": "0001-26-1", "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-09-28T09:00:00Z"},
            {"id": "https://www.nasdaq.com/press-release/2", "disposition": "REVIEWED_IRRELEVANT",
             "reviewed_at": "2026-09-28T09:00:00Z"},
        ]
        rec.update(overrides)
        return rec

    def rss_fetch(self, items):
        """items: (pub_date, title, link) tuples served as an RSS feed for the record's IR url."""
        def fetch(url):
            self.assertEqual(url, "https://investor.marvell.com/news-events/press-releases/rss")
            body = ("<rss><channel>" + "".join(
                f"<item><title>{t}</title><link>{l}</link><pubDate>{p}</pubDate></item>" for p, t, l in items) + "</channel></rss>")
            return body.encode("utf-8")
        return fetch

    def guidance_items(self):
        # The guidance release itself (on the reference date, titled exactly as the registry reviewed it) plus a
        # quiet later item and one item older than the reference date (the feed is complete).
        return [
            ("Wed, 27 Aug 2026 08:00:00 -0700", self.IR_TITLE,
             "https://investor.marvell.com/news-events/press-releases/detail/1001/"),
            ("Wed, 09 Sep 2026 08:00:00 -0700", "Marvell to Showcase Optical Demos",
             "https://investor.marvell.com/news-events/press-releases/detail/1002/"),
            ("Wed, 01 Jul 2026 08:00:00 -0700", "Marvell Introduces Products",
             "https://investor.marvell.com/news-events/press-releases/detail/1000/"),
        ]

    def test_ir_channel_ok_with_guidance_title_excluded(self):
        r = check.receipt_for(self.ir_record(), NOW, sec(BASE_SEC), wire(BASE_WIRE), self.rss_fetch(self.guidance_items()))
        self.assertEqual(r["status"], "OK")
        self.assertEqual(r["coverage"], "SEC_WIRE_IR")
        self.assertEqual([c["kind"] for c in r["channels"]], ["SEC_SUBMISSIONS", "WIRE_PRESS_RELEASES", "ISSUER_IR"])
        self.assertTrue(all(c["complete"] for c in r["channels"]))
        ir_later = [d for d in r["later_documents"] if d["channel"] == "ISSUER_IR"]
        # The guidance release itself is the reference point, not a later document; the quiet item is irrelevant.
        self.assertEqual(len(ir_later), 1)
        self.assertEqual(ir_later[0]["id"], "https://investor.marvell.com/news-events/press-releases/detail/1002/")
        self.assertEqual(ir_later[0]["disposition"], "IRRELEVANT")
        self.assertNotIn(self.IR_TITLE, [d["label"] for d in ir_later])

    def test_ir_results_release_after_guidance_suspends_the_path(self):
        # A later IR item carrying results language (before any SEC results filing) is a review item: the receipt is
        # REVIEW_REQUIRED and the real caller suspends the company-guidance path (never NOT_DISCLOSED, zero, consensus).
        items = self.guidance_items() + [
            ("Wed, 18 Sep 2026 08:00:00 -0700", "Marvell Reports Third Quarter Fiscal 2027 Financial Results",
             "https://investor.marvell.com/news-events/press-releases/detail/1003/"),
        ]
        r = check.receipt_for(self.ir_record(), NOW, sec(BASE_SEC), wire(BASE_WIRE), self.rss_fetch(items))
        self.assertEqual(r["status"], "REVIEW_REQUIRED")
        ir_later = [d for d in r["later_documents"] if d["channel"] == "ISSUER_IR"]
        self.assertEqual([d["disposition"] for d in ir_later], ["IRRELEVANT", "POSSIBLY_RELEVANT"])
        res = self._build_with_receipt(r)
        self.assertEqual((res["status"], res["reason"]), ("UNAVAILABLE", "STALE"))

    def test_same_day_extra_ir_item_needs_review(self):
        items = self.guidance_items() + [
            ("Wed, 27 Aug 2026 19:00:00 -0700", "Marvell Announces Conference Call to Discuss Results",
             "https://investor.marvell.com/news-events/press-releases/detail/1004/"),
        ]
        r = check.receipt_for(self.ir_record(), NOW, sec(BASE_SEC), wire(BASE_WIRE), self.rss_fetch(items))
        self.assertEqual(r["status"], "REVIEW_REQUIRED")
        same_day = [d for d in r["later_documents"] if d["channel"] == "ISSUER_IR" and d["date"] == "2026-08-27"]
        self.assertEqual([d["disposition"] for d in same_day], ["POSSIBLY_RELEVANT"])

    def test_reviewed_ir_item_is_ok(self):
        item_id = "https://investor.marvell.com/news-events/press-releases/detail/1005/"
        items = self.guidance_items() + [
            ("Wed, 18 Sep 2026 08:00:00 -0700", "Marvell Reports Third Quarter Fiscal 2027 Financial Results", item_id),
        ]
        rec = self.ir_record()
        rec["reviewed_later_documents"].append(
            {"id": item_id, "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-09-28T09:00:00Z",
             "note": "results release; the registry guidance is superseded by a new claim in the next revision"})
        r = check.receipt_for(rec, NOW, sec(BASE_SEC), wire(BASE_WIRE), self.rss_fetch(items))
        self.assertEqual(r["status"], "OK")
        self.assertEqual(
            [d["disposition"] for d in r["later_documents"] if d["channel"] == "ISSUER_IR" and d["id"] == item_id],
            ["REVIEWED_IRRELEVANT"])

    def test_incomplete_rss_is_unverified(self):
        # The feed's newest item does not reach back to the reference date: incomplete, never "no release".
        items = [
            ("Wed, 18 Sep 2026 08:00:00 -0700", "Marvell Reports Third Quarter Fiscal 2027 Financial Results",
             "https://investor.marvell.com/news-events/press-releases/detail/1003/"),
        ]
        r = check.receipt_for(self.ir_record(), NOW, sec(BASE_SEC), wire(BASE_WIRE), self.rss_fetch(items))
        self.assertEqual(r["status"], "FRESHNESS_UNVERIFIED")
        self.assertFalse(r["channels"][2]["complete"])

    def test_failed_ir_channel_is_unverified(self):
        def boom(url):
            raise OSError("IR site unreachable")
        r = check.receipt_for(self.ir_record(), NOW, sec(BASE_SEC), wire(BASE_WIRE), boom)
        self.assertEqual(r["status"], "FRESHNESS_UNVERIFIED")
        self.assertEqual(r["channels"][2]["status"], "FAILED")

    def test_ir_url_on_another_host_is_refused(self):
        # A receipt whose ISSUER_IR channel reads a feed host the registry did not review is not the issuer's own
        # channel: it fails closed (the distinct IR_COVERAGE_MISSING diagnostic does not apply: the coverage label
        # itself is present, the channel identity is not).
        rec = self.ir_record()
        base = check.receipt_for(rec, NOW, sec(BASE_SEC), wire(BASE_WIRE), self.rss_fetch(self.guidance_items()))
        forged = json.loads(json.dumps(base))
        forged["channels"][2]["url"] = "https://feeds.mirror.example/rss"
        forged["digest"] = revenue_guidance.compute_receipt_digest(forged)
        valid, status, err = revenue_guidance.validate_receipt(
            forged, "MRVL", "2026-08-01", "MRVL-GUIDANCE", self.CUTOFF,
            rec.get("reviewed_later_documents"), "2026-08-27",
            expected_ir=rec["release_channels"]["ir"])
        # The stored OK status no longer recomputes: the channel-identity tamper surfaces as a status recompute
        # mismatch, and the distinct IR_COVERAGE_MISSING diagnostic does not apply (the coverage label matched).
        self.assertFalse(valid)
        self.assertIn(status, ("INVALID", "FRESHNESS_UNVERIFIED"))
        self.assertNotEqual(err, "IR_COVERAGE_MISSING")

    def test_issuer_without_ir_channel_gets_ir_coverage_missing(self):
        # The real caller: a record without a reviewed IR channel (classic SEC_AND_WIRE receipt) suspends the
        # company-guidance revenue path with the distinct diagnostic (Astra W1 ruling).
        record_full = {
            "symbol": "SNDK", "company_name": "Sandisk Corporation", "status": "GUIDANCE",
            "url_prefixes": ["https://investor.sandisk.com/"],
            "documents": [{"id": "SNDK-GUIDANCE", "issuer": "SNDK", "publisher": "Sandisk Corporation",
                           "source_kind": "SEC_8K_EXHIBIT", "url": "https://www.sec.gov/Archives/edgar/data/x.htm",
                           "published_date": "2026-08-05", "retrieved_at": "2026-08-05T12:00:00Z",
                           "sha256": "0" * 64, "byte_size": 1000, "lineage_id": "L1"}],
            "claims": [{"id": "SNDK-Q", "document_id": "SNDK-GUIDANCE", "locator": "Outlook", "passage": "x",
                         "metric": "REVENUE", "assertion_kind": "COMPANY_GUIDANCE", "currency": "USD",
                         "unit_multiplier": 1, "stated_point": 10.5, "scope": "COMPANY", "accounting_basis": "GAAP",
                         "fiscal_label": "Q1 FY27", "period_kind": "QUARTER", "period_start": "2026-07-04",
                         "period_end": "2026-10-02"}],
            "reported_quarters": [
                {"fiscal_label": "Q1 FY26", "start": "2025-07-04", "end": "2025-10-03", "revenue": 2.0e9,
                 "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "SNDK-GUIDANCE", "locator": "p.1"},
                {"fiscal_label": "Q2 FY26", "start": "2025-10-04", "end": "2026-01-02", "revenue": 3.0e9,
                 "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "SNDK-GUIDANCE", "locator": "p.1"},
                {"fiscal_label": "Q3 FY26", "start": "2026-01-03", "end": "2026-04-03", "revenue": 5.0e9,
                 "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "SNDK-GUIDANCE", "locator": "p.1"},
                {"fiscal_label": "Q4 FY26", "start": "2026-04-04", "end": "2026-07-03", "revenue": 8.0e9,
                 "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "SNDK-GUIDANCE", "locator": "p.1"},
            ],
            "forward_intervals": [
                {"fiscal_label": "Q1 FY27", "start": "2026-07-04", "end": "2026-10-02"},
                {"fiscal_label": "Q2 FY27", "start": "2026-10-03", "end": "2027-01-01"},
                {"fiscal_label": "Q3 FY27", "start": "2027-01-02", "end": "2027-04-02"},
                {"fiscal_label": "Q4 FY27", "start": "2027-04-03", "end": "2027-07-02"}],
            "release_channels": {"sec_cik": 2023554, "wire_symbol": "SNDK", "wire_names": ["Sandisk"]},
        }
        receipt = {
            "issuer": "SNDK", "checked_at": "2026-09-28T11:00:00Z", "status": "OK",
            "guidance_document_id": "SNDK-GUIDANCE", "guidance_published_date": "2026-08-05", "anchor_end": "2026-07-03",
            "coverage": "SEC_AND_WIRE",
            "channels": [
                {"kind": "SEC_SUBMISSIONS", "url": "https://data.sec.gov/submissions/CIK0002023554.json",
                 "status": "OK", "checked_through": "2026-09-28", "complete": True},
                {"kind": "WIRE_PRESS_RELEASES",
                 "url": "https://api.nasdaq.com/api/news/topic/press_release?q=symbol:sndk|assetclass:stocks",
                 "status": "OK", "checked_through": "2026-09-28", "complete": True},
            ],
            "later_documents": [],
        }
        receipt["digest"] = revenue_guidance.compute_receipt_digest(receipt)
        cache = {"schema": "revenue-guidance-release-checks-v1", "generated_at": "2026-09-28T11:00:00Z",
                 "issuers": {"SNDK": [receipt]}}
        res = revenue_guidance.build_forward_quarters("SNDK", record_full, self.CUTOFF, cache)
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "FRESHNESS_UNVERIFIED")
        self.assertEqual(res["diagnostic"], "IR_COVERAGE_MISSING")

    def _build_with_receipt(self, receipt):
        """Run the real caller (build_forward_quarters) with a collector-built receipt on the IR record."""
        rec = self.ir_record()
        # A minimal complete record shape around the MRVL claim so the model reaches the receipt stage.
        rec["documents"][0].update({"id": "MRVL-GUIDANCE", "issuer": "MRVL", "publisher": "Marvell Technology, Inc.",
                                    "title": "Q2 release", "source_kind": "SEC_8K_EXHIBIT",
                                    "url": "https://www.sec.gov/Archives/edgar/data/x.htm",
                                    "retrieved_at": "2026-08-27T12:00:00Z", "sha256": "0" * 64,
                                    "byte_size": 1000, "lineage_id": "L1"})
        rec["claims"][0].update({"period_start": "2026-08-02", "period_end": "2026-11-01",
                                 "fiscal_label": "Q1 FY27", "locator": "p.1", "passage": "x"})
        rec["reported_quarters"] = [
            {"fiscal_label": "Q1 FY26", "start": "2025-05-29", "end": "2025-08-28", "revenue": 4.0e9, "currency": "USD",
             "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "MRVL-GUIDANCE", "locator": "p.1"},
            {"fiscal_label": "Q2 FY26", "start": "2025-08-29", "end": "2025-11-28", "revenue": 4.5e9, "currency": "USD",
             "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "MRVL-GUIDANCE", "locator": "p.1"},
            {"fiscal_label": "Q3 FY26", "start": "2025-11-29", "end": "2026-02-27", "revenue": 5.0e9, "currency": "USD",
             "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "MRVL-GUIDANCE", "locator": "p.1"},
            {"fiscal_label": "Q4 FY26", "start": "2026-02-28", "end": "2026-08-01", "revenue": 6.0e9, "currency": "USD",
             "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "MRVL-GUIDANCE", "locator": "p.1"},
        ]
        rec["forward_intervals"] = [
            {"fiscal_label": "Q1 FY27", "start": "2026-08-02", "end": "2026-11-01"},
            {"fiscal_label": "Q2 FY27", "start": "2026-11-02", "end": "2027-01-31"},
            {"fiscal_label": "Q3 FY27", "start": "2027-02-01", "end": "2027-04-30"},
            {"fiscal_label": "Q4 FY27", "start": "2027-05-01", "end": "2027-07-31"},
        ]
        cache = {"schema": "revenue-guidance-release-checks-v1", "generated_at": receipt["checked_at"],
                 "issuers": {"MRVL": [receipt]}}
        return revenue_guidance.build_forward_quarters("MRVL", rec, NOW, cache)


if __name__ == "__main__":
    unittest.main()


class ReleaseCheckConservativeIrTests(ReleaseCheckIrChannelTests):
    """Astra final review A2: the executed counterexamples - an explicit withdrawal of financial targets without the
    old keywords, an empty feed answer and a truncated RSS body - must not certify current coverage."""

    def test_withdrawal_of_financial_targets_is_a_review_item(self):
        items = self.guidance_items() + [("Thu, 28 Aug 2026 08:00:00 -0700", "Marvell Withdraws Its Financial Targets",
                                          "https://investor.marvell.com/news-events/press-releases/detail/1005/")]
        r = check.receipt_for(self.ir_record(), NOW, sec(BASE_SEC), wire(BASE_WIRE), self.rss_fetch(items))
        self.assertEqual(r["status"], "REVIEW_REQUIRED")
        self.assertEqual(self._build_with_receipt(r)["status"], "UNAVAILABLE")

    def test_a_feed_without_the_reviewed_guidance_release_is_incomplete(self):
        items = [item for item in self.guidance_items() if item[1] != self.IR_TITLE]
        r = check.receipt_for(self.ir_record(), NOW, sec(BASE_SEC), wire(BASE_WIRE), self.rss_fetch(items))
        self.assertEqual(r["status"], "FRESHNESS_UNVERIFIED")
        self.assertFalse([c for c in r["channels"] if c["kind"] == "ISSUER_IR"][0]["complete"])

    def test_an_empty_or_truncated_feed_never_renews_coverage(self):
        def empty(url):
            return b"<rss><channel></channel></rss>"

        def truncated(url):
            body = self.rss_fetch(self.guidance_items())(url).decode("utf-8")
            return (body[:-len("</channel></rss>")] + "<item><title>Marvell Announces Preliminary Results").encode("utf-8")
        for fetch in (empty, truncated):
            r = check.receipt_for(self.ir_record(), NOW, sec(BASE_SEC), wire(BASE_WIRE), fetch)
            self.assertEqual(r["status"], "FRESHNESS_UNVERIFIED", fetch.__name__)
            self.assertEqual(self._build_with_receipt(r)["status"], "UNAVAILABLE", fetch.__name__)


class MaterialTitleTests(unittest.TestCase):
    def test_title_table(self):
        relevant = ["NVIDIA Withdraws Its Financial Targets", "X Announces Quarterly Results and Conference Call",
                    "X Reports Record Second Quarter 2026 Financial Results", "X Updates Full-Year Outlook",
                    "X Reaffirms Fiscal 2027 Guidance", "X Announces Preliminary Third Quarter Revenue", "X Provides Business Update",
                    "X Lowers Revenue Expectations", "X updates guidance at annual meeting",
                    # Astra r7 A2: compound material statements take precedence over scheduling/dividend wording
                    "NVIDIA Reports Record Revenue and Announces Conference Call",
                    "NVIDIA Reports Quarterly Earnings and Declares Dividend", "NVIDIA Announces Revenue of $110 Billion and Webcast",
                    # Astra r8 A2: meeting outcomes and release dates in another clause never erase reported figures
                    "NVIDIA Reports Record Revenue and Announces Date of Conference Call",
                    "NVIDIA Reports Quarterly Earnings and Announces Results of Its Annual General Meeting",
                    "NVIDIA Announces Revenue of $110 Billion and Date of Webcast",
                    "NVIDIA to Report Results and Reaffirms Guidance", "NVIDIA Reports Revenue, Announces Date of Third Quarter Results",
                    "Sandisk Details Growth Strategy and Long-Term Financial Model at 2026 Investor Day",
                    # Astra r9 A2: "to report" with figures, growth or an expectation is never a scheduling notice
                    "NVIDIA Expects to Report Revenue of $100 Billion", "NVIDIA Expects to Report a 20% Decline in Revenue",
                    "NVIDIA to Report Revenue of $100 Billion", "NVIDIA Will Report Record Revenue",
                    "NVIDIA to Report Third Quarter Revenue Above Guidance", "NVIDIA to Report Revenue Growth of 50%",
                    "NVIDIA Anticipates Third Quarter Revenue Below Outlook",
                    # Astra r10 A2: only a whole known notice is exempt; figures after punctuation, "&" or a date keep the review
                    "NVIDIA to Report Third Quarter Revenue, Up 50% Year over Year", "NVIDIA to Report Third Quarter Revenue: $100 Billion",
                    "NVIDIA to Report Third Quarter Results; Revenue Up 50%",
                    "NVIDIA to Report Third Quarter Results on November 18, 2026, Revenue $100 Billion",
                    "NVIDIA to Report Third Quarter Results and Record Revenue", "NVIDIA Third Quarter: $100 Billion", "NVIDIA Q3 Up 50%",
                    "NVIDIA to Report Third Quarter Results & Raises Outlook", "NVIDIA to Report Third Quarter Results Above Expectations"]
        irrelevant = ["Micron Technology to Report Fiscal Fourth Quarter Results on September 30, 2026",
                      "Nebius Group N.V. announces results of its Annual General Meeting",
                      "Marvell Technology, Inc. Declares Quarterly Dividend Payment", "NVIDIA Announces Upcoming Event for Financial Community",
                      "Credo to Showcase 1.6T Optical Connectivity Solutions", "CoreWeave Announces At-the-Market Offering Program",
                      "NVIDIA Announces a $150 Billion Share Repurchase Authorization Increase", "Nebius to participate in upcoming investor conferences",
                      "Nebius Group announces date of second quarter 2026 results and conference call",
                      "Marvell Technology, Inc. Announces Conference Call to Review Second Quarter Results",
                      "AWS and NVIDIA to Deliver 2 Million Additional GPUs and Next-Generation Infrastructure for Agentic and Physical AI",
                      "Lumentum to Announce Fiscal First Quarter 2027 Results", "AMD to Report Fiscal Third Quarter 2026 Financial Results",
                      "Credo to Report First Quarter Fiscal Year 2027 Financial Results on September 2, 2026"]
        for title in relevant:
            self.assertTrue(check.is_wire_title_possibly_relevant(title), title)
        for title in irrelevant:
            self.assertFalse(check.is_wire_title_possibly_relevant(title), title)
