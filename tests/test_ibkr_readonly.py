from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_options import load_policy  # noqa: E402
from fetch_options_ibkr import (  # noqa: E402
    _equity_position_quantities,
    get_ibkr_option_suggestion,
)
from providers.ibkr_client_portal import (  # noqa: E402
    IbkrClientPortalReadOnly,
    IbkrReadOnlyError,
    IbkrTarget,
    UnderlyingDefinition,
    validate_loopback_base_url,
)


def nested_keys(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            result.add(str(key).replace("-", "_").casefold())
            result.update(nested_keys(item))
    elif isinstance(value, list):
        for item in value:
            result.update(nested_keys(item))
    return result


def scalar_values(value: Any) -> list[Any]:
    if isinstance(value, dict):
        result: list[Any] = []
        for item in value.values():
            result.extend(scalar_values(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(scalar_values(item))
        return result
    return [value]


class FakeOptionClient:
    def __init__(self, ticker: str, monthly_only: bool = False) -> None:
        self.ticker = ticker
        self.monthly_only = monthly_only
        self.underlying_conid = 1000 if ticker == "TEST" else 2000
        self.option_conids: dict[int, tuple[str, float, str]] = {}

    def search_underlying(self, target: IbkrTarget) -> UnderlyingDefinition:
        return UnderlyingDefinition(
            ticker=target.ticker,
            conid=self.underlying_conid,
            currency=target.currency,
            listing_exchange=target.preferred_listing_exchange,
            option_exchange=target.preferred_option_exchange,
            option_months=(),
        )

    def strikes(self, _definition, month: str):
        if self.monthly_only and month != "SEP26":
            return {"call": [], "put": []}
        return {"call": [110.0], "put": [90.0]}

    def option_contract_info(
        self,
        _definition,
        *,
        month: str,
        strike: float,
        right: str,
    ):
        expiration = (
            "20260918"
            if self.monthly_only
            else ("20260828" if month == "AUG26" else "20260918")
        )
        conid = 3000 + len(self.option_conids)
        self.option_conids[conid] = (right, strike, expiration)
        return [
            {
                "conid": conid,
                "localSymbol": f"{self.ticker}-{expiration}-{right}-{strike}",
                "maturityDate": expiration,
                "strike": strike,
                "right": right,
                "currency": "USD" if self.ticker == "TEST" else "SEK",
            }
        ]

    def market_snapshot(self, conids, fields):
        if list(conids) == [self.underlying_conid]:
            return [{"conid": self.underlying_conid, "31": 100.0}]
        rows = []
        for conid in conids:
            right, _strike, _expiration = self.option_conids[conid]
            premium = 5.0 if right == "C" else 3.0
            rows.append(
                {
                    "conid": conid,
                    "84": premium,
                    "86": premium + 0.2,
                    "31": premium + 0.1,
                    "_updated": 1787350000000,
                }
            )
        return rows


class IbkrReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy()
        cls.config = json.loads(
            (ROOT / "config" / "ibkr-readonly.json").read_text(encoding="utf-8")
        )

    def test_gateway_must_be_loopback_https(self) -> None:
        self.assertEqual(
            validate_loopback_base_url("https://127.0.0.1:5000/v1/api"),
            "https://127.0.0.1:5000/v1/api",
        )
        with self.assertRaises(IbkrReadOnlyError):
            validate_loopback_base_url("http://127.0.0.1:5000/v1/api")
        with self.assertRaises(IbkrReadOnlyError):
            validate_loopback_base_url("https://example.com/v1/api")

    def test_order_and_transfer_endpoints_are_rejected(self) -> None:
        with self.assertRaises(IbkrReadOnlyError):
            IbkrClientPortalReadOnly._validate_path("POST", "iserver/account/orders")
        with self.assertRaises(IbkrReadOnlyError):
            IbkrClientPortalReadOnly._validate_path("GET", "portfolio/account/transfer")

    def test_dynamic_position_discovery_uses_only_long_stock_shares(self) -> None:
        quantities = _equity_position_quantities(
            [
                {"assetClass": "STK", "ticker": "TEST", "position": 250.75},
                {"assetClass": "STK", "ticker": "NEXT", "position": 125},
                {"assetClass": "OPT", "ticker": "TEST", "position": 10},
                {"assetClass": "CFD", "ticker": "NEXT", "position": 1000},
                {"assetClass": "STK", "ticker": "SHORT", "position": -200},
                {"ticker": "UNKNOWN", "position": 500},
            ]
        )
        self.assertEqual(quantities, {"TEST": 250.75, "NEXT": 125.0})

    def test_contract_search_uses_exact_symbol_with_options(self) -> None:
        client = IbkrClientPortalReadOnly(
            base_url="https://127.0.0.1:5000/v1/api",
            verify_tls=False,
        )
        rows = [
            {
                "symbol": "TESX",
                "conid": 999,
                "description": "ALT",
                "sections": [{"secType": "OPT"}],
            },
            {
                "symbol": "TEST",
                "conid": 123456,
                "description": "PRIMARY",
                "currency": "USD",
                "countryCode": "US",
                "sections": [
                    {"secType": "STK"},
                    {"secType": "OPT", "exchange": "SMART"},
                ],
            },
        ]
        target = IbkrTarget(
            ticker="TEST",
            search_symbol="TEST",
            provider_symbol="TEST",
            currency="USD",
            preferred_listing_exchange="PRIMARY",
            preferred_option_exchange="SMART",
        )
        with patch.object(client, "_request", return_value=rows):
            definition = client.search_underlying(target)
        self.assertEqual(definition.conid, 123456)
        self.assertEqual(definition.option_exchange, "SMART")

    def test_output_uses_derived_capacity_without_exact_quantity_or_ids(self) -> None:
        target = IbkrTarget(
            ticker="TEST",
            search_symbol="TEST",
            provider_symbol="TEST",
            currency="USD",
            preferred_listing_exchange="PRIMARY",
            preferred_option_exchange="SMART",
        )
        result = get_ibkr_option_suggestion(
            FakeOptionClient("TEST"),
            target,
            quantity=250.0,
            policy=self.policy,
            config=self.config,
            today=date(2026, 8, 23),
        )
        self.assertEqual(result["position"]["covered_contract_capacity"], 2)
        self.assertIsNone(result["position"]["shares"])

        keys = nested_keys(result)
        forbidden_identifier_keys = {
            "account",
            "account_id",
            "accountid",
            "acctid",
            "account_number",
            "conid",
        }
        leaked = sorted(keys & forbidden_identifier_keys)
        self.assertEqual(leaked, [], f"IBKR output leaked identifier keys: {leaked}")
        self.assertNotIn(250.0, scalar_values(result))
        self.assertEqual(
            result["privacy"],
            {
                "account_identifier_included": False,
                "exact_quantity_included": False,
                "cost_basis_included": False,
                "pnl_included": False,
            },
        )
        self.assertEqual(result["periods"]["weekly"]["expiration"], "2026-08-28")

    def test_monthly_only_chain_does_not_fabricate_weekly_contract(self) -> None:
        target = IbkrTarget(
            ticker="MNTH",
            search_symbol="MNTH",
            provider_symbol="MNTH.EX",
            currency="SEK",
            preferred_listing_exchange="PRIMARY",
            preferred_option_exchange="OMS",
        )
        result = get_ibkr_option_suggestion(
            FakeOptionClient("MNTH", monthly_only=True),
            target,
            quantity=500.0,
            policy=self.policy,
            config=self.config,
            today=date(2026, 8, 23),
        )
        self.assertEqual(
            result["periods"]["weekly"]["status"],
            "NO_EXPIRATION_IN_WINDOW",
        )
        self.assertEqual(result["periods"]["monthly"]["expiration"], "2026-09-18")


if __name__ == "__main__":
    unittest.main()
