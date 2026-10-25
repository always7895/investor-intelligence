#!/usr/bin/env python3
"""scripts/official_quarterly_revenue.py: the reviewed official comparative-quarter record (Astra contract
L18-5351-CURATED-01). Network-free; the config path and the clock are injected."""
from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import official_quarterly_revenue as oqr  # noqa: E402

NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
# Yahoo base-TWD totals equal to the official figures (TWD thousands x 1000); Q1 2025 is absent, as in Yahoo's frame.
YAHOO = {"2025-06-30": 744722000.0, "2025-09-30": 1.1e9, "2025-12-31": 1.9e9, "2026-03-31": 2735412000.0,
         "2026-06-30": 4898686000.0}
CURRENT_YOY = 4898686000.0 / 744722000.0 - 1


def config() -> dict:
    return json.loads(oqr.CONFIG.read_text(encoding="utf-8"))


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, document: object, raw: str | None = None) -> Path:
        path = Path(self.tmp.name) / "official.json"
        path.write_text(raw if raw is not None else json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    def evaluate(self, path: Path | None = None, revenue: dict | None = None, currency: object = "TWD",
                 current_yoy: float | None = CURRENT_YOY, symbol: str = "5351.TWO") -> oqr.Result:
        return oqr.evaluate(symbol, YAHOO if revenue is None else revenue, currency, current_yoy, as_of=NOW, path=path)


class StoredRecordTests(Case):
    def test_the_stored_config_is_the_one_verified_record(self):
        records, digest = oqr.load(as_of=NOW)
        self.assertEqual(len(records), 1)
        self.assertEqual(digest, __import__("hashlib").sha256(oqr.CONFIG.read_bytes()).hexdigest())
        record = records[0]
        self.assertEqual((record["id"], record["symbol"], record["applies_to_quarter_end"], record["previous_quarter_end"]),
                         ("5351.TWO-2026Q2-prev-2026Q1", "5351.TWO", "2026-06-30", "2026-03-31"))
        documents = {document["id"]: document for document in record["documents"]}
        q1, q2 = documents["ETRON-115Q1-CONSOLIDATED"], documents["ETRON-115Q2-CONSOLIDATED"]
        self.assertEqual((q1["sha256"], q1["byte_size"], q1["published_date"], q1["retrieved_at"]),
                         ("51480f108489255be813c50e784fc46bd8d6f15a10a078c72c0b4f613d5b888b", 4002971, "2026-05-11",
                          "2026-09-27T10:14:52Z"))
        self.assertEqual((q2["sha256"], q2["byte_size"], q2["published_date"], q2["retrieved_at"]),
                         ("c5f50733a6b621b802b600f714bde6bd15d196ee69ad771709085cd5c0eabc12", 4270095, "2026-07-31",
                          "2026-09-27T10:14:53Z"))
        self.assertEqual(q1["url"], "https://etron.com/wp-content/uploads/2026/05/115Q1%E5%90%88%E4%BD%B5%E8%B2%A1%E5%A0%B1.pdf")
        self.assertEqual(q2["url"], "https://etron.com/wp-content/uploads/2026/08/115Q2%E5%90%88%E4%BD%B5%E8%B2%A1%E5%A0%B1.pdf")
        claims = [(name, role, record[name][role]) for name in ("previous_pair", "current_pair") for role in ("current", "prior_year")]
        claims += [("half", role, record["restatement_check"]["half_year_claims"][role]) for role in ("current", "prior_year")]
        self.assertEqual([(claim["amount"], claim["start"], claim["end"], claim["document_id"], claim["page_label"], claim["note"])
                          for _, _, claim in claims],
                         [(2735412, "2026-01-01", "2026-03-31", "ETRON-115Q1-CONSOLIDATED", "39", "六(二十四)"),
                          (627130, "2025-01-01", "2025-03-31", "ETRON-115Q1-CONSOLIDATED", "39", "六(二十四)"),
                          (4898686, "2026-04-01", "2026-06-30", "ETRON-115Q2-CONSOLIDATED", "42", "六(二十四)"),
                          (744722, "2025-04-01", "2025-06-30", "ETRON-115Q2-CONSOLIDATED", "42", "六(二十四)"),
                          (7634098, "2026-01-01", "2026-06-30", "ETRON-115Q2-CONSOLIDATED", "42", "六(二十四)"),
                          (1371852, "2025-01-01", "2025-06-30", "ETRON-115Q2-CONSOLIDATED", "42", "六(二十四)")])
        self.assertEqual(oqr.previous_yoy(record), 2735412 / 627130 - 1)
        self.assertAlmostEqual(oqr.previous_yoy(record), 3.3618, places=4)


class LoadTests(Case):
    def assertRejected(self, mutate, reason: str = "INVALID_RECORD") -> None:
        document = config()
        mutate(document)
        result = self.evaluate(self.write(document))
        self.assertEqual((result.reason, result.revenue_yoy_prev, result.source), (reason, None, None))

    def test_the_valid_record_supplies_the_previous_yoy(self):
        result = self.evaluate(self.write(config()))
        self.assertIsNone(result.reason)
        self.assertEqual(result.revenue_yoy_prev, 2735412 / 627130 - 1)

    def test_missing_malformed_or_wrong_schema_config_supplies_nothing(self):
        self.assertEqual(self.evaluate(Path(self.tmp.name) / "absent.json").reason, "NO_RECORD")
        self.assertEqual(self.evaluate(self.write(None, "{ bad json")).reason, "INVALID_RECORD")
        self.assertEqual(self.evaluate(self.write(None, '{"schema": "official-quarterly-revenue-v1", "records": [NaN]}')).reason,
                         "INVALID_RECORD")
        self.assertRejected(lambda d: d.update(schema="official-quarterly-revenue-v2"))
        self.assertRejected(lambda d: d.update(records=[]))
        self.assertRejected(lambda d: d.update(extra=1))

    def test_duplicate_json_keys_and_duplicate_records_are_ambiguous(self):
        raw = oqr.CONFIG.read_text(encoding="utf-8").replace('"symbol": "5351.TWO",', '"symbol": "5351.TWO", "symbol": "5351.TW",', 1)
        self.assertEqual(self.evaluate(self.write(None, raw)).reason, "AMBIGUOUS_RECORD")
        self.assertRejected(lambda d: d["records"].append(copy.deepcopy(d["records"][0])), "AMBIGUOUS_RECORD")
        self.assertRejected(lambda d: d["records"][0]["documents"].append(copy.deepcopy(d["records"][0]["documents"][0])),
                            "AMBIGUOUS_RECORD")

    def test_wrong_issuer_or_suffix_is_no_record(self):
        for symbol in ("5351", "5351.TW", "5351.two", "ETRON"):
            self.assertEqual(self.evaluate(symbol=symbol).reason, "NO_RECORD", symbol)
        document = config()
        document["records"][0]["symbol"] = "5351.TW"
        self.assertEqual(self.evaluate(self.write(document)).reason, "NO_RECORD")

    def test_every_field_is_validated(self):
        record = lambda d: d["records"][0]
        mutations = [
            lambda d: record(d).pop("review"),
            lambda d: record(d).update(extra="x"),
            lambda d: record(d).update(status="PENDING"),
            lambda d: record(d).update(currency="USD"),
            lambda d: record(d).update(unit="MILLIONS"),
            lambda d: record(d).update(unit_multiplier=1000.0),
            lambda d: record(d).update(unit_multiplier=True),
            lambda d: record(d).update(scope="SEGMENT"),
            lambda d: record(d).update(accounting_standard="US_GAAP"),
            lambda d: record(d).update(metric="SEGMENT_REVENUE"),
            lambda d: record(d).update(applies_to_quarter_end="2026-06-31"),
            lambda d: record(d).update(previous_quarter_end="2025-12-31"),   # not adjacent
            lambda d: record(d).update(previous_quarter_end="2026-03-30"),   # one day off
            lambda d: record(d)["documents"][0].pop("sha256"),
            lambda d: record(d)["documents"][0].update(sha256="A" * 64),
            lambda d: record(d)["documents"][0].update(sha256="a" * 63),
            lambda d: record(d)["documents"][0].update(url="http://etron.com/a.pdf"),
            lambda d: record(d)["documents"][0].update(url="https://etron.com.evil.example/a.pdf"),
            lambda d: record(d)["documents"][0].update(url="https://user:pw@etron.com/a.pdf"),
            lambda d: record(d)["documents"][0].update(url="https://etron.com/a.pdf#page=39"),
            lambda d: record(d)["documents"][0].update(url="https://mopsov.twse.com.tw/a.pdf"),
            lambda d: record(d)["documents"][0].update(url="https://etron.com/a b.pdf"),
            lambda d: record(d)["documents"][0].update(retrieved_at="2026-09-27 10:14:52"),
            lambda d: record(d)["documents"][0].update(retrieved_at="2026-09-28T00:00:00Z"),   # after the build clock
            lambda d: record(d)["documents"][0].update(published_date="2026-09-28"),
            lambda d: record(d)["documents"][0].update(byte_size=0),
            lambda d: record(d)["documents"][0].update(assurance="AUDITED"),
            lambda d: record(d)["documents"][0].update(title="a\nb"),
            lambda d: record(d)["previous_pair"]["current"].update(document_id="MISSING"),
            lambda d: record(d)["previous_pair"]["current"].update(page_label=""),
            lambda d: record(d)["previous_pair"]["current"].pop("note"),
            lambda d: record(d)["previous_pair"]["current"].update(unit="MILLIONS"),   # no per-claim override
            lambda d: record(d)["previous_pair"]["current"].update(amount=2735412.0),
            lambda d: record(d)["previous_pair"]["current"].update(amount=True),
            lambda d: record(d)["previous_pair"]["current"].update(amount=0),
            lambda d: record(d)["previous_pair"]["current"].update(amount=-1),
            lambda d: record(d)["previous_pair"]["current"].update(amount="2735412"),
            lambda d: record(d)["previous_pair"]["current"].update(start="2025-10-01"),   # year to date, not a quarter
            lambda d: record(d)["previous_pair"]["current"].update(period_kind="HALF_YEAR"),
            lambda d: record(d)["current_pair"]["prior_year"].update(end="2025-06-29", start="2025-04-01"),
            lambda d: record(d)["restatement_check"].update(status="MATCHED"),
            lambda d: record(d)["restatement_check"]["half_year_claims"]["current"].update(amount=7634099),
            lambda d: record(d)["restatement_check"]["half_year_claims"]["current"].update(document_id="ETRON-115Q1-CONSOLIDATED"),
            lambda d: record(d)["restatement_check"]["reconciliations"][0].update(difference=1),
            lambda d: record(d)["restatement_check"]["reconciliations"].pop(),
            lambda d: record(d)["review"].update(checked_at="2026-09-27T10:00:00Z"),   # before retrieval
            lambda d: record(d)["review"].update(receipt=""),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.assertRejected(mutate)

    def test_nonfinite_numbers_in_config_are_refused(self):
        raw = oqr.CONFIG.read_text(encoding="utf-8").replace('"amount": 2735412', '"amount": Infinity', 1)
        self.assertEqual(self.evaluate(self.write(None, raw)).reason, "INVALID_RECORD")


class ApplicabilityTests(Case):
    def test_period_mismatches(self):
        later = {**YAHOO, "2026-09-30": 5e9}                          # a later Yahoo quarter: not carried forward
        shifted = {key.replace("2026-06-30", "2026-06-29"): value for key, value in YAHOO.items()}
        gap = {key: value for key, value in YAHOO.items() if key != "2026-03-31"}   # the preceding quarter is missing
        for revenue in (later, shifted, gap, {"2026-06-30": 4898686000.0}):
            self.assertEqual(self.evaluate(revenue=revenue).reason, "PERIOD_MISMATCH", sorted(revenue))

    def test_financial_currency_must_be_twd(self):
        for currency in (None, "USD", "twd", ""):
            self.assertEqual(self.evaluate(currency=currency).reason, "CURRENCY_UNVERIFIED", currency)

    def test_overlap_thresholds_are_inclusive_at_one_reporting_unit(self):
        for end in ("2026-06-30", "2025-06-30", "2026-03-31"):
            for delta, ok in ((0.0, True), (1000.0, True), (-1000.0, True), (1000.5, False), (-1001.0, False)):
                revenue = {**YAHOO, end: YAHOO[end] + delta}
                current = revenue["2026-06-30"] / revenue["2025-06-30"] - 1
                result = self.evaluate(revenue=revenue, current_yoy=current)
                self.assertEqual(result.reason is None, ok, (end, delta, result.reason))
                if ok:
                    self.assertEqual(result.source["cross_check"]["current_current" if end == "2026-06-30" else
                                                                  "current_prior_year" if end == "2025-06-30" else
                                                                  "previous_current"]["delta_twd"], abs(delta))

    def test_scaled_totals_with_the_same_ratio_fail(self):
        scaled = {key: value * 1000 for key, value in YAHOO.items()}   # wrong unit, identical YoY
        self.assertEqual(self.evaluate(revenue=scaled).reason, "CROSS_CHECK_MISMATCH")
        numerator = {**YAHOO, "2026-06-30": YAHOO["2026-06-30"] * 1.01}
        self.assertEqual(self.evaluate(revenue=numerator, current_yoy=numerator["2026-06-30"] / YAHOO["2025-06-30"] - 1).reason,
                         "CROSS_CHECK_MISMATCH")
        conflicting_q1 = {**YAHOO, "2026-03-31": 2735412000.0 + 5000}
        self.assertEqual(self.evaluate(revenue=conflicting_q1).reason, "CROSS_CHECK_MISMATCH")

    def test_current_yoy_threshold(self):
        official = 4898686 / 744722 - 1
        for delta, ok in ((0.0, True), (0.000009, True), (0.0000101, False), (-0.00002, False)):
            self.assertEqual(self.evaluate(current_yoy=official + delta).reason is None, ok, delta)
        for bad in (None, math.nan, math.inf):
            self.assertEqual(self.evaluate(current_yoy=bad).reason, "CROSS_CHECK_MISMATCH")

    def test_the_evidence_records_the_observations_unrounded(self):
        revenue = {**YAHOO, "2026-06-30": YAHOO["2026-06-30"] + 123.456}
        current = revenue["2026-06-30"] / revenue["2025-06-30"] - 1
        source = self.evaluate(revenue=revenue, current_yoy=current).source
        self.assertEqual(source["cross_check"]["current_current"],
                         {"period_end": "2026-06-30", "official_twd": 4898686000, "yahoo_twd": revenue["2026-06-30"],
                          "delta_twd": abs(revenue["2026-06-30"] - 4898686000)})
        self.assertEqual(source["cross_check"]["current_yoy"]["yahoo_ratio"], current)
        self.assertEqual(source["cross_check"]["financial_currency"], "TWD")
        self.assertEqual(source["config_sha256"], oqr.load(as_of=NOW)[1])
        self.assertEqual(source["restatement_check"]["half_year_claims"]["current"]["amount"], 7634098)
        self.assertNotIn("review", source)
        self.assertNotIn("_archive", json.dumps(source))


class SealTests(Case):
    def source(self) -> dict:
        return self.evaluate().source

    def seal(self, source: object, **overrides):
        arguments = {"symbol": "5351.TWO", "quarter": "2026-06-30", "current_yoy": CURRENT_YOY,
                     "prev_yoy": 2735412 / 627130 - 1, "as_of": NOW, **overrides}
        return oqr.seal_evidence(source, **arguments)

    def test_valid_evidence_is_rebuilt_and_extras_are_stripped(self):
        source = self.source()
        noisy = copy.deepcopy(source)
        noisy["extra"] = "x"
        noisy["documents"][0]["raw_text"] = "pdf text"
        noisy["cross_check"]["current_current"]["note"] = "x"
        self.assertEqual(self.seal(noisy), source)

    def test_contradictions_refuse(self):
        cases = [
            ({}, lambda s: s.update(config_sha256="0" * 64)),
            ({}, lambda s: s.update(version="official-quarterly-revenue-v1")),
            ({}, lambda s: s.update(record_id="other")),
            ({}, lambda s: s["previous_pair"]["current"].update(amount=2735413)),
            ({}, lambda s: s["documents"][0].update(url="https://etron.com/other.pdf")),
            ({}, lambda s: s["documents"].pop()),
            ({}, lambda s: s["cross_check"]["current_current"].update(yahoo_twd=4898686000.0 + 1001)),
            ({}, lambda s: s["cross_check"]["current_current"].update(delta_twd=0.5)),
            ({}, lambda s: s["cross_check"].update(financial_currency="USD")),
            ({}, lambda s: s["cross_check"]["current_yoy"].update(yahoo_ratio=CURRENT_YOY + 1e-9)),
            ({"symbol": "5351.TW"}, lambda s: None),
            ({"quarter": "2026-09-30"}, lambda s: None),
            ({"prev_yoy": 2735412 / 627130 - 1 + 1e-9}, lambda s: None),
            ({"prev_yoy": None}, lambda s: None),
            ({"current_yoy": CURRENT_YOY + 0.001}, lambda s: None),
            ({"as_of": datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)}, lambda s: None),   # before retrieval
        ]
        for index, (overrides, mutate) in enumerate(cases):
            with self.subTest(index=index):
                source = self.source()
                mutate(source)
                with self.assertRaises(oqr.RecordError):
                    self.seal(source, **overrides)
        with self.assertRaises(oqr.RecordError):
            self.seal(None)


if __name__ == "__main__":
    unittest.main()
