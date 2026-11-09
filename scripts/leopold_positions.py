#!/usr/bin/env python3
"""Leopold Aschenbrenner / Situational Awareness LP positions from SEC 13F-HR filings (Top20 v3 lead layer).

Reads the fund's EDGAR submissions (CIK 0002045724), takes the newest 13F-HR and the one before it, parses both
information tables and maps issuers to tickers through the SEC company-ticker list (normalized issuer names).
Output (schema 2): per ticker the long value, share of the long book, change in shares versus the prior filing, put and call
notional, the match route (CUSIP map or name), a currency factor and the newest Schedule 13D/G event filed after the period,
with the filing URL and period; RESTATEMENT replaces one period, while NEW HOLDINGS adds reported entries to that period.
The filing date and quarter end are distinct; the positions are leads, never company facts.

Usage: leopold_positions.py [--if-older-than-hours H] [--output PATH]   (SEC contact from SEC_CONTACT_EMAIL)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

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
STALE_13F_DAYS = 200  # same age gate as the ranking; represented separately, never double-discounted
MAX_SEC_BYTES = 24 * 1024 * 1024
SUFFIXES = re.compile(r"\b(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings?|group|sa|nv|ag|se|"
                      r"class [a-z]|cl [a-z]|com|common stock|new|del|adr|ads|sponsored|the)\b")

Fetch = Callable[[str], bytes]


def sec_fetcher() -> Fetch:
    from sec_contact_headers import sec_identity_headers
    headers = sec_identity_headers()
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("LEOPOLD_SEC_REDIRECT_REFUSED")
    opener = urllib.request.build_opener(NoRedirect)
    def fetch(url: str) -> bytes:
        parsed = urlparse(url)
        allowed = (parsed.hostname == "data.sec.gov" and parsed.path.startswith("/submissions/")) or (
            parsed.hostname == "www.sec.gov" and parsed.path.startswith(f"/Archives/edgar/data/{int(CIK)}/"))
        if (parsed.scheme != "https" or not allowed or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.query or parsed.fragment):
            raise ValueError("LEOPOLD_SEC_URL_REFUSED")
        time.sleep(0.15)
        with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as response:
            raw = response.read(MAX_SEC_BYTES + 1)
        if len(raw) > MAX_SEC_BYTES:
            raise ValueError("LEOPOLD_SEC_PAYLOAD_LIMIT")
        return raw
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
        value, shares = float(get("value")), float(get("sshPrnamt"))
        put_call = get("putCall").strip().upper() or None
        prn_type = get("sshPrnamtType").strip().upper() or "SH"
        if (not all(math.isfinite(number) and number >= 0 for number in (value, shares))
                or put_call not in (None, "PUT", "CALL") or prn_type not in ("SH", "PRN")):
            raise ValueError("LEOPOLD_TABLE_ROW_INVALID")
        rows.append({"issuer": get("nameOfIssuer").strip(), "cusip": get("cusip").strip().upper(),
                     "value_usd": value, "shares": shares, "put_call": put_call, "prn_type": prn_type})
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
    if not isinstance(accession, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ValueError("LEOPOLD_ACCESSION_INVALID")
    return f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{accession.replace('-', '')}/"


def filing_table(fetch: Fetch, accession: str) -> tuple[str, list[dict[str, Any]]]:
    folder = folder_url(accession)
    index = json.loads(fetch(folder + "index.json").decode("utf-8"))
    names = [item["name"] for item in index["directory"]["item"]
             if isinstance(item.get("name"), str) and re.fullmatch(r"[A-Za-z0-9._-]+\.xml", item["name"], re.I)
             and "primary_doc" not in item["name"].lower()]
    matches = []
    for name in names:
        url = folder + name
        raw = fetch(url)
        root = ET.fromstring(raw)
        if _local(root.tag) == "informationTable":
            matches.append((url, parse_info_table(raw)))
    if len(matches) != 1:
        raise ValueError("LEOPOLD_INFO_TABLE_MISSING_OR_AMBIGUOUS")
    return matches[0]


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
    if (cover is None or cover["entries"] is None or cover["value"] is None or cover["value"] < 0
            or (cover["value"] == 0 and cover["entries"] != 0)):
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




def period_table(fetch: Fetch, members: list[tuple[str, str, str, str]],
                 recon: list[dict[str, Any]] | None = None, *,
                 acceptance_times: dict[str, str] | None = None) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], tuple[str, str]]:
    """Compose exactly one report period, in publication order.

    RESTATEMENT replaces all entries; NEW HOLDINGS adds rows without deleting
    pre-existing entries, including distinct lots/managers of the same CUSIP.
    An untyped amendment or a NEW HOLDINGS filing without its base fails closed.
    """
    if not members or len({member[2] for member in members}) != 1:
        raise ValueError("LEOPOLD_MIXED_OR_EMPTY_PERIOD")
    times = {}
    for accession, raw_time in (acceptance_times or {}).items():
        if not raw_time:
            continue
        accepted = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if accepted.tzinfo is None:
            raise ValueError("LEOPOLD_ACCEPTANCE_TIME_UNVERIFIED")
        times[accession] = accepted.astimezone(timezone.utc)
    amendment_days: dict[str, list[str]] = {}
    for accession, filed, _, form in members:
        if form == "13F-HR/A":
            amendment_days.setdefault(filed, []).append(accession)
    for accessions in amendment_days.values():
        if len(accessions) > 1 and (any(accession not in times for accession in accessions)
                                   or len({times[accession] for accession in accessions}) != len(accessions)):
            raise ValueError("LEOPOLD_AMENDMENT_ORDER_UNKNOWN")
    floor = datetime.min.replace(tzinfo=timezone.utc)
    ordered_members = sorted(members, key=lambda item: (item[1], times.get(item[0], floor),
                                                       item[3] == "13F-HR/A", item[0]))
    url = ""
    rows: list[dict[str, Any]] = []
    amendments: list[dict[str, Any]] = []
    have_base = False
    for accession, filed, _period, form in ordered_members:
        table_url, table = filing_table(fetch, accession)
        root = _cover_root(fetch, accession)
        if root is not None:
            cover_period = next(((node.text or "").strip() for node in root.iter()
                                 if _local(node.tag) in ("reportCalendarOrQuarter", "periodOfReport")), None)
            if cover_period is not None and _iso_date(cover_period) != _period:
                raise ValueError("LEOPOLD_COVER_PERIOD_MISMATCH")
        own = reconcile(table, cover_totals(root)) if recon is not None else None
        if form == "13F-HR/A":
            kind = _amendment_kind(root)
            amendments.append({"accession": accession, "filed": filed, "period": _period, "type": kind})
            if kind not in ("NEW HOLDINGS", "RESTATEMENT"):
                raise ValueError("LEOPOLD_AMENDMENT_TYPE_UNKNOWN")
            if kind == "NEW HOLDINGS":
                if not have_base:
                    raise ValueError("LEOPOLD_AMENDMENT_BASE_MISSING")
                rows.extend(table)
                url = table_url
                if own is not None:
                    recon.append(own)
                continue
        elif form != "13F-HR" or have_base:
            raise ValueError("LEOPOLD_DUPLICATE_OR_INVALID_BASE")
        rows, have_base = table, True
        url = table_url
        if own is not None:
            recon[:] = [own]  # the base or a restatement is the table of record; earlier covers are superseded
    newest = ordered_members[-1]
    return url, rows, amendments, (newest[0], newest[1])


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(text: str | None) -> float | None:
    try:
        value = float(str(text).replace(",", "").strip())
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def _iso_date(text: str | None) -> str | None:
    text = (text or "").strip()
    match = re.fullmatch(r"(\d{2})[/-](\d{2})[/-](\d{4})", text)
    if match:
        text = f"{match.group(3)}-{match.group(1)}-{match.group(2)}"
    try:
        return date.fromisoformat(text).isoformat() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None
    except ValueError:
        return None


def parse_event_document(raw: bytes) -> dict[str, Any]:
    """Subject, event date, shares and percent of class of a Schedule 13D/G primary document.

    Structured XML uses only the fund's identified reporting-person block, never
    the largest unrelated holder. Unstructured cover text is parsed as an
    unverified lead and cannot override a position without owner verification."""
    result: dict[str, Any] = {"subject": None, "cusip": None, "event_date": None,
                              "shares": None, "percent_of_class": None, "reporting_owner_verified": False}
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
    own_persons = [person for person in persons
                   if person.get("reportingPersonCIK", "").lstrip("0") == CIK.lstrip("0")]
    if len(own_persons) == 1:
        person = own_persons[0]
        result["shares"] = _number(person.get("aggregateAmountOwned") or person.get("reportingPersonBeneficiallyOwnedAggregateNumberOfShares"))
        result["percent_of_class"] = _number(person.get("percentOfClass") or person.get("classPercent"))
        result["reporting_owner_verified"] = True
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


def form_34_events(fetch: Fetch, recent: dict[str, list[Any]], newest_period: str, index: dict[str, str],
                   issues: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Public fund-owned Form 3/4 reports; unavailable documents remain explicit coverage gaps."""
    candidates = sorted(((str(recent["filingDate"][i]), recent["accessionNumber"][i], i) for i, form in enumerate(recent["form"])
                         if form in FORM_34 and str(recent["filingDate"][i]) > newest_period), reverse=True)
    if len(candidates) > FORM_34_LIMIT and issues is not None:
        issues.append({"status": "FORM4_WINDOW_TRUNCATED", "reason_zh": "公開持股異動超過單次讀取上限，不能宣稱完整更新。"})
    candidates = candidates[:FORM_34_LIMIT]
    symbols = set(index.values())
    events = []
    for filed, accession, i in candidates:
        document = (recent.get("primaryDocument") or [None] * (i + 1))[i]
        if not document:
            if issues is not None:
                issues.append({"form": recent["form"][i], "filed": filed, "status": "DOCUMENT_UNAVAILABLE",
                               "reason_zh": "公開持股異動缺原始文件；不能視為沒有異動。"})
            continue
        try:
            parsed = parse_ownership_document(fetch(folder_url(accession) + str(document).rsplit("/", 1)[-1]))
        except (ET.ParseError, OSError, KeyError, ValueError, TypeError):
            if issues is not None:
                issues.append({"form": recent["form"][i], "filed": filed, "status": "DOCUMENT_UNAVAILABLE",
                               "reason_zh": "公開持股異動原文無法讀取或解析；保留未驗證。"})
            continue
        if not _owned_by_fund(parsed["owners"]):
            continue
        shares, event_date = form_34_event_shares(parsed["transactions"])
        events.append({"form": recent["form"][i], "accession": accession, "filed": filed, "event_date": event_date,
                       "subject": parsed["issuer"] or None, "cusip": None, "ticker": parsed["symbol"] if parsed["symbol"] in symbols else None,
                       "shares": shares, "percent_of_class": None, "source_url": folder_url(accession) + str(document).rsplit("/", 1)[-1],
                       "reporting_owner_verified": True})
    return events


def ownership_events(fetch: Fetch, recent: dict[str, list[Any]], newest_period: str, index: dict[str, str],
                     cusip_map: dict[str, dict[str, Any]], issues: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
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
        source_url = None
        for name in dict.fromkeys(names):
            try:
                parsed = parse_event_document(fetch(folder_url(accession) + name))
                source_url = folder_url(accession) + name
                break
            except (OSError, KeyError, ValueError):
                continue
        if source_url is None and issues is not None:
            issues.append({"form": form, "filed": filed, "status": "DOCUMENT_UNAVAILABLE",
                           "reason_zh": "公開 13D／G 原文無法取得；不能宣稱完整更新。"})
        if not parsed.get("reporting_owner_verified"):
            parsed["shares"], parsed["percent_of_class"] = None, None
            if source_url is not None and issues is not None:
                issues.append({"form": form, "filed": filed, "status": "OWNER_IDENTITY_UNVERIFIED",
                               "reason_zh": "未能從原文確認基金申報人身分，不採用其他申報人的持股數。"})
        entry = cusip_map.get(parsed["cusip"] or "")
        ticker = entry.get("ticker") if entry else (match_ticker(parsed["subject"], index) if parsed["subject"] else None)
        events.append({"form": form, "accession": accession, "filed": filed, "event_date": parsed["event_date"],
                       "subject": parsed["subject"], "cusip": parsed["cusip"], "ticker": ticker, "shares": parsed["shares"],
                       "percent_of_class": parsed["percent_of_class"], "source_url": source_url,
                       "reporting_owner_verified": parsed.get("reporting_owner_verified", False)})
    events += form_34_events(fetch, recent, newest_period, index, issues)
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


def _validated_recent(raw: Any) -> dict[str, list[Any]]:
    keys = ("form", "accessionNumber", "filingDate", "reportDate")
    if (not isinstance(raw, dict) or not all(isinstance(raw.get(key), list) for key in keys)
            or len({len(raw[key]) for key in keys}) != 1):
        raise ValueError("LEOPOLD_SUBMISSION_SHAPE")
    result = {key: list(raw[key]) for key in keys}
    primary = raw.get("primaryDocument", [""] * len(result["form"]))
    if not isinstance(primary, list) or len(primary) != len(result["form"]):
        raise ValueError("LEOPOLD_SUBMISSION_LENGTH")
    result["primaryDocument"] = list(primary)
    accepted = raw.get("acceptanceDateTime", [""] * len(result["form"]))
    if not isinstance(accepted, list) or len(accepted) != len(result["form"]) or not all(isinstance(value, str) for value in accepted):
        raise ValueError("LEOPOLD_ACCEPTANCE_TIME_SHAPE")
    result["acceptanceDateTime"] = list(accepted)
    return result


def _report_periods(recent: dict[str, list[Any]], today: date) -> dict[str, list[tuple[str, str, str, str]]]:
    periods: dict[str, list[tuple[str, str, str, str]]] = {}
    seen = {}
    for i, form in enumerate(recent["form"]):
        filed = _iso_date(recent["filingDate"][i])
        if filed is None:
            raise ValueError("LEOPOLD_FILING_DATE_INVALID")
        if date.fromisoformat(filed) > today:
            continue
        if form not in ("13F-HR", "13F-HR/A"):
            continue
        period = _iso_date(recent["reportDate"][i])
        if (period is None or period[5:] not in ("03-31", "06-30", "09-30", "12-31")
                or period > filed):
            raise ValueError("LEOPOLD_REPORT_PERIOD_INVALID")
        accession = recent["accessionNumber"][i]
        folder_url(accession)
        member = (accession, filed, period, form)
        if accession in seen:
            if seen[accession] != member:
                raise ValueError("LEOPOLD_ACCESSION_CONFLICT")
            continue
        seen[accession] = member
        periods.setdefault(period, []).append(member)
    return periods


def stale_quarter(period: str, now: datetime) -> dict[str, Any]:
    """Expose the existing 200-day ranking discount, without changing or stacking score weights."""
    age = (now.date() - date.fromisoformat(period)).days
    stale = age > STALE_13F_DAYS
    return {"period": period, "age_days": age, "threshold_days": STALE_13F_DAYS,
            "factor": 0.0 if stale else 1.0, "status": "STALE_QUARTER" if stale else "LAGGED_QUARTER_END",
            "applied_by": "RANKING_AGE_GATE",
            "reason_zh": "申報季末超過 200 天，投資線索權重歸零。" if stale else "13F 僅代表申報季末部位，並非即時持股。"}


def build(fetch: Fetch, index: dict[str, str], now: datetime, cusip_map: dict[str, dict[str, Any]] | None = None,
          regime_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cusip_map = load_cusip_map() if cusip_map is None else cusip_map
    regime_events = load_regime_events() if regime_events is None else regime_events
    submissions_bytes = fetch(SUBMISSIONS)
    submissions = json.loads(submissions_bytes.decode("utf-8"))
    if submissions.get("cik") is not None and int(submissions["cik"]) != int(CIK):
        raise ValueError("LEOPOLD_FUND_IDENTITY_MISMATCH")
    recent = _validated_recent(submissions["filings"]["recent"])
    periods = _report_periods(recent, now.date())
    newest = sorted(periods, reverse=True)[:2]
    needs_history = len(newest) < 2 or any(
        not any(member[3] == "13F-HR" for member in periods[period]) for period in newest)
    archives = submissions["filings"].get("files", []) if needs_history else []
    if not isinstance(archives, list) or len(archives) > 8:
        raise ValueError("LEOPOLD_HISTORY_WINDOW_UNVERIFIED")
    for archive in archives:
        name = archive.get("name", "")
        if not re.fullmatch(r"CIK\d{10}-submissions-\d+\.json", name) or not name.startswith(f"CIK{CIK}-"):
            raise ValueError("LEOPOLD_HISTORY_SOURCE_INVALID")
        older = _validated_recent(json.loads(fetch("https://data.sec.gov/submissions/" + name)))
        for key in recent:
            recent[key].extend(older[key])
    periods = _report_periods(recent, now.date())
    eligible = [i for i, filed in enumerate(recent["filingDate"]) if date.fromisoformat(filed) <= now.date()]
    recent = {key: [values[i] for i in eligible] for key, values in recent.items()}
    acceptance_times = dict(zip(recent["accessionNumber"], recent["acceptanceDateTime"]))
    if not periods:
        raise ValueError("LEOPOLD_NO_13F")
    ordered = sorted(periods, reverse=True)
    latest_period = ordered[0]
    recon: list[dict[str, Any]] = []
    latest_url, latest_rows, amendments, (latest_accession, latest_filed) = period_table(
        fetch, periods[latest_period], recon, acceptance_times=acceptance_times)
    reconciliation = worst_reconciliation(recon)
    prior_recon: list[dict[str, Any]] = []
    prior_rows: list[dict[str, Any]] = []
    prior_meta = None
    if len(ordered) > 1:
        _, prior_rows, prior_amendments, newest_prior = period_table(
            fetch, periods[ordered[1]], prior_recon, acceptance_times=acceptance_times)
        prior_meta = (newest_prior[0], newest_prior[1], ordered[1])
        amendments = amendments + prior_amendments
    prior_shares: dict[str, float] = {}  # sum over every non-option row of a CUSIP; PRN amounts are not shares
    for row in prior_rows:
        if not row["put_call"]:
            prior_shares[row["cusip"]] = prior_shares.get(row["cusip"], 0.0) + (row["shares"] if counts_as_shares(row) else 0.0)
    invalid_cusips = sum(1 for row in latest_rows if not valid_cusip(row["cusip"]))
    long_total = sum(row["value_usd"] for row in latest_rows if not row["put_call"])
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
    issues: list[dict[str, Any]] = []
    if prior_meta is not None and worst_reconciliation(prior_recon)["status"] != "RECON_OK":
        issues.append({"status": "PRIOR_QUARTER_UNVERIFIED", "reason_zh": "前季比較基準未完整核對；不能將持股變動標為完整更新。"})
    events = ownership_events(fetch, recent, latest_period, index, cusip_map, issues)
    quarter = stale_quarter(latest_period, now)
    applying = [event for event in regime_events if latest_period < event["superseded_by_13f_period_on_or_after"]
                and latest_period < event["date"]]
    today = now.strftime("%Y-%m-%d")
    for event in events:
        if event.get("event_date") and event["event_date"] > event["filed"]:
            issues.append({"form": event["form"], "filed": event["filed"], "status": "EVENT_DATE_UNVERIFIED",
                           "reason_zh": "持股異動日期晚於申報日期，未核實前不覆寫季末部位線索。"})
    overdue = any(today > event["review_by"] for event in applying)
    small_book = bool(prior_total) and long_total < 0.10 * prior_total
    for item in positions.values():
        item["long_weight"] = round(item["long_value_usd"] / long_total, 4) if long_total else 0.0
        item["stale_quarter_factor"] = quarter["factor"]
        seen = [prior_shares[cusip] for cusip in item["cusips"] if cusip in prior_shares]
        before = sum(seen) if seen else None
        item["prior_shares"] = before
        item["shares_change"] = None if before is None else item["long_shares"] - before
        item["status"] = ("UNKNOWN_PRIOR" if prior_meta is None else
                          "NEW" if before is None and item["long_shares"] > 0 else "HELD")
        newest = next((event for event in events
                       if (event["cusip"] == item["cusip"] or (item["ticker"] and event["ticker"] == item["ticker"]))
                       and (event.get("event_date") is None or latest_period < event["event_date"] <= event["filed"])), None)
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
    if reconciliation["status"] in ("RECON_UNKNOWN", "RECON_MISMATCH", "CONFIDENTIAL_OMITTED"):
        issues.append({"status": reconciliation["status"], "reason_zh": "申報表核對未完整通過或含保密省略，不可宣稱完整持股更新。"})
    if invalid_cusips:
        issues.append({"status": "ISSUER_IDENTITY_UNVERIFIED", "reason_zh": "部分申報證券識別碼無法核實，不能自動建立股票身分。"})
    return {"schema_version": 2, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "submissions_sha256": hashlib.sha256(submissions_bytes).hexdigest(),
            "refresh_status": "PARTIAL" if issues else "COMPLETE",
            "freshness_status": "NOT_FULLY_VERIFIED" if issues else "VERIFIED_QUARTER_END_ONLY",
            "source_issues": issues, "stale_quarter": quarter,
            "fund": "Situational Awareness LP", "cik": CIK, "authority": "LEAD_ONLY_NOT_COMPANY_FACT",
            "filing": {"accession": latest_accession, "filed": latest_filed, "period": latest_period, "url": latest_url,
                       "reconciliation": reconciliation, "invalid_cusips": invalid_cusips},
            "prior_filing": None if prior_meta is None else {"accession": prior_meta[0], "filed": prior_meta[1], "period": prior_meta[2],
                                                           "reconciliation": worst_reconciliation(prior_recon)},
            "amendments": amendments, "long_book_usd": long_total, "options_book": options_book, "positions": ranked,
            "events": events, "regime": regime, "regime_review_overdue": overdue, "caveat": caveat}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    previous = None
    try:
        previous = json.loads(args.output.read_text(encoding="utf-8")) if args.if_older_than_hours > 0 and args.output.exists() else None
        age = (now - datetime.strptime(previous["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
    except (OSError, ValueError, KeyError, TypeError):
        age = None  # unreadable previous file: rebuild
    try:
        remote_fetch = sec_fetcher()
        submissions_bytes = remote_fetch(SUBMISSIONS)  # always poll the publication head, even inside the age window
        unchanged = previous and previous.get("submissions_sha256") == hashlib.sha256(submissions_bytes).hexdigest()
        if (age is not None and 0 <= age < args.if_older_than_hours and unchanged
                and previous.get("refresh_status") == "COMPLETE"):
            print(json.dumps({"status": "UNCHANGED_QUARTER_END", "age_hours": round(age, 1)}))
            return 0
        def fetch(url: str) -> bytes:
            return submissions_bytes if url == SUBMISSIONS else remote_fetch(url)
        document = build(fetch, ticker_index(), now)
    except Exception as error:  # keep the last good file
        print(json.dumps({"status": "FAILED", "error": type(error).__name__,
                          "reason_zh": "免費 SEC 原始資料無法完整核實；保留上次結果，不更新其時效。"}, ensure_ascii=False))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_name(args.output.name + ".tmp")  # atomic: a killed run never leaves a truncated file
    temp.write_bytes(json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    temp.replace(args.output)
    print(json.dumps({"status": document["refresh_status"], "filing": document["filing"]["period"],
                      "source_issue_count": len(document["source_issues"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
