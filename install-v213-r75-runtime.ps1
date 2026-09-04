[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$RuntimeRoot = ''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
if([string]::IsNullOrWhiteSpace($RuntimeRoot)){$RuntimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime'}
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$base=Join-Path $ProjectRoot 'install-v213-serenity-latest-runtime.ps1'
if(-not(Test-Path -LiteralPath $base -PathType Leaf)){throw "Missing Serenity runtime installer: $base"}
& $base -ProjectRoot $ProjectRoot -RuntimeRoot $RuntimeRoot
if(-not$?){throw 'Base Serenity runtime installation failed.'}

$copyMap=[ordered]@{
    'activate-v213-seven-field-schedule.ps1'='activate-v213-seven-field-schedule.ps1'
    'activate-v213-seven-field-schedule-serenity-latest.ps1'='activate-v213-seven-field-schedule-serenity-latest.ps1'
    'run-v213-local-llm-bridge-source-diverse.ps1'='run-v213-local-llm-bridge.ps1'
    'run-v213-scheduled-refresh.ps1'='run-v213-scheduled-refresh.ps1'
    'register-v213-refresh-tasks.ps1'='register-v213-refresh-tasks.ps1'
    'scripts\v213_r75_activation_preflight.py'='scripts\v213_r75_activation_preflight.py'
    'scripts\v213_r75_activation_preflight_entry.py'='scripts\v213_r75_activation_preflight_entry.py'
    'scripts\run_v213_local_llm_bridge_core_v3.ps1'='scripts\run_v213_local_llm_bridge_core_v3.ps1'
    'scripts\run_v213_local_llm_bridge_core_v2.ps1'='scripts\run_v213_local_llm_bridge_core_v2.ps1'
    'scripts\run_v213_local_llm_bridge_core.ps1'='scripts\run_v213_local_llm_bridge_core.ps1'
    'scripts\v213_local_llm_gateway_r75.py'='scripts\v213_local_llm_gateway_r75.py'
    'scripts\v213_local_llm_gateway.py'='scripts\v213_local_llm_gateway.py'
    'scripts\v212_local_llm_gateway.py'='scripts\v212_local_llm_gateway.py'
}
foreach($entry in $copyMap.GetEnumerator()){
    $source=Join-Path $ProjectRoot $entry.Key
    $destination=Join-Path $RuntimeRoot $entry.Value
    if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "R75 runtime source is missing: $($entry.Key)"}
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
    if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash-ne(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash){throw "R75 runtime copy hash mismatch: $($entry.Value)"}
}
$activation=Get-Content -LiteralPath (Join-Path $RuntimeRoot 'activate-v213-seven-field-schedule.ps1') -Raw -Encoding utf8
foreach($marker in @('V213_R75_ACTIVATION_PREFLIGHT','V213_ACTIVATION_PREFLIGHT_ONLY','publication_mode_aware=true','V213_R75_SEALED_BUNDLE_SHA256')){if(-not$activation.Contains($marker)){throw "Stable R75 activation lost marker: $marker"}}
$bridge=Get-Content -LiteralPath (Join-Path $RuntimeRoot 'run-v213-local-llm-bridge.ps1') -Raw -Encoding utf8
if(-not$bridge.Contains('run_v213_local_llm_bridge_core_v3.ps1')){throw 'Stable bridge did not select the R75 safe-path core.'}
$scheduled=Get-Content -LiteralPath (Join-Path $RuntimeRoot 'run-v213-scheduled-refresh.ps1') -Raw -Encoding utf8
foreach($marker in @('-NoModelBridge','-NoTunnel','-NoSync','production_mutation=$false')){if(-not$scheduled.Contains($marker)){throw "Scheduled data-only runtime lost marker: $marker"}}
[ordered]@{
    schema_version=1
    status='PASS'
    product_version='2.1.3'
    runtime_profile='R75'
    installed_utc=(Get-Date).ToUniversalTime().ToString('o')
    runtime_root=$RuntimeRoot
    sealed_activation_bundle_preflight=$true
    publication_mode_aware=$true
    optional_bls_policy_aligned=$true
    exact_model_pin=$true
    spaced_parenthesized_source_path_supported=$true
    quick_tunnel_uptime_guarantee=$false
    scheduled_refresh_data_only=$true
    scheduled_refresh_production_mutation=$false
}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $RuntimeRoot 'V213-R75-RUNTIME.json') -Encoding utf8
Write-Host "V213_R75_RUNTIME = PASS; path=$RuntimeRoot; publication_mode_aware=true; scheduled_data_only=true" -ForegroundColor Green
