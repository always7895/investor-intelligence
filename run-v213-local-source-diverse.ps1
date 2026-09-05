[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$Model = '',
    [string]$LlamaBaseUrl = '',
    [switch]$NoModelBridge,
    [switch]$NoTunnel,
    [ValidateSet('None','QuickTest','FreeRelay','Named')][string]$TunnelMode = 'FreeRelay',
    [string]$NamedTunnelName = '',
    [string]$NamedTunnelHostname = '',
    [string]$NamedTunnelConfig = '',
    [string]$FreeRelayConfigPath = '',
    [int]$FreeRelayLeaseTtlSeconds = 180,
    [switch]$InstallCloudflared,
    [switch]$NoSync,
    [switch]$NoAutoActivation,
    [switch]$Synthetic,
    [switch]$SelfTest
)
# Compatibility entrypoint: keep parameters, not a second implementation.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'run-v213-local.ps1') @PSBoundParameters
exit $LASTEXITCODE
