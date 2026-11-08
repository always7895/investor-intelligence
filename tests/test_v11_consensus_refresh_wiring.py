"""Operator 2026-10-13 (A1): the analyst-consensus revenue route needs its quarterly consensus capture refreshed. The installed
daily refresh (scripts/run_daily_data_refresh.ps1) owns that: this test dot-sources the REAL script (definition-only path: no
contact lookup, environment change, native launch or exit) and runs the REAL Invoke-DailyDataRefresh with a fake step runner,
so the step list, arguments, order and failure handling are the script's own. No Python step runs, no network, no credentials.
It also covers the default-off D2 switch (script `-D2ForceGuidanceRankingPair`, function parameter `ForceGuidanceRankingPair`):
off, the recorded argument lists are the shipped ones; on, only the guidance_release_check and bottleneck_v3 cadence values change.

The collector itself (the step's own gate on the registry's consensus_enabled flag, its cadence, exit codes and cache) is
tests/test_v11_consensus_collector.py; the producer chain behind it is tests/test_v11_consensus_producer.py."""
from __future__ import annotations

import json
import os
import re
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
# The shipped step list in order (the disabled-orchestration pair sits at indexes 7 and 8) and its D2-forced variant.
DEFAULT_STEPS = [
    "zh_names|scripts\\build_zh_names.py --if-older-than-hours 168",
    "identity_shards|scripts\\build_identity_shards.py --if-older-than-hours 20",
    "serenity_signals|scripts\\serenity_signals.py --refresh --if-older-than-hours 6",
    STEP,
    "industry_rotation|scripts\\industry_rotation.py --refresh --if-older-than-hours 20",
    "company_reports|scripts\\company_deep_report.py --refresh --if-older-than-hours 20",
    "leopold_13f|scripts\\leopold_positions.py --if-older-than-hours 24",
    "guidance_release_check|scripts\\revenue_guidance_release_check.py --if-older-than-hours 0.9",
    "bottleneck_v3|scripts\\bottleneck_top20_v3.py --if-older-than-hours 3",
    "price_shards|scripts\\build_price_shards.py --if-older-than-hours 2.9",
    "market_observations|scripts\\build_market_quotes_options.py --if-older-than-hours 0.9",
]
FORCED_STEPS = list(DEFAULT_STEPS)
FORCED_STEPS[7] = "guidance_release_check|scripts\\revenue_guidance_release_check.py --if-older-than-hours 0"
FORCED_STEPS[8] = "bottleneck_v3|scripts\\bottleneck_top20_v3.py --if-older-than-hours 0"


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


STUB_PYTHON = "@echo off\n>>\"%STUB_LOG%\" echo %*\nexit /b 0\n"


@unittest.skipUnless(shells(), "no PowerShell on this host")
class DailyRefreshForcePairTests(unittest.TestCase):
    """The default-off D2 switch: the disabled-orchestration pair (guidance_release_check 0.9h, bottleneck_v3 3h) runs with
    --if-older-than-hours 0 (never skip) only when the switch is set; nothing else in the step list changes."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.driver = Path(cls._tmp.name) / "driver.ps1"
        cls.driver.write_text(DRIVER, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_daily(self, shell: list[str], *flags: str) -> dict:
        command = [*shell, "-File", str(self.driver), "-Repo", str(ROOT), *flags]
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT, timeout=240)
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        self.assertTrue(lines, done.stdout[-600:] + done.stderr[-600:])
        return json.loads(lines[-1])

    def test_the_switch_off_keeps_the_shipped_argument_lists(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                result = self.run_daily(shell)  # the parameter is not passed at all
                self.assertEqual(result["steps"], DEFAULT_STEPS)
                self.assertEqual((result["exit"], result["failed"]), (0, []))

    def test_the_switch_on_zeroes_exactly_the_release_check_and_the_ranking(self):
        for shell in shells():
            with self.subTest(shell=shell[0]):
                default = self.run_daily(shell)["steps"]
                forced = self.run_daily(shell, "-Force")
                self.assertEqual(forced["steps"], FORCED_STEPS)
                self.assertEqual((forced["exit"], forced["failed"]), (0, []))
                self.assertEqual(len(forced["steps"]), 11)
                # the same 11 steps in the same order; only those two argument lists differ, and only in the hours value
                self.assertEqual([s.split("|")[0] for s in forced["steps"]], [s.split("|")[0] for s in default])
                self.assertEqual([i for i, (a, b) in enumerate(zip(default, forced["steps"])) if a != b], [7, 8])
                self.assertEqual(forced["steps"][7].split("|")[0], "guidance_release_check")
                self.assertEqual(forced["steps"][8].split("|")[0], "bottleneck_v3")

    def test_the_switch_changes_nothing_when_the_pair_is_not_run_by_the_disabled_branch(self):
        for shell in shells():
            for flags in (("-Auto",), ("-NoContact",)):
                with self.subTest(shell=shell[0], flags=flags):
                    # automatic mode owns the pair (blocked here: no provider); without the SEC contact the pair never runs
                    self.assertEqual(self.run_daily(shell, *flags, "-Force"), self.run_daily(shell, *flags))

    def test_the_step_call_sites_stay_the_eleven_the_rollout_audit_counts(self):
        source = SCRIPT.read_text(encoding="utf-8")
        names = re.findall(r"Invoke-DailyStep '([a-z0-9_]+)' @", source)
        self.assertEqual(names, [step.split("|")[0] for step in DEFAULT_STEPS])

    def test_the_normal_entry_passes_the_switch_through_to_the_two_steps(self):
        """Runs the script's real normal entry hermetically: the python executable is a recording stub, LOCALAPPDATA points to a
        temporary install state holding a throwaway DPAPI-protected contact, so nothing real is read, launched or written."""
        if os.name != "nt":
            self.skipTest("the SEC-contact adapter is DPAPI (Windows only)")
        # a PSModulePath inherited from a PowerShell 7 parent hides the Security module from Windows PowerShell 5.1
        clean = {key: value for key, value in os.environ.items() if key.upper() not in ("PSMODULEPATH", "SEC_CONTACT_EMAIL")}
        for shell in shells():
            def entry(*flags: str) -> list[str]:
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    config = base / "config"
                    (base / "InvestorIntelligence").mkdir()
                    config.mkdir()
                    (base / "InvestorIntelligence" / "install-state.json").write_text(
                        json.dumps({"user_config_root": str(config)}), encoding="utf-8")
                    protect = subprocess.run(
                        [*shell, "-Command", "ConvertTo-SecureString 'qa@example.invalid' -AsPlainText -Force | ConvertFrom-SecureString"],
                        capture_output=True, text=True, encoding="utf-8", env=clean, timeout=120)
                    self.assertEqual(protect.returncode, 0, protect.stderr[-400:])
                    (config / "sec-contact.local.txt").write_text(protect.stdout.strip(), encoding="utf-8")
                    stub = base / "python-stub.cmd"
                    stub.write_text(STUB_PYTHON, encoding="ascii")
                    log = base / "calls.log"
                    env = {**clean, "LOCALAPPDATA": str(base), "PROJECT_PYTHON": str(stub), "STUB_LOG": str(log)}
                    done = subprocess.run([*shell, "-File", str(SCRIPT), *flags], capture_output=True, text=True,
                                          encoding="utf-8", errors="replace", cwd=base, env=env, timeout=240)
                    self.assertEqual(done.returncode, 0, done.stdout[-600:] + done.stderr[-600:])
                    self.assertIn("DATA_REFRESH OK", done.stdout)
                    return [line.strip() for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
            with self.subTest(shell=shell[0]):
                default = entry()
                forced = entry("-D2ForceGuidanceRankingPair")
                self.assertEqual(len(default), 11)
                self.assertIn("scripts\\revenue_guidance_release_check.py --if-older-than-hours 0.9", default)
                self.assertIn("scripts\\bottleneck_top20_v3.py --if-older-than-hours 3", default)
                self.assertEqual(len(forced), 11)
                self.assertEqual([i for i, (a, b) in enumerate(zip(default, forced)) if a != b], [7, 8])
                self.assertEqual(forced[7], "scripts\\revenue_guidance_release_check.py --if-older-than-hours 0")
                self.assertEqual(forced[8], "scripts\\bottleneck_top20_v3.py --if-older-than-hours 0")


if __name__ == "__main__":
    unittest.main()
