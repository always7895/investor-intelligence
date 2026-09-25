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
    & $py "scripts\publish_sealed_snapshot.py" --live-clock 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[$stamp] GENERATE FAILED — pointer untouched, previous run still serving"
        Add-Content -Path $log -Value "[$stamp] GENERATE FAILED exit=$LASTEXITCODE (pointer untouched)"
        exit $LASTEXITCODE
    }
    $sumDir = Get-ChildItem (Join-Path $repo "state\v213-snapshots") -Directory |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    & $py "scripts\sync_sealed_snapshot_kv.py" --run-dir $sumDir.FullName 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[$stamp] SYNC FAILED — pointer untouched, previous run still serving"
        Add-Content -Path $log -Value "[$stamp] SYNC FAILED exit=$LASTEXITCODE (pointer untouched)"
        exit $LASTEXITCODE
    }
    Add-Content -Path $log -Value "[$stamp] REFRESH OK run=$($sumDir.Name) pointer last"
    Write-Host "[$stamp] sealed refresh OK"
} finally {
    Exit-V213OperationLock
}
exit 0