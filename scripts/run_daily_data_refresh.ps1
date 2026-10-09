# Post-seal data refresh (operator rules 2026-09-25/26: data change with the market, nothing hand-written, refreshed
# near real time). Each step keeps its own cadence (--if-older-than-hours) and its last good output on failure; the
# sealed publisher applies its own age limits.
#
# SEC steps (rotation, company reports, Leopold 13F, bottleneck v3) need the declared SEC Fair Access contact, which is
# decrypted from the user's DPAPI file into this process only, never printed or written, and cleared afterwards.
# Steps that need no SEC contact (Chinese names, identity shards, Serenity signals, quotes/options) always run. Every step logs one
# STEP line with its exit code; native stderr never aborts the remaining steps (Windows PowerShell 5.1 would turn a
# warning line into a terminating error under Stop). The script exits non-zero when any step failed.
#
# B2-ORCH-01: the daily body is Invoke-DailyDataRefresh. Dot-sourcing this script defines functions only: no contact
# lookup, environment changes, native launches, cwd changes or exit. The normal entry below constructs the current
# native/contact adapters, invokes the same function with disabled-by-default feature switches, and
# exits with its returned ExitCode. The revenue-guidance pair (release check 0.9h + bottleneck v3 3h) is owned by
# scripts/revenue_guidance_orchestration.psm1 when GuidanceAutoUpdateEnabled is set; both feature options default to
# $false and the default GuidanceProvider is $null. Explicit normal-entry opt-in builds the protected
# private-pipe backend/P1 provider and same-owner ranking adapter; prerequisite absence is nonzero.
[CmdletBinding()]
param(
    [double]$IfOlderThanHours = 20,
    [switch]$GuidanceAutoUpdateEnabled,
    [switch]$GuidanceDirtyRebuildEnabled,
    [switch]$GuidanceMachinePublicationEnabled,
    [string]$GuidancePublicRunId=$null,
    [ValidateRange(1,600000)][long]$GuidanceBudgetMilliseconds = 600000
)

# Definition-time setup only (safe to dot-source): pure path computations and module load. No contact lookup,
# no environment/session changes, no native launches, no cwd changes, no exit.
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = if ($env:PROJECT_PYTHON) { $env:PROJECT_PYTHON } else { 'python' }
Import-Module (Join-Path (Join-Path $repo 'scripts') 'revenue_guidance_orchestration.psm1')

function Invoke-DailyDataRefresh {
    [CmdletBinding()]
    param(
        [double]$IfOlderThanHours = 20,
        [bool]$GuidanceAutoUpdateEnabled = $false,
        [bool]$GuidanceDirtyRebuildEnabled = $false,
        [bool]$GuidanceMachinePublicationEnabled = $false,
        # { [string]$Name, [string[]]$Arguments } -> { ExitCode, Lines }. The real adapter launches the existing
        # Python executable and captures the native exit immediately; the fake records exact arguments in memory.
        [scriptblock]$RunStep,
        # SAME acquired protected backend owner; not the ordinary Python CLI.
        [scriptblock]$RunGuidanceRanking,
        # Invokes Work(ContactAvailable) exactly once. The real adapter preserves the install-state/DPAPI lookup, the
        # temporary SEC_CONTACT_EMAIL and its cleanup; the fake invokes the work with true/false touching no path,
        # credential or environment.
        [scriptblock]$WithSecContact,
        # Narrowly documented provider object (Acquire scriptblock member) or $null (the shipped default, unavailable).
        [AllowNull()][object]$GuidanceProvider = $null
    )

    if ($GuidanceMachinePublicationEnabled -and (-not $GuidanceAutoUpdateEnabled -or -not $GuidanceDirtyRebuildEnabled)) {
        throw 'MACHINE_INPUTS_UNAVAILABLE' # explicit prerequisites; never implicitly turn them on
    }
    $failed = New-Object System.Collections.Generic.List[string]

    # The daily function's own step-logging adapter: emits the step's output lines and the existing STEP line,
    # records failures. Step output is returned inside the result object, never contaminating the function result.
    function Invoke-DailyStep([string]$Name, [string[]]$Arguments) {
        $started = Get-Date
        $r = & $RunStep $Name $Arguments
        if ($null -ne $r.Lines) { $r.Lines | ForEach-Object { Write-Host $_ } }
        Write-Host ("STEP {0} exit={1} seconds={2}" -f $Name, $r.ExitCode, [int]((Get-Date) - $started).TotalSeconds)
        if ($r.ExitCode -ne 0) { $failed.Add($Name) }
        if ($GuidanceAutoUpdateEnabled -and $null -ne $r.PSObject.Properties['Status']) {
            Write-Host ("STEP_OBSERVATION {0} status={1} attempted={2} completed={3}" -f $Name,$r.Status,$r.Attempted,$r.Completed)
        }
        return $r
    }

    # B2 disposition defaults to DISABLED: disabled mode executes the legacy pair exactly once at the old location
    # and neither acquires a provider nor examines automatic state.
    $b2 = New-GuidanceOrchestrationResult -Disposition 'DISABLED' -Reason 'AUTO_MODE_DISABLED' -ExitCode 0

    Push-Location $repo
    try {
        # Steps without the SEC contact. Chinese names (weekly, sourced, never translated) feed the identity shards.
        Invoke-DailyStep 'zh_names' @('scripts\build_zh_names.py', '--if-older-than-hours', '168') | Out-Null
        Invoke-DailyStep 'identity_shards' @('scripts\build_identity_shards.py', '--if-older-than-hours', "$IfOlderThanHours") | Out-Null
        Invoke-DailyStep 'serenity_signals' @('scripts\serenity_signals.py', '--refresh', '--if-older-than-hours', '6') | Out-Null
        # The Work scriptblock has its own scope: its B2 result comes back via output; a $null output keeps the
        # DISABLED default.
        $b2Scope = & $WithSecContact {
            param([bool]$ContactAvailable)
            $b2Local = $null
            if ($ContactAvailable) {
                # Company reports use the rotation just written; a failure keeps the last good file.
                Invoke-DailyStep 'industry_rotation' @('scripts\industry_rotation.py', '--refresh', '--if-older-than-hours', "$IfOlderThanHours") | Out-Null
                Invoke-DailyStep 'company_reports' @('scripts\company_deep_report.py', '--refresh', '--if-older-than-hours', "$IfOlderThanHours") | Out-Null
                Invoke-DailyStep 'leopold_13f' @('scripts\leopold_positions.py', '--if-older-than-hours', '24') | Out-Null
                # Revenue-guidance pair (B2-ORCH-01). Disabled mode: the legacy release-check 0.9h and ranking 3h steps
                # run exactly once, in the old location (receipts captured before the v3 build, ORDERS-V3-01). Enabled
                # mode owns this pair exclusively: no duplicate checker/ranking after the module returns, a missing
                # provider is an explicit blocked (never a silent legacy fallback), other independent daily steps
                # still proceed.
                if ($GuidanceAutoUpdateEnabled) {
                    $b2Local = Invoke-GuidanceOrchestration -GuidanceProvider $GuidanceProvider `
                        -RunStep {
                            param([string]$StepName, [string[]]$StepArguments)
                            Invoke-DailyStep $StepName $StepArguments
                        } `
                        -RunGuidanceRanking $RunGuidanceRanking `
                        -DirtyRebuildEnabled $GuidanceDirtyRebuildEnabled
                }
                else {
                    # Disabled mode: the legacy release-check 0.9h and ranking 3h steps run exactly once, in the old
                    # location. The B2 result stays the DISABLED default (neither a provider is acquired nor any
                    # automatic state examined).
                    Invoke-DailyStep 'guidance_release_check' @('scripts\revenue_guidance_release_check.py', '--if-older-than-hours', '0.9') | Out-Null
                    Invoke-DailyStep 'bottleneck_v3' @('scripts\bottleneck_top20_v3.py', '--if-older-than-hours', '3') | Out-Null
                }
            }
            else {
                # Reference object shared with the real contact adapter (set by the adapter, read here after it ran).
                $secIssue = $null
                $secExceptionType = ''
                if ($null -ne $secContactState) {
                    $secIssue = $secContactState.Issue
                    $secExceptionType = [string]$secContactState.ExceptionType
                }
                if ($secIssue -eq 'decode_failure') {
                    Write-Host ('STEP sec_contact exit=1 ' + $secExceptionType)
                    $failed.Add('sec_contact')
                }
                else {
                    Write-Host 'STEP sec_steps SKIPPED (install-state or SEC contact not configured)'
                    $failed.Add('sec_contact_missing')
                }
                # B2 requested without the SEC contact: explicit blocked, never labelled complete.
                if ($GuidanceAutoUpdateEnabled) {
                    $b2Local = New-GuidanceOrchestrationResult -Disposition 'BLOCKED_PREREQUISITE_UNAVAILABLE' `
                        -Reason 'SEC_CONTACT_UNAVAILABLE' -ExitCode 1
                }
            }
            return $b2Local
        }
        if ($null -ne $b2Scope) { $b2 = $b2Scope }
        # Delayed quotes and covered-call suggestions for the LINE lookup and options queries, every hour.
        # Delayed daily prices for every listing (official bulk feeds per market) for the stock lookup, every 3 hours.
        Invoke-DailyStep 'price_shards' @('scripts\build_price_shards.py', '--if-older-than-hours', '2.9') | Out-Null
        Invoke-DailyStep 'market_observations' @('scripts\build_market_quotes_options.py', '--if-older-than-hours', '0.9') | Out-Null
    }
    finally {
        Pop-Location
    }

    # Aggregate exit: any failed step, or a nonzero B2 disposition for requested B2, fails the refresh.
    $exitCode = 0
    if ($failed.Count -gt 0) { $exitCode = 1 }
    if ($null -ne $b2 -and $b2.ExitCode -ne 0) { $exitCode = 1 }
    # One bounded B2 disposition line, only for requested B2; no revision, input payload, path, exception or
    # contact data in that log.
    if ($GuidanceAutoUpdateEnabled) {
        Write-Host ("B2 GUIDANCE_ORCHESTRATION disposition={0} reason={1} exit={2}" -f $b2.Disposition, $b2.Reason, $b2.ExitCode)
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        FailedSteps = [string[]]@($failed)
        B2 = $b2
    }
}

# Normal entry: skipped when this script is dot-sourced (tests dot-source it and invoke Invoke-DailyDataRefresh
# with injected fakes). The normal run calls the same function with explicit switches (both default false),
# never opens the backend while disabled, and exits with its returned ExitCode.
#
# Dot-source discrimination by actual invocation mode: a dot-sourced invocation carries InvocationName '.'
# (the dot-source operator); direct execution (-File, &, Start-Process) carries a non-'.' InvocationName. This is
# the invocation mode itself, not a text heuristic on invocation lines.
$dotSourced = ($MyInvocation.InvocationName -eq '.')
if ($dotSourced) {
    # Definition only.
}
else {
    if ($GuidanceMachinePublicationEnabled -and (-not $GuidanceAutoUpdateEnabled -or -not $GuidanceDirtyRebuildEnabled -or
        $GuidancePublicRunId -cnotmatch '^[0-9a-f]{32}$')) {
        Write-Host 'MACHINE_INPUTS_UNAVAILABLE'
        exit 2
    }
    $bundle=$null
    $guidanceBackendLoaded=$false
    $guidanceClock=$null
    if ($GuidanceAutoUpdateEnabled) { $guidanceClock=[Diagnostics.Stopwatch]::StartNew() }
    try {
    $ErrorActionPreference = 'Continue'
    $env:PYTHONUTF8 = '1'
    $secContactState = [pscustomobject]@{ Issue = $null; ExceptionType = '' }
    $ordinaryStepsLeft=[pscustomobject]@{Count=8} # enabled normal-entry independent steps, no duplicate legacy pair
    $realRunStep = {
        param([string]$Name, [string[]]$Arguments)
        if ($GuidanceAutoUpdateEnabled) {
            $left=[Math]::Max(0L,$GuidanceBudgetMilliseconds - $guidanceClock.ElapsedMilliseconds)
            # Meaningful fair observation slices leave time for both guidance
            # and later independent steps. Expiry is NOT permission to kill a
            # possibly native-owning child or claim an unobserved completion.
            $slice=[long][Math]::Min(60000L,[Math]::Floor($left / ($ordinaryStepsLeft.Count + 2)))
            $ordinaryStepsLeft.Count=[Math]::Max(0,$ordinaryStepsLeft.Count - 1)
            if (-not $guidanceBackendLoaded) {
                return [pscustomobject]@{ExitCode=125;Lines=@();Status='NOT_ATTEMPTED_PREREQUISITE';Attempted=$false;Completed=$false}
            }
            return Invoke-GuidanceObservedProcess -Label ('DAILY_' + $Name) -Executable $python -Arguments $Arguments `
                -WorkingDirectory $repo -RemainingMilliseconds $slice
        }
        # Real adapter: the existing Python executable; the native exit is captured immediately, output lines
        # are returned (not emitted), so they cannot contaminate the result object.
        $lines = & $python @Arguments 2>&1 | ForEach-Object { [string]$_ }
        $code = $LASTEXITCODE
        [pscustomobject]@{ ExitCode = $code; Lines = $lines }
    }
    $realWithSecContact = {
        param([scriptblock]$Work)
        # Existing install-state/DPAPI lookup, temporary SEC_CONTACT_EMAIL and cleanup, preserved unchanged.
        $contactPath = $null
        $statePath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\install-state.json'
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            try {
                $state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
                $candidate = Join-Path ([string]$state.user_config_root) 'sec-contact.local.txt'
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $contactPath = $candidate }
            } catch { $contactPath = $null }
        }
        $pointer = [IntPtr]::Zero
        $previous = $env:SEC_CONTACT_EMAIL
        $available = $false
        if ($contactPath) {
            try {
                $protected = ConvertTo-SecureString -String (Get-Content -LiteralPath $contactPath -Raw -Encoding utf8).Trim()
                $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($protected)
                $env:SEC_CONTACT_EMAIL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
                $available = $true
            } catch {
                $secContactState.Issue = 'decode_failure'
                $secContactState.ExceptionType = $_.Exception.GetType().Name
                $available = $false
            }
        }
        try {
            & $Work $available
        }
        finally {
            if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
            $env:SEC_CONTACT_EMAIL = $previous
        }
    }
    $realProvider = $null
    $realRanking = $null
    if ($GuidanceAutoUpdateEnabled) {
        try {
            # Explicit opt-in only. No $PROJECT_PYTHON/fallback interpreter: the
            # backend independently selects/holds protected machine CPython.
            Import-Module (Join-Path $repo 'scripts\revenue_guidance_backend.psm1') -ErrorAction Stop
            $guidanceBackendLoaded=$true
            Import-Module (Join-Path $repo 'scripts\revenue_guidance_provider.psm1') -ErrorAction Stop
            $left=[Math]::Max(0L,$GuidanceBudgetMilliseconds - $guidanceClock.ElapsedMilliseconds)
            if ($left -le 0) { throw 'GUIDANCE_REFUSED_BEFORE_DISPATCH' }
            $bundle = New-GuidanceBackend -Enabled $true -RemainingMilliseconds $left `
                -MachineEnabled ([bool]$GuidanceMachinePublicationEnabled) -PublicRunId $GuidancePublicRunId
            $realProvider = New-GuidanceProvider -BackendFactory $bundle.BackendFactory
            $realRanking = {
                param([string]$Mode,[object]$Revision)
                $ranked = & $bundle.RunGuidanceRanking $Mode $Revision
                if ($ranked.AcquisitionProgress -eq $true) {
                    Write-Host 'GUIDANCE_ACQUISITION_PENDING' # known progress, nonzero, no witness/ACK
                }
                return $ranked
            }.GetNewClosure()
        } catch {
            # Requested automatic mode stays explicitly blocked; no legacy
            # ranking/checker or arbitrary interpreter fallback, no raw error.
            Write-Host 'GUIDANCE_BACKEND_PREREQUISITE_UNAVAILABLE'
        }
    }
    $result = Invoke-DailyDataRefresh -IfOlderThanHours $IfOlderThanHours `
        -GuidanceAutoUpdateEnabled ([bool]$GuidanceAutoUpdateEnabled) `
        -GuidanceDirtyRebuildEnabled ([bool]$GuidanceDirtyRebuildEnabled) `
        -GuidanceMachinePublicationEnabled ([bool]$GuidanceMachinePublicationEnabled) `
        -GuidanceProvider $realProvider -RunGuidanceRanking $realRanking `
        -RunStep $realRunStep -WithSecContact $realWithSecContact
    if ($GuidanceMachinePublicationEnabled) {
        try {
            if ($result.ExitCode -ne 0 -or $null -eq $bundle) { throw 'MACHINE_EXPORT_UNAVAILABLE' }
            $public = & $bundle.GetPublicBundle # original normal workflow ACK, observed settled Close/host exit
            if ($public.RunId -cne $GuidancePublicRunId) { throw 'MACHINE_EXPORT_UNAVAILABLE' }
            # ONE bounded context-bound PUBLIC metadata frame. Expected digests
            # come from original private export/readback, not a writable manifest.
            Write-Host ('GUIDANCE_MACHINE_RESULT_V1|'+$GuidancePublicRunId+'|'+$public.Token+'|'+$public.BodySha256+'|'+$public.BindingSha256)
        } catch {
            $reason='MACHINE_EXPORT_UNAVAILABLE'
            if ($null -eq $bundle) { $reason='GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE' }
            else {
                $fixed=& $bundle.GetMachineFailure
                if ($fixed -cin @('MACHINE_INPUTS_UNAVAILABLE','MACHINE_EVIDENCE_LIMIT','MACHINE_EXPORT_UNAVAILABLE','GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE')) { $reason=$fixed }
            }
            Write-Host ('GUIDANCE_MACHINE_ERROR_V1|'+$GuidancePublicRunId+'|'+$reason)
            $result.ExitCode=2 # requested machine failure never becomes ordinary successful refresh
        }
    }
    if ($result.ExitCode -ne 0) {
        Write-Host ('DATA_REFRESH FAILED steps=' + ($result.FailedSteps -join ','))
    }
    else {
        Write-Host 'DATA_REFRESH OK'
    }
    }
    finally {
        if ($GuidanceAutoUpdateEnabled -and $guidanceBackendLoaded) {
            Wait-GuidanceCustody # actual executable lifetime, including exception/exit paths
        }
    }
    exit $result.ExitCode
}
