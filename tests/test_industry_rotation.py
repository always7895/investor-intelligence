from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import industry_rotation as rot  # noqa: E402

TODAY = date(2026, 9, 25)


def config():
    base = rot.load_config()
    base = copy.deepcopy(base)
    base["industries"] = [
        {"industry_id": "alpha", "name_zh": "阿爾法設備", "name_en": "Alpha equipment", "sic": ["1111"], "ppi": ["PCU111111111111"]},
        {"industry_id": "beta", "name_zh": "貝塔材料", "name_en": "Beta materials", "sic": ["2222"], "ppi": ["PCU222222222222"]},
        {"industry_id": "gamma", "name_zh": "伽瑪服務", "name_en": "Gamma services", "sic": ["3333"], "ppi": ["PCU333333333333"]},
    ]
    base["thresholds"]["min_frame_rows"] = 1
    return base


def bls_payload(values):
    series = []
    for series_id, (latest, prior) in values.items():
        series.append({"seriesID": series_id, "data": [
            {"year": "2026", "period": "M08", "value": str(latest)}, {"year": "2026", "period": "M13", "value": "1"},
            {"year": "2025", "period": "M08", "value": str(prior)}]})
    return json.dumps({"status": "REQUEST_SUCCEEDED", "Results": {"series": series}}).encode()


MEMBERS = {"1111": [101, 102, 103], "2222": [201, 202, 203], "3333": [301, 302, 303]}
# (revenue now, revenue prior, rpo now, rpo prior, inventory now, inventory prior)
FIN = {101: (500, 400, 300, 150, 50, 50), 102: (300, 250, 200, 100, 40, 40), 103: (200, 150, 100, 60, 20, 20),
       201: (100, 100, 50, 50, 90, 50), 202: (100, 100, 50, 50, 90, 50), 203: (100, 100, 50, 50, 90, 50),
       301: (100, 90, 10, 10, 10, 10), 302: (100, 90, 10, 10, 10, 10), 303: (100, 90, 10, 10, 10, 10)}


def sec_fetch(calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        if "browse-edgar" in url:
            sic = url.split("SIC=")[1][:4]
            start = int(url.split("start=")[1].split("&")[0])
            entries = "".join(f'<entry title="x"><content><company-info><cik>{c:010d}</cik></company-info></content></entry>'
                              for c in MEMBERS[sic]) if start == 0 else ""
            return f"<feed>{entries}</feed>".encode()
        concept = url.split("/us-gaap/")[1].split("/")[0]
        period = url.rsplit("/", 1)[1][:-5]
        year = int(period[2:6])
        column = {"RevenueFromContractWithCustomerExcludingAssessedTax": 0, "Revenues": None,
                  "RevenueRemainingPerformanceObligation": 2, "InventoryNet": 4}[concept]
        if column is None:
            return json.dumps({"data": []}).encode()
        offset = 0 if year == 2026 else 1
        rows = [{"cik": cik, "entityName": f"Issuer {cik}", "val": values[column + offset], "end": "2026-06-30", "accn": "x"}
                for cik, values in FIN.items()]
        return json.dumps({"data": rows}).encode()
    return fetch


def post(url, body):
    return bls_payload({"PCU111111111111": (110, 100), "PCU222222222222": (90, 100), "PCU333333333333": (101, 100)})


class RotationTests(unittest.TestCase):
    def build(self, **kwargs):
        return rot.build_rotation(config(), fetch_sec=sec_fetch(), post_bls=post, today=TODAY, member_cache=None, **kwargs)

    def test_yoy_uses_same_month_and_skips_annual_average(self):
        points = [(date(2025, 8, 1), 100.0), (date(2026, 7, 1), 104.0), (date(2026, 8, 1), 110.0)]
        self.assertEqual(rot.yoy_latest(points)["yoy_pct"], 10.0)
        self.assertEqual(rot.yoy_latest(points)["as_of"], "2026-08-31")
        self.assertIsNone(rot.yoy_latest([(date(2026, 8, 1), 1.0)]))

    def test_two_families_confirm_and_order_follows_phase_then_strength(self):
        doc = self.build()
        rows = {r["industry_id"]: r for r in doc["industries"]}
        alpha = rows["alpha"]
        self.assertEqual(alpha["price"]["yoy_pct"], 10.0)
        self.assertEqual(alpha["revenue"]["yoy_pct"], 25.0)   # 1000 vs 800
        self.assertEqual(alpha["backlog"]["yoy_pct"], 93.55)  # 600 vs 310
        self.assertEqual(alpha["phase"]["phase"], "EARLY_VALIDATION")
        self.assertEqual(rows["beta"]["phase"]["phase"], "RELIEVING")  # price down + inventory build
        self.assertEqual(doc["industries"][0]["industry_id"], "alpha")
        self.assertEqual([c["industry_id"] for c in doc["macro_candidates"]], ["alpha"])

    def test_card_and_deep_analysis_text_come_from_numbers_with_sources(self):
        doc = self.build()
        card = doc["macro_candidates"][0]
        self.assertIn("+10.0%", card["pricing"])
        self.assertIn("PCU111111111111", card["pricing"])
        self.assertEqual(card["growth"]["rate_pct"], 25.0)
        self.assertEqual(card["growth"]["type"], "actual")
        self.assertEqual(card["beneficiaries_key_suppliers"][0], "Issuer 101")
        self.assertEqual(card["confidence"]["verification_status"], "OFFICIAL_DATA_COMPUTED")
        deep = doc["deep_analyses"]["alpha"]
        self.assertTrue(all(ref["url"].startswith("https://") for ref in deep["source_references"]))
        self.assertIn("不捏造", deep["catalysts"]["y2"])
        self.assertEqual(len(deep["killers"]), 3)

    def test_small_samples_are_not_used(self):
        cfg = config()
        cfg["thresholds"]["min_matched_issuers"] = 4
        doc = rot.build_rotation(cfg, fetch_sec=sec_fetch(), post_bls=post, today=TODAY, member_cache=None)
        alpha = {r["industry_id"]: r for r in doc["industries"]}["alpha"]
        self.assertIsNone(alpha["revenue"]["yoy_pct"])
        self.assertEqual(alpha["phase"]["phase"], "DISCOVERY")
        self.assertEqual(doc["macro_candidates"], [])  # no revenue growth -> not admitted

    def test_unavailable_listing_is_recorded_not_guessed(self):
        def failing(url):
            if "SIC=2222" in url:
                raise OSError("down")
            return sec_fetch()(url)
        doc = rot.build_rotation(config(), fetch_sec=failing, post_bls=post, today=TODAY, member_cache=None)
        self.assertEqual(doc["unavailable_sic"], ["2222"])
        self.assertEqual({r["industry_id"]: r for r in doc["industries"]}["beta"]["member_count"], 0)

    def test_503_listing_pages_are_retried_but_fences_are_not(self):
        attempts = []

        class Unavailable(Exception):
            code = 503

        def flaky(url):
            attempts.append(url)
            if len(attempts) == 1:
                raise Unavailable()
            return sec_fetch()(url)
        members = rot.sic_members("1111", flaky, config(), today=TODAY, cache_dir=None, receipts=[], sleep=lambda s: None)
        self.assertEqual(len(members), 3)

        class Fenced(Exception):
            code = 429
        with self.assertRaises(Fenced):
            rot.sic_members("1111", lambda url: (_ for _ in ()).throw(Fenced()), config(), today=TODAY, cache_dir=None,
                            receipts=[], sleep=lambda s: None)

    def test_member_cache_skips_empty_listings(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            rot.sic_members("1111", sec_fetch(), config(), today=TODAY, cache_dir=cache, receipts=[])
            self.assertTrue((cache / "SIC1111.json").exists())
            empty = lambda url: b"<feed></feed>"  # noqa: E731
            rot.sic_members("9999", empty, config(), today=TODAY, cache_dir=cache, receipts=[])
            self.assertFalse((cache / "SIC9999.json").exists())

    def test_load_rotation_rejects_stale_or_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rotation.json"
            rot.atomic_write(path, {"schema_version": 1, "as_of": "2026-09-01", "macro_candidates": []})
            self.assertIsNotNone(rot.load_rotation(path, max_age_days=45, today=TODAY))
            self.assertIsNone(rot.load_rotation(path, max_age_days=10, today=TODAY))
            path.write_text("{", encoding="utf-8")
            self.assertIsNone(rot.load_rotation(path, max_age_days=45, today=TODAY))

    def test_macro_builder_publishes_rotation_with_embedded_deep_analyses(self):
        import build_v213_macro_industry_research as mb
        self.assertFalse(hasattr(mb, "WIDER_CANDIDATE_UNIVERSE"))  # no hand-written production universe
        doc = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rotation.json"
            rot.atomic_write(path, {**doc, "as_of": date.today().isoformat()})
            candidates, deep, rotation = mb.load_rotation_candidates(path)
            qualified, disqualified = mb.evaluate_candidates(candidates)
            overview = mb.build_macro_overview_output(qualified, disqualified, deep_analyses=deep, rotation=rotation)
        self.assertEqual([c["industry_id"] for c in overview["industries"]], ["alpha"])
        self.assertEqual(overview["industries"][0]["opportunity_score"], doc["macro_candidates"][0]["data_strength"])
        self.assertEqual(list(overview["deep_analyses"]), ["alpha"])
        self.assertEqual(overview["status"], "SHORTFALL_NOT_QUALIFIED")  # one admitted industry is an honest shortfall
        self.assertIn("BLS PPI", overview["data_basis"]["method"])
        empty, _, missing = mb.load_rotation_candidates(Path(tmp) / "absent.json")
        self.assertEqual((empty, missing), ([], None))

    def test_publisher_reads_the_rotation_not_a_fixed_list(self):
        source = (ROOT / "scripts" / "publish_sealed_snapshot.py").read_text(encoding="utf-8")
        self.assertIn("load_rotation_candidates()", source)
        self.assertNotIn("_SYNTHETIC_CONTRACT_UNIVERSE", source)

    def test_bls_failure_status_fails_closed(self):
        bad = lambda url, body: json.dumps({"status": "REQUEST_NOT_PROCESSED"}).encode()  # noqa: E731
        with self.assertRaises(rot.RotationError):
            rot.build_rotation(config(), fetch_sec=sec_fetch(), post_bls=bad, today=TODAY, member_cache=None)


if __name__ == "__main__":
    unittest.main()
