# Task #23 PRODUCTION_FRESHNESS_REPAIR — 60-minute sealed-snapshot refresh.
#
# Default pipeline (strict fail-closed): pre-pointer failures leave the previous pointer alone;
# an attempted pointer write stays unconfirmed until readback. Post-readback local failure
# still fails the task but does NOT undo observed pointer confirmation.
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
#      failure records a 2 h backoff (data\cache\top20-lkg\refresh-state.json). Maintenance follows the publication
#      attempt even on failure, within the SAME budget; it never retries publication or changes its primary result.
#
# Scheduling: Windows Task Scheduler, every 60 minutes via
#   schtasks /Create /TN "InvestorIntelligenceSealedFreshness" /SC MINUTE /MO 60 /TR "<this file>"
# Kept well inside the V21_TOP20_MAX_AGE_SECONDS=7200 (2h) window: two consecutive
# failures still fit one window if the previous run was <=0h50m old.
param(
    [switch]$CarryForwardTop20,
    [int]$RefreshTimeoutSeconds = 1800,
    # Parameter names stay $TabbyUrl/$TabbyModel for compatibility with installed task actions; the defaults are
    # now ninfer (TabbyAPI :5000 removed 2026-09-27).
    [string]$TabbyUrl = 'http://127.0.0.1:8080',
    [string]$TabbyModel = 'Qwen3.8-27B',
    # Sealed runs directory (default state\v213-snapshots); an installed runtime uses data\v213-snapshots so its
    # attested payload never changes. Exported as II_SNAPSHOT_ROOT for the publisher and the company reports.
    [string]$SnapshotRoot = '',
    # Post-seal work may only start while the run is younger than this (the task limit is 1 h, the next trigger
    # would otherwise be skipped by the operation lock); each child is further capped by RefreshTimeoutSeconds.
    [int]$PostSealBudgetSeconds = 2100,
    # Sealed runs kept under -SnapshotRoot (hourly runs are not rollback targets; the pointer's run is always kept).
    [int]$KeepRuns = 48,
    # F02D explicit local guidance opt-in. Disabled defaults preserve F01.
    [switch]$GuidanceAutoUpdateEnabled,
    [switch]$GuidanceDirtyRebuildEnabled,
    [switch]$GuidanceMachinePublicationEnabled,
    [ValidateRange(1,600000)][long]$GuidanceBudgetMilliseconds = 600000
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$stamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
$runStarted = Get-Date
function Assert-PlainLocalRefreshPath([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:[\\/]' -or $Path -match '[\x00-\x1f]') { throw 'UNSAFE_ROOT' }
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'UNSAFE_ROOT' }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
try {
    $repo = [IO.Path]::GetFullPath($repo)
    $logDir = Join-Path $repo 'data\cache'
    $log = Join-Path $logDir 'sealed-refresh.log'
    $runsRoot = if ([string]::IsNullOrWhiteSpace($SnapshotRoot)) { Join-Path $repo 'state\v213-snapshots' }
                elseif ([IO.Path]::IsPathRooted($SnapshotRoot)) { $SnapshotRoot } else { Join-Path $repo $SnapshotRoot }
    $runsRoot = [IO.Path]::GetFullPath($runsRoot)
    foreach ($path in @($repo, $logDir, $log, $runsRoot, (Join-Path $repo 'scripts'))) { Assert-PlainLocalRefreshPath $path }
    foreach ($path in @($repo, $logDir, $runsRoot, (Join-Path $repo 'scripts'))) {
        if ((Test-Path -LiteralPath $path) -and -not (Test-Path -LiteralPath $path -PathType Container)) { throw 'ROOT_NOT_DIRECTORY' }
    }
    if ((Test-Path -LiteralPath $log) -and -not (Test-Path -LiteralPath $log -PathType Leaf)) { throw 'LOG_NOT_FILE' }
    if ($RefreshTimeoutSeconds -lt 1 -or $PostSealBudgetSeconds -lt 1 -or $KeepRuns -lt 0) { throw 'BUDGET_INVALID' }
    . (Join-Path $repo 'scripts\v213_operation_lock.ps1')
    if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
    if (-not [string]::IsNullOrWhiteSpace($SnapshotRoot)) { $env:II_SNAPSHOT_ROOT = $runsRoot }
} catch {
    Write-Host 'SEALED_REFRESH_FAILED phase=ROOT_OR_PREREQUISITE pointer_state=NOT_ATTEMPTED maintenance=NOT_ADMITTED'
    exit 1
}

function Invoke-LoggedNative([scriptblock]$Command) {
    # Run a native command with Continue so stderr lines are logged, not thrown; return its lines and exit code.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # PS5.1/7 native completion updates global:LASTEXITCODE. Clear and read
        # that exact scope; a local shadow would survive a child-scope invocation.
        # Dot-invoke the admitted single-native call in this frame, then capture
        # immediately (the string-conversion pipeline starts no native process).
        $global:LASTEXITCODE = $null
        $lines = @(. $Command 2>&1 | ForEach-Object { "$_" })
        $nativeCode = $global:LASTEXITCODE
        $code = if ($null -eq $nativeCode) { 1 } else { $nativeCode }
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($lines.Count -gt 0) {
        try { Add-Content -Path $log -Value $lines }
        catch { $script:OperationalLogFailed=$true; Write-Host 'LOCAL_LOG_WRITE_FAILED' }
    }
    $lines | ForEach-Object { Write-Host $_ }
    return [pscustomobject]@{ Code = $code; NativeExitCode = $nativeCode; Lines = $lines }
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

function Get-LocalModel {
    # Records the local model the business-profile translator will use. The translator finds it itself
    # (scripts/local_model_endpoint.py: -TabbyUrl, the launcher's saved address, known and listening loopback ports;
    # -TabbyModel exactly, else the same family or the only model served; operator 2026-09-26: the port and model
    # change). Without one the refresh runs label-only and the seal is never blocked.
    try {
        $raw = & $py "scripts\local_model_endpoint.py" --want $TabbyModel --base $TabbyUrl 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $found = ($raw | Select-Object -Last 1) | ConvertFrom-Json
        return $found
    } catch { return $null }
}

function Invoke-MachinePresealDaily {
    if (-not $GuidanceAutoUpdateEnabled -or -not $GuidanceDirtyRebuildEnabled) { throw 'MACHINE_INPUTS_UNAVAILABLE' }
    Import-Module (Join-Path $repo 'scripts\revenue_guidance_backend.psm1') -ErrorAction Stop
    $remaining=[long][Math]::Floor([Math]::Max(0, $PostSealBudgetSeconds * 1000L - ((Get-Date) - $runStarted).TotalMilliseconds))
    $left=[long][Math]::Min($GuidanceBudgetMilliseconds,[Math]::Min($RefreshTimeoutSeconds * 1000L,$remaining))
    if ($left -le 0) { throw 'MACHINE_EXPORT_UNAVAILABLE' }
    $contextRun=[Guid]::NewGuid().ToString('N')
    $dailyArgs=@('-NoProfile','-NonInteractive','-File',(Join-Path $repo 'scripts\run_daily_data_refresh.ps1'),
        '-GuidanceAutoUpdateEnabled','-GuidanceDirtyRebuildEnabled','-GuidanceMachinePublicationEnabled',
        '-GuidancePublicRunId',$contextRun,'-GuidanceBudgetMilliseconds',[string]$left)
    $script:presealDaily=Invoke-GuidanceObservedProcess -Label 'DATA_REFRESH' -Executable 'C:\Program Files\PowerShell\7\pwsh.exe' `
        -Arguments $dailyArgs -WorkingDirectory $repo -RemainingMilliseconds $left -MachineRunId $contextRun
    if (-not $script:presealDaily.Completed -or $script:presealDaily.ExitCode -ne 0 -or
        $null -eq $script:presealDaily.MachineBundle -or $script:presealDaily.MachineBundle.RunId -cne $contextRun) {
        if ($script:presealDaily.PSObject.Properties['MachineReason'] -and
            $script:presealDaily.MachineReason -cin @('MACHINE_INPUTS_UNAVAILABLE','MACHINE_EVIDENCE_LIMIT','MACHINE_EXPORT_UNAVAILABLE','GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE')) {
            throw $script:presealDaily.MachineReason
        }
        throw 'MACHINE_EXPORT_UNAVAILABLE' # no ordinary-body fallback / second producer
    }
    $public=$script:presealDaily.MachineBundle # independently captured channel result stays in THIS parent memory
    $script:MachinePublisherArgs=@('--guidance-machine','--guidance-public-token',$public.Token,
        '--guidance-report-sha256',$public.BodySha256,'--guidance-binding-sha256',$public.BindingSha256)
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
    if ($GuidanceMachinePublicationEnabled) {
        # Requested machine body+binding are mandatory in EVERY candidate: no
        # WITHOUT_LAZY/INSUFFICIENT tier may silently discard their unavailable state.
        $tiers=@([pscustomobject]@{Stage='MACHINE_CARRIED';Args=@('--top20-bundle','--identity-shards','--market-observations','--price-shards')+$script:MachinePublisherArgs})
    }
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
    # Local-only candidate -> staged replay -> LKG. NEVER sync or retry publication.
    $due = Invoke-LoggedNative { & $py 'scripts\top20_carry_forward.py' due }
    if ($due.Code -ne 0) { return [pscustomobject]@{Status='DUE_FAILED';ExitCode=$due.Code} }
    if (($due.Lines -join "`n") -notmatch '"due":\s*true') { return [pscustomobject]@{Status='NOT_DUE_OR_BACKOFF';ExitCode=0} }
    $stageRoot = Join-Path ([IO.Path]::GetTempPath()) ('ii-top20-candidate-' + [Guid]::NewGuid().ToString('N'))
    Assert-PlainLocalRefreshPath $stageRoot
    $localModel = Get-LocalModel
    if ($localModel) { Add-Content -Path $log -Value "[$stamp] LOCAL_MODEL_DETECTED $($localModel.model) at $($localModel.base_url) match=$($localModel.match)" }
    else { Add-Content -Path $log -Value "[$stamp] LOCAL_MODEL_UNAVAILABLE (translation label-only)" }
    $code = Invoke-BoundedScript 'TOP20_REFRESH' (Join-Path $repo 'run-v213-local.ps1') `
        @('-ProjectRoot', $repo, '-NoModelBridge', '-NoTunnel', '-NoSync', '-NoAutoActivation') $RefreshTimeoutSeconds
    if ($code -ne 0) {
        Invoke-LoggedNative { & $py 'scripts\top20_carry_forward.py' record --result fail --note "REFRESH_EXIT_$code" } | Out-Null
        return [pscustomobject]@{Status='REFRESH_FAILED';ExitCode=$code}
    }
    $candidate = Join-Path $repo 'data\cache\v213_activation_bundle_upload.json'
    try {
        $staged = Invoke-LoggedNative { & $py 'scripts\publish_sealed_snapshot.py' --live-clock --top20-bundle $candidate --snapshot-root $stageRoot }
        $stagedRun = Get-PrintedRunId $staged
        $ok = ($staged.Code -eq 0) -and $stagedRun -and (($staged.Lines -join "`n") -match '"top20_state":\s*"CARRIED_FORWARD"')
        $candidateCode = if ($staged.Code -ne 0) { $staged.Code } else { 1 }
        if ($ok) {
            $replayed = Invoke-LoggedNative { & $py 'scripts\stage_sealed_replay.py' --run-dir (Join-Path $stageRoot $stagedRun) }
            $ok = $replayed.Code -eq 0
            $candidateCode = $replayed.Code
        }
        if ($ok) {
            $promoted = Invoke-LoggedNative { & $py 'scripts\top20_carry_forward.py' promote --candidate $candidate }
            $ok = $promoted.Code -eq 0
            $candidateCode = $promoted.Code
        }
        $result = if ($ok) { 'ok' } else { 'fail' }
        $recorded = Invoke-LoggedNative { & $py 'scripts\top20_carry_forward.py' record --result $result --note "CANDIDATE_$($result.ToUpper())" }
        if ($recorded.Code -ne 0 -and $candidateCode -eq 0) { $candidateCode = $recorded.Code }
        return [pscustomobject]@{Status=$(if ($ok -and $recorded.Code -eq 0) {'LOCAL_LKG_PROMOTED'} else {'CANDIDATE_FAILED'});ExitCode=$candidateCode}
    } finally { Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue }
}

function Test-OutcomeInteger([object]$Value, [long]$Minimum, [long]$Maximum) {
    # Support the JSON integral CLR types on PS5.1/7 without accepting coercions.
    if ($Value -isnot [int32] -and $Value -isnot [int64]) { return $false }
    return ($Value -ge $Minimum -and $Value -le $Maximum)
}
function Read-SafeSyncOutcome([string]$Path, [string]$ExpectedRun) {
    Assert-PlainLocalRefreshPath $Path
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-Item -LiteralPath $Path).Length -gt 8192) { throw 'SYNC_OUTCOME_UNAVAILABLE' }
    $r = Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json
    if (-not (Test-OutcomeInteger $r.schema_version 1 1) -or $r.operation -cne 'SYNC' -or $r.run_id -cne $ExpectedRun -or
        $r.status -cnotin @('SUCCEEDED','FAILED') -or
        $r.pointer_state -cnotin @('NOT_ATTEMPTED','ATTEMPTED_UNCONFIRMED','READBACK_CONFIRMED') -or
        $r.error_category -cnotin @('NONE','AUTHENTICATION_ERROR','DAILY_KV_LIMIT','NETWORK_FAILURE','TRANSIENT_HTTP','TIMEOUT','UNKNOWN','CLI_UNAVAILABLE','CLI_LAUNCH_FAILED','READBACK_MISMATCH','INPUT_INVALID','LOCAL_IO_FAILURE','OUTCOME_WRITE_FAILED') -or
        $r.phase -cnotin @('INPUT','OBJECT_PUT','OBJECT_READBACK','POINTER_PUT','POINTER_READBACK','LOCAL_LEDGER','COMPLETE') -or
        -not (Test-OutcomeInteger $r.cli_attempts_total 0 2147483647) -or
        -not (Test-OutcomeInteger $r.last_cli_attempts 0 3) -or
        $r.last_cli_attempts -gt $r.cli_attempts_total -or
        -not (Test-OutcomeInteger $r.objects_uploaded 0 2147483647) -or
        -not (Test-OutcomeInteger $r.objects_reused 0 2147483647) -or
        -not (Test-OutcomeInteger $r.objects_verified 0 2147483647) -or
        ($null -ne $r.last_cli_exit_code -and -not (Test-OutcomeInteger $r.last_cli_exit_code -2147483648 4294967295))) { throw 'SYNC_OUTCOME_INVALID' }
    return $r
}

function Invoke-AdmittedLocalMaintenance([bool]$PublicationConfirmed) {
    $m = [ordered]@{data_status='NOT_RUN';data_exit=$null;top20_status='NOT_RUN';top20_exit=$null;prune_status='NOT_RUN'}
    # Never prune against a guessed current pointer after failed/unconfirmed sync.
    if ($PublicationConfirmed) {
        try { Remove-OldRuns; $m.prune_status='DONE' } catch { $m.prune_status='FAILED' }
    } else { $m.prune_status='SKIPPED_PUBLICATION_UNCONFIRMED' }
    $elapsed = [int]((Get-Date) - $runStarted).TotalSeconds
    if ($GuidanceMachinePublicationEnabled -and $null -ne $presealDaily) {
        $m.data_exit=$presealDaily.ExitCode
        $m.data_status=if (-not $presealDaily.Completed) {$presealDaily.Status} elseif ($presealDaily.ExitCode -eq 0) {'LOCAL_REFRESH_COMPLETED_PRESEAL'} else {'FAILED_EXIT_OBSERVED'}
    } elseif ($elapsed -lt $PostSealBudgetSeconds) {
        try {
            $budget = [Math]::Min($RefreshTimeoutSeconds, [Math]::Max(60, $PostSealBudgetSeconds - $elapsed))
            if ($GuidanceAutoUpdateEnabled) {
                Import-Module (Join-Path $repo 'scripts\revenue_guidance_backend.psm1') -ErrorAction Stop
                # Actual millisecond remainder: no old Max(60) extension of a
                # nearly exhausted run. WHOLE daily-child observation is bounded
                # independently of its private host and ordinary step slices.
                $remaining=[long][Math]::Floor([Math]::Max(0, $PostSealBudgetSeconds * 1000L - ((Get-Date) - $runStarted).TotalMilliseconds))
                $left=[long][Math]::Min($GuidanceBudgetMilliseconds,[Math]::Min($RefreshTimeoutSeconds * 1000L,$remaining))
                $dailyArgs=@('-NoProfile','-NonInteractive','-File',(Join-Path $repo 'scripts\run_daily_data_refresh.ps1'),
                    '-GuidanceAutoUpdateEnabled','-GuidanceBudgetMilliseconds',[string][Math]::Max(1L,$left))
                if ($GuidanceDirtyRebuildEnabled) { $dailyArgs += '-GuidanceDirtyRebuildEnabled' }
                $daily=Invoke-GuidanceObservedProcess -Label 'DATA_REFRESH' -Executable 'C:\Program Files\PowerShell\7\pwsh.exe' `
                    -Arguments $dailyArgs -WorkingDirectory $repo -RemainingMilliseconds $left
                $m.data_exit=$daily.ExitCode
                $m.data_status=if (-not $daily.Completed) {$daily.Status} elseif ($daily.ExitCode -eq 0) {'LOCAL_REFRESH_COMPLETED'} else {'FAILED_EXIT_OBSERVED'}
            } else {
                $dailyArgs = if ($GuidanceDirtyRebuildEnabled) { @('-GuidanceDirtyRebuildEnabled') } else { @() }
                $m.data_exit = Invoke-BoundedScript 'DATA_REFRESH' (Join-Path $repo 'scripts\run_daily_data_refresh.ps1') $dailyArgs $budget
                $m.data_status = if ($m.data_exit -eq 0) { 'LOCAL_REFRESH_COMPLETED' } else { 'FAILED' }
            }
        } catch { $m.data_status='LOCAL_EXCEPTION' }
    } else { $m.data_status='SKIPPED_BUDGET' }
    # Data failure does not silently starve the separate due/backoff-admitted Top20 path.
    $elapsed = [int]((Get-Date) - $runStarted).TotalSeconds
    if ($elapsed -lt $PostSealBudgetSeconds) {
        try {
            $script:RefreshTimeoutSeconds = [Math]::Min($RefreshTimeoutSeconds, [Math]::Max(60, $PostSealBudgetSeconds - $elapsed))
            $top = Invoke-Top20Refresh
            $m.top20_status = $top.Status
            $m.top20_exit = $top.ExitCode
        } catch {
            $m.top20_status='LOCAL_EXCEPTION'
            Invoke-LoggedNative { & $py 'scripts\top20_carry_forward.py' record --result fail --note 'LOCAL_MAINTENANCE_EXCEPTION' } | Out-Null
        }
    } else { $m.top20_status='SKIPPED_BUDGET' }
    return $m
}

try { Enter-V213OperationLock -Owner 'SealedRefresh' -TimeoutSeconds 0 | Out-Null }
catch {
    # No producer or CLI work without the owned operation lock.
    $busy = $_.Exception.Message -like 'V213_OPERATION_LOCK_BUSY;*'
    Write-Host ('SEALED_REFRESH_SKIPPED phase=LOCK maintenance=NOT_ADMITTED busy=' + $busy)
    if ($busy) { exit 0 } else { exit 1 }
}
$script:OperationalLogFailed = $false
$primaryCode = 0
$primaryPhase = 'GENERATE'
$pointerState = 'NOT_ATTEMPTED'
$primaryCategory = 'NONE'
$runId = ''
$maintenance = $null
$presealDaily = $null
$script:MachinePublisherArgs=@()
$maintenanceAdmitted = $true
$py = if ($env:PROJECT_PYTHON) { $env:PROJECT_PYTHON } else { 'python' }
try {
    try {
        Set-Location $repo
        if ($GuidanceMachinePublicationEnabled) {
            $primaryPhase='MACHINE_PRESEAL'
            Invoke-MachinePresealDaily # BOTH branches, before any seal: one same-owner producer/export
            $primaryPhase='GENERATE'
        }
        if ($CarryForwardTop20) {
            Add-Content -Path $log -Value "[$stamp] CARRY_FORWARD_TOP20 seal first"
            $sealed = Invoke-CarryForwardSeal
            if ($sealed.Code -ne 0) { $primaryCode=$sealed.Code; $primaryPhase=$sealed.Stage; $primaryCategory='GENERATION_OR_REPLAY_FAILED' }
            else { $runId=$sealed.RunId }
        } else {
            # Machine mode already observed ONE actual pre-seal daily above;
            # machine-off retains r3's original data-before-generation behavior.
            if (-not $GuidanceMachinePublicationEnabled) {
            try {
                if ($GuidanceAutoUpdateEnabled) {
                    Import-Module (Join-Path $repo 'scripts\revenue_guidance_backend.psm1') -ErrorAction Stop
                    $remaining=[long][Math]::Floor([Math]::Max(0, $PostSealBudgetSeconds * 1000L - ((Get-Date) - $runStarted).TotalMilliseconds))
                    $left=[long][Math]::Min($GuidanceBudgetMilliseconds,[Math]::Min($RefreshTimeoutSeconds * 1000L,$remaining))
                    $dailyArgs=@('-NoProfile','-NonInteractive','-File',(Join-Path $repo 'scripts\run_daily_data_refresh.ps1'),
                        '-GuidanceAutoUpdateEnabled','-GuidanceBudgetMilliseconds',[string][Math]::Max(1L,$left))
                    if ($GuidanceDirtyRebuildEnabled) { $dailyArgs += '-GuidanceDirtyRebuildEnabled' }
                    $presealDaily=Invoke-GuidanceObservedProcess -Label 'DATA_REFRESH' -Executable 'C:\Program Files\PowerShell\7\pwsh.exe' `
                        -Arguments $dailyArgs -WorkingDirectory $repo -RemainingMilliseconds $left
                    Add-Content -Path $log -Value "[$stamp] ROTATION status=$($presealDaily.Status) exit=$($presealDaily.ExitCode)"
                } else {
                    # Exact disabled native invocation/logging behavior retained.
                    $dailyArgs = @()
                    $dailyShell = 'powershell'
                    if ($GuidanceDirtyRebuildEnabled) { $dailyArgs += '-GuidanceDirtyRebuildEnabled' }
                    & $dailyShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `
                        (Join-Path $repo 'scripts\run_daily_data_refresh.ps1') @dailyArgs 2>&1 |
                        Tee-Object -FilePath $log -Append | Out-Null
                    Add-Content -Path $log -Value "[$stamp] ROTATION exit=$LASTEXITCODE"
                }
            } catch { Add-Content -Path $log -Value "[$stamp] ROTATION FAILED (publication continues)" }
            }
            $machineArgs=$script:MachinePublisherArgs
            $published = Invoke-LoggedNative { & $py 'scripts\publish_sealed_snapshot.py' --live-clock @machineArgs }
            if ($published.Code -ne 0) { $primaryCode=$published.Code; $primaryCategory='GENERATION_FAILED' }
            else {
                $runId=Get-PrintedRunId $published
                if (-not $runId) { $primaryCode=1; $primaryCategory='GENERATED_RUN_UNCONFIRMED' }
            }
        }
        if ($primaryCode -eq 0) {
            $primaryPhase = 'SYNC'
            $outcomePath = Join-Path $logDir ('sealed-sync-' + [guid]::NewGuid().ToString('N') + '.json')
            $runDir = Join-Path $runsRoot $runId
            try { Assert-PlainLocalRefreshPath $runDir }
            catch { $maintenanceAdmitted=$false; $primaryCategory='UNSAFE_RUN_ROOT'; throw }
            $pointerState='UNKNOWN'
            $synced = Invoke-LoggedNative { & $py 'scripts\sync_sealed_snapshot_kv.py' --run-dir $runDir --outcome-path $outcomePath }
            $primaryCode = $synced.Code
            try {
                $outcome = Read-SafeSyncOutcome $outcomePath $runId
                $pointerState=$outcome.pointer_state
                $primaryCategory=$outcome.error_category
                $primaryPhase=$outcome.phase
                if ($primaryCode -eq 0 -and ($outcome.status -cne 'SUCCEEDED' -or $pointerState -cne 'READBACK_CONFIRMED' -or $primaryCategory -cne 'NONE')) {
                    $primaryCode=1; $primaryCategory='SYNC_SUCCESS_UNPROVEN'
                } elseif ($primaryCode -ne 0 -and $primaryCategory -eq 'NONE') {
                    $primaryCategory='SYNC_PROCESS_FAILED'
                }
            } catch {
                $pointerState='UNKNOWN'; $primaryCategory='SYNC_OUTCOME_UNAVAILABLE'
                if ($primaryCode -eq 0) { $primaryCode=1 }
            }
        }
    } catch {
        if ($GuidanceMachinePublicationEnabled -and $_.Exception.Message -cin @('MACHINE_INPUTS_UNAVAILABLE','MACHINE_EVIDENCE_LIMIT','MACHINE_EXPORT_UNAVAILABLE','GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE')) {
            $primaryCode=2; $primaryCategory=$_.Exception.Message
        } elseif ($primaryCode -eq 0) { $primaryCode=1; if ($primaryCategory -eq 'NONE') { $primaryCategory='PRIMARY_EXCEPTION' } }
    }
    # Preserve the first primary failure. This finally-shaped continuation has
    # no extra publication, no sync, no LINE, and cannot turn that failure green.
    if ($CarryForwardTop20 -and $maintenanceAdmitted) {
        try { $maintenance=Invoke-AdmittedLocalMaintenance ($primaryCode -eq 0 -and $pointerState -eq 'READBACK_CONFIRMED') }
        catch { $maintenance=[ordered]@{data_status='UNKNOWN';top20_status='UNKNOWN';error_category='MAINTENANCE_EXCEPTION'} }
    } elseif (-not $maintenanceAdmitted) { $maintenance=[ordered]@{data_status='NOT_ADMITTED';top20_status='NOT_ADMITTED'} }
    $summary = [ordered]@{schema_version=1;primary_exit=$primaryCode;primary_phase=$primaryPhase;error_category=$primaryCategory;pointer_state=$pointerState;run_id=$runId;local_maintenance=$maintenance;secondary_log_failure=$script:OperationalLogFailed;publication_confirmed=($pointerState -eq 'READBACK_CONFIRMED');publication_operation_succeeded=($primaryCode -eq 0 -and $pointerState -eq 'READBACK_CONFIRMED')}
    if ($GuidanceAutoUpdateEnabled -and $null -ne $presealDaily) {
        $summary['daily_observation']=[ordered]@{status=$presealDaily.Status;attempted=$presealDaily.Attempted;
            completed=$presealDaily.Completed;exit=$presealDaily.ExitCode}
    }
    $line='SEALED_REFRESH_OUTCOME ' + ($summary | ConvertTo-Json -Depth 5 -Compress)
    Write-Host $line
    try { Add-Content -LiteralPath $log -Value $line -Encoding utf8 }
    catch { if ($primaryCode -eq 0) { $primaryCode=1 }; Write-Host 'SEALED_REFRESH_STATUS_WRITE_FAILED' }
} finally {
    try {
        if ($GuidanceAutoUpdateEnabled -and $null -ne (Get-Command Wait-GuidanceCustody -ErrorAction SilentlyContinue)) {
            Wait-GuidanceCustody # after publication/Top20/status continuation, before owner graph/lock unload
        }
    } finally { Exit-V213OperationLock }
}
exit $primaryCode
