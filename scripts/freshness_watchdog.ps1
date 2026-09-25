# Read-only freshness watchdog for the InvestorIntelligenceV213 public pointer.
#
# Contract (production-safety):
#   * NEVER writes to any KV namespace; NEVER Promotes, rolls back, or re-seals.
#   * Reads snapshot:current via the cached Wrangler CLI session (network only).
#   * Computes the ASSEMBLY anchor age (public_data_as_of) against the 7200s
#     reader cap and appends one durable line per run to
#     data/cache/freshness-watch.jsonl (append-only transition record).
#   * Exit code is always 0 for logging-type failures; a NON-ZERO (3) exit is
#     reserved for STALE detection so Task Scheduler LastTaskResult becomes the
#     alert signal. No secret, tenant, or credential material is read or printed.

[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$CapSeconds = 7200)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$cacheDir = Join-Path $RepoRoot 'data\cache'
if (-not (Test-Path -LiteralPath $cacheDir)) {
    New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
}
$logPath = Join-Path $cacheDir 'freshness-watch.jsonl'

$namespaceId = '96142af40b5d4213862d5483fe3a66da'

# Pointer anchors are UTC ISO-8601. PowerShell 7 ConvertFrom-Json already yields a DateTime whose string form
# drops the zone, so never re-parse that string; an unzoned value is UTC by contract (same as the deploy gate).
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
if ($CapSeconds -lt 60) { throw 'CAP_SECONDS_INVALID' }

$entry = [ordered]@{
    utc        = (Get-Date).ToUniversalTime().ToString('o')
    status     = 'UNKNOWN'
    run_id     = ''
    anchor     = ''
    ageSeconds = $null
    capSeconds = $CapSeconds
    note       = ''
}

try {
    # Wrangler 4 KV commands default to the local Miniflare store; the watchdog must read Production.
    $raw = & npx --yes wrangler kv key get 'snapshot:current' --namespace-id $namespaceId --remote --cwd (Join-Path $RepoRoot 'cloud') 2>$null
    if ($null -eq $raw -or $raw -is [string] -and -not $raw) { $raw = $null }
} catch {
    $entry.note = 'WRANGLER_READ_FAILED'
}

$rawText = ($raw -join '').Trim()
if ($rawText -match '\{') {
    try {
        $pointer = $rawText | ConvertFrom-Json
        $entry.run_id = [string]$pointer.run_id
        $anchor = ConvertTo-UtcAnchor $pointer.public_data_as_of
        if ($null -eq $anchor) { $anchor = ConvertTo-UtcAnchor $pointer.promoted_at }
        if ($null -ne $anchor) {
            $anchorRaw = $anchor.ToString('o')
            $age = [int]((Get-Date).ToUniversalTime() - $anchor).TotalSeconds
            $entry.anchor = $anchorRaw
            $entry.ageSeconds = $age
            if ($age -lt -300) {
                $entry.status = 'CLOCK_ANOMALY'
                $entry.note = 'anchor in future beyond 300s skew; no product mutation performed'
            }
            elseif ($age -le [int]($CapSeconds * 0.8)) {
                $entry.status = 'FRESH'
            }
            elseif ($age -le $CapSeconds) {
                $entry.status = 'AT_RISK'
            }
            else {
                $entry.status = 'STALE'
                $entry.note = 'pointer exceeds reader cap; Top20 fails until the next healthy automated re-point'
            }
        }
        else {
            $entry.note = 'ANCHOR_PARSE_FAILED'
        }
    }
    catch {
        $entry.note = 'POINTER_PARSE_FAILED'
    }
}
else {
    if ($entry.note -eq '') { $entry.note = 'NO_POINTER_READ' }
}

$line = ($entry | ConvertTo-Json -Compress)
Add-Content -LiteralPath $logPath -Value $line -Encoding utf8

$exitCode = 0
if ($entry.status -eq 'STALE' -or $entry.status -eq 'CLOCK_ANOMALY') { $exitCode = 3 }
Write-Host ("FRESHNESS_WATCH {0} run={1} anchor={2} age={3}s" -f $entry.status, $entry.run_id, $entry.anchor, $entry.ageSeconds)
exit $exitCode