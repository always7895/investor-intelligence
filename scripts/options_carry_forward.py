#!/usr/bin/env python3
"""Previous-session carry-forward for covered-call suggestions (operator 2026-10-13, answer A2 "use the last quote of the previous session").

Outside the regular US session Yahoo returns zero bid and ask, so a chain without any valid two-sided quote reads "no valid
two-sided quote for the selected expiry" although the same expiry had a full set of suggestions during the last session. This module
keeps a small state file with the LAST VALID IN-SESSION cycle per ticker and period and, only when the current chain has no valid
two-sided quote for the selected expiry, replaces that unavailable entry by the captured cycle with the distinct quote basis
`previous_session_last` (the capture's own timestamp, spot, dte and asof_date are kept; the Worker labels it with the capture time).

Never carried: a capture for another expiry than the one now selected, an expired expiry (the New York date; on its expiry day only
before the close), a capture that was not taken inside a regular US session (weekday 09:30-16:00 New York), a capture older than four
days, a capture whose claimed identity the rights catalog does not admit under the carried basis, or one that fails the shared
covered-call validator. A live valid cycle is never replaced (only the exact "no valid two-sided quote" entry is). No new KV key: the
carried cycle sits in the same `v213:options:v2` slot as a live one. A reader that does not know the basis refuses it (it only reads
quote_basis "delayed"), so an old Worker fails closed.

State file: closed schema, validated on read (a malformed file or entry is dropped, never trusted), written atomically next to the
options cache by default (--carry-state or V213_OPTIONS_CARRY_STATE override it; tests and local runs point it into their own folder).
"""
from __future__ import annotations

import copy
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import option_recommendation_rules as rules
import public_options_provider_gate as option_rights
from validate_v213_market_products import (
    CARRIED_MAX_AGE_SECONDS,
    CARRIED_QUOTE_BASIS,
    MarketProductValidationError,
    validate_covered_call_cycle,
)

ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = "v213-options-carry-v1"
STATE_FILE_NAME = "options_carry_forward.json"
STATE_ENV = "V213_OPTIONS_CARRY_STATE"
MAX_STATE_BYTES = 8_000_000
PERIODS = ("weekly", "monthly")
# The producer's reason for a chain read without any valid two-sided quote (scripts/build_market_quotes_options.py us_options builds the
# message from this fragment, and only an entry carrying it, selected-expiry health included, may be replaced).
NO_TWO_SIDED_REASON = "所選到期無有效雙邊報價"
# The covered-call cycles the producer admits for carrying are the Yahoo US chains it claims the catalog identity for.
CARRIED_PROVIDER_ID = "yahoo_finance_option_chain"
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{0,15}$")  # US keys only: no dotted (other-market) keys
CYCLE_KEYS = frozenset({
    "ticker", "strategy", "expiry", "dte", "spot", "currency", "multiplier", "quote_basis", "timestamp", "source", "provenance",
    "rights_status", "provider_id", "jurisdiction", "venue", "instrument_kind", "publication_scope", "suggestions", "middle_suggestion",
    "asof_date", "weekly_week", "strategies",
})
REQUIRED_CYCLE_KEYS = CYCLE_KEYS - {"middle_suggestion", "weekly_week", "strategies"}
SUGGESTION_KEYS = frozenset({
    "role", "strike", "bid", "ask", "mid", "limit_price", "premium_per_contract", "period_yield", "annualized_yield", "upside_to_strike",
    "delta", "delta_basis", "iv", "oi", "volume", "spread_pct",
})


def default_state_path(output: Path | None = None) -> Path:
    """The state file: V213_OPTIONS_CARRY_STATE, else next to the options cache file (data/cache by default)."""
    override = os.environ.get(STATE_ENV, "").strip()
    if override:
        return Path(override)
    return (Path(output).parent if output is not None else ROOT / "data" / "cache") / STATE_FILE_NAME


def _instant(stamp: str) -> datetime:
    return datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _closed_shape(cycle: Any) -> bool:
    """Exact key sets of a stored cycle and its suggestions (the closed state schema)."""
    if not isinstance(cycle, dict) or not REQUIRED_CYCLE_KEYS <= set(cycle) <= CYCLE_KEYS:
        return False
    suggestions = cycle.get("suggestions")
    items = [*(suggestions if isinstance(suggestions, list) else []), *([cycle["middle_suggestion"]] if "middle_suggestion" in cycle else [])]
    # V21: the optional `strategies` object is closed by the shared validator (exact key sets per block, leg and item), run on every stored cycle.
    return (bool(items) or isinstance(cycle.get("strategies"), dict)) and all(isinstance(item, dict) and set(item) == SUGGESTION_KEYS for item in items)


def _stored_cycle_ok(ticker: str, period: str, cycle: Any, now: datetime) -> bool:
    """A state entry is trusted only when it is exactly what the producer wrote for a live Yahoo cycle, was captured inside a regular
    US session no more than four days ago, is for a contract that is still listed and passes the shared validator AS CAPTURED."""
    try:
        if period not in PERIODS or not isinstance(ticker, str) or not TICKER_RE.fullmatch(ticker) or not _closed_shape(cycle):
            return False
        if cycle["ticker"] != ticker or cycle["quote_basis"] != "delayed" or cycle["provider_id"] != CARRIED_PROVIDER_ID:
            return False
        if not isinstance(cycle["timestamp"], str) or not cycle["timestamp"].endswith("Z"):
            return False
        captured = _instant(cycle["timestamp"])
        if not rules.us_regular_session_open(captured):
            return False
        if not 0 <= (now - captured).total_seconds() <= CARRIED_MAX_AGE_SECONDS:
            return False
        today = rules.exchange_date(now, "US")
        expiry = date.fromisoformat(cycle["expiry"])
        if expiry < today or (expiry == today and not rules.expiry_day_open(now, "US")):
            return False
        validate_covered_call_cycle(cycle, evaluated_at=captured, document_at=cycle["timestamp"], period=period)
        return True
    except (MarketProductValidationError, KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return False


def load_state(path: Path, now: datetime) -> dict[str, dict[str, dict[str, Any]]]:
    """The valid entries of the state file; a missing, oversize, malformed or foreign-schema file yields an empty state."""
    try:
        if path.stat().st_size > MAX_STATE_BYTES:
            return {}
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict) or set(document) != {"schema", "generated_at", "cycles"} or document["schema"] != STATE_SCHEMA \
            or not isinstance(document["cycles"], dict):
        return {}
    state: dict[str, dict[str, dict[str, Any]]] = {}
    for ticker, per_period in document["cycles"].items():
        if not isinstance(per_period, dict):
            continue
        for period, cycle in per_period.items():
            if _stored_cycle_ok(ticker, period, cycle, now):
                state.setdefault(ticker, {})[period] = cycle
    return state


class CarryForward:
    """The carry-forward state of one producer run: load, capture the live in-session cycles, carry where the live chain has none, save."""

    def __init__(self, path: Path | None = None, *, policy: Any | None = None) -> None:
        self.path = Path(path) if path is not None else default_state_path()
        self._policy = policy
        self.cycles: dict[str, dict[str, dict[str, Any]]] = {}
        self.dirty = False
        self._loaded = False
        self.summary = {"state_entries": 0, "captured": 0, "carried": 0}

    def _policy_for(self, now: datetime) -> Any:
        if self._policy is None:  # the audited canonical catalog; an empty/invalid one admits nothing, so nothing is captured or carried
            self._policy = option_rights.load_public_option_policy(today=now.astimezone(timezone.utc).date())
        return self._policy

    def load(self, now: datetime) -> None:
        self.cycles = load_state(self.path, now)
        self._loaded = True
        self.summary["state_entries"] = sum(len(per) for per in self.cycles.values())

    def capture(self, options: dict[str, Any], now: datetime) -> int:
        """Keep the live valid Yahoo cycles of an in-session run as the last in-session capture per ticker and period (the newest
        capture replaces the older one); entries that aged out or expired are dropped. Returns the number captured."""
        if not self._loaded:
            self.load(now)
        before = copy.deepcopy(self.cycles)
        for ticker in list(self.cycles):
            for period in list(self.cycles[ticker]):
                if not _stored_cycle_ok(ticker, period, self.cycles[ticker][period], now):
                    del self.cycles[ticker][period]
            if not self.cycles[ticker]:
                del self.cycles[ticker]
        captured = 0
        policy = self._policy_for(now)
        if rules.us_regular_session_open(now):
            for ticker, per_period in options.items():
                if not isinstance(per_period, dict):
                    continue
                for period in PERIODS:
                    cycle = per_period.get(period)
                    if not isinstance(cycle, dict) or "unavailable" in cycle or cycle.get("provider_id") != CARRIED_PROVIDER_ID:
                        continue
                    if option_rights.public_option_cycle_admission(cycle, policy) is not None or not _stored_cycle_ok(ticker, period, cycle, now):
                        continue
                    self.cycles.setdefault(ticker, {})[period] = copy.deepcopy(cycle)
                    captured += 1
        self.dirty = self.dirty or self.cycles != before
        self.summary["captured"] = captured
        return captured

    def _carried(self, ticker: str, period: str, expiry: str, now: datetime) -> dict[str, Any] | None:
        captured = self.cycles.get(ticker, {}).get(period)
        if captured is None or captured.get("expiry") != expiry or not _stored_cycle_ok(ticker, period, captured, now):
            return None
        carried = copy.deepcopy(captured)
        carried["quote_basis"] = CARRIED_QUOTE_BASIS
        for block in (carried.get("strategies") or {}).values():  # V21: a block's label follows its cycle's basis
            if isinstance(block, dict) and "quote_basis" in block:
                block["quote_basis"] = CARRIED_QUOTE_BASIS
        try:
            if option_rights.public_option_cycle_admission(carried, self._policy_for(now)) is not None:
                return None
            validate_covered_call_cycle(carried, evaluated_at=now, document_at=_iso(now), period=period, allow_previous_session=True)
        except (MarketProductValidationError, TypeError, ValueError, KeyError, AttributeError, OverflowError):
            return None
        return carried

    def apply(self, options: dict[str, Any], health: Iterable[dict[str, Any]], now: datetime) -> int:
        """Replace each Yahoo cycle whose chain was READ without any valid two-sided quote by the last in-session capture of the same
        ticker, period and expiry. Anything else (a live valid cycle, another unavailable reason, another expiry) is left untouched."""
        if not self._loaded:
            self.load(now)
        carried = 0
        for item in health:
            if not (isinstance(item, dict) and item.get("venue") == "US" and item.get("status") == "READ" and item.get("read") is True
                    and item.get("two_sided") is False and item.get("cycle") in PERIODS and isinstance(item.get("expiry"), str)
                    and isinstance(item.get("underlying"), str)):
                continue
            ticker, period = item["underlying"], item["cycle"]
            per_period = options.get(ticker)
            live = per_period.get(period) if isinstance(per_period, dict) else None
            if not (isinstance(live, dict) and set(live) == {"unavailable"} and NO_TWO_SIDED_REASON in str(live["unavailable"])):
                continue  # a live valid cycle, or a different reason, always wins
            replacement = self._carried(ticker, period, item["expiry"], now)
            if replacement is not None:
                per_period[period] = replacement
                carried += 1
        self.summary["carried"] = carried
        return carried

    def update(self, options: dict[str, Any], health: Iterable[dict[str, Any]], now: datetime) -> dict[str, int]:
        """One producer run: capture the live cycles first, then carry where the live chain has none."""
        self.load(now)
        self.capture(options, now)
        self.apply(options, list(health), now)
        return dict(self.summary)

    def save(self, now: datetime) -> bool:
        """Atomic write of the state when it changed; a write failure never blocks the run. Returns whether a file was written."""
        if not self.dirty:
            return False
        document = {"schema": STATE_SCHEMA, "generated_at": _iso(now), "cycles": self.cycles}
        try:
            body = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_bytes(body)
            temp.replace(self.path)
        except (OSError, ValueError):
            return False
        self.dirty = False
        return True
