"""V21: covered call + cash-secured put + collar, independently validated; no annualized-yield floor; ineligible calls remain non-executable observations.

PRODUCER half: put parsing for the three providers (Yahoo option_chain().puts, Nasdaq US p_* fields, Nasdaq Nordic put rows), the
strategy selection and arithmetic, fail-closed negatives, the Python validators, carry-forward, block-level degradation in the sealer and the
size of the options object. Synthetic chains only (tests/fixtures/v21_put_chains.py); no network.
"""
from __future__ import annotations

import copy
import json
import math
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
import option_delta_model as md  # noqa: E402
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
    @staticmethod
    def coherent_call(strike: float, dte: int, sigma: float = .30) -> dict:
        fair=md.bs_call_price(100., strike, max(dte,1)/365, sigma)
        assert fair > 0
        bid=math.floor(fair*.97*1_000_000)/1_000_000
        ask=math.ceil(fair*1.03*1_000_000)/1_000_000
        return {"strike":strike,"bid":bid,"ask":ask,"delta":.9,
                "iv":sigma,"oi":10,"volume":1}

    def test_there_is_no_annualized_yield_floor_any_more(self) -> None:
        self.assertFalse(hasattr(builder,"MIN_ANNUALIZED_YIELD"))
        self.assertFalse(hasattr(builder,"MONTHLY_ANNUAL_HURDLE"))
        quotes=[self.coherent_call(k,30) for k in (112.,115.,118.)]
        recommendations=builder.covered_call_suggestions(quotes,100.,30)
        self.assertTrue(recommendations)
        self.assertTrue(any(0<x["annualized_yield"]<.02 for x in recommendations))
        self.assertTrue(all(x["delta_basis"]=="QUOTED_IV" for x in recommendations))
        self.assertTrue(all(x["delta"]!=.9 for x in recommendations))

    def test_dte_zero_and_a_wide_spread_keep_their_rules(self) -> None:
        row=self.coherent_call(103.,0,.30)
        # Quote-implied model, not input Delta; DTE=0 uses effective one day.
        tiers=builder.covered_call_suggestions([row],100.,0)
        if tiers:
            self.assertAlmostEqual(tiers[0]["annualized_yield"],tiers[0]["period_yield"]*365,delta=.0001)
        wide={"strike":105.,"bid":.3,"ask":.6,"delta":.1,"iv":None,"oi":1,"volume":1}
        # A >25% *price spread* is not the uncertainty predicate.
        # Here |delta_bid-delta_ask| is .062 < .10 so Stage1C Q path stays.
        kept=builder.covered_call_suggestions([wide],100.,30)
        self.assertTrue(kept)
        self.assertEqual(kept[0]["delta_basis"],"QUOTED")
        self.assertEqual(builder.covered_call_suggestions([{**wide,"ask":.9}],100.,30),[])


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

    def test_nordic_exchange_roots_preserve_calls_csp_and_collar(self) -> None:
        for base, root in (("TELIA", "TLSN"), ("BOL", "BOLI"), ("KINV-B", "KINB")):
            with self.subTest(base=base):
                rows = [chains.nordic_row(kind, k, b, a, root=root)
                        for kind, quotes in (("C", chains.CALLS), ("P", chains.PUTS)) for k, b, a in quotes]
                with mock.patch.object(builder, "http_json", return_value={"data": {"instrumentListing": {"rows": rows}}}):
                    out = builder.nordic_options(f"{base}.ST", base, SPOT, TODAY, STAMP, "TX_VERIFIED", spot_currency="SEK")
                cycle = out["monthly"]
                validate(cycle)
                self.assertEqual(builder._nordic_chain_root(rows), root)
                self.assertEqual((cycle["ticker"], cycle["currency"], cycle["multiplier"]), (f"{base}.ST", "SEK", 100))
                self.assertEqual(len(cycle["suggestions"]), 2)
                self.assertEqual([item["strike"] for item in cycle["strategies"]["csp"]["suggestions"]], [94.0, 96.0])
                self.assertEqual(cycle["strategies"]["collar"]["put"]["strike"], 92.0)
                self.assertEqual(cycle["strategies"]["collar"]["items"][0]["call"]["strike"], 107.0)

    def test_grouped_nordic_call_and_put_strikes_preserve_all_strategy_selection(self) -> None:
        for base, root, scale in (("AZN", "AZN", 15), ("SAAB-B", "SAAB", 12)):
            with self.subTest(base=base):
                # Scale a deterministic chain with known deltas; grouping never touches quote-price parsing.
                rows = [chains.nordic_row(kind, k * scale, b * scale, a * scale, root=root,
                                          strikePrice=f"{k * scale:,.2f}")
                        for kind, quotes in (("C", chains.CALLS), ("P", chains.PUTS)) for k, b, a in quotes]
                self.assertTrue(all("," in row["strikePrice"] for row in rows))
                self.assertEqual(builder._nordic_chain_root(rows), root)
                with mock.patch.object(builder, "http_json", return_value={"data": {"instrumentListing": {"rows": rows}}}):
                    out = builder.nordic_options(f"{base}.ST", base, SPOT * scale, TODAY, STAMP,
                                                "TX_VERIFIED", spot_currency="SEK")
                cycle = out["monthly"]
                validate(cycle)
                self.assertEqual(cycle["expiry"], EXPIRY)
                self.assertEqual(len(cycle["suggestions"]), 2)
                self.assertEqual([item["strike"] for item in cycle["strategies"]["csp"]["suggestions"]], [94 * scale, 96 * scale])
                self.assertEqual(cycle["strategies"]["collar"]["put"]["strike"], 92 * scale)
                self.assertEqual(cycle["strategies"]["collar"]["items"][0]["call"]["strike"], 107 * scale)
                self.assertEqual([h["status"] for h in out.health], ["NO_EXPIRY", "READ"])

    def test_nordic_mixed_call_and_put_roots_refuse_both_cycles(self) -> None:
        calls = [chains.nordic_row("C", k, b, a, root="TLSN") for k, b, a in chains.CALLS]
        puts = [chains.nordic_row("P", k, b, a, root="BOLI") for k, b, a in chains.PUTS]
        for rows in (calls + puts, puts + calls):
            self.assertEqual(builder._nordic_chain_root(puts), "BOLI", "puts alone can prove a root")
            self.assertIsNone(builder._nordic_chain_root(rows))
            with mock.patch.object(builder, "http_json", return_value={"data": {"instrumentListing": {"rows": rows}}}):
                out = builder.nordic_options("TELIA.ST", "TELIA", SPOT, TODAY, STAMP, "TX_VERIFIED", spot_currency="SEK")
            self.assertTrue(all("unavailable" in cycle for cycle in out.values()))
            self.assertFalse(any(h["read"] or h["two_sided"] for h in out.health))

    def test_grouped_nordic_put_identity_refuses_adjusted_and_disagreeing_contracts(self) -> None:
        good = chains.nordic_row("P", 1460, 1.0, 1.1, root="AZN", strikePrice="1,460.00")
        put = builder._nordic_put_evidence(good, "AZN", TODAY)
        self.assertIsInstance(put, dict)
        self.assertEqual((put["strike"], put["expiry"]), (1460.0, EXPIRY))
        self.assertEqual(builder._nordic_chain_root([good]), "AZN")
        bad = [
            {"fullName": "SAAB 20NOV26 1460P"}, {"symbol": "SAAB6W1460"},
            {"fullName": "AZN 20NOV26 1461P"}, {"symbol": "AZN6W1461"},
            {"expirationDate": "2026-11-27"}, {"symbol": "AZN6V1460"}, {"symbol": "AZN6K1460"},
            {"symbol": "AZN7W1460"}, {"symbol": "AZN6W27Y1460"},
            {"fullName": "AZN 31NOV26 1460P", "expirationDate": "2026-11-31"},
            {"strikePrice": "14,60.00"}, {"strikePrice": "1.460,00"}, {"strikePrice": "1,460"},
            {"strikePrice": "1,460.00000"}, {"strikePrice": "1,460.0001"}, {"strikePrice": 1460.0},
            {"fullName": "AZN-X101 20NOV26 1460P", "symbol": "AZN6W1460-X101", "contractSize": "101"},
            {"fullName": "AZN 20NOV26 1460P-X101", "symbol": "AZN6W1460-X101", "contractSize": "101"},
            {"symbol": "AZN6W1460X", "contractSize": "100"},
        ]
        for override in bad:
            with self.subTest(override=override):
                row = {**good, **override}
                self.assertNotIsInstance(builder._nordic_put_evidence(row, "AZN", TODAY), dict)
                self.assertIsNone(builder._nordic_chain_root([row]))

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
    def prepared(rows: list[dict], deltas: dict[float, float]) -> list[dict]:
        """Inject computed Delta only at the *tier selection boundary*. This
        is a pure selection fixture, not a producer/validator model bypass:
        actual side-IV computations have dedicated end-to-end tests.
        """
        return [{**row, "delta": round(deltas[row["strike"]], 3),
                 "delta_exact": deltas[row["strike"]], "delta_basis": "QUOTED"}
                for row in rows]

    def test_the_csp_band_edges_are_inclusive_and_the_nearest_to_020_goes_first(self) -> None:
        puts=[{"strike":float(k),"bid":1.,"ask":1.04,"oi":1,"volume":1} for k in (90,91,92,93,94)]
        deltas={90.:.1999,91.:.20,92.:.25,93.:.30,94.:.3001}
        items,reason=builder.cash_secured_put_tiers(puts,SPOT,28,
                                                    prepared=self.prepared(puts,deltas))
        self.assertIsNone(reason)
        self.assertEqual([(i["role"],i["strike"]) for i in items],
                         [("CONSERVATIVE",91.),("BALANCED",93.)])

    def test_a_single_band_strike_yields_one_item_and_no_strike_in_band_says_so(self) -> None:
        puts=[{"strike":91.,"bid":1.,"ask":1.04,"oi":1,"volume":1}]
        items,_=builder.cash_secured_put_tiers(puts,SPOT,28,
                                               prepared=self.prepared(puts,{91.:.25}))
        self.assertEqual([i["role"] for i in items],["CONSERVATIVE"])
        items,reason=builder.cash_secured_put_tiers(puts,SPOT,28,
                                                    prepared=self.prepared(puts,{91.:.45}))
        self.assertEqual(items,[])
        self.assertIn("0.20–0.30",reason)

    def test_the_csp_has_no_yield_floor(self) -> None:
        for bid in (.01,.05):
            puts=[{"strike":91.,"bid":bid,"ask":bid+.02,"oi":1,"volume":1}]
            items,reason=builder.cash_secured_put_tiers(puts,SPOT,28,
                                                        prepared=self.prepared(puts,{91.:.25}))
            self.assertIsNone(reason,bid)
            self.assertEqual(len(items),1,bid)
            self.assertLess(items[0]["annualized_yield"],.02,bid)

    def test_collar_credit_and_debit_cases_are_signed_and_recomputable(self) -> None:
        calls=[{"strike":107.,"bid":.25,"ask":.29,"oi":1,"volume":1}]
        puts=[{"strike":92.,"bid":.80,"ask":.84,"oi":1,"volume":1}]
        block,reason=builder.collar_tiers(calls,puts,SPOT,28,
                                           prepared_calls=self.prepared(calls,{107.:.22}),
                                           prepared_puts=self.prepared(puts,{92.:.15}))
        self.assertIsNone(reason)
        item=block["items"][0]
        self.assertEqual(block["put"]["limit_price"],.82)
        self.assertEqual((item["call"]["limit_price"],item["net_premium_per_share"]),(.27,-.55))
        self.assertEqual((item["max_loss_per_share"],item["max_gain_per_share"],item["break_even"]),(8.55,6.45,100.55))
        self.assertEqual(item["worst_case_net_per_share"],round(.25-.84,4))

    def test_buy_limit_rounds_up_never_above_ask_and_sell_limit_rounds_down_never_below_bid(self) -> None:
        self.assertEqual(builder._buy_limit(.50,.53),.52)
        self.assertEqual(builder._buy_limit(.50,.51),.51)
        self.assertEqual(builder._buy_limit(.50,.5049),.5049)
        self.assertEqual(builder._buy_limit(1.,1.5),1.25)
        self.assertEqual(builder._sell_limit(.50,.53),.51)
        self.assertEqual(builder._sell_limit(1.,1.5),1.25)
        for bid,ask in ((.5,2.5),(.005,.006),(.5051,.5052),(.50999,.51001),(1.00001,1.00002)):
            with self.subTest(bid=bid,ask=ask):
                sell,buy=builder._sell_limit(bid,ask),builder._buy_limit(bid,ask)
                self.assertLessEqual(bid,sell)
                self.assertLessEqual(sell,(bid+ask)/2)
                self.assertLessEqual((bid+ask)/2,buy)
                self.assertLessEqual(buy,ask)
        self.assertEqual(builder._sell_limit(.005,None),.005)
        self.assertEqual(builder._buy_limit(None,.005),.005)


class FailClosedTests(unittest.TestCase):
    def assert_put_side_unavailable(self, cycle: dict, label: str) -> None:
        validate(cycle)
        self.assertEqual(len(cycle["suggestions"]), 2, label)  # the covered call is untouched
        for name in ("csp", "collar"):
            block = cycle["strategies"][name]
            self.assertNotIn("suggestions", block, f"{label} {name}")
            self.assertNotIn("items", block, f"{label} {name}")
            self.assertTrue(block["unavailable"], label)

    def test_empty_inverted_and_nonfinite_put_quotes_refuse_only_put_strategies(self) -> None:
        cases = {
            "empty put table": [],
            "inverted": [(k, a, b) for k, b, a in chains.PUTS],
            "nan": [(k, float("nan"), float("nan")) for k, b, a in chains.PUTS],
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

    def assert_call_observation(self, cycle: dict, kind: str) -> dict:
        validate(cycle)
        self.assertEqual((cycle["expiry"], cycle["dte"], cycle["timestamp"]), (EXPIRY, chains.DTE, STAMP))
        self.assertEqual(cycle["suggestions"], [])
        self.assertNotIn("middle_suggestion", cycle)
        cc = cycle.get("strategies", {}).get("cc")
        if cc is not None:
            self.assertTrue(cc.get("unavailable"))
            self.assertFalse(cc.get("suggestions"))
        observation = cycle["quote_observation"]
        self.assertEqual(observation["kind"], kind)
        return observation

    def test_unusable_call_quotes_preserve_csp_but_never_create_cc_or_collar(self) -> None:
        expected_csp = yahoo_cycle()["strategies"]["csp"]
        cases = {
            "no bid": [(k, None, a) for k, b, a in chains.CALLS],
            "zero bid": [(k, 0.0, a) for k, b, a in chains.CALLS],
            "inverted": [(k, a, b) for k, b, a in chains.CALLS],
            "nan": [(k, float("nan"), float("nan")) for k, b, a in chains.CALLS],
        }
        for label, calls in cases.items():
            with self.subTest(label=label):
                cycle = yahoo_cycle(chains.yahoo_chain(calls=calls))
                observed = self.assert_call_observation(cycle, "NO_TWO_SIDED")
                self.assertIn(observed["strike"], [k for k, b, a in calls])
                for field in ("bid", "ask", "last", "annualized_yield"):
                    self.assertIsNone(observed[field], field)
                self.assertEqual((observed["oi"], observed["volume"]), (100, 10))
                self.assertEqual(cycle["strategies"]["csp"], expected_csp)
                self.assertTrue(cycle["strategies"]["collar"]["unavailable"])
                self.assertFalse(cycle["strategies"]["collar"].get("items"))

    def test_last_trade_remains_indicative_and_never_supplies_an_executable_call_leg(self) -> None:
        chain = chains.yahoo_chain(calls=[(108.0, None, 0.90)])
        row = next(chain.calls.itertuples())
        row.lastPrice = 0.09
        row.openInterest = row.volume = None
        cycle = yahoo_cycle(chain)
        observed = self.assert_call_observation(cycle, "NO_TWO_SIDED")
        self.assertIsNone(observed["bid"])
        self.assertIsNone(observed["ask"])
        self.assertEqual((observed["strike"], observed["last"]), (108.0, 0.09))
        self.assertAlmostEqual(observed["annualized_yield"], 0.09 / SPOT * 365 / chains.DTE, places=6)
        self.assertIsNone(observed["oi"])
        self.assertIsNone(observed["volume"])
        self.assertEqual(cycle["strategies"]["csp"], yahoo_cycle()["strategies"]["csp"])
        self.assertTrue(cycle["strategies"]["collar"]["unavailable"])

    def test_delta_ineligible_call_is_observed_without_discarding_valid_puts(self) -> None:
        # The only call's delta is above the covered-call cap despite its high premium.
        cycle = yahoo_cycle(chains.yahoo_chain(calls=[(104.0, 1.83, 1.87)]))
        observed = self.assert_call_observation(cycle, "TWO_SIDED")
        self.assertEqual((observed["strike"], observed["bid"], observed["ask"]), (104.0, 1.83, 1.87))
        self.assertIsNone(observed["last"])
        self.assertAlmostEqual(observed["annualized_yield"], 1.83 / SPOT * 365 / chains.DTE, places=6)
        self.assertGreater(observed["annualized_yield"], 0.06)
        self.assertEqual(cycle["strategies"]["csp"], yahoo_cycle()["strategies"]["csp"])
        self.assertTrue(cycle["strategies"]["collar"]["unavailable"])

    def test_wide_low_premium_call_does_not_become_a_strategy_without_history(self) -> None:
        cycle=yahoo_cycle(chains.yahoo_chain(calls=[(107.,.01,.50),(110.,.01,.50)]))
        validate(cycle)
        self.assertEqual(cycle["suggestions"],[])
        self.assertEqual(cycle["quote_observation"]["kind"],"TWO_SIDED")
        # Per-side Stage1E: calls contain wide quotes without HV and refuse,
        # but the unrelated all-tight put side retains Stage1C SOURCE_IV CSP.
        self.assertIn("unavailable",cycle["strategies"]["cc"])
        self.assertTrue(cycle["strategies"]["csp"]["suggestions"])
        self.assertEqual(cycle["strategies"]["csp"]["suggestions"][0]["delta_basis"],"QUOTED_IV")
        self.assertIn("unavailable",cycle["strategies"]["collar"])

    def test_no_executable_strategy_preserves_only_source_backed_observations(self) -> None:
        cases = (
            ("NO_TWO_SIDED", [(k, None, a) for k, b, a in chains.CALLS], [(k, None, a) for k, b, a in chains.PUTS]),
            ("TWO_SIDED", [(104.0, 1.83, 1.87)], []),
        )
        for kind, calls, puts in cases:
            with self.subTest(kind=kind):
                cycle = yahoo_cycle(chains.yahoo_chain(calls=calls, puts=puts))
                observed = self.assert_call_observation(cycle, kind)
                self.assertIn(observed["strike"], [k for k, b, a in calls])
                self.assertIsNone(observed["last"])
                if kind == "NO_TWO_SIDED":
                    for field in ("bid", "ask", "annualized_yield"):
                        self.assertIsNone(observed[field], field)
                else:
                    self.assertEqual((observed["bid"], observed["ask"]), (1.83, 1.87))
                    self.assertAlmostEqual(observed["annualized_yield"], 1.83 / SPOT * 365 / chains.DTE, places=6)
                for name in ("cc", "csp", "collar"):
                    block = cycle["strategies"][name]
                    self.assertTrue(block.get("unavailable"), name)
                    self.assertFalse(block.get("suggestions"), name)
                    self.assertFalse(block.get("items"), name)


class OneSidedRecommendationTests(unittest.TestCase):
    def test_one_sided_yahoo_calls_never_become_executable_asks_or_yields(self) -> None:
        for absent in (None,0.0):
            chain=chains.yahoo_chain(calls=[(k,b,absent) for k,b,_ in chains.CALLS],
                                     puts=[(k,b,absent) for k,b,_ in chains.PUTS])
            with mock.patch.dict(sys.modules,{"yfinance":chains.yahoo_module(chain)}):
                result=builder.us_options("AAA",SPOT,TODAY,STAMP)
            cycle=result["monthly"]
            validate(cycle)
            self.assertFalse(next(h for h in result.health if h["cycle"]=="monthly")["two_sided"])
            self.assertEqual(cycle["suggestions"],[])
            self.assertEqual(cycle["quote_observation"]["kind"],"NO_TWO_SIDED")
            for name in ("cc","csp","collar"):
                self.assertTrue(cycle["strategies"][name]["unavailable"])

    def test_missing_sell_bid_or_buy_ask_refuses_put_strategies(self) -> None:
        for name,puts in (
            ("sell_bid",[(k,None,a) for k,_,a in chains.PUTS]),
            ("buy_ask",[(k,b,None) for k,b,_ in chains.PUTS])):
            with self.subTest(name=name):
                cycle=yahoo_cycle(chains.yahoo_chain(puts=puts))
                validate(cycle)
                self.assertEqual(len(cycle["suggestions"]),2)
                self.assertIn("unavailable",cycle["strategies"]["csp"])
                self.assertIn("unavailable",cycle["strategies"]["collar"])
                self.assertFalse(cycle["strategies"]["csp"].get("suggestions"))

    def test_weekly_one_sided_quotes_refuse_but_preserve_chain_evidence(self) -> None:
        calls,puts=chains.bs_chain(3)
        chain=chains.yahoo_chain([(k,b,None) for k,b,_ in calls],[(k,None,a) for k,_,a in puts])
        stamp="2026-10-13T15:00:00Z"
        with mock.patch.dict(sys.modules,{"yfinance":chains.yahoo_module(chain,"2026-10-16")}):
            result=builder.us_options("AAA",SPOT,date(2026,10,13),stamp)
        cycle=result["weekly"]
        # The publisher rejects malformed all-one-sided weekly cycles;
        # a rejected raw cycle is not permitted to become a recommendation.
        with self.assertRaises(MarketProductValidationError):
            validate_covered_call_cycle(cycle,evaluated_at=stamp,document_at=stamp,period="weekly")
        self.assertEqual(cycle.get("suggestions",[]),[])
        if "quote_observation" in cycle:
            self.assertEqual(cycle["quote_observation"]["kind"],"NO_TWO_SIDED")
        else:
            self.assertIn("unavailable",cycle)
        self.assertFalse(next(h for h in result.health if h["cycle"]=="weekly")["two_sided"])

    def test_missing_midpoint_never_fabricates_delta_or_reinterprets_source_delta(self) -> None:
        call={"strike":110.,"bid":.5,"ask":None,"iv":None}
        put={"strike":94.,"bid":.5,"ask":None,"iv":None}
        for delta in (None,-.1,True,float("nan"),float("inf"),.2,.2003):
            self.assertEqual(builder.covered_call_suggestions([{**call,"delta":delta}],SPOT,chains.DTE),[])
            self.assertEqual(builder.cash_secured_put_tiers([{**put,"delta":delta}],SPOT,chains.DTE)[0],[])
        for strike in (100.,99.,110.001):
            self.assertEqual(builder.covered_call_suggestions([{**call,"strike":strike,"delta":.1}],SPOT,chains.DTE),[])

    def test_malformed_opposite_quotes_are_not_normalized_as_absence(self) -> None:
        for invalid in (-.01,float("nan"),float("inf"),10**309,True,"bad",[],{}):
            with self.subTest(invalid_type=type(invalid).__name__):
                chain=chains.yahoo_chain(calls=[(112.,.5,invalid)])
                cycle=yahoo_cycle(chain)
                validate(cycle)
                self.assertEqual(cycle["suggestions"],[])
                self.assertTrue(cycle["strategies"]["cc"]["unavailable"])
                for parser in (builder._float,builder._nasdaq_us_quote,builder._nordic_price):
                    value=builder._quote_value(invalid,parser)
                    self.assertTrue(cycle["strategies"]["cc"]["unavailable"])

    def test_quoted_leg_tampering_never_forges_premium_or_executable_mid(self) -> None:
        good=yahoo_cycle()
        validate(good)
        for field,value in (("bid",None),("ask",None),("ask",0),("ask",-1),
                            ("ask",float("nan")),("mid",1),
                            ("limit_price",99),("delta_basis","QUOTED"),
                            ("delta_basis",None)):
            bad=copy.deepcopy(good)
            bad["suggestions"][0][field]=value
            with self.assertRaises(MarketProductValidationError,msg=field):
                validate(bad)
        for field,value in (("limit_price",0),("premium_per_contract",999)):
            bad=copy.deepcopy(good)
            bad["strategies"]["csp"]["suggestions"][0][field]=value
            with self.assertRaises(MarketProductValidationError,msg=field):
                validate(bad)

    def test_one_bad_collar_leg_degrades_without_hiding_good_call_and_csp(self) -> None:
        good=yahoo_cycle()
        validate(good)
        bad=copy.deepcopy(good)
        bad["strategies"]["collar"]["put"]["ask"]=None
        degraded=degrade_bad_strategy_blocks(bad)
        validate(degraded)
        self.assertEqual(degraded["suggestions"],good["suggestions"])
        self.assertEqual(degraded["strategies"]["csp"],good["strategies"]["csp"])
        self.assertEqual(degraded["strategies"]["collar"],{"unavailable":"報價未通過驗證"})


class RecommendationReasonTests(unittest.TestCase):
    def test_wide_quotes_without_verified_hv_refuse_all_three_without_forged_midpoint(self) -> None:
        calls=[(k,.01,.50) for k,_,_ in chains.CALLS]
        puts=[(k,.01,.50) for k,_,_ in chains.PUTS]
        cycle=yahoo_cycle(chains.yahoo_chain(calls=calls,puts=puts))
        validate(cycle)
        self.assertEqual(cycle["suggestions"],[])
        self.assertEqual(cycle["quote_observation"]["kind"],"TWO_SIDED")
        for name in ("cc","csp","collar"):
            self.assertIn("HV20/HV60",cycle["strategies"][name]["unavailable"])
        for omitted in ([],None):
            independent=yahoo_cycle(chains.yahoo_chain(calls=calls,puts=omitted))
            validate(independent)
            self.assertEqual(independent["suggestions"],[])
            for name in ("csp","collar"):
                self.assertIn("unavailable",independent["strategies"][name])

    def test_call_delta_refusal_does_not_discard_valid_puts(self) -> None:
        cycle = yahoo_cycle(chains.yahoo_chain(calls=[(104.0, 1.83, 1.87)]))
        validate(cycle)
        self.assertIn("Delta 不超過 0.20", cycle["strategies"]["cc"]["unavailable"])
        self.assertIn("delta 介於 0.20–0.30", cycle["strategies"]["collar"]["unavailable"])
        self.assertEqual(cycle["strategies"]["csp"], yahoo_cycle()["strategies"]["csp"])

    def test_synthetic_nordic_wide_chain_refuses_without_hv(self) -> None:
        puts=[(round(13+index/100,2),.01,.50) for index in range(299)]
        cycle=nordic_cycle(chains.nordic_rows(calls=[(16.4,.5,2.5)],puts=puts),spot=16.2)["monthly"]
        validate(cycle)
        self.assertEqual(cycle["suggestions"],[])
        # N3: a CC strike-band refusal must not be labelled with the put-side
        # HV or with a concatenation of unrelated strategy reasons.
        self.assertIn("Delta 不超過 0.20",cycle["strategies"]["cc"]["unavailable"])
        self.assertNotIn("賣權：",cycle["strategies"]["cc"]["unavailable"])
        self.assertNotIn("領口：",cycle["strategies"]["cc"]["unavailable"])
        self.assertIn("unavailable",cycle["strategies"]["csp"])
        self.assertIn("unavailable",cycle["strategies"]["collar"])

    def test_later_expiry_puts_never_supply_nearest_month_strategy_or_reason(self) -> None:
        later="2026-12-18"
        calls=[{"expiry":EXPIRY,"dte":chains.DTE,"size":100,"strike":110.,
                "bid":.01,"ask":.50,"delta":.35}]
        puts=[{"expiry":later,"dte":(date.fromisoformat(later)-TODAY).days,"size":100,
               "strike":k,"bid":bid,"ask":ask,"iv":chains.IV} for k,bid,ask in chains.PUTS]
        cycle=builder._cycles_from_calls(calls,"AAA",SPOT,STAMP,currency="USD",
            source="synthetic",provenance="https://example.com/options",
            rights=builder.YAHOO_RIGHTS_LABEL,missing="無到期資料",
            today=TODAY,identity=builder.YAHOO_OPTION_IDENTITY,puts=puts)["monthly"]
        validate(cycle)
        self.assertEqual(cycle["expiry"],EXPIRY)
        self.assertIn("HV20/HV60",cycle["strategies"]["cc"]["unavailable"])
        for name in ("csp","collar"):
            self.assertTrue(cycle["strategies"][name]["unavailable"])
            self.assertFalse(cycle["strategies"][name].get("suggestions"))

    def test_otm_required_side_and_delta_failures_are_distinguished(self) -> None:
        for bid,ask in ((None,.50),(.50,None),(.50,.40)):
            puts=[{"strike":90.,"bid":bid,"ask":ask},
                  {"strike":101.,"bid":1.,"ask":1.04}]
            calls=[{"strike":110.,"bid":bid,"ask":ask},
                   {"strike":99.,"bid":1.,"ask":1.04}]
            csp,reason=builder.cash_secured_put_tiers(puts,SPOT,chains.DTE)
            collar,creason=builder.collar_tiers(calls,puts,SPOT,chains.DTE)
            self.assertEqual(csp,[])
            self.assertIsNone(collar)
            self.assertTrue(reason)
            self.assertTrue(creason)
            self.assertTrue(builder._covered_call_unavailable(calls,SPOT,chains.DTE,EXPIRY,model=None))

    def test_all_unavailable_requires_a_valid_observation_and_cc_reason(self) -> None:
        cycle = yahoo_cycle(chains.yahoo_chain(calls=[(104.0, 1.83, 1.87)], puts=[]))
        validate(cycle)
        for mutation in ("no_observation", "bad_observation", "missing_cc", "empty_cc", "oversized_cc"):
            bad = copy.deepcopy(cycle)
            if mutation == "no_observation":
                del bad["quote_observation"]
            elif mutation == "bad_observation":
                bad["quote_observation"]["annualized_yield"] = 99
            elif mutation == "missing_cc":
                del bad["strategies"]["cc"]
            else:
                bad["strategies"]["cc"]["unavailable"] = "" if mutation == "empty_cc" else "x" * 201
            with self.assertRaises(MarketProductValidationError, msg=mutation):
                validate(bad)


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
    NOW = datetime(2026, 10, 23, 17, 5, tzinfo=UTC)

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

    def test_bad_put_blocks_preserve_a_valid_observation_but_not_a_strategy_only_cycle(self) -> None:
        cycle = yahoo_cycle(chains.yahoo_chain(calls=[(k, None, a) for k, b, a in chains.CALLS]))
        cycle["strategies"]["csp"]["suggestions"][0]["cash_required"] = 1.0
        self.assertEqual(list(cycle["strategies"]["collar"]), ["unavailable"])  # no call quote, so no collar either
        sealed = json.loads(self.seal({"AAA": {"monthly": cycle}}, {"AAA"})["v213:options:v2"])["options"]["AAA"]["monthly"]
        self.assertEqual(sealed["quote_observation"], cycle["quote_observation"])
        self.assertEqual(sealed["strategies"]["csp"], {"unavailable": "報價未通過驗證"})
        self.assertEqual(sealed["strategies"]["cc"], cycle["strategies"]["cc"])
        self.assertEqual(sealed["strategies"]["collar"], cycle["strategies"]["collar"])
        del cycle["quote_observation"]
        refused = json.loads(self.seal({"AAA": {"monthly": cycle}}, {"AAA"})["v213:options:v2"])["options"]["AAA"]["monthly"]
        self.assertEqual(list(refused), ["unavailable"])
        self.assertIn("報價未通過驗證", refused["unavailable"])

    def test_all_unavailable_observation_reasons_survive_the_sealer_unchanged(self) -> None:
        from tests.fixtures.v21_worker_cases import generate_fixture_document
        for name, cycle in generate_fixture_document()["observations"].items():
            with self.subTest(name=name):
                sealed = json.loads(self.seal({"AAA": {"monthly": cycle}}, {"AAA"})["v213:options:v2"])["options"]["AAA"]["monthly"]
                self.assertEqual(sealed, cycle)

    def test_over_the_size_cap_fails_loudly_without_stripping_strategies(self) -> None:
        good = yahoo_cycle()
        options = {f"T{i:03d}": {"monthly": dict(good, ticker=f"T{i:03d}")} for i in range(40)}
        baseline = copy.deepcopy(options)
        compact = len(json.dumps(good, ensure_ascii=False, separators=(",", ":")))
        with mock.patch.object(publisher,"LAZY_BODY_MAX_BYTES", 40 * compact - 20_000):
            with self.assertRaisesRegex(RuntimeError,"STAGE1F_OPTIONS_CAP_EXCEEDED"):
                self.seal(options,set(options))
        self.assertEqual(options,baseline)
        with mock.patch.object(publisher,"LAZY_BODY_MAX_BYTES",1000):
            with self.assertRaisesRegex(RuntimeError,"STAGE1F_OPTIONS_CAP_EXCEEDED"):
                self.seal(options,set(options))


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

    def test_one_sided_live_recommendations_never_replace_a_two_sided_capture(self) -> None:
        calls, puts = chains.bs_chain(3)
        for name, call_rows, put_rows in (
                ("call ask", [(k, b, None) for k, b, _ in calls], puts),
                ("csp ask", calls, [(k, b, None) for k, b, _ in puts]),
                ("protective bid", calls, [(k, None, a) for k, _, a in puts])):
            with self.subTest(name=name):
                chain = chains.yahoo_chain(call_rows, put_rows)
                with mock.patch.dict(sys.modules, {"yfinance": chains.yahoo_module(chain, "2026-10-16")}):
                    live = builder.us_options("T00", SPOT, date(2026, 10, 13), self.stamp)["weekly"]
                validate_covered_call_cycle(live, self.stamp, self.stamp, "weekly")
                state = self.state()
                state.cycles, state._loaded = {"T00": {"weekly": copy.deepcopy(self.cycle)}}, True
                # A valid subset such as quoted puts can be stored, but no
                # missing-side call/put is ever admitted as an executable leg.
                self.assertEqual(state.capture({"T00": {"weekly": live}}, self.IN_SESSION), 1)
                self.assertTrue(carry._stored_cycle_ok("T00", "weekly", live, self.IN_SESSION))
                self.assertEqual(state.cycles["T00"]["weekly"],live)
                options = {"T00": {"weekly": live}}
                health = [{"venue": "US", "underlying": "T00", "expiry": "2026-10-16", "cycle": "weekly",
                           "status": "READ", "read": True, "two_sided": False}]
                self.assertEqual(state.apply(options, health, self.OFF_SESSION), 0)
                self.assertEqual(options["T00"]["weekly"],live)
                carried = copy.deepcopy(live)
                carried["quote_basis"] = "previous_session_last"
                for block in carried["strategies"].values():
                    if "quote_basis" in block:
                        block["quote_basis"] = "previous_session_last"
                validate_covered_call_cycle(carried, self.OFF_SESSION, self.OFF_SESSION, "weekly", allow_previous_session=True)
                if name == "call ask":
                    self.assertEqual(carried["suggestions"], [])
                elif name == "csp ask":
                    self.assertIn("unavailable", carried["strategies"]["csp"])
                else:
                    self.assertIn("unavailable", carried["strategies"]["collar"])

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
        self.assertLess(600 * full, publisher.LAZY_BODY_MAX_BYTES * 0.97)

    def test_the_constants_are_shared_and_pinned(self) -> None:
        self.assertEqual(rules.CONSERVATIVE_DELTA_BAND, (0.20, 0.30))
        self.assertEqual(rules.PROTECTIVE_PUT_DELTA, 0.15)
        self.assertEqual(builder.MAX_HIGH_STRIKE_DELTA, 0.20)  # master ruling O1
        self.assertFalse(hasattr(builder, "MIN_ANNUALIZED_YIELD"))  # the floor was removed on 2026-11-03


class Stage1GHistoryDedupeTests(unittest.TestCase):
    def test_carried_and_current_periods_with_distinct_hv_do_not_abort(self):
        import copy
        import publish_sealed_snapshot as sealed
        keys=sealed.STAGE1F_HISTORY_KEYS
        baseline={"ticker":"AAA","currency":"USD","hv20":.30,"hv60":.31,
                  "observations":61,"start_date_20":"2026-09-24",
                  "start_date_60":"2026-07-28","asof_date":"2026-10-22",
                  "source_url":"https://query1.finance.yahoo.com/v8/finance/chart/AAA?interval=1d&range=6mo",
                  "source_sha256":"a"*64,"price_basis":"PROVIDER_ADJUSTED_CLOSE"}
        earlier=[baseline[k] for k in keys]
        later=copy.deepcopy(baseline)
        later.update(asof_date="2026-10-23",source_sha256="b"*64)
        current=[later[k] for k in keys]
        options={"AAA":{"weekly":{"quote_basis":"previous_session_last",
                    "historical_volatility":earlier.copy()},
                        "monthly":{"quote_basis":"delayed",
                    "historical_volatility":current.copy()}}}
        sealed.dedupe_sealed_history(options)
        self.assertNotIn("_hv", options["AAA"])
        self.assertEqual(options["AAA"]["weekly"]["historical_volatility"], earlier)
        self.assertEqual(options["AAA"]["monthly"]["historical_volatility"], current)
        self.assertEqual(sealed.expand_sealed_cycle(
            options["AAA"]["weekly"])["historical_volatility"], baseline)
        self.assertEqual(sealed.expand_sealed_cycle(
            options["AAA"]["monthly"])["historical_volatility"], later)
        identical={"AAA":{"weekly":{"historical_volatility":earlier.copy()},
                           "monthly":{"historical_volatility":earlier.copy()}}}
        sealed.dedupe_sealed_history(identical)
        self.assertEqual(identical["AAA"]["_hv"],earlier)
        self.assertEqual(identical["AAA"]["weekly"]["historical_volatility"],"@")
        self.assertEqual(identical["AAA"]["monthly"]["historical_volatility"],"@")

if __name__ == "__main__":
    unittest.main()
