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
    [switch]$SelfTest,
    [switch]$RoutingCheckOnly,
    [AllowNull()][AllowEmptyString()][string]$BindingJson,
    [switch]$BindingMetadataCheckOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){
    $ProjectRoot=Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$core=Join-Path $ProjectRoot 'scripts\run_v213_local_llm_bridge_core.ps1'
if(-not(Test-Path -LiteralPath $core -PathType Leaf)){throw "Missing bridge core: $core"}
# Presence-driven explicit path BEFORE any Python/import/install/bootstrap probe.
$bindingFile = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v213-runtime-binding-v1.json'
$selectionFile = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v213-model-selection.json'
$explicit = $PSBoundParameters.ContainsKey('BindingJson') -or $null -ne [Environment]::GetEnvironmentVariable('V213_RUNTIME_BINDING_JSON') -or (Test-Path -LiteralPath $bindingFile)
if (Test-Path -LiteralPath $selectionFile) {
    if (-not (Test-Path -LiteralPath $selectionFile -PathType Leaf) -or (Get-Item -LiteralPath $selectionFile).Length -gt 16384) { throw 'MODEL_SELECTION_INVALID' }
    # Raw top-level object check BEFORE decoding: never infer the type from pipeline-enumerated output (version-independent).
    try {
        $selectionText = [IO.File]::ReadAllText($selectionFile)
        if ($selectionText -cnotmatch '\A[ \t\r\n]*\{') { throw 'MODEL_SELECTION_INVALID' }
        $selection = $selectionText | ConvertFrom-Json -ErrorAction Stop
    } catch { throw 'MODEL_SELECTION_INVALID' }
    if ($null -eq $selection -or $selection -isnot [pscustomobject]) { throw 'MODEL_SELECTION_INVALID' }
    $explicit = $explicit -or $null -ne $selection.PSObject.Properties['engine'] -or $null -ne $selection.PSObject.Properties['runtime_binding_sha256']
}
if ($SelfTest) {
    if ($explicit -or $BindingMetadataCheckOnly -or $RoutingCheckOnly) { throw 'BINDING_OPERATION_CONFLICT' }
    & $core -ProjectRoot $ProjectRoot -SelfTest
    exit $LASTEXITCODE
}
if ($explicit -or $BindingMetadataCheckOnly) {
    $forward = @{}
    foreach ($key in $PSBoundParameters.Keys) { $forward[$key] = $PSBoundParameters[$key] }
    $forward['ProjectRoot'] = $ProjectRoot
    # Core validates locally then selected metadata before any actuation, and
    # explicitly refuses missing existing Python; never call the installer lane.
    & $core @forward
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
    $forward = @{}
    foreach ($key in $PSBoundParameters.Keys) { $forward[$key] = $PSBoundParameters[$key] }
    $forward['ProjectRoot'] = $ProjectRoot
    & $core @forward
    if($LASTEXITCODE-ne0){exit $LASTEXITCODE}
}finally{
    $env:PROJECT_PYTHON=$oldProjectPython
}
