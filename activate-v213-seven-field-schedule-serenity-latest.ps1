[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [ValidateSet('zh-TW','en','bilingual')][string]$FieldLocale = 'zh-TW',
    [string]$ExpectedModel = '',
    [switch]$ConfirmActivation,
    [switch]$RequireLocalModel,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)

function Test-Python([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try { & $Path -c "import requests,sys; assert sys.version_info >= (3,10)" 2>$null; return ($LASTEXITCODE -eq 0) }
    catch { return $false }
}
function Resolve-Python {
    if (Test-Python $env:PROJECT_PYTHON) { return $env:PROJECT_PYTHON }
    foreach ($name in @('python.exe','python3.exe','python','py.exe','py')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and (Test-Python $command.Source)) { return $command.Source }
    }
    & (Join-Path $ProjectRoot 'scripts\resolve_python.ps1') -VenvPath (Join-Path $ProjectRoot '.venv-v213-latest-activation')
    if (Test-Python $env:PROJECT_PYTHON) { return $env:PROJECT_PYTHON }
    throw 'Verified Python runtime is unavailable for latest-evidence activation.'
}

if ($SelfTest) {
    $python = Resolve-Python
    foreach ($command in @(
        @('scripts\v213_refresh_serenity_public_sources.py','--self-test'),
        @('scripts\v213_serenity_latest_multisource_audit.py','--self-test'),
        @('scripts\v213_tam_capture_claim_guard.py','--self-test')
    )) {
        & $python @command
        if ($LASTEXITCODE -ne 0) { throw "Activation preflight self-test failed: $($command -join ' ')" }
    }
    & (Join-Path $ProjectRoot 'activate-v213-seven-field-schedule-core.ps1') -ProjectRoot $ProjectRoot -SelfTest
    if ($LASTEXITCODE -ne 0) { throw 'Atomic activation core self-test failed.' }
    Write-Host 'V213_SERENITY_LATEST_ACTIVATION_SELF_TEST = PASS; latest_available=true; per_ticker_multisource=true; exact_rollback=true' -ForegroundColor Green
    exit 0
}

if (-not $ConfirmActivation) { throw 'Formal Serenity-latest scheduled activation requires -ConfirmActivation.' }
$python = Resolve-Python
$env:PROJECT_PYTHON = $python
& $python (Join-Path $ProjectRoot 'scripts\v213_refresh_serenity_public_sources.py') '--enforce'
if ($LASTEXITCODE -ne 0) { throw 'Latest public Serenity source verification failed before activation.' }
& $python (Join-Path $ProjectRoot 'scripts\v213_serenity_latest_multisource_audit.py')
if ($LASTEXITCODE -ne 0) { throw 'Latest per-ticker multi-source Serenity audit failed before activation.' }
Write-Host 'V213_SERENITY_LATEST_ACTIVATION_PREFLIGHT = PASS; latest_public_source=true; per_ticker_claim_sources>=2; fresh_primary=true; yahoo_truth_anchor=false' -ForegroundColor Green

& (Join-Path $ProjectRoot 'activate-v213-seven-field-schedule-core.ps1') -ProjectRoot $ProjectRoot -FieldLocale $FieldLocale -ExpectedModel $ExpectedModel -ConfirmActivation -RequireLocalModel:$RequireLocalModel
if ($LASTEXITCODE -ne 0) { throw 'Atomic exact-rollback activation core failed.' }
Write-Host 'V2.1.3 SERENITY-LATEST MULTI-SOURCE SCHEDULE ACTIVATION = PASS' -ForegroundColor Green
