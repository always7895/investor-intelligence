[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$RuntimeRoot = ''
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$baseRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
if([string]::IsNullOrWhiteSpace($RuntimeRoot)){$RuntimeRoot=Join-Path $baseRoot 'V213Runtime'}
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$refs=Join-Path $ProjectRoot 'VERSION-REFS.json'
if(-not(Test-Path -LiteralPath $refs -PathType Leaf)){
    $hotfixRefs=Join-Path $ProjectRoot 'HOTFIX-REFS.json'
    if(-not(Test-Path -LiteralPath $hotfixRefs -PathType Leaf)){throw 'Package identity is missing (VERSION-REFS.json or HOTFIX-REFS.json required).'}
    $identity=Get-Content -LiteralPath $hotfixRefs -Raw -Encoding utf8|ConvertFrom-Json
    if($identity.artifact_kind-ne'R75_FREE_WORKERS_RELAY_HOTFIX'-or $identity.package_version-ne'2.1.3'-or
       $identity.source_commit-notmatch'^[0-9a-f]{40}$'-or [string]$identity.workflow_run_id-notmatch'^\d+$'-or
       $identity.production_mutation_by_ci-ne$false){throw 'R75 FREE_RELAY package identity is invalid.'}
}
New-Item -ItemType Directory -Force -Path $baseRoot,$RuntimeRoot|Out-Null

$sameRoot=$ProjectRoot.TrimEnd('\')-eq$RuntimeRoot.TrimEnd('\')
if(-not$sameRoot){
    $robocopy=(Get-Command robocopy.exe -ErrorAction Stop).Source
    & $robocopy $ProjectRoot $RuntimeRoot /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XD '.git' 'versions' 'cloud\node_modules' '.venv-v213-local' '.npm-cache'
    $code=$LASTEXITCODE
    if($code-gt7){throw "Runtime copy failed with robocopy exit code $code."}
}else{
    Write-Host "V213_RUNTIME_SOURCE = IN_PLACE; path=$RuntimeRoot" -ForegroundColor DarkGray
}

# Canonicalize the source-diverse entrypoints inside the stable runtime. This is
# executed inside the activation core's rollback scope, so a missing or invalid
# overlay prevents Production from remaining on an unverified deployment.
$overlayMap=[ordered]@{
    'run-v213-local-llm-bridge-source-diverse.ps1'='run-v213-local-llm-bridge.ps1'
    'install-v213-source-diverse-runtime-v2.ps1'='install-v213-source-diverse-runtime.ps1'
}
foreach($entry in $overlayMap.GetEnumerator()){
    $source=Join-Path $RuntimeRoot $entry.Key
    $destination=Join-Path $RuntimeRoot $entry.Value
    if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "Source-diverse runtime overlay is missing: $($entry.Key)"}
    if($source-ine$destination){Copy-Item -LiteralPath $source -Destination $destination -Force}
    if(-not(Test-Path -LiteralPath $destination -PathType Leaf)){throw "Source-diverse canonical entrypoint was not created: $($entry.Value)"}
    if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash-ne(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash){
        throw "Source-diverse runtime overlay hash mismatch: $($entry.Value)"
    }
}

$required=@(
    'run-v213-local.ps1',
    'run-v213-local-llm-bridge.ps1',
    'activate-v213-seven-field-schedule.ps1',
    'activate-v213-seven-field-schedule-core.ps1',
    'activate-v213-diversified-schedule.ps1',
    'sync-v213-top20-report.ps1',
    'register-v213-refresh-tasks.ps1',
    'install-v213-source-diverse-runtime.ps1',
    'InvestorIntelligence.exe',
    'config\v213-source-federation-policy.json',
    'config\v213-serenity-evidence-standard-v3.json',
    'config\v213-serenity-public-logic-policy.json',
    'config\v213-market-corroboration-degradation-policy.json',
    'config\v213-source-diversity-field-labels.zh-en.json',
    'config\authoritative-sources\v213-runtime-extensions.json',
    'scripts\v213_source_federation.py',
    'scripts\v213_source_federation_gate.py',
    'scripts\v213_apply_diversified_operationalization.py',
    'scripts\v213_build_v21_public_snapshot.py',
    'scripts\build_v213_activation_bundle_v2.py',
    'sync-v213-activation-bundle.ps1',
    'scripts\v213_pipeline_boundary_self_test.py',
    'scripts\v213_methodology_and_source_audit.py',
    'scripts\v213_source_independence_gate.py',
    'scripts\v213_source_independence_gate_v2.py',
    'scripts\v213_source_independence_gate_v3.py',
    'scripts\audit_v213_source_diversity_fields.py',
    'scripts\v213_local_llm_gateway.py',
    'scripts\run_v213_local_llm_bridge_core.ps1',
    'scripts\run_v213_local_llm_bridge_core_v2.ps1',
    'scripts\adapters\nasdaq_symbol_directory.py'
)
foreach($item in $required){
    if(-not(Test-Path -LiteralPath (Join-Path $RuntimeRoot $item) -PathType Leaf)){throw "Runtime installation missing $item"}
}

$refresh=Get-Content -LiteralPath (Join-Path $RuntimeRoot 'run-v213-local.ps1') -Raw -Encoding utf8
$orderedPipeline=@(
    'v213_v21_progress_runner.py',
    'v213_v212_progress_runner.py',
    'reconcile_v213_order_evidence.py',
    'build_v213_scheduled_top20_report.py',
    'v213_source_federation.py',
    'v213_source_federation_gate.py',
    'v213_apply_diversified_operationalization.py',
    'v213_source_independence_gate_v3.py',
    'v213_build_v21_public_snapshot.py'
)
$previous=-1
foreach($token in $orderedPipeline){
    $position=$refresh.IndexOf($token,[StringComparison]::Ordinal)
    if($position-le$previous){throw "The canonical stable refresh pipeline order is invalid at: $token"}
    $previous=$position
}
if($refresh.Contains("& `$python 'scripts\build_v21_public_snapshot.py'")){
    throw 'The canonical stable refresh entrypoint still promotes the provisional shortlist through the legacy snapshot builder.'
}
if(-not$refresh.Contains('--enforce')){throw 'The canonical stable refresh entrypoint does not enforce the source-independence gate.'}
if(-not$refresh.Contains('company/claim diversity is blocking; unavailable free market cross-checks are disclosed and cap confidence')){
    throw 'The canonical stable refresh entrypoint lost the market-quality degradation boundary.'
}
$bridge=Get-Content -LiteralPath (Join-Path $RuntimeRoot 'run-v213-local-llm-bridge.ps1') -Raw -Encoding utf8
if(-not$bridge.Contains('run_v213_local_llm_bridge_core_v2.ps1')){
    throw 'The canonical stable bridge entrypoint does not use the HealthSchema2 dependency-bootstrap core.'
}

# Two reviewed activation wrappers are valid at this base-install layer:
#   1) the source-diverse wrapper used by the base runtime, and
#   2) the stricter Serenity-latest wrapper that the final package overlays.
# The latter delegates to the same exact-rollback core and adds the current
# per-ticker/latest-evidence qualification.  Requiring only legacy strings here
# incorrectly rejects the stronger final wrapper before its own installer can
# finish overlaying the stable runtime.
$activation=Get-Content -LiteralPath (Join-Path $RuntimeRoot 'activate-v213-seven-field-schedule.ps1') -Raw -Encoding utf8
$sourceDiverseMarkers=@(
    'V213_SOURCE_INDEPENDENCE_PREFLIGHT',
    'V213_MARKET_CORROBORATION_QUALITY = DEGRADED',
    'market_corroboration_status',
    'health-schema-v2',
    'install-v213-source-diverse-runtime.ps1',
    'rollback'
)
$serenityLatestMarkers=@(
    'V213_SERENITY_LATEST_ACTIVATION_PREFLIGHT',
    'v213_refresh_serenity_public_sources.py',
    'v213_serenity_latest_multisource_audit.py',
    'activate-v213-seven-field-schedule-core.ps1',
    'RequireLocalModel',
    'ConfirmActivation'
)
$sourceDiverseActivationValid=$true
foreach($needle in $sourceDiverseMarkers){if(-not$activation.Contains($needle)){$sourceDiverseActivationValid=$false;break}}
$serenityLatestActivationValid=$true
foreach($needle in $serenityLatestMarkers){if(-not$activation.Contains($needle)){$serenityLatestActivationValid=$false;break}}
$r75ActivationMarkers=@(
    'v213_r75_activation_preflight.py',
    'V213_R75_ACTIVATION_WRAPPER_SELF_TEST',
    'V213_R75_SEALED_BUNDLE_SHA256',
    'activate-v213-seven-field-schedule-core.ps1',
    'ConfirmActivation',
    'RequireLocalModel'
)
$r75ActivationValid=$true
foreach($needle in $r75ActivationMarkers){if(-not$activation.Contains($needle)){$r75ActivationValid=$false;break}}
if(-not$sourceDiverseActivationValid-and-not$serenityLatestActivationValid-and-not$r75ActivationValid){
    throw 'The stable activation entrypoint matches no reviewed source-diverse, Serenity-latest, or R75 sealed contract.'
}
$activationProfile=if($r75ActivationValid){'R75_SEALED'}elseif($serenityLatestActivationValid){'SERENITY_LATEST'}else{'SOURCE_DIVERSE'}
Write-Host "V213_RUNTIME_ACTIVATION_CONTRACT = PASS; profile=$activationProfile; exact_core=activate-v213-seven-field-schedule-core.ps1" -ForegroundColor Green

$gateway=Get-Content -LiteralPath (Join-Path $RuntimeRoot 'scripts\v213_local_llm_gateway.py') -Raw -Encoding utf8
foreach($needle in @('SOURCE-INDEPENDENCE RULES','v213_source_independence_latest.json','cap confidence at LIMITED','Yahoo/yfinance','Conflicting sources')){
    if(-not$gateway.Contains($needle)){throw "The stable local-model gateway is missing source contract: $needle"}
}

[ordered]@{
    schema_version=6
    product_version='2.1.3'
    runtime_root=$RuntimeRoot
    source_root=$ProjectRoot
    installed_utc=(Get-Date).ToUniversalTime().ToString('o')
    runtime_profile='source-diverse-exact-model-health-schema2-pipeline-v3-market-quality-aware'
    activation_contract_profile=$activationProfile
    scoring_version='system-operationalization-v2.1.3-diversified'
    provisional_scoring_version='system-operationalization-v2.1.3-safe-preselection'
    provisional_snapshot_promotion_blocked=$true
    diversified_operationalization_required_before_snapshot=$true
    canonical_snapshot_builder='scripts/v213_build_v21_public_snapshot.py'
    serenity_evidence_standard='2.1.3-source-independence-v3'
    source_catalog_count=101
    source_catalog_is_not_live_use=$true
    live_source_federation_required=$true
    claim_level_source_independence_required=$true
    source_independence_gate='scripts/v213_source_independence_gate_v3.py'
    source_independence_policy='config/v213-serenity-public-logic-policy.json'
    market_quality_policy='config/v213-market-corroboration-degradation-policy.json'
    market_endpoint_unavailability_is_global_blocker=$false
    market_corroboration_required_for_high_confidence_inference=$true
    uncorroborated_valuation_factor_max=3.75
    provider_failures_disclosed=$true
    source_conflicts_averaged=$false
    source_diversity_labels='config/v213-source-diversity-field-labels.zh-en.json'
    market_calculation_source='yfinance_compatibility_only'
    independent_market_attempts=@('stooq_daily_csv','nasdaq_historical_api','hfmarketdata_daily_bars','optional_alpha_vantage_adjusted')
    official_macro_context='fred_official_macro'
    preferred_model='RVN-Q6_K-multilingual-mtp'
    health_schema_version=2
    official_serenity_formula_claimed=$false
    official_serenity_score_claimed=$false
    private_serenity_method_reproduced=$false
}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $baseRoot 'v213-runtime-state.json') -Encoding utf8
# Robocopy 0..7 indicate success; do not leak its successful nonzero status
# into the caller's native-exit gate after all installation checks passed.
$global:LASTEXITCODE=0
Write-Host "V213_RUNTIME = PASS; path=$RuntimeRoot; profile=source-diverse-exact-model-health-schema2-pipeline-v3-market-quality-aware; activation=$activationProfile" -ForegroundColor Green
