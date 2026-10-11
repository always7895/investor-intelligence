"""Sourced Chinese company names: Wikipedia zh-tw display titles first, Wikidata labels as fallback, company-registered
names override; nothing is translated, ambiguous or non-Chinese candidates are dropped. No network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_zh_names as zh  # noqa: E402

EX = "http://www.wikidata.org/entity/"
BINDINGS = [
    {"ex": EX + "Q82059", "ticker": "NVDA", "title": "英伟达", "tw": "輝達"},
    {"ex": EX + "Q82059", "ticker": "MU", "title": "美光科技", "tw": "美光記憶台"},  # the article title beats a stray label
    {"ex": EX + "Q13677", "ticker": "AMD", "title": "AMD", "tw": "超微半導體"},  # Latin title: label fallback
    {"ex": EX + "Q13677", "ticker": "COHR", "title": "Coherent, Inc."},  # no Chinese anywhere
    {"ex": EX + "Q495372", "ticker": "005930", "title": "三星電子", "pub": "1"},
    {"ex": EX + "Q495372", "ticker": "005930", "title": "三星集团"},  # a group item with the listed company's ticker
    {"ex": EX + "Q495372", "ticker": "000001", "title": "甲公司"},
    {"ex": EX + "Q495372", "ticker": "000001", "title": "乙公司"},  # two non-public candidates: ambiguous
    {"ex": EX + "Q217475", "ticker": "8035", "title": "東京威力科創股份有限公司"},
] + [{"ex": EX + "Q82059", "ticker": f"X{i}"} for i in range(1000)]
DISPLAY = {"英伟达": "<span>輝達</span>", "美光科技": "美光科技", "AMD": "AMD", "Coherent, Inc.": "Coherent, Inc.", "甲公司": "甲公司", "乙公司": "乙公司",
           "三星電子": "三星電子", "三星集团": "三星集團", "東京威力科創股份有限公司": "東京威力科創股份有限公司"}


def fetch(url: str) -> bytes:
    if url.startswith(zh.SPARQL):
        rows = [{key: {"value": value} for key, value in row.items()} for row in BINDINGS]
        return json.dumps({"results": {"bindings": rows}}).encode("utf-8")
    page = urllib.parse.unquote(url.split("&page=", 1)[1])
    return json.dumps({"parse": {"displaytitle": DISPLAY[page]}}, ensure_ascii=False).encode("utf-8")


class ZhNameTests(unittest.TestCase):
    def test_sources_order_and_cleaning(self):
        official = {"US:AMD": ["超微半導體", "OFFICIAL"]}
        document, cache = zh.build(fetch, datetime(2026, 9, 26, tzinfo=timezone.utc), cache={}, official=official)
        names = document["names"]
        self.assertEqual(names["US:NVDA"], ["輝達", "ZHWIKI"])  # the article's own zh-tw conversion, not 英偉達
        self.assertEqual(names["US:MU"], ["美光科技", "ZHWIKI"])
        self.assertEqual(names["US:AMD"], ["超微半導體", "OFFICIAL"])
        self.assertNotIn("US:COHR", names)
        self.assertEqual(names["KOREA:005930"], ["三星電子", "ZHWIKI"])
        self.assertNotIn("KOREA:000001", names)
        self.assertEqual(document["stats"]["ambiguous_dropped"], 1)
        self.assertEqual(names["JAPAN:8035"], ["東京威力科創", "ZHWIKI"])  # legal-form suffix dropped
        self.assertIn("英伟达", cache)

    def test_title_cache_bounds_rendering(self):
        cache: dict = {}
        document, _ = zh.build(fetch, datetime(2026, 9, 26, tzinfo=timezone.utc), cache=cache, max_parse=2, official={})
        self.assertEqual(document["stats"]["rendered_this_run"], 2)
        again, _ = zh.build(fetch, datetime(2026, 9, 26, tzinfo=timezone.utc), cache=cache, max_parse=100, official={})
        self.assertEqual(again["stats"]["rendered_this_run"], len(DISPLAY) - 2)

    def test_listing_keys_and_symbol_lookup(self):
        self.assertEqual([zh.listing_key(s) for s in ("SIVE.ST", "VOLV-B.ST", "BRK-B", "5351.TWO", "000660.KS", "0700.HK")],
                         ["SWEDEN:SIVE", "SWEDEN:VOLV B", "US:BRK.B", "TAIWAN:5351", "KOREA:000660", "HK:0700"])
        with tempfile.TemporaryDirectory() as tmp:
            identity = Path(tmp) / "identity.json"
            identity.write_text(json.dumps({"symbol_shards": {"5": {"rows": [
                ["5351", "TPEX", "TAIWAN", "Taiwan", "鈺創科技股份有限公司", "鈺創", "COMMON_STOCK", "TWD", 3, ["鈺創", "TPEX"]]]}}},
                ensure_ascii=False), encoding="utf-8")
            names = Path(tmp) / "names.json"
            names.write_text(json.dumps({"names": {"US:NVDA": ["輝達", "ZHWIKI"]}}, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(zh.names_for(["5351.TWO", "NVDA", "SIVE.ST"], identity, names),
                             {"5351.TWO": ["鈺創", "TPEX"], "NVDA": ["輝達", "ZHWIKI"]})

    def test_a_contested_identity_key_gets_no_identity_or_cache_chinese_name(self):
        # ICON12: the identity build keeps a contradictory variant of one venue:symbol after the first row, so a key with more than
        # one retained row is contested: no identity Chinese name (first variant) and no name-cache name; a clean key and a sourced
        # config entry are unchanged.
        def row(symbol, venue, market, name, klass, zh_pair):
            return [symbol, venue, market, "Country", name, None, klass, "USD", 0, zh_pair]
        with tempfile.TemporaryDirectory() as tmp:
            identity = Path(tmp) / "identity.json"
            identity.write_text(json.dumps({"symbol_shards": {"A": {"rows": [
                row("ACME", "NASDAQ", "US", "Acme Orbit", "COMMON_STOCK", ["頂點", "ZHWIKI"]),
                row("ACME", "NASDAQ", "US", "Acme Orbit ETF", "ETF", ["頂點基金", "ZHWIKI"]),
                row("CLEAN", "NASDAQ", "US", "Clean Corp", "COMMON_STOCK", ["乾淨", "ZHWIKI"]),
                row("NONAME", "NASDAQ", "US", "No Name", "COMMON_STOCK", None),
                row("MU", "NASDAQ", "US", "Micron", "COMMON_STOCK", ["假美光", "ZHWIKI"]),
                row("MU", "NASDAQ", "US", "Micron Alt", "ETF", ["別名美光", "ZHWIKI"]),
                row("ONLYSECOND", "NASDAQ", "US", "Only Second", "COMMON_STOCK", None),
                row("ONLYSECOND", "NASDAQ", "US", "Only Second B", "ETF", ["第二", "ZHWIKI"]),
                row("TWOVENUE", "NASDAQ", "US", "Two Venue", "COMMON_STOCK", ["雙場一", "ZHWIKI"]),
                row("TWOVENUE", "NYSE", "US", "Two Venue B", "COMMON_STOCK", ["雙場二", "ZHWIKI"])]}}},
                ensure_ascii=False), encoding="utf-8")
            names = Path(tmp) / "names.json"
            names.write_text(json.dumps({"names": {"US:ACME": ["快取頂點", "ZHWIKI"], "US:CLEAN": ["快取乾淨", "ZHWIKI"],
                                                   "US:NONAME": ["快取無名", "ZHWIKI"], "US:ONLYSECOND": ["快取第二", "ZHWIKI"]}},
                                        ensure_ascii=False), encoding="utf-8")
            found = zh.names_for(["ACME", "CLEAN", "NONAME", "MU", "ONLYSECOND", "TWOVENUE"], identity, names)
            self.assertNotIn("ACME", found)  # contested: neither the first variant nor the cache name is shown
            self.assertNotIn("ONLYSECOND", found)  # the named variant is the later one: still contested
            self.assertEqual(found["CLEAN"], ["乾淨", "ZHWIKI"])  # a single retained row keeps its identity name
            self.assertEqual(found["NONAME"], ["快取無名", "ZHWIKI"])  # a clean key without an identity name still falls back to the cache
            self.assertEqual(found["MU"], ["美光科技", "ZHWIKI"])  # a sourced config entry is explicit and wins even for a contested key
            self.assertEqual(found["TWOVENUE"], ["雙場一", "ZHWIKI"])  # two venues of one market are two clean keys: first row, as before

    def test_official_entries_cite_a_source_and_are_chinese(self):
        entries = json.loads(zh.OFFICIAL.read_text(encoding="utf-8"))["names"]
        self.assertTrue(entries)
        for entry in entries:
            self.assertTrue(entry["source_url"].startswith("https://"), entry)
            self.assertIsNotNone(zh.clean_name(entry["name_zh"]), entry)
        official = zh.load_official()
        self.assertEqual(len(official), len(entries))
        self.assertEqual(official["US:SNDK"], ["晟碟", "ZHWIKI"])  # operator 2026-09-26
        self.assertEqual(official["US:MU"], ["美光科技", "ZHWIKI"])
        self.assertEqual(official["US:LITE"][1], "OFFICIAL")

    def test_sourced_entries_override_the_name_cache_at_seal_time_and_a_wiki_source_must_be_zh_wikipedia(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = Path(tmp) / "names.json"
            names.write_text(json.dumps({"names": {"US:MU": ["美光記憶台", "WIKIDATA_LABEL"], "US:NVDA": ["輝達", "ZHWIKI"]}},
                                        ensure_ascii=False), encoding="utf-8")
            found = zh.names_for(["MU", "NVDA", "SNDK", "4062.T"], Path(tmp) / "absent.json", names)
            self.assertEqual(found, {"MU": ["美光科技", "ZHWIKI"], "NVDA": ["輝達", "ZHWIKI"], "SNDK": ["晟碟", "ZHWIKI"],
                                     "4062.T": ["揖斐電", "OFFICIAL"]})
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"names": [{"market": "US", "symbol": "X", "name_zh": "某公司", "source": "ZHWIKI",
                                                 "source_url": "https://example.com/x"}]}, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                zh.load_official(bad)


if __name__ == "__main__":
    unittest.main()
