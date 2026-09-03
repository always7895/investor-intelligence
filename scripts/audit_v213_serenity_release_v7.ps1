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

function Require-File([string]$Relative) {
    $path = Join-Path $ProjectRoot $Relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required release file is missing: $Relative" }
    return $path
}
function Read-Text([string]$Relative) { Get-Content -LiteralPath (Require-File $Relative) -Raw -Encoding utf8 }
function Read-Json([string]$Relative) { (Read-Text $Relative) | ConvertFrom-Json }
function Require-True([object]$Value,[string]$Label) { if ($Value -ne $true) { throw "Required true: $Label" } }
function Require-False([object]$Value,[string]$Label) { if ($Value -ne $false) { throw "Required false: $Label" } }
function Require-Markers([string]$Relative,[string[]]$Markers) {
    $text = Read-Text $Relative
    foreach ($marker in $Markers) {
        if (-not $text.Contains($marker)) { throw "Missing release marker in ${Relative}: $marker" }
    }
}

$fresh = Read-Json 'config\v213-serenity-evidence-freshness-policy.json'
if ($fresh.schema_version -ne 1 -or $fresh.product_version -ne '2.1.3') { throw 'Freshness policy schema/version mismatch.' }
if ([double]$fresh.activation_snapshot_max_age_hours -gt 2) { throw 'Activation snapshot may be older than two hours.' }
if ([double]$fresh.market_observation_max_age_days -gt 7) { throw 'Market observation may be older than seven days.' }
if ([double]$fresh.market_high_confidence_freshest_max_age_days -gt 4) { throw 'High-confidence freshest market observation may be older than four days.' }
if ([double]$fresh.market_comparable_provider_max_lag_days -gt 3) { throw 'Comparable provider dates may lag by more than three days.' }
if ([double]$fresh.macro_observation_max_age_days -gt 45) { throw 'Macro context may be older than 45 days.' }
if ([double]$fresh.current_state_claim_max_age_days -gt 135) { throw 'Current-state company evidence may be older than 135 days.' }
if ([double]$fresh.structural_claim_max_age_days -gt 550) { throw 'Structural evidence may be older than 550 days.' }
if ([int]$fresh.minimum_claim_source_families_per_ticker -lt 2) { throw 'Per-ticker claim-family minimum is below two.' }
if ([int]$fresh.minimum_claim_source_domains_per_ticker -lt 2) { throw 'Per-ticker claim-domain minimum is below two.' }
if ([int]$fresh.minimum_claim_primary_sources_per_ticker -lt 1) { throw 'Per-ticker primary-source minimum is below one.' }
if ([int]$fresh.minimum_sensitive_advantage_source_units -lt 2) { throw 'Positive-advantage source-unit minimum is below two.' }
if ([int]$fresh.minimum_sensitive_advantage_domains -lt 2) { throw 'Positive-advantage source-domain minimum is below two.' }
if ([int]$fresh.minimum_independent_market_providers_for_high_confidence -lt 2) { throw 'High-confidence market-provider minimum is below two.' }
if ([double]$fresh.minimum_claim_dated_evidence_ratio -lt 0.8) { throw 'Dated claim-evidence ratio is below 80%.' }
foreach ($name in @(
    'market_data_is_company_claim_evidence','official_macro_is_company_claim_evidence',
    'same_registrable_domain_is_independent','same_publisher_family_is_independent',
    'syndicated_duplicate_is_independent','conflicting_sources_are_averaged',
    'stale_live_market_observation_is_publishable','undated_sensitive_advantage_is_publishable',
    'single_source_positive_advantage_is_publishable'
)) { Require-False $fresh.$name "freshness.$name" }
foreach ($name in @(
    'fresh_non_primary_corroborator_required_for_positive_advantage',
    'retrieval_timestamp_cannot_substitute_publication_date',
    'latest_available_evidence_must_be_selected',
    'comparable_market_metric_basis_required_for_high_confidence'
)) { Require-True $fresh.$name "freshness.$name" }

$limited = Read-Json 'config\v213-limited-research-candidate-policy.json'
if ($limited.schema_version -ne 1 -or $limited.product_version -ne '2.1.3') { throw 'Limited-candidate policy schema/version mismatch.' }
$limitedPolicy = $limited.limited_research_candidate_policy
Require-True $limitedPolicy.limited_research_candidate_publication_allowed 'limited candidate publication policy'
Require-True $limitedPolicy.limited_research_candidate_requires_all_sensitive_advantage_factors_zero 'limited candidate positive-factor zeroing'
Require-True $limitedPolicy.limited_research_candidate_requires_latest_available_primary_source 'limited candidate latest primary source'
Require-False $limitedPolicy.identity_provenance_can_support_positive_advantage 'identity provenance advantage support'
Require-False $limitedPolicy.limited_research_candidate_is_validated_thesis 'limited candidate validated-thesis status'
Require-False $limitedPolicy.limited_research_candidate_high_confidence_allowed 'limited candidate high-confidence permission'
if ([int]$limitedPolicy.minimum_limited_candidate_primary_claim_sources -lt 1) { throw 'Limited candidate primary-source minimum is below one.' }
if ([int]$limitedPolicy.minimum_limited_candidate_provenance_origins -lt 2) { throw 'Limited candidate provenance-origin minimum is below two.' }
if ([int]$limitedPolicy.minimum_limited_candidate_provenance_domains -lt 2) { throw 'Limited candidate provenance-domain minimum is below two.' }
if ([double]$limitedPolicy.identity_provenance_max_age_days -gt 7) { throw 'Identity provenance may be older than seven days.' }

$logic = Read-Json 'config\v213-serenity-public-logic-policy.json'
if ($logic.schema_version -lt 3 -or $logic.product_version -ne '2.1.3') { throw 'Public-logic policy schema/version mismatch.' }
Require-False $logic.non_claims.private_method_reproduced 'non_claims.private_method_reproduced'
Require-False $logic.non_claims.official_serenity_formula 'non_claims.official_serenity_formula'
Require-False $logic.non_claims.official_serenity_score 'non_claims.official_serenity_score'
foreach ($name in @(
    'duplicate_syndication_counts_once','same_registrable_domain_counts_once_per_claim',
    'same_corporate_source_family_is_not_independent_corroboration',
    'broader_inference_requires_independent_corroboration','conflicting_primary_sources_force_review',
    'source_conflicts_are_not_averaged','unknown_remains_unknown'
)) { Require-True $logic.source_rules.$name "source_rules.$name" }
foreach ($name in @(
    'keyword_cannot_prove_bottleneck','gross_margin_cannot_prove_replacement_friction',
    'revenue_growth_cannot_prove_tam_capture','quantitative_overlay_cannot_override_broken_thesis',
    'dependency_claim_requires_evidence_binding','killer_claim_requires_evidence_binding',
    'commercial_claim_requires_evidence_binding','graph_edge_requires_evidence_binding',
    'architecture_requires_dated_evidence_for_bottleneck_class',
    'single_source_high_confidence_is_forbidden'
)) { Require-True $logic.fail_closed.$name "fail_closed.$name" }

$pins = Read-Json 'config\v213-serenity-methodology-reference-pins.json'
if ($pins.schema_version -ne 1 -or $pins.product_version -ne '2.1.3') { throw 'Methodology reference pins schema/version mismatch.' }
Require-False $pins.references_are_company_evidence 'methodology pins company-evidence boundary'
Require-False $pins.references_define_official_serenity_formula 'methodology pins official-formula boundary'
if (@($pins.repositories).Count -lt 3) { throw 'Fewer than three independently maintained methodology references are pinned.' }
$now = [DateTimeOffset]::UtcNow
$owners = @{}
foreach ($repo in @($pins.repositories)) {
    if ([string]::IsNullOrWhiteSpace([string]$repo.repository) -or [string]::IsNullOrWhiteSpace([string]$repo.commit_sha)) { throw 'Methodology pin is incomplete.' }
    if ([string]$repo.commit_sha -notmatch '^[0-9a-f]{40}$') { throw "Methodology pin SHA is invalid: $($repo.repository)" }
    $observed = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$repo.observed_at,[ref]$observed)) { throw "Methodology pin observation time is invalid: $($repo.repository)" }
    if (($now - $observed.ToUniversalTime()).TotalDays -gt 7.0) { throw "Methodology pin is stale: $($repo.repository)" }
    $owner = ([string]$repo.repository).Split('/')[0].ToLowerInvariant()
    $owners[$owner] = $true
}
if ($owners.Count -lt 3) { throw 'Methodology references are not independently maintained.' }

$degrade = Read-Json 'config\v213-market-corroboration-degradation-policy.json'
Require-False $degrade.market_corroboration_unavailable_is_global_blocker 'provider outage alone is not a global blocker'
Require-True $degrade.market_corroboration_required_for_high_confidence_model_inference 'market corroboration required for high confidence'
Require-True $degrade.market_corroboration_required_for_uncapped_valuation_factor 'market corroboration required for uncapped valuation'
Require-True $degrade.provider_failure_must_be_disclosed 'provider failure disclosure'
Require-True $degrade.provider_failure_must_not_be_silently_relabelled_as_success 'provider failure cannot be relabelled success'
Require-True $degrade.source_conflicts_are_not_averaged 'source conflicts are not averaged'
if ([double]$degrade.uncorroborated_valuation_factor_max -gt 3.75) { throw 'Uncorroborated valuation factor cap exceeds 3.75.' }

Require-Markers 'scripts\v213_source_independence_gate_v3.py' @('v213_source_independence_gate_v4.py','v4.self_test()','v4.gate.main()')
Require-Markers 'scripts\v213_source_independence_gate_v4.py' @(
    'MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS = 2','MARKET_HARD_MAX_AGE_DAYS = 7.0',
    'MARKET_HIGH_CONFIDENCE_FRESHEST_MAX_AGE_DAYS = 4.0','MARKET_COMPARABLE_PROVIDER_MAX_LAG_DAYS = 3.0',
    'ADJUSTED_CLOSE_BASIS = "split_dividend_adjusted_close"','comparable_metric_basis_required_for_high_confidence',
    'market_conflicts_compared_pairwise_without_yahoo_authority','compatibility_calculation_only_not_authoritative_corroboration',
    'stale market as_of','pairwise_same_basis','worker_degradation_schema_compatible=true','source_conflicts_are_not_averaged'
)
Require-Markers 'scripts\build_v213_activation_bundle_v2.py' @(
    'EVIDENCE_QUALIFIED','LIMITED_RESEARCH_CANDIDATE','limited research candidate still depends on one publication origin',
    'positive Serenity advantages lack a fresh primary source plus an independently operated non-primary corroborator',
    'identity_provenance_can_support_positive_advantage','limited_high_confidence=false','single_origin_rejected=true'
)
Require-Markers 'scripts\v213_source_federation_gate.py' @(
    'nasdaq_symbol_directory_entity_reference','same_origin_as_regulated_listing_identity',
    'fallback_independent_family_increment','can_support_positive_serenity_advantage'
)
Require-Markers 'run-v213-local-source-diverse.ps1' @('v213_source_independence_gate_v3.py','build_v213_activation_bundle_v2.py','provisional shortlist replaced by final diversified Top20')
Require-Markers 'cloud\src\v213\activation-v2.ts' @(
    'EVIDENCE_QUALIFIED','LIMITED_RESEARCH_CANDIDATE','V213_ACTIVATION_LIMITED_EVIDENCE_INVALID',
    'publication_provenance_origin_count','identity_provenance_can_support_positive_advantage',
    'limited_rows_high_confidence_eligible_count','positive_advantage_factors'
)
Require-Markers 'cloud\test\v213-activation.test.ts' @(
    'rejects a limited research candidate that carries a positive advantage',
    'writes all immutable objects before switching the pointer','rolls back exact text',
    'finalizes only the matching current pointer'
)
Require-Markers 'activate-v213-seven-field-schedule-core.ps1' @(
    'Get-BalancedJsonDocumentEnd','multiple deployment JSON documents',
    'node_modules\wrangler\bin\wrangler.js','V213_WRANGLER_INVOCATION = DIRECT_NODE',
    'pointer_written_last=true','V213_ACTIVATION_POINTER_ROLLBACK = PASS','V213_ACTIVATION_WORKER_ROLLBACK = PASS'
)
Require-Markers 'docs\V213_SERENITY_RELATED_PROJECTS_REVIEW.zh-TW.md' @(
    'yan-labs/serenity-aleabitoreddit','muxuuu/serenity-skill',
    'quantskills/skill-serenity-research-model','方法論參考，不是公司證據'
)

$result = [ordered]@{
    schema_version = 7
    product_version = '2.1.3'
    status = 'PASS'
    audited_utc = $now.ToString('o')
    attribution_boundary = [ordered]@{
        public_source_reconstruction = $true
        official_formula_claimed = $false
        private_method_reproduced = $false
        system_overlay_can_override_broken_thesis = $false
    }
    publication_evidence_modes = [ordered]@{
        evidence_qualified = [ordered]@{
            claim_families_min = 2
            claim_domains_min = 2
            primary_sources_min = 1
            positive_advantage_requires_primary_plus_independent_non_primary = $true
        }
        limited_research_candidate = [ordered]@{
            positive_advantages_allowed = $false
            primary_company_source_min = 1
            independent_provenance_origins_min = 2
            independent_provenance_domains_min = 2
            validated_thesis = $false
            high_confidence_allowed = $false
        }
    }
    latest_data = [ordered]@{
        activation_snapshot_max_age_hours = [double]$fresh.activation_snapshot_max_age_hours
        market_hard_max_age_days = [double]$fresh.market_observation_max_age_days
        high_confidence_freshest_market_max_age_days = [double]$fresh.market_high_confidence_freshest_max_age_days
        comparable_provider_lag_max_days = [double]$fresh.market_comparable_provider_max_lag_days
        current_state_claim_max_age_days = [double]$fresh.current_state_claim_max_age_days
        retrieval_time_cannot_replace_publication_time = $true
        latest_available_evidence_required = $true
    }
    methodology_reference_review = [ordered]@{
        repository_count = @($pins.repositories).Count
        independent_owner_count = $owners.Count
        maximum_pin_age_days = 7
        company_evidence = $false
        official_formula = $false
    }
    market_independence = [ordered]@{
        yahoo_authoritative = $false
        yahoo_role = 'compatibility_calculation_only'
        comparable_provider_minimum_for_high_confidence = 2
        same_metric_basis_required = $true
        pairwise_conflict_comparison = $true
        conflicts_averaged = $false
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
$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Host "V213_SERENITY_RELEASE_AUDIT_V7 = PASS; output=$OutputPath; latest_data=true; evidence_modes=qualified_or_limited; limited_positive_advantage=false; limited_high_confidence=false; methodology_pins=$(@($pins.repositories).Count); yahoo_authoritative=false; conflicts_not_averaged=true" -ForegroundColor Green
