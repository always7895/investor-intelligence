#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h5_fidelity_deepening_v5 as mod


class H5V5Tests(unittest.TestCase):
    def fixtures(self):
        text_2024 = "Each customer or prospective customer has at least two qualified substrate suppliers."
        text_2026 = "Sumitomo and JX also compete with us in the InP market."
        coherent = " ".join([
            "The Agreement establishes the terms for the mass development and supply of certain agreed-upon specifications for 6-inch indium phosphide (InP) wafer substrates (the Products) from AXT to Coherent.",
            "The initial term is three (3) years from the Effective Date.",
            "AXT has agreed to increase its manufacturing capacity of the Products at its Beijing facility in 2026 through 2028.",
            "The Capacity Commitment is supported by a prepayment of US$22,288,500.",
            "If Coherent fails to meet its minimum order quantity requirement, the unused prepayment may become nonrefundable.",
        ])
        lumentum = " ".join([
            "AXT and Lumentum entered into a Capacity Reservation Agreement.",
            "AXT agreed to reserve a minimum annual commitment for a six (6) year period.",
            "Lumentum agreed to pay an initial deposit of $43,500,000 and a second deposit of $43,500,000.",
        ])
        casela = " ".join([
            "Casela made a binding commitment to purchase a fixed aggregate quantity of InP wafer substrates during the period from January 1, 2027 through December 31, 2027.",
            "The total price of RMB 173,000,000 is approximately US $25.4 million.",
            "Casela is required to purchase at least 80% of the fixed aggregate quantity.",
        ])
        return text_2024, text_2026, coherent, lumentum, casela

    def test_coherent_ordering_matches_filed_sentence_order(self):
        result = mod.axti_substitute_capacity_map_v5(*self.fixtures())
        events = [row["event"] for row in result["capacity_series"]]
        self.assertTrue(any("Coherent_three_year_6inch" in event for event in events))
        self.assertTrue(result["capacity_tightness_candidate"])
        self.assertFalse(result["dependency_promotion_allowed"])

    def test_order_outlook_uses_contracts_but_refuses_total_order_estimate(self):
        result = mod.axti_substitute_capacity_map_v5(*self.fixtures())
        outlook = result["order_outlook"]
        self.assertIn("Casela", outlook["current_orders_summary"])
        self.assertIn("Lumentum", outlook["current_orders_summary"])
        self.assertIn("2027", outlook["future_orders_estimate"])
        self.assertTrue(outlook["numeric_total_order_estimate_prohibited"])
        self.assertEqual(len(outlook["evidence_urls"]), 3)

    def test_missing_minimum_order_language_fails_closed(self):
        parts = list(self.fixtures())
        parts[2] = parts[2].replace("minimum order quantity requirement", "expected purchasing activity")
        with self.assertRaises(ValueError):
            mod.axti_substitute_capacity_map_v5(*parts)


if __name__ == "__main__":
    unittest.main()
