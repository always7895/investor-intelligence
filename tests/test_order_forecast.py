"""Focused tests for scripts/order_forecast.py (Astra contract %TEMP%/ii-live/astra-contract-orders.md,
items 5-21, 28-30, 39-42; batch 32).

Only build(), from_recognition(), from_stock() and add_months() are exercised, with the report date
2026-09-27 throughout. Recognition fixtures mirror company_deep_report.order_scenario output; stock
fixtures mirror the v3 outlook.orders shape (kind RPO/BACKLOG, amount, currency, as_of, yoy, source_url).
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import order_forecast as ofc  # noqa: E402

REPORT_DAY = date(2026, 9, 27)


def make_synthetic_approval(registry_sha256: str, issuers: dict, reviewed_at: str = "2026-09-28T11:00:00Z") -> dict:
    """A1: a synthetic enforced reviewed profile covering every operative input of a synthetic registry record
    (the same decision set tests/fixtures/make_orders_v3_golden.py seals). The writer-owned real file is
    config/revenue-guidance-approval-v1.json; tests pass this shape through build_v3's revenue_approval."""
    import hashlib as _hashlib
    import revenue_guidance as _rg
    records: dict[str, dict] = {}
    for sym, rec in issuers.items():
        record_sha = _hashlib.sha256(_rg.canonical_json(rec).encode("utf-8")).hexdigest()
        decisions: list[dict] = []
        for claim in rec.get("claims", []):
            decisions.append({"kind": "CLAIM", "ref": claim["id"], "decision": "VERBATIM_IN_SOURCE", "reviewed_at": reviewed_at})
            if claim.get("reaffirmed_by"):
                decisions.append({"kind": "REAFFIRMATION", "ref": claim["id"], "decision": "VERBATIM_IN_SOURCE", "reviewed_at": reviewed_at})
        for actual in rec.get("reported_quarters", []):
            decisions.append({"kind": "ACTUAL", "ref": actual["end"], "decision": "VALUE_IN_SOURCE", "reviewed_at": reviewed_at})
        decisions.append({"kind": "CALENDAR", "ref": "calendar", "decision": "RULE_QUOTED", "reviewed_at": reviewed_at})
        if rec.get("fy_reconciliation") is not None:
            decisions.append({"kind": "FY_RECONCILIATION", "ref": "fy_reconciliation",
                              "decision": "DERIVATION_OPERANDS_IN_SOURCE", "reviewed_at": reviewed_at})
        routing = "NONDISCLOSURE_CONFIRMED" if rec.get("status") == "NOT_DISCLOSED" else "RULE_QUOTED"
        decisions.append({"kind": "ROUTING", "ref": "routing", "decision": routing, "reviewed_at": reviewed_at})
        records[sym] = {"record_sha256": record_sha, "decisions": decisions}
    return {"status": "OK", "sha256": "f" * 64, "registry_sha256": registry_sha256, "approved_at": reviewed_at,
            "reviewer": "test", "records": records}


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


class OrderForecastV3Tests(unittest.TestCase):
    """Astra contract ORDERS-V3-01: build_v3 tests, revenue vs orders separation, dual fields."""

    def setUp(self):
        self.cutoff = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
        self.report_day = date(2026, 9, 28)
        self.claims = {"status": "EMPTY", "sha256": "0" * 64, "issuers": {}}

    def _sample_receipt_cache(self, symbol="TEST", anchor_end="2026-07-31", guidance_doc="DOC-1", pub="2026-08-20"):
        import revenue_guidance
        rc = {
            "issuer": symbol, "checked_at": "2026-09-28T09:00:00Z", "status": "OK",
            "guidance_document_id": guidance_doc, "guidance_published_date": pub, "anchor_end": anchor_end,
            "coverage": "SEC_WIRE_IR",
            "channels": [
                {"kind": "SEC_SUBMISSIONS", "url": "https://data.sec.gov/submissions/CIK0000000000.json", "status": "OK", "checked_through": "2026-09-28", "complete": True},
                {"kind": "WIRE_PRESS_RELEASES", "url": "https://api.nasdaq.com/api/news/topic/press_release?q=symbol:" + symbol, "status": "OK", "checked_through": "2026-09-28", "complete": True},
                # The official IR channel (Astra W1 ruling, astra-ir-coverage): the company-guidance path requires
                # SEC_WIRE_IR coverage with the ISSUER_IR channel on the record's own IR host.
                {"kind": "ISSUER_IR", "url": "https://investor.test.com/feed/PressRelease.svc/GetPressReleaseList", "status": "OK", "checked_through": "2026-09-28", "complete": True},
            ],
            "later_documents": [],
        }
        rc["digest"] = revenue_guidance.compute_receipt_digest(rc)
        return {"schema": "revenue-guidance-release-checks-v1", "generated_at": "2026-09-28T09:00:00Z", "issuers": {symbol: [rc]}}

    def _sample_registry(self, q_end="2026-10-31", stated_point=32.5):
        return {
            "status": "OK",
            "sha256": "a" * 64,
            "issuers": {
                "TEST": {
                    "symbol": "TEST",
                    "company_name": "Test Co",
                    "status": "GUIDANCE",
                    "url_prefixes": ["https://investor.test.com/"],
                    "documents": [
                        {
                            "id": "DOC-1",
                            "issuer": "TEST",
                            "publisher": "Test Co",
                            "title": "Release",
                            "source_kind": "ISSUER_EARNINGS_RELEASE",
                            "url": "https://investor.test.com/q2.pdf",
                            "published_date": "2026-08-20",
                            "retrieved_at": "2026-08-20T12:00:00Z",
                            "sha256": "1" * 64,
                            "byte_size": 2048,
                            "lineage_id": "L1",
                        }
                    ],
                    "claims": [
                        {
                            "id": "CLAIM-1",
                            "document_id": "DOC-1",
                            "locator": "p.1",
                            "passage": f"Revenue outlook is {stated_point} billion",
                            "metric": "REVENUE",
                            "assertion_kind": "COMPANY_GUIDANCE",
                            "currency": "USD",
                            "unit_multiplier": 1000000000,
                            "stated_point": stated_point,
                            "original_representation": f"{stated_point} billion",
                            "scope": "COMPANY",
                            "accounting_basis": "GAAP",
                            "fiscal_label": "Q3 FY26",
                            "period_kind": "QUARTER",
                            "period_start": "2026-08-01",
                            "period_end": q_end,
                        }
                    ],
                    "reported_quarters": [
                        {"fiscal_label": "Q3 FY25", "start": "2025-08-01", "end": "2025-10-31", "revenue": 18.0e9, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                        {"fiscal_label": "Q4 FY25", "start": "2025-11-01", "end": "2026-01-31", "revenue": 22.0e9, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.2"},
                        {"fiscal_label": "Q1 FY26", "start": "2026-02-01", "end": "2026-04-30", "revenue": 26.0e9, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.3"},
                        {"fiscal_label": "Q2 FY26", "start": "2026-05-01", "end": "2026-07-31", "revenue": 30.0e9, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.4"},
                    ],
                    "forward_intervals": [
                        {"fiscal_label": "Q3 FY26", "start": "2026-08-01", "end": q_end, "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.5)"},
                        {"fiscal_label": "Q4 FY26", "start": "2026-11-01", "end": "2027-01-31", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.5)"},
                        {"fiscal_label": "Q1 FY27", "start": "2027-02-01", "end": "2027-04-30", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.5)"},
                        {"fiscal_label": "Q2 FY27", "start": "2027-05-01", "end": "2027-07-31", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.5)"},
                    ],
                    # The official IR channel (Astra W1 ruling, astra-ir-coverage): the company-guidance path
                    # requires SEC_WIRE_IR coverage, so the record carries its IR feed.
                    "release_channels": {
                        "ir": {"kind": "Q4_PRESS_RELEASES",
                               "url": "https://investor.test.com/feed/PressRelease.svc/GetPressReleaseList"},
                        "ir_guidance_release_title": "Test Co Reports Financial Results",
                    },
                }
            },
        }

    def test_build_v3_with_quarter_company_guidance(self):
        reg = self._sample_registry(stated_point=32.0)
        cache = self._sample_receipt_cache()
        approval = make_synthetic_approval(reg["sha256"], reg["issuers"])
        v3 = ofc.build_v3("TEST", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg, release_checks_cache=cache,
                          revenue_approval=approval)

        self.assertEqual(v3["version"], 3)
        self.assertEqual(v3["status"], "AVAILABLE")
        self.assertEqual(v3["revenue_status"], "AVAILABLE")
        self.assertEqual(v3["revenue_basis"], "COMPANY_GUIDANCE")
        self.assertEqual(v3["horizon_convention"], "FISCAL_2Q_4Q")

        # Baseline B = 18 + 22 + 26 + 30 = 96B
        self.assertAlmostEqual(v3["baseline_b"], 96.0e9)
        # Forward quarters: 4 quarters flat at 32B: [32B, 32B, 32B, 32B]
        # amount6 = 64B, amount12 = 128B
        self.assertAlmostEqual(v3["m6"]["amount"], 64.0e9)
        self.assertAlmostEqual(v3["m12"]["amount"], 128.0e9)
        # TTM6 = 26 + 30 + 32 + 32 = 120B. change6 = 120 / 96 - 1 = 0.25 (+25%)
        self.assertAlmostEqual(v3["m6"]["scenario"]["change"], 0.25, places=9)
        # TTM12 = 32 * 4 = 128B. change12 = 128 / 96 - 1 = 32 / 96 = 1/3 (+33.33%)
        self.assertAlmostEqual(v3["m12"]["scenario"]["change"], 32.0 / 96.0, places=9)

    def test_build_v3_retains_contracted_recognition_when_revenue_nondisclosed(self):
        reg = {"status": "OK", "sha256": "0" * 64, "issuers": {}}  # no revenue guidance
        rec_order = recognition(horizons={"m6": {"share_pct": 20, "derived": False}, "m12": {"share_pct": 50, "derived": False}})
        v3 = ofc.build_v3("FIX", None, rec_order, REPORT_DAY, self.cutoff, self.claims, revenue_registry=reg)

        self.assertEqual(v3["version"], 3)
        self.assertEqual(v3["status"], "AVAILABLE")
        self.assertEqual(v3["revenue_status"], "UNAVAILABLE")
        # Tile 2 shows contracted recognition
        self.assertEqual(v3["m6"]["status"], "AVAILABLE")
        self.assertEqual(v3["m6"]["basis"], "RECOGNITION")
        self.assertEqual(v3["m6"]["basis_label"], "已簽約預計認列")
        # Tile 3 has no revenue basis
        self.assertEqual(v3["m6"]["scenario"]["status"], "NO_BASIS")
        self.assertEqual(v3["m6"]["scenario"]["reason"], "NO_REVENUE_BASIS")

    def test_build_v3_uses_consensus_when_guidance_not_disclosed(self):
        # Issuer record has status NOT_DISCLOSED; the registry gate explicitly enables the consensus route here.
        reg = {
            "status": "OK", "sha256": "b" * 64, "consensus_enabled": True,
            "issuers": {
                "000660.KS": {
                    "symbol": "000660.KS",
                    "company_name": "SK hynix Inc.",
                    "status": "NOT_DISCLOSED",
                    "reason": "COMPANY_DOES_NOT_GUIDE",
                    "url_prefixes": ["https://www.skhynix.com/"],
                    "documents": [
                        {
                            "id": "DOC-1", "issuer": "000660.KS", "publisher": "SK hynix",
                            "source_kind": "OFFICIAL_FINANCIAL_STATEMENT", "url": "https://www.skhynix.com/q.pdf",
                            "published_date": "2026-08-01", "retrieved_at": "2026-08-01T12:00:00Z",
                            "sha256": "0" * 64, "byte_size": 1000, "lineage_id": "L1",
                        },
                        # The fiscal calendar the forward intervals are bound to (Astra r5 item 10: calendar links on
                        # every branch, including the NOT_DISCLOSED consensus path).
                        {
                            "id": "DOC-CAL", "issuer": "000660.KS", "publisher": "SK hynix",
                            "source_kind": "OFFICIAL_FISCAL_CALENDAR", "url": "https://www.skhynix.com/calendar.pdf",
                            "published_date": "2026-08-01", "retrieved_at": "2026-08-01T12:00:00Z",
                            "sha256": "1" * 64, "byte_size": 2000, "lineage_id": "L2",
                        },
                    ],
                    "claims": [],
                    "nondisclosure_evidence": {"document_ids": ["DOC-1"], "note": "No numeric revenue guidance"},
                    "reported_quarters": [
                        {"fiscal_label": "Q3 25", "start": "2025-07-01", "end": "2025-09-30", "revenue": 10e12, "currency": "KRW", "scope": "COMPANY", "accounting_basis": "K-IFRS", "document_id": "DOC-1", "locator": "p.1"},
                        {"fiscal_label": "Q4 25", "start": "2025-10-01", "end": "2025-12-31", "revenue": 11e12, "currency": "KRW", "scope": "COMPANY", "accounting_basis": "K-IFRS", "document_id": "DOC-1", "locator": "p.2"},
                        {"fiscal_label": "Q1 26", "start": "2026-01-01", "end": "2026-03-31", "revenue": 12e12, "currency": "KRW", "scope": "COMPANY", "accounting_basis": "K-IFRS", "document_id": "DOC-1", "locator": "p.3"},
                        {"fiscal_label": "Q2 26", "start": "2026-04-01", "end": "2026-06-30", "revenue": 13e12, "currency": "KRW", "scope": "COMPANY", "accounting_basis": "K-IFRS", "document_id": "DOC-1", "locator": "p.4"},
                    ],
                    "forward_intervals": [
                        {"fiscal_label": "Q3 26", "start": "2026-07-01", "end": "2026-09-30",
                         "calendar_document_id": "DOC-CAL", "calendar_locator": "p.5"},
                        {"fiscal_label": "Q4 26", "start": "2026-10-01", "end": "2026-12-31",
                         "calendar_document_id": "DOC-CAL", "calendar_locator": "p.5"},
                        {"fiscal_label": "Q1 27", "start": "2027-01-01", "end": "2027-03-31",
                         "calendar_document_id": "DOC-CAL", "calendar_locator": "p.5"},
                        {"fiscal_label": "Q2 27", "start": "2027-04-01", "end": "2027-06-30",
                         "calendar_document_id": "DOC-CAL", "calendar_locator": "p.5"},
                    ],
                }
            }
        }
        consensus_cache = {
            "000660.KS": {
                "symbol": "000660.KS",
                "captured_at": "2026-09-28T08:00:00Z",
                "currency": "KRW",
                "quarters": [
                    {"period": "0q", "end": "2026-09-30", "revenue": 15e12, "analysts": 25},
                    {"period": "+1q", "end": "2026-12-31", "revenue": 16e12, "analysts": 24},
                ],
            }
        }
        v3 = ofc.build_v3("000660.KS", None, None, self.report_day, self.cutoff, self.claims,
                          revenue_registry=reg, consensus_cache=consensus_cache,
                          revenue_approval=make_synthetic_approval(reg["sha256"], reg["issuers"]))

        self.assertEqual(v3["status"], "AVAILABLE")
        self.assertEqual(v3["revenue_basis"], "CONSENSUS")
        self.assertEqual(v3["m6"]["basis_label"], "非公司揭露、非訂單：分析師季度營收共識＋模型")
        # amount6 = 15e12 + 16e12 = 31e12
        self.assertAlmostEqual(v3["m6"]["amount"], 31e12)
        # amount12 = 15 + 16 + 16 + 16 = 63e12
        self.assertAlmostEqual(v3["m12"]["amount"], 63e12)


class OrdersV3ContainmentTests(unittest.TestCase):
    """A4 (Astra acceptance r7): the sealed envelope is a projected, bounded copy - unknown record fields never
    reach the outer object, and a revenue EVIDENCE_LIMIT produces a small, coherent scoped state that PRESERVES
    the independently validated sibling order recognition (NVDA m12 USD 1,248,000,000), so
    lazy_bottleneck_v3_body keeps all 20 Top20 entries."""

    def setUp(self):
        import revenue_guidance
        self.revenue_guidance = revenue_guidance
        self.cutoff = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
        self.report_day = date(2026, 9, 28)
        self.claims = {"status": "EMPTY", "sha256": "0" * 64, "issuers": {}}

    def _receipt_cache(self, symbol="TEST"):
        rc = {
            "issuer": symbol, "checked_at": "2026-09-28T09:00:00Z", "status": "OK",
            "guidance_document_id": "DOC-1", "guidance_published_date": "2026-08-20", "anchor_end": "2026-07-31",
            "coverage": "SEC_WIRE_IR",
            "channels": [
                {"kind": "SEC_SUBMISSIONS", "url": "https://data.sec.gov/submissions/CIK0000000000.json", "status": "OK", "checked_through": "2026-09-28", "complete": True},
                {"kind": "WIRE_PRESS_RELEASES", "url": "https://api.nasdaq.com/api/news/topic/press_release?q=symbol:" + symbol, "status": "OK", "checked_through": "2026-09-28", "complete": True},
                {"kind": "ISSUER_IR", "url": "https://investor.test.com/feed/PressRelease.svc/GetPressReleaseList", "status": "OK", "checked_through": "2026-09-28", "complete": True},
            ],
            "later_documents": [],
        }
        rc["digest"] = self.revenue_guidance.compute_receipt_digest(rc)
        return {"schema": "revenue-guidance-release-checks-v1", "generated_at": "2026-09-28T09:00:00Z", "issuers": {symbol: [rc]}}

    def _registry(self, symbol="TEST", claim_id="CLAIM-1"):
        return {
            "status": "OK", "sha256": "a" * 64,
            "issuers": {
                symbol: {
                    "symbol": symbol, "company_name": "Test Co", "status": "GUIDANCE",
                    "url_prefixes": ["https://investor.test.com/"],
                    "documents": [{
                        "id": "DOC-1", "issuer": symbol, "publisher": "Test Co", "title": "Release",
                        "source_kind": "ISSUER_EARNINGS_RELEASE", "url": "https://investor.test.com/q2.pdf",
                        "published_date": "2026-08-20", "retrieved_at": "2026-08-20T12:00:00Z",
                        "sha256": "1" * 64, "byte_size": 2048, "lineage_id": "L1",
                    }],
                    "claims": [{
                        "id": claim_id, "document_id": "DOC-1", "locator": "p.1",
                        "passage": "Revenue outlook is 32.5 billion", "metric": "REVENUE",
                        "assertion_kind": "COMPANY_GUIDANCE", "currency": "USD", "unit_multiplier": 1000000000,
                        "stated_point": 32.5, "original_representation": "32.5 billion", "scope": "COMPANY",
                        "accounting_basis": "GAAP", "fiscal_label": "Q3 FY26", "period_kind": "QUARTER",
                        "period_start": "2026-08-01", "period_end": "2026-10-31",
                    }],
                    "reported_quarters": [
                        {"fiscal_label": "Q3 FY25", "start": "2025-08-01", "end": "2025-10-31", "revenue": 18.0e9, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                        {"fiscal_label": "Q4 FY25", "start": "2025-11-01", "end": "2026-01-31", "revenue": 22.0e9, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.2"},
                        {"fiscal_label": "Q1 FY26", "start": "2026-02-01", "end": "2026-04-30", "revenue": 26.0e9, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.3"},
                        {"fiscal_label": "Q2 FY26", "start": "2026-05-01", "end": "2026-07-31", "revenue": 30.0e9, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.4"},
                    ],
                    "forward_intervals": [
                        {"fiscal_label": "Q3 FY26", "start": "2026-08-01", "end": "2026-10-31", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.5)"},
                        {"fiscal_label": "Q4 FY26", "start": "2026-11-01", "end": "2027-01-31", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.5)"},
                        {"fiscal_label": "Q1 FY27", "start": "2027-02-01", "end": "2027-04-30", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.5)"},
                        {"fiscal_label": "Q2 FY27", "start": "2027-05-01", "end": "2027-07-31", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.5)"},
                    ],
                    "release_channels": {
                        "ir": {"kind": "Q4_PRESS_RELEASES", "url": "https://investor.test.com/feed/PressRelease.svc/GetPressReleaseList"},
                        "ir_guidance_release_title": "Test Co Reports Financial Results",
                    },
                }
            },
        }

    def test_unknown_actual_fields_do_not_reach_the_outer_object(self):
        # A forged, oversized unknown field on a used actual stays out of every outer duplicate: the top-level
        # reported_quarters and the evidence copy are the projected bounded projection (allowed keys only).
        reg = self._registry()
        reg["issuers"]["TEST"]["reported_quarters"][0]["forged_multimegabyte"] = "x" * 200_000
        approval = make_synthetic_approval(reg["sha256"], reg["issuers"])
        v3 = ofc.build_v3("TEST", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                         release_checks_cache=self._receipt_cache(), revenue_approval=approval)
        blob = json.dumps(v3)
        self.assertNotIn("x" * 1000, blob)
        allowed = {"fiscal_label", "start", "end", "revenue", "currency", "scope", "accounting_basis",
                   "document_id", "locator", "derivation"}
        for actuals in (v3["reported_quarters"], v3["evidence"]["reported_quarters"]):
            for q in actuals:
                self.assertTrue(set(q) <= allowed, q)

    def test_evidence_limit_preserves_sister_recognition(self):
        # The scoped EVIDENCE_LIMIT state: the oversized/canonicalization-failed revenue originals are cleared to a
        # small coherent envelope, while the independently validated m12 recognition (3.2B x 39% = 1.248B, Astra's
        # executed NVDA case) stays AVAILABLE beside it.
        import revenue_guidance
        reg = self._registry(claim_id="CLAIM-OVER")
        approval = make_synthetic_approval(reg["sha256"], reg["issuers"])
        saved_canonical = revenue_guidance.canonical_json

        def flaky_canonical_json(obj):
            # The canonicalization-failure signal (the same branch the >100KB byte check raises): a claim marked
            # CLAIM-OVER simulates the oversized evidence the bounds check refuses to carry sealed.
            if isinstance(obj, dict) and any(isinstance(c, dict) and c.get("id") == "CLAIM-OVER" for c in obj.get("claims", [])):
                raise ValueError("simulated canonicalization failure (oversized evidence)")
            return saved_canonical(obj)

        revenue_guidance.canonical_json = flaky_canonical_json
        try:
            v3 = ofc.build_v3("TEST", None, recognition(horizons={"m6": None, "m12": {"share_pct": 39, "derived": False}}),
                              self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                              release_checks_cache=self._receipt_cache(), revenue_approval=approval)
        finally:
            revenue_guidance.canonical_json = saved_canonical

        self.assertEqual(v3["revenue_status"], "UNAVAILABLE")
        self.assertEqual(v3["revenue_reason"], "EVIDENCE_LIMIT")
        self.assertEqual(v3["status"], "AVAILABLE")  # the recognition keeps the entry alive
        self.assertEqual(v3["m12"]["status"], "AVAILABLE")
        self.assertEqual(v3["m12"]["basis"], "RECOGNITION")
        self.assertAlmostEqual(v3["m12"]["amount"], 1.248e9)  # 3.2B x 39%
        self.assertEqual(v3["m6"]["status"], "UNAVAILABLE")
        self.assertEqual(v3["m6"]["reason"], "EVIDENCE_LIMIT")
        # The scoped envelope is small and coherent: the revenue originals are cleared, the bounded v2 order view
        # and the approval nulls stay sealed so the Worker re-derives exactly this state (never INVALID).
        self.assertEqual(v3["reported_quarters"], [])
        self.assertEqual(v3["evidence"]["documents"], [])
        self.assertEqual(v3["evidence"]["claims"], [])
        self.assertEqual(v3["evidence"]["reported_quarters"], [])
        self.assertEqual(v3["evidence"]["forward_intervals"], [])
        self.assertIsNone(v3["evidence"]["consensus"])
        self.assertIsNone(v3["evidence"]["latest_release_check"])
        self.assertIsNone(v3["evidence"]["fy_reconciliation"])
        self.assertIsNone(v3["evidence"]["approval_sha256"])
        self.assertIsNone(v3["evidence"]["approval_decisions"])
        self.assertTrue(v3["evidence"].get("order_evidence"))  # the preserved recognition re-derives from it

    def test_lazy_bottleneck_keeps_all_20_entries_when_one_is_limited(self):
        # Astra's executed A4 case through the real caller: one Top20 issuer's revenue evidence limits while its
        # m12 recognition survives - all 20 entries stay sealed, none is wiped from the document.
        import json as _json
        import tempfile
        from pathlib import Path
        import publish_sealed_snapshot as publisher

        reg = self._registry(symbol="S5", claim_id="CLAIM-OVER")
        approval = make_synthetic_approval(reg["sha256"], reg["issuers"])
        saved = {
            "load_registry": publisher.revenue_guidance.load_registry,
            "load_approval": publisher.revenue_guidance.load_approval,
            "select_for_cutoff": publisher.revenue_consensus_quarterly.select_for_cutoff,
            "load_release_checks_cache": publisher.revenue_guidance.load_release_checks_cache,
            "load_order_scenarios": publisher.company_deep_report.load_order_scenarios,
            "load_reports": publisher.company_deep_report.load_reports,
            "canonical_json": self.revenue_guidance.canonical_json,
        }
        publisher.revenue_guidance.load_registry = lambda *a, **k: reg
        publisher.revenue_guidance.load_approval = lambda *a, **k: approval
        publisher.revenue_consensus_quarterly.select_for_cutoff = lambda *a, **k: {}
        publisher.revenue_guidance.load_release_checks_cache = lambda *a, **k: {}
        publisher.company_deep_report.load_order_scenarios = lambda *a, **k: {
            "S5": recognition(horizons={"m6": None, "m12": {"share_pct": 39, "derived": False}})}
        publisher.company_deep_report.load_reports = lambda *a, **k: {}

        def flaky_canonical_json(obj):
            if isinstance(obj, dict) and any(isinstance(c, dict) and c.get("id") == "CLAIM-OVER" for c in obj.get("claims", [])):
                raise ValueError("simulated canonicalization failure (oversized evidence)")
            return saved["canonical_json"](obj)

        self.revenue_guidance.canonical_json = flaky_canonical_json

        registry_dir = tempfile.TemporaryDirectory()
        registry_path = Path(registry_dir.name) / "order-claims-v2.json"
        registry_path.write_text(_json.dumps({"schema": "order-claims-v2", "issuers": {}, "documents": [], "claims": []}), encoding="utf-8")
        saved_registry_path = publisher.order_claims.REGISTRY_PATH
        publisher.order_claims.REGISTRY_PATH = registry_path

        now = datetime.now(timezone.utc).replace(microsecond=0)
        entry = {"rank": 1, "symbol": "S1", "name": "S One", "layer": "optics", "archetype": "EXPLOSION", "score": 60.9,
                 "role": "CW laser", "role_source": {"url": "https://x.com/a/status/1", "date": "2026-09-03"},
                 "score_parts": {"layer_heat": 5, "capture": 4, "lead": 14, "confirmation": 15, "size": 10, "penalty": 0},
                 "fundamentals": None, "market": {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/S1",
                                                  "asof": "2026-09-25", "ret_6m": 0.9, "ret_1y": 0.5, "cagr_2y": 0.6,
                                                  "currency": "USD", "price": 1.0},
                 "market_cap_usd": 1.05e9, "serenity": None, "leopold": None}
        doc = {"schema": "v213-bottleneck-top20-v3", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "leads": {"serenity": {"url": None, "latest_post_at": None}, "leopold": {"filing": None}},
               "top": [{**entry, "rank": index + 1, "symbol": f"S{index + 1}"} for index in range(20)],
               "industries": []}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "v3.json"
                path.write_text(_json.dumps(doc), encoding="utf-8")
                body = publisher.lazy_bottleneck_v3_body(path, now)
        finally:
            publisher.revenue_guidance.load_registry = saved["load_registry"]
            publisher.revenue_guidance.load_approval = saved["load_approval"]
            publisher.revenue_consensus_quarterly.select_for_cutoff = saved["select_for_cutoff"]
            publisher.revenue_guidance.load_release_checks_cache = saved["load_release_checks_cache"]
            publisher.company_deep_report.load_order_scenarios = saved["load_order_scenarios"]
            publisher.company_deep_report.load_reports = saved["load_reports"]
            self.revenue_guidance.canonical_json = saved["canonical_json"]
            publisher.order_claims.REGISTRY_PATH = saved_registry_path
            registry_dir.cleanup()

        self.assertTrue(body, "the 20-entry document must seal even with one scoped EVIDENCE_LIMIT issuer")
        sealed = _json.loads(body[publisher.BOTTLENECK_V3_KEY])
        self.assertEqual(len(sealed["top"]), 20)  # every entry kept
        by_symbol = {row["symbol"]: row for row in sealed["top"]}
        s5 = by_symbol["S5"]["outlook"]["order_forecast_v3"]
        self.assertEqual(s5["revenue_status"], "UNAVAILABLE")
        self.assertEqual(s5["revenue_reason"], "EVIDENCE_LIMIT")
        self.assertEqual(s5["m12"]["status"], "AVAILABLE")
        self.assertEqual(s5["m12"]["basis"], "RECOGNITION")
        self.assertAlmostEqual(s5["m12"]["amount"], 1.248e9)
        # The unreviewed-record entries keep their own (independent) state beside the limited one.
        for sym in ("S1", "S20"):
            self.assertIsNotNone(by_symbol[sym]["outlook"]["order_forecast_v3"])
            self.assertEqual(by_symbol[sym]["outlook"]["order_forecast_v3"]["revenue_reason"], "INPUTS_MISSING")


class OrdersV3ProbeFixtureTests(unittest.TestCase):
    """Astra r7 acceptance A1/A2/A4: the producer-to-reader probe fixture is reproducible from its frozen real inputs
    and carries the required producer states (the Worker test parses the same outlooks)."""

    def test_probe_fixture_is_current_and_states_hold(self):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        done = subprocess.run([sys.executable, str(root / "tests" / "fixtures" / "make_orders_v3_probes.py"), "--check"], cwd=root)
        self.assertEqual(done.returncode, 0, "run tests/fixtures/make_orders_v3_probes.py")
        cases = json.loads((root / "tests" / "fixtures" / "v213-orders-v3-probes.json").read_text(encoding="utf-8"))["cases"]
        states = {name: (c["outlook"]["order_forecast_v3"]["revenue_status"], c["outlook"]["order_forecast_v3"]["revenue_reason"],
                         c["outlook"]["order_forecast_v3"].get("revenue_diagnostic"), c["outlook"]["order_forecast_v3"]["m12"].get("basis"))
                  for name, c in cases.items()}
        self.assertEqual(states["control"], ("AVAILABLE", None, None, "COMPANY_GUIDANCE"))
        self.assertEqual(states["unreviewed_extra_field"], ("UNAVAILABLE", "INVALID", "UNREVIEWED_INPUTS", "RECOGNITION"))
        self.assertEqual(states["unreviewed_without_orders"][:3], ("UNAVAILABLE", "INVALID", "UNREVIEWED_INPUTS"))
        self.assertEqual(states["evidence_limit_fiscal_label"], ("UNAVAILABLE", "EVIDENCE_LIMIT", None, "RECOGNITION"))
        self.assertIsNotNone(cases["evidence_limit_fiscal_label"]["outlook"]["order_forecast_v3"]["contracted_recognition"])
        for name, c in cases.items():
            if name.startswith("title_"):
                self.assertEqual(c["receipt_status"], "REVIEW_REQUIRED" if c["material"] else "OK", c["title"])
