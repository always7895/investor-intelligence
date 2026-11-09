"""Daily refresh cadence/wiring through the real function and normal-entry call plan.

Only in-memory step/contact collaborators run: no collectors, network, credentials or
installed state. The normal-entry case evaluates its actual parameter block and daily
dispatch command, not the native/contact/backend adapters. Collector cache/gating is
covered separately by test_v11_consensus_collector.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r"""param(
    [string]$Repo, [string]$FailStep = '', [switch]$Auto, [switch]$NoContact,
    [switch]$Force, [switch]$ExplicitDisabled, [switch]$NormalEntryPlan, [switch]$BudgetPlan,
    [double]$Hours = 20
)
$ErrorActionPreference = 'Continue'
. (Join-Path (Join-Path $Repo 'scripts') 'run_daily_data_refresh.ps1')
$script:Rec = New-Object System.Collections.Generic.List[string]
$script:FailStep = $FailStep
$script:HasContact = -not $NoContact
$runStep = {
    param([string]$Name, [string[]]$Arguments)
    $script:Rec.Add($Name + '|' + ($Arguments -join ' '))
    $code = 0
    if ($Name -eq $script:FailStep) { $code = 1 }
    [pscustomobject]@{ ExitCode = $code; Lines = @() }
}
$withContact = { param([scriptblock]$Work) & $Work $script:HasContact }
$script:Slices = New-Object System.Collections.Generic.List[long]
$extra = @{ IfOlderThanHours = $Hours }
if ($Force) { $extra['ForceGuidanceRankingPair'] = $true }
if ($Auto) { $extra['GuidanceAutoUpdateEnabled'] = $true }
if ($ExplicitDisabled) {
    $extra['GuidanceAutoUpdateEnabled'] = $false
    $extra['GuidanceDirtyRebuildEnabled'] = $false
    $extra['ForceGuidanceRankingPair'] = $false
}
if ($NormalEntryPlan -or $BudgetPlan) {
    # Parse only; no normal-entry contact, backend, native launch or exit paths.
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path (Join-Path $Repo 'scripts') 'run_daily_data_refresh.ps1'),
        [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -ne 0) { throw 'DAILY_PLAN_PARSE_FAILED' }
}
if ($NormalEntryPlan) {
    $calls = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.CommandAst] -and
            $node.GetCommandName() -eq 'Invoke-DailyDataRefresh'
    }, $true))
    if ($calls.Count -ne 1) { throw 'DAILY_PLAN_DISPATCH_AMBIGUOUS' }
    $realRunStep = $runStep
    $realWithSecContact = $withContact
    $realProvider = $null
    $realRanking = $null
    $plan = [scriptblock]::Create($ast.ParamBlock.Extent.Text + "`n" + $calls[0].Extent.Text)
    $entryOptions = @{}
    if ($Force) { $entryOptions['D2ForceGuidanceRankingPair'] = $true }
    if ($Auto) { $entryOptions['GuidanceAutoUpdateEnabled'] = $true }
    $result = & $plan @entryOptions
}
elseif ($BudgetPlan) {
    # Execute the real budget initialization and step adapter, but replace the
    # observed-process boundary so no process or protected backend is opened.
    $countAssignments = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
            $node.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
            $node.Left.VariablePath.UserPath -eq 'ordinaryStepsLeft'
    }, $true))
    $stepAssignments = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
            $node.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
            $node.Left.VariablePath.UserPath -eq 'realRunStep'
    }, $true))
    if ($countAssignments.Count -ne 1 -or $stepAssignments.Count -ne 1) { throw 'DAILY_BUDGET_PLAN_AMBIGUOUS' }
    function Invoke-GuidanceObservedProcess {
        param([string]$Label, [string]$Executable, [string[]]$Arguments,
              [string]$WorkingDirectory, [long]$RemainingMilliseconds)
        $script:Slices.Add($RemainingMilliseconds)
        $script:Rec.Add($Label.Substring('DAILY_'.Length) + '|' + ($Arguments -join ' '))
        [pscustomobject]@{ ExitCode = 0; Lines = @(); Status = 'COMPLETED'; Attempted = $true; Completed = $true }
    }
    $GuidanceAutoUpdateEnabled = $true
    $guidanceBackendLoaded = $true
    $guidanceClock = [pscustomobject]@{ ElapsedMilliseconds = 0 }
    $GuidanceBudgetMilliseconds = 600000
    $python = 'plan-only'
    . ([scriptblock]::Create($countAssignments[0].Extent.Text + "`n" + $stepAssignments[0].Extent.Text))
    $result = Invoke-DailyDataRefresh -RunStep $realRunStep -WithSecContact $withContact -GuidanceAutoUpdateEnabled $true
}
else {
    $result = Invoke-DailyDataRefresh -RunStep $runStep -WithSecContact $withContact @extra
}
[pscustomobject]@{
    steps = @($script:Rec); exit = $result.ExitCode; failed = @($result.FailedSteps)
    disposition = $result.B2.Disposition; reason = $result.B2.Reason
    slices = @($script:Slices)
} | ConvertTo-Json -Compress
"""
STEP = "revenue_consensus|scripts\\revenue_consensus_quarterly.py --if-older-than-hours 6"
DEFAULT_STEPS = [
    "zh_names|scripts\\build_zh_names.py --if-older-than-hours 168",
    "identity_shards|scripts\\build_identity_shards.py --if-older-than-hours 20",
    "serenity_signals|scripts\\serenity_signals.py --refresh --if-older-than-hours 0.9",
    STEP,
    "industry_rotation|scripts\\industry_rotation.py --refresh --if-older-than-hours 20",
    "company_reports|scripts\\company_deep_report.py --refresh --if-older-than-hours 20",
    "leopold_13f|scripts\\leopold_positions.py --if-older-than-hours 0.9",
    "public_events|scripts\\public_event_research.py --refresh-sec --if-older-than-hours 0.9",
    "guidance_release_check|scripts\\revenue_guidance_release_check.py --if-older-than-hours 0.9",
    "bottleneck_v3|scripts\\bottleneck_top20_v3.py --if-older-than-hours 0",
    "price_shards|scripts\\build_price_shards.py --if-older-than-hours 2.9",
    "market_observations|scripts\\build_market_quotes_options.py --if-older-than-hours 0.9",
]
AUTO_STEPS = DEFAULT_STEPS[:8] + DEFAULT_STEPS[10:]
NO_CONTACT_STEPS = DEFAULT_STEPS[:4] + DEFAULT_STEPS[10:]
FORCED_STEPS = list(DEFAULT_STEPS)
# Ranking already runs every refresh; D2 now changes only the release-check cache.
FORCED_STEPS[8] = "guidance_release_check|scripts\\revenue_guidance_release_check.py --if-older-than-hours 0"


def shells() -> list[list[str]]:
    found = []
    if shutil.which("pwsh"):
        found.append(["pwsh", "-NoProfile", "-NonInteractive"])
    if shutil.which("powershell"):
        found.append(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"])
    return found


@unittest.skipUnless(shells(), "no PowerShell on this host")
class DailyRefreshConsensusStepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.driver = Path(cls._tmp.name) / "driver.ps1"
        cls.driver.write_text(DRIVER, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_daily(self, shell: list[str], *flags: str, fail: str = "") -> dict:
        command = [*shell, "-File", str(self.driver), "-Repo", str(ROOT), *flags, *(["-FailStep", fail] if fail else [])]
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT, timeout=240)
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        self.assertTrue(lines, done.stdout[-600:] + done.stderr[-600:])
        self.assertEqual(done.returncode, 0, done.stdout[-600:] + done.stderr[-600:])
        return json.loads(lines[-1])

    def test_the_ordinary_daily_refresh_runs_consensus_once_in_the_current_step_plan(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell)
                self.assertEqual(result["steps"], DEFAULT_STEPS)
                self.assertEqual(result["steps"].count(STEP), 1)
                self.assertEqual((result["exit"], result["failed"], result["disposition"]), (0, [], "DISABLED"))


    def test_the_collector_needs_no_sec_contact(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell, "-NoContact")
                self.assertEqual(result["steps"], NO_CONTACT_STEPS)
                self.assertEqual((result["exit"], result["failed"]), (1, ["sec_contact_missing"]))
                self.assertEqual(result["steps"].count(STEP), 1)

    def test_a_failed_collector_fails_the_run_but_never_stops_the_other_steps(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell, fail="revenue_consensus")
                self.assertEqual((result["exit"], result["failed"]), (1, ["revenue_consensus"]))
                self.assertEqual(result["steps"], DEFAULT_STEPS)

    def test_automatic_mode_keeps_all_ten_independent_steps_without_legacy_fallback(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell, "-Auto")
                self.assertEqual(result["steps"], AUTO_STEPS)
                self.assertEqual(len(result["steps"]), 10)
                self.assertEqual(result["steps"].count(STEP), 1)
                self.assertEqual((result["exit"], result["failed"]), (1, []))
                self.assertEqual(result["disposition"], "BLOCKED_PREREQUISITE_UNAVAILABLE")
                self.assertEqual(result["reason"], "GUIDANCE_PROVIDER_UNAVAILABLE")

    def test_normal_entry_budget_adapter_allocates_for_all_ten_independent_steps(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell, "-BudgetPlan")
                self.assertEqual(result["steps"], AUTO_STEPS)
                # Fixed clock/budget: count=10 leaves two shares for guidance.
                # The first two slices expose a missing/extra ordinary step;
                # later slices reach the adapter's 60-second observation cap.
                self.assertEqual(result["slices"], [50000, 54545, *([60000] * 8)])
                self.assertEqual((result["exit"], result["failed"]), (1, []))
                self.assertEqual(result["reason"], "GUIDANCE_PROVIDER_UNAVAILABLE")

    def test_omitted_and_explicitly_disabled_options_have_the_same_plan(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                omitted = self.run_daily(shell)
                explicit = self.run_daily(shell, "-ExplicitDisabled")
                self.assertEqual(explicit, omitted)
                self.assertEqual(explicit["steps"], DEFAULT_STEPS)

    def test_force_zeroes_only_the_release_check_because_ranking_is_already_hourly(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                default = self.run_daily(shell)
                forced = self.run_daily(shell, "-Force")
                self.assertEqual(forced["steps"], FORCED_STEPS)
                self.assertEqual((forced["exit"], forced["failed"]), (0, []))
                changed = [i for i, (a, b) in enumerate(zip(default["steps"], forced["steps"])) if a != b]
                self.assertEqual(changed, [8])
                self.assertEqual(len(forced["steps"]), len(default["steps"]))

    def test_force_does_not_change_the_plan_when_the_disabled_pair_cannot_run(self):
        for shell in shells():
            for flags in (("-Auto",), ("-NoContact",), ("-Auto", "-NoContact")):
                with self.subTest(shell=shell[0], flags=flags):
                    self.assertEqual(self.run_daily(shell, *flags, "-Force"), self.run_daily(shell, *flags))

    def test_custom_report_cadence_does_not_throttle_hourly_or_consensus_steps(self):
        expected = list(DEFAULT_STEPS)
        for index in (1, 4, 5):
            expected[index] = expected[index].replace("--if-older-than-hours 20", "--if-older-than-hours 12")
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell, "-Hours", "12")
                self.assertEqual(result["steps"], expected)
                self.assertEqual((result["exit"], result["failed"]), (0, []))

    def test_forced_pair_failures_are_aggregated_without_skipping_trailing_steps(self):
        for shell in shells():
            for name in ("guidance_release_check", "bottleneck_v3"):
                with self.subTest(shell=shell[0], step=name):
                    result = self.run_daily(shell, "-Force", fail=name)
                    self.assertEqual(result["steps"], FORCED_STEPS)
                    self.assertEqual((result["exit"], result["failed"]), (1, [name]))

    def test_normal_entry_parameter_binding_dispatches_the_same_default_and_forced_plans(self):
        for shell in shells():
            for flags, expected in (((), DEFAULT_STEPS), (("-Force",), FORCED_STEPS), (("-Auto",), AUTO_STEPS)):
                with self.subTest(shell=shell[0], flags=flags):
                    result = self.run_daily(shell, "-NormalEntryPlan", *flags)
                    self.assertEqual(result["steps"], expected)
                    self.assertEqual(result, self.run_daily(shell, *flags))

if __name__ == "__main__":
    unittest.main()
