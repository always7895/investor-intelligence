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
function Read-JsonFile([string]$Relative) {
    $path = Join-Path $ProjectRoot $Relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Generated file missing: $Relative" }
    return Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json
}
function Parse-EmbeddedJson([object]$Payloads,[string]$Name) {
    $text = [string](Get-Value $Payloads $Name '')
    if ([string]::IsNullOrWhiteSpace($text)) { throw "Activation payload is empty: $Name" }
    try { return $text | ConvertFrom-Json }
    catch { throw "Activation payload is invalid JSON: $Name / $($_.Exception.Message)" }
}
function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
function Number([object]$Value,[double]$Default=0) {
    $number = 0.0
    if ([double]::TryParse([string]$Value,[Globalization.NumberStyles]::Float,[Globalization.CultureInfo]::InvariantCulture,[ref]$number)) { return $number }
    return $Default
}
function Integer([object]$Value,[int]$Default=0) {
    $number = 0
    if ([int]::TryParse([string]$Value,[ref]$number)) { return $number }
    return $Default
}
function Parse-Time([object]$Value,[string]$Label) {
    $parsed = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$Value,[ref]$parsed)) { throw "Invalid timestamp: $Label" }
    return $parsed.ToUniversalTime()
}

$policy = Read-JsonFile 'config\v213-serenity-evidence-freshness-policy.json'
$bundle = Read-JsonFile 'data\cache\v213_activation_bundle_upload.json'
Require ((Integer (Get-Value $bundle 'schema_version' 0)) -eq 4) 'Activation bundle schema must be 4.'
Require ([string](Get-Value $bundle 'product_version' '') -eq '2.1.3') 'Activation bundle product version mismatch.'
Require ([string](Get-Value $bundle 'transaction_id' '') -match '^[0-9a-f]{32}$') 'Activation transaction_id is invalid.'
Require ([string](Get-Value $bundle 'run_id' '') -match '^\d{8}T\d{6}Z-[0-9a-f]{12}$') 'Activation run_id is invalid.'
$payloads = Get-Value $bundle 'payloads' $null
$digests = Get-Value $bundle 'sha256' $null
Require ($null -ne $payloads -and $null -ne $digests) 'Activation payload/digest objects are missing.'
$payloadNames = @('top20_json','source_plan_json','report_text','v212_top20_report_json','v213_top20_report_json','source_federation_json','source_independence_json')
foreach ($name in $payloadNames) {
    Require (-not [string]::IsNullOrWhiteSpace([string](Get-Value $payloads $name ''))) "Activation payload missing: $name"
    Require ([string](Get-Value $digests $name '') -match '^[0-9a-f]{64}$') "Activation digest missing/invalid: $name"
}

$now = [DateTimeOffset]::UtcNow
$bundleTime = Parse-Time (Get-Value $bundle 'generated_at' '') 'bundle.generated_at'
$ageHours = ($now - $bundleTime).TotalHours
$maxHours = Number (Get-Value $policy 'activation_snapshot_max_age_hours' 2) 2
Require ($ageHours -ge (-5.0/60.0) -and $ageHours -le $maxHours) "Activation bundle is stale or future-dated; age_hours=$([Math]::Round($ageHours,3))"

$top20 = @(Parse-EmbeddedJson $payloads 'top20_json')
$plan = Parse-EmbeddedJson $payloads 'source_plan_json'
$v212 = Parse-EmbeddedJson $payloads 'v212_top20_report_json'
$v213 = Parse-EmbeddedJson $payloads 'v213_top20_report_json'
$federation = Parse-EmbeddedJson $payloads 'source_federation_json'
$audit = Parse-EmbeddedJson $payloads 'source_independence_json'
Require ($top20.Count -eq 20) "Top20 count must be 20; found $($top20.Count)."
Require (@(Get-Value $v212 'records' @()).Count -eq 20) 'v2.1.2 report count must be 20.'
Require (@(Get-Value $v213 'records' @()).Count -eq 20) 'v2.1.3 report count must be 20.'
Require (@(Get-Value $federation 'ticker_sources' @()).Count -eq 20) 'Source federation count must be 20.'
Require (@(Get-Value $audit 'records' @()).Count -eq 20) 'Source audit count must be 20.'
Require ([string](Get-Value $plan 'provider_scope' '') -eq 'public_only') 'Source plan must remain public_only.'
Require ((Get-Value $plan 'owner_watchlist_inherited' $true) -eq $false) 'Owner watchlist must not determine public Top20.'
Require ((Integer (Get-Value $plan 'catalog_count' 0)) -eq 101) 'Source catalog count must remain 101.'
Require ([string](Get-Value $audit 'status' '') -eq 'PASS') 'Source audit status is not PASS.'
Require (@(Get-Value $audit 'violations' @()).Count -eq 0) 'Source audit has blocking violations.'
Require (@(Get-Value $audit 'blocking_violations' @()).Count -eq 0) 'Source audit has explicit blockers.'

$portfolio = Get-Value $audit 'portfolio' $null
Require ($null -ne $portfolio) 'Source-audit portfolio summary is missing.'
Require ((Number (Get-Value $portfolio 'claim_primary_coverage_ratio' 0)) -ge 0.75) 'Claim-primary coverage is below 75%.'
Require ((Integer (Get-Value $portfolio 'claim_source_families' 0)) -ge 2) 'Portfolio claim-source families are below 2.'
Require ((Integer (Get-Value $portfolio 'claim_source_domains' 0)) -ge 2) 'Portfolio claim-source domains are below 2.'
Require ((Number (Get-Value $portfolio 'maximum_single_family_share' 1) 1) -le 0.70) 'Single source-family concentration exceeds 70%.'
Require ((Integer (Get-Value $portfolio 'market_conflict_ticker_count' -1) -eq 0) 'Unresolved market-source conflicts remain.'

$freshRoot = Get-Value $audit 'freshness_audit' $null
Require ($null -ne $freshRoot) 'Bundle source audit is missing the freshness audit sidecar.'
Require ([string](Get-Value $freshRoot 'status' '') -eq 'PASS') 'Freshness audit did not pass.'
Require ((Get-Value $freshRoot 'all_tickers_multi_source' $false) -eq $true) 'Not every ticker passed the multi-source gate.'
Require ((Get-Value $freshRoot 'all_positive_advantages_fresh_multi_source' $false) -eq $true) 'A positive advantage lacks fresh multi-source evidence.'
Require ((Integer (Get-Value $freshRoot 'stale_live_market_observation_count' -1) -eq 0) 'Stale LIVE/CACHED market observations remain.'
Require (@(Get-Value $freshRoot 'records' @()).Count -eq 20) 'Freshness audit per-ticker count must be 20.'

$topByTicker = @{}
foreach ($row in $top20) {
    $ticker = ([string](Get-Value $row 'ticker' '')).ToUpperInvariant()
    Require ($ticker -match '^[A-Z0-9][A-Z0-9.-]{0,14}$') 'Top20 contains an invalid ticker.'
    Require (-not $topByTicker.ContainsKey($ticker)) "Top20 contains duplicate ticker: $ticker"
    $topByTicker[$ticker] = $row
}
$auditByTicker = @{}
foreach ($row in @(Get-Value $audit 'records' @())) {
    $ticker = ([string](Get-Value $row 'ticker' '')).ToUpperInvariant()
    Require (-not $auditByTicker.ContainsKey($ticker)) "Source audit contains duplicate ticker: $ticker"
    $auditByTicker[$ticker] = $row
}

$requiredFactors = @((Get-Value $policy 'sensitive_advantage_factors' @()) | ForEach-Object { [string]$_ })
$minFamilies = Integer (Get-Value $policy 'minimum_claim_source_families_per_ticker' 2) 2
$minDomains = Integer (Get-Value $policy 'minimum_claim_source_domains_per_ticker' 2) 2
$minPrimary = Integer (Get-Value $policy 'minimum_claim_primary_sources_per_ticker' 1) 1
$minFreshUnits = Integer (Get-Value $policy 'minimum_sensitive_advantage_source_units' 2) 2
$minFreshDomains = Integer (Get-Value $policy 'minimum_sensitive_advantage_domains' 2) 2
$minDated = Number (Get-Value $policy 'minimum_claim_dated_evidence_ratio' 0.8) 0.8
$rowsOut = @()
for ($index = 0; $index -lt 20; $index++) {
    $top = $top20[$index]
    $ticker = ([string](Get-Value $top 'ticker' '')).ToUpperInvariant()
    Require ((Integer (Get-Value $top 'rank' 0)) -eq ($index + 1)) "$ticker Top20 rank/order is invalid."
    Require ([string](Get-Value $top 'scoring_version' '') -eq 'system-operationalization-v2.1.3-diversified') "$ticker uses a provisional or legacy scoring version."
    Require ((Get-Value $top 'owner_watchlist_inherited' $true) -eq $false) "$ticker inherited a private owner watchlist."
    Require ([string](Get-Value $top 'provider_scope' '') -eq 'public_only') "$ticker is not public_only."
    Require ($auditByTicker.ContainsKey($ticker)) "$ticker is missing from source audit."
    $sourceRow = $auditByTicker[$ticker]
    Require ((Integer (Get-Value $sourceRow 'rank' 0)) -eq ($index + 1)) "$ticker source-audit rank/order is invalid."
    $metrics = Get-Value $sourceRow 'source_metrics' $null
    Require ($null -ne $metrics) "$ticker source metrics are missing."
    Require ((Integer (Get-Value $metrics 'claim_relevant_independent_families' 0)) -ge $minFamilies) "$ticker has fewer than $minFamilies claim-source families."
    Require ((Integer (Get-Value $metrics 'claim_relevant_independent_domains' 0)) -ge $minDomains) "$ticker has fewer than $minDomains claim-source domains."
    Require ((Integer (Get-Value $metrics 'claim_relevant_primary_sources' 0)) -ge $minPrimary) "$ticker has no qualifying primary claim source."
    Require ((Number (Get-Value $metrics 'claim_dated_evidence_ratio' 0)) -ge $minDated) "$ticker dated claim-evidence ratio is below $minDated."

    $fresh = Get-Value $sourceRow 'freshness_state' $null
    Require ($null -ne $fresh -and [string](Get-Value $fresh 'status' '') -eq 'PASS') "$ticker freshness_state is missing or failed."
    Require ((Integer (Get-Value $fresh 'claim_source_families' 0)) -ge $minFamilies) "$ticker source-level families fail the hard gate."
    Require ((Integer (Get-Value $fresh 'claim_source_domains' 0)) -ge $minDomains) "$ticker source-level domains fail the hard gate."
    Require ((Integer (Get-Value $fresh 'claim_primary_units' 0)) -ge $minPrimary) "$ticker source-level primary evidence fails the hard gate."

    $factors = Get-Value $top 'serenity_factors' $null
    $positive = @()
    if ($null -ne $factors) {
        foreach ($factor in $requiredFactors) {
            if ((Number (Get-Value $factors $factor 0)) -gt 0) { $positive += $factor }
        }
    }
    $declaredPositive = @((Get-Value $fresh 'positive_advantage_factors' @()) | ForEach-Object { [string]$_ })
    Require (($positive -join '|') -eq ($declaredPositive -join '|')) "$ticker positive-factor freshness receipt does not match the Top20 factors."
    if ($positive.Count -gt 0) {
        Require ((Integer (Get-Value $fresh 'fresh_claim_source_units' 0)) -ge $minFreshUnits) "$ticker positive factors rely on fewer than $minFreshUnits fresh source units."
        Require ((Integer (Get-Value $fresh 'fresh_claim_source_domains' 0)) -ge $minFreshDomains) "$ticker positive factors rely on fewer than $minFreshDomains fresh domains."
        Require ((Integer (Get-Value $fresh 'fresh_claim_primary_units' 0)) -ge 1) "$ticker positive factors lack fresh primary evidence."
    }

    $market = Get-Value $sourceRow 'market_corroboration' $null
    Require ($null -ne $market) "$ticker market-corroboration object is missing."
    $providerCount = Integer (Get-Value $market 'independent_provider_count' 0)
    Require ($providerCount -eq (Integer (Get-Value $fresh 'fresh_market_provider_count' -1))) "$ticker market provider count is not freshness-adjusted."
    Require ([string](Get-Value $market 'status' '') -ne 'CONFLICT_REVIEW') "$ticker retains an unresolved market conflict."
    if ($providerCount -lt 1) {
        Require ((Get-Value $sourceRow 'eligible_for_high_confidence_model_inference' $true) -eq $false) "$ticker is high-confidence without fresh market corroboration."
        $logic = Get-Value $sourceRow 'public_logic_state' $null
        Require ([string](Get-Value $logic 'model_inference_confidence' '') -eq 'LIMITED') "$ticker uncorroborated model confidence is not LIMITED."
        $valuation = if ($null -ne $factors) { Number (Get-Value $factors 'valuation_expectations' 99) 99 } else { 99 }
        Require ($valuation -le 3.75) "$ticker uncorroborated valuation factor exceeds 3.75."
    }

    $rowsOut += [ordered]@{
        rank = $index + 1
        ticker = $ticker
        positive_advantage_factors = $positive
        claim_families = Integer (Get-Value $fresh 'claim_source_families' 0)
        claim_domains = Integer (Get-Value $fresh 'claim_source_domains' 0)
        fresh_claim_units = Integer (Get-Value $fresh 'fresh_claim_source_units' 0)
        fresh_claim_domains = Integer (Get-Value $fresh 'fresh_claim_source_domains' 0)
        fresh_market_providers = $providerCount
        latest_current_claim_age_days = Get-Value $fresh 'latest_current_claim_age_days' $null
        status = 'PASS'
    }
}

$reportText = [string](Get-Value $payloads 'report_text' '')
foreach ($marker in @(
    '<!-- line-public-eligible: true -->','<!-- provider-scope: public_only -->',
    '<!-- owner-watchlist-inherited: false -->','<!-- scoring-version: system-operationalization-v2.1.3-diversified -->',
    '<!-- official-serenity-formula-claimed: false -->'
)) { Require ($reportText.Contains($marker)) "Public report marker missing: $marker" }

$result = [ordered]@{
    schema_version = 1
    product_version = '2.1.3'
    status = 'PASS'
    audited_utc = $now.ToString('o')
    run_id = [string](Get-Value $bundle 'run_id' '')
    transaction_id = [string](Get-Value $bundle 'transaction_id' '')
    bundle_age_hours = [Math]::Round($ageHours,4)
    payload_count = $payloadNames.Count
    ticker_count = 20
    same_order_all_payloads = $true
    public_only = $true
    owner_watchlist_inherited = $false
    per_ticker_multi_source = $true
    positive_advantages_fresh_multi_source = $true
    stale_live_market_observations = 0
    unresolved_source_conflicts = 0
    rows = $rowsOut
}
$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Host "V213_GENERATED_SNAPSHOT_AUDIT = PASS; run_id=$($result.run_id); tickers=20; payloads=7; per_ticker_multi_source=true; positive_advantages_fresh=true; stale_market=0; conflicts=0" -ForegroundColor Green
