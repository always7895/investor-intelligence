# Canonical registration for the hourly sealed-freshness pipeline task and the
# read-only freshness watchdog. Idempotent: re-registers with verified settings
# and rolls back to the captured XML definition on any verification failure.
#
#   * InvestorIntelligenceSealedFreshness  - hourly generate + fail-closed KV sync
#       (scripts/run_production_sealed_refresh.ps1; the previous ad-hoc task keeps
#       its name so the known-good schedule identity survives the re-point).
#   * InvestorIntelligenceFreshnessWatchdog - every 30 minutes, READ-ONLY
#       (scripts/freshness_watchdog.ps1; never writes KV; durable jsonl artifact).
#
# Settings hardening (P0 freshness incident follow-up):
#   * StartWhenAvailable ON  (a missed align under host sleep catches up on wake)
#   * ExecutionTimeLimit PT1H (the previous PT72H hides multi-hour overruns)
#   * Repetition interval anchored at registration (hourly / 30)
#
# No and no secret, tenant, or credential material is read, stored, or printed.
# Requires the owning user's current session; never requests a password.

[CmdletBinding()]
param(
    [string]$ScriptRoot = '',
    [switch]$ValidateOnly)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ScriptRoot)) {
    $ScriptRoot = (Split-Path -Parent $PSScriptRoot)
}
$ScriptRoot = [IO.Path]::GetFullPath($ScriptRoot)
$PowerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name

$definitions = @(
    @{
        Name = 'InvestorIntelligenceSealedFreshness'
        ArgumentScript = 'run_production_sealed_refresh.ps1'
        RepetitionMinutes = 60
        Due = 'DAILY'
        Description = 'Hourly sealed snapshot: live-clock generate, fail-closed KV sync, pointer last. Any failure leaves the previously sealed run serving.'
    },
    @{
        Name = 'InvestorIntelligenceFreshnessWatchdog'
        ArgumentScript = 'freshness_watchdog.ps1'
        RepetitionMinutes = 30
        Due = 'DAILY'
        Description = 'Read-only hourly public pointer freshness watchdog; appends durable state lines; never writes to any KV namespace.'
    }
)

function Build-Action([hashtable]$Definition) {
    $scriptPath = Join-Path $ScriptRoot "scripts\$($Definition.ArgumentScript)"
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "SCRIPT_MISSING: $scriptPath"
    }
    return New-ScheduledTaskAction -Execute $PowerShellExe `
        -Argument ("-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`"") `
        -WorkingDirectory $ScriptRoot
}

if ($ValidateOnly) {
    foreach ($Definition in $definitions) {
        [void](Build-Action $Definition)
    }
    Write-Host "SEALED_FRESHNESS_TASKS_VALIDATE = PASS; production_mutation=false" -ForegroundColor Green
    exit 0
}

$backup = @{}
try {
    foreach ($Definition in $definitions) {
        $existing = Get-ScheduledTask -TaskName $Definition.Name -ErrorAction SilentlyContinue
        if ($existing) { $backup[$Definition.Name] = Export-ScheduledTask -TaskName $Definition.Name -ErrorAction Stop }
        else { $backup[$Definition.Name] = $null }
    }

    $logonType = 'Interactive'
    foreach ($Definition in $definitions) {
        $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType $logonType -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $Definition.RepetitionMinutes) -RepetitionDuration (New-TimeSpan -Days 10000)
        Register-ScheduledTask -TaskName $Definition.Name -Action (Build-Action $Definition) -Trigger $trigger -Settings $settings -Principal $principal -Description $Definition.Description -Force | Out-Null
    }

    foreach ($Definition in $definitions) {
        $Task = Get-ScheduledTask -TaskName $Definition.Name -ErrorAction Stop
        if ([string]$Task.Principal.LogonType -ne $logonType) { throw "LOGON_TYPE_INVALID: $($Definition.Name)" }
        $TaskSettings = $Task.Settings
        if (-not $TaskSettings.StartWhenAvailable) { throw "START_WHEN_AVAILABLE_MISSING: $($Definition.Name)" }
        $limitSpan = if ($TaskSettings.ExecutionTimeLimit -is [TimeSpan]) { $TaskSettings.ExecutionTimeLimit } else { [System.Xml.XmlConvert]::ToTimeSpan([string]$TaskSettings.ExecutionTimeLimit) }
        if ($limitSpan -ne (New-TimeSpan -Hours 1)) { throw "EXECUTION_TIME_LIMIT_INVALID: $($Definition.Name)" }
        $repetition = $Task.Triggers[0].Repetition
        $repSpan = if ($repetition -and $repetition.Interval -is [TimeSpan]) { $repetition.Interval } elseif ($repetition) { [System.Xml.XmlConvert]::ToTimeSpan([string]$repetition.Interval) } else { $null }
        if (-not $repSpan -or $repSpan -ne (New-TimeSpan -Minutes $Definition.RepetitionMinutes)) {
            throw "REPETITION_INTERVAL_INVALID: $($Definition.Name)"
        }
    }
}
catch {
    $failure = $_.Exception.Message
    $rollbackFailed = $false
    foreach ($Definition in $definitions) {
        try {
            if ($backup[$Definition.Name]) {
                Register-ScheduledTask -TaskName $Definition.Name -Xml ([string]$backup[$Definition.Name]) -Force -ErrorAction Stop | Out-Null
            }
            elseif (Get-ScheduledTask -TaskName $Definition.Name -ErrorAction SilentlyContinue) {
                Unregister-ScheduledTask -TaskName $Definition.Name -Confirm:$false -ErrorAction Stop
            }
        }
        catch { $rollbackFailed = $true }
    }
    if ($rollbackFailed) { throw "SEALED_FRESHNESS_TASKS_UPGRADE_FAILED; rollback_unverified=true" }
    throw "SEALED_FRESHNESS_TASKS_UPGRADE_FAILED; rollback commands completed. $failure"
}

[ordered]@{
    schemaVersion = 1
    registeredUtc = (Get-Date).ToUniversalTime().ToString('o')
    scriptRoot = $ScriptRoot
    tasks = $definitions | ForEach-Object { @{ name = $_.Name; intervalMinutes = $_.RepetitionMinutes } }
    startWhenAvailable = $true
    executionTimeLimitMinutes = 60
    logonType = $logonType
    ownerLoggedInRequired = $false
    productionMutation = $false
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $ScriptRoot 'state\sealed-freshness-tasks.json') -Encoding utf8

Write-Host "SEALED_FRESHNESS_TASKS = PASS; hourly sealed refresh + 30min read-only watchdog registered." -ForegroundColor Green