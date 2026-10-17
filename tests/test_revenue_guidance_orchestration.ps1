# tests/test_revenue_guidance_orchestration.ps1
#
# B2-ORCH-01 / F02D - in-memory caller cases; no native/platform certification.
# Dot-sources the REAL scripts/run_daily_data_refresh.ps1 (definition-only path: no contact lookup,
# environment change, native launch, cwd change or exit) and invokes the REAL Invoke-DailyDataRefresh
# with separate fake RunStep/RunGuidanceRanking/WithSecContact collaborators and an in-memory provider. Testing only the
# module would be insufficient: the public daily function and its step-logging adapter are exercised.
# No real Python steps, no contact/native adapters, no network, no credentials, no state files, no
# existing test imports. Self-contained assertions, no Pester. Exits nonzero on the first assertion
# failure. These are orchestration examples, not safety tests.

$ErrorActionPreference = 'Continue'
$W = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path (Join-Path $W 'scripts') 'run_daily_data_refresh.ps1')

# --- shared in-memory state (script-scope so injected scriptblocks resolve it from any call chain) ---
$script:Store = $null
$script:Rec = $null

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        Write-Output ("ASSERT_FAIL: {0}" -f $Message)
        exit 1
    }
}

function Assert-Equal([object]$Actual, [object]$Expected, [string]$Message) {
    if ($Actual -ne $Expected) {
        Write-Output ("ASSERT_FAIL: {0} (expected [{1}], got [{2}])" -f $Message, $Expected, $Actual)
        exit 1
    }
}

function New-B2Store {
    # Coherent ordinary revision state: InputRevision is the current effective input identity; a changed
    # input (e.g. v1 -> v2) is carried as the pending revision until rebuilt and acknowledged.
    param([string]$InputRevision = 'input-v1', [object]$InitialPending = $null, [bool]$ChangedThisRun = $false, [object]$NewPending = $null)
    [pscustomobject]@{
        InputRevision   = $InputRevision
        PendingRevision = $InitialPending
        StateRequired   = $true
        ChangedThisRun  = $ChangedThisRun
        NewPending      = $NewPending
        TraceSteps      = $false
        RankingCompleted = $true
        AckCompleted   = $true
        RankingCalls   = New-Object System.Collections.Generic.List[object]
        Operations      = New-Object System.Collections.Generic.List[string]
        Acknowledged    = New-Object System.Collections.Generic.List[string]
        ClosedCount     = 0
        # Fault injection (CASE 9-11): CheckMode/UpdateMode ok|fail|null|throw; CloseThrows throws after counting.
        CheckMode       = 'ok'
        UpdateMode      = 'ok'
        CloseThrows     = $false
    }
}

function New-B2InMemoryProvider {
    # Ordinary contract modeling only: a fresh invocation-local session per Acquire; its availability is
    # not a certification bit. No durable-reconcile claim is made with this in-memory state. State objects
    # carry the agreed fields { InputRevision, PendingRevision, StateRequired }.
    [pscustomobject]@{
        Acquire = {
            $script:Store.Operations.Add('Acquire')
            $session = [pscustomobject]@{
                ReadState = {
                    $script:Store.Operations.Add('ReadState')
                    [pscustomobject]@{
                        InputRevision   = $script:Store.InputRevision
                        PendingRevision = $script:Store.PendingRevision
                        StateRequired   = $script:Store.StateRequired
                    }
                }
                BeginRefresh = { $script:Store.Operations.Add('BeginRefresh') }
                CheckRelease = {
                    $script:Store.Operations.Add('CheckRelease')
                    if ($script:Store.CheckMode -eq 'throw') { throw 'RAW_PROVIDER_TEXT_CHECK' }
                    if ($script:Store.CheckMode -eq 'null') { return $null }
                    if ($script:Store.CheckMode -eq 'fail') { return [pscustomobject]@{ Succeeded = $false; Reason = 'RAW_PROVIDER_TEXT_CHECK' } }
                    [pscustomobject]@{ Succeeded = $true; Reason = '' }
                }
                Update = {
                    $script:Store.Operations.Add('Update')
                    if ($script:Store.UpdateMode -eq 'throw') { throw 'RAW_PROVIDER_TEXT_UPDATE' }
                    if ($script:Store.UpdateMode -eq 'null') { return $null }
                    if ($script:Store.UpdateMode -eq 'fail') { return [pscustomobject]@{ Succeeded = $false; Reason = 'RAW_PROVIDER_TEXT_UPDATE' } }
                    [pscustomobject]@{ Succeeded = $true; Reason = '' }
                }
                FinishRefresh = {
                    $script:Store.Operations.Add('FinishRefresh')
                    # A successful changed input makes the new revision both the current input and the pending
                    # revision; a no-change cycle retains prior pending work.
                    if ($null -ne $script:Store.NewPending) {
                        $script:Store.InputRevision = $script:Store.NewPending
                        $script:Store.PendingRevision = $script:Store.NewPending
                    }
                    [pscustomobject]@{
                        Changed = $script:Store.ChangedThisRun
                        State   = [pscustomobject]@{
                            InputRevision   = $script:Store.InputRevision
                            PendingRevision = $script:Store.PendingRevision
                            StateRequired   = $script:Store.StateRequired
                        }
                    }
                }
                AcknowledgeRebuild = {
                    param([object]$Revision)
                    $script:Store.Operations.Add('AcknowledgeRebuild')
                    $script:Store.Acknowledged.Add([string]$Revision)
                    # Clears only the revision that is both the current input and the pending work, and only then.
                    if ($script:Store.AckCompleted -and ($script:Store.PendingRevision -eq $Revision) -and ($script:Store.InputRevision -eq $Revision)) {
                        $script:Store.PendingRevision = $null
                        [pscustomobject]@{
                            Completed = $true
                            State = [pscustomobject]@{
                                InputRevision   = $script:Store.InputRevision
                                PendingRevision = $null
                                StateRequired   = $script:Store.StateRequired
                            }
                        }
                    }
                    else {
                        [pscustomobject]@{
                            Completed = $false
                            State = [pscustomobject]@{
                                InputRevision   = $script:Store.InputRevision
                                PendingRevision = $script:Store.PendingRevision
                                StateRequired   = $script:Store.StateRequired
                            }
                        }
                    }
                }
                Close = {
                    $script:Store.Operations.Add('Close')
                    $script:Store.ClosedCount++
                    if ($script:Store.CloseThrows) { throw 'RAW_PROVIDER_TEXT_CLOSE' }
                }
            }
            [pscustomobject]@{ Available = $true; Session = $session }
        }
    }
}

function New-FakeRunStep {
    # Records exact name/arguments; returns an ordinary in-memory success. When tracing is enabled for the
    # current case, ranking invocations join the shared provider Operations trace, so the same six cases
    # can assert the check/update -> ranking -> acknowledgement order.
    {
        param([string]$Name, [string[]]$Arguments)
        $script:Rec.Add([pscustomobject]@{ Name = $Name; Arguments = @($Arguments) })
        if ($Name -eq 'bottleneck_v3' -and $script:Store.TraceSteps) {
            $script:Store.Operations.Add('Ranking' + [string]$Arguments[-1] + 'h')
        }
        [pscustomobject]@{ ExitCode = 0; Lines = @() }
    }
}

function New-FakeRunGuidanceRanking {
    # Independent SAME-owner collaborator: never delegated to generic RunStep or a CLI.
    {
        param([string]$Mode, [object]$Revision)
        $completed = $script:Store.RankingCompleted
        $script:Store.RankingCalls.Add([pscustomobject]@{
            Mode = $Mode; Revision = $Revision; Completed = $completed
        })
        $script:Store.Operations.Add('Ranking:' + $Mode)
        [pscustomobject]@{ ExitCode = 0; Completed = $completed; Revision = $Revision }
    }
}

function Assert-RankingCall {
    param([int]$Index, [string]$Mode, [object]$Revision)
    $call = $script:Store.RankingCalls[$Index]
    Assert-Equal $call.Mode $Mode 'same-owner ranking mode'
    Assert-True ([object]::Equals($call.Revision, $Revision)) 'same-owner exact revision'
    Assert-True ($call.Completed -is [bool] -and $call.Completed) 'same-owner completed trace'
}

function New-FakeWithSecContact {
    # Invokes the work with true once, touching no path, credential or environment.
    {
        param([scriptblock]$Work)
        & $Work $true
    }
}

function Get-StepSignatures {
    param([object]$Rec)
    $sigs = @()
    foreach ($s in $Rec) { $sigs += ($s.Name + '|' + ($s.Arguments -join ' ')) }
    $sigs
}

function Invoke-B2FaultDaily {
    # Runs the REAL daily function with auto mode on and captures the host (information) stream, so the bounded
    # B2 line can be checked for raw provider text. Returns the single daily result object.
    param([bool]$Dirty, [object]$Provider)
    $all = @(Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
        -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $Dirty -GuidanceProvider $Provider `
        -RunGuidanceRanking (New-FakeRunGuidanceRanking) 6>&1)
    $script:HostText = (@($all | Where-Object { $_ -is [System.Management.Automation.InformationRecord] } |
        ForEach-Object { [string]$_.MessageData }) -join "`n")
    $results = @($all | Where-Object { $_ -isnot [System.Management.Automation.InformationRecord] })
    Assert-Equal $results.Count 1 'fault harness: exactly one daily result object'
    $results[0]
}

$ranking3h = 'bottleneck_v3|scripts\bottleneck_top20_v3.py --if-older-than-hours 3'
$ranking0h = 'bottleneck_v3|scripts\bottleneck_top20_v3.py --if-older-than-hours 0'

# ---------------------------------------------------------------------------
Write-Output 'CASE 1: both options omitted vs both explicitly false -> identical daily steps/args, aggregate success, provider unused, B2 DISABLED'
$script:Store = New-B2Store
$provider1 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$r1 = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact)
$sigs1 = (Get-StepSignatures $script:Rec) -join '; '
$script:Rec = New-Object System.Collections.Generic.List[object]
$r2 = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $false -GuidanceDirtyRebuildEnabled $false -GuidanceProvider $provider1
$sigs2 = (Get-StepSignatures $script:Rec) -join '; '
$expectedSteps = @(
    'zh_names|scripts\build_zh_names.py --if-older-than-hours 168',
    'identity_shards|scripts\build_identity_shards.py --if-older-than-hours 20',
    'serenity_signals|scripts\serenity_signals.py --refresh --if-older-than-hours 6',
    'revenue_consensus|scripts\revenue_consensus_quarterly.py --if-older-than-hours 6',
    'industry_rotation|scripts\industry_rotation.py --refresh --if-older-than-hours 20',
    'company_reports|scripts\company_deep_report.py --refresh --if-older-than-hours 20',
    'leopold_13f|scripts\leopold_positions.py --if-older-than-hours 24',
    'guidance_release_check|scripts\revenue_guidance_release_check.py --if-older-than-hours 0.9',
    'bottleneck_v3|scripts\bottleneck_top20_v3.py --if-older-than-hours 3',
    'price_shards|scripts\build_price_shards.py --if-older-than-hours 2.9',
    'market_observations|scripts\build_market_quotes_options.py --if-older-than-hours 0.9'
)
Assert-True ($sigs1 -eq ($expectedSteps -join '; ')) 'case1 omitted-options exact existing step list/arguments'
Assert-True ($sigs2 -eq ($expectedSteps -join '; ')) 'case1 explicit-false exact existing step list/arguments'
Assert-Equal $r1.ExitCode 0 'case1 omitted-options aggregate success'
Assert-Equal $r2.ExitCode 0 'case1 explicit-false aggregate success'
Assert-Equal $r1.B2.Disposition 'DISABLED' 'case1 omitted-options B2 disposition'
Assert-Equal $r2.B2.Disposition 'DISABLED' 'case1 explicit-false B2 disposition'
Assert-Equal $script:Store.Operations.Count 0 'case1 provider never acquired in disabled mode'
Assert-Equal $script:Store.RankingCalls.Count 0 'case1 same-owner ranking unused'

# ---------------------------------------------------------------------------
Write-Output 'CASE 2: auto true, provider available, ordinary unchanged/clean refresh -> ordered check then updater, normal 3h ranking exactly once, NO_CHANGE'
$script:Store = New-B2Store -ChangedThisRun $false -NewPending $null
$script:Store.TraceSteps = $true
$provider2 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $false -GuidanceProvider $provider2 -RunGuidanceRanking (New-FakeRunGuidanceRanking)
$sigs = (Get-StepSignatures $script:Rec) -join '; '
Assert-Equal $r.B2.Disposition 'NO_CHANGE' 'case2 disposition'
Assert-Equal $r.B2.ExitCode 0 'case2 B2 exit zero'
Assert-Equal $r.ExitCode 0 'case2 aggregate success'
Assert-True ($sigs -notlike '*guidance_release_check*') 'case2 no legacy checker step in enabled mode'
Assert-True ($sigs -notlike '*bottleneck_v3*') 'case2 no generic ranking fallback'
Assert-Equal $script:Store.RankingCalls.Count 1 'case2 same-owner ranking exactly once'
Assert-RankingCall 0 'Cadence' $null
Assert-True $r.B2.ReleaseCheckAttempted 'case2 release check attempted flag'
Assert-True $r.B2.UpdateAttempted 'case2 updater attempted flag'
Assert-True $r.B2.RankingAttempted 'case2 ranking attempted flag'
Assert-True (-not $r.B2.ForcedRebuildAttempted) 'case2 no forced rebuild flag'
Assert-True (-not $r.B2.RebuildCompleted) 'case2 rebuild not completed'
Assert-True ($r.B2.Changed -eq $false) 'case2 Changed=false known'
Assert-True ($null -eq $r.B2.PendingRevision) 'case2 no pending revision'
Assert-Equal ($script:Store.Operations -join ',') 'Acquire,ReadState,BeginRefresh,CheckRelease,Update,FinishRefresh,Ranking:Cadence,Close' 'case2 ordered shared trace incl. ranking before close'

# ---------------------------------------------------------------------------
Write-Output 'CASE 3: ordinary changed inputs, rebuild false -> pending retained, no ranking/acknowledgement, independent trailing steps still run, CHANGED_REBUILD_PENDING'
$script:Store = New-B2Store -ChangedThisRun $true -NewPending 'input-v2'
$script:Store.TraceSteps = $true
$provider3 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $false -GuidanceProvider $provider3 -RunGuidanceRanking (New-FakeRunGuidanceRanking)
$sigs = (Get-StepSignatures $script:Rec) -join '; '
Assert-Equal $r.B2.Disposition 'CHANGED_REBUILD_PENDING' 'case3 disposition'
Assert-Equal $r.B2.ExitCode 1 'case3 B2 nonzero'
Assert-Equal $r.ExitCode 1 'case3 aggregate nonzero'
Assert-True ($r.B2.PendingRevision -eq 'input-v2') 'case3 pending revision retained in result'
Assert-True (-not $r.B2.RankingAttempted) 'case3 no ranking attempted'
Assert-True (-not $r.B2.ForcedRebuildAttempted) 'case3 no forced rebuild attempted'
Assert-True (-not $r.B2.RebuildCompleted) 'case3 rebuild lifecycle not complete'
Assert-True ($sigs -notlike '*bottleneck_v3*') 'case3 no ranking invocation at all'
Assert-True ($sigs -like '*price_shards*' -and $sigs -like '*market_observations*') 'case3 independent trailing daily steps still run'
Assert-True (($sigs.IndexOf('price_shards') -gt 0) -and ($sigs.IndexOf('leopold_13f') -lt $sigs.IndexOf('price_shards'))) 'case3 trailing steps keep their order'
Assert-Equal $script:Store.PendingRevision 'input-v2' 'case3 store pending retained (no acknowledgement issued)'
Assert-Equal $script:Store.InputRevision 'input-v2' 'case3 successful changed transition updates the current input to the same pending revision'
Assert-Equal $script:Store.Acknowledged.Count 0 'case3 no acknowledgement'
Assert-Equal $script:Store.RankingCalls.Count 0 'case3 no same-owner ranking'

# ---------------------------------------------------------------------------
Write-Output 'CASE 4: ordinary changed inputs, rebuild true -> check/update precede 0h ranking, acknowledgement of the same revision, REBUILD_COMPLETED'
$script:Store = New-B2Store -ChangedThisRun $true -NewPending 'input-v2'
$script:Store.TraceSteps = $true
$provider4 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $true -GuidanceProvider $provider4 -RunGuidanceRanking (New-FakeRunGuidanceRanking)
$sigs = (Get-StepSignatures $script:Rec) -join '; '
Assert-Equal $r.B2.Disposition 'REBUILD_COMPLETED' 'case4 disposition'
Assert-Equal $r.B2.ExitCode 0 'case4 B2 exit zero'
Assert-Equal $r.ExitCode 0 'case4 aggregate success'
Assert-True ($sigs -notlike '*bottleneck_v3*') 'case4 no generic ranking fallback'
Assert-Equal $script:Store.RankingCalls.Count 1 'case4 same-owner ranking exactly once'
Assert-RankingCall 0 'Dirty' 'input-v2'
Assert-True ($sigs -notlike '*guidance_release_check*') 'case4 no legacy checker step'
Assert-True $r.B2.RankingAttempted 'case4 ranking attempted flag'
Assert-True $r.B2.ForcedRebuildAttempted 'case4 forced rebuild attempted flag'
Assert-True $r.B2.RebuildCompleted 'case4 rebuild completed flag'
Assert-Equal $script:Store.Acknowledged.Count 1 'case4 exactly one acknowledgement'
Assert-Equal $script:Store.Acknowledged[0] 'input-v2' 'case4 acknowledged the exact pending revision'
Assert-True ($null -eq $script:Store.PendingRevision) 'case4 pending cleared after completed rebuild'
Assert-Equal $script:Store.InputRevision 'input-v2' 'case4 final cleared state keeps the new current input revision'
$ops = $script:Store.Operations -join ','
Assert-True (($ops.IndexOf('CheckRelease') -lt $ops.IndexOf('Update')) -and ($ops.IndexOf('Update') -lt $ops.IndexOf('Ranking:Dirty')) -and ($ops.IndexOf('Ranking:Dirty') -lt $ops.IndexOf('AcknowledgeRebuild'))) 'case4 shared-trace order: check/update -> ranking -> acknowledgement'

# ---------------------------------------------------------------------------
Write-Output 'CASE 5: previously pending state, this refresh unchanged, rebuild true -> retained pending forces 0h ranking and is acknowledged, never dropped'
$script:Store = New-B2Store -InputRevision 'input-v2' -InitialPending 'input-v2' -ChangedThisRun $false -NewPending $null
$script:Store.TraceSteps = $true
$provider5 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $true -GuidanceProvider $provider5 -RunGuidanceRanking (New-FakeRunGuidanceRanking)
$sigs = (Get-StepSignatures $script:Rec) -join '; '
Assert-Equal $r.B2.Disposition 'REBUILD_COMPLETED' 'case5 disposition'
Assert-Equal $r.B2.ExitCode 0 'case5 B2 exit zero'
Assert-Equal $r.ExitCode 0 'case5 aggregate success'
Assert-True ($sigs -notlike '*bottleneck_v3*') 'case5 no generic ranking fallback'
Assert-Equal $script:Store.RankingCalls.Count 1 'case5 same-owner ranking exactly once'
Assert-RankingCall 0 'Dirty' 'input-v2'
Assert-Equal $script:Store.Acknowledged.Count 1 'case5 exactly one acknowledgement'
Assert-Equal $script:Store.Acknowledged[0] 'input-v2' 'case5 acknowledged the retained revision'
Assert-True ($null -eq $script:Store.PendingRevision) 'case5 pending cleared, not dropped by Changed=false'
Assert-Equal $script:Store.InputRevision 'input-v2' 'case5 current input revision remains the acknowledged revision'
Assert-True $r.B2.RebuildCompleted 'case5 rebuild completed flag'
$ops = $script:Store.Operations -join ','
Assert-True (($ops.IndexOf('Update') -lt $ops.IndexOf('Ranking:Dirty')) -and ($ops.IndexOf('Ranking:Dirty') -lt $ops.IndexOf('AcknowledgeRebuild'))) 'case5 shared-trace order: update -> ranking -> acknowledgement'

# ---------------------------------------------------------------------------
Write-Output 'CASE 6: repeated clean no-change invocations with the same in-memory provider -> stable command order/result, no forced rebuild or invented pending state, per-invocation isolation'
$script:Store = New-B2Store -ChangedThisRun $false -NewPending $null
$script:Store.TraceSteps = $true
$provider6 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$ra = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $false -GuidanceProvider $provider6 -RunGuidanceRanking (New-FakeRunGuidanceRanking)
$sigsA = (Get-StepSignatures $script:Rec) -join '; '
$script:Rec = New-Object System.Collections.Generic.List[object]
$rb = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $false -GuidanceProvider $provider6 -RunGuidanceRanking (New-FakeRunGuidanceRanking)
$sigsB = (Get-StepSignatures $script:Rec) -join '; '
Assert-Equal $ra.B2.Disposition 'NO_CHANGE' 'case6 first invocation NO_CHANGE'
Assert-Equal $rb.B2.Disposition 'NO_CHANGE' 'case6 second invocation NO_CHANGE'
Assert-Equal $ra.ExitCode 0 'case6 first aggregate success'
Assert-Equal $rb.ExitCode 0 'case6 second aggregate success'
Assert-True ($sigsA -eq $sigsB) 'case6 stable command order across invocations'
Assert-True ($sigsB -notlike '*bottleneck_v3*') 'case6 no generic ranking fallback'
Assert-Equal $script:Store.RankingCalls.Count 2 'case6 one same-owner ranking per invocation'
Assert-RankingCall 0 'Cadence' $null
Assert-RankingCall 1 'Cadence' $null
Assert-True (-not $ra.B2.ForcedRebuildAttempted) 'case6 first no forced rebuild flag'
Assert-True (-not $rb.B2.ForcedRebuildAttempted) 'case6 second no forced rebuild flag'
Assert-True ($null -eq $script:Store.PendingRevision) 'case6 no invented pending state after repeated clean runs'
Assert-Equal $script:Store.Acknowledged.Count 0 'case6 no acknowledgements'
Assert-Equal $script:Store.ClosedCount 2 'case6 each invocation closed its own session'
Assert-True ([object]::ReferenceEquals($ra.B2, $rb.B2) -eq $false) 'case6 per-invocation result isolation'

# No Completed=true means no success, even when ExitCode=0. Dirty work must survive
# this failed invocation and can only be acknowledged by a later completed same-owner call.
Write-Output 'CASE 7: incomplete ranking refuses success; pending survives and recovers'
foreach ($dirty in @($false, $true)) {
    foreach ($completion in @($false, $null, 'true')) {
        $script:Store = if ($dirty) {
            New-B2Store -InputRevision 'input-v2' -InitialPending 'input-v2'
        } else { New-B2Store }
        $script:Store.RankingCompleted = $completion
        $script:Rec = New-Object System.Collections.Generic.List[object]
        $provider7 = New-B2InMemoryProvider
        $r = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
            -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $dirty -GuidanceProvider $provider7 `
            -RunGuidanceRanking (New-FakeRunGuidanceRanking)
        Assert-Equal $r.ExitCode 1 'case7 exit-0 ranking without boolean completion must fail'
        Assert-Equal $r.B2.Disposition 'FAILED' 'case7 not a success'
        $reason = if ($dirty) { 'FAILED_AT_REBUILD_RANKING' } else { 'FAILED_AT_RANKING' }
        Assert-Equal $r.B2.Reason $reason 'case7 bounded ranking failure'
        Assert-True (-not $r.B2.RebuildCompleted) 'case7 no false rebuild completion'
        Assert-Equal $script:Store.RankingCalls.Count 1 'case7 fake must actually run'
        Assert-Equal $script:Store.Acknowledged.Count 0 'case7 failed ranking never acknowledged'
        Assert-Equal $script:Store.ClosedCount 1 'case7 failed invocation closes'
        Assert-True (((Get-StepSignatures $script:Rec) -join ';') -notlike '*bottleneck_v3*') 'case7 no CLI fallback'
        if ($dirty) {
            Assert-Equal $r.B2.PendingRevision 'input-v2' 'case7 result retains pending'
            Assert-Equal $script:Store.PendingRevision 'input-v2' 'case7 failure preserves recoverable state'
            $script:Store.RankingCompleted = $true
            $recovered = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
                -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $true -GuidanceProvider $provider7 `
                -RunGuidanceRanking (New-FakeRunGuidanceRanking)
            Assert-Equal $recovered.B2.Disposition 'REBUILD_COMPLETED' 'case7 later completed invocation recovers'
            Assert-RankingCall 1 'Dirty' 'input-v2'
            Assert-Equal $script:Store.Acknowledged.Count 1 'case7 exactly one eventual acknowledgement'
            Assert-True ($null -eq $script:Store.PendingRevision) 'case7 clear only after successful recovery'
        }
    }
}

Write-Output 'CASE 8: incomplete acknowledgement cannot complete recovery or drop pending'
$script:Store = New-B2Store -InputRevision 'input-v2' -InitialPending 'input-v2'
$script:Store.AckCompleted = $false
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $true -GuidanceProvider (New-B2InMemoryProvider) `
    -RunGuidanceRanking (New-FakeRunGuidanceRanking)
Assert-Equal $r.ExitCode 1 'case8 recovery not complete'
Assert-Equal $r.B2.Disposition 'CHANGED_REBUILD_PENDING' 'case8 incomplete ack not success'
Assert-True (-not $r.B2.RebuildCompleted) 'case8 completed ranking is not completed recovery'
Assert-Equal $r.B2.PendingRevision 'input-v2' 'case8 result retains pending'
Assert-Equal $script:Store.PendingRevision 'input-v2' 'case8 store retains pending'
Assert-Equal $script:Store.ClosedCount 1 'case8 incomplete recovery closes session'
Assert-Equal $script:Store.Acknowledged.Count 1 'case8 actual acknowledgement attempted'
Assert-RankingCall 0 'Dirty' 'input-v2'

# CASE 9/10: a failed, null or throwing release check / updater stops ONLY the B2 work. Header rules: no
# Update (case 9), no FinishRefresh, ranking or acknowledgement, independent daily steps still run, pending
# retained, bounded reason token only, truthful attempt flags.
foreach ($faultCase in @(
        [pscustomobject]@{ Number = 9;  Stage = 'check';  Reason = 'FAILED_AT_RELEASE_CHECK'; Update = $false },
        [pscustomobject]@{ Number = 10; Stage = 'update'; Reason = 'FAILED_AT_UPDATER';       Update = $true })) {
    $n = $faultCase.Number
    Write-Output ("CASE {0}: {1} fails (false result / null result / throw), dirty rebuild off and on -> bounded {2}, later B2 work skipped, independent steps run, pending retained" -f $n, $faultCase.Stage, $faultCase.Reason)
    foreach ($dirty in @($false, $true)) {
        foreach ($mode in @('fail', 'null', 'throw')) {
            $label = "case$n/$mode/dirty=$dirty"
            $script:Store = New-B2Store -InputRevision 'input-v2' -InitialPending 'input-v2' -ChangedThisRun $true -NewPending 'input-v3'
            $script:Store.TraceSteps = $true
            if ($faultCase.Stage -eq 'check') { $script:Store.CheckMode = $mode } else { $script:Store.UpdateMode = $mode }
            $script:Rec = New-Object System.Collections.Generic.List[object]
            $r = Invoke-B2FaultDaily -Dirty $dirty -Provider (New-B2InMemoryProvider)
            $sigs = (Get-StepSignatures $script:Rec) -join '; '
            Assert-Equal $r.ExitCode 1 "$label aggregate nonzero"
            Assert-Equal $r.B2.Disposition 'FAILED' "$label disposition"
            Assert-Equal $r.B2.Reason $faultCase.Reason "$label bounded stage reason"
            Assert-Equal $r.B2.ExitCode 1 "$label B2 nonzero"
            Assert-True $r.B2.ReleaseCheckAttempted "$label release check attempted flag"
            Assert-True ($r.B2.UpdateAttempted -eq $faultCase.Update) "$label update attempted flag is truthful"
            Assert-True (-not $r.B2.RankingAttempted) "$label no ranking attempted"
            Assert-True (-not $r.B2.ForcedRebuildAttempted) "$label no forced rebuild attempted"
            Assert-True (-not $r.B2.RebuildCompleted) "$label no rebuild completion"
            Assert-True ($null -eq $r.B2.Changed) "$label Changed stays unknown (FinishRefresh never ran)"
            $expectedOps = if ($faultCase.Update) { 'Acquire,ReadState,BeginRefresh,CheckRelease,Update,Close' } else { 'Acquire,ReadState,BeginRefresh,CheckRelease,Close' }
            Assert-Equal ($script:Store.Operations -join ',') $expectedOps "$label provider trace stops at the failed stage and closes"
            $expectedAttempts = if ($faultCase.Update) { 'release_check,updater' } else { 'release_check' }
            Assert-Equal (@($r.B2.AttemptedSteps) -join ',') $expectedAttempts "$label attempted steps are truthful"
            Assert-Equal $script:Store.RankingCalls.Count 0 "$label no same-owner ranking"
            Assert-Equal $script:Store.Acknowledged.Count 0 "$label no acknowledgement"
            Assert-Equal $script:Store.ClosedCount 1 "$label session closed once"
            Assert-Equal $r.B2.PendingRevision 'input-v2' "$label result retains pending"
            Assert-Equal $script:Store.PendingRevision 'input-v2' "$label store retains pending"
            Assert-Equal $script:Store.InputRevision 'input-v2' "$label no FinishRefresh transition to the new input"
            Assert-True ($sigs -notlike '*bottleneck_v3*') "$label no generic ranking fallback"
            Assert-True ($sigs -notlike '*guidance_release_check*') "$label no legacy checker fallback"
            Assert-True ($sigs -like '*price_shards*' -and $sigs -like '*market_observations*' -and $sigs -like '*leopold_13f*') "$label independent daily steps still run"
            Assert-True ($sigs.IndexOf('leopold_13f') -lt $sigs.IndexOf('price_shards')) "$label independent steps keep their order"
            Assert-True ($r.B2.Reason -notlike '*RAW_PROVIDER_TEXT*') "$label result reason carries no raw provider text"
            Assert-True ($script:HostText -like ('*B2 GUIDANCE_ORCHESTRATION disposition=FAILED reason=' + $faultCase.Reason + ' exit=1*')) "$label bounded B2 log line"
            Assert-True ($script:HostText -notlike '*RAW_PROVIDER_TEXT*') "$label raw provider/exception text never surfaced in the log"
        }
    }
}

Write-Output 'CASE 11: Close throws after an otherwise successful run -> FAILED_AT_CLOSE, truthful flags, pending kept or cleared exactly as the provider state says'
# 11a: clean unchanged refresh (would be NO_CHANGE) with a failing Close.
$script:Store = New-B2Store -ChangedThisRun $false -NewPending $null
$script:Store.TraceSteps = $true
$script:Store.CloseThrows = $true
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-B2FaultDaily -Dirty $false -Provider (New-B2InMemoryProvider)
Assert-Equal $r.ExitCode 1 'case11a aggregate nonzero'
Assert-Equal $r.B2.Disposition 'FAILED' 'case11a close failure is not NO_CHANGE'
Assert-Equal $r.B2.Reason 'FAILED_AT_CLOSE' 'case11a bounded close reason'
Assert-Equal $r.B2.ExitCode 1 'case11a B2 nonzero'
Assert-True ($r.B2.ReleaseCheckAttempted -and $r.B2.UpdateAttempted -and $r.B2.RankingAttempted) 'case11a completed attempt flags stay truthful'
Assert-True (-not $r.B2.ForcedRebuildAttempted -and -not $r.B2.RebuildCompleted) 'case11a no rebuild claimed'
Assert-True ($r.B2.Changed -eq $false) 'case11a known Changed=false retained'
Assert-True ($null -eq $r.B2.PendingRevision) 'case11a no invented pending state'
Assert-Equal $script:Store.RankingCalls.Count 1 'case11a ranking ran before close'
Assert-Equal $script:Store.ClosedCount 1 'case11a close attempted exactly once, never retried'
Assert-Equal ($script:Store.Operations -join ',') 'Acquire,ReadState,BeginRefresh,CheckRelease,Update,FinishRefresh,Ranking:Cadence,Close' 'case11a full trace then the single close'
Assert-True ($script:HostText -like '*B2 GUIDANCE_ORCHESTRATION disposition=FAILED reason=FAILED_AT_CLOSE exit=1*') 'case11a bounded B2 log line'
Assert-True ($script:HostText -notlike '*RAW_PROVIDER_TEXT*') 'case11a raw close text never surfaced'

# 11b: changed input, rebuild off (would be CHANGED_REBUILD_PENDING): pending is retained, no ranking or ack.
$script:Store = New-B2Store -ChangedThisRun $true -NewPending 'input-v2'
$script:Store.TraceSteps = $true
$script:Store.CloseThrows = $true
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-B2FaultDaily -Dirty $false -Provider (New-B2InMemoryProvider)
Assert-Equal $r.ExitCode 1 'case11b aggregate nonzero'
Assert-Equal $r.B2.Disposition 'FAILED' 'case11b disposition'
Assert-Equal $r.B2.Reason 'FAILED_AT_CLOSE' 'case11b bounded close reason'
Assert-Equal $r.B2.PendingRevision 'input-v2' 'case11b result retains pending'
Assert-Equal $script:Store.PendingRevision 'input-v2' 'case11b store retains pending'
Assert-True ($r.B2.ReleaseCheckAttempted -and $r.B2.UpdateAttempted -and -not $r.B2.RankingAttempted) 'case11b attempt flags stay truthful (no ranking)'
Assert-Equal $script:Store.RankingCalls.Count 0 'case11b no ranking'
Assert-Equal $script:Store.Acknowledged.Count 0 'case11b no acknowledgement'
Assert-Equal $script:Store.ClosedCount 1 'case11b close attempted exactly once'

# 11c: completed rebuild (ranking + acknowledgement done) then a failing Close: never reported as success.
$script:Store = New-B2Store -InputRevision 'input-v2' -InitialPending 'input-v2'
$script:Store.TraceSteps = $true
$script:Store.CloseThrows = $true
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-B2FaultDaily -Dirty $true -Provider (New-B2InMemoryProvider)
Assert-Equal $r.ExitCode 1 'case11c aggregate nonzero'
Assert-Equal $r.B2.Disposition 'FAILED' 'case11c close failure overrides REBUILD_COMPLETED'
Assert-Equal $r.B2.Reason 'FAILED_AT_CLOSE' 'case11c bounded close reason'
Assert-Equal $r.B2.ExitCode 1 'case11c B2 nonzero'
Assert-True ($r.B2.RankingAttempted -and $r.B2.ForcedRebuildAttempted) 'case11c ranking and forced rebuild flags stay truthful'
Assert-Equal $script:Store.Acknowledged.Count 1 'case11c the acknowledgement that actually happened is recorded once'
Assert-Equal $script:Store.ClosedCount 1 'case11c close attempted exactly once'
Assert-True ($r.B2.RebuildCompleted -eq ($null -eq $script:Store.PendingRevision)) 'case11c result flag matches the provider state (pending cleared only by the real acknowledgement)'
Assert-True ($script:HostText -notlike '*RAW_PROVIDER_TEXT*') 'case11c raw close text never surfaced'

Write-Output 'B2 ORCHESTRATION: 11/11 caller case groups passed (synthetic collaborators only)'
exit 0
