"""Offline feed responses for the lane V11 guidance tests (no network): the real response shapes of the EDGAR submissions feed, the Nasdaq
wire feed and the three official IR channel kinds, rebuilt from tests/fixtures/v11-guidance-release-feeds.json. That fixture holds the rows of
the live feeds read on 2026-10-13, reduced to the reference day onward plus the one older row each channel needs to be a complete read; dates,
titles and ids keep their raw spelling."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FEEDS_PATH = ROOT / "tests" / "fixtures" / "v11-guidance-release-feeds.json"
IR_DIR = ROOT / "tests" / "fixtures" / "ir-feeds"


def load() -> dict:
    return json.loads(FEEDS_PATH.read_text(encoding="utf-8"))


def sec_response(entry: dict) -> dict:
    rows = entry["sec"]["rows"]
    return {"filings": {"recent": {key: [r[key] for r in rows] for key in ("form", "filingDate", "items", "accessionNumber", "reportDate")}}}


def wire_response(entry: dict) -> dict:
    rows = entry["wire"]["rows"]
    return {"data": {"rows": [dict(r) for r in rows], "totalrecords": len(rows)}}


def rss_bytes(rows: list[dict]) -> bytes:
    items = "".join(f"<item><title>{r['title']}</title><link>{r['link']}</link><pubDate>{r['pubDate']}</pubDate></item>" for r in rows)
    return f'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>feed</title>{items}</channel></rss>'.encode("utf-8")


def q4_bytes(rows: list[dict], year: str) -> bytes:
    return json.dumps({"GetPressReleaseListResult": [r for r in rows if r["PressReleaseDate"].split("/")[2][:4] == year]}).encode("utf-8")


def fetchers(entry: dict):
    """(sec_fetch, wire_fetch, ir_fetch) for one issuer entry, as revenue_guidance_release_check.receipt_for takes them. A URL that is not the
    issuer's own feed raises, as an unreachable channel would."""
    cik = entry["sec"]["cik"]

    def sec_fetch(url):
        if url != f"https://data.sec.gov/submissions/CIK{cik:010d}.json":
            raise OSError("UNKNOWN_SEC_URL")
        return sec_response(entry)

    def wire_fetch(url):
        query = parse_qs(urlsplit(url).query)
        if query.get("q") != [f"symbol:{entry['wire']['symbol'].lower()}|assetclass:stocks"]:
            raise OSError("UNKNOWN_WIRE_URL")
        if query.get("offset") != ["0"]:
            return {"data": {"rows": [], "totalrecords": len(entry["wire"]["rows"])}}
        return wire_response(entry)

    def ir_fetch(url):
        ir = entry["ir"]
        if not url.startswith(ir["url"]):
            raise OSError("UNKNOWN_IR_URL")
        if ir["kind"] == "RSS":
            return rss_bytes(ir["rows"])
        if ir["kind"] == "Q4_PRESS_RELEASES":
            return q4_bytes(ir["rows"], parse_qs(urlsplit(url).query)["year"][0])
        return (IR_DIR / ir["file"]).read_bytes()

    return sec_fetch, wire_fetch, ir_fetch


def entry_copy(feeds: dict, symbol: str) -> dict:
    return copy.deepcopy(feeds["issuers"][symbol])
