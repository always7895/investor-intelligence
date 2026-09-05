[CmdletBinding()]
param(
    [string]$RuntimeRoot = '',
    [ValidateSet('morning','evening','manual')][string]$Slot = 'manual',
    [switch]$PublishSealedBundle
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($RuntimeRoot)){$RuntimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime'}
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$run=Join-Path $RuntimeRoot 'run-v213-local.ps1'
$lockScript=Join-Path $RuntimeRoot 'scripts\v213_operation_lock.ps1'
if(-not(Test-Path -LiteralPath $lockScript -PathType Leaf)){throw "R75 operation-lock module is missing: $lockScript"}
. $lockScript
if(-not(Test-Path -LiteralPath $run -PathType Leaf)){throw "Stable R75 refresh entrypoint is missing: $run"}
$statusRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\status'
$logRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\logs\scheduled-refresh'
New-Item -ItemType Directory -Force -Path $statusRoot,$logRoot|Out-Null
$started=(Get-Date).ToUniversalTime()
$log=Join-Path $logRoot ('r75-'+$Slot+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
$status='FAIL';$exitCode=1;$errorMessage='';$publication=$null;$beforeRunId=''
$publicationResult=Join-Path $statusRoot ('sealed-publication/'+[guid]::NewGuid().ToString('N')+'.json')
try{
    [void](Enter-V213OperationLock -Owner ("scheduled-refresh-"+$Slot) -TimeoutSeconds 0)
    if($PublishSealedBundle){
        . (Join-Path $RuntimeRoot 'scripts/v213_sealed_refresh.ps1')
        $bundle=Join-Path $RuntimeRoot 'data/cache/v213_activation_bundle_upload.json'
        if(Test-Path -LiteralPath $bundle){try{$beforeRunId=[string](Get-Content -LiteralPath $bundle -Raw -Encoding utf8|ConvertFrom-Json).run_id}catch{}}
    }
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $run -ProjectRoot $RuntimeRoot -NoModelBridge -NoTunnel -NoSync -NoAutoActivation *>&1|Tee-Object -FilePath $log
    $exitCode=$LASTEXITCODE
    if($exitCode-ne0){throw "Scheduled data-only refresh returned exit code $exitCode."}
    if($PublishSealedBundle){
        $newRunId=[string](Get-Content -LiteralPath $bundle -Raw -Encoding utf8|ConvertFrom-Json).run_id
        if($newRunId-cnotmatch'^\d{8}T\d{6}Z-[0-9a-f]{12}$'-or$newRunId-ceq$beforeRunId){throw 'V213_REFRESH_NEW_BUNDLE_REQUIRED'}
        $runTime=[DateTimeOffset]::ParseExact($newRunId.Substring(0,16),"yyyyMMdd'T'HHmmss'Z'",[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::AssumeUniversal)
        if($runTime-lt$started.AddSeconds(-1)-or$runTime-gt[DateTimeOffset]::UtcNow.AddSeconds(300)){throw 'V213_REFRESH_BUNDLE_NOT_FROM_THIS_JOB'}
        $config=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence/UserData/config/v21-owner-line.local.json'
        $publication=Invoke-V213SealedRefresh -ProjectRoot $RuntimeRoot -LocalConfigPath $config -ResultPath $publicationResult
    }
    $status='PASS'
}catch{$errorMessage=$_.Exception.Message;$exitCode=1}
finally{Exit-V213OperationLock}
if($null-eq$publication-and(Test-Path -LiteralPath $publicationResult)){
    try{$publication=Get-Content -LiteralPath $publicationResult -Raw -Encoding utf8|ConvertFrom-Json}catch{throw 'V213_REFRESH_PUBLICATION_JOURNAL_UNREADABLE; mutation_unknown=true'}
}
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
    production_mutation=$(if($null-ne$publication){$publication.production_mutation}else{$false})
    model_bridge_started=$false
    remote_sync_attempted=$(if($null-ne$publication){$publication.remote_sync_attempted}else{$false})
    sealed_publication_enabled=[bool]$PublishSealedBundle
    publication_state=$(if($null-ne$publication){$publication.publication_state}else{'NOT_ATTEMPTED'})
    publication_journal=$(if($null-ne$publication){$publicationResult}else{''})
    log=$log
    error=$errorMessage
    operation_lock='Local\InvestorIntelligence_V213_R75_OPERATION'
    missed_slot_policy='StartWhenAvailable'
    timeout_recovery='TaskScheduler_IgnoreNew_hard_timeout_100m'
}
$latest=Join-Path $statusRoot ('v213-r75-scheduled-refresh-'+$Slot+'-latest.json')
$temp=$latest+'.tmp'
$receipt|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $temp -Encoding utf8
Move-Item -LiteralPath $temp -Destination $latest -Force
if($status-ne'PASS'){Write-Error $errorMessage;exit 1}
Write-Host "V213_R75_SCHEDULED_REFRESH = PASS; slot=$Slot; production_mutation=$($receipt.production_mutation); log=$log" -ForegroundColor Green
exit 0
