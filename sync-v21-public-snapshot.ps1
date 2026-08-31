[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$SnapshotPath = '',
    [string]$LocalConfigPath = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
if ([string]::IsNullOrWhiteSpace($SnapshotPath)) {
    $SnapshotPath = Join-Path $ProjectRoot 'data\cache\v21_public_snapshot_upload.json'
}
if ([string]::IsNullOrWhiteSpace($LocalConfigPath)) {
    $LocalConfigPath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v21-owner-line.local.json'
}
if (-not (Test-Path -LiteralPath $SnapshotPath -PathType Leaf)) {
    throw 'The v2.1 public snapshot envelope does not exist.'
}
if (-not (Test-Path -LiteralPath $LocalConfigPath -PathType Leaf)) {
    throw 'The v2.1 local deployment configuration does not exist.'
}

$config = Get-Content -LiteralPath $LocalConfigPath -Raw -Encoding utf8 | ConvertFrom-Json
$endpoint = [uri][string]$config.public_snapshot_endpoint
if ($endpoint.Scheme -ne 'https' -or $endpoint.UserInfo) {
    throw 'The public snapshot endpoint must be a credential-free HTTPS URL.'
}
$protected = ConvertTo-SecureString -String ([string]$config.encrypted_hmac)
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($protected)
$keyMaterial = ''
try {
    $keyMaterial = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $body = Get-Content -LiteralPath $SnapshotPath -Raw -Encoding utf8
    $timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()
    $nonce = [guid]::NewGuid().ToString('N')
    $message = "$timestamp.$nonce.$body"
    $hmac = [Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($keyMaterial))
    try {
        $signature = ([BitConverter]::ToString(
            $hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($message))
        )).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $hmac.Dispose()
    }
    $headers = @{
        'x-ii-v21-timestamp' = $timestamp
        'x-ii-v21-nonce' = $nonce
        'x-ii-v21-signature' = $signature
    }
    $response = Invoke-RestMethod -Method Post -Uri $endpoint -Headers $headers `
        -ContentType 'application/json; charset=utf-8' `
        -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 90
    if ([string]$response.status -ne 'accepted') {
        throw 'The v2.1 Worker did not accept the public snapshot.'
    }
    Write-Host "V2.1 public snapshot promoted: $($response.run_id)" -ForegroundColor Green
}
finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    $keyMaterial = $null
}
