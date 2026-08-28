[CmdletBinding()]
param(
    [string]$BaseInstallRoot = '',
    [switch]$NonInteractive,
    [switch]$OpenReports
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Version = '2.0.0'
if ([string]::IsNullOrWhiteSpace($BaseInstallRoot)) {
    $BaseInstallRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
}
$BaseInstallRoot = [System.IO.Path]::GetFullPath($BaseInstallRoot)
$StatePath = Join-Path $BaseInstallRoot 'install-state.json'
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "Investor Intelligence is not installed at $BaseInstallRoot. Run install-final.ps1 or install.ps1 first."
}
$state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
$ApplicationRoot = [string]$state.application_root
$PythonExe = [string]$state.python_executable
$UserConfigRoot = [string]$state.user_config_root
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw 'The verified portable Python runtime is missing. Re-run install.ps1 -Force.'
}
if (-not (Test-Path -LiteralPath $ApplicationRoot -PathType Container)) {
    throw 'The installed application directory is missing. Re-run install.ps1 -Force.'
}

$UniversePath = Join-Path $UserConfigRoot 'research-universe.local.json'
$PreferencesPath = Join-Path $UserConfigRoot 'user-preferences.local.json'
if (-not (Test-Path -LiteralPath $UniversePath -PathType Leaf)) {
    New-Item -ItemType Directory -Force -Path $UserConfigRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $ApplicationRoot 'config\research-universe.example.json') -Destination $UniversePath
}
if (-not (Test-Path -LiteralPath $PreferencesPath -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path $ApplicationRoot 'config\user-preferences.example.json') -Destination $PreferencesPath
}

$universeText = Get-Content -LiteralPath $UniversePath -Raw -Encoding utf8
if ($universeText -match '"ticker"\s*:\s*"EXAMPLE"') {
    if ($NonInteractive) {
        throw "Local research universe is not configured: $UniversePath"
    }
    Write-Host 'First-run setup: replace EXAMPLE with one or more public ticker symbols, save, then run again.' -ForegroundColor Yellow
    Start-Process notepad.exe -ArgumentList @($UniversePath)
    exit 3
}

$env:LOCAL_RESEARCH_UNIVERSE_PATH = $UniversePath
$env:LOCAL_USER_PREFERENCES_PATH = $PreferencesPath
$env:FREE_ONLY_MODE = 'true'
$env:PAID_FALLBACK_ENABLED = 'false'
$env:DELIVERY_ENABLED = 'false'
$env:LINE_ENABLED = 'false'
$env:LINE_PUSH_ENABLED = 'false'
$env:LINE_ACCESS_MODE = 'disabled'
$env:PUBLIC_KV_SYNC_ENABLED = 'false'
$env:CURRENT_PUBLIC_DATA_ENABLED = 'false'
$env:CLOUD_INFERENCE_ENABLED = 'false'
$env:MEMORY_FEATURE_AVAILABLE = 'false'
$env:IBKR_READONLY_ENABLED = 'false'
$env:PYTHONUTF8 = '1'

Push-Location $ApplicationRoot
try {
    & $PythonExe scripts\daily_briefing.py
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
if ($exitCode -ne 0) {
    throw "Local briefing failed with exit code $exitCode. Review $(Join-Path $ApplicationRoot 'daily_briefing.log')."
}

Write-Host 'Local briefing completed. No LINE, public KV, broker write or paid fallback was used.' -ForegroundColor Green
if ($OpenReports -and (Test-Path -LiteralPath (Join-Path $ApplicationRoot 'reports') -PathType Container)) {
    Start-Process explorer.exe -ArgumentList @((Join-Path $ApplicationRoot 'reports'))
}
exit 0
