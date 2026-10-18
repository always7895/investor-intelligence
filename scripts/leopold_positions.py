#!/usr/bin/env python3
"""Leopold Aschenbrenner / Situational Awareness LP positions from SEC 13F-HR filings (Top20 v3 lead layer).

Reads the fund's EDGAR submissions (CIK 0002045724), takes the newest 13F-HR and the one before it, parses both
information tables and maps issuers to tickers through the SEC company-ticker list (normalized issuer names).
Output (schema 2): per ticker the long value, share of the long book, change in shares versus the prior filing, put and call
notional, the match route (CUSIP map or name), a currency factor and the newest Schedule 13D/G event filed after the period,
with the filing URL and period; 13F-HR/A amendments are merged per period. A 13F is a quarter-end snapshot filed up to 45 days later; the filing
date and period travel with every figure, and the positions are leads, never company facts.

Usage: leopold_positions.py [--if-older-than-hours H] [--output PATH]   (SEC contact from SEC_CONTACT_EMAIL)
"""
from __future__ import annotations

import argparse
import json
import math
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
CUSIP_MAP = ROOT / "config" / "leopold-cusip-map-v1.json"
REGIME_EVENTS = ROOT / "config" / "leopold-regime-events-v1.json"
OWNERSHIP_FORMS = ("SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A")
SMALL_BOOK_FACTOR = 0.25  # judgment-node multiplier (Xor 2026-10-18), no unit
RECON_FACTOR = 0.5  # judgment-node multiplier (Xor then JEV 2026-10-18): the table does not reconcile with its own cover page
FORM_34 = ("3", "3/A", "4", "4/A")
FORM_34_LIMIT = 20
OPEN_MARKET_CODES = ("P", "S")
RECON_TOLERANCE = 0.005
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
        rows.append({"issuer": get("nameOfIssuer").strip(), "cusip": get("cusip").strip().upper(),
                     "value_usd": float(get("value") or 0), "shares": float(get("sshPrnamt") or 0),
                     "put_call": get("putCall").strip().upper() or None,
                     "prn_type": get("sshPrnamtType").strip().upper() or "SH"})  # a missing type counts as shares
    return rows


def counts_as_shares(row: dict[str, Any]) -> bool:
    """Share count of a row: not an option row and not a principal amount (PRN keeps its value, never its amount as shares)."""
    return not row["put_call"] and row.get("prn_type", "SH") != "PRN"


def valid_cusip(cusip: str) -> bool:
    """9 characters; the ninth is the modulus-10 double-add-double check digit of the first eight (A=10.., * @ # = 36 37 38)."""
    cusip = (cusip or "").strip().upper()
    if len(cusip) != 9 or not cusip[8].isdigit():
        return False
    total = 0
    for i, char in enumerate(cusip[:8]):
        if char.isdigit():
            value = int(char)
        elif "A" <= char <= "Z":
            value = ord(char) - 55
        elif char in "*@#":
            value = 36 + "*@#".index(char)
        else:
            return False
        if i % 2 == 1:
            value *= 2
        total += value // 10 + value % 10
    return int(cusip[8]) == (10 - total % 10) % 10


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_cusip_map(path: Path = CUSIP_MAP) -> dict[str, dict[str, Any]]:
    entries = dict(_load_json(path)["entries"])
    for key in entries:
        if not valid_cusip(key):
            raise ValueError(f"LEOPOLD_CUSIP_MAP_INVALID: {key}")
    return entries


def load_regime_events(path: Path = REGIME_EVENTS) -> list[dict[str, Any]]:
    return list(_load_json(path)["events"])


def resolve_ticker(issuer: str, cusip: str, index: dict[str, str], cusip_map: dict[str, dict[str, Any]]) -> tuple[str | None, str]:
    """CUSIP map first (a null entry is final), then the normalized issuer name, else NONE."""
    if not valid_cusip(cusip):
        return None, "NONE"  # a failed check digit is never name-matched
    entry = cusip_map.get(cusip)
    if entry is not None:
        ticker = entry.get("ticker")
        return (ticker, "CUSIP_MAP") if ticker else (None, "NONE")
    ticker = match_ticker(issuer, index)
    return (ticker, "NAME") if ticker else (None, "NONE")


def folder_url(accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{accession.replace('-', '')}/"


def filing_table(fetch: Fetch, accession: str) -> tuple[str, list[dict[str, Any]]]:
    folder = folder_url(accession)
    index = json.loads(fetch(folder + "index.json").decode("utf-8"))
    names = [item["name"] for item in index["directory"]["item"] if item["name"].lower().endswith(".xml")
             and "primary_doc" not in item["name"].lower()]
    if not names:
        raise ValueError("LEOPOLD_INFO_TABLE_MISSING")
    url = folder + names[0]
    return url, parse_info_table(fetch(url))


def _cover_root(fetch: Fetch, accession: str) -> ET.Element | None:
    try:
        return ET.fromstring(fetch(folder_url(accession) + "primary_doc.xml"))
    except (ET.ParseError, OSError, KeyError, ValueError):
        return None


def amendment_type(fetch: Fetch, accession: str) -> str | None:
    """amendmentType of a 13F-HR/A cover page (RESTATEMENT or NEW HOLDINGS); None when absent or unreadable."""
    return _amendment_kind(_cover_root(fetch, accession))


def _amendment_kind(root: ET.Element | None) -> str | None:
    if root is None:
        return None
    for node in root.iter():
        if node.tag.endswith("amendmentType") and (node.text or "").strip():
            return " ".join((node.text or "").upper().split())
    return None


def cover_totals(root: ET.Element | None) -> dict[str, Any] | None:
    """tableEntryTotal, tableValueTotal and isConfidentialOmitted of a 13F primary_doc.xml; None when unreadable."""
    if root is None:
        return None
    found: dict[str, str] = {}
    for node in root.iter():
        name = _local(node.tag)
        if name in ("tableEntryTotal", "tableValueTotal", "isConfidentialOmitted") and name not in found:
            found[name] = (node.text or "").strip()
    entries, value = _number(found.get("tableEntryTotal")), _number(found.get("tableValueTotal"))
    return {"entries": None if entries is None else int(entries), "value": value,
            "confidential_omitted": found.get("isConfidentialOmitted", "").lower() in ("true", "1", "yes")}


def reconcile(rows: list[dict[str, Any]], cover: dict[str, Any] | None) -> dict[str, Any]:
    """One filing's own parsed table against its own cover page. RECON_MISMATCH only on a real mismatch (row count or value
    sum beyond 0.5 % of the cover total); a missing or unreadable cover is RECON_UNKNOWN, never an error."""
    if cover is None or cover["entries"] is None or not cover["value"] or cover["value"] <= 0:
        return {"entries_ok": None, "value_ok": None, "confidential_omitted": bool(cover and cover["confidential_omitted"]),
                "status": "RECON_UNKNOWN"}
    entries_ok = len(rows) == cover["entries"]
    value_ok = abs(sum(row["value_usd"] for row in rows) - cover["value"]) <= RECON_TOLERANCE * cover["value"]
    status = "RECON_MISMATCH" if not (entries_ok and value_ok) else "CONFIDENTIAL_OMITTED" if cover["confidential_omitted"] else "RECON_OK"
    return {"entries_ok": entries_ok, "value_ok": value_ok, "confidential_omitted": cover["confidential_omitted"], "status": status}


RECON_ORDER = ("RECON_MISMATCH", "RECON_UNKNOWN", "CONFIDENTIAL_OMITTED", "RECON_OK")


def worst_reconciliation(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Worst status over the filings that form the table of record."""
    if not parts:
        return {"entries_ok": None, "value_ok": None, "confidential_omitted": False, "status": "RECON_UNKNOWN"}

    def all_or_none(key: str) -> bool | None:
        values = [part[key] for part in parts]
        return None if any(value is None for value in values) else all(values)
    return {"entries_ok": all_or_none("entries_ok"), "value_ok": all_or_none("value_ok"),
            "confidential_omitted": any(part["confidential_omitted"] for part in parts),
            "status": min((part["status"] for part in parts), key=RECON_ORDER.index)}


def _row_key(row: dict[str, Any]) -> tuple[str, str | None]:
    return (row["cusip"], row["put_call"])


def period_table(fetch: Fetch, members: list[tuple[str, str, str, str]],
                 recon: list[dict[str, Any]] | None = None) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], tuple[str, str]]:
    """Table of one report period from its 13F-HR and 13F-HR/A filings (accession, filed, period, form), oldest first.

    RESTATEMENT replaces the table; NEW HOLDINGS rows join it as a union keyed by (cusip, put_call), the amended row winning.
    Returns (base url, rows, amendments, (accession, filed) of the newest filing). When recon is a list, the reconciliation of each
    filing's own table with its own cover page is collected there for the filings that form the table of record."""
    url = ""
    rows: list[dict[str, Any]] = []
    amendments: list[dict[str, Any]] = []
    have_base = False
    for accession, filed, _period, form in sorted(members, key=lambda item: (item[1], item[0])):
        table_url, table = filing_table(fetch, accession)
        root = _cover_root(fetch, accession) if recon is not None or form == "13F-HR/A" else None
        own = reconcile(table, cover_totals(root)) if recon is not None else None
        if form == "13F-HR/A":
            kind = _amendment_kind(root)
            amendments.append({"accession": accession, "filed": filed, "type": kind})
            if have_base and kind is not None and "NEW" in kind:
                amended = {_row_key(row) for row in table}
                rows = [row for row in rows if _row_key(row) not in amended] + table
                if own is not None:
                    recon.append(own)
                continue
        rows, have_base = table, True
        url = table_url
        if own is not None:
            recon[:] = [own]  # the base or a restatement is the table of record; earlier covers are superseded
    newest = max(members, key=lambda item: (item[1], item[0]))
    return url, rows, amendments, (newest[0], newest[1])


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(text: str | None) -> float | None:
    try:
        return float(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _iso_date(text: str | None) -> str | None:
    text = (text or "").strip()
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", text)
    if match:
        return f"{match.group(3)}-{match.group(1)}-{match.group(2)}"
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None


def parse_event_document(raw: bytes) -> dict[str, Any]:
    """Subject, event date, shares and percent of class of a Schedule 13D/G primary document.

    Structured XML first (the fund's own reporting-person block when present, else the largest holder); otherwise the cover
    page text. Fields that cannot be read stay None."""
    result: dict[str, Any] = {"subject": None, "cusip": None, "event_date": None, "shares": None, "percent_of_class": None}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return _parse_event_text(raw.decode("utf-8", errors="replace"), result)
    persons: list[dict[str, str]] = []
    for node in root.iter():
        name = _local(node.tag)
        text = (node.text or "").strip()
        if name in ("issuerName", "nameOfIssuer") and text and not result["subject"]:
            result["subject"] = text
        elif name in ("issuerCusipNumber", "issuerCusip", "cusip") and text and not result["cusip"]:
            result["cusip"] = text
        elif name in ("dateOfEvent", "eventDateRequiresFilingThisStatement") and text and not result["event_date"]:
            result["event_date"] = _iso_date(text)
        elif name in ("reportingPersonInfo", "coverPageHeaderReportingPersonDetails"):
            persons.append({_local(child.tag): (child.text or "").strip() for child in node.iter()})
    best = None
    for person in persons:
        shares = _number(person.get("aggregateAmountOwned") or person.get("reportingPersonBeneficiallyOwnedAggregateNumberOfShares"))
        percent = _number(person.get("percentOfClass") or person.get("classPercent"))
        own = person.get("reportingPersonCIK", "").lstrip("0") == CIK.lstrip("0")
        candidate = (own, shares or 0.0, shares, percent)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is not None:
        result["shares"], result["percent_of_class"] = best[2], best[3]
    if not persons and not result["cusip"]:  # well-formed markup without the 13D/G schema: read the cover page text
        return _parse_event_text(raw.decode("utf-8", errors="replace"), result)
    return result


def _parse_event_text(text: str, result: dict[str, Any]) -> dict[str, Any]:
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    cusip = re.search(r"CUSIP(?: No\.?| Number)?[:\s]+([0-9A-Z]{9})\b", plain, re.I)
    result["cusip"] = cusip.group(1).upper() if cusip else None
    event = re.search(r"Date of Event[^0-9]{0,80}(\d{2}/\d{2}/\d{4})", plain, re.I)
    result["event_date"] = _iso_date(event.group(1)) if event else None
    shares = re.search(r"Aggregate Amount Beneficially Owned[^0-9]{0,80}([\d,]{4,})", plain, re.I)
    result["shares"] = _number(shares.group(1)) if shares else None
    percent = re.search(r"Percent of Class[^0-9]{0,80}(\d+(?:\.\d+)?)\s*%?", plain, re.I)
    result["percent_of_class"] = _number(percent.group(1)) if percent else None
    return result


def _text(node: ET.Element, name: str) -> str:
    """Text of the first descendant called name (its own text, else its <value> child)."""
    for child in node.iter():
        if _local(child.tag) == name:
            if (child.text or "").strip():
                return child.text.strip()
            return next(((sub.text or "").strip() for sub in child if _local(sub.tag) == "value"), "")
    return ""


def parse_ownership_document(raw: bytes) -> dict[str, Any]:
    """Form 3/4 ownershipDocument: issuer symbol, reporting-owner CIKs and the non-derivative transactions (document order)."""
    root = ET.fromstring(raw)
    owners = [_text(node, "rpOwnerCik") for node in root.iter() if _local(node.tag) == "reportingOwner"]
    transactions = []
    for node in root.iter():
        if _local(node.tag) != "nonDerivativeTransaction":
            continue
        transactions.append({"date": _iso_date(_text(node, "transactionDate")), "code": _text(node, "transactionCode").upper(),
                             "shares": _number(_text(node, "transactionShares")),
                             "owned_after": _number(_text(node, "sharesOwnedFollowingTransaction")),
                             "nature": _text(node, "directOrIndirectOwnership").upper()})
    return {"symbol": _text(root, "issuerTradingSymbol").upper(), "issuer": _text(root, "issuerName"),
            "owners": [owner for owner in owners if owner], "transactions": transactions}


def _owned_by_fund(owners: list[str]) -> bool:
    for owner in owners:
        try:
            if int(owner) == int(CIK):
                return True
        except ValueError:
            continue
    return False


def form_34_event_shares(transactions: list[dict[str, Any]]) -> tuple[float | None, str | None]:
    """(shares owned after the newest open-market P or S row, its date); mixed ownership natures use the newest direct row."""
    rows = [row for row in transactions if row["code"] in OPEN_MARKET_CODES and row["owned_after"] is not None and row["date"]]
    if not rows:
        return None, None
    if len({row["nature"] for row in rows}) > 1:
        rows = [row for row in rows if row["nature"] == "D"]
        if not rows:
            return None, None
    newest = max(range(len(rows)), key=lambda i: (rows[i]["date"], i))  # ties: the later row in document order
    return rows[newest]["owned_after"], rows[newest]["date"]


def form_34_events(fetch: Fetch, recent: dict[str, list[Any]], newest_period: str, index: dict[str, str]) -> list[dict[str, Any]]:
    """Form 3/4 filings with the fund as a reporting owner, newest FORM_34_LIMIT filed after the newest 13F period end."""
    candidates = sorted(((str(recent["filingDate"][i]), recent["accessionNumber"][i], i) for i, form in enumerate(recent["form"])
                         if form in FORM_34 and str(recent["filingDate"][i]) > newest_period), reverse=True)[:FORM_34_LIMIT]
    symbols = set(index.values())
    events = []
    for filed, accession, i in candidates:
        document = (recent.get("primaryDocument") or [None] * (i + 1))[i]
        if not document:
            continue
        try:
            parsed = parse_ownership_document(fetch(folder_url(accession) + str(document).rsplit("/", 1)[-1]))
        except (ET.ParseError, OSError, KeyError, ValueError, TypeError):
            continue
        if not _owned_by_fund(parsed["owners"]):
            continue
        shares, event_date = form_34_event_shares(parsed["transactions"])
        events.append({"form": recent["form"][i], "accession": accession, "filed": filed, "event_date": event_date,
                       "subject": parsed["issuer"] or None, "cusip": None, "ticker": parsed["symbol"] if parsed["symbol"] in symbols else None,
                       "shares": shares, "percent_of_class": None})
    return events


def ownership_events(fetch: Fetch, recent: dict[str, list[Any]], newest_period: str, index: dict[str, str],
                     cusip_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Schedule 13D/13G filings made by the fund after the newest 13F period end, newest first."""
    events: list[dict[str, Any]] = []
    for i, form in enumerate(recent["form"]):
        if form not in OWNERSHIP_FORMS or str(recent["filingDate"][i]) <= newest_period:
            continue
        accession, filed = recent["accessionNumber"][i], recent["filingDate"][i]
        parsed: dict[str, Any] = {"subject": None, "cusip": None, "event_date": None, "shares": None, "percent_of_class": None}
        names = ["primary_doc.xml"]
        document = (recent.get("primaryDocument") or [None] * (i + 1))[i]
        if document:
            names.append(str(document).rsplit("/", 1)[-1])
        for name in dict.fromkeys(names):
            try:
                parsed = parse_event_document(fetch(folder_url(accession) + name))
                break
            except (OSError, KeyError, ValueError):
                continue
        entry = cusip_map.get(parsed["cusip"] or "")
        ticker = entry.get("ticker") if entry else (match_ticker(parsed["subject"], index) if parsed["subject"] else None)
        events.append({"form": form, "accession": accession, "filed": filed, "event_date": parsed["event_date"],
                       "subject": parsed["subject"], "cusip": parsed["cusip"], "ticker": ticker, "shares": parsed["shares"],
                       "percent_of_class": parsed["percent_of_class"]})
    events += form_34_events(fetch, recent, newest_period, index)
    return sorted(events, key=lambda event: (event["filed"], event["accession"]), reverse=True)


def currency(item: dict[str, Any], *, small_book: bool, regimes: list[dict[str, Any]], event: dict[str, Any] | None,
             recon_mismatch: bool = False) -> tuple[float, list[str]]:
    """Currency factor of one position and its reasons (SMALL_BOOK, REGIME_<id>, EVENT_<form>_<filed>, RECON_MISMATCH), in that order."""
    factor, reasons = 1.0, []
    if small_book:
        factor *= SMALL_BOOK_FACTOR
        reasons.append("SMALL_BOOK")
    event_date = (event or {}).get("event_date") or (event or {}).get("filed") or ""
    event_shares = (event or {}).get("shares")
    sized = event is not None and event_shares is not None and item["long_shares"] > 0
    for regime in regimes:
        if sized and event_date >= regime["date"]:
            continue  # the ownership event is dated after the regime event: it measures the position directly
        factor *= float(regime["factor"])
        reasons.append("REGIME_" + regime["id"])
    if event is not None:
        if sized:
            factor *= min(1.0, event_shares / item["long_shares"])
            reasons.append(f"EVENT_{event['form']}_{event['filed']}")
        elif event_shares is None:
            reasons.append("EVENT_SHARES_UNKNOWN")
    if recon_mismatch:
        factor *= RECON_FACTOR
        reasons.append("RECON_MISMATCH")
    return factor, reasons


def build(fetch: Fetch, index: dict[str, str], now: datetime, cusip_map: dict[str, dict[str, Any]] | None = None,
          regime_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cusip_map = load_cusip_map() if cusip_map is None else cusip_map
    regime_events = load_regime_events() if regime_events is None else regime_events
    submissions = json.loads(fetch(SUBMISSIONS).decode("utf-8"))
    recent = submissions["filings"]["recent"]
    periods: dict[str, list[tuple[str, str, str, str]]] = {}
    for i, form in enumerate(recent["form"]):
        if form in ("13F-HR", "13F-HR/A"):
            period = recent["reportDate"][i]
            periods.setdefault(period, []).append((recent["accessionNumber"][i], recent["filingDate"][i], period, form))
    if not periods:
        raise ValueError("LEOPOLD_NO_13F")
    ordered = sorted(periods, reverse=True)
    latest_period = ordered[0]
    recon: list[dict[str, Any]] = []
    latest_url, latest_rows, amendments, (latest_accession, latest_filed) = period_table(fetch, periods[latest_period], recon)
    reconciliation = worst_reconciliation(recon)
    prior_rows: list[dict[str, Any]] = []
    prior_meta = None
    if len(ordered) > 1:
        _, prior_rows, prior_amendments, newest_prior = period_table(fetch, periods[ordered[1]])
        prior_meta = (newest_prior[0], newest_prior[1], ordered[1])
        amendments = amendments + prior_amendments
    prior_shares: dict[str, float] = {}  # sum over every non-option row of a CUSIP; PRN amounts are not shares
    for row in prior_rows:
        if not row["put_call"]:
            prior_shares[row["cusip"]] = prior_shares.get(row["cusip"], 0.0) + (row["shares"] if counts_as_shares(row) else 0.0)
    invalid_cusips = sum(1 for row in latest_rows if not valid_cusip(row["cusip"]))
    long_total = sum(row["value_usd"] for row in latest_rows if not row["put_call"]) or 1.0
    prior_total = sum(row["value_usd"] for row in prior_rows if not row["put_call"])
    positions: dict[str, dict[str, Any]] = {}
    options_book = {"long_usd": sum(row["value_usd"] for row in latest_rows if not row["put_call"]),
                    "put_notional_usd": 0.0, "call_notional_usd": 0.0}
    for row in latest_rows:
        ticker, match = resolve_ticker(row["issuer"], row["cusip"], index, cusip_map)
        key = ticker or f"CUSIP:{row['cusip']}"
        item = positions.setdefault(key, {"ticker": ticker, "issuer": row["issuer"], "cusip": row["cusip"], "match": match,
                                          "cusips": [], "long_value_usd": 0.0, "long_shares": 0.0, "principal_usd": 0.0, "options": [],
                                          "put_notional_usd": 0.0, "call_notional_usd": 0.0})
        if row["cusip"] not in item["cusips"]:
            item["cusips"].append(row["cusip"])
        if row["put_call"]:
            item["options"].append({"type": row["put_call"], "value_usd": row["value_usd"], "shares": row["shares"]})
            side = "put_notional_usd" if row["put_call"] == "PUT" else "call_notional_usd"
            item[side] += row["value_usd"]  # 13F value of an option row is the underlying notional
            options_book[side] += row["value_usd"]
        else:
            item["long_value_usd"] += row["value_usd"]
            if counts_as_shares(row):
                item["long_shares"] += row["shares"]
            else:
                item["principal_usd"] += row["value_usd"]  # PRN rows keep their value, never their amount as shares
    events = ownership_events(fetch, recent, latest_period, index, cusip_map)
    applying = [event for event in regime_events if latest_period < event["superseded_by_13f_period_on_or_after"]
                and latest_period < event["date"]]
    today = now.strftime("%Y-%m-%d")
    overdue = any(today > event["review_by"] for event in applying)
    small_book = bool(prior_total) and long_total < 0.10 * prior_total
    for item in positions.values():
        item["long_weight"] = round(item["long_value_usd"] / long_total, 4)
        seen = [prior_shares[cusip] for cusip in item["cusips"] if cusip in prior_shares]
        before = sum(seen) if seen else None
        item["prior_shares"] = before
        item["shares_change"] = None if before is None else item["long_shares"] - before
        item["status"] = "NEW" if before is None and item["long_shares"] > 0 else "HELD"
        newest = next((event for event in events if event["cusip"] == item["cusip"]
                       or (item["ticker"] and event["ticker"] == item["ticker"])), None)
        item["post_period_event"] = newest
        item["currency_factor"], item["currency_reason"] = currency(item, small_book=small_book, regimes=applying, event=newest,
                                                                 recon_mismatch=reconciliation["status"] == "RECON_MISMATCH")
    ranked = sorted(positions.values(), key=lambda item: -item["long_value_usd"])
    regime = None
    if regime_events:
        shown = applying or regime_events
        regime = {"id": shown[0]["id"], "applies": bool(applying),
                  "factor": round(math.prod(float(event["factor"]) for event in applying), 6) if applying else 1.0,
                  "review_overdue": overdue}
    caveat = "13F shows quarter-end holdings filed up to 45 days later; later trades are not visible."
    if applying:
        caveat += (f" Regime event {applying[0]['id']} ({applying[0]['kind']}, {applying[0]['date']}, press reports of one lineage, "
                   f"no primary confirmation) is later than the 13F period: positions are discounted by currency_factor.")
    return {"schema_version": 2, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fund": "Situational Awareness LP", "cik": CIK, "authority": "LEAD_ONLY_NOT_COMPANY_FACT",
            "filing": {"accession": latest_accession, "filed": latest_filed, "period": latest_period, "url": latest_url,
                       "reconciliation": reconciliation, "invalid_cusips": invalid_cusips},
            "prior_filing": None if prior_meta is None else {"accession": prior_meta[0], "filed": prior_meta[1], "period": prior_meta[2]},
            "amendments": amendments, "long_book_usd": long_total, "options_book": options_book, "positions": ranked,
            "events": events, "regime": regime, "regime_review_overdue": overdue, "caveat": caveat}


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
