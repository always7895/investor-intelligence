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
# Compatibility entrypoint: all preflight/activation rules live in one file.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'activate-v213-diversified-schedule.ps1') @PSBoundParameters
exit $LASTEXITCODE
