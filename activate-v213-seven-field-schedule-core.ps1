[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [ValidateSet('zh-TW','en','bilingual')][string]$FieldLocale = 'zh-TW',
    [string]$ExpectedModel = '',
    [switch]$ConfirmActivation,
    [switch]$RequireLocalModel,
    [switch]$SelfTest
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
$utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8NoBom
$OutputEncoding=$utf8NoBom

function ConvertTo-NativeArgument([string]$Value){
    if($null-eq$Value -or $Value.Length-eq0){return '""'.Replace('\','')}
    if($Value -notmatch '[\s"]'){return $Value}
    $builder=New-Object System.Text.StringBuilder
    [void]$builder.Append('"'.Replace('\',''))
    $slashes=0
    foreach($character in $Value.ToCharArray()){
        if($character -eq '\'){$slashes++;continue}
        if($character -eq '"'.Replace('\','')){
            if($slashes -gt 0){[void]$builder.Append(('\' * ($slashes*2)))}
            [void]$builder.Append('\"')
            $slashes=0
            continue
        }
        if($slashes -gt 0){[void]$builder.Append(('\' * $slashes));$slashes=0}
        [void]$builder.Append($character)
    }
    if($slashes -gt 0){[void]$builder.Append(('\' * ($slashes*2)))}
    [void]$builder.Append('"'.Replace('\',''))
    return $builder.ToString()
}
function Invoke-NativeCapture([string]$Exe,[string[]]$Args,[string]$Cwd,[string]$InputText=''){
    $psi=New-Object System.Diagnostics.ProcessStartInfo
    $extension=[IO.Path]::GetExtension($Exe)
    $quotedArgs=($Args|ForEach-Object{ConvertTo-NativeArgument ([string]$_)})-join' '
    if($extension -ieq '.cmd' -or $extension -ieq '.bat'){
        $psi.FileName=if($env:ComSpec){$env:ComSpec}else{'cmd.exe'}
        $psi.Arguments='/d /s /c ""'.Replace('\','')+$Exe+'" '.Replace('\','')+$quotedArgs+'"'.Replace('\','')
    }else{
        $psi.FileName=$Exe
        $psi.Arguments=$quotedArgs
    }
    $psi.WorkingDirectory=$Cwd
    $psi.UseShellExecute=$false
    $psi.CreateNoWindow=$true
    $psi.RedirectStandardOutput=$true
    $psi.RedirectStandardError=$true
    $psi.RedirectStandardInput=$true
    $psi.StandardOutputEncoding=$utf8NoBom
    $psi.StandardErrorEncoding=$utf8NoBom
    $psi.EnvironmentVariables['NO_COLOR']='1'
    $psi.EnvironmentVariables['CI']='true'
    $psi.EnvironmentVariables['TERM']='dumb'
    $psi.EnvironmentVariables['WRANGLER_SEND_METRICS']='false'
    $process=New-Object System.Diagnostics.Process
    $process.StartInfo=$psi
    if(-not$process.Start()){throw "Unable to start native command: $Exe"}
    $stdoutTask=$process.StandardOutput.ReadToEndAsync()
    $stderrTask=$process.StandardError.ReadToEndAsync()
    if($InputText){$process.StandardInput.WriteLine($InputText)}
    $process.StandardInput.Close()
    $process.WaitForExit()
    $stdout=$stdoutTask.GetAwaiter().GetResult()
    $stderr=$stderrTask.GetAwaiter().GetResult()
    $exitCode=$process.ExitCode
    $process.Dispose()
    return [pscustomobject]@{ExitCode=$exitCode;Stdout=[string]$stdout;Stderr=[string]$stderr}
}
function Capture([string]$Exe,[string[]]$Args,[string]$Cwd,[string]$InputText=''){
    $result=Invoke-NativeCapture $Exe $Args $Cwd $InputText
    if($result.ExitCode-ne0){
        $tail=(($result.Stdout+"`n"+$result.Stderr)-split'\r?\n'|Select-Object -Last 30)-join"`n"
        throw "$Exe failed with exit code $($result.ExitCode)`n$tail"
    }
    return [string]$result.Stdout
}
function Run([string]$Exe,[string[]]$Args,[string]$Cwd,[string]$InputText=''){
    $result=Invoke-NativeCapture $Exe $Args $Cwd $InputText
    if($result.Stdout){Write-Host $result.Stdout.TrimEnd()}
    if($result.Stderr){Write-Host $result.Stderr.TrimEnd()}
    if($result.ExitCode-ne0){
        $tail=(($result.Stdout+"`n"+$result.Stderr)-split'\r?\n'|Select-Object -Last 30)-join"`n"
        throw "$Exe failed with exit code $($result.ExitCode)`n$tail"
    }
    return [string]$result.Stdout
}
function Parse-JsonOutput([string]$Raw){
    if([string]::IsNullOrWhiteSpace($Raw)){throw 'Wrangler JSON stdout was empty.'}
    $escape=[regex]::Escape([string][char]27)
    $value=[regex]::Replace($Raw,$escape+'\[[0-?]*[ -/]*[@-~]','').Trim().TrimStart([char]0xFEFF)
    try{return($value|ConvertFrom-Json)}catch{throw "Wrangler stdout was not one valid JSON document. $($_.Exception.Message)"}
}
function Get-SingleActiveVersion([string]$Raw){
    $root=Parse-JsonOutput $Raw
    $versions=@($root.versions)
    if($versions.Count-eq0){throw 'Wrangler deployment JSON has no versions array.'}
    $active=@($versions|Where-Object{
        $percentage=0.0
        [void][double]::TryParse([string]$_.percentage,[ref]$percentage)
        ($percentage-ge99.999-and$percentage-le100.001)-or($percentage-ge.99999-and$percentage-le1.00001)
    })
    if($active.Count-ne1){throw "Expected exactly one 100% active Worker version; found $($active.Count)."}
    $version=[string]$active[0].version_id
    if($version -notmatch '^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}$'){throw 'Active Worker version_id is invalid.'}
    return $version.ToLowerInvariant()
}
function Set-Var([string]$Text,[string]$Key,[string]$Value){
    $Text=[regex]::Replace($Text,"(?m)^\s*$Key\s*=.*(?:\r?\n)?",'')
    $escaped=$Value.Replace('\','\\').Replace('"','\"')
    [regex]::Replace($Text,'(?m)^\[vars\]\s*$',"[vars]`r`n$Key = `"$escaped`"",1)
}
function Remove-Var([string]$Text,[string]$Key){return[regex]::Replace($Text,"(?m)^\s*$Key\s*=.*(?:\r?\n)?",'')}
function Get-HealthyModelState([string]$Path,[string]$RequiredModel){
    if(-not(Test-Path $Path -PathType Leaf)){return $null}
    try{
        $modelState=Get-Content $Path -Raw -Encoding utf8|ConvertFrom-Json
        if(-not$modelState.public_url -or -not$modelState.allowed_host -or -not$modelState.model -or -not$modelState.encrypted_shared_secret){return $null}
        if($modelState.selected_model_verified -ne $true){return $null}
        if($RequiredModel -and [string]$modelState.model -ine $RequiredModel){return $null}
        $connected=[DateTimeOffset]::MinValue
        if(-not[DateTimeOffset]::TryParse([string]$modelState.connected_at,[ref]$connected)){return $null}
        $age=([DateTimeOffset]::UtcNow-$connected.ToUniversalTime()).TotalMinutes
        if($age-lt-5-or$age-gt30){return $null}
        $health=Invoke-RestMethod -Method Get -Uri (([string]$modelState.public_url).TrimEnd('/')+'/health') -Headers @{'cache-control'='no-cache'} -TimeoutSec 15
        if($health.ok-ne$true-or$health.llama_reachable-ne$true-or$health.selected_model_available-ne$true){return $null}
        if([string]$health.selected_model -ine [string]$modelState.model){return $null}
        return $modelState
    }catch{return $null}
}

if($SelfTest){
    $version='12345678-1234-1234-1234-123456789abc'
    $testRoot=Join-Path $env:TEMP ('ii-v213-wrangler-json-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $testRoot|Out-Null
    $testCmd=Join-Path $testRoot 'emit.cmd'
    $cmdBody=@"
@echo off
echo {"versions":[{"version_id":"$version","percentage":100}]}
echo search... 1>&2
exit /b 0
"@
    [IO.File]::WriteAllText($testCmd,$cmdBody,[Text.Encoding]::ASCII)
    try{
        $captured=Invoke-NativeCapture $testCmd @() $testRoot
        if($captured.ExitCode-ne0){throw 'Native capture self-test process failed.'}
        if($captured.Stderr-notmatch'search\.\.\.'){throw 'Native stderr was not captured separately.'}
        if($captured.Stdout-match'search\.\.\.'){throw 'Native stderr contaminated stdout.'}
        if((Get-SingleActiveVersion $captured.Stdout)-ne$version){throw 'Wrangler JSON parser self-test failed.'}
    }finally{Remove-Item $testRoot -Recurse -Force -ErrorAction SilentlyContinue}
    Write-Host 'V213_ACTIVATION_JSON_CAPTURE_SELF_TEST = PASS' -ForegroundColor Green
    exit 0
}

if(-not$ConfirmActivation){throw 'Formal scheduled activation requires -ConfirmActivation.'}
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent $MyInvocation.MyCommand.Path}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$CloudRoot=Join-Path $ProjectRoot 'cloud'
$ReportPath=Join-Path $ProjectRoot 'data\cache\v213_top20_report_public_latest.json'
if(-not(Test-Path $ReportPath -PathType Leaf)){throw 'Build the v2.1.3 seven-field report before activation.'}
$report=Get-Content $ReportPath -Raw -Encoding utf8|ConvertFrom-Json
if([string]$report.product_version-ne'2.1.3'-or@($report.records).Count-ne20){throw 'The local v2.1.3 report failed the activation preflight.'}
$reportTime=[DateTimeOffset]::MinValue
if(-not[DateTimeOffset]::TryParse([string]$report.generated_at,[ref]$reportTime)){throw 'The v2.1.3 report generated_at value is invalid.'}
$reportAge=([DateTimeOffset]::UtcNow-$reportTime.ToUniversalTime()).TotalSeconds
if($reportAge-lt-300-or$reportAge-gt7200){throw "The v2.1.3 report is outside the 2-hour activation freshness gate (age_seconds=$([Math]::Round($reportAge))). Refresh first."}

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
$selectionPath=Join-Path $configRoot 'v213-model-selection.json'
if(-not$ExpectedModel-and(Test-Path $selectionPath -PathType Leaf)){
    try{$ExpectedModel=[string](Get-Content $selectionPath -Raw -Encoding utf8|ConvertFrom-Json).model}catch{}
}
if($ExpectedModel-and$ExpectedModel-notmatch'^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}$'){throw 'ExpectedModel contains unsupported characters.'}
$productionConfig=@(
    (Join-Path $configRoot 'wrangler.v213.production.local.toml'),
    (Join-Path $configRoot 'wrangler.v211.production.local.toml'),
    (Join-Path $configRoot 'wrangler.v21.production.local.toml')
)|Where-Object{Test-Path $_ -PathType Leaf}|Select-Object -First 1
if(-not$productionConfig){throw 'Installed Production Wrangler config was not found.'}

$modelState=Join-Path $configRoot 'v213-local-model.json'
$healthyModel=Get-HealthyModelState $modelState $ExpectedModel
if($RequireLocalModel-and-not$healthyModel){throw "Formal activation requires a fresh healthy bridge for the explicitly selected model '$ExpectedModel'. Production was not changed."}
if($healthyModel){
    $ExpectedModel=[string]$healthyModel.model
    Write-Host "V213_SELECTED_MODEL_PREFLIGHT = PASS; model=$ExpectedModel" -ForegroundColor Green
}

$temp=Join-Path $CloudRoot ('.wrangler.v213.activation.'+[guid]::NewGuid().ToString('N')+'.toml')
$text=Get-Content $productionConfig -Raw -Encoding utf8
$text=[regex]::Replace($text,'(?m)^\s*main\s*=.*$','main = "src/v213/production-worker.ts"',1)
$text=Set-Var $text 'V213_FIELD_LOCALE' $FieldLocale
if($healthyModel){
    $text=Set-Var $text 'LOCAL_LLM_BASE_URL' ([string]$healthyModel.public_url)
    $text=Set-Var $text 'LOCAL_LLM_ALLOWED_HOSTS' ([string]$healthyModel.allowed_host)
    $text=Set-Var $text 'LOCAL_LLM_MODEL' ([string]$healthyModel.model)
    Write-Host "V213_LOCAL_MODEL_ROUTE_PREFLIGHT = PASS; host=$($healthyModel.allowed_host); model=$($healthyModel.model)" -ForegroundColor Green
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
        schema_version=2;status='PASS';product_version='2.1.3'
        activated_utc=(Get-Date).ToUniversalTime().ToString('o')
        prior_worker_version=$prior;active_worker_version=$current
        scheduled_times=@('08:00 Asia/Taipei','21:00 Asia/Taipei')
        local_refresh_times=@('07:20','20:20')
        scheduled_format='v213_seven_fields';field_locale=$FieldLocale
        runtime_root=$stableRuntime;selected_model=$ExpectedModel
        local_model_route=$(if($healthyModel){'HEALTHY_WIRED_EXACT_MODEL'}else{'FAIL_CLOSED_NOT_WIRED'})
        local_model_required=[bool]$RequireLocalModel
        wrangler_json_stdout_isolated=$true;rollback_on_failure=$true
    }|ConvertTo-Json -Depth 6|Set-Content (Join-Path $env:USERPROFILE 'Desktop\Investor-Intelligence-v2.1.3-Scheduled-Activation-Receipt.json') -Encoding utf8
    Write-Host "V2.1.3 SCHEDULED SEVEN-FIELD ACTIVATION = PASS; active_version=$current; model=$ExpectedModel" -ForegroundColor Green
}catch{
    $failure=$_.Exception.Message
    if($deployed-and$prior){
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