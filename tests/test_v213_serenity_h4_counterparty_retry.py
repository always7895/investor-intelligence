#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "v213_serenity_h4_counterparty_retry.py"
spec = importlib.util.spec_from_file_location("v213_serenity_h4_counterparty_retry", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
assert spec.loader is not None
spec.loader.exec_module(mod)


class H4CounterpartyRetryTests(unittest.TestCase):
    def test_generic_gf_page_is_not_enough(self):
        text = "GlobalFoundries silicon photonics enables CPO for many ecosystem partners."
        self.assertFalse(mod.validate_gf_sivers_corroboration(text))

    def test_explicit_sivers_gf_relationship_is_accepted(self):
        text = "Sivers & GlobalFoundries Advance AI Data Center Optical Solutions through silicon photonics collaboration."
        self.assertTrue(mod.validate_gf_sivers_corroboration(text))

    def test_patch_adds_independent_edge_without_changing_role(self):
        doc = {
            "summary": {"production_ranking_changed": False},
            "results": [{
                "ticker": "SIVE",
                "independent_graph_edge_count": 0,
                "independent_corroboration": [],
                "public_logic_fidelity": {
                    "dependency_role": "BENEFICIARY",
                    "supply_chain_graph": [],
                    "graph_touches_focal_company": False,
                },
            }],
        }
        corr = {
            "official_counterparty_ok": True,
            "attempts": [{
                "counterparty": "GlobalFoundries Inc.",
                "url": mod.GF_OFFICIAL_URLS[0],
                "relationship": "official ecosystem collaboration",
                "independent": True,
                "official_counterparty": True,
                "ok": True,
            }],
        }
        patched = mod.patch_document(doc, corr)
        row = patched["results"][0]
        self.assertEqual(row["independent_graph_edge_count"], 1)
        self.assertEqual(row["public_logic_fidelity"]["dependency_role"], "BENEFICIARY")
        self.assertTrue(row["public_logic_fidelity"]["graph_touches_focal_company"])
        self.assertEqual(patched["summary"]["independent_graph_edge_count"], 1)

    def test_hard_role_input_is_refused(self):
        doc = {
            "summary": {},
            "results": [{
                "ticker": "SIVE",
                "independent_graph_edge_count": 0,
                "public_logic_fidelity": {
                    "dependency_role": "SEMI_MONOPOLY",
                    "supply_chain_graph": [],
                },
            }],
        }
        with self.assertRaises(ValueError):
            mod.patch_document(doc, {"official_counterparty_ok": False, "attempts": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
