from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import company_deep_report as cdr  # noqa: E402

TODAY = date(2026, 9, 25)


def fact(val, end, frame, start=None, fp="Q2", form="10-Q"):
    row = {"val": val, "end": end, "frame": frame, "fp": fp, "form": form, "accn": "0000000001-26-000001"}
    if start:
        row["start"] = start
    return row


FACTS = {"entityName": "Synthetic Devices Inc.", "facts": {"us-gaap": {
    "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
        fact(1000, "2026-06-30", "CY2026Q2", "2026-04-01"), fact(800, "2025-06-30", "CY2025Q2", "2025-04-01"),
        fact(1800, "2026-06-30", None, "2026-01-01"),  # year-to-date row without a quarter frame is ignored
        fact(3200, "2025-12-31", "CY2025", "2025-01-01", fp="FY", form="10-K")]}},
    "GrossProfit": {"units": {"USD": [fact(600, "2026-06-30", "CY2026Q2", "2026-04-01"), fact(440, "2025-06-30", "CY2025Q2", "2025-04-01")]}},
    "OperatingIncomeLoss": {"units": {"USD": [fact(300, "2026-06-30", "CY2026Q2", "2026-04-01"), fact(200, "2025-06-30", "CY2025Q2", "2025-04-01")]}},
    "RevenueRemainingPerformanceObligation": {"units": {"USD": [fact(5000, "2026-06-30", "CY2026Q2I"), fact(2500, "2025-06-30", "CY2025Q2I")]}},
    "InventoryNet": {"units": {"USD": [fact(110, "2026-06-30", "CY2026Q2I"), fact(100, "2025-06-30", "CY2025Q2I")]}},
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [fact(900, "2026-06-30", "CY2026Q2I")]}},
    "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
        fact(106, "2026-06-30", "CY2026Q2", "2026-04-01"), fact(100, "2025-06-30", "CY2025Q2", "2025-04-01")]}},
    "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [fact(320, "2025-12-31", "CY2025", "2025-01-01", fp="FY", form="10-K")]}},
}}}
INDUSTRY = {"industry_id": "semis", "name_zh": "合成半導體", "phase": {"phase": "EARLY_VALIDATION"}, "quarter": "2026 Q2",
            "price": {"yoy_pct": 6.0, "series": [{"series": "PCU000", "month": "2026-08"}]}, "backlog": {"yoy_pct": 30.0},
            "signals": [{"signal_id": "semis:PRICE", "kind": "PRICE", "as_of": "2026-08-31", "direction": "UP", "value": 6.0,
                         "evidence_family": "bls_ppi", "source_url": "https://data.bls.gov/timeseries/PCU000"}]}
ROTATION = {"industries": [INDUSTRY]}
CONFIG = {"industries": [{"industry_id": "semis", "sic": ["3674"]}]}


class DeepReportTests(unittest.TestCase):
    def test_metrics_compare_the_same_calendar_quarter(self):
        m = cdr.extract_metrics(FACTS)
        self.assertEqual((m["quarter_frame"], m["revenue_yoy_pct"]), ("CY2026Q2", 25.0))
        self.assertEqual((m["gross_margin_pct"], m["gross_margin_change_pp"]), (60.0, 5.0))
        self.assertEqual(m["rpo_yoy_pct"], 100.0)
        self.assertEqual(m["dilution_yoy_pct"], 6.0)
        self.assertEqual(m["capex_share_of_revenue_pct"], 10.0)
        self.assertEqual(m["inventory_minus_revenue_pp"], -15.0)
        self.assertIsNone(m["long_term_debt"])

    def test_report_sections_phase_and_sources(self):
        report = cdr.build_report("SYN", "0000000001", facts=FACTS, submissions={"sic": "3674"},
                                  business={"phrase_zh": "設計合成晶片", "form": "10-K", "filed": "2026-02-01",
                                            "url": "https://www.sec.gov/Archives/edgar/data/1/x.htm"},
                                  rotation=ROTATION, rotation_config=CONFIG, today=TODAY)
        text = {s["title"]: s["text"] for s in report["sections"]}
        self.assertIn("設計合成晶片", text["公司業務"])
        self.assertIn("年增 +25.0%", text["營運動能"])
        self.assertIn("年增 +100.0%", text["訂單能見度"])
        self.assertIn("合成半導體", text["所屬產業訊號"])
        # RPO up (issuer) + industry PPI up (BLS) + margin up (capture) -> commercial validation
        self.assertEqual(report["phase"]["phase"], "COMMERCIAL_VALIDATION")
        self.assertTrue(report["phase"]["dilution_overhang"])  # +6% diluted shares
        self.assertTrue(all(ref["url"].startswith("https://") for ref in report["source_references"]))

    def test_missing_facts_are_stated_and_stale_evidence_downgrades(self):
        empty = {"entityName": "Empty Co", "facts": {"us-gaap": {}}}
        report = cdr.build_report("EMP", "0000000002", facts=empty, submissions={}, business=None, rotation=None,
                                  rotation_config=None, today=TODAY)
        text = {s["title"]: s["text"] for s in report["sections"]}
        self.assertIn("未申報剩餘履約義務", text["訂單能見度"])
        self.assertEqual(report["phase"]["phase"], "INSUFFICIENT_EVIDENCE")
        late = cdr.build_report("SYN", "0000000001", facts=FACTS, submissions={"sic": "3674"}, business=None,
                                rotation=ROTATION, rotation_config=CONFIG, today=date(2027, 6, 1))
        self.assertIn(late["phase"]["phase"], ("INSUFFICIENT_EVIDENCE", "DISCOVERY"))

    def test_build_reports_records_failures_without_guessing(self):
        def fetch(url):
            if "CIK0000000009" in url:
                raise OSError("down")
            return json.dumps(FACTS if "companyfacts" in url else {"sic": "3674"}).encode()
        document = cdr.build_reports({"SYN": "0000000001", "BAD": "0000000009"}, fetch, today=TODAY,
                                     rotation=ROTATION, rotation_config=CONFIG)
        self.assertEqual(list(document["reports"]), ["SYN"])
        self.assertEqual(document["failures"], {"BAD": "OSError"})
        self.assertFalse(document["publication_eligible"])


class SealingTests(unittest.TestCase):
    def test_load_reports_compacts_for_the_worker_and_rejects_stale(self):
        import tempfile
        report = cdr.build_report("SYN", "0000000001", facts=FACTS, submissions={"sic": "3674"}, business=None,
                                  rotation=ROTATION, rotation_config=CONFIG, today=TODAY)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reports.json"
            path.write_text(json.dumps({"as_of": TODAY.isoformat(), "reports": {"SYN": report}}), encoding="utf-8")
            compact = cdr.load_reports(path, tickers=["SYN", "ABSENT"], today=TODAY)
            self.assertEqual(list(compact), ["SYN"])
            self.assertEqual(set(compact["SYN"]), {"ticker", "name", "as_of", "boundary", "phase", "sections", "source_references", "kpis"})
            self.assertNotIn("metrics", compact["SYN"])
            tiles = {row["label"]: row for row in compact["SYN"]["kpis"]}
            self.assertEqual(tiles["營收年增"]["value"], report["metrics"]["revenue_yoy_pct"])
            self.assertTrue(tiles["營收年增"]["signed"])
            self.assertFalse(tiles["毛利率"]["signed"])
            self.assertTrue(all(len(row["label"]) <= 12 and row["unit"] == "%" for row in compact["SYN"]["kpis"]))
            self.assertTrue(all(row["value"] is None or isinstance(row["value"], float) for row in compact["SYN"]["kpis"]))
            self.assertTrue(all(len(s["text"]) <= 700 and "\n" not in s["text"] for s in compact["SYN"]["sections"]))
            self.assertEqual(cdr.load_reports(path, tickers=["SYN"], today=date(2026, 10, 9)), {})  # older than 7 days
            self.assertEqual(cdr.load_reports(Path(tmp) / "absent.json", tickers=["SYN"], today=TODAY), {})

    def test_sealed_tickers_and_ticker_map_cache(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "20260925T115615Z-a34e5d5b5326"
            run.mkdir()
            (run / "summary.json").write_text(json.dumps({"ranked": [[1, "GEV", 96.0], [2, "6501", 93.0]]}), encoding="utf-8")
            self.assertEqual(cdr.sealed_tickers(Path(tmp)), ["GEV", "6501"])
            calls = []
            payload = json.dumps({"fields": ["cik", "name", "ticker", "exchange"], "data": [[1, "Syn", "syn", "NYSE"]]}).encode()

            def fetch(url):
                calls.append(url)
                return payload
            cache = Path(tmp) / "tickers.json"
            self.assertEqual(cdr.ticker_ciks(fetch, today=TODAY, cache=cache), {"SYN": "0000000001"})
            cdr.ticker_ciks(fetch, today=date.today(), cache=cache)
            self.assertEqual(len(calls), 1)  # second call served from the weekly cache


if __name__ == "__main__":
    unittest.main()
