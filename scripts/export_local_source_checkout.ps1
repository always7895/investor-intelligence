# Export one commit of the development repository as a LOCAL_SOURCE_CHECKOUT package for
# scripts/v213_runtime_install_coordinator.ps1 -PackageOrigin LOCAL_SOURCE_CHECKOUT.
#
# The package is the exact `git archive` of the commit (no working-tree bytes, core.autocrlf off), plus three
# allowed extras the installer's blob check tolerates: InvestorIntelligence.exe compiled from the exported launcher
# source (revision LocalSource-<sha12>, launcher self-test run in the package root), cloud/node_modules from
# `npm ci --ignore-scripts` of the committed lockfile, and LOCAL-SOURCE-REFS.json. The identity is honest: no CI
# workflow run, never release-qualified, no Production mutation. Tracked modifications refuse the export, so the
# exported commit is the one the gates ran on.
[CmdletBinding()]
param(
    [string]$SourceRepository = '',
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$Commit = 'HEAD',
    # Tests only: skip the launcher build and npm ci (the installer still requires wrangler.cmd).
    [switch]$SkipToolchain
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($SourceRepository)) { $SourceRepository = Split-Path -Parent $PSScriptRoot }
$SourceRepository = [IO.Path]::GetFullPath($SourceRepository)
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$git = (Get-Command git.exe -ErrorAction Stop).Source

function Invoke-Git([string[]]$Arguments) {
    # Continue: a git warning on stderr must not become a terminating error under Windows PowerShell 5.1.
    $ErrorActionPreference = 'Continue'
    $output = & $git -C $SourceRepository @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) { throw ('EXPORT_GIT_FAILED ' + ($Arguments -join ' ')) }
    return @($output | ForEach-Object { "$_" })
}

if (@(Invoke-Git @('status', '--porcelain', '--untracked-files=no')).Count -gt 0) { throw 'EXPORT_SOURCE_TREE_DIRTY' }
$sha = [string]@(Invoke-Git @('rev-parse', '--verify', ($Commit + '^{commit}')))[0]
if ($sha -notmatch '^[0-9a-f]{40}$') { throw 'EXPORT_COMMIT_INVALID' }
if (Test-Path -LiteralPath $OutputRoot) {
    if (@(Get-ChildItem -LiteralPath $OutputRoot -Force).Count -gt 0) { throw 'EXPORT_OUTPUT_NOT_EMPTY' }
}
else { New-Item -ItemType Directory -Path $OutputRoot | Out-Null }

$archive = Join-Path ([IO.Path]::GetTempPath()) ('ii-local-source-' + $sha.Substring(0, 12) + '-' + [Guid]::NewGuid().ToString('N') + '.tar')
try {
    [void](Invoke-Git @('-c', 'core.autocrlf=false', 'archive', '--format=tar', '-o', $archive, $sha))
    & (Join-Path $env:WINDIR 'System32\tar.exe') -xf $archive -C $OutputRoot
    if ($LASTEXITCODE -ne 0) { throw 'EXPORT_EXTRACT_FAILED' }
}
finally { Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue }

$revision = 'LocalSource-' + $sha.Substring(0, 12)
if (-not $SkipToolchain) {
    $csc = @(
        "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $csc) { throw 'EXPORT_CSC_UNAVAILABLE' }
    $launcherSource = [IO.File]::ReadAllText((Join-Path $OutputRoot 'launcher\InvestorIntelligenceLauncher.cs'), (New-Object Text.UTF8Encoding($false)))
    $launcherSource = [regex]::Replace($launcherSource, 'const string Revision = "[^"]+";', ('const string Revision = "' + $revision + '";'), 1)
    $temporarySource = Join-Path ([IO.Path]::GetTempPath()) ('InvestorIntelligence-' + $revision + '.cs')
    [IO.File]::WriteAllText($temporarySource, $launcherSource, (New-Object Text.UTF8Encoding($false)))
    $launcherExe = Join-Path $OutputRoot 'InvestorIntelligence.exe'
    try {
        & $csc /nologo /target:winexe /platform:anycpu /optimize+ /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "/out:$launcherExe" $temporarySource | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'EXPORT_LAUNCHER_COMPILE_FAILED' }
    }
    finally { Remove-Item -LiteralPath $temporarySource -Force -ErrorAction SilentlyContinue }
    $selfTest = Start-Process -FilePath $launcherExe -ArgumentList '--self-test' -WorkingDirectory $OutputRoot -Wait -PassThru -WindowStyle Hidden
    if ($selfTest.ExitCode -ne 0) { throw ('EXPORT_LAUNCHER_SELF_TEST_FAILED exit=' + $selfTest.ExitCode) }

    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    Push-Location (Join-Path $OutputRoot 'cloud')
    try {
        & $npm ci --ignore-scripts --no-audit --no-fund 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'EXPORT_NPM_CI_FAILED' }
    }
    finally { Pop-Location }
    if (-not (Test-Path -LiteralPath (Join-Path $OutputRoot 'cloud\node_modules\.bin\wrangler.cmd') -PathType Leaf)) { throw 'EXPORT_WRANGLER_MISSING' }
}

$identity = [ordered]@{
    schema_version = 1
    artifact_kind = 'LOCAL_SOURCE_CHECKOUT'
    package_version = '2.1.3'
    source_commit = $sha
    launcher_revision = $(if ($SkipToolchain) { $null } else { $revision })
    exported_utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    workflow_run_id = $null
    release_qualified = $false
    production_mutation_by_ci = $false
}
[IO.File]::WriteAllText((Join-Path $OutputRoot 'LOCAL-SOURCE-REFS.json'), (($identity | ConvertTo-Json -Depth 4) + "`n"), (New-Object Text.UTF8Encoding($false)))
Write-Host "V213_LOCAL_SOURCE_EXPORT = PASS; commit=$sha; root=$OutputRoot; release_qualified=false" -ForegroundColor Green
