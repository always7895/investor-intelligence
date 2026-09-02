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
    [switch]$Synthetic
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
$utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8NoBom
$OutputEncoding=$utf8NoBom
if([string]::IsNullOrWhiteSpace($ProjectRoot)){ $ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$runtimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\Runtime'
$logRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\logs\v213-refresh'
New-Item -ItemType Directory -Force -Path $runtimeRoot,$logRoot | Out-Null
$logPath=Join-Path $logRoot ('refresh-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
Start-Transcript -Path $logPath -Force | Out-Null
$oldPythonUnbuffered=$env:PYTHONUNBUFFERED
$env:PYTHONUNBUFFERED='1'

function Stage([int]$Number,[int]$Total,[string]$Name){
    Write-Host ("II_STAGE {0}/{1} | {2}" -f $Number,$Total,$Name) -ForegroundColor Cyan
}
function Test-Python([string]$Path){
    if(-not $Path -or -not(Test-Path -LiteralPath $Path -PathType Leaf)){return $false}
    try{& $Path -c "import sys; assert sys.version_info >= (3,10)" 2>$null;return $LASTEXITCODE -eq 0}catch{return $false}
}
function Resolve-ProjectPython {
    if(Test-Python $env:PROJECT_PYTHON){return $env:PROJECT_PYTHON}
    foreach($n in @('python.exe','python3.exe','python','py.exe','py')){
        $c=Get-Command $n -ErrorAction SilentlyContinue
        if($c -and (Test-Python $c.Source)){return $c.Source}
    }
    $portable=Join-Path $runtimeRoot 'python-3.12.10'
    $python=Join-Path $portable 'python.exe'
    if(-not(Test-Python $python)){
        Write-Host 'No usable Python found; installing verified portable CPython 3.12.10...' -ForegroundColor Cyan
        & (Join-Path $ProjectRoot 'scripts\bootstrap_portable_python.ps1') -DestinationPath $portable
        if(-not(Test-Python $python)){throw 'Verified portable Python bootstrap failed.'}
    }
    $marker=Join-Path $portable '.investor-intelligence-requirements-v213.ok'
    if(-not(Test-Path $marker -PathType Leaf)){
        Write-Host 'Installing hash-locked Investor Intelligence Python dependencies...' -ForegroundColor Cyan
        & $python -m pip install --isolated --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple --require-hashes -r (Join-Path $ProjectRoot 'requirements-ci.txt')
        if($LASTEXITCODE -ne 0){throw 'Hash-locked Python dependency installation failed.'}
        & $python -m pip check
        if($LASTEXITCODE -ne 0){throw 'pip check failed.'}
        Set-Content -LiteralPath $marker -Value ((Get-Date).ToUniversalTime().ToString('o')) -Encoding ascii
    }
    return $python
}
function Load-SecContact {
    if($env:SEC_CONTACT_EMAIL -match '^[^@\s]+@[^@\s]+\.[^@\s]+$'){return}
    $path=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\sec-contact.local.txt'
    if(-not(Test-Path $path -PathType Leaf)){return}
    try{
        $secure=ConvertTo-SecureString -String ((Get-Content $path -Raw -Encoding utf8).Trim())
        $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try{$plain=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}
        if($plain -match '^[^@\s]+@[^@\s]+\.[^@\s]+$'){$env:SEC_CONTACT_EMAIL=$plain}
    }catch{}
}
function Assert-Exit([string]$Label){
    if($LASTEXITCODE -ne 0){throw "$Label failed with exit code $LASTEXITCODE."}
}

try{
    Stage 1 10 'Python runtime, dependency and methodology policy preflight'
    $python=Resolve-ProjectPython
    $env:PROJECT_PYTHON=$python
    Load-SecContact
    & $python (Join-Path $ProjectRoot 'scripts\v213_methodology_and_source_audit.py')
    Assert-Exit 'v2.1.3 methodology/source audit'
    Write-Host "PROJECT_PYTHON = $python" -ForegroundColor Green

    Stage 2 10 'Exact selected llama.cpp model bridge'
    $modelBridgeReady=$false
    if(-not $NoModelBridge){
        try{
            & (Join-Path $ProjectRoot 'run-v213-local-llm-bridge.ps1') -ProjectRoot $ProjectRoot -Model $Model -LlamaBaseUrl $LlamaBaseUrl -NoTunnel:$NoTunnel -InstallCloudflared:$InstallCloudflared -StopExisting
            $modelBridgeReady=$true
            Write-Host 'II_PROGRESS exact selected-model bridge ready' -ForegroundColor Green
        }catch{
            Write-Warning ("Selected-model bridge is not ready yet; public-data refresh will continue but formal activation remains fail-closed. " + $_.Exception.Message)
        }
    }else{
        Write-Host 'II_PROGRESS local-model bridge intentionally skipped' -ForegroundColor DarkGray
    }

    Push-Location $ProjectRoot
    try {
        Stage 3 10 'Candidate discovery and SEC fact extraction; Yahoo is T3 seed only'
        $engine=@('scripts\v213_v21_progress_runner.py')
        if($Synthetic){$engine+='--synthetic'}
        & $python @engine
        Assert-Exit 'Top20 candidate engine'
        Write-Host 'II_PROGRESS candidate and SEC extraction complete' -ForegroundColor Green

        if(-not $Synthetic){
            Stage 4 10 'Build v2.1.2 market and SEC report'
            & $python 'scripts\v213_v212_progress_runner.py'
            Assert-Exit 'v2.1.2 report build'
            Write-Host 'II_PROGRESS v2.1.2 report complete' -ForegroundColor Green

            Stage 5 10 'Reconcile evidence-bound order fields to current membership'
            & $python 'scripts\reconcile_v213_order_evidence.py'
            Assert-Exit 'v2.1.3 order-evidence reconciliation'
            Write-Host 'II_PROGRESS v2.1.3 order-evidence reconciliation complete' -ForegroundColor Green

            Stage 6 10 'Build initial v2.1.3 seven-field report'
            & $python 'scripts\build_v213_scheduled_top20_report.py' '--baseline' 'data\cache\v213_order_evidence_runtime.json'
            Assert-Exit 'v2.1.3 seven-field build'
            Write-Host 'II_PROGRESS initial v2.1.3 seven-field report complete' -ForegroundColor Green

            Stage 7 10 'Build live multi-source federation: SEC, Nasdaq, World Bank, BLS, ECB, GLEIF and market observations'
            & $python 'scripts\v213_source_federation.py'
            Assert-Exit 'v2.1.3 live source federation'
            & $python 'scripts\v213_source_federation_gate.py'
            Assert-Exit 'v2.1.3 source federation truth gate'
            Write-Host 'II_PROGRESS live source federation and claim-scope gate complete' -ForegroundColor Green

            Stage 8 10 'Apply diversified evidence-bound System operationalization'
            & $python 'scripts\v213_apply_diversified_operationalization.py'
            Assert-Exit 'v2.1.3 diversified operationalization'
            Write-Host 'II_PROGRESS proxy-heavy legacy factors replaced and reports re-ordered' -ForegroundColor Green

            Stage 9 10 'Build final signed public snapshot after diversified ranking'
            & $python 'scripts\v213_build_v21_public_snapshot.py'
            Assert-Exit 'v2.1.3 diversified public snapshot'
            Write-Host 'II_PROGRESS diversified signed public snapshot complete' -ForegroundColor Green

            Stage 10 10 'Signed sync and exact selected-model route refresh'
            if(-not $NoSync){
                $syncConfig=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v21-owner-line.local.json'
                if(Test-Path $syncConfig -PathType Leaf){
                    Write-Host 'II_PROGRESS signed sync: diversified v2.1 snapshot'
                    & .\sync-v21-public-snapshot.ps1 -ProjectRoot $ProjectRoot -LocalConfigPath $syncConfig
                    Write-Host 'II_PROGRESS signed sync: re-ordered v2.1.2 report'
                    & .\sync-v212-top20-report.ps1 -ProjectRoot $ProjectRoot -LocalConfigPath $syncConfig
                }else{
                    Write-Warning 'LINE signed-sync configuration is not installed; local reports were refreshed but not uploaded.'
                }
                $v213Config=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\wrangler.v213.production.local.toml'
                if(Test-Path $v213Config -PathType Leaf){
                    if(-not $NoAutoActivation -and $modelBridgeReady){
                        Write-Host 'II_PROGRESS refreshing active v2.1.3 Worker/model route under source-federation gate'
                        & .\activate-v213-seven-field-schedule.ps1 -ProjectRoot $ProjectRoot -ConfirmActivation -RequireLocalModel -ExpectedModel $Model
                        Write-Host 'V213_SCHEDULE_AND_MODEL_ROUTE_REFRESH = PASS' -ForegroundColor Green
                    }elseif(-not $NoAutoActivation){
                        if(Test-Path $syncConfig -PathType Leaf){
                            Write-Host 'II_PROGRESS model bridge offline; syncing seven-field report without changing Worker route' -ForegroundColor Yellow
                            & .\sync-v213-top20-report.ps1 -ProjectRoot $ProjectRoot -LocalConfigPath $syncConfig
                            Write-Host 'V213_REPORT_SYNC = PASS; model route unchanged because bridge is offline.' -ForegroundColor Yellow
                        }else{
                            Write-Warning 'v2.1.3 Worker is configured but signed-sync config is missing; seven-field report could not be promoted.'
                        }
                    }else{
                        Write-Host 'V213_REPORT_READY = PASS; explicit activation preflight completed without automatic deployment.' -ForegroundColor Green
                    }
                }else{
                    Write-Host 'V213_REPORT_READY = PASS; formal v2.1.3 schedule activation has not been performed yet.' -ForegroundColor Green
                }
            }else{
                Write-Host 'II_PROGRESS signed sync intentionally skipped (-NoSync)' -ForegroundColor DarkGray
            }
        }else{
            Write-Host 'II_STAGE 4-10/10 | synthetic mode: reports, source federation and sync skipped' -ForegroundColor DarkGray
        }
        Write-Host 'INVESTOR_INTELLIGENCE_V213_LOCAL = PASS' -ForegroundColor Green
        Write-Host "LOCAL_MODEL_BRIDGE_READY = $modelBridgeReady" -ForegroundColor DarkGray
        Write-Host "SCORING_VERSION = system-operationalization-v2.1.3-diversified" -ForegroundColor DarkGray
        Write-Host "SOURCE_FEDERATION = SEC,NASDAQ,WORLD_BANK,BLS,ECB,GLEIF,YAHOO_T3,ALPHA_OPTIONAL" -ForegroundColor DarkGray
        Write-Host "LOG = $logPath" -ForegroundColor DarkGray
    }
    finally { Pop-Location }
}
catch{
    Write-Error ("V213_REFRESH_FAILED: " + $_.Exception.Message)
    Write-Host "LOG = $logPath" -ForegroundColor Yellow
    exit 1
}
finally{
    $env:PYTHONUNBUFFERED=$oldPythonUnbuffered
    try{Stop-Transcript|Out-Null}catch{}
}
exit 0
