"""FREE_RELAY watchdog (operator 2026-09-26: LINE Q&A reconnects after a local model or port change). The decision
function is executed from the real script under Windows PowerShell 5.1 and PowerShell 7; no process, network or task
is touched."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "v213_free_relay_watchdog.ps1"
REGISTER = ROOT / "register-v213-free-relay-task.ps1"

CHECK = r'''
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('SCRIPT_PATH',[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'PARSE_FAILED'}
foreach($f in $ast.FindAll({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([scriptblock]::Create($f.Extent.Text))}
$found=[pscustomobject]@{model='Qwen3.8-27B';base_url='http://127.0.0.1:8080';match='family'}
$state=[pscustomobject]@{model='Qwen3.8-27B';llama_base_url='http://127.0.0.1:8080';gateway_port=8814}
$cases=@(
 @((Get-WatchdogDecision $null $state $true $true),'IDLE_NO_LOCAL_MODEL'),
 @((Get-WatchdogDecision ([pscustomobject]@{error='LOCAL_MODEL_NOT_FOUND'}) $state $true $true),'IDLE_NO_LOCAL_MODEL'),
 @((Get-WatchdogDecision $found $null $false $false),'CONNECT'),
 @((Get-WatchdogDecision ([pscustomobject]@{model='Other-8B';base_url='http://127.0.0.1:8080'}) $state $true $true),'RECONNECT_MODEL_CHANGED'),
 @((Get-WatchdogDecision ([pscustomobject]@{model='Qwen3.8-27B';base_url='http://127.0.0.1:9000'}) $state $true $true),'RECONNECT_MODEL_CHANGED'),
 @((Get-WatchdogDecision $found $state $false $true),'RECONNECT_PROCESS_UNAVAILABLE'),
 @((Get-WatchdogDecision $found $state $true $false),'RECONNECT_GATEWAY_UNHEALTHY'),
 @((Get-WatchdogDecision $found $state $true $true),'HEALTHY'))
foreach($c in $cases){ if($c[0] -cne $c[1]){ throw ('DECISION ' + $c[0] + ' expected ' + $c[1]) } }
Write-Output 'WATCHDOG_DECISIONS=PASS'
'''


class FreeRelayWatchdogTests(unittest.TestCase):
    def test_decisions_under_both_shells(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "check.ps1"
            path.write_text(CHECK.replace("SCRIPT_PATH", str(SCRIPT).replace("'", "''")), encoding="utf-8-sig")
            for shell in ("powershell.exe", "pwsh"):
                if not shutil.which(shell):
                    continue
                result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(path)], capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=60)
                with self.subTest(shell=shell):
                    self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-1500:])
                    self.assertIn("WATCHDOG_DECISIONS=PASS", result.stdout)

    def test_task_runs_the_watchdog_every_five_minutes_and_validates_without_registering(self):
        text = REGISTER.read_text(encoding="utf-8")
        self.assertIn("v213_free_relay_watchdog.ps1", text)
        self.assertIn("-RepetitionInterval (New-TimeSpan -Minutes 5)", text)
        self.assertIn("-MultipleInstances IgnoreNew", text)
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(REGISTER),
                                 "-ProjectRoot", str(ROOT), "-ValidateOnly"], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("every_minutes=5", result.stdout)
        self.assertIn("registration_performed=false", result.stdout)
        watchdog = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("-StopExisting -TunnelMode FreeRelay", watchdog)  # restarts through the verified bridge only


if __name__ == "__main__":
    unittest.main()
