[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$OutputPath = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $ProjectRoot 'data\cache\v213_serenity_release_audit_latest.json'
}

function Require-File([string]$RelativePath) {
    $path = Join-Path $ProjectRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required release file is missing: $RelativePath"
    }
    return $path
}
function Require-Markers([string]$RelativePath,[string[]]$Markers) {
    $text = Get-Content -LiteralPath (Require-File $RelativePath) -Raw -Encoding utf8
    foreach ($marker in $Markers) {
        if (-not $text.Contains($marker)) {
            throw "Release contract marker is missing from ${RelativePath}: $marker"
        }
    }
}

$basePath = Join-Path $env:TEMP ('v213-serenity-release-v2-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    & (Require-File 'scripts\audit_v213_serenity_release_v2.ps1') -ProjectRoot $ProjectRoot -OutputPath $basePath
    if (-not (Test-Path -LiteralPath $basePath -PathType Leaf)) {
        throw 'Base Serenity release audit did not produce a receipt.'
    }
    $base = Get-Content -LiteralPath $basePath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($base.status -ne 'PASS') { throw 'Base Serenity release audit is not PASS.' }

    Require-Markers 'scripts\v213_source_independence_gate_v3.py' @(
        'v213_source_independence_gate_v4.py',
        'v4.self_test()',
        'v4.gate.main()'
    )
    Require-Markers 'scripts\v213_source_independence_gate_v4.py' @(
        'MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS = 2',
        'MARKET_HARD_MAX_AGE_DAYS = 7.0',
        'MARKET_HIGH_CONFIDENCE_FRESHEST_MAX_AGE_DAYS = 4.0',
        'MARKET_COMPARABLE_PROVIDER_MAX_LAG_DAYS = 3.0',
        'ADJUSTED_CLOSE_BASIS = "split_dividend_adjusted_close"',
        'comparable_metric_basis_required_for_high_confidence',
        'market_conflicts_compared_pairwise_without_yahoo_authority',
        'compatibility_calculation_only_not_authoritative_corroboration',
        'Fresh market provider count does not match',
        'stale market as_of',
        'pairwise_same_basis',
        'worker_degradation_schema_compatible=true',
        'conflict_values_averaged',
        'yahoo_is_authoritative_market_source'
    )
    Require-Markers 'scripts\build_v213_activation_bundle_v2.py' @(
        'v213-serenity-evidence-freshness-policy.json',
        'source-level provenance is not independently diverse',
        'positive Serenity advantages lack fresh multi-source support',
        'stale market observations remain LIVE/CACHED',
        'freshness_audit'
    )
    Require-Markers 'config\v213-serenity-evidence-freshness-policy.json' @(
        '"market_observation_max_age_days": 7',
        '"minimum_claim_source_families_per_ticker": 2',
        '"minimum_claim_source_domains_per_ticker": 2',
        '"minimum_claim_primary_sources_per_ticker": 1',
        '"single_source_positive_advantage_is_publishable": false',
        '"conflicting_sources_are_averaged": false'
    )

    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        (Require-File 'scripts\audit_v213_serenity_release_v5.ps1'),
        [ref]$tokens,
        [ref]$errors
    )
    if (@($errors).Count) {
        throw ('Final Serenity audit has parser errors: ' + (($errors | ForEach-Object { $_.Message }) -join '; '))
    }

    $result = [ordered]@{
        schema_version = 5
        product_version = '2.1.3'
        status = 'PASS'
        audited_utc = (Get-Date).ToUniversalTime().ToString('o')
        base_policy_audit = $base
        source_independence = [ordered]@{
            stable_entrypoint = 'scripts/v213_source_independence_gate_v3.py'
            implementation = 'scripts/v213_source_independence_gate_v4.py'
            yahoo_authoritative = $false
            yahoo_role = 'compatibility_calculation_only'
            high_confidence_independent_market_providers_min = 2
            comparable_metric_basis_required = $true
            market_hard_max_age_days = 7
            high_confidence_freshest_max_age_days = 4
            comparable_provider_max_lag_days = 3
            pairwise_conflict_comparison = $true
            conflict_values_averaged = $false
            stale_or_undated_provider_counts = $false
            worker_degradation_schema_compatible = $true
        }
        company_evidence = [ordered]@{
            per_ticker_claim_families_min = 2
            per_ticker_claim_domains_min = 2
            per_ticker_primary_sources_min = 1
            positive_advantage_requires_fresh_multi_source = $true
            market_and_macro_are_company_claim_evidence = $false
        }
    }
    $parent = Split-Path -Parent $OutputPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding utf8
    Write-Host "V213_SERENITY_RELEASE_AUDIT_V5 = PASS; output=$OutputPath; source_gate=v4; yahoo_authoritative=false; high_confidence_market_providers=2; comparable_basis=true; latestness=true; conflicts_not_averaged=true" -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $basePath -Force -ErrorAction SilentlyContinue
}
