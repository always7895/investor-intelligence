"""Deterministic, offline producer->consumer bridge fixtures for OPTIONS-GLOBAL-01 (amendment-02).

The single source of truth for `cloud/test/fixtures/options-global-publisher.json`. It drives the *real* publisher
`scripts.publish_sealed_snapshot.lazy_market_bodies` at a fixed synthetic clock and records the exact emitted body
strings for `v213:options:v2` and `v213:quotes:v1`, plus per-case metadata. The Python test regenerates these bodies in
temp files and asserts they equal the committed JSON byte-for-byte; the Worker test seals and consumes the same emitted
strings verbatim (never a reconstructed DTO). No network, auth or sockets: `lazy_market_bodies` performs no I/O beyond
reading the temp file, and generation runs under a socket guard that fails closed on any connect attempt.

Case matrix (all TSM.monthly unless the period column says otherwise; GOOD.monthly and the quote object are healthy
controls that must survive every rejection):
  healthy / stale-row / invalid-row / calendar-rollover row / future row / exact 5h / just beyond 5h /
  expired / impossible expiry / fractional DTE / expiry-DTE mismatch / malformed suggestion shapes /
  weekly DTE bucket boundaries / source-calendar monthly dates and unproven-expiry guards /
  actual-evaluation-now vs outer document time / row-after-document /
  I2 optional nonfinite (raw JSON exponent 1e309) on oi, volume and spread_pct /
  I2a optional big-integer (raw JSON 10**309) on oi, volume and spread_pct.

Generator source inputs deliberately contain the raw JSON number 1e309 (exponent -> inf) and a bare big-integer literal
10**309 (a Python int whose float() overflows) for the I2/I2a negatives; the *published* output never contains either
because the shared validator translates both representations to the per-cycle domain error and the cycle becomes
explicitly unavailable while the healthy GOOD sibling and the quote object survive.
Regenerate the committed fixture with:  python tests/fixtures/options_global_publisher_cases.py
"""
from __future__ import annotations

import copy
import json
import socket
import sys
import tempfile
from calendar import Calendar, FRIDAY
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import option_delta_model as delta_math  # noqa: E402
import option_delta_side_model as side_math  # noqa: E402

FIXTURE_PATH = ROOT / "cloud" / "test" / "fixtures" / "options-global-publisher.json"
BRIDGE_SCHEMA = "options-global-publisher-bridge-v1"

# Fixed synthetic evaluation clock and the outer document time used by the base and bucket cases.
NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
CLOCK = "2026-09-30T12:00:00Z"
BASE_GENERATED_AT = "2026-09-30T11:59:00Z"
BASE_ROW_STAMP = "2026-09-30T11:30:00Z"

SPOT = 300.0
LIMIT = 2.05
STRIKE = 330.0
QUOTES = {"TSM": {"symbol": "TSM", "price": 300.0, "currency": "USD", "asof": BASE_ROW_STAMP,
                  "source": "Yahoo Finance (unofficial, delayed)", "source_url": "https://finance.yahoo.com/quote/TSM"}}


def standard_monthly_expiry(year: int, month: int) -> date:
    """Independent test calendar: select the third Friday from the month's actual weeks."""
    fridays = [week[FRIDAY] for week in Calendar().monthdayscalendar(year, month) if week[FRIDAY]]
    return date(year, month, fridays[2])


def _expiry(dte: int) -> str:
    return (NOW + timedelta(days=int(dte))).date().isoformat()


def _cycle(ticker: str, dte: int, expiry: str, timestamp: str = BASE_ROW_STAMP) -> dict:
    # Synthetic fixed-price book: derive its one coherent model at this case's tenor.
    analysis = side_math.calculate_side(
        [{"strike": STRIKE, "bid": 2.0, "ask": 2.1}], SPOT, max(dte, 0), None)
    assert len(analysis["computed"]) == 1, analysis["reason"]
    leg = analysis["computed"][0]
    return {
        "ticker": ticker, "strategy": "COVERED_CALL", "expiry": expiry, "dte": dte, "spot": SPOT,
        "currency": "USD", "multiplier": 100, "quote_basis": "delayed", "timestamp": timestamp,
        "source": "Yahoo Finance (unofficial, delayed)", "provenance": "https://finance.yahoo.com/quote/TSM/options",
        "rights_status": "unadmitted_third_party",
        "delta_model": "E1|Q,0,-|-,0,-",
        "suggestions": [{
            "role": "HIGH_STRIKE", "strike": STRIKE, "bid": 2.0, "ask": 2.1, "mid": 2.05, "limit_price": LIMIT,
            "premium_per_contract": LIMIT * 100, "period_yield": LIMIT / SPOT,
            "annualized_yield": LIMIT / SPOT * 365 / max(dte, 1), "upside_to_strike": STRIKE / SPOT - 1,
             "delta": leg["delta"], "delta_basis": leg["delta_basis"], "iv": leg["iv"], "oi": 900, "volume": 50, "spread_pct": 0.0488,
        }],
    }


def _base_tsm() -> dict:
    expiry = standard_monthly_expiry(2026, 10)
    return _cycle("TSM", (expiry - NOW.date()).days, expiry.isoformat())


def _good(timestamp: str = BASE_ROW_STAMP) -> dict:
    row = _base_tsm()
    row.update(ticker="GOOD", timestamp=timestamp)
    return row


@contextmanager
def _no_network():
    """Fail closed on any socket connect during generation; restore afterwards so the guard is scoped to this block."""
    saved_create = socket.create_connection
    saved_connect = socket.socket.connect

    def blocked(*_a, **_kw):
        raise AssertionError("NETWORK_FORBIDDEN")

    socket.create_connection = blocked  # type: ignore[assignment]
    socket.socket.connect = blocked  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.create_connection = saved_create  # type: ignore[assignment]
        socket.socket.connect = saved_connect  # type: ignore[assignment]


def _emit(tsm_period: str, tsm_row, generated_at: str, overflow_field: str | None = None, good_stamp: str = BASE_ROW_STAMP):
    """Build one input document, drive the real publisher, and return (options_body, quotes_body)."""
    from publish_sealed_snapshot import lazy_market_bodies

    doc = {
        "schema": "v213-market-observations-v2", "generated_at": generated_at,
        "quotes": copy.deepcopy(QUOTES),
        "options": {"TSM": {tsm_period: tsm_row}, "GOOD": {"monthly": _good(good_stamp)}},
    }
    text = json.dumps(doc, ensure_ascii=False)
    if overflow_field is not None:
        # Inject the raw JSON number 1e309 for the chosen optional field (float('inf') -> "Infinity" -> "1e309").
        text = text.replace("Infinity", "1e309")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        handle.write(text)
        path = Path(handle.name)
    try:
        bodies = lazy_market_bodies(path, NOW)
    finally:
        path.unlink(missing_ok=True)
    return bodies.get("v213:options:v2", ""), bodies.get("v213:quotes:v1", "")


def _cases():
    """Ordered (name, period, tsm_row, generated_at, overflow_field, good_stamp) tuples covering the full matrix."""
    out: list[tuple[str, str, dict, str, str | None, str]] = []

    # Base monthly matrix: patch one field of a healthy row.
    def patched(**patch) -> dict:
        row = _base_tsm()
        row.update({k: v for k, v in patch.items() if k != "suggestions"})
        if "suggestions" in patch:
            row["suggestions"] = patch["suggestions"]
        return row

    base = [
        ("healthy", {}),
        ("stale_row", {"timestamp": "2020-01-01T00:00:00Z"}),
        ("invalid_row", {"timestamp": "not-a-time"}),
        ("rollover_row", {"timestamp": "2026-02-30T12:00:00Z"}),
        ("future_row", {"timestamp": "2026-09-30T12:00:01Z"}),
        ("edge_5h", {"timestamp": "2026-09-30T07:00:00Z"}),
        ("beyond_5h", {"timestamp": "2026-09-30T06:59:59Z"}),
        ("expired", {"expiry": "2026-09-29"}),
        ("impossible_expiry", {"expiry": "2026-02-30"}),
        ("fractional_dte", {"dte": 21.5}),
        ("expiry_dte_mismatch", {"expiry": "2026-10-07"}),
        ("suggestions_null_entry", {"suggestions": [None]}),
        ("suggestions_object", {"suggestions": {}}),
    ]
    for name, patch in base:
        out.append((name, "monthly", patched(**patch), BASE_GENERATED_AT, None, BASE_ROW_STAMP))

    # Weekly outer bounds remain 0-14. Monthly admission also requires a proven
    # standard date, without a minimum DTE; arbitrary offsets are not healthy monthly controls.
    for dte in (2, 3, 14, 15, 21):
        out.append((f"weekly_dte_{dte}", "weekly", _cycle("TSM", dte, _expiry(dte)), BASE_GENERATED_AT, None, BASE_ROW_STAMP))
    # Keep the shared Worker clock fixed: its reachable third Fridays are 16,
    # 51 and 79 days away. Exact 0/60-day boundaries use shifted clocks in unit tests.
    for month in (10, 11, 12):
        expiry = standard_monthly_expiry(2026, month)
        dte = (expiry - NOW.date()).days
        out.append((f"monthly_dte_{dte}", "monthly", _cycle("TSM", dte, expiry.isoformat()), BASE_GENERATED_AT, None, BASE_ROW_STAMP))
    for dte in (0, 2, 6):
        out.append((f"monthly_unproven_dte_{dte}", "monthly", _cycle("TSM", dte, _expiry(dte)), BASE_GENERATED_AT, None, BASE_ROW_STAMP))
    false_standard = _cycle("TSM", 21, _expiry(21))
    false_standard["monthly_rule"] = "THIRD_FRIDAY"
    out.append(("monthly_false_standard", "monthly", false_standard, BASE_GENERATED_AT, None, BASE_ROW_STAMP))

    # Actual evaluation-now (not the outer document time) is used; a row later than the document is rejected. The GOOD
    # sibling carries a timestamp valid against that case's shifted document so it stays a genuine healthy control.
    out.append(("actual_now_not_doc", "monthly", patched(timestamp="2026-09-30T06:59:59Z"), "2026-09-30T09:00:00Z", None, "2026-09-30T08:30:00Z"))
    out.append(("row_after_document", "monthly", _base_tsm(), "2026-09-30T11:24:59Z", None, "2026-09-30T11:20:00Z"))

    # I2: a raw JSON exponent 1e309 optional field rejects only that cycle; GOOD sibling and the quote object survive.
    for field in ("oi", "volume", "spread_pct"):
        row = _base_tsm()
        row["suggestions"][0][field] = float("inf")  # serialized to Infinity, rewritten to raw JSON 1e309
        out.append((f"overflow_{field}", "monthly", row, BASE_GENERATED_AT, field, BASE_ROW_STAMP))

    # I2a: a raw JSON big-integer (10**309) optional field must also reject only that cycle -- via the translated float()
    # OverflowError, never an uncaught crash. The int serializes to a bare JSON integer literal and is read back as a
    # Python int (no exponent), the representation the 1e309 exponent case cannot exercise. overflow_field stays None:
    # no text rewrite is needed because json.dumps already emits the big-integer literal directly.
    for field in ("oi", "volume", "spread_pct"):
        row = _base_tsm()
        row["suggestions"][0][field] = 10 ** 309
        out.append((f"bigint_{field}", "monthly", row, BASE_GENERATED_AT, None, BASE_ROW_STAMP))

    return out


def generate_bridge() -> dict:
    """Regenerate the full bridge structure from the real publisher under a no-network guard."""
    cases: dict[str, dict] = {}
    with _no_network():
        for name, period, row, generated_at, overflow_field, good_stamp in _cases():
            options_body, quotes_body = _emit(period, row, generated_at, overflow_field, good_stamp)
            doc = json.loads(options_body) if options_body else {}
            tsm = doc.get("options", {}).get("TSM", {}).get(period, {})
            good = doc.get("options", {}).get("GOOD", {}).get("monthly", {})
            admitted = isinstance(tsm, dict) and "suggestions" in tsm
            cases[name] = {
                "period": period,
                "query_ticker": "TSM",
                "admitted": admitted,
                "sibling_healthy": isinstance(good, dict) and "suggestions" in good,
                "options_body": options_body,
                "quotes_body": quotes_body,
            }
    return {
        "schema": BRIDGE_SCHEMA,
        "clock": CLOCK,
        "note": "Real lazy_market_bodies emitted bodies; regenerate with tests/fixtures/options_global_publisher_cases.py.",
        "cases": cases,
    }


def serialize(bridge: dict) -> str:
    return json.dumps(bridge, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    # CLI generation opts into exactly the same synthetic-only seam as the reproducibility test.
    # generate_bridge itself keeps real rights-NONE behavior for the denial regressions.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tests.synthetic_option_admission import synthetic_option_admission
    with synthetic_option_admission({"TSM", "GOOD"}):
        text = serialize(generate_bridge())
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"WROTE {FIXTURE_PATH} ({len(text.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
