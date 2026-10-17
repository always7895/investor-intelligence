"""M2 source wiring tripwires ONLY: no PowerShell/native/UI execution proof."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def source(name):
    return (ROOT / name).read_text(encoding='utf-8-sig')


class CallerSourceContracts(unittest.TestCase):
    def test_both_root_wrappers_forward_presence_not_default_binding(self):
        for name in ('run-v213-local-llm-bridge.ps1', 'run-v213-local-llm-bridge-source-diverse.ps1'):
            text = source(name)
            with self.subTest(name=name):
                self.assertIn('[AllowNull()][AllowEmptyString()][string]$BindingJson', text)
                self.assertIn('[switch]$BindingMetadataCheckOnly', text)
                self.assertIn('scripts\\run_v213_local_llm_bridge_core_v2.ps1', text)
                self.assertTrue(text.rstrip().endswith('& $core @PSBoundParameters'))
                self.assertNotIn('Start-Process', text)
                self.assertNotIn('Invoke-RestMethod', text)

    def test_core_v2_explicit_branch_precedes_bootstrap_and_core_returns_metadata_early(self):
        text = source('scripts/run_v213_local_llm_bridge_core_v2.ps1')
        start = text.index('if ($explicit -or $BindingMetadataCheckOnly) {')
        end = text.index('function Test-GatewayPython')
        branch = text[start:end]
        self.assertIn('$PSBoundParameters.Keys', branch)
        self.assertIn('& $core @forward', branch)
        self.assertIn('exit $LASTEXITCODE', branch)
        self.assertLess(end, text.index('& $bootstrap -DestinationPath'))
        core = source('scripts/run_v213_local_llm_bridge_core.ps1')
        early = core.index('if ($BindingMetadataCheckOnly -or $BindingPreflightOnly) { $intentOutput; return }')
        self.assertLess(core.index("$intentArgs += '--metadata-check'"), early)
        self.assertLess(core.index("throw 'BINDING_PYTHON_PREREQUISITE_UNAVAILABLE'"), early)
        self.assertLess(early, core.index('if ($StopExisting) { $FinalizeCutover = $true }'))
        self.assertIn('$env:V213_RUNTIME_BINDING_JSON = $BindingJson', core)
        self.assertIn("scripts\\v213_local_llm_gateway.py", core)

    def test_watchdog_refusal_precedes_runtime_state_processes_and_health(self):
        text = source('scripts/v213_free_relay_watchdog.ps1')
        branch_start = text.index("if ($null -eq $found -or $null -ne (Get-Field $found 'error')) {")
        state_start = text.index('$state = $null', branch_start)
        self.assertIn('exit 0', text[branch_start:state_start])
        self.assertLess(state_start, text.index('$alive = (Test-Alive'))
        self.assertLess(state_start, text.index('$health = Invoke-RestMethod'))
        health = text[text.index('function Test-GatewayServesFound'):text.index('function Get-WatchdogDecision')]
        for field in ('runtime_binding_sha256', 'binding_sha256', 'model_profile_sha256', 'UNQUALIFIED'):
            self.assertIn(field, health)
        self.assertIn("[string](Get-Field $Health 'selected_model') -ceq [string](Get-Field $Found 'model')", health)

    def test_launcher_uses_one_helper_and_serialized_explicit_operations(self):
        text = source('launcher/InvestorIntelligenceLauncher.cs')
        self.assertIn('Path.Combine(Root, "scripts", "local_model_catalog.py")', text)
        self.assertIn('static void RemoveExplicitBinding() { WithIntentLock(RemoveExplicitBindingLocked); }', text)
        self.assertIn('WithIntentLock(delegate { SaveExplicitBindingLocked(model, endpoint, effort, output, smoke, timeout); });', text)
        self.assertIn('return WithIntentLock(delegate { return RunCatalogSelectionLocked(op, request); });', text)
        self.assertIn('" -BindingJson " + PowerShellLiteral(selection.BindingJson)', text)
        self.assertIn('RunBindingHelper("--save-binding-stdin", request, true)', text)
        self.assertIn('RunBindingHelper("--remove-binding", null, true)', text)


if __name__ == '__main__':
    unittest.main()
