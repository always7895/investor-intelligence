[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$LlamaBaseUrl = '',
    [int]$GatewayPort = 8814,
    [string]$Model = '',
    [switch]$NoTunnel,
    [switch]$InstallCloudflared,
    [switch]$StopExisting
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$GatewayScript = Join-Path $ProjectRoot 'scripts\v213_local_llm_gateway.py'
if (-not (Test-Path -LiteralPath $GatewayScript -PathType Leaf)) { throw "Missing $GatewayScript" }

function Test-Llama([string]$Base) {
    foreach ($suffix in @('/health','/v1/models')) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri ($Base.TrimEnd('/') + $suffix) -TimeoutSec 4
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) { return $true }
        } catch {}
    }
    return $false
}
function Resolve-Llama {
    if ($LlamaBaseUrl) {
        if ($LlamaBaseUrl -notmatch '^http://(?:127\.0\.0\.1|localhost):\d{2,5}$') { throw 'LlamaBaseUrl must be loopback HTTP.' }
        if (-not (Test-Llama $LlamaBaseUrl)) { throw "llama.cpp unavailable: $LlamaBaseUrl" }
        return $LlamaBaseUrl.TrimEnd('/')
    }
    foreach ($candidate in @(
        'http://127.0.0.1:8080',
        'http://127.0.0.1:7905',
        'http://127.0.0.1:14410',
        'http://127.0.0.1:8813',
        'http://127.0.0.1:8081'
    )) { if (Test-Llama $candidate) { return $candidate } }

    $starter = 'D:\LocalAI\Start-LocalAI.cmd'
    if (Test-Path -LiteralPath $starter -PathType Leaf) {
        Write-Host 'Starting local llama.cpp stack...' -ForegroundColor Cyan
        Start-Process -FilePath $starter | Out-Null
        $deadline=(Get-Date).AddSeconds(90)
        while ((Get-Date) -lt $deadline) {
            foreach ($candidate in @('http://127.0.0.1:8080','http://127.0.0.1:7905','http://127.0.0.1:14410','http://127.0.0.1:8813')) {
                if (Test-Llama $candidate) { return $candidate }
            }
            Start-Sleep -Seconds 2
        }
    }
    throw 'No healthy llama.cpp OpenAI-compatible loopback endpoint was found.'
}

function Resolve-Model([string]$Base,[string]$Requested) {
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { return $Requested.Trim() }
    try {
        $models = Invoke-RestMethod -Method Get -Uri ($Base.TrimEnd('/') + '/v1/models') -TimeoutSec 8
        $candidate = @($models.data | ForEach-Object { [string]$_.id } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) | Select-Object -First 1
        if ($candidate) { return [string]$candidate }
    } catch {}
    return 'qwen3.8-27b'
}
function Resolve-Cloudflared {
    $command=Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if(-not $command){$command=Get-Command cloudflared -ErrorAction SilentlyContinue}
    if($command){return $command.Source}
    if(-not $InstallCloudflared){throw 'cloudflared is required for the cloud-to-local model bridge. Re-run with -InstallCloudflared.'}
    $winget=Get-Command winget.exe -ErrorAction Stop
    & $winget.Source install --id Cloudflare.cloudflared -e --accept-package-agreements --accept-source-agreements --silent
    if($LASTEXITCODE -ne 0){throw 'cloudflared installation failed.'}
    $command=Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if(-not $command){$command=Get-Command cloudflared -ErrorAction Stop}
    return $command.Source
}

function Resolve-Python {
    if ($env:PROJECT_PYTHON -and (Test-Path -LiteralPath $env:PROJECT_PYTHON)) { return $env:PROJECT_PYTHON }
    foreach ($name in @('python.exe','python','py.exe','py')) {
        $cmd=Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    throw 'Python 3 was not found.'
}
function Random-Secret {
    $b=New-Object byte[] 32
    $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($b) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($b)
}

$stateRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
$logRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\logs\v213-local-model'
New-Item -ItemType Directory -Force -Path $stateRoot,$logRoot | Out-Null
$statePath=Join-Path $stateRoot 'v213-local-model.json'
if ($StopExisting -and (Test-Path -LiteralPath $statePath)) {
    try {
        $old=Get-Content $statePath -Raw -Encoding utf8 | ConvertFrom-Json
        foreach($p in @($old.gateway_pid,$old.cloudflared_pid)) {
            if ($p) { Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue }
        }
    } catch {}
}

$llama=Resolve-Llama
$Model=Resolve-Model $llama $Model
$python=Resolve-Python
$secret=Random-Secret
$secContact=''
$secPath=Join-Path $stateRoot 'sec-contact.local.txt'
if(Test-Path $secPath -PathType Leaf){
    try{
        $secureContact=ConvertTo-SecureString -String ((Get-Content $secPath -Raw -Encoding utf8).Trim())
        $cp=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureContact)
        try{$secContact=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($cp)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($cp)}
    }catch{}
}
$oldSecret=$env:II_LOCAL_LLM_SHARED_SECRET
$oldLlama=$env:II_LLAMA_BASE_URL
$oldModel=$env:II_LOCAL_LLM_MODEL
$oldContact=$env:SEC_CONTACT_EMAIL
try {
    $env:II_LOCAL_LLM_SHARED_SECRET=$secret
    $env:II_LLAMA_BASE_URL=$llama
    $env:II_LOCAL_LLM_MODEL=$Model
    if($secContact){$env:SEC_CONTACT_EMAIL=$secContact}
    $stdout=Join-Path $logRoot 'gateway.stdout.log'
    $stderr=Join-Path $logRoot 'gateway.stderr.log'
    Remove-Item $stdout,$stderr -Force -ErrorAction SilentlyContinue
    $gateway=Start-Process -FilePath $python -ArgumentList @($GatewayScript,'--host','127.0.0.1','--port',[string]$GatewayPort) -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Start-Sleep -Seconds 2
    $health=Invoke-RestMethod -Uri "http://127.0.0.1:$GatewayPort/health" -TimeoutSec 10
    if ($health.ok -ne $true -or $health.llama_reachable -ne $true) { throw 'v2.1.3 local gateway health failed.' }

    $publicUrl=''
    $tunnelPid=0
    if (-not $NoTunnel) {
        $cloudflaredPath=Resolve-Cloudflared
        $tout=Join-Path $logRoot 'cloudflared.stdout.log'
        $terr=Join-Path $logRoot 'cloudflared.stderr.log'
        Remove-Item $tout,$terr -Force -ErrorAction SilentlyContinue
        $tunnel=Start-Process -FilePath $cloudflaredPath -ArgumentList @('tunnel','--url',"http://127.0.0.1:$GatewayPort",'--no-autoupdate') -PassThru -WindowStyle Hidden -RedirectStandardOutput $tout -RedirectStandardError $terr
        $tunnelPid=$tunnel.Id
        $deadline=(Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline -and -not $publicUrl) {
            Start-Sleep -Milliseconds 750
            $text=''
            foreach($p in @($tout,$terr)){ if(Test-Path $p){$text+="`n"+(Get-Content $p -Raw -ErrorAction SilentlyContinue)}}
            $m=[regex]::Match($text,'https://[a-z0-9-]+\.trycloudflare\.com','IgnoreCase')
            if($m.Success){$publicUrl=$m.Value.TrimEnd('/')}
        }
        if(-not $publicUrl){ throw 'Quick tunnel URL was not produced.' }
    }

    # Store the shared secret only as a Windows DPAPI-protected value.
    $protected = ConvertTo-SecureString -String $secret -AsPlainText -Force | ConvertFrom-SecureString
    [ordered]@{
        schema_version=1
        product_version='2.1.3'
        model=$Model
        llama_base_url=$llama
        gateway_url="http://127.0.0.1:$GatewayPort"
        public_url=$publicUrl
        allowed_host= $(if($publicUrl){([uri]$publicUrl).Host}else{''})
        encrypted_shared_secret=$protected
        gateway_pid=$gateway.Id
        cloudflared_pid=$tunnelPid
        connected_at=(Get-Date).ToUniversalTime().ToString('o')
        shared_secret_plaintext_persisted=$false
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding utf8

    Write-Host "V213_LOCAL_MODEL = PASS; model=$Model; llama=$llama; gateway=127.0.0.1:$GatewayPort" -ForegroundColor Green
    if($publicUrl){ Write-Host "V213_LOCAL_MODEL_TUNNEL = PASS; host=$(([uri]$publicUrl).Host)" -ForegroundColor Green }
}
finally {
    $env:II_LOCAL_LLM_SHARED_SECRET=$oldSecret
    $env:II_LLAMA_BASE_URL=$oldLlama
    $env:II_LOCAL_LLM_MODEL=$oldModel
    $env:SEC_CONTACT_EMAIL=$oldContact
    $secret=$null
    $secContact=$null
}
