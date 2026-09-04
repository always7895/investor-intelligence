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

$Version = '2.1.0'
$PatchVersion = '2.1.1'
if ([string]::IsNullOrWhiteSpace($BaseInstallRoot)) {
    $BaseInstallRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
}
$BaseInstallRoot = [System.IO.Path]::GetFullPath($BaseInstallRoot)
$StatePath = Join-Path $BaseInstallRoot 'install-state.json'
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "Investor Intelligence v$Version is not installed at $BaseInstallRoot."
}
$state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
if ([string]$state.version -ne $Version) {
    throw "Installed base version mismatch. Expected $Version, found $($state.version)."
}

$ApplicationRoot = [string]$state.application_root
$PythonExe = [string]$state.python_executable
$UserConfigRoot = [string]$state.user_config_root
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw 'The verified portable Python runtime is missing.'
}
foreach ($relative in @(
    'scripts\v211_serenity_top20.py',
    'scripts\v211_serenity_top20_evidence_gate.py',
    'scripts\v211_serenity_top20_coverage_gate.py',
    'scripts\build_v211_public_options.py',
    'scripts\build_v211_public_snapshot.py',
    'config\v211-serenity-policy.json'
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $ApplicationRoot $relative) -PathType Leaf)) {
        throw "The v$PatchVersion production patch is incomplete: $relative"
    }
}

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
$env:II_V21_SCHEDULED_SLOT = $ScheduledSlot

$contactPointer = [IntPtr]::Zero
$contactText = $null
try {
    if (-not $Synthetic) {
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
    }

    Push-Location $ApplicationRoot
    try {
        $engineArguments = @('scripts\v211_serenity_top20_coverage_gate.py')
        if ($Synthetic) { $engineArguments += '--synthetic' }
        & $PythonExe @engineArguments
        if ($LASTEXITCODE -ne 0) {
            throw "v$PatchVersion coverage/evidence-gated Serenity research-universe pipeline failed with exit code $LASTEXITCODE."
        }

        if (-not $Synthetic) {
            & $PythonExe 'scripts\build_v211_public_options.py' '--sleep' '0.25'
            if ($LASTEXITCODE -ne 0) {
                throw "v$PatchVersion public option snapshot failed with exit code $LASTEXITCODE."
            }
            & $PythonExe 'scripts\build_v211_public_snapshot.py'
            if ($LASTEXITCODE -ne 0) {
                throw "v$PatchVersion public snapshot builder failed with exit code $LASTEXITCODE."
            }
        }
        else {
            & $PythonExe 'scripts\build_v211_public_snapshot.py' '--self-test'
            if ($LASTEXITCODE -ne 0) { throw 'v2.1.1 synthetic snapshot self-test failed.' }
            Write-Host "Investor Intelligence v$PatchVersion synthetic acceptance completed." -ForegroundColor Green
            exit 0
        }
    }
    finally {
        Pop-Location
    }

    $syncConfig = Join-Path $UserConfigRoot 'v21-owner-line.local.json'
    $snapshotPath = Join-Path $ApplicationRoot 'data\cache\v211_public_snapshot_upload.json'
    if (-not $NoSync -and (Test-Path -LiteralPath $syncConfig -PathType Leaf)) {
        & (Join-Path $ApplicationRoot 'sync-v21-public-snapshot.ps1') `
            -ProjectRoot $ApplicationRoot `
            -SnapshotPath $snapshotPath `
            -LocalConfigPath $syncConfig
        if ($LASTEXITCODE -ne 0) {
            throw "v$PatchVersion signed public snapshot sync failed with exit code $LASTEXITCODE."
        }
    }
    elseif (-not $NoSync) {
        Write-Host 'Owner LINE delivery is not configured; v2.1.1 remains local-only.' -ForegroundColor Yellow
    }

    Write-Host "Investor Intelligence v$PatchVersion research + public-options refresh completed ($ScheduledSlot)." -ForegroundColor Green
    Write-Host 'Coverage gate: SEC official-name optical/photonics lane is enabled without ticker hard-coding.' -ForegroundColor Green
    Write-Host 'Evidence gate: every scored universe record has at least one public SEC evidence item.' -ForegroundColor Green
    Write-Host 'No owner watchlist, portfolio, brokerage write, automatic trading or paid fallback was used.' -ForegroundColor Green
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
