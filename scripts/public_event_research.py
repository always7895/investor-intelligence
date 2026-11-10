"""Public filing/notice EVENT discovery, not a news sentiment score.

SEC 8-K/425/S-4 and TWSE/MOPS/DART original notices are discovery metadata.
A filing is not automatically a bullish event, an order, or a qualified company.
Inputs can be captured official JSON fixtures; the SEC HTTP refresh requires a
separately configured fair-access identity. No paid fallback or private data.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "config" / "bottleneck-layers-v3.json"
DEFAULT_TICKERS = ROOT / "data" / "cache" / "v21" / "company_tickers_exchange.json"
DEFAULT_CACHE = ROOT / "data" / "cache" / "public_event_research_latest.json"

SCHEMA = "public-events-r2b-v1"
SEC_FORMS = frozenset(("8-K", "8-K/A", "425", "S-4", "S-4/A"))
EVENT_LIMIT_PER_SYMBOL = 5
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,15}$")
DATE = re.compile(r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]$")
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data/"
SUPPORTED_ORIGINS = {
    "US": ("www.sec.gov", "data.sec.gov"),
    "TW": ("mops.twse.com.tw", "mopsov.twse.com.tw", "www.twse.com.tw",
           "openapi.twse.com.tw", "www.tpex.org.tw"),
    "KR": ("dart.fss.or.kr", "englishdart.fss.or.kr", "kind.krx.co.kr"),
}
TW_NOTICE_URLS = (
    "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O",
)
DART_RSS_URL = "https://dart.fss.or.kr/api/todayRSS.xml"
BODY_LIMIT = 12 * 1024 * 1024
METADATA_LABELS = {"US": "SEC 公告（內容待查）", "TW": "交易所公告（內容待查）",
                   "KR": "交易所公告（內容待查）"}


def _source_status(source: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"source": source, "status": status, "reason_zh": reason, **extra}


def _payload(fetch: Any, url: str) -> bytes:
    raw = fetch(url)
    if type(raw) is not bytes or not raw or len(raw) > BODY_LIMIT:
        raise ValueError("PUBLIC_EVENT_PAYLOAD_INVALID")
    return raw


def sec_daily_index_events(raw: bytes, *, cik_map: dict[str, int],
                           cutoff: date) -> list[dict[str, Any]]:
    """Market-wide official index, exact CIK/ticker identity; never issuer-name matching."""
    text = raw.decode("utf-8-sig")
    if "CIK|Company Name|Form Type|Date Filed|Filename" not in text:
        raise ValueError("SEC_DAILY_INDEX_INVALID")
    symbols_by_cik: dict[int, list[str]] = {}
    for symbol, cik in cik_map.items():
        if SYMBOL.fullmatch(symbol) and type(cik) is int and cik > 0:
            symbols_by_cik.setdefault(cik, []).append(symbol)
    events = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 3 or parts[2] not in SEC_FORMS:
            continue
        if len(parts) != 5:
            raise ValueError("SEC_DAILY_INDEX_ROW_INVALID")
        cik, _, form, filed, filename = parts
        when = _day(filed)
        match = re.fullmatch(r"edgar/data/(\d+)/(\d{10}-\d{2}-\d{6})\.txt", filename)
        if not (cik.isdigit() and match and int(cik) == int(match[1])
                and when and when <= cutoff):
            raise ValueError("SEC_DAILY_INDEX_ROW_INVALID")
        for symbol in symbols_by_cik.get(int(cik), []):
            events.append({"symbol": symbol, "market": "US", "form": form,
                           "published_on": filed, "source_url": "https://www.sec.gov/Archives/" + filename,
                           "headline_zh": METADATA_LABELS["US"], "status": "PRIMARY_METADATA_ONLY",
                           "rights": "PUBLIC_RESEARCH_ONLY"})
    return events


def twse_notice_events(raw: bytes, *, source_url: str, cutoff: date) -> list[dict[str, Any]]:
    """TWSE/TPEX redistribution of MOPS filings; retain dates/identity, not personal body text."""
    if source_url not in TW_NOTICE_URLS:
        raise ValueError("TW_NOTICE_SOURCE_INVALID")
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError("TW_NOTICE_SHAPE")
    result = []
    suffix = ".TW" if source_url == TW_NOTICE_URLS[0] else ".TWO"
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("TW_NOTICE_ROW_INVALID")
        code = row.get("公司代號") or row.get("SecuritiesCompanyCode")
        filed = str(row.get("發言日期", ""))
        if not isinstance(code, str) or not re.fullmatch(r"\d{4,6}", code) or not re.fullmatch(r"\d{7}", filed):
            raise ValueError("TW_NOTICE_IDENTITY_DATE_MISSING")
        when = _day(f"{int(filed[:3]) + 1911:04d}-{filed[3:5]}-{filed[5:]}")
        if when is None:
            raise ValueError("TW_NOTICE_DATE_INVALID")
        if when > cutoff:
            continue
        row_hash = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        result.append({"symbol": code + suffix, "market": "TW", "form": "MOPS_NOTICE",
                       "published_on": when.isoformat(), "source_url": source_url,
                       "headline_zh": METADATA_LABELS["TW"], "status": "PRIMARY_METADATA_ONLY",
                       "rights": "PUBLIC_RESEARCH_ONLY", "source_record_sha256": row_hash})
    return result


def dart_rss_notices(raw: bytes, *, cutoff: date) -> list[dict[str, Any]]:
    """Public DART feed has receipt identity but no stock code; do not guess one from company names."""
    root = ET.fromstring(raw)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("DART_RSS_INVALID")
    result = []
    for item in root.findall("./channel/item"):
        url = item.findtext("link", "")
        if not re.fullmatch(r"https://dart\.fss\.or\.kr/api/link\.jsp\?rcpNo=\d{14}", url):
            raise ValueError("DART_RECEIPT_INVALID")
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
        except (ValueError, TypeError) as error:
            raise ValueError("DART_DATE_INVALID") from error
        if published.tzinfo is None:
            raise ValueError("DART_TIMEZONE_MISSING")
        when = published.astimezone(timezone.utc).date()
        if when > cutoff:
            continue
        result.append({"market": "KR", "published_on": when.isoformat(), "source_url": url,
                       "status": "ISSUER_IDENTITY_UNVERIFIED", "rights": "PUBLIC_RESEARCH_ONLY",
                       "reason_zh": "免費 DART 公開快訊未提供股票代號；未核對官方身分前不建立股票候選。"})
    return result


def refresh_public_discovery(*, cutoff: date, cik_map: dict[str, int], fetch: Any,
                             sec_fetch: Any | None = None, lookback_days: int = 7) -> dict[str, Any]:
    """Real free-primary discovery outside coverage. Partial coverage is explicitly not fresh.

    Only dates, official document links and hashes leave the fetch boundary. No news
    sentiment, translated body claim or automatic company admission is created.
    """
    if not 1 <= lookback_days <= 31:
        raise ValueError("DISCOVERY_LOOKBACK_BOUND")
    events, statuses, unresolved = [], [], []
    for offset in range(lookback_days):
        day = cutoff - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        url = (f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/"
               f"QTR{(day.month - 1) // 3 + 1}/master.{day:%Y%m%d}.idx")
        try:
            raw = _payload(sec_fetch or fetch, url)
            found = sec_daily_index_events(raw, cik_map=cik_map, cutoff=cutoff)
            events.extend(found)
            statuses.append(_source_status(url, "RETRIEVED_METADATA", "僅有申報索引，公告內容及公司資格仍待核實。",
                                           source_sha256=hashlib.sha256(raw).hexdigest(), count=len(found)))
        except (ValueError, TypeError, KeyError):
            statuses.append(_source_status(url, "INVALID_SOURCE",
                "免費 SEC 索引格式、日期或證券身分不一致；事件覆蓋範圍未驗證。"))
        except OSError:
            statuses.append(_source_status(url, "UNAVAILABLE", "免費 SEC 當日索引尚未公布或無法取得；不可宣稱完整或新鮮。"))
    for url in TW_NOTICE_URLS:
        try:
            raw = _payload(fetch, url)
            found = twse_notice_events(raw, source_url=url, cutoff=cutoff)
            events.extend(found)
            statuses.append(_source_status(url, "RETRIEVED_METADATA", "已取得交易所公開重大訊息；內容、權利及公司資格仍須獨立審核。",
                                           source_sha256=hashlib.sha256(raw).hexdigest(), count=len(found)))
        except (OSError, ValueError, TypeError, KeyError):
            statuses.append(_source_status(url, "UNAVAILABLE", "免費 MOPS／交易所重大訊息無法取得；不改用未授權鏡像。"))
    try:
        raw = _payload(fetch, DART_RSS_URL)
        unresolved = dart_rss_notices(raw, cutoff=cutoff)
        statuses.append(_source_status(DART_RSS_URL, "IDENTITY_UNVERIFIED",
                                       "DART 免費快訊缺股票代號；完整 API 需另行核准憑證，不猜身分或繞過限制。",
                                       source_sha256=hashlib.sha256(raw).hexdigest(), count=len(unresolved)))
    except (OSError, ValueError, TypeError, KeyError, ET.ParseError):
        statuses.append(_source_status(DART_RSS_URL, "UNAVAILABLE", "免費 DART 快訊無法取得；韓國事件維持未驗證。"))
    candidates = [{"symbol": row["symbol"], "market": row["market"],
                   "observed_on": row["published_on"], "source_url": row["source_url"]} for row in events]
    return {"events": events, "discovered_candidates": open_discovery(candidates, cutoff=cutoff),
            "unresolved_notices": unresolved, "source_status": statuses,
            "refresh_status": "PARTIAL", "freshness_status": "NOT_FULLY_VERIFIED",
            "coverage_zh": "僅涵蓋指定 SEC 索引日期及交易所即日快訊；非完整歷史或全市場即時事件。"}


def public_notice_fetcher() -> Any:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("PUBLIC_NOTICE_REDIRECT_REFUSED")
    opener = urllib.request.build_opener(NoRedirect)
    def fetch(url: str) -> bytes:
        if url not in (*TW_NOTICE_URLS, DART_RSS_URL):
            raise ValueError("PUBLIC_NOTICE_URL_REFUSED")
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "PublicResearch/1.0"}),
                         timeout=35) as stream:
            raw = stream.read(BODY_LIMIT + 1)
        if len(raw) > BODY_LIMIT:
            raise ValueError("PUBLIC_NOTICE_PAYLOAD_LIMIT")
        return raw
    return fetch


def bind_primary_body_review(event: dict[str, Any], body: bytes, *, excerpt: str,
                             reviewed_on: date) -> dict[str, Any]:
    """Bind a HUMAN-reviewed claim to retrieved primary body bytes, never infer it from metadata.

    The reviewer supplies the precise supporting clause. Only hashes are persisted;
    retrieval and a substring match do not themselves validate the claim's meaning.
    """
    if (event.get("reviewed") is not True or event.get("rights") != "PUBLIC_RESEARCH_ONLY"
            or not _url(event.get("source_url"), event.get("market"))
            or type(body) is not bytes or not body or len(body) > BODY_LIMIT):
        raise ValueError("PRIMARY_BODY_REVIEW_REQUIRED")
    plain = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body.decode("utf-8", errors="replace"))).split())
    quote = " ".join(excerpt.split())
    if len(quote) < 20 or quote not in plain:
        raise ValueError("PRIMARY_BODY_CLAUSE_MISSING")
    return {**event, "primary_body": {"sha256": hashlib.sha256(body).hexdigest(),
                                    "excerpt_sha256": hashlib.sha256(quote.encode()).hexdigest(),
                                    "source_url": event["source_url"], "claim_reviewed": True,
                                    "reviewed_on": reviewed_on.isoformat()}}


def _body_reviewed(event: dict[str, Any], *, cutoff: date) -> bool:
    proof = event.get("primary_body")
    if not isinstance(proof, dict):
        return False
    reviewed = _day(proof.get("reviewed_on"))
    return bool(reviewed and reviewed <= cutoff and reviewed >= (_day(event.get("published_on")) or cutoff)
                and proof.get("claim_reviewed") is True and proof.get("source_url") == event.get("source_url")
                and all(isinstance(proof.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", proof[key])
                        for key in ("sha256", "excerpt_sha256")))


def _day(value: Any) -> date | None:
    if not isinstance(value, str) or not DATE.fullmatch(value):
        return None
    try: parsed = date.fromisoformat(value)
    except ValueError: return None
    return parsed if parsed.isoformat() == value else None


def _url(raw: Any, market: str) -> bool:
    if not isinstance(raw, str) or len(raw) > 500:
        return False
    try:
        u = urlparse(raw)
        return (u.scheme == "https" and u.hostname in SUPPORTED_ORIGINS.get(market, ())
                and u.port in (None, 443) and u.username is None and u.password is None and not u.fragment)
    except ValueError:
        return False


def sec_submission_events(symbol: str, raw: dict[str, Any], *, cutoff: date) -> list[dict[str, Any]]:
    """Read only official EDGAR submissions JSON; no document-content claims."""
    if not SYMBOL.fullmatch(symbol):
        raise ValueError("EVENT_SYMBOL_INVALID")
    filings = raw.get("filings", {}).get("recent", {})
    keys = ("form", "filingDate", "accessionNumber", "primaryDocument")
    if not all(isinstance(filings.get(k), list) for k in keys):
        raise ValueError("SEC_SUBMISSION_SHAPE")
    if len({len(filings[k]) for k in keys}) != 1:
        raise ValueError("SEC_SUBMISSION_LENGTH")
    issuer_cik = raw.get("cik")
    if type(issuer_cik) is not int or issuer_cik <= 0:
        raise ValueError("SEC_ISSUER_INVALID")
    result = []
    for form, filed, accession, doc in zip(*(filings[k] for k in keys)):
        when = _day(filed)
        if form not in SEC_FORMS or when is None or when > cutoff:
            continue
        # EDGAR metadata may be advertised before a document is accessible. Check
        # the original filing document before promoting to a company claim.
        if not (isinstance(accession, str) and re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession)
                and isinstance(doc, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,200}", doc)):
            continue
        url = SEC_ARCHIVES + str(issuer_cik) + "/" + accession.replace("-", "") + "/" + doc
        result.append({"symbol": symbol, "market": "US", "form": form, "published_on": filed,
                       "source_url": url, "headline_zh": "SEC 公告（內容待查）",
                       "status": "PRIMARY_METADATA_ONLY", "rights": "PUBLIC_RESEARCH_ONLY"})
    return sorted(result, key=lambda x: (x["published_on"], x["source_url"]), reverse=True)[:EVENT_LIMIT_PER_SYMBOL]


def exchange_notice_events(market: str, symbol: str, raw: list[dict[str, Any]],
                           *, cutoff: date) -> list[dict[str, Any]]:
    """Adapt already-retrieved official MOPS/TWSE or KR DART notices with dates and original URLs.

    No unauthenticated website scraping or DART API key guessing; a caller must
    separately document the allowed official source/rights before live activation.
    """
    if market not in ("TW", "KR") or not SYMBOL.fullmatch(symbol):
        raise ValueError("EXCHANGE_EVENT_SCOPE")
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        day = _day(item.get("published_on"))
        url = item.get("source_url")
        if item.get("symbol") != symbol or day is None or day > cutoff or not _url(url, market):
            continue
        result.append({"symbol": symbol, "market": market, "form": "EXCHANGE_NOTICE",
                       "published_on": day.isoformat(), "source_url": url,
                       "headline_zh": "交易所公告（內容待查）",
                       "status": "PRIMARY_METADATA_ONLY", "rights": "PUBLIC_RESEARCH_ONLY"})
    return sorted(result, key=lambda x: (x["published_on"], x["source_url"]), reverse=True)[:EVENT_LIMIT_PER_SYMBOL]


def refresh_sec_events(*, symbols: list[str], cik_map: dict[str, int], cutoff: date,
                       fetch: Any) -> list[dict[str, Any]]:
    """One bounded, official EDGAR submissions fetch per known US issuer.

    Malformed or unavailable filings fail the refresh, not a previously sealed ranking;
    original SEC filing notices are only metadata until independent content review.
    """
    if len(symbols) > 100 or len(set(symbols)) != len(symbols):
        raise ValueError("SEC_EVENT_UNIVERSE_BOUND")
    results: list[dict[str, Any]] = []
    for symbol in symbols:
        cik = cik_map.get(symbol)
        if not isinstance(cik, int) or cik <= 0:
            continue  # Non-US / unknown mapping: not a fabricated SEC issuer
        url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        raw = fetch(url)
        if type(raw) is not bytes or len(raw) > 12 * 1024 * 1024:
            raise ValueError("SEC_EVENT_BYTES")
        document = json.loads(raw)
        if document.get("cik") != cik:
            raise ValueError("SEC_EVENT_ISSUER_MISMATCH")
        results.extend(sec_submission_events(symbol, document, cutoff=cutoff))
    return results


def official_ticker_map(raw: dict[str, Any]) -> dict[str, int]:
    """SEC ticker directory only; symbol-to-CIK identity must not be guessed."""
    fields = raw.get("fields") if type(raw) is dict else None
    rows = raw.get("data") if type(raw) is dict else None
    if not isinstance(fields, list) or not isinstance(rows, list) or "ticker" not in fields or "cik" not in fields:
        raise ValueError("SEC_TICKER_MAP_INVALID")
    t, c = fields.index("ticker"), fields.index("cik")
    result: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(t,c):
            continue
        symbol, cik = row[t], row[c]
        if isinstance(symbol, str) and SYMBOL.fullmatch(symbol) and type(cik) is int and cik > 0:
            if symbol in result and result[symbol] != cik:
                raise ValueError("SEC_TICKER_MAP_AMBIGUOUS")
            result[symbol] = cik
    return result


def registered_us_symbols(layers: dict[str, Any]) -> list[str]:
    """Known covered US issuers; wider discovery stages separately before admission."""
    seen = set()
    for layer in layers.get("layers", []):
        for row in layer.get("capturers", []):
            symbol = row.get("symbol")
            if isinstance(symbol, str) and "." not in symbol and SYMBOL.fullmatch(symbol):
                seen.add(symbol)
    return sorted(seen)


def sec_public_fetcher() -> Any:
    from sec_contact_headers import sec_identity_headers
    headers = sec_identity_headers()
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("SEC_EVENT_REDIRECT_REFUSED")
    opener = urllib.request.build_opener(NoRedirect)
    def fetch(url: str) -> bytes:
        parsed = urlparse(url)
        allowed = (parsed.hostname == "data.sec.gov" and parsed.path.startswith("/submissions/")) or (
            parsed.hostname == "www.sec.gov" and parsed.path.startswith("/Archives/edgar/"))
        if (parsed.scheme != "https" or not allowed or parsed.username or parsed.password
                or parsed.fragment or parsed.query or parsed.port not in (None, 443)):
            raise ValueError("SEC_EVENT_URL_REFUSED")
        time.sleep(0.15)  # SEC Fair Access; no parallel unbounded requests
        response = opener.open(urllib.request.Request(url, headers=headers), timeout=35)
        with response as stream:
            content = stream.read(12 * 1024 * 1024 + 1)
        if len(content) > 12 * 1024 * 1024:
            raise ValueError("SEC_EVENT_PAYLOAD_LIMIT")
        return content
    return fetch


def curated_company_event(event: dict[str, Any], *, cutoff: date) -> dict[str, Any] | None:
    """An explicit reviewed, dated primary event can be shown (never scored)."""
    if not isinstance(event, dict):
        return None
    published = _day(event.get("published_on"))
    market = event.get("market")
    if not (published and published <= cutoff and market in SUPPORTED_ORIGINS
            and _url(event.get("source_url"), market)
            and isinstance(event.get("headline_zh"), str)
            and 1 <= len(event["headline_zh"]) <= 70
            and "\n" not in event["headline_zh"]
            and event.get("reviewed") is True and event.get("rights") == "PUBLIC_RESEARCH_ONLY"
            and _body_reviewed(event, cutoff=cutoff)):
        return None
    return {"published_on": published.isoformat(), "source_url": event["source_url"],
            "headline_zh": event["headline_zh"], "status": "PRIMARY_REVIEWED"}


def validate_latest_event(raw: Any, *, cutoff: date, symbol: str | None = None,
                          reviewed_events: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Return the card's four safe fields; projected claims require a body-bound registration."""
    if not isinstance(raw, dict) or (symbol and raw.get("symbol", symbol) != symbol):
        return None
    when = _day(raw.get("published_on"))
    if when is None or when > cutoff:
        return None
    market = next((market for market in SUPPORTED_ORIGINS if _url(raw.get("source_url"), market)), None)
    if market is None:
        return None
    if raw.get("status") == "PRIMARY_METADATA_ONLY":
        if raw.get("headline_zh") != METADATA_LABELS[market]:
            return None
        return {key: raw[key] for key in ("published_on", "source_url", "headline_zh", "status")}
    if raw.get("status") != "PRIMARY_REVIEWED":
        return None
    if not isinstance(reviewed_events, list):
        return None
    projection = {key: raw.get(key) for key in ("published_on", "source_url", "headline_zh", "status")}
    for event in reviewed_events:
        if isinstance(event, dict) and (not symbol or event.get("symbol") == symbol):
            if curated_company_event(event, cutoff=cutoff) == projection:
                return projection
    return None


def latest_event(events: list[dict[str, Any]], *, symbol: str, cutoff: date,
                 reviewed_events: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    candidate = []
    for event in events:
        if not isinstance(event, dict) or event.get("symbol") != symbol:
            continue
        chosen = curated_company_event(event, cutoff=cutoff)
        chosen = validate_latest_event(chosen if chosen is not None else event, cutoff=cutoff,
                                       symbol=symbol, reviewed_events=reviewed_events)
        if chosen is not None:
            candidate.append(chosen)
    return max(candidate, key=lambda x: (x["published_on"], x["status"] == "PRIMARY_REVIEWED")) if candidate else None


def open_discovery(candidates: list[dict[str, Any]], *, cutoff: date) -> list[dict[str, Any]]:
    """Market-wide discovery staging, NOT an admission decision or sector whitelist."""
    accepted = {}
    for row in candidates:
        if not isinstance(row, dict):
            continue
        market, symbol = row.get("market"), row.get("symbol")
        day = _day(row.get("observed_on"))
        if (market in SUPPORTED_ORIGINS and isinstance(symbol, str) and SYMBOL.fullmatch(symbol)
                and day is not None and day <= cutoff and _url(row.get("source_url"), market)):
            accepted[(market, symbol)] = {"market": market, "symbol": symbol, "observed_on": day.isoformat(),
                                           "source_url": row["source_url"], "admission": "DISCOVERED_UNVERIFIED"}
    return [accepted[key] for key in sorted(accepted)]


def admitted_candidate_rows(rows: list[dict[str, Any]], *,
                            cutoff: date, layer_ids: set[str]) -> list[dict[str, Any]]:
    """Evidence-qualified *extra* issuers, not author-following or an automatic hype list.

    Requires a manually reviewed issuer filing and independently registered
    counterparty filing, with distinct SEC filer CIKs. The ranking's pre-existing
    return, corporate action, source, sector and bearish gates still apply.
    """
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("DYNAMIC_ADMISSION_BOUND")
    accepted = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym, layer = row.get("symbol"), row.get("layer_id")
        role, role_zh = row.get("role"), row.get("role_zh")
        day = _day(row.get("source_date"))
        evidence = row.get("evidence")
        if not (row.get("reviewed") is True and row.get("admission") == "REVIEWED_PRIMARY"
                and row.get("market") == "US"
                and isinstance(sym, str) and SYMBOL.fullmatch(sym) and sym not in seen
                and layer in layer_ids and isinstance(role, str) and 1 <= len(role) <= 160
                and isinstance(role_zh, str) and 1 <= len(role_zh) <= 160
                and day and day <= cutoff and isinstance(evidence, list) and len(evidence) == 2):
            continue
        issuer_ciks = []
        for idx, piece in enumerate(evidence):
            if (not isinstance(piece, dict) or piece.get("reviewed") is not True
                    or piece.get("rights") != "PUBLIC_RESEARCH_ONLY" or not _body_reviewed(piece, cutoff=cutoff)):
                break
            if piece.get("role") != ("ISSUER" if idx == 0 else "COUNTERPARTY"):
                break
            filing_date = _day(piece.get("published_on"))
            url = piece.get("source_url")
            if not filing_date or filing_date > cutoff or not isinstance(url, str):
                break
            match = re.fullmatch(
                r"https://www\.sec\.gov/Archives/edgar/data/(\d{1,12})/\d{18}/[A-Za-z0-9._-]{1,200}",
                url,
            )
            if match is None:
                break
            if piece.get("issuer_cik") != int(match.group(1)):
                break
            if idx == 0 and piece.get("symbol") != sym:
                break
            issuer_ciks.append(int(match.group(1)))
        if len(issuer_ciks) != 2 or issuer_ciks[0] == issuer_ciks[1]:
            continue
        seen.add(sym)
        accepted.append({
            "symbol": sym, "layer_id": layer, "role": role, "role_zh": role_zh,
            "source_date": day.isoformat(), "source_url": evidence[0]["source_url"],
            "counterparty_source_url": evidence[1]["source_url"],
            "admission": "REVIEWED_PRIMARY", "reviewed": True,
            "market": "US", "evidence": evidence,
        })
    return sorted(accepted, key=lambda x: x["symbol"])


def build(event_rows: list[dict[str, Any]], *, cutoff: date,
          universe: list[dict[str, Any]] | None = None,
          admissions: list[dict[str, Any]] | None = None,
          layer_ids: set[str] | None = None) -> dict[str, Any]:
    clean = []
    for event in event_rows:
        if not isinstance(event, dict):
            continue
        sym = event.get("symbol")
        if not (isinstance(sym, str) and SYMBOL.fullmatch(sym)):
            continue
        chosen = curated_company_event(event, cutoff=cutoff)
        if chosen is not None:
            clean.append({**{key: event[key] for key in ("market", "reviewed", "rights", "primary_body")},
                          "symbol": sym, **chosen})
        elif event.get("status") == "PRIMARY_METADATA_ONLY" and event.get("market") in SUPPORTED_ORIGINS:
            date_ = _day(event.get("published_on"))
            expected = "SEC 公告（內容待查）" if event["market"] == "US" else "交易所公告（內容待查）"
            if (date_ and date_ <= cutoff and _url(event.get("source_url"), event["market"])
                    and event.get("headline_zh") == expected and event.get("rights") == "PUBLIC_RESEARCH_ONLY"):
                clean.append({k: event[k] for k in ("symbol", "market", "published_on", "source_url", "headline_zh", "status", "rights")})
    clean.sort(key=lambda x: (x["symbol"], x["published_on"], x["source_url"]))
    return {"schema": SCHEMA, "generated_for": cutoff.isoformat(), "events": clean,
            "source_status": [], "refresh_status": "UNVERIFIED_INPUT",
            "freshness_status": "NOT_FULLY_VERIFIED",
            "discovered_candidates": open_discovery(universe or [], cutoff=cutoff),
            "admitted_candidates": admitted_candidate_rows(admissions or [], cutoff=cutoff,
                                                            layer_ids=layer_ids or set()),
            "score_authority": "NONE", "requires_independent_company_admission": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--events", type=Path)
    source.add_argument("--refresh-sec", action="store_true")
    parser.add_argument("--universe", type=Path)
    parser.add_argument("--ticker-map", type=Path, default=DEFAULT_TICKERS)
    parser.add_argument("--layers", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--exchange-notices", type=Path)  # already captured official, never scraped
    parser.add_argument("--reviewed-events", type=Path, default=ROOT / "config" / "public-reviewed-events-v1.json")
    parser.add_argument("--admissions", type=Path,
                        default=ROOT / "config" / "reviewed-open-candidates-v1.json")
    # Only manually reviewed primary issuer+counterparty filings can satisfy this input.
    parser.add_argument("--output", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--as-of", type=str, default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    args = parser.parse_args(argv)
    cutoff = _day(args.as_of)
    if cutoff is None:
        return 2
    try:
        if args.if_older_than_hours > 0 and args.output.is_file():
            existing = json.loads(args.output.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(existing["retrieved_at"].replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - created
            if (existing.get("refresh_status") == "COMPLETE" and existing.get("freshness_status") == "VERIFIED"
                    and 0 <= elapsed.total_seconds() < args.if_older_than_hours * 3600):
                print("PUBLIC_EVENT_DISCOVERY=SKIPPED_FRESH")
                return 0
        discovery = None
        submission_status = []
        if args.refresh_sec:
            mapping = official_ticker_map(json.loads(args.ticker_map.read_text(encoding="utf-8")))
            layers = json.loads(args.layers.read_text(encoding="utf-8"))
            try:
                sec_fetch = sec_public_fetcher()
                rows = refresh_sec_events(symbols=registered_us_symbols(layers),
                                          cik_map=mapping, cutoff=cutoff, fetch=sec_fetch)
                submission_status.append(_source_status("SEC_SUBMISSIONS", "RETRIEVED_METADATA",
                                                        "取得已覆蓋公司的申報索引，不代表內容已核實。"))
            except (OSError, ValueError, RuntimeError, TypeError, KeyError):
                rows = []
                submission_status.append(_source_status("SEC_SUBMISSIONS", "UNAVAILABLE",
                                                        "SEC 免費原始來源或合規聯絡身分不可用；保留未驗證狀態。"))
                def sec_fetch(url: str) -> bytes:
                    raise ValueError("SEC_SOURCE_UNAVAILABLE")
            discovery = refresh_public_discovery(cutoff=cutoff, cik_map=mapping,
                                                 fetch=public_notice_fetcher(), sec_fetch=sec_fetch)
            rows.extend(discovery["events"])
        else:
            rows = json.loads(args.events.read_text(encoding="utf-8"))
        if args.exchange_notices:
            extra = json.loads(args.exchange_notices.read_text(encoding="utf-8"))
            if not isinstance(extra, dict) or set(extra) - {"TW", "KR"}:
                raise ValueError("EXCHANGE_NOTICES_INVALID")
            for market, symbol_groups in extra.items():
                if not isinstance(symbol_groups, dict):
                    raise ValueError("EXCHANGE_NOTICES_INVALID")
                for symbol, notices in symbol_groups.items():
                    if not isinstance(notices, list):
                        raise ValueError("EXCHANGE_NOTICES_INVALID")
                    rows.extend(exchange_notice_events(market, symbol, notices, cutoff=cutoff))
        universe = json.loads(args.universe.read_text(encoding="utf-8")) if args.universe else []
        if discovery is not None:
            universe.extend(discovery["discovered_candidates"])
        reviewed = (json.loads(args.reviewed_events.read_text(encoding="utf-8"))
                    if args.reviewed_events.is_file() else [])
        if not isinstance(rows, list) or not isinstance(universe, list) or not isinstance(reviewed, list):
            return 2
        admissions = json.loads(args.admissions.read_text(encoding="utf-8")) if args.admissions.is_file() else []
        if not isinstance(admissions, list):
            raise ValueError("DYNAMIC_ADMISSION_SHAPE")
        layers_for_admission = json.loads(args.layers.read_text(encoding="utf-8"))
        layer_ids = {layer["id"] for layer in layers_for_admission["layers"]}
        doc = build(rows + reviewed, cutoff=cutoff, universe=universe,
                    admissions=admissions, layer_ids=layer_ids)
        if discovery is not None:
            for key in ("unresolved_notices", "source_status", "refresh_status", "freshness_status", "coverage_zh"):
                doc[key] = discovery[key]
            doc["source_status"] = submission_status + doc["source_status"]
        doc["retrieved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_suffix(".tmp")
        temp.write_text(json.dumps(doc, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temp.replace(args.output)
        print("PUBLIC_EVENT_DISCOVERY=" + doc["refresh_status"])
        return 0
    except (OSError, TypeError, ValueError, RuntimeError, ET.ParseError):
        print("PUBLIC_EVENT_DISCOVERY=FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
