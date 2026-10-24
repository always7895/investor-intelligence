"""V21 synthetic option chains WITH the put side, one per provider shape (Yahoo option_chain().puts, Nasdaq US p_* fields, Nasdaq Nordic put rows).

The prices are SYNTHETIC: Black-Scholes at spot 100, 28 days, volatility 0.30, rounded to the cent with a 0.04 spread (the literals are pinned here
so a test does not re-derive them from the code under test). The shape of each provider is the retained one (tests/fixtures/v19_nasdaq_us_options_cases.py,
tests/test_build_market_quotes_options.py). Run date 2026-09-30, monthly expiry 2026-10-28 (28 DTE).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from datetime import date, timedelta
from typing import Any

SPOT = 100.0
TODAY = date(2026, 9, 30)
STAMP = "2026-09-30T17:00:00Z"
DTE = 28
EXPIRY = (TODAY + timedelta(days=DTE)).isoformat()   # 2026-10-28
IV = 0.30

# (strike, bid, ask): absolute put delta 0.029 .. 0.374 and call delta 0.347 .. 0.099 (see the module note).
CALLS = [(104.0, 1.83, 1.87), (105.0, 1.53, 1.57), (106.0, 1.28, 1.32), (107.0, 1.05, 1.09), (108.0, 0.86, 0.90), (110.0, 0.56, 0.60), (112.0, 0.36, 0.40)]
PUTS = [(86.0, 0.08, 0.12), (88.0, 0.17, 0.21), (90.0, 0.33, 0.37), (92.0, 0.59, 0.63), (94.0, 0.98, 1.02), (95.0, 1.23, 1.27),
        (96.0, 1.52, 1.56), (98.0, 2.23, 2.27)]


class _Table:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def itertuples(self):
        return iter(self._rows)


def yahoo_chain(calls: list[tuple] = CALLS, puts: list[tuple] | None = PUTS, *, iv: float = IV) -> types.SimpleNamespace:
    """What yfinance returns: .calls and .puts tables with strike, bid, ask, impliedVolatility, openInterest, volume."""
    def table(rows):
        return _Table([types.SimpleNamespace(strike=k, bid=b, ask=a, impliedVolatility=iv, openInterest=100, volume=10,
                                            contractSize="REGULAR", currency="USD") for k, b, a in rows])
    chain = types.SimpleNamespace(calls=table(calls))
    if puts is not None:
        chain.puts = table(puts)
    return chain


def yahoo_module(chain: types.SimpleNamespace, expiry: str = EXPIRY) -> types.SimpleNamespace:
    ticker = types.SimpleNamespace(options=[expiry], option_chain=lambda e: chain)
    return types.SimpleNamespace(Ticker=lambda s: ticker)


def nasdaq_rows(calls: list[tuple] = CALLS, puts: list[tuple] | None = PUTS, expiry: str = EXPIRY) -> list[dict[str, Any]]:
    """The retained Nasdaq US shape: an `expirygroup` header per expiry, then one row per strike carrying c_* and p_* fields."""
    day = date.fromisoformat(expiry)
    rows: list[dict[str, Any]] = [{"expirygroup": f"{day.strftime('%B')} {day.day}, {day.year}"}]
    put_by_strike = {k: (b, a) for k, b, a in (puts or [])}
    for strike in sorted({k for k, _, _ in calls} | set(put_by_strike)):
        row: dict[str, Any] = {"expirygroup": "", "strike": f"{strike:.2f}"}
        call = next(((b, a) for k, b, a in calls if k == strike), None)
        row.update({"c_Bid": f"{call[0]:.2f}" if call else "--", "c_Ask": f"{call[1]:.2f}" if call else "--", "c_Openinterest": "50", "c_Volume": "5"})
        if puts is not None:
            put = put_by_strike.get(strike)
            text = lambda value: f"{value:.2f}" if isinstance(value, (int, float)) and value == value else "--"  # noqa: E731
            row.update({"p_Bid": text(put[0]) if put else "--", "p_Ask": text(put[1]) if put else "--", "p_Openinterest": "60", "p_Volume": "6"})
        rows.append(row)
    return rows


def nasdaq_payload(rows: list[dict[str, Any]], asof: date = TODAY - timedelta(days=1)) -> dict[str, Any]:
    return {"data": {"lastTrade": f"LAST TRADE: $100.00 (AS OF {asof.strftime('%b').upper()} {asof.day}, {asof.year})", "table": {"rows": rows}}}


def nordic_row(kind: str, strike: float, bid: float, ask: float, *, root: str = "SIVE", expiry: str = EXPIRY, **override: Any) -> dict[str, Any]:
    """A Nasdaq Nordic option row. Calls: 'SIVE 28OCT26 107C' / native 'SIVE6J107' (October = J); puts: 'SIVE 28OCT26 94P' / native 'SIVE6V94' (October = V)."""
    day = date.fromisoformat(expiry)
    text = f"{strike:g}"
    letters = "ABCDEFGHIJKL" if kind == "C" else "MNOPQRSTUVWX"
    row = {"fullName": f"{root} {day.day:02d}{day.strftime('%b').upper()}{day.year % 100:02d} {text}{kind}", "orderbookId": f"OB{kind}{text}",
           "symbol": f"{root}{day.year % 10}{letters[day.month - 1]}{text}", "expirationDate": expiry, "strikePrice": f"{strike:.2f}",
           "contractSize": "100", "bidPrice": f"{bid:.2f}", "askPrice": f"{ask:.2f}", "openInterest": "40", "volume": "4",
           "assetClass": "OPTIONS", "currency": "SEK"}
    row.update(override)
    return row


def nordic_rows(calls: list[tuple] = CALLS, puts: list[tuple] | None = PUTS) -> list[dict[str, Any]]:
    return [nordic_row("C", k, b, a) for k, b, a in calls] + [nordic_row("P", k, b, a) for k, b, a in (puts or [])]


def bs_chain(dte: int, *, spot: float = SPOT, iv: float = IV, half_spread: float = 0.02) -> tuple[list[tuple], list[tuple]]:
    """A synthetic chain for any DTE (calls above, puts below the spot, strikes 1.00 apart): Black-Scholes prices of the producer's own model, so
    the deltas land in the bands at every maturity. Used for the weekly, the carry-forward and the size tests, never to pin a number."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import build_market_quotes_options as builder
    years = max(dte, 1) / 365
    calls, puts = [], []
    for strike in range(int(spot * 0.75), int(spot * 1.25) + 1):
        strike = float(strike)
        if strike > spot:
            price = builder.bs_call_price(spot, strike, years, iv)
            if price - half_spread > 0.0:
                calls.append((strike, round(price - half_spread, 2), round(price + half_spread, 2)))
        elif strike < spot:
            price = builder.bs_put_price(spot, strike, years, iv)
            if price - half_spread > 0.0:
                puts.append((strike, round(price - half_spread, 2), round(price + half_spread, 2)))
    return calls, puts
