[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$CloudflaredPath = '',
    [Parameter(Mandatory=$false)][string]$NamedTunnelName = '',
    [Parameter(Mandatory=$false)][string]$NamedTunnelHostname = '',
    [Parameter(Mandatory=$false)][string]$NamedTunnelConfig = '',
    [string]$StateRoot = '',
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
. (Join-Path $ProjectRoot 'scripts\v213_named_tunnel_helpers.ps1')

function Resolve-SetupCloudflared {
    param([string]$ExplicitPath)
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) { throw 'Explicit cloudflared path does not exist.' }
        return [IO.Path]::GetFullPath($ExplicitPath)
    }
    $command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command cloudflared -ErrorAction SilentlyContinue }
    if (-not $command) { throw 'cloudflared was not found. Install cloudflared and run cloudflared tunnel login/create outside this script first.' }
    return $command.Source
}

function New-FakeCloudflaredForSelfTest {
    param([string]$Root)
    $path = Join-Path $Root 'fake cloudflared (測試).cmd'
    $body = @'
@echo off
setlocal enabledelayedexpansion
if not "%II_FAKE_CLOUDFLARED_LOG%"=="" echo %*>>"%II_FAKE_CLOUDFLARED_LOG%"
if "%1"=="tunnel" if "%2"=="list" exit /b 0
if "%1"=="tunnel" if "%2"=="--config" if "%4"=="ingress" if "%5"=="validate" exit /b 0
if "%1"=="tunnel" if "%2"=="info" (echo ID: 12345678-1234-1234-1234-123456789abc & exit /b 0)
if "%1"=="tunnel" if "%2"=="route" if "%3"=="dns" exit /b 0
echo unexpected args 1>&2
exit /b 7
'@
    [IO.File]::WriteAllText($path, $body, [Text.Encoding]::ASCII)
    return $path
}

if ($SelfTest) {
    $probeRoot = Join-Path $env:TEMP ('Investor Intelligence named tunnel 測試 (1)-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $probeRoot | Out-Null
    $oldLog = $env:II_FAKE_CLOUDFLARED_LOG
    try {
        $env:II_FAKE_CLOUDFLARED_LOG = Join-Path $probeRoot 'cloudflared-args.log'
        $fake = New-FakeCloudflaredForSelfTest $probeRoot
        $credential = Join-Path $probeRoot '12345678-1234-1234-1234-123456789abc.json'
        [IO.File]::WriteAllText($credential, '{"AccountTag":"account-self-test","TunnelID":"12345678-1234-1234-1234-123456789abc","TunnelSecret":"self-test-secret-not-real"}', [Text.UTF8Encoding]::new($false))
        $config = Join-Path $probeRoot 'named tunnel config (測試).yml'
        $configText = "tunnel: qwen38-q6-prod`ncredentials-file: $credential`ningress:`n  - hostname: qwen38.example.com`n    service: http://127.0.0.1:8814`n  - service: http_status:404`n"
        [IO.File]::WriteAllText($config, $configText, [Text.UTF8Encoding]::new($false))
        $stateRoot = Join-Path $probeRoot 'state'
        & $MyInvocation.MyCommand.Path -ProjectRoot $ProjectRoot -CloudflaredPath $fake -NamedTunnelName 'qwen38-q6-prod' -NamedTunnelHostname 'qwen38.example.com' -NamedTunnelConfig $config -StateRoot $stateRoot
        $metadataPath = Join-Path $stateRoot 'v213-named-tunnel.json'
        if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) { throw 'Named tunnel metadata was not written.' }
        $metadataText = Get-Content -LiteralPath $metadataPath -Raw -Encoding utf8
        $metadata = $metadataText | ConvertFrom-Json
        if ([string]$metadata.named_tunnel_name -ne 'qwen38-q6-prod' -or [string]$metadata.named_tunnel_hostname -ne 'qwen38.example.com') { throw 'Named tunnel metadata identity mismatch.' }
        if ($metadataText -match 'account-self-test|TunnelSecret|self-test-secret-not-real|AccountTag') { throw 'Secret-like credential contents were persisted.' }
        if ([bool]$metadata.plaintext_credentials_persisted -ne $false -or [bool]$metadata.credential_file_path_persisted -ne $false) { throw 'Credential persistence flags are unsafe.' }
        $argsLog = Get-Content -LiteralPath $env:II_FAKE_CLOUDFLARED_LOG -Raw -Encoding utf8
        foreach ($required in @('tunnel list','tunnel --config','ingress validate','tunnel info qwen38-q6-prod','tunnel route dns --overwrite-dns qwen38-q6-prod qwen38.example.com')) {
            if ($argsLog -notlike "*$required*") { throw "cloudflared prerequisite command missing: $required" }
        }
        try {
            & $MyInvocation.MyCommand.Path -ProjectRoot $ProjectRoot -CloudflaredPath $fake -NamedTunnelName '' -NamedTunnelHostname 'qwen38.example.com' -NamedTunnelConfig $config -StateRoot $stateRoot
            throw 'Missing NamedTunnelName was accepted.'
        }
        catch { if ($_.Exception.Message -eq 'Missing NamedTunnelName was accepted.') { throw } }
        $badConfig = Join-Path $probeRoot 'bad.yml'
        [IO.File]::WriteAllText($badConfig, "tunnel: qwen38-q6-prod`ningress:`n - service: http://127.0.0.1:8814`n", [Text.UTF8Encoding]::new($false))
        try {
            & $MyInvocation.MyCommand.Path -ProjectRoot $ProjectRoot -CloudflaredPath $fake -NamedTunnelName 'qwen38-q6-prod' -NamedTunnelHostname 'qwen38.example.com' -NamedTunnelConfig $badConfig -StateRoot $stateRoot
            throw 'Missing credentials-file was accepted.'
        }
        catch { if ($_.Exception.Message -eq 'Missing credentials-file was accepted.') { throw } }
        $wrongCredential = Join-Path $probeRoot 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.json'
        [IO.File]::WriteAllText($wrongCredential, '{"AccountTag":"account-self-test","TunnelID":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","TunnelSecret":"self-test-secret-not-real"}', [Text.UTF8Encoding]::new($false))
        $wrongConfig = Join-Path $probeRoot 'wrong-credential.yml'
        [IO.File]::WriteAllText($wrongConfig, "tunnel: qwen38-q6-prod`ncredentials-file: $wrongCredential`ningress:`n - service: http://127.0.0.1:8814`n", [Text.UTF8Encoding]::new($false))
        try {
            & $MyInvocation.MyCommand.Path -ProjectRoot $ProjectRoot -CloudflaredPath $fake -NamedTunnelName 'qwen38-q6-prod' -NamedTunnelHostname 'qwen38.example.com' -NamedTunnelConfig $wrongConfig -StateRoot $stateRoot
            throw 'Mismatched tunnel credentials were accepted.'
        }
        catch { if ($_.Exception.Message -eq 'Mismatched tunnel credentials were accepted.') { throw } }
        Write-Host 'V213_NAMED_TUNNEL_SETUP_SELF_TEST = PASS; cloudflared_auth=true; credentials=true; mismatched_credentials_rejected=true; dns_route=true; special_path=true; no_secret_persistence=true; exact_model=qwen38-q6' -ForegroundColor Green
        exit 0
    }
    finally {
        $env:II_FAKE_CLOUDFLARED_LOG = $oldLog
        Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$cloudflared = Resolve-SetupCloudflared $CloudflaredPath
$prereq = Test-V213NamedTunnelPrerequisites -CloudflaredPath $cloudflared -Name $NamedTunnelName -Hostname $NamedTunnelHostname -ConfigPath $NamedTunnelConfig
$dnsStatus = Invoke-V213NamedTunnelDnsRoute -CloudflaredPath $cloudflared -Name $NamedTunnelName -Hostname $NamedTunnelHostname
$metadataPath = Write-V213NamedTunnelMetadata -StateRoot $StateRoot -PrerequisiteResult $prereq -DnsRouteStatus $dnsStatus
Write-Host "V213_NAMED_TUNNEL_SETUP = PASS; name=$NamedTunnelName; host=$NamedTunnelHostname; dns_route=$dnsStatus; metadata=$metadataPath; credentials_validated=true; credentials_printed=false; production_mutation_by_ci=false" -ForegroundColor Green
