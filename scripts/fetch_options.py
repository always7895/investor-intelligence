#!/usr/bin/env python3
"""Local-only holdings-aware weekly and monthly option quote analysis.

The module displays BID, ASK, midpoint, spread, liquidity and non-binding sell
limit observations. It never places orders and never invents Greeks that the
provider does not supply. Any local portfolio or research universe remains
outside Git and can never enter LINE, Worker or public KV.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from local_research_config import (
    DEFAULT_LOCAL_UNIVERSE_PATH,
    UNIVERSE_ENV,
    load_research_universe,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data" / "cache"
DEFAULT_POLICY_PATH = CONFIG_DIR / "options-policy.json"
DEFAULT_PORTFOLIO_PATH = CONFIG_DIR / "portfolio.local.json"
DEFAULT_MARKET_PATH = DATA_DIR / "market_latest.json"

DEFAULT_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "periods": {
        "weekly": {"target_dte": 7, "minimum_dte": 3, "maximum_dte": 14},
        "monthly": {"target_dte": 30, "minimum_dte": 21, "maximum_dte": 45},
    },
    "covered_call": {
        "enabled": True,
        "require_position_shares": 100,
        "minimum_otm_pct": 0.05,
        "maximum_otm_pct": 0.20,
        "maximum_candidates": 3,
    },
    "cash_secured_put": {
        "enabled": True,
        "minimum_otm_pct": 0.05,
        "maximum_otm_pct": 0.20,
        "maximum_candidates": 3,
    },
    "liquidity": {
        "require_two_sided_quote": True,
        "maximum_spread_pct_of_mid": 0.40,
        "minimum_open_interest": 5,
        "minimum_volume": 0,
        "maximum_last_trade_age_days": 7,
    },
    "sell_limit_policy": {
        "lower_fraction_above_bid": 0.25,
        "upper_reference": "midpoint",
        "minimum_tick": 0.01,
    },
}


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def safe_int(value: Any) -> int:
    number = safe_float(value)
    return 0 if number is None else max(0, int(number))


def round_price(value: float | None, tick: float = 0.01) -> float | None:
    if value is None:
        return None
    if tick <= 0:
        tick = 0.01
    return round(round(value / tick) * tick, 2)


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    document = load_json(path, {})
    if not isinstance(document, dict):
        raise ValueError("options-policy.json must contain an object")
    return deep_merge(DEFAULT_POLICY, document)


def load_watchlist(path: Path | None = None) -> list[dict[str, Any]]:
    selected = Path(path) if path is not None else DEFAULT_LOCAL_UNIVERSE_PATH
    if path is None and not selected.is_file() and not os.getenv(UNIVERSE_ENV):
        return []
    return load_research_universe(path)


def normalize_position(item: dict[str, Any], source: str) -> dict[str, Any] | None:
    ticker = str(item.get("ticker") or item.get("symbol") or "").strip().upper()
    shares = safe_float(item.get("shares") if "shares" in item else item.get("position"))
    if not ticker or shares is None:
        return None
    whole_shares = max(0, math.floor(shares))
    return {
        "ticker": ticker,
        "market_data_ticker": str(item.get("market_data_ticker") or ticker),
        "exchange": item.get("exchange"),
        "currency": item.get("currency"),
        "shares": shares,
        "whole_shares": whole_shares,
        "covered_contract_capacity": whole_shares // 100,
        "source": source,
        "as_of": item.get("as_of"),
    }


def load_portfolio(path: Path = DEFAULT_PORTFOLIO_PATH) -> dict[str, dict[str, Any]]:
    """Load private runtime positions without requiring them in Git.

    Supported sources:
    - PORTFOLIO_JSON environment variable;
    - config/portfolio.local.json, ignored by Git.
    """
    document: Any = None
    source = "none"
    raw = os.environ.get("PORTFOLIO_JSON")
    if raw:
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("PORTFOLIO_JSON is invalid JSON") from exc
        source = "environment"
    elif path.is_file():
        document = load_json(path, {})
        source = "portfolio.local.json"

    if document is None:
        return {}
    positions = document.get("positions") if isinstance(document, dict) else document
    if not isinstance(positions, list):
        raise ValueError("Portfolio must contain a positions array")

    result: dict[str, dict[str, Any]] = {}
    for item in positions:
        if not isinstance(item, dict):
            continue
        normalized = normalize_position(item, source)
        if normalized:
            result[normalized["ticker"]] = normalized
    return result


def parse_expiration(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def days_to_expiration(expiration: str, today: date | None = None) -> int:
    return (parse_expiration(expiration) - (today or datetime.now(timezone.utc).date())).days


def select_expiration(
    expirations: list[str], period: dict[str, Any], today: date | None = None
) -> tuple[str | None, int | None, str]:
    current = today or datetime.now(timezone.utc).date()
    target = int(period.get("target_dte", 7))
    minimum = int(period.get("minimum_dte", 1))
    maximum = int(period.get("maximum_dte", 60))

    candidates: list[tuple[int, str]] = []
    for value in expirations:
        try:
            dte = days_to_expiration(value, current)
        except (TypeError, ValueError):
            continue
        if minimum <= dte <= maximum:
            candidates.append((dte, value))

    if not candidates:
        return None, None, "NO_EXPIRATION_IN_WINDOW"
    dte, expiration = min(candidates, key=lambda item: (abs(item[0] - target), item[0]))
    return expiration, dte, "OK"


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def annualized_yield_pct(credit: float | None, capital_per_share: float, dte: int) -> float | None:
    if credit is None or credit < 0 or capital_per_share <= 0 or dte <= 0:
        return None
    return round(credit / capital_per_share * (365 / dte) * 100, 2)


def sell_limit_observation(
    bid: float | None,
    ask: float | None,
    policy: dict[str, Any],
) -> dict[str, float | None]:
    tick = safe_float(policy.get("minimum_tick")) or 0.01
    fraction = safe_float(policy.get("lower_fraction_above_bid"))
    fraction = 0.25 if fraction is None else min(max(fraction, 0.0), 1.0)
    if bid is None or ask is None or bid <= 0 or ask < bid:
        return {
            "bid_floor": bid,
            "reference_mid": None,
            "observed_limit_low": None,
            "observed_limit_high": None,
        }
    midpoint = (bid + ask) / 2
    low = bid + (ask - bid) * fraction
    return {
        "bid_floor": round_price(bid, tick),
        "reference_mid": round_price(midpoint, tick),
        "observed_limit_low": round_price(low, tick),
        "observed_limit_high": round_price(midpoint, tick),
    }


def row_value(row: Any, key: str) -> Any:
    try:
        return row.get(key)
    except AttributeError:
        try:
            return row[key]
        except (KeyError, TypeError):
            return None


def option_observation(
    row: Any,
    *,
    option_type: str,
    ticker: str,
    spot: float,
    expiration: str,
    dte: int,
    policy: dict[str, Any],
    position: dict[str, Any] | None,
    retrieved_at: str,
) -> dict[str, Any] | None:
    strike = safe_float(row_value(row, "strike"))
    if strike is None or strike <= 0 or spot <= 0:
        return None

    bid = safe_float(row_value(row, "bid"))
    ask = safe_float(row_value(row, "ask"))
    last = safe_float(row_value(row, "lastPrice"))
    volume = safe_int(row_value(row, "volume"))
    open_interest = safe_int(row_value(row, "openInterest"))
    implied_vol = safe_float(row_value(row, "impliedVolatility"))
    last_trade = parse_timestamp(row_value(row, "lastTradeDate"))

    two_sided = bid is not None and ask is not None and bid > 0 and ask >= bid
    midpoint = (bid + ask) / 2 if two_sided else None
    spread = ask - bid if two_sided else None
    spread_pct = spread / midpoint if spread is not None and midpoint and midpoint > 0 else None
    last_trade_age_days = (
        (datetime.now(timezone.utc) - last_trade).total_seconds() / 86400
        if last_trade is not None
        else None
    )

    if option_type == "call":
        distance_pct = strike / spot - 1
        capital = spot
        effective_sale = {
            key: round(strike + value, 2) if value is not None else None
            for key, value in {"bid": bid, "mid": midpoint, "ask": ask}.items()
        }
        break_even = None
        cash_requirement = None
    else:
        distance_pct = 1 - strike / spot
        capital = strike
        effective_sale = None
        break_even = {
            key: round(strike - value, 2) if value is not None else None
            for key, value in {"bid": bid, "mid": midpoint, "ask": ask}.items()
        }
        cash_requirement = round(strike * 100, 2)

    yields = {
        "bid": annualized_yield_pct(bid, capital, dte),
        "mid": annualized_yield_pct(midpoint, capital, dte),
        "ask": annualized_yield_pct(ask, capital, dte),
    }

    liquidity_policy = policy.get("liquidity", {})
    reasons: list[str] = []
    if bool(liquidity_policy.get("require_two_sided_quote", True)) and not two_sided:
        reasons.append("No valid two-sided BID/ASK quote")
    max_spread = safe_float(liquidity_policy.get("maximum_spread_pct_of_mid"))
    if max_spread is not None and (spread_pct is None or spread_pct > max_spread):
        reasons.append("Bid/ask spread exceeds policy")
    min_oi = safe_int(liquidity_policy.get("minimum_open_interest"))
    if open_interest < min_oi:
        reasons.append(f"Open interest below {min_oi}")
    min_volume = safe_int(liquidity_policy.get("minimum_volume"))
    if volume < min_volume:
        reasons.append(f"Volume below {min_volume}")
    max_age = safe_float(liquidity_policy.get("maximum_last_trade_age_days"))
    if max_age is not None and last_trade_age_days is not None and last_trade_age_days > max_age:
        reasons.append("Last trade is stale")

    liquidity_pass = not reasons
    limit_observation = sell_limit_observation(
        bid, ask, policy.get("sell_limit_policy", {})
    )

    # Rank only quote/liquidity observations; this is not a trade score.
    spread_quality = 0.0
    if spread_pct is not None and max_spread and max_spread > 0:
        spread_quality = max(0.0, 1.0 - spread_pct / max_spread)
    oi_quality = min(open_interest / 100.0, 1.0)
    volume_quality = min(volume / 50.0, 1.0)
    credit_quality = min((yields.get("bid") or 0.0) / 100.0, 1.0)
    distance_quality = min(max(distance_pct, 0.0) / 0.20, 1.0)
    quote_rank = round(
        spread_quality * 35
        + oi_quality * 20
        + volume_quality * 10
        + credit_quality * 20
        + distance_quality * 15,
        2,
    )

    shares = safe_float((position or {}).get("shares"))
    covered_capacity = safe_int((position or {}).get("covered_contract_capacity"))
    coverage_status = (
        "COVERED"
        if option_type == "call" and covered_capacity >= 1
        else "NOT_COVERED_OR_UNKNOWN"
        if option_type == "call"
        else "NOT_APPLICABLE"
    )

    return {
        "ticker": ticker,
        "option_type": option_type,
        "contract_symbol": row_value(row, "contractSymbol"),
        "expiration": expiration,
        "actual_dte": dte,
        "strike": round(strike, 4),
        "spot": round(spot, 4),
        "distance_from_spot_pct": round(distance_pct * 100, 2),
        "bid": round_price(bid),
        "ask": round_price(ask),
        "midpoint": round_price(midpoint),
        "last": round_price(last),
        "spread": round_price(spread),
        "spread_pct_of_mid": round(spread_pct * 100, 2) if spread_pct is not None else None,
        "volume": volume,
        "open_interest": open_interest,
        "implied_volatility_pct": round(implied_vol * 100, 2) if implied_vol is not None else None,
        "delta": None,
        "delta_status": "NOT_SUPPLIED_BY_YFINANCE",
        "last_trade_at": last_trade.isoformat() if last_trade else None,
        "last_trade_age_days": round(last_trade_age_days, 2) if last_trade_age_days is not None else None,
        "retrieved_at": retrieved_at,
        "quote_source": "yfinance",
        "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
        "two_sided_quote": two_sided,
        "liquidity_pass": liquidity_pass,
        "liquidity_reasons": reasons,
        "quote_quality_rank": quote_rank,
        "sell_limit_observation": limit_observation,
        "annualized_yield_pct": yields,
        "effective_sale_price": effective_sale,
        "put_break_even": break_even,
        "cash_secured_put_cash_requirement": cash_requirement,
        "position_shares": shares,
        "covered_contract_capacity": covered_capacity,
        "coverage_status": coverage_status,
        # Backward-compatible fields for the existing report pipeline.
        "premium": round_price(midpoint if midpoint is not None else bid if bid is not None else last),
        "annualized_yield_pct_mid": yields.get("mid"),
        "implied_vol": round(implied_vol * 100, 2) if implied_vol is not None else None,
    }


def candidate_rows(
    frame: Any,
    *,
    option_type: str,
    ticker: str,
    spot: float,
    expiration: str,
    dte: int,
    policy: dict[str, Any],
    position: dict[str, Any] | None,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    config_key = "covered_call" if option_type == "call" else "cash_secured_put"
    config = policy.get(config_key, {})
    minimum_otm = safe_float(config.get("minimum_otm_pct")) or 0.05
    maximum_otm = safe_float(config.get("maximum_otm_pct")) or 0.20

    observations: list[dict[str, Any]] = []
    if frame is None or getattr(frame, "empty", True):
        return observations

    for _, row in frame.iterrows():
        strike = safe_float(row_value(row, "strike"))
        if strike is None:
            continue
        if option_type == "call":
            in_window = spot * (1 + minimum_otm) <= strike <= spot * (1 + maximum_otm)
        else:
            in_window = spot * (1 - maximum_otm) <= strike <= spot * (1 - minimum_otm)
        if not in_window:
            continue
        observation = option_observation(
            row,
            option_type=option_type,
            ticker=ticker,
            spot=spot,
            expiration=expiration,
            dte=dte,
            policy=policy,
            position=position,
            retrieved_at=retrieved_at,
        )
        if observation:
            observations.append(observation)

    observations.sort(
        key=lambda item: (
            bool(item.get("liquidity_pass")),
            float(item.get("quote_quality_rank") or 0),
            int(item.get("open_interest") or 0),
        ),
        reverse=True,
    )
    return observations


def summarized_candidates(
    observations: list[dict[str, Any]],
    maximum: int,
    *,
    require_covered: bool = False,
) -> dict[str, Any]:
    eligible = [
        item
        for item in observations
        if item.get("liquidity_pass")
        and (not require_covered or int(item.get("covered_contract_capacity") or 0) >= 1)
    ]
    return {
        "status": "OK" if eligible else "NO_ELIGIBLE_LIQUID_CONTRACT",
        "recommended_candidates": eligible[:maximum],
        "all_window_observations": observations,
        "eligible_count": len(eligible),
        "window_observation_count": len(observations),
    }


def get_option_suggestion(
    ticker: str,
    current_price: float,
    *,
    policy: dict[str, Any] | None = None,
    position: dict[str, Any] | None = None,
    yf_ticker: str | None = None,
) -> dict[str, Any]:
    """Fetch weekly/monthly option observations for one symbol.

    The function name is retained for compatibility with the original pipeline.
    """
    policy = policy or load_policy()
    provider_symbol = yf_ticker or ticker
    retrieved_at = datetime.now(timezone.utc).isoformat()
    base: dict[str, Any] = {
        "schema_version": 2,
        "ticker": ticker,
        "provider_symbol": provider_symbol,
        "current_price": current_price,
        "retrieved_at": retrieved_at,
        "quote_source": "yfinance",
        "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
        "position": position
        or {
            "ticker": ticker,
            "shares": None,
            "whole_shares": None,
            "covered_contract_capacity": 0,
            "source": "unavailable",
        },
        "periods": {},
        "suggestions": {},
    }

    try:
        instrument = yf.Ticker(provider_symbol)
        expirations = list(instrument.options or [])
    except Exception as exc:  # network/provider isolation
        logger.warning("Options expiration fetch failed for %s: %s", ticker, exc)
        return {**base, "status": "PROVIDER_ERROR", "error": str(exc)}

    if not expirations:
        return {**base, "status": "NO_LISTED_OPTIONS"}

    any_period = False
    for period_name, period_policy in policy.get("periods", {}).items():
        expiration, dte, expiration_status = select_expiration(expirations, period_policy)
        if not expiration or dte is None:
            base["periods"][period_name] = {
                "status": expiration_status,
                "target_dte": period_policy.get("target_dte"),
            }
            continue

        try:
            chain = instrument.option_chain(expiration)
        except Exception as exc:
            base["periods"][period_name] = {
                "status": "CHAIN_PROVIDER_ERROR",
                "expiration": expiration,
                "actual_dte": dte,
                "error": str(exc),
            }
            continue

        calls = candidate_rows(
            chain.calls,
            option_type="call",
            ticker=ticker,
            spot=current_price,
            expiration=expiration,
            dte=dte,
            policy=policy,
            position=position,
            retrieved_at=retrieved_at,
        )
        puts = candidate_rows(
            chain.puts,
            option_type="put",
            ticker=ticker,
            spot=current_price,
            expiration=expiration,
            dte=dte,
            policy=policy,
            position=position,
            retrieved_at=retrieved_at,
        )

        call_policy = policy.get("covered_call", {})
        put_policy = policy.get("cash_secured_put", {})
        call_summary = summarized_candidates(
            calls,
            safe_int(call_policy.get("maximum_candidates")) or 3,
            require_covered=True,
        )
        put_summary = summarized_candidates(
            puts,
            safe_int(put_policy.get("maximum_candidates")) or 3,
        )

        period_result = {
            "status": "OK",
            "target_dte": period_policy.get("target_dte"),
            "expiration": expiration,
            "actual_dte": dte,
            "covered_call": call_summary,
            "cash_secured_put": put_summary,
        }
        base["periods"][period_name] = period_result
        any_period = True

        best_call = (
            call_summary["recommended_candidates"][0]
            if call_summary["recommended_candidates"]
            else None
        )
        best_put = (
            put_summary["recommended_candidates"][0]
            if put_summary["recommended_candidates"]
            else None
        )
        base["suggestions"][period_name] = {
            "sell_call": best_call,
            "sell_put": best_put,
            "covered_call_candidates": call_summary["recommended_candidates"],
            "cash_secured_put_candidates": put_summary["recommended_candidates"],
        }

    base["status"] = "OK" if any_period else "NO_USABLE_EXPIRATION_OR_CHAIN"
    return base


def load_market_prices(path: Path = DEFAULT_MARKET_PATH) -> dict[str, float]:
    document = load_json(path, [])
    if not isinstance(document, list):
        return {}
    result: dict[str, float] = {}
    for item in document:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").upper()
        price = safe_float(item.get("current_price"))
        if ticker and price and price > 0:
            result[ticker] = price
    return result


def fetch_all_options(
    *,
    watchlist_path: Path | None = None,
    portfolio_path: Path = DEFAULT_PORTFOLIO_PATH,
    market_path: Path = DEFAULT_MARKET_PATH,
    policy_path: Path = DEFAULT_POLICY_PATH,
    output_dir: Path = DATA_DIR,
) -> list[dict[str, Any]]:
    policy = load_policy(policy_path)
    watchlist = load_watchlist(watchlist_path)
    portfolio = load_portfolio(portfolio_path)
    prices = load_market_prices(market_path)

    metadata: dict[str, dict[str, Any]] = {
        str(item.get("ticker") or "").upper(): item
        for item in watchlist
        if item.get("ticker")
    }
    tickers = list(metadata)
    for ticker in portfolio:
        if ticker not in metadata:
            tickers.append(ticker)

    if not tickers:
        raise ValueError(
            "Local option analysis requires an ignored research universe or local portfolio"
        )

    results: list[dict[str, Any]] = []
    for index, ticker in enumerate(tickers, start=1):
        position = portfolio.get(ticker)
        provider_symbol = (
            str((position or {}).get("market_data_ticker"))
            if position and position.get("market_data_ticker")
            else str(metadata.get(ticker, {}).get("market_data_ticker") or ticker)
        )
        price = prices.get(ticker)
        if not price:
            try:
                last_price = yf.Ticker(provider_symbol).fast_info.last_price
                price = safe_float(last_price)
            except Exception as exc:
                logger.warning("Underlying quote failed for %s: %s", ticker, exc)
        if not price or price <= 0:
            results.append(
                {
                    "schema_version": 2,
                    "ticker": ticker,
                    "provider_symbol": provider_symbol,
                    "status": "NO_UNDERLYING_PRICE",
                    "position": position,
                }
            )
            continue

        logger.info(
            "[%d/%d] %s @ %.2f, covered capacity=%d",
            index,
            len(tickers),
            ticker,
            price,
            int((position or {}).get("covered_contract_capacity") or 0),
        )
        results.append(
            get_option_suggestion(
                ticker,
                price,
                policy=policy,
                position=position,
                yf_ticker=provider_symbol,
            )
        )
        time.sleep(1.0)

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    atomic_write_json(output_dir / f"options_{timestamp}.json", results)
    atomic_write_json(output_dir / "options_latest.json", results)
    logger.info("Option observations saved for %d symbols", len(results))
    return results


def main() -> int:
    results = fetch_all_options()
    for result in results:
        ticker = result.get("ticker", "N/A")
        status = result.get("status", "UNKNOWN")
        print(f"{ticker}: {status}")
        for period, value in (result.get("periods") or {}).items():
            print(
                f"  {period}: {value.get('status')} expiry={value.get('expiration')} dte={value.get('actual_dte')}"
            )
            for strategy_key in ("covered_call", "cash_secured_put"):
                strategy = value.get(strategy_key) or {}
                candidates = strategy.get("recommended_candidates") or []
                print(f"    {strategy_key}: {strategy.get('status')} ({len(candidates)} candidates)")
                for item in candidates:
                    print(
                        "      strike={strike} bid={bid} ask={ask} mid={midpoint} "
                        "spread={spread_pct_of_mid}% OI={open_interest} volume={volume}".format(
                            **item
                        )
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
