[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$RuntimeRoot = ''
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){ $ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$baseRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
if([string]::IsNullOrWhiteSpace($RuntimeRoot)){ $RuntimeRoot=Join-Path $baseRoot 'V213Runtime' }
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$refs=Join-Path $ProjectRoot 'VERSION-REFS.json'
if(-not(Test-Path $refs -PathType Leaf)){ throw 'This is not an Investor Intelligence v2.1.3 All-in-One package (VERSION-REFS.json missing).' }
New-Item -ItemType Directory -Force -Path $baseRoot | Out-Null
if($ProjectRoot.TrimEnd('\') -eq $RuntimeRoot.TrimEnd('\')){
    Write-Host "V213_RUNTIME = READY; path=$RuntimeRoot" -ForegroundColor Green
    return
}
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
$robocopy=(Get-Command robocopy.exe -ErrorAction Stop).Source
& $robocopy $ProjectRoot $RuntimeRoot /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XD '.git' 'versions' 'cloud\node_modules' '.venv-v213-local' '.npm-cache'
$code=$LASTEXITCODE
if($code -gt 7){ throw "Runtime copy failed with robocopy exit code $code." }
$required=@(
    'run-v213-local.ps1',
    'run-v213-local-llm-bridge.ps1',
    'activate-v213-seven-field-schedule.ps1',
    'activate-v213-seven-field-schedule-core.ps1',
    'activate-v213-diversified-schedule.ps1',
    'sync-v213-top20-report.ps1',
    'register-v213-refresh-tasks.ps1',
    'InvestorIntelligence.exe',
    'config\v213-source-federation-policy.json',
    'config\v213-serenity-evidence-standard-v3.json',
    'config\authoritative-sources\v213-runtime-extensions.json',
    'scripts\v213_source_federation.py',
    'scripts\v213_source_federation_gate.py',
    'scripts\v213_apply_diversified_operationalization.py',
    'scripts\v213_build_v21_public_snapshot.py',
    'scripts\v213_methodology_and_source_audit.py',
    'scripts\adapters\nasdaq_symbol_directory.py'
)
foreach($item in $required){
    if(-not(Test-Path (Join-Path $RuntimeRoot $item) -PathType Leaf)){ throw "Runtime installation missing $item" }
}
[ordered]@{
    schema_version=2
    product_version='2.1.3'
    runtime_root=$RuntimeRoot
    source_root=$ProjectRoot
    installed_utc=(Get-Date).ToUniversalTime().ToString('o')
    scoring_version='system-operationalization-v2.1.3-diversified'
    serenity_evidence_standard='serenity-public-logic-evidence-standard-v3'
    source_catalog_count=101
    source_catalog_is_not_live_use=$true
    live_source_federation_required=$true
    official_serenity_formula_claimed=$false
}|ConvertTo-Json -Depth 4|Set-Content (Join-Path $baseRoot 'v213-runtime-state.json') -Encoding utf8
Write-Host "V213_RUNTIME = PASS; path=$RuntimeRoot; scoring=diversified; catalog=101" -ForegroundColor Green
