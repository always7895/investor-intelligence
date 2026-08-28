[CmdletBinding()]
param(
    [string]$ArchivePath = '',
    [string]$ChecksumPath = '',
    [string]$BaseInstallRoot = '',
    [switch]$CreateDesktopShortcut,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

$Version = '2.0.0'
if ([string]::IsNullOrWhiteSpace($ArchivePath)) {
    $ArchivePath = Join-Path $PSScriptRoot "investor-intelligence-$Version.zip"
}
if ([string]::IsNullOrWhiteSpace($ChecksumPath)) {
    $ChecksumPath = Join-Path $PSScriptRoot "investor-intelligence-$Version.sha256"
}
$ArchivePath = [System.IO.Path]::GetFullPath($ArchivePath)
$ChecksumPath = [System.IO.Path]::GetFullPath($ChecksumPath)

if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
    throw "Final release archive not found: $ArchivePath"
}
if (-not (Test-Path -LiteralPath $ChecksumPath -PathType Leaf)) {
    throw "SHA-256 checksum file not found: $ChecksumPath"
}

$checksumLine = (Get-Content -LiteralPath $ChecksumPath -Raw -Encoding ascii).Trim()
if ($checksumLine -notmatch '^([0-9a-fA-F]{64})\s+\*?(.+)$') {
    throw 'Checksum file has an invalid format.'
}
$expected = $Matches[1].ToLowerInvariant()
$expectedName = [System.IO.Path]::GetFileName($Matches[2].Trim())
$actualName = [System.IO.Path]::GetFileName($ArchivePath)
if ($expectedName -ne $actualName) {
    throw "Checksum is bound to $expectedName, not $actualName."
}
$actual = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    throw "Final release SHA-256 verification failed. Expected $expected, received $actual."
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("investor-intelligence-final-" + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $tempRoot -Force
    $metadataPath = Join-Path $tempRoot 'release-metadata.json'
    $bootstrapPath = Join-Path $tempRoot 'bootstrap.ps1'
    if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $bootstrapPath -PathType Leaf)) {
        throw 'Verified archive is missing final installer metadata or bootstrap.ps1.'
    }
    $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ([string]$metadata.version -ne $Version -or [string]$metadata.build_mode -ne 'final_release') {
        throw 'Extracted archive is not the expected final v2.0.0 release.'
    }

    $arguments = @{}
    if (-not [string]::IsNullOrWhiteSpace($BaseInstallRoot)) { $arguments.BaseInstallRoot = $BaseInstallRoot }
    if ($CreateDesktopShortcut) { $arguments.CreateDesktopShortcut = $true }
    if ($Force) { $arguments.Force = $true }
    & $bootstrapPath @arguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Final release bootstrap failed.'
    }
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Verified Investor Intelligence v$Version installation completed." -ForegroundColor Green
exit 0
