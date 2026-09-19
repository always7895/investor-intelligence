"""Bounded official announcement RSS parsers; headlines are leads, not issuer facts."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from .base import AdapterError, ParsedBatch, make_batch, utc_iso

FEEDS = {
    "federal_reserve_news": ("https://www.federalreserve.gov/feeds/press_all.xml", "federalreserve.gov"),
    "ecb_news": ("https://www.ecb.europa.eu/rss/press.html", "ecb.europa.eu"),
    "sec_news": ("https://www.sec.gov/news/pressreleases.rss", "sec.gov"),
}
MAX_BYTES = 2_000_000


class OfficialRssAdapter:
    parser_version = "official-rss-v1"

    def __init__(self, source_id: str):
        self.source_id = source_id
        self.url, self.domain = FEEDS[source_id]

    def parse(self, content: bytes, *, content_type: str, retrieved_at: str,
              context: Mapping[str, Any]) -> ParsedBatch:
        if len(content) > MAX_BYTES:
            raise AdapterError("RSS_TOO_LARGE")
        try:
            document = content.decode("utf-8-sig")
            if "<!DOCTYPE" in document.upper() or "<!ENTITY" in document.upper():
                raise AdapterError("RSS_ENTITY_DECLARATION_FORBIDDEN")
            root = ET.fromstring(document)
        except (UnicodeDecodeError, ET.ParseError):
            raise AdapterError("INVALID_RSS") from None
        if root.tag != "rss" or root.find("channel") is None:
            raise AdapterError("EXPECTED_RSS_CHANNEL")
        retrieved = datetime.fromisoformat(utc_iso(retrieved_at))
        rows, warnings, seen = [], [], set()
        items = root.findall("./channel/item")
        if len(items) > 1000:
            raise AdapterError("RSS_TOO_MANY_ITEMS")
        for index, item in enumerate(items):
            try:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                stamp = (item.findtext("pubDate") or "").strip()
                parsed = urlsplit(link)
                host = (parsed.hostname or "").lower()
                if not title or len(title) > 1000 or any(ord(c) < 32 for c in title):
                    raise ValueError("INVALID_TITLE")
                if parsed.scheme != "https" or host not in {self.domain, "www." + self.domain} or parsed.username or parsed.password or parsed.port not in (None, 443):
                    raise ValueError("UNADMITTED_LINK")
                published = parsedate_to_datetime(stamp)
                if published.tzinfo is None:
                    raise ValueError("DATE_OFFSET_REQUIRED")
                published = published.astimezone(timezone.utc)
                if published > retrieved:
                    raise ValueError("FUTURE_PUBLICATION")
                # Fragments do not establish a second independent announcement.
                link = parsed._replace(fragment="").geturl()
                if link in seen:
                    warnings.append(f"DUPLICATE_ITEM:{index}")
                    continue
                seen.add(link)
                rows.append({"title": title, "url": link, "published_at": published.isoformat(),
                             "source_id": self.source_id, "origin": self.domain,
                             "source_url": self.url, "evidence_role": "announcement_lead",
                             "age_seconds": (retrieved - published).total_seconds(),
                             "freshness": "STALE" if (retrieved - published).total_seconds() > 7 * 86400 else "RECENT_ANNOUNCEMENT",
                             "issuer_claim_verified": False, "publication_eligible": False})
            except (ValueError, TypeError, OverflowError, AttributeError):
                warnings.append(f"INVALID_ITEM:{index}")
        return make_batch(source_id=self.source_id, parser_version=self.parser_version,
                          content=content, retrieved_at=retrieved_at, records=rows, warnings=warnings)


RSS_ADAPTERS = {source: OfficialRssAdapter(source) for source in FEEDS}
