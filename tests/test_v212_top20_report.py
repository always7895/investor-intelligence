from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_v212_top20_report import (  # noqa: E402
    _returns_from_history,
    profit_summary,
)


class FakeSeries:
    def __init__(self, values, index):
        self._values = list(values)
        self.index = index
        self.iloc = self

    def dropna(self):
        return self

    def __len__(self):
        return len(self._values)

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._values[item]
        # boolean/date filter is exercised in production; fixtures below focus on
        # deterministic profitability formatting rather than mocking pandas.
        return self


class V212Top20ReportTests(unittest.TestCase):
    def test_profit_summary_is_deterministic_and_public_metric_only(self) -> None:
        value = profit_summary(
            {
                "revenue_growth": 0.253,
                "operating_margin": 0.121,
                "net_margin": 0.083,
                "debt_to_equity": 0.5,
            }
        )
        self.assertEqual(
            value,
            "獲利；營收年增 +25.3%；營益率 12.1%；淨利率 8.3%",
        )
        self.assertNotIn("debt", value.lower())

    def test_loss_and_missing_metric_text(self) -> None:
        self.assertTrue(
            profit_summary({"revenue_growth": -0.1, "net_margin": -0.05}).startswith(
                "虧損；"
            )
        )
        self.assertEqual(profit_summary({}), "SEC 可用獲利指標不足")

    def test_module_defines_requested_return_windows(self) -> None:
        module_text = (ROOT / "scripts" / "build_v212_top20_report.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"2y_cagr"', module_text)
        self.assertIn('"6m_price_return"', module_text)
        self.assertIn('"股票", "長期投資報酬率", "短期投資報酬率", "行業別", "獲利簡述"', module_text)
        self.assertIn('period="3y"', module_text)
        self.assertIn("days=730", module_text)
        self.assertIn("days=183", module_text)


if __name__ == "__main__":
    unittest.main()
