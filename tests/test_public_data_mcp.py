"""Public-data MCP server: JSON-RPC handling, host allowlist, bounded tool outputs. No network, no secrets."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import public_data_mcp as server  # noqa: E402


def call(name, arguments):
    response = server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return response["result"]


class ProtocolTests(unittest.TestCase):
    def test_initialize_lists_tools_and_ignores_notifications(self):
        init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", init["result"]["capabilities"])
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = [tool["name"] for tool in server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
        self.assertEqual(names, ["sec_filings", "sec_facts", "sec_full_text_search", "sec_filing_text", "tw_monthly_revenue"])
        self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"], -32601)
        self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "x"}})["error"]["code"], -32602)

    def test_only_allowlisted_https_hosts_are_fetched(self):
        for url in ("https://example.com/x", "http://data.sec.gov/x", "https://data.sec.gov.evil.com/x", "https://data.sec.gov:8443/x",
                    "https://user@data.sec.gov/x", "https://evil.com@data.sec.gov/x", "https://data.sec.gov:bad/x"):
            with self.assertRaises(server.ToolError):
                server.http_get(url)
        # A redirect leaving the allowlist is refused before any header is sent to the new host.
        request = server.urllib.request.Request("https://data.sec.gov/x", headers={"From": "contact"})
        with self.assertRaises(server.ToolError):
            server._AllowlistRedirect().redirect_request(request, None, 302, "Found", {}, "https://collector.example/")
        # urllib resolves a relative Location before redirect_request, so the handler always sees an absolute URL.
        self.assertIsNotNone(server._AllowlistRedirect().redirect_request(request, None, 302, "Found", {}, "https://www.sec.gov/y"))
        result = call("sec_filing_text", {"url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"})
        self.assertTrue(result["isError"])
        self.assertIn("EDGAR_ARCHIVE", result["content"][0]["text"])


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.saved = (server.http_json, server.http_get, dict(server._tickers))
        server._tickers.clear()
        server._tickers["NVDA"] = {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"}

    def tearDown(self):
        server.http_json, server.http_get, tickers = self.saved
        server._tickers.clear()
        server._tickers.update(tickers)

    def test_facts_keep_the_latest_values_per_tag(self):
        facts = {"facts": {"us-gaap": {"RevenueRemainingPerformanceObligation": {"units": {"USD": [
            {"end": "2025-07-27", "val": 1, "form": "10-Q", "filed": "2025-08-27"},
            {"end": "2026-07-26", "val": 3200000000, "form": "10-Q", "filed": "2026-08-26"}]}}}}}
        server.http_json = lambda url: facts
        payload = json.loads(call("sec_facts", {"ticker": "nvda", "tags": ["RevenueRemainingPerformanceObligation", "Backlog"], "limit": 1})["content"][0]["text"])
        self.assertEqual(payload["cik"], "0001045810")
        self.assertEqual(payload["facts"]["RevenueRemainingPerformanceObligation"][0]["val"], 3200000000)
        self.assertEqual(len(payload["facts"]["RevenueRemainingPerformanceObligation"]), 1)
        self.assertEqual(payload["facts"]["Backlog"], "NOT_REPORTED")
        self.assertTrue(call("sec_facts", {"ticker": "NOPE"})["isError"])

    def test_filings_build_archive_urls(self):
        recent = {"filings": {"recent": {"form": ["8-K", "10-Q"], "filingDate": ["2026-09-01", "2026-08-26"],
                                          "reportDate": ["", "2026-07-26"], "accessionNumber": ["a-1", "0001045810-26-000123"],
                                          "primaryDocument": ["x.htm", "nvda-20260726.htm"]}}}
        server.http_json = lambda url: recent
        payload = json.loads(call("sec_filings", {"ticker": "NVDA", "forms": ["10-q"]})["content"][0]["text"])
        self.assertEqual(payload["filings"], [{"form": "10-Q", "filed": "2026-08-26", "period": "2026-07-26",
                                               "accession": "0001045810-26-000123",
                                               "url": "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000123/nvda-20260726.htm"}])

    def test_filing_text_returns_bounded_matching_passages(self):
        body = ("<html><style>x</style><p>Intro</p><p>" + "filler " * 3000 +
                "We expect to recognize approximately 40% of remaining performance obligations over the next 12 months.</p></html>")
        server.http_get = lambda url: body.encode("utf-8")
        url = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000123/nvda-20260726.htm"
        payload = json.loads(call("sec_filing_text", {"url": url, "find": "no such phrase | Remaining Performance Obligations", "context": 60})["content"][0]["text"])
        self.assertEqual(len(payload["passages"]), 1)
        self.assertIn("approximately 40%", payload["passages"][0]["text"])
        # Phrases are literal: regex syntax (a catastrophic-backtracking pattern here) matches nothing and returns at once.
        literal = json.loads(call("sec_filing_text", {"url": url, "find": "(a+)+$", "context": "x"})["content"][0]["text"])
        self.assertEqual(literal["passages"], [])
        whole = json.loads(call("sec_filing_text", {"url": url})["content"][0]["text"])
        self.assertTrue(whole["truncated"])
        self.assertLessEqual(len(whole["text"]), server.MAX_TEXT)
        self.assertNotIn("<p>", whole["text"])

    def test_full_text_search_lists_the_newest_filings_first(self):
        hits = [{"_id": f"0001769628-{year % 100}-000014:crwv-{year}.htm", "_source": {"form": "10-Q", "file_date": f"{year}-05-15",
                 "ciks": ["0001769628"], "display_names": ["CoreWeave"]}} for year in (2025, 2026)]
        server.http_json = lambda url: {"hits": {"hits": hits}}
        payload = json.loads(call("sec_full_text_search", {"query": "backlog", "limit": 1})["content"][0]["text"])
        self.assertEqual([hit["filed"] for hit in payload["hits"]], ["2026-05-15"])
        self.assertTrue(payload["hits"][0]["url"].endswith("/1769628/000176962826000014/crwv-2026.htm"))

    def test_taiwan_revenue_tries_both_exchange_feeds(self):
        def fake(url):
            if url == server.TW_FEEDS["TWSE"]:
                raise server.ToolError("SOURCE_UNAVAILABLE: openapi.twse.com.tw URLError")
            return [{"公司代號": "5351", "營業收入-當月營收": "2260221"}]
        server.http_json = fake
        payload = json.loads(call("tw_monthly_revenue", {"code": "5351.TWO"})["content"][0]["text"])
        self.assertEqual((payload["market"], payload["row"]["營業收入-當月營收"]), ("TPEX", "2260221"))
        server.http_json = lambda url: (_ for _ in ()).throw(server.ToolError("SOURCE_UNAVAILABLE"))
        self.assertTrue(call("tw_monthly_revenue", {"code": "2330"})["isError"])


if __name__ == "__main__":
    unittest.main()
