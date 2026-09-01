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
if([string]::IsNullOrWhiteSpace($ProjectRoot)){ $ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$runtimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\Runtime'
$logRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\logs\v213-refresh'
New-Item -ItemType Directory -Force -Path $runtimeRoot,$logRoot | Out-Null
$logPath=Join-Path $logRoot ('refresh-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
Start-Transcript -Path $logPath -Force | Out-Null

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

try{
    $python=Resolve-ProjectPython
    $env:PROJECT_PYTHON=$python
    Load-SecContact
    Write-Host "PROJECT_PYTHON = $python" -ForegroundColor Green

    if(-not $NoModelBridge){
        try{
            & (Join-Path $ProjectRoot 'run-v213-local-llm-bridge.ps1') -ProjectRoot $ProjectRoot -Model $Model -LlamaBaseUrl $LlamaBaseUrl -NoTunnel:$NoTunnel -InstallCloudflared:$InstallCloudflared -StopExisting
        }catch{
            Write-Warning ("Local-model bridge is not ready yet; public-data refresh will continue. " + $_.Exception.Message)
        }
    }

    Push-Location $ProjectRoot
    try {
        $engine=@('scripts\v21_serenity_top20.py')
        if($Synthetic){$engine+='--synthetic'}
        & $python @engine
        if($LASTEXITCODE -ne 0){throw 'Top20 engine failed.'}
        & $python 'scripts\build_v21_public_snapshot.py'
        if($LASTEXITCODE -ne 0){throw 'v2.1 snapshot build failed.'}
        if(-not $Synthetic){
            & $python 'scripts\build_v212_top20_report.py'
            if($LASTEXITCODE -ne 0){throw 'v2.1.2 five-field refresh failed.'}
            & $python 'scripts\build_v213_scheduled_top20_report.py'
            if($LASTEXITCODE -ne 0){throw 'v2.1.3 seven-field build failed.'}
            if(-not $NoSync){
                $syncConfig=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v21-owner-line.local.json'
                if(Test-Path $syncConfig -PathType Leaf){
                    & .\sync-v21-public-snapshot.ps1 -ProjectRoot $ProjectRoot -LocalConfigPath $syncConfig
                    & .\sync-v212-top20-report.ps1 -ProjectRoot $ProjectRoot -LocalConfigPath $syncConfig
                }else{
                    Write-Warning 'LINE signed-sync configuration is not installed; local reports were refreshed but not uploaded.'
                }
                $v213Config=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\wrangler.v213.production.local.toml'
                if((Test-Path $v213Config -PathType Leaf) -and -not $NoAutoActivation){
                    & .\activate-v213-seven-field-schedule.ps1 -ProjectRoot $ProjectRoot -ConfirmActivation
                    Write-Host 'V213_SCHEDULE_AND_MODEL_ROUTE_REFRESH = PASS' -ForegroundColor Green
                }elseif(Test-Path $v213Config -PathType Leaf){
                    Write-Host 'V213_REPORT_READY = PASS; auto-activation intentionally skipped for explicit activation preflight.' -ForegroundColor Green
                }else{
                    Write-Host 'V213_REPORT_READY = PASS; formal v2.1.3 schedule activation has not been performed yet.' -ForegroundColor Green
                }
            }
        }
        Write-Host 'INVESTOR_INTELLIGENCE_V213_LOCAL = PASS' -ForegroundColor Green
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
    try{Stop-Transcript|Out-Null}catch{}
}
exit 0
