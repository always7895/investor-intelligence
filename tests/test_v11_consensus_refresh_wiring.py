"""Operator 2026-10-13 (A1): the analyst-consensus revenue route needs its quarterly consensus capture refreshed. The installed
daily refresh (scripts/run_daily_data_refresh.ps1) owns that: this test dot-sources the REAL script (definition-only path: no
contact lookup, environment change, native launch or exit) and runs the REAL Invoke-DailyDataRefresh with a fake step runner,
so the step list, arguments, order and failure handling are the script's own. No Python step runs, no network, no credentials.

The collector itself (the step's own gate on the registry's consensus_enabled flag, its cadence, exit codes and cache) is
tests/test_v11_consensus_collector.py; the producer chain behind it is tests/test_v11_consensus_producer.py."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_daily_data_refresh.ps1"
DRIVER = r"""param([string]$Repo, [string]$FailStep = '', [switch]$Auto, [switch]$NoContact)
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
$result = Invoke-DailyDataRefresh -RunStep $runStep -WithSecContact $withContact -GuidanceAutoUpdateEnabled ([bool]$Auto)
[pscustomobject]@{ steps = @($script:Rec); exit = $result.ExitCode; failed = @($result.FailedSteps) } | ConvertTo-Json -Compress
"""
STEP = "revenue_consensus|scripts\\revenue_consensus_quarterly.py --if-older-than-hours 6"


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
        return json.loads(lines[-1])

    def test_the_ordinary_daily_refresh_runs_the_consensus_collector_once_in_its_place(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell)
                steps = result["steps"]
                self.assertEqual(steps.count(STEP), 1)
                self.assertEqual(result["exit"], 0)
                # after the Serenity signals, before the SEC steps; the guidance pair and the quote steps keep their order
                names = [step.split("|")[0] for step in steps]
                self.assertEqual(names, ["zh_names", "identity_shards", "serenity_signals", "revenue_consensus", "industry_rotation",
                                         "company_reports", "leopold_13f", "guidance_release_check", "bottleneck_v3", "price_shards",
                                         "market_observations"])

    def test_the_collector_needs_no_sec_contact(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell, "-NoContact")
                self.assertIn(STEP, result["steps"])
                self.assertNotIn("industry_rotation", [step.split("|")[0] for step in result["steps"]])  # the SEC steps are skipped
                self.assertEqual(result["exit"], 1)  # the missing contact fails the run, not the consensus step
                self.assertNotIn("revenue_consensus", result["failed"])

    def test_a_failed_collector_fails_the_run_but_never_stops_the_other_steps(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell, fail="revenue_consensus")
                self.assertEqual((result["exit"], result["failed"]), (1, ["revenue_consensus"]))
                names = [step.split("|")[0] for step in result["steps"]]
                for later in ("industry_rotation", "bottleneck_v3", "price_shards", "market_observations"):
                    self.assertIn(later, names)

    def test_the_requested_automatic_mode_still_runs_the_collector_as_an_independent_step(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell, "-Auto")  # no provider: the guidance pair is blocked, not the independent steps
                names = [step.split("|")[0] for step in result["steps"]]
                self.assertEqual(result["steps"].count(STEP), 1)
                self.assertNotIn("bottleneck_v3", names)  # no duplicate legacy pair in the automatic mode
                self.assertEqual(len(names), 9)

    def test_the_step_budget_counts_every_ordinary_step(self):
        """The automatic mode slices its time budget by the number of independent steps still to run (Count=N in the normal
        entry): it must equal the steps the function runs in that mode, including the consensus collector."""
        source = SCRIPT.read_text(encoding="utf-8")
        counted = int(re.search(r"\$ordinaryStepsLeft=\[pscustomobject\]@\{Count=(\d+)\}", source).group(1))
        for shell in shells():
            with self.subTest(shell=shell[0]):
                self.assertEqual(counted, len(self.run_daily(shell, "-Auto")["steps"]))


if __name__ == "__main__":
    unittest.main()
