# Task #23 PRODUCTION_FRESHNESS_REPAIR — 60-minute sealed-snapshot refresh.
#
# Default pipeline (strict fail-closed; the previous sealed run keeps serving on any failure):
#   1. scripts/publish_sealed_snapshot.py --live-clock  (re-evaluates the multi-lineage
#      evidence pipeline at the current UTC clock; exits non-zero on corpus drift or
#      non-2/2 qualification — nothing is published in that case)
#   2. scripts/sync_sealed_snapshot_kv.py --run-dir <new run>  (14 objects FIRST,
#      readback sha verification, snapshot:current pointer LAST)
#
# -CarryForwardTop20 (single-writer design T5; off by default, so the flow above is unchanged):
#   1. seal first: publish --top20-bundle (newest validated last-known-good bundle, exact bytes; an invalid or
#      missing bundle seals an INSUFFICIENT Top20 with a reason code), then replay the staged run through the
#      real Worker readers (scripts/stage_sealed_replay.py);
#   2. a failed replay republishes with an INSUFFICIENT Top20 (macro still sealed) and replays again;
#   3. sync the printed run, pointer last;
#   4. only after the pointer: the daily data refresh, then — when the LKG is refresh_after_hours old and no
#      backoff is active — a data-only Top20 refresh (run-v213-local.ps1 -NoSync), each under a hard timeout with a
#      process-tree kill. The candidate becomes the LKG only after the bundle checks and a staged replay pass; a
#      failure records a 3 h backoff (data\cache\top20-lkg\refresh-state.json). Nothing here blocks the seal.
#
# Scheduling: Windows Task Scheduler, every 60 minutes via
#   schtasks /Create /TN "InvestorIntelligenceSealedFreshness" /SC MINUTE /MO 60 /TR "<this file>"
# Kept well inside the V21_TOP20_MAX_AGE_SECONDS=7200 (2h) window: two consecutive
# failures still fit one window if the previous run was <=0h50m old.
param(
    [switch]$CarryForwardTop20,
    [int]$RefreshTimeoutSeconds = 1800,
    [string]$TabbyUrl = 'http://127.0.0.1:5000',
    [string]$TabbyModel = 'Qwen3.8-27B-EXL3-5.5bpw-v2',
    # Sealed runs directory (default state\v213-snapshots); an installed runtime uses data\v213-snapshots so its
    # attested payload never changes. Exported as II_SNAPSHOT_ROOT for the publisher and the company reports.
    [string]$SnapshotRoot = '',
    # Post-seal work may only start while the run is younger than this (the task limit is 1 h, the next trigger
    # would otherwise be skipped by the operation lock); each child is further capped by RefreshTimeoutSeconds.
    [int]$PostSealBudgetSeconds = 2100,
    # Sealed runs kept under -SnapshotRoot (hourly runs are not rollback targets; the pointer's run is always kept).
    [int]$KeepRuns = 48
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logDir = Join-Path $repo "data\cache"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "sealed-refresh.log"
$stamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
$runStarted = Get-Date
if ([string]::IsNullOrWhiteSpace($SnapshotRoot)) { $runsRoot = Join-Path $repo "state\v213-snapshots" }
else {
    $runsRoot = if ([IO.Path]::IsPathRooted($SnapshotRoot)) { $SnapshotRoot } else { Join-Path $repo $SnapshotRoot }
    $runsRoot = [IO.Path]::GetFullPath($runsRoot)
    $env:II_SNAPSHOT_ROOT = $runsRoot
}

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

function Get-PrintedRunId([object]$Result) {
    $match = [regex]::Match(($Result.Lines -join "`n"), '"run_id":\s*"(\d{8}T\d{6}Z-[0-9a-f]{12})"')
    if ($match.Success) { return $match.Groups[1].Value }
    return $null
}

function Invoke-BoundedScript([string]$Label, [string]$File, [string[]]$Arguments, [int]$TimeoutSeconds) {
    # A child powershell.exe with a hard timeout; on timeout the whole process tree is killed. Output goes to the log.
    $out = [IO.Path]::GetTempFileName()
    $err = [IO.Path]::GetTempFileName()
    $argList = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $File) + $Arguments |
        ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -WorkingDirectory $repo -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $process.Handle  # keeps ExitCode readable under Windows PowerShell 5.1
    if ($process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.WaitForExit()
        $code = $process.ExitCode
    } else {
        & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
        $code = 124
        Add-Content -Path $log -Value "[$stamp] $Label TIMEOUT after ${TimeoutSeconds}s (process tree killed)"
    }
    foreach ($file in @($out, $err)) {
        $content = @(Get-Content -LiteralPath $file -Encoding utf8 -ErrorAction SilentlyContinue)
        if ($content.Count -gt 0) { Add-Content -Path $log -Value $content }
        Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
    }
    Add-Content -Path $log -Value "[$stamp] $Label exit=$code"
    return $code
}

function Test-TabbyModel {
    # The exact local writer model must be loaded before any translation; otherwise the refresh runs label-only
    # (the business-profile translator refuses a reply from any other model) and the seal is never blocked.
    try {
        $loaded = Invoke-RestMethod -Uri ($TabbyUrl.TrimEnd('/') + '/v1/model') -TimeoutSec 5
        return ([string]$loaded.id -ceq $TabbyModel)
    } catch { return $false }
}

function Invoke-CarryForwardSeal {
    # Seal first, in tiers, each replayed through the real readers before any KV write: (1) the carried Top20 plus
    # the identity shards, (2) the carried Top20 alone (an identity defect never costs the Top20), (3) an
    # INSUFFICIENT Top20. The macro overview is sealed in every tier.
    $tiers = @(
        [pscustomobject]@{ Stage = 'OK'; Args = @('--top20-bundle', '--identity-shards', '--bottleneck-v3', '--market-observations', '--price-shards') },
        [pscustomobject]@{ Stage = 'WITHOUT_LAZY'; Args = @('--top20-bundle') },
        [pscustomobject]@{ Stage = 'INSUFFICIENT_FALLBACK'; Args = @('--top20-insufficient', 'TOP20_STAGED_REPLAY_FAILED') }
    )
    $last = [pscustomobject]@{ Code = 1; RunId = $null; Stage = 'REPLAY' }
    foreach ($tier in $tiers) {
        $tierArgs = $tier.Args
        $published = Invoke-LoggedNative { & $py "scripts\publish_sealed_snapshot.py" --live-clock @tierArgs }
        $runId = if ($published.Code -eq 0) { Get-PrintedRunId $published } else { $null }
        if (-not $runId) {
            # A crash caused by an optional input must not cost the seal: fall through to the next tier.
            Add-Content -Path $log -Value "[$(Get-Date -Format o)] GENERATE FAILED tier=$($tier.Stage) exit=$($published.Code); trying the next tier"
            $last = [pscustomobject]@{ Code = $(if ($published.Code) { $published.Code } else { 1 }); RunId = $null; Stage = 'GENERATE' }
            continue
        }
        $replayed = Invoke-LoggedNative { & $py "scripts\stage_sealed_replay.py" --run-dir (Join-Path $runsRoot $runId) }
        if ($replayed.Code -eq 0) { return [pscustomobject]@{ Code = 0; RunId = $runId; Stage = $tier.Stage } }
        Add-Content -Path $log -Value "[$stamp] REPLAY FAILED run=$runId tier=$($tier.Stage); trying the next tier"
        $last = [pscustomobject]@{ Code = $replayed.Code; RunId = $null; Stage = 'REPLAY' }
    }
    return $last
}

function Remove-OldRuns {
    # Keep the newest $KeepRuns sealed runs under an explicit -SnapshotRoot (generated hourly artifacts outside Git;
    # the tracked state\v213-snapshots tree is never pruned).
    if ([string]::IsNullOrWhiteSpace($SnapshotRoot) -or -not (Test-Path -LiteralPath $runsRoot)) { return }
    $runs = @(Get-ChildItem -LiteralPath $runsRoot -Directory | Where-Object { $_.Name -match '^\d{8}T\d{6}Z-[0-9a-f]{12}$' } |
        Sort-Object Name -Descending)
    foreach ($old in ($runs | Select-Object -Skip $KeepRuns)) {
        if ($old.Name -ne $runId) { Remove-Item -LiteralPath $old.FullName -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Invoke-Top20Refresh {
    # After the pointer write: data-only refresh when due, candidate -> staged seal + replay -> LKG promotion.
    $due = Invoke-LoggedNative { & $py "scripts\top20_carry_forward.py" due }
    if (($due.Lines -join "`n") -notmatch '"due":\s*true') { return }
    if (Test-TabbyModel) { Add-Content -Path $log -Value "[$stamp] TABBY_MODEL_VERIFIED $TabbyModel" }
    else { Add-Content -Path $log -Value "[$stamp] TABBY_MODEL_UNVERIFIED (translation label-only)" }
    $code = Invoke-BoundedScript 'TOP20_REFRESH' (Join-Path $repo 'run-v213-local.ps1') `
        @('-ProjectRoot', $repo, '-NoModelBridge', '-NoTunnel', '-NoSync', '-NoAutoActivation') $RefreshTimeoutSeconds
    if ($code -ne 0) {
        Invoke-LoggedNative { & $py "scripts\top20_carry_forward.py" record --result fail --note "REFRESH_EXIT_$code" } | Out-Null
        return
    }
    $candidate = Join-Path $repo 'data\cache\v213_activation_bundle_upload.json'
    $stageRoot = Join-Path ([IO.Path]::GetTempPath()) ('ii-top20-candidate-' + [Guid]::NewGuid().ToString('N'))
    try {
        $staged = Invoke-LoggedNative { & $py "scripts\publish_sealed_snapshot.py" --live-clock --top20-bundle $candidate --snapshot-root $stageRoot }
        $stagedRun = Get-PrintedRunId $staged
        $carried = ($staged.Lines -join "`n") -match '"top20_state":\s*"CARRIED_FORWARD"'
        $ok = ($staged.Code -eq 0) -and $stagedRun -and $carried
        if ($ok) {
            $replayed = Invoke-LoggedNative { & $py "scripts\stage_sealed_replay.py" --run-dir (Join-Path $stageRoot $stagedRun) }
            $ok = $replayed.Code -eq 0
        }
        if ($ok) {
            $promoted = Invoke-LoggedNative { & $py "scripts\top20_carry_forward.py" promote --candidate $candidate }
            $ok = $promoted.Code -eq 0
        }
        $result = if ($ok) { 'ok' } else { 'fail' }
        Invoke-LoggedNative { & $py "scripts\top20_carry_forward.py" record --result $result --note "CANDIDATE_$($result.ToUpper())" } | Out-Null
        Add-Content -Path $log -Value "[$stamp] TOP20 CANDIDATE $($result.ToUpper())"
    } finally {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
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
    if ($CarryForwardTop20) {
        Add-Content -Path $log -Value "[$stamp] CARRY_FORWARD_TOP20 seal first"
        $sealed = Invoke-CarryForwardSeal
        if ($sealed.Code -ne 0) {
            Add-Content -Path $log -Value "[$stamp] GENERATE FAILED stage=$($sealed.Stage) exit=$($sealed.Code) (pointer untouched)"
            exit $(if ($sealed.Code) { $sealed.Code } else { 1 })
        }
        $runId = $sealed.RunId
    } else {
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
        $runId = Get-PrintedRunId $published
        if (-not $runId) {
            Add-Content -Path $log -Value "[$stamp] GENERATE FAILED run id not printed (pointer untouched)"
            exit 1
        }
    }
    $runDir = Join-Path $runsRoot $runId
    $synced = Invoke-LoggedNative { & $py "scripts\sync_sealed_snapshot_kv.py" --run-dir $runDir }
    if ($synced.Code -ne 0) {
        Write-Host "[$stamp] SYNC FAILED — pointer untouched, previous run still serving"
        Add-Content -Path $log -Value "[$stamp] SYNC FAILED exit=$($synced.Code) (pointer untouched)"
        exit $synced.Code
    }
    Add-Content -Path $log -Value "[$stamp] REFRESH OK run=$runId pointer last"
    Write-Host "[$stamp] sealed refresh OK"
    if ($CarryForwardTop20) {
        # Only after the pointer write: nothing below can delay or block this hour's seal, or fail the task.
        try {
            Remove-OldRuns
            $elapsed = [int]((Get-Date) - $runStarted).TotalSeconds
            if ($elapsed -lt $PostSealBudgetSeconds) {
                $budget = [Math]::Min($RefreshTimeoutSeconds, [Math]::Max(60, $PostSealBudgetSeconds - $elapsed))
                Invoke-BoundedScript 'DATA_REFRESH' (Join-Path $repo 'scripts\run_daily_data_refresh.ps1') @() $budget | Out-Null
            } else { Add-Content -Path $log -Value "[$(Get-Date -Format o)] POST_SEAL SKIPPED data refresh (elapsed ${elapsed}s)" }
            $elapsed = [int]((Get-Date) - $runStarted).TotalSeconds
            if ($elapsed -lt $PostSealBudgetSeconds) {
                $script:RefreshTimeoutSeconds = [Math]::Min($RefreshTimeoutSeconds, [Math]::Max(60, $PostSealBudgetSeconds - $elapsed))
                Invoke-Top20Refresh
            } else { Add-Content -Path $log -Value "[$(Get-Date -Format o)] POST_SEAL SKIPPED Top20 refresh (elapsed ${elapsed}s)" }
        } catch {
            Add-Content -Path $log -Value ("[$stamp] POST_SEAL REFRESH FAILED " + $_.Exception.GetType().Name + ": " + $_.Exception.Message)
            Invoke-LoggedNative { & $py "scripts\top20_carry_forward.py" record --result fail --note "POST_SEAL_EXCEPTION" } | Out-Null
        }
    }
} catch {
    # Anything unexpected is recorded with its type and message before the task reports failure.
    Add-Content -Path $log -Value ("[$stamp] REFRESH FAILED " + $_.Exception.GetType().Name + ": " + $_.Exception.Message)
    exit 1
} finally {
    Exit-V213OperationLock
}
exit 0
