"""Source gates for the operator decision of 2026-10-11 (LINE Q&A always follows the auto-detected local model, nothing hardcoded).

Behaviour is proved by the real-caller tests (tests.test_local_model_endpoint FollowDetectedTests, tests.test_local_runtime_independence,
tests.test_v213_bridge_model_identity, tests.test_company_business_profile). These gates only keep the shipped literals from
coming back: they read repository text, run no network, no PowerShell and no server."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "scripts" / "run_v213_local_llm_bridge_core.ps1"
ACTIVATION = ("activate-v213-diversified-schedule.ps1", "activate-v213-seven-field-schedule.ps1",
              "activate-v213-seven-field-schedule-core.ps1")


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


class FollowDetectedSourceGates(unittest.TestCase):
    def test_runtime_config_names_no_served_model(self):
        config = json.loads(text(ROOT / "config" / "local-runtime-independence-v1.json"))
        reasoner = config["primary_reasoner"]
        self.assertEqual((reasoner["model"], reasoner["model_selection"]), ("", "FOLLOW_DETECTED"))
        self.assertTrue(reasoner["base_url"].startswith("http://127.0.0.1:"))  # a first-probe hint, loopback only
        self.assertEqual((config["LOCAL_AI_ONLY"], config["PAID_INFERENCE_ALLOWED"], config["CLOUD_AI_FALLBACK"]), (True, False, False))

    def test_bridge_has_no_preferred_model_and_never_accepts_any_server_on_a_blank_id(self):
        source = text(BRIDGE)
        self.assertNotIn("RVN-Q6_K-multilingual-mtp", source)
        self.assertRegex(source, r"(?m)^\$preferredModel = ''\s*$")
        guard = "if ([string]::IsNullOrWhiteSpace($WantedModel)) { return $null }"
        self.assertIn(guard, source)
        self.assertLess(source.index(guard), source.index("foreach ($port in @(8080, 11434, 1234, 5001, 8081))"))
        self.assertNotIn("[string]::IsNullOrWhiteSpace($WantedModel) -or", source)  # the old blank-accepts-any-server clause is gone
        # The bridge asks Find-LocalModelServer for the real wanted id (request, else the saved selection), not the raw request.
        self.assertIn("$found = Find-LocalModelServer $Base $wanted", source)
        # Windows PowerShell 5.1 drops an empty argument: --want is passed only when a wanted id exists.
        self.assertIn("@('--want', $wanted)", source)

    def test_bridge_profile_model_pins_only_for_an_explicit_binding_and_the_following_profile_exists_for_every_mode(self):
        source = text(BRIDGE)
        self.assertIn("if ($runtimeProfile -and -not $script:ExplicitBinding) { $runtimeProfile = $null }", source)
        self.assertIn("if (-not $script:ExplicitBinding -and -not $runtimeProfile) { $runtimeProfile = Set-FollowingModelProfile $Model }", source)
        self.assertNotRegex(source, r"-and \$tunnelPolicy\.mode -eq 'FreeRelay' -and -not \$runtimeProfile")
        self.assertIn("if ($script:ExplicitBinding -and $Model -and $Model -cne $checkProfile.model)", source)
        self.assertIn("'MODEL_PROFILE_SELECTION_MISMATCH'", source)  # the explicit-binding pin still refuses a different id

    def test_activation_scripts_do_not_pin_a_model_literal_but_keep_the_exact_equality_with_the_verified_state(self):
        for name in ACTIVATION:
            source = text(ROOT / name)
            with self.subTest(script=name):
                self.assertNotIn("qwen38-q6", source)
                self.assertRegex(source, r"(?i)\$(?:model|RequiredModel)\s*-ine\s*\$RequiredModel|\$model-ine\$RequiredModel")
                self.assertIn("[A-Za-z0-9][A-Za-z0-9._:/+", source)  # the same model-id character class as every other validator

    def test_launcher_prefers_the_saved_selection_over_the_profile_model(self):
        source = text(ROOT / "launcher" / "InvestorIntelligenceLauncher.cs")
        self.assertIn('Model = (root.ContainsKey("model") && !String.IsNullOrEmpty(Convert.ToString(root["model"]))) '
                      '? Convert.ToString(root["model"]) : PreferredModel,', source)
        self.assertNotIn('Model = !String.IsNullOrEmpty(PreferredModel) ? PreferredModel', source)

    def test_company_business_profile_reads_the_optional_configured_model_without_a_key_error(self):
        source = text(ROOT / "scripts" / "company_business_profile.py")
        self.assertIn('configured_model = str(reasoner.get("model") or "")', source)
        self.assertNotRegex(source, r'reasoner\["model"\]')

    def test_explicit_binding_and_loopback_safety_properties_are_still_declared(self):
        endpoint = text(ROOT / "scripts" / "local_model_endpoint.py")
        self.assertIn("NEVER_PROBED = {5000, 8000}", endpoint)
        self.assertIn("LOCAL_MODEL_AMBIGUOUS", endpoint)
        self.assertRegex(endpoint, r'ProxyHandler\(\{\}\)')
        self.assertIsNone(re.search(r"https?://(?!127\.0\.0\.1|localhost)[a-z0-9.-]+/v1", text(ROOT / "config" / "local-runtime-independence-v1.json")))


if __name__ == "__main__":
    unittest.main()
