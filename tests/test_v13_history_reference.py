"""V13 item 1: Python reference for the Worker-only HISTORY_YOY_V1 revenue estimate.

The production model lives in cloud/src/v213/revenue-history-model.ts and is not sealed, so this independent
implementation of the same formula guards drift: both languages must reproduce the shared vectors in
cloud/test/fixtures/v13-history-vectors.json (the TypeScript side is cloud/test/v213-revenue-history-model.test.ts), and the
reference must accept the calendar of every issuer in config/revenue-guidance-v1.json.

Regenerate the vectors after a deliberate formula change with:
    python -B -X utf8 tests/test_v13_history_reference.py --write
"""
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "cloud" / "test" / "fixtures" / "v13-history-vectors.json"
REGISTRY = ROOT / "config" / "revenue-guidance-v1.json"

MAX_ANCHOR_DAYS = 200
CALENDAR_TOLERANCE_DAYS = 14
YOY_ALIGN_DAYS = 10
GROWTH_FLOOR = -0.5
GROWTH_CAP = 1.0
YOY_FAULT = 3.0
NEWER_QUARTER_DAYS = 45


def _day(value):
    return date.fromisoformat(value)


def _days(a, b):
    return (_day(b) - _day(a)).days


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf")


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    return ordered[(n - 1) // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def evaluate(actuals, intervals, currency, fund, report_day):
    """Return {"ok": True, ...} or {"ok": False, "reason": ...}; mirrors evaluateHistory()."""
    if len(actuals) < 4 or len(intervals) != 4:
        return {"ok": False, "reason": "NO_INPUTS"}
    a = actuals[-4:]
    f = intervals
    if not isinstance(currency, str) or not currency:
        return {"ok": False, "reason": "BAD_ACTUALS"}
    for q in a:
        if not _num(q["revenue"]) or not q["revenue"] > 0 or q["currency"] != currency or q["start"] > q["end"]:
            return {"ok": False, "reason": "BAD_ACTUALS"}
    for i in range(1, 4):
        if _days(a[i - 1]["end"], a[i]["start"]) != 1 or _days(f[i - 1]["end"], f[i]["start"]) != 1:
            return {"ok": False, "reason": "CALENDAR_UNALIGNED"}
    anchor = a[3]["end"]
    if _days(anchor, f[0]["start"]) != 1:
        return {"ok": False, "reason": "CALENDAR_UNALIGNED"}
    for k in range(4):
        if abs(_days(a[k]["end"], f[k]["end"]) - 364) > CALENDAR_TOLERANCE_DAYS:
            return {"ok": False, "reason": "CALENDAR_UNALIGNED"}
    age = _days(anchor, report_day)
    if age < 0 or age > MAX_ANCHOR_DAYS:
        return {"ok": False, "reason": "ANCHOR_STALE"}
    if fund and fund.get("quarter_end") and _days(anchor, fund["quarter_end"]) >= NEWER_QUARTER_DAYS:
        return {"ok": False, "reason": "NEWER_QUARTER_REPORTED"}

    rates = []
    if fund and fund.get("quarter_end") and abs(_days(fund["quarter_end"], anchor)) <= YOY_ALIGN_DAYS:
        for key in ("revenue_yoy", "revenue_yoy_prev"):
            if _num(fund.get(key)):
                rates.append(fund[key])
    tier, g, g_raw, capped = "B", None, None, None
    if rates:
        g_raw = _median(rates)
        if abs(g_raw) <= YOY_FAULT:
            tier = "A"
            g = min(GROWTH_CAP, max(GROWTH_FLOOR, g_raw))
            capped = "UPPER" if g_raw > GROWTH_CAP else "LOWER" if g_raw < GROWTH_FLOOR else None
    amounts = [(a[k]["revenue"] * (1 + g)) if tier == "A" else a[3]["revenue"] for k in range(4)]
    b = a[0]["revenue"] + a[1]["revenue"] + a[2]["revenue"] + a[3]["revenue"]
    m6 = amounts[0] + amounts[1]
    m12 = amounts[0] + amounts[1] + amounts[2] + amounts[3]
    ttm6 = a[2]["revenue"] + a[3]["revenue"] + m6
    ttm12 = m12
    return {"ok": True, "tier": tier, "g": g, "g_raw": g_raw, "capped": capped, "B": b, "m6": m6, "m12": m12,
            "ttm6": ttm6, "ttm12": ttm12, "change6": ttm6 / b - 1, "change12": ttm12 / b - 1}


def _quarters(ends, revenues, currency="USD"):
    out, start = [], None
    for end, revenue in zip(ends, revenues):
        s = start or (_day(end) - timedelta(days=90)).isoformat()
        out.append({"start": s, "end": end, "revenue": revenue, "currency": currency})
        start = (_day(end) + timedelta(days=1)).isoformat()
    return out


def _intervals(ends, first_start):
    out, start = [], first_start
    for end in ends:
        out.append({"start": start, "end": end})
        start = (_day(end) + timedelta(days=1)).isoformat()
    return out


def _case(case_id, actuals, intervals, fund, report_day, currency="USD"):
    return {"id": case_id, "inputs": {"actuals": actuals, "intervals": intervals, "currency": currency}, "fund": fund,
            "report_day": report_day, "expected": evaluate(actuals, intervals, currency, fund, report_day)}


def build_vectors():
    base_a = _quarters(["2025-09-27", "2025-12-27", "2026-03-28", "2026-06-27"], [100.0, 110.0, 120.0, 130.0])
    # The first actual starts 2025-06-29 so the four quarters are contiguous.
    base_a[0]["start"] = "2025-06-29"
    for i in range(1, 4):
        base_a[i]["start"] = (_day(base_a[i - 1]["end"]) + timedelta(days=1)).isoformat()
    base_f = _intervals(["2026-09-26", "2026-12-26", "2027-03-27", "2027-06-26"], "2026-06-28")
    fund = {"quarter_end": "2026-06-27", "revenue_yoy": 0.30, "revenue_yoy_prev": 0.20}
    day = "2026-07-20"
    cases = [
        _case("tier_a_two_rates_mean", base_a, base_f, fund, day),
        _case("tier_a_latest_rate_only", base_a, base_f, {**fund, "revenue_yoy_prev": None}, day),
        _case("tier_a_prev_rate_only", base_a, base_f, {**fund, "revenue_yoy": None}, day),
        _case("tier_a_negative_growth", base_a, base_f, {**fund, "revenue_yoy": -0.10, "revenue_yoy_prev": -0.20}, day),
        _case("tier_a_zero_growth", base_a, base_f, {**fund, "revenue_yoy": 0.0, "revenue_yoy_prev": 0.0}, day),
        _case("cap_upper_100pct", base_a, base_f, {**fund, "revenue_yoy": 1.8, "revenue_yoy_prev": 1.4}, day),
        _case("cap_lower_minus_50pct", base_a, base_f, {**fund, "revenue_yoy": -0.8, "revenue_yoy_prev": -0.7}, day),
        _case("cap_boundary_exactly_100pct", base_a, base_f, {**fund, "revenue_yoy": 1.0, "revenue_yoy_prev": 1.0}, day),
        _case("extreme_over_300pct_is_tier_b", base_a, base_f, {**fund, "revenue_yoy": 4.2, "revenue_yoy_prev": 3.8}, day),
        _case("exactly_300pct_still_tier_a_capped", base_a, base_f, {**fund, "revenue_yoy": 3.0, "revenue_yoy_prev": 3.0}, day),
        _case("tier_b_no_fundamentals", base_a, base_f, None, day),
        _case("tier_b_null_rates", base_a, base_f, {**fund, "revenue_yoy": None, "revenue_yoy_prev": None}, day),
        _case("tier_b_fund_quarter_misaligned", base_a, base_f, {**fund, "quarter_end": "2026-03-28"}, day),
        _case("fund_quarter_within_10_days_is_aligned", base_a, base_f, {**fund, "quarter_end": "2026-07-05"}, day),
        _case("fund_quarter_11_days_off_is_tier_b", base_a, base_f, {**fund, "quarter_end": "2026-07-08"}, day),
        _case("fund_quarter_44_days_later_is_tier_b", base_a, base_f, {**fund, "quarter_end": "2026-08-10"}, day),
        _case("newer_reported_quarter_refused", base_a, base_f, {**fund, "quarter_end": "2026-09-26"}, "2026-10-17"),
        _case("fund_quarter_45_days_later_refused", base_a, base_f, {**fund, "quarter_end": "2026-08-11"}, day),
        _case("anchor_exactly_200_days_ok", base_a, base_f, fund, "2027-01-13"),
        _case("anchor_201_days_refused", base_a, base_f, fund, "2027-01-14"),
        _case("report_day_before_anchor_refused", base_a, base_f, fund, "2026-06-01"),
        _case("calendar_forward_quarter_shifted_refused", base_a,
              _intervals(["2026-09-26", "2026-12-26", "2027-04-30", "2027-07-31"], "2026-06-28"), fund, day),
        _case("calendar_gap_after_anchor_refused", base_a,
              _intervals(["2026-09-26", "2026-12-26", "2027-03-27", "2027-06-26"], "2026-07-05"), fund, day),
        _case("calendar_within_14_days_tolerance_ok", base_a,
              _intervals(["2026-10-05", "2027-01-04", "2027-04-05", "2027-07-05"], "2026-06-28"), fund, day),
        _case("currency_mix_refused", [base_a[0], base_a[1], base_a[2], {**base_a[3], "currency": "EUR"}], base_f, fund, day),
        _case("nonpositive_revenue_refused", [base_a[0], {**base_a[1], "revenue": 0.0}, base_a[2], base_a[3]], base_f, fund, day),
        _case("three_actuals_refused", base_a[1:], base_f, fund, day),
        _case("three_intervals_refused", base_a, base_f[:3], fund, day),
        _case("krw_large_amounts", [{**q, "revenue": q["revenue"] * 1e12, "currency": "KRW"} for q in base_a], base_f, fund, day, "KRW"),
    ]
    return {"schema": "v13-history-vectors-v1", "method": "HISTORY_YOY_V1", "cases": cases}


class HistoryReferenceTest(unittest.TestCase):
    maxDiff = None

    def vectors(self):
        return json.loads(VECTORS.read_text(encoding="utf-8"))

    def test_vectors_are_the_reference_output(self):
        self.assertEqual(self.vectors(), json.loads(json.dumps(build_vectors())))

    def test_hand_calc_tier_a(self):
        case = next(c for c in self.vectors()["cases"] if c["id"] == "tier_a_two_rates_mean")
        out = case["expected"]
        self.assertTrue(out["ok"])
        self.assertEqual(out["tier"], "A")
        self.assertAlmostEqual(out["g"], 0.25)
        # forward quarters: 100/110/120/130 times 1.25
        self.assertAlmostEqual(out["m6"], (100 + 110) * 1.25)
        self.assertAlmostEqual(out["m12"], 460 * 1.25)
        self.assertAlmostEqual(out["B"], 460)
        self.assertAlmostEqual(out["ttm6"], 120 + 130 + 262.5)
        # a tier-A one-year change equals the growth rate itself
        self.assertAlmostEqual(out["change12"], 0.25)

    def test_one_year_change_equals_g_in_every_tier_a_vector(self):
        seen = 0
        for case in self.vectors()["cases"]:
            out = case["expected"]
            if out["ok"] and out["tier"] == "A":
                seen += 1
                self.assertAlmostEqual(out["change12"], out["g"], places=12, msg=case["id"])
                self.assertGreaterEqual(out["g"], GROWTH_FLOOR)
                self.assertLessEqual(out["g"], GROWTH_CAP)
        self.assertGreaterEqual(seen, 7)

    def test_tier_b_is_flat_run_rate(self):
        case = next(c for c in self.vectors()["cases"] if c["id"] == "tier_b_no_fundamentals")
        out = case["expected"]
        self.assertEqual(out["tier"], "B")
        self.assertAlmostEqual(out["m12"], 130 * 4)
        self.assertAlmostEqual(out["m6"], 260)
        self.assertIsNone(out["g"])

    def test_extreme_yoy_over_300pct_falls_to_tier_b(self):
        out = {c["id"]: c["expected"] for c in self.vectors()["cases"]}
        self.assertEqual(out["extreme_over_300pct_is_tier_b"]["tier"], "B")
        self.assertEqual(out["exactly_300pct_still_tier_a_capped"]["capped"], "UPPER")

    def test_refusals(self):
        out = {c["id"]: c["expected"] for c in self.vectors()["cases"]}
        self.assertEqual(out["anchor_201_days_refused"], {"ok": False, "reason": "ANCHOR_STALE"})
        self.assertTrue(out["anchor_exactly_200_days_ok"]["ok"])
        self.assertEqual(out["calendar_forward_quarter_shifted_refused"]["reason"], "CALENDAR_UNALIGNED")
        self.assertEqual(out["currency_mix_refused"]["reason"], "BAD_ACTUALS")
        self.assertEqual(out["nonpositive_revenue_refused"]["reason"], "BAD_ACTUALS")
        self.assertEqual(out["three_actuals_refused"]["reason"], "NO_INPUTS")
        self.assertEqual(out["newer_reported_quarter_refused"], {"ok": False, "reason": "NEWER_QUARTER_REPORTED"})
        self.assertEqual(out["fund_quarter_45_days_later_refused"]["reason"], "NEWER_QUARTER_REPORTED")
        self.assertEqual(out["fund_quarter_44_days_later_is_tier_b"]["tier"], "B")

    def test_registry_calendar_is_accepted_for_every_issuer(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.assertEqual(len(registry["issuers"]), 21)  # lane V14 added TSM
        fund_template = {"revenue_yoy": 0.25, "revenue_yoy_prev": 0.15}
        for record in registry["issuers"]:
            actuals = record["reported_quarters"]
            intervals = record["forward_intervals"]
            anchor = actuals[-1]["end"]
            fund = {**fund_template, "quarter_end": anchor}
            report_day = (_day(anchor) + timedelta(days=30)).isoformat()
            out = evaluate(actuals, intervals, actuals[0]["currency"], fund, report_day)
            self.assertTrue(out["ok"], f"{record['symbol']}: {out}")
            self.assertEqual(out["tier"], "A", record["symbol"])
            self.assertAlmostEqual(out["change12"], 0.20, places=12, msg=record["symbol"])
            self.assertAlmostEqual(out["B"], sum(q["revenue"] for q in actuals[-4:]), places=3)


if __name__ == "__main__":
    if "--write" in sys.argv:
        VECTORS.write_text(json.dumps(build_vectors(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {VECTORS}")
    else:
        unittest.main()
