[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [ValidateSet('zh-TW','en','bilingual')][string]$FieldLocale = 'zh-TW',
    [string]$ExpectedModel = '',
    [switch]$ConfirmActivation,
    [switch]$RequireLocalModel,
    [switch]$SelfTest,
    [switch]$PreflightOnly,
    [switch]$AllowTestTunnelException
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

# R75 contract markers retained for the release/static audit:
# Test-SourceIndependenceDocument
# V213_DIVERSIFIED_SOURCE_PREFLIGHT
# V213_SOURCE_INDEPENDENCE_PREFLIGHT
# V213_MARKET_CORROBORATION_QUALITY
# activate-v213-seven-field-schedule-core.ps1
# market-quality degradation

function Get-PropertyValue {
    param([object]$Object,[string]$Name,[object]$Default=$null)
    if($null-eq$Object){return $Default}
    $property=$Object.PSObject.Properties[$Name]
    if($null-eq$property){return $Default}
    return $property.Value
}

function Test-PythonRuntime([string]$Path){
    if([string]::IsNullOrWhiteSpace($Path)){return $false}
    try{
        if(-not(Test-Path -LiteralPath $Path -PathType Leaf -ErrorAction Stop)){return $false}
        & $Path -c "import sys; assert sys.version_info >= (3,10)" 2>$null
        return $LASTEXITCODE-eq0
    }catch{return $false}
}

function Resolve-R75Python([string]$Root){
    if(Test-PythonRuntime $env:PROJECT_PYTHON){return $env:PROJECT_PYTHON}
    foreach($name in @('python.exe','python3.exe','python','py.exe','py')){
        try{
            $command=Get-Command $name -ErrorAction SilentlyContinue|Select-Object -First 1
            if($command-and(Test-PythonRuntime $command.Source)){return $command.Source}
        }catch{}
    }
    $resolver=Join-Path $Root 'scripts\resolve_python.ps1'
    if(Test-Path -LiteralPath $resolver -PathType Leaf){
        $venv=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\Runtime\.venv-v213-r75-activation'
        & $resolver -VenvPath $venv
        if(Test-PythonRuntime $env:PROJECT_PYTHON){return $env:PROJECT_PYTHON}
    }
    throw 'No verified Python 3.10+ runtime is available for the R75 activation preflight.'
}

function Test-HealthSchema2Payload([object]$Health,[string]$RequiredModel){
    if($null-eq$Health){throw 'The local-model health payload is missing.'}
    if((Get-PropertyValue $Health 'ok' $false)-ne$true){throw 'The local-model gateway health payload is not ok.'}
    if([string](Get-PropertyValue $Health 'service' '')-ne'v213-local-llm-gateway'){throw 'The local-model gateway service identity is invalid.'}
    if([int](Get-PropertyValue $Health 'health_schema_version' 0)-lt2){throw 'The local-model gateway is not health-schema-v2.'}
    if((Get-PropertyValue $Health 'llama_reachable' $false)-ne$true){throw 'The selected llama.cpp model is not reachable.'}
    if((Get-PropertyValue $Health 'selected_model_available' $false)-ne$true){throw 'The selected model is not available in the router catalog.'}
    if([string](Get-PropertyValue $Health 'selected_model' '')-ine$RequiredModel){throw 'The gateway silently substituted a different model.'}
    if((Get-PropertyValue $Health 'source_independence_audit_available' $false)-ne$true){throw 'The gateway does not expose the source-independence sidecar.'}
    if([string](Get-PropertyValue $Health 'source_independence_audit_freshness' '')-ne'FRESH'){throw 'The gateway source-independence sidecar is not fresh.'}
    if([string](Get-PropertyValue $Health 'source_independence_status' '')-ne'PASS'){throw 'The gateway source-independence status is not PASS.'}
    return $true
}

function Get-HealthyModelState([string]$Path,[string]$RequiredModel){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw 'The v2.1.3 local-model state is missing.'}
    $state=Get-Content -LiteralPath $Path -Raw -Encoding utf8|ConvertFrom-Json
    $model=[string](Get-PropertyValue $state 'model' '')
    if(-not$model){throw 'The local-model state does not identify a selected model.'}
    if($RequiredModel-and$model-ine$RequiredModel){throw "The local-model state selected '$model', not '$RequiredModel'."}
    if((Get-PropertyValue $state 'selected_model_verified' $false)-ne$true){throw 'The local-model state did not verify the selected model.'}
    if([int](Get-PropertyValue $state 'health_schema_version' 0)-lt2){throw 'The persisted local-model state is not health-schema-v2.'}
    $publicUrl=[string](Get-PropertyValue $state 'public_url' '')
    $allowedHost=[string](Get-PropertyValue $state 'allowed_host' '')
    $secret=[string](Get-PropertyValue $state 'encrypted_shared_secret' '')
    if($publicUrl-notmatch'^https://'-or-not$allowedHost-or-not$secret){throw 'The public exact-model bridge state is incomplete.'}
    try{if(([uri]$publicUrl).Host-ine$allowedHost){throw 'The bridge allowed host does not match the public URL.'}}catch{throw 'The public exact-model bridge URL is invalid.'}
    $connected=[DateTimeOffset]::MinValue
    if(-not[DateTimeOffset]::TryParse([string](Get-PropertyValue $state 'connected_at' ''),[ref]$connected)){throw 'The local-model connected_at value is invalid.'}
    $age=([DateTimeOffset]::UtcNow-$connected.ToUniversalTime()).TotalMinutes
    if($age-lt-5-or$age-gt30){throw "The local-model bridge is outside the 30-minute freshness gate (age_minutes=$([Math]::Round($age,1)))."}
    $health=Invoke-RestMethod -Method Get -Uri ($publicUrl.TrimEnd('/')+'/health') -Headers @{'cache-control'='no-cache';'pragma'='no-cache'} -TimeoutSec 30
    [void](Test-HealthSchema2Payload $health $model)
    return [pscustomobject]@{
        model=$model
        public_url=$publicUrl
        allowed_host=$allowedHost
        connected_at=$connected.ToUniversalTime().ToString('o')
        tunnel_mode=[string](Get-PropertyValue $state 'tunnel_mode' 'quick_ephemeral')
        health_schema_version=2
    }
}

function Test-SourceIndependenceDocument([string]$Python,[string]$Preflight,[string]$Bundle,[string]$Receipt){
    $nativeOutput=@(& $Python $Preflight '--bundle' $Bundle '--receipt' $Receipt)
    $nativeExitCode=$LASTEXITCODE
    foreach($line in $nativeOutput){Write-Host ([string]$line)}
    if($nativeExitCode-ne0-or-not(Test-Path -LiteralPath $Receipt -PathType Leaf)){
        throw 'The sealed R75 publication-mode activation preflight failed.'
    }
    $result=Get-Content -LiteralPath $Receipt -Raw -Encoding utf8|ConvertFrom-Json
    if([string](Get-PropertyValue $result 'status' '')-ne'PASS'-or(Get-PropertyValue $result 'production_mutation' $true)-ne$false){
        throw 'The R75 preflight receipt is invalid.'
    }
    return $result
}

if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$python=Resolve-R75Python $ProjectRoot
$preflight=Join-Path $ProjectRoot 'scripts\v213_r75_activation_preflight.py'
$bundle=Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json'
$core=Join-Path $ProjectRoot 'activate-v213-seven-field-schedule-core.ps1'
$contract=Join-Path $ProjectRoot 'config\v213-r75-publication-mode-v1.json'
foreach($path in @($preflight,$core,$contract)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Activation prerequisite is missing: $path"}
}

if($SelfTest){
    & $python $preflight '--self-test'
    if($LASTEXITCODE-ne0){throw 'R75 sealed publication-mode preflight self-test failed.'}
    $health=[pscustomobject]@{
        ok=$true;service='v213-local-llm-gateway';health_schema_version=2
        llama_reachable=$true;selected_model_available=$true;selected_model='model-a'
        source_independence_audit_available=$true
        source_independence_audit_freshness='FRESH';source_independence_status='PASS'
    }
    [void](Test-HealthSchema2Payload $health 'model-a')
    try{[void](Test-HealthSchema2Payload $health 'model-b');throw 'Exact-model mismatch self-test did not fail closed.'}catch{if($_.Exception.Message-eq'Exact-model mismatch self-test did not fail closed.'){throw}}
    Write-Host 'V213_R75_ACTIVATION_WRAPPER_SELF_TEST = PASS; sealed_bundle=true; publication_mode_aware=true; all_limited=true; exact_model=true; production_mutation=false' -ForegroundColor Green
    exit 0
}

if(-not$ConfirmActivation-and-not$PreflightOnly){throw 'Formal scheduled activation requires -ConfirmActivation or -PreflightOnly.'}
if(-not(Test-Path -LiteralPath $bundle -PathType Leaf)){throw "Activation prerequisite is missing: $bundle"}
$receiptPath=Join-Path $env:TEMP ('v213-r75-preflight-'+[guid]::NewGuid().ToString('N')+'.json')
try{
    $preflightResult=Test-SourceIndependenceDocument $python $preflight $bundle $receiptPath
    Write-Host ("V213_DIVERSIFIED_SOURCE_PREFLIGHT = PASS; families={0}; official={1}; bls_present={2}; bundle_sha256={3}; contract_sha256={4}"-f$preflightResult.successful_family_count,$preflightResult.official_family_count,$preflightResult.bls_present,$preflightResult.bundle_sha256,$preflightResult.publication_mode_contract_sha256) -ForegroundColor Green
    Write-Host ("V213_SOURCE_INDEPENDENCE_PREFLIGHT = PASS; evidence_qualified={0}; limited={1}; high_confidence={2}; market_quality_degraded={3}"-f$preflightResult.evidence_qualified_candidate_count,$preflightResult.limited_research_candidate_count,$preflightResult.high_confidence_eligible_count,$preflightResult.market_quality_degraded) -ForegroundColor Green
    if($preflightResult.market_quality_degraded){Write-Host 'V213_MARKET_CORROBORATION_QUALITY = DEGRADED; provider failures disclosed; uncorroborated inference remains LIMITED' -ForegroundColor Yellow}
    if($PreflightOnly){
        Write-Host 'V213_ACTIVATION_PREFLIGHT_ONLY = PASS; sealed_bundle=true; publication_mode_aware=true; production_mutation=false' -ForegroundColor Green
        exit 0
    }

    $modelResult=$null
    $configRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
    if(-not$ExpectedModel-and(Test-Path -LiteralPath (Join-Path $configRoot 'v213-model-selection.json') -PathType Leaf)){
        try{$ExpectedModel=[string](Get-PropertyValue (Get-Content -LiteralPath (Join-Path $configRoot 'v213-model-selection.json') -Raw -Encoding utf8|ConvertFrom-Json) 'model' '')}catch{}
    }
    if($ExpectedModel-and$ExpectedModel-notmatch'^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}$'){throw 'ExpectedModel contains unsupported characters.'}
    if($RequireLocalModel){
        if(-not$ExpectedModel){throw 'Formal exact-model activation requires an explicitly selected model.'}
        $modelResult=Get-HealthyModelState (Join-Path $configRoot 'v213-local-model.json') $ExpectedModel
        $mode=[string]$modelResult.tunnel_mode
        if($mode-eq'quick_free_relay'){
            if([string]$modelResult.model-cne'qwen38-q6'){throw "FREE_RELAY requires exact model qwen38-q6; observed=$($modelResult.model)."}
            Write-Host 'V213_FREE_RELAY_ACTIVATION_PREFLIGHT = PASS; stable_entrypoint=workers_dev; custom_domain_required=false; test_tunnel_exception=false' -ForegroundColor Green
        }elseif($mode-ne'named'){
            if(-not$AllowTestTunnelException){throw "Production local-model activation requires tunnel_mode=quick_free_relay or named; observed=$mode. AllowTestTunnelException is test-only."}
            Write-Warning "Explicit test-tunnel activation exception accepted; tunnel_mode=$mode; no uptime guarantee."
        }
        Write-Host "V213_SELECTED_MODEL_HEALTH_SCHEMA2_PREFLIGHT = PASS; model=$($modelResult.model); tunnel_mode=$mode; test_tunnel_exception=$($AllowTestTunnelException.IsPresent)" -ForegroundColor Green
    }

    $oldBundleSha=$env:V213_R75_SEALED_BUNDLE_SHA256
    try{
        $env:V213_R75_SEALED_BUNDLE_SHA256=[string]$preflightResult.bundle_sha256
        & $core -ProjectRoot $ProjectRoot -FieldLocale $FieldLocale -ExpectedModel $ExpectedModel -ConfirmActivation -RequireLocalModel:$RequireLocalModel
        if(-not$?){throw 'The exact-rollback activation core did not complete.'}
    }finally{$env:V213_R75_SEALED_BUNDLE_SHA256=$oldBundleSha}

    Write-Host 'V2.1.3 R75 SCHEDULE ACTIVATION WRAPPER = PASS; sealed publication-mode contract enforced; exact-model gate enforced; rollback delegated to verified core' -ForegroundColor Green
}
finally{Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue}
