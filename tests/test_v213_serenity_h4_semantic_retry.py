#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "v213_serenity_h4_semantic_retry.py"
spec = importlib.util.spec_from_file_location("v213_serenity_h4_semantic_retry", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
assert spec.loader is not None
spec.loader.exec_module(mod)


class H4SemanticRetryTests(unittest.TestCase):
    def test_par_value_does_not_create_atm_event(self):
        text = (
            "On March 12, 2026, we entered into an at-the-market Sales Agreement for up to $250 million. "
            "The common stock has a par value of $0.001 per share."
        )
        self.assertEqual(mod.strong_atm_event_keys(text), ["entered into|march 12, 2026|$250000000"])

    def test_same_atm_event_repeated_in_text_is_deduped(self):
        text = (
            "On March 12, 2026, we entered into an at-the-market Sales Agreement for up to $250 million. "
            "On March 12, 2026, the at-the-market Sales Agreement for up to $250 million was described again."
        )
        self.assertEqual(len(mod.strong_atm_event_keys(text)), 1)

    def test_undated_or_noamount_atm_reference_is_not_event(self):
        self.assertEqual(mod.strong_atm_event_keys("We may use our at-the-market program from time to time."), [])

    def test_tsem_explicit_announcement_is_eventive(self):
        self.assertTrue(mod.tsem_capacity_is_observed(
            "The Registrant Announces Tower Semiconductor with METI Support Announces Strategic Capacity Expansion in Japan"
        ))

    def test_tsem_hypothetical_expansion_is_not_eventive(self):
        self.assertFalse(mod.tsem_capacity_is_observed(
            "If market demand improves, we may consider a capacity expansion in Japan."
        ))

    def test_sive_capture_reconciliation_does_not_change_dependency_role(self):
        row = {
            "ticker": "SIVE",
            "identity_verification": {
                "official_primary_retry": {"official_primary_ok": True, "official_sources": []},
                "official_sources": [{"ok": True, "url": "https://www.sivers-semiconductors.com/press/q2-2026-test/"}],
            },
            "supported_signals": {"commercial_validation": ["customer_named_ramp"]},
            "public_logic_fidelity": {
                "dependency_role": "BENEFICIARY",
                "company_capture": {"state": "UNPROVEN", "evidence_urls": []},
                "thesis_class": "UNPROVEN",
                "thesis_state": "INSUFFICIENT_EVIDENCE",
            },
        }
        self.assertTrue(mod._reconcile_sive_capture(row))
        self.assertEqual(row["public_logic_fidelity"]["company_capture"]["state"], "POSITIVE")
        self.assertEqual(row["public_logic_fidelity"]["dependency_role"], "BENEFICIARY")
        self.assertEqual(row["public_logic_fidelity"]["thesis_class"], "UNPROVEN")

    def test_tsem_restore_removes_false_correction(self):
        row = {
            "ticker": "TSEM",
            "h3_claim_quality_audit": {
                "accepted": [],
                "rejected": [{
                    "signal": "capacity_expansion",
                    "excerpt": "The Registrant Announces Tower Semiconductor with METI Support Announces Strategic Capacity Expansion in Japan",
                    "evidence_url": "https://www.sec.gov/example",
                    "as_of": "2026-07-14T00:00:00Z",
                    "rejection_reason": "generic_or_hypothetical_not_observed_event",
                }],
            },
            "h4_corrections": [{"signal": "capacity_expansion", "reason": "generic_or_hypothetical_not_observed_event"}],
            "supported_signals": {"expansion": []},
            "public_logic_fidelity": {
                "dependency_role": "UNPROVEN",
                "company_capture": {"state": "UNPROVEN", "evidence_urls": []},
                "thesis_class": "UNPROVEN",
                "thesis_state": "INSUFFICIENT_EVIDENCE",
            },
        }
        self.assertTrue(mod._restore_tsem_capacity(row))
        self.assertEqual(row["h4_corrections"], [])
        self.assertIn("capacity_expansion", row["supported_signals"]["expansion"])
        self.assertEqual(row["public_logic_fidelity"]["thesis_class"], "EXPANSION_THESIS")
        self.assertEqual(row["public_logic_fidelity"]["dependency_role"], "UNPROVEN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
