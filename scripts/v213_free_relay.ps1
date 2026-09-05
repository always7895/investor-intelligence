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

function Get-V213FreeRelaySignature {
    param([string]$HmacSecret,[string]$Timestamp,[string]$Nonce,[string]$Body)
    $value = "$Timestamp.$Nonce.$Body"
    $algorithm = New-Object Security.Cryptography.HMACSHA256 -ArgumentList (,[Text.Encoding]::UTF8.GetBytes($HmacSecret))
    try { return ([BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($value)))).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
}

function Publish-V213FreeRelayRoute {
    param(
        [object]$Configuration,
        [object]$Record,
        [scriptblock]$Transport = $null
    )
    $body = $Record | ConvertTo-Json -Depth 6 -Compress
    $timestamp = [string][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $nonce = [guid]::NewGuid().ToString('N').ToLowerInvariant()
    $signature = Get-V213FreeRelaySignature -HmacSecret ([string]$Configuration.hmac_secret) -Timestamp $timestamp -Nonce $nonce -Body $body
    $headers = @{
        'x-ii-v21-timestamp' = $timestamp
        'x-ii-v21-nonce' = $nonce
        'x-ii-v21-signature' = $signature
        'cache-control' = 'no-store'
    }
    try {
        if ($null -ne $Transport) { $result = & $Transport ([string]$Configuration.registration_endpoint) $headers $body }
        else { $result = Invoke-RestMethod -Method Post -Uri ([string]$Configuration.registration_endpoint) -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 45 }
    }
    catch { throw 'FREE_RELAY authenticated route registration failed closed.' }
    $ok = $result.PSObject.Properties['ok']
    $status = $result.PSObject.Properties['status']
    if (($null -eq $ok -or $ok.Value -ne $true) -and ($null -eq $status -or [string]$status.Value -ne 'accepted')) { throw 'FREE_RELAY Worker rejected the route update.' }
    return [pscustomobject]@{ status='PASS'; route_generation=[string]$Record.route_generation; expires_at=[string]$Record.expires_at }
}
