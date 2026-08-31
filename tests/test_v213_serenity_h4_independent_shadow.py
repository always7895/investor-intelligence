#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "v213_serenity_h4_independent_shadow.py"
spec = importlib.util.spec_from_file_location("v213_serenity_h4_independent_shadow", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
assert spec.loader is not None
spec.loader.exec_module(mod)


class SerenityH4Tests(unittest.TestCase):
    def test_generic_design_win_is_rejected(self):
        self.assertFalse(mod.claim_is_eventive("design_win", "our sales cycle varies based on whether the design win is with an existing or new customer"))

    def test_hypothetical_qualification_constraint_is_rejected(self):
        self.assertFalse(mod.claim_is_eventive("qualification_constraint", "If we fail to meet the product qualification requirements of a customer, we may lose sales to that customer"))

    def test_dependency_candidate_audit_rejects_generic_risk_statement(self):
        audited = mod.audit_h3_claims({
            "extraction": {
                "signal_evidence": [],
                "dependency_candidates": [{
                    "signal": "qualification_constraint",
                    "excerpt": "If we fail to meet the product qualification and volume requirements of a customer, we may lose sales to that customer",
                    "evidence_url": "https://www.sec.gov/example",
                    "as_of": "2026-08-01T00:00:00Z",
                }],
            }
        })
        self.assertEqual(audited["accepted_dependency_candidates"], [])
        self.assertEqual([row["signal"] for row in audited["rejected"]], ["qualification_constraint"])

    def test_hypothetical_qualification_delay_is_rejected(self):
        self.assertFalse(mod.claim_is_eventive("qualification_delay", "Any failure or delay in obtaining such qualification could delay revenue and increase costs"))

    def test_market_network_capacity_is_not_company_capacity_expansion(self):
        self.assertFalse(mod.claim_is_eventive("capacity_expansion", "This need for capacity expansion across DCIs, metro regional networks, and long-haul networks continues"))

    def test_company_manufacturing_capacity_is_eventive(self):
        self.assertTrue(mod.claim_is_eventive("capacity_expansion", "Management expects to continue investments in manufacturing capacity and new equipment through 2027"))

    def test_same_atm_event_is_deduplicated(self):
        text = "On August 1, 2026 we entered into an at-the-market Sales Agreement for up to $100 million. The Sales Agreement entered into on August 1, 2026 may be used from time to time."
        self.assertEqual(len(mod._atm_event_keys_from_text(text)), 1)

    def test_soi_wrong_yahoo_symbol_is_detected(self):
        original = mod.fetch_text
        try:
            mod.fetch_text = lambda url, timeout=(10, 35): "Soitec Investor Relations financial reports"
            identity = mod.official_identity_shadow("SOI", {
                "ticker": "SOI",
                "evidence_summary": {"urls": ["https://finance.yahoo.com/quote/ZQM.SI"]},
            })
            self.assertTrue(identity["official_primary_ok"])
            self.assertEqual(identity["canonical_company_name"], "Soitec S.A.")
            self.assertEqual(identity["market_identity_mismatches"], ["ZQM.SI"])
        finally:
            mod.fetch_text = original

    def test_sive_profile_is_nasdaq_stockholm(self):
        self.assertEqual(mod.FOREIGN_PROFILES["SIVE"]["exchange"], "Nasdaq Stockholm")
        self.assertIn("SIVE", mod.FOREIGN_PROFILES["SIVE"]["allowed_market_symbols"])

    def test_hard_dependency_is_not_created_by_official_collaboration_alone(self):
        record = {
            "ticker": "SIVE", "focal_company_node": "SIVE",
            "architecture": {"current": "CPO", "as_of": "2026-06-02T00:00:00Z", "evidence_urls": ["https://example.com/a"]},
            "supply_chain_graph": [], "dependency_signals": [],
            "beneficiary_signal": True, "beneficiary_evidence_urls": ["https://example.com/a"],
            "signals": [], "signal_evidence": [],
            "information_gap": {"state": "UNKNOWN", "evidence_urls": []},
            "company_capture": {"state": "UNPROVEN", "evidence_urls": []},
            "evidence": [{"tier": "primary_strong", "url": "https://example.com/a"}],
            "thesis_killers": [], "disconfirmation_conditions": ["substitute qualifies"],
            "timing": {}, "serenity_source_views": [], "source_delta": [],
            "system_operationalization_score": None,
        }
        assessed = mod.fidelity.assess_public_logic(record)
        self.assertNotIn(assessed["public_logic_fidelity"]["dependency_role"], {
            "SINGLE_SOURCE", "SEMI_MONOPOLY", "QUALIFICATION_CONSTRAINED", "CAPACITY_BOTTLENECK"
        })


if __name__ == "__main__":
    unittest.main(verbosity=2)
