[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$Model = '',
    [string]$LlamaBaseUrl = '',
    [switch]$NoModelBridge,
    [switch]$NoTunnel,
    [ValidateSet('None','QuickTest','Named')][string]$TunnelMode = 'QuickTest',
    [string]$NamedTunnelName = '',
    [string]$NamedTunnelHostname = '',
    [string]$NamedTunnelConfig = '',
    [switch]$InstallCloudflared,
    [switch]$NoSync,
    [switch]$NoAutoActivation,
    [switch]$Synthetic,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\Runtime'
$logRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\logs\v213-refresh'
New-Item -ItemType Directory -Force -Path $runtimeRoot, $logRoot | Out-Null
$logPath = Join-Path $logRoot ('source-diverse-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
Start-Transcript -Path $logPath -Force | Out-Null
$oldUnbuffered = $env:PYTHONUNBUFFERED
$env:PYTHONUNBUFFERED = '1'

function Stage([int]$Number, [string]$Name) {
    Write-Host ("II_STAGE {0}/8 | {1}" -f $Number, $Name) -ForegroundColor Cyan
}

function Test-Python([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    try {
        & $Path -c "import requests,sys; assert sys.version_info >= (3,10)" 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Resolve-Python {
    if (Test-Python $env:PROJECT_PYTHON) {
        return $env:PROJECT_PYTHON
    }
    foreach ($name in @('python.exe', 'python3.exe', 'python', 'py.exe', 'py')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and (Test-Python $command.Source)) {
            return $command.Source
        }
    }

    $home = Join-Path $runtimeRoot 'python-3.12.10'
    $python = Join-Path $home 'python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        & (Join-Path $ProjectRoot 'scripts\bootstrap_portable_python.ps1') -DestinationPath $home
        if ($LASTEXITCODE -ne 0) {
            throw 'Verified portable Python bootstrap failed.'
        }
    }
    if (-not (Test-Python $python)) {
        & $python -m pip install --isolated --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple --require-hashes -r (Join-Path $ProjectRoot 'requirements-ci.txt')
        if ($LASTEXITCODE -ne 0) {
            throw 'Hash-locked Python dependency installation failed.'
        }
        & $python -m pip check
        if ($LASTEXITCODE -ne 0) {
            throw 'Python dependency check failed.'
        }
    }
    if (-not (Test-Python $python)) {
        throw 'Verified Python runtime is unavailable.'
    }
    return $python
}

function Load-SecContact {
    if ($env:SEC_CONTACT_EMAIL -match '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
        return
    }
    $path = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\sec-contact.local.txt'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return
    }
    try {
        $secure = ConvertTo-SecureString -String ((Get-Content -LiteralPath $path -Raw -Encoding utf8).Trim())
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
        if ($plain -match '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
            $env:SEC_CONTACT_EMAIL = $plain
        }
    }
    catch {}
}

function Invoke-CurrentWorkerBundleSync(
    [string]$SyncConfig,
    [string]$BundlePath
) {
    $bundle = Get-Content -LiteralPath $BundlePath -Raw -Encoding utf8 | ConvertFrom-Json
    $transactionId = [string]$bundle.transaction_id
    $runId = [string]$bundle.run_id
    $resultRoot = Join-Path $env:TEMP ('ii-v213-bundle-sync-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $resultRoot | Out-Null
    $commitResult = Join-Path $resultRoot 'commit.json'
    $commitAttempted = $false
    try {
        $commitAttempted = $true
        & (Join-Path $ProjectRoot 'sync-v213-activation-bundle.ps1') -Action Commit -ProjectRoot $ProjectRoot -BundlePath $BundlePath -LocalConfigPath $SyncConfig -ResultPath $commitResult
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $commitResult -PathType Leaf)) {
            throw 'Atomic activation-bundle commit did not return a receipt.'
        }
        & (Join-Path $ProjectRoot 'sync-v213-activation-bundle.ps1') -Action Finalize -ProjectRoot $ProjectRoot -LocalConfigPath $SyncConfig -TransactionId $transactionId -RunId $runId
        if ($LASTEXITCODE -ne 0) {
            throw 'Atomic activation-bundle finalize failed.'
        }
        Write-Host "V213_ACTIVE_BUNDLE_REFRESH = PASS; run_id=$runId; transaction_id=$transactionId" -ForegroundColor Green
    }
    catch {
        $failure = $_.Exception.Message
        if ($commitAttempted) {
            try {
                & (Join-Path $ProjectRoot 'sync-v213-activation-bundle.ps1') -Action Rollback -ProjectRoot $ProjectRoot -LocalConfigPath $SyncConfig -TransactionId $transactionId -RunId $runId
                Write-Host 'V213_ACTIVE_BUNDLE_REFRESH_ROLLBACK = PASS' -ForegroundColor Green
            }
            catch {
                throw "ACTIVE BUNDLE REFRESH FAILED AND POINTER ROLLBACK WAS NOT VERIFIED. Original: $failure; rollback: $($_.Exception.Message)"
            }
        }
        throw $failure
    }
    finally {
        Remove-Item -LiteralPath $resultRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
    if ($SelfTest) {
        $selfTestPython = Resolve-Python
        if (-not (Test-Python $selfTestPython)) {
            throw 'Resolved Python failed the source-diverse refresh entrypoint self-test.'
        }
        & $selfTestPython (Join-Path $ProjectRoot 'scripts\build_v213_activation_bundle_v2.py') '--self-test'
        if ($LASTEXITCODE -ne 0) { throw 'Activation-bundle builder self-test failed.' }
        & (Join-Path $ProjectRoot 'sync-v213-activation-bundle.ps1') -SelfTest
        if ($LASTEXITCODE -ne 0) { throw 'Activation-bundle sync client self-test failed.' }
        Write-Host "V213_SOURCE_DIVERSE_REFRESH_ENTRYPOINT_SELF_TEST = PASS; python=$selfTestPython; activation_bundle=atomic; legacy_pre_activation_sync=false" -ForegroundColor Green
        return
    }

    Stage 1 'Verified Python runtime and dependencies'
    $python = Resolve-Python
    $env:PROJECT_PYTHON = $python
    Load-SecContact
    Write-Host "PROJECT_PYTHON = $python" -ForegroundColor Green

    Stage 2 'Explicit exact-model llama.cpp bridge / HealthSchema2'
    $bridgeReady = $false
    if (-not $NoModelBridge) {
        try {
            & (Join-Path $ProjectRoot 'run-v213-local-llm-bridge-source-diverse.ps1') -ProjectRoot $ProjectRoot -Model $Model -LlamaBaseUrl $LlamaBaseUrl -NoTunnel:$NoTunnel -InstallCloudflared:$InstallCloudflared -StopExisting -TunnelMode $TunnelMode -NamedTunnelName $NamedTunnelName -NamedTunnelHostname $NamedTunnelHostname -NamedTunnelConfig $NamedTunnelConfig
            if ($LASTEXITCODE -ne 0) {
                throw 'Source-diverse bridge returned nonzero.'
            }
            $bridgeReady = $true
            Write-Host 'II_PROGRESS exact selected-model bridge ready' -ForegroundColor Green
        }
        catch {
            Write-Warning ("Exact-model bridge unavailable; public-data research continues, but formal activation remains blocked. " + $_.Exception.Message)
        }
    }

    Push-Location $ProjectRoot
    try {
        Stage 3 'Provisional Top20 candidate engine and first-party evidence'
        $engineArgs = @('scripts\v213_v21_progress_runner.py')
        if ($Synthetic) {
            $engineArgs += '--synthetic'
        }
        & $python @engineArgs
        if ($LASTEXITCODE -ne 0) {
            throw 'Top20 provisional candidate engine failed.'
        }
        Write-Host 'II_PROGRESS provisional shortlist created; not eligible for public snapshot promotion' -ForegroundColor Yellow

        if ($Synthetic) {
            Stage 4 'Synthetic provisional-to-diversified boundary contract'
            & $python 'scripts\v213_pipeline_boundary_self_test.py'
            if ($LASTEXITCODE -ne 0) {
                throw 'Synthetic provisional-to-diversified boundary contract failed.'
            }
            Write-Host 'II_STAGE 5-8/8 | synthetic mode intentionally skips live market/source/sync stages' -ForegroundColor DarkGray
        }
        else {
            Stage 4 'Five-field market and SEC report for provisional membership'
            & $python 'scripts\v213_v212_progress_runner.py'
            if ($LASTEXITCODE -ne 0) {
                throw 'v2.1.2 five-field report failed.'
            }

            Stage 5 'Current-membership order evidence and seven-field draft'
            & $python 'scripts\reconcile_v213_order_evidence.py'
            if ($LASTEXITCODE -ne 0) {
                throw 'Order-evidence reconciliation failed.'
            }
            Write-Host 'II_PROGRESS order evidence reconciled before source audit' -ForegroundColor Green
            & $python 'scripts\build_v213_scheduled_top20_report.py' '--baseline' 'data\cache\v213_order_evidence_runtime.json'
            if ($LASTEXITCODE -ne 0) {
                throw 'Seven-field draft build failed.'
            }

            Stage 6 'Live source federation, diversified operationalization and claim-level independence'
            & $python 'scripts\v213_source_federation.py'
            if ($LASTEXITCODE -ne 0) {
                throw 'Live source federation failed.'
            }
            & $python 'scripts\v213_source_federation_gate.py'
            if ($LASTEXITCODE -ne 0) {
                throw 'Live source federation fail-closed gate failed.'
            }
            & $python 'scripts\v213_apply_diversified_operationalization.py'
            if ($LASTEXITCODE -ne 0) {
                throw 'Diversified System operationalization failed.'
            }
            Write-Host 'II_PROGRESS provisional shortlist replaced by final diversified Top20' -ForegroundColor Green
            & $python 'scripts\v213_source_independence_gate_v3.py' '--enforce'
            if ($LASTEXITCODE -ne 0) {
                throw 'Claim-level source-independence gate failed; report promotion stopped.'
            }
            Write-Host 'II_PROGRESS source independence PASS: company/claim diversity is blocking; unavailable free market cross-checks are disclosed and cap confidence' -ForegroundColor Green

            Stage 7 'Diversified signed snapshot and atomic activation bundle build'
            & $python 'scripts\v213_build_v21_public_snapshot.py'
            if ($LASTEXITCODE -ne 0) {
                throw 'Diversified public snapshot build failed.'
            }
            & $python 'scripts\build_v213_activation_bundle_v2.py'
            if ($LASTEXITCODE -ne 0) {
                throw 'Atomic v2.1.3 activation-bundle build failed.'
            }
            Write-Host 'II_PROGRESS atomic activation bundle ready; Top20, five-field, seven-field and source sidecars share one run' -ForegroundColor Green

            Stage 8 'Atomic remote commit or formal exact-model activation'
            if ($NoSync) {
                Write-Host 'II_PROGRESS remote sync intentionally skipped (-NoSync); local activation bundle retained' -ForegroundColor DarkGray
            }
            else {
                $configRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
                $syncConfig = Join-Path $configRoot 'v21-owner-line.local.json'
                $activeConfig = Join-Path $configRoot 'wrangler.v213.production.local.toml'
                $bundlePath = Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json'

                if (-not (Test-Path -LiteralPath $activeConfig -PathType Leaf)) {
                    Write-Host 'V213_ACTIVATION_BUNDLE_READY = PASS; legacy Worker sync intentionally skipped before formal v2.1.3 activation.' -ForegroundColor Green
                }
                elseif ($NoAutoActivation) {
                    Write-Host 'V213_ACTIVATION_BUNDLE_READY = PASS; explicit activation preflight requested; no Production mutation performed.' -ForegroundColor Green
                }
                elseif (-not (Test-Path -LiteralPath $syncConfig -PathType Leaf)) {
                    Write-Warning 'Formal v2.1.3 is installed, but signed-sync configuration is missing; local bundle retained and remote data remains fail-closed.'
                }
                elseif ($bridgeReady) {
                    & .\activate-v213-seven-field-schedule.ps1 -ProjectRoot $ProjectRoot -ConfirmActivation -RequireLocalModel -ExpectedModel $Model
                    if ($LASTEXITCODE -ne 0) {
                        throw 'Active source-diverse Worker/model route refresh failed.'
                    }
                    Write-Host 'V213_SOURCE_DIVERSE_SCHEDULE_MODEL_AND_BUNDLE_REFRESH = PASS' -ForegroundColor Green
                }
                else {
                    Invoke-CurrentWorkerBundleSync $syncConfig $bundlePath
                    Write-Host 'V213_ACTIVE_DATA_REFRESH = PASS; Worker model route unchanged because exact-model bridge is offline.' -ForegroundColor Yellow
                }
            }
        }

        Write-Host 'INVESTOR_INTELLIGENCE_V213_SOURCE_DIVERSE_LOCAL = PASS' -ForegroundColor Green
        Write-Host "LOCAL_MODEL_BRIDGE_READY = $bridgeReady" -ForegroundColor DarkGray
        Write-Host "LOG = $logPath" -ForegroundColor DarkGray
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-Error ("V213_SOURCE_DIVERSE_REFRESH_FAILED: " + $_.Exception.Message)
    Write-Host "LOG = $logPath" -ForegroundColor Yellow
    exit 1
}
finally {
    $env:PYTHONUNBUFFERED = $oldUnbuffered
    try {
        Stop-Transcript | Out-Null
    }
    catch {}
}
exit 0
