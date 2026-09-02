[CmdletBinding()]
param(
    [string]$ProjectRoot='',
    [string]$RuntimeRoot=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
if([string]::IsNullOrWhiteSpace($RuntimeRoot)){$RuntimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime'}
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$base=Join-Path $ProjectRoot 'install-v213-runtime.ps1'
if(-not(Test-Path -LiteralPath $base -PathType Leaf)){throw "Missing base runtime installer: $base"}
& $base -ProjectRoot $ProjectRoot -RuntimeRoot $RuntimeRoot
if(-not(Test-Path -LiteralPath (Join-Path $RuntimeRoot 'run-v213-local.ps1') -PathType Leaf)){throw 'Base runtime install did not produce run-v213-local.ps1.'}

$copyMap=[ordered]@{
    'run-v213-local-source-diverse.ps1'='run-v213-local.ps1'
    'run-v213-local-llm-bridge-source-diverse.ps1'='run-v213-local-llm-bridge.ps1'
    'scripts\run_v213_local_llm_bridge_core.ps1'='scripts\run_v213_local_llm_bridge_core.ps1'
    'scripts\run_v213_local_llm_bridge_core_v2.ps1'='scripts\run_v213_local_llm_bridge_core_v2.ps1'
    'scripts\v213_local_llm_gateway.py'='scripts\v213_local_llm_gateway.py'
    'scripts\v213_source_independence_gate.py'='scripts\v213_source_independence_gate.py'
    'scripts\v213_source_independence_gate_v2.py'='scripts\v213_source_independence_gate_v2.py'
    'scripts\v213_source_independence_gate_v3.py'='scripts\v213_source_independence_gate_v3.py'
    'config\v213-serenity-public-logic-policy.json'='config\v213-serenity-public-logic-policy.json'
    'config\v213-market-corroboration-degradation-policy.json'='config\v213-market-corroboration-degradation-policy.json'
    'config\v213-source-diversity-field-labels.zh-en.json'='config\v213-source-diversity-field-labels.zh-en.json'
    'scripts\audit_v213_source_diversity_fields.py'='scripts\audit_v213_source_diversity_fields.py'
    'scripts\v213_methodology_and_source_audit.py'='scripts\v213_methodology_and_source_audit.py'
    'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.zh-TW.md'='docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.zh-TW.md'
    'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.en.md'='docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.en.md'
    'activate-v213-seven-field-schedule.ps1'='activate-v213-seven-field-schedule.ps1'
    'install-v213-source-diverse-runtime-v2.ps1'='install-v213-source-diverse-runtime.ps1'
}
foreach($entry in $copyMap.GetEnumerator()){
    $source=Join-Path $ProjectRoot $entry.Key
    $destination=Join-Path $RuntimeRoot $entry.Value
    if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "Required source-diverse runtime file is missing: $($entry.Key)"}
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
    $sourceHash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    $destinationHash=(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
    if($sourceHash-ne$destinationHash){throw "Stable runtime copy hash mismatch: $($entry.Value)"}
}
[ordered]@{
    schema_version=3
    product_version='2.1.3'
    runtime_profile='source-diverse-exact-model-health-schema2-market-quality-aware'
    installed_utc=(Get-Date).ToUniversalTime().ToString('o')
    preferred_model='RVN-Q6_K-multilingual-mtp'
    health_schema_version=2
    source_independence_gate='scripts/v213_source_independence_gate_v3.py'
    source_policy='config/v213-serenity-public-logic-policy.json'
    market_quality_policy='config/v213-market-corroboration-degradation-policy.json'
    market_endpoint_unavailability_is_global_blocker=$false
    market_corroboration_required_for_high_confidence_inference=$true
    uncorroborated_valuation_factor_max=3.75
    provider_failures_disclosed=$true
    source_conflicts_averaged=$false
    source_field_labels='config/v213-source-diversity-field-labels.zh-en.json'
    official_serenity_formula_claimed=$false
    private_serenity_method_reproduced=$false
}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $RuntimeRoot 'V213-SOURCE-DIVERSE-RUNTIME.json') -Encoding utf8
Write-Host "V213_SOURCE_DIVERSE_RUNTIME = PASS; path=$RuntimeRoot; source_gate=v3; market_quality_policy=v1" -ForegroundColor Green
