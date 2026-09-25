"""Single-writer design (T8): the hourly sealed publisher is the only Production writer.

The launcher's refresh paths are data-only (-NoSync) or preflight-only (-NoAutoActivation); a local refresh stage 8
commits or activates only with the explicit -AllowSealedActivation switch; the Morning/Evening tasks register
data-only unless sealed publication is explicitly enabled. Static checks plus a validation-only registration."""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "launcher" / "InvestorIntelligenceLauncher.cs").read_text(encoding="utf-8")
RUNNERS = ("run-v213-local.ps1", "run-v213-local-serenity-latest.ps1")


class LauncherDataOnlyTests(unittest.TestCase):
    def test_every_launcher_refresh_is_data_only_or_preflight(self):
        calls = re.findall(r'RunPowerShell(?:Cli|Async)\(\s*"run-v213-local\.ps1",(.*?)\);', LAUNCHER, re.S)
        self.assertGreaterEqual(len(calls), 4)
        for arguments in calls:
            self.assertRegex(arguments, r"-NoSync|-NoAutoActivation", arguments)
            self.assertNotIn("-AllowSealedActivation", arguments)


class StageEightFailsClosedTests(unittest.TestCase):
    def test_commit_and_activation_branches_need_the_explicit_switch(self):
        for name in RUNNERS:
            with self.subTest(runner=name):
                text = (ROOT / name).read_text(encoding="utf-8-sig")
                self.assertIn("[switch]$AllowSealedActivation", text)
                stage = text[text.index("Stage 8"):]
                guard = stage.index("elseif (-not $AllowSealedActivation)")
                self.assertLess(stage.index("elseif ($NoAutoActivation)"), guard)
                self.assertLess(guard, stage.index("elseif ($bridgeReady)"))
                self.assertLess(guard, stage.index("Invoke-CurrentWorkerBundleSync $syncConfig"))
                self.assertIn("throw 'V213_SEALED_ACTIVATION_NOT_ALLOWED", stage[guard:guard + 500])

    def test_compatibility_wrapper_forwards_the_switch(self):
        wrapper = (ROOT / "run-v213-local-source-diverse.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("[switch]$AllowSealedActivation", wrapper)
        self.assertIn("@PSBoundParameters", wrapper)


class DataOnlyRegistrationTests(unittest.TestCase):
    def test_default_registration_is_data_only(self):
        shells = [s for s in ("powershell.exe", "pwsh") if shutil.which(s)]
        if not shells:
            self.skipTest("PowerShell not available")
        for shell in shells:
            with self.subTest(shell=shell):
                result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "register-v213-refresh-tasks.ps1"),
                                         "-RuntimeRoot", str(ROOT), "-ValidateOnly"], capture_output=True, encoding="utf-8",
                                        errors="replace", timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("sealed_publication_enabled=False", result.stdout)
                self.assertIn("production_mutation=false", result.stdout)


class HourlyRegistrationTests(unittest.TestCase):
    """T10: the carry-forward switch and snapshot root reach only the hourly task; the receipt stays out of the root."""

    def validate(self, shell, *args):
        return subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "scripts/register_sealed_freshness_tasks.ps1"),
                               "-ValidateOnly", *args], capture_output=True, encoding="utf-8", errors="replace", timeout=60)

    def test_passthrough_is_hourly_only_and_off_by_default(self):
        shells = [s for s in ("powershell.exe", "pwsh") if shutil.which(s)]
        if not shells:
            self.skipTest("PowerShell not available")
        for shell in shells:
            with self.subTest(shell=shell):
                default = self.validate(shell)
                self.assertEqual(default.returncode, 0, default.stdout + default.stderr)
                self.assertNotIn("-CarryForwardTop20", default.stdout)
                carried = self.validate(shell, "-CarryForwardTop20", "-SnapshotRoot", r"data\v213-snapshots")
                self.assertEqual(carried.returncode, 0, carried.stdout + carried.stderr)
                actions = dict(line.split(": ", 1) for line in carried.stdout.splitlines() if line.startswith("TASK_ACTION "))
                self.assertIn('-CarryForwardTop20 -SnapshotRoot "data\\v213-snapshots"', actions["TASK_ACTION InvestorIntelligenceSealedFreshness"])
                self.assertNotIn("-CarryForwardTop20", actions["TASK_ACTION InvestorIntelligenceFreshnessWatchdog"])
                bad = self.validate(shell, "-SnapshotRoot", 'data" -X "')
                self.assertNotEqual(bad.returncode, 0)

    def test_receipt_is_written_outside_the_script_root(self):
        text = (ROOT / "scripts/register_sealed_freshness_tasks.ps1").read_text(encoding="utf-8")
        self.assertNotIn("state\\sealed-freshness-tasks.json", text)
        self.assertIn("InvestorIntelligence\\status", text)


if __name__ == "__main__":
    unittest.main()
