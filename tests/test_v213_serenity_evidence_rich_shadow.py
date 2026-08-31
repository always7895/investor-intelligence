from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "v213_serenity_evidence_rich_shadow",
    SCRIPTS / "v213_serenity_evidence_rich_shadow.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SerenityEvidenceRichH3Tests(unittest.TestCase):
    def filing(self, url="https://www.sec.gov/Archives/test.htm", date="2026-08-01T00:00:00Z"):
        return [{
            "tier": "primary_strong",
            "source_id": "sec_edgar",
            "claim_scope": "company_regulatory_filing",
            "url": url,
            "as_of": date,
            "title": "SEC filing",
        }]

    def extract_text(self, text, evidence=None):
        original = MODULE.fetch_sec_document
        try:
            MODULE.fetch_sec_document = lambda url: text
            return MODULE.extract_from_filings("TEST", evidence or self.filing())
        finally:
            MODULE.fetch_sec_document = original

    def test_issuer_scarcity_language_is_candidate_not_proven_bottleneck(self):
        extracted = self.extract_text(
            "We are one of only two qualified suppliers. Our products are qualified by our customer. "
            "We announced a capacity expansion for 1.6T optical networking."
        )
        self.assertTrue(extracted["dependency_candidates"])
        self.assertFalse(extracted["independent_dependency_corroboration"])
        record = MODULE.build_rich_record("TEST", self.filing(), {}, {"score": 99}, extracted)
        result = MODULE.fidelity.assess_public_logic(record)
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "UNPROVEN")
        self.assertEqual(result["public_logic_fidelity"]["thesis_class"], "EXPANSION_THESIS")

    def test_upstream_single_source_risk_is_not_focal_company_bottleneck(self):
        extracted = self.extract_text("We depend on a sole source supplier for a critical raw material.")
        self.assertTrue(extracted["upstream_dependency_risks"])
        self.assertFalse(extracted["dependency_candidates"])
        record = MODULE.build_rich_record("TEST", self.filing(), {}, {"score": 88}, extracted)
        result = MODULE.fidelity.assess_public_logic(record)
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "UNPROVEN")

    def test_vertical_integration_is_expansion_not_chokepoint(self):
        extracted = self.extract_text("We are vertically integrated and continue our capacity expansion.")
        self.assertIn("vertical_integration", extracted["expansion_signals"])
        record = MODULE.build_rich_record("TEST", self.filing(), {}, None, extracted)
        result = MODULE.fidelity.assess_public_logic(record)
        self.assertEqual(result["public_logic_fidelity"]["thesis_class"], "EXPANSION_THESIS")
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "UNPROVEN")

    def test_two_distinct_atm_filings_create_repeated_dilution_killer(self):
        evidence = self.filing("https://www.sec.gov/Archives/a.htm", "2026-07-01T00:00:00Z") + self.filing(
            "https://www.sec.gov/Archives/b.htm", "2026-08-01T00:00:00Z"
        )
        original = MODULE.fetch_sec_document
        try:
            MODULE.fetch_sec_document = lambda url: "We entered into an at-the-market offering sales agreement for common stock."
            extracted = MODULE.extract_from_filings("TEST", evidence)
        finally:
            MODULE.fetch_sec_document = original
        self.assertIn("repeated_atm_or_material_dilution", extracted["killer_signals"])
        record = MODULE.build_rich_record("TEST", evidence, {}, {"score": 100}, extracted)
        result = MODULE.fidelity.assess_public_logic(record)
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "THESIS_WEAKENING")
        self.assertFalse(result["system_score_can_override_broken_thesis"])

    def test_single_atm_does_not_claim_repeated_atm(self):
        extracted = self.extract_text("We entered into an at-the-market offering sales agreement for common stock.")
        self.assertNotIn("repeated_atm_or_material_dilution", extracted["killer_signals"])

    def test_going_concern_is_evidence_bound_funding_killer(self):
        extracted = self.extract_text("There is substantial doubt about our ability to continue as a going concern.")
        self.assertIn("balance_sheet_funding_failure", extracted["killer_signals"])
        record = MODULE.build_rich_record("TEST", self.filing(), {}, None, extracted)
        result = MODULE.fidelity.assess_public_logic(record)
        self.assertEqual(result["public_logic_fidelity"]["thesis_state"], "THESIS_WEAKENING")

    def test_architecture_candidate_is_dated_and_bound(self):
        extracted = self.extract_text("Our 800G optical networking products entered customer qualification.")
        self.assertEqual(extracted["architecture_candidates"][0]["label"], "800G optical networking")
        record = MODULE.build_rich_record("TEST", self.filing(), {}, None, extracted)
        self.assertEqual(record["architecture"]["as_of"], "2026-08-01T00:00:00Z")
        self.assertEqual(record["architecture"]["evidence_urls"], ["https://www.sec.gov/Archives/test.htm"])

    def test_non_sec_document_is_refused(self):
        with self.assertRaises(ValueError):
            MODULE.fetch_sec_document("https://example.com/filing")

    def test_excerpt_is_bounded(self):
        text = "x" * 500 + " design win " + "y" * 500
        extracted = self.extract_text(text)
        rows = [row for row in extracted["signal_evidence"] if row["signal"] == "design_win"]
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(len(rows[0]["excerpt"]), MODULE.MAX_EXCERPT)

    def test_beneficiary_requires_explicit_demand_link(self):
        extracted = self.extract_text("Demand for our products increased due to data center AI deployments.")
        self.assertTrue(extracted["beneficiary_evidence_urls"])
        record = MODULE.build_rich_record("TEST", self.filing(), {}, None, extracted)
        result = MODULE.fidelity.assess_public_logic(record)
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "BENEFICIARY")
        self.assertNotEqual(result["public_logic_fidelity"]["dependency_role"], "SEMI_MONOPOLY")

    def test_canonical_safety_excludes_retrieval_timestamp_noise(self):
        base = {
            "ticker": "TEST", "system_operationalization_score": 50,
            "public_logic_fidelity": {
                "dependency_role": "UNPROVEN", "thesis_class": "UNPROVEN",
                "thesis_state": "DISCOVERY", "company_capture": {"state": "UNPROVEN"},
                "thesis_killers": [],
            },
            "extraction": {"dependency_candidates": [], "independent_dependency_corroboration": False},
            "generated_at": "one",
        }
        other = dict(base, generated_at="two")
        self.assertEqual(MODULE.canonical_safety(base), MODULE.canonical_safety(other))

    def test_self_test(self):
        MODULE.self_test()


if __name__ == "__main__":
    unittest.main()
