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

function Get-Value([object]$Object,[string]$Name,[object]$Default=$null) {
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}
function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
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
function State-Proven([object]$Logic,[string]$Name) {
    $state = ([string](Get-Value $Logic $Name '')).ToUpperInvariant()
    return -not [string]::IsNullOrWhiteSpace($state) -and $state -notin @('UNPROVEN','UNKNOWN','INSUFFICIENT_EVIDENCE','NOT_ATTACHED')
}

$bundlePath = Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json'
if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) { throw 'Activation bundle is missing.' }
$bundle = Get-Content -LiteralPath $bundlePath -Raw -Encoding utf8 | ConvertFrom-Json
$payloads = Get-Value $bundle 'payloads' $null
$topText = [string](Get-Value $payloads 'top20_json' '')
$sourceText = [string](Get-Value $payloads 'source_independence_json' '')
if ([string]::IsNullOrWhiteSpace($topText) -or [string]::IsNullOrWhiteSpace($sourceText)) {
    throw 'Top20 or source-independence payload is empty.'
}
$top20 = @($topText | ConvertFrom-Json)
$sourceAudit = $sourceText | ConvertFrom-Json
$sourceRows = @(Get-Value $sourceAudit 'records' @())
Require ($top20.Count -eq 20 -and $sourceRows.Count -eq 20) 'Scoring audit requires exactly 20 aligned rows.'

$sourceByTicker = @{}
foreach ($row in $sourceRows) {
    $ticker = ([string](Get-Value $row 'ticker' '')).ToUpperInvariant()
    Require (-not [string]::IsNullOrWhiteSpace($ticker) -and -not $sourceByTicker.ContainsKey($ticker)) 'Source audit ticker membership is invalid.'
    $sourceByTicker[$ticker] = $row
}

$sensitiveFactors = @('demand_wave','chokepoint','pricing_power','replacement_friction','tam_capture')
$severeKillerPatterns = @(
    'architecture_bypass','factual_dependency_contradiction',
    'equity_capture_destroyed_by_financing','thesis_broken',
    'broken_thesis','dependency_contradiction'
)
$receipts = @()
$explicitFactorBindingCount = 0
for ($index = 0; $index -lt 20; $index++) {
    $top = $top20[$index]
    $ticker = ([string](Get-Value $top 'ticker' '')).ToUpperInvariant()
    Require ($sourceByTicker.ContainsKey($ticker)) "$ticker is missing from source audit."
    Require (([int](Get-Value $top 'rank' 0)) -eq ($index + 1)) "$ticker rank/order is invalid."
    Require ([string](Get-Value $top 'scoring_version' '') -eq 'system-operationalization-v2.1.3-diversified') "$ticker uses a provisional or legacy scoring version."
    Require ((Get-Value $top 'line_public_eligible' $false) -eq $true) "$ticker is not marked public eligible."
    Require ([string](Get-Value $top 'provider_scope' '') -eq 'public_only') "$ticker is not public_only."
    Require ((Get-Value $top 'owner_watchlist_inherited' $true) -eq $false) "$ticker inherited a private owner watchlist."

    $overlay = Get-Value $top 'aschenbrenner_overlay' $null
    if ($null -ne $overlay) {
        Require ((Get-Value $overlay 'included_in_serenity_score' $true) -eq $false) "$ticker improperly includes the Aschenbrenner overlay in the Serenity score."
    }

    $rawScore = Number (Get-Value $top 'serenity_raw_score' 0)
    $finalScore = Number (Get-Value $top 'serenity_score' 0)
    $riskPenalty = Number (Get-Value $top 'risk_penalty' 0)
    Require ($riskPenalty -ge 0) "$ticker has a negative risk penalty."
    Require ($finalScore -le ($rawScore + 0.001)) "$ticker final score exceeds its pre-risk score."
    if ($null -ne $top.PSObject.Properties['serenity_raw_score'] -and $null -ne $top.PSObject.Properties['risk_penalty']) {
        Require ([Math]::Abs(($rawScore - $riskPenalty) - $finalScore) -le 0.11) "$ticker score/risk-penalty arithmetic is inconsistent."
    }

    $factors = Get-Value $top 'serenity_factors' $null
    Require ($null -ne $factors) "$ticker Serenity factors are missing."
    $positive = @()
    foreach ($factor in $sensitiveFactors) {
        $value = Number (Get-Value $factors $factor 0)
        Require ($value -ge 0 -and $value -le 1000) "$ticker factor $factor is invalid."
        if ($value -gt 0) { $positive += $factor }
    }

    $source = $sourceByTicker[$ticker]
    $logic = Get-Value $source 'public_logic_state' $null
    Require ($null -ne $logic) "$ticker public-logic state is missing."
    $fresh = Get-Value $source 'freshness_state' $null
    Require ($null -ne $fresh -and [string](Get-Value $fresh 'status' '') -eq 'PASS') "$ticker freshness state is missing or failed."
    $declaredPositive = @((Get-Value $fresh 'positive_advantage_factors' @()) | ForEach-Object { [string]$_ })
    Require (($positive -join '|') -eq ($declaredPositive -join '|')) "$ticker factor list does not match its freshness receipt."

    $sensitiveClaim = (Get-Value $source 'sensitive_claim_present' $false) -eq $true
    if ((Number (Get-Value $factors 'chokepoint' 0)) -gt 0) {
        Require $sensitiveClaim "$ticker has a positive chokepoint factor without a sensitive evidence-bound claim."
        Require (State-Proven $logic 'architecture') "$ticker chokepoint factor lacks architecture evidence."
        Require (State-Proven $logic 'dependency_graph') "$ticker chokepoint factor lacks a dependency graph."
        Require (State-Proven $logic 'bottleneck_or_expansion') "$ticker chokepoint factor is not distinguished from ordinary expansion."
    }
    if ((Number (Get-Value $factors 'replacement_friction' 0)) -gt 0) {
        Require $sensitiveClaim "$ticker has replacement friction without a sensitive evidence-bound claim."
        Require (State-Proven $logic 'dependency_graph') "$ticker replacement-friction factor lacks dependency/qualification evidence."
    }
    if ((Number (Get-Value $factors 'pricing_power' 0)) -gt 0) {
        Require $sensitiveClaim "$ticker has pricing power without a sensitive evidence-bound claim."
        Require (State-Proven $logic 'company_capture') "$ticker pricing-power factor lacks company-capture evidence."
    }
    if ((Number (Get-Value $factors 'tam_capture' 0)) -gt 0) {
        Require (State-Proven $logic 'company_capture') "$ticker TAM-capture factor is inferred from growth without company-capture evidence."
    }

    $riskFlags = @((Get-Value $top 'risk_flags' @()) | ForEach-Object { ([string]$_).ToLowerInvariant() })
    $severe = @()
    foreach ($flag in $riskFlags) {
        foreach ($pattern in $severeKillerPatterns) {
            if ($flag.Contains($pattern)) { $severe += $flag; break }
        }
    }
    Require ($severe.Count -eq 0) "$ticker has an unresolved severe thesis killer in a publishable Top20 row: $($severe -join ',')."

    $boundFactors = @{}
    foreach ($evidence in @(Get-Value $top 'evidence' @())) {
        foreach ($factor in @(Get-Value $evidence 'supports_factors' @())) {
            $name = [string]$factor
            if ($name -in $sensitiveFactors) { $boundFactors[$name] = $true }
        }
    }
    if ($positive.Count -gt 0 -and ($positive | Where-Object { $boundFactors.ContainsKey($_) }).Count -eq $positive.Count) {
        $explicitFactorBindingCount++
    }

    $receipts += [ordered]@{
        rank = $index + 1
        ticker = $ticker
        raw_score = $rawScore
        risk_penalty = $riskPenalty
        final_score = $finalScore
        positive_factors = $positive
        sensitive_claim_present = $sensitiveClaim
        architecture_state = [string](Get-Value $logic 'architecture' '')
        dependency_graph_state = [string](Get-Value $logic 'dependency_graph' '')
        bottleneck_or_expansion_state = [string](Get-Value $logic 'bottleneck_or_expansion' '')
        company_capture_state = [string](Get-Value $logic 'company_capture' '')
        severe_thesis_killer_count = 0
        explicit_factor_to_evidence_binding_complete = ($positive.Count -eq 0 -or ($positive | Where-Object { $boundFactors.ContainsKey($_) }).Count -eq $positive.Count)
        status = 'PASS'
    }
}

$result = [ordered]@{
    schema_version = 1
    product_version = '2.1.3'
    status = 'PASS'
    audited_utc = (Get-Date).ToUniversalTime().ToString('o')
    run_id = [string](Get-Value $bundle 'run_id' '')
    scoring_version = 'system-operationalization-v2.1.3-diversified'
    causality_guards = [ordered]@{
        keyword_alone_can_prove_chokepoint = $false
        growth_alone_can_prove_tam_capture = $false
        margin_alone_can_prove_replacement_friction = $false
        price_action_can_prove_company_advantage = $false
        chokepoint_requires_architecture_and_dependency_graph = $true
        pricing_power_requires_company_capture = $true
        severe_thesis_killer_overrides_positive_score = $true
        aschenbrenner_overlay_included_in_serenity_score = $false
    }
    explicit_factor_to_evidence_binding = [ordered]@{
        complete_ticker_count = $explicitFactorBindingCount
        required_for_this_release = $false
        limitation = 'Current release verifies fresh primary plus independent corroboration at ticker level and causal public-logic states. Exact URL-to-factor supports_factors binding is not yet universal and must not be represented as verified causal truth.'
    }
    records = $receipts
}
$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Host "V213_SERENITY_SCORING_LOGIC_AUDIT = PASS; run_id=$($result.run_id); factor_causality=true; severe_killer_precedence=true; score_risk_arithmetic=true; explicit_factor_binding_complete=$explicitFactorBindingCount/20" -ForegroundColor Green
