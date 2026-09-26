#!/usr/bin/env python3
"""Traditional Chinese (Taiwan) company names for the identity shards and the Top20 (operator rule 2026-09-26: every
stock shows its correct Chinese name next to the original; no machine translation).

Nothing here translates. A name is used only when a human-edited public source states it, in this order:

1. ``config/company-zh-names-v1.json``: a company's own Chinese name, each entry with the URL that states it;
2. the Chinese Wikipedia article of the listed company, as displayed to zh-tw readers (the article's own title
   conversion rules, e.g. 英伟达 -> 輝達), found through the Wikidata listing statement (exchange + ticker, current
   listings only);
3. the Wikidata zh-tw / zh-hant label of that company.

Taiwan listings need none of this: the exchange directories are Chinese (build_identity_shards.py). A company with no
such source has no Chinese name, and the readers say so explicitly instead of inventing one. Legal-form suffixes
(股份有限公司, 有限公司, 公司) are dropped from Wikipedia titles; a candidate without a CJK ideograph is not a Chinese name.
Two different candidates for one listing are ambiguous and dropped.

Output (data/cache/zh_names_latest.json): {"schema", "generated_at", "sources", "names": {"<MARKET>:<SYMBOL>":
[name_zh, source]}} with MARKET as in the identity shards (US, JAPAN, KOREA, SWEDEN, EUROPE, UK, HK) and source one of
OFFICIAL, ZHWIKI, WIKIDATA_LABEL. Rendered titles are cached (data/cache/zh_names_titles.json, 30 days) and at most
--max-parse new titles are rendered per run, so the first fill spreads over several hourly refreshes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "cache" / "zh_names_latest.json"
TITLE_CACHE = ROOT / "data" / "cache" / "zh_names_titles.json"
OFFICIAL = ROOT / "config" / "company-zh-names-v1.json"
SCHEMA = "v213-zh-names-v1"
USER_AGENT = "InvestorIntelligence-research/1.0 (https://github.com/always7895/investor-intelligence)"
SPARQL = "https://query.wikidata.org/sparql"
ZHWIKI_API = "https://zh.wikipedia.org/w/api.php"
TITLE_TTL_SECONDS = 30 * 86400
# Wikidata exchange item -> identity-shard market. Taiwan is left out on purpose (the exchanges publish Chinese names).
EXCHANGES = {
    "Q82059": "US",        # Nasdaq
    "Q13677": "US",        # New York Stock Exchange
    "Q217475": "JAPAN",    # Tokyo Stock Exchange
    "Q495372": "KOREA",    # Korea Exchange (KOSPI)
    "Q495364": "KOREA",    # Korea Exchange (stock market)
    "Q491503": "KOREA",    # KOSDAQ
    "Q1019992": "SWEDEN",  # Nasdaq Stockholm
    "Q2385849": "EUROPE",  # Euronext Paris
    "Q478720": "EUROPE",   # Euronext Amsterdam
    "Q1146518": "EUROPE",  # Euronext Brussels
    "Q936563": "EUROPE",   # Borsa Italiana
    "Q171240": "UK",       # London Stock Exchange
    "Q496672": "HK",       # Hong Kong Stock Exchange
}
QUERY = """SELECT ?item ?ticker ?ex ?title ?tw ?hant WHERE {
  VALUES ?ex { %s }
  ?item p:P414 ?st . ?st ps:P414 ?ex ; pq:P249 ?ticker .
  FILTER NOT EXISTS { ?st pq:P582 ?ended }
  OPTIONAL { ?art schema:about ?item ; schema:isPartOf <https://zh.wikipedia.org/> ; schema:name ?title . }
  OPTIONAL { ?item rdfs:label ?tw FILTER(lang(?tw) = "zh-tw") }
  OPTIONAL { ?item rdfs:label ?hant FILTER(lang(?hant) = "zh-hant") }
}"""
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LEGAL_SUFFIX = re.compile(r"(股份有限公司|有限责任公司|有限責任公司|有限公司|有限|公司)$")
PARENTHETICAL = re.compile(r"\s*[（(][^）)]*[）)]\s*$")
TAG = re.compile(r"<[^>]+>")
SOURCES = ("OFFICIAL", "ZHWIKI", "WIKIDATA_LABEL")
IDENTITY = ROOT / "data" / "cache" / "identity_shards_latest.json"
SUFFIX_MARKET = {"TW": "TAIWAN", "TWO": "TAIWAN", "KS": "KOREA", "KQ": "KOREA", "T": "JAPAN", "ST": "SWEDEN", "PA": "EUROPE",
                 "AS": "EUROPE", "BR": "EUROPE", "MI": "EUROPE", "L": "UK", "HK": "HK"}

Fetch = Callable[[str], bytes]


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - fixed public HTTPS endpoints
        return response.read()


def clean_name(raw: str | None) -> str | None:
    """A displayable Chinese name, or None: tags and a trailing disambiguation are removed, legal-form suffixes
    dropped, and at least one CJK ideograph is required."""
    if not raw:
        return None
    name = PARENTHETICAL.sub("", TAG.sub("", raw)).strip()
    shorter = LEGAL_SUFFIX.sub("", name).strip()
    name = shorter if CJK.search(shorter) else name
    return name if CJK.search(name) and len(name) <= 40 else None


def ticker_key(market: str, ticker: str) -> str | None:
    ticker = ticker.strip().upper()
    if market == "HK":
        ticker = ticker.lstrip("0").zfill(4) if ticker.isdigit() else ticker
    return f"{market}:{ticker}" if re.fullmatch(r"[A-Z0-9][A-Z0-9 .\-]{0,14}", ticker) else None


def listings(fetch: Fetch) -> list[dict[str, str]]:
    query = QUERY % " ".join("wd:" + item for item in EXCHANGES)
    body = json.loads(fetch(SPARQL + "?format=json&query=" + urllib.parse.quote(query)).decode("utf-8"))
    rows = []
    for binding in body["results"]["bindings"]:
        rows.append({key: value["value"] for key, value in binding.items()})
    if len(rows) < 1000:
        raise RuntimeError(f"ZH_NAMES_LISTINGS_TOO_FEW {len(rows)}")
    return rows


def render_titles(titles: list[str], cache: dict[str, Any], fetch: Fetch, now: float, max_parse: int) -> int:
    """zh-tw display title per article (the article's own conversion rules); cached for TITLE_TTL_SECONDS."""
    parsed = 0
    for title in titles:
        entry = cache.get(title)
        if entry and now - entry.get("at", 0) < TITLE_TTL_SECONDS:
            continue
        if parsed >= max_parse:
            break
        url = ZHWIKI_API + "?action=parse&prop=displaytitle&format=json&formatversion=2&variant=zh-tw&page=" + urllib.parse.quote(title)
        try:
            shown = json.loads(fetch(url).decode("utf-8")).get("parse", {}).get("displaytitle")
        except Exception:  # noqa: BLE001 - one article failing keeps the previous value
            continue
        cache[title] = {"tw": TAG.sub("", shown or "").strip() or None, "at": now}
        parsed += 1
        time.sleep(0.05)
    return parsed


def load_official(path: Path = OFFICIAL) -> dict[str, list[str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    names: dict[str, list[str]] = {}
    for entry in document["names"]:
        key = ticker_key(entry["market"], entry["symbol"])
        name = clean_name(entry["name_zh"])
        if not key or not name or not str(entry.get("source_url", "")).startswith("https://"):
            raise ValueError(f"ZH_OFFICIAL_ENTRY_INVALID {entry.get('symbol')}")
        names[key] = [name, "OFFICIAL"]
    return names


def listing_key(symbol: str) -> str:
    """Identity key of a Yahoo-style symbol: 2330.TW -> TAIWAN:2330, VOLV-B.ST -> SWEDEN:VOLV B, BRK-B -> US:BRK.B."""
    base, dot, suffix = symbol.upper().rpartition(".")
    market, body = (SUFFIX_MARKET[suffix], base) if dot and suffix in SUFFIX_MARKET else ("US", symbol.upper())
    if market == "SWEDEN":
        body = body.replace("-", " ")
    elif market == "US":
        body = body.replace("-", ".")
    elif market == "HK" and body.isdigit():
        body = body.lstrip("0").zfill(4)
    return f"{market}:{body}"


def names_for(symbols: list[str], identity_path: Path | None = None, names_path: Path | None = None) -> dict[str, list[str]]:
    """{symbol: [name_zh, source]} for the symbols that have a stated Chinese name (exchange or sourced)."""
    keys = {symbol: listing_key(symbol) for symbol in symbols}
    wanted, found = set(keys.values()), {}
    try:
        document = json.loads((identity_path or IDENTITY).read_bytes().decode("utf-8"))
        for shard in document["symbol_shards"].values():
            for row in shard["rows"]:
                key = f"{row[2]}:{row[0]}"
                if key in wanted and len(row) >= 10 and row[9]:
                    found[key] = list(row[9])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    try:
        names = json.loads((names_path or OUTPUT).read_bytes().decode("utf-8"))["names"]
        for key in wanted - set(found):
            if isinstance(names.get(key), list):
                found[key] = list(names[key])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {symbol: found[key] for symbol, key in keys.items() if key in found}


def build(fetch: Fetch = http_get, now: datetime | None = None, cache: dict[str, Any] | None = None,
          max_parse: int = 400, official: dict[str, list[str]] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    cache = {} if cache is None else cache
    rows = listings(fetch)
    titles = sorted({row["title"] for row in rows if row.get("title")})
    parsed = render_titles(titles, cache, fetch, now.timestamp(), max_parse)
    candidates: dict[str, set[tuple[str, str]]] = {}
    for row in rows:
        key = ticker_key(EXCHANGES[row["ex"].rsplit("/", 1)[1]], row["ticker"])
        if not key:
            continue
        title = row.get("title")
        name = clean_name((cache.get(title) or {}).get("tw")) if title else None
        source = "ZHWIKI"
        if not name:
            name, source = clean_name(row.get("tw") or row.get("hant")), "WIKIDATA_LABEL"
        if name:
            candidates.setdefault(key, set()).add((name, source))
    names: dict[str, list[str]] = {}
    ambiguous = 0
    for key, found in candidates.items():
        best = {name for name, source in found if source == "ZHWIKI"} or {name for name, _ in found}
        if len(best) == 1:
            name = next(iter(best))
            names[key] = [name, "ZHWIKI" if (name, "ZHWIKI") in found else "WIKIDATA_LABEL"]
        else:
            ambiguous += 1
    names.update(official if official is not None else load_official())
    document = {"schema": SCHEMA, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sources": [{"id": "OFFICIAL", "url": "config/company-zh-names-v1.json"},
                            {"id": "ZHWIKI", "url": "https://zh.wikipedia.org/ (zh-tw display title)"},
                            {"id": "WIKIDATA_LABEL", "url": "https://www.wikidata.org/ (zh-tw/zh-hant label)"}],
                "stats": {"listings": len(rows), "titles": len(titles), "rendered_this_run": parsed,
                          "names": len(names), "ambiguous_dropped": ambiguous},
                "names": dict(sorted(names.items()))}
    return document, cache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    parser.add_argument("--max-parse", type=int, default=400)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        cache = json.loads(TITLE_CACHE.read_text(encoding="utf-8"))
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}
    try:
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        age = (now - datetime.strptime(previous["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
        pending = previous.get("stats", {}).get("rendered_this_run", 0) >= args.max_parse  # cache still filling
    except (OSError, ValueError, KeyError, TypeError):
        age, pending = None, False
    if age is not None and age < args.if_older_than_hours and not pending:
        print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age, 1)}))
        return 0
    try:
        document, cache = build(now=now, cache=cache, max_parse=args.max_parse)
    except Exception as error:  # noqa: BLE001 - the last good file keeps serving
        print(json.dumps({"status": "FAILED", "error": f"{type(error).__name__}: {str(error)[:160]}"}))
        return 1
    for path, value in ((TITLE_CACHE, cache), (args.output, document)):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_bytes(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        temp.replace(path)
    print(json.dumps({"status": "OK", **document["stats"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
