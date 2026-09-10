[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$RuntimeRoot = ''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
if([string]::IsNullOrWhiteSpace($RuntimeRoot)){
    $RuntimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime'
}
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$baseInstaller=Join-Path $ProjectRoot 'install-v213-runtime.ps1'
if(-not(Test-Path -LiteralPath $baseInstaller -PathType Leaf)){throw "Missing base runtime installer: $baseInstaller"}
& $baseInstaller -ProjectRoot $ProjectRoot -RuntimeRoot $RuntimeRoot
if($LASTEXITCODE-ne0){throw 'Base v2.1.3 runtime installation failed.'}

$required=@(
    'run-v213-local-llm-bridge.ps1',
    'scripts\run_v213_local_llm_bridge_core.ps1',
    'scripts\v213_local_llm_gateway.py',
    'scripts\v213_source_independence_gate.py',
    'config\v213-serenity-public-logic-policy.json',
    'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.zh-TW.md',
    'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.en.md'
)
foreach($relative in $required){
    $source=Join-Path $ProjectRoot $relative
    if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "Required source-diverse runtime file is missing: $relative"}
    $destination=Join-Path $RuntimeRoot $relative
    $directory=Split-Path -Parent $destination
    New-Item -ItemType Directory -Force -Path $directory|Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
    if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash){
        throw "Runtime copy hash mismatch: $relative"
    }
}
[ordered]@{
    schema_version=1
    product_version='2.1.3'
    runtime_profile='source-diverse-exact-model'
    installed_utc=(Get-Date).ToUniversalTime().ToString('o')
    preferred_model=$null
    model_selection_authority='runtime_model_profile'
    model_profile_qualified=$false
    health_schema_version=2
    source_independence_gate='scripts/v213_source_independence_gate.py'
    source_policy='config/v213-serenity-public-logic-policy.json'
    official_serenity_formula_claimed=$false
    private_serenity_method_reproduced=$false
}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $RuntimeRoot 'V213-SOURCE-DIVERSE-RUNTIME.json') -Encoding utf8
Write-Host "V213_SOURCE_DIVERSE_RUNTIME = PASS; path=$RuntimeRoot" -ForegroundColor Green
