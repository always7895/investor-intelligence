# Task #23 PRODUCTION_FRESHNESS_REPAIR — 60-minute sealed-snapshot refresh.
#
# Pipeline (strict fail-closed; the previous sealed run keeps serving on any failure):
#   1. scripts/publish_sealed_snapshot.py --live-clock  (re-evaluates the multi-lineage
#      evidence pipeline at the current UTC clock; exits non-zero on corpus drift or
#      non-2/2 qualification — nothing is published in that case)
#   2. scripts/sync_sealed_snapshot_kv.py --run-dir <new run>  (14 objects FIRST,
#      readback sha verification, snapshot:current pointer LAST)
#
# Scheduling: Windows Task Scheduler, every 60 minutes via
#   schtasks /Create /TN "InvestorIntelligenceSealedFreshness" /SC MINUTE /MO 60 /TR "<this file>"
# Kept well inside the V21_TOP20_MAX_AGE_SECONDS=7200 (2h) window: two consecutive
# failures still fit one window if the previous run was <=0h50m old.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logDir = Join-Path $repo "data\cache"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "sealed-refresh.log"
$stamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"

. (Join-Path $repo "scripts\v213_operation_lock.ps1")

function Invoke-LoggedNative([scriptblock]$Command) {
    # Run a native command with Continue so stderr lines are logged, not thrown; return its lines and exit code.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = @(& $Command 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($lines.Count -gt 0) { Add-Content -Path $log -Value $lines }
    $lines | ForEach-Object { Write-Host $_ }
    return [pscustomobject]@{ Code = $code; Lines = $lines }
}
try {
    Enter-V213OperationLock -Owner "SealedRefresh" -TimeoutSeconds 0 | Out-Null
} catch {
    Write-Host "[$stamp] LOCK_BUSY — another refresh or operation is running; exiting cleanly"
    Add-Content -Path $log -Value "[$stamp] LOCK_BUSY — collision skipped"
    exit 0
}

try {
    Write-Host "[$stamp] sealed refresh start (cwd=$repo)"
    Set-Location $repo

    $py = "python"
    # Data-driven industry rotation and company reports: at most one refresh per ~20 h; failure is logged and
    # never blocks publication (the publisher reports a shortfall for stale rotation data).
    try {
        & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\run_daily_data_refresh.ps1") 2>&1 |
            Tee-Object -FilePath $log -Append | Out-Null
        Add-Content -Path $log -Value "[$stamp] ROTATION exit=$LASTEXITCODE"
    } catch {
        Add-Content -Path $log -Value "[$stamp] ROTATION FAILED (publication continues)"
    }
    # Native steps run with Continue: under Windows PowerShell 5.1 with Stop, any stderr line from python (a
    # warning or traceback) becomes a terminating error that skipped the failure log (2026-09-25 15:56Z run).
    # Success is judged by the exit code; every line, stderr included, goes to the log.
    $published = Invoke-LoggedNative { & $py "scripts\publish_sealed_snapshot.py" --live-clock }
    if ($published.Code -ne 0) {
        Write-Host "[$stamp] GENERATE FAILED — pointer untouched, previous run still serving"
        Add-Content -Path $log -Value "[$stamp] GENERATE FAILED exit=$($published.Code) (pointer untouched)"
        exit $published.Code
    }
    # Sync exactly the run this publisher just wrote (never a newest-folder guess).
    $runMatch = [regex]::Match(($published.Lines -join "`n"), '"run_id":\s*"(\d{8}T\d{6}Z-[0-9a-f]{12})"')
    if (-not $runMatch.Success) {
        Add-Content -Path $log -Value "[$stamp] GENERATE FAILED run id not printed (pointer untouched)"
        exit 1
    }
    $runId = $runMatch.Groups[1].Value
    $runDir = Join-Path $repo ("state\v213-snapshots\" + $runId)
    $synced = Invoke-LoggedNative { & $py "scripts\sync_sealed_snapshot_kv.py" --run-dir $runDir }
    if ($synced.Code -ne 0) {
        Write-Host "[$stamp] SYNC FAILED — pointer untouched, previous run still serving"
        Add-Content -Path $log -Value "[$stamp] SYNC FAILED exit=$($synced.Code) (pointer untouched)"
        exit $synced.Code
    }
    Add-Content -Path $log -Value "[$stamp] REFRESH OK run=$runId pointer last"
    Write-Host "[$stamp] sealed refresh OK"
} catch {
    # Anything unexpected is recorded with its type and message before the task reports failure.
    Add-Content -Path $log -Value ("[$stamp] REFRESH FAILED " + $_.Exception.GetType().Name + ": " + $_.Exception.Message)
    exit 1
} finally {
    Exit-V213OperationLock
}
exit 0