#!/usr/bin/env python3
"""Owner-only local LLM gateway with bounded multi-source public enrichment.

The gateway binds to loopback and is intended to sit behind a Cloudflare Tunnel.
The public tunnel never reaches llama.cpp directly: requests must carry the
shared-secret header and the gateway forwards only to a loopback llama.cpp
OpenAI-compatible endpoint.

For explicit stock symbols, public evidence is gathered independently from SEC,
Yahoo/yfinance, GLEIF, BLS and World Bank. A failed source remains an explicit
failed source; it is never silently converted into a fact. Option questions may
also add a bounded public yfinance option observation, without portfolio or
brokerage context.
"""
from __future__ import annotations

import argparse
import hmac
import json
import math
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import requests

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

HOST = "127.0.0.1"
PORT = 8814
MAX_BODY = 256_000
MAX_CONTEXT_CHARS = 24_000
TICKER_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])\$?([A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,4})?)(?=$|[^A-Za-z0-9])"
)
IGNORED = {
    "AI", "LINE", "BOT", "TOP", "CALL", "PUT", "SELL", "BUY", "OPTION",
    "OPTIONS", "BID", "ASK", "DTE", "IV", "YES", "NO", "USD", "CAGR",
}
OPTION_RE = re.compile(
    r"(?:選擇權|选择权|期權|期权|option|covered\s*call|sell\s*call|sell\s*put|cash\s*secured\s*put|\bbid\b|\bask\b)",
    re.I,
)
CACHE_ROOT = (
    Path(os.getenv("LOCALAPPDATA", str(Path.home())))
    / "InvestorIntelligence" / "UserData" / "v212-local-llm-cache"
)
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


@dataclass
class SourceResult:
    source_id: str
    ok: bool
    retrieved_at: str
    summary: dict[str, Any]
    error: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact(value: Any, limit: int = MAX_CONTEXT_CHARS) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)[:limit]


def safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def extract_ticker(text: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    for match in TICKER_RE.finditer(normalized):
        value = str(match.group(1) or "").upper()
        if value and value not in IGNORED:
            return value
    return None


def asks_options(text: str) -> bool:
    return bool(OPTION_RE.search(unicodedata.normalize("NFKC", str(text or ""))))


def _cache_json(name: str, ttl_seconds: int, loader: Callable[[], Any]) -> Any:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:100]
    path = CACHE_ROOT / f"{safe}.json"
    if path.is_file() and time.time() - path.stat().st_mtime <= ttl_seconds:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    value = loader()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return value


def sec_headers() -> dict[str, str]:
    contact = os.getenv("SEC_CONTACT_EMAIL", "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact):
        raise RuntimeError("SEC_CONTACT_EMAIL_NOT_CONFIGURED")
    return {
        "User-Agent": f"Investor Intelligence/2.1.2 local-research {contact}",
        "From": contact,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }


def sec_reference() -> dict[str, dict[str, Any]]:
    def load() -> Any:
        response = requests.get(
            "https://www.sec.gov/files/company_tickers_exchange.json",
            headers=sec_headers(), timeout=(10, 40),
        )
        response.raise_for_status()
        return response.json()
    raw = _cache_json("sec-company-tickers-exchange", 6 * 3600, load)
    fields = raw.get("fields") if isinstance(raw, dict) else None
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(fields, list) or not isinstance(data, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in data:
        if not isinstance(row, list) or len(row) != len(fields):
            continue
        item = dict(zip(fields, row))
        ticker = str(item.get("ticker") or "").upper()
        cik = item.get("cik")
        if ticker and cik is not None:
            result[ticker] = {
                "ticker": ticker,
                "name": str(item.get("name") or ticker),
                "exchange": str(item.get("exchange") or ""),
                "cik": int(cik),
            }
    return result


def collect_sec(ticker: str) -> SourceResult:
    retrieved = now_iso()
    try:
        reference = sec_reference().get(ticker)
        if not reference:
            return SourceResult("sec_edgar", False, retrieved, {}, "TICKER_NOT_IN_SEC_REFERENCE")
        cik = int(reference["cik"])
        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        facts_response = requests.get(facts_url, headers=sec_headers(), timeout=(10, 45))
        facts_response.raise_for_status()
        payload = facts_response.json()
        facts = payload.get("facts") if isinstance(payload, dict) else {}
        us_gaap = facts.get("us-gaap") if isinstance(facts, dict) else {}
        selected: dict[str, Any] = {}
        for tag in (
            "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "GrossProfit", "OperatingIncomeLoss", "NetIncomeLoss", "ProfitLoss",
            "StockholdersEquity", "LongTermDebtNoncurrent",
        ):
            raw = us_gaap.get(tag) if isinstance(us_gaap, dict) else None
            units = raw.get("units") if isinstance(raw, dict) else None
            candidates: list[dict[str, Any]] = []
            if isinstance(units, dict):
                for records in units.values():
                    if isinstance(records, list):
                        candidates.extend(item for item in records if isinstance(item, dict))
            candidates.sort(key=lambda item: str(item.get("end") or ""), reverse=True)
            if candidates:
                item = candidates[0]
                selected[tag] = {
                    "value": item.get("val"), "end": item.get("end"),
                    "form": item.get("form"), "accn": item.get("accn"),
                }
        recent_filings: list[dict[str, Any]] = []
        try:
            response = requests.get(submissions_url, headers=sec_headers(), timeout=(10, 35))
            response.raise_for_status()
            submissions = response.json()
            recent = submissions.get("filings", {}).get("recent", {}) if isinstance(submissions, dict) else {}
            forms = recent.get("form", []) if isinstance(recent, dict) else []
            accessions = recent.get("accessionNumber", []) if isinstance(recent, dict) else []
            filing_dates = recent.get("filingDate", []) if isinstance(recent, dict) else []
            primary_docs = recent.get("primaryDocument", []) if isinstance(recent, dict) else []
            for index, form in enumerate(forms[:40] if isinstance(forms, list) else []):
                if str(form) not in {"10-K", "10-Q", "8-K", "20-F", "6-K"}:
                    continue
                accession = str(accessions[index]) if index < len(accessions) else ""
                no_dash = accession.replace("-", "")
                doc = str(primary_docs[index]) if index < len(primary_docs) else ""
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{no_dash}/{doc}" if no_dash and doc else submissions_url
                recent_filings.append({
                    "form": str(form),
                    "filing_date": str(filing_dates[index]) if index < len(filing_dates) else None,
                    "accession": accession, "url": filing_url,
                })
                if len(recent_filings) >= 8:
                    break
        except Exception:
            pass
        return SourceResult(
            "sec_edgar", True, retrieved,
            {
                "ticker": ticker,
                "company": payload.get("entityName") or reference["name"],
                "exchange": reference["exchange"], "cik": cik,
                "companyfacts_url": facts_url,
                "latest_selected_us_gaap_facts": selected,
                "recent_material_filings": recent_filings,
            },
        )
    except Exception as exc:
        return SourceResult("sec_edgar", False, retrieved, {}, type(exc).__name__)


def resolve_yahoo_symbol(ticker: str) -> str:
    if yf is None:
        return ticker
    try:
        search = yf.Search(ticker, max_results=10)
        quotes = getattr(search, "quotes", None)
        if isinstance(quotes, list):
            exact = [item for item in quotes if isinstance(item, dict) and str(item.get("symbol") or "").upper() == ticker]
            if exact:
                return str(exact[0]["symbol"]).upper()
            equity = [item for item in quotes if isinstance(item, dict) and str(item.get("quoteType") or "").upper() in {"EQUITY", "STOCK"}]
            if equity:
                return str(equity[0].get("symbol") or ticker).upper()
    except Exception:
        pass
    return ticker


def _option_observation(obj: Any) -> dict[str, Any]:
    expiries = list(getattr(obj, "options", ()) or ())[:4]
    result: list[dict[str, Any]] = []
    for expiry in expiries[:2]:
        try:
            chain = obj.option_chain(expiry)
            for label, frame in (("call", chain.calls), ("put", chain.puts)):
                if frame is None or len(frame.index) == 0:
                    continue
                rows: list[dict[str, Any]] = []
                for _, row in frame.head(12).iterrows():
                    rows.append({
                        "strike": safe_float(row.get("strike")),
                        "bid": safe_float(row.get("bid")), "ask": safe_float(row.get("ask")),
                        "lastPrice": safe_float(row.get("lastPrice")),
                        "volume": safe_float(row.get("volume")),
                        "openInterest": safe_float(row.get("openInterest")),
                        "impliedVolatility": safe_float(row.get("impliedVolatility")),
                    })
                result.append({"expiration": expiry, "type": label, "rows": rows})
        except Exception:
            continue
    return {
        "source": "yfinance", "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
        "expirations_checked": expiries[:2], "chains": result,
    }


def collect_yahoo(ticker: str, *, include_options: bool) -> SourceResult:
    retrieved = now_iso()
    if yf is None:
        return SourceResult("yahoo_finance_public_unofficial", False, retrieved, {}, "YFINANCE_NOT_INSTALLED")
    symbol = resolve_yahoo_symbol(ticker)
    try:
        obj = yf.Ticker(symbol)
        info: dict[str, Any] = {}
        try:
            raw_info = obj.info
            if isinstance(raw_info, dict):
                for key in (
                    "symbol", "shortName", "longName", "exchange", "quoteType", "currency",
                    "sector", "industry", "marketCap", "currentPrice", "regularMarketPrice",
                    "forwardPE", "priceToSalesTrailing12Months", "beta", "shortPercentOfFloat",
                    "averageVolume", "averageDailyVolume3Month", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
                    "website", "country", "revenueGrowth", "earningsGrowth", "grossMargins",
                    "operatingMargins", "profitMargins", "totalDebt", "totalCash",
                ):
                    if key in raw_info:
                        info[key] = raw_info[key]
        except Exception:
            pass
        history = obj.history(period="6mo", interval="1d", auto_adjust=False)
        history_summary: dict[str, Any] = {}
        if history is not None and len(history.index) > 0:
            closes = history["Close"].dropna()
            if len(closes) > 0:
                first, last = safe_float(closes.iloc[0]), safe_float(closes.iloc[-1])
                history_summary = {
                    "first_close_6m": first, "last_close": last,
                    "return_6m_pct": ((last / first - 1) * 100 if first and last else None),
                    "last_date": str(closes.index[-1]),
                }
        news_rows: list[dict[str, Any]] = []
        try:
            news = obj.news
            if isinstance(news, list):
                for raw in news[:8]:
                    if not isinstance(raw, dict):
                        continue
                    content = raw.get("content") if isinstance(raw.get("content"), dict) else raw
                    canonical = content.get("canonicalUrl") if isinstance(content, dict) else None
                    if isinstance(canonical, dict):
                        canonical = canonical.get("url")
                    news_rows.append({
                        "title": content.get("title") if isinstance(content, dict) else None,
                        "publisher": content.get("provider", {}).get("displayName") if isinstance(content, dict) and isinstance(content.get("provider"), dict) else raw.get("publisher"),
                        "published": content.get("pubDate") if isinstance(content, dict) else raw.get("providerPublishTime"),
                        "url": canonical or raw.get("link"),
                    })
        except Exception:
            pass
        summary: dict[str, Any] = {
            "requested_ticker": ticker, "resolved_symbol": symbol,
            "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
            "info": info, "history_summary": history_summary, "news": news_rows,
        }
        if include_options:
            summary["on_demand_options"] = _option_observation(obj)
        return SourceResult("yahoo_finance_public_unofficial", True, retrieved, summary)
    except Exception as exc:
        return SourceResult("yahoo_finance_public_unofficial", False, retrieved, {"resolved_symbol": symbol}, type(exc).__name__)


def collect_gleif(company_name: str | None) -> SourceResult:
    retrieved = now_iso()
    if not company_name:
        return SourceResult("gleif_lei", False, retrieved, {}, "COMPANY_NAME_UNAVAILABLE")
    try:
        response = requests.get(
            "https://api.gleif.org/api/v1/lei-records",
            params={"filter[entity.legalName]": company_name, "page[size]": 3},
            headers={"Accept": "application/vnd.api+json"}, timeout=(10, 35),
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        result: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for item in rows[:3]:
                attributes = item.get("attributes") if isinstance(item, dict) else None
                entity = attributes.get("entity") if isinstance(attributes, dict) else None
                legal_name = entity.get("legalName") if isinstance(entity, dict) else None
                if isinstance(legal_name, dict):
                    legal_name = legal_name.get("name")
                result.append({
                    "lei": attributes.get("lei") if isinstance(attributes, dict) else item.get("id"),
                    "legal_name": legal_name,
                    "jurisdiction": entity.get("legalJurisdiction") if isinstance(entity, dict) else None,
                    "status": entity.get("status") if isinstance(entity, dict) else None,
                })
        if not result:
            return SourceResult("gleif_lei", False, retrieved, {}, "NO_MATCH")
        return SourceResult("gleif_lei", True, retrieved, {"query_name": company_name, "matches": result, "url": response.url})
    except Exception as exc:
        return SourceResult("gleif_lei", False, retrieved, {"query_name": company_name}, type(exc).__name__)


def collect_bls() -> SourceResult:
    retrieved = now_iso()
    try:
        response = requests.post(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            json={"seriesid": ["CUUR0000SA0", "LNS14000000"], "latest": True}, timeout=(10, 30),
        )
        response.raise_for_status()
        payload = response.json()
        series = payload.get("Results", {}).get("series", []) if isinstance(payload, dict) else []
        summary = []
        for item in series if isinstance(series, list) else []:
            data = item.get("data") if isinstance(item, dict) else None
            latest = data[0] if isinstance(data, list) and data else {}
            summary.append({"seriesID": item.get("seriesID"), "latest": latest})
        return SourceResult("bls_public_data", bool(summary), retrieved, {"series": summary, "url": response.url}, None if summary else "NO_SERIES")
    except Exception as exc:
        return SourceResult("bls_public_data", False, retrieved, {}, type(exc).__name__)


def collect_world_bank() -> SourceResult:
    retrieved = now_iso()
    try:
        response = requests.get(
            "https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.KD.ZG",
            params={"format": "json", "per_page": 5}, timeout=(10, 30),
        )
        response.raise_for_status()
        payload = response.json()
        values = payload[1] if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list) else []
        rows = [{"date": item.get("date"), "value": item.get("value")} for item in values[:5] if isinstance(item, dict)]
        return SourceResult("world_bank_indicators", bool(rows), retrieved, {"indicator": "NY.GDP.MKTP.KD.ZG", "country": "USA", "observations": rows, "url": response.url}, None if rows else "NO_OBSERVATIONS")
    except Exception as exc:
        return SourceResult("world_bank_indicators", False, retrieved, {}, type(exc).__name__)


def build_source_context(ticker: str | None, question: str = "") -> dict[str, Any]:
    results: list[SourceResult] = []
    company_name: str | None = None
    if ticker:
        sec = collect_sec(ticker)
        results.append(sec)
        if sec.ok:
            company_name = str(sec.summary.get("company") or "") or None
        yahoo = collect_yahoo(ticker, include_options=asks_options(question))
        results.append(yahoo)
        if not company_name and yahoo.ok:
            info = yahoo.summary.get("info")
            if isinstance(info, dict):
                company_name = str(info.get("longName") or info.get("shortName") or "") or None
        results.append(collect_gleif(company_name))
    results.append(collect_bls())
    results.append(collect_world_bank())
    successful = [item.source_id for item in results if item.ok]
    return {
        "schema_version": 1,
        "ticker": ticker, "retrieved_at": now_iso(),
        "successful_source_families": successful,
        "successful_source_family_count": len(successful),
        "minimum_source_family_target": 3,
        "source_diversity_status": "PASS" if len(successful) >= 3 else "DEGRADED",
        "sources": [{
            "source_id": item.source_id, "ok": item.ok,
            "retrieved_at": item.retrieved_at, "summary": item.summary, "error": item.error,
        } for item in results],
    }


def enrich_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    clean = [{"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")} for item in messages if isinstance(item, dict)]
    user_text = next((item["content"] for item in reversed(clean) if item["role"] == "user"), "")
    ticker = extract_ticker(user_text)
    context = build_source_context(ticker, user_text)
    supplement = (
        "\n\n[V2.1.2 ON-DEMAND PUBLIC SOURCE ENSEMBLE]\n" + compact(context) +
        "\nRules: source failures are not facts; distinguish SEC/GLEIF/official macro sources from T3 Yahoo market observations; "
        "if source_diversity_status is DEGRADED, explicitly say coverage is limited; do not invent missing prices, filings, option quotes or citations. "
        "A ticker absent from the deterministic Serenity universe has NO Serenity score unless a scored record is explicitly supplied. "
        "For option observations, quote BID/ASK only if present in the provided on-demand option rows and label them third-party/delay-unknown. "
        "End substantive stock answers with a compact '來源覆蓋' line listing successful source families."
    )
    if clean and clean[0]["role"] == "system":
        clean[0] = {"role": "system", "content": clean[0]["content"] + supplement}
    else:
        clean.insert(0, {"role": "system", "content": supplement.lstrip()})
    return clean, context


def llama_base_url() -> str:
    base = os.getenv("II_LLAMA_BASE_URL", "http://127.0.0.1:8813").rstrip("/")
    if not re.fullmatch(r"http://(?:127\.0\.0\.1|localhost)(?::\d{2,5})?", base):
        raise RuntimeError("II_LLAMA_BASE_URL_MUST_BE_LOOPBACK")
    return base


def llama_url() -> str:
    return llama_base_url() + "/v1/chat/completions"


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "InvestorIntelligenceLocalGateway/2.1.2"

    def _json(self, status: int, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("x-content-type-options", "nosniff")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[gateway] " + (fmt % args))

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._json(404, {"ok": False})
            return
        try:
            response = requests.get(llama_base_url() + "/health", timeout=(2, 5))
            llama_ok = response.ok
        except Exception:
            llama_ok = False
        self._json(200, {"ok": True, "service": "v212-local-llm-gateway", "llama_reachable": llama_ok})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": "NOT_FOUND"})
            return
        expected = os.getenv("II_LOCAL_LLM_SHARED_SECRET", "")
        provided = self.headers.get("x-investor-shared-secret", "")
        if len(expected) < 32 or not hmac.compare_digest(expected, provided):
            self._json(401, {"error": "UNAUTHORIZED"})
            return
        try:
            length = int(self.headers.get("content-length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._json(413, {"error": "BODY_SIZE_INVALID"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json(400, {"error": "JSON_INVALID"})
            return
        messages = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(messages, list):
            self._json(400, {"error": "MESSAGES_REQUIRED"})
            return
        try:
            enriched, context = enrich_messages(messages)
            upstream = {
                "model": body.get("model") or os.getenv("II_LOCAL_LLM_MODEL", "qwen3.8-27b"),
                "messages": enriched,
                "temperature": min(0.4, max(0.0, safe_float(body.get("temperature")) or 0.2)),
                "max_tokens": min(1800, max(256, int(body.get("max_tokens") or 1400))),
                "stream": False,
            }
            response = requests.post(llama_url(), json=upstream, headers={"content-type": "application/json"}, timeout=(5, 120))
            if not response.ok:
                self._json(502, {"error": "LLAMA_UPSTREAM_FAILED", "status": response.status_code})
                return
            result = response.json()
            if isinstance(result, dict):
                result["ii_source_ensemble"] = {
                    "successful_source_families": context["successful_source_families"],
                    "source_diversity_status": context["source_diversity_status"],
                }
            self._json(200, result)
        except Exception as exc:
            self._json(502, {"error": "LOCAL_GATEWAY_FAILED", "detail": type(exc).__name__})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert extract_ticker("ABCD 評分") == "ABCD"
        assert extract_ticker("XYZ呢") == "XYZ"
        assert extract_ticker("你好") is None
        assert asks_options("ABCD 這週 sell call")
        os.environ["II_LLAMA_BASE_URL"] = "http://127.0.0.1:8813"
        assert llama_url().endswith("/v1/chat/completions")
        os.environ["II_LLAMA_BASE_URL"] = "https://example.com"
        try:
            llama_url()
        except RuntimeError:
            pass
        else:
            raise AssertionError("Non-loopback llama URL was accepted")
        print("V212_LOCAL_LLM_GATEWAY_SELF_TEST = PASS")
        return 0
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Gateway must bind to loopback only")
    if len(os.getenv("II_LOCAL_LLM_SHARED_SECRET", "")) < 32:
        raise SystemExit("II_LOCAL_LLM_SHARED_SECRET must be configured")
    server = ThreadingHTTPServer((args.host, args.port), GatewayHandler)
    print(f"Investor Intelligence v2.1.2 local gateway listening on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
