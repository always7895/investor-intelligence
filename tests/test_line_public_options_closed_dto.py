from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_line_public_options import to_public_record  # noqa: E402


def raw_fixture() -> dict:
    return {
        "ticker": "TEST",
        "provider_symbol": "TEST",
        "current_price": 100.0,
        "retrieved_at": "2026-08-24T12:00:00+00:00",
        "status": "OK",
        "quote_source": "yfinance",
        "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
        "periods": {
            "weekly": {
                "status": "OK",
                "target_dte": 7,
                "expiration": "2026-08-28",
                "actual_dte": 4,
                "covered_call": {
                    "status": "OK",
                    "recommended_candidates": [],
                    "all_window_observations": [
                        {
                            "ticker": "TEST",
                            "option_type": "call",
                            "contract_symbol": "TEST260828C00110000",
                            "expiration": "2026-08-28",
                            "actual_dte": 4,
                            "strike": 110.0,
                            "spot": 100.0,
                            "distance_from_spot_pct": 10.0,
                            "bid": 1.0,
                            "ask": 1.2,
                            "midpoint": 1.1,
                            "last": 1.05,
                            "spread": 0.2,
                            "spread_pct_of_mid": 18.18,
                            "volume": 10,
                            "open_interest": 100,
                            "implied_volatility_pct": 50.0,
                            "delta": None,
                            "delta_status": "NOT_SUPPLIED_BY_YFINANCE",
                            "last_trade_at": "2026-08-24T11:00:00+00:00",
                            "last_trade_age_days": 0.04,
                            "retrieved_at": "2026-08-24T12:00:00+00:00",
                            "quote_source": "yfinance",
                            "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
                            "two_sided_quote": True,
                            "liquidity_pass": True,
                            "liquidity_reasons": [],
                            "quote_quality_rank": 80.0,
                            "sell_limit_observation": {
                                "bid_floor": 1.0,
                                "reference_mid": 1.1,
                                "observed_limit_low": 1.05,
                                "observed_limit_high": 1.1,
                            },
                            "annualized_yield_pct": {
                                "bid": 91.25,
                                "mid": 100.38,
                                "ask": 109.5,
                            },
                            "effective_sale_price": {
                                "bid": 111.0,
                                "mid": 111.1,
                                "ask": 111.2,
                            },
                            "put_break_even": None,
                            "cash_secured_put_cash_requirement": None,
                            "position_shares": None,
                            "covered_contract_capacity": 0,
                            "coverage_status": "NOT_COVERED_OR_UNKNOWN",
                            "premium": 1.1,
                            "annualized_yield_pct_mid": 100.38,
                            "implied_vol": 50.0,
                        }
                    ],
                    "eligible_count": 1,
                    "window_observation_count": 1,
                },
                "cash_secured_put": {
                    "status": "NO_ELIGIBLE_LIQUID_CONTRACT",
                    "recommended_candidates": [],
                    "all_window_observations": [],
                    "eligible_count": 0,
                    "window_observation_count": 0,
                },
            }
        },
    }


class LinePublicOptionsClosedDtoTests(unittest.TestCase):
    def test_neutral_position_capable_fields_are_not_published(self) -> None:
        public = to_public_record(raw_fixture())
        serialized = str(public)
        self.assertNotIn("position_shares", serialized)
        self.assertNotIn("covered_contract_capacity", serialized)
        self.assertNotIn("coverage_status", serialized)
        candidate = public["periods"]["weekly"]["call_observations"][
            "recommended_candidates"
        ][0]
        self.assertEqual(candidate["bid"], 1.0)
        self.assertEqual(candidate["ask"], 1.2)
        self.assertEqual(candidate["quote_source"], "yfinance")

    def test_non_neutral_position_values_fail_closed(self) -> None:
        for key, value in (
            ("position_shares", 100),
            ("covered_contract_capacity", 1),
            ("coverage_status", "COVERED"),
        ):
            raw = raw_fixture()
            candidate = raw["periods"]["weekly"]["covered_call"][
                "all_window_observations"
            ][0]
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                to_public_record(raw)

    def test_unknown_candidate_fields_fail_closed_instead_of_redaction(self) -> None:
        raw = raw_fixture()
        candidate = raw["periods"]["weekly"]["covered_call"][
            "all_window_observations"
        ][0]
        candidate["owner_research_note"] = "private"
        with self.assertRaises(ValueError):
            to_public_record(raw)

    def test_nested_private_or_broker_lineage_fails_closed(self) -> None:
        cases = (
            ("sell_limit_observation", {"account": "synthetic"}),
            ("liquidity_reasons", ["derived from Interactive Brokers"]),
        )
        for key, value in cases:
            raw = raw_fixture()
            candidate = raw["periods"]["weekly"]["covered_call"][
                "all_window_observations"
            ][0]
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                to_public_record(raw)

    def test_unknown_period_and_group_fields_fail_closed(self) -> None:
        raw = raw_fixture()
        raw["periods"]["daily"] = copy.deepcopy(raw["periods"]["weekly"])
        with self.assertRaises(ValueError):
            to_public_record(raw)

        raw = raw_fixture()
        raw["periods"]["weekly"]["covered_call"]["owner_selector"] = True
        with self.assertRaises(ValueError):
            to_public_record(raw)


if __name__ == "__main__":
    unittest.main()
