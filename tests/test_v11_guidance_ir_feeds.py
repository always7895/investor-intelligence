"""Lane V11 (revenue-guidance registry coverage): the official IR channel reads behind the new `ir` entries, the Nebius category tag and the 403
fallback of the IR fetcher. The feed rows are the live ones of 2026-10-13 (tests/fixtures/v11-guidance-release-feeds.json)."""
from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issuer_ir_feeds as feeds  # noqa: E402
import revenue_guidance_release_check as checker  # noqa: E402
from tests import v11_guidance_feeds as fx  # noqa: E402

TODAY = date(2026, 10, 13)
REGISTRY = {r["symbol"]: r for r in json.loads((ROOT / "config" / "revenue-guidance-v1.json").read_text(encoding="utf-8"))["issuers"]}
FEEDS = fx.load()
NEW_IR = ("SNDK", "AVGO", "MTSI", "AAOI", "ALAB")


def ir_read(symbol, rows=None, since=None):
    """The checker's own IR channel read (ir_channel) of one issuer from its fixture rows."""
    record, entry = REGISTRY[symbol], fx.entry_copy(FEEDS, symbol)
    if rows is not None:
        entry["ir"]["rows"] = rows
    channels = record["release_channels"]
    ref = next(d for d in record["documents"] if d["id"] == f"{symbol}-GUIDANCE")["published_date"]
    return checker.ir_channel(channels["ir"], channels["ir_guidance_release_title"], since or ref, TODAY, set(), fx.fetchers(entry)[2])


class NewlyCoveredIssuerTests(unittest.TestCase):
    def test_the_registry_names_a_rss_channel_for_each_issuer_that_had_none(self):
        for symbol in NEW_IR:
            channels = REGISTRY[symbol]["release_channels"]
            self.assertEqual(channels["ir"]["kind"], "RSS", symbol)
            self.assertTrue(channels["ir"]["url"].startswith("https://") and channels["ir"]["url"].endswith("/rss.xml"), symbol)
            self.assertTrue(channels["ir_guidance_release_title"], symbol)

    def test_each_channel_lists_the_reviewed_guidance_release_on_its_day_and_is_a_complete_read(self):
        for symbol in NEW_IR:
            channel, later = ir_read(symbol)
            self.assertEqual((channel["status"], channel["complete"]), ("OK", True), symbol)
            self.assertFalse([d for d in later if d["disposition"] == "POSSIBLY_RELEVANT" and d["date"] == REGISTRY[symbol]["documents"][0]["published_date"]], symbol)

    def test_a_feed_without_the_guidance_release_on_its_day_is_incomplete_never_a_quiet_success(self):
        for symbol in NEW_IR:
            title = REGISTRY[symbol]["release_channels"]["ir_guidance_release_title"]
            rows = [r for r in fx.entry_copy(FEEDS, symbol)["ir"]["rows"] if r["title"].replace("&amp;", "&") != title]
            channel, _ = ir_read(symbol, rows)
            self.assertEqual((channel["status"], channel["complete"]), ("OK", False), symbol)

    def test_a_ten_item_window_that_no_longer_reaches_before_the_guidance_day_is_incomplete(self):
        entry = fx.entry_copy(FEEDS, "AVGO")
        rows = [r for r in entry["ir"]["rows"] if "31 Aug 2026" not in r["pubDate"]]  # the items older than the guidance day have scrolled out
        channel, _ = ir_read("AVGO", rows)
        self.assertEqual((channel["status"], channel["complete"]), ("OK", False))

    def test_a_malformed_feed_is_a_failed_channel(self):
        record = REGISTRY["SNDK"]
        spec = record["release_channels"]["ir"]
        channel, later = checker.ir_channel(spec, record["release_channels"]["ir_guidance_release_title"], "2026-08-05", TODAY, set(), lambda url: b"<rss><item>")
        self.assertEqual((channel["status"], channel["complete"], later), ("FAILED", False, []))

    def test_later_investor_day_items_are_possibly_relevant_until_reviewed(self):
        """SNDK's Investor Day release (financial model) is a review item; its reviewed ids are the registry's, on the IR host."""
        _, later = ir_read("SNDK")
        flagged = {d["id"] for d in later if d["disposition"] == "POSSIBLY_RELEVANT"}
        self.assertEqual(len(flagged), 1)
        self.assertIn(next(iter(flagged)), {r["id"] for r in REGISTRY["SNDK"]["reviewed_later_documents"]})
        _, reviewed = checker.ir_channel(REGISTRY["SNDK"]["release_channels"]["ir"], REGISTRY["SNDK"]["release_channels"]["ir_guidance_release_title"], "2026-08-05", TODAY,
                                         flagged, fx.fetchers(fx.entry_copy(FEEDS, "SNDK"))[2])
        self.assertEqual([d["disposition"] for d in reviewed if d["id"] in flagged], ["REVIEWED_IRRELEVANT"])


class NebiusNewsroomTagTests(unittest.TestCase):
    PAGE = (ROOT / "tests" / "fixtures" / "ir-feeds" / "newsroom-nebius-20261013.html").read_bytes()

    def test_the_category_tag_in_front_of_a_card_is_not_part_of_its_title(self):
        result = feeds.read_channel({"kind": "NEWSROOM_HTML", "url": "https://group.nebius.com/newsroom"}, date(2026, 8, 12), TODAY, lambda url: self.PAGE)
        self.assertEqual((result["status"], result["complete"]), ("OK", True))
        titles = {item["date"]: item["title"] for item in result["items"]}
        self.assertEqual(titles["2026-08-12"], "Nebius reports second quarter 2026 financial results")
        self.assertFalse([t for t in titles.values() if t.startswith("Press release")])

    def test_the_registry_title_matches_so_the_nebius_channel_is_complete(self):
        record = REGISTRY["NBIS"]
        channel, later = checker.ir_channel(record["release_channels"]["ir"], record["release_channels"]["ir_guidance_release_title"], "2026-08-12", TODAY, set(),
                                            fx.fetchers(fx.entry_copy(FEEDS, "NBIS"))[2])
        self.assertEqual((channel["status"], channel["complete"]), ("OK", True))
        self.assertNotIn("2026-08-12", {d["date"] for d in later})  # the guidance release itself is the reference point, not a later item

    def test_a_title_that_does_not_match_the_listed_release_is_incomplete(self):
        record = REGISTRY["NBIS"]
        channel, _ = checker.ir_channel(record["release_channels"]["ir"], "Press release Nebius reports second quarter 2026 financial results", "2026-08-12", TODAY, set(),
                                        fx.fetchers(fx.entry_copy(FEEDS, "NBIS"))[2])
        self.assertEqual((channel["status"], channel["complete"]), ("OK", False))

    def test_an_untagged_card_still_parses(self):
        old = (ROOT / "tests" / "fixtures" / "ir-feeds" / "newsroom-nebius.html").read_bytes()
        result = feeds.read_channel({"kind": "NEWSROOM_HTML", "url": "https://group.nebius.com/newsroom"}, date(2026, 8, 12), date(2026, 9, 28), lambda url: old)
        self.assertEqual(result["items"][0]["title"], "Nebius reports second quarter 2026 financial results")


class FetchBytesFallbackTests(unittest.TestCase):
    URL = "https://investor.sandisk.com/rss.xml"

    @staticmethod
    def response(body):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        return Response(body)

    def test_a_403_for_the_browser_string_is_retried_once_with_the_plain_observation_string(self):
        seen = []

        def urlopen(request, timeout=None):
            seen.append(request.get_header("User-agent"))
            if request.get_header("User-agent") == feeds.USER_AGENT:
                raise urllib.error.HTTPError(self.URL, 403, "Forbidden", {}, None)
            return self.response(b"<rss></rss>")

        with mock.patch.object(feeds.urllib.request, "urlopen", urlopen):
            self.assertEqual(feeds.fetch_bytes(self.URL), b"<rss></rss>")
        self.assertEqual(seen, [feeds.USER_AGENT, feeds.FALLBACK_USER_AGENT])
        self.assertEqual(feeds.FALLBACK_USER_AGENT, checker.WIRE_USER_AGENT)

    def test_the_browser_string_is_tried_first_and_no_retry_follows_a_success(self):
        seen = []
        with mock.patch.object(feeds.urllib.request, "urlopen", lambda request, timeout=None: seen.append(request.get_header("User-agent")) or self.response(b"ok")):
            self.assertEqual(feeds.fetch_bytes(self.URL), b"ok")
        self.assertEqual(seen, [feeds.USER_AGENT])

    def test_other_http_errors_are_not_retried(self):
        seen = []

        def urlopen(request, timeout=None):
            seen.append(request.get_header("User-agent"))
            raise urllib.error.HTTPError(self.URL, 404, "Not Found", {}, None)

        with mock.patch.object(feeds.urllib.request, "urlopen", urlopen):
            with self.assertRaises(urllib.error.HTTPError):
                feeds.fetch_bytes(self.URL)
        self.assertEqual(len(seen), 1)

    def test_a_403_for_both_strings_fails_the_read(self):
        def urlopen(request, timeout=None):
            raise urllib.error.HTTPError(self.URL, 403, "Forbidden", {}, None)

        with mock.patch.object(feeds.urllib.request, "urlopen", urlopen):
            with self.assertRaises(urllib.error.HTTPError):
                feeds.fetch_bytes(self.URL)

    def test_a_refused_channel_is_an_unverified_channel_through_read_channel(self):
        def urlopen(request, timeout=None):
            raise urllib.error.HTTPError(self.URL, 403, "Forbidden", {}, None)

        with mock.patch.object(feeds.urllib.request, "urlopen", urlopen):
            result = feeds.read_channel({"kind": "RSS", "url": self.URL}, date(2026, 8, 5), TODAY)
        self.assertEqual((result["status"], result["complete"], result["items"]), ("FAILED", False, []))

    def test_an_oversized_response_is_still_refused_after_the_retry(self):
        calls = []

        def urlopen(request, timeout=None):
            calls.append(request.get_header("User-agent"))
            if request.get_header("User-agent") == feeds.USER_AGENT:
                raise urllib.error.HTTPError(self.URL, 403, "Forbidden", {}, None)
            return self.response(b"x" * (feeds.MAX_BYTES + 1))

        with mock.patch.object(feeds.urllib.request, "urlopen", urlopen):
            with self.assertRaises(feeds.IrFeedError):
                feeds.fetch_bytes(self.URL)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
