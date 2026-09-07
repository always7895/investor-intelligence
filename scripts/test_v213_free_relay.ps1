[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$module = Join-Path $ProjectRoot 'scripts\v213_free_relay.ps1'
$heartbeat = Join-Path $ProjectRoot 'scripts\v213_free_relay_heartbeat.ps1'
$bridge = Join-Path $ProjectRoot 'scripts\run_v213_local_llm_bridge_core.ps1'
$task = Join-Path $ProjectRoot 'register-v213-free-relay-task.ps1'
$activation = Join-Path $ProjectRoot 'activate-v213-seven-field-schedule-core.ps1'
foreach ($path in @($module,$heartbeat,$bridge,$task,$activation)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "FREE_RELAY test input missing: $path" } }
. $module
$probeRoot = Join-Path $env:TEMP ('Investor Intelligence FREE RELAY 測試 (1)-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $probeRoot | Out-Null
try {
    $hmac = 'EXAMPLE_FREE_RELAY_HMAC_SECRET_NOT_REAL_123456789'
    $encrypted = ConvertFrom-SecureString (ConvertTo-SecureString $hmac -AsPlainText -Force)
    $configPath = Join-Path $probeRoot 'worker relay config (測試).json'
    [ordered]@{
        schema_version = 1
        public_snapshot_endpoint = 'https://stable-existing-worker.workers.dev/v21/admin/public-snapshot'
        encrypted_hmac = $encrypted
    } | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
    $config = Get-V213FreeRelayConfig -ConfigPath $configPath
    if ([string]$config.worker_origin -ne 'https://stable-existing-worker.workers.dev') { throw 'Stable workers.dev origin was not retained.' }
    $generation = '0123456789abcdef0123456789abcdef'
    $connected = [datetime]::UtcNow.ToString('o')
    $record = New-V213FreeRelayRouteRecord -PublicUrl 'https://ephemeral-free.trycloudflare.com' -Model 'Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548' -Generation $generation -ConnectedAt $connected -LeaseTtlSeconds 180
    $capturedBody = ''; $capturedHeaders = $null
    $transport = {
        param($Endpoint,$Headers,$Body)
        $script:capturedBody = [string]$Body
        $script:capturedHeaders = $Headers
        if ($Endpoint -ne 'https://stable-existing-worker.workers.dev/v213/admin/free-relay-route') { throw 'Registration endpoint changed away from workers.dev.' }
        return [pscustomobject]@{ ok=$true; status='accepted' }
    }
    [void](Publish-V213FreeRelayRoute -Configuration $config -Record $record -Transport $transport)
    $expected = Get-V213FreeRelaySignature -HmacSecret $hmac -Timestamp ([string]$capturedHeaders['x-ii-v21-timestamp']) -Nonce ([string]$capturedHeaders['x-ii-v21-nonce']) -Body $capturedBody
    if ($expected -cne [string]$capturedHeaders['x-ii-v21-signature']) { throw 'FREE_RELAY HMAC signature mismatch.' }
    if ($capturedBody -match [regex]::Escape($hmac) -or $capturedBody -match 'encrypted_hmac') { throw 'FREE_RELAY route body leaked authentication material.' }
    $parsed = $capturedBody | ConvertFrom-Json
    if ([string]$parsed.tunnel_mode -ne 'quick_free_relay' -or [string]$parsed.model -ne 'Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548' -or [int]$parsed.health_schema_version -ne 2 -or [int]$parsed.consecutive_health_checks -ne 3) { throw 'FREE_RELAY route record contract mismatch.' }
    $gatewaySecret = Get-V213FreeRelayGatewaySecret -HmacSecret $hmac -Generation $generation
    if ($gatewaySecret -notmatch '^[0-9a-f]{64}$' -or $capturedBody -match $gatewaySecret) { throw 'Derived gateway secret handling failed.' }
    foreach ($invalidUrl in @('https://stable.example.com','http://bad.trycloudflare.com','https://evil.trycloudflare.com/path')) {
        try { [void](New-V213FreeRelayRouteRecord -PublicUrl $invalidUrl -Model 'Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548' -Generation $generation -ConnectedAt $connected); throw 'Invalid FREE_RELAY URL was accepted.' }
        catch { if ($_.Exception.Message -eq 'Invalid FREE_RELAY URL was accepted.') { throw } }
    }
    try { [void](New-V213FreeRelayRouteRecord -PublicUrl 'https://ok.trycloudflare.com' -Model 'Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548' -Generation 'replayed-invalid-generation' -ConnectedAt $connected); throw 'Malformed route generation was accepted.' }
    catch { if ($_.Exception.Message -eq 'Malformed route generation was accepted.') { throw } }

    $hostPath = (Get-Process -Id $PID).Path
    & $hostPath -NoProfile -ExecutionPolicy Bypass -File $heartbeat -ProjectRoot $ProjectRoot -SelfTest
    if ($LASTEXITCODE -ne 0) { throw 'FREE_RELAY heartbeat/reconnect simulation failed.' }
    & $hostPath -NoProfile -ExecutionPolicy Bypass -File $task -ProjectRoot $ProjectRoot -ValidateOnly
    if ($LASTEXITCODE -ne 0) { throw 'FREE_RELAY startup task validation failed.' }
    & $hostPath -NoProfile -ExecutionPolicy Bypass -File $bridge -ProjectRoot $ProjectRoot -SelfTest
    if ($LASTEXITCODE -ne 0) { throw 'FREE_RELAY bridge self-test failed.' }

    $bridgeSource = Get-Content -LiteralPath $bridge -Raw -Encoding utf8
    $heartbeatSource = Get-Content -LiteralPath $heartbeat -Raw -Encoding utf8
    $activationSource = Get-Content -LiteralPath $activation -Raw -Encoding utf8
    foreach ($marker in @("Model -cne 'Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548'", "mode -eq 'FreeRelay'", 'Start-HealthyQuickTunnel', 'Publish-V213FreeRelayRoute', 'Start-FreeRelayHeartbeat', 'heartbeatActivationFile')) {
        if ($bridgeSource.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "FREE_RELAY bridge marker missing: $marker" }
    }
    if ($bridgeSource.IndexOf('$heartbeat = Start-FreeRelayHeartbeat',[StringComparison]::Ordinal) -gt $bridgeSource.IndexOf('$freeRelayRegistration = Publish-V213FreeRelayRoute',[StringComparison]::Ordinal)) { throw 'Heartbeat startup must precede atomic Worker route publication.' }
    if ($bridgeSource.IndexOf('if ($FinalizeCutover -and $null -ne $oldState) { Stop-RecordedBridge $oldState }',[StringComparison]::Ordinal) -lt 0) { throw 'Blue/green old-process preservation marker is missing.' }
    if ($heartbeatSource.IndexOf('heartbeat activation was not committed',[StringComparison]::Ordinal) -lt 0) { throw 'Heartbeat activation gate is missing.' }
    foreach ($marker in @('free_relay_lease_expires_at','free_relay_route_generation','health_schema_version','v213-local-llm-gateway','stable_entrypoint=workers_dev')) {
        if ($activationSource.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "FREE_RELAY activation fail-closed marker missing: $marker" }
    }
    Write-Host "V213_FREE_RELAY_HOST_TEST = PASS; powershell=$($PSVersionTable.PSVersion); workers_dev_stable=true; custom_domain=false; hmac=true; secret_redaction=true; exact_model=Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548; health_schema_v2=true; consecutive_health=3; reboot_reconnect=true; rollback=true; production_mutation=false" -ForegroundColor Green
}
finally {
    $config = $null; $hmac = $null; $encrypted = $null; $gatewaySecret = $null
    Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
}
