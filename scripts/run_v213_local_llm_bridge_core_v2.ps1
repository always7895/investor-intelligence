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
    [ValidateSet('None','QuickTest','Named')][string]$TunnelMode = 'QuickTest',
    [string]$NamedTunnelName = '',
    [string]$NamedTunnelHostname = '',
    [string]$NamedTunnelConfig = '',
    [switch]$SelfTest
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){
    $ProjectRoot=Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$core=Join-Path $ProjectRoot 'scripts\run_v213_local_llm_bridge_core.ps1'
if(-not(Test-Path -LiteralPath $core -PathType Leaf)){throw "Missing bridge core: $core"}
if($SelfTest){
    & $core -ProjectRoot $ProjectRoot -SelfTest
    exit $LASTEXITCODE
}

function Test-GatewayPython([string]$Path){
    if(-not$Path-or-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $false}
    try{
        & $Path -c "import requests,sys; assert sys.version_info >= (3,10)" 2>$null
        return $LASTEXITCODE -eq 0
    }catch{return $false}
}

$python=''
if(Test-GatewayPython $env:PROJECT_PYTHON){$python=$env:PROJECT_PYTHON}
if(-not$python){
    foreach($name in @('python.exe','python3.exe','python','py.exe','py')){
        $command=Get-Command $name -ErrorAction SilentlyContinue
        if($command-and(Test-GatewayPython $command.Source)){$python=$command.Source;break}
    }
}
if(-not$python){
    $runtimeRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\Runtime\python-3.12.10'
    $python=Join-Path $runtimeRoot 'python.exe'
    if(-not(Test-Path -LiteralPath $python -PathType Leaf)){
        $bootstrap=Join-Path $ProjectRoot 'scripts\bootstrap_portable_python.ps1'
        if(-not(Test-Path -LiteralPath $bootstrap -PathType Leaf)){throw 'Verified portable Python bootstrap is missing.'}
        & $bootstrap -DestinationPath $runtimeRoot
        if($LASTEXITCODE-ne0-or-not(Test-Path -LiteralPath $python -PathType Leaf)){throw 'Portable Python bootstrap failed.'}
    }
    if(-not(Test-GatewayPython $python)){
        $requirements=Join-Path $ProjectRoot 'requirements-ci.txt'
        & $python -m pip install --isolated --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple --require-hashes -r $requirements
        if($LASTEXITCODE-ne0){throw 'Hash-locked bridge dependency installation failed.'}
        & $python -m pip check
        if($LASTEXITCODE-ne0){throw 'Bridge Python dependency check failed.'}
    }
}
if(-not(Test-GatewayPython $python)){throw 'No verified Python runtime with requests is available for the local-model bridge.'}
$oldProjectPython=$env:PROJECT_PYTHON
try{
    $env:PROJECT_PYTHON=$python
    & $core -ProjectRoot $ProjectRoot -LlamaBaseUrl $LlamaBaseUrl -GatewayPort $GatewayPort -Model $Model -NoTunnel:$NoTunnel -InstallCloudflared:$InstallCloudflared -StopExisting:$StopExisting -FinalizeCutover:$FinalizeCutover -TunnelMode $TunnelMode -NamedTunnelName $NamedTunnelName -NamedTunnelHostname $NamedTunnelHostname -NamedTunnelConfig $NamedTunnelConfig
    if($LASTEXITCODE-ne0){exit $LASTEXITCODE}
}finally{
    $env:PROJECT_PYTHON=$oldProjectPython
}
