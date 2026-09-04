[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
& (Join-Path $ProjectRoot 'scripts\ci_v213_r75_validate.ps1') -ProjectRoot $ProjectRoot
if(-not$?){throw 'R75 validation core did not complete.'}
$receipt=Join-Path $env:RUNNER_TEMP 'Investor-Intelligence-v2.1.3-R75-Validation.json'
if(-not(Test-Path -LiteralPath $receipt -PathType Leaf)){throw "R75 validation receipt is missing: $receipt"}
$document=Get-Content -LiteralPath $receipt -Raw -Encoding utf8|ConvertFrom-Json
if([string]$document.status-ne'PASS'-or$document.production_mutation-ne$false){throw 'R75 validation receipt is invalid.'}
$env:R75_VALIDATION=$receipt
"R75_VALIDATION=$receipt"|Out-File $env:GITHUB_ENV -Append -Encoding utf8
Write-Host "V213_R75_VALIDATION_RECEIPT = PASS; path=$receipt; production_mutation=false" -ForegroundColor Green
