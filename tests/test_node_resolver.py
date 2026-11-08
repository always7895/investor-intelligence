from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from tests.test_ci_python_bootstrap import native_shells

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows Node resolver")
class NodeResolverTests(unittest.TestCase):
    def test_current_process_overrides_stale_exports_for_local_callers(self):
        for executable in native_shells(self):
            shell = executable
            with self.subTest(shell=shell), tempfile.TemporaryDirectory(prefix="ii-node-resolver-") as temporary:
                script = Path(temporary) / "check.ps1"
                script.write_text(r'''
param([string]$Resolver)
$ErrorActionPreference='Stop'
$env:PROJECT_NODE='Z:\stale-node.exe'
$env:PROJECT_NPM='Z:\stale-npm.cmd'
Remove-Item Env:GITHUB_ENV -ErrorAction SilentlyContinue
& $Resolver
# deploy_production_gate selects PROJECT_NODE before NODE_FOR_RUNNER/PATH.
# Exercise that selection and the npm choice made by local CI callers, without deployment.
$selected=@($env:PROJECT_NODE,$env:NODE_FOR_RUNNER) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1
if (-not (Test-Path -LiteralPath $selected -PathType Leaf)) { throw 'STALE_NODE_SELECTED' }
if (-not (Test-Path -LiteralPath $env:PROJECT_NPM -PathType Leaf)) { throw 'STALE_NPM_SELECTED' }
& $selected --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'NODE_CALLER_FAILED' }
& $env:PROJECT_NPM --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'NPM_CALLER_FAILED' }
Write-Output 'CURRENT_PROCESS_EXPORTS_PASS'
''', encoding="utf-8")
                result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File", str(script),
                                         str(ROOT / "scripts/resolve_node.ps1")], capture_output=True, text=True, errors="backslashreplace", timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("CURRENT_PROCESS_EXPORTS_PASS", result.stdout)

    def test_resolution_and_ci_export_failures_clear_ambient_exports(self):
        for executable in native_shells(self):
            with self.subTest(shell=executable), tempfile.TemporaryDirectory(prefix="ii-node-failure-") as temporary:
                script = Path(temporary) / "failure.ps1"
                script.write_text(r'''
param([string]$Resolver,[string]$Root)
$ErrorActionPreference='Stop'
foreach($mode in @('resolution','ci-validation','ci-write')) {
    $env:PROJECT_NODE='Z:\stale-node.exe'; $env:PROJECT_NPM='Z:\stale-npm.cmd'
    Remove-Item Env:GITHUB_ENV -ErrorAction SilentlyContinue
    $minimum='999.0.0'
    if($mode -ne 'resolution') {
        $minimum='20.0.0'; $env:GITHUB_ENV=$Root
        $env:RUNNER_TEMP=if($mode -eq 'ci-validation'){''}else{$Root}
    }
    try { & $Resolver -MinimumVersion $minimum; throw 'UNEXPECTED_SUCCESS' }
    catch { if($_.Exception.Message -eq 'UNEXPECTED_SUCCESS'){throw} }
    if($env:PROJECT_NODE -or $env:PROJECT_NPM){throw 'STALE_EXPORT_RETAINED'}
}
Write-Output 'FAILURE_EXPORTS_CLEARED'
''', encoding="utf-8")
                result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File", str(script), str(ROOT / "scripts/resolve_node.ps1"), temporary], capture_output=True, text=True, errors="backslashreplace", timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("FAILURE_EXPORTS_CLEARED", result.stdout)
