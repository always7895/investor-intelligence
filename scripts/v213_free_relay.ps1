Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'v213_windows_security.ps1')

function Get-V213FreeRelayConfig {
    param([string]$ConfigPath = '')
    if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
        $ConfigPath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v21-owner-line.local.json'
    }
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw 'FREE_RELAY local Worker configuration is missing.' }
    try { $raw = Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8 | ConvertFrom-Json }
    catch { throw 'FREE_RELAY local Worker configuration is invalid.' }
    $endpointProperty = $raw.PSObject.Properties['public_snapshot_endpoint']
    $hmacProperty = $raw.PSObject.Properties['encrypted_hmac']
    if ($null -eq $endpointProperty -or $null -eq $hmacProperty) { throw 'FREE_RELAY local Worker configuration lacks endpoint or encrypted authentication.' }
    try { $endpoint = [uri]([string]$endpointProperty.Value) } catch { throw 'FREE_RELAY Worker endpoint is invalid.' }
    if ($endpoint.Scheme -ne 'https' -or $endpoint.Host -notmatch '(?i)^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.workers\.dev$' -or -not $endpoint.IsDefaultPort) {
        throw 'FREE_RELAY requires the existing HTTPS workers.dev Worker endpoint.'
    }
    try {
        $secure = ConvertTo-SecureString -String ([string]$hmacProperty.Value)
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $material = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) } }
    }
    catch { throw 'FREE_RELAY local authentication material cannot be decrypted for this Windows user.' }
    if ([string]::IsNullOrWhiteSpace($material) -or $material.Length -lt 32) { throw 'FREE_RELAY authentication material is invalid.' }
    return [pscustomobject]@{
        config_path = [IO.Path]::GetFullPath($ConfigPath)
        worker_origin = $endpoint.GetLeftPart([UriPartial]::Authority).TrimEnd('/')
        registration_endpoint = $endpoint.GetLeftPart([UriPartial]::Authority).TrimEnd('/') + '/v213/admin/free-relay-route'
        hmac_secret = $material
    }
}

function New-V213FreeRelayGeneration {
    return [guid]::NewGuid().ToString('N').ToLowerInvariant()
}

function Get-V213FreeRelayGatewaySecret {
    param([string]$HmacSecret,[string]$Generation)
    if ($HmacSecret.Length -lt 32 -or $Generation -notmatch '^[0-9a-f]{32}$') { throw 'FREE_RELAY gateway-secret inputs are invalid.' }
    $algorithm = New-Object Security.Cryptography.HMACSHA256 -ArgumentList (,[Text.Encoding]::UTF8.GetBytes($HmacSecret))
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes("v213-free-relay-gateway.$Generation")))).Replace('-','').ToLowerInvariant()
    }
    finally { $algorithm.Dispose() }
}

function New-V213FreeRelayRouteRecord {
    param(
        [string]$PublicUrl,
        [string]$Model,
        [string]$Generation,
        [string]$ConnectedAt,
        [int]$LeaseTtlSeconds = 180,
        [datetime]$Now = [datetime]::UtcNow
    )
    if ($PublicUrl -notmatch '^https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com/?$') { throw 'FREE_RELAY accepts only an ephemeral TryCloudflare HTTPS URL.' }
    if ($Model -notmatch '^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}$') { throw 'FREE_RELAY model ID is invalid.' }
    if ($Generation -notmatch '^[0-9a-f]{32}$') { throw 'FREE_RELAY route generation is invalid.' }
    $connected = [datetime]::MinValue
    if (-not [datetime]::TryParse($ConnectedAt,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind,[ref]$connected)) { throw 'FREE_RELAY connected_at is invalid.' }
    $ttl = [Math]::Max(60,[Math]::Min(300,$LeaseTtlSeconds))
    return [ordered]@{
        schema_version = 1
        tunnel_mode = 'quick_free_relay'
        model = $Model
        public_url = $PublicUrl.TrimEnd('/')
        connected_at = $connected.ToUniversalTime().ToString('o')
        expires_at = $Now.ToUniversalTime().AddSeconds($ttl).ToString('o')
        health_schema_version = 2
        route_generation = $Generation
        consecutive_health_checks = 3
    }
}

# The route refresh's signature purpose (cloud/src/v213/free-relay.ts FREE_RELAY_SIGNATURE_PURPOSE): such a signature is
# valid only at /v213/admin/free-relay-route, never at another admin endpoint.
$script:V213FreeRelaySignaturePurpose = 'ii-v213-free-relay-route-v1'

function Get-V213FreeRelaySignature {
    param([string]$HmacSecret,[string]$Timestamp,[string]$Nonce,[string]$Body,[string]$Purpose = '')
    $value = if ($Purpose) { "$Purpose`n$Timestamp.$Nonce.$Body" } else { "$Timestamp.$Nonce.$Body" }
    $algorithm = New-Object Security.Cryptography.HMACSHA256 -ArgumentList (,[Text.Encoding]::UTF8.GetBytes($HmacSecret))
    try { return ([BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($value)))).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
}

function Get-V213FreeRelayErrorCode([string]$Code) {
    # Case-sensitive, whole-string: an upper-case token of 1..80 characters, nothing else (no newline, no body text).
    if ($Code -cmatch '\A[A-Z0-9_]{1,80}\z') { return $Code }
    return 'UNKNOWN'
}

function Invoke-V213FreeRelayRegistration {
    # One signed registration attempt. Returns ok, or the HTTP status and the Worker's own error code (an upper-case token):
    # never headers or the body.
    param([object]$Configuration,[string]$Body,[string]$Purpose,[scriptblock]$Transport)
    $timestamp = [string][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $nonce = [guid]::NewGuid().ToString('N').ToLowerInvariant()
    $signature = Get-V213FreeRelaySignature -HmacSecret ([string]$Configuration.hmac_secret) -Timestamp $timestamp -Nonce $nonce -Body $Body -Purpose $Purpose
    $headers = @{
        'x-ii-v21-timestamp' = $timestamp
        'x-ii-v21-nonce' = $nonce
        'x-ii-v21-signature' = $signature
        'cache-control' = 'no-store'
    }
    try {
        if ($null -ne $Transport) { $result = & $Transport ([string]$Configuration.registration_endpoint) $headers $Body }
        else { $result = Invoke-RestMethod -Method Post -Uri ([string]$Configuration.registration_endpoint) -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($Body)) -TimeoutSec 45 }
    }
    catch {
        $status = try { [int]$_.Exception.Response.StatusCode } catch { 0 }
        $code = try { [string](($_.ErrorDetails.Message | ConvertFrom-Json).code) } catch { '' }
        return [pscustomobject]@{ ok=$false; http=$status; code=(Get-V213FreeRelayErrorCode $code) }
    }
    $ok = $result.PSObject.Properties['ok']
    $accepted = $result.PSObject.Properties['status']
    if (($null -ne $ok -and $ok.Value -eq $true) -or ($null -ne $accepted -and [string]$accepted.Value -eq 'accepted')) { return [pscustomobject]@{ ok=$true } }
    $code = $result.PSObject.Properties['code']
    return [pscustomobject]@{ ok=$false; http=0; code=(Get-V213FreeRelayErrorCode $(if ($null -ne $code) { [string]$code.Value } else { '' })) }
}

function Publish-V213FreeRelayRoute {
    param(
        [object]$Configuration,
        [object]$Record,
        [scriptblock]$Transport = $null
    )
    $body = $Record | ConvertTo-Json -Depth 6 -Compress
    # The route-only signature first (no KV write on a Worker from batch 28 on). A Worker that predates it (a later Worker
    # rolled back, or this runtime installed first) answers V21_SYNC_SIGNATURE_INVALID: then once more with the generic
    # admin signature and a fresh nonce, which that Worker guards with its KV nonce as before. Any other refusal is final.
    $attempt = Invoke-V213FreeRelayRegistration -Configuration $Configuration -Body $body -Purpose $script:V213FreeRelaySignaturePurpose -Transport $Transport
    if (-not $attempt.ok -and $attempt.code -ceq 'V21_SYNC_SIGNATURE_INVALID') {
        $attempt = Invoke-V213FreeRelayRegistration -Configuration $Configuration -Body $body -Purpose '' -Transport $Transport
    }
    if (-not $attempt.ok) { throw ('FREE_RELAY authenticated route registration failed closed (http={0}; code={1}).' -f $attempt.http, $attempt.code) }
    return [pscustomobject]@{ status='PASS'; route_generation=[string]$Record.route_generation; expires_at=[string]$Record.expires_at }
}
