from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_options import (  # noqa: E402
    DEFAULT_POLICY,
    load_portfolio,
    option_observation,
    select_expiration,
)
from render_options_report import render_options_report  # noqa: E402


class OptionsTests(unittest.TestCase):
    def test_select_expiration_uses_actual_dte_window(self) -> None:
        expiration, dte, status = select_expiration(
            ["2026-08-28", "2026-09-04", "2026-09-25"],
            {"target_dte": 7, "minimum_dte": 3, "maximum_dte": 14},
            today=date(2026, 8, 23),
        )
        self.assertEqual(status, "OK")
        self.assertEqual(expiration, "2026-08-28")
        self.assertEqual(dte, 5)

    def test_bid_ask_mid_spread_and_no_fake_delta(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        observation = option_observation(
            {
                "contractSymbol": "TEST260904C00120000",
                "strike": 120,
                "bid": 4.0,
                "ask": 5.0,
                "lastPrice": 4.25,
                "volume": 20,
                "openInterest": 200,
                "impliedVolatility": 0.80,
                "lastTradeDate": now,
            },
            option_type="call",
            ticker="TEST",
            spot=110,
            expiration="2026-09-04",
            dte=12,
            policy=DEFAULT_POLICY,
            position={"shares": 250, "covered_contract_capacity": 2},
            retrieved_at=now,
        )
        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(observation["bid"], 4.0)
        self.assertEqual(observation["ask"], 5.0)
        self.assertEqual(observation["midpoint"], 4.5)
        self.assertEqual(observation["spread"], 1.0)
        self.assertEqual(observation["delta"], None)
        self.assertEqual(observation["delta_status"], "NOT_SUPPLIED_BY_YFINANCE")
        self.assertEqual(observation["coverage_status"], "COVERED")
        self.assertTrue(observation["liquidity_pass"])
        self.assertEqual(
            observation["sell_limit_observation"]["observed_limit_low"], 4.25
        )
        self.assertEqual(
            observation["sell_limit_observation"]["observed_limit_high"], 4.5
        )

    def test_one_sided_quote_is_not_recommended(self) -> None:
        observation = option_observation(
            {
                "strike": 90,
                "bid": 0,
                "ask": 3,
                "lastPrice": 2,
                "volume": 0,
                "openInterest": 100,
                "impliedVolatility": 0.50,
            },
            option_type="put",
            ticker="TEST",
            spot=100,
            expiration="2026-09-04",
            dte=12,
            policy=DEFAULT_POLICY,
            position=None,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
        )
        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertFalse(observation["liquidity_pass"])
        self.assertIn("No valid two-sided BID/ASK quote", observation["liquidity_reasons"])

    def test_private_portfolio_calculates_covered_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portfolio.local.json"
            path.write_text(
                json.dumps(
                    {
                        "positions": [
                            {"ticker": "ALPHA", "shares": 250.75},
                            {"ticker": "BETA", "shares": 999},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            positions = load_portfolio(path)
        self.assertEqual(positions["ALPHA"]["covered_contract_capacity"], 2)
        self.assertEqual(positions["BETA"]["covered_contract_capacity"], 9)

    def test_report_lists_bid_ask_and_no_chain_status(self) -> None:
        option_item = {
            "ticker": "ALPHA",
            "status": "OK",
            "quote_source": "yfinance",
            "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
            "current_price": 100,
            "position": {
                "source": "portfolio.local.json",
                "covered_contract_capacity": 1,
            },
            "periods": {
                "weekly": {
                    "status": "OK",
                    "expiration": "2026-08-28",
                    "actual_dte": 5,
                    "covered_call": {
                        "status": "OK",
                        "recommended_candidates": [
                            {
                                "strike": 110,
                                "actual_dte": 5,
                                "bid": 2.0,
                                "ask": 2.5,
                                "midpoint": 2.25,
                                "spread_pct_of_mid": 22.22,
                                "open_interest": 100,
                                "volume": 10,
                                "implied_volatility_pct": 80,
                                "annualized_yield_pct": {
                                    "bid": 146,
                                    "mid": 164.25,
                                    "ask": 182.5,
                                },
                                "sell_limit_observation": {
                                    "observed_limit_low": 2.13,
                                    "observed_limit_high": 2.25,
                                },
                                "effective_sale_price": {"mid": 112.25},
                            }
                        ],
                    },
                    "cash_secured_put": {
                        "status": "NO_ELIGIBLE_LIQUID_CONTRACT",
                        "recommended_candidates": [],
                    },
                }
            },
        }
        no_chain = {
            "ticker": "BETA",
            "status": "NO_LISTED_OPTIONS",
            "quote_source": "yfinance",
            "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
            "position": {"source": "portfolio.local.json", "covered_contract_capacity": 9},
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "options.md"
            render_options_report([option_item, no_chain], output)
            text = output.read_text(encoding="utf-8")
        self.assertIn("BID", text)
        self.assertIn("ASK", text)
        self.assertIn("$2.13–$2.25", text)
        self.assertIn("NO_LISTED_OPTIONS", text)
        self.assertIn("不會捏造期權鏈", text)


if __name__ == "__main__":
    unittest.main()
