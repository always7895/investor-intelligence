[CmdletBinding()]
param(
    [string]$RuntimeRoot = '',
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$MorningRefreshTime = '07:20',
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$EveningRefreshTime = '20:20',
    [switch]$ValidateOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($RuntimeRoot)){$RuntimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime'}
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$runScript=Join-Path $RuntimeRoot 'run-v213-scheduled-refresh.ps1'
if(-not(Test-Path -LiteralPath $runScript -PathType Leaf)){throw "Stable R75 scheduled-refresh wrapper is missing: $runScript"}
$taskNames=@('InvestorIntelligence-v21-MorningRefresh','InvestorIntelligence-v21-EveningRefresh')
$ps=(Get-Command powershell.exe -ErrorAction Stop).Source
$definitions=@(
    @{Name=$taskNames[0];Time=$MorningRefreshTime;Slot='morning'},
    @{Name=$taskNames[1];Time=$EveningRefreshTime;Slot='evening'}
)
function Get-ActionArguments([string]$Slot){return "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runScript`" -RuntimeRoot `"$RuntimeRoot`" -Slot $Slot"}
if($ValidateOnly){
    foreach($definition in $definitions){
        [void][DateTime]::ParseExact($definition.Time,'HH:mm',$null)
        $args=Get-ActionArguments $definition.Slot
        if($args-notlike'*run-v213-scheduled-refresh.ps1*'-or$args-notlike"*-Slot $($definition.Slot)*"){throw 'Scheduled task action construction failed.'}
    }
    Write-Host "V213_R75_REFRESH_TASKS_VALIDATE = PASS; $MorningRefreshTime / $EveningRefreshTime; data_only=true; production_mutation=false" -ForegroundColor Green
    exit 0
}
$backup=@{}
foreach($name in $taskNames){
    $existing=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if($existing){try{$backup[$name]=Export-ScheduledTask -TaskName $name}catch{$backup[$name]=$null}}else{$backup[$name]=$null}
}
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -MultipleInstances StopExisting -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 100) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10)
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType S4U -RunLevel Limited
try{
    foreach($definition in $definitions){
        $action=New-ScheduledTaskAction -Execute $ps -Argument (Get-ActionArguments $definition.Slot) -WorkingDirectory $RuntimeRoot
        $trigger=New-ScheduledTaskTrigger -Daily -At ([DateTime]::ParseExact($definition.Time,'HH:mm',$null))
        Register-ScheduledTask -TaskName $definition.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Investor Intelligence v2.1.3 R75 data-only refresh before 08:00 / 21:00 owner LINE push. No model bridge, Worker deploy, Production sync, or activation is attempted.' -Force|Out-Null
    }
    foreach($definition in $definitions){
        $task=Get-ScheduledTask -TaskName $definition.Name -ErrorAction Stop
        $action=@($task.Actions)|Select-Object -First 1
        if(-not$action-or[string]$action.Execute-ne$ps-or[string]$action.Arguments-notlike'*run-v213-scheduled-refresh.ps1*'-or[string]$action.Arguments-notlike"*-Slot $($definition.Slot)*"){
            throw "Scheduled task verification failed: $($definition.Name)"
        }
        $settingsObserved=$task.Settings
        if(-not$settingsObserved.StartWhenAvailable-or-not$settingsObserved.WakeToRun-or-not$settingsObserved.RunOnlyIfNetworkAvailable-or[int]$settingsObserved.RestartCount-lt3-or[string]$settingsObserved.MultipleInstances-ne'StopExisting'){throw "Scheduled task reliability settings failed: $($definition.Name)"}
    }
}catch{
    $failure=$_.Exception.Message
    foreach($name in $taskNames){
        try{if($backup[$name]){Register-ScheduledTask -TaskName $name -Xml ([string]$backup[$name]) -Force|Out-Null}else{Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue}}catch{}
    }
    throw "V213 R75 task upgrade failed and prior definitions were restored. $failure"
}
[ordered]@{
    schema_version=2
    product_version='2.1.3'
    runtime_profile='R75'
    runtime_root=$RuntimeRoot
    local_refresh_times=@($MorningRefreshTime,$EveningRefreshTime)
    line_push_times=@('08:00 Asia/Taipei','21:00 Asia/Taipei')
    task_names=$taskNames
    data_only=$true
    model_bridge_started_by_schedule=$false
    production_mutation_by_schedule=$false
    wake_to_run=$true
    restart_count=3
    restart_interval_minutes=10
    execution_time_limit_minutes=100
    logon_type='S4U'
    network_required=$true
    multiple_instances='StopExisting'
    missed_slot_policy='StartWhenAvailable'
    timeout_recovery='StopExisting_after_100_minutes_then_retry'
    updated_utc=(Get-Date).ToUniversalTime().ToString('o')
}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\v213-refresh-tasks.json') -Encoding utf8
Write-Host "V213_R75_REFRESH_TASKS = PASS; $MorningRefreshTime / $EveningRefreshTime; wake_to_run=true; restart_count=3; data_only=true" -ForegroundColor Green
