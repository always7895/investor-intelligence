"""Tests for ECBFxReferenceAdapter.

Source: https://www.ecb.europa.eu/rss/fxref-usd.html
License: http://www.ecb.europa.eu/home/html/disclaimer.en.html
Canonical terms: https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html
Provenance: Exact snapshot from 2026-09-14 review (ecb-fxref-usd-public.xml).
Free reproduction permitted with attribution to European Central Bank.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

SOURCE_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SOURCE_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from adapters.base import AdapterError  # noqa: E402
import adapters.ecb_fx_reference as ecb_mod  # noqa: E402
from adapters.ecb_fx_reference import ECBFxReferenceAdapter, NS, REQUEST_URL  # noqa: E402

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "ecb-fxref-usd.xml"
with open(FIXTURE_PATH, "rb") as f:
    FIXTURE_BYTES = f.read()

VALID_RETRIEVAL = "2026-09-14T10:00:00+00:00"
VALID_CTX = {"request_url": REQUEST_URL}
CANONICAL_TERMS = "https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html"


def mutate(old: str, new: str, count: int = -1) -> bytes:
    return FIXTURE_BYTES.replace(old.encode("utf-8"), new.encode("utf-8"), count)


class TestECBFxReferenceAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ECBFxReferenceAdapter()

    def test_01_fixture_latest_and_provenance(self) -> None:
        # Actual publisher bytes, including whitespace; never restamp or normalize.
        self.assertEqual(hashlib.sha256(FIXTURE_BYTES).hexdigest(),
                         "2f875f1ce9a154c15b4a97174d90a481aa7ab6ab6e7f7cae167ee0f1363330e4")
        batch = self.adapter.parse(FIXTURE_BYTES, content_type="application/rss+xml",
                                  retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)
        self.assertEqual(batch.record_count, 1)
        self.assertEqual(batch.content_sha256, hashlib.sha256(FIXTURE_BYTES).hexdigest())
        rec = batch.records[0]
        self.assertEqual(rec["published_at"], "2026-09-11T13:15:00+00:00")
        p = rec["payload"]
        self.assertEqual(p["value"], 1.1592)
        self.assertEqual(p["period"], "2026-09-11")
        self.assertEqual(p["source_published_timestamp"], "2026-09-11T14:15:00+01:00")
        self.assertEqual(p["as_of"], "2026-09-11T00:00:00Z")
        self.assertTrue(p["information_only"])
        self.assertTrue(p["no_endorsement"])
        self.assertFalse(p["execution_eligible"])
        self.assertFalse(p["issuer_claim_verified"])
        self.assertFalse(p["full_history_verified"])
        self.assertEqual(p["claim_ids"], ["ecb.fxref.EUR.USD.2026-09-11"])
        self.assertEqual(p["origin_group"], "ecb_euro_reference_rates:2026-09-11")
        self.assertEqual(p["returned_item_count"], 5)
        self.assertEqual(p["selected_reference_date"], "2026-09-11")
        self.assertEqual(p["terms_url"], CANONICAL_TERMS)
        self.assertEqual(p["official_terms_url"], CANONICAL_TERMS)
        self.assertNotIn("source_health", rec)
        self.assertNotIn("content_sha256", rec)

    def test_02_reordered_items_same_latest(self) -> None:
        text = FIXTURE_BYTES.decode("utf-8")
        items = re.findall(r"<item\b.*?</item>", text, re.DOTALL)
        self.assertEqual(len(items), 5)
        reordered = list(reversed(items))
        stripped = re.sub(r"<item\b.*?</item>\s*", "", text, flags=re.DOTALL)
        reordered_text = stripped.replace("</rdf:RDF>", "\n".join(reordered) + "\n</rdf:RDF>")
        batch = self.adapter.parse(reordered_text.encode("utf-8"), content_type="application/rss+xml",
                                  retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)
        self.assertEqual(batch.record_count, 1)
        self.assertEqual(batch.records[0]["payload"]["period"], "2026-09-11")
        self.assertEqual(batch.records[0]["payload"]["value"], 1.1592)

    def test_03_wrong_url_and_mime(self) -> None:
        for bad_ctx in ({"request_url": "https://wrong.url"}, {}, None):
            with self.assertRaises(AdapterError):
                self.adapter.parse(FIXTURE_BYTES, content_type="application/rss+xml",
                                  retrieved_at=VALID_RETRIEVAL, context=bad_ctx)  # type: ignore
        for bad_mime in ("application/json", "text/html", "image/png"):
            with self.assertRaises(AdapterError):
                self.adapter.parse(FIXTURE_BYTES, content_type=bad_mime,
                                  retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_04_wrong_root_and_publisher(self) -> None:
        cases = [
            ("rdf:RDF", "rss"),
            ("<title>ECB | US dollar (USD)", "<title>Wrong Title"),
            ("<dc:publisher>European Central Bank</dc:publisher>", "<dc:publisher>Fed</dc:publisher>"),
            ("http://www.ecb.europa.eu/home/html/disclaimer.en.html", "http://evil.com/terms"),
        ]
        for old, new in cases:
            with self.assertRaises(AdapterError):
                self.adapter.parse(mutate(old, new, 1), content_type="application/rss+xml",
                                  retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_05_wrong_cb_identity(self) -> None:
        cases = [
            ("<cb:country>U2</cb:country>", "<cb:country>US</cb:country>"),
            ("<cb:institutionAbbrev>ECB</cb:institutionAbbrev>", "<cb:institutionAbbrev>FED</cb:institutionAbbrev>"),
            ("<cb:baseCurrency unit_mult=\"0\">EUR</cb:baseCurrency>", "<cb:baseCurrency unit_mult=\"1\">EUR</cb:baseCurrency>"),
            ("<cb:baseCurrency unit_mult=\"0\">EUR</cb:baseCurrency>", "<cb:baseCurrency unit_mult=\"0\">USD</cb:baseCurrency>"),
            ("<cb:targetCurrency>USD</cb:targetCurrency>", "<cb:targetCurrency>EUR</cb:targetCurrency>"),
            ("<cb:rateType>Reference rate</cb:rateType>", "<cb:rateType>Spot rate</cb:rateType>"),
            ("<dc:language>en</dc:language>", "<dc:language>de</dc:language>"),
        ]
        for old, new in cases:
            with self.assertRaises(AdapterError):
                self.adapter.parse(mutate(old, new, 1), content_type="application/rss+xml",
                                  retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_06_nan_negative_zero_and_precision_mismatch(self) -> None:
        cases = [
            (">1.1592<", ">NaN<"),
            (">1.1592<", ">-1.1592<"),
            (">1.1592<", ">0.0000<"),
            ('decimals="4"', 'decimals="3"'),
            ('rate=1.1592"', 'rate=1.1593"'),
            ('1.1592 USD', '1.1593 USD'),
            ('2026-09-11 ECB Reference rate', '2026-09-12 ECB Reference rate'),
        ]
        for old, new in cases:
            with self.assertRaises(AdapterError):
                self.adapter.parse(mutate(old, new, 1), content_type="application/rss+xml",
                                  retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_07_item_uri_validation(self) -> None:
        cases = [
            ("http://www.ecb.europa.eu/stats/", "http://www.ecb.europa.eu:8080/stats/"),
            ("http://www.ecb.europa.eu/stats/", "http://user:pass@www.ecb.europa.eu/stats/"),
            ("http://www.ecb.europa.eu/stats/", "ftp://www.ecb.europa.eu/stats/"),
            ("eurofxref-graph-usd.en.html?", "eurofxref-graph-usd.en.html#frag?"),
            ("eurofxref-graph-usd.en.html?", "eurofxref-graph-usd.en.html?extra=1&"),
            ("eurofxref-graph-usd.en.html", "wrong-graph.en.html"),
        ]
        for old, new in cases:
            with self.assertRaises(AdapterError):
                self.adapter.parse(mutate(old, new), content_type="application/rss+xml",
                                  retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_08_duplicate_item_and_sequence_mismatch(self) -> None:
        with self.assertRaises(AdapterError):
            self.adapter.parse(mutate("2026-09-10", "2026-09-11"), content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)
        with self.assertRaises(AdapterError):
            self.adapter.parse(mutate("rate=1.1592", "rate=9.9999", 1), content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_09_corrupt_older_row_rejects_whole_batch(self) -> None:
        with self.assertRaises(AdapterError):
            self.adapter.parse(mutate(">1.1622<", ">MALFORMED<"), content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_10_missing_naive_future_timestamp(self) -> None:
        naive = mutate("2026-09-11T14:15:00+01:00", "2026-09-11T14:15:00", 1)
        with self.assertRaises(AdapterError):
            self.adapter.parse(naive, content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)
        with self.assertRaises(AdapterError):
            self.adapter.parse(FIXTURE_BYTES, content_type="application/rss+xml",
                              retrieved_at="2026-09-10T00:00:00+00:00", context=VALID_CTX)
        with self.assertRaises(AdapterError):
            self.adapter.parse(mutate("<dc:date>2026-09-11T14:15:00+01:00</dc:date>", "", 1),
                              content_type="application/rss+xml", retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_11_dtd_and_entity_rejection(self) -> None:
        with self.assertRaises(AdapterError):
            self.adapter.parse(b"<!DOCTYPE foo>" + FIXTURE_BYTES, content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)
        with self.assertRaises(AdapterError):
            self.adapter.parse(b"<!ENTITY foo 'bar'>" + FIXTURE_BYTES, content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)
        with self.assertRaises(AdapterError):
            self.adapter.parse(b" " * 8_000_001, content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_12_stale_fixture_not_redated(self) -> None:
        batch = self.adapter.parse(FIXTURE_BYTES, content_type="application/rss+xml",
                                  retrieved_at="2028-01-01T00:00:00+00:00", context=VALID_CTX)
        self.assertEqual(batch.records[0]["payload"]["period"], "2026-09-11")
        self.assertEqual(batch.records[0]["published_at"], "2026-09-11T13:15:00+00:00")

    def test_13_no_transport_mocks_offline_only(self) -> None:
        mod_src = inspect.getsource(ecb_mod)
        for net_lib in ("urllib.request", "requests", "http.client", "socket"):
            self.assertNotIn(net_lib, mod_src)
        with patch("urllib.request.urlopen") as mock_urlopen, \
             patch("socket.create_connection") as mock_connect:
            batch = self.adapter.parse(
                FIXTURE_BYTES,
                content_type="application/rss+xml",
                retrieved_at=VALID_RETRIEVAL,
                context=VALID_CTX,
            )
            self.assertEqual(batch.record_count, 1)
            mock_urlopen.assert_not_called()
            mock_connect.assert_not_called()

    def test_14_probe_four_ambiguity_regressions(self) -> None:
        rss = "{" + NS["rss"] + "}"
        cb = "{" + NS["cb"] + "}"
        dc = "{" + NS["dc"] + "}"

        # 1: multiple_channels
        root1 = ET.fromstring(FIXTURE_BYTES)
        root1.append(ET.fromstring(ET.tostring(root1.find(rss + "channel"))))
        with self.assertRaises(AdapterError):
            self.adapter.parse(ET.tostring(root1, encoding="utf-8"), content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

        # 2: contradictory_duplicate_rate
        root2 = ET.fromstring(FIXTURE_BYTES)
        ET.SubElement(
            root2.find(rss + "item").find(cb + "statistics").find(cb + "exchangeRate"),
            cb + "value",
            {"frequency": "daily", "decimals": "4"},
        ).text = "NaN"
        with self.assertRaises(AdapterError):
            self.adapter.parse(ET.tostring(root2, encoding="utf-8"), content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

        # 3: contradictory_duplicate_timestamp
        root3 = ET.fromstring(FIXTURE_BYTES)
        ET.SubElement(root3.find(rss + "item"), dc + "date").text = "2099-01-01T00:00:00Z"
        with self.assertRaises(AdapterError):
            self.adapter.parse(ET.tostring(root3, encoding="utf-8"), content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

        # 4: ignored_unknown_namespace_item
        root4 = ET.fromstring(FIXTURE_BYTES)
        ET.SubElement(root4, "{urn:unreviewed}item").text = "newer contradictory observation"
        with self.assertRaises(AdapterError):
            self.adapter.parse(ET.tostring(root4, encoding="utf-8"), content_type="application/rss+xml",
                              retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_15_duplicate_key_elements_table_coverage(self) -> None:
        table = [
            ("duplicate_channel_title", "<title>ECB", "<title>ECB | US dollar (USD) - Euro foreign exchange reference rates</title><title>ECB"),
            ("duplicate_channel_link", "<link>http://www.ecb.europa.eu/home/html/rss.en.html</link>",
             "<link>http://www.ecb.europa.eu/home/html/rss.en.html</link><link>http://www.ecb.europa.eu/home/html/rss.en.html</link>"),
            ("duplicate_channel_description", "<description>The reference rates",
             "<description>The reference rates are based on the regular daily concertation procedure between central banks within and outside the European System of Central Banks, which normally takes place at 2.15 p.m. (14:15) ECB time.</description><description>The reference rates"),
            ("duplicate_channel_items", "<items>", "<items><rdf:Seq></rdf:Seq></items><items>"),
            ("duplicate_channel_publisher", "<dc:publisher>European Central Bank</dc:publisher>",
             "<dc:publisher>European Central Bank</dc:publisher><dc:publisher>European Central Bank</dc:publisher>"),
            ("duplicate_channel_license", "<dcterms:license>http://www.ecb.europa.eu/home/html/disclaimer.en.html</dcterms:license>",
             "<dcterms:license>http://www.ecb.europa.eu/home/html/disclaimer.en.html</dcterms:license><dcterms:license>http://www.ecb.europa.eu/home/html/disclaimer.en.html</dcterms:license>"),
            ("duplicate_items_seq", "<rdf:Seq>", "<rdf:Seq></rdf:Seq><rdf:Seq>"),
            ("duplicate_item_title", "<title xml:lang=\"en\">1.1592", "<title xml:lang=\"en\">1.1592 USD = 1 EUR 2026-09-11 ECB Reference rate</title><title xml:lang=\"en\">1.1592"),
            ("duplicate_item_link",
             "<link>http://www.ecb.europa.eu/stats/exchange/eurofxref/html/eurofxref-graph-usd.en.html?date=2026-09-11&amp;rate=1.1592</link>",
             "<link>http://www.ecb.europa.eu/stats/exchange/eurofxref/html/eurofxref-graph-usd.en.html?date=2026-09-11&amp;rate=1.1592</link><link>http://www.ecb.europa.eu/stats/exchange/eurofxref/html/eurofxref-graph-usd.en.html?date=2026-09-11&amp;rate=1.1592</link>"),
            ("duplicate_item_description", "<description xml:lang=\"en\">1 EUR buys 1.1592",
             "<description xml:lang=\"en\">Dup</description><description xml:lang=\"en\">1 EUR buys 1.1592"),
            ("duplicate_item_language", "<dc:language>en</dc:language>", "<dc:language>en</dc:language><dc:language>en</dc:language>"),
            ("duplicate_item_statistics", "<cb:statistics>", "<cb:statistics></cb:statistics><cb:statistics>"),
            ("duplicate_stats_country", "<cb:country>U2</cb:country>", "<cb:country>U2</cb:country><cb:country>U2</cb:country>"),
            ("duplicate_stats_institutionAbbrev", "<cb:institutionAbbrev>ECB</cb:institutionAbbrev>",
             "<cb:institutionAbbrev>ECB</cb:institutionAbbrev><cb:institutionAbbrev>ECB</cb:institutionAbbrev>"),
            ("duplicate_stats_exchangeRate", "<cb:exchangeRate>", "<cb:exchangeRate></cb:exchangeRate><cb:exchangeRate>"),
            ("duplicate_rate_baseCurrency", "<cb:baseCurrency unit_mult=\"0\">EUR</cb:baseCurrency>",
             "<cb:baseCurrency unit_mult=\"0\">EUR</cb:baseCurrency><cb:baseCurrency unit_mult=\"0\">EUR</cb:baseCurrency>"),
            ("duplicate_rate_targetCurrency", "<cb:targetCurrency>USD</cb:targetCurrency>",
             "<cb:targetCurrency>USD</cb:targetCurrency><cb:targetCurrency>USD</cb:targetCurrency>"),
            ("duplicate_rate_rateType", "<cb:rateType>Reference rate</cb:rateType>",
             "<cb:rateType>Reference rate</cb:rateType><cb:rateType>Reference rate</cb:rateType>"),
        ]
        for name, old, new in table:
            with self.subTest(case=name):
                mutated = mutate(old, new, 1)
                with self.assertRaises(AdapterError):
                    self.adapter.parse(mutated, content_type="application/rss+xml",
                                      retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_16_nested_elements_in_scalar_table_coverage(self) -> None:
        table = [
            ("channel_title", "<title>ECB", "<title><nested>bad</nested>ECB"),
            ("channel_publisher", "<dc:publisher>European", "<dc:publisher><nested/>European"),
            ("channel_license", "<dcterms:license>http", "<dcterms:license><nested/>http"),
            ("item_title", "<title xml:lang=\"en\">1.1592", "<title xml:lang=\"en\"><nested/>1.1592"),
            ("item_link", "<link>http://www.ecb.europa.eu/stats", "<link><nested/>http://www.ecb.europa.eu/stats"),
            ("item_description", "<description xml:lang=\"en\">1 EUR", "<description xml:lang=\"en\"><nested/>1 EUR"),
            ("item_dc_date", "<dc:date>2026-09-11", "<dc:date><nested/>2026-09-11"),
            ("item_dc_language", "<dc:language>en</dc:language>", "<dc:language><nested/>en</dc:language>"),
            ("stats_country", "<cb:country>U2</cb:country>", "<cb:country><nested/>U2</cb:country>"),
            ("stats_institutionAbbrev", "<cb:institutionAbbrev>ECB</cb:institutionAbbrev>",
             "<cb:institutionAbbrev><nested/>ECB</cb:institutionAbbrev>"),
            ("rate_value", ">1.1592<", "><nested/>1.1592<"),
            ("rate_baseCurrency", ">EUR<", "><nested/>EUR<"),
            ("rate_targetCurrency", ">USD<", "><nested/>USD<"),
            ("rate_rateType", ">Reference rate<", "><nested/>Reference rate<"),
        ]
        for name, old, new in table:
            with self.subTest(case=name):
                mutated = mutate(old, new, 1)
                with self.assertRaises(AdapterError):
                    self.adapter.parse(mutated, content_type="application/rss+xml",
                                      retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)

    def test_17_stray_text_tails_and_strict_numeric(self) -> None:
        cases = [
            # Stray container texts
            ("stray_root_text", "<channel  rdf:about", "stray root text<channel  rdf:about"),
            ("stray_channel_text", "<title>ECB", "stray channel text<title>ECB"),
            ("stray_ex_rate_text", "<cb:value frequency", "stray ex_rate text<cb:value frequency"),
            # Stray tail text
            ("stray_tail_text", "</cb:value>", "</cb:value>stray tail text"),
            # Strict numeric checks
            ("positive_prefix_rate", ">1.1592<", ">+1.1592<"),
            ("scientific_lower_rate", ">1.1592<", ">1.1592e0<"),
            ("scientific_upper_rate", ">1.1592<", ">1.1592E0<"),
            ("scientific_int_rate", ">1.1592<", ">1e4<"),
            # Unknown elements
            ("unknown_channel_elem", "</channel>", "<unknownTag>val</unknownTag></channel>"),
            ("unknown_item_elem", "</item>", "<unknownTag>val</unknownTag></item>"),
            ("unknown_stats_elem", "</cb:statistics>", "<unknownTag>val</unknownTag></cb:statistics>"),
            ("unknown_ex_rate_elem", "</cb:exchangeRate>", "<unknownTag>val</unknownTag></cb:exchangeRate>"),
        ]
        for name, old, new in cases:
            with self.subTest(case=name):
                mutated = mutate(old, new, 1)
                with self.assertRaises(AdapterError):
                    self.adapter.parse(mutated, content_type="application/rss+xml",
                                      retrieved_at=VALID_RETRIEVAL, context=VALID_CTX)


if __name__ == "__main__":
    unittest.main()
