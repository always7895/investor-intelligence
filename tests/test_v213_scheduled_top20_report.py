"""Seven-field producer emits the two-anchor evidence contract the Worker enforces (regression 2026-09-25:
since e22cd9f every scheduled bundle lacked freshness_policy / evidence_capture_at and the per-record
evidence fields, so the Worker rejected all Morning/Evening publications). Synthetic values only.

Anchor rule: a row showing a company claim (retained order disclosure or a displayed SEC profit metric) is a
current_state_claim anchored at the oldest filing date behind those claims; only a row showing no company
claim is a market_observation anchored at its latest daily bar. Windows keep the 14 h carry margin."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_v213_scheduled_top20_report as producer  # noqa: E402
import v213_evidence_policy as evidence  # noqa: E402
from report_source_acquisition import field_clock, unavailable  # noqa: E402

TICKERS = [f"T{i:02d}" for i in range(20)]
NOW = datetime.now(timezone.utc).replace(microsecond=0)
TODAY = NOW.date().isoformat()


def stamp(delta: timedelta = timedelta()) -> str:
    return (NOW + delta).isoformat().replace("+00:00", "Z")


def day(delta_days: float) -> str:
    return (NOW - timedelta(days=delta_days)).date().isoformat()


def v212(retrieved: list[str] | None = None, profit: str = "獲利；淨利率 12.0%") -> dict:
    generated = stamp(-timedelta(minutes=5))
    doc = {"product_version": "2.1.2", "generated_at": generated, "schema_version": 2, "calculation_cutoff": generated,
           "display_columns": producer.DISPLAY_COLUMNS[:5], "long_term_definition": "trailing_2y_adjusted_close_cagr",
           "short_term_definition": "trailing_6m_adjusted_close_price_return", "provider_scope": "public_only",
           "owner_watchlist_inherited": False, "records": []}
    for i, ticker in enumerate(TICKERS):
        at = (retrieved or [generated] * 20)[i]
        row = {"rank": i + 1, "ticker": ticker, "long_term_return_pct": 10.0 + i, "short_term_return_pct": 2.0 + i,
               "industry": "合成產業", "profit_summary": profit, "retrieved_at": at, "schema_version": 2,
               "long_term_window": "2y_cagr", "short_term_window": "6m_price_return", "market_source": "yfinance",
               "profit_source": "sec_edgar", "provider_scope": "public_only", "owner_watchlist_inherited": False}
        row["source_acquisition"] = {key: field_clock(key, row[key]) if unavailable(key, row[key])
                                     else field_clock(key, row[key], retrieved_at=at, evidence_sha256="1" * 64)
                                     for key in ("long_term_return_pct", "short_term_return_pct", "industry", "profit_summary")}
        doc["records"].append(row)
    return doc


def baseline(claims: dict[str, str] | None = None) -> dict:
    rows = []
    for i, ticker in enumerate(TICKERS):
        if ticker in (claims or {}):
            rows.append({"rank": i + 1, "ticker": ticker, "current_orders": "SEC 文件揭露 backlog 約 US$1.00 billion（合成）",
                         "future_orders_estimate": "無可靠公開預估", "orders_as_of": claims[ticker],
                         "orders_confidence": "HIGH_SEC_DIRECT_ORDER_METRIC", "retrieved_at": stamp(-timedelta(minutes=10)),
                         "current_order_source_urls": ["https://www.sec.gov/Archives/edgar/data/1/synthetic.htm"],
                         "future_order_source_urls": []})
        else:
            rows.append({"rank": i + 1, "ticker": ticker, "current_orders": producer.NO_CURRENT_ORDERS,
                         "future_orders_estimate": producer.NO_FUTURE_ORDER_ESTIMATE, "orders_as_of": "",
                         "orders_confidence": "UNAVAILABLE", "current_order_source_urls": [], "future_order_source_urls": []})
    return {"product_version": "2.1.3", "records": rows}


RETURNS = {"records": {t: {"windows": {"six_month": {"actual_end": TODAY}}} for t in TICKERS}}
NAMES = {t: f"Synthetic Company {i}" for i, t in enumerate(TICKERS)}


def claims(filed: str = TODAY, **overrides: str) -> dict:
    return {"records": {t: {"claim_filed_at": overrides.get(t, filed)} for t in TICKERS}}


class AnchorRuleTests(unittest.TestCase):
    def test_profit_claim_rows_anchor_at_their_filing_and_orders_at_the_oldest_claim(self):
        notes: dict = {}
        report = producer.build(v212(), baseline({"T00": day(30), "T01": day(200)}), NAMES, return_evidence=RETURNS,
                                profit_display=claims(day(60), T00=day(10)), report_notes=notes)
        rows = {row["ticker"]: row for row in report["records"]}
        # T00: order claim 30 d and profit claim 10 d -> the oldest (30 d) anchors the row.
        self.assertEqual((rows["T00"]["evidence_class"], rows["T00"]["orders_state_as_of"]), ("current_state_claim", f"{day(30)}T00:00:00Z"))
        # T01: 200-day order claim withheld; the displayed profit claim (60 d) still anchors it.
        self.assertEqual((rows["T01"]["current_orders"], rows["T01"]["orders_state_as_of"]),
                         (producer.NO_CURRENT_ORDERS, f"{day(60)}T00:00:00Z"))
        self.assertEqual(notes["withheld_stale_order_claims"], ["T01"])
        self.assertTrue(all(row["freshness_policy_key"] == "current_state_claim_max_age_days" for row in report["records"]))
        self.assertTrue(all(row["test_only_admission"] is False for row in report["records"]))

    def test_rows_without_company_claims_anchor_at_the_market_bar(self):
        report = producer.build(v212(profit=producer.NO_PROFIT_METRICS), baseline(), NAMES, return_evidence=RETURNS)
        self.assertTrue(all(row["evidence_class"] == "market_observation" and row["orders_state_as_of"] == f"{TODAY}T00:00:00Z"
                            for row in report["records"]))

    def test_carry_margin_withholds_an_order_claim_at_the_window_edge(self):
        edge = day(135 - 0.3)  # inside 135 d, but within the 14 h carry margin
        notes: dict = {}
        producer.build(v212(), baseline({"T02": edge}), NAMES, return_evidence=RETURNS, profit_display=claims(), report_notes=notes)
        self.assertEqual(notes["withheld_stale_order_claims"], ["T02"])

    def test_missing_or_expired_anchors_fail_the_build(self):
        with self.assertRaisesRegex(producer.V213ScheduledReportError, "PROFIT_CLAIM_DATE_UNKNOWN:T00"):
            producer.build(v212(), baseline(), NAMES, return_evidence=RETURNS, profit_display={"records": {}})
        with self.assertRaisesRegex(producer.V213ScheduledReportError, "EVIDENCE_ANCHOR_OUTSIDE_WINDOW:T03"):
            producer.build(v212(), baseline(), NAMES, return_evidence=RETURNS, profit_display=claims(T03=day(140)))
        partial = {"records": {t: v for t, v in RETURNS["records"].items() if t != "T05"}}
        with self.assertRaisesRegex(producer.V213ScheduledReportError, "EVIDENCE_ANCHOR_MISSING:T05"):
            producer.build(v212(profit=producer.NO_PROFIT_METRICS), baseline(), NAMES, return_evidence=partial)
        stale_bar = {"records": {t: {"windows": {"six_month": {"actual_end": day(9)}}} for t in TICKERS}}
        with self.assertRaisesRegex(producer.V213ScheduledReportError, "EVIDENCE_ANCHOR_OUTSIDE_WINDOW"):
            producer.build(v212(profit=producer.NO_PROFIT_METRICS), baseline(), NAMES, return_evidence=stale_bar)

    def test_two_year_window_anchors_when_the_six_month_window_is_missing(self):
        returns = json.loads(json.dumps(RETURNS))
        returns["records"]["T06"] = {"windows": {"two_year": {"actual_end": day(1)}}}
        report = producer.build(v212(profit=producer.NO_PROFIT_METRICS), baseline(), NAMES, return_evidence=returns)
        self.assertEqual(report["records"][6]["orders_state_as_of"], f"{day(1)}T00:00:00Z")

    def test_capture_time_is_the_oldest_acquisition_and_policy_is_bound(self):
        times = [stamp(-timedelta(minutes=5))] * 20
        times[7] = stamp(-timedelta(hours=3))
        report = producer.build(v212(times), baseline(), NAMES, return_evidence=RETURNS, profit_display=claims())
        self.assertEqual(report["evidence_capture_at"], times[7])
        raw = json.loads(evidence.POLICY_PATH.read_text(encoding="utf-8"))
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        self.assertEqual(report["freshness_policy"], {"policy_id": raw["policy_id"], "policy_sha256": digest})
        self.assertGreaterEqual(evidence.parse_time(report["generated_at"]), max(evidence.parse_time(t) for t in times))


class WorkerMirrorTests(unittest.TestCase):
    def setUp(self):
        self.report = producer.build(v212(profit=producer.NO_PROFIT_METRICS), baseline({"T00": day(30)}), NAMES,
                                     return_evidence=RETURNS)

    def test_fresh_report_is_accepted_now_and_at_the_end_of_the_carry(self):
        self.assertEqual(evidence.validate_seven_field_report(self.report, now=NOW), [])
        self.assertEqual(evidence.validate_seven_field_report(self.report, now=NOW + timedelta(hours=14)), [])

    def test_windows_admission_keys_and_binding_are_enforced(self):
        self.assertIn("RECORD_2_EVIDENCE_ANCHOR_OUTSIDE_WINDOW",
                      evidence.validate_seven_field_report(self.report, now=NOW + timedelta(days=8)))
        mixed = json.loads(json.dumps(self.report))
        mixed["records"][3]["test_only_admission"] = True
        self.assertIn("ADMISSION_MIXED", evidence.validate_seven_field_report(mixed, now=NOW))
        extra = json.loads(json.dumps(self.report))
        extra["records"][0]["unexpected"] = 1
        self.assertIn("RECORD_1_KEYS", evidence.validate_seven_field_report(extra, now=NOW))
        drift = json.loads(json.dumps(self.report))
        drift["freshness_policy"]["policy_sha256"] = "0" * 64
        self.assertIn("FRESHNESS_POLICY_BINDING", evidence.validate_seven_field_report(drift, now=NOW))
        future = json.loads(json.dumps(self.report))
        future["records"][4]["retrieved_at"] = stamp(timedelta(hours=1))
        reasons = evidence.validate_seven_field_report(future, now=NOW)
        self.assertTrue(any(reason.startswith("RECORD_5_RETRIEVED") for reason in reasons), reasons)

    def test_report_freshness_bounds(self):
        bounds = evidence.report_freshness()
        self.assertLess(bounds["refresh_after_hours"], bounds["report_max_age_hours"])
        self.assertLessEqual(bounds["report_max_age_hours"], 24)


if __name__ == "__main__":
    unittest.main()
