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
function Value([object]$Object,[string]$Name,[object]$Default=$null) {
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}
function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Int([object]$Value,[int]$Default=0) {
    $result = 0
    if ([int]::TryParse([string]$Value,[ref]$result)) { return $result }
    return $Default
}
function Num([object]$Value,[double]$Default=0) {
    $result = 0.0
    if ([double]::TryParse([string]$Value,[Globalization.NumberStyles]::Float,[Globalization.CultureInfo]::InvariantCulture,[ref]$result)) { return $result }
    return $Default
}

$baseReceipt = Join-Path $env:TEMP ('v213-generated-snapshot-v4-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    & (Join-Path $ProjectRoot 'scripts\audit_v213_generated_snapshot_v4.ps1') -ProjectRoot $ProjectRoot -OutputPath $baseReceipt
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $baseReceipt -PathType Leaf)) {
        throw 'Base generated snapshot audit v4 failed.'
    }
    $base = Get-Content -LiteralPath $baseReceipt -Raw -Encoding utf8 | ConvertFrom-Json
    Require ([string]$base.status -eq 'PASS') 'Base generated snapshot audit v4 is not PASS.'
}
finally {
    Remove-Item -LiteralPath $baseReceipt -Force -ErrorAction SilentlyContinue
}

$bundlePath = Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json'
Require (Test-Path -LiteralPath $bundlePath -PathType Leaf) 'Activation bundle is missing.'
$bundle = Get-Content -LiteralPath $bundlePath -Raw -Encoding utf8 | ConvertFrom-Json
$payloads = Value $bundle 'payloads' $null
$top20 = @(([string](Value $payloads 'top20_json' '')) | ConvertFrom-Json)
$source = ([string](Value $payloads 'source_independence_json' '')) | ConvertFrom-Json
$records = @(Value $source 'records' @())
Require ($top20.Count -eq 20 -and $records.Count -eq 20) 'Publication-mode audit requires 20 aligned rows.'

$sourceByTicker = @{}
foreach ($record in $records) {
    $ticker = ([string](Value $record 'ticker' '')).ToUpperInvariant()
    Require (-not [string]::IsNullOrWhiteSpace($ticker) -and -not $sourceByTicker.ContainsKey($ticker)) 'Source record membership is invalid.'
    $sourceByTicker[$ticker] = $record
}

$sensitive = @('demand_wave','chokepoint','pricing_power','replacement_friction','tam_capture')
$qualifiedCount = 0
$limitedCount = 0
$receipts = @()
for ($index = 0; $index -lt 20; $index++) {
    $top = $top20[$index]
    $ticker = ([string](Value $top 'ticker' '')).ToUpperInvariant()
    Require ($sourceByTicker.ContainsKey($ticker)) "$ticker is missing from the final source audit."
    $record = $sourceByTicker[$ticker]
    $fresh = Value $record 'freshness_state' $null
    Require ($null -ne $fresh -and [string](Value $fresh 'status' '') -eq 'PASS') "$ticker freshness state is missing or failed."
    $mode = [string](Value $record 'publication_evidence_mode' (Value $fresh 'publication_evidence_mode' ''))
    Require ($mode -in @('EVIDENCE_QUALIFIED','LIMITED_RESEARCH_CANDIDATE')) "$ticker publication evidence mode is invalid."

    $factors = Value $top 'serenity_factors' $null
    Require ($null -ne $factors) "$ticker factors are missing."
    $positive = @()
    foreach ($factor in $sensitive) {
        if ((Num (Value $factors $factor 0)) -gt 0) { $positive += $factor }
    }
    $logic = Value $record 'public_logic_state' $null
    Require ($null -ne $logic) "$ticker public-logic state is missing."
    $metrics = Value $record 'source_metrics' $null
    Require ($null -ne $metrics) "$ticker source metrics are missing."
    $missing = @((Value $record 'missing_or_review' @()) | ForEach-Object { [string]$_ })
    $eligible = (Value $record 'eligible_for_high_confidence_model_inference' $false) -eq $true

    $claimFamilies = Int (Value $fresh 'claim_source_families' 0)
    $claimDomains = Int (Value $fresh 'claim_source_domains' 0)
    $claimPrimary = Int (Value $fresh 'claim_primary_units' 0)
    $provenanceOrigins = Int (Value $fresh 'publication_provenance_origin_count' 0)
    $provenanceDomains = Int (Value $fresh 'publication_provenance_domain_count' 0)

    if ($mode -eq 'EVIDENCE_QUALIFIED') {
        $qualifiedCount++
        Require ($claimFamilies -ge 2) "$ticker evidence-qualified row has fewer than two claim families."
        Require ($claimDomains -ge 2) "$ticker evidence-qualified row has fewer than two claim domains."
        Require ($claimPrimary -ge 1) "$ticker evidence-qualified row lacks primary company evidence."
        if ($positive.Count -gt 0) {
            Require ((Int (Value $fresh 'fresh_claim_primary_units' 0)) -ge 1) "$ticker positive advantages lack fresh primary evidence."
            Require ((Int (Value $fresh 'fresh_claim_non_primary_units' 0)) -ge 1) "$ticker positive advantages lack a fresh independently operated non-primary corroborator."
        }
    }
    else {
        $limitedCount++
        Require ($positive.Count -eq 0) "$ticker limited research candidate retains positive Serenity advantages: $($positive -join ',')."
        Require (-not $eligible) "$ticker limited research candidate is high-confidence eligible."
        Require ([string](Value $logic 'model_inference_confidence' '') -eq 'LIMITED') "$ticker limited research candidate is not LIMITED."
        Require ((Value $logic 'validated_company_thesis $true) -eq $false) "$ticker limited research candidate is mislabeled as a validated thesis."
        Require ((Value $logic 'identity_provenance_is_company_claim_evidence' $true) -eq $false) "$ticker identity provenance is treated as company evidence."
        Require ((Value $logic 'identity_provenance_can_support_positive_advantage' $true) -eq $false) "$ticker identity provenance may support a positive advantage."
        Require ($claimPrimary -ge 1) "$ticker limited research candidate lacks a latest-available primary company source."
        Require ($provenanceOrigins -ge 2) "$ticker limited research candidate depends on one publication origin."
        Require ($provenanceDomains -ge 2) "$ticker limited research candidate depends on one publication domain."
        Require ($missing -contains 'INDEPENDENT_CLAIM_CORROBORATION') "$ticker limited research candidate does not disclose missing independent claim corroboration."
        Require ($missing -contains 'LIMITED_RESEARCH_CANDIDATE') "$ticker limited research candidate mode is not disclosed."
        Require ((Num (Value $factors 'valuation_expectations' 99) 99) -le 3.75) "$ticker limited research candidate exceeds the uncorroborated valuation cap."
    }

    $receipts += [ordered]@{
        rank = $index + 1
        ticker = $ticker
        publication_evidence_mode = $mode
        sensitive_positive_factor_count = $positive.Count
        claim_source_families = $claimFamilies
        claim_source_domains = $claimDomains
        claim_primary_units = $claimPrimary
        publication_provenance_origins = $provenanceOrigins
        publication_provenance_domains = $provenanceDomains
        high_confidence_eligible = $eligible
        status = 'PASS'
    }
}

$portfolio = Value $source 'portfolio' $null
$freshnessAudit = Value $source 'freshness_audit' $null
Require ($null -ne $portfolio -and $null -ne $freshnessAudit) 'Final source audit lacks portfolio/freshness summaries.'
Require ((Int (Value $portfolio 'evidence_qualified_candidate_count' -1)) -eq $qualifiedCount) 'Evidence-qualified count mismatch.'
Require ((Int (Value $portfolio 'limited_research_candidate_count' -1)) -eq $limitedCount) 'Limited-candidate count mismatch.'
Require ((Int (Value $portfolio 'limited_rows_high_confidence_eligible_count' -1)) -eq 0) 'A limited row is high-confidence eligible.'
Require ((Value $portfolio 'all_rows_publication_provenance_multi_source' $false) -eq $true) 'Not every final row has independent publication provenance.'
Require ((Value $freshnessAudit 'all_tickers_publication_provenance_multi_source' $false) -eq $true) 'Freshness receipt does not prove multi-source publication provenance.'
Require ((Value $freshnessAudit 'all_positive_advantages_fresh_multi_source' $false) -eq $true) 'Freshness receipt does not prove positive-advantage source quality.'

$result = [ordered]@{
    schema_version = 5
    product_version = '2.1.3'
    status = 'PASS'
    audited_utc = (Get-Date).ToUniversalTime().ToString('o')
    run_id = [string](Value $bundle 'run_id' '')
    evidence_qualified_candidate_count = $qualifiedCount
    limited_research_candidate_count = $limitedCount
    all_rows_independ_publication_provenance = $true
    single_source_positive_advantage = $false
    limited_candidate_is_validated_thesis = $false
    limited_candidate_high_confidence = $false
    records = $receipts
}
$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Host "V213_GENERATED_SNAPSHOT_AUDIT_V5 = PASS; run_id=$($result.run_id); evidence_qualified=$qualifiedCount; limited=$limitedCount; all_rows_multi_origin=true; single_source_positive_advantage=false" -ForegroundColor Green
