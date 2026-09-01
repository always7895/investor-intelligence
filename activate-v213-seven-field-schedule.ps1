[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [ValidateSet('zh-TW','en','bilingual')][string]$FieldLocale = 'zh-TW',
    [switch]$ConfirmActivation,
    [switch]$RequireLocalModel
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
if(-not $ConfirmActivation){ throw 'Formal scheduled activation requires -ConfirmActivation.' }
if([string]::IsNullOrWhiteSpace($ProjectRoot)){ $ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$CloudRoot=Join-Path $ProjectRoot 'cloud'
$ReportPath=Join-Path $ProjectRoot 'data\cache\v213_top20_report_public_latest.json'
if(-not(Test-Path $ReportPath -PathType Leaf)){throw 'Build the v2.1.3 seven-field report before activation.'}
$report=Get-Content $ReportPath -Raw -Encoding utf8|ConvertFrom-Json
if([string]$report.product_version -ne '2.1.3' -or @($report.records).Count -ne 20){throw 'The local v2.1.3 report failed the activation preflight.'}
$reportTime=[DateTimeOffset]::MinValue
if(-not [DateTimeOffset]::TryParse([string]$report.generated_at,[ref]$reportTime)){throw 'The v2.1.3 report generated_at value is invalid.'}
$reportAge=([DateTimeOffset]::UtcNow-$reportTime.ToUniversalTime()).TotalSeconds
if($reportAge -lt -300 -or $reportAge -gt 7200){throw "The v2.1.3 report is outside the 2-hour activation freshness gate (age_seconds=$([Math]::Round($reportAge))). Refresh first."}

function Capture([string]$Exe,[string[]]$Args,[string]$Cwd,[string]$InputText=''){
    $old=Get-Location
    try{
        Set-Location $Cwd
        if($InputText){$o=@($InputText|& $Exe @Args 2>&1)}else{$o=@(& $Exe @Args 2>&1)}
        $c=$LASTEXITCODE
        $text=($o|ForEach-Object{[string]$_})-join"`n"
        if($c-ne0){$tail=($o|Select-Object -Last 20|ForEach-Object{[string]$_})-join"`n";throw "$Exe failed with exit code $c`n$tail"}
        return $text
    }finally{Set-Location $old}
}
function Run([string]$Exe,[string[]]$Args,[string]$Cwd,[string]$InputText=''){$x=Capture $Exe $Args $Cwd $InputText;if($x){Write-Host $x};return $x}
function Parse-JsonOutput([string]$Raw){
    $v=$Raw.Trim();try{return($v|ConvertFrom-Json)}catch{}
    $s=@($v.IndexOf('{'),$v.IndexOf('['))|Where-Object{$_-ge0}|Sort-Object|Select-Object -First 1
    if($null-eq$s){throw 'Wrangler JSON output missing.'}
    $e=[Math]::Max($v.LastIndexOf('}'),$v.LastIndexOf(']'))
    if($e-le$s){throw 'Wrangler JSON output truncated.'}
    $v.Substring([int]$s,$e-[int]$s+1)|ConvertFrom-Json
}
function Get-SingleActiveVersion([string]$Raw){
    $root=Parse-JsonOutput $Raw
    $pairs=New-Object System.Collections.Generic.List[object]
    function Visit($n){
        if($null-eq$n -or $n-is[string] -or $n-is[ValueType]){return}
        if($n-is[System.Collections.IEnumerable] -and -not($n-is[pscustomobject])){foreach($x in $n){Visit $x};return}
        $props=@($n.PSObject.Properties);if($props.Count-eq0){return}
        $ver=$null
        foreach($name in @('version_id','versionId','version','id')){$p=$props|Where-Object{$_.Name-eq$name}|Select-Object -First 1;if($p -and [string]$p.Value -match '^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}$'){$ver=([string]$p.Value).ToLowerInvariant();break}}
        $pct=$null
        foreach($name in @('percentage','percent','traffic_percentage','trafficPercentage')){$p=$props|Where-Object{$_.Name-eq$name}|Select-Object -First 1;if($p){try{$pct=[double]$p.Value}catch{};if($null-ne$pct){break}}}
        if($ver -and $null-ne$pct){$pairs.Add([pscustomobject]@{version=$ver;percentage=$pct})}
        foreach($p in $props){Visit $p.Value}
    }
    Visit $root
    $valid=@($pairs|Where-Object{($_.percentage-ge99.999-and$_.percentage-le100.001)-or($_.percentage-ge.99999-and$_.percentage-le1.00001)})
    $versions=@($valid.version|Select-Object -Unique)
    if($versions.Count-ne1){throw "Expected exactly one 100% active Worker version; found $($versions.Count)."}
    [string]$versions[0]
}
function Set-Var([string]$Text,[string]$Key,[string]$Value){
    $Text=[regex]::Replace($Text,"(?m)^\s*$Key\s*=.*(?:\r?\n)?",'')
    $escaped=$Value.Replace('\','\\').Replace('"','\"')
    [regex]::Replace($Text,'(?m)^\[vars\]\s*$',"[vars]`r`n$Key = `"$escaped`"",1)
}
function Remove-Var([string]$Text,[string]$Key){ return [regex]::Replace($Text,"(?m)^\s*$Key\s*=.*(?:\r?\n)?",'') }
function Get-HealthyModelState([string]$Path){
    if(-not(Test-Path $Path -PathType Leaf)){return $null}
    try{
        $m=Get-Content $Path -Raw -Encoding utf8|ConvertFrom-Json
        if(-not$m.public_url -or -not$m.allowed_host -or -not$m.model -or -not$m.encrypted_shared_secret){return $null}
        $connected=[DateTimeOffset]::MinValue
        if(-not[DateTimeOffset]::TryParse([string]$m.connected_at,[ref]$connected)){return $null}
        $age=([DateTimeOffset]::UtcNow-$connected.ToUniversalTime()).TotalMinutes
        if($age -lt -5 -or $age -gt 30){return $null}
        $health=Invoke-RestMethod -Method Get -Uri (([string]$m.public_url).TrimEnd('/')+'/health') -Headers @{'cache-control'='no-cache'} -TimeoutSec 12
        if($health.ok -ne $true -or $health.llama_reachable -ne $true){return $null}
        return $m
    }catch{return $null}
}

& (Join-Path $ProjectRoot 'scripts\resolve_node.ps1') -MinimumVersion '22.0.0'
$npm=if($env:PROJECT_NPM){$env:PROJECT_NPM}else{(Get-Command npm.cmd -ErrorAction Stop).Source}
Push-Location $CloudRoot
try{
    & $npm ci --ignore-scripts --no-audit --no-fund
    if($LASTEXITCODE-ne0){throw 'Hash-locked cloud npm ci failed.'}
}finally{Pop-Location}
$wrangler=Join-Path $CloudRoot 'node_modules\.bin\wrangler.cmd'
if(-not(Test-Path $wrangler -PathType Leaf)){throw 'Pinned Wrangler executable is unavailable after npm ci.'}

$configRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
$productionConfig=@(
    (Join-Path $configRoot 'wrangler.v213.production.local.toml'),
    (Join-Path $configRoot 'wrangler.v211.production.local.toml'),
    (Join-Path $configRoot 'wrangler.v21.production.local.toml')
)|Where-Object{Test-Path $_ -PathType Leaf}|Select-Object -First 1
if(-not$productionConfig){throw 'Installed Production Wrangler config was not found.'}

$modelState=Join-Path $configRoot 'v213-local-model.json'
$healthyModel=Get-HealthyModelState $modelState
if($RequireLocalModel -and -not $healthyModel){
    throw 'Formal activation requires a fresh healthy local-model bridge, but its public tunnel health check did not pass. Production was not changed.'
}

$temp=Join-Path $CloudRoot ('.wrangler.v213.activation.'+[guid]::NewGuid().ToString('N')+'.toml')
$text=Get-Content $productionConfig -Raw -Encoding utf8
$text=[regex]::Replace($text,'(?m)^\s*main\s*=.*$','main = "src/v213/production-worker.ts"',1)
$text=Set-Var $text 'V213_FIELD_LOCALE' $FieldLocale
if($healthyModel){
    $text=Set-Var $text 'LOCAL_LLM_BASE_URL' ([string]$healthyModel.public_url)
    $text=Set-Var $text 'LOCAL_LLM_ALLOWED_HOSTS' ([string]$healthyModel.allowed_host)
    $text=Set-Var $text 'LOCAL_LLM_MODEL' ([string]$healthyModel.model)
    Write-Host "V213_LOCAL_MODEL_ROUTE_PREFLIGHT = PASS; host=$($healthyModel.allowed_host)" -ForegroundColor Green
}else{
    foreach($key in @('LOCAL_LLM_BASE_URL','LOCAL_LLM_ALLOWED_HOSTS','LOCAL_LLM_MODEL')){$text=Remove-Var $text $key}
    Write-Warning 'No fresh healthy v2.1.3 local-model tunnel is available; deterministic/public research can activate but open-ended local-model generation will fail closed.'
}
[IO.File]::WriteAllText($temp,$text,[Text.UTF8Encoding]::new($false))
$prior=''
$deployed=$false
try{
    $prior=Get-SingleActiveVersion (Capture $wrangler @('deployments','status','--json','--config',$temp) $CloudRoot)
    Write-Host "V213_ACTIVATION_PRIOR_VERSION = $prior" -ForegroundColor Cyan
    if($healthyModel){
        $secure=ConvertTo-SecureString -String ([string]$healthyModel.encrypted_shared_secret)
        $sp=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $shared=''
        try{
            $shared=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($sp)
            [void](Run $wrangler @('secret','put','LOCAL_LLM_SHARED_SECRET','--config',$temp) $CloudRoot $shared)
            $deployed=$true
        }finally{
            if($sp-ne[IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($sp)}
            $shared=$null
        }
    }
    [void](Run $wrangler @('deploy','--config',$temp,'--message','v2.1.3 bilingual seven-field scheduled activation') $CloudRoot)
    $deployed=$true
    $current=Get-SingleActiveVersion (Capture $wrangler @('deployments','status','--json','--config',$temp) $CloudRoot)
    if($current-eq$prior){throw 'Deployment did not produce a new active Worker version.'}

    & (Join-Path $ProjectRoot 'sync-v213-top20-report.ps1') -ProjectRoot $ProjectRoot
    & (Join-Path $ProjectRoot 'install-v213-runtime.ps1') -ProjectRoot $ProjectRoot
    $stableRuntime=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime'
    & (Join-Path $ProjectRoot 'register-v213-refresh-tasks.ps1') -RuntimeRoot $stableRuntime

    $installedCopy=Join-Path $configRoot 'wrangler.v213.production.local.toml'
    Copy-Item $temp $installedCopy -Force
    [ordered]@{
        schema_version=1;status='PASS';product_version='2.1.3'
        activated_utc=(Get-Date).ToUniversalTime().ToString('o')
        prior_worker_version=$prior;active_worker_version=$current
        scheduled_times=@('08:00 Asia/Taipei','21:00 Asia/Taipei')
        local_refresh_times=@('07:20','20:20')
        scheduled_format='v213_seven_fields';field_locale=$FieldLocale
        runtime_root=$stableRuntime
        local_model_route= $(if($healthyModel){'HEALTHY_WIRED'}else{'FAIL_CLOSED_NOT_WIRED'})
        local_model_required=[bool]$RequireLocalModel
        rollback_on_failure=$true
    }|ConvertTo-Json -Depth 5|Set-Content (Join-Path $env:USERPROFILE 'Desktop\Investor-Intelligence-v2.1.3-Scheduled-Activation-Receipt.json') -Encoding utf8
    Write-Host "V2.1.3 SCHEDULED SEVEN-FIELD ACTIVATION = PASS; active_version=$current" -ForegroundColor Green
}catch{
    $failure=$_.Exception.Message
    if($deployed -and $prior){
        Write-Host 'Activation failed; restoring exact prior Worker version...' -ForegroundColor Yellow
        [void](Run $wrangler @('versions','deploy',($prior+'@100%'),'-y','--config',$temp,'--message','Rollback failed v2.1.3 scheduled activation') $CloudRoot)
        $restored=Get-SingleActiveVersion (Capture $wrangler @('deployments','status','--json','--config',$temp) $CloudRoot)
        if($restored-ne$prior){throw "ACTIVATION FAILED AND ROLLBACK COULD NOT BE VERIFIED. Original: $failure"}
        Write-Host 'V213_ACTIVATION_ROLLBACK = PASS' -ForegroundColor Green
    }
    throw $failure
}finally{
    Remove-Item $temp -Force -ErrorAction SilentlyContinue
}
