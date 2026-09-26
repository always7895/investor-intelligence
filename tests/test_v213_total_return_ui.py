from __future__ import annotations

import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from historical_return_evidence import (
    calculate_return_evidence,
    canonical_return_triplet,
    build_two_year_return_evidence,
    validate_two_year_return_evidence_dict,
    ReturnEvidenceError,
)
import build_v213_scheduled_top20_report as scheduled_builder


def market_anchors(report, day=None):
    """Latest-daily-bar anchors for the seven-field producer (synthetic; today's date unless given)."""
    from datetime import datetime as _dt, timezone as _tz
    day = day or _dt.now(_tz.utc).date().isoformat()
    return {'records': {row['ticker']: {'windows': {'six_month': {'actual_end': day}}} for row in report['records']}}


def profit_claims(report, day=None):
    """Profit-display sidecar: every displayed profit metric filed today (synthetic)."""
    from datetime import datetime as _dt, timezone as _tz
    day = day or _dt.now(_tz.utc).date().isoformat()
    return {'records': {row['ticker']: {'claim_filed_at': day} for row in report['records']}}


def evidence_inputs(report):
    return {'return_evidence': market_anchors(report), 'profit_display': profit_claims(report)}


def write_anchors(path, report):
    """Sidecars next to a v212 report file, where the producer CLI looks by default."""
    path.with_name(path.stem + '.return-evidence-candidate.json').write_text(__import__('json').dumps(market_anchors(report)), encoding='utf-8')
    path.with_name(path.stem + '.profit-display-candidate.json').write_text(__import__('json').dumps(profit_claims(report)), encoding='utf-8')
from report_source_acquisition import field_clock


class V213TotalReturnUITests(unittest.TestCase):
    def test_canonical_return_triplet_units_and_values(self):
        end = date(2026, 9, 9)
        # 2 years = 730 days, start = 2024-09-09
        # Price 80 -> 120 is +50% total return
        points = [
            (date(2024, 9, 9), 80.0),
            (date(2026, 3, 9), 100.0),
            (end, 120.0),
        ]
        evidence = calculate_return_evidence(points)
        total_2y, cagr_2y, ret_6m = canonical_return_triplet(evidence)

        # Explicit percent units, not fraction
        self.assertEqual(total_2y, 50.0)
        self.assertNotEqual(total_2y, 0.5)
        self.assertAlmostEqual(cagr_2y, 22.47, places=1)
        self.assertEqual(ret_6m, 20.0)

    def test_endpoint_arithmetic_consistency(self):
        end = date(2026, 9, 9)
        start = date(2024, 9, 9)
        start_price = 64.5
        end_price = 129.0
        points = [(start, start_price), (end, end_price)]
        evidence = calculate_return_evidence(points)
        total_2y, cagr_2y, _ = canonical_return_triplet(evidence)

        expected_calc = ((end_price / start_price) - 1.0) * 100.0
        self.assertEqual(total_2y, round(expected_calc, 2))
        self.assertEqual(total_2y, 100.0)

    def test_zero_and_negative_returns_are_valid(self):
        end = date(2026, 9, 9)
        start = date(2024, 9, 9)

        # Zero return
        ev_flat = calculate_return_evidence([(start, 100.0), (end, 100.0)])
        tot_flat, _, _ = canonical_return_triplet(ev_flat)
        self.assertEqual(tot_flat, 0.0)

        # Negative return
        ev_down = calculate_return_evidence([(start, 100.0), (end, 65.0)])
        tot_down, _, _ = canonical_return_triplet(ev_down)
        self.assertEqual(tot_down, -35.0)

    def test_never_reverse_cagr_or_use_incomplete_history(self):
        end = date(2026, 9, 9)
        # 500 days history is not 2 years
        incomplete = [(end - timedelta(days=500), 50.0), (end, 100.0)]
        ev_incomplete = calculate_return_evidence(incomplete)
        tot_inc, cagr_inc, _ = canonical_return_triplet(ev_incomplete)
        self.assertIsNone(tot_inc)
        self.assertIsNone(cagr_inc)

    def test_build_two_year_return_evidence_schema(self):
        end = date(2026, 9, 9)
        start = date(2024, 9, 9)
        points = [(start, 80.0), (end, 120.0)]
        evidence = calculate_return_evidence(points)
        envelope = build_two_year_return_evidence("NVDA", evidence)

        self.assertIsNotNone(envelope)
        self.assertEqual(envelope["ticker"], "NVDA")
        self.assertEqual(envelope["window"], "two_year")
        self.assertEqual(envelope["actual_start"], "2024-09-09")
        self.assertEqual(envelope["actual_end"], "2026-09-09")
        self.assertEqual(envelope["start_adjusted_close"], 80.0)
        self.assertEqual(envelope["end_adjusted_close"], 120.0)
        self.assertEqual(envelope["elapsed_days"], 730)
        self.assertEqual(envelope["total_return_pct"], 50.0)
        self.assertEqual(envelope["market_source"], "yfinance")
        self.assertEqual(envelope["basis"], "adjusted_close")
        self.assertEqual(envelope["dividend_split_semantics"], "auto_adjusted")

        self.assertTrue(validate_two_year_return_evidence_dict(envelope, "NVDA", "2026-09-10T00:00:00Z"))

    def test_reject_forged_or_invalid_evidence_dict(self):
        valid_envelope = {
            "ticker": "NVDA",
            "window": "two_year",
            "actual_start": "2024-09-09",
            "actual_end": "2026-09-09",
            "start_adjusted_close": 80.0,
            "end_adjusted_close": 120.0,
            "elapsed_days": 730,
            "total_return_pct": 50.0,
            "market_source": "yfinance",
            "basis": "adjusted_close",
            "dividend_split_semantics": "auto_adjusted",
        }

        # Ticker mismatch
        self.assertFalse(validate_two_year_return_evidence_dict(valid_envelope, "AAPL"))

        # Mismatched calculation (claimed 100%, actual is 50%)
        bad_calc = dict(valid_envelope, total_return_pct=100.0)
        self.assertFalse(validate_two_year_return_evidence_dict(bad_calc, "NVDA"))

        # Invalid basis
        bad_basis = dict(valid_envelope, basis="raw_close")
        self.assertFalse(validate_two_year_return_evidence_dict(bad_basis, "NVDA"))

        # Start >= End
        bad_dates = dict(valid_envelope, actual_start="2026-09-09", actual_end="2024-09-09")
        self.assertFalse(validate_two_year_return_evidence_dict(bad_dates, "NVDA"))

        # Non-finite price
        bad_price = dict(valid_envelope, start_adjusted_close=float("nan"))
        self.assertFalse(validate_two_year_return_evidence_dict(bad_price, "NVDA"))

        # Scalar-only injected value without dates/endpoints
        self.assertFalse(validate_two_year_return_evidence_dict(50.0, "NVDA"))

    def test_reject_one_day_masquerade_730_days(self):
        # 1-day difference between actual_start and actual_end, but claiming elapsed_days = 730
        masquerade = {
            "ticker": "NVDA",
            "window": "two_year",
            "actual_start": "2026-09-08",
            "actual_end": "2026-09-09",
            "start_adjusted_close": 80.0,
            "end_adjusted_close": 120.0,
            "elapsed_days": 730,
            "total_return_pct": 50.0,
            "market_source": "yfinance",
            "basis": "adjusted_close",
            "dividend_split_semantics": "auto_adjusted",
        }
        self.assertFalse(validate_two_year_return_evidence_dict(masquerade, "NVDA", "2026-09-10T00:00:00Z"))

    def test_reject_impossible_calendar_dates(self):
        valid = {
            "ticker": "NVDA",
            "window": "two_year",
            "actual_start": "2024-09-09",
            "actual_end": "2026-09-09",
            "start_adjusted_close": 80.0,
            "end_adjusted_close": 120.0,
            "elapsed_days": 730,
            "total_return_pct": 50.0,
            "market_source": "yfinance",
            "basis": "adjusted_close",
            "dividend_split_semantics": "auto_adjusted",
        }
        # Feb 30
        self.assertFalse(validate_two_year_return_evidence_dict(dict(valid, actual_start="2024-02-30"), "NVDA"))
        # Apr 31
        self.assertFalse(validate_two_year_return_evidence_dict(dict(valid, actual_start="2024-04-31"), "NVDA"))
        # Feb 29 non-leap year
        self.assertFalse(validate_two_year_return_evidence_dict(dict(valid, actual_start="2023-02-29"), "NVDA"))

    def test_reject_stale_future_and_invalid_clocks(self):
        valid = {
            "ticker": "NVDA",
            "window": "two_year",
            "actual_start": "2024-09-09",
            "actual_end": "2026-09-09",
            "start_adjusted_close": 80.0,
            "end_adjusted_close": 120.0,
            "elapsed_days": 730,
            "total_return_pct": 50.0,
            "market_source": "yfinance",
            "basis": "adjusted_close",
            "dividend_split_semantics": "auto_adjusted",
        }
        # Future end relative to retrieved_at
        self.assertFalse(validate_two_year_return_evidence_dict(
            dict(valid, actual_end="2026-09-15"), "NVDA", "2026-09-10T00:00:00Z"
        ))
        # Stale end (2 years old relative to retrieved_at)
        self.assertFalse(validate_two_year_return_evidence_dict(
            dict(valid, actual_start="2022-09-09", actual_end="2024-09-09", elapsed_days=731),
            "NVDA", "2026-09-10T00:00:00Z"
        ))
        # Malformed retrieved_at
        self.assertFalse(validate_two_year_return_evidence_dict(valid, "NVDA", "NOT_A_VALID_DATE"))

    def test_reject_currency_mismatch_and_tampered_keys_and_boolean_prices(self):
        valid = {
            "ticker": "NVDA",
            "window": "two_year",
            "actual_start": "2024-09-09",
            "actual_end": "2026-09-09",
            "start_adjusted_close": 80.0,
            "end_adjusted_close": 120.0,
            "elapsed_days": 730,
            "total_return_pct": 50.0,
            "market_source": "yfinance",
            "basis": "adjusted_close",
            "dividend_split_semantics": "auto_adjusted",
        }
        # Currency mismatch
        self.assertFalse(validate_two_year_return_evidence_dict(dict(valid, currency="EUR"), "NVDA"))
        # Extra tampered key
        self.assertFalse(validate_two_year_return_evidence_dict(dict(valid, injected="forged"), "NVDA"))
        # Boolean price
        self.assertFalse(validate_two_year_return_evidence_dict(dict(valid, start_adjusted_close=True), "NVDA"))
        # Boolean total return pct
        self.assertFalse(validate_two_year_return_evidence_dict(dict(valid, total_return_pct=True), "NVDA"))

    def test_backward_compatibility_when_bundle_lacks_field(self):
        # When v2.1.2 or v2.1.3 scheduled builder encounters older rows without two_year_total_return_pct
        generated = "2026-09-01T12:00:00Z"
        tickers = [f"T{i:02d}" for i in range(20)]
        v212_old = {
            "product_version": "2.1.2",
            "generated_at": generated,
            "schema_version": 2,
            "calculation_cutoff": generated,
            "display_columns": scheduled_builder.DISPLAY_COLUMNS[:5],
            "long_term_definition": "trailing_2y_adjusted_close_cagr",
            "short_term_definition": "trailing_6m_adjusted_close_price_return",
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
            "records": [
                {
                    "schema_version": 2,
                    "rank": i + 1,
                    "ticker": ticker,
                    "long_term_return_pct": 10 + i,
                    "short_term_return_pct": 2 + i,
                    "industry": "半導體",
                    "profit_summary": "獲利",
                    "retrieved_at": generated,
                    "long_term_window": "2y_cagr",
                    "short_term_window": "6m_price_return",
                    "market_source": "yfinance",
                    "profit_source": "sec_edgar",
                    "provider_scope": "public_only",
                    "owner_watchlist_inherited": False,
                }
                for i, ticker in enumerate(tickers)
            ],
        }
        for row in v212_old["records"]:
            row["source_acquisition"] = {
                key: field_clock(key, row[key], retrieved_at=generated, evidence_sha256="1" * 64)
                for key in ("long_term_return_pct", "short_term_return_pct", "industry", "profit_summary")
            }
        baseline = {
            "product_version": "2.1.3",
            "records": [
                {
                    "rank": i + 1,
                    "ticker": ticker,
                    "current_orders": "未揭露（無可靠公開訂單數字）",
                    "future_orders_estimate": "無可靠公開預估",
                    "orders_as_of": "2026-08-31",
                    "orders_confidence": "NO_RELIABLE_PUBLIC_ORDER_NUMBER",
                    "current_order_source_urls": [],
                    "future_order_source_urls": [],
                }
                for i, ticker in enumerate(tickers)
            ],
        }
        names = {ticker: f"Company {i}" for i, ticker in enumerate(tickers)}
        result = scheduled_builder.build(v212_old, baseline, names, **evidence_inputs(v212_old))
        self.assertEqual(len(result["records"]), 20)
        # Verify that absence of two_year_total_return_pct does not crash builder
        self.assertNotIn("two_year_total_return_pct", result["records"][0])

    def test_candidate_helper_does_not_propagate_into_legacy_or_grant_admission(self):
        # Candidate helper remains candidate only; publication eligible is False
        end = date(2026, 9, 9)
        start = date(2024, 9, 9)
        points = [(start, 80.0), (end, 120.0)]
        evidence = calculate_return_evidence(points)
        self.assertFalse(evidence["publication_eligible"])
        envelope = build_two_year_return_evidence("NVDA", evidence)
        self.assertIsNotNone(envelope)
        # Arithmetic and schema validation passes candidate check, but live admission is DEFERRED
        self.assertTrue(validate_two_year_return_evidence_dict(envelope, "NVDA", "2026-09-10T00:00:00Z"))



if __name__ == "__main__":
    unittest.main()
