from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_v212_top20_report import (  # noqa: E402
    DISPLAY_COLUMNS,
    LONG_TERM_WINDOW_DAYS,
    MIN_LONG_TERM_ELAPSED_DAYS,
    MIN_SHORT_TERM_ELAPSED_DAYS,
    SHORT_TERM_WINDOW_DAYS,
    profit_summary,
    translate_industry,
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

    def test_return_windows_and_display_labels_are_explicit(self) -> None:
        self.assertEqual(LONG_TERM_WINDOW_DAYS, 730)
        self.assertEqual(SHORT_TERM_WINDOW_DAYS, 183)
        self.assertEqual(MIN_LONG_TERM_ELAPSED_DAYS, 600)
        self.assertEqual(MIN_SHORT_TERM_ELAPSED_DAYS, 120)
        self.assertEqual(
            DISPLAY_COLUMNS,
            [
                "股票",
                "長期投資報酬率（近2年年化）",
                "短期投資報酬率（近6個月）",
                "行業別",
                "獲利簡述",
            ],
        )
        module_text = (ROOT / "scripts" / "build_v212_top20_report.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('period="3y"', module_text)
        self.assertIn("start_point(LONG_TERM_WINDOW_DAYS)", module_text)
        self.assertIn("start_point(SHORT_TERM_WINDOW_DAYS)", module_text)

    def test_industry_is_localized_to_traditional_chinese(self) -> None:
        self.assertEqual(translate_industry("Semiconductors"), "半導體")
        self.assertEqual(translate_industry("Computer Hardware"), "電腦硬體")
        self.assertEqual(translate_industry("Software - Infrastructure"), "基礎架構軟體")
        self.assertEqual(translate_industry("Electronic Components"), "電子零組件")
        self.assertEqual(translate_industry("Communication Equipment"), "通訊設備")
        self.assertEqual(
            translate_industry("Semiconductor Equipment & Materials"),
            "半導體設備與材料",
        )
        self.assertEqual(translate_industry("Unknown English Taxonomy"), "其他產業")


if __name__ == "__main__":
    unittest.main()
