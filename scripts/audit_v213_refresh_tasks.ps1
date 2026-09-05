[CmdletBinding()]
param([string]$RuntimeRoot = '', [switch]$SelfTest)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime' }
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$run = Join-Path $RuntimeRoot 'run-v213-scheduled-refresh.ps1'
$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source

function Test-RefreshDefinition($Task, [string]$Slot, [string]$Time, $LastResult) {
    if (-not $Task) { return [ordered]@{ slot=$Slot; status='MISSING'; definition_matches=$false; last_result=$null } }
    $actions = @($Task.Actions)
    $expected = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$run`" -RuntimeRoot `"$RuntimeRoot`" -Slot $Slot"
    $definitionMatches = $actions.Count -eq 1 -and [string]$actions[0].Execute -ieq $powershell -and [string]$actions[0].Arguments -ceq $expected -and [string]$actions[0].WorkingDirectory -ieq $RuntimeRoot
    $triggers = @($Task.Triggers)
    $timeMatches = $triggers.Count -eq 1
    if ($timeMatches) { try { $timeMatches = ([DateTime]::Parse([string]$triggers[0].StartBoundary)).ToString('HH:mm') -eq $Time } catch { $timeMatches=$false } }
    $legacy = @($actions | Where-Object { [string]$_.Arguments -match 'run-v212-local\.ps1' }).Count -gt 0
    $healthy = $definitionMatches -and $timeMatches -and $LastResult -eq 0
    return [ordered]@{ slot=$Slot; status=$(if($healthy){'PASS'}else{'REVIEW_REQUIRED'}); definition_matches=$definitionMatches; trigger_time_matches=$timeMatches; legacy_v212=$legacy; last_result=$LastResult }
}

if ($SelfTest) {
    $t = [pscustomobject]@{ Actions=@([pscustomobject]@{ Execute=$powershell; Arguments="-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$run`" -RuntimeRoot `"$RuntimeRoot`" -Slot morning"; WorkingDirectory=$RuntimeRoot }); Triggers=@([pscustomobject]@{ StartBoundary='2026-09-05T07:20:00' }) }
    if ((Test-RefreshDefinition $t morning '07:20' 0).status -ne 'PASS') { throw 'AUDIT_VALID_DEFINITION_FAILED' }
    if ((Test-RefreshDefinition $t morning '07:20' 1).status -eq 'PASS') { throw 'AUDIT_FAILED_RUN_ACCEPTED' }
    if ((Test-RefreshDefinition $t morning '08:00' 0).status -eq 'PASS') { throw 'AUDIT_WRONG_TIME_ACCEPTED' }
    $t.Actions[0].Arguments='-File "C:\synthetic\run-v212-local.ps1"'
    $legacyAudit = Test-RefreshDefinition $t morning '07:20' 0
    if (-not $legacyAudit.legacy_v212 -or $legacyAudit.status -eq 'PASS') { throw 'AUDIT_LEGACY_NOT_DETECTED' }
    $null = $legacyAudit | ConvertTo-Json -Depth 5
    if ((Test-RefreshDefinition $null morning '07:20' $null).status -ne 'MISSING') { throw 'AUDIT_MISSING_NOT_DETECTED' }
    Write-Output 'REFRESH_AUDIT_SELF_TEST=PASS; task_mutation=false'
    exit 0
}
$results = foreach ($item in @(@{name='Morning';slot='morning';time='07:20'},@{name='Evening';slot='evening';time='20:20'})) {
    $task = Get-ScheduledTask -TaskName ('InvestorIntelligence-v21-'+$item.name+'Refresh') -ErrorAction SilentlyContinue
    $last = if ($task) { (Get-ScheduledTaskInfo -InputObject $task).LastTaskResult } else { $null }
    Test-RefreshDefinition $task $item.slot $item.time $last
}
$wrapperMode='UNVERIFIED'
if (Test-Path -LiteralPath $run -PathType Leaf) {
    $text=[IO.File]::ReadAllText($run)
    if ($text.Contains('-NoSync') -and $text.Contains('-NoAutoActivation')) { $wrapperMode='LOCAL_ONLY_NO_PUBLISH' }
}
[ordered]@{ schema_version=1; tasks=@($results); candidate_wrapper_mode=$wrapperMode; production_freshness_verified=$false; task_mutation=$false; production_mutation=$false; note='A local-only refresh cannot certify fresh Production data. Publishing requires separate authorization and sealed validation.' } | ConvertTo-Json -Depth 5
