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
    [ValidateSet('None','QuickTest','FreeRelay','Named')][string]$TunnelMode = 'FreeRelay',
    [string]$NamedTunnelName = '',
    [string]$NamedTunnelHostname = '',
    [string]$NamedTunnelConfig = '',
    [string]$FreeRelayConfigPath = '',
    [int]$FreeRelayLeaseTtlSeconds = 180,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$preferredModel = 'RVN-Q6_K-multilingual-mtp'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$namedTunnelHelpers = Join-Path $scriptRoot 'v213_named_tunnel_helpers.ps1'
if (Test-Path -LiteralPath $namedTunnelHelpers -PathType Leaf) { . $namedTunnelHelpers }
$freeRelayHelpers = Join-Path $scriptRoot 'v213_free_relay.ps1'
if (-not (Test-Path -LiteralPath $freeRelayHelpers -PathType Leaf)) { throw 'FREE_RELAY helper is missing.' }
. $freeRelayHelpers

function ConvertTo-WindowsCommandLineArgument([string]$Value) {
    if ($null -eq $Value -or $Value.Length -eq 0) { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Join-NativeArgumentLine([string[]]$Values) {
    $rendered = @($Values | ForEach-Object { ConvertTo-WindowsCommandLineArgument -Value ([string]$_) })
    return ($rendered -join ' ')
}

function Start-NativeRedirectedProcess {
    param(
        [string]$ExecutablePath,
        [string]$FirstArgument,
        [string[]]$Arguments,
        [string]$StdoutPath,
        [string]$StderrPath
    )
    $allArguments = @($FirstArgument) + @($Arguments)
    $argumentLine = Join-NativeArgumentLine $allArguments
    return Start-Process -FilePath $ExecutablePath -ArgumentList $argumentLine -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath
}

function Start-GatewayNativeProcess {
    param([string]$PythonPath,[string]$ScriptPath,[string[]]$Arguments,[string]$StdoutPath,[string]$StderrPath)
    return Start-NativeRedirectedProcess $PythonPath $ScriptPath $Arguments $StdoutPath $StderrPath
}

function Resolve-TunnelPolicy([string]$Mode,[bool]$NoTunnelRequested,[string]$Name,[string]$Hostname,[string]$ConfigPath) {
    if ($NoTunnelRequested) { $Mode = 'None' }
    if ($Mode -eq 'Named') {
        Assert-V213NamedTunnelInputs -Name $Name -Hostname $Hostname -ConfigPath $ConfigPath
    }
    return [pscustomobject]@{
        mode = $Mode
        test_only = $Mode -eq 'QuickTest'
        production_eligible = $Mode -in @('FreeRelay','Named')
        free_relay = $Mode -eq 'FreeRelay'
    }
}

function Get-BlueGreenDecision([bool]$NewHealthy,[bool]$Finalize) {
    if (-not $NewHealthy) { return 'ROLLBACK_NEW_RETAIN_OLD' }
    if ($Finalize) { return 'PROMOTE_NEW_STOP_OLD' }
    return 'PROMOTE_NEW_RETAIN_OLD_UNTIL_FINALIZE'
}

function Get-RedactedLogTail([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '<missing>' }
    $lines = @(Get-Content -LiteralPath $Path -Tail 20 -ErrorAction SilentlyContinue)
    $safe = foreach ($line in $lines) {
        $value = [string]$line
        $value = [regex]::Replace($value, '(?i)bearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer <redacted>')
        $value = [regex]::Replace($value, '(?i)(authorization|token|secret|api[_-]?key|password)\s*[:=]\s*[^\s;,]+', '$1=<redacted>')
        if ($value.Length -gt 500) { $value = $value.Substring(0, 500) + '<truncated>' }
        $value
    }
    if (@($safe).Count -eq 0) { return '<empty>' }
    return ($safe -join ' | ')
}

function Get-ObjectPropertyValue {
    param([object]$Object, [string]$Name, [object]$Default = $null)
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function Test-HealthModel {
    param([object]$Health, [string]$SelectedModel)
    $ok = Get-ObjectPropertyValue $Health 'ok' $false
    $service = [string](Get-ObjectPropertyValue $Health 'service' '')
    $schema = 0
    [void][int]::TryParse([string](Get-ObjectPropertyValue $Health 'health_schema_version' '0'), [ref]$schema)
    $reachable = Get-ObjectPropertyValue $Health 'llama_reachable' $false
    $available = Get-ObjectPropertyValue $Health 'selected_model_available' $false
    $reportedModel = [string](Get-ObjectPropertyValue $Health 'selected_model' '')
    return (
        $ok -eq $true -and
        $service -eq 'v213-local-llm-gateway' -and
        $schema -ge 2 -and
        $reachable -eq $true -and
        $available -eq $true -and
        $reportedModel -ieq $SelectedModel
    )
}

if ($SelfTest) {
    $legacy = [pscustomobject]@{ ok = $true; llama_reachable = $true }
    if (Test-HealthModel $legacy 'model-a') { throw 'Legacy health payload was incorrectly accepted.' }
    $valid = [pscustomobject]@{
        ok = $true
        service = 'v213-local-llm-gateway'
        health_schema_version = 2
        llama_reachable = $true
        selected_model_available = $true
        selected_model = 'model-a'
    }
    if (-not (Test-HealthModel $valid 'model-a')) { throw 'Health schema v2 payload was rejected.' }
    $pythonPath = ''
    if ($env:PROJECT_PYTHON -and (Test-Path -LiteralPath $env:PROJECT_PYTHON -PathType Leaf)) { $pythonPath = [IO.Path]::GetFullPath($env:PROJECT_PYTHON) }
    if (-not $pythonPath) {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $pythonCommand) { $pythonCommand = Get-Command python -ErrorAction Stop | Select-Object -First 1 }
        $pythonPath = $pythonCommand.Source
    }
    $probeRoot = Join-Path $env:TEMP ('Investor Intelligence 測試 Path (1)-' + [guid]::NewGuid().ToString('N'))
    $probeScripts = Join-Path $probeRoot 'scripts'
    New-Item -ItemType Directory -Force -Path $probeScripts | Out-Null
    $probeStdout = Join-Path $probeRoot 'gateway.stdout.log'
    $probeStderr = Join-Path $probeRoot 'gateway.stderr.log'
    try {
        Copy-Item -LiteralPath (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'v212_local_llm_gateway.py') -Destination $probeScripts
        Copy-Item -LiteralPath (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'v213_local_llm_gateway.py') -Destination $probeScripts
        $probe = Start-GatewayNativeProcess $pythonPath (Join-Path $probeScripts 'v213_local_llm_gateway.py') @('--self-test') $probeStdout $probeStderr
        $finished = $probe.WaitForExit(30000)
        if ($finished) { $probe.WaitForExit(); $probe.Refresh() }
        $probeOutput = if (Test-Path -LiteralPath $probeStdout) { Get-Content -LiteralPath $probeStdout -Raw -ErrorAction SilentlyContinue } else { '' }
        if (-not $finished -or $probeOutput -notmatch 'V213_LOCAL_LLM_GATEWAY_HEALTH_SELF_TEST = PASS') {
            try { $probe.Kill() } catch {}
            throw "Gateway process-path self-test failed. stderr_tail=$(Get-RedactedLogTail $probeStderr); stdout_tail=$(Get-RedactedLogTail $probeStdout)"
        }
    }
    finally { Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue }
    $quickPolicy = Resolve-TunnelPolicy 'QuickTest' $false '' '' ''
    if (-not $quickPolicy.test_only -or $quickPolicy.production_eligible) { throw 'Quick Tunnel policy self-test failed.' }
    $freePolicy = Resolve-TunnelPolicy 'FreeRelay' $false '' '' ''
    if (-not $freePolicy.free_relay -or -not $freePolicy.production_eligible -or $freePolicy.test_only) { throw 'FREE_RELAY policy self-test failed.' }
    $testHmac = 'EXAMPLE_FREE_RELAY_HMAC_SECRET_NOT_REAL_123456789'
    $testGeneration = '0123456789abcdef0123456789abcdef'
    $derived = Get-V213FreeRelayGatewaySecret -HmacSecret $testHmac -Generation $testGeneration
    if ($derived -notmatch '^[0-9a-f]{64}$') { throw 'FREE_RELAY gateway secret derivation failed.' }
    $testRecord = New-V213FreeRelayRouteRecord -PublicUrl 'https://ephemeral-test.trycloudflare.com' -Model 'Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548' -Generation $testGeneration -ConnectedAt ([datetime]::UtcNow.ToString('o'))
    if ([string]$testRecord.tunnel_mode -ne 'quick_free_relay' -or [int]$testRecord.consecutive_health_checks -ne 3) { throw 'FREE_RELAY record contract failed.' }
    if ((Get-BlueGreenDecision $false $true) -ne 'ROLLBACK_NEW_RETAIN_OLD') { throw 'Blue/green rollback self-test failed.' }
    if ((Get-BlueGreenDecision $true $false) -ne 'PROMOTE_NEW_RETAIN_OLD_UNTIL_FINALIZE') { throw 'Blue/green staged cutover self-test failed.' }
    if ((Get-BlueGreenDecision $true $true) -ne 'PROMOTE_NEW_STOP_OLD') { throw 'Blue/green finalize self-test failed.' }
    $namedRoot = Join-Path $env:TEMP ('Investor Intelligence named tunnel bridge policy 測試 (1)-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $namedRoot | Out-Null
    try {
        $credential = Join-Path $namedRoot '12345678-1234-1234-1234-123456789abc.json'
        [IO.File]::WriteAllText($credential, '{"AccountTag":"account-self-test","TunnelID":"12345678-1234-1234-1234-123456789abc","TunnelSecret":"self-test-secret-not-real"}', [Text.UTF8Encoding]::new($false))
        $config = Join-Path $namedRoot 'named config (測試).yml'
        [IO.File]::WriteAllText($config, "tunnel: qwen38-q6-prod`ncredentials-file: $credential`ningress:`n - service: http://127.0.0.1:8814`n", [Text.UTF8Encoding]::new($false))
        try { [void](Resolve-TunnelPolicy 'Named' $false '' '' ''); throw 'Invalid named tunnel policy was accepted.' } catch { if ($_.Exception.Message -eq 'Invalid named tunnel policy was accepted.') { throw } }
        [void](Resolve-TunnelPolicy 'Named' $false 'qwen38-q6-prod' 'qwen38.example.com' $config)
        [void](Get-V213NamedTunnelConfigMetadata -ConfigPath $config -ExpectedLocalPort 8814 -ExpectedTunnelName 'qwen38-q6-prod')
        try { [void](Get-V213NamedTunnelConfigMetadata -ConfigPath $config -ExpectedLocalPort 8815); throw 'Wrong named tunnel local port was accepted.' } catch { if ($_.Exception.Message -eq 'Wrong named tunnel local port was accepted.') { throw } }
        $runtimeConfig = Join-Path $namedRoot 'runtime config (測試).yml'
        [void](New-V213RuntimeNamedTunnelConfig -SourceConfigPath $config -GatewayPort 8815 -DestinationPath $runtimeConfig)
        if ((Get-Content -LiteralPath $runtimeConfig -Raw -Encoding utf8) -notmatch 'http://127\.0\.0\.1:8815') { throw 'Blue/green runtime config did not target the new gateway port.' }
    }
    finally { Remove-Item -LiteralPath $namedRoot -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host 'V213_BRIDGE_STRICTMODE_HEALTH_SELF_TEST = PASS; gateway_process_spaces_unicode_parentheses=true; native_argument_quoting=true; quick_tunnel_test_only=true; free_relay_default=true; free_relay_signed_lease=true; named_tunnel_policy=true; named_tunnel_config_port=true; blue_green_rollback=true' -ForegroundColor Green
    exit 0
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$GatewayScript = Join-Path $ProjectRoot 'scripts\v213_local_llm_gateway.py'
if (-not (Test-Path -LiteralPath $GatewayScript -PathType Leaf)) { throw "Missing $GatewayScript" }
$stateRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
$logRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\logs\v213-local-model'
New-Item -ItemType Directory -Force -Path $stateRoot, $logRoot | Out-Null
$statePath = Join-Path $stateRoot 'v213-local-model.json'
$selectionPath = Join-Path $stateRoot 'v213-model-selection.json'

function Test-Llama {
    param([string]$Base)
    foreach ($suffix in @('/v1/models?reload=1', '/models?reload=1', '/v1/models', '/health')) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri ($Base.TrimEnd('/') + $suffix) -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { return $true }
        }
        catch { }
    }
    return $false
}

function Get-RunningLlamaCandidates {
    $result = New-Object System.Collections.Generic.List[string]
    try {
        $processes = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.ProcessName -match '(?i)llama|localai|kobold'
        })
        foreach ($process in $processes) {
            try {
                $listeners = Get-NetTCPConnection -State Listen -OwningProcess $process.Id -ErrorAction SilentlyContinue
                foreach ($listener in $listeners) {
                    $port = [int]$listener.LocalPort
                    if ($port -gt 0) {
                        $candidate = "http://127.0.0.1:$port"
                        if (-not $result.Contains($candidate)) { $result.Add($candidate) }
                    }
                }
            }
            catch { }
        }
    }
    catch { }
    return @($result)
}

function Read-ModelSelection {
    if (-not (Test-Path -LiteralPath $selectionPath -PathType Leaf)) { return $null }
    try {
        $selection = Get-Content -LiteralPath $selectionPath -Raw -Encoding utf8 | ConvertFrom-Json
        if (-not (Get-ObjectPropertyValue $selection 'model' '')) { return $null }
        return $selection
    }
    catch { return $null }
}

function Resolve-Llama {
    if ($LlamaBaseUrl) {
        if ($LlamaBaseUrl -notmatch '^http://(?:127\.0\.0\.1|localhost):\d{1,5}$') {
            throw 'LlamaBaseUrl must be a loopback HTTP endpoint.'
        }
        if (-not (Test-Llama $LlamaBaseUrl)) { throw "llama.cpp unavailable: $LlamaBaseUrl" }
        return $LlamaBaseUrl.TrimEnd('/')
    }
    $candidates = New-Object System.Collections.Generic.List[string]
    $selection = Read-ModelSelection
    $savedBase = [string](Get-ObjectPropertyValue $selection 'llama_base_url' '')
    if ($savedBase -match '^http://(?:127\.0\.0\.1|localhost):\d{1,5}$') {
        $candidates.Add($savedBase.TrimEnd('/'))
    }
    foreach ($candidate in @(
        'http://127.0.0.1:8080', 'http://127.0.0.1:7905',
        'http://127.0.0.1:14410', 'http://127.0.0.1:8813',
        'http://127.0.0.1:8081', 'http://127.0.0.1:8000'
    )) {
        if (-not $candidates.Contains($candidate)) { $candidates.Add($candidate) }
    }
    foreach ($candidate in @(Get-RunningLlamaCandidates)) {
        if (-not $candidates.Contains($candidate)) { $candidates.Add($candidate) }
    }
    foreach ($candidate in $candidates) {
        if (Test-Llama $candidate) { return $candidate }
    }
    foreach ($starter in @('D:\LocalAI\Start-LocalAI.cmd', 'D:\llama.cpp\Start-LocalAI.cmd')) {
        if (-not (Test-Path -LiteralPath $starter -PathType Leaf)) { continue }
        Write-Host "Starting local llama.cpp stack: $starter" -ForegroundColor Cyan
        Start-Process -FilePath $starter | Out-Null
        $deadline = (Get-Date).AddSeconds(90)
        while ((Get-Date) -lt $deadline) {
            foreach ($candidate in (@(
                'http://127.0.0.1:8080', 'http://127.0.0.1:7905',
                'http://127.0.0.1:14410', 'http://127.0.0.1:8813'
            ) + @(Get-RunningLlamaCandidates) | Select-Object -Unique)) {
                if (Test-Llama $candidate) { return $candidate }
            }
            Start-Sleep -Seconds 2
        }
    }
    throw 'No healthy llama.cpp OpenAI-compatible loopback endpoint was found.'
}

function Get-ModelCatalog {
    param([string]$Base)
    try {
        $payload = Invoke-RestMethod -Method Get -Uri ($Base.TrimEnd('/') + '/models') -Headers @{'cache-control'='no-cache'} -TimeoutSec 15 -MaximumRedirection 0
        $data = @(Get-ObjectPropertyValue $payload 'data' @())
        if ($data.Count -eq 0) { throw 'EMPTY_CATALOG' }
        return $data
    }
    catch { throw 'MODEL_CATALOG_UNAVAILABLE; no_model_substitution=true' }
}

function Invoke-SharedModelIdentity {
    param([string]$Selected, [object[]]$Catalog, $Response = $null, [switch]$VerifyResponse)
    $request = @{ selected=$Selected; catalog=@($Catalog) }
    if ($VerifyResponse) { $request['response']=$Response }
    # ASCII JSON escapes avoid PS5.1 native-pipe codepage loss without changing
    # the user's console encoding. ASCII is also valid UTF-8 for the shared CLI.
    $payload=$request | ConvertTo-Json -Depth 24 -Compress
    $payload=[regex]::Replace($payload,'[^\x00-\x7F]',{param($m) '\u'+([int][char]$m.Value).ToString('x4')})
    $raw=$payload | & $python (Join-Path $ProjectRoot 'scripts/v213_compact_qa_gateway.py') --identity-stdin
    if ($LASTEXITCODE -ne 0) { throw 'MODEL_IDENTITY_PROOF_FAILED' }
    return $raw | ConvertFrom-Json
}

function Resolve-Model {
    param([string]$Base, [string]$Requested)
    $catalog = @(Get-ModelCatalog $Base)
    $ids = @($catalog | ForEach-Object { [string](Get-ObjectPropertyValue $_ 'id' '') })
    $names = @($catalog | ForEach-Object { [string](Get-ObjectPropertyValue $_ 'id' ''); @(Get-ObjectPropertyValue $_ 'aliases' @()) })
    $selection = Read-ModelSelection
    $candidate = ''
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        $candidate = $Requested.Trim()
    }
    else {
        $saved = [string](Get-ObjectPropertyValue $selection 'model' '')
        if (-not [string]::IsNullOrWhiteSpace($saved)) { $candidate = $saved.Trim() }
    }
    if (-not $candidate) {
        $preferred = @($names | Where-Object { $_ -ieq $preferredModel }) | Select-Object -First 1
        if ($preferred) { $candidate = [string]$preferred }
        elseif ($catalog.Count -eq 1) { $candidate = [string]$ids[0] }
        else { throw 'Multiple llama.cpp models are available; explicit selection required.' }
    }
    if ($candidate -notmatch '^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}$') {
        throw 'Selected llama.cpp model ID contains unsupported characters.'
    }
    $proof = Invoke-SharedModelIdentity -Selected $candidate -Catalog $catalog
    return [pscustomobject]@{ model=$candidate; canonical_model=$proof.canonical_model; catalog=$ids; identity_catalog=$catalog }
}

function Test-SelectedModelRoute {
    param([string]$Base, [string]$SelectedModel, [object[]]$Catalog)
    $policy=Get-Content -LiteralPath (Join-Path $ProjectRoot 'config/v213-compact-qa-v1.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $body = [ordered]@{
        model = $SelectedModel
        messages = @(@{ role = 'user'; content = $policy.smoke_prompt })
        temperature = 0
        max_tokens = $policy.smoke_output_tokens
        stream = $false
        chat_template_kwargs = @{ enable_thinking=$policy.compact_request_enable_thinking }
    } | ConvertTo-Json -Depth 6 -Compress
    try {
        $response = Invoke-RestMethod -Method Post -Uri ($Base.TrimEnd('/') + '/v1/chat/completions') -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 300
        $null=Invoke-SharedModelIdentity -Selected $SelectedModel -Catalog $Catalog -Response $response -VerifyResponse
    }
    catch { throw 'MODEL_ROUTING_PROBE_FAILED; complete_exact_identity_and_marker_required=true' }
    Write-Host "II_PROGRESS selected model route verified; model=$SelectedModel" -ForegroundColor Green
}

function Resolve-Python {
    if ($env:PROJECT_PYTHON -and (Test-Path -LiteralPath $env:PROJECT_PYTHON -PathType Leaf)) { return $env:PROJECT_PYTHON }
    foreach ($name in @('python.exe', 'python', 'py.exe', 'py')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    throw 'Python 3 was not found.'
}

function Resolve-Cloudflared {
    $command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command cloudflared -ErrorAction SilentlyContinue }
    if ($command) { return $command.Source }
    if (-not $InstallCloudflared) { throw 'cloudflared is required for the cloud-to-local bridge.' }
    $winget = Get-Command winget.exe -ErrorAction Stop
    & $winget.Source install --id Cloudflare.cloudflared -e --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) { throw 'cloudflared installation failed.' }
    $command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command cloudflared -ErrorAction Stop }
    return $command.Source
}

function Get-PortOwnerPid {
    param([int]$Port)
    try {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($listener) { return [int]$listener.OwningProcess }
    }
    catch { }
    return 0
}

function Stop-RecordedBridge {
    param([object]$OldState)
    if ($null -eq $OldState) { return }
    $gatewayPid = 0
    $tunnelPid = 0
    $heartbeatPid = 0
    $oldPort = 0
    [void][int]::TryParse([string](Get-ObjectPropertyValue $OldState 'gateway_pid' '0'), [ref]$gatewayPid)
    [void][int]::TryParse([string](Get-ObjectPropertyValue $OldState 'cloudflared_pid' '0'), [ref]$tunnelPid)
    [void][int]::TryParse([string](Get-ObjectPropertyValue $OldState 'free_relay_heartbeat_pid' '0'), [ref]$heartbeatPid)
    [void][int]::TryParse([string](Get-ObjectPropertyValue $OldState 'gateway_port' '0'), [ref]$oldPort)
    if ($gatewayPid -gt 0 -and $oldPort -gt 0 -and (Get-PortOwnerPid $oldPort) -eq $gatewayPid) {
        try {
            $process = Get-Process -Id $gatewayPid -ErrorAction Stop
            if ($process.ProcessName -match '(?i)^python') { Stop-Process -Id $gatewayPid -Force -ErrorAction SilentlyContinue }
        }
        catch { }
    }
    if ($heartbeatPid -gt 0) {
        try {
            $process = Get-Process -Id $heartbeatPid -ErrorAction Stop
            if ($process.ProcessName -match '(?i)^powershell$') { Stop-Process -Id $heartbeatPid -Force -ErrorAction SilentlyContinue }
        }
        catch { }
    }
    if ($tunnelPid -gt 0) {
        try {
            $process = Get-Process -Id $tunnelPid -ErrorAction Stop
            if ($process.ProcessName -match '(?i)^cloudflared$') { Stop-Process -Id $tunnelPid -Force -ErrorAction SilentlyContinue }
        }
        catch { }
    }
}

function Resolve-GatewayPort {
    param([int]$Preferred)
    foreach ($port in $Preferred..([Math]::Min(65535, $Preferred + 20))) {
        if ((Get-PortOwnerPid $port) -eq 0) { return $port }
    }
    throw "No free local gateway port was found in range $Preferred-$($Preferred + 20)."
}

function Random-Secret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes)
}

function Wait-LocalGatewayHealth {
    param([int]$Port, [int]$ProcessId, [string]$SelectedModel)
    $deadline = (Get-Date).AddSeconds(35)
    $last = ''
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            throw 'Local gateway exited during startup.'
        }
        try {
            $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$Port/health" -Headers @{'cache-control'='no-cache'} -TimeoutSec 8
            if (Test-HealthModel $health $SelectedModel) { return $health }
            $last = "service=$([string](Get-ObjectPropertyValue $health 'service' '<missing>')); schema=$([string](Get-ObjectPropertyValue $health 'health_schema_version' '<missing>')); selected=$([string](Get-ObjectPropertyValue $health 'selected_model' '<missing>')); available=$([string](Get-ObjectPropertyValue $health 'selected_model_available' '<missing>'))"
        }
        catch { $last = $_.Exception.Message }
        Start-Sleep -Milliseconds 750
    }
    throw "v2.1.3 local gateway health did not verify selected model $SelectedModel. Last observation: $last"
}

function Wait-PublicHealthStable {
    param([string]$Url,[int]$ProcessId,[string]$SelectedModel,[int]$RequiredConsecutive=3)
    $consecutive = 0
    $failures = 0
    $attempts = 0
    $last = ''
    while ($attempts -lt 15 -and $consecutive -lt $RequiredConsecutive) {
        $attempts++
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { throw 'Tunnel exited before stable public health.' }
        try {
            $health = Invoke-RestMethod -Method Get -Uri ($Url.TrimEnd('/') + '/health') -Headers @{'cache-control'='no-cache';'pragma'='no-cache'} -TimeoutSec 12
            if (Test-HealthModel $health $SelectedModel) { $consecutive++; Start-Sleep -Seconds 1; continue }
            $last = 'public health payload did not match exact model'
        }
        catch { $last = $_.Exception.Message }
        $failures++
        $consecutive = 0
        Start-Sleep -Seconds 2
    }
    if ($consecutive -lt $RequiredConsecutive) { throw "Tunnel public health was not stable for $RequiredConsecutive consecutive checks. failures=$failures; last=$last" }
    return [pscustomobject]@{
        consecutive = $consecutive
        transient_failure_count = $failures
        status = $(if ($failures -gt 0) { 'PASS_WITH_TRANSIENT_DNS_FAILURES' } else { 'PASS' })
    }
}

function Start-HealthyQuickTunnel {
    param([string]$CloudflaredPath, [int]$Port, [string]$SelectedModel)
    $last = ''
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Write-Host "II_PROGRESS quick tunnel attempt $attempt/3" -ForegroundColor Cyan
        $stdout = Join-Path $logRoot "cloudflared-attempt-$attempt.stdout.log"
        $stderr = Join-Path $logRoot "cloudflared-attempt-$attempt.stderr.log"
        Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue
        $process = Start-Process -FilePath $CloudflaredPath -ArgumentList @('tunnel', '--url', "http://127.0.0.1:$Port", '--protocol', 'http2', '--no-autoupdate') -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        try {
            $publicUrl = ''
            $deadline = (Get-Date).AddSeconds(45)
            while ((Get-Date) -lt $deadline -and -not $publicUrl) {
                if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) { throw 'cloudflared exited before publishing a URL.' }
                Start-Sleep -Milliseconds 600
                $text = ''
                foreach ($path in @($stdout, $stderr)) {
                    if (Test-Path -LiteralPath $path) { $text += "`n" + (Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue) }
                }
                $match = [regex]::Match($text, 'https://[a-z0-9-]+\.trycloudflare\.com', 'IgnoreCase')
                if ($match.Success) { $publicUrl = $match.Value.TrimEnd('/') }
            }
            if (-not $publicUrl) { throw 'Quick tunnel URL was not produced.' }
            $stability = Wait-PublicHealthStable $publicUrl $process.Id $SelectedModel 3
            return [pscustomobject]@{ process = $process; url = $publicUrl; stability = $stability }
        }
        catch {
            $last = $_.Exception.Message
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
    }
    throw "All quick-tunnel attempts failed. Last observation: $last"
}

function Start-FreeRelayHeartbeat {
    param(
        [string]$ConfigPath,[string]$PublicUrl,[string]$Generation,[string]$SelectedModel,
        [string]$ConnectedAt,[int]$GatewayProcessId,[int]$TunnelProcessId,[string]$BaseUrl,
        [int]$Port,[int]$LeaseTtl,[string]$ActivationFile
    )
    $heartbeatScript = Join-Path $ProjectRoot 'scripts\v213_free_relay_heartbeat.ps1'
    if (-not (Test-Path -LiteralPath $heartbeatScript -PathType Leaf)) { throw 'FREE_RELAY heartbeat script is missing.' }
    $hostCommand = Get-Command powershell.exe -ErrorAction Stop | Select-Object -First 1
    $stdout = Join-Path $logRoot 'free-relay-heartbeat.stdout.log'
    $stderr = Join-Path $logRoot 'free-relay-heartbeat.stderr.log'
    Remove-Item $stdout,$stderr -Force -ErrorAction SilentlyContinue
    return Start-NativeRedirectedProcess $hostCommand.Source '-NoProfile' @(
        '-ExecutionPolicy','Bypass','-File',$heartbeatScript,
        '-ProjectRoot',$ProjectRoot,'-FreeRelayConfigPath',$ConfigPath,
        '-PublicUrl',$PublicUrl,'-RouteGeneration',$Generation,'-Model',$SelectedModel,
        '-ConnectedAt',$ConnectedAt,'-GatewayProcessId',[string]$GatewayProcessId,
        '-TunnelProcessId',[string]$TunnelProcessId,'-LlamaBaseUrl',$BaseUrl,
        '-GatewayPort',[string]$Port,'-LeaseTtlSeconds',[string]$LeaseTtl,'-ActivationFile',$ActivationFile
    ) $stdout $stderr
}

function Start-HealthyNamedTunnel {
    param([string]$CloudflaredPath,[string]$ConfigPath,[string]$Name,[string]$Hostname,[string]$SelectedModel)
    $stdout = Join-Path $logRoot 'cloudflared-named.stdout.log'
    $stderr = Join-Path $logRoot 'cloudflared-named.stderr.log'
    Remove-Item $stdout,$stderr -Force -ErrorAction SilentlyContinue
    $process = Start-NativeRedirectedProcess $CloudflaredPath 'tunnel' @('--config',$ConfigPath,'run',$Name) $stdout $stderr
    try {
        $url = 'https://' + $Hostname
        $stability = Wait-PublicHealthStable $url $process.Id $SelectedModel 3
        return [pscustomobject]@{ process=$process; url=$url; stability=$stability }
    }
    catch {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Named tunnel failed health validation. stderr_tail=$(Get-RedactedLogTail $stderr); stdout_tail=$(Get-RedactedLogTail $stdout); cause=$($_.Exception.Message)"
    }
}

$operationLockScript = Join-Path $ProjectRoot 'scripts\v213_operation_lock.ps1'
if (-not (Test-Path -LiteralPath $operationLockScript -PathType Leaf)) { throw 'R75 operation-lock module is missing.' }
. $operationLockScript
[void](Enter-V213OperationLock -Owner 'model-bridge' -TimeoutSeconds 0)
$oldState = $null
if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    try { $oldState = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json } catch { }
}
if ($StopExisting) { $FinalizeCutover = $true }
$tunnelPolicy = Resolve-TunnelPolicy $TunnelMode $NoTunnel.IsPresent $NamedTunnelName $NamedTunnelHostname $NamedTunnelConfig
$freeRelayConfiguration = $null
$routeGeneration = ''
$routeConnectedAt = ''
if ($tunnelPolicy.mode -eq 'FreeRelay') {
    $freeRelayConfiguration = Get-V213FreeRelayConfig -ConfigPath $FreeRelayConfigPath
    $FreeRelayConfigPath = [string]$freeRelayConfiguration.config_path
    $routeGeneration = New-V213FreeRelayGeneration
    $routeConnectedAt = (Get-Date).ToUniversalTime().ToString('o')
}
$GatewayPort = Resolve-GatewayPort $GatewayPort
$python = Resolve-Python
if ($tunnelPolicy.mode -eq 'FreeRelay' -and [string]::IsNullOrWhiteSpace($LlamaBaseUrl)) { $LlamaBaseUrl='http://127.0.0.1:8080' }
$llama = Resolve-Llama
if ($tunnelPolicy.mode -eq 'FreeRelay' -and [string]::IsNullOrWhiteSpace($Model)) {
    try {
        $activeModels = (Invoke-RestMethod -Uri "$llama/v1/models" -TimeoutSec 5).data
        if ($activeModels -and $activeModels.Count -gt 0) {
            $Model = $activeModels[0].id
        }
    } catch {}
    if ([string]::IsNullOrWhiteSpace($Model)) { $Model = 'Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548' }
}
$modelResolution = Resolve-Model $llama $Model
$Model = [string]$modelResolution.model
$modelCatalog = @($modelResolution.catalog)
if ($tunnelPolicy.mode -eq 'FreeRelay' -and [string]::IsNullOrWhiteSpace($Model)) { throw "FREE_RELAY requires an active model from Router or explicit -Model parameter." }
Test-SelectedModelRoute $llama $Model @($modelResolution.identity_catalog)
$bridgeMaterial = if ($tunnelPolicy.mode -eq 'FreeRelay') { Get-V213FreeRelayGatewaySecret -HmacSecret ([string]$freeRelayConfiguration.hmac_secret) -Generation $routeGeneration } else { Random-Secret }
$oldSecret = $env:II_LOCAL_LLM_SHARED_SECRET
$oldLlama = $env:II_LLAMA_BASE_URL
$oldModel = $env:II_LOCAL_LLM_MODEL
$gateway = $null
$tunnel = $null
$heartbeat = $null
$heartbeatActivationFile = ''
$runtimeNamedConfig = ''
try {
    $env:II_LOCAL_LLM_SHARED_SECRET = $bridgeMaterial
    $env:II_LLAMA_BASE_URL = $llama
    $env:II_LOCAL_LLM_MODEL = $Model
    # FreeRelay pins the exact Pi canonical model; the Worker's usePi path
    # requires the gateway's ii_pi proof, so the gateway must run the Pi backend.
    $env:II_LOCAL_LLM_BACKEND = 'pi'
    $stdout = Join-Path $logRoot 'gateway.stdout.log'
    $stderr = Join-Path $logRoot 'gateway.stderr.log'
    Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue
    $gateway = Start-GatewayNativeProcess $python $GatewayScript @('--host', '127.0.0.1', '--port', [string]$GatewayPort) $stdout $stderr
    [void](Wait-LocalGatewayHealth $GatewayPort $gateway.Id $Model)
    Write-Host "II_PROGRESS local gateway healthy; port=$GatewayPort; model=$Model; health_schema_version=2" -ForegroundColor Green
    $publicUrl = ''
    $tunnelPid = 0
    $tunnelStability = [pscustomobject]@{ consecutive=0; transient_failure_count=0; status='NOT_APPLICABLE' }
    $namedTunnelMetadata = $null
    $namedDnsRouteStatus = ''
    if ($tunnelPolicy.mode -eq 'Named') {
        $cloudflaredPath = Resolve-Cloudflared
        $namedTunnelMetadata = Test-V213NamedTunnelPrerequisites -CloudflaredPath $cloudflaredPath -Name $NamedTunnelName -Hostname $NamedTunnelHostname -ConfigPath $NamedTunnelConfig
        $namedDnsRouteStatus = Invoke-V213NamedTunnelDnsRoute -CloudflaredPath $cloudflaredPath -Name $NamedTunnelName -Hostname $NamedTunnelHostname
        $runtimeNamedConfig = Join-Path $env:TEMP ('ii-v213-named-runtime-' + [guid]::NewGuid().ToString('N') + '.yml')
        [void](New-V213RuntimeNamedTunnelConfig -SourceConfigPath $NamedTunnelConfig -GatewayPort $GatewayPort -DestinationPath $runtimeNamedConfig)
        Assert-V213CloudflaredSuccess (Invoke-V213CloudflaredCommand -CloudflaredPath $cloudflaredPath -Arguments @('tunnel','--config',$runtimeNamedConfig,'ingress','validate') -TimeoutSeconds 45) 'runtime ingress validation'
    }
    if ($tunnelPolicy.mode -in @('QuickTest','FreeRelay')) {
        $healthyTunnel = Start-HealthyQuickTunnel (Resolve-Cloudflared) $GatewayPort $Model
        $tunnel = $healthyTunnel.process
        $publicUrl = [string]$healthyTunnel.url
        $tunnelPid = $tunnel.Id
        $tunnelStability = $healthyTunnel.stability
    }
    elseif ($tunnelPolicy.mode -eq 'Named') {
        $healthyTunnel = Start-HealthyNamedTunnel $cloudflaredPath $runtimeNamedConfig $NamedTunnelName $NamedTunnelHostname $Model
        $tunnel = $healthyTunnel.process
        Remove-Item -LiteralPath $runtimeNamedConfig -Force -ErrorAction SilentlyContinue
        $runtimeNamedConfig = ''
        $publicUrl = [string]$healthyTunnel.url
        $tunnelPid = $tunnel.Id
        $tunnelStability = $healthyTunnel.stability
    }
    $freeRelayRegistration = $null
    if ($tunnelPolicy.mode -eq 'FreeRelay') {
        $record = New-V213FreeRelayRouteRecord -PublicUrl $publicUrl -Model $Model -Generation $routeGeneration -ConnectedAt $routeConnectedAt -LeaseTtlSeconds $FreeRelayLeaseTtlSeconds
        $heartbeatActivationFile = Join-Path $logRoot ("free-relay-heartbeat-$routeGeneration.activate")
        Remove-Item -LiteralPath $heartbeatActivationFile -Force -ErrorAction SilentlyContinue
        $heartbeat = Start-FreeRelayHeartbeat $FreeRelayConfigPath $publicUrl $routeGeneration $Model $routeConnectedAt $gateway.Id $tunnelPid $llama $GatewayPort $FreeRelayLeaseTtlSeconds $heartbeatActivationFile
        Start-Sleep -Milliseconds 500
        if (-not (Get-Process -Id $heartbeat.Id -ErrorAction SilentlyContinue)) { throw 'FREE_RELAY heartbeat monitor failed before route publication.' }
        $freeRelayRegistration = Publish-V213FreeRelayRoute -Configuration $freeRelayConfiguration -Record $record
        New-Item -ItemType File -Path $heartbeatActivationFile -Force | Out-Null
        Write-Host "V213_FREE_RELAY_ROUTE = PASS; model=$Model; generation=$routeGeneration; health_schema_version=2; consecutive=3; lease_expires=$($record.expires_at); stable_entrypoint=$($freeRelayConfiguration.worker_origin)" -ForegroundColor Green
    }
    $protected = ConvertTo-SecureString -String $bridgeMaterial -AsPlainText -Force | ConvertFrom-SecureString
    [ordered]@{
        schema_version = 3
        product_version = '2.1.3'
        model = $Model
        llama_base_url = $llama
        available_models = $modelCatalog
        selected_model_verified = $true
        health_schema_version = 2
        gateway_url = "http://127.0.0.1:$GatewayPort"
        gateway_port = $GatewayPort
        python_executable = $python
        public_url = $publicUrl
        allowed_host = $(if ($publicUrl) { ([uri]$publicUrl).Host } else { '' })
        encrypted_shared_secret = $protected
        gateway_pid = $gateway.Id
        cloudflared_pid = $tunnelPid
        free_relay_heartbeat_pid = $(if ($heartbeat) { $heartbeat.Id } else { 0 })
        tunnel_mode = $(if ($tunnelPolicy.mode -eq 'FreeRelay') { 'quick_free_relay' } else { $tunnelPolicy.mode.ToLowerInvariant().Replace('quicktest','quick_test') })
        tunnel_test_only = [bool]$tunnelPolicy.test_only
        tunnel_production_eligible = [bool]$tunnelPolicy.production_eligible
        tunnel_health_status = [string]$tunnelStability.status
        tunnel_transient_failure_count = [int]$tunnelStability.transient_failure_count
        tunnel_consecutive_health_checks = [int]$tunnelStability.consecutive
        free_relay_worker_origin = $(if ($freeRelayConfiguration) { [string]$freeRelayConfiguration.worker_origin } else { '' })
        free_relay_route_generation = $routeGeneration
        free_relay_connected_at = $routeConnectedAt
        free_relay_lease_expires_at = $(if ($freeRelayRegistration) { [string]$freeRelayRegistration.expires_at } else { '' })
        free_relay_config_path = $(if ($freeRelayConfiguration) { [string]$freeRelayConfiguration.config_path } else { '' })
        free_relay_hmac_plaintext_persisted = $false
        named_tunnel_name = $(if ($namedTunnelMetadata) { [string]$namedTunnelMetadata.named_tunnel_name } else { '' })
        named_tunnel_hostname = $(if ($namedTunnelMetadata) { [string]$namedTunnelMetadata.named_tunnel_hostname } else { '' })
        named_tunnel_config_sha256 = $(if ($namedTunnelMetadata) { [string]$namedTunnelMetadata.named_tunnel_config_sha256 } else { '' })
        named_tunnel_dns_route_status = $namedDnsRouteStatus
        named_tunnel_credentials_file_present = $(if ($namedTunnelMetadata) { [bool]$namedTunnelMetadata.credentials_file_present } else { $false })
        named_tunnel_config_path_persisted = $false
        named_tunnel_credential_file_path_persisted = $false
        blue_green_decision = Get-BlueGreenDecision $true $FinalizeCutover.IsPresent
        previous_gateway_pid = [int](Get-ObjectPropertyValue $oldState 'gateway_pid' 0)
        previous_cloudflared_pid = [int](Get-ObjectPropertyValue $oldState 'cloudflared_pid' 0)
        connected_at = (Get-Date).ToUniversalTime().ToString('o')
        shared_secret_plaintext_persisted = $false
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding utf8
    [ordered]@{
        schema_version = 2
        product_version = '2.1.3'
        model = $Model
        llama_base_url = $llama
        available_models = $modelCatalog
        selected_utc = (Get-Date).ToUniversalTime().ToString('o')
        source = 'verified_bridge'
        preferred_model = $preferredModel
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $selectionPath -Encoding utf8
    if ($FinalizeCutover -and $null -ne $oldState) { Stop-RecordedBridge $oldState }
    Write-Host "V213_LOCAL_MODEL = PASS; model=$Model; llama=$llama; gateway=127.0.0.1:$GatewayPort; selected_model_verified=true; health_schema_version=2; blue_green=$(Get-BlueGreenDecision $true $FinalizeCutover.IsPresent)" -ForegroundColor Green
    if ($publicUrl) {
        $label = if ($tunnelStability.status -eq 'PASS') { 'PASS' } else { [string]$tunnelStability.status }
        Write-Host "V213_LOCAL_MODEL_TUNNEL = $label; host=$(([uri]$publicUrl).Host); model=$Model; mode=$($tunnelPolicy.mode); test_only=$($tunnelPolicy.test_only); transient_failures=$($tunnelStability.transient_failure_count); consecutive=$($tunnelStability.consecutive)" -ForegroundColor Green
    }
}
catch {
    if ($heartbeat) { Stop-Process -Id $heartbeat.Id -Force -ErrorAction SilentlyContinue }
    if ($heartbeatActivationFile) { Remove-Item -LiteralPath $heartbeatActivationFile -Force -ErrorAction SilentlyContinue }
    if ($tunnel) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
    if ($gateway) { Stop-Process -Id $gateway.Id -Force -ErrorAction SilentlyContinue }
    $failure = $_.Exception.Message
    $stderrTail = Get-RedactedLogTail (Join-Path $logRoot 'gateway.stderr.log')
    $stdoutTail = Get-RedactedLogTail (Join-Path $logRoot 'gateway.stdout.log')
    throw "V213_LOCAL_MODEL_BRIDGE_FAILED; cause=$failure; stderr_tail=$stderrTail; stdout_tail=$stdoutTail"
}
finally {
    if ($runtimeNamedConfig) { Remove-Item -LiteralPath $runtimeNamedConfig -Force -ErrorAction SilentlyContinue }
    $env:II_LOCAL_LLM_SHARED_SECRET = $oldSecret
    $env:II_LLAMA_BASE_URL = $oldLlama
    $env:II_LOCAL_LLM_MODEL = $oldModel
    $bridgeMaterial = $null
    $freeRelayConfiguration = $null
    Exit-V213OperationLock
}
