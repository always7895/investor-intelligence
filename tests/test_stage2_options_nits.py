"""Stage 2 follow-ups: decimal rounding parity and historical no-cent refusal."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import option_delta_side_model as side
import build_market_quotes_options as builder


class Stage2OptionNits(unittest.TestCase):
    def test_python_shortest_repr_half_even_and_cent_limits(self):
        self.assertEqual(side.decimal_tick_limit(.01, 1, .3400000000005, buy=True), .34)
        self.assertEqual(side.decimal_tick_limit(.01, 1, .3400000000015, buy=True), .35)
        self.assertEqual(side.decimal_tick_limit(.01, 1, .3400000000005, buy=False), .34)

    def test_no_valid_tick_refuses_individual_historical_leg(self):
        bad = {"strike": 105., "bid": .003, "ask": .004,
               "delta_basis": "HISTORICAL_VOL", "delta": .1,
               "delta_exact": .1, "_entry": {"sigma": .4}}
        self.assertIsNone(side.decimal_tick_limit(.003, .004, .0035, buy=False))
        self.assertIsNone(side.limit_from_computed(bad, 100., 30))
        self.assertEqual(builder.covered_call_tiers([], 100., 30, prepared=[bad]), ([], None))
        put = dict(bad, strike=95., delta=.25, delta_exact=.25)
        self.assertEqual(builder.cash_secured_put_tiers([put], 100., 30, prepared=[put])[0], [])
        collar, reason = builder.collar_tiers([bad], [put], 100., 30,
                                              prepared_calls=[bad], prepared_puts=[put])
        self.assertIsNone(collar)
        self.assertIsNotNone(reason)


if __name__ == "__main__":
    unittest.main()
