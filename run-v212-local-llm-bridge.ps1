[CmdletBinding()]
param(
    [string]$BaseInstallRoot = '',
    [string]$LlamaBaseUrl = '',
    [int]$GatewayPort = 8814,
    [string]$Model = 'qwen3.8-27b',
    [switch]$InstallCloudflared,
    [switch]$NoDeploy,
    [switch]$StopExisting
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($BaseInstallRoot)) {
    $BaseInstallRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
}
$BaseInstallRoot = [IO.Path]::GetFullPath($BaseInstallRoot)
$StatePath = Join-Path $BaseInstallRoot 'install-state.json'
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw 'Investor Intelligence install-state.json is missing.'
}
$state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
$ApplicationRoot = [string]$state.application_root
$PythonExe = [string]$state.python_executable
$UserConfigRoot = [string]$state.user_config_root
$GatewayScript = Join-Path $ApplicationRoot 'scripts\v212_local_llm_gateway.py'
$ProductionConfig = Join-Path $UserConfigRoot 'wrangler.v211.production.local.toml'
$BridgeConfig = Join-Path $UserConfigRoot 'v212-local-llm.local.json'
$SecContactPath = Join-Path $UserConfigRoot 'sec-contact.local.txt'
$LogRoot = Join-Path $BaseInstallRoot 'logs\v212-local-llm'
$GatewayStdout = Join-Path $LogRoot 'gateway.stdout.log'
$GatewayStderr = Join-Path $LogRoot 'gateway.stderr.log'
$TunnelStdout = Join-Path $LogRoot 'cloudflared.stdout.log'
$TunnelStderr = Join-Path $LogRoot 'cloudflared.stderr.log'

foreach ($path in @($ApplicationRoot, $UserConfigRoot)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Missing directory: $path" }
}
foreach ($path in @($PythonExe, $GatewayScript)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing required file: $path" }
}
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Test-LocalLlama([string]$Base) {
    try {
        $health = Invoke-WebRequest -UseBasicParsing -Uri ($Base.TrimEnd('/') + '/health') -TimeoutSec 4
        if ($health.StatusCode -ge 200 -and $health.StatusCode -lt 300) { return $true }
    } catch {}
    try {
        $models = Invoke-WebRequest -UseBasicParsing -Uri ($Base.TrimEnd('/') + '/v1/models') -TimeoutSec 4
        if ($models.StatusCode -ge 200 -and $models.StatusCode -lt 300) { return $true }
    } catch {}
    return $false
}

function Resolve-LlamaBaseUrl {
    if (-not [string]::IsNullOrWhiteSpace($LlamaBaseUrl)) {
        if ($LlamaBaseUrl -notmatch '^http://(?:127\.0\.0\.1|localhost):\d{2,5}$') {
            throw 'LlamaBaseUrl must be a loopback HTTP endpoint.'
        }
        if (-not (Test-LocalLlama $LlamaBaseUrl)) { throw "llama.cpp is not reachable at $LlamaBaseUrl" }
        return $LlamaBaseUrl.TrimEnd('/')
    }
    foreach ($candidate in @(
        'http://127.0.0.1:8813',
        'http://127.0.0.1:8080',
        'http://127.0.0.1:8081',
        'http://127.0.0.1:8000'
    )) {
        if (Test-LocalLlama $candidate) { return $candidate }
    }
    throw 'No healthy loopback llama.cpp OpenAI-compatible server was found. Start the local model first.'
}

function New-RandomText([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+','-').Replace('/','_')
}

function Get-OrCreateSharedSecret {
    if (Test-Path -LiteralPath $BridgeConfig -PathType Leaf) {
        try {
            $config = Get-Content -LiteralPath $BridgeConfig -Raw -Encoding utf8 | ConvertFrom-Json
            if ([string]$config.schema_version -eq '1' -and $config.encrypted_shared_secret) {
                $secure = ConvertTo-SecureString -String ([string]$config.encrypted_shared_secret)
                $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
                try {
                    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
                    if ($plain.Length -ge 32) { return $plain }
                }
                finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
            }
        } catch {}
    }
    return New-RandomText 32
}

function Read-SecContact {
    if (-not (Test-Path -LiteralPath $SecContactPath -PathType Leaf)) { return '' }
    $secure = ConvertTo-SecureString -String ((Get-Content -LiteralPath $SecContactPath -Raw -Encoding utf8).Trim())
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Stop-RecordedProcesses {
    if (-not (Test-Path -LiteralPath $BridgeConfig -PathType Leaf)) { return }
    try {
        $config = Get-Content -LiteralPath $BridgeConfig -Raw -Encoding utf8 | ConvertFrom-Json
        foreach ($pidValue in @($config.gateway_pid, $config.cloudflared_pid)) {
            $pidNumber = 0
            if ([int]::TryParse([string]$pidValue, [ref]$pidNumber) -and $pidNumber -gt 0) {
                Stop-Process -Id $pidNumber -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
}

function Resolve-Cloudflared {
    $command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if ($null -eq $command) { $command = Get-Command cloudflared -ErrorAction SilentlyContinue }
    if ($null -ne $command) { return $command.Source }
    if (-not $InstallCloudflared) {
        throw 'cloudflared is not installed. Re-run with -InstallCloudflared after reviewing this requirement.'
    }
    $winget = Get-Command winget.exe -ErrorAction Stop
    & $winget.Source install --id Cloudflare.cloudflared -e --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) { throw "cloudflared winget install failed with exit code $LASTEXITCODE" }
    $command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if ($null -eq $command) { $command = Get-Command cloudflared -ErrorAction Stop }
    return $command.Source
}

function Wait-TunnelUrl([int]$ProcessId) {
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { throw 'cloudflared exited before producing a tunnel URL.' }
        $text = ''
        foreach ($path in @($TunnelStdout, $TunnelStderr)) {
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                $text += "`n" + (Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue)
            }
        }
        $match = [regex]::Match($text, 'https://[a-z0-9-]+\.trycloudflare\.com', 'IgnoreCase')
        if ($match.Success) { return $match.Value.TrimEnd('/') }
        Start-Sleep -Milliseconds 750
    }
    throw 'Timed out waiting for the Cloudflare quick-tunnel URL.'
}

function Set-LocalModelVars([string]$ConfigPath, [string]$PublicUrl, [string]$ModelName) {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw "Production Wrangler config missing: $ConfigPath" }
    $text = Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8
    if ($text -notmatch '(?m)^\[vars\]\s*$') { throw 'Wrangler config has no [vars] section.' }
    $hostName = ([uri]$PublicUrl).Host
    foreach ($key in @('LOCAL_LLM_BASE_URL','LOCAL_LLM_ALLOWED_HOSTS','LOCAL_LLM_MODEL')) {
        $text = [regex]::Replace($text, "(?m)^\s*$key\s*=.*(?:\r?\n)?", '')
    }
    $block = "[vars]`r`nLOCAL_LLM_BASE_URL = `"$PublicUrl`"`r`nLOCAL_LLM_ALLOWED_HOSTS = `"$hostName`"`r`nLOCAL_LLM_MODEL = `"$ModelName`""
    $text = [regex]::Replace($text, '(?m)^\[vars\]\s*$', [Text.RegularExpressions.MatchEvaluator]{ param($m) $block }, 1)
    [IO.File]::WriteAllText($ConfigPath, $text, [Text.UTF8Encoding]::new($false))
}

function Invoke-Npx([string[]]$Arguments, [string]$StandardInput = '') {
    $npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
    if ($null -eq $npx) { $npx = Get-Command npx -ErrorAction Stop }
    Push-Location (Join-Path $ApplicationRoot 'cloud')
    try {
        if ($StandardInput) { $output = @($StandardInput | & $npx.Source @Arguments 2>&1) }
        else { $output = @(& $npx.Source @Arguments 2>&1) }
        $code = $LASTEXITCODE
        $output | ForEach-Object { Write-Host ([string]$_) }
        if ($code -ne 0) { throw "npx command failed with exit code $code" }
        return (($output | ForEach-Object { [string]$_ }) -join "`n")
    }
    finally { Pop-Location }
}

$ResolvedLlama = Resolve-LlamaBaseUrl
Write-Host "LOCAL_LLAMA = $ResolvedLlama" -ForegroundColor Green
$CloudflaredExe = Resolve-Cloudflared
if ($StopExisting) { Stop-RecordedProcesses }

$SharedSecret = Get-OrCreateSharedSecret
$SecContact = Read-SecContact
if ($SecContact -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
    throw 'The existing protected SEC Fair Access contact could not be loaded.'
}

$previousSecret = $env:II_LOCAL_LLM_SHARED_SECRET
$previousLlama = $env:II_LLAMA_BASE_URL
$previousModel = $env:II_LOCAL_LLM_MODEL
$previousContact = $env:SEC_CONTACT_EMAIL
try {
    $env:II_LOCAL_LLM_SHARED_SECRET = $SharedSecret
    $env:II_LLAMA_BASE_URL = $ResolvedLlama
    $env:II_LOCAL_LLM_MODEL = $Model
    $env:SEC_CONTACT_EMAIL = $SecContact

    Remove-Item -LiteralPath $GatewayStdout,$GatewayStderr,$TunnelStdout,$TunnelStderr -Force -ErrorAction SilentlyContinue
    $gateway = Start-Process -FilePath $PythonExe -ArgumentList @($GatewayScript,'--host','127.0.0.1','--port',[string]$GatewayPort) `
        -PassThru -WindowStyle Hidden -RedirectStandardOutput $GatewayStdout -RedirectStandardError $GatewayStderr
    Start-Sleep -Seconds 2
    if (-not (Get-Process -Id $gateway.Id -ErrorAction SilentlyContinue)) {
        throw 'Local LLM gateway exited during startup.'
    }
    $gatewayHealth = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$GatewayPort/health" -TimeoutSec 8
    if ($gatewayHealth.ok -ne $true -or $gatewayHealth.llama_reachable -ne $true) {
        throw 'Gateway health did not confirm the local model.'
    }
    Write-Host 'LOCAL_GATEWAY = PASS' -ForegroundColor Green

    $tunnel = Start-Process -FilePath $CloudflaredExe -ArgumentList @('tunnel','--url',"http://127.0.0.1:$GatewayPort",'--no-autoupdate') `
        -PassThru -WindowStyle Hidden -RedirectStandardOutput $TunnelStdout -RedirectStandardError $TunnelStderr
    $PublicUrl = Wait-TunnelUrl $tunnel.Id
    $publicHealth = Invoke-RestMethod -Method Get -Uri "$PublicUrl/health" -TimeoutSec 15
    if ($publicHealth.ok -ne $true -or $publicHealth.llama_reachable -ne $true) { throw 'Public tunnel health failed.' }
    Write-Host "LOCAL_LLM_TUNNEL = PASS; host=$(([uri]$PublicUrl).Host)" -ForegroundColor Green

    if (-not $NoDeploy) {
        if (-not (Test-Path -LiteralPath $ProductionConfig -PathType Leaf)) { throw 'v2.1.1 production Wrangler config is missing.' }
        $backup = $ProductionConfig + '.v212-bridge.bak'
        Copy-Item -LiteralPath $ProductionConfig -Destination $backup -Force
        try {
            Set-LocalModelVars $ProductionConfig $PublicUrl $Model
            [void](Invoke-Npx @('wrangler','secret','put','LOCAL_LLM_SHARED_SECRET','--config',$ProductionConfig) $SharedSecret)
            [void](Invoke-Npx @('wrangler','deploy','--config',$ProductionConfig))
        }
        catch {
            Copy-Item -LiteralPath $backup -Destination $ProductionConfig -Force -ErrorAction SilentlyContinue
            throw
        }
        Write-Host 'WORKER_LOCAL_MODEL_ROUTE = PASS' -ForegroundColor Green
    }

    $encrypted = ConvertFrom-SecureString (ConvertTo-SecureString $SharedSecret -AsPlainText -Force)
    [ordered]@{
        schema_version = 1
        product_version = '2.1.2'
        encrypted_shared_secret = $encrypted
        llama_base_url = $ResolvedLlama
        gateway_port = $GatewayPort
        model = $Model
        public_gateway_host = ([uri]$PublicUrl).Host
        gateway_pid = $gateway.Id
        cloudflared_pid = $tunnel.Id
        updated_at = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $BridgeConfig -Encoding utf8

    Write-Host 'V2.1.2 LOCAL MODEL BRIDGE = PASS' -ForegroundColor Green
    Write-Host 'No local-model shared secret was printed.' -ForegroundColor Green
}
finally {
    $env:II_LOCAL_LLM_SHARED_SECRET = $previousSecret
    $env:II_LLAMA_BASE_URL = $previousLlama
    $env:II_LOCAL_LLM_MODEL = $previousModel
    $env:SEC_CONTACT_EMAIL = $previousContact
    $SharedSecret = $null
    $SecContact = $null
}
