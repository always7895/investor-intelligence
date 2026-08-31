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
            return ([{"role": "system", "content": "base rules"}] + [dict(item) for item in messages], {
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
        self.assertIn("supply-chain dependency graph", system)
        self.assertIn("thesis killers", system)
        self.assertIn("public-logic high-fidelity reconstruction", system)
        self.assertEqual(context["serenity_public_logic_fidelity"], "v2.1.3")

    def test_methodology_question_injects_fidelity_even_without_ticker(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "Serenity 的投資邏輯是什麼"}])
        self.assertIn("SERENITY PUBLIC-LOGIC FIDELITY", enriched[0]["content"])
        self.assertEqual(context["legacy_quantitative_overlay_label"], "System operationalization score")

    def test_non_stock_general_question_does_not_force_serenity_method(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "你好"}])
        self.assertNotIn("SERENITY PUBLIC-LOGIC FIDELITY", enriched[0]["content"])
        self.assertNotIn("serenity_public_logic_fidelity", context)

    def test_directive_forbids_false_official_score_attribution(self) -> None:
        directive = MODULE.PUBLIC_LOGIC_DIRECTIVE
        self.assertIn("Never call it an official Serenity score", directive)
        self.assertIn("A keyword", directive)
        self.assertIn("high gross margin", directive)
        self.assertIn("Revenue growth alone", directive)
        self.assertIn("foreign listing", directive)


if __name__ == "__main__":
    unittest.main()
