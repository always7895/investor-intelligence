from __future__ import annotations

import re
import unittest
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts" / "resolve_python.ps1"
BOOTSTRAP = ROOT / "scripts" / "bootstrap_portable_python.ps1"


def native_shells(case):
    shells = [shutil.which(name) for name in ("powershell.exe", "pwsh.exe")]
    if not all(shells):
        reason = "Native PS5.1+7 behavioral acceptance requires both shells on PATH; run II_REQUIRE_NATIVE_SHELLS=1 outside H5"
        if os.environ.get("II_REQUIRE_NATIVE_SHELLS") == "1":
            case.fail(reason)
        case.skipTest(reason)
    return shells


class CiPythonBootstrapPolicyTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows PowerShell runtime contract")
    def test_destinations_fail_closed_before_download_and_preserve_foreign_files(self):
        for executable in native_shells(self):
            shell = executable
            with self.subTest(shell=shell), tempfile.TemporaryDirectory(prefix="ii-bootstrap-safety-") as temporary:
                root = Path(temporary)
                foreign = root / "foreign"
                foreign.mkdir()
                (foreign / "sentinel").write_text("keep", encoding="utf-8")
                shared = root / ".portable-python-downloads"
                shared.mkdir()
                (shared / "sentinel").write_text("shared", encoding="utf-8")
                script = root / "check.ps1"
                script.write_text(r'''
param([string]$Bootstrap, [string]$Root, [string]$Checkout)
$ErrorActionPreference='Stop'
$global:downloads=0
function Invoke-WebRequest { $global:downloads++; throw 'OFFLINE_TEST' }
function Expect-Refusal([string]$Path) {
    $before=$global:downloads
    try { & $Bootstrap -DestinationPath $Path; throw 'UNEXPECTED_SUCCESS' }
    catch { if ($_.Exception.Message -eq 'UNEXPECTED_SUCCESS') { throw } }
    if ($global:downloads -ne $before) { throw 'NETWORK_BEFORE_PREFLIGHT' }
}
Expect-Refusal (Join-Path $Root 'foreign')
Expect-Refusal $Checkout
Expect-Refusal (Split-Path -Parent $Checkout)
Expect-Refusal $env:USERPROFILE
Expect-Refusal $env:SystemRoot
Expect-Refusal ([IO.Path]::GetPathRoot($Root))
$env:GITHUB_ENV=$Root
try { & $Bootstrap -DestinationPath (Join-Path $Root 'bad-export') -ExportGitHubEnvironment; throw 'UNEXPECTED_SUCCESS' }
catch { if($_.Exception.Message -ne 'PORTABLE_ENV_EXPORT_TARGET_INVALID'){throw} }
if($global:downloads -ne 0 -or (Test-Path (Join-Path $Root 'bad-export'))){throw 'BAD_EXPORT_MUTATED_RUNTIME'}
Remove-Item Env:GITHUB_ENV
$target=Join-Path $Root 'new-runtime'
try { & $Bootstrap -DestinationPath $target; throw 'UNEXPECTED_SUCCESS' }
catch { if ($_.Exception.Message -ne 'OFFLINE_TEST') { throw } }
if ($global:downloads -ne 1 -or (Test-Path $target)) { throw 'FAILED_DOWNLOAD_CHANGED_DESTINATION' }
if (@(Get-ChildItem $Root -Directory -Filter '.portable-python-downloads-*').Count -ne 0) { throw 'PRIVATE_DOWNLOAD_LEAK' }
$link=Join-Path $Root 'junction'
New-Item -ItemType Junction -Path $link -Target (Join-Path $Root 'foreign') | Out-Null
try { Expect-Refusal (Join-Path $link 'runtime') }
finally { [IO.Directory]::Delete($link) }
if ((Get-Content (Join-Path $Root 'foreign/sentinel')) -ne 'keep') { throw 'FOREIGN_FILE_CHANGED' }
if ((Get-Content (Join-Path $Root '.portable-python-downloads/sentinel')) -ne 'shared') { throw 'SHARED_DOWNLOAD_CHANGED' }
Write-Output 'SAFE_DESTINATION_PASS'
''', encoding="utf-8")
                result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File", str(script),
                                         str(BOOTSTRAP), str(root), str(ROOT)], capture_output=True, text=True, errors="backslashreplace", timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("SAFE_DESTINATION_PASS", result.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell runtime contract")
    def test_unique_ci_caller_paths_allow_repeat_success_without_deleting_prior_runtime(self):
        shells = native_shells(self)
        with tempfile.TemporaryDirectory(prefix="ii-bootstrap-repeat-") as temporary:
            root = Path(temporary)
            # Offline process stub: identity and download hashes are mocked explicitly;
            # this tests publication/retry filesystem behavior, not Python qualification.
            compile_script = root / "compile.ps1"
            compile_script.write_text("param($Output)\nAdd-Type -TypeDefinition 'public class FakePython { public static int Main(string[] a) { return 0; } }' -OutputAssembly $Output -OutputType ConsoleApplication", encoding="utf-8")
            executable = root / "fake-python.exe"
            built = subprocess.run([shells[0], "-NoProfile", "-NonInteractive", "-File", str(compile_script), str(executable)], capture_output=True, text=True, errors="backslashreplace", timeout=45)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            with zipfile.ZipFile(root / "python.zip", "w") as archive:
                archive.write(executable, "python.exe")
                archive.writestr("python312._pth", ".\n#import site\n")
            with zipfile.ZipFile(root / "pip.zip", "w") as archive:
                archive.writestr("pip/__init__.py", "__version__='mock'\n")
            script = root / "repeat.ps1"
            script.write_text(r'''
param([string]$Bootstrap,[string]$Root,[string]$Checkout)
$ErrorActionPreference='Stop'
# Load utility exports before mocking Get-FileHash; later autoload must not replace the mock.
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
$env:RUNNER_TEMP=$Root
$env:GITHUB_ENV=Join-Path $Root 'exports.txt'
function Invoke-WebRequest { param($Uri,$OutFile,$MaximumRedirection,$Headers)
    Copy-Item -LiteralPath (Join-Path $Root $(if($Uri -like '*embed*'){'python.zip'}else{'pip.zip'})) -Destination $OutFile
}
function Get-FileHash { param($LiteralPath,$Algorithm)
    if ($LiteralPath -like '*embed*') { return @{Hash='4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'} }
    return @{Hash='382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab'}
}
foreach($caller in @('scripts/resolve_python.ps1','scripts/ci_v213_r75_validate.ps1')) {
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Checkout $caller),[ref]$tokens,[ref]$errors)
    $name=if($caller -like '*resolve_python*'){'destination'}else{'portableRoot'}
    $assignment=$ast.Find({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left -is [Management.Automation.Language.VariableExpressionAst] -and $n.Left.VariablePath.UserPath -eq $name},$true)
    if(-not $assignment){throw 'CALLER_DESTINATION_ASSIGNMENT_MISSING'}
    $runtimeRoot=$Root; $runtimeName='repeat'
    $prior=$null
    foreach($run in 1..2) {
        Invoke-Expression $assignment.Extent.Text
        $chosen=Get-Variable -Name $name -ValueOnly
        if ($chosen -eq $prior) { throw 'CALLER_REUSED_DESTINATION' }
        $answer=@(& $Bootstrap -DestinationPath $chosen -ExportGitHubEnvironment) | Select-Object -Last 1
        if (-not (Test-Path -LiteralPath $answer -PathType Leaf)) { throw 'RUNTIME_NOT_COMMITTED' }
        if ($prior -and -not (Test-Path -LiteralPath (Join-Path $prior 'sentinel'))) { throw 'PRIOR_RUNTIME_DELETED' }
        Set-Content -LiteralPath (Join-Path $chosen 'sentinel') -Value 'keep'
        $prior=$chosen
    }
}
function Out-File { throw 'MOCK_EXPORT_WRITE_FAILURE' }
$orphan=Join-Path $Root ('export-failure-'+[guid]::NewGuid().ToString('N'))
try { & $Bootstrap -DestinationPath $orphan -ExportGitHubEnvironment; throw 'UNEXPECTED_SUCCESS' }
catch { if($_.Exception.Message -ne 'PORTABLE_ENV_EXPORT_FAILED_RUNTIME_PRESERVED'){throw} }
if(-not (Test-Path (Join-Path $orphan 'python.exe'))){throw 'VERIFIED_RUNTIME_REMOVED_AFTER_EXPORT_FAILURE'}
Write-Output 'REPEAT_CALLER_SUCCESS_HASH_AND_IDENTITY_MOCKED'
''', encoding="utf-8")
            for shell in shells:
                result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(script), str(BOOTSTRAP), str(root), str(ROOT)], capture_output=True, text=True, errors="backslashreplace", timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("REPEAT_CALLER_SUCCESS_HASH_AND_IDENTITY_MOCKED", result.stdout)

    def test_github_actions_delegates_to_portable_bootstrap(self):
        text = RESOLVER.read_text(encoding="utf-8")
        self.assertIn('$env:GITHUB_ACTIONS -eq "true"', text)
        self.assertIn('bootstrap_portable_python.ps1', text)
        self.assertIn('-ExportGitHubEnvironment', text)
        self.assertIn('portable-python-3.12.10-', text)
        self.assertIn('PROJECT_PYTHON configured from reviewed portable CPython 3.12.10', text)

    def test_non_ci_generic_resolver_is_retained(self):
        text = RESOLVER.read_text(encoding="utf-8")
        self.assertIn('PYTHON_FOR_RUNNER', text)
        self.assertIn('C:\\Users\\*\\AppData\\Local\\Programs\\Python', text)
        self.assertIn('-m venv --copies', text)

    def test_local_branch_never_deletes_and_reuses_the_reviewed_lock_command(self):
        text = RESOLVER.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"Remove-Item[^\n]*-Recurse")
        self.assertIn('[switch]$InstallLockedDependencies', text)
        # The CI branch and the local locked mode run the same reviewed install command.
        install = re.findall(
            r"-m pip install --isolated --disable-pip-version-check `\s+"
            r"--only-binary=:all: --index-url https://pypi\.org/simple `\s+"
            r"--require-hashes -r \$requirements",
            text,
        )
        self.assertEqual(len(install), 2)

    def test_bootstrap_pins_runtime_and_verifies_every_download(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("$PythonVersion = '3.12.10'", text)
        self.assertIn("$PipVersion = '26.1.2'", text)
        self.assertRegex(text, r"\$PythonArchiveSha256 = '[0-9a-f]{64}'")
        self.assertRegex(text, r"\$PipWheelSha256 = '[0-9a-f]{64}'")
        self.assertIn('Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256', text)
        self.assertIn('SHA-256 verification failed', text)

    def test_bootstrap_uses_only_reviewed_official_download_hosts(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        urls = re.findall(r"https://[^\"']+", text)
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(
                url.startswith('https://www.python.org/')
                or url.startswith('https://files.pythonhosted.org/'),
                url,
            )


if __name__ == "__main__":
    unittest.main()
