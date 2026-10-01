"""Mocked transaction tests of scripts/sealed_freshness_task_transaction.ps1 (project audit 2026-09-29, round 2 finding 1).

Every scheduler command the transaction uses is replaced by a PowerShell function over an in-memory store (functions
take precedence over cmdlets), so no real task is read or changed. Each case asserts the actual mutation calls and the
final store, not text."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSACTION = ROOT / "scripts" / "sealed_freshness_task_transaction.ps1"
HOURLY, WATCHDOG = "InvestorIntelligenceSealedFreshness", "InvestorIntelligenceFreshnessWatchdog"

HARNESS = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$case = Get-Content -LiteralPath $args[0] -Raw | ConvertFrom-Json
$global:Store = @{}
foreach ($p in $case.existing.PSObject.Properties) { $global:Store[$p.Name] = [string]$p.Value }
$global:Calls = New-Object System.Collections.Generic.List[string]
$global:Minutes = @{ 'InvestorIntelligenceSealedFreshness' = 60; 'InvestorIntelligenceFreshnessWatchdog' = 30 }
function Fail-Name($list, $name) { return (@($list) -contains $name) }
function Get-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName)
    $global:Calls.Add("GET $TaskName")
    if (Fail-Name $case.lookup_fail $TaskName) { throw "SYNTHETIC_LOOKUP_FAILURE $TaskName" }
    if ($global:Store.ContainsKey($TaskName)) {
        return [pscustomobject]@{ TaskName = $TaskName; Principal = [pscustomobject]@{ LogonType = 'Interactive' }
            Settings = [pscustomobject]@{ StartWhenAvailable = $true; ExecutionTimeLimit = 'PT1H' }
            Triggers = @([pscustomobject]@{ Repetition = [pscustomobject]@{ Interval = "PT$($global:Minutes[$TaskName])M" } }) }
    }
    $record = New-Object Management.Automation.ErrorRecord ([Exception]"No task $TaskName"), 'NotFound', 'ObjectNotFound', $TaskName
    $PSCmdlet.WriteError($record)
}
function Export-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName)
    $global:Calls.Add("EXPORT $TaskName")
    if (Fail-Name $case.export_fail $TaskName) { throw "SYNTHETIC_EXPORT_FAILURE $TaskName" }
    return $global:Store[$TaskName]
}
function Register-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName, $Action, $Trigger, $Settings, $Principal, [string]$Description, [string]$Xml, [switch]$Force)
    $kind = if ($Xml) { 'RESTORE' } else { 'REGISTER' }
    $global:Calls.Add("$kind $TaskName")
    if ($kind -eq 'REGISTER' -and (Fail-Name $case.register_fail $TaskName)) { throw "SYNTHETIC_REGISTER_FAILURE $TaskName" }
    if ($kind -eq 'RESTORE' -and (Fail-Name $case.restore_fail $TaskName)) { throw "SYNTHETIC_RESTORE_FAILURE $TaskName" }
    $global:Store[$TaskName] = if ($Xml) { $Xml } else { "new:$TaskName" }
}
function Unregister-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName, [switch]$Confirm)
    $global:Calls.Add("UNREGISTER $TaskName")
    [void]$global:Store.Remove($TaskName)
}
function New-ScheduledTaskPrincipal { return 'principal' }
function New-ScheduledTaskSettingsSet { return 'settings' }
function New-ScheduledTaskTrigger { return 'trigger' }
. $args[1]
$definitions = @(
    @{ Name = 'InvestorIntelligenceSealedFreshness'; RepetitionMinutes = 60; Description = 'hourly' },
    @{ Name = 'InvestorIntelligenceFreshnessWatchdog'; RepetitionMinutes = 30; Description = 'watchdog' })
$errorText = $null
try { Invoke-SealedFreshnessTaskTransaction -Definitions $definitions -BuildAction { param($d) "action:$($d.Name)" } -CurrentUser 'owner' -LogonType 'Interactive' }
catch { $errorText = $_.Exception.Message }
[pscustomobject]@{ calls = @($global:Calls); store = $global:Store; error = $errorText } | ConvertTo-Json -Depth 5 -Compress
"""


@unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell not available")
class SealedFreshnessTaskTransactionTests(unittest.TestCase):
    def run_case(self, existing=None, **fail):
        case = {"existing": existing if existing is not None else {HOURLY: "<old hourly/>", WATCHDOG: "<old watchdog/>"},
                "lookup_fail": [], "export_fail": [], "register_fail": [], "restore_fail": []}
        case.update(fail)
        with tempfile.TemporaryDirectory() as tmp:
            harness, data = Path(tmp) / "harness.ps1", Path(tmp) / "case.json"
            harness.write_text(HARNESS, encoding="utf-8")
            data.write_text(json.dumps(case), encoding="utf-8")
            done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(harness),
                                   str(data), str(TRANSACTION)], capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        result = json.loads(done.stdout.strip().splitlines()[-1])
        mutations = [c for c in result["calls"] if c.split()[0] in ("REGISTER", "RESTORE", "UNREGISTER")]
        return result, mutations

    def test_first_capture_failure_changes_nothing(self):
        result, mutations = self.run_case(export_fail=[HOURLY])
        self.assertEqual(mutations, [])
        self.assertEqual(result["store"], {HOURLY: "<old hourly/>", WATCHDOG: "<old watchdog/>"})
        self.assertIn("SEALED_FRESHNESS_TASKS_UNCHANGED; PREIMAGE_CAPTURE_FAILED: export " + HOURLY, result["error"])

    def test_second_capture_failure_changes_nothing(self):
        result, mutations = self.run_case(export_fail=[WATCHDOG])
        self.assertEqual(mutations, [])
        self.assertEqual(result["store"], {HOURLY: "<old hourly/>", WATCHDOG: "<old watchdog/>"})
        self.assertIn("SEALED_FRESHNESS_TASKS_UNCHANGED", result["error"])

    def test_a_failed_lookup_is_not_absence(self):
        result, mutations = self.run_case(lookup_fail=[WATCHDOG])
        self.assertEqual(mutations, [])
        self.assertEqual(result["store"], {HOURLY: "<old hourly/>", WATCHDOG: "<old watchdog/>"})
        self.assertIn("PREIMAGE_CAPTURE_FAILED: lookup " + WATCHDOG, result["error"])

    def test_partial_registration_failure_restores_the_attempted_preimages(self):
        result, mutations = self.run_case(register_fail=[WATCHDOG])
        # both were attempted (the second call's outcome is ambiguous), so both return to their captured XML
        self.assertEqual(mutations, [f"REGISTER {HOURLY}", f"REGISTER {WATCHDOG}", f"RESTORE {HOURLY}", f"RESTORE {WATCHDOG}"])
        self.assertEqual(result["store"], {HOURLY: "<old hourly/>", WATCHDOG: "<old watchdog/>"})
        self.assertIn("rollback commands completed for 2 attempted task(s)", result["error"])

    def test_a_failure_on_the_first_task_never_touches_the_second(self):
        result, mutations = self.run_case(register_fail=[HOURLY])
        self.assertEqual(mutations, [f"REGISTER {HOURLY}", f"RESTORE {HOURLY}"])
        self.assertEqual(result["store"], {HOURLY: "<old hourly/>", WATCHDOG: "<old watchdog/>"})

    def test_newly_created_tasks_are_removed_and_preexisting_ones_restored(self):
        result, mutations = self.run_case(existing={HOURLY: "<old hourly/>"}, register_fail=[WATCHDOG])
        self.assertEqual(mutations, [f"REGISTER {HOURLY}", f"REGISTER {WATCHDOG}", f"RESTORE {HOURLY}"])
        # the watchdog did not exist and the failed register left nothing: no unregister was needed
        self.assertEqual(result["store"], {HOURLY: "<old hourly/>"})
        result, mutations = self.run_case(existing={})
        self.assertIsNone(result["error"])
        self.assertEqual(result["store"], {HOURLY: f"new:{HOURLY}", WATCHDOG: f"new:{WATCHDOG}"})

    def test_successful_registration_needs_no_recovery(self):
        result, mutations = self.run_case()
        self.assertIsNone(result["error"])
        self.assertEqual(mutations, [f"REGISTER {HOURLY}", f"REGISTER {WATCHDOG}"])
        self.assertEqual(result["store"], {HOURLY: f"new:{HOURLY}", WATCHDOG: f"new:{WATCHDOG}"})

    def test_rollback_failure_is_reported_unverified(self):
        result, mutations = self.run_case(register_fail=[WATCHDOG], restore_fail=[HOURLY])
        self.assertIn(f"RESTORE {HOURLY}", mutations)
        self.assertIn("rollback_unverified=true", result["error"])


if __name__ == "__main__":
    unittest.main()
