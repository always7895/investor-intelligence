"""Stage 1E master ruling 1-6: isolated side quote and volatility evidence.

Synthetic offline tests; no network or broker. Validate historical per-leg clamp,
Stage1C tight-side source priority, one-sided isolation and monotonic wide-only
exclusion. All scenario quotes arise from the actual Black-Scholes implementation.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import option_delta_side_model as side
import option_delta_model as bs


class SideScopedDeltaTests(unittest.TestCase):
    SPOT = 100.0
    DTE = 28

    @staticmethod
    def source_spread_above_old_threshold(value):
        # Legacy 25%-of-mid spread is a *test diagnostic only*, not the
        # Stage1G selection trigger (which is Delta uncertainty > 0.10).
        return (value["ask"] - value["bid"]) / (value["bid"] / 2 + value["ask"] / 2) > .25

    def quote(self, strike: float, low_vol: float, high_vol: float, *, put: bool = False,
              given_iv: float | None = None, source_delta: float | None = None):
        t = self.DTE / 365
        price = bs.bs_put_price if put else bs.bs_call_price
        bid = price(self.SPOT, strike, t, low_vol)
        ask = price(self.SPOT, strike, t, high_vol)
        self.assertLessEqual(bid, ask)
        self.assertGreater(bid, 0)
        return {"strike": strike, "bid": bid, "ask": ask, "iv": given_iv,
                "delta": source_delta, "oi": 11, "volume": 7}

    def test_all_tight_source_iv_wins_over_provider_delta_and_preserves_stage1c(self):
        row = self.quote(115.0, .30, .31, given_iv=.30, source_delta=.99)
        self.assertFalse(self.source_spread_above_old_threshold(row))
        out = side.calculate_side([row], self.SPOT, self.DTE, None)
        self.assertEqual(out["basis"], "QUOTE_IMPLIED")
        self.assertEqual(len(out["computed"]), 1)
        leg = out["computed"][0]
        self.assertEqual((leg["_entry"]["mode"], leg["delta_basis"], leg["iv"]),
                         ("SOURCE_IV", "QUOTED_IV", .30))
        self.assertNotEqual(leg["delta"], .99)

    def test_all_tight_quoted_delta_is_not_replaced_by_the_midpoint_iv(self):
        row = self.quote(115, .30, .31, source_delta=.12)
        out = side.calculate_side([row], self.SPOT, self.DTE, None)
        self.assertEqual(len(out["computed"]), 1)
        self.assertEqual(out["computed"][0]["_entry"]["mode"], "SOURCE_DELTA")
        self.assertEqual((out["computed"][0]["delta"], out["computed"][0]["delta_basis"]),
                         (.12, "QUOTED"))

    def test_all_tight_different_leg_iv_ranges_do_not_require_intersection(self):
        first = self.quote(110, .31, .32)
        second = self.quote(115, .55, .56)
        self.assertFalse(self.source_spread_above_old_threshold(first))
        self.assertFalse(self.source_spread_above_old_threshold(second))
        result = side.calculate_side([first, second], self.SPOT, self.DTE, None)
        self.assertEqual(result["basis"], "QUOTE_IMPLIED")
        self.assertEqual(len(result["computed"]), 2)
        self.assertEqual(result["skipped"], [])
        self.assertTrue(all(x["delta_basis"] == "QUOTE_IMPLIED" for x in result["computed"]))

    def test_any_wide_call_uses_per_leg_hv_clamp_with_disjoint_iv_ranges(self):
        # High-IV closer strike, lower-IV farther strike: monotone delta is
        # maintained, despite the IV intervals being completely disjoint.
        calls = [self.quote(110, 1.4, 1.9), self.quote(115, .60, .95)]
        self.assertTrue(all(self.source_spread_above_old_threshold(v) for v in calls))
        history = {"observations": 61, "hv20": .7, "hv60": 1.0}
        out = side.calculate_side(calls, self.SPOT, self.DTE, history)
        self.assertEqual(out["basis"], "HISTORICAL_VOL")
        self.assertEqual(len(out["computed"]), 2, out["skipped"])
        a, b = out["computed"]
        self.assertNotAlmostEqual(a["_entry"]["sigma"], b["_entry"]["sigma"])
        for row in out["computed"]:
            e = row["_entry"]
            self.assertEqual(e["mode"], "HISTORICAL_VOL")
            self.assertGreaterEqual(e["sigma"], e["iv_bid"])
            self.assertLessEqual(e["sigma"], e["iv_ask"])
            self.assertAlmostEqual(e["sigma"], min(e["iv_ask"], max(1.0, e["iv_bid"])), places=10)
            self.assertEqual(row["delta_basis"], "HISTORICAL_VOL")
            self.assertIsNone(row["iv"])

    def test_missing_history_refuses_only_the_side_requiring_hv(self):
        wide_call = self.quote(120, .4, 1.2)
        tight_put = self.quote(95, .29, .30, put=True, given_iv=.30)
        self.assertTrue(self.source_spread_above_old_threshold(wide_call))
        self.assertFalse(self.source_spread_above_old_threshold(tight_put))
        calls = side.calculate_side([wide_call], self.SPOT, self.DTE, None)
        puts = side.calculate_side([tight_put], self.SPOT, self.DTE, None, put=True)
        self.assertEqual(calls["computed"], [])
        self.assertIn("HV20/HV60", calls["reason"])
        self.assertEqual(len(puts["computed"]), 1)
        self.assertEqual(puts["basis"], "QUOTE_IMPLIED")

    def test_one_sided_skips_only_invalid_contract_and_keeps_other_leg(self):
        eligible = self.quote(115, .3, .31, given_iv=.3)
        one_sided = {"strike": 130., "bid": .2, "ask": None, "delta": .03, "iv": .3}
        out = side.calculate_side([one_sided, eligible], self.SPOT, self.DTE, None)
        self.assertEqual(len(out["computed"]), 1)
        self.assertEqual(out["computed"][0]["strike"], 115.)
        self.assertEqual(out["basis"], "QUOTE_IMPLIED")
        self.assertEqual(len(out["skipped"]), 1)
        self.assertIn("雙邊", out["skipped"][0]["reason"])

    def test_monotonicity_drops_only_offending_wide_leg(self):
        inputs = [
            {"strike": 105., "bid": 1., "ask": 1.1, "delta_exact": .31, "_wide": False},
            {"strike": 110., "bid": 1., "ask": 2., "delta_exact": .38, "_wide": True},
            {"strike": 115., "bid": 1., "ask": 1.1, "delta_exact": .18, "_wide": False},
            {"strike": 120., "bid": 1., "ask": 2., "delta_exact": .12, "_wide": True},
        ]
        skipped = []
        actual = side._monotone_side(inputs, put=False, skipped=skipped)
        self.assertEqual([r["strike"] for r in actual], [105., 115., 120.])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["strike"], 110.)
        self.assertIn("非單調", skipped[0]["reason"])
        self.assertEqual([r["strike"] for r in actual if not r["_wide"]], [105., 115.])

    def test_compact_wire_is_closed_and_does_not_embed_unverifiable_model_prices(self):
        calls = side.calculate_side([self.quote(115., .3, .31, given_iv=.3)], 100., self.DTE, None)
        puts = side.calculate_side([self.quote(95., .3, .31, put=True, given_iv=.3)], 100., self.DTE, None, put=True)
        wire = side.cycle_model_wire(calls, puts, calls["computed"], puts["computed"])
        self.assertTrue(side.valid_side_model(wire, None))
        self.assertTrue(wire.startswith("E1|Q,"))
        self.assertLess(len(wire), 45)
        self.assertFalse(side.valid_side_model(wire+"EXTRA", None))
        self.assertFalse(side.valid_side_model("E1|X,0,-|H,0,-", None))

    def test_history_model_validates_delta_against_both_real_quote_sides(self):
        row = self.quote(115., .30, 1.8)
        h = {"hv20": 1.3, "hv60": 1.4, "observations": 61}
        self.assertTrue(side.is_uncertain(row,100.,self.DTE,put=False))
        out = side.calculate_side([row], 100., self.DTE, h)
        self.assertEqual(len(out["computed"]), 1)
        leg = out["computed"][0]
        wire = side.cycle_model_wire(out, side.calculate_side([],100.,self.DTE,h,put=True), [leg], [])
        self.assertTrue(side.model_leg_consistent(leg, wire, h, 100., self.DTE, put=False))
        tampered = {**leg, "delta": leg["delta"] + .01}
        self.assertFalse(side.model_leg_consistent(tampered, wire, h, 100., self.DTE, put=False))
        self.assertFalse(side.model_leg_consistent(leg, wire, None, 100., self.DTE, put=False))

    def test_stage1g_decimal_tick_model_limits_snap_after_bounds(self):
        from decimal import Decimal
        cases = [
            (.01, 1.35, 9.0, .68, .68),      # mid=.68
            (.30, .37, 9.0, .33, .33),       # mid=.335: no .335 limit
            (.31, .36, .335, .33, .33),     # mid=.335 => both cap at .33
            (.01, 1.24, 5.0, .62, .62),    # mid=.625 => floor=.62
            (.01, 2.50, .0565, .05, .06),
            (.07, 2.50, .2717, .27, .28),
            (.01, .40, 0.0, .01, .01),      # zero theoretical -> Bid
        ]
        for bid, ask, theoretical, sell, buy in cases:
            with self.subTest(bid=bid,ask=ask,theoretical=theoretical):
                for expected, direction in ((sell,False),(buy,True)):
                    result=side.decimal_tick_limit(bid,ask,theoretical,buy=direction)
                    self.assertEqual(result,expected)
                    self.assertEqual(Decimal(str(result)) % Decimal(".01"),0)
                    self.assertGreaterEqual(result,bid)
                    self.assertLessEqual(Decimal(str(result)),
                        ((Decimal(str(bid))+Decimal(str(ask)))/2).quantize(
                        Decimal(".01"),rounding="ROUND_FLOOR"))
        # If a source supplies a non-grid Bid with no executable cent between
        # it and mid, fail closed rather than output a phantom off-tick order.
        self.assertIsNone(side.decimal_tick_limit(.335,.335,.335,buy=False))
        self.assertIsNone(side.decimal_tick_limit(.335,.335,.335,buy=True))

    def test_absurd_integer_is_invalid_not_an_abort(self):
        self.assertFalse(side.finite(10**309))
        x = side.calculate_side([{"strike": 115., "bid": 1., "ask": 10**309}], 100., self.DTE, None)
        self.assertEqual(x["computed"], [])
        self.assertTrue(x["skipped"])


if __name__ == "__main__":
    unittest.main()
