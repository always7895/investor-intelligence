# Production freshness/deploy gate for the v213 owner-line worker.
#
#   -Phase pre  : BEFORE worker deployment / acceptance.
#                 Reads snapshot:current (read-only); assembly-anchor age must be
#                 <= 80% of the reader cap (5760s of 7200s). A pointer that old
#                 fails closed: fresh generate + fail-closed sync FIRST.
#   -Phase post : AFTER worker activation.
#                 (1) /v213/readiness with hex challenge must report ready and
#                     the expected worker version;
#                 (2) live pointer re-read must be fresh (<7200s);
#                 (3) a live KV readback + real reader replay (top20 loader)
#                     must return the sealed seven-field report, not a stale
#                     message;
#                 (4) immutable acceptance artifact under state/records/.
#
# No secret, tenant, or credential material is read, stored, or printed.
# Requires the cached Wrangler CLI session (same as the sync script).

[CmdletBinding()]
param(
    [ValidateSet('pre', 'post')][Parameter(Mandatory)][string]$Phase,
    [string]$WorkerVersion = '',
    [string]$RepoRoot = '',
    [string]$WorkerUrl = 'https://investor-intelligence-v21-owner-line.moon951753.workers.dev',
    [int]$CapSeconds = 7200)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Split-Path -Parent $PSScriptRoot)
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$CloudDir = Join-Path $RepoRoot 'cloud'
$NamespaceId = '96142af40b5d4213862d5483fe3a66da'
if ($CapSeconds -lt 60) { throw 'CAP_SECONDS_INVALID' }

function Read-LivePointer {
    $bytes = & npx --yes Wrangler kv key get 'snapshot:current' --namespace-id $NamespaceId --cwd $CloudDir 2>$null
    $text = (($bytes -join '')).Trim()
    if ($text -notmatch '\{') { throw 'NO_LIVE_POINTER' }
    return ($text | ConvertFrom-Json)
}

function Get-PointerAgeSeconds([object]$Pointer) {
    $raw = [string]$Pointer.public_data_as_of
    $Anchor = [DateTime]::MinValue
    if ([string]::IsNullOrWhiteSpace($raw)) { $raw = [string]$Pointer.promoted_at }
    if (-not [DateTime]::TryParse([string]$raw, [ref]$Anchor)) { throw 'ANCHOR_PARSE_FAILED' }
    if ($Anchor.Kind -ne [DateTimeKind]::Utc) { $Anchor = $Anchor.ToUniversalTime() }
    return [int]((Get-Date).ToUniversalTime() - $Anchor).TotalSeconds
}

$results = [ordered]@{
    utc = (Get-Date).ToUniversalTime().ToString('o')
    phase = $Phase
    status = 'FAIL'
    pointer = $null
    workerVersion = $WorkerVersion
    checks = @{}
}

try {
    $Pointer = Read-LivePointer
    $age = Get-PointerAgeSeconds $Pointer
    $results.pointer = [ordered]@{
        runId = [string]$Pointer.run_id
        publicDataAsOf = [string]$Pointer.public_data_as_of
        promotedAt = [string]$Pointer.promoted_at
        ageSeconds = $age
    }

    if ($Phase -eq 'pre') {
        $results.checks.asyncAnchorWithinOperableThreshold = ($age -le [int]($CapSeconds * 0.8))
        if (-not $results.checks.asyncAnchorWithinOperableThreshold) {
            throw ('DEPLOY_GATE_POINTER_STALE age={0}s; run the sealed refresh FIRST (run_production_sealed_refresh.ps1) and re-gate.' -f $age)
        }
    }
    else {
        if ([string]::IsNullOrWhiteSpace($WorkerVersion)) { throw 'WORKER_VERSION_REQUIRED' }
        $challenge = [System.Guid]::NewGuid().ToString('N')
        $readinessUrl = '{0}/v213/readiness?challenge={1}' -f $WorkerUrl, $challenge
        $readiness = (Invoke-WebRequest -Uri $readinessUrl -Method Get -UseBasicParsing -TimeoutSec 30).Content | ConvertFrom-Json
        $results.checks.readinessReady = [bool]$readiness.ready
        $results.checks.workerVersionMatch = ([string]$readiness.worker_version -eq $WorkerVersion)
        if (-not $results.checks.readinessReady -or -not $results.checks.workerVersionMatch) {
            throw ('DEPLOY_GATE_READINESS_FAIL ready={0} reported={1} expected={2}' -f $results.checks.readinessReady, [string]$readiness.worker_version, $WorkerVersion)
        }
        # Re-read after activation: activation does not refresh the pointer.
        $PostPointer = Read-LivePointer
        $postAge = Get-PointerAgeSeconds $PostPointer
        $results.pointer.runId = [string]$PostPointer.run_id
        $results.pointer.ageSeconds = $postAge
        $results.checks.pointerFreshAfterActivation = ($postAge -lt $CapSeconds)
        if (-not $results.checks.pointerFreshAfterActivation) {
            throw ('DEPLOY_GATE_POINTER_STALE_AFTER_ACTIVATION age={0}s; run a fresher sealed generate+sync and re-gate before acceptance.' -f $postAge)
        }
        # Real reader replay over live KV bytes: run the in-repo probe (exits
        # non-zero on ANY stale path) and capture its immutable result artifact.
        $ReplayTag = ('DEPLOYP' + (Get-Date -Format 'yyyyMMddHHmmss'))
        $replayLog = & npx --yes vitest run test/live-production-replay.test.ts -t $ReplayTag --passWithNoTests --root $CloudDir 2>&1 | Out-String
        $replayExit = $LASTEXITCODE
        $replayArtifact = Join-Path $CloudDir 'test-live-replay-result.json'
        $replayFresh = $false
        if (Test-Path -LiteralPath $replayArtifact) {
            $replay = Get-Content -LiteralPath $replayArtifact -Raw | ConvertFrom-Json
            $replayFresh = [bool]$replay.fresh
        }
        $results.checks.readerReplayExitZero = ($replayExit -eq 0)
        $results.checks.readerReplayFresh = $replayFresh
        if (-not $results.checks.readerReplayExitZero -or -not $replayFresh) { throw 'DEPLOY_GATE_READER_REPLAY_NOT_FRESH' }
    }
    $results.status = 'PASS'
}
catch {
    $results.failure = $_.Exception.Message
}

$recordsDir = Join-Path $RepoRoot 'state\records'
if (-not (Test-Path -LiteralPath $recordsDir)) { New-Item -ItemType Directory -Path $recordsDir -Force | Out-Null }
$artifact = Join-Path $recordsDir ('production-{0}-gate-{1}.json' -f $Phase.ToLowerInvariant(), (Get-Date -Format 'yyyyMMddHHmmss'))
($results | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $artifact -Encoding utf8
$results.artifact = $artifact

if ($results.status -eq 'PASS') {
    Write-Host ("{0} GATE = PASS {1}" -f $Phase.ToUpperInvariant(), ($results | ConvertTo-Json -Compress -Depth 6)) -ForegroundColor Green
    exit 0
}
Write-Host ('{0} GATE = FAIL {1}' -f $Phase.ToUpperInvariant(), ($results | ConvertTo-Json -Compress -Depth 6)) -ForegroundColor Red
exit 1