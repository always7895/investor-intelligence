"""V16 Serenity lead signals: relay, clause stance, recency, mirror state and oEmbed verification. Synthetic posts, no network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import serenity_signals as serenity  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "serenity"
MAPPING = json.loads((ROOT / "config" / "serenity-ticker-map-v1.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
US = {"RELA", "RELB", "MIXA", "MIXB", "OWNA", "OWNB", "REPL", "ESMT", "SOLD", "ADDD", "LTRM", "NOLO", "THES", "SOUT", "NEGA", "NEGB",
      "THRD", "FLIP", "TRIM", "XXXX", "YYYY"}
REQUIRED_V1_KEYS = {"symbol", "name", "exchange", "currency", "mentions", "bullish", "bearish", "financing_concerns", "intensity",
                    "latest_at", "latest_url", "top_post", "stance"}


def make_post(post_id, text, days_ago, likes=100, now=NOW, **extra):
    created = (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    post = {"id": str(post_id), "text": text, "createdAtISO": created, "isRetweet": False, "metrics": {"likes": likes},
            "sourceUrl": f"https://x.com/aleabitoreddit/status/{post_id}"}
    post.update(extra)
    return post


def archive(posts):
    return {"source_url": serenity.ARCHIVE_URL, "repository": serenity.ARCHIVE_REPO, "retrieved_at": "2026-10-17T00:00:00Z",
            "sha256": "0" * 64, "posts": posts}


def build(posts, now=NOW, **kwargs):
    document = serenity.build_signals(archive(posts), MAPPING, US, now, **kwargs)
    return {row["symbol"]: row for row in document["signals"]}, document


def fixture_posts():
    data = json.loads((FIXTURES / "posts.json").read_text(encoding="utf-8"))
    return [make_post(item["id"], item["text"], item["days_ago"], **({"isReply": True} if item.get("isReply") else {}))
            for item in data["posts"]]


class ClauseTests(unittest.TestCase):
    def test_clause_splitting(self):
        self.assertEqual(serenity.split_clauses("Own $AB. Then sold my $B!\nok"), ["Own $AB", "Then sold my $B", "ok"])
        self.assertEqual(serenity.split_clauses("Revenue $5.6B up in the U.S. Treasury and BRK.B"),
                         ["Revenue $5.6B up in the U.S. Treasury and BRK.B"])
        self.assertEqual(serenity.split_clauses("Sold my $X, added $Y"), ["Sold my $X", "added $Y"])
        self.assertEqual(serenity.split_clauses("Added $X, $Y and $Z"), ["Added $X, $Y and $Z"])


class FixtureStanceTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.document = build(fixture_posts())

    def test_relay_list_post_gives_no_row(self):
        self.assertNotIn("RELA", self.rows)
        self.assertNotIn("RELB", self.rows)
        self.assertEqual(self.document["relay"]["posts"], 1)

    def test_partial_relay_counts_only_first_person_tickers(self):
        self.assertNotIn("MIXA", self.rows)  # appears only in the relay clause
        self.assertEqual(self.rows["MIXB"]["stance"], "BULLISH")
        self.assertEqual(self.rows["MIXB"]["relay_mentions"], 0)

    def test_own_top_holdings_are_not_relay(self):
        self.assertEqual(self.rows["OWNA"]["mentions"], 1)
        self.assertEqual(self.rows["OWNB"]["mentions"], 1)

    def test_reply_keeps_full_weight(self):
        row = self.rows["REPL"]
        self.assertEqual((row["mentions"], row["reply_mentions"], row["stance"]), (1, 1, "BULLISH"))
        self.assertGreater(row["intensity"], 0)

    def test_mixed_post_keeps_second_name_bullish(self):
        self.assertEqual(self.rows["3006.TW"]["stance"], "BULLISH")
        self.assertNotEqual(self.rows["005930.KS"]["stance"], "BEARISH")

    def test_sold_then_added(self):
        self.assertEqual(self.rows["SOLD"]["last_stance"], "BEARISH")
        self.assertEqual(self.rows["SOLD"]["stance"], "BEARISH")
        self.assertEqual(self.rows["ADDD"]["stance"], "BULLISH")

    def test_long_term_is_not_long(self):
        self.assertEqual(self.rows["LTRM"]["stance"], "MENTIONED")
        self.assertEqual(self.rows["LTRM"]["bullish"], 0)

    def test_no_longer_own_is_exit(self):
        self.assertEqual(self.rows["NOLO"]["stance"], "BEARISH")

    def test_sold_out_through_is_thesis_not_stance(self):
        self.assertEqual(self.rows["THES"]["thesis_mentions"], 1)
        self.assertEqual(self.rows["THES"]["stance"], "MENTIONED")

    def test_sold_out_of_ticker_is_exit(self):
        self.assertEqual(self.rows["SOUT"]["stance"], "BEARISH")

    def test_sold_out_of_capacity_is_not_exit(self):
        rows, _ = build([make_post(1, "$XXXX and peers are sold out of capacity for 2027", 2)])
        self.assertEqual(rows["XXXX"]["stance"], "MENTIONED")
        self.assertEqual(rows["XXXX"]["thesis_mentions"], 1)

    def test_negated_bullish_cancels(self):
        self.assertEqual(self.rows["NEGA"]["stance"], "MENTIONED")
        self.assertEqual(self.rows["NEGB"]["stance"], "MENTIONED")

    def test_third_person_holding_is_not_first_person(self):
        self.assertEqual(self.rows["THRD"]["stance"], "MENTIONED")

    def test_schema_two_keeps_schema_one_keys(self):
        self.assertEqual(self.document["schema_version"], 2)
        for row in self.rows.values():
            self.assertLessEqual(REQUIRED_V1_KEYS, set(row))
            self.assertIn(row["stance"], {"BULLISH", "BEARISH", "MENTIONED"})
            self.assertIsInstance(row["mentions"], int)
            self.assertIsInstance(row["intensity"], float)

    def test_list_continues_the_phrase_target(self):
        rows, _ = build([make_post(1, "Added $XXXX, $YYYY and $FLIP today", 1)])
        self.assertEqual(rows["XXXX"]["stance"], "BULLISH")
        self.assertEqual(rows["YYYY"]["stance"], "BULLISH")

    def test_satire_post_carries_no_stance(self):
        rows, _ = build([make_post(1, "@someone This is satire about a fund's long $XXXX short $YYYY trade (don't actually take this post "
                                      "seriously).", 2),
                         make_post(2, "Sold my $FLIP /s", 3)])
        self.assertEqual((rows["XXXX"]["stance"], rows["YYYY"]["stance"], rows["FLIP"]["stance"]), ("MENTIONED",) * 3)
        self.assertEqual((rows["YYYY"]["bearish"], rows["YYYY"]["mentions"]), (0, 1))

    def test_hypothetical_frame_carries_no_stance(self):
        rows, _ = build([make_post(1, "Today I'm writing a weekend guide on how to do DD when shorting $XXXX", 2),
                         make_post(2, "If you're long $YYYY into earnings, size it small", 2),
                         make_post(3, "I'm shorting $FLIP here", 2)])
        self.assertEqual((rows["XXXX"]["stance"], rows["YYYY"]["stance"]), ("MENTIONED", "MENTIONED"))
        self.assertEqual(rows["FLIP"]["stance"], "BEARISH")

    def test_third_party_feed_list_carries_no_stance(self):
        rows, _ = build([make_post(1, "Tech people in real life: I have shares in $XXXX.\n\nPeople on my X feed/comments:\n\n"
                                      "- Long $YYYY short $FLIP because inverse indicators\n\n- calls on $TRIM\n\nI'm long $THES here", 2),
                         make_post(2, "Everyone on X is bearish on $NEGA: I sold my $SOLD", 3),
                         make_post(3, "People are underestimating $ADDD: I added more", 3)])
        self.assertEqual([rows[s]["stance"] for s in ("XXXX", "YYYY", "FLIP", "TRIM")], ["MENTIONED"] * 4)
        self.assertEqual((rows["YYYY"]["mentions"], rows["FLIP"]["bearish"]), (1, 0))
        self.assertEqual(rows["THES"]["stance"], "BULLISH")  # his own line after the list
        self.assertEqual((rows["SOLD"]["stance"], rows["ADDD"]["stance"]), ("BEARISH", "BULLISH"))  # a cashtag or no "on/in"

    def test_anaphoric_trim_targets_previous_clause(self):
        rows, _ = build([make_post(1, "With $XXXX, $YYYY and $FLIP / $THES\nI trimmed down those positions aside from $THES longs", 2),
                         make_post(2, "$NEGA and $NEGB\nI trimmed today", 2)])
        self.assertEqual((rows["XXXX"]["last_stance"], rows["YYYY"]["last_stance"]), ("TRIM", "TRIM"))
        self.assertEqual((rows["XXXX"]["stance"], rows["XXXX"]["bearish"]), ("MENTIONED", 1))  # a trim alone is never BEARISH
        self.assertIsNone(rows["THES"]["last_stance"])  # excepted
        self.assertIsNone(rows["FLIP"]["last_stance"])  # joined to the excepted name by "/"
        self.assertIsNone(rows["NEGA"]["last_stance"])  # no anaphoric object


class FirstPersonVerbTests(unittest.TestCase):
    """V18 S1: first-person verbs (I or we within two tokens before the verb) and the counterfactual guard."""

    CASES = [
        ("I sold $XXXX today", "BEARISH"),
        ("I just sold $XXXX", "BEARISH"),
        ("we've finally dumped $XXXX", "BEARISH"),
        ("I closed my $XXXX", "BEARISH"),
        ("I closed out $XXXX", "BEARISH"),
        ("I scaled out of $XXXX", "BEARISH"),
        ("I've rotated out of $XXXX", "BEARISH"),
        ("I'm out of $XXXX", "BEARISH"),
        ("I scaled back $XXXX", "TRIM"),
        ("I also took some off $XXXX", "TRIM"),
        ("I doubled down on $XXXX", "BULLISH"),
        ("I loaded up on $XXXX", "BULLISH"),
        ("we increased my position in $XXXX", "BULLISH"),
        ("I raised my stake in $XXXX", "BULLISH"),
        ("I opened a position in $XXXX", "BULLISH"),
        ("I should have sold $XXXX", None),  # counterfactual: no stance
        ("shoulda sold $XXXX", None),
        ("wish I sold $XXXX", None),
        ("if only I had dumped $XXXX", None),
        ("I could have bought more $XXXX", None),  # existing phrase, now guarded
        ("He sold $XXXX", None),  # third person
        ("The fund dumped $XXXX", None),
        ("closed my $XXXX", None),  # no pronoun
        ("Closed $XXXX at 12", None),  # plain "closed" never counts
        ("I sold out of capacity at $XXXX", None),  # supply talk, not a first-person sale
        ("I sold covered calls on $XXXX", None),  # option writing is not an exit
        ("I sold puts on $XXXX", None),  # a short put is not a bearish exit
        ("I bought puts on $XXXX", "BEARISH"),
    ]

    def test_phrase_table(self):
        for index, (text, expected) in enumerate(self.CASES, start=1):
            rows, _ = build([make_post(index, text, 1)])
            self.assertEqual(rows["XXXX"]["last_stance"], expected, text)

    def test_sold_then_bought_splits_targets(self):
        rows, _ = build([make_post(1, "I sold $XXXX and bought $YYYY", 1)])
        self.assertEqual((rows["XXXX"]["last_stance"], rows["YYYY"]["last_stance"]), ("BEARISH", "BULLISH"))
        rows, _ = build([make_post(2, "I dumped $XXXX and I loaded up on $YYYY", 1)])
        self.assertEqual((rows["XXXX"]["last_stance"], rows["YYYY"]["last_stance"]), ("BEARISH", "BULLISH"))


class RecencyTests(unittest.TestCase):
    def test_flip_to_bearish(self):
        posts = [make_post(i, "Still holding $FLIP, added more", 60 + i * 10) for i in range(6)]
        posts += [make_post(100 + i, "I sold my $FLIP after the ATM", 7 - i) for i in range(2)]
        rows, _ = build(posts)
        self.assertEqual(rows["FLIP"]["stance"], "BEARISH")
        self.assertEqual(rows["FLIP"]["bullish"], 6)
        self.assertEqual(rows["FLIP"]["bearish"], 2)

    def test_single_recent_trim_after_many_bullish_is_not_bearish(self):
        posts = [make_post(i, "Added more $TRIM", 3 + i) for i in range(8)]
        posts.append(make_post(99, "Trimmed $TRIM a bit", 1))
        rows, _ = build(posts)
        row = rows["TRIM"]
        self.assertEqual(row["last_stance"], "TRIM")
        self.assertEqual(row["stance"], "BULLISH")
        self.assertEqual(row["bearish"], 1)
        self.assertLess(row["bearish_decayed"], 0.6)

    def test_lone_trim_is_mentioned(self):
        rows, _ = build([make_post(1, "Took profits on $TRIM", 2)])
        self.assertEqual(rows["TRIM"]["stance"], "MENTIONED")

    def test_old_post_outside_window(self):
        rows, _ = build([make_post(1, "Added $XXXX", 130)])
        self.assertNotIn("XXXX", rows)


class MirrorTests(unittest.TestCase):
    def mirror(self, hours):
        latest = NOW - timedelta(hours=hours)
        post = make_post(1, "Added $XXXX", 0, now=latest)
        _, document = build([post])
        return document["source"]

    def test_levels(self):
        self.assertEqual(self.mirror(72)["mirror_status"], "FRESH")
        self.assertEqual(self.mirror(73)["mirror_status"], "STALE")
        self.assertEqual(self.mirror(14 * 24)["mirror_status"], "STALE")
        self.assertEqual(self.mirror(14 * 24 + 1)["mirror_status"], "DEAD")
        self.assertEqual(self.mirror(5)["mirror_lag_hours"], 5.0)


class OembedTests(unittest.TestCase):
    def posts(self):
        return [make_post(11, "Added $XXXX", 2, likes=500), make_post(12, "Added $XXXX", 3, likes=900),
                make_post(13, "Added $YYYY", 4, likes=50)]

    def verify(self, fetch, cache=None, budget=120.0, clock=None, limit=5):
        return serenity.build_verified(archive(self.posts()), MAPPING, US, NOW, limit=limit, fetch=fetch,
                                       cache={} if cache is None else cache, budget_seconds=budget,
                                       clock=clock or (lambda: 0.0))

    def test_ok_and_cache_write(self):
        cache = {}
        document, checker = self.verify(lambda url, timeout: 200, cache)
        rows = {row["symbol"]: row for row in document["signals"]}
        self.assertEqual(rows["XXXX"]["verified"], {"latest": "OK", "top": "OK"})
        self.assertEqual(document["source"]["oembed"]["not_found"], 0)
        self.assertTrue(checker.dirty)
        self.assertEqual(cache["11"]["status"], "OK")

    def test_not_found_drops_post_and_rebuilds(self):
        def fetch(url, timeout):
            return 404 if url.endswith("/12") else 200
        cache = {}
        document, _ = self.verify(fetch, cache)
        rows = {row["symbol"]: row for row in document["signals"]}
        self.assertEqual(rows["XXXX"]["mentions"], 1)
        self.assertEqual(rows["XXXX"]["latest_url"].rsplit("/", 1)[1], "11")
        self.assertEqual(cache["12"]["status"], "NOT_FOUND")
        self.assertEqual(document["source"]["oembed"]["not_found"], 1)

    def test_timeout_is_unavailable_and_not_cached(self):
        def fetch(url, timeout):
            raise TimeoutError()
        cache = {}
        document, _ = self.verify(fetch, cache)
        self.assertEqual(document["signals"][0]["verified"], {"latest": "UNAVAILABLE", "top": "UNAVAILABLE"})
        self.assertEqual(cache, {})

    def test_server_error_is_unavailable(self):
        document, _ = self.verify(lambda url, timeout: 402)
        self.assertEqual(document["signals"][0]["verified"]["latest"], "UNAVAILABLE")

    def test_budget_exhausted_makes_no_requests(self):
        calls = []
        ticks = iter([0.0] + [500.0] * 50)
        document, _ = self.verify(lambda url, timeout: calls.append(url) or 200, budget=120.0, clock=lambda: next(ticks))
        self.assertEqual(calls, [])
        self.assertEqual(document["signals"][0]["verified"]["latest"], "UNAVAILABLE")

    def test_cache_rules(self):
        fresh = serenity.iso(NOW - timedelta(days=29))
        old = serenity.iso(NOW - timedelta(days=31))
        calls = []
        cache = {"11": {"status": "OK", "checked_at": fresh}, "12": {"status": "NOT_FOUND", "checked_at": old},
                 "13": {"status": "OK", "checked_at": old}}
        document, _ = self.verify(lambda url, timeout: calls.append(url) or 200, cache)
        self.assertEqual(calls, ["https://x.com/aleabitoreddit/status/13"])  # 11 fresh OK, 12 permanent NOT_FOUND, 13 expired
        rows = {row["symbol"]: row for row in document["signals"]}
        self.assertEqual(rows["XXXX"]["mentions"], 1)  # 12 stays dropped without a request
        self.assertEqual(cache["13"]["checked_at"], serenity.iso(NOW))

    def test_oembed_url_and_status_mapping(self):
        seen = {}

        def fetch(url, timeout):
            seen["url"], seen["timeout"] = url, timeout
            return 200
        checker = serenity.OembedChecker(fetch, {}, NOW)
        self.assertEqual(checker.status("https://x.com/a/status/9"), "OK")
        self.assertEqual(seen["timeout"], 10.0)
        self.assertEqual(checker.status("https://x.com/a/status/9"), "OK")
        self.assertEqual(checker.status("https://x.com/a/nope"), "UNAVAILABLE")
        self.assertTrue(serenity.OEMBED_URL.startswith("https://publish.twitter.com/oembed?url="))
        self.assertIn("omit_script=1", serenity.OEMBED_URL)

    def test_cache_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "c.json"
            self.assertEqual(serenity.load_oembed_cache(path), {})
            serenity.save_oembed_cache(path, {"1": {"status": "OK", "checked_at": "2026-10-18T00:00:00Z"}})
            self.assertEqual(serenity.load_oembed_cache(path)["1"]["status"], "OK")

    def test_defaults(self):
        self.assertEqual(serenity.OEMBED_DEFAULT_LIMIT, 25)
        self.assertEqual(serenity.OEMBED_BUDGET_SECONDS, 120.0)
        sample = json.loads((FIXTURES / "oembed_ok.json").read_text(encoding="utf-8"))
        self.assertIn("html", sample)


if __name__ == "__main__":
    unittest.main()
