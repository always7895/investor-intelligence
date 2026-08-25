#!/usr/bin/env python3
"""Build a LINE-only option snapshot through an explicit public DTO.

This command does not import the IBKR provider, does not load PORTFOLIO_JSON or
``portfolio.local.json``, and does not inherit ``config/watchlist.json``. Symbols
come only from ``config/line-public-symbols.json``. Generic option calculations
may contain neutral position-capable fields for local compatibility; this
builder accepts only neutral values, copies a closed public field allowlist and
fails on every unknown, non-neutral private or broker-lineage field.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from fetch_options import (
    CONFIG_DIR,
    DATA_DIR,
    DEFAULT_MARKET_PATH,
    DEFAULT_POLICY_PATH,
    atomic_write_json,
    get_option_suggestion,
    load_market_prices,
    load_policy,
    safe_float,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS_PATH = CONFIG_DIR / "line-public-symbols.json"
DEFAULT_OUTPUT_PATH = DATA_DIR / "options_public_latest.json"
MAX_PUBLIC_CANDIDATES = 3

FORBIDDEN_KEYS = {
    "account",
    "account_id",
    "accountid",
    "acctid",
    "portfolio",
    "portfolio_weight",
    "holding",
    "holdings",
    "position",
    "positions",
    "shares",
    "whole_shares",
    "position_quantity",
    "quantity",
    "cost_basis",
    "average_price",
    "averagecost",
    "market_value",
    "realized_pnl",
    "unrealized_pnl",
    "daily_pnl",
    "buying_power",
    "margin",
    "cash_balance",
}
NEUTRAL_PRIVATE_INPUT_FIELDS = {
    "position_shares": (None, 0, 0.0),
    "covered_contract_capacity": (None, 0),
    "coverage_status": (None, "NOT_COVERED_OR_UNKNOWN", "NOT_APPLICABLE"),
}
PUBLIC_CANDIDATE_FIELDS = frozenset(
    {
        "ticker",
        "option_type",
        "contract_symbol",
        "expiration",
        "actual_dte",
        "strike",
        "spot",
        "distance_from_spot_pct",
        "bid",
        "ask",
        "midpoint",
        "last",
        "spread",
        "spread_pct_of_mid",
        "volume",
        "open_interest",
        "implied_volatility_pct",
        "delta",
        "delta_status",
        "last_trade_at",
        "last_trade_age_days",
        "retrieved_at",
        "quote_source",
        "quote_delay_status",
        "two_sided_quote",
        "liquidity_pass",
        "liquidity_reasons",
        "quote_quality_rank",
        "sell_limit_observation",
        "annualized_yield_pct",
        "effective_sale_price",
        "put_break_even",
        "cash_secured_put_cash_requirement",
        "premium",
        "annualized_yield_pct_mid",
        "implied_vol",
    }
)
PUBLIC_CANDIDATE_INPUT_FIELDS = PUBLIC_CANDIDATE_FIELDS.union(
    NEUTRAL_PRIVATE_INPUT_FIELDS
)
BROKER_MARKERS = (
    "ibkr",
    "interactive brokers",
    "client portal",
    "brokerage",
    "broker account",
    "portfolio.local",
    "private sync",
    "tenant-private",
)


def load_public_symbols(path: Path = DEFAULT_SYMBOLS_PATH) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("line-public-symbols.json must contain an object")
    allowed_document_fields = {
        "schema_version",
        "owner_watchlist_inheritance",
        "symbols",
    }
    unknown = sorted(set(document).difference(allowed_document_fields))
    if unknown:
        raise ValueError("line-public-symbols.json has unknown field(s): " + ", ".join(unknown))
    if document.get("owner_watchlist_inheritance") is not False:
        raise ValueError("LINE public symbols must not inherit the owner watchlist")
    raw = document.get("symbols")
    if not isinstance(raw, list):
        raise ValueError("line-public-symbols.json must contain a symbols array")

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            value: dict[str, Any] = {"ticker": item}
        elif isinstance(item, dict):
            value = dict(item)
            unknown_item = sorted(
                set(value).difference({"ticker", "market_data_ticker", "currency"})
            )
            if unknown_item:
                raise ValueError(
                    "LINE public symbol has unknown field(s): "
                    + ", ".join(unknown_item)
                )
        else:
            raise ValueError("Each LINE public symbol must be a string or object")
        ticker = str(value.get("ticker") or "").strip().upper()
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid LINE public ticker: {ticker!r}")
        if ticker in seen:
            raise ValueError(f"Duplicate LINE public ticker: {ticker}")
        seen.add(ticker)
        provider_symbol = str(value.get("market_data_ticker") or ticker).strip().upper()
        if not provider_symbol or not provider_symbol.replace(".", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid public market-data ticker: {provider_symbol!r}")
        currency = str(value.get("currency") or "USD").strip().upper()
        if not currency.isalpha() or len(currency) != 3:
            raise ValueError(f"Invalid public option currency: {currency!r}")
        result.append(
            {
                "ticker": ticker,
                "market_data_ticker": provider_symbol,
                "currency": currency,
            }
        )
    return result


def _validate_public_value(value: Any, path: str = "$") -> Any:
    if isinstance(value, list):
        return [_validate_public_value(item, f"{path}[]") for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").casefold()
            if normalized in FORBIDDEN_KEYS:
                raise ValueError(f"Private key is forbidden at {path}.{key}")
            if any(marker.replace(" ", "_") in normalized for marker in BROKER_MARKERS):
                raise ValueError(f"Broker/private key marker at {path}.{key}")
            result[str(key)] = _validate_public_value(item, f"{path}.{key}")
        return result
    if isinstance(value, str):
        normalized = value.casefold()
        if any(marker in normalized for marker in BROKER_MARKERS):
            raise ValueError(f"Broker/private lineage at {path}")
    return value


def _public_candidate(item: dict[str, Any], path: str) -> dict[str, Any]:
    unknown = sorted(set(item).difference(PUBLIC_CANDIDATE_INPUT_FIELDS))
    if unknown:
        raise ValueError(f"Unknown option candidate field(s) at {path}: {', '.join(unknown)}")
    for key, allowed in NEUTRAL_PRIVATE_INPUT_FIELDS.items():
        if key in item and item.get(key) not in allowed:
            raise ValueError(f"Non-neutral private field at {path}.{key}")
    if str(item.get("quote_source") or "").casefold() != "yfinance":
        raise ValueError(f"LINE public option candidate is not from yfinance at {path}")
    return {
        key: _validate_public_value(item[key], f"{path}.{key}")
        for key in PUBLIC_CANDIDATE_FIELDS
        if key in item
    }


def _public_observations(raw: Any, path: str) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    allowed_source_fields = {
        "status",
        "recommended_candidates",
        "all_window_observations",
        "eligible_count",
        "window_observation_count",
    }
    unknown_source = sorted(set(source).difference(allowed_source_fields))
    if unknown_source:
        raise ValueError(
            f"Unknown option observation group field(s) at {path}: "
            + ", ".join(unknown_source)
        )
    observations = source.get("all_window_observations")
    if not isinstance(observations, list):
        observations = []
    eligible: list[dict[str, Any]] = []
    for index, item in enumerate(observations):
        if not isinstance(item, dict) or item.get("liquidity_pass") is not True:
            continue
        eligible.append(_public_candidate(item, f"{path}.all_window_observations[{index}]"))
    return {
        "status": "OK" if eligible else "NO_ELIGIBLE_LIQUID_QUOTE",
        "recommended_candidates": eligible[:MAX_PUBLIC_CANDIDATES],
        "eligible_count": len(eligible),
        "window_observation_count": len(observations),
    }


def to_public_record(raw: dict[str, Any], currency: str = "USD") -> dict[str, Any]:
    source = str(raw.get("quote_source") or "").casefold()
    if source != "yfinance":
        raise ValueError("LINE public option records must originate from yfinance")

    periods: dict[str, Any] = {}
    raw_periods = raw.get("periods")
    if isinstance(raw_periods, dict):
        unknown_periods = sorted(set(raw_periods).difference({"weekly", "monthly"}))
        if unknown_periods:
            raise ValueError("Unknown public option period(s): " + ", ".join(unknown_periods))
        for period_name in ("weekly", "monthly"):
            period_raw = raw_periods.get(period_name)
            if not isinstance(period_raw, dict):
                continue
            allowed_period_fields = {
                "status",
                "target_dte",
                "expiration",
                "actual_dte",
                "covered_call",
                "cash_secured_put",
            }
            unknown_period_fields = sorted(
                set(period_raw).difference(allowed_period_fields)
            )
            if unknown_period_fields:
                raise ValueError(
                    f"Unknown {period_name} option field(s): "
                    + ", ".join(unknown_period_fields)
                )
            period: dict[str, Any] = {
                "status": period_raw.get("status", "UNKNOWN"),
                "target_dte": period_raw.get("target_dte"),
                "expiration": period_raw.get("expiration"),
                "actual_dte": period_raw.get("actual_dte"),
            }
            if period.get("status") == "OK":
                period["call_observations"] = _public_observations(
                    period_raw.get("covered_call"),
                    f"$.periods.{period_name}.covered_call",
                )
                period["put_observations"] = _public_observations(
                    period_raw.get("cash_secured_put"),
                    f"$.periods.{period_name}.cash_secured_put",
                )
            periods[period_name] = period

    return {
        "schema_version": 1,
        "ticker": str(raw.get("ticker") or "").upper(),
        "provider_symbol": raw.get("provider_symbol"),
        "currency": currency,
        "current_price": raw.get("current_price"),
        "retrieved_at": raw.get("retrieved_at") or datetime.now(timezone.utc).isoformat(),
        "status": raw.get("status", "UNKNOWN"),
        "quote_source": "yfinance",
        "quote_delay_status": raw.get("quote_delay_status", "THIRD_PARTY_DELAY_UNKNOWN"),
        "provider_scope": "public_only",
        "line_public_eligible": True,
        "ibkr_connected": False,
        "brokerage_data_included": False,
        "account_data_included": False,
        "position_data_included": False,
        "owner_watchlist_inherited": False,
        "periods": periods,
    }


def build_public_options(
    *,
    symbols_path: Path = DEFAULT_SYMBOLS_PATH,
    market_path: Path = DEFAULT_MARKET_PATH,
    policy_path: Path = DEFAULT_POLICY_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    sleep_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    symbols = load_public_symbols(symbols_path)
    if not symbols:
        raise ValueError("LINE public symbol catalog is empty; refusing to inherit owner symbols")
    prices = load_market_prices(market_path)
    policy = load_policy(policy_path)

    results: list[dict[str, Any]] = []
    for index, item in enumerate(symbols, start=1):
        ticker = item["ticker"]
        provider_symbol = item["market_data_ticker"]
        price = prices.get(ticker)
        if not price:
            try:
                price = safe_float(yf.Ticker(provider_symbol).fast_info.last_price)
            except Exception as exc:
                logger.warning("Public underlying quote failed for %s: %s", ticker, type(exc).__name__)
        if not price or price <= 0:
            results.append(
                {
                    "schema_version": 1,
                    "ticker": ticker,
                    "provider_symbol": provider_symbol,
                    "currency": item["currency"],
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "status": "NO_UNDERLYING_PRICE",
                    "quote_source": "yfinance",
                    "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
                    "provider_scope": "public_only",
                    "line_public_eligible": True,
                    "ibkr_connected": False,
                    "brokerage_data_included": False,
                    "account_data_included": False,
                    "position_data_included": False,
                    "owner_watchlist_inherited": False,
                    "periods": {},
                }
            )
            continue

        logger.info("[%d/%d] public option snapshot for %s", index, len(symbols), ticker)
        raw = get_option_suggestion(
            ticker,
            price,
            policy=policy,
            position=None,
            yf_ticker=provider_symbol,
        )
        results.append(to_public_record(raw, item["currency"]))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    atomic_write_json(output_path, results)
    logger.info("Wrote %d public-only LINE option records to %s", len(results), output_path)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS_PATH)
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET_PATH)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()
    try:
        records = build_public_options(
            symbols_path=args.symbols,
            market_path=args.market,
            policy_path=args.policy,
            output_path=args.output,
            sleep_seconds=max(0.0, args.sleep),
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        logger.error("LINE public option build failed: %s", exc)
        return 1
    print(
        json.dumps(
            {
                "records": len(records),
                "output": str(args.output),
                "provider_scope": "public_only",
                "ibkr_connected": False,
                "owner_watchlist_inherited": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
