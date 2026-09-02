[CmdletBinding()]
param(
    [ValidateSet('Commit','Rollback','Finalize')][string]$Action = 'Commit',
    [string]$ProjectRoot = '',
    [string]$BundlePath = '',
    [string]$LocalConfigPath = '',
    [string]$TransactionId = '',
    [string]$RunId = '',
    [string]$ResultPath = '',
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

function Get-PropertyValue([object]$Object,[string]$Name,[object]$Default=$null) {
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function Get-HmacHex([string]$Secret,[string]$Value) {
    $algorithm = [Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($Secret))
    try {
        return ([BitConverter]::ToString(
            $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))
        )).Replace('-', '').ToLowerInvariant()
    }
    finally { $algorithm.Dispose() }
}

function Read-ResponseBody([System.Net.WebResponse]$Response) {
    if ($null -eq $Response) { return '' }
    $stream = $Response.GetResponseStream()
    if ($null -eq $stream) { return '' }
    try {
        $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8, $true)
        try { return $reader.ReadToEnd() }
        finally { $reader.Dispose() }
    }
    finally { $stream.Dispose() }
}

function Invoke-SignedJsonPost(
    [uri]$Endpoint,
    [string]$Body,
    [string]$Secret
) {
    $timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()
    $nonce = [guid]::NewGuid().ToString('N')
    $signature = Get-HmacHex $Secret "$timestamp.$nonce.$Body"
    $bytes = [Text.Encoding]::UTF8.GetBytes($Body)
    $request = [System.Net.HttpWebRequest]::Create($Endpoint)
    $request.Method = 'POST'
    $request.ContentType = 'application/json; charset=utf-8'
    $request.ContentLength = $bytes.Length
    $request.Timeout = 90000
    $request.ReadWriteTimeout = 90000
    $request.KeepAlive = $false
    $request.Headers.Add('x-ii-v21-timestamp', $timestamp)
    $request.Headers.Add('x-ii-v21-nonce', $nonce)
    $request.Headers.Add('x-ii-v21-signature', $signature)
    $requestStream = $request.GetRequestStream()
    try { $requestStream.Write($bytes, 0, $bytes.Length) }
    finally { $requestStream.Dispose() }

    $response = $null
    $statusCode = 0
    $responseBody = ''
    try {
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        $statusCode = [int]$response.StatusCode
        $responseBody = Read-ResponseBody $response
    }
    catch [System.Net.WebException] {
        if ($null -ne $_.Exception.Response) {
            $response = [System.Net.HttpWebResponse]$_.Exception.Response
            $statusCode = [int]$response.StatusCode
            $responseBody = Read-ResponseBody $response
        }
        else { throw }
    }
    finally {
        if ($null -ne $response) { $response.Dispose() }
    }

    $parsed = $null
    if (-not [string]::IsNullOrWhiteSpace($responseBody)) {
        try { $parsed = $responseBody | ConvertFrom-Json }
        catch {
            throw "V213_ACTIVATION_RESPONSE_NOT_JSON; http_status=$statusCode"
        }
    }
    if ($statusCode -lt 200 -or $statusCode -ge 300) {
        $code = [string](Get-PropertyValue $parsed 'code' 'UNKNOWN')
        throw "V213_ACTIVATION_HTTP_ERROR; action=$Action; http_status=$statusCode; code=$code"
    }
    if ($null -eq $parsed) {
        throw "V213_ACTIVATION_EMPTY_RESPONSE; action=$Action"
    }
    return $parsed
}

if ($SelfTest) {
    $secret = 'SYNTHETIC_V213_ACTIVATION_SECRET_1234567890'
    $body = '{"schema_version":1,"transaction_id":"00000000000000000000000000000000","run_id":"20260902T000000Z-123456789abc"}'
    $stamp = '1700000000'
    $nonce = '11111111111111111111111111111111'
    $first = Get-HmacHex $secret "$stamp.$nonce.$body"
    $second = Get-HmacHex $secret "$stamp.$nonce.$body"
    if ($first -ne $second -or $first -notmatch '^[0-9a-f]{64}$') {
        throw 'Signed activation client HMAC self-test failed.'
    }
    Write-Host 'V213_ACTIVATION_SYNC_CLIENT_SELF_TEST = PASS; no_network=true; secret_not_printed=true' -ForegroundColor Green
    exit 0
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
if ([string]::IsNullOrWhiteSpace($BundlePath)) {
    $BundlePath = Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json'
}
if ([string]::IsNullOrWhiteSpace($LocalConfigPath)) {
    $LocalConfigPath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v21-owner-line.local.json'
}
if (-not (Test-Path -LiteralPath $LocalConfigPath -PathType Leaf)) {
    throw 'The signed-sync local configuration does not exist.'
}
$config = Get-Content -LiteralPath $LocalConfigPath -Raw -Encoding utf8 | ConvertFrom-Json
$baseEndpoint = [uri][string](Get-PropertyValue $config 'public_snapshot_endpoint' '')
if ($baseEndpoint.Scheme -ne 'https' -or $baseEndpoint.UserInfo) {
    throw 'The signed-sync endpoint must be a credential-free HTTPS URL.'
}

$body = ''
if ($Action -eq 'Commit') {
    if (-not (Test-Path -LiteralPath $BundlePath -PathType Leaf)) {
        throw 'The v2.1.3 activation bundle does not exist.'
    }
    $body = Get-Content -LiteralPath $BundlePath -Raw -Encoding utf8
    $bundle = $body | ConvertFrom-Json
    $TransactionId = [string](Get-PropertyValue $bundle 'transaction_id' '')
    $RunId = [string](Get-PropertyValue $bundle 'run_id' '')
}
else {
    if ($TransactionId -notmatch '^[0-9a-f]{32}$' -or $RunId -notmatch '^\d{8}T\d{6}Z-[0-9a-f]{12}$') {
        throw 'Rollback/finalize requires a valid transaction ID and run ID.'
    }
    $body = [ordered]@{
        schema_version = 1
        transaction_id = $TransactionId
        run_id = $RunId
    } | ConvertTo-Json -Compress
}
if ($TransactionId -notmatch '^[0-9a-f]{32}$' -or $RunId -notmatch '^\d{8}T\d{6}Z-[0-9a-f]{12}$') {
    throw 'The activation bundle transaction/run ID is invalid.'
}

$path = switch ($Action) {
    'Commit' { '/v213/admin/activation-bundle' }
    'Rollback' { '/v213/admin/activation-rollback' }
    'Finalize' { '/v213/admin/activation-finalize' }
}
$endpoint = [uri]($baseEndpoint.GetLeftPart([UriPartial]::Authority) + $path)
$protected = ConvertTo-SecureString -String ([string](Get-PropertyValue $config 'encrypted_hmac' ''))
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($protected)
$keyMaterial = ''
try {
    $keyMaterial = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ([string]::IsNullOrWhiteSpace($keyMaterial) -or $keyMaterial.Length -lt 32) {
        throw 'The signed-sync key could not be recovered.'
    }
    $result = Invoke-SignedJsonPost $endpoint $body $keyMaterial
    if (-not [string]::IsNullOrWhiteSpace($ResultPath)) {
        $parent = Split-Path -Parent $ResultPath
        if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ResultPath -Encoding utf8
    }
    $status = [string](Get-PropertyValue $result 'status' '')
    Write-Host "V213_ACTIVATION_$($Action.ToUpperInvariant()) = PASS; status=$status; run_id=$RunId; transaction_id=$TransactionId" -ForegroundColor Green
}
finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    $keyMaterial = $null
}
