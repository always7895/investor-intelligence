"""Bounded collector and cache adapter for quarterly analyst revenue consensus (Yahoo earningsTrend).
Astra contract ORDERS-V3-01 section 3.3, items 12 and 13:
Korean coverage gap validation attempt and general quarterly consensus.

Writes data/cache/revenue_consensus_quarterly.json:
- Absolute quarterly revenue estimates only
- Per-period endDate, avg revenue estimate, analyst count >= 3, currency, retrieval instant
- Resolves 0q / +1q against latest reported quarter end
- Hermetic test support via fake fetcher
- Bounded fetch, bounded cache, and accurate error reporting
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_PATH = ROOT / "data" / "cache" / "revenue_consensus_quarterly.json"
YAHOO_ENDPOINT = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=earningsTrend,financialData"
USER_AGENT = "Mozilla/5.0 (InvestorIntelligence public observation revenue_consensus_v3)"

MIN_ANALYSTS = 3
HISTORY_KEEP = 8
MAX_AGE_HOURS = 24
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
TIMEOUT_SECONDS = 30
CURRENCIES = ("USD", "KRW", "TWD", "SEK", "JPY", "EUR", "GBP", "HKD", "CNY")


class ConsensusCollectorError(Exception):
    """Failure during consensus capture or validation."""


def is_finite_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)


def load_cache(cache_path: Path | None = None) -> dict[str, Any]:
    """Load existing cache or return empty dict if not exists. Raises on malformed JSON."""
    target = cache_path or DEFAULT_CACHE_PATH
    if not target.exists():
        return {}
    raw = target.read_bytes()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ConsensusCollectorError(f"MALFORMED_CACHE_FILE: {target} ({exc})") from exc
    if not isinstance(data, dict):
        raise ConsensusCollectorError(f"INVALID_CACHE_ROOT_TYPE: {target}")
    return data


def save_cache(data: Mapping[str, Any], cache_path: Path | None = None) -> None:
    """Atomic write to cache path."""
    target = cache_path or DEFAULT_CACHE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_suffix(".tmp")
    temp_target.write_bytes(json.dumps(dict(data), ensure_ascii=False, indent=2).encode("utf-8"))
    temp_target.replace(target)


def extract_quarterly_consensus(
    symbol: str,
    raw_quote_summary: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any] | None:
    """Extract and validate quarterly consensus trends from quoteSummary response."""
    result = (raw_quote_summary.get("quoteSummary") or {}).get("result")
    if not isinstance(result, list) or not result:
        return None

    first = result[0] if isinstance(result[0], dict) else {}
    trend_container = first.get("earningsTrend") or {}
    trends = trend_container.get("trend")
    if not isinstance(trends, list):
        return None

    fin_data = first.get("financialData") or {}
    currency = fin_data.get("financialCurrency") or fin_data.get("currency")
    if not isinstance(currency, str) or currency not in CURRENCIES:
        return None

    trend_0q = None
    trend_1q = None

    for t in trends:
        if isinstance(t, dict):
            p = t.get("period")
            if p == "0q":
                if trend_0q is not None:
                    return None  # duplicate 0q
                trend_0q = t
            elif p == "+1q":
                if trend_1q is not None:
                    return None  # duplicate +1q
                trend_1q = t
            else:
                # Only 0q and +1q are supported quarterly keys; an unsupported quarterly key ("+2q", "2q", "+3q") is an
                # unsupported response shape, refused closed (Astra r5 item 15) - never counted toward an ad-hoc limit
                # that lets 0q + "+2q" through. Non-quarterly trend entries ("0y", "-1y") stay ignored.
                if isinstance(p, str) and p.endswith("q"):
                    return None

    if not trend_0q:
        return None

    # Validate 0q
    end_0 = trend_0q.get("endDate")
    rev_est_0 = trend_0q.get("revenueEstimate") or {}
    avg_0 = rev_est_0.get("avg")
    if isinstance(avg_0, dict):
        avg_0 = avg_0.get("raw")
    analysts_0 = rev_est_0.get("numberOfAnalysts")
    if isinstance(analysts_0, dict):
        analysts_0 = analysts_0.get("raw")

    if not isinstance(end_0, str) or not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", end_0):
        return None
    if isinstance(avg_0, bool) or not is_finite_number(avg_0) or avg_0 < 0:
        return None
    if isinstance(analysts_0, bool) or not isinstance(analysts_0, (int, float)) or not float(analysts_0).is_integer() or int(analysts_0) < MIN_ANALYSTS:
        return None

    # Preserve an explicit resolved start when the provider states one (Astra r5 item 15): the sealer binds it to the
    # forward interval's start; an absent start is sealed absent (the reader then checks only the end).
    def _with_start(quarter: dict[str, Any], trend: Mapping[str, Any]) -> dict[str, Any]:
        start_raw = trend.get("startDate")
        if isinstance(start_raw, str) and re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", start_raw):
            quarter = {**quarter, "start": start_raw}
        return quarter

    q0 = _with_start({
        "period": "0q",
        "end": end_0,
        "revenue": float(avg_0),
        "analysts": int(analysts_0),
        "currency": currency,
        "scope": "CONSOLIDATED",
    }, trend_0q)
    quarters_out = [q0]

    # Validate +1q if present
    if trend_1q is not None:
        end_1 = trend_1q.get("endDate")
        rev_est_1 = trend_1q.get("revenueEstimate") or {}
        avg_1 = rev_est_1.get("avg")
        if isinstance(avg_1, dict):
            avg_1 = avg_1.get("raw")
        analysts_1 = rev_est_1.get("numberOfAnalysts")
        if isinstance(analysts_1, dict):
            analysts_1 = analysts_1.get("raw")

        # Explicit malformed check: if present, cannot be string or malformed numbers
        if not isinstance(end_1, str) or not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", end_1):
            return None
        # Backwards +1q ending on or before 0q is a chronological conflict: fail closed
        if end_1 <= end_0:
            return None
        if isinstance(avg_1, bool) or not is_finite_number(avg_1) or avg_1 < 0:
            return None
        if isinstance(analysts_1, bool) or not isinstance(analysts_1, (int, float)) or not float(analysts_1).is_integer() or analysts_1 < 0:
            return None

        # Include as second quarter; analyst count (even if < MIN_ANALYSTS) is preserved
        # so downstream callers/sealer/Worker know the explicit sample count/reason
        q1 = _with_start({
            "period": "+1q",
            "end": end_1,
            "revenue": float(avg_1),
            "analysts": int(analysts_1),
            "currency": currency,
            "scope": "CONSOLIDATED",
        }, trend_1q)
        quarters_out.append(q1)

    return {
        "symbol": symbol,
        "captured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": currency,
        "scope": "CONSOLIDATED",
        "source_url": YAHOO_ENDPOINT.format(symbol=symbol),
        "quarters": quarters_out,
    }


def _valid_start(value: Any, end: str) -> bool:
    """An explicit resolved quarter start (Astra r5 item 15): a real calendar day strictly before the quarter end."""
    if value is None:
        return True
    if not isinstance(value, str) or not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", value):
        return False
    return value < end


def validate_consensus_entry(entry: Any, symbol: str | None = None) -> bool:
    """Validate that a cache entry has proper structure, valid timestamps, and quarters."""
    if not isinstance(entry, dict):
        return False
    if symbol and entry.get("symbol") != symbol:
        return False
    cap_str = entry.get("captured_at")
    if not isinstance(cap_str, str) or not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", cap_str):
        return False
    if entry.get("currency") not in CURRENCIES:
        return False
    quarters = entry.get("quarters")
    if not isinstance(quarters, list) or len(quarters) < 1 or len(quarters) > 2:
        return False
    q0 = quarters[0]
    if not isinstance(q0, dict) or not isinstance(q0.get("end"), str) or not is_finite_number(q0.get("revenue")) or q0.get("revenue") < 0 or type(q0.get("analysts")) is not int or q0.get("analysts") < MIN_ANALYSTS:
        return False
    if not _valid_start(q0.get("start"), str(q0.get("end"))):
        return False
    if len(quarters) > 1:
        q1 = quarters[1]
        if not isinstance(q1, dict) or not isinstance(q1.get("end"), str) or not is_finite_number(q1.get("revenue")) or q1.get("revenue") < 0 or type(q1.get("analysts")) is not int or q1.get("analysts") < 0:
            return False
        if not _valid_start(q1.get("start"), str(q1.get("end"))):
            return False
    return True


def _bounded_fetch(url: str) -> dict[str, Any]:
    """The default transport (Astra r5 item 16): a bounded HTTP read, not an unbounded download. The body is read in
    chunks with the module timeout, refused at MAX_RESPONSE_BYTES before it is ever decoded, and the decoded JSON
    must be a dict whose quoteSummary result list is short (bounded work, bounded cache write)."""
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ConsensusCollectorError(f"RESPONSE_TOO_LARGE: >{MAX_RESPONSE_BYTES} bytes")
            chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConsensusCollectorError(f"RESPONSE_NOT_JSON: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise ConsensusCollectorError("RESPONSE_ROOT_NOT_OBJECT")
    result = (data.get("quoteSummary") or {}).get("result")
    if result is not None and (not isinstance(result, list) or len(result) > 8):
        raise ConsensusCollectorError("RESPONSE_RESULT_UNBOUNDED")
    return data


def _session_fetch(symbol: str) -> dict[str, Any]:
    """The production transport: Yahoo answers quoteSummary only with the cookie and crumb of the project's yfinance
    session (a plain request gets HTTP 401 - writer-verified 2026-09-28 with yfinance 1.5.2 and 1.7.0). The library
    decodes the body itself, so the size limit below applies after decoding; the refresh step's time is bounded by the
    data-refresh budget of scripts/run_production_sealed_refresh.ps1 (a streaming byte cap is follow-up TRANSPORT-01).
    Two symbols, one request each, no retries."""
    import yfinance as yf

    data = yf.Ticker(symbol)._data.get_raw_json(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
                                                 params={"modules": "earningsTrend,financialData", "formatted": "false"})
    if not isinstance(data, dict):
        raise ConsensusCollectorError("RESPONSE_ROOT_NOT_OBJECT")
    result = (data.get("quoteSummary") or {}).get("result")
    if result is not None and (not isinstance(result, list) or len(result) > 8):
        raise ConsensusCollectorError("RESPONSE_RESULT_UNBOUNDED")
    return data


def refresh_symbol(
    symbol: str,
    now: datetime,
    max_age_hours: float = MAX_AGE_HOURS,
    fetch_json: Callable[[str], dict[str, Any]] | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any] | None:
    """Fetch or refresh consensus for a single symbol, appending to its capture history in the local cache (the newest
    HISTORY_KEEP captures per symbol, oldest first; the sealer selects the newest one at or before its cutoff)."""
    cache = load_cache(cache_path)
    history = history_of(cache, symbol)
    entry = history[-1] if history else None
    if isinstance(entry, dict) and validate_consensus_entry(entry, symbol):
        try:
            cap_dt = datetime.strptime(entry["captured_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age_sec = (now - cap_dt).total_seconds()
            # Reuse cached entry if 0 <= age <= max_age_hours; if in the future or older, must refresh
            if 0 <= age_sec <= max_age_hours * 3600:
                return entry
        except Exception:
            pass

    url = YAHOO_ENDPOINT.format(symbol=symbol)
    if fetch_json:
        raw_data = fetch_json(url)
    else:
        raw_data = _session_fetch(symbol)

    raw_bytes_len = len(json.dumps(raw_data).encode("utf-8"))
    if raw_bytes_len > MAX_RESPONSE_BYTES:
        raise ConsensusCollectorError(f"RESPONSE_TOO_LARGE: {raw_bytes_len} bytes exceeds {MAX_RESPONSE_BYTES}")

    extracted = extract_quarterly_consensus(symbol, raw_data, now)
    if extracted:
        cache[symbol] = (history + [extracted])[-HISTORY_KEEP:]
        save_cache(cache, cache_path)
        return extracted
    return None


def history_of(cache: Mapping[str, Any], symbol: str) -> list[dict[str, Any]]:
    """The capture history of one symbol, oldest first (a single legacy entry reads as a history of one)."""
    value = cache.get(symbol)
    if isinstance(value, dict):
        return [value]
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def select_for_cutoff(cache: Mapping[str, Any], cutoff: datetime) -> dict[str, Any]:
    """Per symbol the newest capture taken at or before the cutoff (a sealed build never binds a later capture); the
    24-hour age limit is applied by the forecast builder."""
    selected: dict[str, Any] = {}
    stamp = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    for symbol in cache:
        eligible = [
            entry for entry in history_of(cache, symbol)
            if validate_consensus_entry(entry, symbol) and isinstance(entry.get("captured_at"), str) and entry["captured_at"] <= stamp
        ]
        if eligible:
            selected[symbol] = max(eligible, key=lambda entry: entry["captured_at"])
    return selected


def registry_symbols(registry_path: Path | None = None) -> list[str]:
    """The issuers whose reviewed registry record confirms no company guidance: the only ones the consensus path serves."""
    path = registry_path or (ROOT / "config" / "revenue-guidance-v1.json")
    try:
        registry = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return []
    return [str(record.get("symbol")) for record in registry.get("issuers") or []
            if isinstance(record, dict) and record.get("status") == "NOT_DISCLOSED" and isinstance(record.get("symbol"), str)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh quarterly revenue consensus cache")
    parser.add_argument("--symbols", nargs="*", default=None, help="Symbols to refresh (default: the registry's NOT_DISCLOSED issuers)")
    parser.add_argument("--if-older-than-hours", type=float, default=MAX_AGE_HOURS)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    args = parser.parse_args()

    if args.if_older_than_hours < 0 or not math.isfinite(args.if_older_than_hours):
        return 2

    now = datetime.now(timezone.utc).replace(microsecond=0)
    if args.symbols is None:
        args.symbols = registry_symbols()
    success_count = 0
    failure_count = 0

    for sym in args.symbols:
        try:
            res = refresh_symbol(sym, now, max_age_hours=args.if_older_than_hours, cache_path=args.cache_path)
            if res:
                print(f"Refreshed {sym}: {len(res.get('quarters', []))} quarters")
                success_count += 1
            else:
                print(f"Failed or insufficient analysts for {sym}")
                failure_count += 1
        except Exception as exc:
            print(f"Error refreshing {sym}: {exc}")
            failure_count += 1

    return 0 if failure_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
