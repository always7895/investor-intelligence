from __future__ import annotations

import sys
import io
import json
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from adapters import AdapterError
from adapters.staged_public import parse_source_payload
from adapters.official_rss import FEEDS
from fetch_public_source_observations import collect, fetch_bytes, main


def rss(domain="www.federalreserve.gov", extra=""):
    return (f'<rss version="2.0"><channel><item><title>Synthetic announcement</title>'
            f'<link>https://{domain}/press/test.htm</link>'
            f'<pubDate>Mon, 07 Sep 2026 10:00:00 GMT</pubDate></item>{extra}</channel></rss>').encode()


class OfficialNewsTests(unittest.TestCase):
    def parse(self, content):
        return parse_source_payload("federal_reserve_news", content,
                                    content_type="application/rss+xml", retrieved_at="2026-09-08T00:00:00Z")

    def test_parser_preserves_origin_and_does_not_verify_issuer_claims(self):
        batch = self.parse(rss())
        self.assertEqual(batch.record_count, 1)
        self.assertEqual(batch.records[0]["origin"], "federalreserve.gov")
        self.assertFalse(batch.records[0]["issuer_claim_verified"])
        self.assertFalse(batch.records[0]["publication_eligible"])
        self.assertTrue(batch.records[0]["published_at"].startswith("2026-09-07"))

    def test_all_registered_sources_use_same_bounded_parser(self):
        for source, (_, domain) in FEEDS.items():
            batch = parse_source_payload(source, rss("www." + domain),
                                         content_type="text/xml", retrieved_at="2026-09-08T00:00:00Z")
            self.assertEqual(batch.source_id, source)

    def test_rejects_entities_html_wrong_domains_and_future_dates(self):
        for body in (b'<!DOCTYPE rss [<!ENTITY x "test">]><rss/>', b'<html/>',
                     rss("federalreserve.gov.evil.test"),
                     rss().replace(b'2026', b'2099')):
            with self.assertRaises(AdapterError):
                self.parse(body)

    def test_invalid_and_duplicate_items_remain_warnings(self):
        body = rss(extra='<item><title>Missing fields</title></item>')
        batch = self.parse(body)
        self.assertEqual(batch.warnings, ("INVALID_ITEM:1",))
        item = rss().split(b"<channel>")[1].split(b"</channel>")[0]
        batch = self.parse(rss(extra=item.decode()))
        self.assertEqual(batch.record_count, 1)
        self.assertEqual(batch.warnings, ("DUPLICATE_ITEM:1",))

    def test_actual_collector_isolates_failures_and_deduplicates_requests(self):
        calls = []
        def transport(url):
            calls.append(url)
            if "ecb" in url:
                raise OSError("synthetic-private-error")
            return rss()
        result = collect(["federal_reserve_news", "ecb_news", "federal_reserve_news"], transport=transport)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual([row["status"] for row in result["sources"]], ["OK", "FAILED"])
        self.assertNotIn("synthetic-private-error", str(result))

    def test_cli_summary_is_bounded_even_with_many_rejected_rows(self):
        result = {"status": "PARTIAL", "items": [], "sources": [{
            "source_id": "tpex_equity_eod", "status": "PARTIAL", "record_count": 0,
            "warnings": [f"INVALID_EQUITY_ROW:{i}" for i in range(10000)]}]}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "synthetic.json"
            output = io.StringIO()
            with patch.object(sys, "argv", ["collector", "--fetch", "--output", str(target)]), patch(
                "fetch_public_source_observations.collect", return_value=result
            ), redirect_stdout(output):
                self.assertEqual(main(), 1)
            self.assertLess(len(output.getvalue()), 1000)
            self.assertEqual(json.loads(output.getvalue())["sources"][0]["warning_count"], 10000)
            self.assertEqual(len(json.loads(target.read_text())["sources"][0]["warnings"]), 10000)

    def test_arbitrary_network_target_rejected_before_transport(self):
        with self.assertRaises(ValueError):
            fetch_bytes("https://example.test/private")
        with self.assertRaises(ValueError):
            collect(["unreviewed"])


if __name__ == "__main__":
    unittest.main()
