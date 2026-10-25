"""V11 W2 harness and the committed Worker fixture `cloud/test/fixtures/v11-options-carry.json`.

The fixture is a slice of what the REAL producer (`builder.main`, a fake yfinance module with a patched clock and no network) and the REAL
sealer (`publish_sealed_snapshot.lazy_market_bodies`) emit for one in-session and one after-hours run, under the test copy of the pinned
operator-accepted catalog entry (tests/fixtures/v11_operator_accepted_options.py). The prices are SYNTHETIC (a fixed chain per scenario);
the shape is the producer's. Regenerate with `python -m tests.fixtures.v11_options_carry_cases`; a test pins byte equality.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import public_options_provider_gate as gate  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
from tests.fixtures import v11_operator_accepted_options as support  # noqa: E402

FIXTURE_PATH = ROOT / "cloud" / "test" / "fixtures" / "v11-options-carry.json"
UTC = timezone.utc
IN_SESSION = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)    # Tuesday 11:00 New York (EDT)
OFF_SESSION = datetime(2026, 10, 13, 21, 30, tzinfo=UTC)  # Tuesday 17:30 New York, after the close (Yahoo quotes read zero)
EXPIRIES = ["2026-10-16", "2026-10-23", "2026-11-13", "2026-11-20"]

CallRow = namedtuple("CallRow", ["strike", "bid", "ask", "impliedVolatility", "openInterest", "volume", "lastPrice"])
GOOD_ROWS = [CallRow(115.0, 0.90, 1.00, 0.35, 120, 15, 0.95), CallRow(110.0, 1.40, 1.50, 0.35, 200, 30, 1.45),
             CallRow(105.0, 2.40, 2.50, 0.35, 300, 40, 2.45)]
ZERO_ROWS = [CallRow(row.strike, 0.0, 0.0, row.impliedVolatility, row.openInterest, 0, row.lastPrice) for row in GOOD_ROWS]  # the after-hours read
ITM_ROWS = [CallRow(80.0, 20.1, 20.3, 0.5, 10, 1, 20.2)]  # one two-sided in-the-money row: a healthy chain without any suggestion
US_SYMBOLS = [f"T{index:02d}" for index in range(10)] + ["GOOD0", "GOOD1"]
FIXTURE_TICKERS = ("T00", "T01", "GOOD0")


class _Calls:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def itertuples(self):
        return iter(self._rows)


class _Chain:
    def __init__(self, rows: list[Any]) -> None:
        self.calls = _Calls(rows)


class _Ticker:
    def __init__(self, rows: list[Any], price: float) -> None:
        self.fast_info = {"lastPrice": price, "previousClose": price - 1, "currency": "USD"}
        self.options = list(EXPIRIES)
        self._rows = rows

    def option_chain(self, _expiry: str) -> _Chain:
        return _Chain(self._rows)


class FakeYahoo:
    """The yfinance module surface the producer uses (Ticker.fast_info, .options, .option_chain(expiry).calls.itertuples())."""

    def __init__(self, rows_by_symbol: dict[str, list[Any]], price: float = 100.0) -> None:
        self._tickers = {symbol: _Ticker(rows, price) for symbol, rows in rows_by_symbol.items()}

    def Ticker(self, symbol: str) -> _Ticker:  # noqa: N802 - the yfinance API name
        return self._tickers[symbol]


def chains(default: list[Any], **overrides: list[Any]) -> dict[str, list[Any]]:
    return {symbol: overrides.get(symbol, default) for symbol in US_SYMBOLS}


def run_main(output: Path, now: datetime, rows_by_symbol: dict[str, list[Any]], policy: Any, *extra: str, price: float = 100.0):
    """The real producer CLI at a fixed instant with a fake yfinance module: (exit code, status JSON, the written document or None)."""
    stack = contextlib.ExitStack()
    with stack:
        stack.enter_context(mock.patch.object(builder, "utc_now", lambda: now))
        stack.enter_context(mock.patch.object(builder, "universe", lambda: []))
        stack.enter_context(mock.patch.object(builder, "broad_universe", lambda _now: {"us": list(rows_by_symbol), "sweden": {}}))
        stack.enter_context(mock.patch.object(builder, "alpha_vantage_quote", lambda *_a, **_k: None))
        stack.enter_context(mock.patch.object(builder, "alpha_vantage_key", lambda: None))
        stack.enter_context(mock.patch.object(builder, "http_json", mock.Mock(side_effect=AssertionError("NETWORK_FORBIDDEN"))))
        stack.enter_context(mock.patch.dict(sys.modules, {"yfinance": FakeYahoo(rows_by_symbol, price)}))
        stack.enter_context(mock.patch.object(gate, "load_public_option_policy", return_value=policy))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = builder.main(["--output", str(output), *extra])
    status = json.loads(buffer.getvalue().strip().splitlines()[-1])
    document = json.loads(output.read_text(encoding="utf-8")) if code == 0 else None
    return code, status, document


def seal_options(output: Path, now: datetime, policy: Any) -> dict[str, Any]:
    """The real sealer's v213:options:v2 body for the written observations file."""
    with mock.patch.object(gate, "load_public_option_policy", return_value=policy):
        bodies = publisher.lazy_market_bodies(output, now)
    return json.loads(bodies["v213:options:v2"])


def generate_fixture_document() -> dict[str, Any]:
    policy = support.yahoo_policy()
    with tempfile.TemporaryDirectory(prefix="v11_carry_fixture_") as folder:
        output = Path(folder) / "market_quotes_options.json"
        code, status, _ = run_main(output, IN_SESSION, chains(GOOD_ROWS), policy)
        assert code == 0 and status["carry_forward"]["captured"] == 24, status
        in_session = seal_options(output, IN_SESSION + timedelta(minutes=5), policy)
        code, status, _ = run_main(output, OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS), policy)
        assert code == 0 and status["carry_forward"]["carried"] == 20, status
        off_session = seal_options(output, OFF_SESSION + timedelta(minutes=5), policy)

    def keep(document: dict[str, Any]) -> dict[str, Any]:
        return {"generated_at": document["generated_at"], "options": {ticker: document["options"][ticker] for ticker in FIXTURE_TICKERS}}
    return {
        "schema": "v11-options-carry-fixture-v1",
        "description": ("A slice (T00, T01, GOOD0) of the sealed v213:options:v2 object that the real producer and sealer emit for an in-session run "
                        "(live Yahoo cycles with the claimed catalog identity) and the following after-hours run (T00/T01 chains read zero bid/ask and "
                        "carry the last in-session cycle with quote_basis previous_session_last; GOOD0 is a healthy chain without a suggestion and "
                        "stays an honest live unavailable). SYNTHETIC prices, real shape."),
        "operator_decision": support.DECISION_ID,
        "in_session": keep(in_session),
        "off_session": keep(off_session),
    }


def encode_fixture(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_fixture(path: Path | None = None) -> Path:
    target = path or FIXTURE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode_fixture(generate_fixture_document()))
    return target


if __name__ == "__main__":
    out = write_fixture()
    print(f"V11 carry fixture written: {out} ({out.stat().st_size} bytes)")
