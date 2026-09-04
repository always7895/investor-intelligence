[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$LlamaBaseUrl = '',
    [int]$GatewayPort = 8814,
    [string]$Model = '',
    [switch]$NoTunnel,
    [switch]$InstallCloudflared,
    [switch]$StopExisting,
    [switch]$SelfTest
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
$utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8NoBom
$OutputEncoding=$utf8NoBom

function Get-PropertyValue([object]$Object,[string]$Name,[object]$Default=$null){
    if($null-eq$Object){return $Default}
    $property=$Object.PSObject.Properties[$Name]
    if($null-eq$property){return $Default}
    return $property.Value
}

function Get-LogTail([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return '<missing>'}
    $lines=@(Get-Content -LiteralPath $Path -Tail 25 -ErrorAction SilentlyContinue|ForEach-Object{([string]$_).Trim()}|Where-Object{$_})
    if($lines.Count-eq0){return '<empty>'}
    return ($lines-join' | ')
}

function Get-StableSafeRoot([string]$Target){
    $bytes=[Text.Encoding]::UTF8.GetBytes($Target.ToLowerInvariant())
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$hash=([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant().Substring(0,16)}finally{$sha.Dispose()}
    $parent=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\BridgeSource'
    New-Item -ItemType Directory -Force -Path $parent|Out-Null
    $link=Join-Path $parent ('r75-'+$hash)
    if(Test-Path -LiteralPath $link){
        try{
            $item=Get-Item -LiteralPath $link -Force
            $resolved=[IO.Path]::GetFullPath([string]$item.Target)
            if($resolved-ine$Target){Remove-Item -LiteralPath $link -Force -Recurse}
        }catch{Remove-Item -LiteralPath $link -Force -Recurse -ErrorAction SilentlyContinue}
    }
    if(-not(Test-Path -LiteralPath $link)){
        New-Item -ItemType Junction -Path $link -Target $Target|Out-Null
    }
    if(-not(Test-Path -LiteralPath (Join-Path $link 'scripts\v213_local_llm_gateway.py') -PathType Leaf)){
        throw 'The safe bridge junction does not expose the gateway source.'
    }
    return [IO.Path]::GetFullPath($link)
}

function Test-PublicHealthConsecutive([string]$Url,[string]$RequiredModel,[int]$Count=3){
    $successful=0
    $last=''
    for($attempt=1;$attempt-le12-and$successful-lt$Count;$attempt++){
        try{
            $health=Invoke-RestMethod -Method Get -Uri ($Url.TrimEnd('/')+'/health') -Headers @{'cache-control'='no-cache';'pragma'='no-cache'} -TimeoutSec 15
            $valid=(Get-PropertyValue $health 'ok' $false)-eq$true-and
                [string](Get-PropertyValue $health 'service' '')-eq'v213-local-llm-gateway'-and
                [int](Get-PropertyValue $health 'health_schema_version' 0)-ge2-and
                (Get-PropertyValue $health 'llama_reachable' $false)-eq$true-and
                (Get-PropertyValue $health 'selected_model_available' $false)-eq$true-and
                [string](Get-PropertyValue $health 'selected_model' '')-ieq$RequiredModel
            if($valid){$successful++;Start-Sleep -Seconds 1;continue}
            $last='health payload did not match the exact model';$successful=0
        }catch{$last=$_.Exception.Message;$successful=0}
        Start-Sleep -Seconds 2
    }
    if($successful-lt$Count){throw "Quick-tunnel public health did not remain stable for $Count consecutive checks. Last observation: $last"}
    return $successful
}

if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$v2=Join-Path $ProjectRoot 'scripts\run_v213_local_llm_bridge_core_v2.ps1'
if(-not(Test-Path -LiteralPath $v2 -PathType Leaf)){throw "Missing bridge core v2: $v2"}

if($SelfTest){
    & $v2 -ProjectRoot $ProjectRoot -SelfTest
    if($LASTEXITCODE-ne0){throw 'Bridge v2 dependency self-test failed.'}
    $target=Join-Path $env:TEMP ('Investor Intelligence Source Path (1)-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path (Join-Path $target 'scripts')|Out-Null
    Set-Content -LiteralPath (Join-Path $target 'scripts\v213_local_llm_gateway.py') -Value '# probe' -Encoding utf8
    try{
        $safe=Get-StableSafeRoot ([IO.Path]::GetFullPath($target))
        if($safe-match'[ ()]'){throw "Safe junction still contains unsupported layout characters: $safe"}
        if(-not(Test-Path -LiteralPath (Join-Path $safe 'scripts\v213_local_llm_gateway.py') -PathType Leaf)){throw 'Safe junction self-test cannot read the target file.'}
    }finally{Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue}
    Write-Host 'V213_BRIDGE_STRICTMODE_HEALTH_SELF_TEST = PASS; V213_BRIDGE_SPACED_PATH_JUNCTION_SELF_TEST = PASS; consecutive_public_health=3' -ForegroundColor Green
    exit 0
}

$safeRoot=Get-StableSafeRoot $ProjectRoot
$safeV2=Join-Path $safeRoot 'scripts\run_v213_local_llm_bridge_core_v2.ps1'
$logRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\logs\v213-local-model'
try{
    & $safeV2 -ProjectRoot $safeRoot -LlamaBaseUrl $LlamaBaseUrl -GatewayPort $GatewayPort -Model $Model -NoTunnel:$NoTunnel -InstallCloudflared:$InstallCloudflared -StopExisting:$StopExisting
    if($LASTEXITCODE-ne0){throw "Bridge v2 returned exit code $LASTEXITCODE."}
    $statePath=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v213-local-model.json'
    if(-not(Test-Path -LiteralPath $statePath -PathType Leaf)){throw 'Bridge v2 did not write the local-model state.'}
    $state=Get-Content -LiteralPath $statePath -Raw -Encoding utf8|ConvertFrom-Json
    $selected=[string](Get-PropertyValue $state 'model' '')
    $publicUrl=[string](Get-PropertyValue $state 'public_url' '')
    $checks=0
    if(-not$NoTunnel){
        if($publicUrl-notmatch'^https://'){throw 'Quick tunnel did not produce a public HTTPS URL.'}
        $checks=Test-PublicHealthConsecutive $publicUrl $selected 3
    }
    $state|Add-Member -NotePropertyName source_project_root -NotePropertyValue $ProjectRoot -Force
    $state|Add-Member -NotePropertyName safe_bridge_root -NotePropertyValue $safeRoot -Force
    $state|Add-Member -NotePropertyName spaced_or_parenthesized_source_path_supported -NotePropertyValue $true -Force
    $state|Add-Member -NotePropertyName tunnel_mode -NotePropertyValue $(if($NoTunnel){'none'}else{'quick_ephemeral'}) -Force
    $state|Add-Member -NotePropertyName tunnel_uptime_guarantee -NotePropertyValue $false -Force
    $state|Add-Member -NotePropertyName consecutive_public_health_checks -NotePropertyValue $checks -Force
    $state|Add-Member -NotePropertyName bridge_contract -NotePropertyValue 'r75-safe-junction-v1' -Force
    $state|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $statePath -Encoding utf8
    Write-Host "V213_R75_LOCAL_MODEL_BRIDGE = PASS; source_root=$ProjectRoot; safe_root=$safeRoot; model=$selected; tunnel_mode=$([string](Get-PropertyValue $state 'tunnel_mode' 'none')); consecutive_public_health=$checks" -ForegroundColor Green
}
catch{
    $stderr=Get-LogTail (Join-Path $logRoot 'gateway.stderr.log')
    $stdout=Get-LogTail (Join-Path $logRoot 'gateway.stdout.log')
    throw "R75 local-model bridge failed. $($_.Exception.Message) stderr_tail=$stderr; stdout_tail=$stdout"
}
