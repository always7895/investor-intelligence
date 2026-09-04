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
    $OutputPath = Join-Path $ProjectRoot 'data\cache\v213_generated_snapshot_audit_latest.json'
}

function Get-Value([object]$Object,[string]$Name,[object]$Default=$null) {
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}
function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Integer([object]$Value,[int]$Default=0) {
    $number = 0
    if ([int]::TryParse([string]$Value,[ref]$number)) { return $number }
    return $Default
}
function Number([object]$Value,[double]$Default=0) {
    $number = 0.0
    if ([double]::TryParse(
        [string]$Value,
        [Globalization.NumberStyles]::Float,
        [Globalization.CultureInfo]::InvariantCulture,
        [ref]$number
    )) { return $number }
    return $Default
}
function Parse-Date([object]$Value,[string]$Label) {
    $text = [string]$Value
    if ($text.Length -lt 10) { throw "Missing market date: $Label" }
    $date = [DateTime]::MinValue
    if (-not [DateTime]::TryParseExact(
        $text.Substring(0,10),
        'yyyy-MM-dd',
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal,
        [ref]$date
    )) { throw "Invalid market date: $Label" }
    return $date.Date
}
function Is-PrimaryFamily([string]$Family,[object]$PrimaryValue) {
    if ($PrimaryValue -eq $true) { return $true }
    return $Family -in @('regulator_filing','issuer_primary','exchange_sro')
}
function Is-ClaimSource([object]$Source) {
    $family = [string](Get-Value $Source 'family' '')
    $claimType = [string](Get-Value $Source 'claim_type' '')
    if ([string]::IsNullOrWhiteSpace($family) -or [string]::IsNullOrWhiteSpace($claimType)) { return $false }
    if ($family -in @('official_macro','yahoo_market','stooq_market','nasdaq_market','alpha_vantage_market','hfmarketdata_market')) { return $false }
    if ($family.EndsWith('_market',[StringComparison]::OrdinalIgnoreCase)) { return $false }
    if ($claimType -in @('market_return_calculation','independent_market_corroboration','macro_context','regulated_listing_identity')) { return $false }
    return $true
}

$basePath = Join-Path $env:TEMP ('v213-generated-snapshot-v2-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    & (Join-Path $ProjectRoot 'scripts\audit_v213_generated_snapshot_v2.ps1') -ProjectRoot $ProjectRoot -OutputPath $basePath
    if (-not (Test-Path -LiteralPath $basePath -PathType Leaf)) {
        throw 'Base generated-snapshot audit did not produce a receipt.'
    }
    $base = Get-Content -LiteralPath $basePath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($base.status -ne 'PASS') { throw 'Base generated-snapshot audit is not PASS.' }

    $bundlePath = Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json'
    if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) {
        throw 'Activation bundle is missing.'
    }
    $bundle = Get-Content -LiteralPath $bundlePath -Raw -Encoding utf8 | ConvertFrom-Json
    $payloads = Get-Value $bundle 'payloads' $null
    $sourceText = [string](Get-Value $payloads 'source_independence_json' '')
    if ([string]::IsNullOrWhiteSpace($sourceText)) {
        throw 'Source-independence payload is empty.'
    }
    $sourceAudit = $sourceText | ConvertFrom-Json
    $policyPath = Join-Path $ProjectRoot 'config\v213-serenity-evidence-freshness-policy.json'
    $policy = Get-Content -LiteralPath $policyPath -Raw -Encoding utf8 | ConvertFrom-Json

    $notice = Get-Value $sourceAudit 'methodology_notice' $null
    Require ($null -ne $notice) 'Source-audit methodology notice is missing.'
    Require ((Integer (Get-Value $notice 'minimum_independent_market_providers_for_high_confidence' 0)) -eq 2) 'High-confidence inference does not require two market providers.'
    Require ((Get-Value $notice 'comparable_metric_basis_required_for_high_confidence' $false) -eq $true) 'High-confidence inference does not require a comparable metric basis.'
    Require ((Get-Value $notice 'market_conflicts_compared_pairwise_without_yahoo_authority' $false) -eq $true) 'Independent market conflicts are not pairwise.'
    Require ([string](Get-Value $notice 'yahoo_role' '') -eq 'compatibility_calculation_only_not_authoritative_corroboration') 'Yahoo is not restricted to compatibility calculation.'
    Require ((Get-Value $notice 'source_conflicts_are_not_averaged' $false) -eq $true) 'Source conflicts may still be averaged.'
    Require ((Get-Value $notice 'market_data_is_not_averaged_into_published_returns' $false) -eq $true) 'Market observations may still be averaged into the published return.'
    Require ((Number (Get-Value $notice 'market_hard_max_age_days' 99) 99) -le 7) 'Market hard freshness limit exceeds seven days.'
    Require ((Number (Get-Value $notice 'market_high_confidence_freshest_max_age_days' 99) 99) -le 4) 'High-confidence freshest-market limit exceeds four days.'
    Require ((Number (Get-Value $notice 'market_comparable_provider_max_lag_days' 99) 99) -le 3) 'Comparable-provider lag limit exceeds three days.'

    $portfolio = Get-Value $sourceAudit 'portfolio' $null
    Require ($null -ne $portfolio) 'Source-audit portfolio is missing.'
    Require ((Integer (Get-Value $portfolio 'minimum_market_providers_for_high_confidence' 0)) -eq 2) 'Portfolio weakens the two-provider minimum.'
    Require ((Integer (Get-Value $portfolio 'market_conflict_ticker_count' -1)) -eq 0) 'Pairwise market conflicts remain.'
    Require ((Integer (Get-Value $portfolio 'market_calculation_divergence_ticker_count' -1)) -eq 0) 'Independent adjusted providers disagree with the compatibility calculation.'
    Require ((Get-Value $portfolio 'market_corroboration_global_blocker' $true) -eq $false) 'Passing snapshot retains a global market blocker.'

    $currentClaimMax = Number (Get-Value $policy 'current_state_claim_max_age_days' 210) 210
    $today = [DateTime]::UtcNow.Date
    $rows = @(Get-Value $sourceAudit 'records' @())
    Require ($rows.Count -eq 20) 'Market/source audit requires exactly 20 records.'
    $receipts = @()
    foreach ($row in $rows) {
        $ticker = ([string](Get-Value $row 'ticker' '')).ToUpperInvariant()
        Require ($ticker -match '^[A-Z0-9][A-Z0-9.-]{0,14}$') 'Source audit contains an invalid ticker.'
        $market = Get-Value $row 'market_corroboration' $null
        Require ($null -ne $market) "$ticker market object is missing."
        $providerCount = Integer (Get-Value $market 'independent_provider_count' 0)
        $comparableCount = Integer (Get-Value $market 'comparable_independent_provider_count' 0)
        $basis = [string](Get-Value $market 'comparable_metric_basis' '')
        Require ((Integer (Get-Value $market 'minimum_providers_for_high_confidence' 0)) -eq 2) "$ticker weakens the two-provider minimum."
        Require ((Get-Value $market 'yahoo_is_authoritative_market_source' $true) -eq $false) "$ticker still treats Yahoo as authoritative."
        Require ((Get-Value $market 'conflict_values_averaged' $true) -eq $false) "$ticker may average conflicts."
        Require ((Integer (Get-Value $market 'pairwise_conflict_count' -1)) -eq 0) "$ticker has a pairwise market conflict."
        Require (@(Get-Value $market 'pairwise_independent_provider_conflicts' @()).Count -eq 0) "$ticker has pairwise conflict details."
        Require ((Integer (Get-Value $market 'stale_or_undated_provider_count' -1)) -ge 0) "$ticker stale-provider counter is invalid."
        Require ([string](Get-Value $market 'status' '') -notin @('CONFLICT_REVIEW','CALCULATION_DIVERGENCE_REVIEW')) "$ticker market state is unresolved."

        $counted = 0
        $comparable = 0
        $freshestComparable = [DateTime]::MinValue
        $comparableDates = @()
        foreach ($provider in @(Get-Value $market 'providers' @())) {
            $status = ([string](Get-Value $provider 'status' '')).ToUpperInvariant()
            $freshCoverage = (Get-Value $provider 'fresh_for_coverage' $false) -eq $true
            $freshHigh = (Get-Value $provider 'comparable_for_high_confidence' $false) -eq $true
            if ($freshCoverage) {
                Require ($status -in @('LIVE','CACHED')) "$ticker counts a failed provider."
                $date = Parse-Date (Get-Value $provider 'as_of' '') "$ticker provider as_of"
                $age = ($today - $date).TotalDays
                Require ($age -ge -1 -and $age -le 7) "$ticker counts stale/future market data; age_days=$age."
                $counted++
            }
            elseif ($status -in @('LIVE','CACHED')) {
                throw "$ticker retains a LIVE/CACHED provider that is not fresh_for_coverage."
            }
            if ($freshHigh) {
                $date = Parse-Date (Get-Value $provider 'as_of' '') "$ticker comparable provider as_of"
                $metricBasis = [string](Get-Value $provider 'metric_basis' '')
                Require (-not [string]::IsNullOrWhiteSpace($metricBasis) -and $metricBasis -notin @('unknown','exchange_close_unadjusted_or_unknown','vendor_close_adjustment_unknown')) "$ticker counts a non-comparable metric basis."
                $comparableDates += $date
                if ($date -gt $freshestComparable) { $freshestComparable = $date }
                $comparable++
            }
        }
        Require ($counted -eq $providerCount) "$ticker provider count is not freshness-adjusted; declared=$providerCount counted=$counted."
        Require ($comparable -eq $comparableCount) "$ticker comparable-provider count mismatch; declared=$comparableCount counted=$comparable."
        if ($comparableCount -gt 0) {
            Require (-not [string]::IsNullOrWhiteSpace($basis)) "$ticker comparable metric basis is missing."
            $freshestAge = ($today - $freshestComparable).TotalDays
            Require ($freshestAge -ge -1 -and $freshestAge -le 4) "$ticker high-confidence comparable data is not latest enough; freshest_age_days=$freshestAge."
            foreach ($date in $comparableDates) {
                Require (($freshestComparable - $date).TotalDays -le 3) "$ticker comparable providers are too far apart in market date."
            }
        }

        $eligible = (Get-Value $row 'eligible_for_high_confidence_model_inference' $false) -eq $true
        $logic = Get-Value $row 'public_logic_state' $null
        Require ($null -ne $logic) "$ticker public-logic state is missing."
        Require ((Integer (Get-Value $logic 'minimum_market_providers_for_high_confidence' 0)) -eq 2) "$ticker public-logic state weakens the market minimum."
        Require ((Get-Value $logic 'market_corroboration_is_company_claim_evidence' $true) -eq $false) "$ticker uses market data as company evidence."
        Require ((Get-Value $logic 'market_metric_basis_must_match' $false) -eq $true) "$ticker does not require matching market metric bases."
        Require ((Get-Value $logic 'market_data_latestness_required' $false) -eq $true) "$ticker does not require latest market observations."
        if ($comparableCount -lt 2) {
            Require (-not $eligible) "$ticker is high-confidence without two comparable providers."
            Require ([string](Get-Value $logic 'model_inference_confidence' '') -eq 'LIMITED') "$ticker confidence must be LIMITED."
        }
        elseif ($eligible) {
            Require ([string](Get-Value $market 'status' '') -eq 'CORROBORATED') "$ticker is high-confidence without CORROBORATED market state."
            Require ([string](Get-Value $logic 'model_inference_confidence' '') -eq 'HIGH_ELIGIBLE') "$ticker eligibility and displayed confidence disagree."
        }

        # For every positive advantage, require a fresh primary source plus a
        # fresh independently operated non-primary corroborator. This prevents a
        # filing and an issuer mirror of the same disclosure from masquerading as
        # broad independent confirmation.
        $freshState = Get-Value $row 'freshness_state' $null
        Require ($null -ne $freshState) "$ticker freshness_state is missing."
        $positiveFactors = @(Get-Value $freshState 'positive_advantage_factors' @())
        $freshPrimaryUnits = @{}
        $freshNonPrimaryUnits = @{}
        foreach ($source in @(Get-Value $row 'sources' @())) {
            if (-not (Is-ClaimSource $source)) { continue }
            $url = [string](Get-Value $source 'url' '')
            if (-not $url.StartsWith('https://',[StringComparison]::OrdinalIgnoreCase)) { continue }
            $date = Parse-Date (Get-Value $source 'as_of' '') "$ticker claim source as_of"
            $age = ($today - $date).TotalDays
            if ($age -lt -1 -or $age -gt $currentClaimMax) { continue }
            $family = [string](Get-Value $source 'family' '')
            $domain = [string](Get-Value $source 'domain' '')
            $claimType = [string](Get-Value $source 'claim_type' '')
            if ([string]::IsNullOrWhiteSpace($domain)) {
                try { $domain = ([Uri]$url).Host.ToLowerInvariant() } catch { $domain = '' }
            }
            if ([string]::IsNullOrWhiteSpace($family) -or [string]::IsNullOrWhiteSpace($domain) -or [string]::IsNullOrWhiteSpace($claimType)) { continue }
            $unit = "$family|$domain|$claimType"
            if (Is-PrimaryFamily $family (Get-Value $source 'primary' $false)) {
                $freshPrimaryUnits[$unit] = $true
            }
            else {
                $freshNonPrimaryUnits[$unit] = $true
            }
        }
        if ($positiveFactors.Count -gt 0) {
            Require ($freshPrimaryUnits.Count -ge 1) "$ticker positive advantages lack a fresh primary source."
            Require ($freshNonPrimaryUnits.Count -ge 1) "$ticker positive advantages lack a fresh non-primary independent corroborator."
        }

        $receipts += [ordered]@{
            ticker = $ticker
            independent_market_provider_count = $providerCount
            comparable_market_provider_count = $comparableCount
            comparable_metric_basis = $basis
            high_confidence_eligible = $eligible
            positive_advantage_count = $positiveFactors.Count
            fresh_primary_claim_units = $freshPrimaryUnits.Count
            fresh_non_primary_claim_units = $freshNonPrimaryUnits.Count
            yahoo_authoritative = $false
            pairwise_conflict_count = 0
            calculation_divergence = $false
            status = 'PASS'
        }
    }

    $result = [ordered]@{
        schema_version = 4
        product_version = '2.1.3'
        status = 'PASS'
        audited_utc = (Get-Date).ToUniversalTime().ToString('o')
        run_id = [string](Get-Value $bundle 'run_id' '')
        base_generated_snapshot_audit = $base
        latest_multi_source_market = [ordered]@{
            yahoo_authoritative = $false
            high_confidence_provider_minimum = 2
            comparable_metric_basis_required = $true
            hard_max_age_days = 7
            freshest_max_age_days = 4
            provider_lag_max_days = 3
            pairwise_conflict_ticker_count = 0
            calculation_divergence_ticker_count = 0
            conflicts_averaged = $false
        }
        positive_company_advantages = [ordered]@{
            fresh_primary_source_required = $true
            fresh_non_primary_corroborator_required = $true
            market_or_macro_can_prove_advantage = $false
        }
        records = $receipts
    }
    $parent = Split-Path -Parent $OutputPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $result | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $OutputPath -Encoding utf8
    Write-Host "V213_GENERATED_SNAPSHOT_AUDIT_V4 = PASS; run_id=$($result.run_id); latest_market=true; comparable_providers_for_high_confidence=2; pairwise_conflicts=0; yahoo_authoritative=false; positive_advantage_primary_plus_independent=true" -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $basePath -Force -ErrorAction SilentlyContinue
}
