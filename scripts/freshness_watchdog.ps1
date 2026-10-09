# Read-only pointer/report observation through the shared locked-CLI adapter.
# CLI/auth/parse failure is UNKNOWN, never an old FRESH or measured STALE.
[CmdletBinding()]
param([string]$RepoRoot = '', [int]$CapSeconds = 7200)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$raw = $null
$nativeExit = $null
$record = $null
$logPath = $null
$exitCode = 1
$entry = [ordered]@{
    utc = [DateTime]::UtcNow.ToString('o'); status = 'UNKNOWN'; run_id = ''; anchor = ''
    ageSeconds = $null; capSeconds = $CapSeconds; note = ''; top20State = 'UNKNOWN'
    reportAgeSeconds = $null; errorCategory = 'UNKNOWN'; failedPhase = 'ROOT'
    cliAttempts = 0; cliExitCode = $null; secondaryError = ''
}
function Assert-PlainLocalPath([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:[\\/]' -or $Path -match '[\x00-\x1f]') { throw 'UNSAFE_ROOT' }
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'UNSAFE_ROOT' }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
function Test-OutcomeInteger([object]$Value, [long]$Minimum, [long]$Maximum) {
    # ConvertFrom-Json supports Int32/Int64 on the admitted hosts. No coercion:
    # Boolean, strings, Decimal/Double and out-of-range BigInteger are not integers here.
    if ($Value -isnot [int32] -and $Value -isnot [int64]) { return $false }
    return ($Value -ge $Minimum -and $Value -le $Maximum)
}
function ConvertTo-UtcAnchor([object]$Value) {
    if ($Value -is [DateTime]) {
        if ($Value.Kind -eq [DateTimeKind]::Local) { return $Value.ToUniversalTime() }
        return [DateTime]::SpecifyKind($Value, [DateTimeKind]::Utc)
    }
    if ($Value -isnot [string] -or $Value -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$') { return $null }
    $parsed = [DateTime]::MinValue
    $styles = [Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal
    if (-not [DateTime]::TryParse($Value, [Globalization.CultureInfo]::InvariantCulture, $styles, [ref]$parsed)) { return $null }
    return $parsed
}
try {
    $RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
    Assert-PlainLocalPath $RepoRoot
    $cacheDir = Join-Path $RepoRoot 'data\cache'
    Assert-PlainLocalPath $cacheDir
    New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
    $logPath = Join-Path $cacheDir 'freshness-watch.jsonl'
    Assert-PlainLocalPath $logPath
    $entry.failedPhase = 'POLICY'
    if ($CapSeconds -lt 60) { throw 'CAP_SECONDS_INVALID' }
    $policy = Get-Content -LiteralPath (Join-Path $RepoRoot 'config/v213-top20-report-freshness-v1.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $reportHours = [double]$policy.report_max_age_hours
    if ([double]::IsNaN($reportHours) -or [double]::IsInfinity($reportHours) -or $reportHours -lt 1 -or $reportHours -gt 24) { throw 'REPORT_POLICY_INVALID' }
    $reportCap = $reportHours * 3600
    $entry.failedPhase = 'CLI_ADAPTER'
    $helper = Join-Path $RepoRoot 'scripts/sync_sealed_snapshot_kv.py'
    Assert-PlainLocalPath $helper
    $resultPath = Join-Path $cacheDir ('freshness-read-' + [guid]::NewGuid().ToString('N') + '.json')
    $python = if ($env:PROJECT_PYTHON) { $env:PROJECT_PYTHON } else { 'python' }
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        # Native commands update the global automatic variable. Clear/read that
        # same scope immediately; do not create a local LASTEXITCODE shadow.
        $global:LASTEXITCODE = $null
        & $python $helper --read-freshness --outcome-path $resultPath 2>$null | Out-Null
        $nativeExit = $global:LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
        $entry.errorCategory = 'CLI_ADAPTER_UNAVAILABLE'
        throw 'NO_SAFE_OUTCOME'
    }
    Assert-PlainLocalPath $resultPath
    if ((Get-Item -LiteralPath $resultPath).Length -gt 8192) { throw 'OUTCOME_INVALID' }
    # Not raw CLI stdout: the shared adapter checked the native exit before
    # parsing any KV body and persisted only whitelist metadata, even on failure.
    $record = Get-Content -LiteralPath $resultPath -Raw -Encoding utf8 | ConvertFrom-Json
    $categories = @('NONE','AUTHENTICATION_ERROR','DAILY_KV_LIMIT','NETWORK_FAILURE','TRANSIENT_HTTP','TIMEOUT','UNKNOWN','CLI_UNAVAILABLE','CLI_LAUNCH_FAILED','PARSE_FAILED','LOCAL_IO_FAILURE','OUTCOME_WRITE_FAILED')
    $phases = @('INPUT','POINTER_READ','POINTER_PARSE','REPORT_READ','REPORT_PARSE','COMPLETE')
    if (-not (Test-OutcomeInteger $record.schema_version 1 1) -or $record.operation -cne 'WATCHDOG' -or $record.status -cnotin @('SUCCEEDED','FAILED') -or
        $record.error_category -cnotin $categories -or $record.phase -cnotin $phases -or
        -not (Test-OutcomeInteger $record.cli_attempts_total 0 6) -or
        -not (Test-OutcomeInteger $record.last_cli_attempts 0 3) -or
        $record.last_cli_attempts -gt $record.cli_attempts_total -or
        -not (Test-OutcomeInteger $record.objects_uploaded 0 0) -or
        -not (Test-OutcomeInteger $record.objects_reused 0 0) -or
        -not (Test-OutcomeInteger $record.objects_verified 0 0) -or
        ($null -ne $record.last_cli_exit_code -and -not (Test-OutcomeInteger $record.last_cli_exit_code -2147483648 4294967295))) { throw 'OUTCOME_INVALID' }
    $entry.errorCategory = $record.error_category
    $entry.failedPhase = $record.phase
    $entry.cliAttempts = $record.cli_attempts_total
    $entry.cliExitCode = $record.last_cli_exit_code
    if ($nativeExit -ne 0 -or $record.status -cne 'SUCCEEDED' -or $record.error_category -cne 'NONE') {
        if ($entry.errorCategory -eq 'NONE') { $entry.errorCategory = 'UNKNOWN' }
        $entry.note = 'READ_UNAVAILABLE'
    } else {
        $entry.failedPhase = 'METADATA'
        if ($record.run_id -cnotmatch '^\d{8}T\d{6}Z-[0-9a-f]{12}$' -or $record.top20_state -cnotmatch '^(INSUFFICIENT|RECORDS_[0-9]{1,6})$') { throw 'OUTCOME_INVALID' }
        $anchor = ConvertTo-UtcAnchor $record.anchor
        if ($null -eq $anchor) { throw 'ANCHOR_PARSE_FAILED' }
        $entry.run_id = $record.run_id
        $entry.anchor = $anchor.ToString('o')
        $entry.ageSeconds = [int]([DateTime]::UtcNow - $anchor).TotalSeconds
        $entry.top20State = $record.top20_state
        $entry.failedPhase = ''
        $exitCode = 0
        if ($entry.ageSeconds -lt -300) { $entry.status = 'CLOCK_ANOMALY'; $exitCode = 3 }
        elseif ($entry.ageSeconds -gt $CapSeconds) { $entry.status = 'STALE'; $exitCode = 3 }
        elseif ($entry.ageSeconds -gt [int]($CapSeconds * 0.8)) { $entry.status = 'AT_RISK' }
        else { $entry.status = 'FRESH' }
        if ($record.top20_state -eq 'INSUFFICIENT' -or $record.top20_state -ne 'RECORDS_20') {
            $entry.note = 'TOP20_UNAVAILABLE'
            if ($exitCode -eq 0) { $entry.status = 'UNAVAILABLE'; $exitCode = 1 }
        } else {
            $generated = ConvertTo-UtcAnchor $record.report_generated_at
            if ($null -eq $generated) { throw 'REPORT_PARSE_FAILED' }
            $entry.reportAgeSeconds = [int]([DateTime]::UtcNow - $generated).TotalSeconds
            if ($entry.reportAgeSeconds -lt -300) { $entry.status = 'CLOCK_ANOMALY'; $exitCode = 3 }
            elseif ($entry.reportAgeSeconds -gt $reportCap) { $entry.status = 'STALE'; $entry.note = 'REPORT_AGE_EXCEEDED'; $exitCode = 3 }
        }
    }
} catch {
    # Fixed branch identifiers only; exception messages/types and CLI text are not logged.
    $entry.status = 'UNKNOWN'
    $entry.note = 'OBSERVATION_FAILED'
    if ($entry.errorCategory -eq 'NONE' -or $entry.errorCategory -eq 'UNKNOWN') { $entry.errorCategory = 'OBSERVATION_FAILED' }
    $exitCode = 1
}
if ($null -ne $logPath) {
    try { Add-Content -LiteralPath $logPath -Value ($entry | ConvertTo-Json -Compress) -Encoding utf8 }
    catch { $entry.secondaryError = 'STATUS_WRITE_FAILED'; $exitCode = 1 }
}
# Always emit a sanitized structured status, including when durable storage is unavailable.
Write-Host ('FRESHNESS_WATCH ' + ($entry | ConvertTo-Json -Compress))
exit $exitCode
