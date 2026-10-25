"""V13 item 3b harness and the committed Worker fixture `cloud/test/fixtures/v13-nordic-options.json`.

The fixture is a slice of what the REAL producer (`builder.main` with the retained-shape Nasdaq Nordic transport and a fake yfinance module, a patched
clock and no network, via tests/fixtures/options_nonus_publisher_cases.py) and the REAL sealer (`publish_sealed_snapshot.lazy_market_bodies`, no
admission seam) emit for a Stockholm run beside US siblings, under the test copy of the two pinned operator-accepted catalog entries
(tests/fixtures/v11_operator_accepted_options.py). The prices are SYNTHETIC; the shape is the producer's. The clock is Monday 2026-10-19, after
the Nordic decision day 2026-10-17. Regenerate with `python -m tests.fixtures.v13_nordic_options_cases`; a test pins byte equality.
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

FIXTURE_PATH = ROOT / "cloud" / "test" / "fixtures" / "v13-nordic-options.json"
UTC = timezone.utc
WORLD_TODAY = date(2026, 10, 19)                           # Monday; the exchange-local date in Stockholm and New York
RUN_AT = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)         # 10:00 Stockholm
SEAL_AT = RUN_AT + timedelta(minutes=5)
SIVE = "SIVE.ST"
US_SIBLING = "SYNTHUS00"
FIXTURE_TICKERS = (SIVE, US_SIBLING)


def specs() -> list[dict[str, Any]]:
    """SIVE.ST with a weekly (4 DTE) and a monthly (28 DTE) qualifying call, plus ten healthy US siblings (the producer needs at least ten quotes) (Yahoo identity)."""
    sive = nonus.st(SIVE, [nonus.qualifying_row("SIVE", 4, 13.7), nonus.qualifying_row("SIVE", 28, 13.7)], spot=13.7)
    return [sive, *nonus.healthy_us(10)]


def produce_and_seal(policy: Any) -> dict[str, Any]:
    """The real producer CLI at the fixed instant, then the real sealer under `policy`: the sealed v213:options:v2 object."""
    with mock.patch.object(nonus, "TODAY", WORLD_TODAY), tempfile.TemporaryDirectory(prefix="v13_nordic_fixture_") as folder:
        output = Path(folder) / "market_quotes_options.json"
        # nonus.run_main parses the producer's status line, which is cut at 1500 characters once SIVE.ST carries two full cycles: run main directly.
        with nonus._sealed_world(specs(), RUN_AT, []), contextlib.redirect_stdout(io.StringIO()):
            rc = builder.main(["--output", str(output), "--no-carry"])
        assert rc == 0 and output.exists(), rc
        with mock.patch.object(gate, "load_public_option_policy", return_value=policy):
            bodies = publisher.lazy_market_bodies(output, SEAL_AT)
    return json.loads(bodies["v213:options:v2"])


def generate_fixture_document() -> dict[str, Any]:
    both = produce_and_seal(support.both_policy())
    for period in ("weekly", "monthly"):
        cycle = both["options"][SIVE][period]
        assert "unavailable" not in cycle and cycle["provider_id"] == support.NORDIC_ID and cycle["quote_basis"] == "delayed", cycle
    assert both["options"][US_SIBLING]["monthly"]["provider_id"] == support.YAHOO_ID

    def keep(document: dict[str, Any]) -> dict[str, Any]:
        return {"generated_at": document["generated_at"], "options": {ticker: document["options"][ticker] for ticker in FIXTURE_TICKERS}}
    return {
        "schema": "v13-nordic-options-fixture-v1",
        "description": ("A slice (SIVE.ST and one US sibling) of the sealed v213:options:v2 object that the real producer and the real sealer emit for a "
                        "Stockholm run under a catalog carrying both pinned operator-accepted providers: SIVE.ST claims the Nasdaq Nordic identity with "
                        "quote_basis delayed, the US sibling the Yahoo identity. SYNTHETIC prices, real shape."),
        "operator_decision": support.NORDIC_DECISION_ID,
        "both": keep(both),
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
    print(f"V13 Nordic fixture written: {out} ({out.stat().st_size} bytes)")
