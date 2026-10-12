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
#                     must return the sealed seven-field report within the
#                     report-age bound (config/v213-top20-report-freshness-v1.json)
#                     and, with -ExpectTop20Records N, exactly N records. The
#                     sealed INSUFFICIENT refusal (macro overview sealed) passes
#                     only when no records are expected;
#                 (4) immutable acceptance artifact under state/records/,
#                     including the deployed Wrangler config path and sha256.
#
# No secret, tenant, or credential material is read, stored, or printed.
# Requires the cached Wrangler CLI session (same as the sync script).
# -Phase post takes the Worker origin from -WorkerUrl or from public_snapshot_endpoint of the local Worker configuration
# (-WorkerConfigPath, default under %LOCALAPPDATA%); the repository names no origin, because its workers.dev label is the
# operator's Cloudflare account.

[CmdletBinding()]
param(
    [ValidateSet('pre', 'post')][Parameter(Mandatory)][string]$Phase,
    [string]$WorkerVersion = '',
    [string]$RepoRoot = '',
    [string]$WorkerUrl = '',
    [string]$WorkerConfigPath = '',
    [int]$CapSeconds = 7200,
    [int]$ExpectTop20Records = 0,
    [string]$WranglerConfig = 'wrangler.v213.production.local.toml')

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

# Locked local CLIs of cloud/ only (the rule of sync_sealed_snapshot_kv._cli_command): the version declared in
# cloud/package.json, the lock's version and the installed package's version must be equal, and Node must exist
# (PROJECT_NODE, NODE_FOR_RUNNER or node on PATH). Never `npx --yes`: from the repository root it downloads the latest
# registry package and runs it with the cached Production session. Resolved before any Production read.
# The files are read as dictionaries: npm keeps the root package under the empty key "" of `packages` (lockfile v2 and
# v3), and ConvertFrom-Json refuses an empty property name in both hosts, so PowerShell 7 uses -AsHashtable and Windows
# PowerShell 5.1 the .NET Framework serializer. A missing key fails the lookup and refuses.
function Get-LockedNodeCli([string]$Package, [string]$Entry) {
    function Read-JsonDictionary([string]$Path) {
        $text = Get-Content -LiteralPath $Path -Raw -Encoding utf8
        if ($PSVersionTable.PSVersion.Major -ge 6) { return , ($text | ConvertFrom-Json -AsHashtable) }
        Add-Type -AssemblyName System.Web.Extensions
        $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $serializer.MaxJsonLength = [int]::MaxValue
        return , $serializer.DeserializeObject($text)
    }
    try {
        $declared = [string](Read-JsonDictionary (Join-Path $CloudDir 'package.json'))['devDependencies'][$Package]
        $locked = [string](Read-JsonDictionary (Join-Path $CloudDir 'package-lock.json'))['packages']["node_modules/$Package"]['version']
        $dir = Join-Path (Join-Path $CloudDir 'node_modules') $Package
        $installed = [string](Read-JsonDictionary (Join-Path $dir 'package.json'))['version']
    } catch { throw "LOCKED_CLI_UNAVAILABLE $Package" }
    $exe = @($env:PROJECT_NODE, $env:NODE_FOR_RUNNER) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1
    if (-not $exe) {
        $found = Get-Command node -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { $exe = $found.Source }
    }
    $cli = Join-Path $dir $Entry
    if (-not $exe -or -not (Test-Path -LiteralPath $exe -PathType Leaf) -or -not (Test-Path -LiteralPath $cli -PathType Leaf) -or
        [string]::IsNullOrEmpty($locked) -or $declared -cne $locked -or $installed -cne $locked) { throw "LOCKED_CLI_UNAVAILABLE $Package" }
    return @([IO.Path]::GetFullPath($exe), $cli)
}
$node, $wrangler = Get-LockedNodeCli 'wrangler' 'bin/wrangler.js'
$vitest = if ($Phase -eq 'post') { (Get-LockedNodeCli 'vitest' 'vitest.mjs')[1] } else { $null }

# The Worker origin of -Phase post: -WorkerUrl, else public_snapshot_endpoint of the local Worker configuration (the file the
# setup and relay scripts use). Only an HTTPS workers.dev origin on the default port without user info is accepted (the
# rule of v213_free_relay.ps1); path and query are dropped. Resolved before any Production read.
function Resolve-WorkerOrigin([string]$Explicit, [string]$ConfigPath) {
    $value = $Explicit
    if ([string]::IsNullOrWhiteSpace($value)) {
        if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
            if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'WORKER_URL_UNAVAILABLE' }
            $ConfigPath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v21-owner-line.local.json'
        }
        try { $property = (Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8 | ConvertFrom-Json).PSObject.Properties['public_snapshot_endpoint'] }
        catch { throw 'WORKER_URL_UNAVAILABLE' }
        if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) { throw 'WORKER_URL_UNAVAILABLE' }
        $value = [string]$property.Value
    }
    $uri = $null
    if (-not [uri]::TryCreate($value.Trim(), [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -cne 'https' -or $uri.UserInfo -or
        -not $uri.IsDefaultPort -or $uri.Host -notmatch '^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.workers\.dev$') { throw 'WORKER_URL_INVALID' }
    return $uri.GetLeftPart([UriPartial]::Authority)
}
if ($Phase -eq 'post') { $WorkerUrl = Resolve-WorkerOrigin $WorkerUrl $WorkerConfigPath }

function Read-LivePointer {
    # Read-only. Wrangler 4 KV commands default to the local Miniflare store; the gate must read Production.
    $bytes = & $node $wrangler kv key get 'snapshot:current' --namespace-id $NamespaceId --remote --cwd $CloudDir 2>$null
    $text = (($bytes -join '')).Trim()
    if ($text -notmatch '\{') { throw 'NO_LIVE_POINTER' }
    return ($text | ConvertFrom-Json)
}

# Read-only exact-byte copy of the Production sealed snapshot (scripts/fetch_live_public_snapshot.py).
function Save-LiveSnapshot([object]$Pointer, [string]$Dir) {
    $python = if ($env:PROJECT_PYTHON) { $env:PROJECT_PYTHON } else { 'python' }
    $copy = & $python (Join-Path (Join-Path $RepoRoot 'scripts') 'fetch_live_public_snapshot.py') --out $Dir 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw ('LIVE_SNAPSHOT_COPY_FAILED ' + $copy.Trim()) }
    $copied = $copy | ConvertFrom-Json
    if ([string]$copied.run_id -ne [string]$Pointer.run_id) { throw 'LIVE_POINTER_MOVED_DURING_COPY' }
}

# Pointer anchors are UTC ISO-8601. PowerShell 7 ConvertFrom-Json already yields a DateTime whose string form
# drops the zone, so never re-parse that string; an unzoned value is UTC by contract.
function ConvertTo-UtcAnchor([object]$Value) {
    if ($null -eq $Value) { return $null }
    if ($Value -is [DateTime]) {
        if ($Value.Kind -eq [DateTimeKind]::Local) { return $Value.ToUniversalTime() }
        return [DateTime]::SpecifyKind($Value, [DateTimeKind]::Utc)
    }
    if ([string]::IsNullOrWhiteSpace([string]$Value)) { return $null }
    $parsed = [DateTime]::MinValue
    $styles = [Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal
    if (-not [DateTime]::TryParse([string]$Value, [Globalization.CultureInfo]::InvariantCulture, $styles, [ref]$parsed)) { return $null }
    return $parsed
}

# State-aware replay acceptance: 'PASS', 'PASS_INSUFFICIENT' or a failure reason.
function Test-ReplayAcceptance([object]$Replay, [string]$RunId, [int]$ExpectTop20Records, [double]$ReportMaxAgeSeconds) {
    if ($null -eq $Replay) { return 'REPLAY_RESULT_MISSING' }
    if ([string]$Replay.reader_contract_version -ne 'v213-reader-replay-v4') { return 'READER_CONTRACT_VERSION' }
    if ([string]$Replay.run_id -ne $RunId -or [string]$Replay.integrity -ne 'sealed') { return 'REPLAY_RUN_MISMATCH' }
    # A sealed index that names a machine binding the machine loader cannot read is never deployable (ABSENT: no binding).
    if ([string]$Replay.guidance_machine_probe -eq 'REFUSED') { return 'GUIDANCE_MACHINE_BINDING' }
    if ([bool]$Replay.fresh) {
        if ($ExpectTop20Records -gt 0 -and [int]$Replay.top20_records -ne $ExpectTop20Records) {
            return ('TOP20_RECORDS {0} expected {1}' -f [int]$Replay.top20_records, $ExpectTop20Records)
        }
        $generated = ConvertTo-UtcAnchor $Replay.report_generated_at
        if ($null -eq $generated) { return 'REPORT_GENERATED_AT_INVALID' }
        $reportAge = ((Get-Date).ToUniversalTime() - $generated).TotalSeconds
        if ($reportAge -gt $ReportMaxAgeSeconds -or $reportAge -lt -300) { return ('REPORT_AGE {0}s' -f [int]$reportAge) }
        return 'PASS'
    }
    if ($ExpectTop20Records -gt 0) { return 'TOP20_NOT_FRESH' }
    if ([bool]$Replay.refusal_is_insufficient -and [bool]$Replay.macro_overview_sealed) { return 'PASS_INSUFFICIENT' }
    return 'READER_REPLAY_NOT_FRESH'
}

function Get-PointerAgeSeconds([object]$Pointer) {
    $Anchor = ConvertTo-UtcAnchor $Pointer.public_data_as_of
    if ($null -eq $Anchor) { $Anchor = ConvertTo-UtcAnchor $Pointer.promoted_at }
    if ($null -eq $Anchor) { throw 'ANCHOR_PARSE_FAILED' }
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
        # The receipt names the deployed config (the UserData copy has other bounds and must never be deployed).
        $configPath = Join-Path $CloudDir $WranglerConfig
        $results.deployConfig = [ordered]@{ path = $WranglerConfig
            sha256 = $(if (Test-Path -LiteralPath $configPath) { (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }) }
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
        # Real reader replay over live KV bytes: copy the Production pointer, seal and sealed objects (read-only)
        # and run the actual readers over them. The result file is written by this run only; a missing or
        # leftover file can never pass (the old probe read a file no test wrote any more).
        $replayDir = Join-Path ([IO.Path]::GetTempPath()) ('ii-live-replay-' + [Guid]::NewGuid().ToString('N'))
        $replayArtifact = Join-Path $replayDir 'result.json'
        Save-LiveSnapshot $PostPointer $replayDir
        $env:V213_LIVE_REPLAY_DIR = $replayDir
        $env:V213_LIVE_REPLAY_OUT = $replayArtifact
        $env:V213_LIVE_REPLAY_MAX_AGE = [string]$CapSeconds
        try { $replayLog = & $node $vitest run test/live-kv-replay.test.ts --root $CloudDir 2>&1 | Out-String; $replayExit = $LASTEXITCODE }
        finally { Remove-Item Env:V213_LIVE_REPLAY_DIR, Env:V213_LIVE_REPLAY_OUT, Env:V213_LIVE_REPLAY_MAX_AGE -ErrorAction SilentlyContinue }
        $replay = $null
        if (Test-Path -LiteralPath $replayArtifact) {
            $replay = Get-Content -LiteralPath $replayArtifact -Raw -Encoding utf8 | ConvertFrom-Json
            $gmp = $replay.PSObject.Properties['guidance_machine_probe']
            $results.replay = [ordered]@{ runId = [string]$replay.run_id; fresh = [bool]$replay.fresh; refusal = [string]$replay.refusal
                readerContractVersion = [string]$replay.reader_contract_version; top20Records = [int]$replay.top20_records
                reportGeneratedAt = [string]$replay.report_generated_at; testOnlyAdmission = $replay.test_only_admission
                macroOverviewSealed = [bool]$replay.macro_overview_sealed; potentialRankingRecords = [int]$replay.potential_ranking_records
                guidanceMachineProbe = $(if ($null -ne $gmp) { [string]$gmp.Value } else { $null }) }
        }
        Remove-Item -LiteralPath $replayDir -Recurse -Force -ErrorAction SilentlyContinue
        $reportMaxAge = [double]((Get-Content -LiteralPath (Join-Path $RepoRoot 'config\v213-top20-report-freshness-v1.json') -Raw |
            ConvertFrom-Json).report_max_age_hours) * 3600
        $acceptance = Test-ReplayAcceptance $replay ([string]$PostPointer.run_id) $ExpectTop20Records $reportMaxAge
        $results.checks.readerReplayExitZero = ($replayExit -eq 0)
        $results.checks.readerReplayAccepted = $acceptance
        if (-not $results.checks.readerReplayExitZero -or $acceptance -notlike 'PASS*') { throw ('DEPLOY_GATE_READER_REPLAY_REJECTED ' + $acceptance) }
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