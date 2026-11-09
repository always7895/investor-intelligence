"""Synthetic source-shaped X-series refusals; no market data or network."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_market_quotes_options as builder
from tests.fixtures.v21_put_chains import nordic_row

TODAY = date(2026, 11, 9)
STAMP = "2026-11-09T15:00:00Z"
EXPIRY = "2026-11-20"
REASON = "價外買權僅有原生代號帶X之系列，未核驗是否為調整後系列；不提供建議"


def call(strike: float, *, root: str = "SYNTH", terminal_x: bool = False) -> dict:
    row = nordic_row("C", strike, 0.30, 0.32, root=root, expiry=EXPIRY)
    if terminal_x:
        row["symbol"] += "X"
    return row


def produce(rows: list[dict]):
    with patch.object(builder, "http_json", return_value={"data": {"instrumentListing": {"rows": rows}}}):
        return builder.nordic_options("SYNTH.ST", "SYNTH", 100.0, TODAY, STAMP, "TX_SYNTH", spot_currency="SEK")


class NordicXDiagnosticTests(unittest.TestCase):
    def test_x_only_otm_calls_remain_refused_with_the_precise_cause(self):
        x = call(120, terminal_x=True)
        self.assertIsNone(builder._nordic_chain_root([x]))
        for rows in ([x], [call(90), x]):
            with self.subTest(standard_itm=len(rows) == 2):
                result = produce(rows)
                for period in ("weekly", "monthly"):
                    self.assertEqual(result[period], {"unavailable": REASON})

    def test_a_real_standard_otm_contract_is_not_hidden_by_an_x_series(self):
        standard = call(120)
        result = produce([standard, call(130, terminal_x=True)])
        for period in ("weekly", "monthly"):
            self.assertEqual([item["strike"] for item in result[period]["suggestions"]], [120.0])
            self.assertEqual(result[period]["expiry"], EXPIRY)

    def test_x_diagnostic_does_not_repair_foreign_identity_or_mask_root_conflicts(self):
        x = call(120, terminal_x=True)
        wrong = {**x, "symbol": "OTHER6K120X"}
        for rows in ([wrong], [call(90), x, call(95, root="OTHER")]):
            result = produce(rows)
            for cycle in result.values():
                self.assertIn("unavailable", cycle)
                self.assertNotEqual(cycle["unavailable"], REASON)


if __name__ == "__main__":
    unittest.main()
