"""V11 W2: previous-session carry-forward of covered-call suggestions (operator 2026-10-13, A2).

Real callers: `builder.main` (the producer CLI the refresh runs, with a fake yfinance module and a patched clock) and the real sealer
`publish_sealed_snapshot.lazy_market_bodies` (tests/fixtures/v11_options_carry_cases.py). The catalog policy is the test copy of the pinned
operator-accepted entry (tests/fixtures/v11_operator_accepted_options.py). No network, no write outside a temporary folder.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import option_recommendation_rules as rules  # noqa: E402
import options_carry_forward as carry  # noqa: E402
import public_options_provider_gate as gate  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
from tests.fixtures import v11_operator_accepted_options as support  # noqa: E402
from tests.fixtures import v11_options_carry_cases as cases  # noqa: E402
from tests.fixtures.v11_options_carry_cases import GOOD_ROWS, IN_SESSION, ITM_ROWS, OFF_SESSION, ZERO_ROWS, chains  # noqa: E402
from validate_v213_market_products import MarketProductValidationError, validate_covered_call_cycle  # noqa: E402

UTC = timezone.utc
STAMP_IN = "2026-10-13T15:00:00Z"
WEEKLY, MONTHLY = "2026-10-16", "2026-11-13"


class Harness(unittest.TestCase):
    """One temporary folder per test; run_main drives the real producer CLI with a fake yfinance module at a fixed instant."""

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory(prefix="v11_carry_")
        self.addCleanup(self._folder.cleanup)
        self.folder = Path(self._folder.name)
        self.output = self.folder / "market_quotes_options.json"
        self.state = self.folder / "options_carry_forward.json"
        self.policy = support.yahoo_policy()

    def run_main(self, now: datetime, rows_by_symbol: dict[str, list[Any]], *extra: str, policy: Any = None, price: float = 100.0):
        return cases.run_main(self.output, now, rows_by_symbol, self.policy if policy is None else policy, *extra, price=price)

    def state_document(self) -> dict[str, Any]:
        return json.loads(self.state.read_text(encoding="utf-8"))

    def seal(self, now: datetime, policy: Any = None) -> dict[str, Any]:
        return cases.seal_options(self.output, now, self.policy if policy is None else policy)["options"]


class SessionClockTests(unittest.TestCase):
    def test_the_regular_us_session_bounds_use_the_new_york_clock_and_dst(self) -> None:
        cases = [
            (datetime(2026, 10, 13, 13, 29, tzinfo=UTC), False), (datetime(2026, 10, 13, 13, 30, tzinfo=UTC), True),   # 09:30 EDT
            (datetime(2026, 10, 13, 19, 59, tzinfo=UTC), True), (datetime(2026, 10, 13, 20, 0, tzinfo=UTC), False),    # 16:00 EDT
            (datetime(2026, 12, 15, 14, 29, tzinfo=UTC), False), (datetime(2026, 12, 15, 14, 30, tzinfo=UTC), True),   # 09:30 EST
            (datetime(2026, 12, 15, 20, 59, tzinfo=UTC), True), (datetime(2026, 12, 15, 21, 0, tzinfo=UTC), False),    # 16:00 EST
            (datetime(2026, 10, 17, 15, 0, tzinfo=UTC), False), (datetime(2026, 10, 18, 15, 0, tzinfo=UTC), False),    # Saturday, Sunday
            (datetime(2026, 10, 12, 15, 0, tzinfo=UTC), True), (datetime(2026, 10, 16, 15, 0, tzinfo=UTC), True),      # Monday, Friday
        ]
        for moment, expected in cases:
            self.assertIs(rules.us_regular_session_open(moment), expected, moment.isoformat())
        self.assertEqual(rules.US_SESSION_OPEN_LOCAL_MINUTES, 570)
        self.assertEqual(rules.EXPIRY_DAY_CLOSE_LOCAL_MINUTES["US"], 960)


class CarryThroughTheProducerTests(Harness):
    def in_session_run(self, **extra: Any):
        return self.run_main(IN_SESSION, chains(GOOD_ROWS), **extra)

    def test_a_chain_without_any_valid_quote_carries_the_last_in_session_cycle(self) -> None:
        code, status, live = self.in_session_run()
        self.assertEqual(code, 0, status)
        self.assertEqual(status["carry_forward"], {"state_entries": 0, "captured": 24, "carried": 0})
        self.assertEqual(live["options"]["T00"]["weekly"]["quote_basis"], "delayed")
        self.assertEqual({key: live["options"]["T00"]["weekly"][key] for key in support.IDENTITY}, support.IDENTITY)
        self.assertEqual(live["options"]["T00"]["weekly"]["rights_status"], "operator_accepted_unlicensed")
        stored = self.state_document()
        self.assertEqual((stored["schema"], sorted(stored), len(stored["cycles"])), ("v213-options-carry-v1", ["cycles", "generated_at", "schema"], 12))

        code, status, off = self.run_main(OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
        self.assertEqual(code, 0, status)
        self.assertEqual(status["carry_forward"]["carried"], 20)  # T00..T09, weekly and monthly
        for symbol in (f"T{index:02d}" for index in range(10)):
            for period, expiry in (("weekly", WEEKLY), ("monthly", MONTHLY)):
                carried = off["options"][symbol][period]
                original = live["options"][symbol][period]
                self.assertEqual(carried["quote_basis"], "previous_session_last", (symbol, period))
                self.assertEqual((carried["expiry"], carried["timestamp"], carried["spot"], carried["dte"], carried["asof_date"]),
                                 (expiry, STAMP_IN, 100.0, original["dte"], "2026-10-13"))
                self.assertEqual({key: value for key, value in carried.items() if key != "quote_basis"},
                                 {key: value for key, value in original.items() if key != "quote_basis"})  # nothing recomputed or modelled
                validate_covered_call_cycle(carried, evaluated_at=OFF_SESSION, document_at=off["generated_at"], period=period, allow_previous_session=True)
        # The document clock is the new run's; the carried rows keep the capture's own instant (never relabelled as fresh).
        self.assertEqual(off["generated_at"], "2026-10-13T21:30:00Z")
        # A live chain that IS two-sided but yields no suggestion is a live answer and is never replaced by an older capture.
        for symbol in ("GOOD0", "GOOD1"):
            self.assertIn("unavailable", off["options"][symbol]["weekly"])
            self.assertNotIn("無有效雙邊報價", off["options"][symbol]["weekly"]["unavailable"])

    def test_a_live_valid_cycle_always_wins_over_the_carried_one(self) -> None:
        self.in_session_run()
        old_state = self.state.read_bytes()
        code, status, off = self.run_main(OFF_SESSION, chains(ZERO_ROWS, T05=GOOD_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
        self.assertEqual(code, 0, status)
        live = off["options"]["T05"]["weekly"]
        self.assertEqual((live["quote_basis"], live["timestamp"]), ("delayed", "2026-10-13T21:30:00Z"))
        self.assertEqual(off["options"]["T04"]["weekly"]["quote_basis"], "previous_session_last")
        self.assertEqual(self.state.read_bytes(), old_state)  # an off-session run never rewrites the capture state

    def test_the_capture_is_replaced_only_by_a_newer_in_session_capture(self) -> None:
        self.in_session_run()
        later = IN_SESSION + timedelta(hours=2)
        self.run_main(later, chains(GOOD_ROWS), price=101.0)
        stored = self.state_document()["cycles"]["T00"]["weekly"]
        self.assertEqual((stored["timestamp"], stored["spot"]), ("2026-10-13T17:00:00Z", 101.0))
        _, _, off = self.run_main(OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
        self.assertEqual((off["options"]["T00"]["weekly"]["timestamp"], off["options"]["T00"]["weekly"]["spot"]), ("2026-10-13T17:00:00Z", 101.0))

    def test_never_carried_another_expiry_a_capture_older_than_four_days_or_one_that_is_expired(self) -> None:
        self.in_session_run()
        # Saturday exactly four days after the capture: the monthly expiry is still the selected one and is carried; the weekly choice has
        # rolled to next week's expiry, so the capture (another expiry) is not carried.
        saturday = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
        _, _, document = self.run_main(saturday, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
        self.assertEqual(document["options"]["T00"]["monthly"]["quote_basis"], "previous_session_last")
        self.assertIn("unavailable", document["options"]["T00"]["weekly"])
        self.assertNotEqual(document["options"]["T00"]["weekly"].get("expiry"), WEEKLY)
        # Six hours later the capture is older than four days: nothing is carried.
        _, _, document = self.run_main(saturday + timedelta(hours=6), chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
        for period in ("weekly", "monthly"):
            self.assertIn("unavailable", document["options"]["T00"][period])

    def test_a_malformed_or_foreign_state_file_carries_nothing(self) -> None:
        self.in_session_run()
        good = self.state_document()
        broken = {
            "wrong schema": {**good, "schema": "v213-options-carry-v2"},
            "unknown top key": {**good, "note": "x"},
            "missing key": {key: value for key, value in good.items() if key != "generated_at"},
            "cycles not an object": {**good, "cycles": []},
        }
        for name, document in broken.items():
            with self.subTest(name):
                self.state.write_text(json.dumps(document), encoding="utf-8")
                _, _, off = self.run_main(OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
                self.assertIn("unavailable", off["options"]["T00"]["weekly"])
        for name, text in (("invalid json", "{not json"), ("empty", ""), ("array", "[]")):
            with self.subTest(name):
                self.state.write_text(text, encoding="utf-8")
                _, _, off = self.run_main(OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
                self.assertIn("unavailable", off["options"]["T00"]["weekly"])
        with self.subTest("oversize"):
            self.state.write_text(json.dumps({**good, "pad": "x" * carry.MAX_STATE_BYTES}), encoding="utf-8")
            _, _, off = self.run_main(OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
            self.assertIn("unavailable", off["options"]["T00"]["weekly"])

    def test_tampered_entries_are_dropped_one_by_one_and_never_trusted(self) -> None:
        self.in_session_run()
        good = self.state_document()

        def tamper(name: str, mutate) -> None:
            document = copy.deepcopy(good)
            mutate(document["cycles"]["T00"]["weekly"])
            self.state.write_text(json.dumps(document), encoding="utf-8")
            _, _, off = self.run_main(OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
            self.assertIn("unavailable", off["options"]["T00"]["weekly"], name)
            self.assertEqual(off["options"]["T00"]["monthly"]["quote_basis"], "previous_session_last", name)  # the healthy sibling survives
            self.assertEqual(off["options"]["T01"]["weekly"]["quote_basis"], "previous_session_last", name)

        tamper("limit above mid", lambda c: c["suggestions"][0].__setitem__("limit_price", c["suggestions"][0]["ask"] + 1))
        tamper("derived yield", lambda c: c["suggestions"][0].__setitem__("annualized_yield", 9.9))
        tamper("strike in the money", lambda c: c["suggestions"][0].__setitem__("strike", 90.0))
        tamper("unknown cycle key", lambda c: c.__setitem__("extra", 1))
        tamper("unknown suggestion key", lambda c: c["suggestions"][0].__setitem__("extra", 1))
        tamper("another ticker", lambda c: c.__setitem__("ticker", "T01"))
        tamper("capture not in session", lambda c: c.__setitem__("timestamp", "2026-10-13T13:00:00Z"))  # 09:00 New York
        tamper("capture on a weekend", lambda c: c.__setitem__("timestamp", "2026-10-10T15:00:00Z"))
        tamper("foreign provider", lambda c: c.__setitem__("provider_id", "occ_public_market_data"))
        tamper("already carried basis", lambda c: c.__setitem__("quote_basis", "previous_session_last"))
        tamper("no identity", lambda c: c.pop("provider_id"))

    def test_the_catalog_must_admit_the_capture_and_the_carried_basis_itself(self) -> None:
        # No policy that admits Yahoo (the repository catalog before the operator entry, or after a revert): nothing is captured or carried.
        empty = gate.PublicOptionPolicy({})
        code, status, _ = self.run_main(IN_SESSION, chains(GOOD_ROWS), policy=empty)
        self.assertEqual((code, status["carry_forward"]["captured"]), (0, 0))
        self.assertFalse(self.state.exists())
        # Captured under a policy, then the catalog stops admitting the carried basis (its own scope removed): not carried.
        self.in_session_run()
        document = support.catalog_document()
        next(item for item in document["providers"] if item["id"] == support.YAHOO_ID)["admitted_scopes"].pop()  # drop previous_session_last
        with support.catalog_root(document) as root:
            delayed_only = gate.load_public_option_policy(root, today=support.TODAY)
        self.assertIsNone(gate.public_option_cycle_admission({**support.IDENTITY, "quote_basis": "delayed"}, delayed_only))
        self.assertEqual(gate.public_option_cycle_admission({**support.IDENTITY, "quote_basis": "previous_session_last"}, delayed_only),
                         gate.OPTION_RIGHTS_NOT_ADMITTED)
        _, status, off = self.run_main(OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS), policy=delayed_only)
        self.assertEqual(status["carry_forward"]["carried"], 0)
        self.assertIn("unavailable", off["options"]["T00"]["weekly"])
        # The catalog admits everything again: carried.
        _, status, off = self.run_main(OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
        self.assertEqual(status["carry_forward"]["carried"], 20)

    def test_a_rejected_run_leaves_the_state_alone_and_no_carry_flag_disables_everything(self) -> None:
        self.in_session_run()
        before = self.state.read_bytes()
        # A depleted off-session run (every chain zero-bid, no healthy one) is rejected by the existing coverage guard: nothing is written.
        code, status, _ = self.run_main(OFF_SESSION, chains(ZERO_ROWS))
        self.assertEqual((code, status["error"]), (1, "OPTION_TWO_SIDED_COVERAGE_LOW"))
        self.assertEqual(self.state.read_bytes(), before)
        _, status, off = self.run_main(OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS), "--no-carry")
        self.assertNotIn("carry_forward", status)
        self.assertIn("unavailable", off["options"]["T00"]["weekly"])
        self.assertEqual(self.state.read_bytes(), before)

    def test_state_path_defaults_next_to_the_output_and_can_be_overridden(self) -> None:
        self.in_session_run()
        self.assertTrue(self.state.exists())
        elsewhere = self.folder / "elsewhere" / "state.json"
        self.run_main(IN_SESSION, chains(GOOD_ROWS), "--carry-state", str(elsewhere))
        self.assertTrue(elsewhere.exists())
        env_path = self.folder / "env" / "state.json"
        with mock.patch.dict(os.environ, {carry.STATE_ENV: str(env_path)}):
            self.run_main(IN_SESSION, chains(GOOD_ROWS))
        self.assertTrue(env_path.exists())
        self.assertEqual(carry.default_state_path(self.output), self.folder / carry.STATE_FILE_NAME)
        self.assertEqual(carry.default_state_path(), ROOT / "data" / "cache" / carry.STATE_FILE_NAME)
        self.assertEqual(list(self.folder.rglob("*.tmp")), [])  # atomic writes leave no staging file

    def test_a_failed_state_write_never_blocks_the_run_or_corrupts_the_old_state(self) -> None:
        self.in_session_run()
        before = self.state.read_bytes()
        with mock.patch.object(Path, "replace", side_effect=OSError("disk full")):
            self.assertFalse(self._saved_after_capture(IN_SESSION + timedelta(hours=1)))
        self.assertEqual(self.state.read_bytes(), before)

    def _saved_after_capture(self, now: datetime) -> bool:
        state = carry.CarryForward(self.state, policy=self.policy)
        state.load(now)
        state.dirty = True
        return state.save(now)

    def test_the_sealer_validates_the_carried_basis_and_the_coverage_page_never_counts_it(self) -> None:
        self.in_session_run()
        self.run_main(OFF_SESSION, chains(ZERO_ROWS, GOOD0=ITM_ROWS, GOOD1=ITM_ROWS))
        sealed = self.seal(OFF_SESSION + timedelta(minutes=5))
        carried = sealed["T00"]["weekly"]
        self.assertEqual((carried["quote_basis"], carried["timestamp"], carried["provider_id"]), ("previous_session_last", STAMP_IN, support.YAHOO_ID))
        body = json.dumps({"schema": "v213-options-v2", "generated_at": "2026-10-13T21:30:00Z", "options": sealed}, separators=(",", ":"))
        rows, link = publisher._coverage_observed(body, self.policy, OFF_SESSION + timedelta(minutes=5))
        self.assertEqual(rows, [])  # carried rows are not live observations; GOOD0/GOOD1 and T00..T09 yield none
        self.assertIsNotNone(link)
        # The same row without the sealer's opt-in is refused by the shared validator (coverage and every format-only caller).
        with self.assertRaises(MarketProductValidationError):
            validate_covered_call_cycle(carried, evaluated_at=OFF_SESSION, document_at="2026-10-13T21:30:00Z", period="weekly")
        # A tampered carried row never reaches v213:options:v2.
        document = json.loads(self.output.read_text(encoding="utf-8"))
        document["options"]["T00"]["weekly"]["suggestions"][0]["limit_price"] = 99.0
        self.output.write_text(json.dumps(document), encoding="utf-8")
        refused = self.seal(OFF_SESSION + timedelta(minutes=5))["T00"]["weekly"]
        self.assertTrue(refused["unavailable"].startswith("報價未通過驗證"), refused)

    def test_the_live_sealed_body_still_counts_in_coverage(self) -> None:
        self.in_session_run()
        sealed = self.seal(IN_SESSION + timedelta(minutes=5))
        body = json.dumps({"schema": "v213-options-v2", "generated_at": STAMP_IN, "options": sealed}, separators=(",", ":"))
        rows, _ = publisher._coverage_observed(body, self.policy, IN_SESSION + timedelta(minutes=5))
        self.assertEqual([(row["provider_id"], row["quote_basis"], row["cycle_count"]) for row in rows], [(support.YAHOO_ID, "delayed", 24)])


class WorkerFixtureTests(unittest.TestCase):
    def test_the_committed_worker_fixture_is_byte_for_byte_the_real_producer_and_sealer_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v11_fixture_verify_") as folder:
            target = Path(folder) / "v11-options-carry.json"
            cases.write_fixture(target)
            self.assertEqual(cases.FIXTURE_PATH.read_bytes(), target.read_bytes())
        self.assertNotIn(b"\r", cases.FIXTURE_PATH.read_bytes())

    def test_the_fixture_slice_has_the_documented_shape(self) -> None:
        fixture = json.loads(cases.FIXTURE_PATH.read_text(encoding="utf-8"))
        live, after = fixture["in_session"]["options"], fixture["off_session"]["options"]
        self.assertEqual([live[t]["weekly"]["quote_basis"] for t in cases.FIXTURE_TICKERS], ["delayed"] * 3)
        for ticker in ("T00", "T01"):
            self.assertEqual(after[ticker]["weekly"]["quote_basis"], "previous_session_last")
            self.assertEqual(after[ticker]["weekly"]["timestamp"], fixture["in_session"]["generated_at"])
        self.assertEqual(list(after["GOOD0"]["weekly"]), ["unavailable"])


class CarryUnitTests(unittest.TestCase):
    """The rules on hand-built captures (expiry-day and expired contracts, the four-day bound) through CarryForward.apply."""

    def setUp(self) -> None:
        self.policy = support.yahoo_policy()

    def capture(self, expiry: str, dte: int, *, at: datetime = IN_SESSION, period: str = "weekly", week: str | None = "CURRENT") -> dict[str, Any]:
        rows = [{"strike": 115.0, "bid": 0.9, "ask": 1.0, "delta": 0.1, "iv": None, "oi": 10, "volume": 1}]
        return builder.cycle_result("T00", expiry, dte, 100.0, rows, currency="USD", source="Yahoo Finance option chain (unofficial, delayed)",
                                    provenance=f"https://finance.yahoo.com/quote/T00/options?date={expiry}", rights=builder.YAHOO_RIGHTS_LABEL,
                                    stamp=at.strftime("%Y-%m-%dT%H:%M:%SZ"), asof=rules.exchange_date(at, "US").isoformat(), week=week,
                                    identity=builder.YAHOO_OPTION_IDENTITY)

    def apply(self, cycle: dict[str, Any], now: datetime, expiry: str, period: str = "weekly") -> dict[str, Any]:
        state = carry.CarryForward(Path(tempfile.gettempdir()) / "v11-unused-state.json", policy=self.policy)  # never saved
        state.cycles, state._loaded = {"T00": {period: cycle}}, True
        unavailable = {"unavailable": f"本次回應有 {expiry}（1天）買權，但{carry.NO_TWO_SIDED_REASON}（買賣價須為正且不倒掛）"}
        options = {"T00": {period: dict(unavailable)}}
        health = [{"venue": "US", "underlying": "T00", "expiry": expiry, "cycle": period, "status": "READ", "read": True, "two_sided": False}]
        state.apply(options, health, now)
        return options["T00"][period]

    def test_an_expiry_day_capture_is_carried_until_the_close_and_never_after(self) -> None:
        cycle = self.capture("2026-10-13", 0)
        self.assertEqual(self.apply(cycle, IN_SESSION + timedelta(hours=4), "2026-10-13")["quote_basis"], "previous_session_last")  # 15:00 EDT, open
        self.assertIn("unavailable", self.apply(cycle, datetime(2026, 10, 13, 20, 0, tzinfo=UTC), "2026-10-13"))  # 16:00 EDT, closed
        self.assertIn("unavailable", self.apply(cycle, OFF_SESSION, "2026-10-13"))

    def test_an_expired_expiry_is_never_carried(self) -> None:
        cycle = self.capture("2026-10-13", 0)
        self.assertIn("unavailable", self.apply(cycle, datetime(2026, 10, 14, 15, 0, tzinfo=UTC), "2026-10-13"))
        later = self.capture("2026-10-16", 3)
        self.assertEqual(self.apply(later, datetime(2026, 10, 16, 14, 0, tzinfo=UTC), "2026-10-16")["quote_basis"], "previous_session_last")  # expiry morning
        self.assertIn("unavailable", self.apply(later, datetime(2026, 10, 17, 14, 0, tzinfo=UTC), "2026-10-16"))

    def test_the_four_day_bound_is_exact(self) -> None:
        cycle = self.capture("2026-10-23", 10, week="NEXT")
        edge = IN_SESSION + timedelta(days=4)
        self.assertEqual(self.apply(cycle, edge, "2026-10-23")["quote_basis"], "previous_session_last")
        self.assertIn("unavailable", self.apply(cycle, edge + timedelta(seconds=1), "2026-10-23"))

    def test_the_selected_expiry_must_equal_the_captured_one(self) -> None:
        cycle = self.capture("2026-10-16", 3)
        self.assertIn("unavailable", self.apply(cycle, OFF_SESSION, "2026-10-23"))

    def test_only_the_exact_no_two_sided_entry_is_replaced(self) -> None:
        cycle = self.capture("2026-10-16", 3)
        state = carry.CarryForward(Path(tempfile.gettempdir()) / "v11-unused-state.json", policy=self.policy)
        state.cycles, state._loaded = {"T00": {"weekly": cycle}}, True
        health = [{"venue": "US", "underlying": "T00", "expiry": "2026-10-16", "cycle": "weekly", "status": "READ", "read": True, "two_sided": False}]
        for entry in ({"unavailable": "2026-10-16 到期的價外買權中，沒有年化權利金達 6% 且有雙邊報價的履約價"},   # a live "no strike qualifies" answer
                      {"unavailable": "期權鏈讀取失敗"},                                                       # a read failure
                      copy.deepcopy(cycle)):                                                                    # a live valid cycle
            options = {"T00": {"weekly": entry}}
            self.assertEqual(state.apply(options, health, OFF_SESSION), 0)
            self.assertEqual(options["T00"]["weekly"], entry)
        for bad in ({**health[0], "two_sided": True}, {**health[0], "status": "EMPTY"}, {**health[0], "venue": "STOCKHOLM"},
                    {**health[0], "read": False}, {**health[0], "expiry": None}):
            options = {"T00": {"weekly": {"unavailable": f"x {carry.NO_TWO_SIDED_REASON}"}}}
            self.assertEqual(state.apply(options, [bad], OFF_SESSION), 0, bad)

    def test_unadmitted_cycles_are_never_captured(self) -> None:
        state = carry.CarryForward(Path(tempfile.gettempdir()) / "v11-unused-state.json", policy=self.policy)
        rows = [{"strike": 115.0, "bid": 0.9, "ask": 1.0, "delta": 0.1, "iv": None, "oi": 10, "volume": 1}]
        stamp = IN_SESSION.strftime("%Y-%m-%dT%H:%M:%SZ")
        nasdaq = builder.cycle_result("T00", "2026-10-16", 3, 100.0, rows, currency="USD", source="Nasdaq US option chain (fallback)",
                                      provenance="https://www.nasdaq.com/x", rights="candidate_local_review", stamp=stamp, asof="2026-10-13")
        stockholm = builder.cycle_result("T01", "2026-10-16", 3, 100.0, rows, currency="SEK", source=builder.NORDIC_SOURCE,
                                         provenance="https://api.nasdaq.com/x", rights="candidate_local_review", stamp=stamp, asof="2026-10-13")
        self.assertEqual(state.capture({"T00": {"weekly": nasdaq}, "T01.ST": {"weekly": stockholm}}, IN_SESSION), 0)
        self.assertEqual(state.cycles, {})

    def test_the_session_helper_and_validator_agree_on_what_is_in_session(self) -> None:
        pre = self.capture("2026-10-16", 3, at=datetime(2026, 10, 13, 13, 29, tzinfo=UTC))
        with self.assertRaises(MarketProductValidationError) as raised:
            validate_covered_call_cycle({**pre, "quote_basis": "previous_session_last"}, evaluated_at=OFF_SESSION,
                                        document_at="2026-10-13T21:30:00Z", period="weekly", allow_previous_session=True)
        self.assertIn("NOT_IN_SESSION", str(raised.exception))
        for field, value, code in (("currency", "SEK", "US_CAPTURE_REQUIRED"), ("asof_date", None, "US_CAPTURE_REQUIRED")):
            cycle = {**self.capture("2026-10-16", 3), "quote_basis": "previous_session_last", field: value}
            with self.assertRaises(MarketProductValidationError) as raised:
                validate_covered_call_cycle(cycle, evaluated_at=OFF_SESSION, document_at="2026-10-13T21:30:00Z", period="weekly",
                                            allow_previous_session=True)
            self.assertTrue(raised.exception.args[0], field)
        with self.assertRaises(MarketProductValidationError):  # a carried basis needs an evaluation clock
            validate_covered_call_cycle({**self.capture("2026-10-16", 3), "quote_basis": "previous_session_last"}, allow_previous_session=True)


if __name__ == "__main__":
    unittest.main()
