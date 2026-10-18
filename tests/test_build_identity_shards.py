"""Identity shards for the LINE stock lookup: feed parsing, shard layout, hashing parity with the Worker, and the
lazy sealing path (publisher + content-addressed blobs). Synthetic feeds only; no network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_identity_shards as shards  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402

NASDAQ = ("Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
          + "".join(f"N{i:03d}|Synthetic {i} Inc. - Common Stock|Q|N|N|100|N|N\n" for i in range(3000))
          + "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n" + "NVDA|NVIDIA Corporation - Common Stock|Q|N|N|100|N|N\nZTST|Test issue|Q|Y|N|100|N|N\n"
          + "File Creation Time: 0926202601:00|||||||\n").encode()
OTHER = ("ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
         + "".join(f"O{i:03d}|Other {i} Corp|N|O{i:03d}|N|100|N|O{i:03d}\n" for i in range(3000))).encode()
TWSE = json.dumps([{"公司代號": f"{1000 + i}", "公司名稱": f"合成公司{i}股份有限公司", "公司簡稱": f"合成{i}"} for i in range(800)]
                  + [{"公司代號": "2330", "公司名稱": "台灣積體電路製造股份有限公司", "公司簡稱": "台積電"}], ensure_ascii=False).encode()
TPEX = json.dumps([{"SecuritiesCompanyCode": f"{6000 + i}", "CompanyName": f"櫃買合成{i}", "CompanyAbbreviation": f"櫃{i}"}
                   for i in range(600)], ensure_ascii=False).encode()


def nordic(count: int, extra: list[dict] | None = None) -> bytes:
    rows = [{"symbol": f"S{i:03d}", "fullName": f"Svensk {i}", "currency": "SEK", "assetClass": "SHARES"} for i in range(count)]
    return json.dumps({"data": {"instrumentListing": {"rows": rows + (extra or [])}}}).encode()


def xlsx(rows: list[list[str]]) -> bytes:
    """A minimal one-sheet workbook with inline strings (enough for the standard-library reader)."""
    import io
    import zipfile
    from xml.sax.saxutils import escape
    cells = "".join("<row>" + "".join(f'<c t="inlineStr"><is><t>{escape(v)}</t></is></c>' for v in row) + "</row>" for row in rows)
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             + cells + "</sheetData></worksheet>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


JPX = xlsx([["Effective Date", "Local Code", "Name (English)", "Section/Products"]]
           + [["20260831", f"J{i:03d}", f"JAPAN SYNTH {i}", "Prime Market (Domestic)"] for i in range(3000)]
           + [["20260831", "4062", "IBIDEN CO.,LTD.", "Prime Market (Domestic)"], ["20260831", "2330", "Forside Co.,Ltd.", "Growth Market"]])
KRX = ("<table><tr><th>회사명</th><th>시장구분</th><th>종목코드</th></tr>"
       + "".join(f"<tr><td>합성{i}</td><td>유가</td><td>{100000 + i:06d}</td></tr>" for i in range(1500))
       + "<tr><td>삼성전자</td><td>유가</td><td>005930</td></tr><tr><td>코넥스사</td><td>코넥스</td><td>999999</td></tr></table>").encode("euc-kr")
EURONEXT = ("\ufeffName;ISIN;Symbol;Market;Currency\n"
            + "".join(f"SYN{i};FR{i:010d};SY{i};Euronext Paris;EUR\n" for i in range(800))
            + "SOITEC;FR0013227113;SOI;Euronext Paris;EUR\nSOITEC;FR0013227113;2SOI;Trading After Hours;EUR\n").encode("utf-8")

def lse(n: int, extra: list | None = None) -> bytes:
    rows = (extra or []) + [{"tidm": f"L{i}", "issuername": f"LONDON {i} PLC", "description": f"LONDON {i} PLC ORD 1P",
                             "category": "EQUITY", "currency": "GBX", "lastprice": 100 + i, "percentualchange": 0.5} for i in range(n)]
    return json.dumps([{"content": [{"name": "priceexplorersearch", "value": {"content": rows}}]}]).encode()


IQE = {"tidm": "IQE", "issuername": "IQE PLC", "description": "IQE PLC ORD 1P", "category": "EQUITY", "currency": "GBX",
       "lastprice": 46.4, "percentualchange": 5.3348}
FEEDS = {
    "lse-main-market": lse(800), "lse-aim": lse(400, [IQE, {**IQE, "tidm": "SMSN", "issuername": "SAMSUNG ELECTRONICS CO LTD",
                                                              "description": "SAMSUNG ELECTRONICS CO LD GDR (EACH REP 25 COM STK)"}]),
    "jpx-listed": JPX, "krx-listed": KRX, "euronext-equities": EURONEXT,
    "nasdaq-listed": NASDAQ, "other-us-listed": OTHER, "twse-listed": TWSE, "tpex-listed": TPEX,
    "nasdaq-stockholm-main": nordic(250, [{"symbol": "SIVE", "fullName": "Sivers Semiconductors", "currency": "SEK", "assetClass": "SHARES"}]),
    "nasdaq-stockholm-first-north": nordic(150),
}


def fetch(url: str) -> bytes:
    return next(body for feed, body in FEEDS.items() if shards.FEEDS[feed] == url)


def fetch_or_fail(url: str) -> bytes:
    body = next((body for feed, body in FEEDS.items() if shards.FEEDS[feed] == url), None)
    if body is None:
        raise OSError("synthetic outage")
    return body


class IdentityShardTests(unittest.TestCase):
    def test_layout_parsing_and_exclusions(self):
        document = shards.build(fetch, datetime(2026, 9, 26, 1, tzinfo=timezone.utc), zh=({}, None))
        sym = document["symbol_shards"]
        self.assertIn(["SIVE", "NASDAQ STOCKHOLM", "SWEDEN", "Sweden", "Sivers Semiconductors", None, "COMMON_STOCK", "SEK", 4, None],
                      sym["S"]["rows"])
        self.assertIn(["2330", "TWSE", "TAIWAN", "Taiwan", "台灣積體電路製造股份有限公司", "台積電", "COMMON_STOCK", "TWD", 2, ["台積電", "TWSE"]], sym["2"]["rows"])
        self.assertFalse(any(row[0] == "ZTST" for row in sym["Z"]["rows"]) if "Z" in sym else False)  # test issue excluded
        self.assertTrue(all(row[0][0] == bucket or bucket == "_" for bucket, shard in sym.items() for row in shard["rows"]))
        self.assertIn(["4062", "TSE", "JAPAN", "Japan", "IBIDEN CO.,LTD.", None, "COMMON_STOCK", "JPY", 6, None], sym["4"]["rows"])
        self.assertIn(["005930", "KRX", "KOREA", "Korea", "삼성전자", "삼성전자", "COMMON_STOCK", "KRW", 7, None], sym["0"]["rows"])
        self.assertIn(["SOI", "EURONEXT PARIS", "EUROPE", "France", "SOITEC", None, "COMMON_STOCK", "EUR", 8, None], sym["S"]["rows"])
        self.assertFalse(any(row[0] in ("999999", "2SOI") for shard in sym.values() for row in shard["rows"]))
        self.assertIn(["IQE", "LSE", "UK", "United Kingdom", "IQE PLC", None, "COMMON_STOCK", "GBX", 10, None], sym["I"]["rows"])
        self.assertEqual(next(row for row in sym["S"]["rows"] if row[0] == "SMSN")[6], "ADR")
        self.assertEqual(document["skipped_optional_feeds"], [])
        name_bucket = str(shards.fnv1a_utf16("台積電") % 16)
        self.assertIn(["台積電", "2", "2330", "TWSE"], document["name_shards"][name_bucket]["rows"])

    def test_sourced_chinese_names_are_attached_and_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "zh.json"
            path.write_text(json.dumps({"schema": "v213-zh-names-v1", "generated_at": "2026-09-26T00:00:00Z", "names": {
                "KOREA:005930": ["三星電子", "ZHWIKI"], "SWEDEN:SIVE": ["不可信", "MACHINE"], "JAPAN:4062": ["x" * 41, "ZHWIKI"]}},
                ensure_ascii=False), encoding="utf-8")
            zh = shards.load_zh_names(path)
        self.assertEqual(zh[0], {"KOREA:005930": ["三星電子", "ZHWIKI"]})  # unknown source and over-long names dropped
        document = shards.build(fetch, datetime(2026, 9, 26, 1, tzinfo=timezone.utc), zh=zh)
        rows = {row[0]: row for shard in document["symbol_shards"].values() for row in shard["rows"]}
        self.assertEqual(rows["005930"][9], ["三星電子", "ZHWIKI"])
        self.assertIsNone(rows["SIVE"][9])
        self.assertEqual(document["zh_names"]["rows"], 1)
        bucket = str(shards.fnv1a_utf16("三星電子") % 16)
        self.assertIn(["三星電子", "0", "005930", "KRX"], document["name_shards"][bucket]["rows"])

    def test_london_is_optional(self):
        saved = FEEDS.pop("lse-aim")
        try:
            document = shards.build(fetch_or_fail, zh=({}, None))
        finally:
            FEEDS["lse-aim"] = saved
        self.assertEqual(document["skipped_optional_feeds"], ["lse-aim"])
        self.assertEqual(len(document["feeds"]), len(shards.FEEDS) - 1)

    def test_hash_parity_with_the_worker(self):
        # Values asserted by cloud/test/v213-identity-shards.test.ts for identityNameBucket.
        self.assertEqual(shards.fnv1a_utf16("台積電"), 1342269639)
        self.assertEqual(shards.fnv1a_utf16("abc"), 440920331)

    def test_a_short_or_failed_feed_fails_the_build(self):
        saved = FEEDS["twse-listed"]
        FEEDS["twse-listed"] = b"[]"
        try:
            with self.assertRaisesRegex(shards.IdentityShardError, "IDENTITY_FEED_TOO_SMALL twse-listed"):
                shards.build(fetch, zh=({}, None))
        finally:
            FEEDS["twse-listed"] = saved

    def test_publisher_seals_shards_as_content_addressed_lazy_objects(self):
        document = shards.build(fetch, datetime.now(timezone.utc), zh=({}, None))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.json"
            path.write_bytes(shards.dumps(document).encode("utf-8"))
            lazy = publisher.lazy_identity_bodies(path, datetime.now(timezone.utc))
            self.assertIn("v213:identity:v2:sym:S", lazy)
            self.assertEqual(len(lazy), len(document["symbol_shards"]) + len(document["name_shards"]))
            stale = publisher.lazy_identity_bodies(path, datetime(2027, 1, 1, tzinfo=timezone.utc))
            self.assertEqual(stale, {})


if __name__ == "__main__":
    unittest.main()
