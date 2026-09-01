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
if([string]::IsNullOrWhiteSpace($RuntimeRoot)){ $RuntimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime' }
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$refs=Join-Path $ProjectRoot 'VERSION-REFS.json'
if(-not(Test-Path $refs -PathType Leaf)){ throw 'This is not an Investor Intelligence v2.1.3 All-in-One package (VERSION-REFS.json missing).' }
if($ProjectRoot.TrimEnd('\') -eq $RuntimeRoot.TrimEnd('\')){
    Write-Host "V213_RUNTIME = READY; path=$RuntimeRoot" -ForegroundColor Green
    exit 0
}
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
$robocopy=(Get-Command robocopy.exe -ErrorAction Stop).Source
& $robocopy $ProjectRoot $RuntimeRoot /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XD '.git' 'versions' 'cloud\node_modules' '.venv-v213-local' '.npm-cache'
$code=$LASTEXITCODE
if($code -gt 7){ throw "Runtime copy failed with robocopy exit code $code." }
foreach($required in @('run-v213-local.ps1','run-v213-local-llm-bridge.ps1','activate-v213-seven-field-schedule.ps1','sync-v213-top20-report.ps1','InvestorIntelligence.exe')){
    if(-not(Test-Path (Join-Path $RuntimeRoot $required) -PathType Leaf)){ throw "Runtime installation missing $required" }
}
[ordered]@{
    schema_version=1
    product_version='2.1.3'
    runtime_root=$RuntimeRoot
    source_root=$ProjectRoot
    installed_utc=(Get-Date).ToUniversalTime().ToString('o')
}|ConvertTo-Json -Depth 4|Set-Content (Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\v213-runtime-state.json') -Encoding utf8
Write-Host "V213_RUNTIME = PASS; path=$RuntimeRoot" -ForegroundColor Green
