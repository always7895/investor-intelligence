#!/usr/bin/env python3
"""Path-stable v2.1.3 claim-level source-independence entrypoint.

The authoritative evidence logic remains in ``v213_source_independence_gate.py``.
This compatibility layer adds an independently operated, keyless daily-bar source
(HF Market Data), retains Nasdaq and optional Alpha Vantage observations, keeps
Stooq diagnostic-only when its public CSV no longer yields usable rows, and emits
no-secret provider diagnostics.

HF Market Data is queried once for the complete Top20 through its documented
multi-ticker endpoint. This avoids twenty simultaneous long-running requests and
keeps the clean-run release gate deterministic. Market data remains corroboration
only: it never proves a company fact, dependency, order, bottleneck, or thesis
state, and it is never averaged into the published return.

A provider response is not considered current merely because the HTTP request is
current. Every LIVE/CACHED market observation must also have a recent market
``as_of`` date. Stale observations are explicitly downgraded to UNAVAILABLE before
conflict detection so old price paths cannot create false corroboration or false
conflicts.
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import io
import json
import os
import re
import sys
import threading
import urllib.parse
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
CORE_PATH = SCRIPT_DIR / "v213_source_independence_gate.py"
HF_MARKET_DATA_BASE = "https://www.hfmarketdata.io/v1/bars/stock"
HF_MARKET_DATA_HEALTH = "https://www.hfmarketdata.io/health"
HF_MARKET_DATA_PROVIDER = "hfmarketdata_daily_bars"
HF_MARKET_DATA_FAMILY = "hfmarketdata_market"
HF_MARKET_DATA_TIMEOUT_SECONDS = 90
HF_MARKET_DATA_MAX_TICKERS = 50
MARKET_OBSERVATION_MAX_AS_OF_AGE_DAYS = 7
MARKET_OBSERVATION_MAX_FUTURE_DAYS = 1


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


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _market_as_of_age_days(value: Any) -> int | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        observed = dt.date.fromisoformat(text)
    except ValueError:
        return None
    return (dt.datetime.now(dt.timezone.utc).date() - observed).days


def _freshness_checked_market_observation(observation: Any) -> Any:
    """Fail closed when an apparently live market path is stale or future-dated."""
    status = str(getattr(observation, "status", "")).upper()
    if status not in {"LIVE", "CACHED"}:
        return observation
    as_of = str(getattr(observation, "as_of", "") or "")[:10]
    age_days = _market_as_of_age_days(as_of)
    if (
        age_days is not None
        and age_days >= -MARKET_OBSERVATION_MAX_FUTURE_DAYS
        and age_days <= MARKET_OBSERVATION_MAX_AS_OF_AGE_DAYS
    ):
        return observation
    reason = (
        "market_as_of_missing_or_invalid"
        if age_days is None
        else (
            f"stale_market_data_as_of={as_of}; age_days={age_days}; "
            f"max_age_days={MARKET_OBSERVATION_MAX_AS_OF_AGE_DAYS}"
        )
    )
    return gate.Observation(
        str(getattr(observation, "provider", "unknown")),
        str(getattr(observation, "family", "unknown")),
        str(getattr(observation, "url", "")),
        "UNAVAILABLE",
        gate.iso_now(),
        as_of=as_of,
        error=reason,
    )


def _hf_bulk_url(tickers: Iterable[str], response_format: str) -> str:
    requested: list[str] = []
    for raw in tickers:
        ticker = _normalize_ticker(raw)
        if ticker and ticker not in requested:
            requested.append(ticker)
    if not requested or len(requested) > HF_MARKET_DATA_MAX_TICKERS:
        raise gate.SourceGateError(
            f"HF Market Data requires 1..{HF_MARKET_DATA_MAX_TICKERS} unique tickers"
        )
    if response_format not in {"csv", "json"}:
        raise gate.SourceGateError("HF Market Data format must be csv or json")
    today = dt.date.today()
    query = urllib.parse.urlencode(
        {
            "tickers": ",".join(requested),
            "timeframe": "1day",
            "adjustment": "adj_splitdiv",
            "start": (today - dt.timedelta(days=800)).isoformat(),
            # The provider documents end as an upper bound; tomorrow safely
            # includes the latest completed session without inventing a price.
            "end": (today + dt.timedelta(days=1)).isoformat(),
            "order": "asc",
            "limit": "800",
            "format": response_format,
        },
        safe=",.-",
    )
    return HF_MARKET_DATA_BASE + "?" + query


def _append_hf_row(
    grouped: dict[str, list[tuple[dt.date, float]]],
    row: Mapping[str, Any],
) -> None:
    ticker = _normalize_ticker(row.get("ticker"))
    if not ticker:
        return
    try:
        date_text = str(row.get("datetime") or row.get("date") or "")[:10]
        price = float(row.get("close") or "nan")
        grouped.setdefault(ticker, []).append(
            (dt.date.fromisoformat(date_text), price)
        )
    except (TypeError, ValueError):
        return


def _parse_hf_json(text: str) -> dict[str, list[tuple[dt.date, float]]]:
    payload = json.loads(text)
    rows = payload.get("data") if isinstance(payload, dict) else None
    grouped: dict[str, list[tuple[dt.date, float]]] = {}
    if not isinstance(rows, list):
        detail = (
            str(payload.get("detail") or payload.get("message") or "")
            if isinstance(payload, dict)
            else ""
        )
        raise gate.SourceGateError(
            "HF Market Data JSON did not contain a data array"
            + (f"; provider_detail={detail[:120]}" if detail else "")
        )
    for row in rows:
        if isinstance(row, Mapping):
            _append_hf_row(grouped, row)
    return grouped


def _parse_hf_csv(text: str) -> dict[str, list[tuple[dt.date, float]]]:
    grouped: dict[str, list[tuple[dt.date, float]]] = {}
    reader = csv.DictReader(io.StringIO(text))
    required = {
        str(name or "").strip().casefold()
        for name in (reader.fieldnames or [])
    }
    if not {"ticker", "datetime", "close"}.issubset(required):
        raise gate.SourceGateError(
            "HF Market Data CSV did not contain ticker/datetime/close columns"
        )
    for raw in reader:
        normalized = {
            str(key).strip().casefold(): value
            for key, value in raw.items()
        }
        _append_hf_row(grouped, normalized)
    return grouped


def _build_hf_observations(
    tickers: list[str],
    grouped: Mapping[str, list[tuple[dt.date, float]]],
    url: str,
    cache: Mapping[str, Any],
    request_error: str = "",
) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for ticker in tickers:
        rows = list(grouped.get(ticker, []))
        as_of, long_term, short_term = gate.calculate_returns(rows)
        if as_of:
            live = gate.Observation(
                HF_MARKET_DATA_PROVIDER,
                HF_MARKET_DATA_FAMILY,
                url,
                "LIVE",
                gate.iso_now(),
                as_of,
                long_term,
                short_term,
            )
            # Convert stale HTTP-success data to UNAVAILABLE before cache
            # resolution, allowing a genuinely fresher cached observation to
            # win if one exists.
            live = _freshness_checked_market_observation(live)
        else:
            live = gate.Observation(
                HF_MARKET_DATA_PROVIDER,
                HF_MARKET_DATA_FAMILY,
                url,
                "UNAVAILABLE",
                gate.iso_now(),
                error=(
                    request_error
                    or "no usable adjusted daily bars for requested ticker"
                ),
            )
        resolved = gate.resolve_observation(live, cache, ticker)
        # Cache freshness is checked independently from cache retrieval age.
        observations[ticker] = _freshness_checked_market_observation(resolved)
    return observations


def _top20_tickers() -> list[str]:
    document = gate.read_json(gate.DEFAULT_TOP20)
    return [
        _normalize_ticker(row.get("ticker"))
        for row in gate.extract_rows(document)
    ]


_HF_BULK_LOCK = threading.Lock()
_HF_BULK_READY = False
_HF_BULK_OBSERVATIONS: dict[str, Any] = {}
_HF_BULK_REQUEST_COUNT = 0
_HF_BULK_LAST_ERROR = ""


def _load_hf_bulk(cache: Mapping[str, Any]) -> dict[str, Any]:
    """Load the complete Top20 in one provider request, once per process."""
    global _HF_BULK_READY
    global _HF_BULK_OBSERVATIONS
    global _HF_BULK_REQUEST_COUNT
    global _HF_BULK_LAST_ERROR

    with _HF_BULK_LOCK:
        if _HF_BULK_READY:
            return dict(_HF_BULK_OBSERVATIONS)

        tickers = _top20_tickers()
        grouped: dict[str, list[tuple[dt.date, float]]] = {}
        selected_url = _hf_bulk_url(tickers, "csv")
        errors: list[str] = []

        try:
            health = json.loads(
                gate.fetch_text(HF_MARKET_DATA_HEALTH, timeout=15)
            )
            if (
                not isinstance(health, dict)
                or str(health.get("status") or "").casefold() != "ok"
            ):
                raise gate.SourceGateError("provider health response is not ok")
        except Exception as exc:
            errors.append("health=" + _safe_error(exc))

        # Prefer CSV for the documented two-million-row ceiling and lower
        # serialization overhead. JSON is a single fallback, never an extra
        # evidence family or a duplicate source count.
        for response_format, parser in (
            ("csv", _parse_hf_csv),
            ("json", _parse_hf_json),
        ):
            url = _hf_bulk_url(tickers, response_format)
            try:
                _HF_BULK_REQUEST_COUNT += 1
                text = gate.fetch_text(
                    url,
                    timeout=HF_MARKET_DATA_TIMEOUT_SECONDS,
                )
                candidate = parser(text)
                if not candidate:
                    raise gate.SourceGateError(
                        "provider returned no usable ticker rows"
                    )
                grouped = candidate
                selected_url = url
                break
            except Exception as exc:
                errors.append(response_format + "=" + _safe_error(exc))

        _HF_BULK_LAST_ERROR = "; ".join(errors)
        _HF_BULK_OBSERVATIONS = _build_hf_observations(
            tickers,
            grouped,
            selected_url,
            cache,
            _HF_BULK_LAST_ERROR,
        )
        _HF_BULK_READY = True
        live_count = sum(
            1
            for observation in _HF_BULK_OBSERVATIONS.values()
            if str(getattr(observation, "status", ""))
            in {"LIVE", "CACHED"}
        )
        print(
            "II_PROGRESS keyless multi-ticker market request complete; "
            f"requested={len(tickers)}; usable={live_count}; "
            f"network_requests={_HF_BULK_REQUEST_COUNT}",
            flush=True,
        )
        if _HF_BULK_LAST_ERROR:
            print(
                "II_DIAGNOSTIC keyless multi-ticker provider attempts; "
                + _HF_BULK_LAST_ERROR,
                flush=True,
            )
        return dict(_HF_BULK_OBSERVATIONS)


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
_DIAGNOSTIC_LOCK = threading.Lock()


def _diagnose(ticker: str, observations: Iterable[Any]) -> None:
    with _DIAGNOSTIC_LOCK:
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
    observations = [
        _freshness_checked_market_observation(observation)
        for observation in observations
    ]
    if not offline:
        bulk = _load_hf_bulk(cache)
        observation = bulk.get(_normalize_ticker(resolved_ticker))
        if observation is None:
            observation = gate.Observation(
                HF_MARKET_DATA_PROVIDER,
                HF_MARKET_DATA_FAMILY,
                HF_MARKET_DATA_BASE,
                "UNAVAILABLE",
                gate.iso_now(),
                error="requested ticker missing from multi-ticker result",
            )
        observations.append(
            _freshness_checked_market_observation(observation)
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
        "https://www.hfmarketdata.io/v1/bars/stock?tickers=NVDA",
    ) == HF_MARKET_DATA_FAMILY
    assert HF_MARKET_DATA_FAMILY in gate.MARKET_FAMILIES
    assert gate.domain_of(
        "https://api.nasdaq.com/api/quote/NVDA/historical"
    ) == "nasdaq.com"

    # Static parser fixtures remain intentionally old because they test only
    # parsing, grouping and URL encoding.
    csv_text = (
        "ticker,datetime,open,high,low,close,volume\n"
        "AAA,2024-01-02,9,11,8,10,100\n"
        "BBB,2024-01-02,19,21,18,20,200\n"
        "AAA,2025-01-02,11,13,10,12,120\n"
        "AAA,2026-01-02,14,16,13,15,150\n"
    )
    grouped_csv = _parse_hf_csv(csv_text)
    assert len(grouped_csv["AAA"]) == 3
    assert grouped_csv["AAA"][-1] == (dt.date(2026, 1, 2), 15.0)

    grouped_json = _parse_hf_json(
        json.dumps(
            {
                "count": 3,
                "data": [
                    {
                        "ticker": "AAA",
                        "datetime": "2024-01-02",
                        "close": 10.0,
                    },
                    {
                        "ticker": "AAA",
                        "datetime": "2025-01-02",
                        "close": 12.0,
                    },
                    {
                        "ticker": "AAA",
                        "datetime": "2026-01-02",
                        "close": 15.0,
                    },
                ],
            }
        )
    )
    assert len(grouped_json["AAA"]) == 3
    url = _hf_bulk_url(["AAA", "BBB"], "csv")
    parsed_query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert parsed_query["tickers"] == ["AAA,BBB"]
    assert parsed_query["adjustment"] == ["adj_splitdiv"]
    assert parsed_query["limit"] == ["800"]

    today = dt.datetime.now(dt.timezone.utc).date()
    fresh_grouped = {
        "AAA": [
            (today - dt.timedelta(days=730), 10.0),
            (today - dt.timedelta(days=183), 12.0),
            (today, 15.0),
        ],
        "BBB": [(today, 20.0)],
    }
    fake_cache: dict[str, Any] = {}
    observations = _build_hf_observations(
        ["AAA", "BBB"],
        fresh_grouped,
        url,
        fake_cache,
    )
    assert observations["AAA"].status == "LIVE"
    assert observations["BBB"].status == "UNAVAILABLE"

    stale_grouped = {
        "STALE": [
            (today - dt.timedelta(days=800), 8.0),
            (today - dt.timedelta(days=200), 10.0),
            (today - dt.timedelta(days=14), 12.0),
        ]
    }
    stale = _build_hf_observations(
        ["STALE"],
        stale_grouped,
        url,
        {},
    )["STALE"]
    assert stale.status == "UNAVAILABLE"
    assert "stale_market_data_as_of=" in stale.error
    assert f"max_age_days={MARKET_OBSERVATION_MAX_AS_OF_AGE_DAYS}" in stale.error

    invalid = _freshness_checked_market_observation(
        gate.Observation(
            "synthetic",
            "synthetic_market",
            "https://example.com",
            "CACHED",
            gate.iso_now(),
            as_of="not-a-date",
        )
    )
    assert invalid.status == "UNAVAILABLE"
    assert invalid.error == "market_as_of_missing_or_invalid"

    assert _safe_error("apikey=secret&x=1") == "apikey=<redacted>&x=1"
    assert _safe_error("token=hunter2") == "token=<redacted>"
    assert not os.getenv("HF_MARKET_DATA_API_KEY")
    print(
        "V213_SOURCE_INDEPENDENCE_V2_SELF_TEST = PASS; "
        "keyless_multi_ticker=true; max_tickers=50; "
        "market_data_is_not_company_evidence=true; "
        f"market_as_of_max_age_days={MARKET_OBSERVATION_MAX_AS_OF_AGE_DAYS}; "
        "stale_market_data=UNAVAILABLE"
    )


if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(gate.main())
