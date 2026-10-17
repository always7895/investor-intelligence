"""Operator 2026-10-14 (R/OPERATOR-DECISION-CONSENSUS-BRIDGE-AND-NAME-MATCH-20261014.txt): like the company-guidance route, the
analyst-consensus route keeps its projection for QUARTER_END_BRIDGE_DAYS (70) after the first consensus quarter ended, with a
warning and the unofficial label, but only while the capture itself was taken after that end. These tests drive the real
builders (revenue_guidance.build_consensus_forward_quarters, order_forecast.build_v3 and the refresh's sealer through the
committed fixture builder) at 1, 13, 70 and 71 days after the 2026-09-30 end, and the refusals around the rule."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import order_forecast as ofc  # noqa: E402
import revenue_guidance  # noqa: E402


def load_generator():
    path = ROOT / "tests" / "fixtures" / "make_v11_consensus_sealed.py"
    spec = importlib.util.spec_from_file_location("make_v11_consensus_sealed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = load_generator()
SOURCE = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{}?modules=earningsTrend,financialData"
END = "2026-09-30"
INTERVALS = [{"start": "2026-07-01", "end": "2026-09-30", "fiscal_label": "3Q26"},
             {"start": "2026-10-01", "end": "2026-12-31", "fiscal_label": "4Q26"},
             {"start": "2027-01-01", "end": "2027-03-31", "fiscal_label": "1Q27"},
             {"start": "2027-04-01", "end": "2027-06-30", "fiscal_label": "2Q27"}]


def utc(text: str) -> datetime:
    return GEN.utc(text)


def warning_text(ends: str, captured_at: str) -> str:
    return f"所估季度已於{ends}結束，實際營收尚未公布；截至{captured_at}分析師共識；仍為分析師共識（非官方），非實績"


def entry(captured_at="2026-10-01T02:00:00Z", **override):
    value = {"symbol": "000660.KS", "captured_at": captured_at, "currency": "KRW", "scope": "CONSOLIDATED",
             "source_url": SOURCE.format("000660.KS"),
             "quarters": [{"period": "0q", "end": END, "revenue": 100e12, "analysts": 37, "currency": "KRW", "scope": "CONSOLIDATED"},
                          {"period": "+1q", "end": "2026-12-31", "revenue": 110e12, "analysts": 37, "currency": "KRW", "scope": "CONSOLIDATED"}]}
    value.update(override)
    return value


def derive(captured_at, cutoff, intervals=INTERVALS, **override):
    return revenue_guidance.build_consensus_forward_quarters("000660.KS", entry(captured_at, **override), intervals, utc(cutoff),
                                                             expected_currency="KRW")


class ConsensusBridgeDerivationTests(unittest.TestCase):
    """build_consensus_forward_quarters: the day arithmetic, the capture-after-the-end condition and the other checks."""

    def test_day_zero_is_not_ended_and_carries_no_warning(self):
        got = derive("2026-09-30T02:00:00Z", "2026-09-30T08:00:00Z")
        self.assertEqual((got["status"], got["warning"]), ("AVAILABLE", None))

    def test_one_day_after_the_end_keeps_the_projection_with_the_exact_warning(self):
        got = derive("2026-10-01T02:00:00Z", "2026-10-01T08:00:00Z")
        self.assertEqual((got["status"], got["basis_type"]), ("AVAILABLE", "CONSENSUS"))
        self.assertEqual(got["warning"], {"quarter_index": 0, "quarter_end": END, "checked_at": "2026-10-01T02:00:00Z",
                                          "text": warning_text(END, "2026-10-01T02:00:00Z"), "is_fy": False, "affected_ends": [END]})
        self.assertEqual([got["f1"], got["f2"]], [100e12, 110e12])  # the figures are the capture's, unchanged by the bridge

    def test_day_seventy_is_eligible_and_day_seventy_one_is_stale(self):
        ok = derive("2026-12-09T02:00:00Z", "2026-12-09T08:00:00Z")  # 2026-09-30 + 70 days
        self.assertEqual((ok["status"], ok["warning"]["text"]), ("AVAILABLE", warning_text(END, "2026-12-09T02:00:00Z")))
        stale = derive("2026-12-10T02:00:00Z", "2026-12-10T08:00:00Z")
        self.assertEqual((stale["status"], stale["reason"], stale["warning"], stale["forward_quarters"]), ("UNAVAILABLE", "STALE", None, []))

    def test_a_capture_taken_on_or_before_the_end_day_is_stale(self):
        for captured_at, cutoff in (("2026-09-30T23:00:00Z", "2026-10-01T00:30:00Z"),  # the end day itself, 1.5 hours old
                                    ("2026-09-30T00:00:00Z", "2026-10-01T00:30:00Z")):  # the start of the end day
            got = derive(captured_at, cutoff)
            self.assertEqual((got["status"], got["reason"], got["warning"]), ("UNAVAILABLE", "STALE", None), captured_at)
        got = derive("2026-10-01T00:10:00Z", "2026-10-01T00:30:00Z")  # the first instant of the next day is after the end
        self.assertEqual(got["status"], "AVAILABLE")

    def test_the_other_checks_still_refuse_inside_the_bridge(self):
        cutoff = "2026-10-13T08:00:00Z"
        self.assertEqual(derive("2026-10-12T07:00:00Z", cutoff)["reason"], "STALE")  # 25 hours old
        self.assertEqual(derive("2026-10-13T09:00:00Z", cutoff)["reason"], "STALE")  # after the cutoff
        short = entry("2026-10-13T02:00:00Z")
        short["quarters"][0]["analysts"] = 2
        self.assertEqual(revenue_guidance.build_consensus_forward_quarters("000660.KS", short, INTERVALS, utc(cutoff))["reason"],
                         "SAMPLE_INSUFFICIENT")
        moved = entry("2026-10-13T02:00:00Z")
        moved["quarters"][0]["end"] = "2026-12-31"  # the provider's current quarter moved on: another quarter than the record's
        self.assertEqual(revenue_guidance.build_consensus_forward_quarters("000660.KS", moved, INTERVALS, utc(cutoff))["reason"],
                         "PERIOD_MISMATCH")
        self.assertEqual(derive("2026-10-13T02:00:00Z", cutoff, currency="USD")["reason"], "INVALID")
        self.assertEqual(derive("2026-10-13T02:00:00Z", cutoff, scope="GROUP")["reason"], "INVALID")
        self.assertEqual(derive("2026-10-13T02:00:00Z", cutoff, symbol="005930.KS")["reason"], "INVALID")

    def test_the_second_quarter_after_the_end_is_not_a_consensus_quarter_but_the_first_still_bridges(self):
        # the second interval is short and has ended too: both ends are named, the ended second quarter is not used
        intervals = [dict(i) for i in INTERVALS]
        intervals[1]["end"] = "2026-10-15"
        intervals[2]["start"] = "2026-10-16"
        value = entry("2026-10-20T02:00:00Z")
        value["quarters"][1]["end"] = "2026-10-15"
        got = revenue_guidance.build_consensus_forward_quarters("000660.KS", value, intervals, utc("2026-10-20T08:00:00Z"))
        self.assertEqual(got["status"], "AVAILABLE")
        self.assertEqual(got["warning"]["affected_ends"], [END, "2026-10-15"])
        self.assertEqual(got["warning"]["text"], warning_text("2026-09-30、2026-10-15", "2026-10-20T02:00:00Z"))
        self.assertEqual(got["f2"], got["f1"])  # a consensus quarter that already ended is not used as the second quarter
        # a capture between the two ends does not cover the later ended quarter
        late = derive("2026-10-10T02:00:00Z", "2026-10-20T08:00:00Z", intervals=intervals)
        self.assertEqual(late["status"], "UNAVAILABLE")


class ConsensusBridgeBuilderTests(unittest.TestCase):
    """order_forecast.build_v3 (the producer the refresh calls) and the sealed objects of the committed fixture builder."""

    @classmethod
    def setUpClass(cls):
        cls.cases = GEN.build()["cases"]

    def registry(self, gate=True):
        with tempfile.TemporaryDirectory() as tmp:
            path = GEN.registry_file(Path(tmp), gate)
            registry = revenue_guidance.load_registry(path)
            _, approval = GEN.golden.make_approval(path)
        return registry, approval

    def build(self, symbol, capture, cutoff, gate=True):
        registry, approval = self.registry(gate)
        return ofc.build_v3(symbol, None, None, cutoff.date(), cutoff, GEN.EMPTY_CLAIMS, revenue_registry=registry,
                            consensus_cache={symbol: capture} if capture is not None else {}, revenue_approval=approval,
                            release_checks_cache={})

    def test_the_sealed_bridge_objects_carry_one_warning_in_the_object_and_both_rows(self):
        for name, captured_at in (("bridge_day1", "2026-10-01T02:00:00Z"), ("bridge_day13", "2026-10-13T02:00:00Z"),
                                  ("bridge_day70", "2026-12-09T02:00:00Z")):
            v3 = self.cases[name]["outlooks"]["000660.KS"]["order_forecast_v3"]
            self.assertEqual((v3["revenue_status"], v3["revenue_basis"], v3["m6"]["basis"]), ("AVAILABLE", "CONSENSUS", "CONSENSUS"), name)
            expected = {"quarter_index": 0, "quarter_end": END, "checked_at": captured_at, "text": warning_text(END, captured_at),
                        "is_fy": False, "affected_ends": [END]}
            self.assertEqual((v3["warning"], v3["m6"]["warning"], v3["m12"]["warning"]), (expected, expected, expected), name)
            self.assertIn("分析師共識（非公司財測、非官方）｜Yahoo Finance，37 位分析師", v3["m6"]["basis_label"], name)

    def test_the_refused_neighbours_seal_their_reason_and_no_warning(self):
        for name, reason in (("quarter_ended", "STALE"), ("bridge_day71", "STALE"), ("stale_age", "STALE")):
            v3 = self.cases[name]["outlooks"]["000660.KS"]["order_forecast_v3"]
            self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_basis"], v3["warning"], v3["m6"]["status"]),
                             ("UNAVAILABLE", reason, None, None, "UNAVAILABLE"), name)
            self.assertIsNotNone(v3["evidence"]["consensus"], name)  # the bounded capture seals beside the reason for the Worker

    def test_company_guidance_keeps_its_precedence_and_its_own_warning_wording(self):
        v3 = self.cases["guidance_precedence"]["outlooks"]["NVDA"]["order_forecast_v3"]
        self.assertEqual(v3["revenue_basis"], "COMPANY_GUIDANCE")
        self.assertNotIn("分析師共識", json.dumps(v3["warning"], ensure_ascii=False))
        # A NOT_DISCLOSED record is the only one that reaches the consensus route even inside the bridge window.
        us = self.cases["bridge_day13"]["outlooks"]["ACME"]["order_forecast_v3"]
        self.assertEqual((us["revenue_basis"], us["warning"]["text"]), ("CONSENSUS", warning_text(END, "2026-10-13T02:00:00Z")))

    def test_the_gate_off_state_is_unchanged_inside_the_bridge_window(self):
        cutoff = utc("2026-10-13T08:00:00Z")
        with_capture = self.build("000660.KS", entry("2026-10-13T02:00:00Z"), cutoff, gate=False)
        without = self.build("000660.KS", None, cutoff, gate=False)
        self.assertEqual((with_capture["revenue_reason"], with_capture["revenue_diagnostic"], with_capture["revenue_basis"]),
                         ("NOT_DISCLOSED", "CONSENSUS_DEFERRED", None))
        self.assertEqual(json.dumps(with_capture, sort_keys=True, ensure_ascii=False), json.dumps(without, sort_keys=True, ensure_ascii=False))

    def test_a_forged_bridge_input_is_refused_not_bridged(self):
        # The producer re-reads the capture it is given: a capture dated in the future of the cutoff, or stamped before the
        # quarter ended, never produces the warning however the cutoff is set.
        future = self.build("000660.KS", entry("2026-10-14T02:00:00Z"), utc("2026-10-13T08:00:00Z"))
        self.assertEqual((future["revenue_reason"], future["warning"]), ("STALE", None))
        early = self.build("000660.KS", entry("2026-09-29T02:00:00Z"), utc("2026-09-29T20:00:00Z"))  # a fresh pre-end capture: no ended quarter
        self.assertEqual((early["revenue_basis"], early["warning"]), ("CONSENSUS", None))
        predates = self.build("000660.KS", entry("2026-09-30T20:00:00Z"), utc("2026-10-01T08:00:00Z"))
        self.assertEqual((predates["revenue_reason"], predates["warning"], predates["revenue_basis"]), ("STALE", None, None))


if __name__ == "__main__":
    unittest.main()
