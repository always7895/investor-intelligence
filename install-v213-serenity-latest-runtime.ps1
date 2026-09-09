[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$RuntimeRoot = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) { $RuntimeRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime' }
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$base = Join-Path $ProjectRoot 'install-v213-source-diverse-runtime-v2.ps1'
if (-not (Test-Path -LiteralPath $base -PathType Leaf)) { throw "Missing source-diverse base runtime installer: $base" }

# A PowerShell script invocation does not own the process-level $LASTEXITCODE.
# The base installer intentionally invokes robocopy, whose successful "files
# copied" result is exit code 1.  That value can remain in $LASTEXITCODE even
# after the PowerShell installer itself completed successfully.  Errors in the
# child script already terminate through ErrorActionPreference=Stop, so success
# is established by exception-free completion plus exact runtime artifacts, not
# by a stale native-process exit code.
& $base -ProjectRoot $ProjectRoot -RuntimeRoot $RuntimeRoot
foreach ($requiredBase in @(
    'run-v213-local.ps1',
    'activate-v213-seven-field-schedule.ps1',
    'V213-SOURCE-DIVERSE-RUNTIME.json'
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRoot $requiredBase) -PathType Leaf)) {
        throw "Source-diverse base runtime installation did not produce: $requiredBase"
    }
}
$baseReceipt = Get-Content -LiteralPath (Join-Path $RuntimeRoot 'V213-SOURCE-DIVERSE-RUNTIME.json') -Raw -Encoding utf8 | ConvertFrom-Json
if ([string]$baseReceipt.product_version -ne '2.1.3' -or [string]$baseReceipt.source_independence_gate -ne 'scripts/v213_source_independence_gate_v3.py') {
    throw 'Source-diverse base runtime receipt is invalid.'
}
Write-Host 'V213_SERENITY_BASE_RUNTIME_HANDOFF = PASS; powershell_exception_free=true; stale_native_exit_code_ignored=true' -ForegroundColor Green

$copyMap = [ordered]@{
    'run-v213-local-serenity-latest.ps1' = 'run-v213-local.ps1'
    'activate-v213-seven-field-schedule.ps1' = 'activate-v213-seven-field-schedule.ps1'
    'install-v213-serenity-latest-runtime.ps1' = 'install-v213-source-diverse-runtime.ps1'
    'scripts\v213_refresh_serenity_public_sources.py' = 'scripts\v213_refresh_serenity_public_sources.py'
    'scripts\v213_serenity_latest_multisource_audit.py' = 'scripts\v213_serenity_latest_multisource_audit.py'
    'scripts\v213_tam_capture_claim_guard.py' = 'scripts\v213_tam_capture_claim_guard.py'
    'config\v213-serenity-latest-multisource-policy-v5.json' = 'config\v213-serenity-latest-multisource-policy-v5.json'
    'config\v213-serenity-methodology-lineage-v1.json' = 'config\v213-serenity-methodology-lineage-v1.json'
}
foreach ($entry in $copyMap.GetEnumerator()) {
    $source = Join-Path $ProjectRoot $entry.Key
    $destination = Join-Path $RuntimeRoot $entry.Value
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Latest multi-source runtime source is missing: $($entry.Key)" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash) {
        throw "Latest multi-source runtime copy hash mismatch: $($entry.Value)"
    }
}
$refresh = Get-Content -LiteralPath (Join-Path $RuntimeRoot 'run-v213-local.ps1') -Raw -Encoding utf8
foreach ($marker in @(
    'v213_refresh_serenity_public_sources.py',
    'v213_serenity_latest_multisource_audit.py',
    'v213_tam_capture_claim_guard.py',
    'build_v213_activation_bundle_v2.py'
)) { if (-not $refresh.Contains($marker)) { throw "Stable refresh entrypoint lost marker: $marker" } }

# The stable activation entrypoint is now the source-independence-aware wrapper.
# The legacy Serenity wrapper re-ran a strict post-bundle audit and emitted
# V213_SERENITY_LATEST_ACTIVATION_PREFLIGHT.  That path was retired because it
# incorrectly rejected safe LIMITED publications and diverged from the current
# source-federation policy.  Verify the current wrapper contract instead.
$activation = Get-Content -LiteralPath (Join-Path $RuntimeRoot 'activate-v213-seven-field-schedule.ps1') -Raw -Encoding utf8
foreach ($marker in @(
    'V213_DIVERSIFIED_SOURCE_PREFLIGHT',
    'V213_SOURCE_INDEPENDENCE_PREFLIGHT',
    'V213_MARKET_CORROBORATION_QUALITY',
    'activate-v213-seven-field-schedule-core.ps1'
)) { if (-not $activation.Contains($marker)) { throw "Stable activation entrypoint lost marker: $marker" } }
foreach ($retiredMarker in @(
    'V213_SERENITY_LATEST_ACTIVATION_PREFLIGHT',
    'v213_serenity_latest_multisource_audit.py'
)) { if ($activation.Contains($retiredMarker)) { throw "Stable activation entrypoint regressed to retired marker: $retiredMarker" } }

[ordered]@{
    schema_version = 2
    product_version = '2.1.3'
    runtime_profile = 'serenity-latest-per-ticker-multisource-v5'
    installed_utc = (Get-Date).ToUniversalTime().ToString('o')
    base_runtime_handoff = 'exception-free-plus-receipt-verified'
    stable_activation_wrapper = 'source-independence-aware-current-contract'
    retired_strict_post_bundle_audit = $false
    stale_native_exit_code_is_success_authority = $false
    preferred_model = $null
    model_selection_authority = 'runtime_model_profile'
    model_profile_qualified = $false
    latest_public_serenity_source_required = $true
    per_ticker_claim_source_families_minimum = 2
    per_ticker_claim_source_domains_minimum = 2
    per_ticker_primary_sources_minimum = 1
    market_providers_for_high_confidence = 2
    market_same_metric_basis_required = $true
    yahoo_truth_anchor = $false
    source_values_averaged = $false
    severe_thesis_killers_override_score = $true
    exact_pointer_rollback = $true
    exact_worker_rollback = $true
    official_serenity_formula_claimed = $false
    private_serenity_method_reproduced = $false
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $RuntimeRoot 'V213-SERENITY-LATEST-RUNTIME.json') -Encoding utf8
Write-Host "V213_SERENITY_LATEST_RUNTIME = PASS; path=$RuntimeRoot; policy=v5; activation=source-independence-aware" -ForegroundColor Green
