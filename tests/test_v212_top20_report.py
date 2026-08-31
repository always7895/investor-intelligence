from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_v212_top20_report import (  # noqa: E402
    LONG_TERM_WINDOW_DAYS,
    SHORT_TERM_WINDOW_DAYS,
    profit_summary,
)


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
        self.assertEqual(LONG_TERM_WINDOW_DAYS, 730)
        self.assertEqual(SHORT_TERM_WINDOW_DAYS, 183)
        self.assertIn('"2y_cagr"', module_text)
        self.assertIn('"6m_price_return"', module_text)
        self.assertIn('"股票", "長期投資報酬率", "短期投資報酬率", "行業別", "獲利簡述"', module_text)
        self.assertIn('period="3y"', module_text)
        self.assertIn("start_point(LONG_TERM_WINDOW_DAYS)", module_text)
        self.assertIn("start_point(SHORT_TERM_WINDOW_DAYS)", module_text)


if __name__ == "__main__":
    unittest.main()
