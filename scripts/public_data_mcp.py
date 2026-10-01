#!/usr/bin/env python3
"""Read-only MCP server (stdio, JSON-RPC 2.0, stdlib only) over free official public data for research agents.

Operator 2026-09-26: data sources may be added as MCP servers; any API must be free. No third-party package runs here:
the protocol is newline-delimited JSON-RPC and every request goes to a fixed allowlist of official, keyless hosts.

Tools
- sec_filings           recent filings of a company (data.sec.gov submissions)
- sec_facts             latest XBRL values of us-gaap tags, default: order visibility (RPO) and revenue (data.sec.gov)
- sec_full_text_search  EDGAR full-text search (efts.sec.gov)
- sec_filing_text       one EDGAR archive document as text, optionally only the passages matching a pattern
- tw_monthly_revenue    latest monthly revenue of a TWSE or TPEx company (exchange OpenAPI, two official feeds)

SEC requires a contact in the User-Agent: SEC_CONTACT_EMAIL, else the DPAPI-protected sec-contact.local.txt named by
install-state.json is decrypted into this process only (never printed, logged or returned). Output is bounded text;
nothing here is an order or a recommendation.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "investor-public-data", "version": "1.0.0"}
ALLOWED_HOSTS = {"data.sec.gov", "efts.sec.gov", "www.sec.gov", "openapi.twse.com.tw", "www.tpex.org.tw"}
SEC_HOSTS = {"data.sec.gov", "efts.sec.gov", "www.sec.gov"}
SEC_MIN_INTERVAL = 0.15  # SEC fair access allows 10 requests per second; stay well below
MAX_TEXT = 20_000
DEFAULT_TAGS = ["RevenueRemainingPerformanceObligation", "RevenueRemainingPerformanceObligationPercentage",
                "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]
TW_FEEDS = {"TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
            "TPEX": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"}


class ToolError(Exception):
    """A caller-visible failure (bad input, source unavailable); never carries a secret."""


def _dpapi_unprotect(blob: bytes) -> str:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buffer = ctypes.create_string_buffer(blob, len(blob))  # kept referenced until the call returns
    source = Blob(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise ToolError("SEC_CONTACT_UNAVAILABLE")
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-16-le")
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def ensure_sec_contact() -> None:
    """Sets SEC_CONTACT_EMAIL for this process from the user's DPAPI file when it is not configured."""
    if os.getenv("SEC_CONTACT_EMAIL", "").strip():
        return
    try:
        state = json.loads(Path(os.environ["LOCALAPPDATA"], "InvestorIntelligence", "install-state.json").read_text(encoding="utf-8-sig"))
        text = (Path(state["user_config_root"]) / "sec-contact.local.txt").read_text(encoding="utf-8-sig").strip()
        os.environ["SEC_CONTACT_EMAIL"] = _dpapi_unprotect(bytes.fromhex(text)).strip()
    except ToolError:
        raise
    except Exception as error:
        raise ToolError("SEC_CONTACT_UNAVAILABLE") from error


_sec_lock = threading.Lock()
_sec_last = [0.0]


def _allowed(url: str) -> str:
    """The host of an allowlisted https URL without userinfo or an explicit port; ToolError otherwise."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme != "https" or host not in ALLOWED_HOSTS or parts.username is not None or port is not None or "@" in parts.netloc:
        raise ToolError(f"HOST_NOT_ALLOWED: {host[:80]}")
    return host


class _AllowlistRedirect(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to another allowlisted host, so the SEC contact headers never leave the allowlist."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 - urllib signature
        _allowed(urllib.parse.urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_AllowlistRedirect)


def http_get(url: str) -> bytes:
    host = _allowed(url)
    headers = {"Accept": "application/json, text/html;q=0.9", "User-Agent": "InvestorIntelligence public research"}
    if host in SEC_HOSTS:
        from sec_contact_headers import SecContactError, sec_identity_headers
        ensure_sec_contact()
        try:
            headers.update(sec_identity_headers("InvestorIntelligence-Research/1.0"))
        except SecContactError as error:
            raise ToolError("SEC_CONTACT_UNAVAILABLE") from error
        with _sec_lock:
            wait = SEC_MIN_INTERVAL - (time.monotonic() - _sec_last[0])
            if wait > 0:
                time.sleep(wait)
            _sec_last[0] = time.monotonic()
    try:
        with _opener.open(urllib.request.Request(url, headers=headers), timeout=60) as response:  # noqa: S310 - allowlisted
            return response.read(8_000_000)
    except ToolError:
        raise
    except Exception as error:
        raise ToolError(f"SOURCE_UNAVAILABLE: {host} {type(error).__name__}") from error


def http_json(url: str) -> Any:
    return json.loads(http_get(url).decode("utf-8-sig"))


_tickers: dict[str, dict[str, Any]] = {}


def resolve_cik(args: dict[str, Any]) -> tuple[str, str]:
    """(10-digit CIK, label) from a cik or a ticker (SEC company_tickers.json)."""
    if args.get("cik"):
        digits = re.sub(r"\D", "", str(args["cik"]))
        if not digits or len(digits) > 10:
            raise ToolError("INVALID_CIK")
        return digits.zfill(10), digits.zfill(10)
    ticker = str(args.get("ticker") or "").strip().upper().replace(".", "-")
    if not re.fullmatch(r"[A-Z0-9-]{1,10}", ticker):
        raise ToolError("TICKER_OR_CIK_REQUIRED")
    if not _tickers:
        for row in http_json("https://www.sec.gov/files/company_tickers.json").values():
            _tickers[str(row["ticker"]).upper()] = row
    row = _tickers.get(ticker)
    if not row:
        raise ToolError(f"TICKER_NOT_AN_SEC_FILER: {ticker}")
    return str(row["cik_str"]).zfill(10), f"{ticker} {row.get('title', '')}".strip()


def _limit(args: dict[str, Any], default: int, maximum: int) -> int:
    try:
        return max(1, min(maximum, int(args.get("limit", default))))
    except (TypeError, ValueError):
        return default


def sec_filings(args: dict[str, Any]) -> dict[str, Any]:
    cik, label = resolve_cik(args)
    recent = http_json(f"https://data.sec.gov/submissions/CIK{cik}.json")["filings"]["recent"]
    forms = {str(form).upper() for form in args.get("forms") or []}
    rows = []
    for index, form in enumerate(recent["form"]):
        if forms and form.upper() not in forms:
            continue
        accession = recent["accessionNumber"][index]
        document = recent["primaryDocument"][index]
        rows.append({"form": form, "filed": recent["filingDate"][index], "period": recent["reportDate"][index],
                     "accession": accession,
                     "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}"})
        if len(rows) >= _limit(args, 10, 40):
            break
    return {"company": label, "cik": cik, "source": f"https://data.sec.gov/submissions/CIK{cik}.json", "filings": rows}


def sec_facts(args: dict[str, Any]) -> dict[str, Any]:
    cik, label = resolve_cik(args)
    tags = [str(tag) for tag in (args.get("tags") or DEFAULT_TAGS)][:12]
    if not all(re.fullmatch(r"[A-Za-z0-9]{2,120}", tag) for tag in tags):
        raise ToolError("INVALID_TAG")
    facts = http_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").get("facts", {})
    per = _limit(args, 4, 12)
    out: dict[str, Any] = {}
    for tag in tags:
        concept = next((facts[taxonomy][tag] for taxonomy in ("us-gaap", "ifrs-full", "dei") if tag in facts.get(taxonomy, {})), None)
        if not concept:
            out[tag] = "NOT_REPORTED"
            continue
        values = [dict(value, unit=unit) for unit, rows in concept.get("units", {}).items() for value in rows]
        values.sort(key=lambda value: (value.get("end", ""), value.get("filed", "")), reverse=True)
        out[tag] = [{key: value.get(key) for key in ("end", "start", "val", "unit", "form", "fy", "fp", "filed", "accn")}
                    for value in values[:per]]
    return {"company": label, "cik": cik, "source": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", "facts": out}


def sec_full_text_search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not 2 <= len(query) <= 200:
        raise ToolError("QUERY_REQUIRED")
    params = {"q": query}
    if args.get("forms"):
        params["forms"] = ",".join(str(form).upper() for form in args["forms"])
    if args.get("ticker") or args.get("cik"):
        params["ciks"] = resolve_cik(args)[0]
    for key, name in (("start", "startdt"), ("end", "enddt")):
        if args.get(key):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(args[key])):
                raise ToolError("DATE_FORMAT_YYYY_MM_DD")
            params[name] = str(args[key])
            params["dateRange"] = "custom"
    url = "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(params)
    hits = []
    page = (http_json(url).get("hits") or {}).get("hits", [])  # relevance order; newest filings first here
    page.sort(key=lambda hit: str((hit.get("_source") or {}).get("file_date") or ""), reverse=True)
    for hit in page[:_limit(args, 10, 40)]:
        source = hit.get("_source", {})
        accession, _, document = str(hit.get("_id", "")).partition(":")
        cik = (source.get("ciks") or [""])[0].lstrip("0")
        hits.append({"form": source.get("form"), "filed": source.get("file_date"), "period": source.get("period_ending"),
                     "company": (source.get("display_names") or [""])[0], "accession": accession,
                     "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}" if cik and document else None})
    return {"query": query, "source": url, "hits": hits}


def _html_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style|ix:header)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t\u00a0]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def sec_filing_text(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url") or "")
    if not re.fullmatch(r"https://www\.sec\.gov/Archives/edgar/data/\d+/\d+/[A-Za-z0-9._-]+", url):
        raise ToolError("URL_MUST_BE_AN_EDGAR_ARCHIVE_DOCUMENT")
    text = _html_text(http_get(url))
    pattern = str(args.get("find") or "")
    if not pattern:
        return {"url": url, "chars": len(text), "text": text[:MAX_TEXT], "truncated": len(text) > MAX_TEXT}
    # Literal phrases separated by "|" (case-insensitive); never a caller regex, so no catastrophic backtracking.
    phrases = [phrase.strip() for phrase in pattern.split("|") if phrase.strip()]
    if not phrases or len(pattern) > 300 or len(phrases) > 10:
        raise ToolError("FIND_PHRASES_REQUIRED")
    regex = re.compile("|".join(re.escape(phrase) for phrase in phrases), re.IGNORECASE)
    try:
        context = max(50, min(1500, int(args.get("context", 400))))
    except (TypeError, ValueError):
        context = 400
    passages, used = [], 0
    for match in regex.finditer(text):
        passage = text[max(0, match.start() - context):match.end() + context]
        if used + len(passage) > MAX_TEXT or len(passages) >= 20:
            break
        passages.append({"offset": match.start(), "text": passage})
        used += len(passage)
    return {"url": url, "chars": len(text), "pattern": pattern, "passages": passages}


def tw_monthly_revenue(args: dict[str, Any]) -> dict[str, Any]:
    code = str(args.get("code") or "").strip().upper().removesuffix(".TW").removesuffix(".TWO")
    if not re.fullmatch(r"[0-9A-Z]{4,6}", code):
        raise ToolError("TAIWAN_CODE_REQUIRED")
    failures = []
    for market, url in TW_FEEDS.items():
        try:
            rows = http_json(url)
        except ToolError as error:
            failures.append(str(error))
            continue
        for row in rows:
            if str(row.get("公司代號", "")).strip() == code:
                return {"code": code, "market": market, "source": url, "row": row,
                        "note": "營收單位為新台幣千元；資料年月與出表日期為民國年"}
    if len(failures) == len(TW_FEEDS):
        raise ToolError("; ".join(failures))
    return {"code": code, "found": False, "sources": list(TW_FEEDS.values()), "unavailable_feeds": failures}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


_COMPANY = {"ticker": {"type": "string", "description": "US ticker, e.g. NVDA or BRK.B"},
            "cik": {"type": "string", "description": "SEC CIK instead of a ticker"}}
TOOLS: dict[str, tuple[Callable[[dict[str, Any]], dict[str, Any]], str, dict[str, Any]]] = {
    "sec_filings": (sec_filings, "Recent SEC filings of a company with archive URLs (data.sec.gov).",
                    _schema({**_COMPANY, "forms": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}})),
    "sec_facts": (sec_facts, "Latest XBRL values of tags (default: RPO, RPO percentage, revenue) from SEC companyfacts.",
                  _schema({**_COMPANY, "tags": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}})),
    "sec_full_text_search": (sec_full_text_search, "EDGAR full-text search (efts.sec.gov); phrases in double quotes.",
                             _schema({"query": {"type": "string"}, **_COMPANY, "forms": {"type": "array", "items": {"type": "string"}},
                                      "start": {"type": "string"}, "end": {"type": "string"}, "limit": {"type": "integer"}}, ["query"])),
    "sec_filing_text": (sec_filing_text, "Text of one EDGAR archive document; with `find` (literal phrases separated by |) only the matching passages.",
                        _schema({"url": {"type": "string"}, "find": {"type": "string"}, "context": {"type": "integer"}}, ["url"])),
    "tw_monthly_revenue": (tw_monthly_revenue, "Latest monthly revenue of a Taiwan listed (TWSE) or OTC (TPEx) company.",
                           _schema({"code": {"type": "string", "description": "e.g. 2330 or 5351"}}, ["code"])),
}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message; None for notifications."""
    method, identifier = message.get("method"), message.get("id")
    if identifier is None:
        return None
    if method == "initialize":
        requested = str((message.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION)
        result: dict[str, Any] = {"protocolVersion": requested, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO,
                                  "instructions": "Read-only official public data (SEC EDGAR, TWSE/TPEx). Cite the returned source URLs."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": name, "description": text, "inputSchema": schema} for name, (_, text, schema) in TOOLS.items()]}
    elif method == "tools/call":
        params = message.get("params") or {}
        entry = TOOLS.get(str(params.get("name")))
        if not entry:
            return {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"}}
        try:
            payload = entry[0](dict(params.get("arguments") or {}))
            result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}], "isError": False}
        except ToolError as error:
            result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
        except Exception as error:  # never leak internals beyond the error type
            result = {"content": [{"type": "text", "text": f"INTERNAL_ERROR {type(error).__name__}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            response = handle(message) if isinstance(message, dict) else {"jsonrpc": "2.0", "id": None,
                                                                           "error": {"code": -32600, "message": "batch not supported"}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
