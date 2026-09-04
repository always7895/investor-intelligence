[CmdletBinding()]
param(
    [string]$RuntimeRoot = '',
    [ValidateSet('morning','evening','manual')][string]$Slot = 'manual'
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($RuntimeRoot)){$RuntimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime'}
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$run=Join-Path $RuntimeRoot 'run-v213-local.ps1'
if(-not(Test-Path -LiteralPath $run -PathType Leaf)){throw "Stable R75 refresh entrypoint is missing: $run"}
$statusRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\status'
$logRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\logs\scheduled-refresh'
New-Item -ItemType Directory -Force -Path $statusRoot,$logRoot|Out-Null
$started=(Get-Date).ToUniversalTime()
$log=Join-Path $logRoot ('r75-'+$Slot+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
$status='FAIL';$exitCode=1;$errorMessage=''
try{
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $run -ProjectRoot $RuntimeRoot -NoModelBridge -NoTunnel -NoSync -NoAutoActivation *>&1|Tee-Object -FilePath $log
    $exitCode=$LASTEXITCODE
    if($exitCode-ne0){throw "Scheduled data-only refresh returned exit code $exitCode."}
    $status='PASS'
}catch{$errorMessage=$_.Exception.Message;$exitCode=1}
$finished=(Get-Date).ToUniversalTime()
$receipt=[ordered]@{
    schema_version=1
    product_version='2.1.3'
    runtime_profile='R75'
    slot=$Slot
    status=$status
    exit_code=$exitCode
    started_utc=$started.ToString('o')
    finished_utc=$finished.ToString('o')
    duration_seconds=[Math]::Round(($finished-$started).TotalSeconds,3)
    production_mutation=$false
    model_bridge_started=$false
    remote_sync_attempted=$false
    log=$log
    error=$errorMessage
}
$latest=Join-Path $statusRoot ('v213-r75-scheduled-refresh-'+$Slot+'-latest.json')
$temp=$latest+'.tmp'
$receipt|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $temp -Encoding utf8
Move-Item -LiteralPath $temp -Destination $latest -Force
if($status-ne'PASS'){Write-Error $errorMessage;exit 1}
Write-Host "V213_R75_SCHEDULED_REFRESH = PASS; slot=$Slot; production_mutation=false; log=$log" -ForegroundColor Green
exit 0
