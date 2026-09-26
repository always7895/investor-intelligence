"""Displayed profit metrics are current, same-period and plausible (regression 2026-09-25: PBR showed a 2011
20-F, HIG a 979.1% net margin on an ASC 606 revenue subset, AFRM 133.6%, and 15 of 20 rows an annual revenue
growth from 10-Ks filed 190-226 days earlier). Synthetic values in the real metric-entry shapes."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_v212_top20_report as builder  # noqa: E402

CLOCK = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
WINDOW = 135 * 86400 - 14 * 3600


def operand(value, *, filed, start, end, form="10-Q", tag="Revenues"):
    return {"value": value, "filed": filed, "start": start, "end": end, "form": form, "tag": tag}


def ratio(value, *, filed="2026-07-23", start="2026-04-01", end="2026-06-30", numerator_start=None, denominator_tag="Revenues"):
    return {"status": "AVAILABLE", "value": value,
            "numerator": operand(1, filed=filed, start=numerator_start or start, end=end, tag="NetIncomeLoss"),
            "denominator": operand(1, filed=filed, start=start, end=end, tag=denominator_tag)}


def annual_growth(value, filed):
    return {"status": "AVAILABLE", "value": value,
            "numerator": operand(1, filed=filed, start="2025-01-01", end="2025-12-31", form="10-K"),
            "denominator": operand(1, filed="2025-02-21", start="2024-01-01", end="2024-12-31", form="10-K")}


def fact(value, start, end, filed, tag="Revenues", form="10-Q"):
    return {"record_type": "company_fact", "taxonomy": "us-gaap", "tag": tag, "form": form, "value": value,
            "start": start, "end": end, "filed": filed, "accession_number": f"0000000001-{filed}"}


class ProfitDisplayTests(unittest.TestCase):
    def show(self, entries, quarter=None):
        return builder.profit_display(entries, quarter_growth=quarter, clock=CLOCK, max_age_seconds=WINDOW)

    def test_implausible_margins_are_withheld(self):
        text, display = self.show({"net_margin": ratio(9.790909), "operating_margin": ratio(1.336, denominator_tag="RevenueFromContractWithCustomerExcludingAssessedTax")})
        self.assertEqual(text, "SEC 可用獲利指標不足")
        self.assertEqual(display["withheld"], {"net_margin": "IMPLAUSIBLE_MARGIN_OVER_100_PERCENT",
                                               "operating_margin": "IMPLAUSIBLE_MARGIN_OVER_100_PERCENT",
                                               "revenue_growth": "MISSING_OPERAND"})

    def test_decade_old_filing_and_stale_annual_growth_are_withheld(self):
        text, display = self.show({"net_margin": ratio(0.12, filed="2011-05-26", start="2010-01-01", end="2010-12-31"),
                                   "revenue_growth": annual_growth(0.08, "2026-02-26")})
        self.assertEqual(text, "SEC 可用獲利指標不足")
        self.assertEqual(display["withheld"]["net_margin"], "STALE_FILING")
        self.assertEqual(display["withheld"]["revenue_growth"], "STALE_FILING")
        self.assertIsNone(display["claim_filed_at"])

    def test_latest_quarter_yoy_replaces_the_stale_annual_growth(self):
        records = [fact(1200, "2026-04-01", "2026-06-30", "2026-07-30"), fact(1000, "2025-04-01", "2025-06-30", "2025-07-31"),
                   fact(4000, "2025-01-01", "2025-12-31", "2026-02-26", form="10-K"),
                   fact(900, "2025-04-01", "2025-06-30", "2025-07-31", tag="SalesRevenueNet")]
        quarter = builder.latest_quarter_growth(records)
        self.assertAlmostEqual(quarter["value"], 0.2)
        self.assertEqual((quarter["numerator"]["filed"], quarter["denominator"]["end"]), ("2026-07-30", "2025-06-30"))
        text, display = self.show({"revenue_growth": annual_growth(0.08, "2026-02-26"), "net_margin": ratio(0.1)}, quarter)
        self.assertEqual(text, "獲利；營收年增 +20.0%；淨利率 10.0%")
        self.assertEqual(display["displayed"]["revenue_growth"]["kind"], "latest_quarter_yoy")
        self.assertEqual(display["claim_filed_at"], "2026-07-23")  # the oldest displayed filing anchors the claim

    def test_period_mismatch_and_margin_window_edge(self):
        _, display = self.show({"net_margin": ratio(0.1, numerator_start="2026-01-01")})
        self.assertEqual(display["withheld"]["net_margin"], "PERIOD_MISMATCH")
        inside = datetime.fromtimestamp(CLOCK.timestamp() - WINDOW + 86400, timezone.utc).date().isoformat()  # midnight of a day inside the window
        text, _ = self.show({"net_margin": ratio(0.1, filed=inside)})
        self.assertIn("淨利率 10.0%", text)

    def test_no_quarter_pair_means_no_quarterly_growth(self):
        self.assertIsNone(builder.latest_quarter_growth([fact(1200, "2026-04-01", "2026-06-30", "2026-07-30")]))
        self.assertIsNone(builder.latest_quarter_growth([fact(1200, "2026-01-01", "2026-06-30", "2026-07-30"),
                                                        fact(1000, "2025-01-01", "2025-06-30", "2025-07-31")]))  # half-year, not a quarter

    def test_retail_labels(self):
        self.assertEqual(builder.translate_industry("Discount Stores"), "折扣零售")


if __name__ == "__main__":
    unittest.main()
