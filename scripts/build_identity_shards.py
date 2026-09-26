#!/usr/bin/env python3
"""Global identity shards for the LINE stock lookup (contract v213-identity-shard-v2).

Reads the official listing directories and writes compact shards the Worker loads on demand (sealed as
content-addressed lazy objects; see scripts/publish_sealed_snapshot.py --identity-shards):

- US: Nasdaq Trader symbol directories (nasdaqlisted.txt, otherlisted.txt; test issues excluded);
- Taiwan: TWSE listed companies (t187ap03_L) and TPEx listed companies (mopsfin_t187ap03_O);
- Sweden: Nasdaq Nordic share screener for Stockholm Main Market and First North (public exchange web API);
- Japan: JPX list of TSE-listed issues (data_e.xlsx, read with the standard library);
- Korea: KRX KIND listed-company list (KOSPI and KOSDAQ; Korean names);
- Euronext: Paris, Amsterdam, Brussels and Milan equities (Euronext stock download).

Every row carries a Traditional Chinese name when a source states one (tenth column [name_zh, source]; null
otherwise): Taiwan rows use the exchange's own Chinese short name (source TWSE/TPEX), other markets the sourced names of
scripts/build_zh_names.py (OFFICIAL, ZHWIKI, WIKIDATA_LABEL). Nothing is translated; the Chinese name is also indexed
for name lookups.

Symbol shards are keyed by the first character of the symbol (A-Z, 0-9, _), name shards by FNV-1a(normalized name)
mod 16 (the Worker computes the same hash over UTF-16 code units). Every shard names its feeds with URL, retrieval
time and the SHA-256 of the raw download. A feed that fails keeps its previous rows out entirely (never partial); the
build fails when a required feed is missing, so the last good shards keep serving.

Usage: build_identity_shards.py [--output data/cache/identity_shards_latest.json]
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
from datetime import datetime, timezone
from pathlib import Path
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
}
EURONEXT_VENUES = {"Euronext Paris": ("EURONEXT PARIS", "France"), "Euronext Growth Paris": ("EURONEXT PARIS", "France"),
                   "Euronext Amsterdam": ("EURONEXT AMSTERDAM", "Netherlands"), "Euronext Brussels": ("EURONEXT BRUSSELS", "Belgium"),
                   "Euronext Growth Brussels": ("EURONEXT BRUSSELS", "Belgium"), "Euronext Milan": ("BORSA ITALIANA", "Italy"),
                   "Euronext Growth Milan": ("BORSA ITALIANA", "Italy")}
KRX_MARKETS = {"유가": ("KRX", "KOSPI"), "유가증권": ("KRX", "KOSPI"), "코스닥": ("KOSDAQ", "KOSDAQ")}
OTHER_US_VENUES = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
MINIMUM_ROWS = {"nasdaq-listed": 3000, "other-us-listed": 3000, "twse-listed": 800, "tpex-listed": 600,
                "nasdaq-stockholm-main": 250, "nasdaq-stockholm-first-north": 150, "jpx-listed": 3000, "krx-listed": 1500,
                "euronext-equities": 800}
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9 .\-]{0,14}$")

Fetch = Callable[[str], bytes]


class IdentityShardError(RuntimeError):
    pass


def http_get(url: str) -> bytes:
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


def build(fetch: Fetch = http_get, now: datetime | None = None, zh: tuple[dict[str, list[str]], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    zh_names, zh_feed = zh if zh is not None else load_zh_names()
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    feeds: list[dict[str, Any]] = []
    records: list[list[Any]] = []
    seen: dict[tuple[str, str], int] = {}
    for index, (feed, url) in enumerate(FEEDS.items()):
        try:
            raw = fetch(url)
            parsed = parse_feed(feed, raw)
        except Exception as error:  # a required feed failing fails the build; the last good shards keep serving
            raise IdentityShardError(f"IDENTITY_FEED_FAILED {feed}: {type(error).__name__}") from None
        if len(parsed) < MINIMUM_ROWS[feed]:
            raise IdentityShardError(f"IDENTITY_FEED_TOO_SMALL {feed}: {len(parsed)}")
        feeds.append({"id": feed, "url": url, "retrieved_at": stamp, "sha256": hashlib.sha256(raw).hexdigest(),
                      "rows": len(parsed)})
        for row in parsed:
            key = (row[1], row[0])
            if key in seen:
                continue  # first feed wins for an exact venue:symbol duplicate within one directory
            seen[key] = len(records)
            records.append([*row, index, zh_name(row, zh_names)])
    symbol_shards: dict[str, dict[str, Any]] = {}
    name_shards: dict[str, dict[str, Any]] = {}
    for row in sorted(records, key=lambda item: (item[0], item[1])):
        bucket = symbol_bucket(row[0])
        symbol_shards.setdefault(bucket, {"schema": SCHEMA, "kind": "symbol", "bucket": bucket, "generated_at": stamp,
                                          "feeds": feeds, "rows": []})["rows"].append(row)
        for name in {normalize_name(row[4]), normalize_name(row[5] or ""), normalize_name(row[9][0] if row[9] else "")} - {""}:
            name_bucket = str(fnv1a_utf16(name) % NAME_BUCKETS)
            name_shards.setdefault(name_bucket, {"schema": SCHEMA, "kind": "name", "bucket": name_bucket,
                                                 "generated_at": stamp, "rows": []})["rows"].append(
                [name, bucket, row[0], row[1]])
    return {"schema": SCHEMA, "generated_at": stamp, "feeds": feeds, "records": len(records),
            "zh_names": zh_feed, "zh_named_records": sum(1 for row in records if row[9]),
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
            if age < args.if_older_than_hours and not zh_changed:
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
    print(json.dumps({"status": "OK", "records": document["records"], "symbol_shards": len(document["symbol_shards"]),
                      "name_shards": len(document["name_shards"]), "largest_shard_bytes": largest,
                      "feeds": {feed["id"]: feed["rows"] for feed in document["feeds"]}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
