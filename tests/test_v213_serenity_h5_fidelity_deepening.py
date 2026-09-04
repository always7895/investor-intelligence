#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h5_fidelity_deepening as h5


class SerenityH5FidelityDeepeningTests(unittest.TestCase):
    def test_aaoi_lineage_separates_program_amendment_and_completion(self) -> None:
        fixture = (
            "On February 26, 2026, the Company entered into an Equity Distribution Agreement (the First EDA) having an aggregate offering price of up to $250 million. "
            "On March 12, 2026, the Company entered into Amendment No. 1 to the First EDA to increase the aggregate offering price from $250 million to $500 million. "
            "On April 2, 2026, the Company completed the First ATM Offering and sold approximately 4.8 million shares, providing proceeds of approximately $490 million, net of expenses. "
            "On May 14, 2026, the Company entered into an Equity Distribution Agreement (the Second EDA) having an aggregate offering price of up to $600 million. "
            "84,386 and 74,998 shares issued and outstanding at June 30, 2026 and December 31, 2025. "
            "Total 7,775,523 $ 1,049,814 $ 20,996 $ 1,028,817"
        )
        row = h5.aaoi_financing_lineage(fixture)
        self.assertEqual(row["program_count"], 2)
        self.assertEqual(row["amendment_count"], 1)
        self.assertEqual(row["completed_program_count"], 1)
        self.assertEqual(row["programs"][0]["entered_at"], "2026-02-26")
        self.assertEqual(row["programs"][0]["amended_at"], "2026-03-12")
        self.assertEqual(row["programs"][0]["completed_at"], "2026-04-02")
        self.assertEqual(row["programs"][1]["entered_at"], "2026-05-14")

    def test_aaoi_killer_is_based_on_actual_issuance_not_mention_count(self) -> None:
        fixture = (
            "On February 26, 2026, the Company entered into an Equity Distribution Agreement (the First EDA) having an aggregate offering price of up to $250 million. "
            "On March 12, 2026, the Company entered into Amendment No. 1 to the First EDA to increase the aggregate offering price from $250 million to $500 million. "
            "On April 2, 2026, the Company completed the First ATM Offering and sold approximately 4.8 million shares, providing proceeds of approximately $490 million, net of expenses. "
            "On May 14, 2026, the Company entered into an Equity Distribution Agreement (the Second EDA) having an aggregate offering price of up to $600 million. "
            "84,386 and 74,998 shares issued and outstanding at June 30, 2026 and December 31, 2025. "
            "Total 7,775,523 $ 1,049,814 $ 20,996 $ 1,028,817"
        )
        row = h5.aaoi_financing_lineage(fixture)
        self.assertTrue(row["material_equity_capture_pressure"])
        self.assertEqual(row["shares_sold_through_atm_h1_2026"], 7_775_523)
        self.assertGreater(row["net_proceeds_usd_h1_2026"], 1_000_000_000)
        self.assertGreater(row["share_count_growth_pct"], 10.0)

    def test_axti_disclosed_substitutes_block_hard_dependency_promotion(self) -> None:
        row = h5.axti_substitute_capacity_map(
            "our customer or prospective customer has at least two qualified substrate suppliers",
            "Sumitomo and JX also compete with us in the InP market",
            "initial term of three (3) years for 6-inch indium phosphide wafer substrates and prepayment of US$22,288,500",
            "capacity reservation for a six (6) year period",
            "January 1, 2027 through December 31, 2027",
        )
        self.assertTrue(row["qualified_substitutes_exist"])
        self.assertEqual(row["typical_customer_qualified_supplier_floor"], 2)
        self.assertTrue(row["capacity_tightness_candidate"])
        self.assertFalse(row["dependency_promotion_allowed"])

    def test_axti_capacity_tightness_candidate_is_not_semi_monopoly(self) -> None:
        row = h5.axti_substitute_capacity_map(
            "our customer or prospective customer has at least two qualified substrate suppliers",
            "Sumitomo and JX also compete with us in the InP market",
            "initial term of three (3) years for 6-inch indium phosphide wafer substrates and prepayment of US$22,288,500",
            "capacity reservation for a six (6) year period",
            "January 1, 2027 through December 31, 2027",
        )
        self.assertEqual(row["effective_capacity_substitutability_at_current_ramp"], "UNPROVEN")
        self.assertNotIn("SEMI_MONOPOLY", json.dumps(row))

    def test_sive_material_financing_is_not_automatically_toxic(self) -> None:
        april = "8,620,000 ordinary shares at a subscription price of SEK 14.5 and dilution of approximately 2.5 percent"
        june = "12,280,701 ordinary shares at a subscription price of SEK 57 per share, discount of approximately 9.7 percent and dilution of approximately 3.3 percent"
        q1 = "our qual builds and production readiness is on track for Q4 2026. Given the massive multi-year imbalance in the demand-supply situation for optical networking"
        q2 = "Product Revenue Increases 18% Year-Over-Year. directed share issues amounting to approximately SEK 825 m"
        shares = "355,081,317 ordinary shares"
        row = h5.sive_financing_and_capacity(april, june, q1, q2, shares)
        self.assertEqual(row["equity_capture_pressure"], "MATERIAL")
        self.assertFalse(row["toxic_financing_proven"])
        self.assertEqual(len(row["financing_events"]), 2)

    def test_soitec_architecture_does_not_claim_exclusivity(self) -> None:
        row = h5.soitec_architecture(
            "Photonics-SOI is built on a silicon-on-insulator substrate for data center interconnect applications",
            "Smart Cut technology supports silicon photonics and other engineered substrates",
        )
        self.assertTrue(row["architecture_evidence_bound"])
        self.assertFalse(row["dependency_promotion_allowed"])

    def test_source_history_is_hash_chained_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "history.jsonl"
            first = h5.ensure_source_history(path)
            second = h5.ensure_source_history(path)
            self.assertTrue(first["chain_verified"])
            self.assertEqual(first["entries"], len(h5.SERENITY_SOURCE_SEEDS))
            self.assertEqual(second["appended"], 0)
            self.assertEqual(first["latest_hash"], second["latest_hash"])

    def test_corrupt_source_history_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "history.jsonl"
            h5.ensure_source_history(path)
            lines = path.read_text(encoding="utf-8").splitlines()
            row = json.loads(lines[0])
            row["paraphrase"] = "tampered"
            lines[0] = json.dumps(row, ensure_ascii=False, sort_keys=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                h5.read_history(path)

    def test_source_views_are_never_factual_dependency_proof(self) -> None:
        for ticker in ("AAOI", "AXTI", "SIVE", "SOI", "TSEM", "COHR"):
            views = h5.source_views_for_ticker(ticker)
            self.assertTrue(views)
            self.assertTrue(all(view["factual_dependency_proof"] is False for view in views))

    def test_short_interest_methodology_view_is_preserved(self) -> None:
        views = h5.source_views_for_ticker("AAOI")
        kinds = {row["view_type"] for row in views}
        self.assertIn("short_interest_deemphasized", kinds)
        self.assertIn("financing_disconfirmation", kinds)


if __name__ == "__main__":
    unittest.main()
