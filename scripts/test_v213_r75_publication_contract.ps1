[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$Python = '',
    [string]$ReceiptPath = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
if ([string]::IsNullOrWhiteSpace($Python)) {
    if ($env:PROJECT_PYTHON -and (Test-Path -LiteralPath $env:PROJECT_PYTHON -PathType Leaf)) {
        $Python = $env:PROJECT_PYTHON
    } else {
        $command = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $command) { $command = Get-Command python -ErrorAction Stop | Select-Object -First 1 }
        $Python = $command.Source
    }
}
$preflight = Join-Path $ProjectRoot 'scripts\v213_r75_activation_preflight.py'
$contractPath = Join-Path $ProjectRoot 'config\v213-r75-publication-mode-v1.json'
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding utf8 | ConvertFrom-Json
$hash = (& $Python $preflight --print-contract-hash | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or $hash -notmatch '^[0-9a-f]{64}$') { throw 'R75 contract hash computation failed.' }
$results = @()
foreach ($relative in @($contract.fixture_files)) {
    $fixture = Join-Path $ProjectRoot ([string]$relative).Replace('/', '\')
    $output = & $Python $preflight --fixture $fixture
    if ($LASTEXITCODE -ne 0 -or ($output -join "`n") -notmatch 'V213_R75_PUBLICATION_FIXTURE = PASS') {
        throw "R75 publication fixture failed: $relative"
    }
    $results += [string]$relative
}
$receipt = [ordered]@{
    schema_version = 1
    status = 'PASS'
    publication_mode_contract_id = [string]$contract.contract_id
    publication_mode_contract_sha256 = $hash
    fixture_files = $results
    powershell_version = $PSVersionTable.PSVersion.ToString()
    production_mutation = $false
}
if (-not [string]::IsNullOrWhiteSpace($ReceiptPath)) {
    $parent = Split-Path -Parent $ReceiptPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($ReceiptPath), ($receipt | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
}
Write-Host "V213_R75_POWERSHELL_CONTRACT = PASS; contract_id=$($contract.contract_id); contract_sha256=$hash; fixtures=$($results.Count); production_mutation=false" -ForegroundColor Green
