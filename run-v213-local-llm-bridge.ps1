[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$LlamaBaseUrl = '',
    [int]$GatewayPort = 8814,
    [string]$Model = '',
    [switch]$NoTunnel,
    [switch]$InstallCloudflared,
    [switch]$StopExisting,
    [switch]$FinalizeCutover,
    [ValidateSet('None','QuickTest','Named')][string]$TunnelMode = 'QuickTest',
    [string]$NamedTunnelName = '',
    [string]$NamedTunnelHostname = '',
    [string]$NamedTunnelConfig = '',
    [switch]$SelfTest
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path}
$core=Join-Path ([IO.Path]::GetFullPath($ProjectRoot)) 'scripts\run_v213_local_llm_bridge_core_v2.ps1'
if(-not(Test-Path -LiteralPath $core -PathType Leaf)){throw "Missing source-diverse bridge core: $core"}
& $core @PSBoundParameters
