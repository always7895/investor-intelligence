from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_report as report_module  # noqa: E402


class ReportTests(unittest.TestCase):
    def test_report_separates_source_system_and_user_overlay(self) -> None:
        score = {
            "rank": 1,
            "ticker": "TEST",
            "source": "serenity",
            "rating": "C",
            "total_score": 55,
            "data_quality": 0.40,
            "current_price": None,
            "market_cap": None,
            "revenue_growth": None,
            "category": "Test Category",
            "name": "Test Corp",
            "layer_scores": {
                "L1_demand_wave": 10,
                "L2_bottleneck": 15,
                "L3_company_quality": 10,
                "L4_valuation_catalyst": 5,
                "L5_evidence_risk": 15,
            },
            "warnings": ["Low data completeness"],
            "reasons": ["Test system reason"],
            "user_long_term_overlay": {
                "enabled": True,
                "owner": "repository_user",
                "minimum_holding_years": 2,
                "affects_source_view": False,
                "affects_methodology_research_score": False,
                "score": 45,
                "label": "資料不足",
                "data_quality": 0.40,
                "reasons": ["Primary evidence missing"],
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            original = report_module.REPORTS_DIR
            report_module.REPORTS_DIR = Path(directory)
            try:
                output = Path(
                    report_module.generate_report(
                        indices={},
                        market_data=[],
                        scores=[score],
                        options_data=[],
                        movers=[],
                        watch_moves=[],
                        active_scan={},
                    )
                )
                text = output.read_text(encoding="utf-8")
            finally:
                report_module.REPORTS_DIR = original

        self.assertIn("Source views, system operationalization and user preferences are separate", text)
        self.assertIn("System operationalization — research ranking", text)
        self.assertIn("User-defined long-term suitability overlay", text)
        self.assertIn("not attributed to Serenity or Leopold Aschenbrenner", text)
        self.assertIn("not an official Serenity or Leopold Aschenbrenner score", text)
        self.assertIn("Serenity seed tag", text)
        self.assertIn("No structured, verified source-view records", text)
        self.assertIn("N/A", text)
        self.assertNotIn("projected_return_2yr", text)
        self.assertIn("## 8. Summary, contrary evidence and controls", text)


if __name__ == "__main__":
    unittest.main()
