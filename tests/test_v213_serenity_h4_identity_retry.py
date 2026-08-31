#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "v213_serenity_h4_identity_retry.py"
spec = importlib.util.spec_from_file_location("v213_serenity_h4_identity_retry", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
assert spec.loader is not None
spec.loader.exec_module(mod)


class H4IdentityRetryTests(unittest.TestCase):
    def test_sive_company_plus_sto_ticker_is_accepted(self):
        self.assertTrue(mod.validates_sive_identity("Sivers Semiconductors AB (STO:SIVE) reports Q2 results"))

    def test_sive_company_plus_nasdaq_stockholm_is_accepted(self):
        self.assertTrue(mod.validates_sive_identity("Sivers Semiconductors will publish before trading on Nasdaq Stockholm"))

    def test_company_name_without_exchange_marker_is_rejected(self):
        self.assertFalse(mod.validates_sive_identity("Sivers Semiconductors develops photonics solutions"))

    def test_exchange_marker_without_company_name_is_rejected(self):
        self.assertFalse(mod.validates_sive_identity("Nasdaq Stockholm technology issuer"))

    def test_patch_only_changes_identity_when_retry_passes(self):
        original = mod.retry_sive_identity
        try:
            mod.retry_sive_identity = lambda: {
                "canonical_company_name": "Sivers Semiconductors AB",
                "exchange": "Nasdaq Stockholm",
                "official_sources": [{"url": "https://www.sivers-semiconductors.com/investors/interim-reports/", "ok": True}],
                "official_primary_ok": True,
                "identity_status": "PASS",
                "validation_rule": "test",
            }
            doc = {
                "summary": {},
                "results": [{"ticker": "SIVE", "identity_verification": {"official_primary_ok": False, "identity_status": "DEGRADED"}}],
            }
            patched = mod.patch_report(doc)
            identity = patched["results"][0]["identity_verification"]
            self.assertTrue(identity["official_primary_ok"])
            self.assertEqual(identity["canonical_company_name"], "Sivers Semiconductors AB")
            self.assertEqual(identity["exchange"], "Nasdaq Stockholm")
            self.assertTrue(patched["h4_identity_retry_shadow_only"])
        finally:
            mod.retry_sive_identity = original

    def test_retry_does_not_create_dependency_signal(self):
        original = mod.retry_sive_identity
        try:
            mod.retry_sive_identity = lambda: {
                "canonical_company_name": "Sivers Semiconductors AB",
                "exchange": "Nasdaq Stockholm",
                "official_sources": [{"url": "https://example.invalid", "ok": True}],
                "official_primary_ok": True,
                "identity_status": "PASS",
                "validation_rule": "test",
            }
            doc = {
                "summary": {},
                "results": [{
                    "ticker": "SIVE",
                    "identity_verification": {},
                    "public_logic_fidelity": {"dependency_role": "UNPROVEN"},
                }],
            }
            patched = mod.patch_report(doc)
            self.assertEqual(patched["results"][0]["public_logic_fidelity"]["dependency_role"], "UNPROVEN")
        finally:
            mod.retry_sive_identity = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
