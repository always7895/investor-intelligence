import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issuer_ir_feeds as feeds  # noqa: E402

SAMPLES = ROOT / "tests" / "fixtures" / "ir-feeds"  # official IR responses captured 2026-09-28 (Q4 sample reduced to read fields)
TODAY = date(2026, 9, 28)


def local(name):
    return lambda url: (SAMPLES / name).read_bytes()


class IrFeedTests(unittest.TestCase):
    def test_q4_feed_lists_the_whole_year_and_keeps_same_day_items(self):
        seen = []
        result = feeds.read_channel({"kind": "Q4_PRESS_RELEASES", "url": "https://investor.nvidia.com/feed/PressRelease.svc/GetPressReleaseList"},
                                    date(2026, 8, 26), TODAY, lambda url: seen.append(url) or local("q4-nvidia-2026.json")(url))
        self.assertEqual((result["status"], result["complete"]), ("OK", True))
        self.assertEqual(len(seen), 1)
        self.assertIn("pageSize=-1", seen[0])
        self.assertIn("year=2026", seen[0])
        titles = {item["title"] for item in result["items"] if item["date"] == "2026-08-26"}
        self.assertIn("NVIDIA Announces Financial Results for Second Quarter Fiscal 2027", titles)  # the guidance release itself
        self.assertTrue(all(item["date"] >= "2026-08-26" for item in result["items"]))
        self.assertTrue(all(item["id"].startswith("https://investor.nvidia.com/news/") for item in result["items"]))

    def test_q4_feed_reads_every_year_from_the_guidance_year(self):
        seen = []
        feeds.read_channel({"kind": "Q4_PRESS_RELEASES", "url": "https://investor.nvidia.com/feed/PressRelease.svc/GetPressReleaseList"},
                           date(2025, 11, 19), TODAY, lambda url: seen.append(url) or local("q4-nvidia-2026.json")(url))
        self.assertEqual([u.split("year=")[1].split("&")[0] for u in seen], ["2025", "2026"])

    def test_rss_is_complete_only_when_it_reaches_before_the_start(self):
        rss = {"kind": "RSS", "url": "https://investor.marvell.com/news-events/press-releases/rss"}
        result = feeds.read_channel(rss, date(2026, 8, 27), TODAY, local("rss-marvell.xml"))
        self.assertEqual((result["status"], result["complete"]), ("OK", True))
        self.assertEqual(result["items"][0]["date"], "2026-08-27")
        # the ten newest items do not reach back to a start in May: incomplete, never a quiet success
        self.assertFalse(feeds.read_channel(rss, date(2026, 5, 1), TODAY, local("rss-marvell.xml"))["complete"])

    def test_newsroom_list_parses_dated_items_and_skips_navigation(self):
        news = {"kind": "NEWSROOM_HTML", "url": "https://group.nebius.com/newsroom"}
        result = feeds.read_channel(news, date(2026, 8, 12), TODAY, local("newsroom-nebius.html"))
        self.assertEqual((result["status"], result["complete"]), ("OK", True))
        self.assertEqual(result["items"][0]["date"], "2026-08-12")
        self.assertTrue(result["items"][0]["title"].lower().startswith("nebius reports second quarter 2026"))
        self.assertTrue(all(item["id"].startswith("https://group.nebius.com/newsroom/") for item in result["items"]))

    def test_failures_are_failed_and_incomplete(self):
        def boom(url):
            raise OSError("blocked")
        for channel, fetch in (({"kind": "RSS", "url": "https://x.example/rss"}, boom),
                               ({"kind": "RSS", "url": "https://x.example/rss"}, lambda url: b"<rss></rss>"),
                               ({"kind": "Q4_PRESS_RELEASES", "url": "https://x.example/feed"}, lambda url: b'{"other": 1}'),
                               ({"kind": "NEWSROOM_HTML", "url": "https://x.example/newsroom"}, lambda url: b"<html></html>"),
                               ({"kind": "PDF", "url": "https://x.example/a"}, boom),
                               ({"kind": "RSS", "url": "http://x.example/rss"}, boom)):
            result = feeds.read_channel(channel, date(2026, 8, 1), TODAY, fetch)
            self.assertEqual((result["status"], result["complete"], result["items"]), ("FAILED", False, []), channel)


if __name__ == "__main__":
    unittest.main()


class RssIntegrityTests(unittest.TestCase):
    def test_truncated_rss_is_a_failed_read(self):
        body = (SAMPLES / "rss-marvell.xml").read_bytes()
        cut = body[: body.rindex(b"</channel>")] + b"<item><title>Marvell Announces Preliminary Results"
        result = feeds.read_channel({"kind": "RSS", "url": "https://investor.marvell.com/news-events/press-releases/rss"},
                                    date(2026, 8, 27), TODAY, lambda url: cut)
        self.assertEqual((result["status"], result["complete"], result["items"]), ("FAILED", False, []))
        self.assertEqual(result["error"], "RSS_MALFORMED")
