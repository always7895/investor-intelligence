"""V33b: TREND_YOY_V1, the lowest-priority revenue estimate of a Top20 card (scripts/revenue_trend.py).

Covers the pure model (6-month and 1-year figures, the price-scenario arithmetic, the growth clamp, the flat fallback and
every refusal), the collectors that keep the input beside the fundamentals, and the sealer that carries the optional
`revenue_trend` entry field. The Worker side (validation, priority, rendering) is cloud/test/v213-revenue-trend.test.ts;
the shared vectors are cloud/test/fixtures/revenue-trend-vectors.json (regenerate with `python tests/test_revenue_trend.py --write`)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import bottleneck_top20_v3 as engine  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
import revenue_trend as trend  # noqa: E402
from tests.test_bottleneck_top20_v3 import FACTS, fixture_names_for  # noqa: E402

VECTORS = ROOT / "cloud" / "test" / "fixtures" / "revenue-trend-vectors.json"
REPORT_DAY = date(2026, 11, 3)
M = 1e6
QUARTERS = [{"end": "2025-09-30", "revenue": 100.0 * M}, {"end": "2025-12-31", "revenue": 110.0 * M},
            {"end": "2026-03-31", "revenue": 120.0 * M}, {"end": "2026-06-30", "revenue": 150.0 * M}]


def fund(**over):
    base = {"source": "Yahoo Finance quarterly income statement (unofficial)", "source_url": "https://finance.yahoo.com/quote/POET/financials",
            "quarter_end": "2026-06-30", "revenue_unit": "USD", "revenue_yoy": 0.5, "revenue_yoy_prev": 0.3,
            "revenue_quarters": [dict(q) for q in QUARTERS]}
    base.update(over)
    return base


def vector_cases():
    return {
        "growth": fund(),
        "upper_clamp": fund(revenue_yoy=2.0, revenue_yoy_prev=1.5),
        "lower_clamp": fund(revenue_yoy=-0.8, revenue_yoy_prev=-0.7),
        "flat_out_of_range": fund(revenue_yoy=5.0, revenue_yoy_prev=4.0),
        "flat_no_rate": fund(revenue_yoy=None, revenue_yoy_prev=None),
        "latest_rate_only": fund(revenue_yoy_prev=None),
    }


class TrendModelTests(unittest.TestCase):
    def test_six_and_twelve_month_figures_and_price_scenario_from_fixture_quarters(self):
        t = trend.build(fund(), REPORT_DAY)
        self.assertEqual((t["tier"], t["capped"], t["tier_b_reason"]), ("A", None, None))
        self.assertAlmostEqual(t["growth_raw"], 0.4)  # the mean of 0.5 and 0.3
        self.assertAlmostEqual(t["growth"], 0.4)
        self.assertAlmostEqual(t["baseline"], 480.0 * M)
        self.assertAlmostEqual(t["m6"]["amount"], (100 + 110) * 1.4 * M)   # the two year-ago quarters x (1 + g)
        self.assertAlmostEqual(t["m12"]["amount"], 480 * 1.4 * M)
        # The existing arithmetic (revenue_guidance.compute_v3_arithmetic): TTM6 = q3 + q4 + f1 + f2, TTM12 = f1..f4.
        self.assertAlmostEqual(t["m6"]["change"], (120 + 150 + 294) / 480 - 1)
        self.assertAlmostEqual(t["m12"]["change"], 672 / 480 - 1)
        self.assertEqual((t["m6"]["start"], t["m6"]["end"], t["m12"]["start"], t["m12"]["end"]),
                         ("2026-07-01", "2026-12-31", "2026-07-01", "2027-06-30"))
        self.assertEqual((t["schema"], t["method"], t["currency"], t["anchor"]), ("revenue-trend-v1", "TREND_YOY_V1", "USD", "2026-06-30"))
        self.assertEqual(t["rates"], [{"label": "latest", "value": 0.5}, {"label": "previous", "value": 0.3}])

    def test_the_price_scenario_matches_compute_v3_arithmetic(self):
        import revenue_guidance
        t = trend.build(fund(), REPORT_DAY)
        g = t["growth"]
        arith = revenue_guidance.compute_v3_arithmetic([q["revenue"] for q in t["quarters"]], [q["revenue"] * (1 + g) for q in t["quarters"]])
        self.assertAlmostEqual(arith["change6"], t["m6"]["change"])
        self.assertAlmostEqual(arith["change12"], t["m12"]["change"])
        self.assertAlmostEqual(arith["amount6"], t["m6"]["amount"])
        self.assertAlmostEqual(arith["amount12"], t["m12"]["amount"])

    def test_growth_is_clamped_and_flagged(self):
        up = trend.build(fund(revenue_yoy=2.0, revenue_yoy_prev=1.5), REPORT_DAY)
        self.assertEqual((up["capped"], up["growth"], up["tier"]), ("UPPER", 1.0, "A"))
        self.assertAlmostEqual(up["growth_raw"], 1.75)
        self.assertAlmostEqual(up["m12"]["amount"], 480 * 2.0 * M)
        down = trend.build(fund(revenue_yoy=-0.8, revenue_yoy_prev=-0.7), REPORT_DAY)
        self.assertEqual((down["capped"], down["growth"]), ("LOWER", -0.5))
        self.assertAlmostEqual(down["m12"]["amount"], 480 * 0.5 * M)
        self.assertAlmostEqual(down["m12"]["change"], -0.5)

    def test_a_single_rate_is_used_as_it_is_and_no_rate_or_an_extreme_rate_holds_the_latest_quarter_flat(self):
        only = trend.build(fund(revenue_yoy_prev=None), REPORT_DAY)
        self.assertAlmostEqual(only["growth"], 0.5)
        self.assertEqual(only["rates"], [{"label": "latest", "value": 0.5}])
        for case, reason in ((fund(revenue_yoy=None, revenue_yoy_prev=None), "NO_ALIGNED_YOY"),
                             (fund(revenue_yoy=5.0, revenue_yoy_prev=4.0), "YOY_OUT_OF_RANGE")):
            flat = trend.build(case, REPORT_DAY)
            self.assertEqual((flat["tier"], flat["growth"], flat["capped"], flat["tier_b_reason"]), ("B", None, None, reason))
            self.assertAlmostEqual(flat["m6"]["amount"], 300.0 * M)
            self.assertAlmostEqual(flat["m12"]["amount"], 600.0 * M)
            self.assertAlmostEqual(flat["m6"]["change"], (120 + 150 + 300) / 480 - 1)

    def test_missing_or_invalid_inputs_produce_nothing(self):
        refused = {
            "no quarters": fund(revenue_quarters=None),
            "three quarters": fund(revenue_quarters=QUARTERS[1:]),
            "anchor differs from the quarter end": fund(quarter_end="2026-03-31"),
            "a gap of two quarters": fund(revenue_quarters=[QUARTERS[0], QUARTERS[1], {"end": "2026-09-30", "revenue": 120.0 * M}, {"end": "2026-12-31", "revenue": 150.0 * M}]),
            "non-positive revenue": fund(revenue_quarters=[{**QUARTERS[0], "revenue": 0.0}] + QUARTERS[1:]),
            "non-finite revenue": fund(revenue_quarters=[{**QUARTERS[0], "revenue": float("inf")}] + QUARTERS[1:]),
            "no currency": fund(revenue_unit=None),
            "lowercase currency": fund(revenue_unit="usd"),
            "no source": fund(source=""),
            "http source": fund(source_url="http://finance.yahoo.com/x"),
            "bad quarter date": fund(revenue_quarters=[{**QUARTERS[0], "end": "2025-13-30"}] + QUARTERS[1:]),
        }
        for name, case in refused.items():
            self.assertIsNone(trend.build(case, REPORT_DAY), name)
        self.assertIsNone(trend.build(None, REPORT_DAY))
        self.assertIsNone(trend.build(fund(), date(2027, 1, 20)), "an anchor older than 200 days")
        self.assertIsNone(trend.build(fund(), date(2026, 6, 29)), "an anchor after the report day")
        self.assertIsNotNone(trend.build(fund(), date(2026, 6, 30) + timedelta(days=200)))

    def test_quarters_of_requires_four_contiguous_quarters_ending_at_the_latest(self):
        series = {"2025-03-31": 90.0, "2025-06-30": 95.0, "2025-09-30": 100.0 * M, "2025-12-31": 110.0 * M, "2026-03-31": 120.0 * M, "2026-06-30": 150.0 * M}
        self.assertEqual([q["end"] for q in trend.quarters_of(series, "2026-06-30")], ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"])
        self.assertEqual([q["revenue"] for q in trend.quarters_of(series, "2026-06-30")], [100.0 * M, 110.0 * M, 120.0 * M, 150.0 * M])
        self.assertIsNone(trend.quarters_of({**series, "2026-03-31": None}, "2026-06-30"))
        self.assertIsNone(trend.quarters_of({k: v for k, v in series.items() if k != "2026-03-31"}, "2026-06-30"), "a missing quarter never stretches the window")
        self.assertIsNone(trend.quarters_of(series, "2026-09-30"))
        self.assertIsNone(trend.quarters_of({k: v for k, v in list(series.items())[-3:]}, "2026-06-30"))
        keyed = {date.fromisoformat(k): v for k, v in series.items()}
        self.assertEqual(trend.quarters_of(keyed, date(2026, 6, 30))[0]["end"], "2025-09-30")

    def test_window_end_follows_calendar_months_and_odd_fiscal_quarter_ends(self):
        self.assertEqual(trend.window_end(date(2026, 6, 30), 6).isoformat(), "2026-12-31")
        self.assertEqual(trend.window_end(date(2026, 6, 30), 12).isoformat(), "2027-06-30")
        self.assertEqual(trend.window_end(date(2026, 7, 26), 6).isoformat(), "2027-01-26")
        self.assertEqual(trend.window_end(date(2026, 8, 31), 6).isoformat(), "2027-02-28")


class CollectorTests(unittest.TestCase):
    def test_sec_fundamentals_keep_the_last_four_filed_quarters(self):
        result = engine.sec_fundamentals("X", 1, FACTS)
        self.assertEqual([q["end"] for q in result["revenue_quarters"]], ["2025-09-27", "2025-12-27", "2026-03-28", "2026-06-27"])
        self.assertEqual([q["revenue"] for q in result["revenue_quarters"]], [150, 180, 220, 280])
        self.assertEqual(result["revenue_unit"], "USD")

    def test_yahoo_input_needs_a_known_statement_currency_equal_to_the_quote_currency(self):
        series = {q["end"]: q["revenue"] for q in QUARTERS}
        self.assertEqual(engine._yahoo_trend_quarters(series, "2026-06-30", "USD", "USD")["revenue_quarters"], QUARTERS)
        self.assertEqual(engine._yahoo_trend_quarters(series, "2026-06-30", "TWD", "USD"), {})
        self.assertEqual(engine._yahoo_trend_quarters(series, "2026-06-30", None, "USD"), {})
        self.assertEqual(engine._yahoo_trend_quarters({**series, "2026-03-31": None}, "2026-06-30", "USD", "USD"), {})


class SealerTests(unittest.TestCase):
    def setUp(self):
        saved = publisher.company_deep_report.load_order_scenarios
        publisher.company_deep_report.load_order_scenarios = lambda *args, **kwargs: {}
        self.addCleanup(setattr, publisher.company_deep_report, "load_order_scenarios", saved)
        registry_dir = tempfile.TemporaryDirectory()
        self.addCleanup(registry_dir.cleanup)
        registry = Path(registry_dir.name) / "order-claims-v2.json"
        registry.write_text(json.dumps({"schema": "order-claims-v2", "issuers": {}, "documents": [], "claims": []}), encoding="utf-8")
        saved_registry = publisher.order_claims.REGISTRY_PATH
        publisher.order_claims.REGISTRY_PATH = registry
        self.addCleanup(setattr, publisher.order_claims, "REGISTRY_PATH", saved_registry)

    def seal(self, fundamentals, now):
        entry = {"rank": 1, "symbol": "POET", "name": "POET Technologies", "layer": "optics", "archetype": "EXPLOSION", "score": 70.0,
                 "role": "optical interposer", "role_source": {"url": "https://x.com/a/status/1", "date": "2026-09-03"},
                 "score_parts": {"layer_heat": 5, "capture": 4, "lead": 14, "confirmation": 15, "size": 10, "penalty": 0},
                 "fundamentals": fundamentals,
                 "market": {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/POET", "asof": "2026-09-25", "ret_6m": 1.9,
                            "ret_1y": 8.5, "cagr_2y": 1.6, "currency": "USD", "price": 3.2},
                 "market_cap_usd": 5e8, "serenity": None, "leopold": None}
        doc = {"schema": "v213-bottleneck-top20-v3", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "leads": {},
               "top": [{**entry, "rank": index + 1, "symbol": "POET" if index == 0 else f"S{index}"} for index in range(12)],
               "industries": [{"rank": 1, "id": "optics", "name_zh": "光通訊", "chain": "network_optics", "leopold_constraint": "x",
                               "explosiveness": 52.1, "median_revenue_yoy": 0.3, "median_acceleration": 0.1, "median_return_6m": 0.5,
                               "fund_13f_weight": 0.0, "serenity_heat": 12.0, "news": None}]}
        saved = publisher.build_zh_names.names_for
        publisher.build_zh_names.names_for = fixture_names_for({})
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "v3.json"
                path.write_text(json.dumps(doc), encoding="utf-8")
                return json.loads(publisher.lazy_bottleneck_v3_body(path, now)[publisher.BOTTLENECK_V3_KEY])["top"][0]
        finally:
            publisher.build_zh_names.names_for = saved

    def test_entry_carries_the_optional_field_only_when_the_inputs_are_complete(self):
        now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
        with_quarters = self.seal(fund(), now)
        self.assertEqual(with_quarters["revenue_trend"], trend.build(fund(), now.date()))
        self.assertNotIn("revenue_quarters", with_quarters["fundamentals"])  # the closed fundamentals key set is unchanged
        self.assertNotIn("revenue_quarters", json.dumps(with_quarters["fundamentals"]))
        without = self.seal({k: v for k, v in fund().items() if k != "revenue_quarters"}, now)
        self.assertNotIn("revenue_trend", without)
        self.assertNotIn("revenue_trend", self.seal(None, now))
        self.assertNotIn("revenue_trend", self.seal(fund(revenue_quarters=QUARTERS[1:]), now))


def write_vectors():
    cases = vector_cases()
    out = {"report_day": REPORT_DAY.isoformat(),
           "cases": {name: {"fund": {k: v for k, v in f.items() if k != "revenue_quarters"}, "trend": trend.build(f, REPORT_DAY)}
                     for name, f in cases.items()}}
    VECTORS.write_bytes((json.dumps(out, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


class SharedVectorTests(unittest.TestCase):
    def test_vectors_are_current(self):
        stored = json.loads(VECTORS.read_text(encoding="utf-8"))
        for name, f in vector_cases().items():
            self.assertEqual(stored["cases"][name]["trend"], trend.build(f, REPORT_DAY), name)


if __name__ == "__main__":
    if "--write" in sys.argv:
        write_vectors()
    else:
        unittest.main()
