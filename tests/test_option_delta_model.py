"""Behavioral common-sigma regressions using explicitly synthetic quotes."""
from __future__ import annotations

import copy
import math
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import option_delta_model as model  # noqa: E402
from tests.test_option_historical_volatility import calculate, synthetic_chart  # noqa: E402

SPOT = 100.0
DTE = 30
YEARS = DTE / 365


def quote(strike: float, low: float, high: float, *, put: bool = False, dte: float = DTE) -> dict[str, Any]:
    price = model.bs_put_price if put else model.bs_call_price
    bid = price(SPOT, strike, max(dte, 1) / 365, low)
    ask = price(SPOT, strike, max(dte, 1) / 365, high)
    assert bid is not None and ask is not None
    return {"strike": strike, "bid": bid, "ask": ask}


def history(hv20: float = 0.3, hv60: float = 0.5) -> dict[str, Any]:
    # Source bytes are synthetic; override realized values for isolated formula cases.
    evidence = calculate(synthetic_chart())
    assert evidence is not None
    return {**evidence, "hv20": hv20, "hv60": hv60}


def displayed(leg: dict[str, Any], delta_model: dict[str, Any], *, put: bool = False,
              iv: bool = False, dte: float = DTE) -> dict[str, Any]:
    call = model.bs_call_delta(SPOT, leg["strike"], max(dte, 1) / 365, delta_model["sigma"], digits=None)
    assert call is not None
    value = {**leg, "delta_basis": delta_model["basis"], "delta": round(1 - call if put else call, 3)}
    if iv:
        value["iv"] = None if delta_model["basis"] == "HISTORICAL_VOL" else round(delta_model["sigma"], 4)
    return value


class BlackScholesTests(unittest.TestCase):
    def test_put_call_parity_and_full_precision_delta(self) -> None:
        call = model.bs_call_price(100, 105, YEARS, 0.4)
        put = model.bs_put_price(100, 105, YEARS, 0.4)
        assert call is not None and put is not None
        self.assertAlmostEqual(call - put, 100 - 105 * math.exp(-0.04 * YEARS), places=12)
        exact = model.bs_call_delta(100, 105, YEARS, 0.4, digits=None)
        assert exact is not None
        self.assertEqual(model.bs_call_delta(100, 105, YEARS, 0.4), round(exact, 3))
        self.assertNotEqual(exact, round(exact, 3))
        self.assertGreater(model.bs_call_delta(100, 105, YEARS, 0.4, rate=0.08), exact)

    def test_adaptive_inversion_exceeds_five_hundred_percent(self) -> None:
        for price_function, inverse in ((model.bs_call_price, model.implied_vol), (model.bs_put_price, model.implied_vol_put)):
            for sigma in (0.2, 2.0, 6.0, 12.0):
                with self.subTest(function=inverse.__name__, sigma=sigma):
                    price = price_function(100, 100, 1 / 365, sigma)
                    assert price is not None
                    inferred = inverse(price, 100, 100, 1 / 365)
                    assert inferred is not None
                    self.assertAlmostEqual(inferred, sigma, places=10)

    def test_theoretical_endpoints_and_malformed_inputs(self) -> None:
        for strike, price_function, inverse, upper in (
            (90, model.bs_call_price, model.implied_vol, 100),
            (110, model.bs_put_price, model.implied_vol_put, 110 * math.exp(-0.04 * YEARS)),
        ):
            lower = price_function(100, strike, YEARS, 0)
            assert lower is not None
            self.assertEqual(inverse(lower, 100, strike, YEARS), 0)
            self.assertIsNone(inverse(lower - 0.01, 100, strike, YEARS))
            self.assertIsNone(inverse(upper, 100, strike, YEARS))
            self.assertIsNone(inverse(upper + 1, 100, strike, YEARS))
        self.assertEqual(model.implied_vol(0, 100, 110, YEARS), 0)
        for bad in (None, True, "1", float("nan"), float("inf"), -1, 10 ** 400):
            self.assertIsNone(model.implied_vol(bad, 100, 105, YEARS))
            self.assertIsNone(model.implied_vol_put(bad, 100, 95, YEARS))
            self.assertIsNone(model.bs_call_delta(100, 105, YEARS, bad))
        self.assertIsNone(model.bs_call_price(True, 100, YEARS, 0.3))
        self.assertIsNone(model.bs_put_price(100, 100, 0, 0.3))


class CohortModelTests(unittest.TestCase):
    def build(self, calls: list[dict[str, Any]], puts: list[dict[str, Any]], hv: Any = None,
              dte: float = DTE) -> dict[str, Any]:
        value, reason = model.build_delta_model(calls, puts, SPOT, dte, hv)
        self.assertIsNone(reason)
        self.assertIsNotNone(value)
        assert value is not None
        self.assertTrue(model.valid_delta_model(value, hv))
        self.assertEqual(set(value), {"basis", "sigma", "iv_bid", "iv_ask"})
        return value

    def test_tight_cohort_uses_common_iv_interval_midpoint_not_price_midpoint(self) -> None:
        calls = [quote(101, 0.38, 0.41), quote(105, 0.39, 0.42)]
        puts = [quote(95, 0.385, 0.415, put=True)]
        value = self.build(calls, puts)
        self.assertEqual(value["basis"], "QUOTE_IMPLIED")
        self.assertAlmostEqual(value["iv_bid"], 0.39, places=10)
        self.assertAlmostEqual(value["iv_ask"], 0.41, places=10)
        self.assertAlmostEqual(value["sigma"], 0.4, places=10)
        for leg in calls:
            self.assertTrue(model.model_leg_consistent(displayed(leg, value, iv=True), value, SPOT, DTE))
        for leg in puts:
            self.assertTrue(model.model_leg_consistent(displayed(leg, value, put=True), value, SPOT, DTE, put=True))

    def test_wide_cohort_uses_larger_hv_and_clamps_both_bounds(self) -> None:
        calls, puts = [quote(105, 0.2, 0.8)], [quote(95, 0.25, 0.7, put=True)]
        for hv20, hv60, expected in ((0.3, 0.5, 0.5), (0.6, 0.4, 0.6), (0.0, 0.0, 0.25), (1.2, 0.9, 0.7)):
            with self.subTest(hv20=hv20, hv60=hv60):
                value = self.build(calls, puts, history(hv20, hv60))
                self.assertEqual(value["basis"], "HISTORICAL_VOL")
                self.assertAlmostEqual(value["iv_bid"], 0.25, places=10)
                self.assertAlmostEqual(value["iv_ask"], 0.7, places=10)
                self.assertAlmostEqual(value["sigma"], expected, places=10)
                self.assertTrue(model.model_leg_consistent(displayed(calls[0], value, iv=True), value, SPOT, DTE))
                self.assertTrue(model.model_leg_consistent(displayed(puts[0], value, put=True), value, SPOT, DTE, put=True))

    def test_history_from_actual_synthetic_chart_drives_model(self) -> None:
        hv = calculate(synthetic_chart())
        assert hv is not None
        value = self.build([quote(105, 0.1, 0.8)], [], hv)
        self.assertAlmostEqual(value["sigma"], max(hv["hv20"], hv["hv60"]), places=12)

    def test_common_sigma_preserves_monotone_call_delta_without_using_source_greeks(self) -> None:
        calls = [{**quote(strike, 0.2, 0.8), "iv": 9.0, "delta": 0.99} for strike in (101, 105, 110)]
        original = copy.deepcopy(calls)
        value = self.build(calls, [], history())
        deltas = [model.bs_call_delta(SPOT, leg["strike"], YEARS, value["sigma"], digits=None) for leg in calls]
        self.assertTrue(all(left > right for left, right in zip(deltas, deltas[1:])))
        self.assertEqual(calls, original)
        plain = [{key: leg[key] for key in ("strike", "bid", "ask")} for leg in calls]
        self.assertEqual(self.build(plain, [], history()), value)

    def test_quarter_spread_boundary_is_tight_and_strictly_above_is_wide(self) -> None:
        boundary = {"strike": 105.0, "bid": 7.0, "ask": 9.0}  # (9-7)/8 = .25 exactly.
        tight = self.build([boundary], [], dte=365)
        self.assertEqual(tight["basis"], "QUOTE_IMPLIED")
        wide = self.build([{**boundary, "ask": 9.0001}], [], history(), dte=365)
        self.assertEqual(wide["basis"], "HISTORICAL_VOL")

    def test_mixed_cohort_refuses_without_discarding_any_eligible_leg(self) -> None:
        calls = [quote(105, 0.39, 0.41), quote(110, 0.2, 0.8)]
        original = copy.deepcopy(calls)
        value, reason = model.build_delta_model(calls, [], SPOT, DTE, history())
        self.assertIsNone(value)
        self.assertIn("混合", reason)
        self.assertEqual(calls, original)
        value, reason = model.build_delta_model([calls[0]], [quote(95, 0.2, 0.8, put=True)], SPOT, DTE, history())
        self.assertIsNone(value)
        self.assertIn("混合", reason)

    def test_empty_common_interval_refuses_entire_ranking(self) -> None:
        calls = [quote(105, 0.1, 0.3), quote(110, 0.6, 1.2)]
        value, reason = model.build_delta_model(calls, [], SPOT, DTE, history())
        self.assertIsNone(value)
        self.assertIn("交集為空", reason)

    def test_one_sided_or_bad_quote_refuses_even_with_source_greeks(self) -> None:
        good = quote(105, 0.2, 0.8)
        for changes in ({"bid": None}, {"ask": 0}, {"bid": True}, {"ask": float("inf")}, {"ask": good["bid"] / 2}):
            with self.subTest(changes=changes):
                bad = {**good, **changes, "iv": 0.5, "delta": 0.3}
                value, reason = model.build_delta_model([bad], [], SPOT, DTE, history())
                self.assertIsNone(value)
                self.assertIn("報價", reason)

    def test_missing_hv_and_unbounded_quote_have_distinct_causal_refusals(self) -> None:
        for hv in (None, {}, {"hv20": 0.2, "observations": 61}, {"hv20": 0.2, "hv60": 0.3, "observations": 21},
                   {"hv20": True, "hv60": 0.3, "observations": 61}):
            value, reason = model.build_delta_model([quote(105, 0.2, 0.8)], [], SPOT, DTE, hv)
            self.assertIsNone(value)
            self.assertIn("61", reason)
            self.assertIn("HV20/HV60", reason)
        value, reason = model.build_delta_model([{"strike": 105, "bid": 90, "ask": 110}], [], SPOT, DTE, history())
        self.assertIsNone(value)
        self.assertIn("IV 區間", reason)
        self.assertIn("理論界限", reason)

    def test_expiry_day_uses_one_calendar_day_and_invalid_context_fails(self) -> None:
        leg = quote(100.01, 0.2, 0.8, dte=0)
        value = self.build([leg], [], history(), dte=0)
        self.assertTrue(model.model_leg_consistent(displayed(leg, value, dte=0), value, SPOT, 0))
        for spot, dte in ((True, 30), (100, True), (0, 30), (100, -1), (100, float("nan"))):
            self.assertIsNone(model.build_delta_model([leg], [], spot, dte, history())[0])
        self.assertIsNone(model.build_delta_model([], [], SPOT, DTE, history())[0])


class SealedModelConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hv = history()
        self.quote = quote(105, 0.2, 0.8)
        value, reason = model.build_delta_model([self.quote], [], SPOT, DTE, self.hv)
        assert value is not None and reason is None
        self.model = value
        self.leg = displayed(self.quote, self.model, iv=True)

    def test_exact_model_wire_bounds_basis_and_arithmetic(self) -> None:
        self.assertTrue(model.valid_delta_model(self.model, self.hv))
        for key in self.model:
            value = dict(self.model)
            del value[key]
            self.assertFalse(model.valid_delta_model(value, self.hv))
        for changes in ({"extra": 1}, {"basis": "QUOTED"}, {"sigma": True}, {"sigma": float("nan")},
                        {"sigma": 0}, {"iv_bid": -0.1}, {"iv_ask": 0.1}, {"sigma": 0.4}):
            self.assertFalse(model.valid_delta_model({**self.model, **changes}, self.hv), changes)
        self.assertFalse(model.valid_delta_model(self.model, None))
        tight = {"basis": "QUOTE_IMPLIED", "sigma": 0.3, "iv_bid": 0.2, "iv_ask": 0.4}
        self.assertTrue(model.valid_delta_model(tight, None))
        self.assertFalse(model.valid_delta_model({**tight, "sigma": 0.31}, None))

    def test_leg_basis_price_delta_and_iv_must_match_common_model(self) -> None:
        self.assertTrue(model.model_leg_consistent(self.leg, self.model, SPOT, DTE))
        changes = ({"delta_basis": "QUOTED"}, {"delta": True}, {"delta": -0.2}, {"delta": self.leg["delta"] + 0.002},
                   {"iv": 0.5}, {"bid": self.quote["ask"] * 2, "ask": self.quote["ask"] * 4}, {"ask": None})
        for change in changes:
            self.assertFalse(model.model_leg_consistent({**self.leg, **change}, self.model, SPOT, DTE), change)
        strategy = dict(self.leg)
        del strategy["iv"]
        self.assertTrue(model.model_leg_consistent(strategy, self.model, SPOT, DTE))
        self.assertFalse(model.model_leg_consistent(self.leg, self.model, SPOT, DTE, put=True))

    def test_full_precision_band_cannot_be_bypassed_by_rounding_delta(self) -> None:
        exact = model.bs_call_delta(SPOT, self.leg["strike"], YEARS, self.model["sigma"], digits=None)
        assert exact is not None
        self.assertTrue(model.model_leg_consistent(self.leg, self.model, SPOT, DTE, band=(exact, exact)))
        self.assertFalse(model.model_leg_consistent(self.leg, self.model, SPOT, DTE, band=(0, exact - 0.00001)))
        for band in ((True, 1), (0.8, 0.2), (-1, 1), (0, 2)):
            self.assertFalse(model.model_leg_consistent(self.leg, self.model, SPOT, DTE, band=band))

    def test_sealed_tight_wide_substitution_is_rejected(self) -> None:
        price = model.bs_call_price(SPOT, 105, YEARS, self.model["sigma"])
        assert price is not None
        tight = {**self.leg, "bid": price * 0.99, "ask": price * 1.01}
        self.assertFalse(model.model_leg_consistent(tight, self.model, SPOT, DTE))

    def test_quote_implied_cc_iv_rounding_and_put_absolute_delta(self) -> None:
        leg = quote(105, 0.39, 0.41)
        value, _ = model.build_delta_model([leg], [], SPOT, DTE, None)
        assert value is not None
        shown = displayed(leg, value, iv=True)
        self.assertTrue(model.model_leg_consistent(shown, value, SPOT, DTE))
        self.assertFalse(model.model_leg_consistent({**shown, "iv": None}, value, SPOT, DTE))
        self.assertFalse(model.model_leg_consistent({**shown, "iv": shown["iv"] + 0.0002}, value, SPOT, DTE))
        put = quote(95, 0.2, 0.8, put=True)
        self.assertTrue(model.model_leg_consistent(displayed(put, self.model, put=True), self.model, SPOT, DTE, put=True))


if __name__ == "__main__":
    unittest.main()
