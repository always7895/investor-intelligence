"""V21 (operator 2026-10-19): covered call + cash-secured put + collar on every weekly and monthly cycle, conservative first; floor 2%.

PRODUCER half: put parsing for the three providers (Yahoo option_chain().puts, Nasdaq US p_* fields, Nasdaq Nordic put rows), the
strategy selection and arithmetic, fail-closed negatives, the Python validators, carry-forward, block-level degradation in the sealer and the
size of the options object. Synthetic chains only (tests/fixtures/v21_put_chains.py); no network.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import option_recommendation_rules as rules  # noqa: E402
import options_carry_forward as carry  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
from tests.fixtures import v11_operator_accepted_options as support  # noqa: E402
from tests.fixtures import v21_put_chains as chains  # noqa: E402
from tests.synthetic_option_admission import synthetic_option_admission  # noqa: E402
from validate_v213_market_products import (  # noqa: E402
    MarketProductValidationError, degrade_bad_strategy_blocks, validate_covered_call_cycle, validate_strategy_block)

UTC = timezone.utc
SPOT, TODAY, STAMP, EXPIRY = chains.SPOT, chains.TODAY, chains.STAMP, chains.EXPIRY


def validate(cycle: dict, stamp: str = STAMP) -> None:
    validate_covered_call_cycle(cycle, evaluated_at=stamp, document_at=stamp, period="monthly")


def yahoo_cycle(chain=None, spot: float = SPOT) -> dict:
    with mock.patch.dict(sys.modules, {"yfinance": chains.yahoo_module(chain or chains.yahoo_chain())}):
        return builder.us_options("AAA", spot, TODAY, STAMP)["monthly"]


def nasdaq_cycle(rows=None, asof: date | None = None) -> dict:
    payload = chains.nasdaq_payload(rows if rows is not None else chains.nasdaq_rows(), *( [asof] if asof else []))
    with mock.patch.object(builder, "http_json", lambda url: payload):
        return builder.nasdaq_us_options("AAA", SPOT, TODAY, STAMP)["monthly"]


def nordic_cycle(rows, spot: float = SPOT):
    with mock.patch.object(builder, "http_json", lambda url: {"data": {"instrumentListing": {"rows": rows}}}):
        return builder.nordic_options("SIVE.ST", "SIVE", spot, TODAY, STAMP, "TX1", spot_currency="SEK")


class FloorTests(unittest.TestCase):
    def test_the_floor_is_two_percent_and_the_boundary_is_inclusive_on_the_bid(self) -> None:
        self.assertEqual(builder.MIN_ANNUALIZED_YIELD, 0.02)
        # spot 100, 30 DTE: a bid of 0.16 pays 1.947% annualized (refused), 0.17 pays 2.068% (accepted); the old floor refused both
        for bid, ask, expected in ((0.16, 0.17, 0), (0.17, 0.18, 1)):
            row = {"strike": 110.0, "bid": bid, "ask": ask, "delta": 0.10, "iv": None, "oi": 1, "volume": 1}
            self.assertEqual(len(builder.covered_call_suggestions([row], 100.0, 30)), expected, bid)
        exact = {"strike": 110.0, "bid": 0.1644, "ask": 0.17, "delta": 0.10, "iv": None, "oi": 1, "volume": 1}
        self.assertEqual(len(builder.covered_call_suggestions([exact], 100.0, 30)), 1)  # 0.1644 / 100 * 365 / 30 = 2.0003%

    def test_dte_zero_and_a_wide_spread_keep_their_rules_under_the_new_floor(self) -> None:
        for bid, ask, expected in ((0.01, 0.011, 1), (0.005, 0.006, 0)):  # DTE 0 annualizes over one day: 0.01 -> 3.65%, 0.005 -> 1.825%
            row = {"strike": 105.0, "bid": bid, "ask": ask, "delta": 0.10, "iv": None, "oi": 1, "volume": 1}
            self.assertEqual(len(builder.covered_call_suggestions([row], 100.0, 0)), expected, bid)
        wide = {"strike": 105.0, "bid": 0.30, "ask": 0.60, "delta": 0.10, "iv": None, "oi": 1, "volume": 1}  # spread 67% of mid: still tradeable
        self.assertEqual(builder.covered_call_suggestions([wide], 100.0, 30)[0]["limit_price"], 0.37)
        self.assertEqual(builder.covered_call_suggestions([{**wide, "ask": 0.90}], 100.0, 30), [])  # spread over 100% of mid: refused


class PutParsingTests(unittest.TestCase):
    def test_yahoo_puts_become_csp_and_collar_blocks_with_the_exact_arithmetic(self) -> None:
        cycle = yahoo_cycle()
        validate(cycle)
        self.assertEqual(len(cycle["suggestions"]), 2)
        strategies = cycle["strategies"]
        self.assertEqual(list(strategies), ["csp", "collar"])  # cc is absent because the covered call exists
        csp, collar = strategies["csp"], strategies["collar"]
        label = {"rights_status": "operator_accepted_unlicensed", "provider_id": "yahoo_finance_option_chain", "quote_basis": "delayed", "timestamp": STAMP}
        for block in (csp, collar):
            self.assertEqual({key: block[key] for key in label}, label)
        first, second = csp["suggestions"]
        self.assertEqual((first["role"], first["strike"], first["delta"], first["delta_basis"]), ("CONSERVATIVE", 94.0, 0.205, "QUOTED_IV"))
        self.assertEqual((first["bid"], first["ask"], first["limit_price"]), (0.98, 1.02, 1.0))
        self.assertEqual((first["premium_per_contract"], first["cash_required"], first["breakeven"], first["downside_buffer"]), (100.0, 9400.0, 93.0, 0.06))
        self.assertAlmostEqual(first["annualized_yield"], 1.0 / 94 * 365 / 28, places=5)
        self.assertEqual((second["role"], second["strike"], second["delta"], second["cash_required"]), ("BALANCED", 96.0, 0.284, 9600.0))
        put = collar["put"]
        self.assertEqual((put["strike"], put["delta"], put["limit_price"]), (92.0, 0.14, 0.61))  # |delta| nearest 0.15; mid 0.61 rounded up
        conservative, balanced = collar["items"]
        self.assertEqual((conservative["role"], conservative["call"]["strike"], conservative["call"]["delta"]), ("CONSERVATIVE", 107.0, 0.231))
        self.assertEqual((conservative["net_premium_per_share"], conservative["max_loss_per_share"], conservative["max_gain_per_share"]), (0.46, 7.54, 7.46))
        self.assertEqual((conservative["break_even"], conservative["worst_case_net_per_share"]), (99.54, 0.42))
        self.assertEqual((balanced["role"], balanced["call"]["strike"], balanced["net_premium_per_share"]), ("BALANCED", 106.0, 0.69))

    def test_nasdaq_us_p_fields_give_quote_implied_put_deltas(self) -> None:
        cycle = nasdaq_cycle()
        validate(cycle)
        csp = cycle["strategies"]["csp"]
        self.assertEqual(csp["provider_id"], "nasdaq_public_option_chain")
        self.assertEqual([(i["role"], i["strike"], i["delta_basis"]) for i in csp["suggestions"]],
                         [("CONSERVATIVE", 94.0, "QUOTE_IMPLIED"), ("BALANCED", 96.0, "QUOTE_IMPLIED")])
        self.assertTrue(0.20 <= csp["suggestions"][0]["delta"] <= 0.21)
        self.assertEqual(cycle["strategies"]["collar"]["put"]["strike"], 92.0)

    def test_nasdaq_us_without_any_put_field_has_no_strategies_object(self) -> None:
        cycle = nasdaq_cycle(chains.nasdaq_rows(puts=None))
        validate(cycle)
        self.assertNotIn("strategies", cycle)

    def test_nordic_put_rows_are_proven_like_calls_and_typed_sek(self) -> None:
        out = nordic_cycle(chains.nordic_rows())
        cycle = out["monthly"]
        validate(cycle)
        self.assertEqual((cycle["currency"], cycle["strategies"]["csp"]["provider_id"]), ("SEK", "nasdaq_nordic_option_chain"))
        self.assertEqual([i["strike"] for i in cycle["strategies"]["csp"]["suggestions"]], [94.0, 96.0])
        self.assertEqual(cycle["strategies"]["collar"]["items"][0]["call"]["strike"], 107.0)
        self.assertEqual([h["status"] for h in out.health], ["NO_EXPIRY", "READ"])  # health stays call-based and unchanged by puts

    def test_malformed_nordic_put_rows_are_dropped_without_touching_the_call_path(self) -> None:
        calls = [chains.nordic_row("C", k, b, a) for k, b, a in chains.CALLS]
        bad = {
            "call series letter on a put": {"symbol": "SIVE6J94"},
            "name date differs": {"expirationDate": "2026-10-29"},
            "strike differs": {"strikePrice": "999.00"},
            "other root": {"fullName": "OTHER 28OCT26 94P"},
            "non-string symbol": {"symbol": 7},
            "nonstandard size": {"contractSize": "50"},
            "foreign currency": {"currency": "USD"},
        }
        for label, override in bad.items():
            rows = calls + [chains.nordic_row("P", k, b, a, **override) for k, b, a in chains.PUTS]
            out = nordic_cycle(rows)
            cycle = out["monthly"]
            validate(cycle)
            self.assertEqual(len(cycle["suggestions"]), 2, label)  # the covered call is exactly as without puts
            self.assertIn("unavailable", cycle["strategies"]["csp"], label)
            self.assertIn("unavailable", cycle["strategies"]["collar"], label)
            self.assertNotIn("MALFORMED_ROWS", [h["status"] for h in out.health], label)
        self.assertEqual(builder._nordic_put_evidence(chains.nordic_row("C", 107.0, 1.0, 1.1), "SIVE", TODAY), "NONE")
        self.assertEqual(builder._nordic_put_evidence({"assetClass": "FUTURES"}, "SIVE", TODAY), "NONE")
        self.assertIsInstance(builder._nordic_put_evidence(chains.nordic_row("P", 94.0, 1.0, 1.1), "SIVE", TODAY), dict)
        # a put never proves a call: the call evidence function still ignores a P name
        self.assertEqual(builder._nordic_row_evidence(chains.nordic_row("P", 94.0, 1.0, 1.1), "SIVE", TODAY)[0], "IGNORE")

    def test_weekly_cycles_carry_the_strategies_too(self) -> None:
        today = date(2026, 10, 13)  # Tuesday; the weekly expiry is that Friday, 3 DTE
        calls, puts = chains.bs_chain(3)
        chain = chains.yahoo_chain(calls, puts)
        ticker = types.SimpleNamespace(options=["2026-10-16"], option_chain=lambda e: chain)
        stamp = "2026-10-13T15:00:00Z"
        with mock.patch.dict(sys.modules, {"yfinance": types.SimpleNamespace(Ticker=lambda s: ticker)}):
            out = builder.us_options("AAA", SPOT, today, stamp)
        weekly = out["weekly"]
        validate_covered_call_cycle(weekly, evaluated_at=stamp, document_at=stamp, period="weekly")
        self.assertEqual(weekly["dte"], 3)
        self.assertIn("csp", weekly["strategies"])


class SelectionTests(unittest.TestCase):
    @staticmethod
    def with_deltas(deltas: dict[float, float]):
        def fake(row, spot, dte):
            delta = deltas[row["strike"]]
            return {**row, "delta": round(delta, 3), "delta_exact": delta, "delta_basis": "QUOTED_IV"}
        return mock.patch.object(builder, "with_put_delta", side_effect=fake)

    def test_the_csp_band_edges_are_inclusive_and_the_nearest_to_020_goes_first(self) -> None:
        puts = [{"strike": float(k), "bid": 1.0, "ask": 1.04, "iv": None, "oi": 1, "volume": 1, "size": 100} for k in (90, 91, 92, 93, 94)]
        deltas = {90.0: 0.1999, 91.0: 0.20, 92.0: 0.25, 93.0: 0.30, 94.0: 0.3001}
        with self.with_deltas(deltas):
            items, reason = builder.cash_secured_put_tiers(puts, SPOT, 28)
        self.assertIsNone(reason)
        self.assertEqual([(i["role"], i["strike"]) for i in items], [("CONSERVATIVE", 91.0), ("BALANCED", 93.0)])

    def test_a_single_band_strike_yields_one_item_and_no_strike_in_band_says_so(self) -> None:
        puts = [{"strike": 91.0, "bid": 1.0, "ask": 1.04, "iv": None, "oi": 1, "volume": 1, "size": 100}]
        with self.with_deltas({91.0: 0.25}):
            items, _ = builder.cash_secured_put_tiers(puts, SPOT, 28)
        self.assertEqual([i["role"] for i in items], ["CONSERVATIVE"])
        with self.with_deltas({91.0: 0.45}):
            items, reason = builder.cash_secured_put_tiers(puts, SPOT, 28)
        self.assertEqual(items, [])
        self.assertIn("0.20–0.30", reason)

    def test_the_csp_floor_applies_to_the_bid_on_the_cash(self) -> None:
        # strike 91, 28 DTE: bid 0.13 -> 0.13 / 91 * 365 / 28 = 1.862% (refused); bid 0.14 -> 2.005% (accepted)
        for bid, expected in ((0.13, 0), (0.14, 1)):
            puts = [{"strike": 91.0, "bid": bid, "ask": bid + 0.02, "iv": None, "oi": 1, "volume": 1, "size": 100}]
            with self.with_deltas({91.0: 0.25}):
                items, reason = builder.cash_secured_put_tiers(puts, SPOT, 28)
            self.assertEqual(len(items), expected, bid)
            if not expected:
                self.assertIn("2%", reason)

    def test_collar_credit_and_debit_cases_are_signed_and_recomputable(self) -> None:
        calls = [{"strike": 107.0, "bid": 0.25, "ask": 0.29, "iv": None, "delta": None, "oi": 1, "volume": 1, "size": 100}]
        puts = [{"strike": 92.0, "bid": 0.80, "ask": 0.84, "iv": None, "oi": 1, "volume": 1, "size": 100}]
        with self.with_deltas({92.0: 0.15}), mock.patch.object(builder, "with_delta", side_effect=lambda row, s, d: {**row, "delta": 0.22,
                                                                                                            "delta_exact": 0.22, "delta_basis": "QUOTED_IV"}):
            block, reason = builder.collar_tiers(calls, puts, SPOT, 28)
        self.assertIsNone(reason)
        item = block["items"][0]
        self.assertEqual(block["put"]["limit_price"], 0.82)  # mid 0.82 rounded up, not above ask 0.84
        self.assertEqual((item["call"]["limit_price"], item["net_premium_per_share"]), (0.27, -0.55))  # a DEBIT: negative
        self.assertEqual((item["max_loss_per_share"], item["max_gain_per_share"], item["break_even"]), (8.55, 6.45, 100.55))
        self.assertEqual(item["worst_case_net_per_share"], round(0.25 - 0.84, 4))

    def test_buy_limit_rounds_up_never_above_ask_and_sell_limit_rounds_down_never_below_bid(self) -> None:
        self.assertEqual(builder._buy_limit(0.50, 0.53), 0.52)   # mid 0.515 -> up to 0.52
        self.assertEqual(builder._buy_limit(0.50, 0.51), 0.51)   # mid 0.505 -> 0.51 = ask
        self.assertEqual(builder._buy_limit(0.50, 0.5049), 0.5049)  # capped at an off-tick ask
        self.assertEqual(builder._buy_limit(1.00, 1.50), 1.38)   # wide spread: ask minus a quarter, rounded up (1.375 -> 1.38)
        self.assertEqual(builder._sell_limit(0.50, 0.53), 0.51)
        self.assertEqual(builder._sell_limit(1.00, 1.50), 1.12)  # wide spread: bid plus a quarter, rounded down


class FailClosedTests(unittest.TestCase):
    def assert_put_side_unavailable(self, cycle: dict, label: str) -> None:
        validate(cycle)
        self.assertEqual(len(cycle["suggestions"]), 2, label)  # the covered call is untouched
        for name in ("csp", "collar"):
            block = cycle["strategies"][name]
            self.assertEqual(list(block), ["unavailable"], f"{label} {name}")
            self.assertTrue(block["unavailable"], label)

    def test_no_put_rows_one_sided_inverted_zero_and_nan_quotes_make_only_the_put_strategies_unavailable(self) -> None:
        cases = {
            "empty put table": [],
            "one-sided (no bid)": [(k, None, a) for k, b, a in chains.PUTS],
            "one-sided (no ask)": [(k, b, None) for k, b, a in chains.PUTS],
            "inverted": [(k, a, b) for k, b, a in chains.PUTS],
            "zero bid": [(k, 0.0, a) for k, b, a in chains.PUTS],
            "nan": [(k, float("nan"), float("nan")) for k, b, a in chains.PUTS],
            "spread wider than the mid": [(k, 0.01, 0.50) for k, b, a in chains.PUTS],
        }
        for label, puts in cases.items():
            self.assert_put_side_unavailable(yahoo_cycle(chains.yahoo_chain(puts=puts)), f"yahoo {label}")
        for label, puts in {"nasdaq empty": [], "nasdaq one-sided": [(k, None, a) for k, b, a in chains.PUTS]}.items():
            rows = chains.nasdaq_rows(puts=puts)
            self.assert_put_side_unavailable(nasdaq_cycle(rows), label)

    def test_a_chain_object_without_a_put_table_has_no_strategies_object(self) -> None:
        cycle = yahoo_cycle(chains.yahoo_chain(puts=None))
        validate(cycle)
        self.assertNotIn("strategies", cycle)

    def test_a_put_without_a_delta_or_off_the_cent_grid_is_never_used(self) -> None:
        puts = [(94.005, 0.98, 1.02), (96.0, 1.52, 1.56)]
        cycle = yahoo_cycle(chains.yahoo_chain(puts=puts))
        validate(cycle)
        self.assertEqual([i["strike"] for i in cycle["strategies"]["csp"]["suggestions"]], [96.0])  # 94.005 cannot be shown exactly
        itm_only = [(k + 20, b, a) for k, b, a in chains.PUTS]  # strikes above the spot: not out of the money
        self.assert_put_side_unavailable(yahoo_cycle(chains.yahoo_chain(puts=itm_only)), "in the money")

    def test_stale_or_unconfirmed_nasdaq_as_of_withholds_everything_including_puts(self) -> None:
        stale = nasdaq_cycle(asof=TODAY - timedelta(days=10))
        self.assertEqual(stale, {"unavailable": builder.NASDAQ_US_STALE_TEXT})
        payload = chains.nasdaq_payload(chains.nasdaq_rows())
        payload["data"]["lastTrade"] = None
        with mock.patch.object(builder, "http_json", lambda url: payload):
            self.assertEqual(builder.nasdaq_us_options("AAA", SPOT, TODAY, STAMP)["monthly"], {"unavailable": builder.NASDAQ_US_STALE_TEXT})

    def test_a_cycle_without_a_covered_call_but_with_puts_is_emitted_with_the_cc_reason(self) -> None:
        one_sided_calls = [(k, None, a) for k, b, a in chains.CALLS]
        cycle = yahoo_cycle(chains.yahoo_chain(calls=one_sided_calls))
        validate(cycle)
        self.assertEqual(cycle["suggestions"], [])
        self.assertIn(carry.NO_TWO_SIDED_REASON, cycle["strategies"]["cc"]["unavailable"])
        self.assertIn("suggestions", cycle["strategies"]["csp"])
        # the floor case: a covered call that no strike qualifies for keeps the existing reason text, now at 2%
        low_yield = [(112.0, 0.01, 0.02)]
        cycle = yahoo_cycle(chains.yahoo_chain(calls=low_yield))
        validate(cycle)
        self.assertIn("沒有年化權利金達 2%", cycle["strategies"]["cc"]["unavailable"])
        self.assertEqual(list(cycle["strategies"]["collar"]), ["unavailable"])  # no call in the band for the collar either

    def test_everything_unavailable_stays_the_plain_cycle_unavailable(self) -> None:
        both = yahoo_cycle(chains.yahoo_chain(calls=[(k, None, a) for k, b, a in chains.CALLS], puts=[(k, None, a) for k, b, a in chains.PUTS]))
        self.assertEqual(list(both), ["unavailable"])
        self.assertIn(carry.NO_TWO_SIDED_REASON, both["unavailable"])  # the carry-forward trigger keeps its exact shape
        no_puts_no_strike = yahoo_cycle(chains.yahoo_chain(calls=[(112.0, 0.01, 0.02)], puts=[]))
        self.assertEqual(list(no_puts_no_strike), ["unavailable"])


class ValidatorTests(unittest.TestCase):
    def good(self) -> dict:
        return copy.deepcopy(yahoo_cycle())

    def assert_rejected(self, cycle: dict, label: str) -> None:
        with self.assertRaises(MarketProductValidationError, msg=label):
            validate(cycle)

    def test_the_producer_output_passes_and_zero_suggestions_need_a_real_strategy(self) -> None:
        cycle = self.good()
        validate(cycle)
        cycle["suggestions"] = []
        cycle.pop("middle_suggestion", None)
        self.assert_rejected(cycle, "zero suggestions without cc unavailable")
        cycle["strategies"] = {"cc": {"unavailable": "x"}, "csp": {"unavailable": "x"}, "collar": {"unavailable": "x"}}
        self.assert_rejected(cycle, "every block unavailable")
        cycle["strategies"]["csp"] = self.good()["strategies"]["csp"]
        validate(cycle)  # one real block is enough
        no_strategies = self.good()
        del no_strategies["strategies"]
        no_strategies["suggestions"] = []
        no_strategies.pop("middle_suggestion", None)
        self.assert_rejected(no_strategies, "empty suggestions and no strategies")

    def test_mutants_of_the_csp_block_are_rejected(self) -> None:
        def mutate(path, value):
            cycle = self.good()
            node = cycle["strategies"]["csp"]["suggestions"][0]
            if path is None:
                node["delta"] = value
            else:
                node[path] = value
            return cycle
        for label, cycle in {
            "tampered cash_required": mutate("cash_required", 9000.0),
            "tampered breakeven": mutate("breakeven", 94.0),
            "tampered premium": mutate("premium_per_contract", 150.0),
            "tampered annualized": mutate("annualized_yield", 0.5),
            "strike at the spot": mutate("strike", 100.0),
            "strike above the spot": mutate("strike", 101.0),
            "delta above one": mutate("delta", 1.5),
            "delta below the band": mutate("delta", 0.10),
            "delta above the band": mutate("delta", 0.35),
            "limit above the mid": mutate("limit_price", 1.01),
            "limit below the bid": mutate("limit_price", 0.5),
            "inverted quote": mutate("bid", 1.5),
            "unknown delta basis": mutate("delta_basis", "MAGIC"),
            "bool as number": mutate("bid", True),
            "extra key": mutate("surprise", 1),
        }.items():
            self.assert_rejected(cycle, label)
        reordered = self.good()
        reordered["strategies"]["csp"]["suggestions"].reverse()
        self.assert_rejected(reordered, "roles out of order")

    def test_mutants_of_the_collar_block_are_rejected(self) -> None:
        def with_item(key, value, leg=None):
            cycle = self.good()
            item = cycle["strategies"]["collar"]["items"][0]
            (item[leg] if leg else item)[key] = value
            return cycle
        def with_put(key, value):
            cycle = self.good()
            cycle["strategies"]["collar"]["put"][key] = value
            return cycle
        for label, cycle in {
            "net sign flipped": with_item("net_premium_per_share", -0.46),
            "max loss tampered": with_item("max_loss_per_share", 1.0),
            "max gain tampered": with_item("max_gain_per_share", 9.0),
            "break-even tampered": with_item("break_even", 100.0),
            "worst case tampered": with_item("worst_case_net_per_share", 0.46),
            "call strike at the spot": with_item("strike", 100.0, "call"),
            "call strike below the spot": with_item("strike", 99.0, "call"),
            "put strike at the spot": with_put("strike", 100.0),
            "put strike above the spot": with_put("strike", 101.0),
            "put delta above one": with_put("delta", 1.2),
            "put delta outside its window": with_put("delta", 0.40),
            "call delta outside the band": with_item("delta", 0.50, "call"),
            "buy limit above the ask": with_put("limit_price", 0.70),
            "buy limit below the mid": with_put("limit_price", 0.60),
            "extra item key": with_item("surprise", 1),
        }.items():
            self.assert_rejected(cycle, label)
        different = self.good()
        different["strategies"]["collar"]["items"].append(copy.deepcopy(different["strategies"]["collar"]["items"][0]))
        self.assert_rejected(different, "balanced call not lower than the conservative one")

    def test_label_and_shape_mutants_are_rejected(self) -> None:
        for key in ("rights_status", "provider_id", "quote_basis", "timestamp"):
            cycle = self.good()
            del cycle["strategies"]["csp"][key]
            self.assert_rejected(cycle, f"missing {key}")
            cycle = self.good()
            cycle["strategies"]["collar"][key] = "other"
            self.assert_rejected(cycle, f"mismatched {key}")
        for label, mutate in {
            "unknown strategy name": lambda c: c["strategies"].update({"straddle": {"unavailable": "x"}}),
            "cc block with suggestions": lambda c: c["strategies"].update({"cc": {"unavailable": "x"}}),
            "strategies not a dict": lambda c: c.update({"strategies": []}),
            "empty strategies": lambda c: c.update({"strategies": {}}),
            "unavailable with extras": lambda c: c["strategies"].update({"csp": {"unavailable": "x", "suggestions": []}}),
            "unavailable not a string": lambda c: c["strategies"].update({"csp": {"unavailable": 3}}),
            "block not a dict": lambda c: c["strategies"].update({"csp": None}),
            "three csp items": lambda c: c["strategies"]["csp"]["suggestions"].append(copy.deepcopy(c["strategies"]["csp"]["suggestions"][0])),
        }.items():
            cycle = self.good()
            mutate(cycle)
            self.assert_rejected(cycle, label)

    def test_the_covered_call_checks_are_unchanged(self) -> None:
        cycle = self.good()
        cycle["suggestions"][0]["delta"] = 0.25  # HIGH_STRIKE over the 0.20 cap (master ruling O1: the cap stays)
        self.assert_rejected(cycle, "high strike delta cap")

    def test_degrade_bad_strategy_blocks_replaces_only_the_failing_block(self) -> None:
        cycle = self.good()
        cycle["strategies"]["csp"]["suggestions"][0]["cash_required"] = 1.0
        out = degrade_bad_strategy_blocks(cycle)
        self.assertEqual(out["strategies"]["csp"], {"unavailable": "報價未通過驗證"})
        self.assertEqual(out["strategies"]["collar"], cycle["strategies"]["collar"])
        self.assertEqual(out["suggestions"], cycle["suggestions"])
        validate(out)
        self.assertEqual(cycle["strategies"]["csp"]["suggestions"][0]["cash_required"], 1.0)  # the input is not mutated
        for odd in (None, [], "x", {"strategy": "COVERED_CALL"}):
            self.assertIs(degrade_bad_strategy_blocks(odd), odd)
        junk = self.good()
        junk["strategies"] = {"straddle": {}, "csp": 7}
        self.assertEqual(degrade_bad_strategy_blocks(junk)["strategies"], {"csp": {"unavailable": "報價未通過驗證"}})

    def test_validate_strategy_block_is_callable_per_block(self) -> None:
        cycle = self.good()
        validate_strategy_block("csp", cycle["strategies"]["csp"], cycle)
        validate_strategy_block("cc", {"unavailable": "x"}, cycle)
        with self.assertRaises(MarketProductValidationError):
            validate_strategy_block("cc", cycle["strategies"]["csp"], cycle)


class SealingTests(unittest.TestCase):
    NOW = datetime(2026, 9, 30, 17, 5, tzinfo=UTC)

    def test_yahoo_nonstandard_unknown_or_mismatched_contract_terms_never_publish_strategies(self):
        for size, currency in (("MINI", "USD"), ("REGULAR", "EUR"), (None, "USD"), ("REGULAR", None), ("UNKNOWN", "USD"),
                               (["REGULAR"], "USD"), ("REGULAR", {"currency": "USD"}), (100, "USD")):
            with self.subTest(size=size, currency=currency):
                chain = chains.yahoo_chain()
                for table in (chain.calls, chain.puts):
                    for row in table.itertuples():
                        row.contractSize, row.currency = size, currency
                cycle = yahoo_cycle(chain)
                self.assertEqual(list(cycle), ["unavailable"])
                body = self.seal({"AAA": {"monthly": cycle}}, {"AAA"})
                output = json.loads(body["v213:options:v2"])["options"]["AAA"]["monthly"]
                self.assertEqual(list(output), ["unavailable"])
        good = yahoo_cycle()
        validate(good)
        self.assertEqual(good["multiplier"], 100)
        self.assertTrue(good["strategies"]["csp"]["suggestions"])
        self.assertTrue(good["strategies"]["collar"]["items"])
        # A malformed side does not erase independently verified standard contracts on the other side.
        chain = chains.yahoo_chain()
        for row in chain.puts.itertuples(): row.contractSize = "MINI"
        cycle = yahoo_cycle(chain)
        validate(cycle)
        self.assertTrue(cycle["suggestions"])
        self.assertIn("unavailable", cycle["strategies"]["csp"])
        self.assertIn("unavailable", cycle["strategies"]["collar"])

    def seal(self, options: dict, tickers: set[str]) -> dict:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "market_quotes_options.json"
            doc = {"schema": "v213-market-observations-v2", "generated_at": STAMP, "quotes": {"AAA": {"symbol": "AAA", "price": SPOT}}, "options": options}
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            with synthetic_option_admission(tickers):
                return publisher.lazy_market_bodies(path, self.NOW)

    def test_one_bad_block_degrades_alone_and_the_good_covered_call_and_block_survive(self) -> None:
        bad = copy.deepcopy(yahoo_cycle())
        bad["strategies"]["csp"]["suggestions"][0]["cash_required"] = 1.0
        bodies = self.seal({"AAA": {"monthly": bad}}, {"AAA"})
        self.assertEqual(sorted(bodies), ["v213:options:v2", "v213:quotes:v1"])  # no new key
        sealed = json.loads(bodies["v213:options:v2"])["options"]["AAA"]["monthly"]
        self.assertEqual(sealed["suggestions"], bad["suggestions"])
        self.assertEqual(sealed["strategies"]["csp"], {"unavailable": "報價未通過驗證"})
        self.assertEqual(sealed["strategies"]["collar"], bad["strategies"]["collar"])

    def test_a_good_cycle_is_sealed_byte_for_byte_and_a_cycle_without_strategies_is_unchanged(self) -> None:
        good = yahoo_cycle()
        plain = {k: v for k, v in good.items() if k != "strategies"}
        plain = dict(plain, ticker="BBB")
        sealed = json.loads(self.seal({"AAA": {"monthly": good}, "BBB": {"monthly": plain}}, {"AAA", "BBB"})["v213:options:v2"])["options"]
        self.assertEqual(sealed["AAA"]["monthly"], good)
        self.assertEqual(sealed["BBB"]["monthly"], plain)

    def test_a_cycle_without_a_covered_call_whose_strategies_all_fail_is_dropped_as_a_cycle(self) -> None:
        cycle = yahoo_cycle(chains.yahoo_chain(calls=[(k, None, a) for k, b, a in chains.CALLS]))
        cycle["strategies"]["csp"]["suggestions"][0]["cash_required"] = 1.0
        self.assertEqual(list(cycle["strategies"]["collar"]), ["unavailable"])  # no call quote, so no collar either
        sealed = json.loads(self.seal({"AAA": {"monthly": cycle}}, {"AAA"})["v213:options:v2"])["options"]["AAA"]["monthly"]
        self.assertEqual(list(sealed), ["unavailable"])
        self.assertIn("報價未通過驗證", sealed["unavailable"])

    def test_over_the_size_cap_the_strategies_are_dropped_before_the_covered_calls(self) -> None:
        good = yahoo_cycle()
        options = {f"T{i:03d}": {"monthly": dict(good, ticker=f"T{i:03d}")} for i in range(40)}
        compact = len(json.dumps(good, ensure_ascii=False, separators=(",", ":")))
        with mock.patch.object(publisher, "LAZY_BODY_MAX_BYTES", 40 * compact - 20_000):  # fits only without the strategies (about 1.4 KB each)
            bodies = self.seal(options, set(options))
        sealed = json.loads(bodies["v213:options:v2"])["options"]
        self.assertEqual(len(sealed), 40)
        self.assertTrue(all("strategies" not in v["monthly"] and v["monthly"]["suggestions"] for v in sealed.values()))
        with mock.patch.object(publisher, "LAZY_BODY_MAX_BYTES", 1000):
            self.assertEqual(self.seal(options, set(options)), {})


class CarryForwardTests(unittest.TestCase):
    IN_SESSION = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
    OFF_SESSION = datetime(2026, 10, 13, 21, 30, tzinfo=UTC)

    def setUp(self) -> None:
        self.policy = support.yahoo_policy()
        self.stamp = self.IN_SESSION.strftime("%Y-%m-%dT%H:%M:%SZ")
        calls, puts = chains.bs_chain(3)
        chain = chains.yahoo_chain(calls, puts)
        ticker = types.SimpleNamespace(options=["2026-10-16"], option_chain=lambda e: chain)
        with mock.patch.dict(sys.modules, {"yfinance": types.SimpleNamespace(Ticker=lambda s: ticker)}):
            self.cycle = builder.us_options("T00", SPOT, date(2026, 10, 13), self.stamp)["weekly"]
        self.assertIn("strategies", self.cycle)

    def state(self) -> carry.CarryForward:
        return carry.CarryForward(Path(tempfile.gettempdir()) / "v21-unused-state.json", policy=self.policy)

    def test_a_captured_cycle_with_strategies_is_carried_with_every_block_label_following_the_basis(self) -> None:
        state = self.state()
        self.assertEqual(state.capture({"T00": {"weekly": copy.deepcopy(self.cycle)}}, self.IN_SESSION), 1)
        unavailable = {"unavailable": f"本次回應有 2026-10-16（1天）買權，但{carry.NO_TWO_SIDED_REASON}（買賣價須為正且不倒掛）"}
        options = {"T00": {"weekly": dict(unavailable)}}
        health = [{"venue": "US", "underlying": "T00", "expiry": "2026-10-16", "cycle": "weekly", "status": "READ", "read": True, "two_sided": False}]
        self.assertEqual(state.apply(options, health, self.OFF_SESSION), 1)
        carried = options["T00"]["weekly"]
        self.assertEqual(carried["quote_basis"], "previous_session_last")
        self.assertEqual(carried["strategies"]["csp"]["quote_basis"], "previous_session_last")
        self.assertEqual(carried["strategies"]["collar"]["quote_basis"], "previous_session_last")
        self.assertEqual(carried["strategies"]["csp"]["suggestions"], self.cycle["strategies"]["csp"]["suggestions"])
        validate_covered_call_cycle(carried, evaluated_at=self.OFF_SESSION, document_at=self.OFF_SESSION.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    period="weekly", allow_previous_session=True)

    def test_the_state_file_round_trips_strategies_and_a_tampered_block_is_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            state = carry.CarryForward(path, policy=self.policy)
            state.capture({"T00": {"weekly": copy.deepcopy(self.cycle)}}, self.IN_SESSION)
            self.assertTrue(state.save(self.IN_SESSION))
            loaded = carry.load_state(path, self.IN_SESSION + timedelta(hours=1))
            self.assertEqual(loaded["T00"]["weekly"]["strategies"], self.cycle["strategies"])
            document = json.loads(path.read_text(encoding="utf-8"))
            document["cycles"]["T00"]["weekly"]["strategies"]["csp"]["suggestions"][0]["cash_required"] = 1.0
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(carry.load_state(path, self.IN_SESSION + timedelta(hours=1)), {})
            document["cycles"]["T00"]["weekly"]["strategies"] = {"csp": {"unavailable": "x"}, "collar": {"unavailable": "x"}, "surprise": 1}
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(carry.load_state(path, self.IN_SESSION + timedelta(hours=1)), {})

    def test_the_closed_key_set_accepts_strategies_only_as_an_optional_key(self) -> None:
        self.assertIn("strategies", carry.CYCLE_KEYS)
        self.assertNotIn("strategies", carry.REQUIRED_CYCLE_KEYS)
        plain = {k: v for k, v in self.cycle.items() if k != "strategies"}
        self.assertTrue(carry._closed_shape(plain))
        self.assertTrue(carry._closed_shape(self.cycle))


class SizeAndSealKeyTests(unittest.TestCase):
    def test_cycle_growth_stays_small_and_the_seal_keys_do_not_change(self) -> None:
        cycle = yahoo_cycle()
        full = len(json.dumps(cycle, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        base = len(json.dumps({k: v for k, v in cycle.items() if k != "strategies"}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.assertLess(full - base, 1600)   # two CSP items, one protective put and two collar items, with labels, in about 1.45 KB
        # a 300-ticker, two-cycle universe stays below the 1.9 MB cap of the options body with room to spare
        self.assertLess(600 * full, publisher.LAZY_BODY_MAX_BYTES * 0.95)

    def test_the_constants_are_shared_and_pinned(self) -> None:
        self.assertEqual(rules.CONSERVATIVE_DELTA_BAND, (0.20, 0.30))
        self.assertEqual(rules.PROTECTIVE_PUT_DELTA, 0.15)
        self.assertEqual(builder.MAX_HIGH_STRIKE_DELTA, 0.20)  # master ruling O1
        self.assertEqual(builder.MIN_ANNUALIZED_YIELD, 0.02)


if __name__ == "__main__":
    unittest.main()
