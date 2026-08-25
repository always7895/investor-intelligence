#!/usr/bin/env python3
"""Normalize and admit owner-independent public symbol requests.

This module performs no network access and stores no query history. It prepares
an on-demand public-only lookup plan that can be executed only after an official
instrument reference and a reviewed free public quote provider are available.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = ROOT / "config" / "public-symbol-admission-policy.json"


class SymbolAdmissionError(ValueError):
    """Raised when a symbol request violates a privacy or integrity boundary."""


@dataclass(frozen=True)
class PublicInstrumentReference:
    symbol: str
    exchange: str
    security_type: str
    reference_source_id: str
    reference_url: str
    active: bool
    provider_symbol: str | None = None
    currency: str | None = None


@dataclass(frozen=True)
class PublicSymbolPlan:
    symbols: tuple[str, ...]
    provider_symbols: tuple[str, ...]
    cache_keys: tuple[str, ...]
    reference_sources: tuple[str, ...]
    owner_watchlist_inherited: bool = False
    portfolio_inherited: bool = False
    broker_used: bool = False
    query_history_persisted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbols": list(self.symbols),
            "provider_symbols": list(self.provider_symbols),
            "cache_keys": list(self.cache_keys),
            "reference_sources": list(self.reference_sources),
            "owner_watchlist_inherited": False,
            "portfolio_inherited": False,
            "broker_used": False,
            "query_history_persisted": False,
        }


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise SymbolAdmissionError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SymbolAdmissionError("Public symbol policy must be an object")
    required_false = (
        "owner_watchlist_inheritance",
        "portfolio_inheritance",
        "broker_symbol_discovery",
        "popular_query_analytics",
        "cross_tenant_query_history",
        "raw_query_persistence",
        "automatic_universe_promotion",
        "tenant_identifier_in_public_cache_key",
    )
    for key in required_false:
        if value.get(key) is not False:
            raise SymbolAdmissionError(f"public symbol policy requires {key}=false")
    required_true = (
        "official_instrument_reference_required",
        "public_quote_provider_required",
        "current_data_requires_reviewed_provider",
    )
    for key in required_true:
        if value.get(key) is not True:
            raise SymbolAdmissionError(f"public symbol policy requires {key}=true")
    if value.get("mode") != "on_demand_public_only":
        raise SymbolAdmissionError("public symbol policy mode must be on_demand_public_only")
    return value


def _ascii_upper(value: object) -> str:
    # Reject the original input before any compatibility normalization. NFKC
    # would turn full-width or confusable Unicode text such as ＡＡＯＩ into ASCII
    # and could make visually deceptive input look canonical after admission.
    text = str(value or "").strip()
    if any(ord(character) > 127 for character in text):
        raise SymbolAdmissionError("Ticker must contain native ASCII characters only")
    return text.upper()


def normalize_symbol(value: object, policy: Mapping[str, Any]) -> str:
    symbol = _ascii_upper(value)
    maximum = int(policy.get("maximum_ticker_length") or 12)
    pattern = re.compile(str(policy.get("allowed_ticker_pattern") or r"^[A-Z0-9][A-Z0-9.-]{0,11}$"))
    if not symbol or len(symbol) > maximum or not pattern.fullmatch(symbol):
        raise SymbolAdmissionError(f"Invalid public ticker: {symbol!r}")
    if symbol.startswith(("HTTP", "WWW")) or ".." in symbol or "--" in symbol:
        raise SymbolAdmissionError(f"Suspicious public ticker: {symbol!r}")
    return symbol


def _reference(value: Any) -> PublicInstrumentReference:
    if isinstance(value, PublicInstrumentReference):
        return value
    if not isinstance(value, Mapping):
        raise SymbolAdmissionError("Instrument reference must be an object")
    return PublicInstrumentReference(
        symbol=str(value.get("symbol") or ""),
        exchange=str(value.get("exchange") or ""),
        security_type=str(value.get("security_type") or ""),
        reference_source_id=str(value.get("reference_source_id") or ""),
        reference_url=str(value.get("reference_url") or ""),
        active=value.get("active") is True,
        provider_symbol=(str(value.get("provider_symbol")).strip() if value.get("provider_symbol") else None),
        currency=(str(value.get("currency")).strip().upper() if value.get("currency") else None),
    )


def _validate_reference_url(raw_url: object, symbol: str) -> str:
    value = str(raw_url or "").strip()
    if not value or any(ord(character) < 32 for character in value) or "\\" in value:
        raise SymbolAdmissionError(f"Instrument reference URL is malformed for {symbol}")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise SymbolAdmissionError(f"Instrument reference URL is malformed for {symbol}") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise SymbolAdmissionError(f"Instrument reference URL must be credential-free HTTPS/443 for {symbol}")
    try:
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").casefold()
    except (UnicodeError, ValueError) as exc:
        raise SymbolAdmissionError(f"Instrument reference hostname is invalid for {symbol}") from exc
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
    ):
        raise SymbolAdmissionError(f"Instrument reference hostname is local for {symbol}")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise SymbolAdmissionError(f"Instrument reference IP is not public for {symbol}")
    decoded_path = unquote(parsed.path).replace("\\", "/")
    if any(segment in {".", ".."} for segment in decoded_path.split("/")):
        raise SymbolAdmissionError(f"Instrument reference URL contains path traversal for {symbol}")
    if any(character.isspace() for character in value):
        raise SymbolAdmissionError(f"Instrument reference URL contains whitespace for {symbol}")
    return value


def build_public_symbol_plan(
    requested_symbols: Iterable[object],
    references: Mapping[str, Any],
    *,
    reviewed_quote_provider_available: bool,
    policy: Mapping[str, Any] | None = None,
) -> PublicSymbolPlan:
    document = dict(policy or load_policy())
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in requested_symbols:
        symbol = normalize_symbol(raw, document)
        if symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    maximum = int(document.get("maximum_symbols_per_request") or 5)
    if not normalized:
        raise SymbolAdmissionError("At least one public symbol is required")
    if len(normalized) > maximum:
        raise SymbolAdmissionError(f"At most {maximum} public symbols may be requested")
    if not reviewed_quote_provider_available:
        raise SymbolAdmissionError("No reviewed public quote provider is available")

    allowed_types = {
        str(value).strip().upper()
        for value in document.get("allowed_security_types", [])
        if str(value).strip()
    }
    provider_symbols: list[str] = []
    cache_keys: list[str] = []
    source_ids: list[str] = []
    for symbol in normalized:
        raw_reference = references.get(symbol)
        if raw_reference is None:
            raise SymbolAdmissionError(f"No reviewed public instrument reference for {symbol}")
        reference = _reference(raw_reference)
        if normalize_symbol(reference.symbol, document) != symbol:
            raise SymbolAdmissionError(f"Instrument reference symbol mismatch for {symbol}")
        if not reference.active:
            raise SymbolAdmissionError(f"Instrument reference is inactive for {symbol}")
        if reference.security_type.upper() not in allowed_types:
            raise SymbolAdmissionError(
                f"Unsupported public security type for {symbol}: {reference.security_type}"
            )
        if not reference.exchange or not reference.reference_source_id:
            raise SymbolAdmissionError(f"Incomplete public instrument reference for {symbol}")
        _validate_reference_url(reference.reference_url, symbol)
        provider_symbol = normalize_symbol(reference.provider_symbol or symbol, document)
        provider_symbols.append(provider_symbol)
        cache_keys.append(f"public:options:{symbol}")
        source_ids.append(reference.reference_source_id)

    return PublicSymbolPlan(
        symbols=tuple(normalized),
        provider_symbols=tuple(provider_symbols),
        cache_keys=tuple(cache_keys),
        reference_sources=tuple(source_ids),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*")
    parser.add_argument(
        "--validate-policy",
        action="store_true",
        help="Validate policy only; no instrument/reference input is required",
    )
    args = parser.parse_args()
    try:
        policy = load_policy()
        if args.validate_policy:
            print(json.dumps({"policy_valid": True, "mode": policy["mode"]}, sort_keys=True))
            return 0
        # CLI deliberately cannot execute a lookup without an externally reviewed
        # reference set/provider. This prevents accidental live activation.
        raise SymbolAdmissionError(
            "CLI lookup is disabled; use build_public_symbol_plan with reviewed references"
        )
    except (FileNotFoundError, SymbolAdmissionError) as exc:
        print(f"PUBLIC SYMBOL ADMISSION FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
