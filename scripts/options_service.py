#!/usr/bin/env python3
"""IBKR-first, privacy-minimized option-provider orchestration.

The service never places orders. It uses an explicitly enabled local IBKR
read-only gateway first and yfinance as a labelled fallback. Exact quantities,
cost basis, account identifiers and P&L are removed before output. When an IBKR
chain has valid structure but lacks optional liquidity fields, only the derived
covered-contract capacity is carried into the fallback quote analysis.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fetch_options import (
    DATA_DIR,
    DEFAULT_MARKET_PATH,
    DEFAULT_POLICY_PATH,
    DEFAULT_PORTFOLIO_PATH,
    atomic_write_json,
    fetch_all_options as fetch_yfinance_options,
)
from fetch_options_ibkr import DEFAULT_CONFIG_PATH, fetch_all_options_ibkr, provider_enabled
from providers.ibkr_client_portal import IbkrReadOnlyError

logger = logging.getLogger(__name__)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _clean_observation(value: Any) -> Any:
    if isinstance(value, list):
        return [_clean_observation(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in {
            "shares",
            "whole_shares",
            "position_shares",
            "quantity",
            "position_quantity",
            "cost_basis",
            "average_price",
            "averageCost",
            "account_id",
            "accountId",
            "market_value",
            "unrealized_pnl",
            "daily_pnl",
        }:
            continue
        result[key] = _clean_observation(item)
    return result


def privacy_minimize(record: dict[str, Any]) -> dict[str, Any]:
    clean = _clean_observation(record)
    position = clean.get("position")
    if not isinstance(position, dict):
        position = {}
    capacity = int(position.get("covered_contract_capacity") or 0)
    clean["position"] = {
        "ticker": clean.get("ticker"),
        "covered_contract_capacity": capacity,
        "source": position.get("source") or "unavailable",
        "as_of": position.get("as_of") or clean.get("retrieved_at"),
        "exact_quantity_included": False,
    }
    clean["privacy"] = {
        "account_identifier_included": False,
        "exact_quantity_included": False,
        "cost_basis_included": False,
        "pnl_included": False,
    }
    return clean


def _recommended_count(record: dict[str, Any]) -> int:
    total = 0
    periods = record.get("periods")
    if not isinstance(periods, dict):
        return 0
    for period in periods.values():
        if not isinstance(period, dict) or period.get("status") != "OK":
            continue
        for key in ("covered_call", "cash_secured_put"):
            strategy = period.get(key)
            if not isinstance(strategy, dict):
                continue
            candidates = strategy.get("recommended_candidates")
            if isinstance(candidates, list):
                total += len(candidates)
    return total


def _usable(record: dict[str, Any] | None) -> bool:
    return bool(record and record.get("status") == "OK" and _recommended_count(record) > 0)


def _derived_capacity(record: dict[str, Any] | None) -> int:
    if not record:
        return 0
    position = record.get("position")
    if not isinstance(position, dict):
        return 0
    return max(0, int(position.get("covered_contract_capacity") or 0))


def apply_derived_capacity(record: dict[str, Any], capacity: int) -> dict[str, Any]:
    value = dict(record)
    position = value.get("position")
    if not isinstance(position, dict):
        position = {}
    value["position"] = {
        **position,
        "shares": None,
        "whole_shares": None,
        "covered_contract_capacity": capacity,
        "source": "ibkr_readonly_derived",
    }
    periods = value.get("periods")
    if isinstance(periods, dict):
        for period in periods.values():
            if not isinstance(period, dict):
                continue
            covered_call = period.get("covered_call")
            if not isinstance(covered_call, dict):
                continue
            for collection in ("recommended_candidates", "all_window_observations"):
                candidates = covered_call.get(collection)
                if not isinstance(candidates, list):
                    continue
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    candidate["position_shares"] = None
                    candidate["covered_contract_capacity"] = capacity
                    candidate["coverage_status"] = "COVERED" if capacity >= 1 else "NOT_COVERED_OR_UNKNOWN"
            if capacity >= 1:
                observations = covered_call.get("all_window_observations")
                if isinstance(observations, list):
                    eligible = [
                        item
                        for item in observations
                        if isinstance(item, dict) and item.get("liquidity_pass")
                    ]
                    maximum = max(1, len(covered_call.get("recommended_candidates") or []) or 3)
                    covered_call["recommended_candidates"] = eligible[:maximum]
                    covered_call["eligible_count"] = len(eligible)
                    covered_call["status"] = "OK" if eligible else "NO_ELIGIBLE_LIQUID_CONTRACT"
    return value


def merge_results(
    ibkr_results: list[dict[str, Any]], fallback_results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ibkr = {
        str(item.get("ticker") or "").upper(): item
        for item in ibkr_results
        if isinstance(item, dict) and item.get("ticker")
    }
    fallback = {
        str(item.get("ticker") or "").upper(): item
        for item in fallback_results
        if isinstance(item, dict) and item.get("ticker")
    }
    order = list(dict.fromkeys([*ibkr, *fallback]))
    output: list[dict[str, Any]] = []
    for ticker in order:
        primary = ibkr.get(ticker)
        secondary = fallback.get(ticker)
        capacity = _derived_capacity(primary)
        if _usable(primary):
            chosen = dict(primary or {})
            chosen["fallback_provider_status"] = (
                secondary.get("status") if secondary else "NOT_ATTEMPTED"
            )
        elif secondary is not None:
            chosen = apply_derived_capacity(dict(secondary), capacity)
            chosen["primary_provider_status"] = (
                primary.get("status") if primary else "NOT_ENABLED"
            )
            chosen["primary_provider_capacity_applied"] = capacity > 0
            if primary and primary.get("error"):
                chosen["primary_provider_error"] = str(primary.get("error"))[:200]
        elif primary is not None:
            chosen = dict(primary)
        else:
            continue
        output.append(privacy_minimize(chosen))
    return output


def fetch_options(
    *,
    provider: str | None = None,
    watchlist_path: Path | None = None,
    portfolio_path: Path = DEFAULT_PORTFOLIO_PATH,
    market_path: Path = DEFAULT_MARKET_PATH,
    policy_path: Path = DEFAULT_POLICY_PATH,
    ibkr_config_path: Path = DEFAULT_CONFIG_PATH,
    output_dir: Path = DATA_DIR,
) -> list[dict[str, Any]]:
    selected = (provider or os.getenv("OPTIONS_PROVIDER", "auto")).strip().casefold()
    if selected not in {"auto", "ibkr", "yfinance"}:
        raise ValueError("OPTIONS_PROVIDER must be auto, ibkr or yfinance")

    config = json.loads(ibkr_config_path.read_text(encoding="utf-8"))
    ibkr_enabled = provider_enabled(config)
    ibkr_results: list[dict[str, Any]] = []
    fallback_results: list[dict[str, Any]] = []

    if selected in {"auto", "ibkr"} and ibkr_enabled:
        try:
            ibkr_results = fetch_all_options_ibkr(
                config_path=ibkr_config_path,
                policy_path=policy_path,
                output_dir=output_dir,
                write_output=False,
            )
        except (IbkrReadOnlyError, OSError, ValueError) as exc:
            logger.warning("IBKR read-only provider unavailable: %s", exc)
            if selected == "ibkr" and not env_bool("OPTIONS_ALLOW_FALLBACK", True):
                raise
    elif selected == "ibkr":
        raise IbkrReadOnlyError("IBKR provider selected but IBKR_READONLY_ENABLED is false")

    fallback_required = selected in {"auto", "yfinance"} or (
        selected == "ibkr" and env_bool("OPTIONS_ALLOW_FALLBACK", True)
    )
    if fallback_required:
        with tempfile.TemporaryDirectory(prefix="investor-options-fallback-") as temporary:
            fallback_results = fetch_yfinance_options(
                watchlist_path=watchlist_path,
                portfolio_path=portfolio_path,
                market_path=market_path,
                policy_path=policy_path,
                output_dir=Path(temporary),
            )

    results = merge_results(ibkr_results, fallback_results)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    atomic_write_json(output_dir / f"options_{timestamp}.json", results)
    atomic_write_json(output_dir / "options_latest.json", results)
    logger.info(
        "Options provider merge complete: %d results (IBKR=%d, fallback=%d)",
        len(results),
        len(ibkr_results),
        len(fallback_results),
    )
    return results


def main() -> int:
    try:
        results = fetch_options()
    except (FileNotFoundError, ValueError, IbkrReadOnlyError) as exc:
        logger.error("Options service failed: %s", exc)
        return 1
    for item in results:
        print(
            f"{item.get('ticker')}: source={item.get('quote_source')} status={item.get('status')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
