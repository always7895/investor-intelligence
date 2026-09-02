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
$utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8NoBom
$OutputEncoding=$utf8NoBom
$preferredModel='RVN-Q6_K-multilingual-mtp'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$GatewayScript = Join-Path $ProjectRoot 'scripts\v213_local_llm_gateway.py'
if (-not (Test-Path -LiteralPath $GatewayScript -PathType Leaf)) { throw "Missing $GatewayScript" }
$stateRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
$logRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\logs\v213-local-model'
New-Item -ItemType Directory -Force -Path $stateRoot,$logRoot | Out-Null
$statePath=Join-Path $stateRoot 'v213-local-model.json'
$selectionPath=Join-Path $stateRoot 'v213-model-selection.json'

function Test-Llama([string]$Base) {
    foreach ($suffix in @('/v1/models?reload=1','/v1/models','/health')) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri ($Base.TrimEnd('/') + $suffix) -TimeoutSec 4
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) { return $true }
        } catch {}
    }
    return $false
}
function Get-RunningLlamaCandidates {
    $result=New-Object System.Collections.Generic.List[string]
    try{
        $processes=@(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '(?i)llama|localai|kobold' })
        foreach($process in $processes){
            try{
                $listeners=Get-NetTCPConnection -State Listen -OwningProcess $process.Id -ErrorAction SilentlyContinue
                foreach($listener in $listeners){
                    $port=[int]$listener.LocalPort
                    if($port -gt 0){$candidate="http://127.0.0.1:$port";if(-not$result.Contains($candidate)){$result.Add($candidate)}}
                }
            }catch{}
        }
    }catch{}
    return @($result)
}
function Read-ModelSelection {
    if(-not(Test-Path $selectionPath -PathType Leaf)){return $null}
    try{
        $selection=Get-Content $selectionPath -Raw -Encoding utf8|ConvertFrom-Json
        if(-not$selection.model){return $null}
        return $selection
    }catch{return $null}
}
function Resolve-Llama {
    if ($LlamaBaseUrl) {
        if ($LlamaBaseUrl -notmatch '^http://(?:127\.0\.0\.1|localhost):\d{2,5}$') { throw 'LlamaBaseUrl must be loopback HTTP.' }
        if (-not (Test-Llama $LlamaBaseUrl)) { throw "llama.cpp unavailable: $LlamaBaseUrl" }
        return $LlamaBaseUrl.TrimEnd('/')
    }
    $candidates=New-Object System.Collections.Generic.List[string]
    $selection=Read-ModelSelection
    if($selection -and [string]$selection.llama_base_url -match '^http://(?:127\.0\.0\.1|localhost):\d{2,5}$'){
        $candidates.Add(([string]$selection.llama_base_url).TrimEnd('/'))
    }
    foreach($candidate in @(
        'http://127.0.0.1:8080','http://127.0.0.1:7905','http://127.0.0.1:14410',
        'http://127.0.0.1:8813','http://127.0.0.1:8081','http://127.0.0.1:8000'
    )){if(-not$candidates.Contains($candidate)){$candidates.Add($candidate)}}
    foreach($candidate in @(Get-RunningLlamaCandidates)){if(-not$candidates.Contains($candidate)){$candidates.Add($candidate)}}
    foreach ($candidate in $candidates) { if (Test-Llama $candidate) { return $candidate } }

    foreach($starter in @('D:\LocalAI\Start-LocalAI.cmd','D:\llama.cpp\Start-LocalAI.cmd')){
        if (Test-Path -LiteralPath $starter -PathType Leaf) {
            Write-Host "Starting local llama.cpp stack: $starter" -ForegroundColor Cyan
            Start-Process -FilePath $starter | Out-Null
            $deadline=(Get-Date).AddSeconds(90)
            while ((Get-Date) -lt $deadline) {
                $retry=@('http://127.0.0.1:8080','http://127.0.0.1:7905','http://127.0.0.1:14410','http://127.0.0.1:8813') + @(Get-RunningLlamaCandidates)
                foreach ($candidate in ($retry|Select-Object -Unique)) { if (Test-Llama $candidate) { return $candidate } }
                Start-Sleep -Seconds 2
            }
        }
    }
    throw 'No healthy llama.cpp OpenAI-compatible loopback endpoint was found. Start llama-server/OpenCode local model and retry.'
}
function Get-ModelCatalog([string]$Base) {
    $last=''
    foreach($suffix in @('/v1/models?reload=1','/models?reload=1','/v1/models')){
        try{
            $payload=Invoke-RestMethod -Method Get -Uri ($Base.TrimEnd('/')+$suffix) -Headers @{'cache-control'='no-cache'} -TimeoutSec 12
            $ids=@($payload.data|ForEach-Object{[string]$_.id}|Where-Object{$_ -and $_.Trim()}|ForEach-Object{$_.Trim()}|Select-Object -Unique)
            if($ids.Count -gt 0){return $ids}
        }catch{$last=$_.Exception.Message}
    }
    throw "Unable to read the llama.cpp model catalog from $Base. Last observation: $last"
}
function Resolve-Model([string]$Base,[string]$Requested) {
    $catalog=@(Get-ModelCatalog $Base)
    $selection=Read-ModelSelection
    $candidate=''
    if(-not[string]::IsNullOrWhiteSpace($Requested)){$candidate=$Requested.Trim()}
    elseif($selection -and -not[string]::IsNullOrWhiteSpace([string]$selection.model)){$candidate=([string]$selection.model).Trim()}
    else{
        $preferred=@($catalog|Where-Object{$_ -ieq $preferredModel})|Select-Object -First 1
        if($preferred){$candidate=[string]$preferred}
        elseif($catalog.Count -eq 1){$candidate=[string]$catalog[0]}
        else{
            throw ("Multiple llama.cpp models are available, but no explicit model selection exists. Use the EXE model selector first. Available: "+($catalog -join ', '))
        }
    }
    if($candidate -notmatch '^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}$'){
        throw 'The selected llama.cpp model ID contains unsupported characters.'
    }
    $canonical=@($catalog|Where-Object{$_ -ieq $candidate})|Select-Object -First 1
    if(-not$canonical){
        throw ("Selected llama.cpp model is not present in the current router catalog: $candidate. Available: "+($catalog -join ', '))
    }
    return [pscustomobject]@{model=[string]$canonical;catalog=$catalog}
}
function Test-SelectedModelRoute([string]$Base,[string]$SelectedModel) {
    $body=[ordered]@{
        model=$SelectedModel
        messages=@(@{role='user';content='Reply with OK.'})
        temperature=0
        max_tokens=4
        stream=$false
    }|ConvertTo-Json -Depth 6 -Compress
    try{
        $response=Invoke-RestMethod -Method Post -Uri ($Base.TrimEnd('/')+'/v1/chat/completions') -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 300
        if(-not$response){throw 'empty response'}
    }catch{
        throw "Selected llama.cpp model could not complete a minimal routing probe: $SelectedModel. $($_.Exception.Message)"
    }
    Write-Host "II_PROGRESS selected model route verified; model=$SelectedModel" -ForegroundColor Green
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
function Stop-RecordedBridge([object]$OldState) {
    $gatewayPid=0;$tunnelPid=0;$oldPort=$GatewayPort
    [void][int]::TryParse([string]$OldState.gateway_pid,[ref]$gatewayPid)
    [void][int]::TryParse([string]$OldState.cloudflared_pid,[ref]$tunnelPid)
    if($OldState.gateway_port){[void][int]::TryParse([string]$OldState.gateway_port,[ref]$oldPort)}
    if($gatewayPid -gt 0){
        try{
            $process=Get-Process -Id $gatewayPid -ErrorAction Stop
            $ownsPort=$false
            try{$ownsPort=@(Get-NetTCPConnection -State Listen -LocalPort $oldPort -OwningProcess $gatewayPid -ErrorAction SilentlyContinue).Count -gt 0}catch{}
            if($process.ProcessName -match '(?i)^python' -and $ownsPort){Stop-Process -Id $gatewayPid -Force -ErrorAction SilentlyContinue}
        }catch{}
    }
    if($tunnelPid -gt 0){
        try{$process=Get-Process -Id $tunnelPid -ErrorAction Stop;if($process.ProcessName -match '(?i)^cloudflared$'){Stop-Process -Id $tunnelPid -Force -ErrorAction SilentlyContinue}}catch{}
    }
}
function Test-HealthModel([object]$Health,[string]$SelectedModel){
    return ($Health.ok -eq $true -and $Health.llama_reachable -eq $true -and $Health.selected_model_available -eq $true -and [string]$Health.selected_model -ieq $SelectedModel)
}
function Wait-PublicHealth([string]$Url,[int]$ProcessId,[string]$SelectedModel,[int]$Seconds=35){
    $deadline=(Get-Date).AddSeconds($Seconds);$last='';$hostName=([uri]$Url).Host
    while((Get-Date)-lt$deadline){
        if(-not(Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)){throw 'cloudflared exited before public health succeeded.'}
        try{
            $health=Invoke-RestMethod -Method Get -Uri ($Url.TrimEnd('/')+'/health') -Headers @{'cache-control'='no-cache';'pragma'='no-cache'} -TimeoutSec 12
            if(Test-HealthModel $health $SelectedModel){return $health}
            $last="ok=$($health.ok); llama_reachable=$($health.llama_reachable); selected_model=$($health.selected_model); available=$($health.selected_model_available)"
        }catch{
            $last=$_.Exception.Message
            try{
                $resolver=Get-Command Resolve-DnsName -ErrorAction SilentlyContinue
                $curl=Get-Command curl.exe -ErrorAction SilentlyContinue
                if($resolver -and $curl){
                    $answer=Resolve-DnsName -Name $hostName -Type A -Server 1.1.1.1 -DnsOnly -ErrorAction Stop |
                        Where-Object { $_.Type -eq 'A' -and $_.IPAddress } | Select-Object -First 1
                    if($answer){
                        $resolveArg='{0}:443:{1}' -f $hostName,[string]$answer.IPAddress
                        $curlOutput=@(& $curl.Source '--silent' '--show-error' '--fail' '--max-time' '10' '--resolve' $resolveArg ($Url.TrimEnd('/')+'/health') 2>&1)
                        if($LASTEXITCODE -eq 0){
                            $curlHealth=(($curlOutput|ForEach-Object{[string]$_})-join"`n")|ConvertFrom-Json
                            if(Test-HealthModel $curlHealth $SelectedModel){
                                Write-Host 'QUICK_TUNNEL_HEALTH = PASS; dns=1.1.1.1; selected_model_verified=true' -ForegroundColor Green
                                return $curlHealth
                            }
                        }
                    }
                }
            }catch{}
        }
        Start-Sleep -Seconds 2
    }
    throw "Quick tunnel public health timed out for selected model $SelectedModel. Last observation: $last"
}
function Start-HealthyQuickTunnel([string]$CloudflaredPath,[int]$Port,[string]$LogRoot,[string]$SelectedModel){
    $last=''
    for($attempt=1;$attempt -le 3;$attempt++){
        Write-Host "II_PROGRESS quick tunnel attempt $attempt/3" -ForegroundColor Cyan
        $tout=Join-Path $LogRoot ("cloudflared-attempt-$attempt.stdout.log")
        $terr=Join-Path $LogRoot ("cloudflared-attempt-$attempt.stderr.log")
        Remove-Item $tout,$terr -Force -ErrorAction SilentlyContinue
        $process=Start-Process -FilePath $CloudflaredPath -ArgumentList @('tunnel','--url',"http://127.0.0.1:$Port",'--protocol','http2','--no-autoupdate') -PassThru -WindowStyle Hidden -RedirectStandardOutput $tout -RedirectStandardError $terr
        try{
            $publicUrl='';$deadline=(Get-Date).AddSeconds(40)
            while((Get-Date)-lt$deadline -and -not$publicUrl){
                if(-not(Get-Process -Id $process.Id -ErrorAction SilentlyContinue)){throw 'cloudflared exited before publishing a quick-tunnel URL.'}
                Start-Sleep -Milliseconds 600
                $text=''
                foreach($path in @($tout,$terr)){if(Test-Path $path){$text+="`n"+(Get-Content $path -Raw -ErrorAction SilentlyContinue)}}
                $match=[regex]::Match($text,'https://[a-z0-9-]+\.trycloudflare\.com','IgnoreCase')
                if($match.Success){$publicUrl=$match.Value.TrimEnd('/')}
            }
            if(-not$publicUrl){throw 'Quick tunnel URL was not produced.'}
            [void](Wait-PublicHealth $publicUrl $process.Id $SelectedModel 35)
            return [pscustomobject]@{process=$process;url=$publicUrl;stdout=$tout;stderr=$terr}
        }catch{
            $last=$_.Exception.Message
            Write-Warning ("Quick tunnel attempt $attempt failed: $last")
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
    }
    throw "All quick-tunnel attempts failed. Last observation: $last"
}

if ($StopExisting -and (Test-Path -LiteralPath $statePath)) {
    try { Stop-RecordedBridge (Get-Content $statePath -Raw -Encoding utf8 | ConvertFrom-Json) } catch {}
}

$llama=Resolve-Llama
$modelResolution=Resolve-Model $llama $Model
$Model=[string]$modelResolution.model
$modelCatalog=@($modelResolution.catalog)
Test-SelectedModelRoute $llama $Model
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
$oldSecret=$env:II_LOCAL_LLM_SHARED_SECRET;$oldLlama=$env:II_LLAMA_BASE_URL;$oldModel=$env:II_LOCAL_LLM_MODEL;$oldContact=$env:SEC_CONTACT_EMAIL
$gateway=$null;$tunnel=$null
try {
    $env:II_LOCAL_LLM_SHARED_SECRET=$secret;$env:II_LLAMA_BASE_URL=$llama;$env:II_LOCAL_LLM_MODEL=$Model
    if($secContact){$env:SEC_CONTACT_EMAIL=$secContact}
    $stdout=Join-Path $logRoot 'gateway.stdout.log';$stderr=Join-Path $logRoot 'gateway.stderr.log'
    Remove-Item $stdout,$stderr -Force -ErrorAction SilentlyContinue
    $gateway=Start-Process -FilePath $python -ArgumentList @($GatewayScript,'--host','127.0.0.1','--port',[string]$GatewayPort) -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Start-Sleep -Seconds 2
    if(-not(Get-Process -Id $gateway.Id -ErrorAction SilentlyContinue)){throw 'Local gateway exited during startup.'}
    $health=Invoke-RestMethod -Uri "http://127.0.0.1:$GatewayPort/health" -Headers @{'cache-control'='no-cache'} -TimeoutSec 15
    if(-not(Test-HealthModel $health $Model)){throw "v2.1.3 local gateway health did not verify selected model $Model."}
    Write-Host "II_PROGRESS local gateway healthy; llama=$llama; model=$Model; selected_model_verified=true" -ForegroundColor Green

    $publicUrl='';$tunnelPid=0
    if (-not $NoTunnel) {
        $cloudflaredPath=Resolve-Cloudflared
        $healthy=Start-HealthyQuickTunnel $cloudflaredPath $GatewayPort $logRoot $Model
        $tunnel=$healthy.process
        $publicUrl=[string]$healthy.url
        $tunnelPid=$tunnel.Id
    }

    $protected = ConvertTo-SecureString -String $secret -AsPlainText -Force | ConvertFrom-SecureString
    [ordered]@{
        schema_version=2;product_version='2.1.3';model=$Model;llama_base_url=$llama
        available_models=$modelCatalog;selected_model_verified=$true
        gateway_url="http://127.0.0.1:$GatewayPort";gateway_port=$GatewayPort;python_executable=$python
        public_url=$publicUrl;allowed_host=$(if($publicUrl){([uri]$publicUrl).Host}else{''})
        encrypted_shared_secret=$protected;gateway_pid=$gateway.Id;cloudflared_pid=$tunnelPid
        connected_at=(Get-Date).ToUniversalTime().ToString('o');shared_secret_plaintext_persisted=$false
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath -Encoding utf8
    [ordered]@{
        schema_version=1;product_version='2.1.3';model=$Model;llama_base_url=$llama
        available_models=$modelCatalog;selected_utc=(Get-Date).ToUniversalTime().ToString('o')
        source='verified_bridge';preferred_model=$preferredModel
    }|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $selectionPath -Encoding utf8
    Write-Host "V213_LOCAL_MODEL = PASS; model=$Model; llama=$llama; gateway=127.0.0.1:$GatewayPort; selected_model_verified=true" -ForegroundColor Green
    if($publicUrl){ Write-Host "V213_LOCAL_MODEL_TUNNEL = PASS; host=$(([uri]$publicUrl).Host); model=$Model" -ForegroundColor Green }
}
catch{
    if($tunnel){Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue}
    if($gateway){Stop-Process -Id $gateway.Id -Force -ErrorAction SilentlyContinue}
    throw
}
finally {
    $env:II_LOCAL_LLM_SHARED_SECRET=$oldSecret;$env:II_LLAMA_BASE_URL=$oldLlama;$env:II_LOCAL_LLM_MODEL=$oldModel;$env:SEC_CONTACT_EMAIL=$oldContact
    $secret=$null;$secContact=$null
}