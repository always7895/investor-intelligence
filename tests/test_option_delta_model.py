"""Numerical primitives still used by the independent-side option model."""
from __future__ import annotations
import math
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import option_delta_model as model
import option_delta_side_model as side
DTE = 30
YEARS = DTE / 365


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


class CurrentSideModelBoundaryTests(unittest.TestCase):
    def test_retired_common_sigma_dictionary_is_not_admitted(self) -> None:
        for basis in ("QUOTE_IMPLIED", "HISTORICAL_VOL"):
            legacy = {"basis": basis, "sigma": 0.4, "iv_bid": 0.2, "iv_ask": 0.8}
            self.assertFalse(side.is_side_model(legacy))
            self.assertIsNone(side.parsed_side_model(legacy))
            self.assertFalse(side.valid_side_model(legacy, None))

    def test_current_independent_sides_remain_admitted(self) -> None:
        wire = "E1|H,2,105|Q,1,95"
        self.assertTrue(side.is_side_model(wire))
        self.assertTrue(side.valid_side_model(wire, None))
        self.assertEqual(side.parsed_side_model(wire), {
            "calls": ("HISTORICAL_VOL", 2, 105.0), "puts": ("QUOTE_IMPLIED", 1, 95.0)})

    def test_referenced_history_helper_keeps_zero_variance_and_refuses_bad_history(self) -> None:
        self.assertEqual(model._history_sigmas({"observations": 61, "hv20": 0, "hv60": 0.3}), (0, 0.3))
        for value in (None, {}, {"observations": 60, "hv20": 0.3, "hv60": 0.4},
                      {"observations": 61, "hv20": True, "hv60": 0.4},
                      {"observations": 61, "hv20": -0.1, "hv60": 0.4}):
            self.assertIsNone(model._history_sigmas(value))


if __name__ == "__main__":
    unittest.main()
