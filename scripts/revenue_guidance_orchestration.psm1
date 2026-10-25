# revenue_guidance_orchestration.psm1
#
# B2-ORCH-01 - staged daily orchestration for the revenue-guidance pair (release check + bottleneck v3
# ranking) inside scripts/run_daily_data_refresh.ps1. Default remains disabled/unavailable.
# F02D explicit normal entry wires the real private-pipe protected backend, original P1
# provider and SAME-owner RunGuidanceRanking. This module never performs native I/O,
# registry lookup, replay, marker probing or filesystem authority itself. In-memory
# injection examples are NOT certification or a genuine model witness.
#
# Provider interface (narrowly documented): a provider/session object with named scriptblock members.
#   $provider.Acquire() -> { Available=$false, Reason } | { Available=$true, Session }
#   $session.ReadState()              -> { InputRevision, PendingRevision, StateRequired }. Revisions are
#                                         opaque input identities, not paths. Null pending means clean.
#                                         StateRequired is provider-reported, never inferred from missing files.
#   $session.BeginRefresh()          -> establishes the provider-owned recoverable refresh intent before
#                                         checker/updater work.
#   $session.CheckRelease()         -> { Succeeded, Reason } for the capability-backed release check over
#                                         effective discovery inputs.
#   $session.Update()               -> { Succeeded, Reason } for the updater using that check. An issuer
#                                         WAITING/BLOCKED can be a successfully completed updater operation,
#                                         not an automatic availability grant.
#   $session.FinishRefresh()        -> { Changed, State }, reconciling actual combined effective-input /
#                                         receipt identities and retaining any prior pending work. A new
#                                         changed input produces its pending revision; a no-change cycle can
#                                         retire its own provisional intent only if it began clean and inputs
#                                         remained the same. State carries the agreed fields
#                                         { InputRevision, PendingRevision, StateRequired }.
#   $session.AcknowledgeRebuild(r)  -> { Completed, State }; clears only the pending revision actually
#                                         rebuilt, and only when it is still the current input revision.
#                                         State carries the agreed fields.
#   $session.Close()                -> releases the invocation session in finally. Never means commit,
#                                         acknowledgement or success.
#
# Ordering: Acquire -> ReadState -> BeginRefresh -> CheckRelease -> Update -> FinishRefresh -> optional
# ranking -> optional AcknowledgeRebuild -> Close. Check/update failure stops subsequent B2 work, never
# ordinary independent daily steps. No acknowledgement on checker/updater/ranking failure, interruption or
# a withheld rebuild; pending work is retained. A future provider must durably reconcile an interrupted
# BeginRefresh and own state-required persistence, identity comparison, locking and atomicity; those
# guarantees are not claimed with a hashtable mock.
#
# Truthful finalization rules:
#   - The known pending state from ReadState is retained in the result even when a later stage fails.
#   - A missing or unknown FinishRefresh outcome (no result, no explicit Changed, no agreed State) is
#     FAILED_AT_FINISH_REFRESH, never NO_CHANGE; a clean state is never inferred.
#   - REBUILD_COMPLETED requires the acknowledgement to report completion AND a final state that is not
#     still pending; otherwise the disposition stays CHANGED_REBUILD_PENDING.
#   - A Close failure after an apparent success is not swallowed: the final result is finalized as
#     FAILED_AT_CLOSE with truthful attempt flags and retained pending work.
#   - Bounded reason tokens only: the raw provider Reason text is never surfaced; an unavailable acquire
#     maps to the fixed token GUIDANCE_PROVIDER_UNAVAILABLE.
#
# Dispositions (result.Disposition):
#   DISABLED                         - auto flag false; the daily caller ran the legacy pair (module unused).
#   BLOCKED_PREREQUISITE_UNAVAILABLE - provider unavailable; fixed reason token; nonzero; no automatic
#                                      checker/updater/ranking or state fallback.
#   NO_CHANGE                       - successful unchanged/clean refresh; ordinary ranking 3h ran once and
#                                      succeeded. No forced rebuild is claimed.
#   CHANGED_REBUILD_PENDING         - pending revision (new or retained) with rebuild flag false, or a
#                                      completed rebuild whose acknowledgement reported incomplete/still
#                                      pending. Nonzero; no ranking in the flag-false case, no acknowledgement.
#   REBUILD_COMPLETED               - actual same-owner model/readback plus provider-reported dirty
#                                      acknowledgement for that exact revision, with a final state not still
#                                      pending. Zero.
#   FAILED                          - any operation failed/threw (fixed stage reason, including
#                                      FAILED_AT_CLOSE for a failed session release); nonzero; completed
#                                      attempt flags stay truthful; pending work retained; session closed.
#
# Result shape: Disposition, Reason, ExitCode, Changed (nullable until known), PendingRevision, ordered
# AttemptedSteps, ReleaseCheckAttempted, UpdateAttempted, RankingAttempted, ForcedRebuildAttempted,
# RebuildCompleted. Attempted flags are set immediately before the actual invocation, never from the
# planned branch; release check and updater are counted separately from ranking.
#
# REBUILD_COMPLETED requires same-owner ranking/model/readback and original provider
# acknowledgement for the exact pending revision. It is not fresh-market evidence, native durability,
# machine admission, complete report refresh or cloud publication.
#
# PowerShell 5.1 compatible; no dependencies.

function New-GuidanceOrchestrationResult {
    [CmdletBinding()]
    param(
        [string]$Disposition = '',
        [string]$Reason = '',
        [int]$ExitCode = 0,
        [AllowNull()][object]$Changed = $null,
        [AllowNull()][object]$PendingRevision = $null,
        [string[]]$AttemptedSteps = @(),
        [bool]$ReleaseCheckAttempted = $false,
        [bool]$UpdateAttempted = $false,
        [bool]$RankingAttempted = $false,
        [bool]$ForcedRebuildAttempted = $false,
        [bool]$RebuildCompleted = $false
    )
    $stepsCopy = @()
    foreach ($s in $AttemptedSteps) { $stepsCopy += $s }
    [pscustomobject]@{
        Disposition            = $Disposition
        Reason                 = $Reason
        ExitCode               = $ExitCode
        Changed                = $Changed
        PendingRevision        = $PendingRevision
        AttemptedSteps         = [string[]]$stepsCopy
        ReleaseCheckAttempted  = $ReleaseCheckAttempted
        UpdateAttempted        = $UpdateAttempted
        RankingAttempted       = $RankingAttempted
        ForcedRebuildAttempted = $ForcedRebuildAttempted
        RebuildCompleted       = $RebuildCompleted
    }
}

# Internal: member-presence check for ordinary object and IDictionary/hashtable state shapes. Presence is
# checked separately from (and without) value retrieval, so an explicitly present null member is distinct
# from an absent member.
function Test-GuidanceStateMember {
    [CmdletBinding()]
    param(
        [AllowNull()][object]$State,
        [string]$Member
    )
    if ($null -eq $State) { return $false }
    if ($State -is [System.Collections.IDictionary]) {
        return [bool]$State.Contains($Member)
    }
    $property = $State.PSObject.Properties[$Member]
    return ($null -ne $property)
}

# Internal: value retrieval for ordinary object and IDictionary/hashtable state shapes (call only after
# Test-GuidanceStateMember confirmed presence).
function Get-GuidanceStateMember {
    [CmdletBinding()]
    param(
        [AllowNull()][object]$State,
        [string]$Member
    )
    if ($null -eq $State) { return $null }
    if ($State -is [System.Collections.IDictionary]) {
        return $State[$Member]
    }
    return $State.$Member
}

function Invoke-GuidanceOrchestration {
    [CmdletBinding()]
    param(
        # Provider object exposing an Acquire scriptblock member; $null is the shipped default (unavailable).
        [AllowNull()][object]$GuidanceProvider,
        # The daily function's own step-logging adapter: { [string]$Name, [string[]]$Arguments }
        # -> { ExitCode, Lines }. Ranking steps run through it, never through a module-private path.
        [scriptblock]$RunStep,
        # F02D: SAME acquired backend owner, never ranking CLI/exit-0 completion.
        # { Mode (Cadence/Dirty), Revision } -> { ExitCode, Completed, Revision }.
        [scriptblock]$RunGuidanceRanking,
        # GuidanceDirtyRebuildEnabled: true alone does NOT opt into automatic mode; it only permits the
        # forced 0h rebuild when a pending revision exists.
        [bool]$DirtyRebuildEnabled = $false
    )

    $steps = @()
    $session = $null
    $stage = 'acquire'
    $changed = $null
    $pending = $null
    $releaseCheckAttempted = $false
    $updateAttempted = $false
    $rankingAttempted = $false
    $forcedRebuildAttempted = $false
    $rebuildCompleted = $false
    $result = $null

    $buildResult = {
        param([string]$Disposition, [string]$Reason, [int]$ExitCode)
        New-GuidanceOrchestrationResult -Disposition $Disposition -Reason $Reason -ExitCode $ExitCode `
            -Changed $changed -PendingRevision $pending -AttemptedSteps $steps `
            -ReleaseCheckAttempted $releaseCheckAttempted -UpdateAttempted $updateAttempted `
            -RankingAttempted $rankingAttempted -ForcedRebuildAttempted $forcedRebuildAttempted `
            -RebuildCompleted $rebuildCompleted
    }

    try {
        if ($null -eq $GuidanceProvider) {
            $result = & $buildResult 'BLOCKED_PREREQUISITE_UNAVAILABLE' 'GUIDANCE_PROVIDER_UNAVAILABLE' 1
        }
        else {
            $acquireMember = $GuidanceProvider.PSObject.Properties['Acquire']
            $acquired = $null
            if ($null -ne $acquireMember -and $null -ne $acquireMember.Value) {
                $acquired = & $acquireMember.Value
            }
            if ($null -eq $acquired) {
                $result = & $buildResult 'FAILED' 'FAILED_AT_ACQUIRE' 1
            }
            elseif ($acquired.Available -ne $true) {
                # Bounded reason token: the raw provider Reason text is never surfaced in the B2 log.
                $result = & $buildResult 'BLOCKED_PREREQUISITE_UNAVAILABLE' 'GUIDANCE_PROVIDER_UNAVAILABLE' 1
            }
            else {
                $session = $acquired.Session
                $stage = 'read_state'
                $initialState = & $session.ReadState
                # Retain the known pending state from ReadState; it is carried in the result even if a
                # later stage fails.
                if ($null -ne $initialState) { $pending = $initialState.PendingRevision }
                $stage = 'begin_refresh'
                & $session.BeginRefresh | Out-Null
                $stage = 'release_check'
                $releaseCheckAttempted = $true
                $steps += 'release_check'
                $check = & $session.CheckRelease
                if ($null -eq $check -or $check.Succeeded -ne $true) {
                    $result = & $buildResult 'FAILED' 'FAILED_AT_RELEASE_CHECK' 1
                }
                else {
                    $stage = 'updater'
                    $updateAttempted = $true
                    $steps += 'updater'
                    $updated = & $session.Update
                    if ($null -eq $updated -or $updated.Succeeded -ne $true) {
                        $result = & $buildResult 'FAILED' 'FAILED_AT_UPDATER' 1
                    }
                    else {
                        $stage = 'finish_refresh'
                        $steps += 'finish_refresh'
                        $finished = & $session.FinishRefresh
                        # A missing or unknown finish outcome is never called NO_CHANGE: an actual
                        # System.Boolean Changed flag and an obtained State with a PRESENT PendingRevision
                        # member must be obtained, not inferred. Member presence is checked separately from
                        # the member's (possibly null) value, for ordinary object and IDictionary shapes.
                        $changedKnown = $false
                        if ($null -ne $finished -and (Test-GuidanceStateMember $finished 'Changed')) {
                            $candidateChanged = Get-GuidanceStateMember $finished 'Changed'
                            # Changed must be an actual System.Boolean, not a non-null/string/truthy value.
                            if ($candidateChanged -is [bool]) {
                                $changed = $candidateChanged
                                $changedKnown = $true
                            }
                        }
                        if (-not $changedKnown) {
                            $result = & $buildResult 'FAILED' 'FAILED_AT_FINISH_REFRESH' 1
                        }
                        elseif (-not (Test-GuidanceStateMember $finished 'State') -or $null -eq (Get-GuidanceStateMember $finished 'State')) {
                            # The agreed finish State was not obtained: pending is unknown, not clean.
                            $result = & $buildResult 'FAILED' 'FAILED_AT_FINISH_REFRESH' 1
                        }
                        elseif (-not (Test-GuidanceStateMember (Get-GuidanceStateMember $finished 'State') 'PendingRevision')) {
                            # The agreed PendingRevision member is absent: pending is unknown, not clean.
                            $result = & $buildResult 'FAILED' 'FAILED_AT_FINISH_REFRESH' 1
                        }
                        else {
                            $pending = Get-GuidanceStateMember (Get-GuidanceStateMember $finished 'State') 'PendingRevision'
                            if ($null -eq $pending) {
                                if ($changed -eq $true) {
                                    # A changed input must produce its pending revision (provider contract);
                                    # never synthesize one.
                                    $result = & $buildResult 'FAILED' 'FAILED_AT_FINISH_REFRESH' 1
                                }
                                else {
                                    # Successful unchanged/clean refresh: run the ordinary 3h ranking once;
                                    # NO_CHANGE if that step succeeds.
                                    $stage = 'ranking'
                                    $rankingAttempted = $true
                                    $steps += 'ranking'
                                    $ranked = if ($null -ne $RunGuidanceRanking) { & $RunGuidanceRanking 'Cadence' $null } else { $null }
                                    if ($null -eq $ranked -or $ranked.ExitCode -ne 0 -or $ranked.Completed -isnot [bool] -or $ranked.Completed -ne $true) {
                                        $result = & $buildResult 'FAILED' 'FAILED_AT_RANKING' 1
                                    }
                                    else {
                                        $result = & $buildResult 'NO_CHANGE' 'NO_CHANGE' 0
                                    }
                                }
                            }
                            elseif (-not $DirtyRebuildEnabled) {
                                # Pending input change (new or retained), rebuild flag false: no ranking,
                                # no acknowledgement.
                                $result = & $buildResult 'CHANGED_REBUILD_PENDING' 'CHANGED_REBUILD_PENDING' 1
                            }
                            else {
                                $stage = 'rebuild_ranking'
                                $rankingAttempted = $true
                                $forcedRebuildAttempted = $true
                                $steps += 'forced_rebuild'
                                $ranked = if ($null -ne $RunGuidanceRanking) { & $RunGuidanceRanking 'Dirty' $pending } else { $null }
                                if ($null -eq $ranked -or $ranked.ExitCode -ne 0 -or $ranked.Completed -isnot [bool] -or
                                    $ranked.Completed -ne $true -or $ranked.Revision -isnot [string] -or
                                    -not [string]::Equals($ranked.Revision,[string]$pending,[StringComparison]::Ordinal)) {
                                    # Ranking failed: pending work is retained; the rebuild lifecycle is not complete.
                                    $result = & $buildResult 'FAILED' 'FAILED_AT_REBUILD_RANKING' 1
                                }
                                else {
                                    $stage = 'acknowledge'
                                    $steps += 'acknowledge'
                                    $ack = & $session.AcknowledgeRebuild $pending
                                    # The acknowledgement's final state must be OBTAINED and carry a PRESENT
                                    # PendingRevision member, checked separately from the member's null value.
                                    # Only an explicitly present null pending in the obtained state supports
                                    # completion; a missing ack/State/member stays unknown and is never
                                    # REBUILD_COMPLETED.
                                    $ackFinalPending = $null
                                    $ackFinalPendingKnown = $false
                                    if ($null -ne $ack -and (Test-GuidanceStateMember $ack 'State')) {
                                        $ackState = Get-GuidanceStateMember $ack 'State'
                                        if ($null -ne $ackState -and (Test-GuidanceStateMember $ackState 'PendingRevision')) {
                                            $ackFinalPending = Get-GuidanceStateMember $ackState 'PendingRevision'
                                            $ackFinalPendingKnown = $true
                                        }
                                    }
                                    if ($null -eq $ack -or $ack.Completed -ne $true -or -not $ackFinalPendingKnown -or $null -ne $ackFinalPending) {
                                        # Incomplete acknowledgement, a final state that is still pending, or a
                                        # missing/unknown final state: the rebuild lifecycle is not complete.
                                        # Never REBUILD_COMPLETED.
                                        if ($ackFinalPendingKnown -and $null -ne $ackFinalPending) { $pending = $ackFinalPending }
                                        $result = & $buildResult 'CHANGED_REBUILD_PENDING' 'CHANGED_REBUILD_PENDING' 1
                                    }
                                    else {
                                        $pending = $null
                                        $rebuildCompleted = $true
                                        $result = & $buildResult 'REBUILD_COMPLETED' 'REBUILD_COMPLETED' 0
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    catch {
        # Any operation threw: fixed stage reason, truthful flags, pending work retained (session closed in finally).
        $stageNames = @{
            'acquire' = 'ACQUIRE'; 'read_state' = 'READ_STATE'; 'begin_refresh' = 'BEGIN_REFRESH'
            'release_check' = 'RELEASE_CHECK'; 'updater' = 'UPDATER'; 'finish_refresh' = 'FINISH_REFRESH'
            'ranking' = 'RANKING'; 'rebuild_ranking' = 'REBUILD_RANKING'; 'acknowledge' = 'ACKNOWLEDGE'
        }
        $stageName = $stageNames[$stage]
        if ([string]::IsNullOrEmpty($stageName)) { $stageName = 'UNKNOWN' }
        $result = & $buildResult 'FAILED' ('FAILED_AT_' + $stageName) 1
    }
    finally {
        if ($null -ne $session) {
            $closeFailed = $false
            try {
                & $session.Close | Out-Null
            }
            catch { $closeFailed = $true }
            if ($closeFailed) {
                # A failed session release after an apparent success is not swallowed: finalize as truthful
                # FAILED with the fixed close-stage reason, keeping the attempt flags and pending work.
                $result = & $buildResult 'FAILED' 'FAILED_AT_CLOSE' 1
            }
        }
    }
    return $result
}

Export-ModuleMember -Function 'Invoke-GuidanceOrchestration', 'New-GuidanceOrchestrationResult'
