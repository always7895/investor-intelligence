[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [ValidateSet('zh-TW','en','bilingual')][string]$FieldLocale = 'zh-TW',
    [string]$ExpectedModel = '',
    [switch]$ConfirmActivation,
    [switch]$RequireLocalModel,
    [switch]$SelfTest
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
$utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8NoBom
$OutputEncoding=$utf8NoBom
$MarketCoverageTarget=0.75
$MarketDegradationCode='INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE'
$MarketMissingCode='NON_YAHOO_MARKET_CORROBORATION'

function Get-PropertyValue {
    param([object]$Object,[string]$Name,[object]$Default=$null)
    if($null-eq$Object){return $Default}
    $property=$Object.PSObject.Properties[$Name]
    if($null-eq$property){return $Default}
    return $property.Value
}
function Get-Array([object]$Value){
    if($null-eq$Value){return @()}
    return @($Value)
}
function Get-BooleanProperty([object]$Value,[string]$Name,[bool]$Default=$false){
    return [bool](Get-PropertyValue $Value $Name $Default)
}
function Get-IntProperty([object]$Value,[string]$Name,[int]$Default=0){
    $result=$Default
    [void][int]::TryParse([string](Get-PropertyValue $Value $Name $Default),[ref]$result)
    return $result
}
function Get-DoubleProperty([object]$Value,[string]$Name,[double]$Default=0.0){
    $result=$Default
    [void][double]::TryParse([string](Get-PropertyValue $Value $Name $Default),[ref]$result)
    return $result
}
function Get-FreshTimestamp([object]$Document,[string]$Label,[DateTimeOffset]$Now){
    $generated=[DateTimeOffset]::MinValue
    if(-not[DateTimeOffset]::TryParse([string](Get-PropertyValue $Document 'generated_at' ''),[ref]$generated)){
        throw "The $Label generated_at value is invalid."
    }
    $age=($Now.ToUniversalTime()-$generated.ToUniversalTime()).TotalSeconds
    if($age-lt-300-or$age-gt7200){
        throw "The $Label is outside the 2-hour activation freshness gate (age_seconds=$([Math]::Round($age)))."
    }
    return [pscustomobject]@{
        generated_at=$generated.ToUniversalTime().ToString('o')
        age_seconds=[Math]::Round($age)
    }
}
function Test-FederationDocument([object]$Document,[DateTimeOffset]$Now){
    if($null-eq$Document){throw 'The live source federation document is missing.'}
    if((Get-IntProperty $Document 'schema_version')-ne1-or[string](Get-PropertyValue $Document 'product_version' '')-ne'2.1.3'){
        throw 'The live source federation schema/product version is invalid.'
    }
    $stamp=Get-FreshTimestamp $Document 'live source federation' $Now
    $gates=Get-PropertyValue $Document 'gates' $null
    if($null-eq$gates-or-not(Get-BooleanProperty $gates 'pass')){
        throw 'The live source federation truth gate did not pass.'
    }
    $successful=@(Get-Array (Get-PropertyValue $gates 'successful_families' @())|ForEach-Object{[string]$_})
    $official=@(Get-Array (Get-PropertyValue $gates 'official_successful_families' @())|ForEach-Object{[string]$_})
    $required=@('us_sec','nasdaq','world_bank','ecb')
    $missingRequired=@($required|Where-Object{$successful-notcontains$_})
    if($successful.Count-lt5-or$official.Count-lt4-or$missingRequired.Count-gt0){
        throw ('Live source federation lacks required independent families: '+($missingRequired-join','))
    }
    if(@(Get-Array (Get-PropertyValue $gates 'missing_required_families' @())).Count-ne0){
        throw 'The live source federation reports missing required families.'
    }
    $tickerCoverage=Get-DoubleProperty $gates 'ticker_coverage_ratio'
    if($tickerCoverage-lt0.8){
        throw 'Fewer than 80% of Top20 tickers passed multi-source identity/filing coverage.'
    }
    if((Get-IntProperty $gates 'unresolved_material_conflict_count')-ne0){
        throw 'The live source federation contains unresolved material conflicts.'
    }
    if(-not(Get-BooleanProperty $gates 'concentration_pass')){
        throw 'The live source federation failed the single-family concentration cap.'
    }
    if(Get-BooleanProperty $gates 'yahoo_authoritative'){
        throw 'Yahoo/yfinance may not be authoritative in the activation document.'
    }
    if(-not(Get-BooleanProperty $gates 'catalog_source_count_is_not_live_use')){
        throw 'The activation document does not distinguish catalog inventory from live use.'
    }
    return [pscustomobject]@{
        generated_at=$stamp.generated_at
        age_seconds=$stamp.age_seconds
        successful_families=$successful
        official_families=$official
        ticker_coverage_ratio=$tickerCoverage
        largest_family_share=Get-DoubleProperty $gates 'largest_family_share'
    }
}
function Test-SourceIndependenceDocument {
    param(
        [object]$Document,
        [DateTimeOffset]$Now,
        [object[]]$Top20
    )
    if($null-eq$Document){throw 'The claim-level source-independence document is missing.'}
    if((Get-IntProperty $Document 'schema_version')-lt3-or[string](Get-PropertyValue $Document 'product_version' '')-ne'2.1.3'){
        throw 'The claim-level source-independence schema/product version is invalid.'
    }
    if([string](Get-PropertyValue $Document 'status' '')-ne'PASS'){
        throw 'The claim-level source-independence gate is not PASS.'
    }
    $blocking=@(Get-Array (Get-PropertyValue $Document 'blocking_violations' @())|ForEach-Object{[string]$_}|Where-Object{$_})
    $violations=@(Get-Array (Get-PropertyValue $Document 'violations' @())|ForEach-Object{[string]$_}|Where-Object{$_})
    if($blocking.Count-gt0-or$violations.Count-gt0){
        throw ('The source-independence document contains blocking violations: '+(@($blocking+$violations)|Select-Object -Unique)-join',')
    }
    $stamp=Get-FreshTimestamp $Document 'claim-level source-independence audit' $Now
    $records=@(Get-Array (Get-PropertyValue $Document 'records' @()))
    if($records.Count-ne20){throw 'The claim-level source-independence document must contain exactly 20 records.'}
    if($Top20.Count-ne20){throw 'The diversified Top20 must contain exactly 20 rows.'}
    for($index=0;$index-lt20;$index++){
        $topTicker=[string](Get-PropertyValue $Top20[$index] 'ticker' '')
        $sourceTicker=[string](Get-PropertyValue $records[$index] 'ticker' '')
        if($topTicker-ne$sourceTicker){
            throw "Top20/source-independence order mismatch at rank $($index+1): $topTicker vs $sourceTicker."
        }
    }

    $portfolio=Get-PropertyValue $Document 'portfolio' $null
    if($null-eq$portfolio){throw 'The source-independence portfolio summary is missing.'}
    $families=Get-IntProperty $portfolio 'independent_source_families'
    $domains=Get-IntProperty $portfolio 'independent_domains'
    $claimFamilies=Get-IntProperty $portfolio 'claim_source_families'
    $claimDomains=Get-IntProperty $portfolio 'claim_source_domains'
    $nonYahoo=Get-DoubleProperty $portfolio 'non_yahoo_market_coverage_ratio'
    $target=Get-DoubleProperty $portfolio 'non_yahoo_market_coverage_target_ratio' $MarketCoverageTarget
    $claimPrimary=Get-DoubleProperty $portfolio 'claim_primary_coverage_ratio'
    $largestFamily=Get-DoubleProperty $portfolio 'maximum_single_family_share' 1.0
    $marketConflicts=Get-IntProperty $portfolio 'market_conflict_ticker_count'
    $marketStatus=[string](Get-PropertyValue $portfolio 'market_corroboration_status' '')
    $marketGlobalBlocker=Get-BooleanProperty $portfolio 'market_corroboration_global_blocker' $true
    $degradations=@(Get-Array (Get-PropertyValue $Document 'degradations' @())|ForEach-Object{[string]$_}|Where-Object{$_})
    if($families-lt3-or$domains-lt3){throw 'Portfolio source-family/domain independence is below 3.'}
    if($claimFamilies-lt2-or$claimDomains-lt2){throw 'Claim-relevant source-family/domain independence is below 2.'}
    if($claimPrimary-lt0.75){throw "Claim-relevant primary-source coverage is below 75% ($claimPrimary)."}
    if($largestFamily-gt0.70){throw "A single source family exceeds the 70% concentration cap ($largestFamily)."}
    if($marketConflicts-ne0){throw "The source-independence document contains $marketConflicts unresolved market-source conflicts."}

    $marketDegraded=$nonYahoo-lt$target
    if($marketDegraded){
        if($marketStatus-ne'DEGRADED'){
            throw 'Low non-Yahoo market coverage is not explicitly labelled DEGRADED.'
        }
        if($marketGlobalBlocker){
            throw 'The market-quality policy incorrectly makes endpoint unavailability a global blocker.'
        }
        if($degradations-notcontains$MarketDegradationCode){
            throw 'The expected non-Yahoo market degradation code is missing.'
        }
    }
    elseif($marketStatus-ne'CORROBORATED'){
        throw 'Adequate non-Yahoo market coverage is not labelled CORROBORATED.'
    }

    $notice=Get-PropertyValue $Document 'methodology_notice' $null
    if($null-eq$notice){throw 'The source-independence methodology notice is missing.'}
    if(Get-BooleanProperty $notice 'official_serenity_formula' $true){throw 'The source document claims an official Serenity formula.'}
    if(Get-BooleanProperty $notice 'official_serenity_score' $true){throw 'The source document claims an official Serenity score.'}
    if(Get-BooleanProperty $notice 'private_method_reproduced' $true){throw 'The source document claims private-method reproduction.'}
    if(Get-BooleanProperty $notice 'single_source_inference_allowed' $true){throw 'The source document permits single-source inference.'}
    if(-not(Get-BooleanProperty $notice 'source_diversity_is_not_truth_by_itself')){throw 'The source document does not preserve the source-diversity/ground-truth distinction.'}
    if(-not(Get-BooleanProperty $notice 'official_macro_is_not_company_claim_evidence')){throw 'The source document does not isolate official macro context from company claims.'}
    if(Get-BooleanProperty $notice 'market_corroboration_unavailable_is_global_blocker' $true){throw 'The methodology notice does not preserve graceful market-quality degradation.'}
    if(-not(Get-BooleanProperty $notice 'market_corroboration_required_for_high_confidence_model_inference')){throw 'The methodology notice does not require market corroboration for high-confidence inference.'}
    if(-not(Get-BooleanProperty $notice 'market_corroboration_required_for_uncapped_valuation_factor')){throw 'The methodology notice does not cap valuation confidence without market corroboration.'}
    if(-not(Get-BooleanProperty $notice 'provider_failure_must_be_disclosed')){throw 'The methodology notice permits silent provider failure.'}
    if(-not(Get-BooleanProperty $notice 'market_data_is_not_averaged_into_published_returns')){throw 'The methodology notice permits averaging market sources into published returns.'}
    $valuationCap=Get-DoubleProperty $notice 'uncorroborated_valuation_factor_max' 3.75

    $eligibleCount=0
    for($index=0;$index-lt20;$index++){
        $record=$records[$index]
        $eligible=Get-BooleanProperty $record 'eligible_for_high_confidence_model_inference'
        $metrics=Get-PropertyValue $record 'source_metrics' $null
        $market=Get-PropertyValue $record 'market_corroboration' $null
        if($null-eq$metrics-or$null-eq$market){throw 'A source record lacks source metrics or market corroboration.'}
        $providerCount=Get-IntProperty $market 'independent_provider_count'
        $marketRowStatus=[string](Get-PropertyValue $market 'status' '')
        $missing=@(Get-Array (Get-PropertyValue $record 'missing_or_review' @())|ForEach-Object{[string]$_})
        $logic=Get-PropertyValue $record 'public_logic_state' $null
        if($eligible){
            $eligibleCount++
            if((Get-IntProperty $metrics 'claim_relevant_independent_families')-lt2){throw 'A HIGH-eligible record has fewer than two claim-relevant source families.'}
            if((Get-IntProperty $metrics 'claim_relevant_independent_domains')-lt2){throw 'A HIGH-eligible record has fewer than two claim-relevant source domains.'}
            if((Get-IntProperty $metrics 'claim_relevant_primary_sources')-lt1){throw 'A HIGH-eligible record lacks claim-relevant primary evidence.'}
            if((Get-DoubleProperty $metrics 'claim_dated_evidence_ratio')-lt0.8){throw 'A HIGH-eligible record has insufficient dated claim evidence.'}
            if($marketRowStatus-ne'CORROBORATED'-or$providerCount-lt1){throw 'A HIGH-eligible record lacks conflict-free non-Yahoo market corroboration.'}
            if($missing-contains'MARKET_SOURCE_CONFLICT_REVIEW'){throw 'A HIGH-eligible record contains an unresolved market conflict.'}
        }
        if($providerCount-lt1){
            if($eligible){throw 'An uncorroborated record is incorrectly HIGH eligible.'}
            if($missing-notcontains$MarketMissingCode){throw 'An uncorroborated record does not disclose the missing market cross-check.'}
            if($null-eq$logic-or[string](Get-PropertyValue $logic 'model_inference_confidence' '')-ne'LIMITED'){
                throw 'An uncorroborated record does not cap model inference at LIMITED.'
            }
            $topFactors=Get-PropertyValue $Top20[$index] 'serenity_factors' $null
            if($null-eq$topFactors-or(Get-DoubleProperty $topFactors 'valuation_expectations')-gt$valuationCap){
                throw 'An uncorroborated Top20 row exceeds the valuation-confidence cap.'
            }
        }
    }
    if($eligibleCount-ne(Get-IntProperty $portfolio 'high_confidence_model_inference_eligible_count')){
        throw 'High-confidence eligible count does not match the record-level truth.'
    }
    return [pscustomobject]@{
        generated_at=$stamp.generated_at
        age_seconds=$stamp.age_seconds
        independent_source_families=$families
        independent_domains=$domains
        claim_source_families=$claimFamilies
        claim_source_domains=$claimDomains
        non_yahoo_market_coverage_ratio=$nonYahoo
        non_yahoo_market_coverage_target_ratio=$target
        claim_primary_coverage_ratio=$claimPrimary
        maximum_single_family_share=$largestFamily
        high_confidence_eligible_count=$eligibleCount
        fred_macro_status=[string](Get-PropertyValue $portfolio 'fred_macro_status' 'UNKNOWN')
        market_corroboration_status=$marketStatus
        market_quality_degraded=$marketDegraded
        degradations=$degradations
    }
}
function Test-Top20AndReport([object[]]$Top20,[object]$Report){
    if($Top20.Count-ne20){throw 'The diversified Top20 must contain exactly 20 rows.'}
    if($null-eq$Report-or[string](Get-PropertyValue $Report 'product_version' '')-ne'2.1.3'-or@(Get-Array (Get-PropertyValue $Report 'records' @())).Count-ne20){
        throw 'The v2.1.3 seven-field report contract is invalid.'
    }
    $reportRows=@(Get-Array (Get-PropertyValue $Report 'records' @()))
    for($index=0;$index-lt20;$index++){
        $row=$Top20[$index]
        $reportRow=$reportRows[$index]
        if((Get-IntProperty $row 'rank')-ne($index+1)-or(Get-IntProperty $reportRow 'rank')-ne($index+1)){
            throw 'Top20/report ranks are not exactly 1..20.'
        }
        if([string](Get-PropertyValue $row 'ticker' '')-ne[string](Get-PropertyValue $reportRow 'ticker' '')){
            throw "Top20/report order mismatch at rank $($index+1)."
        }
        if([string](Get-PropertyValue $row 'scoring_version' '')-ne'system-operationalization-v2.1.3-diversified'){
            throw "Top20 row $($index+1) does not use the diversified scoring version."
        }
        if((Get-IntProperty $row 'source_count')-lt2-or@(Get-Array (Get-PropertyValue $row 'evidence' @())).Count-lt2){
            throw "Top20 row $($index+1) lacks transparent multi-source evidence."
        }
        $factors=Get-PropertyValue $row 'serenity_factors' $null
        if($null-eq$factors){throw "Top20 row $($index+1) lacks Serenity-factor compatibility fields."}
        if((Get-DoubleProperty $factors 'chokepoint')-ne0-or(Get-DoubleProperty $factors 'replacement_friction')-ne0){
            throw "Top20 row $($index+1) bypassed the evidence-bound chokepoint/friction gate."
        }
    }
    return $true
}
function Test-HealthSchema2Payload([object]$Health,[string]$RequiredModel){
    if($null-eq$Health){throw 'The local-model health payload is missing.'}
    if(-not(Get-BooleanProperty $Health 'ok')){throw 'The local-model gateway health payload is not ok.'}
    if([string](Get-PropertyValue $Health 'service' '')-ne'v213-local-llm-gateway'){throw 'The local-model gateway service identity is invalid.'}
    if((Get-IntProperty $Health 'health_schema_version')-lt2){throw 'The local-model gateway is not health-schema-v2.'}
    if(-not(Get-BooleanProperty $Health 'llama_reachable')){throw 'The selected llama.cpp model is not reachable.'}
    if(-not(Get-BooleanProperty $Health 'selected_model_available')){throw 'The selected model is not available in the router catalog.'}
    if([string](Get-PropertyValue $Health 'selected_model' '')-ine$RequiredModel){throw 'The local-model health payload silently substituted a different model.'}
    if(-not(Get-BooleanProperty $Health 'source_independence_audit_available')){throw 'The gateway does not expose the current source-independence sidecar.'}
    if([string](Get-PropertyValue $Health 'source_independence_audit_freshness' '')-ne'FRESH'){throw 'The gateway source-independence sidecar is not fresh.'}
    if([string](Get-PropertyValue $Health 'source_independence_status' '')-ne'PASS'){throw 'The gateway source-independence status is not PASS.'}
    return $true
}
function Get-HealthSchema2ModelState([string]$Path,[string]$RequiredModel){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw 'The v2.1.3 local-model state is missing.'}
    $state=Get-Content -LiteralPath $Path -Raw -Encoding utf8|ConvertFrom-Json
    $model=[string](Get-PropertyValue $state 'model' '')
    if(-not$model){throw 'The local-model state does not identify a selected model.'}
    if($RequiredModel-and$model-ine$RequiredModel){throw "The local-model state selected '$model', not required model '$RequiredModel'."}
    if(-not(Get-BooleanProperty $state 'selected_model_verified')){throw 'The local-model state did not verify the selected model.'}
    if((Get-IntProperty $state 'health_schema_version')-lt2){throw 'The persisted local-model state is not health-schema-v2.'}
    $publicUrl=[string](Get-PropertyValue $state 'public_url' '')
    $allowedHost=[string](Get-PropertyValue $state 'allowed_host' '')
    $secret=[string](Get-PropertyValue $state 'encrypted_shared_secret' '')
    if($publicUrl-notmatch'^https://'-or-not$allowedHost-or-not$secret){throw 'The public exact-model bridge state is incomplete.'}
    try{
        if(([uri]$publicUrl).Host-ine$allowedHost){throw 'The bridge allowed host does not match the public URL.'}
    }catch{throw 'The public exact-model bridge URL is invalid.'}
    $connected=[DateTimeOffset]::MinValue
    if(-not[DateTimeOffset]::TryParse([string](Get-PropertyValue $state 'connected_at' ''),[ref]$connected)){throw 'The local-model connected_at value is invalid.'}
    $age=([DateTimeOffset]::UtcNow-$connected.ToUniversalTime()).TotalMinutes
    if($age-lt-5-or$age-gt30){throw "The local-model bridge is outside the 30-minute freshness gate (age_minutes=$([Math]::Round($age,1)))."}
    $health=Invoke-RestMethod -Method Get -Uri ($publicUrl.TrimEnd('/')+'/health') -Headers @{'cache-control'='no-cache';'pragma'='no-cache'} -TimeoutSec 20
    [void](Test-HealthSchema2Payload $health $model)
    return [pscustomobject]@{
        model=$model
        public_url=$publicUrl
        allowed_host=$allowedHost
        connected_at=$connected.ToUniversalTime().ToString('o')
        health_schema_version=2
        source_independence_policy_version=[string](Get-PropertyValue $health 'source_independence_policy_version' '')
    }
}

if($SelfTest){
    $now=[DateTimeOffset]::UtcNow
    $families=@('us_sec','nasdaq','world_bank','us_bls','ecb')
    $federation=[pscustomobject]@{
        schema_version=1;product_version='2.1.3';generated_at=$now.ToString('o')
        gates=[pscustomobject]@{
            pass=$true;successful_families=$families;official_successful_families=$families
            missing_required_families=@();ticker_coverage_ratio=1.0
            unresolved_material_conflict_count=0;concentration_pass=$true
            largest_family_share=0.34;yahoo_authoritative=$false
            catalog_source_count_is_not_live_use=$true
        }
    }
    $top20=@()
    $sourceRecords=@()
    for($index=1;$index-le20;$index++){
        $ticker=('T{0:D2}'-f$index)
        $top20+=[pscustomobject]@{
            rank=$index;ticker=$ticker
            serenity_factors=[pscustomobject]@{chokepoint=0;replacement_friction=0;valuation_expectations=3.75}
        }
        $sourceRecords+=[pscustomobject]@{
            rank=$index;ticker=$ticker;evidence_independence_score=70
            eligible_for_high_confidence_model_inference=$false
            source_metrics=[pscustomobject]@{
                claim_relevant_independent_families=2
                claim_relevant_independent_domains=2
                claim_relevant_primary_sources=1
                claim_dated_evidence_ratio=1.0
            }
            market_corroboration=[pscustomobject]@{status='UNAVAILABLE';independent_provider_count=0}
            missing_or_review=@($MarketMissingCode)
            public_logic_state=[pscustomobject]@{model_inference_confidence='LIMITED'}
        }
    }
    $sourceAudit=[pscustomobject]@{
        schema_version=3;product_version='2.1.3';status='PASS';quality_status='PASS_WITH_DEGRADATION';generated_at=$now.ToString('o')
        violations=@();blocking_violations=@();degradations=@($MarketDegradationCode)
        portfolio=[pscustomobject]@{
            independent_source_families=5;independent_domains=5
            claim_source_families=2;claim_source_domains=2
            non_yahoo_market_coverage_ratio=0.0;non_yahoo_market_coverage_target_ratio=$MarketCoverageTarget
            market_corroboration_status='DEGRADED';market_corroboration_global_blocker=$false
            claim_primary_coverage_ratio=1.0;maximum_single_family_share=0.4
            market_conflict_ticker_count=0;high_confidence_model_inference_eligible_count=0
            fred_macro_status='LIVE'
        }
        methodology_notice=[pscustomobject]@{
            official_serenity_formula=$false;official_serenity_score=$false
            private_method_reproduced=$false;single_source_inference_allowed=$false
            source_diversity_is_not_truth_by_itself=$true
            official_macro_is_not_company_claim_evidence=$true
            market_corroboration_unavailable_is_global_blocker=$false
            market_corroboration_required_for_high_confidence_model_inference=$true
            market_corroboration_required_for_uncapped_valuation_factor=$true
            uncorroborated_valuation_factor_max=3.75
            provider_failure_must_be_disclosed=$true
            market_data_is_not_averaged_into_published_returns=$true
        }
        records=$sourceRecords
    }
    [void](Test-FederationDocument $federation $now)
    $sourceResult=Test-SourceIndependenceDocument $sourceAudit $now $top20
    if(-not$sourceResult.market_quality_degraded-or$sourceResult.high_confidence_eligible_count-ne0){throw 'Market-quality degradation self-test failed.'}
    $sourceRecords[0].eligible_for_high_confidence_model_inference=$true
    try{[void](Test-SourceIndependenceDocument $sourceAudit $now $top20);throw 'Uncorroborated HIGH inference self-test did not fail closed.'}catch{if($_.Exception.Message-eq'Uncorroborated HIGH inference self-test did not fail closed.'){throw}}
    $sourceRecords[0].eligible_for_high_confidence_model_inference=$false
    $sourceAudit.blocking_violations=@('INSUFFICIENT_CLAIM_PRIMARY_COVERAGE')
    try{[void](Test-SourceIndependenceDocument $sourceAudit $now $top20);throw 'Blocking-violation self-test did not fail closed.'}catch{if($_.Exception.Message-eq'Blocking-violation self-test did not fail closed.'){throw}}
    $sourceAudit.blocking_violations=@()
    $health=[pscustomobject]@{
        ok=$true;service='v213-local-llm-gateway';health_schema_version=2
        llama_reachable=$true;selected_model_available=$true;selected_model='model-a'
        source_independence_audit_available=$true
        source_independence_audit_freshness='FRESH';source_independence_status='PASS'
    }
    [void](Test-HealthSchema2Payload $health 'model-a')
    $federation.gates.yahoo_authoritative=$true
    try{[void](Test-FederationDocument $federation $now);throw 'Yahoo authority self-test did not fail closed.'}catch{if($_.Exception.Message-eq'Yahoo authority self-test did not fail closed.'){throw}}
    Write-Host 'V213_SOURCE_INDEPENDENCE_PREFLIGHT_SELF_TEST = PASS; market-quality degradation = PASS; claim blockers = PASS; health-schema-v2 = PASS' -ForegroundColor Green
    exit 0
}

if(-not$ConfirmActivation){throw 'Formal source-diverse scheduled activation requires -ConfirmActivation.'}
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$federationPath=Join-Path $ProjectRoot 'data\cache\v213_source_federation_latest.json'
$sourcePath=Join-Path $ProjectRoot 'data\cache\v213_source_independence_latest.json'
$top20Path=Join-Path $ProjectRoot 'data\cache\top20_public_latest.json'
$reportPath=Join-Path $ProjectRoot 'data\cache\v213_top20_report_public_latest.json'
$inner=Join-Path $ProjectRoot 'activate-v213-seven-field-schedule-core.ps1'
$sourceDiverseInstaller=Join-Path $ProjectRoot 'install-v213-source-diverse-runtime.ps1'
foreach($path in @($federationPath,$sourcePath,$top20Path,$reportPath,$inner,$sourceDiverseInstaller)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Activation prerequisite is missing: $path"}
}
$federation=Get-Content -LiteralPath $federationPath -Raw -Encoding utf8|ConvertFrom-Json
$sourceAudit=Get-Content -LiteralPath $sourcePath -Raw -Encoding utf8|ConvertFrom-Json
$top20Document=Get-Content -LiteralPath $top20Path -Raw -Encoding utf8|ConvertFrom-Json
$top20Property=$top20Document.PSObject.Properties['records']
$top20=if($null-ne$top20Property){@(Get-Array $top20Property.Value)}else{@($top20Document)}
$report=Get-Content -LiteralPath $reportPath -Raw -Encoding utf8|ConvertFrom-Json
$now=[DateTimeOffset]::UtcNow
$federationResult=Test-FederationDocument $federation $now
$sourceResult=Test-SourceIndependenceDocument $sourceAudit $now $top20
[void](Test-Top20AndReport $top20 $report)
$federationSha=(Get-FileHash -LiteralPath $federationPath -Algorithm SHA256).Hash.ToLowerInvariant()
$sourceSha=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host ("V213_DIVERSIFIED_SOURCE_PREFLIGHT = PASS; families={0}; official={1}; ticker_coverage={2:P0}; source_sha256={3}"-f$federationResult.successful_families.Count,$federationResult.official_families.Count,$federationResult.ticker_coverage_ratio,$federationSha) -ForegroundColor Green
Write-Host ("V213_SOURCE_INDEPENDENCE_PREFLIGHT = PASS; families={0}; domains={1}; claim_families={2}; claim_domains={3}; non_yahoo={4:P0}; market_status={5}; claim_primary={6:P0}; high_confidence={7}; source_sha256={8}"-f$sourceResult.independent_source_families,$sourceResult.independent_domains,$sourceResult.claim_source_families,$sourceResult.claim_source_domains,$sourceResult.non_yahoo_market_coverage_ratio,$sourceResult.market_corroboration_status,$sourceResult.claim_primary_coverage_ratio,$sourceResult.high_confidence_eligible_count,$sourceSha) -ForegroundColor Green
if($sourceResult.market_quality_degraded){
    Write-Host 'V213_MARKET_CORROBORATION_QUALITY = DEGRADED; provider failures disclosed; valuation capped; uncorroborated model inference LIMITED; company/claim evidence gates remain PASS' -ForegroundColor Yellow
}

$configRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
$selectionPath=Join-Path $configRoot 'v213-model-selection.json'
if(-not$ExpectedModel-and(Test-Path -LiteralPath $selectionPath -PathType Leaf)){
    try{$ExpectedModel=[string](Get-PropertyValue (Get-Content -LiteralPath $selectionPath -Raw -Encoding utf8|ConvertFrom-Json) 'model' '')}catch{}
}
if($ExpectedModel-and$ExpectedModel-notmatch'^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}$'){throw 'ExpectedModel contains unsupported characters.'}
$modelResult=$null
if($RequireLocalModel){
    if(-not$ExpectedModel){throw 'Formal exact-model activation requires an explicitly selected model.'}
    $modelResult=Get-HealthSchema2ModelState (Join-Path $configRoot 'v213-local-model.json') $ExpectedModel
    Write-Host "V213_SELECTED_MODEL_HEALTH_SCHEMA2_PREFLIGHT = PASS; health-schema-v2; model=$($modelResult.model); source_policy=$($modelResult.source_independence_policy_version)" -ForegroundColor Green
}

$arguments=@{
    ProjectRoot=$ProjectRoot
    FieldLocale=$FieldLocale
    ExpectedModel=$ExpectedModel
    ConfirmActivation=$true
    RequireLocalModel=[bool]$RequireLocalModel
}
& $inner @arguments
if(-not$?){throw 'The inner exact-rollback activation script did not complete.'}

$stableRuntime=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime'
$stableRefresh=Join-Path $stableRuntime 'run-v213-local.ps1'
$stableBridge=Join-Path $stableRuntime 'run-v213-local-llm-bridge.ps1'
if(-not(Test-Path -LiteralPath $stableRefresh -PathType Leaf)-or-not(Test-Path -LiteralPath $stableBridge -PathType Leaf)){
    throw 'The post-activation stable runtime is incomplete.'
}
if(-not(Get-Content -LiteralPath $stableRefresh -Raw -Encoding utf8).Contains('v213_source_independence_gate_v3.py')){
    throw 'The stable runtime refresh entrypoint lost the market-quality-aware claim source gate.'
}
if(-not(Get-Content -LiteralPath $stableBridge -Raw -Encoding utf8).Contains('run_v213_local_llm_bridge_core_v2.ps1')){
    throw 'The stable runtime bridge entrypoint lost health-schema-v2 dependency bootstrap.'
}

$receiptPath=Join-Path $env:USERPROFILE 'Desktop\Investor-Intelligence-v2.1.3-Scheduled-Activation-Receipt.json'
if(Test-Path -LiteralPath $receiptPath -PathType Leaf){
    $receipt=Get-Content -LiteralPath $receiptPath -Raw -Encoding utf8|ConvertFrom-Json
    $receipt|Add-Member -NotePropertyName source_federation_sha256 -NotePropertyValue $federationSha -Force
    $receipt|Add-Member -NotePropertyName source_federation_generated_at -NotePropertyValue $federationResult.generated_at -Force
    $receipt|Add-Member -NotePropertyName live_source_families -NotePropertyValue $federationResult.successful_families -Force
    $receipt|Add-Member -NotePropertyName official_live_source_families -NotePropertyValue $federationResult.official_families -Force
    $receipt|Add-Member -NotePropertyName ticker_multisource_coverage_ratio -NotePropertyValue $federationResult.ticker_coverage_ratio -Force
    $receipt|Add-Member -NotePropertyName source_independence_sha256 -NotePropertyValue $sourceSha -Force
    $receipt|Add-Member -NotePropertyName source_independence_generated_at -NotePropertyValue $sourceResult.generated_at -Force
    $receipt|Add-Member -NotePropertyName independent_source_families -NotePropertyValue $sourceResult.independent_source_families -Force
    $receipt|Add-Member -NotePropertyName independent_source_domains -NotePropertyValue $sourceResult.independent_domains -Force
    $receipt|Add-Member -NotePropertyName claim_source_families -NotePropertyValue $sourceResult.claim_source_families -Force
    $receipt|Add-Member -NotePropertyName claim_source_domains -NotePropertyValue $sourceResult.claim_source_domains -Force
    $receipt|Add-Member -NotePropertyName non_yahoo_market_coverage_ratio -NotePropertyValue $sourceResult.non_yahoo_market_coverage_ratio -Force
    $receipt|Add-Member -NotePropertyName non_yahoo_market_coverage_target_ratio -NotePropertyValue $sourceResult.non_yahoo_market_coverage_target_ratio -Force
    $receipt|Add-Member -NotePropertyName market_corroboration_status -NotePropertyValue $sourceResult.market_corroboration_status -Force
    $receipt|Add-Member -NotePropertyName market_quality_degraded -NotePropertyValue $sourceResult.market_quality_degraded -Force
    $receipt|Add-Member -NotePropertyName source_quality_degradations -NotePropertyValue $sourceResult.degradations -Force
    $receipt|Add-Member -NotePropertyName claim_primary_coverage_ratio -NotePropertyValue $sourceResult.claim_primary_coverage_ratio -Force
    $receipt|Add-Member -NotePropertyName high_confidence_eligible_count -NotePropertyValue $sourceResult.high_confidence_eligible_count -Force
    $receipt|Add-Member -NotePropertyName fred_macro_status -NotePropertyValue $sourceResult.fred_macro_status -Force
    $receipt|Add-Member -NotePropertyName local_model_health_schema_version -NotePropertyValue $(if($modelResult){2}else{0}) -Force
    $receipt|Add-Member -NotePropertyName source_diverse_runtime_installer -NotePropertyValue 'install-v213-source-diverse-runtime.ps1' -Force
    $receipt|Add-Member -NotePropertyName scoring_version -NotePropertyValue 'system-operationalization-v2.1.3-diversified' -Force
    $receipt|Add-Member -NotePropertyName serenity_evidence_standard -NotePropertyValue '2.1.3-source-independence-v3' -Force
    $receipt|Add-Member -NotePropertyName market_quality_policy -NotePropertyValue 'v213-market-corroboration-graceful-degradation-v1' -Force
    $receipt|Add-Member -NotePropertyName official_serenity_formula_claimed -NotePropertyValue $false -Force
    $receipt|Add-Member -NotePropertyName private_serenity_method_reproduced -NotePropertyValue $false -Force
    $receipt|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $receiptPath -Encoding utf8
}
Write-Host 'V2.1.3 SOURCE-DIVERSE SCHEDULE ACTIVATION WRAPPER = PASS; claim-evidence blockers enforced; market-quality degradation explicit; health-schema-v2 exact-model gate enforced; rollback delegated to verified core' -ForegroundColor Green
