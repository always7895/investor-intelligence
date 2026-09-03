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
    $OutputPath = Join-Path $ProjectRoot 'data\cache\v213_serenity_scoring_logic_audit_latest.json'
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
function Num([object]$Value,[double]$Default=0) {
    $result = 0.0
    if ([double]::TryParse([string]$Value,[Globalization.NumberStyles]::Float,[Globalization.CultureInfo]::InvariantCulture,[ref]$result)) { return $result }
    return $Default
}

$baseReceipt = Join-Path $env:TEMP ('v213-serenity-scoring-v1-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    & (Join-Path $ProjectRoot 'scripts\audit_v213_serenity_scoring_logic.ps1') -ProjectRoot $ProjectRoot -OutputPath $baseReceipt
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $baseReceipt -PathType Leaf)) {
        throw 'Base Serenity scoring audit failed.'
    }
    $base = Get-Content -LiteralPath $baseReceipt -Raw -Encoding utf8 | ConvertFrom-Json
    Require ([string]$base.status -eq 'PASS') 'Base Serenity scoring audit is not PASS.'
}
finally {
    Remove-Item -LiteralPath $baseReceipt -Force -ErrorAction SilentlyContinue
}

$bundle = Get-Content -LiteralPath (Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json') -Raw -Encoding utf8 | ConvertFrom-Json
$payloads = Value $bundle 'payloads' $null
$top20 = @(([string](Value $payloads 'top20_json' '')) | ConvertFrom-Json)
$source = ([string](Value $payloads 'source_independence_json' '')) | ConvertFrom-Json
$records = @(Value $source 'records' @())
Require ($top20.Count -eq 20 -and $records.Count -eq 20) 'Scoring mode audit requires 20 rows.'
$sourceByTicker = @{}
foreach ($record in $records) {
    $sourceByTicker[([string](Value $record 'ticker' '')).ToUpperInvariant()] = $record
}

$sensitive = @('demand_wave','chokepoint','pricing_power','replacement_friction','tam_capture')
$qualified = 0
$limited = 0
$limitedScoreMax = 0.0
$receipts = @()
foreach ($top in $top20) {
    $ticker = ([string](Value $top 'ticker' '')).ToUpperInvariant()
    Require ($sourceByTicker.ContainsKey($ticker)) "$ticker source record is missing."
    $record = $sourceByTicker[$ticker]
    $fresh = Value $record 'freshness_state' $null
    $mode = [string](Value $record 'publication_evidence_mode' (Value $fresh 'publication_evidence_mode' ''))
    $factors = Value $top 'serenity_factors' $null
    Require ($null -ne $factors) "$ticker factor object is missing."
    $positive = @()
    foreach ($factor in $sensitive) {
        if ((Num (Value $factors $factor 0)) -gt 0) { $positive += $factor }
    }
    $logic = Value $record 'public_logic_state' $null
    Require ($null -ne $logic) "$ticker public-logic state is missing."

    if ($mode -eq 'EVIDENCE_QUALIFIED') {
        $qualified++
        if ($positive.Count -gt 0) {
            Require (([int](Value $fresh 'fresh_claim_primary_units' 0)) -ge 1) "$ticker positive score lacks fresh primary evidence."
            Require (([int](Value $fresh 'fresh_claim_non_primary_units' 0)) -ge 1) "$ticker positive score lacks independent non-primary evidence."
        }
    }
    elseif ($mode -eq 'LIMITED_RESEARCH_CANDIDATE') {
        $limited++
        Require ($positive.Count -eq 0) "$ticker limited candidate contributes a sensitive positive factor."
        Require ((Value $record 'eligible_for_high_confidence_model_inference' $false) -eq $false) "$ticker limited candidate is high-confidence eligible."
        Require ([string](Value $logic 'model_inference_confidence' '') -eq 'LIMITED') "$ticker limited candidate model confidence is not LIMITED."
        Require ((Value $logic 'validated_company_thesis $true) -eq $false) "$ticker limited candidate is labeled a validated thesis."
        Require ((Value $logic 'identity_provenance_can_support_positive_advantage' $true) -eq $false) "$ticker identity provenance may create an advantage."
        foreach ($state in @('architecture','dependency_graph','bottleneck_or_expansion','company_capture','lifecycle')) {
            Require ([string](Value $logic $state '') -eq 'UNPROVEN') "$ticker limited candidate has a proven claim state: $state."
        }
        $limitedScoreMax = [Math]::Max($limitedScoreMax,(Num (Value $top 'serenity_score' 0))
    }
    else {
        throw "$ticker has an unknown publication evidence mode: $mode"
    }

    $receipts += [ordered]@{
        ticker = $ticker
        publication_evidence_mode = $mode
        sensitive_positive_factor_count = $positive.Count
        score = Num (Value $top 'serenity_score' 0)
        model_inference_confidence = [string](Value $logic 'model_inference_confidence' '')
        validated_company_thesis = (Value $logic 'validated_company_thesis' $false) -eq $true
        status = 'PASS'
    }
}

$result = [ordered]@{
    schema_version = 2
    product_version = '2.1.3'
    status = 'PASS'
    audited_utc = (Get-Date).ToUniversalTime().ToString('o')
    run_id = [string](Value $bundle 'run_id' '')
    evidence_qualified_candidate_count = $qualified
    limited_research_candidate_count = $limited
    limited_candidate_max_system_score = [Math]::Round($limitedScoreMax,2)
    causal_rules = [ordered]@{
        positive_advantage_requires_fresh_primary_and_independent_non_primary = $true
        limited_candidate_sensitive_positive_factors = 0
        limited_candidate_is_validated_thesis = $false
        limited_candidate_high_confidence = $false
        identity_provenance_can_create_positive_advantage = $false
        market_or_macro_can_create_company_advantage = $false
        severe_thesis_killer_precedence = $true
        aschenbrenner_overlay_included_in_system_score = $false
    }
    records = $receipts
}
$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Host "V213_SERENITY_SCORING_LOGIC_AUDIT_V2 = PASS; run_id=$($result.run_id); evidence_qualified=$qualified; limited=$limited; limited_positive_factors=0; identity_advantage_support=false" -ForegroundColor Green
