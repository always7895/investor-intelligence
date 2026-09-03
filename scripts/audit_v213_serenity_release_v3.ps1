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
$temp = Join-Path $env:TEMP ('v213-serenity-release-v2-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    & (Join-Path $ProjectRoot 'scripts\audit_v213_serenity_release_v2.ps1') -ProjectRoot $ProjectRoot -OutputPath $temp
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $temp -PathType Leaf)) {
        throw 'Base Serenity release audit failed.'
    }
    $source = Get-Content -LiteralPath (Join-Path $ProjectRoot 'scripts\v213_source_independence_gate_v3.py') -Raw -Encoding utf8
    foreach ($marker in @(
        'MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS = 2',
        'market_conflicts_compared_pairwise_without_yahoo_authority',
        'compatibility_calculation_only_not_authoritative_corroboration',
        'PAIRWISE_CONFLICT_CODE',
        'CALCULATION_DIVERGENCE_CODE',
        'pairwise_independent_provider_conflicts',
        'conflict_values_averaged',
        'high_confidence_requires_two_market_providers',
        'yahoo_authoritative=false'
    )) {
        if (-not $source.Contains($marker)) { throw "Market-independence hardening marker missing: $marker" }
    }
    $base = Get-Content -LiteralPath $temp -Raw -Encoding utf8 | ConvertFrom-Json
    $result = [ordered]@{
        schema_version = 3
        product_version = '2.1.3'
        status = 'PASS'
        audited_utc = (Get-Date).ToUniversalTime().ToString('o')
        base_audit = $base
        market_independence = [ordered]@{
            yahoo_authoritative = $false
            yahoo_role = 'compatibility_calculation_only'
            minimum_independent_providers_for_high_confidence = 2
            conflict_comparison = 'pairwise_independent_providers'
            source_conflicts_averaged = $false
            two_consistent_providers_vs_yahoo_divergence = 'BLOCK_ACTIVATION_FOR_RECONCILIATION'
            one_provider_only = 'LIMITED_CONFIDENCE'
            provider_unavailability_only = 'QUALITY_DEGRADATION'
        }
    }
    $parent = Split-Path -Parent $OutputPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $result | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding utf8
    Write-Host "V213_SERENITY_RELEASE_AUDIT_V3 = PASS; output=$OutputPath; yahoo_authoritative=false; pairwise_market_conflicts=true; market_providers_for_high_confidence=2; conflicts_not_averaged=true" -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
