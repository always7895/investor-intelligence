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
        self.assertIn("SERENITY PUBLIC-LOGIC FIDELITY", system)
        self.assertIn("System operationalization score", system)
        self.assertIn("evidence-bound supply-chain dependency graph", system)
        self.assertIn("company capture", system)
        self.assertIn("thesis-killer signal must be tied", system)
        self.assertIn("public-logic high-fidelity reconstruction", system)
        self.assertEqual(context["serenity_public_logic_fidelity"], "v2.1.3")
        self.assertFalse(context["private_process_reproduction_claimed"])
        self.assertFalse(context["cross_run_source_delta_append_only_verified"])

    def test_methodology_question_injects_fidelity_even_without_ticker(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "Serenity 的投資邏輯是什麼"}])
        self.assertIn("SERENITY PUBLIC-LOGIC FIDELITY", enriched[0]["content"])
        self.assertEqual(context["legacy_quantitative_overlay_label"], "System operationalization score")

    def test_supply_chain_question_injects_fidelity_even_without_ticker(self) -> None:
        enriched, _ = MODULE.enrich_messages([{"role": "user", "content": "這個供應鏈瓶頸怎麼判斷"}])
        self.assertIn("SERENITY PUBLIC-LOGIC FIDELITY", enriched[0]["content"])

    def test_non_stock_general_question_does_not_force_serenity_method(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "你好"}])
        self.assertNotIn("SERENITY PUBLIC-LOGIC FIDELITY", enriched[0]["content"])
        self.assertNotIn("serenity_public_logic_fidelity", context)

    def test_directive_forbids_false_official_score_and_unbound_signals(self) -> None:
        directive = MODULE.PUBLIC_LOGIC_DIRECTIVE
        self.assertIn("Never call it an official Serenity score", directive)
        self.assertIn("named customer dependency alone", directive)
        self.assertIn("BENEFICIARY label", directive)
        self.assertIn("Every dependency", directive)
        self.assertIn("UNPROVEN cannot jump", directive)
        self.assertIn("valid publication date", directive)
        self.assertIn("company capture", directive)
        self.assertIn("company-capture label alone cannot break", directive)
        self.assertIn("cross-run append-only", directive)
        self.assertIn("foreign listing", directive)


if __name__ == "__main__":
    unittest.main()
