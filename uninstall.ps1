[CmdletBinding()]
param(
    [string]$BaseInstallRoot = '',
    [switch]$RemoveLocalData
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($BaseInstallRoot)) {
    $BaseInstallRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
}
$BaseInstallRoot = [System.IO.Path]::GetFullPath($BaseInstallRoot)
$StatePath = Join-Path $BaseInstallRoot 'install-state.json'

foreach ($name in @('InvestorIntelligence-Morning', 'InvestorIntelligence-Evening')) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $BaseInstallRoot -PathType Container)) {
    Write-Host 'Investor Intelligence is already absent.' -ForegroundColor Green
    exit 0
}

if ($RemoveLocalData) {
    Remove-Item -LiteralPath $BaseInstallRoot -Recurse -Force
    Write-Host 'Investor Intelligence code, runtime, reports and local configuration were removed.' -ForegroundColor Green
    exit 0
}

$PreserveRoot = Join-Path $BaseInstallRoot ('Preserved-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Force -Path $PreserveRoot | Out-Null
if (Test-Path -LiteralPath (Join-Path $BaseInstallRoot 'UserData')) {
    Move-Item -LiteralPath (Join-Path $BaseInstallRoot 'UserData') -Destination $PreserveRoot -Force
}
if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
    $state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
    $appRoot = [string]$state.application_root
    foreach ($relative in @('reports', 'data', 'daily_briefing.log')) {
        $candidate = Join-Path $appRoot $relative
        if (Test-Path -LiteralPath $candidate) {
            Move-Item -LiteralPath $candidate -Destination $PreserveRoot -Force
        }
    }
}

foreach ($child in Get-ChildItem -LiteralPath $BaseInstallRoot -Force) {
    if ($child.FullName -eq $PreserveRoot) { continue }
    Remove-Item -LiteralPath $child.FullName -Recurse -Force
}
Write-Host "Investor Intelligence was uninstalled. Local configuration/reports were preserved at: $PreserveRoot" -ForegroundColor Green
Write-Host 'Use -RemoveLocalData only when permanent local-data deletion is intended.' -ForegroundColor Yellow
exit 0
