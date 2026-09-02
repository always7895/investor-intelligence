[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$Model = '',
    [string]$LlamaBaseUrl = '',
    [switch]$NoModelBridge,
    [switch]$NoTunnel,
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

try {
    if ($SelfTest) {
        $selfTestPython = Resolve-Python
        if (-not (Test-Python $selfTestPython)) {
            throw 'Resolved Python failed the source-diverse refresh entrypoint self-test.'
        }
        Write-Host "V213_SOURCE_DIVERSE_REFRESH_ENTRYPOINT_SELF_TEST = PASS; python=$selfTestPython" -ForegroundColor Green
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
            & (Join-Path $ProjectRoot 'run-v213-local-llm-bridge-source-diverse.ps1') -ProjectRoot $ProjectRoot -Model $Model -LlamaBaseUrl $LlamaBaseUrl -NoTunnel:$NoTunnel -InstallCloudflared:$InstallCloudflared -StopExisting
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
        Stage 3 'Top20 public engine and first-party evidence'
        $engineArgs = @('scripts\v213_v21_progress_runner.py')
        if ($Synthetic) {
            $engineArgs += '--synthetic'
        }
        & $python @engineArgs
        if ($LASTEXITCODE -ne 0) {
            throw 'Top20 engine failed.'
        }

        Stage 4 'Signed public snapshot build'
        & $python 'scripts\build_v21_public_snapshot.py'
        if ($LASTEXITCODE -ne 0) {
            throw 'Public snapshot build failed.'
        }

        if ($Synthetic) {
            Write-Host 'II_STAGE 5-8/8 | synthetic mode intentionally skips live report/source/sync stages' -ForegroundColor DarkGray
        }
        else {
            Stage 5 'Five-field market and SEC report'
            & $python 'scripts\v213_v212_progress_runner.py'
            if ($LASTEXITCODE -ne 0) {
                throw 'v2.1.2 five-field report failed.'
            }

            Stage 6 'Current-membership order evidence plus source-independence gate'
            & $python 'scripts\reconcile_v213_order_evidence.py'
            if ($LASTEXITCODE -ne 0) {
                throw 'Order-evidence reconciliation failed.'
            }
            Write-Host 'II_PROGRESS order evidence reconciled before source audit' -ForegroundColor Green
            & $python 'scripts\v213_source_independence_gate_v2.py' '--enforce'
            if ($LASTEXITCODE -ne 0) {
                throw 'Multi-source independence gate failed; report promotion stopped.'
            }
            Write-Host 'II_PROGRESS source independence PASS: SEC/issuer + Stooq/Nasdaq/optional Alpha Vantage + FRED' -ForegroundColor Green

            Stage 7 'Seven-field report from reconciled evidence'
            & $python 'scripts\build_v213_scheduled_top20_report.py' '--baseline' 'data\cache\v213_order_evidence_runtime.json'
            if ($LASTEXITCODE -ne 0) {
                throw 'Seven-field report build failed.'
            }

            Stage 8 'Signed sync and exact-model route refresh'
            if ($NoSync) {
                Write-Host 'II_PROGRESS signed sync intentionally skipped (-NoSync)' -ForegroundColor DarkGray
            }
            else {
                $configRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
                $syncConfig = Join-Path $configRoot 'v21-owner-line.local.json'
                if (Test-Path -LiteralPath $syncConfig -PathType Leaf) {
                    & .\sync-v21-public-snapshot.ps1 -ProjectRoot $ProjectRoot -LocalConfigPath $syncConfig
                    if ($LASTEXITCODE -ne 0) {
                        throw 'Signed public snapshot sync failed.'
                    }
                    & .\sync-v212-top20-report.ps1 -ProjectRoot $ProjectRoot -LocalConfigPath $syncConfig
                    if ($LASTEXITCODE -ne 0) {
                        throw 'Signed five-field sync failed.'
                    }
                }
                else {
                    Write-Warning 'Signed-sync configuration is not installed; local outputs were retained.'
                }

                $activeConfig = Join-Path $configRoot 'wrangler.v213.production.local.toml'
                if (Test-Path -LiteralPath $activeConfig -PathType Leaf) {
                    if (-not $NoAutoActivation -and $bridgeReady) {
                        & .\activate-v213-seven-field-schedule.ps1 -ProjectRoot $ProjectRoot -ConfirmActivation -RequireLocalModel -ExpectedModel $Model
                        if ($LASTEXITCODE -ne 0) {
                            throw 'Active source-diverse Worker/model route refresh failed.'
                        }
                        Write-Host 'V213_SOURCE_DIVERSE_SCHEDULE_AND_MODEL_ROUTE_REFRESH = PASS' -ForegroundColor Green
                    }
                    elseif (-not $NoAutoActivation -and (Test-Path -LiteralPath $syncConfig -PathType Leaf)) {
                        & .\sync-v213-top20-report.ps1 -ProjectRoot $ProjectRoot -LocalConfigPath $syncConfig
                        if ($LASTEXITCODE -ne 0) {
                            throw 'Seven-field sync failed.'
                        }
                        Write-Host 'V213_REPORT_SYNC = PASS; Worker model route unchanged because bridge is offline.' -ForegroundColor Yellow
                    }
                    else {
                        Write-Host 'V213_REPORT_READY = PASS; explicit activation preflight requested.' -ForegroundColor Green
                    }
                }
                else {
                    Write-Host 'V213_REPORT_READY = PASS; formal source-diverse schedule activation has not been performed.' -ForegroundColor Green
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
