"""Operator rule 2026-09-25: Top20 order fields need sources and no vague wording."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reconcile_v213_order_evidence as reconcile  # noqa: E402
from v213_sourced_wording_guard import find_violations, guard_order_fields, load_policy  # noqa: E402
from v213_top20_order_outlook_contract import NO_CURRENT_ORDERS, NO_FUTURE_ESTIMATE  # noqa: E402

POLICY = load_policy()
URL = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/example.htm"


def row(current: str, future: str, current_urls=(URL,), future_urls=(URL,)) -> dict:
    return {"rank": 1, "ticker": "SYN", "current_orders": current, "future_orders_estimate": future,
            "orders_confidence": "EVIDENCE_BOUND", "current_order_source_urls": list(current_urls),
            "future_order_source_urls": list(future_urls)}


class SourcedWordingGuardTests(unittest.TestCase):
    def test_fallback_texts_match_the_contract(self):
        self.assertEqual(POLICY["fields"]["current_orders"]["fallback"], NO_CURRENT_ORDERS)
        self.assertEqual(POLICY["fields"]["future_orders_estimate"]["fallback"], NO_FUTURE_ESTIMATE)

    def test_sourced_quantities_pass_unchanged(self):
        original = row("SEC 10-K 揭露 backlog 89 億美元（文件日 2026-02-11）", "約 40% 於未來 12 個月認列（公司揭露）")
        clean, findings = guard_order_fields(original, POLICY)
        self.assertEqual(findings, [])
        self.assertEqual(clean, original)

    def test_operator_examples_and_known_offenders_are_withheld(self):
        for text in ("訂單很多", "市場很大，需求旺盛", "公司預期幾乎全部既有backlog於未來12個月內履行",
                     "能見度偏高；已簽多年產能承諾", "strong visibility into a multi-year backlog",
                     "Substantially all backlog ships this year"):
            with self.subTest(text=text):
                clean, findings = guard_order_fields(row(NO_CURRENT_ORDERS, text), POLICY)
                self.assertEqual(clean["future_orders_estimate"], NO_FUTURE_ESTIMATE)
                self.assertEqual(clean["future_order_source_urls"], [])
                self.assertTrue(findings[0]["codes"][0].startswith("VAGUE_PHRASE:"))

    def test_english_matching_respects_word_boundaries(self):
        self.assertEqual(find_violations("Germany orders 12 units", [URL], POLICY), [])
        self.assertEqual(find_violations("insignificantly small", [URL], POLICY), [])
        self.assertIn("VAGUE_PHRASE:many", find_violations("many orders", [URL], POLICY))

    def test_numbers_without_any_source_are_withheld(self):
        clean, findings = guard_order_fields(row("固定量合約 1.73 億人民幣", NO_FUTURE_ESTIMATE, current_urls=()), POLICY)
        self.assertEqual(clean["current_orders"], NO_CURRENT_ORDERS)
        self.assertEqual(findings, [{"field": "current_orders", "codes": ["NUMBER_WITHOUT_SOURCE"]}])
        self.assertEqual(clean["orders_confidence"], "UNAVAILABLE")
        self.assertIn("NUMBER_WITHOUT_SOURCE", find_violations("２０２７ 交貨", [], POLICY))
        self.assertIn("NUMBER_WITHOUT_SOURCE", find_violations("backlog 12", ["http://insecure.example"], POLICY))

    def test_confidence_kept_when_one_field_survives_and_input_not_mutated(self):
        original = row("SEC 揭露 backlog 12 億美元", "訂單很多")
        before = copy.deepcopy(original)
        clean, _ = guard_order_fields(original, POLICY)
        self.assertEqual(original, before)
        self.assertEqual(clean["orders_confidence"], "EVIDENCE_BOUND")
        self.assertEqual(clean["current_orders"], "SEC 揭露 backlog 12 億美元")

    def test_reconcile_guards_retained_baseline_rows_and_records_the_receipt(self):
        v212 = {"product_version": "2.1.2", "records": [{"rank": i + 1, "ticker": f"T{i:02d}"} for i in range(20)]}
        rows = []
        for i in range(20):
            item = row(NO_CURRENT_ORDERS, NO_FUTURE_ESTIMATE, current_urls=(), future_urls=())
            item.update(rank=i + 1, ticker=f"T{i:02d}", retrieved_at="2026-09-01T00:00:00Z", orders_as_of="2026-09-01T00:00:00Z")
            rows.append(item)
        rows[0].update(future_orders_estimate="公司預期幾乎全部既有backlog於未來12個月內履行", future_order_source_urls=[URL])
        baseline = {"product_version": "2.1.3", "accepted_from": "TEST_FIXTURE", "records": rows}
        document, receipt = reconcile.reconcile(v212, baseline, resolver=lambda ticker: self.fail("no new members"))
        self.assertEqual(document["records"][0]["future_orders_estimate"], NO_FUTURE_ESTIMATE)
        self.assertEqual(receipt["wording_guard_policy"], "v213-sourced-wording-v1")
        self.assertEqual([item["ticker"] for item in receipt["wording_guard_withheld"]], ["T00"])
        self.assertEqual(receipt["preserved_count"], 20)


if __name__ == "__main__":
    unittest.main()
