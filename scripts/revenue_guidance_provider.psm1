# revenue_guidance_provider.psm1
#
# PROVIDER-CORE-01 / Deliverable B (r2) — guidance provider factory.
# PowerShell 5.1; no dependencies. Exports only: New-GuidanceProvider.
#
# Design (SR-01..05 repairs):
#   All private helpers are named module-scope functions; their scriptblock references are
#   captured into per-invocation context objects at acquisition time so that tiny
#   GetNewClosure session callbacks can dispatch to them without resolving departed locals.
#   Post-acquisition lease ownership: ONE guard owns the lease after the non-null
#   handoff; the reconcile helper NEVER closes; every non-handoff exit (validation
#   exception included) releases at most once, and a bounded release failure
#   (LEASE_RELEASE_FAILED) overrides the generic unavailability reason.
#   Backend lease operations (scriptblock properties) are invoked as: & $op [args...].
#   Every backend operation, including the factory OpenSession member, MUST be an
#   actual [scriptblock]; non-scriptblock members are treated as absent (fixed token).
#   Journal Version is kept INTERNALLY as a single-element wrapper @{V=$token} to survive
#   pipeline unrolling; the wrapper never leaves the module — backend CommitJournal
#   receives the ORIGINAL raw opaque token in exactly one argument slot.
#   Explicit phase/closed state enforced per session; no shared globals between sessions.
#
# Backend contract (P2/P3; NOT implemented here):
#   $backend.OpenSession  -> { Available=$false, Reason } | { Available=$true, Lease }
#     Lease is a PSObject/hashtable with scriptblock properties:
#       ReadJournal           -> { Version={opaque}, State={journal-dict} }
#       ReadInputRevision     -> <gir1:hex string>
#       CommitJournal ExpectedVersion NewState
#                             (ExpectedVersion = raw opaque Version token, single slot)
#                             -> { Committed={bool}, Version={opaque}, State={journal-dict} }
#       CheckRelease          -> { Succeeded={bool}, Reason={string} }
#       Update                -> { Succeeded={bool}, Reason={string} }
#       ReadRebuildCompletion Revision
#                             -> $null/absent | { Completed={bool}, Revision={string} }
#       Close                 -> (void; release only)
#   Journals from the backend must be initialized (StateRequired=$true); absent/uninit
#   journals are not initialized by this provider.
#
# CODE_ONLY_WRITTEN_NOT_EXECUTED. Not functional ACCEPT.

Set-StrictMode -Version 2.0

# ---------------------------------------------------------------------------
# Module-scope constants (captured by reference into context objects)
# ---------------------------------------------------------------------------
$script:JOURNAL_SCHEMA = 'guidance-provider-journal-v1'
$script:UNAVAIL_REASON = 'GUIDANCE_BACKEND_UNAVAILABLE'

# ---------------------------------------------------------------------------
# Private: invoke a scriptblock property from a PSObject or hashtable lease.
# Backend operations are ALWAYS called as: & $op [args...] — never method syntax.
# $op must be a [scriptblock]; any other representation is refused with a fixed token.
# Returns the raw result without success-stream enumeration; caller validates shape.
# ---------------------------------------------------------------------------
function _Invoke-LeaseOp {
    param([object]$Lease, [string]$OpName, [object[]]$OpArgs)
    $op = $null
    if ($Lease -is [System.Collections.IDictionary]) { $op = $Lease[$OpName] }
    else { $prop = $Lease.PSObject.Properties[$OpName]; if ($null -ne $prop) { $op = $prop.Value } }
    if ($null -eq $op) { throw "MISSING_LEASE_OP:$OpName" }
    if ($op -isnot [scriptblock]) { throw "INVALID_LEASE_OP_TYPE:$OpName" }
    if ($OpArgs.Count -eq 0) { $result = & $op } else { $result = & $op @OpArgs }
    Write-Output -NoEnumerate $result
}

# ---------------------------------------------------------------------------
# Private: member-presence check (IDictionary + PSObject). Explicit null is PRESENT.
# ---------------------------------------------------------------------------
function _Has {
    param([AllowNull()][object]$Obj, [string]$Name)
    if ($null -eq $Obj) { return $false }
    if ($Obj -is [System.Collections.IDictionary]) { return [bool]$Obj.Contains($Name) }
    return ($null -ne $Obj.PSObject.Properties[$Name])
}

# ---------------------------------------------------------------------------
# Private: member-value retrieval (call only after _Has confirmed presence).
# ---------------------------------------------------------------------------
function _Get {
    param([AllowNull()][object]$Obj, [string]$Name)
    if ($null -eq $Obj) { return $null }
    if ($Obj -is [System.Collections.IDictionary]) { return $Obj[$Name] }
    return $Obj.$Name
}

# ---------------------------------------------------------------------------
# Private: wrap a Version token to survive pipeline without array unrolling.
# ---------------------------------------------------------------------------
function _WrapVer { param([object]$V) ; @{ V = $V } }

# ---------------------------------------------------------------------------
# Private: build the public B2 state copy { InputRevision, PendingRevision, StateRequired }.
# Never exposes journal internals (Intent, Schema, Version) to the B2 caller.
# ---------------------------------------------------------------------------
function _PublicState {
    param([object]$J)
    [pscustomobject]@{
        InputRevision   = _Get $J 'InputRevision'
        PendingRevision = _Get $J 'PendingRevision'
        StateRequired   = _Get $J 'StateRequired'
    }
}

# ---------------------------------------------------------------------------
# Private: actual Boolean check (not truthy; must be [bool]).
# ---------------------------------------------------------------------------
function _Is-Bool { param([object]$V) ; ($V -is [bool]) }

# ---------------------------------------------------------------------------
# Private: gir1 token check — exact shape: 'gir1:' + lowercase 64-hex.  No coercion.
# ---------------------------------------------------------------------------
function _Is-Gir1 {
    param([object]$V)
    if ($V -isnot [string]) { return $false }
    if ($V.Length -ne 69) { return $false }
    if (-not $V.StartsWith('gir1:', [System.StringComparison]::Ordinal)) { return $false }
    $hex = $V.Substring(5)
    foreach ($c in ($hex.ToCharArray())) {
        $isHex = ($c -ge '0' -and $c -le '9') -or ($c -ge 'a' -and $c -le 'f')
        if (-not $isHex) { return $false }
    }
    return $true
}

# ---------------------------------------------------------------------------
# Private: validate a full journal shape. Requires actual [bool] $true for
# StateRequired; gir1 InputRevision; present PendingRevision (null or gir1);
# present Intent (null or sub-object with all 4 required fields).
# ---------------------------------------------------------------------------
function _Valid-Journal {
    param([AllowNull()][object]$J)
    if ($null -eq $J) { return $false }
    $sch = _Get $J 'Schema'
    if ($sch -isnot [string] -or $sch -ne $script:JOURNAL_SCHEMA) { return $false }
    $sr = _Get $J 'StateRequired'
    if ($sr -isnot [bool] -or $sr -ne $true) { return $false }
    if (-not (_Has $J 'InputRevision') -or -not (_Is-Gir1 (_Get $J 'InputRevision'))) { return $false }
    if (-not (_Has $J 'PendingRevision')) { return $false }
    $pr = _Get $J 'PendingRevision'
    if ($null -ne $pr -and -not (_Is-Gir1 $pr)) { return $false }
    if (-not (_Has $J 'Intent')) { return $false }
    $intent = _Get $J 'Intent'
    if ($null -ne $intent) {
        foreach ($k in @('Id','BaseInputRevision','ObservedAtBeginRevision','PriorPendingRevision')) {
            if (-not (_Has $intent $k)) { return $false }
        }
        if ((_Get $intent 'Id') -isnot [string] -or [string]::IsNullOrEmpty((_Get $intent 'Id'))) { return $false }
        if (-not (_Is-Gir1 (_Get $intent 'BaseInputRevision')))       { return $false }
        if (-not (_Is-Gir1 (_Get $intent 'ObservedAtBeginRevision'))) { return $false }
        $pp = _Get $intent 'PriorPendingRevision'
        if ($null -ne $pp -and -not (_Is-Gir1 $pp)) { return $false }
    }
    return $true
}

# ---------------------------------------------------------------------------
# Private: validate CommitJournal result and confirm full readback matches
# the requested state hashtable (every key, including Intent sub-fields).
# Requires actual [bool] Committed=$true, non-null opaque Version, valid journal.
# On success, sets OutVerWrapper to a new wrapped version token.
# ---------------------------------------------------------------------------
function _Valid-Commit {
    param([AllowNull()][object]$CR, [hashtable]$Req, [ref]$OutVerWrapper)
    if ($null -eq $CR) { return $false }
    $c = _Get $CR 'Committed'
    if ($c -isnot [bool] -or $c -ne $true) { return $false }
    if (-not (_Has $CR 'Version')) { return $false }
    # Preserve Version identity AT EXTRACTION: direct member assignment inside the
    # IDictionary / PSObject branch (no _Get success stream, no if-expression).
    if ($CR -is [System.Collections.IDictionary]) { $rawVer = $CR['Version'] } else { $rawVer = $CR.Version }
    if ($null -eq $rawVer) { return $false }
    $rb = _Get $CR 'State'
    if (-not (_Valid-Journal $rb)) { return $false }
    foreach ($k in $Req.Keys) {
        if (-not (_Has $rb $k)) { return $false }
        $got = _Get $rb $k ; $want = $Req[$k]
        if ($null -eq $want -and $null -eq $got) { continue }
        if ($null -eq $want -or $null -eq $got)  { return $false }
        if ($k -eq 'Intent') {
            foreach ($ik in $want.Keys) {
                if (-not (_Has $got $ik)) { return $false }
                if ((_Get $got $ik) -ne $want[$ik]) { return $false }
            }
        } elseif ($got -ne $want) { return $false }
    }
    $OutVerWrapper.Value = (_WrapVer $rawVer)
    return $true
}

# ---------------------------------------------------------------------------
# Private: fixed unavailable acquire result (bounded token; no raw backend text).
# ---------------------------------------------------------------------------
function _Unavail { param([string]$R) ; [pscustomobject]@{ Available=$false; Reason=$R } }

# ---------------------------------------------------------------------------
# Private: read + validate the journal and run prior-intent recovery on an
# already-owned lease. This helper NEVER closes the lease; ownership and cleanup
# belong to the _Open-ReconciledLease guard below. Returns @{OK=$true;Journal;
# VerWrapper} or @{OK=$false;Reason}.
# ---------------------------------------------------------------------------
function _Reconcile-OwnedLease {
    param([object]$Lease)
    # Read journal.
    $jr = $null
    try { $jr = _Invoke-LeaseOp $Lease 'ReadJournal' @() } catch { return @{OK=$false;Reason='FAILED_AT_READ_JOURNAL'} }
    if ($null -eq $jr -or -not (_Has $jr 'Version') -or -not (_Has $jr 'State')) {
        return @{OK=$false;Reason='FAILED_AT_READ_JOURNAL'}
    }
    # Preserve Version identity AT EXTRACTION: assign the member DIRECTLY inside the
    # IDictionary / PSObject branch — no _Get success stream, no if-expression
    # (both would enumerate an enumerable token). Wrap only after direct assignment.
    if ($jr -is [System.Collections.IDictionary]) { $rawVer = $jr['Version'] } else { $rawVer = $jr.Version }
    if ($null -eq $rawVer) { return @{OK=$false;Reason='FAILED_AT_READ_JOURNAL'} }
    $vw = _WrapVer $rawVer
    $j  = _Get $jr 'State'
    if (-not (_Valid-Journal $j)) { return @{OK=$false;Reason='JOURNAL_NOT_INITIALIZED'} }

    # Prior-intent recovery: if Intent is non-null, conservatively commit
    # InputRevision=current, PendingRevision=current, Intent=$null.
    $intent = _Get $j 'Intent'
    if ($null -ne $intent) {
        $curRev = $null
        try { $curRev = _Invoke-LeaseOp $Lease 'ReadInputRevision' @() } catch { return @{OK=$false;Reason='FAILED_AT_READ_REVISION'} }
        if (-not (_Is-Gir1 $curRev)) { return @{OK=$false;Reason='FAILED_AT_READ_REVISION'} }
        $recov = @{
            Schema='guidance-provider-journal-v1'; StateRequired=$true
            InputRevision=$curRev; PendingRevision=$curRev; Intent=$null
        }
        # ExpectedVersion = ORIGINAL raw opaque token (wrapper is internal bookkeeping only).
        $cr = $null
        try { $cr = _Invoke-LeaseOp $Lease 'CommitJournal' @($vw.V, $recov) } catch { return @{OK=$false;Reason='FAILED_AT_RECOVERY_COMMIT'} }
        $newVw = $null
        if (-not (_Valid-Commit $cr $recov ([ref]$newVw))) { return @{OK=$false;Reason='FAILED_AT_RECOVERY_COMMIT'} }
        $vw = $newVw
        $j  = _Get $cr 'State'
    }

    return @{OK=$true; Journal=$j; VerWrapper=$vw}
}

# ---------------------------------------------------------------------------
# Private: open backend session, then reconcile under ONE ownership guard. The
# lease-owned region begins immediately after the non-null lease handoff and
# covers validation, extraction, reads and the recovery commit. Every non-handoff
# exit/exception releases the lease at most once (shared $released/$handed markers);
# a bounded release failure yields the fixed LEASE_RELEASE_FAILED reason, never a
# swallowed cleanup and never the generic unavailability reason. The final bounded
# result is evaluated AFTER cleanup in the finally block, so a release failure can
# never be silently lost. Returns @{OK=$true;Lease;Journal;VerWrapper} or
# @{OK=$false;Reason}.
# ---------------------------------------------------------------------------
function _Open-ReconciledLease {
    param([object]$OpenSessionOp)
    # Open session via scriptblock property (no lease owned before this handoff).
    $opened = $null
    try { $opened = & $OpenSessionOp } catch { return @{OK=$false;Reason=$script:UNAVAIL_REASON} }
    if ($null -eq $opened -or -not (_Has $opened 'Available')) { return @{OK=$false;Reason=$script:UNAVAIL_REASON} }
    $avail = _Get $opened 'Available'
    if ($avail -isnot [bool] -or $avail -ne $true) { return @{OK=$false;Reason=$script:UNAVAIL_REASON} }
    $lease = _Get $opened 'Lease'
    if ($null -eq $lease) { return @{OK=$false;Reason=$script:UNAVAIL_REASON} }

    # ONE ownership guard over the entire post-handoff region. The reconcile helper
    # NEVER closes; this guard is the sole release site (at most once per invocation).
    # The bounded result is evaluated AFTER cleanup (single post-guard return), so a
    # release failure can never be silently lost behind an early-returned value.
    # A shared marker object carries result/handed/released across the
    # try/catch/finally blocks (object mutation is scope-safe; block-local
    # variables would not be visible after the guard).
    $g = @{ result=$null; released=$false; handed=$false }
    try {
        $res = _Reconcile-OwnedLease $lease
        if ($null -ne $res -and $res.OK -eq $true) {
            $g.handed = $true
            $g.result = @{OK=$true;Lease=$lease;Journal=$res.Journal;VerWrapper=$res.VerWrapper}
        }
        else {
            $rsn = if ($null -ne $res -and $res.OK -ne $true -and -not [string]::IsNullOrEmpty($res.Reason)) { $res.Reason } else { 'RECONCILE_FAILED' }
            $g.result = @{OK=$false;Reason=$rsn}
        }
    }
    catch {
        # Bounded validation/extraction/commit exceptions become a fixed stage failure.
        $g.result = @{OK=$false;Reason='FAILED_AT_RECONCILE'}
    }
    finally {
        # No successful handoff: release the lease exactly once. A FAILED release
        # OVERRIDES the ordinary failure result with the fixed visible
        # LEASE_RELEASE_FAILED reason — never swallowed, never generic unavailability.
        if ($null -eq $g.result) { $g.result = @{OK=$false;Reason='RECONCILE_FAILED'} }
        if (-not $g.handed -and -not $g.released -and $null -ne $lease) {
            $g.released = $true
            try { _Invoke-LeaseOp $lease 'Close' @() | Out-Null }
            catch { $g.result = @{OK=$false;Reason='LEASE_RELEASE_FAILED'} }
        }
    }
    return $g.result
}

# ---------------------------------------------------------------------------
# Private per-phase dispatch functions. Each accepts a shared context hashtable
# @{Lease;VerWrapper;Journal;Phase;Closed}. Phase guards enforce ordering;
# Closed blocks all operations. No raw backend payload surfaces in results.
# ---------------------------------------------------------------------------
function _Do-ReadState {
    param([hashtable]$Ctx)
    if ($Ctx.Closed) { throw 'SESSION_CLOSED' }
    try { return _PublicState $Ctx.Journal }
    catch { throw 'FAILED_AT_READ_STATE' }  # bounded: no raw property/backend exception escapes
}

function _Do-BeginRefresh {
    param([hashtable]$Ctx)
    if ($Ctx.Closed) { throw 'SESSION_CLOSED' }
    if ($Ctx.Phase -eq 'failed' -or $Ctx.Phase -eq 'dispatching') { throw 'OPERATION_FAILED' }
    if ($Ctx.Phase -ne 'idle') { throw 'INVALID_PHASE' }
    $curRev = $null
    try { $curRev = _Invoke-LeaseOp $Ctx.Lease 'ReadInputRevision' @() }
    catch { throw 'FAILED_AT_READ_REVISION' }
    if (-not (_Is-Gir1 $curRev)) { throw 'FAILED_AT_READ_REVISION' }
    try {
        $priorPending = _Get $Ctx.Journal 'PendingRevision'
        $intentId  = [System.Guid]::NewGuid().ToString('N')
        $intentObj = @{ Id=$intentId; BaseInputRevision=(_Get $Ctx.Journal 'InputRevision')
                        ObservedAtBeginRevision=$curRev; PriorPendingRevision=$priorPending }
        $req = @{ Schema=$script:JOURNAL_SCHEMA; StateRequired=$true
                  InputRevision=(_Get $Ctx.Journal 'InputRevision')
                  PendingRevision=$priorPending; Intent=$intentObj }
    }
    catch { throw 'FAILED_AT_BEGIN_VALIDATE' }  # bounded validation, not a raw property exception
    # Mark the attempt BEFORE dispatch: a failed/uncertain cycle is terminal.
    $Ctx.Phase = 'dispatching'
    $cr = $null
    try { $cr = _Invoke-LeaseOp $Ctx.Lease 'CommitJournal' @($Ctx.VerWrapper.V, $req) }
    catch { $Ctx.Phase = 'failed'; throw 'FAILED_AT_BEGIN_COMMIT' }
    $newVw = $null
    try {
        # Bounded post-commit validation/readback: the validator and committed-state
        # extraction are guarded; no raw property/StrictMode exception escapes.
        if (-not (_Valid-Commit $cr $req ([ref]$newVw))) { throw 'FAILED_AT_BEGIN_COMMIT' }
        $Ctx.VerWrapper = $newVw
        $Ctx.Journal   = _Get $cr 'State'
    }
    catch { $Ctx.Phase = 'failed'; throw 'FAILED_AT_BEGIN_COMMIT' }
    $Ctx.Phase = 'begun'   # transition only after ALL validated readback values obtained
}

function _Do-CheckRelease {
    param([hashtable]$Ctx)
    if ($Ctx.Closed) { throw 'SESSION_CLOSED' }
    if ($Ctx.Phase -eq 'failed' -or $Ctx.Phase -eq 'dispatching') { throw 'OPERATION_FAILED' }
    if ($Ctx.Phase -ne 'begun') { throw 'INVALID_PHASE' }
    # Mark the attempt BEFORE dispatch: a failed/uncertain cycle is terminal
    # (no retry, no Finish after a failed checker).
    $Ctx.Phase = 'dispatching'
    $r = $null
    try { $r = _Invoke-LeaseOp $Ctx.Lease 'CheckRelease' @() }
    catch { $Ctx.Phase = 'failed'; throw 'FAILED_AT_CHECK_RELEASE' }
    try {
        if ($null -eq $r -or -not (_Has $r 'Succeeded')) { throw 'FAILED_AT_CHECK_RELEASE' }
        $s = _Get $r 'Succeeded'
        if ($s -isnot [bool]) { throw 'FAILED_AT_CHECK_RELEASE' }
        if ($s -eq $true) { $Ctx.Phase = 'checked' }
    }
    catch { $Ctx.Phase = 'failed'; throw 'FAILED_AT_CHECK_RELEASE' }
    [pscustomobject]@{ Succeeded=$s; Reason='CHECK_RELEASE_RESULT' }
}

function _Do-Update {
    param([hashtable]$Ctx)
    if ($Ctx.Closed) { throw 'SESSION_CLOSED' }
    if ($Ctx.Phase -eq 'failed' -or $Ctx.Phase -eq 'dispatching') { throw 'OPERATION_FAILED' }
    if ($Ctx.Phase -ne 'checked') { throw 'INVALID_PHASE' }
    $Ctx.Phase = 'dispatching'
    $r = $null
    try { $r = _Invoke-LeaseOp $Ctx.Lease 'Update' @() }
    catch { $Ctx.Phase = 'failed'; throw 'FAILED_AT_UPDATE' }
    try {
        if ($null -eq $r -or -not (_Has $r 'Succeeded')) { throw 'FAILED_AT_UPDATE' }
        $s = _Get $r 'Succeeded'
        if ($s -isnot [bool]) { throw 'FAILED_AT_UPDATE' }
        if ($s -eq $true) { $Ctx.Phase = 'updated' }
    }
    catch { $Ctx.Phase = 'failed'; throw 'FAILED_AT_UPDATE' }
    [pscustomobject]@{ Succeeded=$s; Reason='UPDATE_RESULT' }
}

function _Do-FinishRefresh {
    param([hashtable]$Ctx)
    if ($Ctx.Closed) { throw 'SESSION_CLOSED' }
    if ($Ctx.Phase -eq 'failed' -or $Ctx.Phase -eq 'dispatching') { throw 'OPERATION_FAILED' }
    if ($Ctx.Phase -ne 'updated') { throw 'INVALID_PHASE' }
    $curRev = $null
    try { $curRev = _Invoke-LeaseOp $Ctx.Lease 'ReadInputRevision' @() }
    catch { throw 'FAILED_AT_READ_REVISION' }
    if (-not (_Is-Gir1 $curRev)) { throw 'FAILED_AT_READ_REVISION' }
    try {
        $intent  = _Get $Ctx.Journal 'Intent'
        $baseIR  = if ($null -ne $intent) { _Get $intent 'BaseInputRevision' } else { $null }
        $changed = [bool]($curRev -ne $baseIR)
        $curIR   = _Get $Ctx.Journal 'InputRevision'
        $priorPR = _Get $Ctx.Journal 'PendingRevision'
    }
    catch { throw 'FAILED_AT_FINISH_VALIDATE' }  # bounded validation, not a raw property exception
    if ($changed) { $newIR = $curRev; $newPR = $curRev }
    else {
        $newIR = $curIR
        # Reconcile diverged pending to current rather than acknowledge an old token.
        if ($null -ne $priorPR -and $priorPR -ne $curRev) { $newPR = $curRev }
        else { $newPR = $priorPR }
    }
    $req = @{ Schema=$script:JOURNAL_SCHEMA; StateRequired=$true
              InputRevision=$newIR; PendingRevision=$newPR; Intent=$null }
    $Ctx.Phase = 'dispatching'
    $cr = $null
    try { $cr = _Invoke-LeaseOp $Ctx.Lease 'CommitJournal' @($Ctx.VerWrapper.V, $req) }
    catch { $Ctx.Phase = 'failed'; throw 'FAILED_AT_FINISH_COMMIT' }
    $newVw = $null
    try {
        # Bounded post-commit validation/readback (validator + committed state +
        # public-state extraction); no raw property/StrictMode exception escapes.
        if (-not (_Valid-Commit $cr $req ([ref]$newVw))) { throw 'FAILED_AT_FINISH_COMMIT' }
        $Ctx.VerWrapper = $newVw
        $Ctx.Journal    = _Get $cr 'State'
        $publicState    = _PublicState $Ctx.Journal
    }
    catch { $Ctx.Phase = 'failed'; throw 'FAILED_AT_FINISH_COMMIT' }
    $Ctx.Phase = 'idle'   # transition only after ALL validated readback values obtained
    [pscustomobject]@{ Changed=$changed; State=$publicState }
}

function _Do-AcknowledgeRebuild {
    param([hashtable]$Ctx, [object]$Revision)
    if ($Ctx.Closed) { throw 'SESSION_CLOSED' }
    if ($Ctx.Phase -eq 'failed' -or $Ctx.Phase -eq 'dispatching') { throw 'OPERATION_FAILED' }
    if ($Ctx.Phase -ne 'idle') { throw 'INVALID_PHASE' }
    $noComp = [pscustomobject]@{ Completed=$false; State=(_PublicState $Ctx.Journal) }
    if (-not (_Is-Gir1 $Revision)) { return $noComp }
    try {
        if ($null -ne (_Get $Ctx.Journal 'Intent')) { return $noComp }  # outstanding intent
        $curIR = _Get $Ctx.Journal 'InputRevision'
        $curPR = _Get $Ctx.Journal 'PendingRevision'
    }
    catch { return $noComp }
    if ($Revision -ne $curIR -or $Revision -ne $curPR) { return $noComp }
    $liveRev = $null
    try { $liveRev = _Invoke-LeaseOp $Ctx.Lease 'ReadInputRevision' @() } catch { return $noComp }
    # The LIVE revision itself must be a valid gir1 token, then exact ordinal string
    # equality with the requested token, before requesting completion or committing.
    if (-not (_Is-Gir1 $liveRev)) { return $noComp }
    if ([string]::Compare($liveRev, $Revision, [System.StringComparison]::Ordinal) -ne 0) { return $noComp }
    $comp = $null
    try { $comp = _Invoke-LeaseOp $Ctx.Lease 'ReadRebuildCompletion' @($Revision) } catch { return $noComp }
    try {
        if ($null -eq $comp -or -not (_Has $comp 'Completed') -or -not (_Has $comp 'Revision')) { return $noComp }
        $compDone = _Get $comp 'Completed'
        $compRev  = _Get $comp 'Revision'
        if ($compDone -isnot [bool] -or $compDone -ne $true) { return $noComp }
        # Exact non-null string token equality; no coercion or collection comparison.
        if ($compRev -isnot [string] -or -not ([string]::Equals($compRev, $Revision))) { return $noComp }
    }
    catch { return $noComp }  # bounded validation: a throwing property read is not a completion
    $req = @{ Schema=$script:JOURNAL_SCHEMA; StateRequired=$true
              InputRevision=$curIR; PendingRevision=$null; Intent=$null }
    # Mark the attempt BEFORE dispatch; a failed commit leaves the cycle terminal
    # (Phase stays 'dispatching'), pending state preserved — no blind retry.
    $Ctx.Phase = 'dispatching'
    $cr = $null
    try { $cr = _Invoke-LeaseOp $Ctx.Lease 'CommitJournal' @($Ctx.VerWrapper.V, $req) } catch { return $noComp }
    $newVw = $null
    try {
        # Bounded post-commit validation/readback; a throwing/incomplete readback is
        # NOT a completion. Terminal state; pending preserved; no blind retry.
        if (-not (_Valid-Commit $cr $req ([ref]$newVw))) { return $noComp }
        $Ctx.VerWrapper = $newVw
        $Ctx.Journal    = _Get $cr 'State'
        $publicState    = _PublicState $Ctx.Journal
    }
    catch { $Ctx.Phase = 'failed'; return $noComp }  # fixed bounded outcome; state unreadable
    $Ctx.Phase = 'idle'   # transition only after ALL validated readback values obtained
    [pscustomobject]@{ Completed=$true; State=$publicState }
}

function _Do-Close {
    param([hashtable]$Ctx)
    if ($Ctx.Closed) { return }        # idempotent
    $Ctx.Closed = $true                # mark before attempt so re-entry is safe
    try { _Invoke-LeaseOp $Ctx.Lease 'Close' @() | Out-Null }
    catch { throw 'FAILED_AT_CLOSE' }  # surface; never swallow
}

# ---------------------------------------------------------------------------
# Private: build per-invocation context and return a session PSObject.
# Scriptblock refs to named _Do-* functions are captured once into locals;
# each tiny GetNewClosure callback closes over $ctx + one ref — no departed locals.
# Named functions resolve private helpers and $script: constants at call time
# from module scope, unaffected by GetNewClosure's variable capture.
# ---------------------------------------------------------------------------
function _New-GuidanceSession {
    param([object]$Lease, [object]$VerWrapper, [object]$Journal)
    $ctx = @{ Lease=$Lease; VerWrapper=$VerWrapper; Journal=$Journal; Phase='idle'; Closed=$false }
    $sbRS = (Get-Item function:_Do-ReadState).ScriptBlock
    $sbBR = (Get-Item function:_Do-BeginRefresh).ScriptBlock
    $sbCR = (Get-Item function:_Do-CheckRelease).ScriptBlock
    $sbU  = (Get-Item function:_Do-Update).ScriptBlock
    $sbFR = (Get-Item function:_Do-FinishRefresh).ScriptBlock
    $sbAR = (Get-Item function:_Do-AcknowledgeRebuild).ScriptBlock
    $sbCl = (Get-Item function:_Do-Close).ScriptBlock
    $readState     = { & $sbRS $ctx }.GetNewClosure()
    $beginRefresh  = { & $sbBR $ctx }.GetNewClosure()
    $checkRelease  = { & $sbCR $ctx }.GetNewClosure()
    $update        = { & $sbU  $ctx }.GetNewClosure()
    $finishRefresh = { & $sbFR $ctx }.GetNewClosure()
    $ackRebuild    = { param($Rev) & $sbAR $ctx $Rev }.GetNewClosure()
    $close         = { & $sbCl $ctx }.GetNewClosure()
    [pscustomobject]@{
        ReadState=$readState; BeginRefresh=$beginRefresh; CheckRelease=$checkRelease
        Update=$update; FinishRefresh=$finishRefresh; AcknowledgeRebuild=$ackRebuild; Close=$close
    }
}

# ---------------------------------------------------------------------------
# Private: ORIGINAL module-bound acquire dispatch. Resolves its private helpers
# (_Unavail, _Open-ReconciledLease, _New-GuidanceSession, _Invoke-LeaseOp) in the
# original module scope. The exported Acquire closure invokes this scriptblock with
# the per-provider context @{OpenOp; UnavailReason}; it never resolves private command
# names or $script: constants from the dynamic closure scope.
# ---------------------------------------------------------------------------
function _Acquire-Session {
    param([hashtable]$P)
    if ($null -eq $P.OpenOp) { return _Unavail $P.UnavailReason }
    $r = $null
    try { $r = _Open-ReconciledLease $P.OpenOp } catch { return _Unavail $P.UnavailReason }
    if ($null -eq $r -or $r.OK -ne $true) {
        $rsn = if ($null -ne $r -and -not [string]::IsNullOrEmpty($r.Reason)) { $r.Reason } else { $P.UnavailReason }
        return _Unavail $rsn
    }
    $sess = $null
    try { $sess = _New-GuidanceSession -Lease $r.Lease -VerWrapper $r.VerWrapper -Journal $r.Journal }
    catch {
        # Session construction failed AFTER the lease was owned: release once and
        # surface the outcome; a failed release is a fixed visible failure.
        $closed = $false
        try { _Invoke-LeaseOp $r.Lease 'Close' @() | Out-Null; $closed = $true } catch { $closed = $false }
        if (-not $closed) { return _Unavail 'LEASE_RELEASE_FAILED' }
        return _Unavail $P.UnavailReason
    }
    [pscustomobject]@{ Available=$true; Session=$sess }
}

# ---------------------------------------------------------------------------
# Public factory — sole export. BackendFactory: nullable object with an
# OpenSession scriptblock property; default $null (unavailable).
# Factory creation performs no acquisition, load, path read or process launch.
# ---------------------------------------------------------------------------
function New-GuidanceProvider {
    [CmdletBinding()]
    param([AllowNull()][object]$BackendFactory = $null)
    $openOp = $null
    if ($null -ne $BackendFactory) {
        if ($BackendFactory -is [System.Collections.IDictionary]) { $openOp = $BackendFactory['OpenSession'] }
        else { $p = $BackendFactory.PSObject.Properties['OpenSession']; if ($null -ne $p) { $openOp = $p.Value } }
        # Contract: the factory OpenSession member must be an ACTUAL [scriptblock].
        # Any other representation is treated as absent -> fixed unavailability.
        if ($null -ne $openOp -and $openOp -isnot [scriptblock]) { $openOp = $null }
    }
    # Acquire closure captures the ORIGINAL module-bound _Acquire-Session scriptblock
    # reference plus the per-provider context (OpenSession op + fixed unavailability
    # reason value). No private command or $script: constant lookup happens from the
    # dynamic closure scope; the session's captured _Do-* helper refs are unchanged.
    $pctx    = @{ OpenOp=$openOp; UnavailReason=$script:UNAVAIL_REASON }
    $sbAcq   = (Get-Item function:_Acquire-Session).ScriptBlock
    $acquire = { & $sbAcq $pctx }.GetNewClosure()
    [pscustomobject]@{ Acquire=$acquire }
}

Export-ModuleMember -Function 'New-GuidanceProvider'
