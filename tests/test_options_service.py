from __future__ import annotations

import json
from copy import deepcopy
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from options_service import fetch_options, merge_results, privacy_minimize  # noqa: E402


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
    def test_no_primary_preserves_fallback_provenance(self) -> None:
        fallback = {"ticker": "TEST", "status": "OK", "position": {
            "source": "local_portfolio", "covered_contract_capacity": 2}}
        result = merge_results([], [fallback])[0]
        self.assertEqual(result["position"]["source"], "local_portfolio")
        self.assertEqual(result["position"]["covered_contract_capacity"], 2)
        self.assertFalse(result["primary_provider_capacity_applied"])

    def test_failed_primary_cannot_supply_capacity_or_raw_error(self) -> None:
        primary = {"ticker": "TEST", "status": "ERROR", "error": "synthetic-private-detail",
                   "position": {"covered_contract_capacity": 9}}
        result = merge_results([primary], [{"ticker": "TEST", "status": "OK"}])[0]
        self.assertEqual(result["position"]["covered_contract_capacity"], 0)
        self.assertFalse(result["primary_provider_capacity_applied"])
        self.assertNotIn("synthetic-private-detail", json.dumps(result))

    def test_yfinance_caller_does_not_require_broker_config(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("options_service.fetch_yfinance_options", return_value=[{
                "ticker": "TEST", "status": "OK", "quote_source": "yfinance"
            }]) as fetch, patch("options_service.fetch_all_options_ibkr") as broker:
                result = fetch_options(provider="yfinance", ibkr_config_path=root / "missing.json",
                                       output_dir=root)
            fetch.assert_called_once()
            broker.assert_not_called()
            self.assertEqual(json.loads((root / "options_latest.json").read_text()), result)
            self.assertEqual(result[0]["position"]["source"], "unavailable")

    def test_caller_isolates_failed_fallback_and_marks_unknown_coverage(self) -> None:
        primary = {"ticker": "TEST", "status": "OK", "periods": {"weekly": {
            "status": "OK", "cash_secured_put": {"recommended_candidates": [candidate(120)]}
        }}}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "ibkr.json"
            config.write_text("{}")
            with patch("options_service.provider_enabled", return_value=True), patch(
                "options_service.fetch_all_options_ibkr", return_value=[primary]
            ), patch("options_service.fetch_yfinance_options", side_effect=RuntimeError("synthetic-private-error")):
                result = fetch_options(provider="auto", ibkr_config_path=config, output_dir=root)
            self.assertEqual(result[0]["fallback_provider_status"], "PROVIDER_ERROR")
            self.assertEqual(result[0]["universe_coverage_status"], "UNKNOWN_FALLBACK_FAILED")
            self.assertNotIn("synthetic-private-error", json.dumps(result))
            self.assertTrue((root / "options_latest.json").exists())

    def test_total_provider_failure_does_not_publish_success(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("options_service.fetch_yfinance_options", side_effect=RuntimeError("synthetic-private-error")):
                with self.assertRaisesRegex(ValueError, "OPTIONS_FALLBACK_FAILED_NO_USABLE_PRIMARY"):
                    fetch_options(provider="yfinance", output_dir=root)
            self.assertFalse((root / "options_latest.json").exists())

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
        original = deepcopy(fallback)
        result = merge_results([primary], [fallback])[0]
        self.assertEqual(fallback, original)
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
