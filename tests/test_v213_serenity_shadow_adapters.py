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
    "v213_serenity_shadow_adapters",
    SCRIPTS / "v213_serenity_shadow_adapters.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SerenityShadowAdaptersV213Tests(unittest.TestCase):
    def context(self):
        return {
            "ticker": "TEST",
            "retrieved_at": "2026-08-31T00:00:00Z",
            "successful_source_families": [
                "sec_edgar", "yahoo_finance_public_unofficial", "gleif_lei", "world_bank_indicators",
            ],
            "source_diversity_status": "PASS",
            "sources": [
                {
                    "source_id": "sec_edgar", "ok": True,
                    "retrieved_at": "2026-08-31T00:00:00Z",
                    "summary": {
                        "companyfacts_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
                        "recent_material_filings": [{
                            "form": "10-Q", "filing_date": "2026-08-01",
                            "url": "https://www.sec.gov/Archives/test.htm",
                        }],
                    },
                },
                {
                    "source_id": "yahoo_finance_public_unofficial", "ok": True,
                    "retrieved_at": "2026-08-31T00:00:00Z",
                    "summary": {
                        "resolved_symbol": "TEST",
                        "news": [{"title": "lead", "published": "2026-08-30T00:00:00Z",
                                  "url": "https://finance.yahoo.com/news/test"}],
                    },
                },
                {
                    "source_id": "gleif_lei", "ok": True,
                    "retrieved_at": "2026-08-31T00:00:00Z",
                    "summary": {"url": "https://api.gleif.org/api/v1/lei-records?test=1"},
                },
                {
                    "source_id": "world_bank_indicators", "ok": True,
                    "retrieved_at": "2026-08-31T00:00:00Z",
                    "summary": {"url": "https://api.worldbank.org/v2/test"},
                },
            ],
        }

    def test_sec_is_primary_and_yahoo_is_lead_only(self):
        rows, status = MODULE.context_to_evidence(self.context())
        self.assertTrue(any(row["source_id"] == "sec_edgar" and row["tier"] == "primary_strong" for row in rows))
        self.assertTrue(any(row["source_id"] == "yahoo_finance_public_unofficial" and row["tier"] == "lead_only" for row in rows))
        self.assertGreaterEqual(status["primary_company_evidence_count"], 1)

    def test_macro_context_is_not_company_dependency_proof(self):
        rows, _ = MODULE.context_to_evidence(self.context())
        self.assertTrue([row for row in rows if row["claim_scope"] == "macro_context_only"])
        result = MODULE.fidelity.assess_public_logic(MODULE.conservative_record("TEST", rows, {}, None))
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "UNPROVEN")
        self.assertEqual(result["public_logic_fidelity"]["thesis_class"], "UNPROVEN")

    def test_signed_system_evidence_is_reused_as_context_without_creating_signals(self):
        rows, status = MODULE.context_to_evidence(self.context())
        system = {
            "score": 99,
            "evidence": [{
                "source_id": "sec_edgar", "tier": "T0",
                "url": "https://www.sec.gov/Archives/signed.htm",
                "as_of": "2026-08-15T00:00:00Z", "title": "Signed SEC evidence",
            }],
        }
        merged = MODULE.merge_system_evidence(rows, system)
        self.assertTrue(any(row["url"].endswith("signed.htm") and row["tier"] == "primary_strong" for row in merged))
        record = MODULE.conservative_record("TEST", merged, status, system)
        self.assertEqual(record["dependency_signals"], [])
        result = MODULE.fidelity.assess_public_logic(record)
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "UNPROVEN")

    def test_high_system_score_does_not_create_public_logic_bottleneck(self):
        rows, status = MODULE.context_to_evidence(self.context())
        record = MODULE.conservative_record("TEST", rows, status, {"score": 99, "rank": 1})
        result = MODULE.fidelity.assess_public_logic(record)
        self.assertEqual(result["system_operationalization_score"], 99)
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "UNPROVEN")
        self.assertFalse(result["system_score_can_override_broken_thesis"])

    def test_foreign_symbol_can_be_shadowed_without_sec(self):
        context = self.context()
        context["ticker"] = "SIVE"
        context["sources"] = [item for item in context["sources"] if item["source_id"] != "sec_edgar"]
        rows, status = MODULE.context_to_evidence(context)
        result = MODULE.fidelity.assess_public_logic(MODULE.conservative_record("SIVE", rows, status, None))
        self.assertEqual(result["ticker"], "SIVE")
        self.assertEqual(result["public_logic_fidelity"]["dependency_role"], "UNPROVEN")

    def test_no_signal_is_invented_by_adapter(self):
        rows, status = MODULE.context_to_evidence(self.context())
        record = MODULE.conservative_record("TEST", rows, status, {"score": 88})
        self.assertEqual(record["dependency_signals"], [])
        self.assertEqual(record["signals"], [])
        self.assertEqual(record["thesis_killers"], [])
        self.assertEqual(record["company_capture"]["state"], "UNPROVEN")

    def test_shadow_validator_enforces_boundaries(self):
        rows, status = MODULE.context_to_evidence(self.context())
        result = MODULE.fidelity.assess_public_logic(MODULE.conservative_record("TEST", rows, status, {"score": 80}))
        result["shadow_only"] = True
        MODULE.validate_shadow_result(result)

    def test_invalid_symbol_rejected(self):
        self.assertEqual(MODULE.clean_ticker(""), "")
        self.assertEqual(MODULE.clean_ticker("hello world"), "")

    def test_self_test(self):
        MODULE.self_test()


if __name__ == "__main__":
    unittest.main()
