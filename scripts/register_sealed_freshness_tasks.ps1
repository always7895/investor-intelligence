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
# -CarryForwardTop20 / -SnapshotRoot are passed through to the hourly task only (single-writer design T10: the
# hourly publisher carries the validated Top20 bundle; an installed runtime keeps sealed runs under data\). The
# registration receipt is written under %LOCALAPPDATA%\InvestorIntelligence\status, never into the script root.
#
# No secret, tenant, or credential material is read, stored, or printed.
# Requires the owning user's current session; never requests a password.

[CmdletBinding()]
param(
    [string]$ScriptRoot = '',
    [switch]$CarryForwardTop20,
    [string]$SnapshotRoot = '',
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
        -Argument (Get-ActionArguments $Definition $scriptPath) `
        -WorkingDirectory $ScriptRoot
}

function Get-ActionArguments([hashtable]$Definition, [string]$ScriptPath) {
    $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$ScriptPath`""
    if ($Definition.Name -eq 'InvestorIntelligenceSealedFreshness') {
        if ($CarryForwardTop20) { $arguments += ' -CarryForwardTop20' }
        if ($SnapshotRoot) {
            if ($SnapshotRoot -match '["\r\n]') { throw 'SNAPSHOT_ROOT_INVALID' }
            $arguments += " -SnapshotRoot `"$SnapshotRoot`""
        }
    }
    return $arguments
}

if ($ValidateOnly) {
    foreach ($Definition in $definitions) {
        $action = Build-Action $Definition
        Write-Host ("TASK_ACTION {0}: {1}" -f $Definition.Name, $action.Arguments)
    }
    Write-Host "SEALED_FRESHNESS_TASKS_VALIDATE = PASS; carry_forward_top20=$([bool]$CarryForwardTop20); production_mutation=false" -ForegroundColor Green
    exit 0
}

# Capture every preimage first (any lookup/export failure changes nothing), then register and verify; recovery
# touches only the attempted definitions (scripts/sealed_freshness_task_transaction.ps1).
. (Join-Path $PSScriptRoot 'sealed_freshness_task_transaction.ps1')
$logonType = 'Interactive'
Invoke-SealedFreshnessTaskTransaction -Definitions $definitions -BuildAction ${function:Build-Action} -CurrentUser $currentUser -LogonType $logonType

$statusDir = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\status'
New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
$receiptPath = Join-Path $statusDir 'sealed-freshness-tasks.json'
[ordered]@{
    schemaVersion = 1
    registeredUtc = (Get-Date).ToUniversalTime().ToString('o')
    scriptRoot = $ScriptRoot
    tasks = $definitions | ForEach-Object { @{ name = $_.Name; intervalMinutes = $_.RepetitionMinutes } }
    carryForwardTop20 = [bool]$CarryForwardTop20
    snapshotRoot = $SnapshotRoot
    startWhenAvailable = $true
    executionTimeLimitMinutes = 60
    logonType = $logonType
    # Interactive tasks run only while the owning user is logged on. Registration itself changes production schedules
    # and activates the publishing task (which writes KV when it runs); the registration writes no KV directly.
    ownerLoggedInRequired = ($logonType -eq 'Interactive')
    productionMutation = $true
    scheduleMutation = $true
    activatesPublishingTask = $true
    directKvWrite = $false
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8

Write-Host "SEALED_FRESHNESS_TASKS = PASS; hourly sealed refresh + 30min read-only watchdog registered." -ForegroundColor Green