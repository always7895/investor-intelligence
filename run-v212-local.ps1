[CmdletBinding()]
param(
    [string]$BaseInstallRoot = '',
    [ValidateSet('manual', 'morning', 'evening')][string]$ScheduledSlot = 'manual',
    [switch]$NonInteractive,
    [switch]$OpenReports,
    [switch]$NoSync,
    [switch]$Synthetic
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($BaseInstallRoot)) {
    $BaseInstallRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
}
$BaseInstallRoot = [IO.Path]::GetFullPath($BaseInstallRoot)
$StatePath = Join-Path $BaseInstallRoot 'install-state.json'
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "Investor Intelligence is not installed at $BaseInstallRoot."
}
$state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
$ApplicationRoot = [string]$state.application_root
$PythonExe = [string]$state.python_executable
$UserConfigRoot = [string]$state.user_config_root

foreach ($relative in @(
    'run-v211-evidence-gated.ps1',
    'scripts\build_v212_top20_report.py',
    'scripts\historical_return_evidence.py',
    'sync-v21-public-snapshot.ps1',
    'sync-v212-top20-report.ps1'
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $ApplicationRoot $relative) -PathType Leaf)) {
        throw "The v2.1.2 patch is incomplete: $relative"
    }
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw 'The verified portable Python runtime is missing.'
}

$contactPointer = [IntPtr]::Zero
$contactText = $null
try {
    $v211Args = @(
        '-NoProfile','-ExecutionPolicy','Bypass',
        '-File',(Join-Path $ApplicationRoot 'run-v211-evidence-gated.ps1'),
        '-BaseInstallRoot',$BaseInstallRoot,
        '-ScheduledSlot',$ScheduledSlot,
        '-NoSync'
    )
    if ($NonInteractive) { $v211Args += '-NonInteractive' }
    if ($Synthetic) { $v211Args += '-Synthetic' }
    & powershell.exe @v211Args
    if ($LASTEXITCODE -ne 0) {
        throw "v2.1.1 base research refresh failed with exit code $LASTEXITCODE."
    }

    if ($Synthetic) {
        Push-Location $ApplicationRoot
        try {
            & $PythonExe 'scripts\build_v212_top20_report.py' '--self-test'
            if ($LASTEXITCODE -ne 0) { throw 'v2.1.2 Top 20 report self-test failed.' }
        }
        finally { Pop-Location }
        Write-Host 'Investor Intelligence v2.1.2 synthetic refresh = PASS' -ForegroundColor Green
        exit 0
    }

    $contactPath = Join-Path $UserConfigRoot 'sec-contact.local.txt'
    if (-not (Test-Path -LiteralPath $contactPath -PathType Leaf)) {
        throw 'SEC Fair Access contact is not configured.'
    }
    $protected = ConvertTo-SecureString -String (
        Get-Content -LiteralPath $contactPath -Raw -Encoding utf8
    ).Trim()
    $contactPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($protected)
    $contactText = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($contactPointer)
    if ($contactText -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
        throw 'The protected SEC Fair Access contact configuration is invalid.'
    }
    $env:SEC_CONTACT_EMAIL = $contactText
    $env:PYTHONUTF8 = '1'

    Push-Location $ApplicationRoot
    try {
        & $PythonExe 'scripts\build_v212_top20_report.py'
        if ($LASTEXITCODE -ne 0) {
            throw "v2.1.2 five-field Top 20 report build failed with exit code $LASTEXITCODE."
        }
    }
    finally { Pop-Location }

    $reportPath = Join-Path $ApplicationRoot 'data\cache\v212_top20_report_public_latest.json'
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        throw 'v2.1.2 five-field Top 20 report output is missing.'
    }
    $report = Get-Content -LiteralPath $reportPath -Raw -Encoding utf8 | ConvertFrom-Json
    if (
        [string]$report.product_version -ne '2.1.2' -or
        @($report.records).Count -ne 20 -or
        (@($report.display_columns) -join '/') -ne '股票/長期投資報酬率（近2年年化）/短期投資報酬率（近6個月）/行業別/獲利簡述'
    ) {
        throw 'v2.1.2 Top 20 closed presentation contract failed.'
    }
    foreach ($row in @($report.records)) {
        if ([string]::IsNullOrWhiteSpace([string]$row.industry) -or [string]$row.industry -notmatch '[\u3400-\u9fff]') {
            throw "v2.1.2 Top 20 industry is not Traditional-Chinese localized: $($row.ticker)"
        }
    }

    if (-not $NoSync) {
        $syncConfig = Join-Path $UserConfigRoot 'v21-owner-line.local.json'
        if (-not (Test-Path -LiteralPath $syncConfig -PathType Leaf)) {
            throw 'Owner LINE signed-sync configuration is missing.'
        }
        $snapshotPath = Join-Path $ApplicationRoot 'data\cache\v211_public_snapshot_upload.json'
        & (Join-Path $ApplicationRoot 'sync-v21-public-snapshot.ps1') `
            -ProjectRoot $ApplicationRoot -SnapshotPath $snapshotPath -LocalConfigPath $syncConfig
        if ($LASTEXITCODE -ne 0) { throw 'v2.1.1 signed public snapshot sync failed.' }
        & (Join-Path $ApplicationRoot 'sync-v212-top20-report.ps1') `
            -ProjectRoot $ApplicationRoot -ReportPath $reportPath -LocalConfigPath $syncConfig
        if ($LASTEXITCODE -ne 0) { throw 'v2.1.2 five-field Top 20 report sync failed.' }
    }

    Write-Host "Investor Intelligence v2.1.2 refresh completed ($ScheduledSlot)." -ForegroundColor Green
    Write-Host 'TOP20_DISPLAY_COLUMNS = 股票 / 長期投資報酬率（近2年年化） / 短期投資報酬率（近6個月） / 行業別 / 獲利簡述' -ForegroundColor Green
    Write-Host 'Long term = trailing ~2-year adjusted-close CAGR; short term = trailing ~6-month adjusted-close return.' -ForegroundColor Green
    Write-Host 'Industry = Traditional-Chinese localized public market taxonomy.' -ForegroundColor Green
    Write-Host 'Profit summary is deterministic SEC EDGAR public evidence; no owner portfolio/brokerage data was used.' -ForegroundColor Green
    if ($OpenReports -and (Test-Path -LiteralPath (Join-Path $ApplicationRoot 'reports') -PathType Container)) {
        Start-Process explorer.exe -ArgumentList @((Join-Path $ApplicationRoot 'reports'))
    }
}
finally {
    $env:SEC_CONTACT_EMAIL = $null
    if ($contactPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($contactPointer)
    }
    $contactText = $null
}
exit 0
