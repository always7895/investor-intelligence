"""Official investor-relations press-release channels for the revenue-guidance latest-release check (ORDERS-V3-01, W1).

Astra's W1 ruling: every admitted company-guidance issuer needs its official IR earnings/news channel checked in addition
to the SEC and wire channels; an issuer whose IR channel cannot be read keeps its projection unavailable. Three reviewed
channel kinds (the registry record names one per issuer, `release_channels.ir`):
- Q4_PRESS_RELEASES: the IR site's Q4 press-release feed (`/feed/PressRelease.svc/GetPressReleaseList`), read per calendar
  year from the guidance year to the check year with pageSize=-1 (the whole year), so the list is complete by request;
- RSS: the IR site's press-release RSS (the newest items only): complete only when its oldest item predates the start;
- NEWSROOM_HTML: a server-rendered corporate newsroom list (`<a href="/newsroom/...">title ... Month D, YYYY</a>`),
  complete only when its oldest dated item predates the start.
Items carry the publication DAY (the feeds give local times without a zone; days are compared, never instants) so a
same-day item stays visible to the caller. Nothing here classifies relevance or turns text into numbers.
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
# Several IR sites (the Drupal-hosted ones: Sandisk, Broadcom, MACOM, AOI, Astera Labs) answer the browser string with 403 and the
# plain observation string with the feed, so a 403 is retried once with it (the wire channel and the controlled checker use it too).
FALLBACK_USER_AGENT = "Mozilla/5.0 (InvestorIntelligence public observation)"
MAX_BYTES = 8_000_000
TIMEOUT_SECONDS = 30
KINDS = ("Q4_PRESS_RELEASES", "RSS", "NEWSROOM_HTML", "TSMC_NEWS_HTML")
Q4_CATEGORY = "1cb807d2-208f-4bc3-9133-6a9ad45ac3b0"  # the Q4 platform's press-release category
MONTHS = {name: index for index, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}


class IrFeedError(RuntimeError):
    """A channel that could not be read completely (never an empty success)."""


def _read(url: str, user_agent: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read(MAX_BYTES + 1)


def fetch_bytes(url: str) -> bytes:
    try:
        body = _read(url, USER_AGENT)
    except urllib.error.HTTPError as error:
        if error.code != 403:
            raise
        body = _read(url, FALLBACK_USER_AGENT)
    if len(body) > MAX_BYTES:
        raise IrFeedError("IR_RESPONSE_TOO_LARGE")
    return body


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def q4_items(base: str, since: date, today: date, fetch: Callable[[str], bytes]) -> tuple[list[dict[str, str]], bool]:
    """All press releases of each calendar year from `since` to `today` (the feed returns a whole year at pageSize=-1)."""
    host = urllib.parse.urlsplit(base)
    items = []
    for year in range(since.year, today.year + 1):
        url = (f"{base}?LanguageId=1&bodyType=0&pressReleaseDateFilter=3&categoryId={Q4_CATEGORY}&pageSize=-1&pageNumber=0"
               f"&tagList=&includeTags=true&year={year}&excludeSelection=1")
        rows = json.loads(fetch(url).decode("utf-8")).get("GetPressReleaseListResult")
        if not isinstance(rows, list):
            raise IrFeedError("Q4_SHAPE")
        for row in rows:
            stamp, headline = row.get("PressReleaseDate"), row.get("Headline")
            if not isinstance(stamp, str) or not isinstance(headline, str):
                raise IrFeedError("Q4_ITEM_SHAPE")
            day = datetime.strptime(stamp.strip()[:10], "%m/%d/%Y").date()
            link = str(row.get("LinkToDetailPage") or "")
            items.append({"date": day.isoformat(), "title": _clean(headline)[:200],
                          "id": f"{host.scheme}://{host.netloc}{link}" if link.startswith("/") else link[:400]})
    return items, True


def rss_items(url: str, since: date, fetch: Callable[[str], bytes]) -> tuple[list[dict[str, str]], bool]:
    raw = fetch(url)
    try:
        ElementTree.fromstring(raw)  # a truncated or malformed feed is a failed read, never a shorter list
    except ElementTree.ParseError as error:
        raise IrFeedError("RSS_MALFORMED") from error
    text = raw.decode("utf-8", "replace")
    items = []
    for block in re.findall(r"<item\b.*?</item>", text, re.S):
        title = re.search(r"<title>(.*?)</title>", block, re.S)
        link = re.search(r"<link>(.*?)</link>", block, re.S)
        stamp = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
        if not title or not stamp:
            raise IrFeedError("RSS_ITEM_SHAPE")
        day = parsedate_to_datetime(stamp.group(1).strip()).date()  # the feed's own local date (offset kept by the parser)
        items.append({"date": day.isoformat(), "title": _clean(re.sub(r"<!\[CDATA\[|\]\]>", "", title.group(1)))[:200],
                      "id": _clean(link.group(1))[:400] if link else ""})
    if not items:
        raise IrFeedError("RSS_EMPTY")
    return items, min(item["date"] for item in items) < since.isoformat()


def newsroom_items(url: str, since: date, fetch: Callable[[str], bytes]) -> tuple[list[dict[str, str]], bool]:
    text = fetch(url).decode("utf-8", "replace")
    base = urllib.parse.urlsplit(url)
    embedded = re.search(r'<script\b[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.S)
    if re.search(r'<script\b[^>]*id="__NEXT_DATA__"', text) and not embedded:
        raise IrFeedError("NEWSROOM_ARCHIVE_TRUNCATED")
    if embedded and base.netloc in ("group.nebius.com", "nebius.com") and base.path == "/newsroom":
        # This exact observed query requests the entire archive, not a visible-card page.
        # Resolve only public press-release fields; unrelated embedded state is never inspected or retained.
        try:
            data = json.loads(embedded.group(1))
            state = data["props"]["pageProps"]["__APOLLO_STATE__"]
            refs = state["ROOT_QUERY"]['press_releases({"limit":-1,"sort":["-date","-publication_datetime"]})']
            if not isinstance(refs, list) or not 1 <= len(refs) <= 2000:
                raise ValueError()
            items, seen = [], set()
            for ref in refs:
                if not isinstance(ref, dict) or set(ref) != {"__ref"} or not isinstance(ref["__ref"], str):
                    raise ValueError()
                key = ref["__ref"]
                if not key.startswith("press_releases:") or key in seen:
                    raise ValueError()
                seen.add(key)
                row = state[key]
                if row.get("__typename") != "press_releases":
                    raise ValueError()
                day, title, slug = row["date"], row["title"], row["name"]
                if (not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
                        or not isinstance(title, str) or not 1 <= len(title) <= 1000
                        or not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,300}", slug)):
                    raise ValueError()
                items.append({"date": day, "title": title[:200], "id": f"{base.scheme}://{base.netloc}/newsroom/{slug}"})
            if len({item["id"] for item in items}) != len(items):
                raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise IrFeedError("NEWSROOM_ARCHIVE_SHAPE") from error
        return items, min(item["date"] for item in items) < since.isoformat()
    items = []
    for href, inner in re.findall(r'<a[^>]+href="(/newsroom/[^"#?]+)"[^>]*>(.*?)</a>', text, re.S):
        # Since October 2026 each card carries a category tag ("Press release") in front of its title: it is not part of the title.
        inner = re.sub(r'<div class="pc-basic-card__labels">(?:<div class="pc-tag[^"]*"[^>]*>.*?</div>)*</div>', " ", inner, flags=re.S)
        label = _clean(inner)
        found = re.search(r"(" + "|".join(MONTHS) + r") (\d{1,2}), (20\d\d)$", label)
        if not found:
            continue  # navigation links carry no date
        day = date(int(found.group(3)), MONTHS[found.group(1)], int(found.group(2)))
        items.append({"date": day.isoformat(), "title": label[:found.start()].strip()[:200],
                      "id": f"{base.scheme}://{base.netloc}{href}"[:400]})
    if not items:
        raise IrFeedError("NEWSROOM_EMPTY")
    return items, min(item["date"] for item in items) < since.isoformat()


def tsmc_news_items(url: str, since: date, fetch: Callable[[str], bytes]) -> tuple[list[dict[str, str]], bool]:
    """TSMC's dated latest-news cards; an incomplete list never renews coverage."""
    if url != "https://pr.tsmc.com/english/latest-news":
        raise IrFeedError("TSMC_CHANNEL_URL")
    text = fetch(url).decode("utf-8", "strict")
    items = []
    blocks = re.findall(r"<article\b[^>]*>.*?</article>", text, re.S)
    if len(re.findall(r"<article\b", text)) != len(blocks):
        raise IrFeedError("TSMC_HTML_TRUNCATED")
    for block in blocks:
        if 'node--type-news' not in block:
            continue
        link = re.search(r'href="(/english/news/\d+)"', block)
        stamp = re.search(r'<time\b[^>]*datetime="(\d{4}-\d{2}-\d{2})T[^"<>]+"', block)
        title = re.search(r'<h2\b[^>]*>(.*?)</h2>', block, re.S)
        if not link or not stamp or not title:
            raise IrFeedError("TSMC_ITEM_SHAPE")
        day = date.fromisoformat(stamp.group(1))
        label = _clean(title.group(1))
        if not label or len(label) > 200:
            raise IrFeedError("TSMC_ITEM_TITLE")
        items.append({"date": day.isoformat(), "title": label, "id": "https://pr.tsmc.com" + link.group(1)})
    if not items:
        raise IrFeedError("TSMC_NEWS_EMPTY")
    return items, min(item["date"] for item in items) < since.isoformat()


def safe_error_code(error: Exception) -> str:
    """Public bounded diagnostic only; never include exception URLs, headers or bodies."""
    if isinstance(error, urllib.error.HTTPError):
        return "HTTP_" + str(error.code) if type(error.code) is int else "HTTP_ERROR"
    return (str(error) if isinstance(error, IrFeedError) else type(error).__name__)[:60]


def read_channel(channel: Mapping[str, Any], since: date, today: date, fetch: Callable[[str], bytes] = fetch_bytes) -> dict[str, Any]:
    """{"kind", "url", "status": OK|FAILED, "complete", "items": [...] (items dated on or after `since`)}; any failure is
    FAILED and incomplete, with no items."""
    kind, url = channel.get("kind"), channel.get("url")
    result = {"kind": kind, "url": url, "status": "FAILED", "complete": False, "items": []}
    if kind not in KINDS or not isinstance(url, str) or not url.startswith("https://"):
        return {**result, "error": "IR_CHANNEL_UNSUPPORTED"}
    try:
        if kind == "Q4_PRESS_RELEASES":
            items, complete = q4_items(url, since, today, fetch)
        elif kind == "RSS":
            items, complete = rss_items(url, since, fetch)
        elif kind == "NEWSROOM_HTML":
            items, complete = newsroom_items(url, since, fetch)
        else:
            items, complete = tsmc_news_items(url, since, fetch)
    except Exception as error:  # noqa: BLE001 - a channel that cannot be read is unverified, never "no release"
        return {**result, "error": safe_error_code(error)}
    later = sorted((item for item in items if item["date"] >= since.isoformat()), key=lambda item: (item["date"], item["id"]))
    return {**result, "status": "OK", "complete": complete, "items": later}
