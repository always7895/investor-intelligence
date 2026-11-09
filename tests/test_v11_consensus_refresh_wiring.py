"""Daily refresh failure propagation and contact-independent public collection.

Injected step failures exercise aggregate status without live requests or credentials.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_daily_data_refresh.ps1"
DRIVER = r"""param([string]$Repo, [string]$FailStep = '', [switch]$Auto, [switch]$NoContact, [switch]$Force)
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
$extra = @{}
if ($Force) { $extra['ForceGuidanceRankingPair'] = $true }
$result = Invoke-DailyDataRefresh -RunStep $runStep -WithSecContact $withContact -GuidanceAutoUpdateEnabled ([bool]$Auto) @extra
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





if __name__ == "__main__":
    unittest.main()
