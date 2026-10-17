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
    $record = New-V213FreeRelayRouteRecord -PublicUrl 'https://ephemeral-free.trycloudflare.com' -Model 'qwen38-q6' -Generation $generation -ConnectedAt $connected -LeaseTtlSeconds 180
    $capturedBody = ''; $capturedHeaders = $null
    $transport = {
        param($Endpoint,$Headers,$Body)
        $script:capturedBody = [string]$Body
        $script:capturedHeaders = $Headers
        if ($Endpoint -ne 'https://stable-existing-worker.workers.dev/v213/admin/free-relay-route') { throw 'Registration endpoint changed away from workers.dev.' }
        return [pscustomobject]@{ ok=$true; status='accepted' }
    }
    [void](Publish-V213FreeRelayRoute -Configuration $config -Record $record -Transport $transport)
    $expected = Get-V213FreeRelaySignature -HmacSecret $hmac -Timestamp ([string]$capturedHeaders['x-ii-v21-timestamp']) -Nonce ([string]$capturedHeaders['x-ii-v21-nonce']) -Body $capturedBody -Purpose 'ii-v213-free-relay-route-v1'
    if ($expected -cne [string]$capturedHeaders['x-ii-v21-signature']) { throw 'FREE_RELAY HMAC signature mismatch (purpose-bound route refresh).' }
    $generic = Get-V213FreeRelaySignature -HmacSecret $hmac -Timestamp ([string]$capturedHeaders['x-ii-v21-timestamp']) -Nonce ([string]$capturedHeaders['x-ii-v21-nonce']) -Body $capturedBody
    if ($generic -ceq [string]$capturedHeaders['x-ii-v21-signature']) { throw 'FREE_RELAY route refresh carried a generic admin signature.' }
    # Signer x verifier compatibility: this (new) publisher against a Worker that verifies only the route-bound form (new),
    # only the generic form (old, e.g. 16cb1b3 or a rollback) and neither (a forged-secret Worker: both attempts refused).
    foreach ($workerKind in @('new','old','none')) {
        $attempts = New-Object System.Collections.ArrayList
        $verifier = {
            param($Endpoint,$Headers,$Body)
            $purposeBound = Get-V213FreeRelaySignature -HmacSecret $hmac -Timestamp ([string]$Headers['x-ii-v21-timestamp']) -Nonce ([string]$Headers['x-ii-v21-nonce']) -Body $Body -Purpose 'ii-v213-free-relay-route-v1'
            $generic = Get-V213FreeRelaySignature -HmacSecret $hmac -Timestamp ([string]$Headers['x-ii-v21-timestamp']) -Nonce ([string]$Headers['x-ii-v21-nonce']) -Body $Body
            $form = if ([string]$Headers['x-ii-v21-signature'] -ceq $purposeBound) { 'route' } elseif ([string]$Headers['x-ii-v21-signature'] -ceq $generic) { 'generic' } else { 'invalid' }
            [void]$attempts.Add(@($form, [string]$Headers['x-ii-v21-nonce']))
            $accepted = ($workerKind -eq 'new' -and $form -eq 'route') -or ($workerKind -eq 'old' -and $form -eq 'generic')
            if ($accepted) { return [pscustomobject]@{ ok=$true; status='accepted' } }
            return [pscustomobject]@{ ok=$false; code='V21_SYNC_SIGNATURE_INVALID' }
        }.GetNewClosure()
        $failed = $false
        try { [void](Publish-V213FreeRelayRoute -Configuration $config -Record $record -Transport $verifier) } catch { $failed = $true }
        $forms = ($attempts | ForEach-Object { $_[0] }) -join ','
        $expected = @{ new = 'route'; old = 'route,generic'; none = 'route,generic' }[$workerKind]
        if ($forms -ne $expected) { throw "FREE_RELAY compatibility ($workerKind): attempts $forms, expected $expected." }
        if ($failed -ne ($workerKind -eq 'none')) { throw "FREE_RELAY compatibility ($workerKind): outcome mismatch." }
        if ($attempts.Count -eq 2 -and $attempts[0][1] -eq $attempts[1][1]) { throw 'FREE_RELAY fallback reused the nonce.' }
    }
    # Any refusal other than a signature mismatch is final (no generic retry).
    $refused = New-Object System.Collections.ArrayList
    $refusing = { param($Endpoint,$Headers,$Body) [void]$refused.Add('x'); return [pscustomobject]@{ ok=$false; code='FREE_RELAY_PUBLIC_HEALTH_FAILED' } }.GetNewClosure()
    try { [void](Publish-V213FreeRelayRoute -Configuration $config -Record $record -Transport $refusing); throw 'FREE_RELAY refusal was accepted.' }
    catch { if ($_.Exception.Message -notmatch 'code=FREE_RELAY_PUBLIC_HEALTH_FAILED') { throw } }
    if ($refused.Count -ne 1) { throw 'FREE_RELAY retried after a non-signature refusal.' }
    # A failed registration logs only an upper-case error token; anything else becomes UNKNOWN.
    foreach ($case in @(@('FREE_RELAY_PUBLIC_HEALTH_FAILED','FREE_RELAY_PUBLIC_HEALTH_FAILED'), @('free_relay_lower','UNKNOWN'), @("SAFE`n",'UNKNOWN'),
                        @(('A' * 81),'UNKNOWN'), @('','UNKNOWN'), @('<html>','UNKNOWN'), @('CODE WITH SPACE','UNKNOWN'))) {
        if ((Get-V213FreeRelayErrorCode $case[0]) -cne $case[1]) { throw ('FREE_RELAY error-code filter accepted: ' + $case[0].Length) }
    }
    if ($capturedBody -match [regex]::Escape($hmac) -or $capturedBody -match 'encrypted_hmac') { throw 'FREE_RELAY route body leaked authentication material.' }
    $parsed = $capturedBody | ConvertFrom-Json
    if ([string]$parsed.tunnel_mode -ne 'quick_free_relay' -or [string]$parsed.model -ne 'qwen38-q6' -or [int]$parsed.health_schema_version -ne 2 -or [int]$parsed.consecutive_health_checks -ne 3) { throw 'FREE_RELAY route record contract mismatch.' }
    $gatewaySecret = Get-V213FreeRelayGatewaySecret -HmacSecret $hmac -Generation $generation
    if ($gatewaySecret -notmatch '^[0-9a-f]{64}$' -or $capturedBody -match $gatewaySecret) { throw 'Derived gateway secret handling failed.' }
    foreach ($invalidUrl in @('https://stable.example.com','http://bad.trycloudflare.com','https://evil.trycloudflare.com/path')) {
        try { [void](New-V213FreeRelayRouteRecord -PublicUrl $invalidUrl -Model 'qwen38-q6' -Generation $generation -ConnectedAt $connected); throw 'Invalid FREE_RELAY URL was accepted.' }
        catch { if ($_.Exception.Message -eq 'Invalid FREE_RELAY URL was accepted.') { throw } }
    }
    try { [void](New-V213FreeRelayRouteRecord -PublicUrl 'https://ok.trycloudflare.com' -Model 'qwen38-q6' -Generation 'replayed-invalid-generation' -ConnectedAt $connected); throw 'Malformed route generation was accepted.' }
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
    # Since 57b9ea6 the relay follows the auto-detected model: an unprofiled FreeRelay derives its profile from the resolved
    # model, and Test-SelectedModelRoute checks the exact served identity (the old qwen38-q6 pin is gone).
    foreach ($marker in @('Set-FollowingModelProfile $Model', 'Test-SelectedModelRoute $llama $Model', "mode -eq 'FreeRelay'", 'Start-HealthyQuickTunnel', 'Publish-V213FreeRelayRoute', 'Start-FreeRelayHeartbeat', 'heartbeatActivationFile')) {
        if ($bridgeSource.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "FREE_RELAY bridge marker missing: $marker" }
    }
    if ($bridgeSource.IndexOf('$heartbeat = Start-FreeRelayHeartbeat',[StringComparison]::Ordinal) -gt $bridgeSource.IndexOf('$freeRelayRegistration = Publish-V213FreeRelayRoute',[StringComparison]::Ordinal)) { throw 'Heartbeat startup must precede atomic Worker route publication.' }
    if ($bridgeSource.IndexOf('if ($FinalizeCutover -and $null -ne $oldState) { Stop-RecordedBridge $oldState }',[StringComparison]::Ordinal) -lt 0) { throw 'Blue/green old-process preservation marker is missing.' }
    if ($heartbeatSource.IndexOf('heartbeat activation was not committed',[StringComparison]::Ordinal) -lt 0) { throw 'Heartbeat activation gate is missing.' }
    foreach ($marker in @('free_relay_lease_expires_at','free_relay_route_generation','health_schema_version','v213-local-llm-gateway','stable_entrypoint=workers_dev')) {
        if ($activationSource.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "FREE_RELAY activation fail-closed marker missing: $marker" }
    }
    Write-Host "V213_FREE_RELAY_HOST_TEST = PASS; powershell=$($PSVersionTable.PSVersion); workers_dev_stable=true; custom_domain=false; hmac=true; secret_redaction=true; exact_model=qwen38-q6; health_schema_v2=true; consecutive_health=3; reboot_reconnect=true; rollback=true; production_mutation=false" -ForegroundColor Green
}
finally {
    $config = $null; $hmac = $null; $encrypted = $null; $gatewaySecret = $null
    Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
}
