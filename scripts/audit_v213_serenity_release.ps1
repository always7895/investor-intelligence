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
        throw "Required Serenity release file is missing: $RelativePath"
    }
    return $path
}

function Read-Text([string]$RelativePath) {
    return Get-Content -LiteralPath (Require-File $RelativePath) -Raw -Encoding utf8
}

function Read-Json([string]$RelativePath) {
    return (Read-Text $RelativePath) | ConvertFrom-Json
}

function Require-Markers([string]$RelativePath,[string[]]$Markers) {
    $text = Read-Text $RelativePath
    foreach ($marker in $Markers) {
        if (-not $text.Contains($marker)) {
            throw "Serenity contract marker is missing from ${RelativePath}: $marker"
        }
    }
}

function Require-True([object]$Value,[string]$Label) {
    if ($Value -ne $true) { throw "Serenity policy must remain true: $Label" }
}

function Require-False([object]$Value,[string]$Label) {
    if ($Value -ne $false) { throw "Serenity policy must remain false: $Label" }
}

$freshness = Read-Json 'config\v213-serenity-evidence-freshness-policy.json'
if ($freshness.schema_version -ne 1 -or $freshness.product_version -ne '2.1.3') {
    throw 'Serenity freshness policy schema/version is invalid.'
}
if ([int]$freshness.minimum_claim_source_families_per_ticker -lt 2) { throw 'Per-ticker claim-family minimum was weakened.' }
if ([int]$freshness.minimum_claim_source_domains_per_ticker -lt 2) { throw 'Per-ticker claim-domain minimum was weakened.' }
if ([int]$freshness.minimum_claim_primary_sources_per_ticker -lt 1) { throw 'Per-ticker primary-source minimum was weakened.' }
if ([int]$freshness.minimum_sensitive_advantage_source_units -lt 2) { throw 'Positive-advantage source-unit minimum was weakened.' }
if ([int]$freshness.minimum_sensitive_advantage_domains -lt 2) { throw 'Positive-advantage source-domain minimum was weakened.' }
if ([double]$freshness.minimum_claim_dated_evidence_ratio -lt 0.8) { throw 'Dated claim-evidence minimum was weakened.' }
if ([double]$freshness.market_observation_max_age_days -gt 7) { throw 'Market freshness window exceeds seven days.' }
if ([double]$freshness.current_state_claim_max_age_days -gt 210) { throw 'Current-state claim freshness window exceeds 210 days.' }
if ([double]$freshness.activation_snapshot_max_age_hours -gt 2) { throw 'Activation snapshot freshness window exceeds two hours.' }
foreach ($name in @(
    'market_data_is_company_claim_evidence',
    'official_macro_is_company_claim_evidence',
    'same_registrable_domain_is_independent',
    'same_publisher_family_is_independent',
    'syndicated_duplicate_is_independent',
    'conflicting_sources_are_averaged',
    'stale_live_market_observation_is_publishable',
    'undated_sensitive_advantage_is_publishable',
    'single_source_positive_advantage_is_publishable'
)) {
    Require-False $freshness.$name "freshness.$name"
}

$publicLogic = Read-Json 'config\v213-serenity-public-logic-policy.json'
if ($publicLogic.schema_version -lt 3 -or $publicLogic.product_version -ne '2.1.3') {
    throw 'Serenity public-logic policy schema/version is invalid.'
}
Require-False $publicLogic.non_claims.private_method_reproduced 'non_claims.private_method_reproduced'
Require-False $publicLogic.non_claims.official_serenity_formula 'non_claims.official_serenity_formula'
Require-False $publicLogic.non_claims.official_serenity_score 'non_claims.official_serenity_score'
Require-True $publicLogic.source_rules.duplicate_syndication_counts_once 'source_rules.duplicate_syndication_counts_once'
Require-True $publicLogic.source_rules.same_registrable_domain_counts_once_per_claim 'source_rules.same_registrable_domain_counts_once_per_claim'
Require-True $publicLogic.source_rules.same_corporate_source_family_is_not_independent_corroboration 'source_rules.same_corporate_source_family_is_not_independent_corroboration'
Require-True $publicLogic.source_rules.broader_inference_requires_independent_corroboration 'source_rules.broader_inference_requires_independent_corroboration'
Require-True $publicLogic.source_rules.conflicting_primary_sources_force_review 'source_rules.conflicting_primary_sources_force_review'
Require-True $publicLogic.source_rules.source_conflicts_are_not_averaged 'source_rules.source_conflicts_are_not_averaged'
Require-True $publicLogic.source_rules.unknown_remains_unknown 'source_rules.unknown_remains_unknown'
Require-True $publicLogic.fail_closed.keyword_cannot_prove_bottleneck 'fail_closed.keyword_cannot_prove_bottleneck'
Require-True $publicLogic.fail_closed.gross_margin_cannot_prove_replacement_friction 'fail_closed.gross_margin_cannot_prove_replacement_friction'
Require-True $publicLogic.fail_closed.revenue_growth_cannot_prove_tam_capture 'fail_closed.revenue_growth_cannot_prove_tam_capture'
Require-True $publicLogic.fail_closed.quantitative_overlay_cannot_override_broken_thesis 'fail_closed.quantitative_overlay_cannot_override_broken_thesis'
Require-True $publicLogic.fail_closed.dependency_claim_requires_evidence_binding 'fail_closed.dependency_claim_requires_evidence_binding'
Require-True $publicLogic.fail_closed.killer_claim_requires_evidence_binding 'fail_closed.killer_claim_requires_evidence_binding'
Require-True $publicLogic.fail_closed.single_source_high_confidence_is_forbidden 'fail_closed.single_source_high_confidence_is_forbidden'
if ([int]$publicLogic.minimums.portfolio_claim_source_families -lt 2) { throw 'Portfolio claim-family minimum was weakened.' }
if ([int]$publicLogic.minimums.portfolio_claim_source_domains -lt 2) { throw 'Portfolio claim-domain minimum was weakened.' }
if ([double]$publicLogic.minimums.portfolio_claim_primary_coverage_ratio -lt 0.75) { throw 'Primary claim coverage minimum was weakened.' }
if ([double]$publicLogic.minimums.maximum_single_family_share -gt 0.70) { throw 'Single-family concentration ceiling was weakened.' }

$degradation = Read-Json 'config\v213-market-corroboration-degradation-policy.json'
Require-False $degradation.market_corroboration_unavailable_is_global_blocker 'degradation.market_corroboration_unavailable_is_global_blocker'
Require-True $degradation.market_corroboration_required_for_high_confidence_model_inference 'degradation.market_corroboration_required_for_high_confidence_model_inference'
Require-True $degradation.market_corroboration_required_for_uncapped_valuation_factor 'degradation.market_corroboration_required_for_uncapped_valuation_factor'
Require-True $degradation.provider_failure_must_be_disclosed 'degradation.provider_failure_must_be_disclosed'
Require-True $degradation.provider_failure_must_not_be_silently_relabelled_as_success 'degradation.provider_failure_must_not_be_silently_relabelled_as_success'
Require-True $degradation.source_conflicts_are_not_averaged 'degradation.source_conflicts_are_not_averaged'
if ([double]$degradation.uncorroborated_valuation_factor_max -gt 3.75) { throw 'Uncorroborated valuation cap was weakened.' }

Require-Markers 'scripts\build_v213_activation_bundle_v2.py' @(
    'v213-serenity-evidence-freshness-policy.json',
    'stale market observations remain LIVE/CACHED',
    'positive Serenity advantages lack fresh multi-source support',
    'source-level provenance is not independently diverse',
    'market provider count is not freshness-adjusted',
    'freshness_audit',
    'single_source_advantage_rejected=true'
)
Require-Markers 'scripts\v213_source_independence_gate.py' @(
    'MARKET_FAMILIES',
    'CLAIM_PRIMARY_FAMILIES',
    'NON_CLAIM_TYPES',
    'same registrable domain counts once per claim',
    'MARKET_SOURCE_CONFLICT_REVIEW',
    'PORTFOLIO_SOURCE_POLICY'
)
Require-Markers 'scripts\v213_source_independence_gate_v2.py' @(
    'keyless multi-ticker market request complete',
    'market_data_is_not_company_evidence=true',
    'HF_MARKET_DATA_PROVIDER',
    'HF_MARKET_DATA_FAMILY'
)
Require-Markers 'scripts\v213_source_independence_gate_v3.py' @(
    'market_corroboration_unavailable_is_global_blocker',
    'market_corroboration_required_for_high_confidence_model_inference',
    'provider_failure_must_not_be_silently_relabelled_as_success',
    'market_data_is_not_averaged_into_published_returns',
    'claim_evidence_failures=blocking'
)
Require-Markers 'run-v213-local-source-diverse.ps1' @(
    'v213_source_independence_gate_v3.py',
    'build_v213_activation_bundle_v2.py',
    'provisional shortlist replaced by final diversified Top20'
)
Require-Markers 'cloud\src\v213\activation-v2.ts' @(
    'validateSourceAudit',
    'rejectPrivateKeys',
    'MARKET_DEGRADATION',
    'MARKET_MISSING',
    'market_conflict_ticker_count',
    'uncorroborated_valuation_factor_max',
    'V213_ACTIVATION_UNCORROBORATED_CONFIDENCE_INVALID'
)
Require-Markers 'cloud\test\v213-activation.test.ts' @(
    'PASS_WITH_DEGRADATION',
    'NON_YAHOO_MARKET_CORROBORATION',
    'writes all immutable objects before switching the pointer',
    'rolls back exact text',
    'finalizes only the matching current pointer'
)
Require-Markers 'activate-v213-seven-field-schedule-core.ps1' @(
    'Get-BalancedJsonDocumentEnd',
    'multiple deployment JSON documents',
    'node_modules\wrangler\bin\wrangler.js',
    'V213_WRANGLER_INVOCATION = DIRECT_NODE',
    'pointer_written_last=true',
    'V213_ACTIVATION_POINTER_ROLLBACK = PASS',
    'V213_ACTIVATION_WORKER_ROLLBACK = PASS'
)

$parserErrors = New-Object System.Collections.Generic.List[string]
foreach ($relative in @(
    'scripts\audit_v213_serenity_release.ps1',
    'scripts\test_v213_activation_core.ps1',
    'activate-v213-seven-field-schedule-core.ps1',
    'sync-v213-activation-bundle.ps1'
)) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile((Require-File $relative),[ref]$tokens,[ref]$errors)
    foreach ($error in @($errors)) { $parserErrors.Add("${relative}: $($error.Message)") }
}
if ($parserErrors.Count -gt 0) { throw ($parserErrors -join "`n") }

$result = [ordered]@{
    schema_version = 1
    product_version = '2.1.3'
    status = 'PASS'
    audited_utc = (Get-Date).ToUniversalTime().ToString('o')
    public_logic_boundary = [ordered]@{
        official_formula_claimed = $false
        private_method_reproduced = $false
        quantitative_shortcuts_can_prove_advantage = $false
        broken_thesis_can_be_overridden_by_score = $false
    }
    source_independence = [ordered]@{
        per_ticker_claim_families_min = [int]$freshness.minimum_claim_source_families_per_ticker
        per_ticker_claim_domains_min = [int]$freshness.minimum_claim_source_domains_per_ticker
        primary_claim_sources_min = [int]$freshness.minimum_claim_primary_sources_per_ticker
        same_domain_counts_as_independent = $false
        same_publisher_family_counts_as_independent = $false
        syndicated_duplicates_count_as_independent = $false
        conflicts_are_averaged = $false
    }
    freshness = [ordered]@{
        activation_snapshot_max_age_hours = [double]$freshness.activation_snapshot_max_age_hours
        market_observation_max_age_days = [double]$freshness.market_observation_max_age_days
        current_state_claim_max_age_days = [double]$freshness.current_state_claim_max_age_days
        stale_live_market_rejected = $true
        positive_advantage_requires_fresh_multi_source = $true
    }
    atomic_delivery = [ordered]@{
        immutable_objects_before_pointer = $true
        pointer_written_last = $true
        exact_pointer_rollback = $true
        exact_worker_rollback = $true
        ambiguous_wrangler_json_rejected = $true
    }
}
$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Host "V213_SERENITY_RELEASE_AUDIT = PASS; output=$OutputPath; multi_source_per_ticker=true; fresh_positive_advantage=true; stale_market_rejected=true; conflicts_not_averaged=true; private_formula_claimed=false" -ForegroundColor Green
