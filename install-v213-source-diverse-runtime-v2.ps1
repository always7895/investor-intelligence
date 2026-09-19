[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$RuntimeRoot = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$baseRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) { $RuntimeRoot = Join-Path $baseRoot 'V213Runtime' }
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$coordinator = Join-Path $ProjectRoot 'scripts\v213_runtime_install_coordinator.ps1'
if (-not (Test-Path -LiteralPath $coordinator -PathType Leaf)) { throw 'RUNTIME_INSTALL_COORDINATOR_MISSING' }
& $coordinator -ProjectRoot $ProjectRoot -RuntimeRoot $RuntimeRoot -Profile SOURCE_DIVERSE_V2
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
