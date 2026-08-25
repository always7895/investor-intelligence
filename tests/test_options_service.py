from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from options_service import merge_results, privacy_minimize  # noqa: E402


def candidate(strike: float, ticker: str = "TEST") -> dict:
    return {
        "ticker": ticker,
        "option_type": "call",
        "strike": strike,
        "bid": 4.0,
        "ask": 4.2,
        "midpoint": 4.1,
        "liquidity_pass": True,
        "position_shares": None,
        "covered_contract_capacity": 0,
        "coverage_status": "NOT_COVERED_OR_UNKNOWN",
    }


class OptionsServiceTests(unittest.TestCase):
    def test_usable_ibkr_result_is_preferred(self) -> None:
        primary = {
            "ticker": "TEST",
            "status": "OK",
            "quote_source": "ibkr_client_portal_read_only",
            "position": {"covered_contract_capacity": 2},
            "periods": {
                "weekly": {
                    "status": "OK",
                    "covered_call": {
                        "recommended_candidates": [candidate(120)],
                        "all_window_observations": [candidate(120)],
                    },
                    "cash_secured_put": {"recommended_candidates": []},
                }
            },
        }
        fallback = {
            "ticker": "TEST",
            "status": "OK",
            "quote_source": "yfinance",
            "periods": {},
        }
        result = merge_results([primary], [fallback])[0]
        self.assertEqual(result["quote_source"], "ibkr_client_portal_read_only")
        self.assertEqual(result["position"]["covered_contract_capacity"], 2)

    def test_fallback_receives_only_derived_ibkr_coverage(self) -> None:
        primary = {
            "ticker": "TEST",
            "status": "OK",
            "quote_source": "ibkr_client_portal_read_only",
            "position": {
                "shares": 250,
                "covered_contract_capacity": 2,
                "account_id": "synthetic-account",
            },
            "periods": {
                "weekly": {
                    "status": "OK",
                    "covered_call": {
                        "recommended_candidates": [],
                        "all_window_observations": [],
                    },
                    "cash_secured_put": {"recommended_candidates": []},
                }
            },
        }
        observation = candidate(120)
        fallback = {
            "ticker": "TEST",
            "status": "OK",
            "quote_source": "yfinance",
            "position": {"shares": None, "covered_contract_capacity": 0},
            "periods": {
                "weekly": {
                    "status": "OK",
                    "covered_call": {
                        "status": "NO_ELIGIBLE_LIQUID_CONTRACT",
                        "recommended_candidates": [],
                        "all_window_observations": [observation],
                    },
                    "cash_secured_put": {"recommended_candidates": []},
                }
            },
        }
        result = merge_results([primary], [fallback])[0]
        self.assertEqual(result["quote_source"], "yfinance")
        self.assertEqual(result["position"]["covered_contract_capacity"], 2)
        calls = result["periods"]["weekly"]["covered_call"]
        self.assertEqual(calls["status"], "OK")
        self.assertEqual(calls["recommended_candidates"][0]["covered_contract_capacity"], 2)
        serialized = json.dumps(result)
        self.assertNotIn("250", serialized)
        self.assertNotIn("synthetic-account", serialized)

    def test_monthly_only_status_preserves_weekly_unavailable(self) -> None:
        primary = {
            "ticker": "MNTH",
            "status": "OK",
            "quote_source": "ibkr_client_portal_read_only",
            "position": {"covered_contract_capacity": 3},
            "periods": {
                "weekly": {"status": "NO_EXPIRATION_IN_WINDOW"},
                "monthly": {
                    "status": "OK",
                    "covered_call": {
                        "recommended_candidates": [candidate(40, "MNTH")],
                        "all_window_observations": [candidate(40, "MNTH")],
                    },
                    "cash_secured_put": {"recommended_candidates": []},
                },
            },
        }
        result = merge_results([primary], [])[0]
        self.assertEqual(result["periods"]["weekly"]["status"], "NO_EXPIRATION_IN_WINDOW")
        self.assertEqual(result["periods"]["monthly"]["status"], "OK")

    def test_privacy_minimize_removes_account_and_exact_position_fields(self) -> None:
        result = privacy_minimize(
            {
                "ticker": "TEST",
                "position": {
                    "shares": 250,
                    "whole_shares": 250,
                    "covered_contract_capacity": 2,
                    "account_id": "synthetic-account",
                },
                "cost_basis": 123.45,
            }
        )
        serialized = json.dumps(result)
        self.assertNotIn("250", serialized)
        self.assertNotIn("123.45", serialized)
        self.assertNotIn("synthetic-account", serialized)
        self.assertEqual(result["position"]["covered_contract_capacity"], 2)


if __name__ == "__main__":
    unittest.main()
