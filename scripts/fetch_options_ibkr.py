#!/usr/bin/env python3
"""IBKR Client Portal option adapter for the audited option-report schema.

The adapter is read-only. It uses raw quantities only in memory to calculate
covered-contract capacity and removes exact shares, account identifiers, cost
basis and P&L before writing any result. Configured symbol mappings are optional
overrides; additional long stock positions are discovered dynamically.
"""
from __future__ import annotations

import calendar
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from fetch_options import (
    DATA_DIR,
    DEFAULT_POLICY_PATH,
    atomic_write_json,
    load_policy,
    option_observation,
    safe_float,
    safe_int,
    summarized_candidates,
)
from providers.ibkr_client_portal import (
    IbkrClientPortalReadOnly,
    IbkrReadOnlyError,
    IbkrTarget,
    UnderlyingDefinition,
    target_from_config,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "ibkr-readonly.json"


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def provider_enabled(config: dict[str, Any]) -> bool:
    return env_bool("IBKR_READONLY_ENABLED", bool(config.get("enabled", False)))


def _equity_position_quantities(records: Iterable[dict[str, Any]]) -> dict[str, float]:
    """Return long STK quantities in memory without account metadata.

    Unknown/non-stock asset classes are ignored rather than being treated as
    share coverage. This prevents an option/CFD position from accidentally
    creating covered-call capacity.
    """
    result: dict[str, float] = {}
    for record in records:
        asset_class = str(
            record.get("assetClass")
            or record.get("asset_class")
            or record.get("secType")
            or record.get("security_type")
            or ""
        ).upper()
        if asset_class != "STK":
            continue
        symbol = ""
        for key in ("ticker", "symbol", "contractDesc", "contract_description"):
            raw = record.get(key)
            if raw:
                symbol = str(raw).split(" ", 1)[0].split("@", 1)[0].strip().upper()
                break
        quantity: float | None = None
        for key in ("position", "quantity", "pos"):
            quantity = safe_float(record.get(key))
            if quantity is not None:
                break
        if symbol and quantity is not None and quantity > 0:
            result[symbol] = result.get(symbol, 0.0) + quantity
    return result


def _parse_expiration(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    if len(text) >= 8 and text[:8].isdigit():
        try:
            return datetime.strptime(text[:8], "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date().isoformat()
    except ValueError:
        return None


def _contract_expiration(record: dict[str, Any]) -> str | None:
    for key in (
        "maturityDate",
        "maturity",
        "lastTradingDay",
        "last_trading_day",
        "expiry",
        "expiration",
        "expirationDate",
    ):
        result = _parse_expiration(record.get(key))
        if result:
            return result
    return None


def _contract_id(record: dict[str, Any]) -> int | None:
    for key in ("conid", "contract_id", "contractId"):
        value = safe_int(record.get(key))
        if value > 0:
            return value
    return None


def _contract_strike(record: dict[str, Any]) -> float | None:
    for key in ("strike", "strikePrice"):
        value = safe_float(record.get(key))
        if value is not None and value > 0:
            return value
    return None


def _contract_right(record: dict[str, Any], default: str) -> str:
    value = str(record.get("right") or record.get("putOrCall") or default).upper()
    return "C" if value.startswith("C") else "P"


def _month_token(day: date) -> str:
    return f"{calendar.month_abbr[day.month].upper()}{str(day.year)[-2:]}"


def _period_months(period: dict[str, Any], today: date) -> list[str]:
    minimum = max(0, int(period.get("minimum_dte", 0)))
    maximum = max(minimum, int(period.get("maximum_dte", 60)))
    start = today + timedelta(days=minimum)
    end = today + timedelta(days=maximum)
    cursor = date(start.year, start.month, 1)
    end_month = date(end.year, end.month, 1)
    result: list[str] = []
    while cursor <= end_month:
        result.append(_month_token(cursor))
        cursor = date(
            cursor.year + (1 if cursor.month == 12 else 0),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return result


def _strict_expiration(
    expirations: Iterable[str], period: dict[str, Any], *, today: date
) -> tuple[str | None, int | None, str]:
    minimum = int(period.get("minimum_dte", 1))
    maximum = int(period.get("maximum_dte", 60))
    target = int(period.get("target_dte", 7))
    candidates: list[tuple[int, int, str]] = []
    for expiration in expirations:
        try:
            dte = (datetime.fromisoformat(expiration[:10]).date() - today).days
        except (TypeError, ValueError):
            continue
        if minimum <= dte <= maximum:
            candidates.append((abs(dte - target), dte, expiration))
    if not candidates:
        return None, None, "NO_EXPIRATION_IN_WINDOW"
    _, dte, expiration = sorted(candidates, key=lambda item: (item[0], item[1], item[2]))[0]
    return expiration, dte, "OK"


def _select_strikes(values: Iterable[float], *, spot: float, maximum: int) -> list[float]:
    unique = sorted({float(value) for value in values})
    bounded = [value for value in unique if spot * 0.65 <= value <= spot * 1.35]
    source = bounded if len(bounded) >= min(maximum, 10) else unique
    return sorted(sorted(source, key=lambda value: (abs(value - spot), value))[:maximum])


def _snapshot_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return None


def _snapshot_index(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        conid = safe_int(row.get("conid") or row.get("contract_id") or row.get("contractId"))
        if conid > 0:
            result[conid] = row
    return result


def _snapshot_datetime(record: dict[str, Any]) -> datetime | None:
    raw = _snapshot_value(record, "_updated", "updated", "timestamp", "ts")
    number = safe_float(raw)
    if number is None:
        return None
    if number > 10_000_000_000:
        number /= 1000
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _normalize_iv(value: Any) -> float | None:
    number = safe_float(value)
    if number is None or number < 0:
        return None
    return number / 100 if number > 5 else number


def _underlying_price(
    client: IbkrClientPortalReadOnly,
    definition: UnderlyingDefinition,
    fields: dict[str, str],
) -> float | None:
    rows = client.market_snapshot(
        [definition.conid],
        [fields.get("last", "31"), fields.get("bid", "84"), fields.get("ask", "86")],
    )
    if not rows:
        return None
    row = rows[0]
    last = safe_float(_snapshot_value(row, fields.get("last", "31"), "31"))
    bid = safe_float(_snapshot_value(row, fields.get("bid", "84"), "84"))
    ask = safe_float(_snapshot_value(row, fields.get("ask", "86"), "86"))
    if last is not None and last > 0:
        return last
    if bid is not None and ask is not None and ask >= bid > 0:
        return (bid + ask) / 2
    return None


def _collect_contracts(
    client: IbkrClientPortalReadOnly,
    definition: UnderlyingDefinition,
    *,
    month: str,
    spot: float,
    maximum_strikes: int,
) -> list[dict[str, Any]]:
    strike_document = client.strikes(definition, month)
    result: dict[int, dict[str, Any]] = {}
    for right, key in (("C", "call"), ("P", "put")):
        for strike in _select_strikes(
            strike_document.get(key, []), spot=spot, maximum=maximum_strikes
        ):
            for record in client.option_contract_info(
                definition, month=month, strike=strike, right=right
            ):
                conid = _contract_id(record)
                if conid is None or _contract_expiration(record) is None:
                    continue
                item = dict(record)
                item["_right"] = _contract_right(item, right)
                result[conid] = item
    return list(result.values())


def _raw_quote_row(
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    fields: dict[str, str],
    currency: str,
) -> dict[str, Any]:
    # Optional Client Portal field IDs are read only when explicitly configured.
    optional = {
        key: value
        for key, value in {
            "option_volume": fields.get("option_volume"),
            "option_open_interest": fields.get("option_open_interest"),
            "implied_volatility": fields.get("implied_volatility"),
            "delta": fields.get("delta"),
        }.items()
        if value
    }
    return {
        "contractSymbol": contract.get("localSymbol") or contract.get("symbol"),
        "strike": _contract_strike(contract),
        "bid": safe_float(_snapshot_value(snapshot, fields.get("bid", "84"), "84")),
        "ask": safe_float(_snapshot_value(snapshot, fields.get("ask", "86"), "86")),
        "lastPrice": safe_float(_snapshot_value(snapshot, fields.get("last", "31"), "31")),
        "volume": safe_int(_snapshot_value(snapshot, optional.get("option_volume", "__missing__"))),
        "openInterest": safe_int(
            _snapshot_value(snapshot, optional.get("option_open_interest", "__missing__"))
        ),
        "impliedVolatility": _normalize_iv(
            _snapshot_value(snapshot, optional.get("implied_volatility", "__missing__"))
        ),
        "delta": safe_float(_snapshot_value(snapshot, optional.get("delta", "__missing__"))),
        "lastTradeDate": _snapshot_datetime(snapshot),
        "currency": contract.get("currency") or currency,
        "inTheMoney": bool(contract.get("inTheMoney")),
    }


def _sanitize_observation(
    value: dict[str, Any], *, raw_row: dict[str, Any], currency: str, exchange: str | None
) -> dict[str, Any]:
    result = dict(value)
    result.pop("position_shares", None)
    delta = safe_float(raw_row.get("delta"))
    result["delta"] = delta
    result["delta_status"] = "IBKR_SUPPLIED" if delta is not None else "NOT_AVAILABLE"
    result["quote_source"] = "ibkr_client_portal_read_only"
    result["quote_delay_status"] = "REALTIME_OR_DELAYED_PER_IBKR_SUBSCRIPTION"
    result["currency"] = raw_row.get("currency") or currency
    result["option_exchange"] = exchange
    return result


def _period_observations(
    client: IbkrClientPortalReadOnly,
    contracts: list[dict[str, Any]],
    *,
    expiration: str,
    dte: int,
    ticker: str,
    spot: float,
    policy: dict[str, Any],
    private_position: dict[str, Any],
    fields: dict[str, str],
    currency: str,
    exchange: str | None,
    retrieved_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = [record for record in contracts if _contract_expiration(record) == expiration]
    calls: list[dict[str, Any]] = []
    puts: list[dict[str, Any]] = []
    requested_fields = list(dict.fromkeys(str(value) for value in fields.values() if value))
    for start in range(0, len(selected), 50):
        batch = selected[start : start + 50]
        conids = [value for record in batch if (value := _contract_id(record)) is not None]
        snapshots = _snapshot_index(client.market_snapshot(conids, requested_fields))
        for contract in batch:
            conid = _contract_id(contract)
            if conid is None:
                continue
            right = _contract_right(contract, "C")
            raw = _raw_quote_row(contract, snapshots.get(conid, {}), fields, currency)
            observation = option_observation(
                raw,
                option_type="call" if right == "C" else "put",
                ticker=ticker,
                spot=spot,
                expiration=expiration,
                dte=dte,
                policy=policy,
                position=private_position,
                retrieved_at=retrieved_at,
            )
            if observation is None:
                continue
            clean = _sanitize_observation(
                observation, raw_row=raw, currency=currency, exchange=exchange
            )
            (calls if right == "C" else puts).append(clean)
    calls.sort(key=lambda item: float(item.get("quote_quality_rank") or 0), reverse=True)
    puts.sort(key=lambda item: float(item.get("quote_quality_rank") or 0), reverse=True)
    return calls, puts


def get_ibkr_option_suggestion(
    client: IbkrClientPortalReadOnly,
    target: IbkrTarget,
    *,
    quantity: float,
    policy: dict[str, Any],
    config: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    capacity = max(0, int(quantity // 100))
    public_position = {
        "ticker": target.ticker,
        "shares": None,
        "whole_shares": None,
        "covered_contract_capacity": capacity,
        "source": "ibkr_readonly_private",
        "as_of": retrieved_at,
        "exact_quantity_included": False,
    }
    private_position = {
        "ticker": target.ticker,
        "shares": quantity,
        "whole_shares": max(0, int(quantity)),
        "covered_contract_capacity": capacity,
        "source": "ibkr_readonly_private",
        "as_of": retrieved_at,
    }
    base: dict[str, Any] = {
        "schema_version": 2,
        "ticker": target.ticker,
        "provider_symbol": target.provider_symbol,
        "retrieved_at": retrieved_at,
        "quote_source": "ibkr_client_portal_read_only",
        "quote_delay_status": "REALTIME_OR_DELAYED_PER_IBKR_SUBSCRIPTION",
        "position": public_position,
        "periods": {},
        "suggestions": {},
        "privacy": {
            "account_identifier_included": False,
            "exact_quantity_included": False,
            "cost_basis_included": False,
            "pnl_included": False,
        },
    }

    definition = client.search_underlying(target)
    fields = dict(config.get("market_data_fields", {}))
    optional_fields = config.get("optional_market_data_fields", {})
    if isinstance(optional_fields, dict):
        for key in ("option_volume", "option_open_interest", "implied_volatility", "delta"):
            value = optional_fields.get(key)
            if value:
                fields[key] = str(value)
    spot = _underlying_price(client, definition, fields)
    base["current_price"] = spot
    base["currency"] = definition.currency or target.currency
    base["option_exchange"] = definition.option_exchange
    if spot is None or spot <= 0:
        return {**base, "status": "NO_UNDERLYING_PRICE"}

    maximum_strikes = max(4, int(config.get("maximum_strikes_per_right_per_month", 18)))
    month_cache: dict[str, list[dict[str, Any]]] = {}
    any_period = False
    for period_name, period_policy in policy.get("periods", {}).items():
        contracts: list[dict[str, Any]] = []
        for month in _period_months(period_policy, today):
            if month not in month_cache:
                try:
                    month_cache[month] = _collect_contracts(
                        client,
                        definition,
                        month=month,
                        spot=spot,
                        maximum_strikes=maximum_strikes,
                    )
                except IbkrReadOnlyError:
                    month_cache[month] = []
            contracts.extend(month_cache[month])

        expirations = sorted(
            {value for record in contracts if (value := _contract_expiration(record))}
        )
        expiration, dte, status = _strict_expiration(expirations, period_policy, today=today)
        if not expiration or dte is None:
            base["periods"][period_name] = {
                "status": status,
                "target_dte": period_policy.get("target_dte"),
                "available_expirations": expirations,
            }
            continue

        calls, puts = _period_observations(
            client,
            contracts,
            expiration=expiration,
            dte=dte,
            ticker=target.ticker,
            spot=spot,
            policy=policy,
            private_position=private_position,
            fields=fields,
            currency=base["currency"],
            exchange=definition.option_exchange,
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
        base["periods"][period_name] = {
            "status": "OK" if calls or puts else "NO_QUOTES",
            "target_dte": period_policy.get("target_dte"),
            "expiration": expiration,
            "actual_dte": dte,
            "covered_call": call_summary,
            "cash_secured_put": put_summary,
        }
        base["suggestions"][period_name] = {
            "sell_call": call_summary["recommended_candidates"][0]
            if call_summary["recommended_candidates"]
            else None,
            "sell_put": put_summary["recommended_candidates"][0]
            if put_summary["recommended_candidates"]
            else None,
            "covered_call_candidates": call_summary["recommended_candidates"],
            "cash_secured_put_candidates": put_summary["recommended_candidates"],
        }
        any_period = any_period or bool(calls or puts)

    base["status"] = "OK" if any_period else "NO_USABLE_EXPIRATION_OR_QUOTES"
    return base


def fetch_all_options_ibkr(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    policy_path: Path = DEFAULT_POLICY_PATH,
    output_dir: Path = DATA_DIR,
    write_output: bool = True,
    today: date | None = None,
) -> list[dict[str, Any]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not provider_enabled(config):
        raise IbkrReadOnlyError("IBKR read-only provider is disabled")
    policy = load_policy(policy_path)
    configured_targets = {
        target.ticker: target
        for target in (
            target_from_config(item)
            for item in config.get("targets", [])
            if isinstance(item, dict) and item.get("ticker")
        )
    }

    client = IbkrClientPortalReadOnly(
        base_url=os.getenv("IBKR_CP_BASE_URL", str(config.get("base_url"))),
        verify_tls=env_bool("IBKR_CP_VERIFY_TLS", bool(config.get("verify_tls", False))),
        timeout_seconds=float(config.get("request_timeout_seconds", 20)),
        snapshot_retry_count=int(config.get("snapshot_retry_count", 3)),
        snapshot_retry_delay_seconds=float(config.get("snapshot_retry_delay_seconds", 1.0)),
        maximum_position_pages_per_account=int(
            config.get("maximum_position_pages_per_account", 20)
        ),
    )
    client.require_authenticated()

    # One private in-memory position read discovers future long stock holdings.
    # Raw records are never returned, logged or written to disk.
    quantities = _equity_position_quantities(client.positions())
    targets = dict(configured_targets)
    for symbol in quantities:
        if symbol not in targets:
            targets[symbol] = IbkrTarget(
                ticker=symbol,
                search_symbol=symbol,
                provider_symbol=symbol,
                currency="USD",  # Search result replaces this fallback currency.
            )
    if not targets:
        raise IbkrReadOnlyError("No configured or long-stock option targets are available")

    current_day = today or datetime.now(timezone.utc).date()
    results: list[dict[str, Any]] = []
    for ticker, target in targets.items():
        quantity = quantities.get(ticker, 0.0)
        try:
            results.append(
                get_ibkr_option_suggestion(
                    client,
                    target,
                    quantity=quantity,
                    policy=policy,
                    config=config,
                    today=current_day,
                )
            )
        except IbkrReadOnlyError as exc:
            results.append(
                {
                    "schema_version": 2,
                    "ticker": target.ticker,
                    "provider_symbol": target.provider_symbol,
                    "status": "PROVIDER_ERROR",
                    "error": str(exc),
                    "quote_source": "ibkr_client_portal_read_only",
                    "position": {
                        "ticker": target.ticker,
                        "shares": None,
                        "whole_shares": None,
                        "covered_contract_capacity": max(0, int(quantity // 100)),
                        "source": "ibkr_readonly_private",
                        "exact_quantity_included": False,
                    },
                    "periods": {},
                    "suggestions": {},
                }
            )

    if write_output:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        atomic_write_json(output_dir / f"options_ibkr_{timestamp}.json", results)
        atomic_write_json(output_dir / "options_latest.json", results)
    return results


def main() -> int:
    try:
        results = fetch_all_options_ibkr()
    except (IbkrReadOnlyError, FileNotFoundError, ValueError) as exc:
        logger.error("IBKR option adapter failed: %s", exc)
        return 1
    for result in results:
        print(f"{result.get('ticker')}: {result.get('status')}")
        for period, value in (result.get("periods") or {}).items():
            print(
                f"  {period}: {value.get('status')} expiry={value.get('expiration')} "
                f"dte={value.get('actual_dte')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
