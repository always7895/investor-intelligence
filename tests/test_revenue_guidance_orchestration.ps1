# tests/test_revenue_guidance_orchestration.ps1
#
# B2-ORCH-01 - six ordinary in-memory functional cases for the staged daily orchestration.
# Dot-sources the REAL scripts/run_daily_data_refresh.ps1 (definition-only path: no contact lookup,
# environment change, native launch, cwd change or exit) and invokes the REAL Invoke-DailyDataRefresh
# with fake RunStep/WithSecContact collaborators and an ordinary in-memory provider. Testing only the
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
        Operations      = New-Object System.Collections.Generic.List[string]
        Acknowledged    = New-Object System.Collections.Generic.List[string]
        ClosedCount     = 0
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
                    [pscustomobject]@{ Succeeded = $true; Reason = '' }
                }
                Update = {
                    $script:Store.Operations.Add('Update')
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
                    if (($script:Store.PendingRevision -eq $Revision) -and ($script:Store.InputRevision -eq $Revision)) {
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
                Close = { $script:Store.Operations.Add('Close'); $script:Store.ClosedCount++ }
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

# ---------------------------------------------------------------------------
Write-Output 'CASE 2: auto true, provider available, ordinary unchanged/clean refresh -> ordered check then updater, normal 3h ranking exactly once, NO_CHANGE'
$script:Store = New-B2Store -ChangedThisRun $false -NewPending $null
$script:Store.TraceSteps = $true
$provider2 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $false -GuidanceProvider $provider2
$sigs = (Get-StepSignatures $script:Rec) -join '; '
Assert-Equal $r.B2.Disposition 'NO_CHANGE' 'case2 disposition'
Assert-Equal $r.B2.ExitCode 0 'case2 B2 exit zero'
Assert-Equal $r.ExitCode 0 'case2 aggregate success'
Assert-True ($sigs -notlike '*guidance_release_check*') 'case2 no legacy checker step in enabled mode'
Assert-Equal ([regex]::Matches($sigs, [regex]::Escape($ranking3h)).Count) 1 'case2 normal 3h ranking exactly once'
Assert-True $r.B2.ReleaseCheckAttempted 'case2 release check attempted flag'
Assert-True $r.B2.UpdateAttempted 'case2 updater attempted flag'
Assert-True $r.B2.RankingAttempted 'case2 ranking attempted flag'
Assert-True (-not $r.B2.ForcedRebuildAttempted) 'case2 no forced rebuild flag'
Assert-True (-not $r.B2.RebuildCompleted) 'case2 rebuild not completed'
Assert-True ($r.B2.Changed -eq $false) 'case2 Changed=false known'
Assert-True ($null -eq $r.B2.PendingRevision) 'case2 no pending revision'
Assert-Equal ($script:Store.Operations -join ',') 'Acquire,ReadState,BeginRefresh,CheckRelease,Update,FinishRefresh,Ranking3h,Close' 'case2 ordered shared trace incl. ranking before close'

# ---------------------------------------------------------------------------
Write-Output 'CASE 3: ordinary changed inputs, rebuild false -> pending retained, no ranking/acknowledgement, independent trailing steps still run, CHANGED_REBUILD_PENDING'
$script:Store = New-B2Store -ChangedThisRun $true -NewPending 'input-v2'
$script:Store.TraceSteps = $true
$provider3 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $false -GuidanceProvider $provider3
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

# ---------------------------------------------------------------------------
Write-Output 'CASE 4: ordinary changed inputs, rebuild true -> check/update precede 0h ranking, acknowledgement of the same revision, REBUILD_COMPLETED'
$script:Store = New-B2Store -ChangedThisRun $true -NewPending 'input-v2'
$script:Store.TraceSteps = $true
$provider4 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $true -GuidanceProvider $provider4
$sigs = (Get-StepSignatures $script:Rec) -join '; '
Assert-Equal $r.B2.Disposition 'REBUILD_COMPLETED' 'case4 disposition'
Assert-Equal $r.B2.ExitCode 0 'case4 B2 exit zero'
Assert-Equal $r.ExitCode 0 'case4 aggregate success'
Assert-Equal ([regex]::Matches($sigs, [regex]::Escape($ranking0h)).Count) 1 'case4 forced 0h ranking exactly once'
Assert-Equal ([regex]::Matches($sigs, [regex]::Escape($ranking3h)).Count) 0 'case4 no ordinary 3h ranking'
Assert-True ($sigs -notlike '*guidance_release_check*') 'case4 no legacy checker step'
Assert-True $r.B2.RankingAttempted 'case4 ranking attempted flag'
Assert-True $r.B2.ForcedRebuildAttempted 'case4 forced rebuild attempted flag'
Assert-True $r.B2.RebuildCompleted 'case4 rebuild completed flag'
Assert-Equal $script:Store.Acknowledged.Count 1 'case4 exactly one acknowledgement'
Assert-Equal $script:Store.Acknowledged[0] 'input-v2' 'case4 acknowledged the exact pending revision'
Assert-True ($null -eq $script:Store.PendingRevision) 'case4 pending cleared after completed rebuild'
Assert-Equal $script:Store.InputRevision 'input-v2' 'case4 final cleared state keeps the new current input revision'
$ops = $script:Store.Operations -join ','
Assert-True (($ops.IndexOf('CheckRelease') -lt $ops.IndexOf('Update')) -and ($ops.IndexOf('Update') -lt $ops.IndexOf('Ranking0h')) -and ($ops.IndexOf('Ranking0h') -lt $ops.IndexOf('AcknowledgeRebuild'))) 'case4 shared-trace order: check/update -> ranking -> acknowledgement'

# ---------------------------------------------------------------------------
Write-Output 'CASE 5: previously pending state, this refresh unchanged, rebuild true -> retained pending forces 0h ranking and is acknowledged, never dropped'
$script:Store = New-B2Store -InputRevision 'input-v2' -InitialPending 'input-v2' -ChangedThisRun $false -NewPending $null
$script:Store.TraceSteps = $true
$provider5 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$r = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $true -GuidanceProvider $provider5
$sigs = (Get-StepSignatures $script:Rec) -join '; '
Assert-Equal $r.B2.Disposition 'REBUILD_COMPLETED' 'case5 disposition'
Assert-Equal $r.B2.ExitCode 0 'case5 B2 exit zero'
Assert-Equal $r.ExitCode 0 'case5 aggregate success'
Assert-Equal ([regex]::Matches($sigs, [regex]::Escape($ranking0h)).Count) 1 'case5 retained pending forces 0h ranking exactly once'
Assert-Equal $script:Store.Acknowledged.Count 1 'case5 exactly one acknowledgement'
Assert-Equal $script:Store.Acknowledged[0] 'input-v2' 'case5 acknowledged the retained revision'
Assert-True ($null -eq $script:Store.PendingRevision) 'case5 pending cleared, not dropped by Changed=false'
Assert-Equal $script:Store.InputRevision 'input-v2' 'case5 current input revision remains the acknowledged revision'
Assert-True $r.B2.RebuildCompleted 'case5 rebuild completed flag'
$ops = $script:Store.Operations -join ','
Assert-True (($ops.IndexOf('Update') -lt $ops.IndexOf('Ranking0h')) -and ($ops.IndexOf('Ranking0h') -lt $ops.IndexOf('AcknowledgeRebuild'))) 'case5 shared-trace order: update -> ranking -> acknowledgement'

# ---------------------------------------------------------------------------
Write-Output 'CASE 6: repeated clean no-change invocations with the same in-memory provider -> stable command order/result, no forced rebuild or invented pending state, per-invocation isolation'
$script:Store = New-B2Store -ChangedThisRun $false -NewPending $null
$script:Store.TraceSteps = $true
$provider6 = New-B2InMemoryProvider
$script:Rec = New-Object System.Collections.Generic.List[object]
$ra = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $false -GuidanceProvider $provider6
$sigsA = (Get-StepSignatures $script:Rec) -join '; '
$script:Rec = New-Object System.Collections.Generic.List[object]
$rb = Invoke-DailyDataRefresh -RunStep (New-FakeRunStep) -WithSecContact (New-FakeWithSecContact) `
    -GuidanceAutoUpdateEnabled $true -GuidanceDirtyRebuildEnabled $false -GuidanceProvider $provider6
$sigsB = (Get-StepSignatures $script:Rec) -join '; '
Assert-Equal $ra.B2.Disposition 'NO_CHANGE' 'case6 first invocation NO_CHANGE'
Assert-Equal $rb.B2.Disposition 'NO_CHANGE' 'case6 second invocation NO_CHANGE'
Assert-Equal $ra.ExitCode 0 'case6 first aggregate success'
Assert-Equal $rb.ExitCode 0 'case6 second aggregate success'
Assert-True ($sigsA -eq $sigsB) 'case6 stable command order across invocations'
Assert-Equal ([regex]::Matches($sigsB, [regex]::Escape($ranking3h)).Count) 1 'case6 normal 3h ranking once in second invocation'
Assert-True (-not $ra.B2.ForcedRebuildAttempted) 'case6 first no forced rebuild flag'
Assert-True (-not $rb.B2.ForcedRebuildAttempted) 'case6 second no forced rebuild flag'
Assert-True ($null -eq $script:Store.PendingRevision) 'case6 no invented pending state after repeated clean runs'
Assert-Equal $script:Store.Acknowledged.Count 0 'case6 no acknowledgements'
Assert-Equal $script:Store.ClosedCount 2 'case6 each invocation closed its own session'
Assert-True ([object]::ReferenceEquals($ra.B2, $rb.B2) -eq $false) 'case6 per-invocation result isolation'

Write-Output 'B2 ORCHESTRATION: 6/6 ordinary functional cases passed'
exit 0
