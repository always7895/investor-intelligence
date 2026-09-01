#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6b1_zero_safe as guard


class H6B1ZeroSafeTests(unittest.TestCase):
    def policy(self) -> dict:
        return {
            "h6a_source_history_checkpoint": {
                "entries": 4,
                "latest_hash": "checkpoint",
            }
        }

    def valid(self) -> dict:
        return {
            "summary": {
                "completed": 7,
                "failed": 0,
                "hard_dependency_count": 0,
                "production_ranking_changed": False,
            },
            "h6_source_history_attestation": {
                "entries": 4,
                "latest_hash": "checkpoint",
                "structural_chain_verified": True,
            },
        }

    def test_numeric_zero_failed_and_hard_dependency_are_preserved(self) -> None:
        result = guard.verify_h6a_zero_safe(self.valid(), self.policy())
        self.assertEqual(result["entries"], 4)
        self.assertTrue(result["structural_chain_verified"])

    def test_missing_failed_fails_closed(self) -> None:
        doc = self.valid()
        del doc["summary"]["failed"]
        with self.assertRaises(guard.base.H6BError):
            guard.verify_h6a_zero_safe(doc, self.policy())

    def test_missing_hard_dependency_count_fails_closed(self) -> None:
        doc = self.valid()
        del doc["summary"]["hard_dependency_count"]
        with self.assertRaises(guard.base.H6BError):
            guard.verify_h6a_zero_safe(doc, self.policy())

    def test_boolean_is_not_accepted_as_integer_attestation(self) -> None:
        doc = self.valid()
        doc["summary"]["failed"] = False
        with self.assertRaises(guard.base.H6BError):
            guard.verify_h6a_zero_safe(doc, self.policy())

    def test_production_ranking_requires_explicit_false(self) -> None:
        doc = self.valid()
        del doc["summary"]["production_ranking_changed"]
        with self.assertRaises(guard.base.H6BError):
            guard.verify_h6a_zero_safe(doc, self.policy())

    def test_wrapper_bootstraps_its_script_directory_before_sibling_import(self) -> None:
        source = (SCRIPTS / "v213_serenity_h6b1_zero_safe.py").read_text(encoding="utf-8")
        insert_pos = source.index("sys.path.insert(0, str(SCRIPT_DIR))")
        import_pos = source.index("import v213_serenity_h6b_full_top20 as base")
        self.assertLess(insert_pos, import_pos)
        self.assertEqual(guard.SCRIPT_DIR, SCRIPTS)
        self.assertIn(str(SCRIPTS), sys.path)


if __name__ == "__main__":
    unittest.main()
