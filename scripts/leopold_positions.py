#!/usr/bin/env python3
"""Leopold Aschenbrenner / Situational Awareness LP positions from SEC 13F-HR filings (Top20 v3 lead layer).

Reads the fund's EDGAR submissions (CIK 0002045724), takes the newest 13F-HR and the one before it, parses both
information tables and maps issuers to tickers through the SEC company-ticker list (normalized issuer names).
Output: per ticker the long value, share of the long book, change in shares versus the prior filing, and any put or
call rows, with the filing URL and period. A 13F is a quarter-end snapshot filed up to 45 days later; the filing
date and period travel with every figure, and the positions are leads, never company facts.

Usage: leopold_positions.py [--if-older-than-hours H] [--output PATH]   (SEC contact from SEC_CONTACT_EMAIL)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

CIK = "0002045724"
SUBMISSIONS = f"https://data.sec.gov/submissions/CIK{CIK}.json"
TICKERS = ROOT / "data" / "cache" / "v21" / "company_tickers_exchange.json"
OUTPUT = ROOT / "data" / "cache" / "leopold_positions_latest.json"
SUFFIXES = re.compile(r"\b(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings?|group|sa|nv|ag|se|"
                      r"class [a-z]|cl [a-z]|com|common stock|new|del|adr|ads|sponsored|the)\b")

Fetch = Callable[[str], bytes]


def sec_fetcher() -> Fetch:
    from sec_contact_headers import sec_identity_headers
    headers = sec_identity_headers()

    def fetch(url: str) -> bytes:
        time.sleep(0.15)  # SEC fair access: well under 10 requests per second
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed SEC hosts
            return response.read()
    return fetch


def normalize(name: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and "))
    return re.sub(r"\s+", " ", SUFFIXES.sub(" ", text)).strip()


def ticker_index(path: Path = TICKERS) -> dict[str, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    fields = document["fields"]
    index: dict[str, str] = {}
    for row in document["data"]:
        item = dict(zip(fields, row))
        key = normalize(str(item["name"]))
        if key and key not in index:  # first (primary) listing wins
            index[key] = str(item["ticker"])
    return index


def match_ticker(issuer: str, index: dict[str, str]) -> str | None:
    """Exact normalized name, else a unique prefix match (13F issuer names are truncated to about 28 characters)."""
    key = normalize(issuer)
    if not key:
        return None
    if key in index:
        return index[key]
    candidates = {ticker for name, ticker in index.items() if len(key) >= 6 and (name.startswith(key) or key.startswith(name + " "))}
    return next(iter(candidates)) if len(candidates) == 1 else None


def parse_info_table(raw: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    rows = []
    for node in root.iter():
        if not node.tag.endswith("infoTable"):
            continue
        get = lambda name: next((child.text or "" for child in node.iter() if child.tag.endswith(name)), "")  # noqa: E731
        rows.append({"issuer": get("nameOfIssuer").strip(), "cusip": get("cusip").strip(),
                     "value_usd": float(get("value") or 0), "shares": float(get("sshPrnamt") or 0),
                     "put_call": get("putCall").strip().upper() or None})
    return rows


def filing_table(fetch: Fetch, accession: str) -> tuple[str, list[dict[str, Any]]]:
    folder = f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{accession.replace('-', '')}/"
    index = json.loads(fetch(folder + "index.json").decode("utf-8"))
    names = [item["name"] for item in index["directory"]["item"] if item["name"].lower().endswith(".xml")
             and "primary_doc" not in item["name"].lower()]
    if not names:
        raise ValueError("LEOPOLD_INFO_TABLE_MISSING")
    url = folder + names[0]
    return url, parse_info_table(fetch(url))


def build(fetch: Fetch, index: dict[str, str], now: datetime) -> dict[str, Any]:
    submissions = json.loads(fetch(SUBMISSIONS).decode("utf-8"))
    recent = submissions["filings"]["recent"]
    filings = [(recent["accessionNumber"][i], recent["filingDate"][i], recent["reportDate"][i])
               for i, form in enumerate(recent["form"]) if form in ("13F-HR", "13F-HR/A")]
    if not filings:
        raise ValueError("LEOPOLD_NO_13F")
    latest_accession, latest_filed, latest_period = filings[0]
    latest_url, latest_rows = filing_table(fetch, latest_accession)
    prior_rows: list[dict[str, Any]] = []
    prior_meta = None
    if len(filings) > 1:
        prior_meta = filings[1]
        _, prior_rows = filing_table(fetch, prior_meta[0])
    prior_shares = {row["cusip"]: row["shares"] for row in prior_rows if not row["put_call"]}
    long_total = sum(row["value_usd"] for row in latest_rows if not row["put_call"]) or 1.0
    positions: dict[str, dict[str, Any]] = {}
    for row in latest_rows:
        ticker = match_ticker(row["issuer"], index)
        key = ticker or f"CUSIP:{row['cusip']}"
        item = positions.setdefault(key, {"ticker": ticker, "issuer": row["issuer"], "cusip": row["cusip"], "long_value_usd": 0.0,
                                          "long_shares": 0.0, "options": []})
        if row["put_call"]:
            item["options"].append({"type": row["put_call"], "value_usd": row["value_usd"], "shares": row["shares"]})
        else:
            item["long_value_usd"] += row["value_usd"]
            item["long_shares"] += row["shares"]
    for item in positions.values():
        item["long_weight"] = round(item["long_value_usd"] / long_total, 4)
        before = prior_shares.get(item["cusip"])
        item["shares_change"] = None if before is None else item["long_shares"] - before
        item["status"] = "NEW" if before is None and item["long_shares"] > 0 else "HELD"
    ranked = sorted(positions.values(), key=lambda item: -item["long_value_usd"])
    return {"schema_version": 1, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fund": "Situational Awareness LP", "cik": CIK, "authority": "LEAD_ONLY_NOT_COMPANY_FACT",
            "filing": {"accession": latest_accession, "filed": latest_filed, "period": latest_period, "url": latest_url},
            "prior_filing": None if prior_meta is None else {"accession": prior_meta[0], "filed": prior_meta[1], "period": prior_meta[2]},
            "long_book_usd": long_total, "positions": ranked,
            "caveat": "13F shows quarter-end holdings filed up to 45 days later; later trades are not visible."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        previous = json.loads(args.output.read_text(encoding="utf-8")) if args.if_older_than_hours > 0 and args.output.exists() else None
        age = (now - datetime.strptime(previous["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
    except (OSError, ValueError, KeyError, TypeError):
        age = None  # unreadable previous file: rebuild
    if age is not None and age < args.if_older_than_hours:
        print(json.dumps({"status": "SKIPPED_FRESH", "age_hours": round(age, 1)}))
        return 0
    try:
        document = build(sec_fetcher(), ticker_index(), now)
    except Exception as error:  # keep the last good file
        print(json.dumps({"status": "FAILED", "error": type(error).__name__, "detail": str(error)[:120]}))
        return 1
    temp = args.output.with_name(args.output.name + ".tmp")  # atomic: a killed run never leaves a truncated file
    temp.write_bytes(json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    temp.replace(args.output)
    print(json.dumps({"status": "OK", "filing": document["filing"]["period"],
                      "top": [(p["ticker"] or p["issuer"], p["long_weight"], p["status"]) for p in document["positions"][:12]]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
