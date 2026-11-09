"""Explicitly synthetic, source-derived HV -> producer -> Worker regression fixtures.

No request, market assertion, publication or LINE delivery. The 61 adjusted closes
have alternating log returns: +/-8% for 40 sessions, +/-6% for the final 20.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_market_quotes_options as builder
import option_delta_model as delta_math
import option_historical_volatility as history_math
from tests.test_option_historical_volatility import raw_bytes, synthetic_chart

TODAY = date(2026, 11, 9)
STAMP = "2026-11-09T15:00:00Z"
EXPIRY = "2026-11-20"
DTE = 11
SPOT = 100.0
FIXTURE_PATH = ROOT / "cloud/test/fixtures/historical-options.json"


def inputs(currency: str = "USD") -> tuple[list[dict], list[dict], dict, bytes]:
    ticker = "SYNTH.ST" if currency == "SEK" else "SYNTH"
    chart = synthetic_chart(ticker=ticker, currency=currency)
    prices = [SPOT]
    for index in range(60):
        change = 0.08 if index < 40 else 0.06
        prices.append(prices[-1] * math.exp(change if index % 2 else -change))
    chart["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"] = prices
    raw = raw_bytes(chart)
    source = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&includeAdjustedClose=true"
    history = history_math.from_yahoo_chart(raw, ticker, currency, TODAY, source)
    assert history is not None
    calls, puts = [], []
    for strike in range(75, 126):
        if strike == SPOT:
            continue
        price = delta_math.bs_call_price if strike > SPOT else delta_math.bs_put_price
        lower, upper = price(SPOT, strike, DTE / 365, 0.25), price(SPOT, strike, DTE / 365, 1.6)
        assert lower is not None and upper is not None
        # A synthetic positive .01 bid floor; not a producer eligibility rule.
        row = {"strike": float(strike), "bid": max(0.01, lower), "ask": upper,
               "expiry": EXPIRY, "dte": DTE, "size": 100, "oi": 100, "volume": 10,
               "iv": 9.9, "delta": 0.99}
        (calls if strike > SPOT else puts).append(row)
    return calls, puts, history, raw


def produce(currency: str = "USD", *, missing_history: bool = False, one_sided: bool = False,
            tight: bool = False, mixed: bool = False) -> dict:
    calls, puts, history, _ = inputs(currency)
    if tight or mixed:
        for row in calls + puts:
            if mixed and row is not calls[0]:
                continue
            price = delta_math.bs_call_price if row["strike"] > SPOT else delta_math.bs_put_price
            fair = price(SPOT, row["strike"], DTE / 365, history["hv60"])
            assert fair is not None and fair > 0
            row.update(bid=fair * 0.99, ask=fair * 1.01)
    if one_sided:
        for row in calls + puts:
            row["ask"] = None
    identity = builder.NORDIC_OPTION_IDENTITY if currency == "SEK" else builder.YAHOO_OPTION_IDENTITY
    return builder._cycles_from_calls(
        calls, history["ticker"], SPOT, STAMP, currency=currency, source="SYNTHETIC offline option book",
        provenance="https://synthetic.invalid/options", rights="operator_accepted_unlicensed", missing="synthetic missing expiry",
        venue="STOCKHOLM" if currency == "SEK" else "US", today=TODAY, identity=identity, puts=puts,
        historical_volatility=None if missing_history or tight else history)["monthly"]


def document() -> dict:
    return {"note": "SYNTHETIC source-derived HV and quotes; not market data or publication authority", "stamp": STAMP,
            "cases": {"usd_wide": produce(), "sek_wide": produce("SEK"), "tight": produce(tight=True),
                      "missing_history": produce(missing_history=True), "one_sided": produce(one_sided=True),
                      "mixed": produce(mixed=True)}}


if __name__ == "__main__":
    FIXTURE_PATH.write_bytes((json.dumps(document(), ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    print("Wrote explicitly synthetic historical option fixture")
