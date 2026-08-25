from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_line_public_options as module  # noqa: E402


class BuildLinePublicOptionsTests(unittest.TestCase):
    def write_symbols(self, value: dict) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "symbols.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return temporary, path

    def test_public_symbols_are_owner_independent_and_normalized(self) -> None:
        temporary, path = self.write_symbols(
            {
                "schema_version": 1,
                "owner_watchlist_inheritance": False,
                "symbols": [
                    "test",
                    {
                        "ticker": "brk-b",
                        "market_data_ticker": "brk-b",
                        "currency": "usd",
                    },
                ],
            }
        )
        try:
            symbols = module.load_public_symbols(path)
        finally:
            temporary.cleanup()
        self.assertEqual(
            symbols,
            [
                {
                    "ticker": "TEST",
                    "market_data_ticker": "TEST",
                    "currency": "USD",
                },
                {
                    "ticker": "BRK-B",
                    "market_data_ticker": "BRK-B",
                    "currency": "USD",
                },
            ],
        )

    def test_symbol_catalog_rejects_owner_inheritance_duplicates_and_unknown_fields(self) -> None:
        documents = (
            {
                "schema_version": 1,
                "owner_watchlist_inheritance": True,
                "symbols": ["TEST"],
            },
            {
                "schema_version": 1,
                "owner_watchlist_inheritance": False,
                "symbols": ["TEST", "test"],
            },
            {
                "schema_version": 1,
                "owner_watchlist_inheritance": False,
                "symbols": [{"ticker": "TEST", "owner_priority": 1}],
            },
            {
                "schema_version": 1,
                "owner_watchlist_inheritance": False,
                "symbols": ["TEST"],
                "owner_watchlist": ["PRIVATE"],
            },
        )
        for document in documents:
            temporary, path = self.write_symbols(document)
            try:
                with self.subTest(document=document), self.assertRaises(ValueError):
                    module.load_public_symbols(path)
            finally:
                temporary.cleanup()

    def test_public_record_requires_yfinance_and_never_includes_broker_attestations_true(self) -> None:
        raw = {
            "ticker": "TEST",
            "provider_symbol": "TEST",
            "current_price": 100.0,
            "retrieved_at": "2026-08-24T00:00:00+00:00",
            "status": "OK",
            "quote_source": "yfinance",
            "periods": {},
        }
        record = module.to_public_record(raw)
        self.assertTrue(record["line_public_eligible"])
        self.assertEqual(record["provider_scope"], "public_only")
        self.assertFalse(record["ibkr_connected"])
        self.assertFalse(record["brokerage_data_included"])
        self.assertFalse(record["account_data_included"])
        self.assertFalse(record["position_data_included"])
        self.assertFalse(record["owner_watchlist_inherited"])

        bad = dict(raw)
        bad["quote_source"] = "ibkr_client_portal_read_only"
        with self.assertRaises(ValueError):
            module.to_public_record(bad)

    def test_builder_source_has_no_ibkr_portfolio_or_owner_watchlist_import(self) -> None:
        text = (ROOT / "scripts" / "build_line_public_options.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("fetch_options_ibkr", text)
        self.assertNotIn("options_service", text)
        self.assertNotIn("load_portfolio", text)
        self.assertNotIn("portfolio.local.json\")", text)
        self.assertNotIn("config/watchlist.json\")", text)
        self.assertIn("DEFAULT_SYMBOLS_PATH", text)
        self.assertIn("PUBLIC_CANDIDATE_FIELDS", text)
        self.assertIn("Unknown option candidate field", text)
        self.assertIn("Non-neutral private field", text)

    def test_empty_public_symbol_catalog_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            symbols = root / "symbols.json"
            market = root / "market.json"
            policy = root / "policy.json"
            output = root / "output.json"
            symbols.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "owner_watchlist_inheritance": False,
                        "symbols": [],
                    }
                ),
                encoding="utf-8",
            )
            market.write_text("[]", encoding="utf-8")
            policy.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                module.build_public_options(
                    symbols_path=symbols,
                    market_path=market,
                    policy_path=policy,
                    output_path=output,
                    sleep_seconds=0,
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
