"""V19 harness and the committed Worker fixture `cloud/test/fixtures/v19-nasdaq-us-options.json`.

The fixture is a slice of what the REAL producer (`builder.main` with a retained-shape Nasdaq US option-chain transport, Yahoo forced to fail for one
ticker, a fake yfinance module, a patched clock and no network, via tests/fixtures/options_nonus_publisher_cases.py) and the REAL sealer
(`publish_sealed_snapshot.lazy_market_bodies`, no admission seam) emit under the test copy of the three pinned operator-accepted catalog entries
(tests/fixtures/v11_operator_accepted_options.py). The prices are SYNTHETIC; the shape is the producer's. The clock is Monday 2026-10-19, the
decision day. Regenerate with `python -m tests.fixtures.v19_nasdaq_us_options_cases`; a test pins byte equality.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import public_options_provider_gate as gate  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
from tests.fixtures import options_nonus_publisher_cases as nonus  # noqa: E402
from tests.fixtures import v11_operator_accepted_options as support  # noqa: E402

FIXTURE_PATH = ROOT / "cloud" / "test" / "fixtures" / "v19-nasdaq-us-options.json"
UTC = timezone.utc
WORLD_TODAY = date(2026, 10, 19)                           # Monday; the exchange-local date in New York
RUN_AT = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)        # 10:00 New York
SEAL_AT = RUN_AT + timedelta(minutes=5)
NASDAQ_TICKER = "SYNTHNQ00"                                # Yahoo fails here: the Nasdaq US chain answers
US_SIBLING = "SYNTHUS00"                                   # Yahoo answers
FIXTURE_TICKERS = (NASDAQ_TICKER, US_SIBLING)
WEEKLY_DTE, MONTHLY_DTE = 4, 28


def last_trade(day: date) -> str:
    return f"LAST TRADE: $100.00 (AS OF {day.strftime('%b').upper()} {day.day}, {day.year})"


def nasdaq_rows(spot: float = 100.0) -> list[dict[str, Any]]:
    """The retained shape: an `expirygroup` header row per expiry, then strike rows with c_Bid, c_Ask and c_Openinterest."""
    rows: list[dict[str, Any]] = []
    for dte in (WEEKLY_DTE, MONTHLY_DTE):
        strike, bid, ask = nonus.qualifying(spot, dte)
        day = WORLD_TODAY + timedelta(days=dte)
        rows.append({"expirygroup": f"{day.strftime('%B')} {day.day}, {day.year}"})
        rows.append({"expirygroup": "", "strike": f"{strike:.2f}", "c_Bid": f"{bid:.2f}", "c_Ask": f"{ask:.2f}",
                     "c_Openinterest": "--", "c_Volume": "--"})
    return rows


def nasdaq_spec(symbol: str = NASDAQ_TICKER, **extra: Any) -> dict[str, Any]:
    spec = nonus.us(symbol, {}, yahoo_error=True, nasdaq_rows=nasdaq_rows())
    spec.update(extra)
    return spec


def specs(extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """One Nasdaq-fallback ticker plus ten healthy Yahoo siblings (the producer needs at least ten quotes)."""
    return [nasdaq_spec(**(extra or {})), *nonus.healthy_us(10)]


def run_producer(spec_list: list[dict[str, Any]], directory: Path) -> tuple[int, Path]:
    output = directory / "market_quotes_options.json"
    with mock.patch.object(nonus, "TODAY", WORLD_TODAY), nonus._sealed_world(spec_list, RUN_AT, []), contextlib.redirect_stdout(io.StringIO()):
        rc = builder.main(["--output", str(output), "--no-carry"])
    return rc, output


def produce_and_seal(policy: Any, spec_list: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The real producer CLI at the fixed instant, then the real sealer under `policy`: the sealed v213:options:v2 object."""
    with tempfile.TemporaryDirectory(prefix="v19_nasdaq_us_fixture_") as folder:
        rc, output = run_producer(spec_list or specs(), Path(folder))
        assert rc == 0 and output.exists(), rc
        with mock.patch.object(gate, "load_public_option_policy", return_value=policy):
            bodies = publisher.lazy_market_bodies(output, SEAL_AT)
    return json.loads(bodies["v213:options:v2"])


def generate_fixture_document() -> dict[str, Any]:
    allowed = produce_and_seal(support.all_policy())
    for period in ("weekly", "monthly"):
        cycle = allowed["options"][NASDAQ_TICKER][period]
        assert "unavailable" not in cycle and cycle["provider_id"] == support.NASDAQ_ID and cycle["quote_basis"] == "delayed", cycle
    assert allowed["options"][US_SIBLING]["monthly"]["provider_id"] == support.YAHOO_ID

    def keep(document: dict[str, Any]) -> dict[str, Any]:
        return {"generated_at": document["generated_at"], "options": {ticker: document["options"][ticker] for ticker in FIXTURE_TICKERS}}
    return {
        "schema": "v19-nasdaq-us-options-fixture-v1",
        "description": ("A slice (one Nasdaq-fallback ticker and one Yahoo sibling) of the sealed v213:options:v2 object that the real producer and the real "
                        "sealer emit for a US run in which Yahoo fails for one ticker, under a catalog carrying all three pinned operator-accepted providers: "
                        "the fallback ticker claims the Nasdaq US identity with quote_basis delayed, the sibling the Yahoo identity. SYNTHETIC prices, real shape."),
        "operator_decision": support.NASDAQ_DECISION_ID,
        "all": keep(allowed),
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
    print(f"V19 Nasdaq US fixture written: {out} ({out.stat().st_size} bytes)")
