"""Score-neutral R3 research and append-only provenance behaviors; synthetic inputs, no network."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import top20_rotation_provenance as rotation
import validated_rule_engine as rules

CUTOFF = date(2026, 11, 8)
KEY = b"synthetic-shadow-test-key-not-a-real-key-123456"


def fundamentals():
    return {"source": "SEC EDGAR XBRL companyfacts", "source_url": "https://data.sec.gov/api/xbrl/companyfacts/EXAMPLE.json",
            "filed": "2026-10-20", "quarter_end": "2026-09-30", "revenue_yoy": 0.30, "revenue_yoy_prev": 0.20,
            "gross_margin_change": -0.01, "shares_yoy": 0.05, "shares_basis": "DILUTED_WEIGHTED_AVERAGE",
            "rpo_yoy": 0.22, "rpo_end": "2026-09-30", "rpo_filed": "2026-10-20",
            "rpo_prior_end": "2025-09-30", "rpo_prior_filed": "2025-10-21"}


def market():
    return {"source": "Yahoo Finance adjusted daily close (unofficial)", "source_url": "https://finance.yahoo.com/quote/EXAMPLE",
            "asof": "2026-11-06", "ret_6m": 0.10, "ret_6m_start": "2026-05-08", "cagr_2y": 0.12,
            "max_drawdown_12m": -0.20, "drawdown_start": "2025-11-06"}


def document(top=("A", "B"), candidates=("A", "B", "C")):
    return {"top": [{"symbol": symbol, "score": 100 - rank} for rank, symbol in enumerate(top)],
            "candidate_fingerprints": [{"symbol": symbol, **{name: rotation.digest([name, symbol])
                for name in rotation.INPUT_FAMILIES}} for symbol in candidates],
            "input_context": {"prices": "captured-price-digest", "serenity": "captured-author-digest",
                              "context": {"config": "public-config-digest", "fx": "public-fx-digest"}},
            "screener_shadow": [{"symbol": symbol, "conditions": rules.evaluate(fundamentals(), market(), cutoff=CUTOFF, symbol=symbol)}
                                for symbol in candidates]}


class ScreenerBehavior(unittest.TestCase):
    def evaluate(self, fund=None, prices=None, cutoff=CUTOFF):
        output = rules.evaluate(fund if fund is not None else fundamentals(),
                                prices if prices is not None else market(), cutoff=cutoff, symbol="A")
        return output, {row["rule_id"]: row for row in output["rules"]}

    def test_frozen_thresholds_and_document_shortfalls_are_explicit_and_score_neutral(self):
        fund, prices = fundamentals(), market()
        before = copy.deepcopy((fund, prices))
        output, by = self.evaluate(fund, prices)
        self.assertEqual(by["R01_REV_GROWTH_20"]["status"], "PASS")
        self.assertEqual(by["R02_REV_ACCEL_10PP"]["status"], "PASS")
        self.assertEqual(by["R03_GM_EXPAND_2PP"]["status"], "FAIL")
        self.assertEqual(by["R05_DILUTION_BELOW_5"]["status"], "PASS")
        self.assertEqual(by["R07_PRICE_2Y_POSITIVE"]["status"], "PASS")
        self.assertEqual(by["R09_MAX_DRAWDOWN_12M"]["status"], "PASS")
        for name in ("R10_ATM_MATERIAL_DILUTION", "R13_INDEPENDENT_13F_POSITION_CHANGE"):
            self.assertEqual(by[name]["status"], "UNKNOWN")
            self.assertTrue(by[name]["reason_zh"])
        self.assertEqual(output["state"], "UNVERIFIED")
        self.assertEqual(output["rules_kept"], 0)
        self.assertEqual((fund, prices), before)
        self.assertFalse(any("score" in row for row in output["rules"]))
        self.assertEqual({row["rule_id"] for row in rules.display_projection(output)["rules"]}, set(by))

    def test_benchmark_relative_rules_require_aligned_adjusted_benchmarks_not_positive_stock(self):
        prices = market()
        _, missing = self.evaluate(prices=prices)
        self.assertEqual(missing["R06_REL_MOMENTUM_6M"]["status"], "UNKNOWN")
        prices["benchmarks"] = {name: {**market(), "ret_6m": ret} for name, ret in (("QQQ", 0.03), ("SOXX", 0.20))}
        _, by = self.evaluate(prices=prices)
        self.assertEqual(by["R06_REL_MOMENTUM_6M"]["status"], "PASS")
        self.assertEqual(by["R08_REL_MOMENTUM_SOXX_6M"]["status"], "FAIL")
        prices["benchmarks"]["QQQ"]["ret_6m_start"] = "2026-05-01"
        _, by = self.evaluate(prices=prices)
        self.assertEqual(by["R06_REL_MOMENTUM_6M"]["status"], "UNKNOWN")

    def test_dates_fail_closed_and_hashes_describe_evidence_not_wallclock(self):
        output, _ = self.evaluate()
        later, _ = self.evaluate(cutoff=date(2026, 11, 9))
        self.assertEqual(output["input_sha256"], later["input_sha256"])
        for stamp in (None, "2026-11-10", "2026-11-08junk", "not-a-date"):
            _, by = self.evaluate({**fundamentals(), "filed": stamp, "rpo_filed": stamp}, {**market(), "asof": stamp})
            self.assertTrue(all(row["status"] == "UNKNOWN" for row in by.values()))
            self.assertTrue(all(row["reason_zh"] and row["freshness"] != "FRESH" for row in by.values()))
        stale, by = self.evaluate(cutoff=date(2027, 11, 8))
        self.assertTrue(all(row["status"] == "UNKNOWN" for row in by.values()))
        self.assertEqual(stale["input_sha256"], output["input_sha256"])
        self.assertTrue(any(row["freshness"] == "STALE" for row in by.values()))

    def test_rpo_uses_own_filing_dates_not_unrelated_revenue_filing(self):
        _, by = self.evaluate({**fundamentals(), "rpo_filed": "2026-11-10"})
        self.assertEqual(by["R01_REV_GROWTH_20"]["status"], "PASS")
        self.assertEqual(by["R04_RPO_GROWTH_20"]["status"], "UNKNOWN")
        _, by = self.evaluate({**fundamentals(), "rpo_prior_filed": None})
        self.assertEqual(by["R04_RPO_GROWTH_20"]["status"], "UNKNOWN")

    def test_price_adjustment_unknown_cannot_be_overridden_by_a_number(self):
        _, by = self.evaluate(prices={**market(), "return_reasons": {"cagr_2y": "PUBLIC_DISTRIBUTION_UNRESOLVED"}})
        self.assertEqual(by["R07_PRICE_2Y_POSITIVE"]["status"], "UNKNOWN")
        _, by = self.evaluate({**fundamentals(), "revenue_yoy": float("nan"), "shares_yoy": True})
        self.assertEqual(by["R01_REV_GROWTH_20"]["status"], "UNKNOWN")
        self.assertEqual(by["R05_DILUTION_BELOW_5"]["status"], "UNKNOWN")


class RotationBehavior(unittest.TestCase):
    def test_identical_inputs_have_no_false_rotation_and_shuffled_candidates_do_not_change_hashes(self):
        doc = document()
        original = copy.deepcopy(doc)
        first = rotation.build_record(doc, None, asof="2026-11-08T00:00:00Z")
        second_doc = copy.deepcopy(doc)
        second_doc["candidate_fingerprints"].reverse()
        second_doc["screener_shadow"].reverse()
        second = rotation.build_record(second_doc, first, asof="2026-11-08T01:00:00Z")
        self.assertEqual(second["input_sha256"], first["input_sha256"])
        self.assertEqual(second["diff"]["reason_code"], "NO_CHANGE")
        self.assertEqual(second["diff"]["changed_input_families"], [])
        self.assertEqual(second["diff"]["changed_candidates"], [])
        self.assertEqual(second["diff"]["changed_screener_symbols"], [])
        self.assertFalse(second["diff"]["ranking_changed"])
        self.assertEqual(doc, original)

    def test_rank_only_change_is_not_misreported_as_changed_prices_or_filings(self):
        first = rotation.build_record(document(), None, asof="2026-11-08T00:00:00Z")
        second = rotation.build_record(document(top=("B", "A")), first, asof="2026-11-08T01:00:00Z")
        self.assertEqual(second["diff"]["changed_input_families"], [])
        self.assertTrue(second["diff"]["ranking_changed"])
        self.assertEqual(second["diff"]["reason_code"], "RANKING_CHANGED_WITHOUT_INPUT_CHANGE")
        self.assertEqual(second["diff"]["entered"], [])
        self.assertEqual(len(second["diff"]["moved"]), 2)
        # Full-candidate provenance is mandatory, even for an otherwise valid Top20.
        incomplete = document()
        incomplete.pop("candidate_fingerprints")
        with self.assertRaises(ValueError):
            rotation.build_record(incomplete, first, asof="2026-11-08T01:00:00Z")

    def test_overflow_input_change_and_removed_candidate_have_specific_family_evidence(self):
        first = rotation.build_record(document(), None, asof="2026-11-08T00:00:00Z")
        changed = document()
        changed["candidate_fingerprints"][-1]["events"] = rotation.digest("new-public-filing")
        second = rotation.build_record(changed, first, asof="2026-11-08T01:00:00Z")
        self.assertEqual(second["diff"]["changed_input_families"], ["events"])
        self.assertEqual(second["diff"]["changed_candidates"], [{"symbol": "C", "families": ["events"], "change": "UPDATED"}])
        self.assertEqual(second["diff"]["reason_code"], "INPUT_CHANGED_RANKING_UNCHANGED")
        removed = rotation.build_record(document(candidates=("A", "B")), first, asof="2026-11-08T02:00:00Z")
        self.assertEqual(removed["diff"]["changed_candidates"][0]["change"], "REMOVED")

    def test_source_context_is_hash_only_and_rule_evidence_is_not_lost(self):
        doc = document()
        first = rotation.build_record(doc, None, asof="2026-11-08T00:00:00Z")
        doc["input_context"]["context"]["fx"] = "new-public-fx-digest"
        second = rotation.build_record(doc, first, asof="2026-11-08T01:00:00Z")
        self.assertEqual(second["diff"]["changed_input_families"], ["context"])
        self.assertNotIn("new-public-fx-digest", json.dumps(second))
        self.assertEqual(len(second["screener_shadow"]), 3)
        for symbol in second["screener_shadow"]:
            self.assertEqual(len(symbol["rules"]), len(rules.RULES))
            self.assertTrue(all(row["provenance_hash"] and row["reason_zh"] for row in symbol["rules"]))
            self.assertTrue(any(row["filed_at"] == "2026-10-20" for row in symbol["rules"]))
        self.assertEqual(second["rules_kept"], 0)

    def test_full_signed_chain_must_validate_before_any_append(self):
        for defect in ("signature", "entry_hash", "chain", "truncated"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "shadow.jsonl"
                for hour in range(3):
                    rotation.append_signed(path, document(), key=KEY, asof=f"2026-11-08T0{hour}:00:00Z")
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(rotation.verify_log(path, KEY)["ranked"], ["A", "B"])
                if defect != "truncated":
                    rows[0]["diff"]["reason_zh"] = "已改寫的合成測試資料"
                if defect in {"entry_hash", "chain"}:
                    rows[0].pop("signature")
                    if defect == "chain":
                        rows[0].pop("entry_sha256")
                        rows[0]["entry_sha256"] = rotation.digest(rows[0])
                    rows[0]["signature"] = hmac.new(KEY, rotation.canonical(rows[0]), hashlib.sha256).hexdigest()
                raw = b"\n".join(rotation.canonical(row) for row in rows) + (b"" if defect == "truncated" else b"\n")
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    rotation.append_signed(path, document(), key=KEY, asof="2026-11-08T03:00:00Z")
                self.assertEqual(path.read_bytes(), raw)
                self.assertFalse(path.with_name(path.name + ".lock").exists())

    def test_failed_refresh_does_not_advance_last_good_signed_observation(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "shadow.jsonl"
            rotation.append_signed(path, document(), key=KEY, asof="2026-11-08T00:00:00Z")
            before = path.read_bytes()
            result = rotation.append_signed(path, {**document(), "refresh_state": "REFRESH_FAILED"},
                                            key=KEY, asof="2026-11-08T01:00:00Z")
            self.assertEqual(result["state"], "REFRESH_FAILED")
            self.assertEqual(result["asof_utc"], "2026-11-08T00:00:00Z")
            self.assertEqual(path.read_bytes(), before)

    def test_concurrent_lock_missing_key_and_equal_utc_clock_fail_without_append(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "shadow.jsonl"
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(rotation.append_if_configured(document(), path=path, asof="2026-11-08T00:00:00Z"), "UNCONFIGURED")
            self.assertFalse(path.exists())
            rotation.append_signed(path, document(), key=KEY, asof="2026-11-08T00:00:00Z")
            raw = path.read_bytes()
            with self.assertRaises(ValueError):
                rotation.append_signed(path, document(), key=KEY, asof="2026-11-08T00:00:00+00:00")
            lock = path.with_name(path.name + ".lock")
            lock.touch()
            with self.assertRaises(ValueError):
                rotation.append_signed(path, document(), key=KEY, asof="2026-11-08T01:00:00Z")
            self.assertEqual(path.read_bytes(), raw)
            self.assertTrue(lock.exists())


if __name__ == "__main__":
    unittest.main()
