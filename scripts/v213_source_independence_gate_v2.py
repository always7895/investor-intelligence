#!/usr/bin/env python3
"""Path-stable v2.1.3 claim-level source-independence entrypoint.

The authoritative evidence logic remains in ``v213_source_independence_gate.py``.
This compatibility layer adds an independently operated, keyless daily-bar source
(HF Market Data), retains Nasdaq and optional Alpha Vantage observations, keeps
Stooq diagnostic-only when its public CSV no longer yields usable rows, and emits
no-secret provider diagnostics.  Market data remains corroboration only: it never
proves a company fact, dependency, order, bottleneck, or thesis state.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
CORE_PATH = SCRIPT_DIR / "v213_source_independence_gate.py"
HF_MARKET_DATA_BASE = "https://www.hfmarketdata.io/v1/bars/stock"
HF_MARKET_DATA_PROVIDER = "hfmarketdata_daily_bars"
HF_MARKET_DATA_FAMILY = "hfmarketdata_market"


def load_core() -> ModuleType:
    if not CORE_PATH.is_file():
        raise RuntimeError(f"Missing source-independence core: {CORE_PATH}")
    spec = importlib.util.spec_from_file_location(
        "investor_intelligence_v213_source_gate",
        CORE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to create import specification: {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = load_core()


def _safe_error(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(
        r"(?i)((?:api[_-]?key|apikey|token))=([^&\s]+)",
        r"\1=<redacted>",
        text,
    )
    return " ".join(text.split())[:240] or "none"


def _parse_hf_market_data_rows(payload: Any) -> list[tuple[dt.date, float]]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    parsed: list[tuple[dt.date, float]] = []
    if not isinstance(rows, list):
        return parsed
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            date_text = str(row.get("datetime") or row.get("date") or "")[:10]
            price = float(row.get("close") or "nan")
            parsed.append((dt.date.fromisoformat(date_text), price))
        except (TypeError, ValueError):
            continue
    return parsed


def observe_hf_market_data(ticker: str):
    """Fetch split-and-dividend-adjusted keyless daily bars.

    The provider is an independent T3 market observation.  Its returns are only
    compared with the compatibility calculation; they are never averaged into the
    published return and never used as company-claim evidence.
    """
    today = dt.date.today()
    query = urllib.parse.urlencode(
        {
            "timeframe": "1day",
            "adjustment": "adj_splitdiv",
            "start": (today - dt.timedelta(days=800)).isoformat(),
            # The documented end bound is exclusive; tomorrow includes today.
            "end": (today + dt.timedelta(days=1)).isoformat(),
            "order": "asc",
            "limit": "5000",
            "format": "json",
        }
    )
    url = (
        HF_MARKET_DATA_BASE
        + "/"
        + urllib.parse.quote(ticker, safe=".-")
        + "?"
        + query
    )
    try:
        payload = json.loads(gate.fetch_text(url, timeout=25))
        parsed = _parse_hf_market_data_rows(payload)
        as_of, long_term, short_term = gate.calculate_returns(parsed)
        if not as_of:
            detail = ""
            if isinstance(payload, dict):
                detail = str(payload.get("detail") or payload.get("message") or "")
            raise gate.SourceGateError(
                "no usable adjusted daily bars"
                + (f"; provider_detail={detail[:120]}" if detail else "")
            )
        return gate.Observation(
            HF_MARKET_DATA_PROVIDER,
            HF_MARKET_DATA_FAMILY,
            url,
            "LIVE",
            gate.iso_now(),
            as_of,
            long_term,
            short_term,
        )
    except Exception as exc:
        return gate.Observation(
            HF_MARKET_DATA_PROVIDER,
            HF_MARKET_DATA_FAMILY,
            url,
            "UNAVAILABLE",
            gate.iso_now(),
            error=str(exc)[:300],
        )


_original_family_for = gate.family_for


def source_family_with_hf_market_data(source_id: str, url: str) -> str:
    if (
        "hfmarketdata" in source_id.casefold()
        or gate.domain_of(url) == "hfmarketdata.io"
    ):
        return HF_MARKET_DATA_FAMILY
    return _original_family_for(source_id, url)


gate.family_for = source_family_with_hf_market_data
gate.MARKET_FAMILIES.add(HF_MARKET_DATA_FAMILY)
_original_collect_observations = gate.collect_observations


def _diagnose(ticker: str, observations: Iterable[Any]) -> None:
    for observation in observations:
        status = str(getattr(observation, "status", "UNKNOWN"))
        provider = str(getattr(observation, "provider", "unknown"))
        if status in {"LIVE", "CACHED"}:
            print(
                "II_PROGRESS market corroboration "
                f"{ticker} | {provider} | {status} | "
                f"as_of={getattr(observation, 'as_of', '')}",
                flush=True,
            )
        else:
            print(
                "II_DIAGNOSTIC market corroboration unavailable "
                f"{ticker} | {provider} | status={status} | "
                f"error={_safe_error(getattr(observation, 'error', ''))}",
                flush=True,
            )


def diversified_collect_observations(
    ticker: str,
    cache: dict[str, Any],
    api_key: str,
    offline: bool,
):
    resolved_ticker, observations = _original_collect_observations(
        ticker,
        cache,
        api_key,
        offline,
    )
    observations = list(observations)
    if not offline:
        # HF Market Data is keyless and independently operated.  Stooq/Nasdaq
        # remain visible attempts rather than being silently discarded.
        observations.append(
            gate.resolve_observation(
                observe_hf_market_data(resolved_ticker),
                cache,
                resolved_ticker,
            )
        )
    _diagnose(resolved_ticker, observations)
    return resolved_ticker, observations


gate.collect_observations = diversified_collect_observations


def self_test() -> None:
    assert gate.family_for(
        "fred_official_macro",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
    ) == "official_macro"
    assert gate.family_for(
        "sec_edgar",
        "https://www.sec.gov/Archives/edgar/data/1/test.htm",
    ) == "regulator_filing"
    assert gate.family_for(
        "yfinance_adjusted_close",
        "https://finance.yahoo.com/quote/NVDA/history",
    ) == "yahoo_market"
    assert gate.family_for(
        HF_MARKET_DATA_PROVIDER,
        "https://www.hfmarketdata.io/v1/bars/stock/NVDA",
    ) == HF_MARKET_DATA_FAMILY
    assert HF_MARKET_DATA_FAMILY in gate.MARKET_FAMILIES
    assert gate.domain_of(
        "https://api.nasdaq.com/api/quote/NVDA/historical"
    ) == "nasdaq.com"
    rows = _parse_hf_market_data_rows(
        {
            "count": 3,
            "data": [
                {"ticker": "TEST", "datetime": "2024-01-02", "close": 10.0},
                {"ticker": "TEST", "datetime": "2025-01-02", "close": 12.0},
                {"ticker": "TEST", "datetime": "2026-01-02", "close": 15.0},
            ],
        }
    )
    assert len(rows) == 3 and rows[-1] == (dt.date(2026, 1, 2), 15.0)
    assert _safe_error("apikey=secret&x=1") == "apikey=<redacted>&x=1"
    assert _safe_error("token=hunter2") == "token=<redacted>"
    assert not os.getenv("HF_MARKET_DATA_API_KEY")
    print(
        "V213_SOURCE_INDEPENDENCE_V2_SELF_TEST = PASS; "
        "keyless_hfmarketdata=true; market_data_is_not_company_evidence=true"
    )


if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(gate.main())
