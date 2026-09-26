#!/usr/bin/env python3
"""Serenity (@aleabitoreddit) lead signals from the public post archive (Top20 v3 lead layer).

Source: the public GitHub archive yan-labs/serenity-aleabitoreddit (data/aleabitoreddit_tweets.json), which mirrors
the author's X posts with ids, timestamps and engagement; each signal cites its post URL. Posts are LEADS, never
company facts: a mention can admit a company to the candidate universe and weight its lead score, but figures in
the Top20 always come from company filings and market data.

Per listing (cashtags validated against the official US directory, other tags and names through
config/serenity-ticker-map-v1.json): original-post mentions in the last 120 days, recency- and engagement-weighted
intensity (30-day half-life), bullish and bearish stance counts, dilution/financing concerns, the latest mention and
the most-engaged recent post. Retweets are excluded.

Usage: serenity_signals.py [--refresh] [--if-older-than-hours H] [--archive PATH] [--output PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_URL = "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/aleabitoreddit_tweets.json"
ARCHIVE_REPO = "https://github.com/yan-labs/serenity-aleabitoreddit"
ARCHIVE_CACHE = ROOT / "data" / "cache" / "serenity_archive.json"
OUTPUT = ROOT / "data" / "cache" / "serenity_signals_latest.json"
TICKER_MAP = ROOT / "config" / "serenity-ticker-map-v1.json"
IDENTITY = ROOT / "data" / "cache" / "identity_shards_latest.json"
WINDOW_DAYS = 120
HALF_LIFE_DAYS = 30.0
CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9.]{0,7})\b")
BULLISH = re.compile(r"\b(?:own(?:ing)?|added|adding|add(?:ed)? more|bought|buying|holding|my position|positions? in|long|"
                     r"favou?rite|conviction|top holding|largest position|race ?horse|compounder|accumulat\w*|cost.averag\w*|"
                     r"bottleneck|sold out|shortage|allocation)\b", re.I)
BEARISH = re.compile(r"\b(?:sold (?:my|all|out of)|exited|exit(?:ing)? my|shorting|shorted|(?:am|i'm|went) short|bearish|"
                     r"avoid|not a fan|overvalued)\b", re.I)
FINANCING = re.compile(r"\b(?:ATM|dilut\w*|share offering|convertible|stock comp\w*)\b", re.I)
IGNORED_TAGS = {"USD", "BTC", "ETH", "SPX", "SPY", "QQQ", "NDX", "VIX"}


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


def build_signals(archive: dict[str, Any], mapping: dict[str, Any], us: set[str], now: datetime) -> dict[str, Any]:
    start = now - timedelta(days=WINDOW_DAYS)
    signals: dict[str, dict[str, Any]] = {}
    latest_post: datetime | None = None
    for post in archive["posts"]:
        if post.get("isRetweet"):
            continue
        created = parse_time(post.get("createdAtISO"))
        if created is None:
            continue
        latest_post = max(latest_post or created, created)
        if created < start or created > now + timedelta(minutes=5):
            continue
        text = str(post.get("text") or "")
        found = listings_in(text, mapping, us)
        if not found:
            continue
        metrics = post.get("metrics") or {}
        engagement = math.log1p(float(metrics.get("likes") or 0) + 2 * float(metrics.get("retweets") or 0))
        decay = 0.5 ** ((now - created).total_seconds() / 86400 / HALF_LIFE_DAYS)
        bullish = bool(BULLISH.search(text))
        bearish = bool(BEARISH.search(text))
        financing = bool(FINANCING.search(text))
        url = str(post.get("sourceUrl") or f"https://x.com/aleabitoreddit/status/{post.get('id')}")
        for key, listing in found.items():
            row = signals.setdefault(key, {"symbol": listing["symbol"], "name": listing.get("name"), "exchange": listing.get("exchange"),
                                           "currency": listing.get("currency"), "mentions": 0, "bullish": 0, "bearish": 0,
                                           "financing_concerns": 0, "intensity": 0.0, "latest_at": None, "latest_url": None,
                                           "top_post": None})
            row["mentions"] += 1
            row["bullish"] += int(bullish and not bearish)
            row["bearish"] += int(bearish)
            row["financing_concerns"] += int(financing)
            row["intensity"] += decay * (1.0 + engagement / 6.0) * (0.5 if len(found) > 4 else 1.0)
            if row["latest_at"] is None or created > parse_time(row["latest_at"]):
                row["latest_at"], row["latest_url"] = iso(created), url
            likes = int(metrics.get("likes") or 0)
            if row["top_post"] is None or likes > row["top_post"]["likes"]:
                row["top_post"] = {"url": url, "created_at": iso(created), "likes": likes, "excerpt": text[:160]}
    for row in signals.values():
        row["intensity"] = round(row["intensity"], 3)
        # Posts often mix names ("trimmed X, started Y"): bearish only when bearish posts clearly outnumber bullish ones.
        row["stance"] = ("BEARISH" if row["bearish"] >= 2 and row["bearish"] > 2 * row["bullish"]
                         else "BULLISH" if row["bullish"] > 0 else "MENTIONED")
    ranked = sorted(signals.values(), key=lambda item: (-item["intensity"], item["symbol"]))
    return {"schema_version": 1, "generated_at": iso(now), "window_days": WINDOW_DAYS, "half_life_days": HALF_LIFE_DAYS,
            "source": {"url": archive["source_url"], "repository": archive["repository"], "retrieved_at": archive["retrieved_at"],
                       "sha256": archive["sha256"], "latest_post_at": iso(latest_post) if latest_post else None,
                       "authority": "LEAD_ONLY_NOT_COMPANY_FACT"},
            "signals": ranked}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    parser.add_argument("--archive", type=Path, default=ARCHIVE_CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    now = utc_now()
    try:
        if args.if_older_than_hours > 0 and args.output.exists():
            previous = json.loads(args.output.read_bytes().decode("utf-8"))
            age = (now - parse_time(previous["generated_at"])).total_seconds() / 3600
            if age < args.if_older_than_hours:
                print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age, 1)}))
                return 0
        archive = fetch_archive(args.archive) if args.refresh or not args.archive.exists() else \
            json.loads(args.archive.read_bytes().decode("utf-8"))
        document = build_signals(archive, json.loads(TICKER_MAP.read_text(encoding="utf-8")), us_symbols(), now)
    except Exception as error:  # keep the last good signals file
        print(json.dumps({"status": "FAILED", "error": type(error).__name__}))
        return 1
    temp = args.output.with_name(args.output.name + ".tmp")
    temp.write_bytes(json.dumps(document, ensure_ascii=False).encode("utf-8"))
    temp.replace(args.output)
    print(json.dumps({"status": "OK", "signals": len(document["signals"]), "latest_post_at": document["source"]["latest_post_at"],
                      "top": [(row["symbol"], row["stance"], row["mentions"], row["intensity"]) for row in document["signals"][:25]]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
