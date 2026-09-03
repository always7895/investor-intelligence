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

$baseAuditPath = Join-Path $env:TEMP ('v213-generated-snapshot-v2-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    & (Join-Path $ProjectRoot 'scripts\audit_v213_generated_snapshot_v2.ps1') -ProjectRoot $ProjectRoot -OutputPath $baseAuditPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $baseAuditPath -PathType Leaf)) {
        throw 'Base generated-snapshot audit failed.'
    }

    $bundlePath = Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json'
    if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) {
        throw 'Activation bundle is missing for market-independence audit.'
    }
    $bundle = Get-Content -LiteralPath $bundlePath -Raw -Encoding utf8 | ConvertFrom-Json
    $payloads = Get-Value $bundle 'payloads' $null
    $sourceText = [string](Get-Value $payloads 'source_independence_json' '')
    if ([string]::IsNullOrWhiteSpace($sourceText)) { throw 'Source-independence payload is empty.' }
    $sourceAudit = $sourceText | ConvertFrom-Json

    $notice = Get-Value $sourceAudit 'methodology_notice' $null
    Require ($null -ne $notice) 'Source audit methodology notice is missing.'
    Require ((Integer (Get-Value $notice 'minimum_independent_market_providers_for_high_confidence' 0)) -eq 2) 'High-confidence inference does not require two independent market providers.'
    Require ((Get-Value $notice 'market_conflicts_compared_pairwise_without_yahoo_authority' $false) -eq $true) 'Independent market conflicts are not compared pairwise.'
    Require ([string](Get-Value $notice 'yahoo_role' '') -eq 'compatibility_calculation_only_not_authoritative_corroboration') 'Yahoo is not restricted to the non-authoritative compatibility-calculation role.'
    Require ((Get-Value $notice 'source_conflicts_are_not_averaged' $false) -eq $true) 'Source conflicts may still be averaged.'
    Require ((Get-Value $notice 'market_data_is_not_averaged_into_published_returns' $false) -eq $true) 'Independent market returns may still be averaged into the published calculation.'

    $portfolio = Get-Value $sourceAudit 'portfolio' $null
    Require ($null -ne $portfolio) 'Source-audit portfolio is missing.'
    Require ((Integer (Get-Value $portfolio 'minimum_market_providers_for_high_confidence' 0)) -eq 2) 'Portfolio does not preserve the two-provider confidence minimum.'
    Require ((Integer (Get-Value $portfolio 'market_conflict_ticker_count' -1)) -eq 0) 'Pairwise independent-market conflicts remain.'
    Require ((Integer (Get-Value $portfolio 'market_calculation_divergence_ticker_count' -1)) -eq 0) 'Independent providers still disagree materially with the compatibility calculation.'

    $rows = @(Get-Value $sourceAudit 'records' @())
    Require ($rows.Count -eq 20) 'Market-independence audit requires exactly 20 records.'
    $rowReceipts = @()
    foreach ($row in $rows) {
        $ticker = ([string](Get-Value $row 'ticker' '')).ToUpperInvariant()
        Require ($ticker -match '^[A-Z0-9][A-Z0-9.-]{0,14}$') 'Source audit contains an invalid ticker.'
        $market = Get-Value $row 'market_corroboration' $null
        Require ($null -ne $market) "$ticker market object is missing."
        $providerCount = Integer (Get-Value $market 'independent_provider_count' 0)
        Require ((Integer (Get-Value $market 'minimum_providers_for_high_confidence' 0)) -eq 2) "$ticker does not preserve the two-provider confidence minimum."
        Require ((Get-Value $market 'yahoo_is_authoritative_market_source' $true) -eq $false) "$ticker still treats Yahoo as authoritative corroboration."
        Require ((Get-Value $market 'conflict_values_averaged' $true) -eq $false) "$ticker may average conflicting market values."
        Require ((Integer (Get-Value $market 'pairwise_conflict_count' -1)) -eq 0) "$ticker has unresolved pairwise independent-provider conflict."
        Require (@(Get-Value $market 'pairwise_independent_provider_conflicts' @()).Count -eq 0) "$ticker pairwise conflict detail is non-empty."
        Require ([string](Get-Value $market 'status' '') -notin @('CONFLICT_REVIEW','CALCULATION_DIVERGENCE_REVIEW')) "$ticker market state is unresolved."

        $eligible = (Get-Value $row 'eligible_for_high_confidence_model_inference' $false) -eq $true
        $logic = Get-Value $row 'public_logic_state' $null
        Require ($null -ne $logic) "$ticker public-logic state is missing."
        Require ((Integer (Get-Value $logic 'minimum_market_providers_for_high_confidence' 0)) -eq 2) "$ticker public-logic state weakens the market-source minimum."
        Require ((Get-Value $logic 'market_corroboration_is_company_claim_evidence' $true) -eq $false) "$ticker uses market data as company-claim evidence."
        if ($providerCount -lt 2) {
            Require (-not $eligible) "$ticker is high-confidence with fewer than two independent market providers."
            Require ([string](Get-Value $logic 'model_inference_confidence' '') -eq 'LIMITED') "$ticker must be LIMITED with fewer than two independent market providers."
        }
        elseif ($eligible) {
            Require ([string](Get-Value $market 'status' '') -eq 'CORROBORATED') "$ticker is high-confidence without a corroborated market state."
            Require ([string](Get-Value $logic 'model_inference_confidence' '') -eq 'HIGH_ELIGIBLE') "$ticker eligible state and displayed confidence disagree."
        }

        $rowReceipts += [ordered]@{
            ticker = $ticker
            independent_market_provider_count = $providerCount
            high_confidence_eligible = $eligible
            market_status = [string](Get-Value $market 'status' '')
            yahoo_authoritative = $false
            pairwise_conflict_count = 0
            conflict_values_averaged = $false
            status = 'PASS'
        }
    }

    $base = Get-Content -LiteralPath $baseAuditPath -Raw -Encoding utf8 | ConvertFrom-Json
    $result = [ordered]@{
        schema_version = 3
        product_version = '2.1.3'
        status = 'PASS'
        audited_utc = (Get-Date).ToUniversalTime().ToString('o')
        run_id = [string](Get-Value $bundle 'run_id' '')
        base_generated_snapshot_audit = $base
        market_independence = [ordered]@{
            yahoo_authoritative = $false
            yahoo_role = 'compatibility_calculation_only'
            minimum_independent_providers_for_high_confidence = 2
            conflict_comparison = 'pairwise_independent_providers'
            pairwise_conflict_ticker_count = 0
            calculation_divergence_ticker_count = 0
            source_conflicts_averaged = $false
            rows = $rowReceipts
        }
    }
    $parent = Split-Path -Parent $OutputPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding utf8
    Write-Host "V213_GENERATED_SNAPSHOT_AUDIT_V3 = PASS; run_id=$($result.run_id); yahoo_authoritative=false; pairwise_market_conflicts=0; calculation_divergences=0; high_confidence_market_providers=2; conflicts_not_averaged=true" -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $baseAuditPath -Force -ErrorAction SilentlyContinue
}
