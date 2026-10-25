# The registration transaction of scripts/register_sealed_freshness_tasks.ps1, kept in its own file so the mutation
# sequence can be tested with mocked scheduler commands (project audit 2026-09-29, round 2 finding 1).
#
#   1. Capture: every definition's preimage is taken before anything changes. A task is "absent" only when the
#      scheduler answers ObjectNotFound; any other lookup error, an ambiguous name or a failed/empty XML export stops
#      here with zero registrations and zero unregistrations.
#   2. Mutate: each definition is recorded as attempted before its Register call (an attempted call with an
#      ambiguous outcome still needs recovery), then the registered settings are verified.
#   3. Recover: only attempted definitions are touched: a task that existed is re-registered from its captured XML;
#      a task that was absent is unregistered if it now exists (a failed lookup marks recovery unverified). Untouched
#      or uncaptured definitions are never altered.

function Get-SealedFreshnessTaskPreimage([string]$Name) {
    try {
        $found = @(Get-ScheduledTask -TaskName $Name -ErrorAction Stop)
    } catch {
        if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { return @{ Exists = $false; Xml = $null } }
        throw "PREIMAGE_CAPTURE_FAILED: lookup $Name"
    }
    if ($found.Count -ne 1) { throw "PREIMAGE_CAPTURE_FAILED: $($found.Count) tasks named $Name" }
    try {
        $xml = [string](Export-ScheduledTask -TaskName $Name -ErrorAction Stop)
    } catch {
        throw "PREIMAGE_CAPTURE_FAILED: export $Name"
    }
    if ([string]::IsNullOrWhiteSpace($xml)) { throw "PREIMAGE_CAPTURE_FAILED: empty export $Name" }
    return @{ Exists = $true; Xml = $xml }
}

function Invoke-SealedFreshnessTaskTransaction {
    param(
        [Parameter(Mandatory)] [object[]]$Definitions,
        [Parameter(Mandatory)] [scriptblock]$BuildAction,
        [Parameter(Mandatory)] [string]$CurrentUser,
        [string]$LogonType = 'Interactive')

    $preimages = @{}
    try {
        foreach ($Definition in $Definitions) { $preimages[$Definition.Name] = Get-SealedFreshnessTaskPreimage $Definition.Name }
    } catch {
        throw "SEALED_FRESHNESS_TASKS_UNCHANGED; $($_.Exception.Message)"
    }

    $attempted = New-Object System.Collections.Generic.List[string]
    try {
        foreach ($Definition in $Definitions) {
            $action = & $BuildAction $Definition
            $principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType $LogonType -RunLevel Limited
            $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
            $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $Definition.RepetitionMinutes) -RepetitionDuration (New-TimeSpan -Days 10000)
            $attempted.Add($Definition.Name)
            Register-ScheduledTask -TaskName $Definition.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $Definition.Description -Force -ErrorAction Stop | Out-Null
        }

        foreach ($Definition in $Definitions) {
            $Task = Get-ScheduledTask -TaskName $Definition.Name -ErrorAction Stop
            if ([string]$Task.Principal.LogonType -ne $LogonType) { throw "LOGON_TYPE_INVALID: $($Definition.Name)" }
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
        foreach ($name in $attempted) {
            try {
                if ($preimages[$name].Exists) {
                    Register-ScheduledTask -TaskName $name -Xml $preimages[$name].Xml -Force -ErrorAction Stop | Out-Null
                } else {
                    $present = $true
                    try { Get-ScheduledTask -TaskName $name -ErrorAction Stop | Out-Null }
                    catch {
                        if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { $present = $false } else { throw }
                    }
                    if ($present) { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop }
                }
            }
            catch { $rollbackFailed = $true }
        }
        if ($rollbackFailed) { throw "SEALED_FRESHNESS_TASKS_UPGRADE_FAILED; rollback_unverified=true. $failure" }
        throw "SEALED_FRESHNESS_TASKS_UPGRADE_FAILED; rollback commands completed for $($attempted.Count) attempted task(s). $failure"
    }
}
