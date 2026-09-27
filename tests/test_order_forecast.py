"""Focused tests for scripts/order_forecast.py (Astra contract %TEMP%/ii-live/astra-contract-orders.md,
items 5-21, 28-30, 39-42; batch 32).

Only build(), from_recognition(), from_stock() and add_months() are exercised, with the report date
2026-09-27 throughout. Recognition fixtures mirror company_deep_report.order_scenario output; stock
fixtures mirror the v3 outlook.orders shape (kind RPO/BACKLOG, amount, currency, as_of, yoy, source_url).
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import order_forecast as ofc  # noqa: E402

REPORT_DAY = date(2026, 9, 27)


def recognition(status="DISCLOSED", rpo=3.2e9, revenue=96.221e9, as_of="2026-07-26",
                quarter_end="2026-07-26", filed="2026-08-26", url="https://www.sec.gov/fixture",
                form="10-Q", horizons=None, **extra):
    # the mandatory evidence (Astra batch 33): accession, passage, report period and the quarter's start
    quarter_start = str(date.fromisoformat(quarter_end) - timedelta(days=90)) if quarter_end else None
    orders = {"status": status, "form": form, "filed": filed, "url": url, "rpo": rpo,
              "rpo_as_of": as_of, "quarter_revenue": revenue, "quarter_end": quarter_end, "quarter_start": quarter_start,
              "quarter_basis": "FRAME", "accession": "0001045810-26-000075", "passage": "fixture passage stating the schedule",
              "report_date": as_of, "horizons": horizons if horizons is not None else {}}
    orders.update(extra)
    return orders


def stock(**overrides):
    orders = {"kind": "RPO", "amount": 1e9, "currency": "USD", "as_of": "2026-06-29",
              "yoy": 0.2, "source_url": "https://www.sec.gov/fixture-stock", "scope_kind": "COMPANY",
              "yoy_evidence": "fixture: the company states the book grew 20% on the year-ago quarter"}
    orders.update(overrides)
    return orders


# Contract fixture values (item 39): NVDA 3.2B x 39% = 1.248B, AVGO 179.2B x 25% = 44.8B,
# AMD 222M x 64.9% = 144.078M; CRWV 103.7B x 41% = 42.517B is 24M-only (item 40).
NVDA = recognition(horizons={"m6": None, "m12": {"share_pct": 39, "derived": False}})
AVGO = recognition(rpo=179.2e9, revenue=70.5e9, as_of="2026-06-27", quarter_end="2026-06-27",
                   filed="2026-07-31", form="10-K", url="https://www.sec.gov/fixture-avgo",
                   horizons={"m12": {"share_pct": 25, "derived": False}})
AMD = recognition(rpo=222e6, revenue=7.0e9, as_of="2026-06-27", quarter_end="2026-06-27",
                  filed="2026-08-04", url="https://www.sec.gov/fixture-amd",
                  horizons={"m12": {"share_pct": 64.9, "derived": False}})
CRWV = recognition(rpo=103.7e9, revenue=50.0e9, as_of="2026-06-30", quarter_end="2026-06-30",
                  filed="2026-08-07", form="10-K", url="https://www.sec.gov/fixture-crwv",
                  horizons={"m24": {"share_pct": 41, "derived": False}})


class AddMonthsTests(unittest.TestCase):
    def test_same_day_forward(self):
        self.assertEqual(ofc.add_months(date(2026, 7, 26), 12), date(2027, 7, 26))
        self.assertEqual(ofc.add_months(REPORT_DAY, 6), date(2027, 3, 27))
        self.assertEqual(ofc.add_months(REPORT_DAY, 12), date(2027, 9, 27))

    def test_month_end_clamp(self):
        self.assertEqual(ofc.add_months(date(2026, 8, 31), 6), date(2027, 2, 28))

    def test_leap_day_clamp(self):
        self.assertEqual(ofc.add_months(date(2028, 2, 29), 12), date(2029, 2, 28))


class RecognitionTests(unittest.TestCase):
    def test_nvda_m12_recognition_and_m6_gap(self):
        f = ofc.from_recognition("FIX", NVDA, REPORT_DAY)
        self.assertEqual(f["status"], "AVAILABLE")
        m12 = f["m12"]
        self.assertEqual(m12["status"], "AVAILABLE")
        self.assertEqual(m12["basis"], "RECOGNITION")
        self.assertEqual(m12["amount"], 1.248e9)
        self.assertEqual(m12["start"], "2026-07-26")
        self.assertEqual(m12["end"], "2027-07-26")
        self.assertEqual(m12["scenario"]["status"], "INSUFFICIENT_COVERAGE")
        self.assertEqual(m12["scenario"]["coverage"], 1.248e9 / (96.221e9 * 4))
        self.assertNotIn("change", m12["scenario"])
        # A missing 6M horizon stays unavailable; it is never half of the 12M figure (item 8).
        self.assertEqual(f["m6"]["status"], "UNAVAILABLE")
        self.assertEqual(f["m6"]["reason"], "NOT_DISCLOSED_HORIZON")
        self.assertNotIn("amount", f["m6"])

    def test_avgo_amount(self):
        self.assertEqual(ofc.from_recognition("FIX", AVGO, REPORT_DAY)["m12"]["amount"], 44.8e9)

    def test_amd_amount(self):
        self.assertAlmostEqual(ofc.from_recognition("FIX", AMD, REPORT_DAY)["m12"]["amount"], 144.078e6, delta=1e-3)

    def test_crwv_24m_reference_only(self):
        f = ofc.from_recognition("FIX", CRWV, REPORT_DAY)
        self.assertEqual(f["status"], "UNAVAILABLE")
        self.assertEqual(f["reason"], "NOT_DISCLOSED_HORIZON")
        for key in ("m6", "m12"):
            self.assertEqual(f[key]["status"], "UNAVAILABLE")
            self.assertEqual(f[key]["reason"], "NOT_DISCLOSED_HORIZON")
        (reference,) = f["references"]
        self.assertEqual({k: reference[k] for k in ("kind", "amount", "currency", "start", "end", "share_pct", "source_url", "rpo", "as_of")},
                         {"kind": "RECOGNITION_24M", "amount": 42.517e9, "currency": "USD", "start": "2026-06-30", "end": "2028-06-30",
                          "share_pct": 41, "source_url": "https://www.sec.gov/fixture-crwv", "rpo": 103.7e9, "as_of": "2026-06-30"})
        self.assertTrue(reference["accession"] and reference["passage"] and reference["explicit"])  # independently verifiable

    def test_explicit_coverage_gives_available_change(self):
        f = ofc.from_recognition("FIX", recognition(rpo=1e9, revenue=1e8,
                                             horizons={"m6": {"share_pct": 30, "derived": False}, "m12": {"share_pct": 80, "derived": False}}), REPORT_DAY)
        self.assertEqual(f["m6"]["scenario"], {"status": "AVAILABLE", "coverage": 1.5, "change": 0.5})
        self.assertEqual(f["m12"]["scenario"], {"status": "AVAILABLE", "coverage": 2.0, "change": 1.0})

    def test_unit_coverage_zero_change(self):
        f = ofc.from_recognition("FIX", recognition(rpo=1e9, revenue=1e8, horizons={"m6": {"share_pct": 20, "derived": False}}), REPORT_DAY)
        scenario = f["m6"]["scenario"]
        self.assertEqual(scenario["status"], "AVAILABLE")
        self.assertEqual(scenario["coverage"], 1.0)
        self.assertEqual(scenario["change"], 0.0)

    def test_derived_m6_is_not_evidence(self):
        f = ofc.from_recognition("FIX", recognition(rpo=1e9, revenue=1e8, horizons={"m6": {"share_pct": 30, "derived": True},
                                                                                  "m12": {"share_pct": 50, "derived": False}}), REPORT_DAY)
        self.assertEqual(f["m6"]["status"], "UNAVAILABLE")
        self.assertEqual(f["m6"]["reason"], "NOT_DISCLOSED_HORIZON")
        self.assertEqual(f["m12"]["status"], "AVAILABLE")

    def test_invalid_share_values_unavailable(self):
        for share in (0, 101, True, float("nan")):
            f = ofc.from_recognition("FIX", recognition(rpo=1e9, revenue=1e8, horizons={"m6": {"share_pct": share, "derived": False},
                                                                                    "m12": {"share_pct": 50, "derived": False}}), REPORT_DAY)
            # a stated share that is not a percentage is malformed evidence for the whole schedule (Astra batch 33)
            self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "INVALID_SHARE"), share)

    def test_fail_closed_statuses(self):
        for status in ("PERIOD_MISMATCH", "INPUTS_MISSING"):
            f = ofc.from_recognition("FIX", recognition(status=status), REPORT_DAY)
            self.assertEqual(f["status"], "UNAVAILABLE", status)
            self.assertEqual(f["reason"], status)
            for key in ("m6", "m12"):
                self.assertEqual(f[key]["status"], "UNAVAILABLE", status)
                self.assertEqual(f[key]["reason"], status)
            self.assertEqual(f["references"], [])

    def test_fail_closed_statuses_block_stock_fallback(self):
        for status in ("PERIOD_MISMATCH", "INPUTS_MISSING"):
            f = ofc.build("FIX", stock(), recognition(status=status), REPORT_DAY)
            self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", status))
            self.assertEqual(f["m6"]["reason"], status)
            self.assertEqual(f["m12"]["reason"], status)

    def test_age_boundaries(self):
        ok = ofc.from_recognition("FIX", recognition(as_of="2026-03-11", quarter_end="2026-03-11", filed="2026-03-12",
                                              horizons={"m12": {"share_pct": 50, "derived": False}}), REPORT_DAY)
        self.assertEqual(ok["status"], "AVAILABLE")
        stale = ofc.from_recognition("FIX", recognition(as_of="2026-03-10", quarter_end="2026-03-10", filed="2026-03-11",
                                                horizons={"m12": {"share_pct": 50, "derived": False}}), REPORT_DAY)
        self.assertEqual((stale["status"], stale["reason"]), ("UNAVAILABLE", "STALE"))
        self.assertEqual(stale["m6"]["reason"], "STALE")

    def test_future_as_of_invalid(self):
        f = ofc.from_recognition("FIX", recognition(as_of="2026-09-28", quarter_end="2026-09-28", filed="2026-09-28",
                                             horizons={"m12": {"share_pct": 50, "derived": False}}), REPORT_DAY)
        self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "INVALID"))

    def test_filed_after_report_day_invalid(self):
        f = ofc.from_recognition("FIX", recognition(filed="2026-09-28", horizons={"m12": {"share_pct": 50, "derived": False}}), REPORT_DAY)
        self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "INVALID"))

    def test_http_url_invalid(self):
        f = ofc.from_recognition("FIX", recognition(url="http://www.sec.gov/fixture",
                                            horizons={"m12": {"share_pct": 50, "derived": False}}), REPORT_DAY)
        self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "INVALID"))

    def test_period_mismatch_tolerance(self):
        mismatch = ofc.from_recognition("FIX", recognition(quarter_end="2026-09-10", horizons={"m12": {"share_pct": 50, "derived": False}}),
                                       REPORT_DAY)
        self.assertEqual((mismatch["status"], mismatch["reason"]), ("UNAVAILABLE", "PERIOD_MISMATCH"))
        ok = ofc.from_recognition("FIX", recognition(quarter_end="2026-09-09", horizons={"m12": {"share_pct": 50, "derived": False}}),
                                 REPORT_DAY)
        self.assertEqual(ok["status"], "AVAILABLE")

    def test_missing_quarter_end_invalid(self):
        f = ofc.from_recognition("FIX", recognition(quarter_end=None, horizons={"m12": {"share_pct": 50, "derived": False}}), REPORT_DAY)
        self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "INVALID"))

    def test_not_disclosed_status_returns_none(self):
        self.assertIsNone(ofc.from_recognition("FIX", recognition(status="NOT_DISCLOSED"), REPORT_DAY))
        self.assertIsNone(ofc.from_recognition("FIX", None, REPORT_DAY))


class StockTests(unittest.TestCase):
    def test_extrapolation_uses_report_day_baseline(self):
        f = ofc.from_stock("FIX", stock(), REPORT_DAY)
        self.assertEqual(f["status"], "AVAILABLE")
        as_of, g, amount = date(2026, 6, 29), 0.2, 1e9  # a 90-day-old stock proves the baseline is the report date
        for key, months in (("m6", 6), ("m12", 12)):
            end = ofc.add_months(REPORT_DAY, months)
            tile = f[key]
            self.assertEqual(tile["status"], "AVAILABLE")
            self.assertEqual(tile["basis"], "STOCK_EXTRAPOLATION")
            self.assertEqual(tile["start"], "2026-09-27")
            self.assertEqual(tile["end"], str(end))
            self.assertEqual(tile["amount"], amount * (1 + g) ** ((end - as_of).days / 365))
            self.assertAlmostEqual(tile["scenario"]["change"],
                                   (1 + g) ** ((end - REPORT_DAY).days / 365) - 1, delta=1e-9)
        self.assertEqual(f["m6"]["baseline"], amount * (1 + g) ** (90 / 365))
        m12 = f["m12"]["scenario"]["change"]
        self.assertAlmostEqual(m12, (1 + g) ** ((date(2027, 9, 27) - REPORT_DAY).days / 365) - 1, delta=1e-9)
        # NOT O(end)/O(disclosure date) - 1 (item 14): the 90-day-old disclosure date would differ.
        disclosure_based = (1 + g) ** ((date(2027, 9, 27) - as_of).days / 365) - 1
        self.assertGreater(abs(m12 - disclosure_based), 0.01)

    def test_stock_used_only_without_recognition(self):
        self.assertEqual(ofc.build("FIX", stock(), None, REPORT_DAY)["m6"]["basis"], "STOCK_EXTRAPOLATION")
        f = ofc.build("FIX", stock(), recognition(status="NOT_DISCLOSED"), REPORT_DAY)
        self.assertEqual(f["status"], "AVAILABLE")
        self.assertEqual(f["m12"]["basis"], "STOCK_EXTRAPOLATION")

    def test_growth_bounds(self):
        for g in (-1.0, 1.5):
            f = ofc.from_stock("FIX", stock(yoy=g), REPORT_DAY)
            self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "GROWTH_OUT_OF_RANGE"), g)
            self.assertEqual(f["m6"]["reason"], "GROWTH_OUT_OF_RANGE")
        self.assertEqual(ofc.from_stock("FIX", stock(yoy=1.0), REPORT_DAY)["status"], "AVAILABLE")

    def test_missing_or_nan_yoy_no_growth(self):
        self.assertEqual(ofc.from_stock("FIX", stock(yoy=None), REPORT_DAY)["reason"], "NO_GROWTH")
        self.assertEqual(ofc.from_stock("FIX", stock(yoy=float("nan")), REPORT_DAY)["reason"], "NO_GROWTH")

    def test_invalid_amount_currency_and_future_as_of(self):
        for orders in (stock(amount=0), stock(amount=-5), stock(currency=None), stock(currency="")):
            f = ofc.from_stock("FIX", orders, REPORT_DAY)
            self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "INVALID"))
        self.assertEqual(ofc.from_stock("FIX", stock(as_of="2026-09-28"), REPORT_DAY)["reason"], "INVALID")

    def test_stale_boundaries(self):
        self.assertEqual(ofc.from_stock("FIX", stock(as_of="2026-03-10"), REPORT_DAY)["reason"], "STALE")
        self.assertEqual(ofc.from_stock("FIX", stock(as_of="2026-03-11"), REPORT_DAY)["status"], "AVAILABLE")

    def test_not_disclosed_kind_returns_none(self):
        self.assertIsNone(ofc.from_stock("FIX", None, REPORT_DAY))
        self.assertIsNone(ofc.from_stock("FIX", {"kind": "NOT_DISCLOSED"}, REPORT_DAY))

    def test_overflow_fails_closed(self):
        # Found by this test (batch 32): the horizons failed closed but the top-level status still read AVAILABLE;
        # an all-unavailable forecast now reports UNAVAILABLE/INVALID (contract items 30 and 32).
        f = ofc.from_stock("FIX", stock(amount=1.7e308, yoy=1.0), REPORT_DAY)
        self.assertEqual(f["m6"]["status"], "UNAVAILABLE")
        self.assertEqual(f["m6"]["reason"], "INVALID")
        self.assertEqual(f["m12"]["status"], "UNAVAILABLE")
        self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "INVALID"))


class BuildTests(unittest.TestCase):
    def test_no_orders(self):
        f = ofc.build("FIX", None, None, REPORT_DAY)
        self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "NO_ORDERS"))
        self.assertEqual(f["m6"]["reason"], "NO_ORDERS")
        self.assertEqual(f["references"], [])

    def test_not_disclosed(self):
        f = ofc.build("FIX", {"kind": "NOT_DISCLOSED"}, None, REPORT_DAY)
        self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "NOT_DISCLOSED"))

    def test_annual_guidance_is_reference_only(self):
        orders = {"kind": "NOT_DISCLOSED", "currency": "USD",
                  "source_url": "https://www.sec.gov/fixture-guidance",
                  "guidance": {"kind": "ANNUAL_NEW_ORDERS", "amount": 5e9, "year": 2027}}
        f = ofc.build("FIX", orders, None, REPORT_DAY)
        self.assertEqual(f["references"], [{
            "kind": "ANNUAL_NEW_ORDERS_GUIDANCE", "amount": 5e9, "currency": "USD",
            "year": 2027, "source_url": "https://www.sec.gov/fixture-guidance"}])
        for key in ("m6", "m12"):
            self.assertEqual(f[key]["status"], "UNAVAILABLE")  # guidance never becomes a tile

    def test_fractional_guidance_year_ignored(self):
        orders = {"kind": "NOT_DISCLOSED", "currency": "USD",
                  "source_url": "https://www.sec.gov/fixture-guidance",
                  "guidance": {"kind": "ANNUAL_NEW_ORDERS", "amount": 5e9, "year": 2026.5}}
        self.assertEqual(ofc.build("FIX", orders, None, REPORT_DAY)["references"], [])

    def test_guidance_reference_on_stock_forecast(self):
        f = ofc.build("FIX", stock(guidance={"kind": "ANNUAL_NEW_ORDERS", "amount": 5e9, "year": 2027}), None, REPORT_DAY)
        self.assertEqual(f["m6"]["status"], "AVAILABLE")
        self.assertEqual(f["references"][0]["kind"], "ANNUAL_NEW_ORDERS_GUIDANCE")


class TileQuantityTests(unittest.TestCase):
    def test_recognition_tile_money_vs_ratio(self):
        tile = ofc.from_recognition("FIX", NVDA, REPORT_DAY)["m12"]
        self.assertIsInstance(tile["amount"], float)  # money
        self.assertAlmostEqual(tile["amount"], 1.248e9)
        scenario = tile["scenario"]
        self.assertIsInstance(scenario["coverage"], float)  # dimensionless ratio
        self.assertNotIn("change", scenario)
        self.assertNotAlmostEqual(tile["amount"], scenario["coverage"], delta=1.0)

    def test_stock_tile_change_is_ratio(self):
        tile = ofc.from_stock("FIX", stock(), REPORT_DAY)["m6"]
        self.assertIsInstance(tile["amount"], float)
        self.assertIsInstance(tile["scenario"]["change"], float)
        self.assertNotIn("coverage", tile["scenario"])
        self.assertNotAlmostEqual(tile["amount"], tile["scenario"]["change"], delta=1.0)


if __name__ == "__main__":
    unittest.main()


class ContractFixtureTests(unittest.TestCase):
    """tests/fixtures/v213-order-forecast-sealed.json is the wire contract with the Worker (cloud/test/v213-bottleneck-v3.test.ts
    renders these exact records): each recorded `sealed` forecast must equal build() for its inputs."""

    def test_the_worker_fixture_is_what_build_produces(self):
        import json
        from pathlib import Path
        golden = json.loads((Path(__file__).resolve().parent / "fixtures" / "v213-order-forecast-sealed.json").read_text(encoding="utf-8"))
        day = date.fromisoformat(golden["report_day"])
        self.assertGreaterEqual(len(golden["cases"]), 7)
        for case in golden["cases"]:
            self.assertEqual(ofc.build(case["issuer"], case["stock"], case["recognition"], day), case["sealed"], case["name"])


class AstraBatch32ProbeTests(unittest.TestCase):
    """The probes of Astra's batch-32 review, each now failing closed."""

    def test_an_unresolved_or_unknown_schedule_status_never_falls_back_to_the_book(self):
        for status in ("INVALID", "STALE", "PERIOD_MISMATCH", "INPUTS_MISSING", "SOMETHING_NEW"):
            f = ofc.build("FIX", stock(), recognition(status=status), REPORT_DAY)
            self.assertEqual(f["status"], "UNAVAILABLE", status)
            self.assertNotEqual(f["m12"].get("basis"), "STOCK_EXTRAPOLATION", status)
        # only a filing that states no schedule lets the book apply
        self.assertEqual(ofc.build("FIX", stock(), recognition(status="NOT_DISCLOSED"), REPORT_DAY)["m12"]["basis"], "STOCK_EXTRAPOLATION")

    def test_a_shrinking_cumulative_schedule_is_a_contradiction(self):
        f = ofc.from_recognition("FIX", recognition(horizons={"m6": {"share_pct": 80, "derived": False}, "m12": {"share_pct": 20, "derived": False}}), REPORT_DAY)
        self.assertEqual((f["status"], f["reason"]), ("UNAVAILABLE", "SCHEDULE_CONTRADICTION"))
        f = ofc.from_recognition("FIX", recognition(horizons={"m12": {"share_pct": 50, "derived": False}, "m24": {"share_pct": 40, "derived": False}}), REPORT_DAY)
        self.assertEqual(f["reason"], "SCHEDULE_CONTRADICTION")

    def test_an_expired_window_is_not_a_future_estimate(self):
        orders = recognition(as_of="2026-03-11", quarter_end="2026-03-11", filed="2026-03-12", revenue=4e9, rpo=40e9,
                             horizons={"m6": {"share_pct": 30, "derived": False}, "m12": {"share_pct": 55, "derived": False}})
        f = ofc.from_recognition("FIX", orders, REPORT_DAY)
        self.assertEqual(f["m6"]["reason"], "EXPIRED")  # ended 2026-09-11, before the report day
        self.assertEqual((f["m12"]["status"], f["m12"]["end"]), ("AVAILABLE", "2027-03-11"))
        ends_today = recognition(as_of="2026-03-27", quarter_end="2026-03-27", filed="2026-04-10", horizons={"m6": {"share_pct": 30, "derived": False}})
        self.assertEqual(ofc.from_recognition("FIX", ends_today, REPORT_DAY)["m6"]["reason"], "EXPIRED")  # ends on the report day
        tomorrow = recognition(as_of="2026-03-28", quarter_end="2026-03-28", filed="2026-04-10", horizons={"m6": {"share_pct": 30, "derived": False}})
        self.assertEqual(ofc.from_recognition("FIX", tomorrow, REPORT_DAY)["m6"]["status"], "AVAILABLE")

    def test_currency_url_and_intermediate_overflow_fail_closed(self):
        self.assertEqual(ofc.from_stock("FIX", stock(currency="BANANAS"), REPORT_DAY)["reason"], "INVALID")
        self.assertEqual(ofc.from_recognition("FIX", recognition(url="https://", horizons={"m12": {"share_pct": 39, "derived": False}}), REPORT_DAY)["reason"], "INVALID")
        self.assertEqual(ofc.from_recognition("FIX", recognition(url="https://sec gov/x", horizons={"m12": {"share_pct": 39, "derived": False}}), REPORT_DAY)["reason"], "INVALID")
        huge = ofc.from_recognition("FIX", recognition(rpo=1.7e308, horizons={"m12": {"share_pct": 39, "derived": False}}), REPORT_DAY)
        self.assertEqual((huge["status"], huge["m12"]["reason"]), ("UNAVAILABLE", "INVALID"))  # rpo x 39 overflows before / 100

    def test_a_segment_book_is_never_priced_as_the_company_and_growth_needs_its_comparison(self):
        segment = ofc.from_stock("FIX", stock(scope_kind="SEGMENT", scope="重工業部門"), REPORT_DAY)
        self.assertEqual((segment["m12"]["status"], segment["m12"]["scope"]), ("AVAILABLE", "SEGMENT"))
        self.assertEqual(segment["m12"]["scenario"], {"status": "NO_BASIS", "reason": "SCOPE_PARTIAL"})
        unscoped = ofc.from_stock("FIX", {k: v for k, v in stock().items() if k != "scope_kind"}, REPORT_DAY)
        self.assertEqual(unscoped["m12"]["scope"], "SEGMENT")  # an unstated scope is never taken as company-wide
        no_lineage = ofc.from_stock("FIX", {k: v for k, v in stock().items() if k != "yoy_evidence"}, REPORT_DAY)
        self.assertEqual(no_lineage["reason"], "NO_GROWTH_LINEAGE")
        series = ofc.from_stock("FIX", {**{k: v for k, v in stock().items() if k != "yoy_evidence"}, "yoy_prior_amount": 1e9 / 1.2,
                                        "yoy_prior_as_of": "2025-06-29"}, REPORT_DAY)
        self.assertEqual(series["m12"]["lineage"], "SERIES")
        wrong = ofc.from_stock("FIX", {**{k: v for k, v in stock().items() if k != "yoy_evidence"}, "yoy_prior_amount": 0.5e9,
                                       "yoy_prior_as_of": "2025-06-29"}, REPORT_DAY)
        self.assertEqual(wrong["reason"], "NO_GROWTH_LINEAGE")  # the stated growth does not match its own comparison

    def test_every_record_names_its_issuer(self):
        f = ofc.build("NVDA", None, NVDA, REPORT_DAY)
        self.assertEqual(f["issuer"], "NVDA")


class LegacyScheduleCacheTests(unittest.TestCase):
    """Astra batch 32 item 1: a schedule cached before horizons were marked "derived" is not qualified evidence."""

    def test_the_extractor_version_invalidates_older_caches(self):
        import order_timing
        self.assertGreaterEqual(order_timing.EXTRACTOR_VERSION, 8)

    def test_an_unqualified_cached_schedule_yields_no_disclosed_horizon(self):
        import company_deep_report as deep
        metrics = {"rpo": 3.2e9, "rpo_as_of": "2026-07-26", "revenue": 96.221e9, "quarter_end": "2026-07-26",
                   "order_quarter": {"val": 96.221e9, "start": "2026-04-27", "end": "2026-07-26", "basis": "FRAME"}}
        legacy = {"status": "DISCLOSED", "form": "10-Q", "filed": "2026-08-26", "url": "https://www.sec.gov/x.htm", "accession": "0001045810-26-000075",
                  "passages": ["Approximately 39% of this amount is expected to be recognized as revenue over the next twelve months"],
                  "report_date": "2026-07-26", "schedule": {"m6": 20.0, "m12": 39.0, "m24": None, "premises": ["6 個月以揭露的 0–12 個月區間線性攤提"]}}
        scenario = deep.order_scenario(metrics, legacy)
        self.assertTrue(scenario["horizons"]["m12"]["derived"])
        forecast = ofc.build("NVDA", None, scenario, REPORT_DAY)
        self.assertEqual((forecast["status"], forecast["m12"]["reason"]), ("UNAVAILABLE", "NOT_DISCLOSED_HORIZON"))
        qualified = {**legacy, "schedule": {**legacy["schedule"], "m6": None, "derived": []}}
        self.assertEqual(ofc.build("NVDA", None, deep.order_scenario(metrics, qualified), REPORT_DAY)["m12"]["status"], "AVAILABLE")


class AstraBatch33ProbeTests(unittest.TestCase):
    """The probes of Astra's batch-33 review, each now failing closed."""
    STATED = {"m12": {"share_pct": 39, "derived": False}}

    def test_the_recognition_evidence_is_mandatory_and_never_relabelled(self):
        for field in ("accession", "passage", "report_date", "quarter_start"):
            orders = recognition(horizons=self.STATED)
            orders.pop(field)
            self.assertEqual(ofc.from_recognition("FIX", orders, REPORT_DAY)["reason"], "INVALID", field)
        for change in ({"report_date": "2025-01-01"}, {"accession": "not-an-accession"}, {"form": "8-K"}, {"quarter_start": "2026-07-20"},
                       {"scope": "SEGMENT"}, {"currency": "KRW"}):
            self.assertEqual(ofc.from_recognition("FIX", recognition(horizons=self.STATED, **change), REPORT_DAY)["reason"], "INVALID", change)
        record = ofc.from_recognition("FIX", recognition(horizons=self.STATED), REPORT_DAY)["m12"]
        self.assertEqual((record["explicit"], record["accession"], record["report_period"]), (True, "0001045810-26-000075", "2026-07-26"))

    def test_the_fourth_quarter_derivation_is_validated_as_a_whole(self):
        good = {"annual": 20.248e9, "annual_start": "2025-06-28", "annual_accession": "0001628280-26-057406",
                "nine_months": 11.283e9, "nine_months_end": "2026-04-03", "nine_months_accession": "0001628280-26-040001"}
        base = dict(rpo=59.8e9, revenue=8.965e9, as_of="2026-07-03", quarter_end="2026-07-03", filed="2026-08-17", form="10-K",
                    horizons={"m12": {"share_pct": 19, "derived": False}}, quarter_basis="DERIVED_Q4")
        ok = recognition(**base, quarter_derivation=good)
        ok["quarter_start"] = "2026-04-04"
        self.assertEqual(ofc.from_recognition("FIX", ok, REPORT_DAY)["m12"]["quarter_derivation"], good)
        for change in ({"nine_months_end": "1900-01-01"}, {"annual_accession": None}, {"annual": -20.248e9, "nine_months": -29.213e9},
                       {"annual_start": "2025-01-01"}, {"nine_months": 11.0e9}):
            bad = recognition(**base, quarter_derivation={**good, **change})
            bad["quarter_start"] = "2026-04-04"
            self.assertEqual(ofc.from_recognition("FIX", bad, REPORT_DAY)["reason"], "INVALID", change)
        shifted = recognition(**base, quarter_derivation=good)
        shifted["quarter_start"] = "2026-04-05"  # not the day after the nine months
        self.assertEqual(ofc.from_recognition("FIX", shifted, REPORT_DAY)["reason"], "INVALID")

    def test_malformed_urls_are_invalid_evidence_not_exceptions(self):
        for url in ("https://:password@example.com/x", "https://user@example.com/x", "https://example.com:bad/x", "https://[bad/x",
                    "https://example.com:0/x", "https://localhost/x"):
            self.assertIsNone(ofc._https(url), url)
            self.assertEqual(ofc.from_recognition("FIX", recognition(url=url, horizons=self.STATED), REPORT_DAY)["reason"], "INVALID", url)
        self.assertEqual(ofc._https("https://www.sec.gov:443/x"), "https://www.sec.gov:443/x")

    def test_malformed_shares_and_the_top_level_reason_are_explicit(self):
        f = ofc.from_recognition("FIX", recognition(horizons={"m12": {"share_pct": 101, "derived": False}}), REPORT_DAY)
        self.assertEqual(f["reason"], "INVALID_SHARE")
        huge = ofc.from_recognition("FIX", recognition(rpo=1.7e308, horizons=self.STATED), REPORT_DAY)
        self.assertEqual((huge["reason"], huge["m6"]["reason"], huge["m12"]["reason"]), ("INVALID", "NOT_DISCLOSED_HORIZON", "INVALID"))
        self.assertEqual(ofc.top_reason(ofc._unavailable("EXPIRED"), ofc._unavailable("NOT_DISCLOSED_HORIZON")), "NOT_DISCLOSED_HORIZON")


class AstraBatch34ProbeTests(unittest.TestCase):
    def test_url_acceptance_matches_the_worker_table(self):
        import json
        from pathlib import Path
        table = json.loads((Path(__file__).resolve().parent / "fixtures" / "v213-order-forecast-urls.json").read_text(encoding="utf-8"))
        for case in table["cases"]:
            self.assertEqual(ofc._https(case["url"]) is not None, case["accepted"], case["url"])
            if not case["accepted"]:
                self.assertEqual(ofc.from_recognition("FIX", recognition(url=case["url"], horizons={"m12": {"share_pct": 39, "derived": False}}),
                                                      REPORT_DAY)["reason"], "INVALID", case["url"])
                self.assertEqual(ofc.from_stock("FIX", stock(source_url=case["url"]), REPORT_DAY)["reason"], "INVALID", case["url"])
            crwv = ofc.from_recognition("FIX", {**CRWV, "url": case["url"]}, REPORT_DAY)  # a 24-month-only schedule: the reference alone
            self.assertEqual(len(crwv["references"]) == 1, case["accepted"], case["url"])
