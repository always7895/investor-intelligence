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

function Get-Array([object]$Value){
    if($null-eq$Value){return @()}
    return @($Value)
}
function Get-BooleanProperty([object]$Value,[string]$Name,[bool]$Default=$false){
    if($null-eq$Value){return $Default}
    $property=$Value.PSObject.Properties[$Name]
    if($null-eq$property){return $Default}
    return [bool]$property.Value
}
function Test-FederationDocument([object]$Document,[DateTimeOffset]$Now){
    if($null-eq$Document){throw 'The live source federation document is missing.'}
    if([int]$Document.schema_version-ne1-or[string]$Document.product_version-ne'2.1.3'){
        throw 'The live source federation schema/product version is invalid.'
    }
    $generated=[DateTimeOffset]::MinValue
    if(-not[DateTimeOffset]::TryParse([string]$Document.generated_at,[ref]$generated)){
        throw 'The live source federation generated_at value is invalid.'
    }
    $age=($Now.ToUniversalTime()-$generated.ToUniversalTime()).TotalSeconds
    if($age-lt-300-or$age-gt7200){
        throw "The live source federation is outside the 2-hour activation freshness gate (age_seconds=$([Math]::Round($age)))."
    }
    $gates=$Document.gates
    if($null-eq$gates-or-not(Get-BooleanProperty $gates 'pass')){
        throw 'The live source federation truth gate did not pass.'
    }
    $successful=@(Get-Array $gates.successful_families|ForEach-Object{[string]$_})
    $official=@(Get-Array $gates.official_successful_families|ForEach-Object{[string]$_})
    $required=@('us_sec','nasdaq','world_bank','ecb')
    $missingRequired=@($required|Where-Object{$successful -notcontains $_})
    if($successful.Count-lt5-or$official.Count-lt4-or$missingRequired.Count-gt0){
        throw ('Live source federation lacks required independent families: '+($missingRequired-join','))
    }
    if(@(Get-Array $gates.missing_required_families).Count-ne0){
        throw 'The live source federation reports missing required families.'
    }
    if([double]$gates.ticker_coverage_ratio-lt0.8){
        throw 'Fewer than 80% of Top20 tickers passed multi-source identity/filing coverage.'
    }
    if([int]$gates.unresolved_material_conflict_count-ne0){
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
        generated_at=$generated.ToUniversalTime().ToString('o')
        age_seconds=[Math]::Round($age)
        successful_families=$successful
        official_families=$official
        ticker_coverage_ratio=[double]$gates.ticker_coverage_ratio
        largest_family_share=[double]$gates.largest_family_share
    }
}
function Test-Top20AndReport([object[]]$Top20,[object]$Report){
    if($Top20.Count-ne20){throw 'The diversified Top20 must contain exactly 20 rows.'}
    if($null-eq$Report-or[string]$Report.product_version-ne'2.1.3'-or@(Get-Array $Report.records).Count-ne20){
        throw 'The v2.1.3 seven-field report contract is invalid.'
    }
    $reportRows=@(Get-Array $Report.records)
    for($index=0;$index-lt20;$index++){
        $row=$Top20[$index]
        $reportRow=$reportRows[$index]
        if([int]$row.rank-ne($index+1)-or[int]$reportRow.rank-ne($index+1)){
            throw 'Top20/report ranks are not exactly 1..20.'
        }
        if([string]$row.ticker-ne[string]$reportRow.ticker){
            throw "Top20/report order mismatch at rank $($index+1)."
        }
        if([string]$row.scoring_version-ne'system-operationalization-v2.1.3-diversified'){
            throw "Top20 row $($index+1) does not use the diversified scoring version."
        }
        if([int]$row.source_count-lt2-or@($row.evidence).Count-lt2){
            throw "Top20 row $($index+1) lacks transparent multi-source evidence."
        }
        if([double]$row.serenity_factors.chokepoint-ne0-or[double]$row.serenity_factors.replacement_friction-ne0){
            throw "Top20 row $($index+1) bypassed the evidence-bound chokepoint/friction gate."
        }
    }
    return $true
}

if($SelfTest){
    $now=[DateTimeOffset]::UtcNow
    $families=@('us_sec','nasdaq','world_bank','us_bls','ecb')
    $document=[pscustomobject]@{
        schema_version=1;product_version='2.1.3';generated_at=$now.ToString('o')
        gates=[pscustomobject]@{
            pass=$true;successful_families=$families;official_successful_families=$families
            missing_required_families=@();ticker_coverage_ratio=1.0
            unresolved_material_conflict_count=0;concentration_pass=$true
            largest_family_share=0.34;yahoo_authoritative=$false
            catalog_source_count_is_not_live_use=$true
        }
    }
    $result=Test-FederationDocument $document $now
    if($result.successful_families.Count-ne5){throw 'Federation self-test count failed.'}
    $document.gates.yahoo_authoritative=$true
    try{[void](Test-FederationDocument $document $now);throw 'Yahoo authority self-test did not fail closed.'}catch{if($_.Exception.Message-eq'Yahoo authority self-test did not fail closed.'){throw}}
    Write-Host 'V213_DIVERSIFIED_ACTIVATION_PREFLIGHT_SELF_TEST = PASS' -ForegroundColor Green
    exit 0
}

if(-not$ConfirmActivation){throw 'Formal diversified scheduled activation requires -ConfirmActivation.'}
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$federationPath=Join-Path $ProjectRoot 'data\cache\v213_source_federation_latest.json'
$top20Path=Join-Path $ProjectRoot 'data\cache\top20_public_latest.json'
$reportPath=Join-Path $ProjectRoot 'data\cache\v213_top20_report_public_latest.json'
$inner=Join-Path $ProjectRoot 'activate-v213-seven-field-schedule-core.ps1'
foreach($path in @($federationPath,$top20Path,$reportPath,$inner)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Activation prerequisite is missing: $path"}
}
$federation=Get-Content -LiteralPath $federationPath -Raw -Encoding utf8|ConvertFrom-Json
$top20=@(Get-Content -LiteralPath $top20Path -Raw -Encoding utf8|ConvertFrom-Json)
$report=Get-Content -LiteralPath $reportPath -Raw -Encoding utf8|ConvertFrom-Json
$federationResult=Test-FederationDocument $federation ([DateTimeOffset]::UtcNow)
[void](Test-Top20AndReport $top20 $report)
$federationSha=(Get-FileHash -LiteralPath $federationPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host ("V213_DIVERSIFIED_SOURCE_PREFLIGHT = PASS; families={0}; official={1}; ticker_coverage={2:P0}; source_sha256={3}" -f $federationResult.successful_families.Count,$federationResult.official_families.Count,$federationResult.ticker_coverage_ratio,$federationSha) -ForegroundColor Green

$arguments=@{
    ProjectRoot=$ProjectRoot
    FieldLocale=$FieldLocale
    ExpectedModel=$ExpectedModel
    ConfirmActivation=$true
    RequireLocalModel=[bool]$RequireLocalModel
}
& $inner @arguments
if(-not$?){throw 'The inner exact-rollback activation script did not complete.'}

$receiptPath=Join-Path $env:USERPROFILE 'Desktop\Investor-Intelligence-v2.1.3-Scheduled-Activation-Receipt.json'
if(Test-Path -LiteralPath $receiptPath -PathType Leaf){
    $receipt=Get-Content -LiteralPath $receiptPath -Raw -Encoding utf8|ConvertFrom-Json
    $receipt|Add-Member -NotePropertyName source_federation_sha256 -NotePropertyValue $federationSha -Force
    $receipt|Add-Member -NotePropertyName source_federation_generated_at -NotePropertyValue $federationResult.generated_at -Force
    $receipt|Add-Member -NotePropertyName live_source_families -NotePropertyValue $federationResult.successful_families -Force
    $receipt|Add-Member -NotePropertyName official_live_source_families -NotePropertyValue $federationResult.official_families -Force
    $receipt|Add-Member -NotePropertyName ticker_multisource_coverage_ratio -NotePropertyValue $federationResult.ticker_coverage_ratio -Force
    $receipt|Add-Member -NotePropertyName scoring_version -NotePropertyValue 'system-operationalization-v2.1.3-diversified' -Force
    $receipt|Add-Member -NotePropertyName serenity_evidence_standard -NotePropertyValue 'serenity-public-logic-evidence-standard-v3' -Force
    $receipt|Add-Member -NotePropertyName official_serenity_formula_claimed -NotePropertyValue $false -Force
    $receipt|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $receiptPath -Encoding utf8
}
Write-Host 'V2.1.3 DIVERSIFIED SCHEDULE ACTIVATION WRAPPER = PASS' -ForegroundColor Green
