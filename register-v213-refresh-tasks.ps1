[CmdletBinding()]
param(
    [string]$RuntimeRoot = '',
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$MorningRefreshTime = '07:20',
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$EveningRefreshTime = '20:20'
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($RuntimeRoot)){ $RuntimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime' }
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$runScript=Join-Path $RuntimeRoot 'run-v213-local.ps1'
if(-not(Test-Path $runScript -PathType Leaf)){ throw "Stable v2.1.3 runtime is missing: $runScript" }
$taskNames=@('InvestorIntelligence-v21-MorningRefresh','InvestorIntelligence-v21-EveningRefresh')
$backup=@{}
foreach($name in $taskNames){
    $existing=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if($existing){ try{$backup[$name]=Export-ScheduledTask -TaskName $name}catch{$backup[$name]=$null} } else {$backup[$name]=$null}
}
$ps=(Get-Command powershell.exe -ErrorAction Stop).Source
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$definitions=@(
    @{Name=$taskNames[0];Time=$MorningRefreshTime},
    @{Name=$taskNames[1];Time=$EveningRefreshTime}
)
try{
    foreach($d in $definitions){
        $args="-NoProfile -ExecutionPolicy Bypass -File `"$runScript`" -ProjectRoot `"$RuntimeRoot`""
        $action=New-ScheduledTaskAction -Execute $ps -Argument $args -WorkingDirectory $RuntimeRoot
        $trigger=New-ScheduledTaskTrigger -Daily -At ([DateTime]::ParseExact($d.Time,'HH:mm',$null))
        Register-ScheduledTask -TaskName $d.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Investor Intelligence v2.1.3 local-model/public-data refresh before 08:00 / 21:00 owner LINE push.' -Force | Out-Null
    }
    foreach($d in $definitions){
        $task=Get-ScheduledTask -TaskName $d.Name -ErrorAction Stop
        $action=@($task.Actions)|Select-Object -First 1
        if(-not $action -or [string]$action.Execute -ne $ps -or [string]$action.Arguments -notlike '*run-v213-local.ps1*'){
            throw "Scheduled task verification failed: $($d.Name)"
        }
    }
}catch{
    $failure=$_.Exception.Message
    foreach($name in $taskNames){
        try{
            if($backup[$name]){ Register-ScheduledTask -TaskName $name -Xml ([string]$backup[$name]) -Force | Out-Null }
            else{ Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue }
        }catch{}
    }
    throw "V213 task upgrade failed and prior task definitions were restored where available. $failure"
}
[ordered]@{
    schema_version=1
    product_version='2.1.3'
    runtime_root=$RuntimeRoot
    local_refresh_times=@($MorningRefreshTime,$EveningRefreshTime)
    line_push_times=@('08:00 Asia/Taipei','21:00 Asia/Taipei')
    task_names=$taskNames
    updated_utc=(Get-Date).ToUniversalTime().ToString('o')
}|ConvertTo-Json -Depth 5|Set-Content (Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\v213-refresh-tasks.json') -Encoding utf8
Write-Host "V213_REFRESH_TASKS = PASS; $MorningRefreshTime / $EveningRefreshTime" -ForegroundColor Green
