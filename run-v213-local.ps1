[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$Model = '',
    [string]$LlamaBaseUrl = '',
    [switch]$NoModelBridge,
    [switch]$NoTunnel,
    [switch]$InstallCloudflared,
    [switch]$NoSync,
    [switch]$Synthetic
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){ $ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
function PythonExe {
    if($env:PROJECT_PYTHON -and (Test-Path $env:PROJECT_PYTHON)){return $env:PROJECT_PYTHON}
    foreach($n in @('python.exe','python','py.exe','py')){ $c=Get-Command $n -ErrorAction SilentlyContinue;if($c){return $c.Source}}
    throw 'Python 3 not found.'
}
$python=PythonExe
if(-not $NoModelBridge){
    & (Join-Path $ProjectRoot 'run-v213-local-llm-bridge.ps1') -ProjectRoot $ProjectRoot -Model $Model -LlamaBaseUrl $LlamaBaseUrl -NoTunnel:$NoTunnel -InstallCloudflared:$InstallCloudflared
    if($LASTEXITCODE -ne 0){throw 'Local-model bridge failed.'}
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
            if(Test-Path 'sync-v21-public-snapshot.ps1'){
                & .\sync-v21-public-snapshot.ps1 -ProjectRoot $ProjectRoot
                if($LASTEXITCODE -ne 0){throw 'v2.1 signed public snapshot sync failed.'}
            }
            # Preserve the currently-active v2.1.2 five-field schedule while a new
            # snapshot is promoted. The formal v2.1.3 activation delegates the
            # legacy /v212 admin route, so this remains safe after activation too.
            if(Test-Path 'sync-v212-top20-report.ps1'){
                & .\sync-v212-top20-report.ps1 -ProjectRoot $ProjectRoot
                if($LASTEXITCODE -ne 0){throw 'v2.1.2 report sync failed.'}
            }
            $v213Config=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\wrangler.v213.production.local.toml'
            if(Test-Path $v213Config -PathType Leaf){
                # Re-apply the guarded activation after every new quick tunnel so
                # the Worker local-model allowlist/secret never points at a dead
                # trycloudflare hostname. This also promotes the fresh v2.1.3 report.
                & .\activate-v213-seven-field-schedule.ps1 -ProjectRoot $ProjectRoot -ConfirmActivation
                if($LASTEXITCODE -ne 0){throw 'v2.1.3 scheduled route/model refresh failed.'}
                Write-Host 'V213_SCHEDULE_AND_MODEL_ROUTE_REFRESH = PASS' -ForegroundColor Green
            } else {
                Write-Host 'V213_REPORT_READY = PASS; formal v2.1.3 schedule activation has not been performed yet.' -ForegroundColor Green
            }
        }
    }
    Write-Host 'INVESTOR_INTELLIGENCE_V213_LOCAL = PASS' -ForegroundColor Green
}
finally { Pop-Location }
