#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6b1_metric_semantic_guard_v3 as guard


class H6B1MetricSemanticGuardV3Tests(unittest.TestCase):
    def test_crdo_supplier_deposit_is_not_backlog(self) -> None:
        text = (
            "The cash outflows from working capital were driven by an increase in inventory of $174.0 million "
            "to support unfulfilled backlog and related new product ramps; (c) an increase in other current and "
            "non-current assets of $71.3 million of payment for refundable deposits to suppliers. "
            "Revenue Recognition. Remaining Performance Obligations. The contracted but unsatisfied performance "
            "obligation was approximately $31.9 million which the Company expects to recognize over the next fiscal year."
        )
        metric = guard.r4._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        self.assertEqual(metric["metric_type"], "RPO")
        self.assertEqual(metric["amount"], "$31.9 million")

    def test_valid_same_clause_backlog_still_binds(self) -> None:
        metric = guard.r4._extract_strict_metric(
            "As of July 31, 2026, we had backlog of approximately $5.9 billion."
        )
        self.assertIsNotNone(metric)
        self.assertEqual(metric["metric_type"], "BACKLOG")
        self.assertEqual(metric["amount"], "$5.9 billion")

    def test_semicolon_blocks_cross_clause_backlog_amount(self) -> None:
        metric = guard.r4._extract_strict_metric(
            "inventory increased to support unfulfilled backlog and new ramps; other assets increased by $71.3 million."
        )
        self.assertIsNone(metric)

    def test_nvda_recognition_wording_remains_supported(self) -> None:
        text = (
            "As of July 26, 2026, revenue related to remaining performance obligations from contracts greater than one year in length "
            "was $3.2 billion. Approximately 39% of revenue from contracts greater than one year in length will be recognized over the next twelve months."
        )
        metric = guard.r4._extract_strict_metric(text)
        self.assertIsNotNone(metric)
        future, classification = guard.r4._future_from_context(metric)
        self.assertEqual(classification, "INFERENCE")
        self.assertIn("39%", future)

    def test_r4_fail_closed_cases_remain_rejected(self) -> None:
        self.assertIsNone(guard.r4._extract_strict_metric("remaining performance obligations were $946"))
        self.assertIsNone(
            guard.r4._extract_strict_metric(
                "amortization expense included $23.5 related to the amortization of acquired backlog"
            )
        )


if __name__ == "__main__":
    unittest.main()
