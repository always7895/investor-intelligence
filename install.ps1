[CmdletBinding()]
param(
    [string]$BaseInstallRoot = '',
    [switch]$CreateDesktopShortcut,
    [switch]$Force,
    [switch]$ValidateOnly,
    [switch]$SkipSecContactConfiguration
)

$ErrorActionPreference = 'Stop'
$Bootstrap = Join-Path $PSScriptRoot 'bootstrap.ps1'
if (-not (Test-Path -LiteralPath $Bootstrap -PathType Leaf)) {
    throw 'bootstrap.ps1 is missing from the final release package.'
}
& $Bootstrap @PSBoundParameters
exit $LASTEXITCODE
