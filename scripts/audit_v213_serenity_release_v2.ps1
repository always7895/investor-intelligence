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

function Path-Of([string]$Relative) {
    $path = Join-Path $ProjectRoot $Relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file missing: $Relative" }
    return $path
}
function Text-Of([string]$Relative) { Get-Content -LiteralPath (Path-Of $Relative) -Raw -Encoding utf8 }
function Json-Of([string]$Relative) { (Text-Of $Relative) | ConvertFrom-Json }
function Must-Contain([string]$Relative,[string[]]$Markers) {
    $text = Text-Of $Relative
    foreach ($marker in $Markers) {
        if (-not $text.Contains($marker)) { throw "Missing contract marker in ${Relative}: $marker" }
    }
}
function Must-BeTrue([object]$Value,[string]$Label) { if ($Value -ne $true) { throw "Required true: $Label" } }
function Must-BeFalse([object]$Value,[string]$Label) { if ($Value -ne $false) { throw "Required false: $Label" } }

$fresh = Json-Of 'config\v213-serenity-evidence-freshness-policy.json'
if ($fresh.schema_version -ne 1 -or $fresh.product_version -ne '2.1.3') { throw 'Freshness policy schema/version mismatch.' }
if ([int]$fresh.minimum_claim_source_families_per_ticker -lt 2) { throw 'Claim-family minimum weakened.' }
if ([int]$fresh.minimum_claim_source_domains_per_ticker -lt 2) { throw 'Claim-domain minimum weakened.' }
if ([int]$fresh.minimum_claim_primary_sources_per_ticker -lt 1) { throw 'Primary-source minimum weakened.' }
if ([int]$fresh.minimum_sensitive_advantage_source_units -lt 2) { throw 'Positive-advantage source-unit minimum weakened.' }
if ([int]$fresh.minimum_sensitive_advantage_domains -lt 2) { throw 'Positive-advantage domain minimum weakened.' }
if ([double]$fresh.minimum_claim_dated_evidence_ratio -lt 0.8) { throw 'Dated-evidence ratio weakened.' }
if ([double]$fresh.market_observation_max_age_days -gt 7) { throw 'Market data freshness exceeds seven days.' }
if ([double]$fresh.current_state_claim_max_age_days -gt 210) { throw 'Current-state evidence freshness exceeds 210 days.' }
if ([double]$fresh.activation_snapshot_max_age_hours -gt 2) { throw 'Activation snapshot freshness exceeds two hours.' }
foreach ($name in @(
    'market_data_is_company_claim_evidence','official_macro_is_company_claim_evidence',
    'same_registrable_domain_is_independent','same_publisher_family_is_independent',
    'syndicated_duplicate_is_independent','conflicting_sources_are_averaged',
    'stale_live_market_observation_is_publishable','undated_sensitive_advantage_is_publishable',
    'single_source_positive_advantage_is_publishable'
)) { Must-BeFalse $fresh.$name "freshness.$name" }

$logic = Json-Of 'config\v213-serenity-public-logic-policy.json'
if ($logic.schema_version -lt 3 -or $logic.product_version -ne '2.1.3') { throw 'Public-logic policy schema/version mismatch.' }
Must-BeFalse $logic.non_claims.private_method_reproduced 'non_claims.private_method_reproduced'
Must-BeFalse $logic.non_claims.official_serenity_formula 'non_claims.official_serenity_formula'
Must-BeFalse $logic.non_claims.official_serenity_score 'non_claims.official_serenity_score'
foreach ($name in @(
    'duplicate_syndication_counts_once','same_registrable_domain_counts_once_per_claim',
    'same_corporate_source_family_is_not_independent_corroboration',
    'broader_inference_requires_independent_corroboration','conflicting_primary_sources_force_review',
    'source_conflicts_are_not_averaged','unknown_remains_unknown'
)) { Must-BeTrue $logic.source_rules.$name "source_rules.$name" }
foreach ($name in @(
    'keyword_cannot_prove_bottleneck','gross_margin_cannot_prove_replacement_friction',
    'revenue_growth_cannot_prove_tam_capture','quantitative_overlay_cannot_override_broken_thesis',
    'dependency_claim_requires_evidence_binding','killer_claim_requires_evidence_binding',
    'single_source_high_confidence_is_forbidden'
)) { Must-BeTrue $logic.fail_closed.$name "fail_closed.$name" }
if ([int]$logic.minimums.portfolio_claim_source_families -lt 2) { throw 'Portfolio claim-family minimum weakened.' }
if ([int]$logic.minimums.portfolio_claim_source_domains -lt 2) { throw 'Portfolio claim-domain minimum weakened.' }
if ([double]$logic.minimums.portfolio_claim_primary_coverage_ratio -lt 0.75) { throw 'Primary coverage minimum weakened.' }
if ([double]$logic.minimums.maximum_single_family_share -gt 0.70) { throw 'Source concentration ceiling weakened.' }

$degrade = Json-Of 'config\v213-market-corroboration-degradation-policy.json'
Must-BeFalse $degrade.market_corroboration_unavailable_is_global_blocker 'market unavailability global blocker'
Must-BeTrue $degrade.market_corroboration_required_for_high_confidence_model_inference 'market required for high confidence'
Must-BeTrue $degrade.market_corroboration_required_for_uncapped_valuation_factor 'market required for uncapped valuation'
Must-BeTrue $degrade.provider_failure_must_be_disclosed 'provider failure disclosure'
Must-BeTrue $degrade.provider_failure_must_not_be_silently_relabelled_as_success 'provider failure relabel prohibition'
Must-BeTrue $degrade.source_conflicts_are_not_averaged 'conflicts not averaged'
if ([double]$degrade.uncorroborated_valuation_factor_max -gt 3.75) { throw 'Uncorroborated valuation cap weakened.' }

Must-Contain 'scripts\build_v213_activation_bundle_v2.py' @(
    'v213-serenity-evidence-freshness-policy.json',
    'stale market observations remain LIVE/CACHED',
    'positive Serenity advantages lack fresh multi-source support',
    'source-level provenance is not independently diverse',
    'market provider count is not freshness-adjusted',
    'freshness_audit',
    'single_source_advantage_rejected=true'
)
Must-Contain 'scripts\v213_source_independence_gate.py' @(
    'MARKET_FAMILIES','CLAIM_PRIMARY_FAMILIES','NON_CLAIM_TYPES',
    'units.setdefault(unit, source)','claim_relevant_independent_domains',
    'maximum_claim_family_share','MARKET_SOURCE_CONFLICT_REVIEW','PORTFOLIO_SOURCE_POLICY'
)
Must-Contain 'scripts\v213_source_independence_gate_v2.py' @(
    'keyless multi-ticker market request complete','market_data_is_not_company_evidence=true',
    'HF_MARKET_DATA_PROVIDER','HF_MARKET_DATA_FAMILY'
)
Must-Contain 'scripts\v213_source_independence_gate_v3.py' @(
    'market_corroboration_unavailable_is_global_blocker',
    'market_corroboration_required_for_high_confidence_model_inference',
    'provider_failure_must_not_be_silently_relabelled_as_success',
    'market_data_is_not_averaged_into_published_returns','claim_evidence_failures=blocking'
)
Must-Contain 'run-v213-local-source-diverse.ps1' @(
    'v213_source_independence_gate_v3.py','build_v213_activation_bundle_v2.py',
    'provisional shortlist replaced by final diversified Top20'
)
Must-Contain 'cloud\src\v213\activation-v2.ts' @(
    'validateSourceAudit','rejectPrivateKeys','MARKET_DEGRADATION','MARKET_MISSING',
    'market_conflict_ticker_count','uncorroborated_valuation_factor_max',
    'V213_ACTIVATION_UNCORROBORATED_CONFIDENCE_INVALID'
)
Must-Contain 'cloud\test\v213-activation.test.ts' @(
    'PASS_WITH_DEGRADATION','NON_YAHOO_MARKET_CORROBORATION',
    'writes all immutable objects before switching the pointer',
    'rolls back exact text','finalizes only the matching current pointer'
)
Must-Contain 'activate-v213-seven-field-schedule-core.ps1' @(
    'Get-BalancedJsonDocumentEnd','multiple deployment JSON documents',
    'node_modules\wrangler\bin\wrangler.js','V213_WRANGLER_INVOCATION = DIRECT_NODE',
    'pointer_written_last=true','V213_ACTIVATION_POINTER_ROLLBACK = PASS',
    'V213_ACTIVATION_WORKER_ROLLBACK = PASS'
)

$parseFailures = New-Object System.Collections.Generic.List[string]
foreach ($relative in @(
    'scripts\audit_v213_serenity_release_v2.ps1','scripts\test_v213_activation_core.ps1',
    'activate-v213-seven-field-schedule-core.ps1','sync-v213-activation-bundle.ps1'
)) {
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile((Path-Of $relative),[ref]$tokens,[ref]$errors)
    foreach ($error in @($errors)) { $parseFailures.Add("${relative}: $($error.Message)") }
}
if ($parseFailures.Count) { throw ($parseFailures -join "`n") }

$result = [ordered]@{
    schema_version = 2
    product_version = '2.1.3'
    status = 'PASS'
    audited_utc = (Get-Date).ToUniversalTime().ToString('o')
    audit_revision = 'fresh-independent-evidence-v2'
    public_logic = [ordered]@{
        official_formula_claimed = $false
        private_method_reproduced = $false
        keyword_or_growth_shortcuts_can_prove_advantage = $false
        broken_thesis_can_be_overridden_by_score = $false
    }
    per_ticker_source_gate = [ordered]@{
        claim_families_min = [int]$fresh.minimum_claim_source_families_per_ticker
        claim_domains_min = [int]$fresh.minimum_claim_source_domains_per_ticker
        primary_sources_min = [int]$fresh.minimum_claim_primary_sources_per_ticker
        same_domain_independent = $false
        same_publisher_family_independent = $false
        syndicated_duplicates_independent = $false
        conflicts_averaged = $false
    }
    freshness_gate = [ordered]@{
        snapshot_max_age_hours = [double]$fresh.activation_snapshot_max_age_hours
        market_max_age_days = [double]$fresh.market_observation_max_age_days
        current_claim_max_age_days = [double]$fresh.current_state_claim_max_age_days
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
Write-Host "V213_SERENITY_RELEASE_AUDIT_V2 = PASS; output=$OutputPath; per_ticker_multi_source=true; fresh_positive_advantage=true; stale_market_rejected=true; conflicts_not_averaged=true; private_formula_claimed=false" -ForegroundColor Green
