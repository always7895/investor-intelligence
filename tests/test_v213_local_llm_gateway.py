from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location("v213_local_llm_gateway", SCRIPTS / "v213_local_llm_gateway.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class V213LocalGatewayFidelityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = MODULE.ORIGINAL_ENRICH

        def fake_enrich(messages):
            user = next((str(item.get("content") or "") for item in reversed(messages) if item.get("role") == "user"), "")
            ticker = MODULE.base.extract_ticker(user)
            return ([{"role": "system", "content": "base rules"}] + [dict(item) for item in messages], {
                "ticker": ticker,
                "successful_source_families": ["sec_edgar", "yahoo_finance_public_unofficial", "gleif_lei"],
                "source_diversity_status": "PASS",
            })

        MODULE.ORIGINAL_ENRICH = fake_enrich

    def tearDown(self) -> None:
        MODULE.ORIGINAL_ENRICH = self.original

    def test_stock_question_injects_public_logic_fidelity(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "AXTI 怎麼看"}])
        system = enriched[0]["content"]
        self.assertIn("SERENITY PUBLIC-LOGIC HIGH-FIDELITY RECONSTRUCTION", system)
        self.assertIn("legacy deterministic score", system)
        self.assertIn("Evidence-bound dependency graph", system)
        self.assertIn("company capture", system)
        self.assertIn("thesis killers", system)
        self.assertIn("public-logic reconstruction", system)
        self.assertEqual(context["serenity_public_logic_fidelity"], "2.1.3-source-independence-v3")
        self.assertFalse(context["private_process_reproduction_claimed"])
        self.assertFalse(context["official_serenity_formula_claimed"])
        self.assertEqual(context["model_confidence_cap"], "LIMITED")

    def test_methodology_question_injects_fidelity_even_without_ticker(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "Serenity 的投資邏輯是什麼"}])
        self.assertIn("SERENITY PUBLIC-LOGIC HIGH-FIDELITY RECONSTRUCTION", enriched[0]["content"])
        self.assertEqual(context["legacy_quantitative_overlay_label"], "System operationalization score")

    def test_supply_chain_question_injects_fidelity_even_without_ticker(self) -> None:
        enriched, _ = MODULE.enrich_messages([{"role": "user", "content": "這個供應鏈瓶頸怎麼判斷"}])
        self.assertIn("SERENITY PUBLIC-LOGIC HIGH-FIDELITY RECONSTRUCTION", enriched[0]["content"])

    def test_leopold_is_context_only_and_does_not_certify_full_skill(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "Leopold Aschenbrenner 的方法"}])
        self.assertIn("CONTEXT_ONLY", enriched[0]["content"])
        self.assertIn("6/12/24-month", enriched[0]["content"])
        self.assertIn("a filing/retrieval date is not delivery", enriched[0]["content"])
        proof = MODULE.methodology_execution_evidence(None, context)
        self.assertEqual(proof["lane"], "LEGACY_SYSTEM_DIRECTIVE")
        self.assertFalse(proof["full_skill_executed"])
        self.assertFalse(proof["model_adherence_verified"])
        self.assertEqual(proof["reference_files_loaded"], [])
        self.assertRegex(proof["directive_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(proof["aschenbrenner_role"], "CONTEXT_ONLY")

    def test_compact_and_smoke_cannot_borrow_legacy_methodology_evidence(self) -> None:
        _, context = MODULE.enrich_messages([{"role": "user", "content": "Serenity"}])
        for mode, lane in (("compact_public_v1", "COMPACT_POLICY_ONLY"),
                           ("transport_smoke_v1", "TRANSPORT_SMOKE")):
            proof = MODULE.methodology_execution_evidence(mode, context)
            self.assertEqual(proof["lane"], lane)
            self.assertIsNone(proof["directive_sha256"])
            self.assertFalse(proof["full_skill_executed"])
            self.assertEqual(proof["reference_files_loaded"], [])
        self.assertEqual(MODULE.methodology_execution_evidence(None, {})["lane"], "NO_RESEARCH_ENRICHMENT")

    def test_non_stock_general_question_does_not_force_serenity_method(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "你好"}])
        self.assertNotIn("SERENITY PUBLIC-LOGIC HIGH-FIDELITY RECONSTRUCTION", enriched[0]["content"])
        self.assertNotIn("serenity_public_logic_fidelity", context)

    def test_directive_forbids_false_official_score_and_unbound_signals(self) -> None:
        directive = MODULE.PUBLIC_LOGIC_DIRECTIVE
        self.assertIn("never as a Serenity score", directive)
        self.assertIn("named customer alone", directive)
        self.assertIn("evidence-bound graph edge", directive)
        self.assertIn("UNPROVEN/INSUFFICIENT_EVIDENCE", directive)
        self.assertIn("claim-relevant primary source", directive)
        self.assertIn("Company capture", directive)
        self.assertIn("independent corroboration", directive)
        self.assertIn("Conflicting sources", directive)
        self.assertIn("FRED is official macro context only", directive)


if __name__ == "__main__":
    unittest.main()
