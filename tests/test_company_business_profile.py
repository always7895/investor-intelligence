from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_v212_top20_report as builder  # noqa: E402
import company_business_profile as profile  # noqa: E402
from report_source_acquisition import field_clock, row_time  # noqa: E402

SELF = ("Acme Materials is a materials science company that develops and manufactures "
        "compound semiconductor substrates used in optical and wireless devices.")
FILING = ("<html><body><p>Table of Contents Item 1. Business 3 Item 1A. Risk Factors 12</p>"
          "<p>Item 1. Business</p><p>Overview We were incorporated in Delaware in 1986 and our "
          "headquarters are located in California near our main plant.</p><p>" + SELF +
          "</p><p>We sell through direct sales teams and distributors in three regions of the world.</p>"
          "</body></html>").encode("utf-8")
SUBMISSIONS = {"sic": "3674", "sicDescription": "Semiconductors & Related Devices", "filings": {"recent": {
    "form": ["8-K", "10-Q", "10-K"], "filingDate": ["2026-08-01", "2026-07-30", "2026-03-01"],
    "accessionNumber": ["0000000001-26-000003", "0000000001-26-000002", "0000000001-26-000001"],
    "primaryDocument": ["a.htm", "q.htm", "k.htm"]}}}
PHRASE = "開發及生產化合物半導體基板"


def fake_fetch(url: str) -> bytes:
    if url.startswith("https://data.sec.gov/submissions/"):
        return json.dumps(SUBMISSIONS).encode("utf-8")
    if url.endswith("/k.htm"):
        return FILING
    raise AssertionError(f"unexpected url {url}")


class BusinessSentenceTests(unittest.TestCase):
    def test_table_of_contents_is_skipped_and_self_description_wins(self):
        self.assertEqual(profile.business_sentence(profile.business_text(FILING)), SELF)

    def test_20f_heading_is_supported(self):
        text = "Item 4. Information on the Company A. History. " + SELF.replace("Acme Materials", "Acme Holding")
        self.assertIn("compound semiconductor substrates", profile.business_sentence(text))

    def test_activity_sentence_is_the_fallback_and_missing_heading_is_none(self):
        text = "Item 1. Business We design and sell programmable logic devices to data center and industrial customers."
        self.assertIn("programmable logic devices", profile.business_sentence(text))
        self.assertIsNone(profile.business_sentence("Annual report without the required section headings at all."))

    def test_overview_excerpt_is_used_when_no_self_description_exists(self):
        text = ("Item 1. Business Cautionary Statement Regarding Forward-Looking Statements These statements are "
                "forward-looking. Overview At Acme, our mission is to transform connectivity at scale for data centers. "
                "The Company’s copper and optical interconnect products deliver power efficiency for AI clusters. "
                "We are headquartered in San Jose, California, with offices in Asia and Europe.")
        excerpt = profile.business_sentence(text, "Acme Technology Group Holding Ltd", ["ACME"])
        self.assertTrue(excerpt.startswith("At Acme, our mission"))
        self.assertIn("optical interconnect products", excerpt)
        self.assertNotIn("headquartered", excerpt)

    def test_ticker_subject_long_list_clip_and_auditor_text(self):
        text = ("Item 1. Business Overview AMD is a global semiconductor company offering " + ", ".join(
            f"product line {i} for data centers and embedded systems" for i in range(12)) + ". "
                "We are a public accounting firm registered with the PCAOB and are independent of the Company.")
        sentence = profile.business_sentence(text, "ADVANCED MICRO DEVICES INC", ["AMD"])
        self.assertTrue(sentence.startswith("AMD is a global semiconductor company offering"))
        self.assertLessEqual(len(sentence), 400)
        auditor = ("Report of Independent Registered Public Accounting Firm. We are a public accounting firm "
                   "registered with the PCAOB and are required to be independent with respect to the Company.")
        self.assertIsNone(profile.business_sentence(auditor, "Acme Corp", ["ACME"]))

    def test_latest_annual_filing_selects_newest_10k_or_20f(self):
        filing = profile.latest_annual_filing(SUBMISSIONS, "0000000001")
        self.assertEqual(filing["form"], "10-K")
        self.assertEqual(filing["url"], "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/k.htm")
        none = {"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-01-01"],
                                       "accessionNumber": ["x"], "primaryDocument": ["a.htm"]}}}
        self.assertIsNone(profile.latest_annual_filing(none, "0000000001"))


class ResolveProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.urls: list[str] = []
        self.translations: list[str] = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url):
        self.urls.append(url)
        return fake_fetch(url)

    def translate(self, sentence):
        self.translations.append(sentence)
        return PHRASE

    def resolve(self, translate=None):
        return profile.resolve_business_profile("0000000001", self.fetch, translate, cache_root=self.root,
                                                now=lambda: "2026-09-25T01:00:00Z")

    def test_profile_binds_document_and_index_and_rejects_bad_cik(self):
        record = self.resolve(self.translate)
        self.assertEqual((record["sentence_en"], record["phrase_zh"]), (SELF, PHRASE))
        self.assertEqual(record["sic_description"], "Semiconductors & Related Devices")
        self.assertEqual(record["retrieved_at"], "2026-09-25T01:00:00Z")
        self.assertNotEqual(record["evidence_sha256"], record["document_sha256"])
        with self.assertRaises(ValueError):
            profile.resolve_business_profile("1", self.fetch, None, cache_root=self.root)

    def test_same_accession_reuses_document_and_translation_but_rechecks_index(self):
        self.resolve(self.translate)
        self.urls.clear()
        again = self.resolve(self.translate)
        self.assertEqual(self.urls, ["https://data.sec.gov/submissions/CIK0000000001.json"])
        self.assertEqual((again["phrase_zh"], len(self.translations)), (PHRASE, 1))

    def test_failed_translation_is_retried_and_tampered_cache_is_revalidated(self):
        self.assertEqual(self.resolve(lambda sentence: None)["translation"], "UNAVAILABLE")
        self.assertEqual(self.resolve(self.translate)["phrase_zh"], PHRASE)
        cache = self.root / "CIK0000000001.json"
        cache.write_text(json.dumps({**json.loads(cache.read_text(encoding="utf-8")), "phrase_zh": "很多基板"}),
                         encoding="utf-8")
        self.assertEqual(self.resolve(None)["translation"], "UNAVAILABLE")

    def test_new_accession_fetches_the_new_annual_report(self):
        self.resolve(self.translate)
        newer = json.loads(json.dumps(SUBMISSIONS))
        newer["filings"]["recent"]["accessionNumber"][2] = "0000000001-27-000001"
        self.urls.clear()
        with patch(f"{__name__}.SUBMISSIONS", newer):
            self.resolve(self.translate)
        self.assertEqual(len(self.urls), 2)
        self.assertEqual(len(self.translations), 2)

    def test_sec_fetcher_admits_only_sec_https_and_fences_after_403(self):
        from urllib.error import HTTPError

        class Opener:
            calls = 0

            def open(self, request, timeout):
                Opener.calls += 1
                raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

        with patch.object(profile, "build_opener", return_value=Opener()):
            fetch = profile.sec_fetcher({"User-Agent": "test"}, min_interval=0)
            with self.assertRaises(ValueError):
                fetch("https://example.com/a.json")
            for _ in range(2):
                with self.assertRaises(profile.ProfileBlocked):
                    fetch("https://data.sec.gov/submissions/CIK0000000001.json")
        self.assertEqual(Opener.calls, 1)


class PhraseTests(unittest.TestCase):
    def test_valid_phrase_is_cleaned(self):
        self.assertEqual(profile.validate_phrase("<think>x</think>「" + PHRASE + "。」", SELF), PHRASE)

    def test_invented_numbers_vague_words_english_and_length_are_rejected(self):
        for bad in ("年產3000萬片化合物半導體基板", "很多化合物半導體基板產品", "compound substrates maker",
                    "化合物" * 20, "基板", "化合物半導體\n基板", "化合物｜半導體基板"):
            self.assertIsNone(profile.validate_phrase(bad, SELF), bad)
        self.assertEqual(profile.validate_phrase("三大區域銷售1986年成立", "founded in 1986 in three regions"),
                         "三大區域銷售1986年成立")

    def test_compose_keeps_worker_limit(self):
        self.assertEqual(profile.compose_industry("半導體設備與材料", PHRASE), "半導體設備與材料：" + PHRASE)
        self.assertEqual(profile.compose_industry("半導體", None), "半導體")
        self.assertEqual(len(profile.compose_industry("半" * 90, "基" * 40)), profile.MAX_INDUSTRY_CHARS)

    def test_translator_refuses_non_loopback_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "runtime.json"
            config.write_text(json.dumps({"primary_reasoner": {"base_url": "https://example.com/v1", "model": "m"}}),
                              encoding="utf-8")
            with self.assertRaises(ValueError):
                profile.local_translator(config)


class SelectorRegressionTests(unittest.TestCase):
    """Failure patterns seen 2026-09-25 on a non-technology Top20 (shortened synthetic excerpts)."""

    def pick(self, text: str, name: str, tickers=("SYN",)) -> str | None:
        return profile.business_sentence(text, name, list(tickers))

    def test_combined_heading_parentheticals_and_engaged_in(self):
        text = ("Items 1 and 2. Business and Properties Our Company Synthetic Resources Corporation (individually "
                "referred to as “Synthetic”) and its consolidated subsidiaries (collectively referred to as the "
                "“Company,” “we” or “our”) are engaged in the development, production and exploration of natural gas "
                "properties located in one basin. Synthetic Midstream is a growth-oriented midstream energy company "
                "formed to own and operate gathering assets.")
        chosen = self.pick(text, "SYNTHETIC RESOURCES Corp")
        self.assertTrue(chosen.startswith("Synthetic Resources Corporation and its consolidated subsidiaries are engaged in"), chosen)
        self.assertNotIn("Midstream", chosen)  # an affiliate is not the registrant

    def test_incorporation_clause_and_accounting_sentences(self):
        text = ("Item 1. Business Introduction Synthetic Gold Corporation was incorporated in 1921 and is primarily a gold "
                "producer with operations in three countries. The Company presented these assets as held for sale and "
                "recorded them at the lower of their carrying value or fair value, less costs to sell.")
        self.assertEqual(self.pick(text, "SYNTHETIC GOLD Corp /DE/"),
                         "Synthetic Gold Corporation is primarily a gold producer with operations in three countries.")

    def test_abbreviation_does_not_end_the_sentence(self):
        text = ("Item 1. Business Synthetic Mining, Inc. (“Synthetic”, “the Company”, or “we”), founded in 1928, is a "
                "precious metals producer with assets located in the U.S. and Mexico.")
        self.assertEqual(self.pick(text, "SYNTHETIC MINING, INC."),
                         "Synthetic Mining, Inc., founded in 1928, is a precious metals producer with assets located in the U.S. and Mexico.")

    def test_holding_company_statement_with_subsidiaries(self):
        text = ("Item 1. BUSINESS The Synthetic Companies, Inc. (together with its subsidiaries, collectively, the Company) "
                "is a holding company principally engaged, through its subsidiaries, in providing property and casualty "
                "insurance products. The Company is an integral part of its business operations.")
        chosen = self.pick(text, "SYNTHETIC COMPANIES, INC.")
        self.assertIn("is a holding company principally engaged, through its subsidiaries, in providing", chosen)

    def test_cross_reference_index_is_skipped_for_a_self_description_elsewhere(self):
        text = ("Item 4. Information on the company A. History and development of the company Disclaimer (Documents on "
                "Display); About Us (About us; Overview) 6, 23, 25 B. Business overview. " + "Filler text. " * 50 +
                "We are a Brazilian partially state-owned company and one of the world’s largest oil and gas producers.")
        self.assertEqual(self.pick(text, "SYNTHETIC ENERGY SA"),
                         "We are a Brazilian partially state-owned company and one of the world’s largest oil and gas producers.")

    def test_lowercase_words_are_not_part_of_the_company_name(self):
        text = ("Item 1. Business Synthetic Buy Marketplace, where there is a risk that third-party sellers fail, may "
                "affect our reputation. Both segments operate an omnichannel platform that allows customers to shop "
                "online or visit our stores.")
        self.assertNotIn("where there is a risk", self.pick(text, "SYNTHETIC BUY CO INC") or "")

    def test_activity_less_statement_takes_the_next_same_subject_sentence(self):
        text = ("Item 1. Business OUR COMPANY General Synthetic Capital is a publicly listed Bermuda exempted company with "
                "approximately $26.9 billion in capital and is part of the S&P 500 index. Synthetic provides insurance, "
                "reinsurance and mortgage insurance on a worldwide basis.")
        self.assertEqual(self.pick(text, "SYNTHETIC CAPITAL GROUP LTD."),
                         "Synthetic Capital is a publicly listed Bermuda exempted company with approximately $26.9 billion in "
                         "capital. Synthetic provides insurance, reinsurance and mortgage insurance on a worldwide basis.")

    def test_vague_quantity_is_rejected(self):
        sentence = "We are the largest discount retailer in the United States by number of stores, with 20,959 stores."
        self.assertIsNone(profile.validate_phrase("美國折扣零售商，經營數萬家門店", sentence))
        self.assertEqual(profile.validate_phrase("美國折扣零售商，經營20,959家門店", sentence), "美國折扣零售商，經營20,959家門店")

    def test_simplified_chinese_phrase_is_rejected(self):
        self.assertIsNone(profile.validate_phrase("訴訟指控存在固有不确定性", "The allegations are subject to uncertainties."))
        self.assertEqual(profile.validate_phrase("美國、加拿大、墨西哥貴金屬生產商", "precious metals producer"),
                         "美國、加拿大、墨西哥貴金屬生產商")

    def test_translator_asks_once_more_after_a_failure(self):
        replies = [OSError("timed out"), json.dumps({"choices": [{"message": {"content": "貴金屬生產商"}}]}).encode()]

        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def read(self): return self.body

        class Opener:
            def open(self, request, timeout):
                reply = replies.pop(0)
                if isinstance(reply, Exception):
                    raise reply
                return Response(reply)

        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "runtime.json"
            config.write_text(json.dumps({"primary_reasoner": {"base_url": "http://127.0.0.1:5000/v1", "model": "local"}}),
                              encoding="utf-8")
            with patch.object(profile, "build_opener", return_value=Opener()):
                translate = profile.local_translator(config)
                self.assertEqual(translate("Synthetic is a precious metals producer."), "貴金屬生產商")
        self.assertEqual(replies, [])


class ReportIntegrationTests(unittest.TestCase):
    def report(self, *, translate, label_clock: bool, _build=None, **kwargs):
        rows = [{"ticker": f"T{i:02}", "rank": i + 1} for i in range(20)]

        def market(ticker, fallback, *, evidence_sink=None):
            if label_clock:
                evidence_sink["source_acquisition"] = {"industry": field_clock(
                    "industry", "半導體設備與材料", retrieved_at="2026-09-25T00:00:00Z", evidence_sha256="a" * 64)}
            return None, None, "半導體設備與材料"

        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            source = Path(tmp) / "top20.json"
            source.write_text("[]", encoding="utf-8")
            stack.enter_context(patch.object(builder.snapshot, "validate_top20", return_value=rows))
            policy = {"sec_companyfacts_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                      "sec_minimum_interval_seconds": 0}
            for name, value in [("validate_policy", (policy, {})), ("sec_headers", {}), ("session", None),
                                ("sec_reference", {r["ticker"]: {"cik": "1"} for r in rows}),
                                ("sec_companyfacts", [])]:
                stack.enter_context(patch.object(builder.base, name, return_value=value))
            stack.enter_context(patch.object(builder, "_market_observation", side_effect=market))
            sink = kwargs.pop("business_profile_sink", {})
            document = (_build or builder.build)(top20_path=source, translate=translate, business_profile_sink=sink,
                                                 profile_fetch=fake_fetch, profile_cache_root=Path(tmp) / "profiles",
                                                 **kwargs)
            return document, sink

    def test_receipted_label_is_composed_with_sec_phrase(self):
        document, sink = self.report(translate=lambda sentence: PHRASE, label_clock=True)
        row = document["records"][0]
        self.assertEqual(row["industry"], "半導體設備與材料：" + PHRASE)
        clock = row["source_acquisition"]["industry"]
        self.assertEqual((clock["status"], clock["retrieved_at"]), ("KNOWN", "2026-09-25T00:00:00Z"))
        self.assertEqual(sink["T00"]["phrase_zh"], PHRASE)
        self.assertEqual(sink["T00"]["url"], "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/k.htm")
        row_time(row, generated_at=document["generated_at"])

    def test_composed_industry_passes_the_seven_field_caller_and_preview(self):
        import build_v213_scheduled_top20_report as scheduled
        document, _ = self.report(translate=lambda sentence: PHRASE, label_clock=True)
        baseline = {"product_version": "2.1.3", "records": [
            {"rank": row["rank"], "ticker": row["ticker"], "current_order_source_urls": [],
             "future_order_source_urls": [], "current_orders": "未揭露（無可靠公開訂單數字）",
             "future_orders_estimate": "無可靠公開預估", "orders_confidence": "UNAVAILABLE", "orders_as_of": ""}
            for row in document["records"]]}
        names = {row["ticker"]: f"Synthetic Company {i}" for i, row in enumerate(document["records"])}
        seven = scheduled.build(document, baseline, names)
        self.assertEqual(seven["records"][0]["industry"], "半導體設備與材料：" + PHRASE)
        self.assertIn("半導體設備與材料：" + PHRASE, scheduled.preview(seven))

    def test_unreceipted_label_is_replaced_by_sourced_phrase(self):
        document, sink = self.report(translate=lambda sentence: PHRASE, label_clock=False)
        row = document["records"][0]
        self.assertEqual(row["industry"], PHRASE)
        self.assertEqual(row["source_acquisition"]["industry"]["evidence_sha256"], sink["T00"]["evidence_sha256"])

    def test_failed_or_invalid_translation_keeps_label_and_records_failure(self):
        for translate in (lambda sentence: None, lambda sentence: "市場很大的化合物半導體基板"):
            document, sink = self.report(translate=translate, label_clock=False)
            self.assertEqual(document["records"][0]["industry"], "半導體設備與材料")
            self.assertEqual(document["records"][0]["source_acquisition"]["industry"]["status"], "UNKNOWN")
            self.assertEqual(sink["T00"]["translation"], "UNAVAILABLE")

    def test_cli_profile_is_opt_in_and_sidecar_is_not_publishable(self):
        original = builder.build
        calls = []

        def run(**kw):
            calls.append(kw["translate"])
            return self.report(label_clock=False, _build=original, **kw)[0]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            with patch.object(builder, "build", side_effect=run), \
                    patch.object(sys, "argv", ["build", "--output", str(output)]), \
                    redirect_stdout(StringIO()):
                self.assertEqual(builder.main(), 0)
            self.assertEqual(calls, [None])
            sidecar = json.loads((Path(tmp) / "report.business-profile-candidate.json").read_text(encoding="utf-8"))
            self.assertFalse(sidecar["publication_eligible"])
            self.assertEqual(sidecar["status"], "CANDIDATE_NOT_PUBLICATION_QUALIFIED")
            with patch.object(builder, "build", side_effect=run), \
                    patch.object(builder, "local_translator", return_value=lambda sentence: PHRASE), \
                    patch.object(sys, "argv", ["build", "--output", str(output), "--business-profile"]), \
                    redirect_stdout(StringIO()):
                self.assertEqual(builder.main(), 0)
            self.assertIsNotNone(calls[-1])
            sidecar = json.loads((Path(tmp) / "report.business-profile-candidate.json").read_text(encoding="utf-8"))
            self.assertEqual(sidecar["records"]["T00"]["phrase_zh"], PHRASE)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["records"][0]["industry"], PHRASE)


if __name__ == "__main__":
    unittest.main()
