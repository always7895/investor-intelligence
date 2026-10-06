#!/usr/bin/env python3
"""Global identity shards for the LINE stock lookup (contract v213-identity-shard-v2).

Reads the official listing directories and writes compact shards the Worker loads on demand (sealed as
content-addressed lazy objects; see scripts/publish_sealed_snapshot.py --identity-shards):

- US: Nasdaq Trader symbol directories (nasdaqlisted.txt, otherlisted.txt; test issues excluded). Only when either
  directory fails or is too small are BOTH replaced as one unit by the already cached SEC raw file
  company_tickers_exchange.json (Nasdaq and NYSE rows only, class REVIEW_REQUIRED, the cache's file mtime as retrieval
  time, at most 7 days old; local read only, no new request). That build is DEGRADED_US_FALLBACK (exit 2): partial US
  coverage, availability only, not independent corroboration;
- Taiwan: TWSE listed companies (t187ap03_L) and TPEx listed companies (mopsfin_t187ap03_O);
- Sweden: Nasdaq Nordic share screener for Stockholm Main Market and First North (public exchange web API);
- Japan: JPX list of TSE-listed issues (data_e.xlsx, read with the standard library);
- Korea: KRX KIND listed-company list (KOSPI and KOSDAQ; Korean names);
- Euronext: Paris, Amsterdam, Brussels and Milan equities (Euronext stock download);
- London: Main Market and AIM equities (the exchange's price-explorer API; optional: a failure leaves London out).

Every row carries a Traditional Chinese name when a source states one (tenth column [name_zh, source]; null
otherwise): Taiwan rows use the exchange's own Chinese short name (source TWSE/TPEX), other markets the sourced names of
scripts/build_zh_names.py (OFFICIAL, ZHWIKI, WIKIDATA_LABEL). Nothing is translated; the Chinese name is also indexed
for name lookups.

Symbol shards are keyed by the first character of the symbol (A-Z, 0-9, _), name shards by FNV-1a(normalized name)
mod 16 (the Worker computes the same hash over UTF-16 code units). Every shard names its feeds with URL, retrieval
time and the SHA-256 of the raw download. A feed that fails keeps its previous rows out entirely (never partial); the
build fails when a required feed is missing, so the last good shards keep serving.

Usage: build_identity_shards.py [--output data/cache/identity_shards_latest.json]
Exit status: 0 OK or skipped fresh; 1 failed (the last good shards keep serving); 2 DEGRADED_US_FALLBACK written.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from stat import S_ISREG
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from global_identity_index import classify_security  # noqa: E402

OUTPUT = ROOT / "data" / "cache" / "identity_shards_latest.json"
ZH_NAMES = ROOT / "data" / "cache" / "zh_names_latest.json"
ZH_SOURCES = {"OFFICIAL", "ZHWIKI", "WIKIDATA_LABEL"}
SCHEMA = "v213-identity-shard-v2"
NAME_BUCKETS = 16
USER_AGENT = "Mozilla/5.0 (InvestorIntelligence public identity directory)"  # Euronext refuses clients without a browser agent
FEEDS = {
    "nasdaq-listed": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "other-us-listed": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
    "twse-listed": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "tpex-listed": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
    "nasdaq-stockholm-main": "https://api.nasdaq.com/api/nordic/screener/shares?category=MAIN_MARKET&tableonly=false&market=STO",
    "nasdaq-stockholm-first-north": "https://api.nasdaq.com/api/nordic/screener/shares?category=FIRST_NORTH&tableonly=false&market=STO",
    "jpx-listed": "https://www.jpx.co.jp/english/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_e.xlsx",
    "krx-listed": "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13",
    "euronext-equities": "https://live.euronext.com/en/pd_es/data/stocks/download?mics=dm_all_stock&initialLetter=&fe_type=csv&fe_decimal_separator=.&fe_date_format=d%2Fm%2FY",
    "lse-main-market": "https://api.londonstockexchange.com/api/v1/components/refresh#markets=MAINMARKET",
    "lse-aim": "https://api.londonstockexchange.com/api/v1/components/refresh#markets=AIM",
}
OPTIONAL_FEEDS = {"lse-main-market", "lse-aim"}
EURONEXT_VENUES = {"Euronext Paris": ("EURONEXT PARIS", "France"), "Euronext Growth Paris": ("EURONEXT PARIS", "France"),
                   "Euronext Amsterdam": ("EURONEXT AMSTERDAM", "Netherlands"), "Euronext Brussels": ("EURONEXT BRUSSELS", "Belgium"),
                   "Euronext Growth Brussels": ("EURONEXT BRUSSELS", "Belgium"), "Euronext Milan": ("BORSA ITALIANA", "Italy"),
                   "Euronext Growth Milan": ("BORSA ITALIANA", "Italy")}
KRX_MARKETS = {"유가": ("KRX", "KOSPI"), "유가증권": ("KRX", "KOSPI"), "코스닥": ("KOSDAQ", "KOSDAQ")}
OTHER_US_VENUES = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
MINIMUM_ROWS = {"nasdaq-listed": 3000, "other-us-listed": 3000, "twse-listed": 800, "tpex-listed": 600,
                "nasdaq-stockholm-main": 250, "nasdaq-stockholm-first-north": 150, "jpx-listed": 3000, "krx-listed": 1500,
                "euronext-equities": 800, "lse-main-market": 800, "lse-aim": 400}
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9 .\-]{0,14}$")
US_FEEDS = ("nasdaq-listed", "other-us-listed")
# US availability fallback: the raw SEC file that company_deep_report.ticker_ciks already keeps; read locally, never fetched here.
SEC_FEED = "sec-company-tickers-exchange"
SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_CACHE = ROOT / "data" / "cache" / "v21" / "company_tickers_exchange.json"
SEC_MAX_BYTES = 32 * 1024 * 1024
SEC_MAX_AGE = timedelta(days=7)  # the age policy of company_deep_report.ticker_ciks
SEC_VENUES = {"Nasdaq": "NASDAQ", "NYSE": "NYSE"}  # exact SEC exchange names; every other value is skipped, never guessed
SEC_FIELDS = ("cik", "name", "ticker", "exchange")

Fetch = Callable[[str], bytes]


class IdentityShardError(RuntimeError):
    pass


# London Stock Exchange: the exchange publishes its lists only through its web application; its public price-explorer
# component API (POST) returns every equity of a market with TIDM, ISIN, issuer, currency and last price.
LSE_API = "https://api.londonstockexchange.com/api/v1/components/refresh"
LSE_COMPONENT = "block_content:9524a5dd-7053-4f7a-ac75-71d12db796b4"


def lse_post(url: str) -> bytes:
    """url = LSE_API#markets=<MAINMARKET|AIM>: the whole market's equities in one page."""
    market = url.split("#markets=", 1)[1]
    body = {"path": "live-markets/market-data-dashboard/price-explorer", "parameters": "",
            "components": [{"componentId": LSE_COMPONENT, "parameters": f"markets={market}&categories=EQUITY&page=0&size=3000"}]}
    request = urllib.request.Request(LSE_API, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - fixed public HTTPS endpoint
        return response.read()


def lse_rows(raw: bytes) -> list[dict[str, Any]]:
    document = json.loads(raw.decode("utf-8"))
    for component in document:
        for item in component.get("content") or []:
            if item.get("name") == "priceexplorersearch":
                return list(item["value"]["content"])
    raise ValueError("LSE_PRICE_EXPLORER_MISSING")


def http_get(url: str) -> bytes:
    if url.startswith(LSE_API):
        return lse_post(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed public HTTPS feeds
        return response.read()


def normalize_name(name: str) -> str:
    """Mirror of the Worker's normalizeCompanyName (trim, lower-case, collapse whitespace)."""
    return re.sub(r"\s+", " ", name.strip().lower())


def fnv1a_utf16(text: str) -> int:
    """FNV-1a 32-bit over UTF-16 code units (the Worker hashes String.charCodeAt values)."""
    value = 0x811C9DC5
    for unit in text.encode("utf-16-le").hex(" ", 2).split():
        code = int(unit[2:4] + unit[0:2], 16)
        value ^= code
        value = (value * 0x01000193) & 0xFFFFFFFF
    return value


def symbol_bucket(symbol: str) -> str:
    first = symbol[:1].upper()
    return first if re.fullmatch(r"[A-Z0-9]", first) else "_"


def _pipe_rows(raw: bytes) -> list[dict[str, str]]:
    text = raw.decode("utf-8", "replace")
    lines = [line for line in text.splitlines() if line and not line.startswith("File Creation Time")]
    return list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|"))


def xlsx_rows(raw: bytes) -> list[list[str]]:
    """First worksheet of an .xlsx as rows of cell text (standard library only; shared strings resolved)."""
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    book = zipfile.ZipFile(io.BytesIO(raw))
    shared = []
    if "xl/sharedStrings.xml" in book.namelist():
        shared = ["".join(node.text or "" for node in item.iter(namespace + "t"))
                  for item in ET.fromstring(book.read("xl/sharedStrings.xml")).findall(namespace + "si")]
    rows = []
    for row in ET.fromstring(book.read("xl/worksheets/sheet1.xml")).iter(namespace + "row"):
        values = []
        for cell in row.findall(namespace + "c"):
            if cell.get("t") == "inlineStr":
                values.append("".join(node.text or "" for node in cell.iter(namespace + "t")))
                continue
            value = cell.find(namespace + "v")
            text = value.text if value is not None and value.text is not None else ""
            values.append(shared[int(text)] if cell.get("t") == "s" and text else text)
        rows.append(values)
    return rows


def parse_feed(feed: str, raw: bytes) -> list[list[Any]]:
    """Rows: [symbol, venue, market, country, security_name, native_name, class, currency]."""
    rows: list[list[Any]] = []
    if feed in ("nasdaq-listed", "other-us-listed"):
        for row in _pipe_rows(raw):
            symbol = (row.get("Symbol") or row.get("ACT Symbol") or "").strip().upper()
            if not symbol or (row.get("Test Issue") or "N").strip().upper() == "Y":
                continue
            name = (row.get("Security Name") or "").strip()
            venue = "NASDAQ" if feed == "nasdaq-listed" else OTHER_US_VENUES.get((row.get("Exchange") or "").strip().upper(), "OTHER_US")
            security_class = classify_security(name, (row.get("ETF") or "N").strip().upper() == "Y")
            rows.append([symbol, venue, "US", "United States", name, None, security_class, "USD"])
    elif feed in ("twse-listed", "tpex-listed"):
        for row in json.loads(raw.decode("utf-8")):
            if feed == "twse-listed":
                code, full, short = row.get("公司代號"), row.get("公司名稱"), row.get("公司簡稱")
            else:
                code, full, short = row.get("SecuritiesCompanyCode"), row.get("CompanyName"), row.get("CompanyAbbreviation")
            code, full, short = str(code or "").strip(), str(full or "").strip(), str(short or "").strip()
            if not code:
                continue
            name = full or short
            rows.append([code, "TWSE" if feed == "twse-listed" else "TPEX", "TAIWAN", "Taiwan", name,
                         short if short and short != name else None, "COMMON_STOCK", "TWD"])
    elif feed == "jpx-listed":
        table = xlsx_rows(raw)
        header = table[0]
        code_at, name_at, section_at = header.index("Local Code"), header.index("Name (English)"), header.index("Section/Products")
        for row in table[1:]:
            if len(row) <= max(code_at, name_at, section_at) or not row[code_at]:
                continue
            section = row[section_at]
            security_class = "ETF" if "ETF" in section.upper() else "REVIEW_REQUIRED" if "REIT" in section.upper() or "PRO MARKET" in section.upper() else "COMMON_STOCK"
            rows.append([row[code_at].strip().upper(), "TSE", "JAPAN", "Japan", row[name_at].strip(), None, security_class, "JPY"])
    elif feed == "krx-listed":
        page = raw.decode("euc-kr", "replace")
        for row_html in re.findall(r"<tr>(.*?)</tr>", page, re.S)[1:]:
            cells = [html.unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]
            if len(cells) < 3 or cells[1] not in KRX_MARKETS:
                continue
            venue, _ = KRX_MARKETS[cells[1]]
            rows.append([cells[2].upper(), venue, "KOREA", "Korea", cells[0], cells[0], "COMMON_STOCK", "KRW"])
    elif feed == "euronext-equities":
        text = raw.decode("utf-8-sig", "replace")
        for row in csv.reader(io.StringIO(text), delimiter=";"):
            if len(row) < 5 or row[3] not in EURONEXT_VENUES or row[0] == "Name":
                continue
            venue, country = EURONEXT_VENUES[row[3]]
            rows.append([row[2].strip().upper(), venue, "EUROPE", country, row[0].strip(), None, "COMMON_STOCK", row[4].strip() or "EUR"])
    elif feed.startswith("lse-"):
        for row in lse_rows(raw):
            symbol = str(row.get("tidm") or "").strip().upper()
            description = str(row.get("description") or "").upper()
            if not symbol or str(row.get("category") or "").upper() != "EQUITY":
                continue
            security_class = ("ADR" if re.search(r"\b(GDR|ADR|DEPOSITARY)\b", description)
                              else "PREFERRED_STOCK" if re.search(r"\bPREF", description) else "COMMON_STOCK")
            rows.append([symbol, "LSE", "UK", "United Kingdom", str(row.get("issuername") or row.get("description") or "").strip(),
                         None, security_class, str(row.get("currency") or "GBX").strip() or "GBX"])
    else:
        listing = json.loads(raw.decode("utf-8"))["data"]["instrumentListing"]["rows"]
        for row in listing:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol or str(row.get("assetClass") or "SHARES").upper() != "SHARES":
                continue
            rows.append([symbol, "NASDAQ STOCKHOLM", "SWEDEN", "Sweden", str(row.get("fullName") or "").strip(), None,
                         "COMMON_STOCK", str(row.get("currency") or "SEK").strip() or "SEK"])
    # Names are bounded for the Worker reader (300 characters); longer registered names are cut, never dropped.
    for row in rows:
        row[4] = row[4][:300]
        row[5] = row[5][:100] if row[5] else None
    return [row for row in rows if _SYMBOL.fullmatch(row[0]) and row[4]]


def _sec_cik(value: Any) -> int | None:
    """A positive integral CIK from an int or a digit string; bool, float and every other type are refused."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}", value):
        number = int(value)
    else:
        return None
    return number if 0 < number <= 9_999_999_999 else None


def load_sec_cache(path: Path, now: datetime, minimum: int) -> tuple[bytes, datetime, list[list[Any]], int]:
    """Rows of the already cached SEC company_tickers_exchange.json: (exact raw bytes, file mtime, rows, skipped count).

    Local read only: no request, no write, no SEC contact. The file's mtime is the only retrieval time (LOCAL_CACHE_MTIME);
    it is neither an authenticated acquisition time nor proof of origin, and a before/after metadata comparison only observes
    drift (it is not a lock). Only the exact SEC exchanges in SEC_VENUES are kept, every row is REVIEW_REQUIRED (no class is
    guessed), unusable rows are skipped and counted, a malformed layout or conflicting duplicate rejects the file, and the
    unique accepted rows must reach `minimum` and cover both exchanges. A name must be 1..300 UTF-16 code units (the Worker's
    unit) both as stripped and in its normalized form, strictly encoded: a lone surrogate, an overlong name or a name that
    grows when normalized skips the row before any de-duplication or count, and is never cut or repaired. Anything
    unusable raises IdentityShardError.
    """
    try:
        before = path.stat()
        if not S_ISREG(before.st_mode):
            raise IdentityShardError("IDENTITY_SEC_CACHE_NOT_A_FILE")
        if before.st_size > SEC_MAX_BYTES:
            raise IdentityShardError("IDENTITY_SEC_CACHE_TOO_LARGE")
        with path.open("rb") as handle:
            raw = handle.read(SEC_MAX_BYTES + 1)
        if len(raw) > SEC_MAX_BYTES:
            raise IdentityShardError("IDENTITY_SEC_CACHE_TOO_LARGE")
        after = path.stat()
        if len(raw) != before.st_size or (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise IdentityShardError("IDENTITY_SEC_CACHE_CHANGED")
        modified = datetime.fromtimestamp(before.st_mtime, timezone.utc)
        if now - modified < timedelta(0):
            raise IdentityShardError("IDENTITY_SEC_CACHE_FUTURE")
        if now - modified > SEC_MAX_AGE:
            raise IdentityShardError("IDENTITY_SEC_CACHE_STALE")
        document = json.loads(raw.decode("utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("fields"), list) or not isinstance(document.get("data"), list):
            raise IdentityShardError("IDENTITY_SEC_CACHE_SCHEMA")
        fields = document["fields"]
        if (not all(isinstance(name, str) for name in fields) or len(set(fields)) != len(fields)
                or any(fields.count(name) != 1 for name in SEC_FIELDS)):
            raise IdentityShardError("IDENTITY_SEC_CACHE_SCHEMA")
        at = {name: fields.index(name) for name in SEC_FIELDS}
        accepted: dict[tuple[str, str], tuple[str, int]] = {}
        skipped = 0
        for item in document["data"]:
            if not isinstance(item, list) or len(item) != len(fields):
                raise IdentityShardError("IDENTITY_SEC_CACHE_SCHEMA")
            exchange, symbol, name, cik = item[at["exchange"]], item[at["ticker"]], item[at["name"]], _sec_cik(item[at["cik"]])
            if (not isinstance(exchange, str) or exchange not in SEC_VENUES or not isinstance(symbol, str)
                    or not isinstance(name, str) or cik is None):
                skipped += 1
                continue
            symbol, name = symbol.strip(), name.strip()
            if _SYMBOL.fullmatch(symbol) is None:
                skipped += 1
                continue
            try:  # the Worker counts UTF-16 code units: the stripped AND the normalized name must be 1..300, never cut
                units = len(name.encode("utf-16-le", "strict")) // 2
                normalized_units = len(normalize_name(name).encode("utf-16-le", "strict")) // 2
            except UnicodeEncodeError:  # a lone surrogate (a JSON escape can decode to one): unusable, never repaired
                skipped += 1
                continue
            if not 0 < units <= 300 or not 0 < normalized_units <= 300:
                skipped += 1
                continue
            key = (SEC_VENUES[exchange], symbol)
            if key in accepted:
                if accepted[key] != (name, cik):
                    raise IdentityShardError("IDENTITY_SEC_CACHE_CONFLICT")
                continue  # an exact duplicate collapses
            accepted[key] = (name, cik)
        rows = [[symbol, venue, "US", "United States", name, None, "REVIEW_REQUIRED", "USD"]
                for (venue, symbol), (name, _cik) in sorted(accepted.items(), key=lambda item: (item[0][1], item[0][0]))]
        if len(rows) < minimum or {row[1] for row in rows} != set(SEC_VENUES.values()):
            raise IdentityShardError(f"IDENTITY_SEC_CACHE_COVERAGE {len(rows)}")
        return raw, modified.replace(microsecond=0), rows, skipped
    except IdentityShardError:
        raise
    except Exception as error:  # unreadable, undecodable or otherwise malformed: unusable, never silently ignored
        raise IdentityShardError(f"IDENTITY_SEC_CACHE_FAILED {type(error).__name__}") from None


def load_zh_names(path: Path | None = None) -> tuple[dict[str, list[str]], dict[str, Any] | None]:
    """Sourced Chinese names by "<MARKET>:<SYMBOL>" and the feed entry describing them (None when absent)."""
    path = path or ZH_NAMES
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return {}, None
    names = document.get("names") if isinstance(document, dict) and document.get("schema") == "v213-zh-names-v1" else None
    if not isinstance(names, dict):
        return {}, None
    kept = {key: [value[0], value[1]] for key, value in names.items() if isinstance(value, list) and len(value) == 2
            and isinstance(value[0], str) and 0 < len(value[0]) <= 40 and value[1] in ZH_SOURCES}
    digest = hashlib.sha256(json.dumps(kept, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return kept, {"id": "zh-names", "url": "https://www.wikidata.org/", "retrieved_at": document.get("generated_at"),
                  "sha256": digest, "rows": len(kept)}


def zh_name(row: list[Any], names: dict[str, list[str]]) -> list[str] | None:
    if row[2] == "TAIWAN":  # the exchange directory itself is Chinese
        return [str(row[5] or row[4])[:40], row[1]]
    return names.get(f"{row[2]}:{row[0]}")


def build(fetch: Fetch = http_get, now: datetime | None = None, zh: tuple[dict[str, list[str]], dict[str, Any] | None] | None = None,
          *, sec_cache: Path | None = SEC_CACHE, minimum_rows: dict[str, int] | None = None) -> dict[str, Any]:
    """The shard document. The two US directories are read first; only when either fails or is too small are both replaced
    as a unit by the local SEC raw cache `sec_cache` (None disables the fallback; a small `minimum_rows` override, used by
    isolated tests, also sets the fallback's row minimum). An unusable cache re-raises the original US error. Any other
    required feed failing still fails the whole build; the healthy path never reads the local file."""
    now = now or datetime.now(timezone.utc)
    minimums = MINIMUM_ROWS if minimum_rows is None else {**MINIMUM_ROWS, **minimum_rows}
    zh_names, zh_feed = zh if zh is not None else load_zh_names()
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    feeds: list[dict[str, Any]] = []
    records: list[list[Any]] = []
    # ICON2: the identities already kept per (venue, symbol); a contradictory variant is kept too, an equal one is not.
    seen: dict[tuple[str, str], set[tuple[Any, ...]]] = {}
    skipped: list[str] = []
    entries: list[tuple[dict[str, Any], list[list[Any]]]] = []  # (feed record, parsed rows) in feed order
    us_entries: list[tuple[dict[str, Any], list[list[Any]]]] = []
    us_error: IdentityShardError | None = None
    for feed in US_FEEDS:  # a failure is held back: the pair is replaced as a unit, never mixed with a fallback
        try:
            raw = fetch(FEEDS[feed])
            parsed = parse_feed(feed, raw)
            if len(parsed) < minimums[feed]:
                raise IdentityShardError(f"IDENTITY_FEED_TOO_SMALL {feed}: {len(parsed)}")
        except IdentityShardError as error:
            us_error = error
            break
        except Exception as error:  # fetch or parse failure of a required US directory
            us_error = IdentityShardError(f"IDENTITY_FEED_FAILED {feed}: {type(error).__name__}")
            break
        us_entries.append(({"id": feed, "url": FEEDS[feed], "retrieved_at": stamp, "sha256": hashlib.sha256(raw).hexdigest(),
                            "rows": len(parsed)}, parsed))
    if us_error is None:
        entries.extend(us_entries)
    else:
        if sec_cache is None:
            raise us_error
        try:
            raw, retrieved, parsed, rows_skipped = load_sec_cache(sec_cache, now, minimums["nasdaq-listed"])
        except IdentityShardError as sec_error:
            raise us_error from sec_error  # the original US error stays the reported one
        entries.append(({"id": SEC_FEED, "url": SEC_URL, "retrieved_at": retrieved.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "sha256": hashlib.sha256(raw).hexdigest(), "rows": len(parsed), "retrieval_basis": "LOCAL_CACHE_MTIME",
                         "fallback_for": list(US_FEEDS), "fallback_reason": str(us_error), "rows_skipped": rows_skipped}, parsed))
    for feed, url in FEEDS.items():
        if feed in US_FEEDS:
            continue
        try:
            raw = fetch(url)
            parsed = parse_feed(feed, raw)
            if len(parsed) < minimums[feed]:
                raise IdentityShardError(f"IDENTITY_FEED_TOO_SMALL {feed}: {len(parsed)}")
        except IdentityShardError:
            if feed in OPTIONAL_FEEDS:
                skipped.append(feed)
                continue
            raise
        except Exception as error:  # a required feed failing fails the build; the last good shards keep serving
            if feed in OPTIONAL_FEEDS:
                skipped.append(feed)
                continue
            raise IdentityShardError(f"IDENTITY_FEED_FAILED {feed}: {type(error).__name__}") from None
        entries.append(({"id": feed, "url": url, "retrieved_at": stamp, "sha256": hashlib.sha256(raw).hexdigest(),
                         "rows": len(parsed)}, parsed))
    for record, parsed in entries:
        index = len(feeds)
        feeds.append(record)
        for row in parsed:
            key = (row[1], row[0])
            zh = zh_name(row, zh_names)
            # Identity = market, country, name, native name, class, currency and the Chinese-name pair (the Worker compares the
            # same fields; the symbol is the key). A later row or feed with an equal identity adds provenance only: the first row
            # stays the representative, as before. A contradictory variant is kept after it (stable first-encounter order).
            identity = (*row[2:8], tuple(zh) if zh else None)
            kept = seen.setdefault(key, set())
            if identity in kept:
                continue
            kept.add(identity)
            records.append([*row, index, zh])
    if any(feed.get("fallback_for") for feed in feeds):
        # Old SEC content must not look fresh: the root and every shard carry the oldest main-feed retrieval time, so the
        # publisher's age check (publish_sealed_snapshot.IDENTITY_MAX_AGE) judges the cache's age, not the build time.
        stamp = min(feed["retrieved_at"] for feed in feeds)
    symbol_shards: dict[str, dict[str, Any]] = {}
    name_shards: dict[str, dict[str, Any]] = {}
    # "records" below counts retained rows (contradictory variants of one venue:symbol included), not unique listings. The sort is
    # stable, so each key's first-encountered row stays first for consumers that take the first row.
    name_rows_seen: set[tuple[str, str, str, str]] = set()
    for row in sorted(records, key=lambda item: (item[0], item[1])):
        bucket = symbol_bucket(row[0])
        symbol_shards.setdefault(bucket, {"schema": SCHEMA, "kind": "symbol", "bucket": bucket, "generated_at": stamp,
                                          "feeds": feeds, "rows": []})["rows"].append(row)
        for name in {normalize_name(row[4]), normalize_name(row[5] or ""), normalize_name(row[9][0] if row[9] else "")} - {""}:
            if (name, bucket, row[0], row[1]) in name_rows_seen:
                continue  # variants of one key share name rows; the loader reads every variant of that key anyway
            name_rows_seen.add((name, bucket, row[0], row[1]))
            name_bucket = str(fnv1a_utf16(name) % NAME_BUCKETS)
            name_shards.setdefault(name_bucket, {"schema": SCHEMA, "kind": "name", "bucket": name_bucket,
                                                 "generated_at": stamp, "rows": []})["rows"].append(
                [name, bucket, row[0], row[1]])
    return {"schema": SCHEMA, "generated_at": stamp, "feeds": feeds, "records": len(records),
            "zh_names": zh_feed, "zh_named_records": sum(1 for row in records if row[9]), "skipped_optional_feeds": skipped,
            "symbol_shards": symbol_shards, "name_shards": name_shards}


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    args = parser.parse_args(argv)
    if args.if_older_than_hours > 0 and args.output.exists():
        try:
            previous = json.loads(args.output.read_bytes().decode("utf-8"))
            stamp = previous["generated_at"]
            age = (datetime.now(timezone.utc) - datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
            current_zh = load_zh_names()[1]
            zh_changed = (current_zh or {}).get("sha256") != ((previous.get("zh_names") or {}).get("sha256"))
            previous_feeds = previous.get("feeds") if isinstance(previous.get("feeds"), list) else []
            degraded = any(isinstance(feed, dict) and feed.get("id") == SEC_FEED and feed.get("fallback_for") == list(US_FEEDS)
                           for feed in previous_feeds)  # a degraded file is never fresh: the next run retries the primary feeds
            if age < args.if_older_than_hours and not zh_changed and not degraded:
                print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age, 1)}))
                return 0
        except (OSError, ValueError, KeyError):
            pass
    try:
        document = build()
    except IdentityShardError as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}))
        return 1
    largest = max(len(dumps(shard).encode("utf-8")) for shard in
                  [*document["symbol_shards"].values(), *document["name_shards"].values()])
    if largest > 1_900_000:
        print(json.dumps({"status": "FAILED", "error": f"IDENTITY_SHARD_TOO_LARGE {largest}"}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_name(args.output.name + ".tmp")
    temp.write_bytes(dumps(document).encode("utf-8"))
    temp.replace(args.output)
    fallback = [feed for feed in document["feeds"] if feed.get("fallback_for")]
    summary = {"status": "DEGRADED_US_FALLBACK" if fallback else "OK", "records": document["records"],
               "symbol_shards": len(document["symbol_shards"]), "name_shards": len(document["name_shards"]),
               "largest_shard_bytes": largest, "feeds": {feed["id"]: feed["rows"] for feed in document["feeds"]}}
    if fallback:  # partial NASDAQ/NYSE REVIEW_REQUIRED rows from the local SEC cache, written like a normal build
        summary["fallback"] = {"feed": fallback[0]["id"], "retrieved_at": fallback[0]["retrieved_at"],
                               "retrieval_basis": fallback[0]["retrieval_basis"], "reason": fallback[0]["fallback_reason"]}
    print(json.dumps(summary))
    return 2 if fallback else 0


if __name__ == "__main__":
    sys.exit(main())
