[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$ReportPath = '',
    [string]$LocalConfigPath = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $ReportPath = Join-Path $ProjectRoot 'data\cache\v213_top20_report_public_latest.json'
}
if ([string]::IsNullOrWhiteSpace($LocalConfigPath)) {
    $LocalConfigPath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v21-owner-line.local.json'
}
if (-not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) {
    throw 'The v2.1.3 seven-field Top 20 report does not exist.'
}
if (-not (Test-Path -LiteralPath $LocalConfigPath -PathType Leaf)) {
    throw 'The existing signed-sync local deployment configuration does not exist.'
}

$config = Get-Content -LiteralPath $LocalConfigPath -Raw -Encoding utf8 | ConvertFrom-Json
$baseEndpoint = [uri][string]$config.public_snapshot_endpoint
if ($baseEndpoint.Scheme -ne 'https' -or $baseEndpoint.UserInfo) {
    throw 'The existing signed-sync endpoint must be a credential-free HTTPS URL.'
}
$endpoint = [uri]($baseEndpoint.GetLeftPart([UriPartial]::Authority) + '/v213/admin/top20-report')
$protected = ConvertTo-SecureString -String ([string]$config.encrypted_hmac)
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($protected)
$keyMaterial = ''
try {
    $keyMaterial = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ([string]::IsNullOrWhiteSpace($keyMaterial) -or $keyMaterial.Length -lt 32) {
        throw 'The existing signed-sync key could not be recovered.'
    }
    $body = Get-Content -LiteralPath $ReportPath -Raw -Encoding utf8
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
    if ([string]$response.status -ne 'accepted' -or [int]$response.report_count -ne 20) {
        throw 'The v2.1.3 Worker did not accept the seven-field Top 20 report.'
    }
    Write-Host "V2.1.3 seven-field Top 20 report promoted: $($response.run_id)" -ForegroundColor Green
}
finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    $keyMaterial = $null
}
