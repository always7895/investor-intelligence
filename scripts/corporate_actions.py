#!/usr/bin/env python3
"""Reviewed corporate-action registry and bounded SEC merger-form discovery.

Public-only: no owner positions, broker data, orders, writes or market subscriptions.
Registration is not legal completion; PENDING withholds target ranking and option ideas.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "corporate-actions-v1.json"
DEFAULT_LAYERS = ROOT / "config" / "bottleneck-layers-v3.json"
DEFAULT_TICKERS = ROOT / "data" / "cache" / "v21" / "company_tickers_exchange.json"
REGISTRY_FIELDS = frozenset({"schema_version", "entries"})
ENTRY_FIELDS = frozenset({
    "target_market", "target_symbol", "acquirer_market", "acquirer_symbol", "kind",
    "exchange_ratio", "cash_per_share", "currency", "announced_on", "expected_close",
    "status", "status_on", "source_url", "source_date", "review_by",
})
DISTRIBUTION_FIELDS = frozenset({
    "target_market", "target_symbol", "kind", "status", "distribution_date",
    "related_market", "related_symbol", "shares_per_share",
    "source_url", "source_date", "review_by",
})
FORMS = frozenset({"425", "DEFM14A", "PREM14A", "S-4", "SC TO-T", "SC 14D9"})
SEC_FORMS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,14}\Z")
CLOSE = re.compile(r"(?:20\d{2}-(?:H[12]|Q[1-4])|(?:first|second) half of calendar year 20\d{2})\Z")
MAX_FILE = 256 * 1024
MAX_SUBMISSION = 24 * 1024 * 1024


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("CORPORATE_ACTION_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _json(raw: bytes, bound: int) -> Any:
    if len(raw) > bound:
        raise ValueError("CORPORATE_ACTION_INPUT_TOO_LARGE")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))


def _day(value: Any) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("CORPORATE_ACTION_BAD_DATE")
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("CORPORATE_ACTION_BAD_DATE") from exc
    if day.isoformat() != value:
        raise ValueError("CORPORATE_ACTION_BAD_DATE")
    return day


def _finite_positive(value: Any) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _filing_url(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 400 or any(ord(c) < 32 for c in value):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    # The public Worker accepts only primary SEC archive exhibits; issuer IR and
    # other SEC endpoints would invalidate the entire sealed Top20 payload.
    return (parsed.scheme == "https" and parsed.hostname == "www.sec.gov"
            and not parsed.username and not parsed.password and parsed.port is None
            and not parsed.query and not parsed.fragment and parsed.path.startswith("/Archives/"))


def load_actions(path: Path = DEFAULT_CONFIG, *, today: date | None = None) -> dict[str, Any]:
    """Standalone loader for independently installed reviewed registries."""
    return load_actions_bytes(Path(path).read_bytes(), today=today)


def load_actions_bytes(raw: bytes, *, today: date | None = None) -> dict[str, Any]:
    """Validate identical registry bytes without reopening a path or bypassing capture."""
    if type(raw) is not bytes:
        raise ValueError("CORPORATE_ACTION_BYTES_REQUIRED")
    doc = _json(raw, MAX_FILE)
    if not isinstance(doc, dict) or set(doc) != REGISTRY_FIELDS or doc["schema_version"] != 1 or not isinstance(doc["entries"], list):
        raise ValueError("CORPORATE_ACTION_SCHEMA")
    if len(doc["entries"]) > 200:
        raise ValueError("CORPORATE_ACTION_LIMIT")
    today = date.today() if today is None else today
    if not isinstance(today, date):
        raise ValueError("CORPORATE_ACTION_CLOCK")
    entries = []
    pending_targets: set[str] = set()
    distribution_keys: set[tuple[str, str, str]] = set()
    for raw in doc["entries"]:
        if not isinstance(raw, dict):
            raise ValueError("CORPORATE_ACTION_ENTRY_FIELDS")
        if raw.get("kind") == "DISTRIBUTION":
            if set(raw) != DISTRIBUTION_FIELDS:
                raise ValueError("CORPORATE_ACTION_DISTRIBUTION_FIELDS")
            if raw["status"] != "CLOSED":
                raise ValueError("CORPORATE_ACTION_DISTRIBUTION_NOT_CLOSED")
            for symbol_key in ("target_symbol", "related_symbol"):
                symbol = raw[symbol_key]
                if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
                    raise ValueError("CORPORATE_ACTION_DISTRIBUTION_SYMBOL")
            if raw["target_market"] != "US" or raw["related_market"] != "US":
                raise ValueError("CORPORATE_ACTION_DISTRIBUTION_MARKET")
            if raw["target_symbol"] == raw["related_symbol"]:
                raise ValueError("CORPORATE_ACTION_DISTRIBUTION_SELF")
            if not _finite_positive(raw["shares_per_share"]) or raw["shares_per_share"] > 10000:
                raise ValueError("CORPORATE_ACTION_DISTRIBUTION_RATIO")
            if not _filing_url(raw["source_url"]):
                raise ValueError("CORPORATE_ACTION_DISTRIBUTION_SOURCE")
            distribution_day = _day(raw["distribution_date"])
            source_day = _day(raw["source_date"])
            review_day = _day(raw["review_by"]) if raw["review_by"] is not None else None
            if source_day < distribution_day or (review_day is not None and review_day < distribution_day):
                raise ValueError("CORPORATE_ACTION_DISTRIBUTION_CHRONOLOGY")
            key = (raw["target_symbol"], raw["distribution_date"], raw["related_symbol"])
            if key in distribution_keys:
                raise ValueError("CORPORATE_ACTION_DUPLICATE_DISTRIBUTION")
            distribution_keys.add(key)
            entries.append({**raw, "flags": []})  # a CLOSED event has no pending review flag
            continue
        if set(raw) != ENTRY_FIELDS:
            raise ValueError("CORPORATE_ACTION_ENTRY_FIELDS")
        for key in ("target_symbol", "acquirer_symbol"):
            if not isinstance(raw[key], str) or not SYMBOL.fullmatch(raw[key]):
                raise ValueError("CORPORATE_ACTION_SYMBOL")
        if raw["target_symbol"] == raw["acquirer_symbol"]:
            raise ValueError("CORPORATE_ACTION_SELF_DEAL")
        if raw["target_market"] != "US" or raw["acquirer_market"] != "US":
            raise ValueError("CORPORATE_ACTION_MARKET_UNSUPPORTED")
        if raw["kind"] not in ("ALL_STOCK", "CASH", "MIXED"):
            raise ValueError("CORPORATE_ACTION_KIND")
        if raw["status"] not in ("PENDING", "CLOSED", "TERMINATED"):
            raise ValueError("CORPORATE_ACTION_STATUS")
        if not _filing_url(raw["source_url"]):
            raise ValueError("CORPORATE_ACTION_SOURCE")
        announced = _day(raw["announced_on"])
        status_on, source_on = (_day(raw[key]) for key in ("status_on", "source_date"))
        review_on = _day(raw["review_by"]) if raw["review_by"] is not None else None
        if status_on < announced or source_on < status_on or (review_on is not None and review_on < announced):
            raise ValueError("CORPORATE_ACTION_CHRONOLOGY")
        close = raw["expected_close"]
        if not (isinstance(close, str) and (CLOSE.fullmatch(close) or _valid_close_day(close))):
            raise ValueError("CORPORATE_ACTION_CLOSE_WINDOW")
        ratio, cash = raw["exchange_ratio"], raw["cash_per_share"]
        if raw["kind"] in ("ALL_STOCK", "MIXED"):
            if not _finite_positive(ratio):
                raise ValueError("CORPORATE_ACTION_RATIO")
        elif ratio is not None:
            raise ValueError("CORPORATE_ACTION_CASH_RATIO")
        if raw["kind"] in ("CASH", "MIXED"):
            if not _finite_positive(cash) or not isinstance(raw["currency"], str) or not re.fullmatch("[A-Z]{3}", raw["currency"]):
                raise ValueError("CORPORATE_ACTION_CASH")
        elif cash is not None or raw["currency"] is not None:
            raise ValueError("CORPORATE_ACTION_ALL_STOCK_CASH")
        if raw["status"] == "PENDING":
            if raw["target_symbol"] in pending_targets:
                raise ValueError("CORPORATE_ACTION_DUPLICATE_PENDING_TARGET")
            pending_targets.add(raw["target_symbol"])
        flags = (["REVIEW_DATE_UNSET"] if review_on is None else
                 ["REVIEW_OVERDUE"] if review_on < today else []) if raw["status"] == "PENDING" else []
        entry = {**raw, "flags": flags}
        entries.append(entry)
    return {"schema_version": 1, "entries": entries}


def _valid_close_day(raw: str) -> bool:
    try:
        return _day(raw).isoformat() == raw
    except ValueError:
        return False


def pending_targets(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["target_symbol"]: entry for entry in doc["entries"] if entry["status"] == "PENDING"}


def pending_acquirers(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """A display-only note; no effect on acquirer scoring, options, or recommendations."""
    return {entry["acquirer_symbol"]: entry for entry in doc["entries"] if entry["status"] == "PENDING"}


def acquirer_note(entry: dict[str, Any]) -> dict[str, Any]:
    """Bounded, whitelist-only additive metadata for the sealed LINE reader."""
    return {key: entry[key] for key in ("target_symbol", "acquirer_symbol", "kind",
             "exchange_ratio", "cash_per_share", "currency", "expected_close", "source_url")}


def completed_distributions(doc: dict[str, Any], *, asof: date | None = None) -> dict[str, list[dict[str, Any]]]:
    """Completed shareholder entitlements; never pending-target suppressions."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in doc["entries"]:
        if (entry["kind"] == "DISTRIBUTION" and entry["status"] == "CLOSED"
                and (asof is None or _day(entry["distribution_date"]) <= asof)):
            grouped.setdefault(entry["target_symbol"], []).append(entry)
    for rows in grouped.values():
        rows.sort(key=lambda x: (x["distribution_date"], x["related_symbol"]))
    return grouped


def distribution_note(entry: dict[str, Any]) -> dict[str, Any]:
    """Exact, public display-only projection (never a merger/acquirer payload)."""
    return {key: entry[key] for key in (
        "target_market", "target_symbol", "kind", "status", "distribution_date",
        "related_market", "related_symbol", "shares_per_share",
        "source_url", "source_date", "review_by")}


def _us_layer_symbols(layers_path: Path) -> list[str]:
    doc = _json(Path(layers_path).read_bytes(), MAX_SUBMISSION)
    if not isinstance(doc, dict) or not isinstance(doc.get("layers"), list):
        raise ValueError("CORPORATE_ACTION_LAYERS")
    symbols = set()
    for layer in doc["layers"]:
        if not isinstance(layer, dict) or not isinstance(layer.get("capturers"), list):
            raise ValueError("CORPORATE_ACTION_LAYERS")
        for capturer in layer["capturers"]:
            symbol = capturer.get("symbol") if isinstance(capturer, dict) else None
            if not isinstance(symbol, str):
                raise ValueError("CORPORATE_ACTION_LAYER_SYMBOL")
            if "." not in symbol and SYMBOL.fullmatch(symbol):
                symbols.add(symbol)
    return sorted(symbols)


def _cik_map(body: bytes) -> dict[str, int]:
    doc = _json(body, MAX_SUBMISSION)
    if not isinstance(doc, dict) or not isinstance(doc.get("fields"), list) or not isinstance(doc.get("data"), list):
        raise ValueError("CORPORATE_ACTION_CIK_MAP")
    fields = doc["fields"]
    if "ticker" not in fields or "cik" not in fields or len(fields) != len(set(fields)):
        raise ValueError("CORPORATE_ACTION_CIK_FIELDS")
    result = {}
    for raw in doc["data"]:
        if not isinstance(raw, list) or len(raw) != len(fields):
            raise ValueError("CORPORATE_ACTION_CIK_ROW")
        row = dict(zip(fields, raw))
        ticker, cik = row["ticker"], row["cik"]
        if isinstance(ticker, str) and isinstance(cik, int) and not isinstance(cik, bool) and cik > 0:
            result[ticker.upper()] = cik
    return result


def discover_filings(*, today: date, fetch: Callable[[str], bytes], cik_by: dict[str, int],
                     layers_path: Path = DEFAULT_LAYERS, config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    """30-day SEC submissions JSON: only existing layer US symbols, never owner watchlists."""
    actions = load_actions(config_path, today=today)
    registered = {value for entry in actions["entries"]
                  for value in (entry.get("target_symbol"), entry.get("acquirer_symbol"), entry.get("related_symbol"))
                  if value is not None}
    symbols = _us_layer_symbols(layers_path)
    cutoff = today - timedelta(days=30)
    results = []
    missing_ciks = []
    for symbol in symbols:
        cik = cik_by.get(symbol)
        if type(cik) is not int or not 0 < cik < 10**10:
            missing_ciks.append(symbol)
            continue
        url = SEC_FORMS_URL.format(cik=cik)
        body = fetch(url)
        data = _json(body, MAX_SUBMISSION)
        recent = data.get("filings", {}).get("recent") if isinstance(data, dict) else None
        if not isinstance(recent, dict):
            raise ValueError("CORPORATE_ACTION_SEC_RECENT")
        columns = [recent.get(key) for key in ("form", "filingDate", "accessionNumber", "primaryDocument")]
        if any(not isinstance(x, list) for x in columns) or len({len(x) for x in columns}) != 1:
            raise ValueError("CORPORATE_ACTION_SEC_COLUMNS")
        for form, filed, accession, primary in zip(*columns):
            if form not in FORMS:
                continue
            filing_day = _day(filed)
            if not cutoff <= filing_day <= today:
                continue
            if not all(isinstance(value, str) and len(value) <= 120 for value in (accession, primary)):
                raise ValueError("CORPORATE_ACTION_SEC_ROW")
            results.append({"symbol": symbol, "form": form, "filed": filed, "accession": accession,
                            "sec_submissions_url": url, "registered": symbol in registered})
    results.sort(key=lambda row: (row["symbol"], row["filed"], row["form"], row["accession"]))
    return {"as_of": today.isoformat(), "window_days": 30, "checked_symbols": symbols,
            "missing_ciks": missing_ciks, "filings": results,
            "unregistered": [row for row in results if not row["registered"]],
            "review_overdue": [row["target_symbol"] for row in actions["entries"] if "REVIEW_OVERDUE" in row["flags"]]}


def _sec_fetch(url: str) -> bytes:
    """Read-only SEC GET, contact header from existing admitted adapter; no generic URL."""
    if not (url.startswith("https://data.sec.gov/submissions/CIK") and url.endswith(".json")
            or url == TICKERS_URL):
        raise ValueError("CORPORATE_ACTION_SEC_HOST")
    import urllib.request
    from sec_contact_headers import sec_identity_headers
    req = urllib.request.Request(url, headers=sec_identity_headers("InvestorIntelligence/CorporateActions"))
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "discover"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--layers", type=Path, default=DEFAULT_LAYERS)
    parser.add_argument("--tickers", type=Path, default=DEFAULT_TICKERS)
    parser.add_argument("--as-of", type=str, default=date.today().isoformat())
    parser.add_argument("--fixture-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        today = _day(args.as_of)
        if args.command == "validate":
            actions = load_actions(args.config, today=today)
            output = {"status": "OK", "entries": len(actions["entries"]),
                      "overdue": [r["target_symbol"] for r in actions["entries"] if r["flags"]]}
        else:
            if args.fixture_dir is None:
                fetch = _sec_fetch
                map_body = args.tickers.read_bytes() if args.tickers.exists() else fetch(TICKERS_URL)
            else:
                # Offline replay explicitly uses fixture bytes only, no network.
                fetch = lambda url: (args.fixture_dir / (url.rsplit("/", 1)[-1])).read_bytes()
                map_body = args.tickers.read_bytes()
            output = discover_filings(today=today, fetch=fetch, cik_by=_cik_map(map_body),
                layers_path=args.layers, config_path=args.config)
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 2 if args.command == "discover" and (output["unregistered"] or output["missing_ciks"]) else 0
    except (OSError, ValueError, KeyError, TypeError, OverflowError, UnicodeError, RuntimeError) as error:
        print(json.dumps({"status": "FAILED", "reason": type(error).__name__, "code": str(error)[:100]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
