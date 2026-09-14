"""Authoritative ECB daily EUR/USD reference exchange rate RSS parser."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit
import xml.etree.ElementTree as ET

try:
    from .base import AdapterError, ParsedBatch, make_batch, utc_iso
except (ImportError, ValueError):
    from adapters.base import AdapterError, ParsedBatch, make_batch, utc_iso

REQUEST_URL = "https://www.ecb.europa.eu/rss/fxref-usd.html"
MAX_BYTES = 8_000_000
ALLOWED_MIMES = {"application/rss+xml", "application/xml", "text/xml"}
NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rss": "http://purl.org/rss/1.0/",
    "cb": "http://www.cbwiki.net/wiki/index.php/Specification_1.1",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}
EXPECTED_TITLE = "ECB | US dollar (USD) - Euro foreign exchange reference rates"
EXPECTED_PUBLISHER = "European Central Bank"
EXPECTED_PATH = "/stats/exchange/eurofxref/html/eurofxref-graph-usd.en.html"
RAW_SOURCE_LICENSE = "http://www.ecb.europa.eu/home/html/disclaimer.en.html"
EXPECTED_LICENSE = RAW_SOURCE_LICENSE
CANONICAL_TERMS_URL = "https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html"


class ECBFxReferenceAdapter:
    source_id = "eu_ecb_fx_reference"
    parser_version = "ecb-fxref-usd-rss1-v1"
    content_type = "application/rss+xml"
    REQUEST_URL = REQUEST_URL
    raw_source_license = RAW_SOURCE_LICENSE
    canonical_terms_url = CANONICAL_TERMS_URL

    def _validate_structure(self, root: ET.Element) -> tuple[ET.Element, list[ET.Element]]:
        if root.tag != f"{{{NS['rdf']}}}RDF":
            raise AdapterError("INVALID_ROOT")
        if root.text and root.text.strip():
            raise AdapterError("STRAY_CONTAINER_TEXT")

        channel: ET.Element | None = None
        raw_items: list[ET.Element] = []
        for child in root:
            if child.tail and child.tail.strip():
                raise AdapterError("STRAY_TAIL_TEXT")
            if child.tag == f"{{{NS['rss']}}}channel":
                if channel is not None:
                    raise AdapterError("DUPLICATE_CHANNEL")
                channel = child
            elif child.tag == f"{{{NS['rss']}}}item":
                raw_items.append(child)
            else:
                raise AdapterError("UNKNOWN_ROOT_CHILD")

        if channel is None:
            raise AdapterError("MISSING_CHANNEL")
        if not (1 <= len(raw_items) <= 10):
            raise AdapterError("INVALID_ITEM_COUNT")

        # Closed channel structure check
        if channel.text and channel.text.strip():
            raise AdapterError("STRAY_CONTAINER_TEXT")
        expected_channel_tags = {
            f"{{{NS['rss']}}}title",
            f"{{{NS['rss']}}}link",
            f"{{{NS['rss']}}}description",
            f"{{{NS['rss']}}}items",
            f"{{{NS['dc']}}}publisher",
            f"{{{NS['dcterms']}}}license",
        }
        channel_tags: list[str] = []
        items_elem: ET.Element | None = None
        for ch in channel:
            if ch.tail and ch.tail.strip():
                raise AdapterError("STRAY_TAIL_TEXT")
            channel_tags.append(ch.tag)
            if ch.tag == f"{{{NS['rss']}}}items":
                items_elem = ch
            else:
                if len(ch) > 0:
                    raise AdapterError("NESTED_ELEMENT_IN_SCALAR")
        if set(channel_tags) != expected_channel_tags or len(channel_tags) != len(expected_channel_tags):
            raise AdapterError("INVALID_CHANNEL_STRUCTURE")
        assert items_elem is not None

        # Closed items / rdf:Seq check
        if items_elem.text and items_elem.text.strip():
            raise AdapterError("STRAY_CONTAINER_TEXT")
        if len(items_elem) != 1:
            raise AdapterError("INVALID_ITEMS_STRUCTURE")
        seq = items_elem[0]
        if seq.tail and seq.tail.strip():
            raise AdapterError("STRAY_TAIL_TEXT")
        if seq.tag != f"{{{NS['rdf']}}}Seq":
            raise AdapterError("INVALID_SEQUENCE_STRUCTURE")
        if seq.text and seq.text.strip():
            raise AdapterError("STRAY_CONTAINER_TEXT")
        if not (1 <= len(seq) <= 10):
            raise AdapterError("INVALID_SEQUENCE_COUNT")
        for li in seq:
            if li.tail and li.tail.strip():
                raise AdapterError("STRAY_TAIL_TEXT")
            if li.tag != f"{{{NS['rdf']}}}li":
                raise AdapterError("INVALID_SEQUENCE_ELEMENT")
            if len(li) > 0:
                raise AdapterError("NESTED_ELEMENT_IN_LI")
            if li.text and li.text.strip():
                raise AdapterError("STRAY_TEXT_IN_LI")

        # Closed item / statistics / exchangeRate checks
        expected_item_tags = {
            f"{{{NS['rss']}}}title",
            f"{{{NS['rss']}}}link",
            f"{{{NS['rss']}}}description",
            f"{{{NS['dc']}}}date",
            f"{{{NS['dc']}}}language",
            f"{{{NS['cb']}}}statistics",
        }
        expected_stats_tags = {
            f"{{{NS['cb']}}}country",
            f"{{{NS['cb']}}}institutionAbbrev",
            f"{{{NS['cb']}}}exchangeRate",
        }
        expected_rate_tags = {
            f"{{{NS['cb']}}}value",
            f"{{{NS['cb']}}}baseCurrency",
            f"{{{NS['cb']}}}targetCurrency",
            f"{{{NS['cb']}}}rateType",
        }

        for it in raw_items:
            if it.text and it.text.strip():
                raise AdapterError("STRAY_CONTAINER_TEXT")
            it_tags: list[str] = []
            stats: ET.Element | None = None
            for ch in it:
                if ch.tail and ch.tail.strip():
                    raise AdapterError("STRAY_TAIL_TEXT")
                it_tags.append(ch.tag)
                if ch.tag == f"{{{NS['cb']}}}statistics":
                    stats = ch
                else:
                    if len(ch) > 0:
                        raise AdapterError("NESTED_ELEMENT_IN_SCALAR")
            if set(it_tags) != expected_item_tags or len(it_tags) != len(expected_item_tags):
                raise AdapterError("INVALID_ITEM_STRUCTURE")
            assert stats is not None

            if stats.text and stats.text.strip():
                raise AdapterError("STRAY_CONTAINER_TEXT")
            stats_tags: list[str] = []
            ex_rate: ET.Element | None = None
            for ch in stats:
                if ch.tail and ch.tail.strip():
                    raise AdapterError("STRAY_TAIL_TEXT")
                stats_tags.append(ch.tag)
                if ch.tag == f"{{{NS['cb']}}}exchangeRate":
                    ex_rate = ch
                else:
                    if len(ch) > 0:
                        raise AdapterError("NESTED_ELEMENT_IN_SCALAR")
            if set(stats_tags) != expected_stats_tags or len(stats_tags) != len(expected_stats_tags):
                raise AdapterError("INVALID_STATISTICS_STRUCTURE")
            assert ex_rate is not None

            if ex_rate.text and ex_rate.text.strip():
                raise AdapterError("STRAY_CONTAINER_TEXT")
            rate_tags: list[str] = []
            for ch in ex_rate:
                if ch.tail and ch.tail.strip():
                    raise AdapterError("STRAY_TAIL_TEXT")
                rate_tags.append(ch.tag)
                if len(ch) > 0:
                    raise AdapterError("NESTED_ELEMENT_IN_SCALAR")
            if set(rate_tags) != expected_rate_tags or len(rate_tags) != len(expected_rate_tags):
                raise AdapterError("INVALID_EXCHANGE_RATE_STRUCTURE")

        return channel, raw_items

    def parse(
        self,
        content: bytes,
        *,
        content_type: str,
        retrieved_at: str,
        context: Mapping[str, Any] | None = None,
    ) -> ParsedBatch:
        req_url = (context or {}).get("request_url") if isinstance(context, Mapping) else None
        if req_url != REQUEST_URL:
            raise AdapterError("INVALID_REQUEST_URL")
        mime = str(content_type or "").split(";")[0].strip().casefold()
        if mime not in ALLOWED_MIMES:
            raise AdapterError("INVALID_CONTENT_TYPE")
        if len(content) > MAX_BYTES:
            raise AdapterError("PAYLOAD_TOO_LARGE")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AdapterError("INVALID_UTF8") from exc
        upper = text.upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise AdapterError("DTD_FORBIDDEN")
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise AdapterError("INVALID_XML") from exc

        channel, raw_items = self._validate_structure(root)

        if (channel.findtext(f"{{{NS['rss']}}}title") or "").strip() != EXPECTED_TITLE:
            raise AdapterError("INVALID_CHANNEL_TITLE")
        if (channel.findtext(f"{{{NS['dc']}}}publisher") or "").strip() != EXPECTED_PUBLISHER:
            raise AdapterError("INVALID_PUBLISHER")
        if (channel.findtext(f"{{{NS['dcterms']}}}license") or "").strip() != EXPECTED_LICENSE:
            raise AdapterError("INVALID_LICENSE")

        items_elem = channel.find(f"{{{NS['rss']}}}items")
        assert items_elem is not None
        seq = items_elem.find(f"{{{NS['rdf']}}}Seq")
        assert seq is not None
        seq_uris = [li.get(f"{{{NS['rdf']}}}resource") for li in seq.findall(f"{{{NS['rdf']}}}li")]
        if any(not u for u in seq_uris) or len(seq_uris) != len(set(seq_uris)):
            raise AdapterError("INVALID_SEQUENCE")

        if len(raw_items) != len(seq_uris):
            raise AdapterError("INVALID_ITEM_COUNT")
        item_uris = [it.get(f"{{{NS['rdf']}}}about") for it in raw_items]
        if any(not u for u in item_uris) or len(item_uris) != len(set(item_uris)):
            raise AdapterError("DUPLICATE_ITEM_URI")
        if set(seq_uris) != set(item_uris):
            raise AdapterError("SEQUENCE_MISMATCH")

        retrieved_iso = utc_iso(retrieved_at)
        retrieved_dt = datetime.fromisoformat(retrieved_iso)
        validated, seen_dates, seen_stamps = [], set(), set()

        for it in raw_items:
            about = it.get(f"{{{NS['rdf']}}}about") or ""
            if (it.findtext(f"{{{NS['rss']}}}link") or "").strip() != about:
                raise AdapterError("LINK_ABOUT_MISMATCH")
            parsed_u = urlsplit(about)
            if parsed_u.scheme not in ("http", "https") or parsed_u.path != EXPECTED_PATH:
                raise AdapterError("INVALID_URI")
            if parsed_u.netloc.lower() != "www.ecb.europa.eu" or parsed_u.hostname != "www.ecb.europa.eu":
                raise AdapterError("INVALID_URI_HOST")
            if parsed_u.username or parsed_u.password or parsed_u.port or parsed_u.fragment:
                raise AdapterError("INVALID_URI_COMPONENTS")

            q_params = parse_qsl(parsed_u.query, keep_blank_values=True)
            if len(q_params) != 2 or set(k for k, _ in q_params) != {"date", "rate"}:
                raise AdapterError("INVALID_QUERY")
            q_dict = dict(q_params)
            date_str, query_rate = q_dict["date"], q_dict["rate"]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
                raise AdapterError("INVALID_DATE_FORMAT")
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError as exc:
                raise AdapterError("INVALID_DATE") from exc

            if (it.findtext(f"{{{NS['dc']}}}language") or "").strip() != "en":
                raise AdapterError("INVALID_LANGUAGE")
            stats = it.find(f"{{{NS['cb']}}}statistics")
            assert stats is not None
            if (stats.findtext(f"{{{NS['cb']}}}country") or "").strip() != "U2":
                raise AdapterError("INVALID_COUNTRY")
            if (stats.findtext(f"{{{NS['cb']}}}institutionAbbrev") or "").strip() != "ECB":
                raise AdapterError("INVALID_INSTITUTION")

            ex_rate = stats.find(f"{{{NS['cb']}}}exchangeRate")
            assert ex_rate is not None
            base = ex_rate.find(f"{{{NS['cb']}}}baseCurrency")
            if base is None or (base.text or "").strip() != "EUR" or base.get("unit_mult") != "0":
                raise AdapterError("INVALID_BASE_CURRENCY")
            target = ex_rate.find(f"{{{NS['cb']}}}targetCurrency")
            if target is None or (target.text or "").strip() != "USD":
                raise AdapterError("INVALID_TARGET_CURRENCY")
            rate_type = ex_rate.find(f"{{{NS['cb']}}}rateType")
            if rate_type is None or (rate_type.text or "").strip() != "Reference rate":
                raise AdapterError("INVALID_RATE_TYPE")

            val_elem = ex_rate.find(f"{{{NS['cb']}}}value")
            if val_elem is None or val_elem.get("frequency") != "daily":
                raise AdapterError("INVALID_FREQUENCY")
            decimals_attr = val_elem.get("decimals")
            try:
                decimals = int(decimals_attr) if decimals_attr is not None else -1
            except ValueError:
                raise AdapterError("INVALID_DECIMALS")
            if not (0 <= decimals <= 8):
                raise AdapterError("INVALID_DECIMALS")

            rate_str = (val_elem.text or "").strip()
            expected_pattern = rf"^\d+\.\d{{{decimals}}}$" if decimals > 0 else r"^\d+$"
            if not re.fullmatch(expected_pattern, rate_str):
                raise AdapterError("INVALID_NUMERIC_RATE")

            lexical_dec = len(rate_str.split(".")[1]) if "." in rate_str else 0
            if lexical_dec != decimals or query_rate != rate_str:
                raise AdapterError("RATE_PRECISION_MISMATCH")
            try:
                rate_dec = Decimal(rate_str)
            except InvalidOperation as exc:
                raise AdapterError("INVALID_NUMERIC_RATE") from exc
            if not rate_dec.is_finite() or rate_dec <= Decimal("0") or rate_dec > Decimal("1000"):
                raise AdapterError("RATE_OUT_OF_BOUNDS")
            rate_float = float(rate_str)
            if Decimal(str(rate_float)) != rate_dec:
                raise AdapterError("FLOAT_PRECISION_LOSS")

            title = (it.findtext(f"{{{NS['rss']}}}title") or "").strip()
            if title != f"{rate_str} USD = 1 EUR {date_str} ECB Reference rate":
                raise AdapterError("INVALID_TITLE")

            pub_str = (it.findtext(f"{{{NS['dc']}}}date") or "").strip()
            if not pub_str:
                raise AdapterError("MISSING_DC_DATE")
            try:
                pub_dt = datetime.fromisoformat(pub_str)
            except ValueError as exc:
                raise AdapterError("INVALID_DC_DATE") from exc
            if pub_dt.tzinfo is None:
                raise AdapterError("NAIVE_DC_DATE")
            pub_utc = pub_dt.astimezone(timezone.utc)
            if pub_utc > retrieved_dt:
                raise AdapterError("FUTURE_DC_DATE")
            if pub_dt.strftime("%Y-%m-%d") != date_str:
                raise AdapterError("DC_DATE_MISMATCH")

            if date_str in seen_dates or pub_utc in seen_stamps:
                raise AdapterError("DUPLICATE_ITEM_DATE_OR_TIMESTAMP")
            seen_dates.add(date_str)
            seen_stamps.add(pub_utc)
            validated.append({
                "pub_utc": pub_utc, "date": date_str, "rate_float": rate_float,
                "title": title, "raw_pub": pub_str, "about": about,
            })

        latest = max(validated, key=lambda x: x["pub_utc"])
        ref_date = latest["date"]
        payload = {
            "subject": "EUR/USD", "metric": "ecb_reference_exchange_rate", "period": ref_date,
            "unit": "USD_per_EUR", "currency": "USD", "basis": "ECB_INFORMATIONAL_REFERENCE_RATE",
            "scope": "EUR_BASE_USD_TARGET", "value": latest["rate_float"],
            "claim_ids": [f"ecb.fxref.EUR.USD.{ref_date}"],
            "origin_group": f"ecb_euro_reference_rates:{ref_date}", "passage": latest["title"],
            "as_of": f"{ref_date}T00:00:00Z", "as_of_precision": "DAY",
            "as_of_semantics": "REFERENCE_DATE_BOUNDARY_NOT_EXECUTION_TIME",
            "source_published_timestamp": latest["raw_pub"], "original_item_uri": latest["about"],
            "publisher": EXPECTED_PUBLISHER, "attribution": EXPECTED_PUBLISHER,
            "information_only": True, "no_endorsement": True, "source_url": REQUEST_URL,
            "terms_url": CANONICAL_TERMS_URL, "official_terms_url": CANONICAL_TERMS_URL,
            "modification_notice": "Selected latest item from returned RSS window; rate unchanged",
            "execution_eligible": False, "issuer_claim_verified": False,
            "full_history_verified": False, "returned_item_count": len(raw_items),
            "selected_reference_date": ref_date,
        }
        record = {
            "source_id": self.source_id, "canonical_url": self.REQUEST_URL,
            "published_at": utc_iso(latest["raw_pub"]), "retrieved_at": retrieved_iso,
            "jurisdiction": "EA", "language": "en", "claim_type": "macro_indicator",
            "evidence_role": "macroeconomics", "parser_id": self.source_id,
            "parser_version": self.parser_version, "payload": payload,
        }
        return make_batch(
            source_id=self.source_id, parser_version=self.parser_version,
            content=content, retrieved_at=retrieved_iso, records=[record],
        )
