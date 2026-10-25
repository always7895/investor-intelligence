"""Tests for revenue_guidance.py and revenue_consensus_quarterly.py.
Astra contract ORDERS-V3-01 section 8 (Oracles 1-7, negative matrix, staleness amendment).
"""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import revenue_guidance
import revenue_consensus_quarterly
CUTOFF = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def make_synthetic_approval(registry_sha256: str, issuers: dict, reviewed_at: str = "2026-09-28T11:00:00Z") -> dict:
    """A1: a synthetic enforced reviewed profile covering every operative input of a synthetic registry record
    (the same decision set tests/fixtures/make_orders_v3_golden.py seals; the writer-owned real file is
    config/revenue-guidance-approval-v1.json)."""
    import hashlib as _hashlib
    records: dict[str, dict] = {}
    for sym, rec in issuers.items():
        record_sha = _hashlib.sha256(revenue_guidance.canonical_json(rec).encode("utf-8")).hexdigest()
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


class TestRevenueGuidanceOracles(unittest.TestCase):
    """Normative Section 8.1 synthetic oracles 1-7."""

    def test_oracle_1_quarter_guidance_only(self):
        actuals = [80.0, 90.0, 100.0, 110.0]
        G = 120.0
        fw = [G, G, G, G]
        res = revenue_guidance.compute_v3_arithmetic(actuals, fw)

        self.assertEqual(res["status"], "AVAILABLE")
        self.assertAlmostEqual(res["baseline_b"], 380.0)
        self.assertAlmostEqual(res["amount6"], 240.0)
        self.assertAlmostEqual(res["amount12"], 480.0)
        self.assertAlmostEqual(res["ttm6"], 450.0)
        self.assertAlmostEqual(res["ttm12"], 480.0)
        self.assertAlmostEqual(res["change6"], 70.0 / 380.0, places=9)
        self.assertAlmostEqual(res["change12"], 100.0 / 380.0, places=9)

    def test_oracle_2_fy_guidance_only(self):
        actuals = [80.0, 90.0, 100.0, 110.0]
        FY, YTD = 500.0, 210.0
        R = FY - YTD  # 290
        n = 2
        q_share = R / n  # 145
        fw = [q_share, q_share, q_share, q_share]
        res = revenue_guidance.compute_v3_arithmetic(actuals, fw)

        self.assertEqual(res["status"], "AVAILABLE")
        self.assertAlmostEqual(res["baseline_b"], 380.0)
        self.assertAlmostEqual(res["amount6"], 290.0)
        self.assertAlmostEqual(res["amount12"], 580.0)
        self.assertAlmostEqual(res["ttm6"], 500.0)
        self.assertAlmostEqual(res["ttm12"], 580.0)
        self.assertAlmostEqual(res["change6"], 120.0 / 380.0, places=9)
        self.assertAlmostEqual(res["change12"], 200.0 / 380.0, places=9)

    def test_oracle_3_concurrent_quarter_and_fy(self):
        actuals = [80.0, 90.0, 100.0, 110.0]
        FY, YTD = 500.0, 210.0
        R = FY - YTD  # 290
        G = 130.0
        f1 = G
        f2 = R - G  # 160
        f3 = f2     # hold flat at last FY quarter
        f4 = f2
        fw = [f1, f2, f3, f4]  # [130, 160, 160, 160]
        res = revenue_guidance.compute_v3_arithmetic(actuals, fw)

        self.assertEqual(res["status"], "AVAILABLE")
        self.assertAlmostEqual(res["baseline_b"], 380.0)
        self.assertAlmostEqual(res["amount6"], 290.0)
        self.assertAlmostEqual(res["amount12"], 610.0)
        self.assertAlmostEqual(res["ttm6"], 500.0)
        self.assertAlmostEqual(res["ttm12"], 610.0)
        self.assertAlmostEqual(res["change6"], 120.0 / 380.0, places=9)
        self.assertAlmostEqual(res["change12"], 230.0 / 380.0, places=9)

    def test_oracle_4_consensus_two_quarters(self):
        actuals = [80.0, 90.0, 100.0, 110.0]
        c1, c2 = 120.0, 130.0
        fw = [c1, c2, c2, c2]  # [120, 130, 130, 130]
        res = revenue_guidance.compute_v3_arithmetic(actuals, fw)

        self.assertEqual(res["status"], "AVAILABLE")
        self.assertAlmostEqual(res["baseline_b"], 380.0)
        self.assertAlmostEqual(res["amount6"], 250.0)
        self.assertAlmostEqual(res["amount12"], 510.0)
        self.assertAlmostEqual(res["ttm6"], 460.0)
        self.assertAlmostEqual(res["ttm12"], 510.0)
        self.assertAlmostEqual(res["change6"], 80.0 / 380.0, places=9)
        self.assertAlmostEqual(res["change12"], 130.0 / 380.0, places=9)

    def test_oracle_5_flat_equality(self):
        actuals = [100.0, 100.0, 100.0, 100.0]
        G = 100.0
        fw = [G, G, G, G]
        res = revenue_guidance.compute_v3_arithmetic(actuals, fw)

        self.assertEqual(res["status"], "AVAILABLE")
        self.assertAlmostEqual(res["baseline_b"], 400.0)
        self.assertAlmostEqual(res["amount6"], 200.0)
        self.assertAlmostEqual(res["amount12"], 400.0)
        self.assertAlmostEqual(res["change6"], 0.0, places=9)
        self.assertAlmostEqual(res["change12"], 0.0, places=9)

    def test_oracle_6_negative_returns(self):
        actuals = [100.0, 100.0, 100.0, 100.0]
        G = 80.0
        fw = [G, G, G, G]
        res = revenue_guidance.compute_v3_arithmetic(actuals, fw)

        self.assertEqual(res["status"], "AVAILABLE")
        self.assertAlmostEqual(res["baseline_b"], 400.0)
        self.assertAlmostEqual(res["amount6"], 160.0)
        self.assertAlmostEqual(res["amount12"], 320.0)
        self.assertAlmostEqual(res["change6"], -0.10, places=9)
        self.assertAlmostEqual(res["change12"], -0.20, places=9)

    def test_oracle_7_missing_history(self):
        actuals = [100.0, 110.0]  # only 2 quarters, missing complete 4 quarters
        G = 120.0
        fw = [G, G, G, G]
        res = revenue_guidance.compute_v3_arithmetic(actuals, fw)

        self.assertEqual(res["status"], "MISSING_HISTORY")
        self.assertAlmostEqual(res["amount6"], 240.0)
        self.assertAlmostEqual(res["amount12"], 480.0)
        self.assertIsNone(res["baseline_b"])
        self.assertIsNone(res["change6"])
        self.assertIsNone(res["change12"])
        self.assertEqual(res["scenario_status"], "NO_BASIS")
        self.assertEqual(res["scenario_reason"], "NO_REVENUE_HISTORY")


class TestStalenessAmendment(unittest.TestCase):
    """Tests for Astra amendment: post-quarter-end bridge (+70d cap, 24h receipt, warnings)."""

    def _make_record(self, q_end: str, checked_at: str, receipt_status="OK", pkind="QUARTER"):
        end_d = date.fromisoformat(q_end)
        start_d = end_d - timedelta(days=90)
        q2_start = end_d + timedelta(days=1)
        q2_end = q2_start + timedelta(days=90)
        q3_start = q2_end + timedelta(days=1)
        q3_end = q3_start + timedelta(days=90)
        q4_start = q3_end + timedelta(days=1)
        q4_end = q4_start + timedelta(days=90)

        anchor_end_d = start_d - timedelta(days=1)
        q4_e = anchor_end_d
        q4_s = q4_e - timedelta(days=90)
        q3_e = q4_s - timedelta(days=1)
        q3_s = q3_e - timedelta(days=90)
        q2_e = q3_s - timedelta(days=1)
        q2_s = q2_e - timedelta(days=90)
        q1_e = q2_s - timedelta(days=1)
        q1_s = q1_e - timedelta(days=90)

        record = {
            "symbol": "NVDA",
            "company_name": "NVIDIA Corporation",
            "status": "GUIDANCE",
            "url_prefixes": ["https://investor.nvidia.com/"],
            "documents": [
                {
                    "id": "DOC-1",
                    "issuer": "NVDA",
                    "publisher": "NVIDIA Corporation",
                    "title": "Earnings Release",
                    "source_kind": "ISSUER_EARNINGS_RELEASE",
                    "url": "https://investor.nvidia.com/release.pdf",
                    "published_date": "2026-08-20",
                    "retrieved_at": "2026-08-20T12:00:00Z",
                    "sha256": "0" * 64,
                    "byte_size": 1000,
                    "lineage_id": "L1",
                }
            ],
            "claims": [
                {
                    "id": "CLAIM-1",
                    "document_id": "DOC-1",
                    "locator": "p.1",
                    "passage": "Revenue is expected to be $32.5 billion",
                    "metric": "REVENUE",
                    "assertion_kind": "COMPANY_GUIDANCE",
                    "currency": "USD",
                    "unit_multiplier": 1000000000,
                    "stated_point": 32.5,
                    "scope": "COMPANY",
                    "accounting_basis": "GAAP",
                    "fiscal_label": "Q3 FY27",
                    "period_kind": pkind,
                    "period_start": str(start_d),
                    "period_end": q_end,
                }
            ],
            "reported_quarters": [
                {"fiscal_label": "Q3 FY26", "start": str(q1_s), "end": str(q1_e), "revenue": 18120000000.0, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                {"fiscal_label": "Q4 FY26", "start": str(q2_s), "end": str(q2_e), "revenue": 22100000000.0, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                {"fiscal_label": "Q1 FY27", "start": str(q3_s), "end": str(q3_e), "revenue": 26044000000.0, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                {"fiscal_label": "Q2 FY27", "start": str(q4_s), "end": str(q4_e), "revenue": 30040000000.0, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
            ],
            "forward_intervals": [
                {"fiscal_label": "Q3 FY27", "start": str(start_d), "end": q_end},
                {"fiscal_label": "Q4 FY27", "start": str(q2_start), "end": str(q2_end)},
                {"fiscal_label": "Q1 FY28", "start": str(q3_start), "end": str(q3_end)},
                {"fiscal_label": "Q2 FY28", "start": str(q4_start), "end": str(q4_end)},
            ],
            # The official IR channel (Astra W1 ruling, astra-ir-coverage): the company-guidance path requires
            # SEC_WIRE_IR coverage, so the record carries its IR feed and the receipt its ISSUER_IR channel.
            "release_channels": {
                "ir": {"kind": "Q4_PRESS_RELEASES",
                       "url": "https://investor.nvidia.com/feed/PressRelease.svc/GetPressReleaseList"},
                "ir_guidance_release_title": "NVIDIA Announces Financial Results for Second Quarter Fiscal 2027",
            },
        }

        chk_through = min(checked_at[:10], CUTOFF.strftime("%Y-%m-%d"))
        receipt = {
            "issuer": "NVDA",
            "checked_at": checked_at,
            "status": "RESULTS_PUBLISHED" if receipt_status in ("NEWER_RELEASE_FOUND", "RESULTS_PUBLISHED") else receipt_status,
            "guidance_document_id": "DOC-1",
            "guidance_published_date": "2026-08-20",
            "anchor_end": str(anchor_end_d),
            "coverage": "SEC_WIRE_IR",
            "channels": [
                {"kind": "SEC_SUBMISSIONS", "url": "https://data.sec.gov/submissions/CIK0000000000.json", "status": "OK", "checked_through": chk_through, "complete": True},
                {"kind": "WIRE_PRESS_RELEASES", "url": "https://api.nasdaq.com/api/news/topic/press_release?q=symbol:NVDA", "status": "OK", "checked_through": chk_through, "complete": True},
                {"kind": "ISSUER_IR", "url": "https://investor.nvidia.com/feed/PressRelease.svc/GetPressReleaseList", "status": "OK", "checked_through": chk_through, "complete": True},
            ],
            "later_documents": [] if receipt_status not in ("NEWER_RELEASE_FOUND", "RESULTS_PUBLISHED") else [
                {"channel": "SEC_SUBMISSIONS", "date": chk_through, "id": "acc-1", "label": "8-K item 2.02", "disposition": "RESULTS_RELEASE"}
            ],
        }
        receipt["digest"] = revenue_guidance.compute_receipt_digest(receipt)
        cache = {"schema": "revenue-guidance-release-checks-v1", "generated_at": checked_at, "issuers": {"NVDA": [receipt]}}
        return record, cache

    def test_quarter_end_within_70_days_eligible_with_warning(self):
        # Quarter ended on 2026-08-28. Cutoff is 2026-09-28 (31 days after end).
        # Should be eligible under post-quarter-end bridge, with warning.
        record, cache = self._make_record("2026-08-28", "2026-09-28T09:00:00Z")
        res = revenue_guidance.build_forward_quarters("NVDA", record, CUTOFF, cache)

        self.assertEqual(res["status"], "AVAILABLE")
        self.assertIsNotNone(res["warning"])
        self.assertIn("財測季度已於2026-08-28結束，實際營收尚未公布", res["warning"]["text"])
        self.assertIn("仍為財測／模型，非實績", res["warning"]["text"])

    def test_quarter_end_exact_70_days_eligible(self):
        # 70 days before 2026-09-28 is 2026-07-20.
        record, cache = self._make_record("2026-07-20", "2026-09-28T09:00:00Z")
        res = revenue_guidance.build_forward_quarters("NVDA", record, CUTOFF, cache)
        self.assertEqual(res["status"], "AVAILABLE")
        self.assertIsNotNone(res["warning"])

    def test_quarter_end_71_days_stale(self):
        # 71 days before 2026-09-28 is 2026-07-19.
        record, cache = self._make_record("2026-07-19", "2026-09-28T09:00:00Z")
        res = revenue_guidance.build_forward_quarters("NVDA", record, CUTOFF, cache)
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "STALE")

    def test_receipt_older_than_24h_fails(self):
        # Receipt checked 25 hours before cutoff
        record, cache = self._make_record("2026-08-28", "2026-09-27T10:00:00Z")
        res = revenue_guidance.build_forward_quarters("NVDA", record, CUTOFF, cache)
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "STALE")

    def test_receipt_newer_release_found_stale(self):
        record, cache = self._make_record("2026-08-28", "2026-09-28T09:00:00Z", receipt_status="NEWER_RELEASE_FOUND")
        res = revenue_guidance.build_forward_quarters("NVDA", record, CUTOFF, cache)
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "STALE")


class TestConsensusAdapter(unittest.TestCase):
    """Tests for revenue_consensus_quarterly.py."""

    def test_extract_valid_quarterly_consensus(self):
        fake_data = {
            "quoteSummary": {
                "result": [
                    {
                        "financialData": {"financialCurrency": "KRW"},
                        "earningsTrend": {
                            "trend": [
                                {
                                    "period": "0q",
                                    "endDate": "2026-09-30",
                                    "revenueEstimate": {"avg": 18500000000000.0, "numberOfAnalysts": 25},
                                },
                                {
                                    "period": "+1q",
                                    "endDate": "2026-12-31",
                                    "revenueEstimate": {"avg": 19200000000000.0, "numberOfAnalysts": 24},
                                },
                                {
                                    "period": "0y",
                                    "endDate": "2026-12-31",
                                    "revenueEstimate": {"avg": 65000000000000.0, "numberOfAnalysts": 28},
                                },
                            ]
                        },
                    }
                ]
            }
        }
        now = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
        extracted = revenue_consensus_quarterly.extract_quarterly_consensus("000660.KS", fake_data, now)
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted["currency"], "KRW")
        self.assertEqual(len(extracted["quarters"]), 2)
        self.assertEqual(extracted["quarters"][0]["analysts"], 25)
        self.assertEqual(extracted["quarters"][1]["analysts"], 24)

    def test_reject_less_than_3_analysts(self):
        fake_data = {
            "quoteSummary": {
                "result": [
                    {
                        "financialData": {"financialCurrency": "USD"},
                        "earningsTrend": {
                            "trend": [
                                {
                                    "period": "0q",
                                    "endDate": "2026-09-30",
                                    "revenueEstimate": {"avg": 100.0, "numberOfAnalysts": 2},
                                }
                            ]
                        },
                    }
                ]
            }
        }
        now = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
        extracted = revenue_consensus_quarterly.extract_quarterly_consensus("POET", fake_data, now)
        self.assertIsNone(extracted)


    def test_reject_less_than_3_analysts(self):
        fake_data = {
            "quoteSummary": {
                "result": [
                    {
                        "financialData": {"financialCurrency": "USD"},
                        "earningsTrend": {
                            "trend": [
                                {
                                    "period": "0q",
                                    "endDate": "2026-09-30",
                                    "revenueEstimate": {"avg": 100.0, "numberOfAnalysts": 2},
                                }
                            ]
                        },
                    }
                ]
            }
        }
        now = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
        extracted = revenue_consensus_quarterly.extract_quarterly_consensus("POET", fake_data, now)
        self.assertIsNone(extracted)


class TestGoldenSealedFixtureIsReproducible(unittest.TestCase):
    """The Worker golden (tests/fixtures/v213-orders-v3-golden-sealed.json) is exactly what the real sealer function
    produces from the reviewed fixtures (tests/fixtures/make_orders_v3_golden.py)."""

    def test_fixture_equals_a_fresh_build(self):
        import importlib.util
        path = Path(__file__).resolve().parent / "fixtures" / "make_orders_v3_golden.py"
        spec = importlib.util.spec_from_file_location("make_orders_v3_golden", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        committed = json.loads(module.OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(json.dumps(module.build(), ensure_ascii=False)), committed)


class TestReaffirmedGuidanceReference(unittest.TestCase):
    """Writer integration: a figure reaffirmed later without being restated (NBIS: May letter states it, August letter
    reaffirms it) is checked for newer releases from the reaffirmation, and only such a receipt is accepted."""

    CUTOFF = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)  # after the writer's reviews in the registry

    def receipt_cache(self, record):
        import revenue_guidance_release_check as rc
        sec = lambda url: {"filings": {"recent": {"form": ["6-K"], "filingDate": ["2026-05-13"], "items": [""],
                                                   "accessionNumber": ["0001104659-26-059872"], "reportDate": [""]}}}
        wire = lambda url: {"data": {"rows": [{"created": "May 13, 2026", "title": "Nebius reports first quarter results", "url": "/press-release/q1"}],
                                     "totalrecords": 1}}
        # The record's official IR channel (Astra W1 ruling) is read from the captured newsroom fixture, never the network.
        ir_fetch = lambda url: (Path(__file__).resolve().parent / "fixtures" / "ir-feeds" / "newsroom-nebius.html").read_bytes()
        receipt = rc.receipt_for(record, self.CUTOFF - timedelta(hours=1), sec, wire, ir_fetch)
        return {"schema": "revenue-guidance-release-checks-v1", "generated_at": receipt["checked_at"], "issuers": {"NBIS": [receipt]}}

    def test_reference_is_the_latest_reaffirmation(self):
        rec = revenue_guidance.load_registry()["issuers"]["NBIS"]
        docs = {d["id"]: d for d in rec["documents"]}
        claim = [c for c in rec["claims"] if c["period_kind"] == "FISCAL_YEAR"][0]
        self.assertEqual(revenue_guidance.guidance_reference_document_id(claim, docs), "NBIS-GUIDANCE")
        self.assertEqual(revenue_guidance.guidance_reference_document_id({**claim, "reaffirmed_by": []}, docs), "NBIS-GUIDANCE-ORIG")

    def test_nbis_builds_from_a_receipt_anchored_at_the_reaffirmation_only(self):
        rec = json.loads(json.dumps(revenue_guidance.load_registry()["issuers"]["NBIS"]))
        result = revenue_guidance.build_forward_quarters("NBIS", rec, self.CUTOFF, release_checks_cache=self.receipt_cache(rec))
        self.assertEqual(result["status"], "AVAILABLE", result.get("reason"))
        self.assertAlmostEqual(result["f1"], (3.2e9 - 981.3e6) / 2)
        # a receipt anchored at the original May document (collected before the reaffirmation was recorded) is refused
        orig = json.loads(json.dumps(rec))
        for doc in orig["documents"]:
            doc["id"] = {"NBIS-GUIDANCE": "NBIS-REAFFIRM", "NBIS-GUIDANCE-ORIG": "NBIS-GUIDANCE"}.get(doc["id"], doc["id"])
        for claim in orig["claims"]:
            claim["document_id"] = "NBIS-GUIDANCE"
            for item in claim.get("reaffirmed_by") or []:
                item["document_id"] = "NBIS-REAFFIRM"
        # Simulate the old receipt: collected before the reaffirmation existed, so it is anchored at the original document.
        stale_rec = json.loads(json.dumps(orig))
        for claim in stale_rec["claims"]:
            claim["reaffirmed_by"] = []
        refused = revenue_guidance.build_forward_quarters("NBIS", orig, self.CUTOFF, release_checks_cache=self.receipt_cache(stale_rec))
        self.assertEqual(refused["status"], "UNAVAILABLE")
        self.assertEqual(refused["reason"], "FRESHNESS_UNVERIFIED")


class TestReviewedLaterDocumentIds(unittest.TestCase):
    """Writer integration: a reviewed later document is an EDGAR accession or a wire item URL on www.nasdaq.com."""

    def record(self, rid):
        rec = json.loads(json.dumps(revenue_guidance.load_registry()["issuers"]["NBIS"]))
        rec["reviewed_later_documents"] = [{"id": rid, "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-09-28T10:00:00Z", "note": "x"}]
        return rec

    def test_accession_and_wire_url_are_accepted(self):
        for rid in ("0001104659-26-101076", "https://www.nasdaq.com/press-release/nebius-group-nv-announces-results-its-annual-general-meeting-2026-08-26"):
            revenue_guidance.validate_issuer_record(self.record(rid))

    def test_other_urls_and_malformed_ids_are_refused(self):
        for rid in ("http://www.nasdaq.com/press-release/x", "https://evil.example/press-release/x", "https://www.nasdaq.com/press-release/a b",
                    "https://www.nasdaq.com/press-release/" + "a" * 400, ""):
            with self.assertRaises(revenue_guidance.GuidanceError):
                revenue_guidance.validate_issuer_record(self.record(rid))


class TestConsensusProductionTransport(unittest.TestCase):
    """Writer integration: Yahoo answers quoteSummary only inside the yfinance session (a plain urllib request gets
    HTTP 401), so the default transport must go through `yf.Ticker(symbol)._data.get_raw_json`, never urllib."""

    RAW = {"quoteSummary": {"result": [{"financialData": {"financialCurrency": "KRW"}, "earningsTrend": {"trend": [
        {"period": "0q", "endDate": "2026-09-30", "revenueEstimate": {"avg": {"raw": 1.0e14}, "numberOfAnalysts": {"raw": 37}}},
        {"period": "+1q", "endDate": "2026-12-31", "revenueEstimate": {"avg": {"raw": 1.1e14}, "numberOfAnalysts": {"raw": 37}}}]}}]}}

    def test_default_transport_uses_the_yfinance_session(self):
        import types
        from unittest import mock
        calls = []

        class Data:
            def get_raw_json(self, url, params=None):
                calls.append((url, params))
                return TestConsensusProductionTransport.RAW

        fake = types.SimpleNamespace(Ticker=lambda symbol: types.SimpleNamespace(_data=Data()))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"yfinance": fake}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("urllib must not be used")):
            entry = revenue_consensus_quarterly.refresh_symbol("000660.KS", datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc),
                                                               max_age_hours=0.9, cache_path=Path(tmp) / "c.json")
        self.assertIsNotNone(entry)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "https://query2.finance.yahoo.com/v10/finance/quoteSummary/000660.KS")
        self.assertEqual(calls[0][1]["formatted"], "false")

    def test_an_unbounded_result_list_is_refused(self):
        import types
        from unittest import mock
        big = {"quoteSummary": {"result": [{}] * 9}}
        fake = types.SimpleNamespace(Ticker=lambda symbol: types.SimpleNamespace(_data=types.SimpleNamespace(get_raw_json=lambda url, params=None: big)))
        with mock.patch.dict(sys.modules, {"yfinance": fake}):
            with self.assertRaises(revenue_consensus_quarterly.ConsensusCollectorError):
                revenue_consensus_quarterly._session_fetch("000660.KS")


class TestConsensusHistory(unittest.TestCase):
    """Writer integration: captures keep a short history and a sealed build binds the newest capture at or before its
    cutoff, so hourly captures never invalidate a v3 build that is up to three hours old."""

    RAW = {"quoteSummary": {"result": [{"financialData": {"financialCurrency": "KRW"}, "earningsTrend": {"trend": [
        {"period": "0q", "endDate": "2026-09-30", "revenueEstimate": {"avg": {"raw": 1.0e14}, "numberOfAnalysts": {"raw": 37}}},
        {"period": "+1q", "endDate": "2026-12-31", "revenueEstimate": {"avg": {"raw": 1.1e14}, "numberOfAnalysts": {"raw": 37}}}]}}]}}

    def test_hourly_captures_keep_history_and_selection_respects_the_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "consensus.json"
            for hour in range(10):
                now = datetime(2026, 9, 28, hour, 0, tzinfo=timezone.utc)
                revenue_consensus_quarterly.refresh_symbol("000660.KS", now, max_age_hours=0.9,
                                                           fetch_json=lambda url: self.RAW, cache_path=cache)
            loaded = revenue_consensus_quarterly.load_cache(cache)
            history = revenue_consensus_quarterly.history_of(loaded, "000660.KS")
            self.assertEqual(len(history), revenue_consensus_quarterly.HISTORY_KEEP)
            self.assertEqual(history[-1]["captured_at"], "2026-09-28T09:00:00Z")
            picked = revenue_consensus_quarterly.select_for_cutoff(loaded, datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc))
            self.assertEqual(picked["000660.KS"]["captured_at"], "2026-09-28T06:00:00Z")
            # a cutoff before every retained capture binds none (never a later capture)
            self.assertEqual(revenue_consensus_quarterly.select_for_cutoff(loaded, datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)), {})

    def test_a_legacy_single_entry_reads_as_a_history_of_one(self):
        entry = {"symbol": "000660.KS", "captured_at": "2026-09-28T05:00:00Z"}
        self.assertEqual(revenue_consensus_quarterly.history_of({"000660.KS": entry}, "000660.KS"), [entry])

    def test_default_symbols_are_the_registry_not_disclosed_issuers(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / "reg.json"
            reg.write_text(json.dumps({"schema": "revenue-guidance-v1", "issuers": [
                {"symbol": "000660.KS", "status": "NOT_DISCLOSED"}, {"symbol": "NVDA", "status": "GUIDANCE"},
                {"symbol": "X", "status": "INPUTS_MISSING"}]}), encoding="utf-8")
            self.assertEqual(revenue_consensus_quarterly.registry_symbols(reg), ["000660.KS"])
        self.assertIn("005930.KS", revenue_consensus_quarterly.registry_symbols())


class TestConsensusDistinguitions(unittest.TestCase):
    """Item 12: absent vs malformed second quarter, fractional counts, low-sample exclusion."""

    def _entry(self, q2_analysts=24, q2_revenue=16.0e12, omit_q2=False):
        quarters = [{"period": "0q", "end": "2026-09-30", "revenue": 15.0e12, "analysts": 25}]
        if not omit_q2:
            quarters.append({"period": "+1q", "end": "2026-12-31", "revenue": q2_revenue, "analysts": q2_analysts})
        return {"symbol": "000660.KS", "captured_at": "2026-09-28T08:00:00Z", "currency": "KRW", "quarters": quarters}

    def _intervals(self):
        return [
            {"fiscal_label": "Q3 26", "start": "2026-07-01", "end": "2026-09-30"},
            {"fiscal_label": "Q4 26", "start": "2026-10-01", "end": "2026-12-31"},
            {"fiscal_label": "Q1 27", "start": "2027-01-01", "end": "2027-03-31"},
            {"fiscal_label": "Q2 27", "start": "2027-04-01", "end": "2027-06-30"},
        ]

    def test_absent_q2_holds_f1_flat(self):
        res = revenue_guidance.build_consensus_forward_quarters("000660.KS", self._entry(omit_q2=True), self._intervals(), CUTOFF)
        self.assertEqual(res["status"], "AVAILABLE")
        self.assertEqual((res["f1"], res["f2"], res["f3"], res["f4"]), (15.0e12,) * 4)

    def test_low_sample_q2_excluded_with_visible_reason(self):
        res = revenue_guidance.build_consensus_forward_quarters("000660.KS", self._entry(q2_analysts=2), self._intervals(), CUTOFF)
        self.assertEqual(res["status"], "AVAILABLE")
        self.assertEqual((res["f1"], res["f2"]), (15.0e12, 15.0e12))  # the visible sample reason is the derivation label

    def test_malformed_q2_fails_closed(self):
        res = revenue_guidance.build_consensus_forward_quarters("000660.KS", self._entry(q2_revenue=-1.0), self._intervals(), CUTOFF)
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "INVALID")

    def test_fractional_analyst_count_rejected_by_extractor(self):
        fake_data = {
            "quoteSummary": {
                "result": [
                    {
                        "financialData": {"financialCurrency": "USD"},
                        "earningsTrend": {"trend": [
                            {"period": "0q", "endDate": "2026-09-30",
                             "revenueEstimate": {"avg": 100.0, "numberOfAnalysts": 3.9}},
                        ]},
                    }
                ]
            }
        }
        now = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
        self.assertIsNone(revenue_consensus_quarterly.extract_quarterly_consensus("POET", fake_data, now))


class TestConsensusCacheValidation(unittest.TestCase):
    """Counterexamples (compact receipt rows 24-25): a recent capture with malformed quarters must not be reused as a
    fresh success, and a backwards +1q / an extra +2q period must not extract."""

    @staticmethod
    def _trend(quarters):
        return {"quoteSummary": {"result": [{"financialData": {"financialCurrency": "KRW"},
                                              "earningsTrend": {"trend": quarters}}]}}

    def _good(self):
        return [
            {"period": "0q", "endDate": "2026-09-30", "revenueEstimate": {"avg": 1.0e14, "numberOfAnalysts": 37}},
            {"period": "+1q", "endDate": "2026-12-31", "revenueEstimate": {"avg": 1.1e14, "numberOfAnalysts": 37}},
        ]

    def test_malformed_fresh_cache_entry_is_not_reused(self):
        now = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
        bad = {"symbol": "POET", "captured_at": "2026-09-28T11:00:00Z", "currency": "KRW", "quarters": "bad"}
        self.assertFalse(revenue_consensus_quarterly.validate_consensus_entry(bad, "POET"))
        # The broken entry is not eligible for cutoff selection: no symbol, no manufactured success.
        selected = revenue_consensus_quarterly.select_for_cutoff({"POET": [bad]}, now)
        self.assertNotIn("POET", selected)

    def test_symbol_mismatch_in_cache_entry_is_rejected(self):
        good = {"symbol": "000660.KS", "captured_at": "2026-09-28T11:00:00Z", "currency": "KRW",
                "quarters": [{"period": "0q", "end": "2026-09-30", "revenue": 1.0e14, "analysts": 37}]}
        self.assertFalse(revenue_consensus_quarterly.validate_consensus_entry(good, "005930.KS"))

    def test_low_sample_plus1q_is_preserved_with_explicit_count(self):
        now = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
        low = [self._good()[0],
               {"period": "+1q", "endDate": "2026-12-31", "revenueEstimate": {"avg": 1.1e14, "numberOfAnalysts": 2}}]
        entry = revenue_consensus_quarterly.extract_quarterly_consensus("000660.KS", self._trend(low), now)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["quarters"][1]["analysts"], 2)  # the explicit low sample is visible downstream

    def test_backwards_plus1q_is_rejected(self):
        now = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
        backwards = [self._good()[0],
                     {"period": "+1q", "endDate": "2026-06-30", "revenueEstimate": {"avg": 1.0e14, "numberOfAnalysts": 37}}]
        self.assertIsNone(revenue_consensus_quarterly.extract_quarterly_consensus("000660.KS", self._trend(backwards), now))

    def test_extra_plus2q_period_is_rejected(self):
        now = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
        extra = self._good() + [{"period": "+2q", "endDate": "2027-03-31", "revenueEstimate": {"avg": 1.2e14, "numberOfAnalysts": 30}}]
        self.assertIsNone(revenue_consensus_quarterly.extract_quarterly_consensus("000660.KS", self._trend(extra), now))


class TestArithmeticEdges(unittest.TestCase):
    """Item 10: finite non-boolean numbers, overflow, zero quarters, n=1 shared tolerance."""

    def test_overflow_inputs_invalid(self):
        res = revenue_guidance.compute_v3_arithmetic([1e308, 1e308, 1e308, 1e308], [1e308] * 4)
        self.assertEqual(res["status"], "INVALID")

    def test_boolean_rejected(self):
        res = revenue_guidance.compute_v3_arithmetic([True, 1.0, 1.0, 1.0], [1.0] * 4)
        self.assertEqual(res["status"], "INVALID")

    def test_zero_quarters_with_positive_baseline(self):
        res = revenue_guidance.compute_v3_arithmetic([10.0, 10.0, 10.0, 10.0], [0.0] * 4)
        self.assertEqual(res["status"], "AVAILABLE")
        self.assertAlmostEqual(res["change12"], -1.0, places=9)

    def test_n1_concurrent_tiny_residual(self):
        # n=1: R and G must agree within the shared 1e-9 tolerance; a tiny difference is absorbed, a real one is not.
        claim = {"id": "C1", "low": 100.0, "high": 100.0, "stated_point": None, "unit_multiplier": 1}
        point, _ = revenue_guidance.compute_model_point(claim)
        self.assertTrue(revenue_guidance.close(100.0 + 1e-12, point))
        self.assertFalse(revenue_guidance.close(100.5, point))


class TestStalenessBoundaries(unittest.TestCase):
    """Item 19: end-day/next-day, exactly-24h receipt, 200-day guidance boundary."""

    def _record(self, q_end: str, checked_at: str, published: str = "2026-08-20"):
        end_d = date.fromisoformat(q_end)
        start_d = end_d - timedelta(days=90)
        q2_start = end_d + timedelta(days=1)
        anchor_end_d = start_d - timedelta(days=1)

        q4_e = anchor_end_d
        q4_s = q4_e - timedelta(days=90)
        q3_e = q4_s - timedelta(days=1)
        q3_s = q3_e - timedelta(days=90)
        q2_e = q3_s - timedelta(days=1)
        q2_s = q2_e - timedelta(days=90)
        q1_e = q2_s - timedelta(days=1)
        q1_s = q1_e - timedelta(days=90)

        record = {
            "symbol": "NVDA", "company_name": "NVIDIA Corporation", "status": "GUIDANCE",
            "url_prefixes": ["https://investor.nvidia.com/"],
            "documents": [{"id": "DOC-1", "issuer": "NVDA", "publisher": "NVIDIA Corporation", "source_kind": "ISSUER_EARNINGS_RELEASE",
                           "url": "https://investor.nvidia.com/release.pdf", "published_date": published,
                           "retrieved_at": "2026-08-20T12:00:00Z", "sha256": "0" * 64, "byte_size": 1000, "lineage_id": "L1"}],
            "claims": [{"id": "CLAIM-1", "document_id": "DOC-1", "locator": "p.1", "passage": "Revenue is expected to be $32.5 billion",
                        "metric": "REVENUE", "assertion_kind": "COMPANY_GUIDANCE", "currency": "USD", "unit_multiplier": 1000000000,
                        "stated_point": 32.5, "scope": "COMPANY", "accounting_basis": "GAAP", "period_kind": "QUARTER",
                        "period_start": str(start_d), "period_end": q_end}],
            "reported_quarters": [
                {"fiscal_label": "Q3 FY26", "start": str(q1_s), "end": str(q1_e), "revenue": 1.8e10, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                {"fiscal_label": "Q4 FY26", "start": str(q2_s), "end": str(q2_e), "revenue": 2.2e10, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                {"fiscal_label": "Q1 FY27", "start": str(q3_s), "end": str(q3_e), "revenue": 2.6e10, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                {"fiscal_label": "Q2 FY27", "start": str(q4_s), "end": str(q4_e), "revenue": 3.0e10, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"}],
            "forward_intervals": [
                {"fiscal_label": "Q3 FY27", "start": str(start_d), "end": q_end},
                {"fiscal_label": "Q4 FY27", "start": str(q2_start), "end": str(q2_start + timedelta(days=90))},
                {"fiscal_label": "Q1 FY28", "start": str(q2_start + timedelta(days=91)), "end": str(q2_start + timedelta(days=181))},
                {"fiscal_label": "Q2 FY28", "start": str(q2_start + timedelta(days=182)), "end": str(q2_start + timedelta(days=272))}],
            # The official IR channel (Astra W1 ruling, astra-ir-coverage): the company-guidance path requires
            # SEC_WIRE_IR coverage, so the record carries its IR feed and the receipt its ISSUER_IR channel.
            "release_channels": {
                "ir": {"kind": "Q4_PRESS_RELEASES",
                       "url": "https://investor.nvidia.com/feed/PressRelease.svc/GetPressReleaseList"},
                "ir_guidance_release_title": "NVIDIA Announces Financial Results for Second Quarter Fiscal 2027",
            },
        }
        chk_through = min(checked_at[:10], CUTOFF.strftime("%Y-%m-%d"))
        receipt = {
            "issuer": "NVDA", "checked_at": checked_at, "status": "OK",
            "guidance_document_id": "DOC-1", "guidance_published_date": published,
            "anchor_end": str(anchor_end_d), "coverage": "SEC_WIRE_IR",
            "channels": [
                {"kind": "SEC_SUBMISSIONS", "url": "https://data.sec.gov/submissions/CIK0000000000.json", "status": "OK", "checked_through": chk_through, "complete": True},
                {"kind": "WIRE_PRESS_RELEASES", "url": "https://api.nasdaq.com/api/news/topic/press_release?q=symbol:NVDA", "status": "OK", "checked_through": chk_through, "complete": True},
                {"kind": "ISSUER_IR", "url": "https://investor.nvidia.com/feed/PressRelease.svc/GetPressReleaseList", "status": "OK", "checked_through": chk_through, "complete": True},
            ],
            "later_documents": [],
        }
        receipt["digest"] = revenue_guidance.compute_receipt_digest(receipt)
        cache = {"schema": "revenue-guidance-release-checks-v1", "generated_at": checked_at, "issuers": {"NVDA": [receipt]}}
        return record, cache

    def test_quarter_end_day_itself_is_not_yet_ended(self):
        # Cutoff day equals the quarter end: the quarter is not yet ended, no bridge warning.
        rec, cache = self._record("2026-09-28", "2026-09-28T09:00:00Z")
        res = revenue_guidance.build_forward_quarters("NVDA", rec, CUTOFF, cache)
        self.assertEqual(res["status"], "AVAILABLE")
        self.assertIsNone(res["warning"])

    def test_quarter_ended_next_day_gets_warning(self):
        rec, cache = self._record("2026-09-27", "2026-09-28T09:00:00Z")
        res = revenue_guidance.build_forward_quarters("NVDA", rec, CUTOFF, cache)
        self.assertEqual(res["status"], "AVAILABLE")
        self.assertIsNotNone(res["warning"])

    def test_receipt_exactly_24h_old_is_eligible(self):
        rec, cache = self._record("2026-08-28", "2026-09-27T12:00:00Z")
        res = revenue_guidance.build_forward_quarters("NVDA", rec, CUTOFF, cache)
        self.assertEqual(res["status"], "AVAILABLE")

    def test_guidance_exactly_200_days_is_eligible(self):
        # 200 days before 2026-09-28 is 2026-03-12.
        rec, cache = self._record("2026-08-28", "2026-09-28T09:00:00Z", published="2026-03-12")
        res = revenue_guidance.build_forward_quarters("NVDA", rec, CUTOFF, cache)
        self.assertEqual(res["status"], "AVAILABLE")

    def test_guidance_201_days_old_is_not_eligible(self):
        rec, cache = self._record("2026-08-28", "2026-09-28T09:00:00Z", published="2026-03-11")
        res = revenue_guidance.build_forward_quarters("NVDA", rec, CUTOFF, cache)
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "STALE")


class TestReceiptTamper(unittest.TestCase):
    """Item 1/9: a runtime-cache receipt is re-validated (digest, status rules) in Python."""

    def _cache_receipt(self, symbol: str, anchor_end: str, guidance_doc: str, checked_at: str = "2026-09-28T11:00:00Z"):
        receipt = {
            "issuer": symbol, "checked_at": checked_at, "status": "OK", "guidance_document_id": guidance_doc,
            "guidance_published_date": "2026-08-20", "anchor_end": anchor_end, "coverage": "SEC_AND_WIRE",
            "channels": [
                {"kind": "SEC_SUBMISSIONS", "url": "https://data.sec.gov/submissions/CIK0001045810.json",
                 "status": "OK", "checked_through": "2026-09-28", "complete": True},
                {"kind": "WIRE_PRESS_RELEASES", "url": "https://api.nasdaq.com/api/news/topic/press_release?q=symbol:NVDA",
                 "status": "OK", "checked_through": "2026-09-28", "complete": True},
            ],
            "later_documents": [],
        }
        receipt["digest"] = revenue_guidance.compute_receipt_digest(receipt)
        return {"schema": "revenue-guidance-release-checks-v1", "generated_at": checked_at, "issuers": {symbol: [receipt]}}

    def test_valid_cache_receipt_passes(self):
        record = {"symbol": "NVDA", "status": "GUIDANCE", "url_prefixes": ["https://investor.nvidia.com/"],
                  "documents": [], "claims": [], "reported_quarters": [], "forward_intervals": [
                      {"start": "2026-07-27", "end": "2026-10-25"}, {"start": "2026-10-26", "end": "2027-01-31"},
                      {"start": "2027-02-01", "end": "2027-05-02"}, {"start": "2027-05-03", "end": "2027-08-01"}]}
        # No claims: the model is unquantified, so prove the receipt path alone via a tamper probe instead.
        valid, status, err = revenue_guidance.validate_receipt(
            self._cache_receipt("NVDA", "2026-07-26", "NVDA-GUIDANCE")["issuers"]["NVDA"][0],
            "NVDA", "2026-07-26", "NVDA-GUIDANCE", CUTOFF)
        self.assertTrue(valid, err)
        self.assertEqual(status, "OK")

    def test_digest_tamper_fails(self):
        cache = self._cache_receipt("NVDA", "2026-07-26", "NVDA-GUIDANCE")
        receipt = cache["issuers"]["NVDA"][0]
        receipt["guidance_document_id"] = "FORGED-DOC"  # breaks the digest
        valid, status, _ = revenue_guidance.validate_receipt(receipt, "NVDA", "2026-07-26", "NVDA-GUIDANCE", CUTOFF)
        self.assertFalse(valid)
        self.assertEqual(status, "INVALID")

    def test_results_release_receipt_is_stale(self):
        cache = self._cache_receipt("NVDA", "2026-07-26", "NVDA-GUIDANCE")
        receipt = cache["issuers"]["NVDA"][0]
        receipt["later_documents"] = [{"channel": "WIRE_PRESS_RELEASES", "date": "2026-09-20", "id": "wire-1",
                                       "label": "NVIDIA reports Q3 revenue", "disposition": "RESULTS_RELEASE"}]
        # status must be recomputed from the later documents; a stale OK status is a recompute mismatch.
        valid, status, _ = revenue_guidance.validate_receipt(receipt, "NVDA", "2026-07-26", "NVDA-GUIDANCE", CUTOFF)
        self.assertFalse(valid)
        self.assertEqual(status, "INVALID")


class TestBuildV3States(unittest.TestCase):
    """Items 4/11/14: registry state distinctions and the sealable missing-history path through build_v3."""

    def setUp(self):
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        if str(root / "scripts") not in sys.path:
            sys.path.insert(0, str(root / "scripts"))
        import order_forecast as ofc
        self.ofc = ofc
        self.cutoff = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
        self.report_day = date(2026, 9, 28)
        self.claims = {"status": "EMPTY", "sha256": "0" * 64, "issuers": {}}

    def _record(self, actuals, with_anchor=False):
        rec = {"symbol": "TEST", "company_name": "Test Co", "status": "GUIDANCE", "url_prefixes": ["https://investor.test.com/"],
               "documents": [{"id": "DOC-1", "issuer": "TEST", "publisher": "Test Co",
                              "source_kind": "ISSUER_EARNINGS_RELEASE", "url": "https://investor.test.com/q2.pdf",
                              "published_date": "2026-08-20", "retrieved_at": "2026-08-20T12:00:00Z",
                              "sha256": "1" * 64, "byte_size": 2048, "lineage_id": "L1"}],
               "claims": [{"id": "CLAIM-1", "document_id": "DOC-1", "locator": "p.1",
                           "passage": "Revenue outlook is 32.5 billion", "metric": "REVENUE",
                           "assertion_kind": "COMPANY_GUIDANCE", "currency": "USD", "unit_multiplier": 1000000000,
                           "stated_point": 32.5, "original_representation": "32.5 billion", "scope": "COMPANY",
                           "accounting_basis": "GAAP", "fiscal_label": "Q3 FY26", "period_kind": "QUARTER",
                           "period_start": "2026-08-01", "period_end": "2026-10-31"}],
               "reported_quarters": [
                   {**q, "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"} for q in actuals
               ],
               "forward_intervals": [{"fiscal_label": "Q3 FY26", "start": "2026-08-01", "end": "2026-10-31", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.9)"},
                                      {"fiscal_label": "Q4 FY26", "start": "2026-11-01", "end": "2027-01-31", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.9)"},
                                      {"fiscal_label": "Q1 FY27", "start": "2027-02-01", "end": "2027-04-30", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.9)"},
                                      {"fiscal_label": "Q2 FY27", "start": "2027-05-01", "end": "2027-07-31", "calendar_document_id": "DOC-1", "calendar_locator": "Fiscal calendar (p.9)"}],
               # The official IR channel (Astra W1 ruling, astra-ir-coverage): the company-guidance path requires
               # SEC_WIRE_IR coverage, so the record carries its IR feed and the receipt its ISSUER_IR channel.
               "release_channels": {
                   "ir": {"kind": "Q4_PRESS_RELEASES",
                          "url": "https://investor.test.com/feed/PressRelease.svc/GetPressReleaseList"},
                   "ir_guidance_release_title": "Test Co Reports Financial Results",
               }}
        if with_anchor:
            rec["anchor_end"] = "2026-07-31"
        return rec

    def _reg(self, record):
        return {"status": "OK", "sha256": "a" * 64, "issuers": {record["symbol"]: record}}

    def _cache(self, symbol="TEST", anchor_end="2026-07-31"):
        rc = {
            "issuer": symbol, "checked_at": "2026-09-28T09:00:00Z", "status": "OK",
            "guidance_document_id": "DOC-1", "guidance_published_date": "2026-08-20", "anchor_end": anchor_end,
            "coverage": "SEC_WIRE_IR",
            "channels": [
                {"kind": "SEC_SUBMISSIONS", "url": "https://data.sec.gov/submissions/CIK0000000000.json", "status": "OK", "checked_through": "2026-09-28", "complete": True},
                {"kind": "WIRE_PRESS_RELEASES", "url": "https://api.nasdaq.com/api/news/topic/press_release?q=symbol:" + symbol, "status": "OK", "checked_through": "2026-09-28", "complete": True},
                {"kind": "ISSUER_IR", "url": "https://investor.test.com/feed/PressRelease.svc/GetPressReleaseList", "status": "OK", "checked_through": "2026-09-28", "complete": True},
            ],
            "later_documents": [],
        }
        rc["digest"] = revenue_guidance.compute_receipt_digest(rc)
        return {"schema": "revenue-guidance-release-checks-v1", "generated_at": "2026-09-28T09:00:00Z", "issuers": {symbol: [rc]}}

    def test_missing_history_path_is_sealable(self):
        # Two actuals plus an independently verified anchor: amounts stay available, the price scenario is NO_REVENUE_HISTORY.
        actuals = [{"fiscal_label": "Q1 FY26", "start": "2026-02-01", "end": "2026-04-30", "revenue": 26.0e9, "currency": "USD"},
                   {"fiscal_label": "Q2 FY26", "start": "2026-05-01", "end": "2026-07-31", "revenue": 30.0e9, "currency": "USD"}]
        rec = self._record(actuals, with_anchor=True)
        reg = self._reg(rec)
        v3 = self.ofc.build_v3("TEST", None, None, self.report_day, self.cutoff, self.claims,
                               revenue_registry=reg, release_checks_cache=self._cache("TEST", "2026-07-31"),
                               revenue_approval=make_synthetic_approval(reg["sha256"], reg["issuers"]))
        self.assertEqual(v3["revenue_status"], "AVAILABLE")
        self.assertIsNone(v3["baseline_b"])
        self.assertEqual(v3["m6"]["scenario"], {"status": "NO_BASIS", "reason": "NO_REVENUE_HISTORY"})
        self.assertEqual(v3["m6"]["start"], "2026-08-01")  # A + 1 day
        self.assertEqual(v3["m6"]["status"], "AVAILABLE")

    def test_issuer_absent_from_populated_registry_is_inputs_missing(self):
        reg = self._reg(self._record([]))
        v3 = self.ofc.build_v3("OTHER", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg)
        self.assertEqual(v3["revenue_status"], "UNAVAILABLE")
        self.assertEqual(v3["revenue_reason"], "INPUTS_MISSING")

    def test_invalid_registry_fails_closed_not_nondisclosed(self):
        reg = {"status": "INVALID", "sha256": "b" * 64, "issuers": {}}
        v3 = self.ofc.build_v3("TEST", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg)
        self.assertEqual(v3["revenue_reason"], "INVALID")

    def test_withdrawn_record_never_becomes_consensus(self):
        # Counterexample: a WITHDRAWN record with a consensus capture supplied must not read as AVAILABLE CONSENSUS.
        rec = self._record([{"fiscal_label": "Q2 FY26", "start": "2026-05-01", "end": "2026-07-31", "revenue": 30.0e9, "currency": "USD"}])
        rec["status"] = "WITHDRAWN"
        consensus = {"symbol": "TEST", "captured_at": "2026-09-28T08:00:00Z", "currency": "USD",
                     "quarters": [{"period": "0q", "end": "2026-09-30", "avg": 40.0e9, "analysts": 25}]}
        reg = self._reg(rec)
        v3 = self.ofc.build_v3("TEST", None, None, self.report_day, self.cutoff, self.claims,
                               revenue_registry=reg, consensus_cache=consensus,
                               revenue_approval=make_synthetic_approval(reg["sha256"], reg["issuers"]))
        self.assertEqual(v3["revenue_status"], "UNAVAILABLE")
        self.assertEqual(v3["revenue_reason"], "WITHDRAWN")
        self.assertIsNone(v3["revenue_basis"])

    def _be_receipt_cache(self, record):
        import revenue_guidance
        doc_id = next(c["document_id"] for c in record["claims"] if c["period_kind"] == "FISCAL_YEAR")
        pub = next(d["published_date"] for d in record["documents"] if d["id"] == doc_id)
        anchor = record.get("anchor_end") or max(q["end"] for q in record["reported_quarters"])
        rc = {
            "issuer": "BE", "checked_at": "2026-09-28T09:00:00Z", "status": "OK",
            "guidance_document_id": doc_id, "guidance_published_date": pub, "anchor_end": anchor,
            "coverage": "SEC_WIRE_IR",
            "channels": [
                {"kind": "SEC_SUBMISSIONS", "url": "https://data.sec.gov/submissions/CIK0001664703.json", "status": "OK",
                 "checked_through": "2026-09-28", "complete": True},
                {"kind": "WIRE_PRESS_RELEASES", "url": "https://api.nasdaq.com/api/news/topic/press_release?q=symbol:BE|assetclass:stocks",
                 "status": "OK", "checked_through": "2026-09-28", "complete": True},
                {"kind": "ISSUER_IR", "url": "https://investor.bloomenergy.com/feed/PressRelease.svc/GetPressReleaseList",
                 "status": "OK", "checked_through": "2026-09-28", "complete": True},
            ],
            "later_documents": [],
        }
        rc["digest"] = revenue_guidance.compute_receipt_digest(rc)
        return {"schema": "revenue-guidance-release-checks-v1", "generated_at": "2026-09-28T09:00:00Z", "issuers": {"BE": [rc]}}

    def test_fy_claim_start_and_span_are_checked(self):
        # Counterexample: a BE-style FY claim starting years before the YTD start (or spanning years) fails closed.
        import json as _json
        fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "revenue-guidance-issuers-r2.json"
        registry = _json.loads(fixture.read_text(encoding="utf-8"))
        import revenue_guidance
        be = _json.loads(_json.dumps(next(r for r in registry["issuers"] if r["symbol"] == "BE")))
        cache = self._be_receipt_cache(be)
        # Baseline: the as-registered record is fine.
        ok = revenue_guidance.build_forward_quarters("BE", be, self.cutoff, release_checks_cache=cache)
        self.assertEqual(ok["status"], "AVAILABLE", ok.get("reason"))
        # FY start moved to 2020 while YTD still starts 2026-01-01: period mismatch, refused.
        bad_start = _json.loads(_json.dumps(be))
        fy2 = next(c for c in bad_start["claims"] if c["period_kind"] == "FISCAL_YEAR")
        fy2["period_start"] = "2020-01-01"
        res = revenue_guidance.build_forward_quarters("BE", bad_start, self.cutoff, release_checks_cache=self._be_receipt_cache(bad_start))
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "PERIOD_MISMATCH")
        # FY span stretched to two years: refused.
        bad_span = _json.loads(_json.dumps(be))
        fy3 = next(c for c in bad_span["claims"] if c["period_kind"] == "FISCAL_YEAR")
        fy3["period_end"] = "2027-12-31"
        res2 = revenue_guidance.build_forward_quarters("BE", bad_span, self.cutoff, release_checks_cache=self._be_receipt_cache(bad_span))
        self.assertEqual(res2["status"], "UNAVAILABLE")
        self.assertEqual(res2["reason"], "INVALID")


class TestWriterRecordsGolden(unittest.TestCase):
    """Item 18/21: the writer's reviewed issuer records (tests/fixtures/revenue-guidance-issuers-r2.json)
    flow through the real Python caller at a fixed clock with a synthetic receipt cache."""

    def setUp(self):
        fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "revenue-guidance-issuers-r2.json"
        self.registry = json.loads(fixture.read_text(encoding="utf-8"))  # the registry root (schema/version/issuers)
        # After the writer's 14:45Z CRWV IR review (astra-ir-coverage data), so the reviewed item is admissible;
        # the strict reviewed_at <= cutoff rule is unchanged, only the build time moves past the review.
        self.cutoff = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)

    def _cache(self, symbol: str, anchor_end: str, guidance_doc: str, guidance_pub: str, checked_at: str = "2026-09-28T11:00:00Z",
               release_channels: dict | None = None):
        # The receipt's channel identity is bound to the record's reviewed release channels (Astra r5 item 2):
        # the SEC feed must be the issuer's own CIK and the wire feed its own symbol, not a placeholder.
        rc = release_channels or {}
        cik = rc.get("sec_cik")
        sec_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json" if cik else "https://data.sec.gov/submissions/CIK0000000000.json"
        wire_sym = rc.get("wire_symbol") or symbol
        channels = [
            {"kind": "SEC_SUBMISSIONS", "url": sec_url,
             "status": "OK", "checked_through": "2026-09-28", "complete": True},
            {"kind": "WIRE_PRESS_RELEASES", "url": f"https://api.nasdaq.com/api/news/topic/press_release?q=symbol:{wire_sym}|assetclass:stocks",
             "status": "OK", "checked_through": "2026-09-28", "complete": True},
        ]
        coverage = "SEC_AND_WIRE"
        ir = rc.get("ir")
        if isinstance(ir, dict) and isinstance(ir.get("url"), str):
            # The record's official IR channel (Astra W1 ruling, astra-ir-coverage): the synthetic receipt carries
            # its ISSUER_IR channel and the SEC_WIRE_IR coverage the company-guidance path now requires.
            channels.append({"kind": "ISSUER_IR", "url": ir["url"],
                             "status": "OK", "checked_through": "2026-09-28", "complete": True})
            coverage = "SEC_WIRE_IR"
        receipt = {
            "issuer": symbol, "checked_at": checked_at, "status": "OK", "guidance_document_id": guidance_doc,
            "guidance_published_date": guidance_pub, "anchor_end": anchor_end, "coverage": coverage,
            "channels": channels,
            "later_documents": [],
        }
        receipt["digest"] = revenue_guidance.compute_receipt_digest(receipt)
        return {"schema": "revenue-guidance-release-checks-v1", "generated_at": checked_at, "issuers": {symbol: [receipt]}}

    def test_registry_root_loads_and_all_records_validate(self):
        fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "revenue-guidance-issuers-r2.json"
        loaded = revenue_guidance.load_registry(fixture)
        self.assertEqual(loaded["status"], "OK")
        self.assertEqual(len(loaded["issuers"]), 16)
        for record in loaded["issuers"].values():
            with self.subTest(symbol=record["symbol"]):
                valid = revenue_guidance.validate_issuer_record(record)
                self.assertEqual(valid["symbol"], record["symbol"])

    def test_each_symbol_is_available_at_fixed_clock(self):
        expected = {
            # symbol: (anchor_end, guidance_doc, warning_expected, ir_channel_expected)
            # Astra W1 ruling (astra-ir-coverage): the nine issuers with a reviewed official IR channel keep the
            # company-guidance path AVAILABLE (SEC_WIRE_IR coverage); the five blocked issuers (no IR channel)
            # suspend it as FRESHNESS_UNVERIFIED with the distinct IR_COVERAGE_MISSING diagnostic.
            "SNDK": ("2026-07-03", "SNDK-GUIDANCE", False, False),
            "NVDA": ("2026-07-26", "NVDA-GUIDANCE", False, True),
            "MU": ("2026-05-28", "MU-GUIDANCE", True, True),      # FQ4-26 ends 2026-09-03, 25 days before cutoff
            "LITE": ("2026-06-27", "LITE-GUIDANCE", True, True),   # Q1 FY27 ends 2026-09-26, 2 days before cutoff
            "MRVL": ("2026-08-01", "MRVL-GUIDANCE", False, True),
            "AMD": ("2026-06-27", "AMD-GUIDANCE", True, True),     # Q3 2026 ends 2026-09-26, 2 days before cutoff
            "AVGO": ("2026-08-02", "AVGO-GUIDANCE", False, False),
            "MTSI": ("2026-07-03", "MTSI-GUIDANCE", False, False),
            "CRDO": ("2026-08-01", "CRDO-GUIDANCE", False, True),
            "AAOI": ("2026-06-30", "AAOI-GUIDANCE", False, False),
            "ALAB": ("2026-06-30", "ALAB-GUIDANCE", False, False),
            "BE": ("2026-06-30", "BE-GUIDANCE", False, True),     # FY path (BE-FY-GUIDANCE)
            "NBIS": ("2026-06-30", "NBIS-GUIDANCE", False, True),  # FY path; the check starts at the August reaffirmation
            "CRWV": ("2026-06-30", "CRWV-GUIDANCE", False, True), # Q + FY concurrent path
        }
        for symbol, (anchor_end, guidance_doc, warning_expected, ir_expected) in expected.items():
            with self.subTest(symbol=symbol):
                record = next(r for r in self.registry["issuers"] if r["symbol"] == symbol)
                valid = revenue_guidance.validate_issuer_record(record)
                guidance_pub = next(d["published_date"] for d in record["documents"] if d["id"] == guidance_doc)
                cache = self._cache(symbol, anchor_end, guidance_doc, guidance_pub,
                                    release_channels=record.get("release_channels"))
                res = revenue_guidance.build_forward_quarters(symbol, valid, self.cutoff, cache)
                if ir_expected:
                    self.assertEqual(res["status"], "AVAILABLE", f"{symbol}: {res}")
                    self.assertEqual(res["basis_type"], "COMPANY_GUIDANCE")
                    if warning_expected:
                        self.assertIsNotNone(res["warning"], f"{symbol} should carry the bridge warning")
                    else:
                        self.assertIsNone(res["warning"], f"{symbol} should not carry a warning")
                else:
                    # No reviewed official IR channel: the company-guidance path suspends with the distinct
                    # diagnostic (never NOT_DISCLOSED, zero or consensus); order recognition stays independent.
                    self.assertEqual(res["status"], "UNAVAILABLE", f"{symbol}: {res}")
                    self.assertEqual(res["reason"], "FRESHNESS_UNVERIFIED")
                    self.assertEqual(res["diagnostic"], "IR_COVERAGE_MISSING")

    def test_be_fy_path_allocates_remaining_quarters(self):
        record = next(r for r in self.registry["issuers"] if r["symbol"] == "BE")
        valid = revenue_guidance.validate_issuer_record(record)
        pub = next(d["published_date"] for d in record["documents"] if d["id"] == "BE-GUIDANCE")
        cache = self._cache("BE", "2026-06-30", "BE-GUIDANCE", pub, release_channels=record.get("release_channels"))
        res = revenue_guidance.build_forward_quarters("BE", valid, self.cutoff, cache)
        self.assertEqual(res["status"], "AVAILABLE")
        # FY midpoint (3.9+4.2)/2 = 4.05e9; YTD 1.816419e9; R = 2.233581e9 over n=2 -> 1.1167905e9 per quarter.
        self.assertAlmostEqual(res["f1"], (4.05e9 - 1816419000.0) / 2, places=9)
        self.assertEqual(res["f1"], res["f2"])  # n=2: both remaining quarters carry the FY allocation


class TestAstraR2Counterexamples(unittest.TestCase):
    """Explicit tests for all executed counterexamples from Astra acceptance review r2."""

    def setUp(self):
        self.cutoff = CUTOFF

    def _sample_valid_record(self):
        return {
            "symbol": "NVDA",
            "company_name": "NVIDIA Corporation",
            "status": "GUIDANCE",
            "url_prefixes": ["https://investor.nvidia.com/"],
            "documents": [
                {
                    "id": "DOC-1",
                    "issuer": "NVDA",
                    "publisher": "NVIDIA Corporation",
                    "title": "Earnings Release",
                    "source_kind": "ISSUER_EARNINGS_RELEASE",
                    "url": "https://investor.nvidia.com/release.pdf",
                    "published_date": "2026-08-20",
                    "retrieved_at": "2026-08-20T12:00:00Z",
                    "sha256": "0" * 64,
                    "byte_size": 1000,
                    "lineage_id": "L1",
                }
            ],
            "claims": [
                {
                    "id": "CLAIM-1",
                    "document_id": "DOC-1",
                    "locator": "p.1",
                    "passage": "Revenue is expected to be $32.5 billion",
                    "metric": "REVENUE",
                    "assertion_kind": "COMPANY_GUIDANCE",
                    "currency": "USD",
                    "unit_multiplier": 1000000000,
                    "stated_point": 32.5,
                    "scope": "COMPANY",
                    "accounting_basis": "GAAP",
                    "fiscal_label": "Q3 FY27",
                    "period_kind": "QUARTER",
                    "period_start": "2026-07-27",
                    "period_end": "2026-10-25",
                }
            ],
            "reported_quarters": [
                {"fiscal_label": "Q3 FY26", "start": "2025-07-28", "end": "2025-10-26", "revenue": 1.8e10, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                {"fiscal_label": "Q4 FY26", "start": "2025-10-27", "end": "2026-01-25", "revenue": 2.2e10, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                {"fiscal_label": "Q1 FY27", "start": "2026-01-26", "end": "2026-04-26", "revenue": 2.6e10, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
                {"fiscal_label": "Q2 FY27", "start": "2026-04-27", "end": "2026-07-26", "revenue": 3.0e10, "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": "DOC-1", "locator": "p.1"},
            ],
            "forward_intervals": [
                {"fiscal_label": "Q3 FY27", "start": "2026-07-27", "end": "2026-10-25"},
                {"fiscal_label": "Q4 FY27", "start": "2026-10-26", "end": "2027-01-31"},
                {"fiscal_label": "Q1 FY28", "start": "2027-02-01", "end": "2027-05-02"},
                {"fiscal_label": "Q2 FY28", "start": "2027-05-03", "end": "2027-08-01"},
            ],
            # The official IR channel (Astra W1 ruling, astra-ir-coverage): the company-guidance path requires
            # SEC_WIRE_IR coverage, so the record carries its IR feed and the receipt its ISSUER_IR channel.
            "release_channels": {
                "ir": {"kind": "Q4_PRESS_RELEASES",
                       "url": "https://investor.nvidia.com/feed/PressRelease.svc/GetPressReleaseList"},
                "ir_guidance_release_title": "NVIDIA Announces Financial Results for Second Quarter Fiscal 2027",
            },
        }

    def _sample_cache(self, symbol="NVDA", anchor="2026-07-26", release_channels=None):
        # Channel identity bound to the record's reviewed release channels (Astra r5 item 2), placeholder when unreviewed.
        rc = release_channels or {}
        cik = rc.get("sec_cik")
        sec_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json" if cik else "https://data.sec.gov/submissions/CIK0000000000.json"
        wire_sym = rc.get("wire_symbol") or symbol
        wire_url = f"https://api.nasdaq.com/api/news/topic/press_release?q=symbol:{wire_sym}|assetclass:stocks"
        channels = [
            {"kind": "SEC_SUBMISSIONS", "url": sec_url, "status": "OK", "checked_through": "2026-09-28", "complete": True},
            {"kind": "WIRE_PRESS_RELEASES", "url": wire_url, "status": "OK", "checked_through": "2026-09-28", "complete": True},
        ]
        coverage = "SEC_AND_WIRE"
        ir = rc.get("ir")
        if isinstance(ir, dict) and isinstance(ir.get("url"), str):
            # The record's official IR channel (Astra W1 ruling, astra-ir-coverage): the receipt carries its channel.
            channels.append({"kind": "ISSUER_IR", "url": ir["url"], "status": "OK", "checked_through": "2026-09-28", "complete": True})
            coverage = "SEC_WIRE_IR"
        receipt = {
            "issuer": symbol,
            "checked_at": "2026-09-28T10:00:00Z",
            "status": "OK",
            "guidance_document_id": "DOC-1",
            "guidance_published_date": "2026-08-20",
            "anchor_end": anchor,
            "coverage": coverage,
            "channels": channels,
            "later_documents": [],
        }
        receipt["digest"] = revenue_guidance.compute_receipt_digest(receipt)
        return {"schema": "revenue-guidance-release-checks-v1", "generated_at": "2026-09-28T10:00:00Z", "issuers": {symbol: [receipt]}}

    def test_requested_issuer_nvda_record_doc_issuers_other(self):
        rec = self._sample_valid_record()
        rec["symbol"] = "OTHER"
        rec["documents"][0]["issuer"] = "OTHER"
        res = revenue_guidance.build_forward_quarters("NVDA", rec, self.cutoff, self._sample_cache())
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "INVALID")

    def test_actual_scope_segment_fails_validation(self):
        rec = self._sample_valid_record()
        rec["reported_quarters"][0]["scope"] = "SEGMENT"
        with self.assertRaises(revenue_guidance.GuidanceError):
            revenue_guidance.validate_issuer_record(rec)

    def test_claim_withdrawn_fails(self):
        rec = self._sample_valid_record()
        rec["claims"][0]["revision"] = {"kind": "WITHDRAWN"}
        res = revenue_guidance.build_forward_quarters("NVDA", rec, self.cutoff, self._sample_cache())
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "WITHDRAWN")

    def test_future_document_retrieval_fails(self):
        rec = self._sample_valid_record()
        rec["documents"][0]["retrieved_at"] = "2026-09-29T12:00:00Z"
        res = revenue_guidance.build_forward_quarters("NVDA", rec, self.cutoff, self._sample_cache())
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "INVALID")

    def test_future_claim_reviews_fails(self):
        rec = self._sample_valid_record()
        rec["claims"][0]["checked_at"] = "2026-09-29T12:00:00Z"
        res = revenue_guidance.build_forward_quarters("NVDA", rec, self.cutoff, self._sample_cache())
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "INVALID")

    def test_be_ytd_window_moved_to_2020(self):
        fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "revenue-guidance-issuers-r2.json"
        with fixture.open(encoding="utf-8") as f:
            reg = json.load(f)
        be_rec = next(r for r in reg["issuers"] if r["symbol"] == "BE")
        be_tampered = json.loads(json.dumps(be_rec))
        be_tampered["fy_reconciliation"]["ytd_start"] = "2020-01-01"
        be_tampered["fy_reconciliation"]["ytd_end"] = "2020-06-30"
        pub = next(d["published_date"] for d in be_tampered["documents"] if d["id"] == "BE-GUIDANCE")
        cache = self._sample_cache("BE", "2026-06-30", release_channels=be_tampered.get("release_channels"))
        cache["issuers"]["BE"][0]["guidance_document_id"] = "BE-GUIDANCE"
        cache["issuers"]["BE"][0]["guidance_published_date"] = pub
        cache["issuers"]["BE"][0]["digest"] = revenue_guidance.compute_receipt_digest(cache["issuers"]["BE"][0])
        res = revenue_guidance.build_forward_quarters("BE", be_tampered, self.cutoff, cache)
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertEqual(res["reason"], "PERIOD_MISMATCH")

    def test_bool_low_with_point_fails(self):
        claim = {"id": "C1", "low": True, "high": 200, "stated_point": 120}
        with self.assertRaises(revenue_guidance.GuidanceError):
            revenue_guidance.compute_model_point(claim)

    def test_close_finite_only(self):
        self.assertFalse(revenue_guidance.close(math.inf, 1))
        self.assertFalse(revenue_guidance.close(1, math.inf))
        self.assertFalse(revenue_guidance.close(1.0, True))
        self.assertFalse(revenue_guidance.close(False, 0.0))

    def test_registry_symbol_is_a_list(self):
        import tempfile
        bad_reg = {"schema": "revenue-guidance-v1", "version": 1, "issuers": [{"symbol": []}]}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
            json.dump(bad_reg, tf)
            tf_path = Path(tf.name)
        try:
            loaded = revenue_guidance.load_registry(tf_path)
            self.assertEqual(loaded["status"], "INVALID")
        finally:
            tf_path.unlink()

    def test_consensus_malformed_plus1q_rejected(self):
        fake_data = {
            "quoteSummary": {
                "result": [
                    {
                        "financialData": {"financialCurrency": "KRW"},
                        "earningsTrend": {
                            "trend": [
                                {"period": "0q", "endDate": "2026-09-30", "revenueEstimate": {"avg": 10e12, "numberOfAnalysts": 20}},
                                {"period": "+1q", "endDate": "2026-12-31", "revenueEstimate": {"avg": "malformed_string", "numberOfAnalysts": 20}},
                            ]
                        }
                    }
                ]
            }
        }
        res = revenue_consensus_quarterly.extract_quarterly_consensus("000660.KS", fake_data, datetime.now(timezone.utc))
        self.assertIsNone(res)

    def test_receipt_unicode_canonicalization(self):
        import hashlib
        obj = {"label": "실적 公告", "channels": [{"kind": "SEC_SUBMISSIONS"}]}
        canon = revenue_guidance.canonical_json(obj)
        digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        # SHA matches Node's crypto on same UTF-8 byte stream
        self.assertEqual(digest, "077ce0478f32d8a2e43e84121a7737a3d6b050ed62dc1dc39631d85b68f4c333")

    def test_rehashed_receipt_with_fake_channel_or_future_checked_through(self):
        cache = self._sample_cache()
        rc = cache["issuers"]["NVDA"][0]
        rc["channels"] = [{"kind": "FAKE", "url": "https://bad.url", "status": "OK", "complete": True, "checked_through": "2099-01-01"}]
        rc["digest"] = revenue_guidance.compute_receipt_digest(rc)
        valid, status, _ = revenue_guidance.validate_receipt(rc, "NVDA", "2026-07-26", "DOC-1", self.cutoff)
        self.assertFalse(valid)
        self.assertIn(status, ("INVALID", "FRESHNESS_UNVERIFIED"))


class TestReviewedProfile(unittest.TestCase):
    """A1 (Astra acceptance r7): the enforced reviewed profile beside the registry, and the A3/A6 consensus gate.

    Every failure mode suspends the issuer's revenue path as UNAVAILABLE / INVALID with the distinct
    UNREVIEWED_INPUTS diagnostic; the independent order recognition is never affected. The writer fills the real
    config/revenue-guidance-approval-v1.json; these tests use synthetic profiles through the real caller.
    """

    def setUp(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        import sys as _sys
        if str(root / "scripts") not in _sys.path:
            _sys.path.insert(0, str(root / "scripts"))
        import order_forecast as ofc
        self.ofc = ofc
        self.cutoff = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)
        self.report_day = date(2026, 9, 28)
        self.claims = {"status": "EMPTY", "sha256": "0" * 64, "issuers": {}}
        self.fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "revenue-guidance-issuers-r2.json"
        self.registry = json.loads(self.fixture.read_text(encoding="utf-8"))
        self.approval_fixture = json.loads(
            (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "revenue-guidance-approval-v1.json").read_text(encoding="utf-8"))

    def _reg(self, symbol: str, sha: str | None = None, consensus_enabled: bool | None = None) -> dict:
        record = next(r for r in self.registry["issuers"] if r["symbol"] == symbol)
        reg = {"status": "OK", "sha256": sha or "a" * 64, "issuers": {record["symbol"]: record}}
        if consensus_enabled is not None:
            reg["consensus_enabled"] = consensus_enabled
        return reg

    def _approval_for(self, reg: dict, symbol: str, reviewed_at: str = "2026-09-28T11:00:00Z") -> dict:
        return make_synthetic_approval(reg["sha256"], {symbol: reg["issuers"][symbol]}, reviewed_at=reviewed_at)

    def test_missing_approval_fails_closed_with_unreviewed_inputs(self):
        reg = self._reg("NVDA")
        v3 = self.ofc.build_v3("NVDA", None, None, self.report_day, self.cutoff, self.claims,
                               revenue_registry=reg,
                               revenue_approval={"status": "UNAVAILABLE", "sha256": None, "registry_sha256": None,
                                                 "approved_at": None, "reviewer": None, "records": {}})
        self.assertEqual(v3["revenue_status"], "UNAVAILABLE")
        self.assertEqual(v3["revenue_reason"], "INVALID")
        self.assertEqual(v3["revenue_diagnostic"], "UNREVIEWED_INPUTS")
        # The approval's absence is sealed as explicit nulls beside the evidence.
        self.assertIsNone(v3["evidence"]["approval_sha256"])
        self.assertIsNone(v3["evidence"]["approval_approved_at"])
        self.assertIsNone(v3["evidence"]["approval_decisions"])

    def test_pending_skeleton_approves_nothing(self):
        # The writer's pending config file (null registry identity, no records) admits no issuer.
        reg = self._reg("NVDA")
        v3 = self.ofc.build_v3("NVDA", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                               revenue_approval={"status": "OK", "sha256": "e" * 64, "registry_sha256": None,
                                                 "approved_at": None, "reviewer": None, "records": {}})
        self.assertEqual(v3["revenue_diagnostic"], "UNREVIEWED_INPUTS")

    def test_registry_bytes_tamper_fails_closed(self):
        reg = self._reg("NVDA", sha="a" * 64)
        approval = self._approval_for(reg, "NVDA")
        approval["registry_sha256"] = "b" * 64  # the registry bytes changed since the approval was sealed
        v3 = self.ofc.build_v3("NVDA", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                               revenue_approval=approval)
        self.assertEqual(v3["revenue_diagnostic"], "UNREVIEWED_INPUTS")

    def test_nvda_first_actual_plus_one_billion_fails_closed(self):
        # Astra's A1 executed case: the first non-derived actual rises by +USD 1 billion with the quoted source,
        # locator and review unchanged - the record hash moves, the profile no longer covers the record, and the
        # revenue path suspends while the independent recognition survives.
        reg = self._reg("NVDA")
        record = reg["issuers"]["NVDA"]
        approval = self._approval_for(reg, "NVDA")
        actuals = record["reported_quarters"]
        idx = next(i for i, q in enumerate(actuals) if q.get("derivation") is None)
        tampered = json.loads(json.dumps(actuals[idx]))
        tampered["revenue"] = tampered["revenue"] + 1.0e9
        record["reported_quarters"] = [tampered if i == idx else q for i, q in enumerate(actuals)]
        rec_order = {"status": "DISCLOSED", "form": "10-Q", "filed": "2026-08-26", "url": "https://www.sec.gov/fixture",
                     "rpo": 3.2e9, "rpo_as_of": "2026-07-26", "quarter_revenue": 96.221e9, "quarter_end": "2026-07-26",
                     "quarter_start": "2026-04-27", "quarter_basis": "FRAME", "accession": "0001045810-26-000075",
                     "passage": "fixture passage", "report_date": "2026-07-26",
                     "horizons": {"m6": None, "m12": {"share_pct": 39, "derived": False}}}
        v3 = self.ofc.build_v3("NVDA", None, rec_order, self.report_day, self.cutoff, self.claims,
                               revenue_registry=reg, revenue_approval=approval)
        self.assertEqual(v3["revenue_status"], "UNAVAILABLE")
        self.assertEqual(v3["revenue_reason"], "INVALID")
        self.assertEqual(v3["revenue_diagnostic"], "UNREVIEWED_INPUTS")
        # Independent recognition survives the revenue suspension (A4 containment of the scoped state).
        self.assertEqual(v3["m12"]["status"], "AVAILABLE")
        self.assertEqual(v3["m12"]["basis"], "RECOGNITION")
        self.assertAlmostEqual(v3["m12"]["amount"], 1.248e9, places=6)
        self.assertEqual(v3["m6"]["status"], "UNAVAILABLE")
        self.assertEqual(v3["m6"]["reason"], "INVALID")

    def test_missing_calendar_decision_fails_closed(self):
        reg = self._reg("NVDA")
        approval = self._approval_for(reg, "NVDA")
        approval["records"]["NVDA"]["decisions"] = [
            d for d in approval["records"]["NVDA"]["decisions"] if d["kind"] != "CALENDAR"]
        v3 = self.ofc.build_v3("NVDA", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                               revenue_approval=approval)
        self.assertEqual(v3["revenue_diagnostic"], "UNREVIEWED_INPUTS")

    def test_review_after_cutoff_fails_closed(self):
        reg = self._reg("NVDA")
        approval = self._approval_for(reg, "NVDA", reviewed_at="2026-09-28T16:00:00Z")  # after the 15:00 cutoff
        v3 = self.ofc.build_v3("NVDA", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                               revenue_approval=approval)
        self.assertEqual(v3["revenue_diagnostic"], "UNREVIEWED_INPUTS")

    def test_review_before_document_retrieval_fails_closed(self):
        reg = self._reg("NVDA")
        approval = self._approval_for(reg, "NVDA", reviewed_at="2026-01-01T00:00:00Z")  # before the record's retrievals
        v3 = self.ofc.build_v3("NVDA", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                               revenue_approval=approval)
        self.assertEqual(v3["revenue_diagnostic"], "UNREVIEWED_INPUTS")

    def test_approved_profile_keeps_the_path_admitted(self):
        # With the profile admitting the record, the guidance path proceeds to its own checks (here: suspended for the
        # missing receipt, never UNREVIEWED_INPUTS) and the approval's identity plus the record's decisions seal
        # beside the evidence.
        reg = self._reg("NVDA")
        approval = self._approval_for(reg, "NVDA")
        v3 = self.ofc.build_v3("NVDA", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                               revenue_approval=approval)
        self.assertNotEqual(v3["revenue_diagnostic"], "UNREVIEWED_INPUTS")
        self.assertEqual(v3["revenue_status"], "UNAVAILABLE")
        self.assertEqual(v3["revenue_reason"], "FRESHNESS_UNVERIFIED")  # no receipt cache in this test
        self.assertEqual(v3["evidence"]["approval_sha256"], approval["sha256"])
        self.assertEqual(v3["evidence"]["approval_approved_at"], approval["approved_at"])
        self.assertEqual(v3["evidence"]["approval_decisions"], approval["records"]["NVDA"]["decisions"])
        self.assertFalse(v3["evidence"]["consensus_enabled"])  # the fixture registry carries no gate: disabled

    def test_consensus_deferred_when_the_gate_is_off(self):
        # A3/A6: with the gate off, a NOT_DISCLOSED record with a consensus capture available stays NOT_DISCLOSED
        # with the distinct CONSENSUS_DEFERRED diagnostic - never routed to the capture.
        reg = self._reg("000660.KS", consensus_enabled=False)
        consensus = {"000660.KS": {"symbol": "000660.KS", "captured_at": "2026-09-28T08:00:00Z", "currency": "KRW",
                                   "quarters": [{"period": "0q", "end": "2026-09-30", "revenue": 15e12, "analysts": 25}]}}
        v3 = self.ofc.build_v3("000660.KS", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                               consensus_cache=consensus, revenue_approval=self._approval_for(reg, "000660.KS"))
        self.assertEqual(v3["revenue_status"], "UNAVAILABLE")
        self.assertEqual(v3["revenue_reason"], "NOT_DISCLOSED")
        self.assertEqual(v3["revenue_diagnostic"], "CONSENSUS_DEFERRED")
        self.assertIsNone(v3["revenue_basis"])
        self.assertIsNone(v3["evidence"]["consensus"])
        self.assertFalse(v3["evidence"]["consensus_enabled"])

    def test_missing_gate_fails_closed_to_deferred(self):
        # The gate is explicit: a registry root without the flag defers the consensus route (first-rollout default).
        reg = self._reg("000660.KS")  # no consensus_enabled key at the root
        v3 = self.ofc.build_v3("000660.KS", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                               revenue_approval=self._approval_for(reg, "000660.KS"))
        self.assertEqual(v3["revenue_reason"], "NOT_DISCLOSED")
        self.assertEqual(v3["revenue_diagnostic"], "CONSENSUS_DEFERRED")

    def test_gate_on_still_routes_to_the_consensus(self):
        reg = self._reg("000660.KS", consensus_enabled=True)
        consensus = {"000660.KS": {"symbol": "000660.KS", "captured_at": "2026-09-28T08:00:00Z", "currency": "KRW",
                                   "quarters": [{"period": "0q", "end": "2026-09-30", "revenue": 15e12, "analysts": 25},
                                                {"period": "+1q", "end": "2026-12-31", "revenue": 16e12, "analysts": 24}]}}
        v3 = self.ofc.build_v3("000660.KS", None, None, self.report_day, self.cutoff, self.claims, revenue_registry=reg,
                               consensus_cache=consensus, revenue_approval=self._approval_for(reg, "000660.KS"))
        self.assertEqual(v3["revenue_status"], "AVAILABLE")
        self.assertEqual(v3["revenue_basis"], "CONSENSUS")
        self.assertTrue(v3["evidence"]["consensus_enabled"])


class TestApprovalFileSchema(unittest.TestCase):
    """A1: the schema/loader of config/revenue-guidance-approval-v1.json (synthetic data; the writer owns the real file)."""

    def _write(self, tmp: Path, data: dict) -> Path:
        p = tmp / "approval.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_pending_skeleton_loads_ok_and_approves_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = self._write(tmp, {"schema": "revenue-guidance-approval-v1", "registry_sha256": None,
                                     "approved_at": None, "reviewer": None, "records": {}})
            loaded = revenue_guidance.load_approval(path)
            self.assertEqual(loaded["status"], "OK")
            self.assertIsNone(loaded["registry_sha256"])
            self.assertEqual(loaded["records"], {})
            # And it admits no issuer: the profile check reports the pending state.
            rec = {"symbol": "NVDA", "status": "GUIDANCE", "documents": [], "claims": [], "reported_quarters": [],
                   "forward_intervals": []}
            self.assertEqual(revenue_guidance.check_reviewed_profile("NVDA", rec, loaded, "a" * 64, datetime(2026, 9, 28, tzinfo=timezone.utc)),
                             "APPROVAL_PENDING")

    def test_valid_file_loads_with_decisions(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data = {"schema": "revenue-guidance-approval-v1", "registry_sha256": "a" * 64, "approved_at": "2026-09-28T14:45:00Z",
                    "reviewer": "writer", "records": {"NVDA": {"record_sha256": "b" * 64, "decisions": [
                        {"kind": "CALENDAR", "ref": "calendar", "decision": "RULE_QUOTED", "reviewed_at": "2026-09-28T14:45:00Z"},
                        {"kind": "ROUTING", "ref": "routing", "decision": "RULE_QUOTED", "reviewed_at": "2026-09-28T14:45:00Z"}]}}}
            loaded = revenue_guidance.load_approval(self._write(tmp, data))
            self.assertEqual(loaded["status"], "OK")
            self.assertEqual(loaded["registry_sha256"], "a" * 64)
            self.assertEqual(len(loaded["records"]["NVDA"]["decisions"]), 2)

    def test_malformed_shapes_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            good = {"schema": "revenue-guidance-approval-v1", "registry_sha256": "a" * 64, "approved_at": "2026-09-28T14:45:00Z",
                    "reviewer": "writer", "records": {}}
            cases = []
            bad_schema = dict(good, schema="nope")
            cases.append(bad_schema)
            cases.append({k: v for k, v in good.items() if k != "reviewer"})  # missing key
            cases.append(dict(good, registry_sha256="zzz"))  # not a sha256 hex
            cases.append(dict(good, approved_at="yesterday"))  # not an instant
            cases.append(dict(good, records=["not-a-dict"]))
            for bad in cases:
                with self.subTest(bad=bad):
                    self.assertEqual(revenue_guidance.load_approval(self._write(tmp, bad))["status"], "INVALID")
            bad_decision = dict(good, records={"NVDA": {"record_sha256": "b" * 64, "decisions": [
                {"kind": "NOPE", "ref": "x", "decision": "RULE_QUOTED", "reviewed_at": "2026-09-28T14:45:00Z"}]}})
            self.assertEqual(revenue_guidance.load_approval(self._write(tmp, bad_decision))["status"], "INVALID")
            bad_time = dict(good, records={"NVDA": {"record_sha256": "b" * 64, "decisions": [
                {"kind": "CALENDAR", "ref": "calendar", "decision": "RULE_QUOTED", "reviewed_at": "not-a-time"}]}})
            self.assertEqual(revenue_guidance.load_approval(self._write(tmp, bad_time))["status"], "INVALID")

    def test_missing_file_is_unavailable(self):
        loaded = revenue_guidance.load_approval(Path("/nonexistent/approval.json"))
        self.assertEqual(loaded["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
