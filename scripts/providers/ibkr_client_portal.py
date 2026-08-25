#!/usr/bin/env python3
"""Loopback-only read access to IBKR Client Portal Gateway.

This module deliberately exposes no order, instruction, exercise, transfer,
funding or account-mutation methods. Raw account identifiers, exact quantities,
cost basis and P&L stay in memory and must never be persisted by callers.
"""
from __future__ import annotations

import ipaddress
import logging
import time
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

ALLOWED_GET_PREFIXES = (
    "iserver/auth/status",
    "portfolio/accounts",
    "portfolio/",
    "iserver/secdef/strikes",
    "iserver/secdef/info",
    "iserver/marketdata/snapshot",
)
ALLOWED_POST_PATHS = {"iserver/secdef/search"}
FORBIDDEN_PATH_TOKENS = (
    "/orders",
    "/order",
    "/transfer",
    "/funding",
    "/withdraw",
    "/deposit",
    "/exercise",
    "/reply/",
)


class IbkrReadOnlyError(RuntimeError):
    """Read-only provider failure with sensitive details removed."""


@dataclass(frozen=True)
class IbkrTarget:
    ticker: str
    search_symbol: str
    provider_symbol: str
    currency: str
    preferred_listing_exchange: str | None = None
    preferred_option_exchange: str | None = None


@dataclass(frozen=True)
class UnderlyingDefinition:
    ticker: str
    conid: int
    currency: str
    listing_exchange: str | None
    option_exchange: str | None
    option_months: tuple[str, ...]


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    text = str(value).strip().replace(",", "")
    # Client Portal may prefix prices with a status letter or suffix percentages.
    if text.endswith("%"):
        text = text[:-1]
    while text and text[0] not in "+-.0123456789":
        text = text[1:]
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def safe_int(value: Any) -> int | None:
    number = safe_float(value)
    return None if number is None else int(number)


def _is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_loopback_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise IbkrReadOnlyError("IBKR gateway URL must use HTTPS")
    if not _is_loopback(parsed.hostname):
        raise IbkrReadOnlyError("IBKR provider accepts loopback gateways only")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}".rstrip("/")


def _sections(value: Any) -> set[str]:
    result: set[str] = set()
    if not isinstance(value, list):
        return result
    for item in value:
        raw = (
            item.get("secType") or item.get("security_type")
            if isinstance(item, dict)
            else item
        )
        if raw:
            result.add(str(raw).upper())
    return result


def _option_months(value: Any) -> tuple[str, ...]:
    months: list[str] = []
    if not isinstance(value, list):
        return ()
    for item in value:
        if not isinstance(item, dict):
            continue
        sec_type = str(item.get("secType") or item.get("security_type") or "").upper()
        if sec_type != "OPT":
            continue
        raw = item.get("months")
        if isinstance(raw, str):
            months.extend(part.strip() for part in raw.replace(",", ";").split(";") if part.strip())
    return tuple(dict.fromkeys(months))


def _account_ids(document: Any) -> list[str]:
    if isinstance(document, list):
        rows = document
    elif isinstance(document, dict) and isinstance(document.get("accounts"), list):
        rows = document["accounts"]
    else:
        rows = []
    result: list[str] = []
    for row in rows:
        if isinstance(row, str):
            value = row
        elif isinstance(row, dict):
            value = row.get("accountId") or row.get("id") or row.get("account")
        else:
            value = None
        if value:
            result.append(str(value))
    return list(dict.fromkeys(result))


def _position_symbol(record: dict[str, Any]) -> str:
    for key in ("ticker", "symbol", "contractDesc", "contract_description", "description"):
        raw = record.get(key)
        if raw:
            return str(raw).split(" ", 1)[0].split("@", 1)[0].strip().upper()
    return ""


def _position_quantity(record: dict[str, Any]) -> float | None:
    for key in ("position", "quantity", "pos"):
        value = safe_float(record.get(key))
        if value is not None:
            return value
    return None


class IbkrClientPortalReadOnly:
    def __init__(
        self,
        *,
        base_url: str,
        verify_tls: bool = False,
        timeout_seconds: float = 20.0,
        snapshot_retry_count: int = 3,
        snapshot_retry_delay_seconds: float = 1.0,
        maximum_position_pages_per_account: int = 20,
    ) -> None:
        self.base_url = validate_loopback_base_url(base_url)
        self.verify_tls = bool(verify_tls)
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.snapshot_retry_count = max(1, int(snapshot_retry_count))
        self.snapshot_retry_delay_seconds = max(0.0, float(snapshot_retry_delay_seconds))
        self.maximum_position_pages_per_account = max(1, int(maximum_position_pages_per_account))
        if not self.verify_tls:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {"Accept": "application/json", "User-Agent": "InvestorIntelligence-ReadOnly/1"}
        )

    @staticmethod
    def _validate_path(method: str, path: str) -> str:
        normalized = path.strip().lstrip("/")
        lowered = f"/{normalized.casefold()}"
        if any(token in lowered for token in FORBIDDEN_PATH_TOKENS):
            raise IbkrReadOnlyError("Forbidden IBKR endpoint requested")
        if method == "GET" and any(normalized.startswith(prefix) for prefix in ALLOWED_GET_PREFIXES):
            return normalized
        if method == "POST" and normalized in ALLOWED_POST_PATHS:
            return normalized
        raise IbkrReadOnlyError("Endpoint is outside the read-only IBKR allowlist")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        operation: str,
    ) -> Any:
        normalized = self._validate_path(method, path)
        response = self.session.request(
            method,
            f"{self.base_url}/{normalized}",
            params=params,
            json=json_body,
            timeout=(5, self.timeout_seconds),
            verify=self.verify_tls,
        )
        if not 200 <= response.status_code < 300:
            raise IbkrReadOnlyError(
                f"IBKR read-only {operation} failed: HTTP {response.status_code}; "
                "authenticate the local gateway and verify market-data permissions"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise IbkrReadOnlyError(f"IBKR {operation} returned invalid JSON") from exc

    def require_authenticated(self) -> None:
        document = self._request("GET", "iserver/auth/status", operation="authentication status")
        if not isinstance(document, dict) or not document.get("authenticated") or not document.get("connected", True):
            raise IbkrReadOnlyError("IBKR Client Portal Gateway is not authenticated and connected")

    def account_ids(self) -> list[str]:
        document = self._request("GET", "portfolio/accounts", operation="account discovery")
        result = _account_ids(document)
        if not result:
            raise IbkrReadOnlyError("IBKR account discovery returned no accessible accounts")
        return result

    def positions(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for account_id in self.account_ids():
            for page in range(self.maximum_position_pages_per_account):
                document = self._request(
                    "GET",
                    f"portfolio/{account_id}/positions/{page}",
                    operation="position retrieval",
                )
                rows = document.get("positions") if isinstance(document, dict) else document
                if not isinstance(rows, list) or not rows:
                    break
                clean = [row for row in rows if isinstance(row, dict)]
                records.extend(clean)
                if len(clean) < 100:
                    break
        return records

    def position_quantities(self, tickers: Iterable[str]) -> dict[str, float]:
        wanted = {str(ticker).upper() for ticker in tickers}
        result = {ticker: 0.0 for ticker in wanted}
        for row in self.positions():
            symbol = _position_symbol(row)
            quantity = _position_quantity(row)
            if symbol in result and quantity is not None:
                result[symbol] += quantity
        return result

    def search_underlying(self, target: IbkrTarget) -> UnderlyingDefinition:
        document = self._request(
            "POST",
            "iserver/secdef/search",
            json_body={"symbol": target.search_symbol, "name": False, "secType": "STK"},
            operation="contract search",
        )
        rows = document if isinstance(document, list) else []
        candidates: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper()
            if symbol == target.search_symbol.upper() and "OPT" in _sections(row.get("sections")):
                candidates.append(row)
        if not candidates:
            raise IbkrReadOnlyError(f"No exact option-enabled IBKR contract found for {target.ticker}")

        def rank(row: dict[str, Any]) -> tuple[int, int]:
            exchange = str(row.get("description") or row.get("exchange") or "").upper()
            preferred = int(
                bool(target.preferred_listing_exchange)
                and str(target.preferred_listing_exchange).upper() in exchange
            )
            primary = int(str(row.get("countryCode") or row.get("country_code") or "").upper() in {"US", "SE"})
            return preferred, primary

        row = sorted(candidates, key=rank, reverse=True)[0]
        conid = safe_int(row.get("conid") or row.get("underlyingConid") or row.get("underlying_contract_id"))
        if conid is None:
            raise IbkrReadOnlyError(f"IBKR search omitted a contract id for {target.ticker}")
        sections = row.get("sections")
        option_exchange = target.preferred_option_exchange
        if not option_exchange and isinstance(sections, list):
            for item in sections:
                if not isinstance(item, dict):
                    continue
                if str(item.get("secType") or item.get("security_type") or "").upper() == "OPT":
                    option_exchange = str(item.get("exchange") or "").strip() or None
                    if option_exchange:
                        break
        return UnderlyingDefinition(
            ticker=target.ticker,
            conid=conid,
            currency=str(row.get("currency") or target.currency),
            listing_exchange=str(row.get("description") or row.get("exchange") or "").strip() or None,
            option_exchange=option_exchange,
            option_months=_option_months(sections),
        )

    def market_snapshot(self, conids: Iterable[int], fields: Iterable[str]) -> list[dict[str, Any]]:
        ids = [int(value) for value in conids]
        if not ids:
            return []
        requested = [str(value) for value in fields]
        params = {"conids": ",".join(map(str, ids)), "fields": ",".join(requested)}
        latest: list[dict[str, Any]] = []
        for attempt in range(self.snapshot_retry_count):
            document = self._request(
                "GET",
                "iserver/marketdata/snapshot",
                params=params,
                operation="market-data snapshot",
            )
            latest = [row for row in document if isinstance(row, dict)] if isinstance(document, list) else []
            if any(any(field in row for field in requested) for row in latest):
                return latest
            if attempt + 1 < self.snapshot_retry_count:
                time.sleep(self.snapshot_retry_delay_seconds)
        return latest

    def strikes(self, definition: UnderlyingDefinition, month: str) -> dict[str, list[float]]:
        params: dict[str, Any] = {"conid": definition.conid, "secType": "OPT", "month": month}
        if definition.option_exchange:
            params["exchange"] = definition.option_exchange
        document = self._request(
            "GET", "iserver/secdef/strikes", params=params, operation="option-strike retrieval"
        )
        if not isinstance(document, dict):
            return {"call": [], "put": []}

        def normalize(values: Any) -> list[float]:
            if not isinstance(values, list):
                return []
            return sorted({value for item in values if (value := safe_float(item)) is not None})

        return {
            "call": normalize(document.get("call") or document.get("calls")),
            "put": normalize(document.get("put") or document.get("puts")),
        }

    def option_contract_info(
        self,
        definition: UnderlyingDefinition,
        *,
        month: str,
        strike: float,
        right: str,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "conid": definition.conid,
            "secType": "OPT",
            "month": month,
            "strike": strike,
            "right": right.upper(),
        }
        if definition.option_exchange:
            params["exchange"] = definition.option_exchange
        document = self._request(
            "GET", "iserver/secdef/info", params=params, operation="option-contract retrieval"
        )
        if isinstance(document, list):
            return [row for row in document if isinstance(row, dict)]
        if isinstance(document, dict):
            rows = document.get("contracts")
            return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else [document]
        return []


def target_from_config(value: dict[str, Any]) -> IbkrTarget:
    return IbkrTarget(
        ticker=str(value.get("ticker") or "").upper(),
        search_symbol=str(value.get("search_symbol") or value.get("ticker") or "").upper(),
        provider_symbol=str(value.get("provider_symbol") or value.get("ticker") or ""),
        currency=str(value.get("currency") or "USD"),
        preferred_listing_exchange=str(value.get("preferred_listing_exchange")) if value.get("preferred_listing_exchange") else None,
        preferred_option_exchange=str(value.get("preferred_option_exchange")) if value.get("preferred_option_exchange") else None,
    )
