[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [ValidateSet('zh-TW','en','bilingual')][string]$FieldLocale = 'zh-TW',
    [switch]$ConfirmActivation
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

function Capture([string]$Exe,[string[]]$Args,[string]$Cwd){
    $old=Get-Location
    try{Set-Location $Cwd;$o=@(& $Exe @Args 2>&1);$c=$LASTEXITCODE;if($c-ne 0){throw "$Exe failed with exit code $c"};($o|%{[string]$_})-join"`n"}
    finally{Set-Location $old}
}
function Run([string]$Exe,[string[]]$Args,[string]$Cwd){$x=Capture $Exe $Args $Cwd; if($x){Write-Host $x}; return $x}
function Parse-JsonOutput([string]$Raw){
    $v=$Raw.Trim();try{return($v|ConvertFrom-Json)}catch{}
    $s=@($v.IndexOf('{'),$v.IndexOf('['))|?{$_-ge 0}|sort|select -First 1
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
        $props=@($n.PSObject.Properties);if($props.Count-eq 0){return}
        $ver=$null
        foreach($name in @('version_id','versionId','version','id')){
            $p=$props|?{$_.Name-eq$name}|select -First 1
            if($p -and [string]$p.Value -match '^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}$'){$ver=([string]$p.Value).ToLowerInvariant();break}
        }
        $pct=$null
        foreach($name in @('percentage','percent','traffic_percentage','trafficPercentage')){
            $p=$props|?{$_.Name-eq$name}|select -First 1
            if($p){try{$pct=[double]$p.Value}catch{};if($null-ne$pct){break}}
        }
        if($ver -and $null-ne$pct){$pairs.Add([pscustomobject]@{version=$ver;percentage=$pct})}
        foreach($p in $props){Visit $p.Value}
    }
    Visit $root
    $valid=@($pairs|?{($_.percentage-ge99.999-and$_.percentage-le100.001)-or($_.percentage-ge.99999-and$_.percentage-le1.00001)})
    $versions=@($valid.version|select -Unique)
    if($versions.Count-ne1){throw "Expected exactly one 100% active Worker version; found $($versions.Count)."}
    [string]$versions[0]
}
function Set-Var([string]$Text,[string]$Key,[string]$Value){
    $Text=[regex]::Replace($Text,"(?m)^\s*$Key\s*=.*(?:\r?\n)?",'')
    $escaped=$Value.Replace('\','\\').Replace('"','\"')
    [regex]::Replace($Text,'(?m)^\[vars\]\s*$',"[vars]`r`n$Key = `"$escaped`"",1)
}

$configRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
$productionConfig=@(
    (Join-Path $configRoot 'wrangler.v213.production.local.toml'),
    (Join-Path $configRoot 'wrangler.v211.production.local.toml'),
    (Join-Path $configRoot 'wrangler.v21.production.local.toml')
)|?{Test-Path $_ -PathType Leaf}|select -First 1
if(-not$productionConfig){throw 'Installed Production Wrangler config was not found.'}

$temp=Join-Path $CloudRoot ('.wrangler.v213.activation.'+[guid]::NewGuid().ToString('N')+'.toml')
$text=Get-Content $productionConfig -Raw -Encoding utf8
$text=[regex]::Replace($text,'(?m)^\s*main\s*=.*$','main = "src/v213/production-worker.ts"',1)
$text=Set-Var $text 'V213_FIELD_LOCALE' $FieldLocale
$modelState=Join-Path $configRoot 'v213-local-model.json'
if(Test-Path $modelState){
    $m=Get-Content $modelState -Raw -Encoding utf8|ConvertFrom-Json
    if($m.public_url -and $m.allowed_host -and $m.model){
        $text=Set-Var $text 'LOCAL_LLM_BASE_URL' ([string]$m.public_url)
        $text=Set-Var $text 'LOCAL_LLM_ALLOWED_HOSTS' ([string]$m.allowed_host)
        $text=Set-Var $text 'LOCAL_LLM_MODEL' ([string]$m.model)
    }
}
[IO.File]::WriteAllText($temp,$text,[Text.UTF8Encoding]::new($false))

$npx=(Get-Command npx.cmd -ErrorAction SilentlyContinue)
if(-not$npx){$npx=Get-Command npx -ErrorAction Stop}
$prior=''
$deployed=$false
try{
    $prior=Get-SingleActiveVersion (Capture $npx.Source @('wrangler','deployments','status','--json','--config',$temp) $CloudRoot)
    Write-Host "V213_ACTIVATION_PRIOR_VERSION = $prior" -ForegroundColor Cyan
    if(Test-Path $modelState){
        $m=Get-Content $modelState -Raw -Encoding utf8|ConvertFrom-Json
        if($m.encrypted_shared_secret){
            $secure=ConvertTo-SecureString -String ([string]$m.encrypted_shared_secret)
            $sp=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
            $shared=''
            try{
                $shared=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($sp)
                $old=Get-Location
                try{
                    Set-Location $CloudRoot
                    $secretOutput=@($shared | & $npx.Source 'wrangler' 'secret' 'put' 'LOCAL_LLM_SHARED_SECRET' '--config' $temp 2>&1)
                    if($LASTEXITCODE-ne0){throw 'LOCAL_LLM_SHARED_SECRET update failed.'}
                    $deployed=$true
                }finally{Set-Location $old}
            }finally{
                if($sp-ne[IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($sp)}
                $shared=$null
            }
        }
    }
    $out=Run $npx.Source @('wrangler','deploy','--config',$temp,'--message','v2.1.3 bilingual seven-field scheduled activation') $CloudRoot
    $deployed=$true
    $current=Get-SingleActiveVersion (Capture $npx.Source @('wrangler','deployments','status','--json','--config',$temp) $CloudRoot)
    if($current-eq$prior){throw 'Deployment did not produce a new active Worker version.'}

    & (Join-Path $ProjectRoot 'sync-v213-top20-report.ps1') -ProjectRoot $ProjectRoot
    if($LASTEXITCODE-ne0){throw 'v2.1.3 report sync failed.'}

    $installedCopy=Join-Path $configRoot 'wrangler.v213.production.local.toml'
    Copy-Item $temp $installedCopy -Force
    [ordered]@{
        schema_version=1;status='PASS';product_version='2.1.3'
        activated_utc=(Get-Date).ToUniversalTime().ToString('o')
        prior_worker_version=$prior;active_worker_version=$current
        scheduled_times=@('08:00 Asia/Taipei','21:00 Asia/Taipei')
        scheduled_format='v213_seven_fields';field_locale=$FieldLocale
        rollback_on_failure=$true
    }|ConvertTo-Json -Depth 5|Set-Content (Join-Path $env:USERPROFILE 'Desktop\Investor-Intelligence-v2.1.3-Scheduled-Activation-Receipt.json') -Encoding utf8
    Write-Host "V2.1.3 SCHEDULED SEVEN-FIELD ACTIVATION = PASS; active_version=$current" -ForegroundColor Green
}catch{
    $failure=$_.Exception.Message
    if($deployed -and $prior){
        Write-Host 'Activation failed; restoring exact prior Worker version...' -ForegroundColor Yellow
        Run $npx.Source @('wrangler','versions','deploy',($prior+'@100%'),'-y','--config',$temp,'--message','Rollback failed v2.1.3 scheduled activation') $CloudRoot|Out-Null
        $restored=Get-SingleActiveVersion (Capture $npx.Source @('wrangler','deployments','status','--json','--config',$temp) $CloudRoot)
        if($restored-ne$prior){throw "ACTIVATION FAILED AND ROLLBACK COULD NOT BE VERIFIED. Original: $failure"}
        Write-Host 'V213_ACTIVATION_ROLLBACK = PASS' -ForegroundColor Green
    }
    throw $failure
}finally{
    Remove-Item $temp -Force -ErrorAction SilentlyContinue
}
