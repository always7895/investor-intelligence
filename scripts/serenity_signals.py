#!/usr/bin/env python3
"""Serenity (@aleabitoreddit) lead signals from the public post archive (Top20 v3 lead layer).

Source: the public GitHub archive yan-labs/serenity-aleabitoreddit (data/aleabitoreddit_tweets.json), which mirrors
the author's X posts with ids, timestamps and engagement; each signal cites its post URL. Posts are LEADS, never
company facts: a mention can admit a company to the candidate universe and weight its lead score, but figures in
the Top20 always come from company filings and market data.

Per listing (cashtags validated against the official US directory, other tags and names through
config/serenity-ticker-map-v1.json): original-post mentions in the last 120 days, recency- and engagement-weighted
intensity (30-day half-life), stance counts, dilution/financing concerns, the latest mention and the most-engaged
recent post. Retweets are excluded. Schema 2 (V16):

* Relay: posts that only report a fund's filing ("Situational Awareness 13F holdings ...") give relay_mentions and no
  stance, intensity or mention. Replies keep full weight and are also counted in reply_mentions.
* Stance is read per clause (exit, trim, topic and bullish phrases attached to the nearest ticker); the decayed
  bullish/bearish weights and the newest stance phrase decide BULLISH, BEARISH or MENTIONED. A third-party header
  ("People on my X feed:") and the list under it carry no stance; a first-person trim or exit of "those positions" applies to
  the previous clause's listings, minus the excepted ones.
* source.mirror_lag_hours / mirror_status say how stale the public mirror is; the ranking recomputes them.
* Under --refresh the strongest symbols' posts are checked through X's public oEmbed endpoint (no login, no cookies);
  a post that is gone (404) is dropped for every ticker it names.

Usage: serenity_signals.py [--refresh] [--if-older-than-hours H] [--archive PATH] [--output PATH]
                           [--verify-oembed N] [--oembed-cache PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_URL = "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/aleabitoreddit_tweets.json"
ARCHIVE_REPO = "https://github.com/yan-labs/serenity-aleabitoreddit"
ARCHIVE_CACHE = ROOT / "data" / "cache" / "serenity_archive.json"
OUTPUT = ROOT / "data" / "cache" / "serenity_signals_latest.json"
OEMBED_CACHE = ROOT / "data" / "cache" / "serenity_oembed_cache.json"
TICKER_MAP = ROOT / "config" / "serenity-ticker-map-v1.json"
IDENTITY = ROOT / "data" / "cache" / "identity_shards_latest.json"
WINDOW_DAYS = 120
HALF_LIFE_DAYS = 30.0
SCHEMA_VERSION = 2
TRIM_WEIGHT = 0.5
BEARISH_SHARE = 0.5  # BEARISH when the newest stance is an exit and bearish_decayed >= this share of bullish_decayed
MIRROR_FRESH_HOURS = 72.0
MIRROR_STALE_HOURS = 14 * 24.0
OEMBED_URL = "https://publish.twitter.com/oembed?url={url}&omit_script=1"
OEMBED_DEFAULT_LIMIT = 25
OEMBED_BUDGET_SECONDS = 120.0
OEMBED_TIMEOUT = 10.0
OEMBED_OK_DAYS = 30
OEMBED_PASSES = 2

CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9.]{0,7})\b")
# First person for the verbs below: the pronoun I or we, at most two tokens before the verb ("I've just", "we also").
FP = r"(?P<fp>\b(?:i|we)(?:'ve|'m|\s+have|\s+am)?\s+(?:(?:just|finally|also)\s+){0,2})"
# "sold $X puts", "sold the calls", "sold all my $X calls": option writing or closing an option is not an exit (up to three
# object tokens before the option word; "sold covered/cash/premium" only right after the verb).
NOT_OPTION = r"(?!(?:\s+[\w$.%/-]+){0,3}?\s+(?:puts?|calls?|options?|leaps)\b)"
# Stance phrases, matched per clause in this priority: exit, trim, topic, bullish (overlaps go to the earlier class).
EXIT_PHRASES = re.compile(
    r"(?:" + FP + r"(?:sold(?!\s+(?:out|covered|cash|premium)\b)" + NOT_OPTION + r"(?: off)?|dumped|closed (?:my|out)|"
    r"(?:scaled|rotated) out of)\b|\bi(?:'m| am) out of\b)"
    r"|\b(?:sold (?:my|all|the rest|out of)" + NOT_OPTION + r"|exited|exit(?:ing)? my|no longer (?:own|hold|long)|shorting|shorted|"
    r"short(?=\s+\$)|(?:i'm|i am|am|went) short|(?<!\bsold )(?<!\bselling )puts?\s+on|bearish on|avoid|not a fan|overvalued|"
    r"wouldn't touch)\b", re.I)
TRIM_PHRASES = re.compile(
    r"(?:" + FP + r"(?:scaled back|took some off)\b)"
    r"|\b(?:trimmed|trimming|(?:took|taking) profits?|(?:reduced|reducing|cut|cutting) my (?:position|stake))\b", re.I)
TOPIC_PHRASES = re.compile(r"\b(?:bottlenecks?|shortages?|sold out|allocations?|supply.constrained)\b", re.I)
BULLISH_PHRASES = re.compile(
    r"(?:" + FP + r"(?:doubled down on|loaded up on|(?:increased|raised) my (?:position|stake)|opened a position)\b)"
    r"|\b(?:own(?:ing)?|holding|added|adding|add(?:ed)? more|bought|buying|my position|top holding|largest position|"
    r"conviction|bullish on|long(?=\s+\$)|(?:i'm|i am|am|went|stay(?:ing)?|still) long\b(?!\W*(?:term|time))|"
    r"started a (?:new )?position|initiated|accumulat\w*|cost.averag\w*)\b", re.I)
NEGATION_BEFORE = re.compile(r"\b(?:not|never|no|don't|dont|didn't|didnt)\b\W+(?:\w+\W+){0,2}$", re.I)
OWN_OF_MINE = re.compile(r"\b(?:my|your|our)\s+$", re.I)  # "my own research" is not ownership of a ticker
THIRD_PERSON_BEFORE = re.compile(
    r"\b(?:he|she|they|his|her|their|its|fund|funds|leopold|aschenbrenner|citadel|insiders?|management|ceo)\b(?:\W+\w+){0,3}\W*$",
    re.I)
EXCEPT_MARKER = re.compile(r"\b(?:except|other than|apart from|aside from|besides)\b", re.I)
# "I thought $X was overvalued" states a past view, not a current exit.
PAST_VIEW_BEFORE = re.compile(r"\b(?:thought|used to think|used to)\b(?:\W+\w+){0,6}\W*$", re.I)
# "a guide on how to do DD when shorting $X" or "if you're long $X" frames a case, not his own stance (any phrase class).
# The frame reaches at most four words and stops at a clause break ("That would have been bad, so I sold $X" is a sale).
HYPOTHETICAL_BEFORE = re.compile(r"\b(?:how to|guide (?:on|to)|if you(?:'re| are)?|in case you|(?:should|could|would)(?: not)?(?: have|'ve)|"
                                 r"shoulda|coulda|woulda|wish i|if only i)\b"
                                 r"(?:(?!\W*[,;:]|\W+(?:so|but|then|because|since)\b)\W+\w+){0,4}(?:(?![,;:])\W)*$", re.I)
# A post he marks as satire or a joke carries no stance for any ticker it names (its mentions still count).
SATIRE = re.compile(r"\b(?:satire|satirical|parody|just kidding|(?:don't|do not) (?:actually )?take this (?:post )?seriously)\b"
                    r"|(?<![\w/])/s(?![\w/])", re.I)
# "People on my X feed/comments:" or "Tech people in real life: ..." reports what others hold or trade: that line and the
# blank or bullet lines under it carry no stance (their mentions still count). A cashtag before the colon is not a header.
THIRD_PARTY_HEADER = re.compile(
    r"^\W*(?:[\w'-]+\s+){0,2}(?:people|everyone|folks|accounts)\s+(?:on|in)\s+(?:my\s+)?(?:x|twitter|fintwit|reddit|real life|"
    r"irl|the replies|the comments|feed|timeline|tl|comments|replies|mentions|dms?)\b[^:\n$]{0,30}:", re.I)
LIST_LINE = re.compile(r"^\s*(?:$|[-*>•–—]|\d+[.)]\s)")
# "I trimmed down those positions": an anaphoric object right after a trim or exit names the previous clause's listings.
ANAPHORIC_OBJECT = re.compile(r"^\s*(?:(?:down|back)\s+)?(?:(?:all|both|most|some|many)\s+(?:of\s+)?)?(?:those|these|them)\b"
                              r"(?:\s+(?:positions?|names|stocks|holdings))?", re.I)
SLASH_GAP = re.compile(r"^\s*/\s*$")
SOLD_OUT_OF = re.compile(r"^sold out of$", re.I)
OBJECT_LEAD = re.compile(r"\s*(?:(?:my|the|all|any)\s+)?", re.I)
LIST_GAP = re.compile(r"^[\s,&/+]*(?:(?:and|or)[\s,&/+]+)?$", re.I)
SENTENCE_BREAK = re.compile(r"[\n;!?]+|(?:(?<=[A-Za-z]{2})|(?<=[0-9)\]]))\.\s+(?=[A-Z])")
FUND_WORDS = re.compile(r"\b(?:situational awareness|leopold|aschenbrenner|13-?f)\b", re.I)
REPORT_WORDS = re.compile(r"\b(?:holdings?|holds?|filed|filing|disclosed|bought|sold|stakes?|positions?|liquidat\w*)\b", re.I)
FIRST_PERSON_I = re.compile(r"\bI(?:'m|'ve|'ll|'d)?(?![\w'])")
FIRST_PERSON_WORDS = re.compile(r"\b(?:my|we|our|we're|we've)(?!\w)", re.I)
FINANCING = re.compile(r"\b(?:ATM|dilut\w*|share offering|convertible|stock comp\w*)\b", re.I)
IGNORED_TAGS = {"USD", "BTC", "ETH", "SPX", "SPY", "QQQ", "NDX", "VIX"}
STATUS_ID = re.compile(r"/status/(\d+)")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_archive(path: Path = ARCHIVE_CACHE) -> dict[str, Any]:
    request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "InvestorIntelligence public research"})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - fixed public HTTPS source
        raw = response.read()
    posts = json.loads(raw.decode("utf-8"))
    if not isinstance(posts, list) or len(posts) < 1000:
        raise ValueError("SERENITY_ARCHIVE_TOO_SMALL")
    envelope = {"source_url": ARCHIVE_URL, "repository": ARCHIVE_REPO, "retrieved_at": iso(utc_now()),
                "sha256": hashlib.sha256(raw).hexdigest(), "posts": posts}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
    temp.replace(path)
    return envelope


def us_symbols(path: Path = IDENTITY) -> set[str]:
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return set()
    return {row[0] for shard in document.get("symbol_shards", {}).values() for row in shard["rows"] if row[2] == "US"}


def listing_for_tag(tag: str, mapping: dict[str, Any], us: set[str]) -> dict[str, Any] | None:
    tag = tag.upper().rstrip(".")
    if tag in IGNORED_TAGS:
        return None
    if tag in mapping["cashtags"]:
        return {"key": mapping["cashtags"][tag]["symbol"], **mapping["cashtags"][tag]}
    if tag in us:
        return {"key": tag, "symbol": tag, "exchange": "US", "currency": "USD"}
    return None


def listing_spans(text: str, mapping: dict[str, Any], us: set[str]) -> list[tuple[int, int, str, dict[str, Any]]]:
    """Every cashtag and name occurrence as (start, end, key, listing), in text order."""
    spans: list[tuple[int, int, str, dict[str, Any]]] = []
    for match in CASHTAG.finditer(text):
        listing = listing_for_tag(match.group(1), mapping, us)
        if listing:
            spans.append((match.start(), match.end(), listing["key"], listing))
    lowered = text.lower()
    for name, row in mapping["names"].items():
        for match in re.finditer(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", lowered):
            spans.append((match.start(), match.end(), row["symbol"], {"key": row["symbol"], **row}))
    return sorted(spans, key=lambda item: (item[0], item[1]))


def listings_in(text: str, mapping: dict[str, Any], us: set[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for tag in CASHTAG.findall(text):
        listing = listing_for_tag(tag, mapping, us)
        if listing:
            found[listing["key"]] = listing
    lowered = text.lower()
    for name, row in mapping["names"].items():
        if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", lowered):
            found.setdefault(row["symbol"], {"key": row["symbol"], **row})
    return found


def parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def has_stance(clause: str) -> bool:
    return bool(EXIT_PHRASES.search(clause) or TRIM_PHRASES.search(clause) or BULLISH_PHRASES.search(clause))


def split_clauses(text: str) -> list[str]:
    """Newline, ';', '!', '?' and '. ' before an uppercase letter end a clause; a comma does when both sides hold a stance phrase."""
    clauses: list[str] = []
    for sentence in SENTENCE_BREAK.split(text.replace("’", "'")):
        if not sentence or not sentence.strip():
            continue
        parts = sentence.split(",")
        current = parts[0]
        for part in parts[1:]:
            if has_stance(current) and has_stance(part):
                clauses.append(current)
                current = part
            else:
                current = current + "," + part
        clauses.append(current)
    return [clause.strip() for clause in clauses if clause.strip()]


def is_first_person(clause: str) -> bool:
    return bool(FIRST_PERSON_I.search(clause) or FIRST_PERSON_WORDS.search(clause))


def is_relay_clause(clause: str) -> bool:
    return bool(FUND_WORDS.search(clause) and REPORT_WORDS.search(clause) and not is_first_person(clause))


def phrase_matches(clause: str, spans: list[tuple[int, int, str, dict[str, Any]]] | None = None) -> list[tuple[int, int, str]]:
    """Non-overlapping stance phrases of one clause as (start, end, kind); kind in EXIT, TRIM, TOPIC, BULL."""
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, int, str]] = []
    for kind, pattern in (("EXIT", EXIT_PHRASES), ("TRIM", TRIM_PHRASES), ("TOPIC", TOPIC_PHRASES), ("BULL", BULLISH_PHRASES)):
        for match in pattern.finditer(clause):
            start, end = match.span()
            if any(start < taken_end and taken_start < end for taken_start, taken_end in taken):
                continue
            before = clause[:start]
            if kind != "TOPIC" and HYPOTHETICAL_BEFORE.search(clause[:start + len(match.groupdict().get("fp") or "")]):
                continue
            if kind == "EXIT" and PAST_VIEW_BEFORE.search(before):
                continue
            if kind == "EXIT" and SOLD_OUT_OF.match(match.group(0)) and spans is not None:
                # "sold out of $X" is an exit; "sold out of capacity" is supply talk (a thesis topic, no stance).
                object_at = end + OBJECT_LEAD.match(clause[end:]).end()
                if not any(item[0] == object_at for item in spans):
                    taken.append((start, end))
                    found.append((start, end, "TOPIC"))
                    continue
            if kind == "BULL":
                if NEGATION_BEFORE.search(before):
                    continue
                if match.group(0).lower() in {"own", "owning", "holding"}:
                    if THIRD_PERSON_BEFORE.search(before) or OWN_OF_MINE.search(before):
                        continue
            taken.append((start, end))
            found.append((start, end, kind))
    return sorted(found)


def phrase_targets(start: int, end: int, clause: str, spans: list[tuple[int, int, str, dict[str, Any]]]) -> list[str]:
    """Tickers a phrase applies to: the nearest following one (plus a plain list continuing it), else the nearest preceding."""
    exception = EXCEPT_MARKER.search(clause, end)
    limit = exception.start() if exception else len(clause)
    following = [item for item in spans if item[0] >= end and item[1] <= limit]
    if following:
        chosen = [following[0]]
        for item in following[1:]:
            if LIST_GAP.match(clause[chosen[-1][1]:item[0]]):
                chosen.append(item)
            else:
                break
        return [item[2] for item in chosen]
    if exception:
        return []  # "trimmed everything except X": the excepted ticker is not the object
    preceding = [item for item in spans if item[1] <= start]
    if not preceding:
        return []
    chosen = [preceding[-1]]
    for item in reversed(preceding[:-1]):
        if LIST_GAP.match(clause[item[1]:chosen[-1][0]]):
            chosen.append(item)
        else:
            break
    return [item[2] for item in chosen]


def post_lines(text: str) -> list[tuple[str, bool]]:
    """The post's lines, each flagged True inside a third-party header block (the header line and the list under it)."""
    lines: list[tuple[str, bool]] = []
    inside = False
    for line in text.split("\n"):
        if THIRD_PARTY_HEADER.match(line):
            inside = True
        elif inside and not LIST_LINE.match(line):
            inside = False
        lines.append((line, inside))
    return lines


def anaphoric_targets(end: int, clause: str, spans: list[tuple[int, int, str, dict[str, Any]]],
                      previous: tuple[str, list[tuple[int, int, str, dict[str, Any]]]] | None) -> list[str]:
    """"I trimmed down those positions aside from X": the previous clause's listings, minus the excepted ones and listings
    joined to an excepted one by "/" ("$EWY / SK Hynix")."""
    if previous is None or not is_first_person(clause) or not ANAPHORIC_OBJECT.match(clause[end:]):
        return []
    prev_clause, prev_spans = previous
    exception = EXCEPT_MARKER.search(clause, end)
    excepted = {item[2] for item in spans if exception and item[0] >= exception.end()}
    chosen: list[str] = []
    for index, item in enumerate(prev_spans):
        if item[2] in excepted:
            continue
        neighbours = [prev_spans[j] for j in (index - 1, index + 1) if 0 <= j < len(prev_spans)]
        if any(other[2] in excepted and SLASH_GAP.match(prev_clause[min(other[1], item[1]):max(other[0], item[0])])
               for other in neighbours):
            continue
        if item[2] not in chosen:
            chosen.append(item[2])
    return chosen


def analyze_post(text: str, mapping: dict[str, Any], us: set[str]) -> dict[str, Any]:
    """Per-post reading: listings, per-ticker last stance (BULLISH, TRIM, BEARISH), thesis keys and relay classification."""
    found = listings_in(text, mapping, us)
    stance: dict[str, str] = {}
    thesis: set[str] = set()
    relay_keys: set[str] = set()
    nonrelay_keys: set[str] = set()
    any_relay = False
    any_first_person = False
    satire = bool(SATIRE.search(text))
    previous: tuple[str, list[tuple[int, int, str, dict[str, Any]]]] | None = None
    # Clauses never span a newline (SENTENCE_BREAK), so the post is read line by line.
    for line, third_party in post_lines(text):
        for clause in split_clauses(line):
            spans = listing_spans(clause, mapping, us)
            keys = {item[2] for item in spans}
            if is_first_person(clause):
                any_first_person = True
            if is_relay_clause(clause):
                any_relay = True
                relay_keys |= keys
                continue
            nonrelay_keys |= keys
            for start, end, kind in phrase_matches(clause, spans):
                if (satire or third_party) and kind != "TOPIC":
                    continue
                targets = phrase_targets(start, end, clause, spans)
                if not targets and kind in {"EXIT", "TRIM"}:
                    targets = anaphoric_targets(end, clause, spans, previous)
                for key in targets:
                    if kind == "TOPIC":
                        thesis.add(key)
                    else:
                        stance[key] = {"EXIT": "BEARISH", "TRIM": "TRIM", "BULL": "BULLISH"}[kind]
            if spans and not third_party:
                previous = (clause, spans)
    relay_post = bool(any_relay and not any_first_person)
    if relay_post:
        relay_keys = set(found)
    else:
        relay_keys -= nonrelay_keys
    return {"found": found, "stance": stance, "thesis": thesis, "relay_post": relay_post, "relay_keys": relay_keys}


def status_id(url: Any) -> str | None:
    match = STATUS_ID.search(str(url or ""))
    return match.group(1) if match else None


def post_key(post: dict[str, Any]) -> str:
    return status_id(post.get("sourceUrl")) or str(post.get("id"))


def mirror_state(now: datetime, latest_post: datetime | None) -> tuple[float | None, str]:
    if latest_post is None:
        return None, "DEAD"
    hours = max(0.0, (now - latest_post).total_seconds() / 3600)
    return round(hours, 1), ("FRESH" if hours <= MIRROR_FRESH_HOURS else "STALE" if hours <= MIRROR_STALE_HOURS else "DEAD")


def build_signals(archive: dict[str, Any], mapping: dict[str, Any], us: set[str], now: datetime, *,
                  exclude_ids: Iterable[str] = ()) -> dict[str, Any]:
    start = now - timedelta(days=WINDOW_DAYS)
    excluded = {str(item) for item in exclude_ids}
    signals: dict[str, dict[str, Any]] = {}
    newest: dict[str, tuple[datetime, str]] = {}
    relay_pending: dict[str, int] = {}
    relay_posts = 0
    latest_post: datetime | None = None
    for post in archive["posts"]:
        if post.get("isRetweet"):
            continue
        created = parse_time(post.get("createdAtISO"))
        if created is None or post_key(post) in excluded:
            continue
        latest_post = max(latest_post or created, created)
        if created < start or created > now + timedelta(minutes=5):
            continue
        text = str(post.get("text") or "")
        reading = analyze_post(text, mapping, us)
        found = reading["found"]
        if not found:
            continue
        if reading["relay_post"]:
            relay_posts += 1
        for key in reading["relay_keys"]:
            relay_pending[key] = relay_pending.get(key, 0) + 1
        counted = {key: listing for key, listing in found.items() if key not in reading["relay_keys"]}
        if not counted:
            continue
        is_reply = bool(post.get("isReply")) or text.lstrip().startswith("@")
        metrics = post.get("metrics") or {}
        engagement = math.log1p(float(metrics.get("likes") or 0) + 2 * float(metrics.get("retweets") or 0))
        decay = 0.5 ** ((now - created).total_seconds() / 86400 / HALF_LIFE_DAYS)
        financing = bool(FINANCING.search(text))
        url = str(post.get("sourceUrl") or f"https://x.com/aleabitoreddit/status/{post.get('id')}")
        for key, listing in counted.items():
            row = signals.setdefault(key, {"symbol": listing["symbol"], "name": listing.get("name"), "exchange": listing.get("exchange"),
                                           "currency": listing.get("currency"), "mentions": 0, "bullish": 0, "bearish": 0,
                                           "financing_concerns": 0, "intensity": 0.0, "latest_at": None, "latest_url": None,
                                           "top_post": None, "thesis_mentions": 0, "reply_mentions": 0, "relay_mentions": 0,
                                           "bullish_decayed": 0.0, "bearish_decayed": 0.0})
            row["mentions"] += 1
            row["reply_mentions"] += int(is_reply)
            row["financing_concerns"] += int(financing)
            row["thesis_mentions"] += int(key in reading["thesis"])
            kind = reading["stance"].get(key)
            if kind == "BULLISH":
                row["bullish"] += 1
                row["bullish_decayed"] += decay
            elif kind in {"BEARISH", "TRIM"}:
                row["bearish"] += 1
                row["bearish_decayed"] += decay * (1.0 if kind == "BEARISH" else TRIM_WEIGHT)
            if kind and (key not in newest or created > newest[key][0]):
                newest[key] = (created, kind)
            row["intensity"] += decay * (1.0 + engagement / 6.0) * (0.5 if len(found) > 4 else 1.0)
            if row["latest_at"] is None or created > parse_time(row["latest_at"]):
                row["latest_at"], row["latest_url"] = iso(created), url
            likes = int(metrics.get("likes") or 0)
            if row["top_post"] is None or likes > row["top_post"]["likes"]:
                row["top_post"] = {"url": url, "created_at": iso(created), "likes": likes, "excerpt": text[:160]}
    for key, row in signals.items():
        row["intensity"] = round(row["intensity"], 3)
        row["bullish_decayed"] = round(row["bullish_decayed"], 4)
        row["bearish_decayed"] = round(row["bearish_decayed"], 4)
        row["relay_mentions"] = relay_pending.get(key, 0)
        last = newest.get(key)
        row["last_stance"] = last[1] if last else None
        row["last_stance_at"] = iso(last[0]) if last else None
        # Posts often mix names ("trimmed X, started Y"); stance is read per clause. A recent exit that is not outweighed
        # by the decayed bullish weight turns the symbol BEARISH; a lone trim never does.
        row["stance"] = ("BEARISH" if row["last_stance"] == "BEARISH" and row["bearish_decayed"] >= BEARISH_SHARE * row["bullish_decayed"]
                         else "BULLISH" if row["bullish_decayed"] > 0 else "MENTIONED")
    ranked = sorted(signals.values(), key=lambda item: (-item["intensity"], item["symbol"]))
    lag_hours, lag_status = mirror_state(now, latest_post)
    return {"schema_version": SCHEMA_VERSION, "generated_at": iso(now), "window_days": WINDOW_DAYS, "half_life_days": HALF_LIFE_DAYS,
            "source": {"url": archive["source_url"], "repository": archive["repository"], "retrieved_at": archive["retrieved_at"],
                       "sha256": archive["sha256"], "latest_post_at": iso(latest_post) if latest_post else None,
                       "mirror_lag_hours": lag_hours, "mirror_status": lag_status,
                       "oembed": {"enabled": False, "checked": 0, "ok": 0, "not_found": 0, "unavailable": 0},
                       "authority": "LEAD_ONLY_NOT_COMPANY_FACT"},
            "relay": {"posts": relay_posts, "mentions": sum(relay_pending.values())},
            "signals": ranked}


# ---- oEmbed verification (network only through an injectable fetch) ----

def fetch_oembed_status(url: str, timeout: float = OEMBED_TIMEOUT) -> int:
    """HTTP status of X's public oEmbed for a post URL (redirects followed; no login, no cookies; the body is not kept)."""
    request = urllib.request.Request(OEMBED_URL.format(url=urllib.parse.quote(url, safe=":/")),
                                     headers={"User-Agent": "Mozilla/5.0 (compatible; public-research)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public HTTPS endpoint
            response.read(1)
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def load_oembed_cache(path: Path) -> dict[str, dict[str, str]]:
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(key): value for key, value in document.items() if isinstance(value, dict)} if isinstance(document, dict) else {}


def save_oembed_cache(path: Path, cache: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(json.dumps(cache, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    temp.replace(path)


class OembedChecker:
    """OK is trusted for 30 days, NOT_FOUND for ever, UNAVAILABLE is never cached (retried next run)."""

    def __init__(self, fetch: Callable[[str, float], int], cache: dict[str, dict[str, str]], now: datetime,
                 budget_seconds: float = OEMBED_BUDGET_SECONDS, clock: Callable[[], float] = time.monotonic,
                 timeout: float = OEMBED_TIMEOUT) -> None:
        self.fetch, self.cache, self.now, self.budget, self.clock, self.timeout = fetch, cache, now, budget_seconds, clock, timeout
        self.started = clock()
        self.run: dict[str, str] = {}
        self.dirty = False

    def cached(self, post_id: str) -> str | None:
        entry = self.cache.get(post_id) or {}
        if entry.get("status") == "NOT_FOUND":
            return "NOT_FOUND"
        checked = parse_time(entry.get("checked_at"))
        if entry.get("status") == "OK" and checked is not None and self.now - checked <= timedelta(days=OEMBED_OK_DAYS):
            return "OK"
        return None

    def status(self, url: Any) -> str:
        post_id = status_id(url)
        if post_id is None:
            return "UNAVAILABLE"
        if post_id in self.run:
            return self.run[post_id]
        result = self.cached(post_id)
        if result is None:
            if self.clock() - self.started >= self.budget:
                return "UNAVAILABLE"  # budget exhausted: not remembered, so a later call in budget could still check it
            try:
                code = int(self.fetch(str(url), self.timeout))
            except Exception:  # timeout, DNS, TLS: nothing is learnt
                code = 0
            result = "OK" if code == 200 else "NOT_FOUND" if code == 404 else "UNAVAILABLE"
            if result != "UNAVAILABLE":
                self.cache[post_id] = {"status": result, "checked_at": iso(self.now)}
                self.dirty = True
        self.run[post_id] = result
        return result

    def counts(self) -> dict[str, int]:
        values = list(self.run.values())
        return {"checked": len(values), "ok": values.count("OK"), "not_found": values.count("NOT_FOUND"),
                "unavailable": values.count("UNAVAILABLE")}


def build_verified(archive: dict[str, Any], mapping: dict[str, Any], us: set[str], now: datetime, *, limit: int,
                   fetch: Callable[[str, float], int], cache: dict[str, dict[str, str]],
                   budget_seconds: float = OEMBED_BUDGET_SECONDS, clock: Callable[[], float] = time.monotonic) -> tuple[dict[str, Any], OembedChecker]:
    """Build, check the strongest `limit` symbols' latest and top posts, drop posts that are gone, rebuild (at most two passes)."""
    checker = OembedChecker(fetch, cache, now, budget_seconds, clock)
    excluded: set[str] = set()
    document: dict[str, Any] | None = None
    for _ in range(OEMBED_PASSES):
        document = build_signals(archive, mapping, us, now, exclude_ids=excluded)
        missing: set[str] = set()
        for row in document["signals"][:limit]:
            for url in (row.get("latest_url"), (row.get("top_post") or {}).get("url")):
                if checker.status(url) == "NOT_FOUND":
                    missing.add(status_id(url) or "")
        missing.discard("")
        if not missing - excluded:
            break
        excluded |= missing
        document = None
    if document is None:
        document = build_signals(archive, mapping, us, now, exclude_ids=excluded)
    for row in document["signals"][:limit]:
        row["verified"] = {"latest": checker.status(row.get("latest_url")), "top": checker.status((row.get("top_post") or {}).get("url"))}
    document["source"]["oembed"] = {"enabled": True, **checker.counts()}
    return document, checker


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    parser.add_argument("--archive", type=Path, default=ARCHIVE_CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify-oembed", type=int, default=None,
                        help=f"check the strongest N symbols' posts through oEmbed (default {OEMBED_DEFAULT_LIMIT} with --refresh, else 0)")
    parser.add_argument("--oembed-cache", type=Path, default=OEMBED_CACHE)
    args = parser.parse_args(list(argv) if argv is not None else None)
    now = utc_now()
    limit = args.verify_oembed if args.verify_oembed is not None else (OEMBED_DEFAULT_LIMIT if args.refresh else 0)
    try:
        if args.if_older_than_hours > 0 and args.output.exists():
            previous = json.loads(args.output.read_bytes().decode("utf-8"))
            age = (now - parse_time(previous["generated_at"])).total_seconds() / 3600
            if age < args.if_older_than_hours:
                print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age, 1)}))
                return 0
        archive = fetch_archive(args.archive) if args.refresh or not args.archive.exists() else \
            json.loads(args.archive.read_bytes().decode("utf-8"))
        mapping = json.loads(TICKER_MAP.read_text(encoding="utf-8"))
        if limit > 0:
            cache = load_oembed_cache(args.oembed_cache)
            document, checker = build_verified(archive, mapping, us_symbols(), now, limit=limit, fetch=fetch_oembed_status, cache=cache)
            if checker.dirty:
                save_oembed_cache(args.oembed_cache, cache)
        else:
            document = build_signals(archive, mapping, us_symbols(), now)
    except Exception as error:  # keep the last good signals file
        print(json.dumps({"status": "FAILED", "error": type(error).__name__}))
        return 1
    temp = args.output.with_name(args.output.name + ".tmp")
    temp.write_bytes(json.dumps(document, ensure_ascii=False).encode("utf-8"))
    temp.replace(args.output)
    print(json.dumps({"status": "OK", "signals": len(document["signals"]), "latest_post_at": document["source"]["latest_post_at"],
                      "mirror_status": document["source"]["mirror_status"], "oembed": document["source"]["oembed"],
                      "top": [(row["symbol"], row["stance"], row["mentions"], row["intensity"]) for row in document["signals"][:25]]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
