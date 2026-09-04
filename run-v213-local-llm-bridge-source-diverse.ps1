[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$LlamaBaseUrl = '',
    [int]$GatewayPort = 8814,
    [string]$Model = '',
    [switch]$NoTunnel,
    [switch]$InstallCloudflared,
    [switch]$StopExisting,
    [switch]$SelfTest
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path}
$core=Join-Path ([IO.Path]::GetFullPath($ProjectRoot)) 'scripts\run_v213_local_llm_bridge_core_v3.ps1'
if(-not(Test-Path -LiteralPath $core -PathType Leaf)){throw "Missing R75 source-diverse bridge core: $core"}
& $core @PSBoundParameters
