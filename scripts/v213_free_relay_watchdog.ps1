[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [switch]$DryRun
)
# Keeps LINE Q&A connected to whatever local model is served (operator 2026-09-26: a changed port or model, or a model
# server started later, must reconnect without a manual step). Run by the InvestorIntelligence-v213-FreeRelay task at
# logon and every five minutes. It does nothing while the bridge is healthy on the model the resolver would choose, and
# nothing while no local model is served; otherwise it restarts the bridge (-StopExisting), which verifies the model,
# starts the gateway and tunnel and leases the route. The heartbeat keeps the lease between runs.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$statePath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v213-local-model.json'
$python = if ($env:PROJECT_PYTHON) { $env:PROJECT_PYTHON } else { 'python' }

function Test-Alive([object]$ProcessId, [string]$ExpectedName) {
    $id = 0
    if (-not [int]::TryParse([string]$ProcessId, [ref]$id) -or $id -le 0) { return $false }
    try { return (Get-Process -Id $id -ErrorAction Stop).ProcessName -match $ExpectedName } catch { return $false }
}

function Get-Field([object]$Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-WatchdogDecision([object]$Found, [object]$State, [bool]$ProcessesAlive, [bool]$GatewayServesModel) {
    if ($null -eq $Found -or $null -ne (Get-Field $Found 'error')) { return 'IDLE_NO_LOCAL_MODEL' }
    if ($null -eq $State) { return 'CONNECT' }
    if ([string](Get-Field $State 'model') -cne [string]$Found.model -or
        ([string](Get-Field $State 'llama_base_url')).TrimEnd('/') -ne ([string]$Found.base_url).TrimEnd('/')) { return 'RECONNECT_MODEL_CHANGED' }
    if (-not $ProcessesAlive) { return 'RECONNECT_PROCESS_UNAVAILABLE' }
    if (-not $GatewayServesModel) { return 'RECONNECT_GATEWAY_UNHEALTHY' }
    return 'HEALTHY'
}

$found = $null
try {
    $raw = & $python (Join-Path $ProjectRoot 'scripts\local_model_endpoint.py') 2>$null
    $found = ($raw | Select-Object -Last 1) | ConvertFrom-Json
} catch { $found = $null }
$state = $null
if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    try { $state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json } catch { $state = $null }
}
$alive = $false
$serves = $false
if ($null -ne $state) {
    $alive = (Test-Alive (Get-Field $state 'gateway_pid') '(?i)^python') -and (Test-Alive (Get-Field $state 'cloudflared_pid') '(?i)^cloudflared$') -and
        (Test-Alive (Get-Field $state 'free_relay_heartbeat_pid') '(?i)^powershell$')
    if ($alive) {
        try {
            $health = Invoke-RestMethod -Method Get -Uri ("http://127.0.0.1:{0}/health" -f [int](Get-Field $state 'gateway_port')) -TimeoutSec 8 -MaximumRedirection 0
            $serves = (Get-Field $health 'selected_model_available') -eq $true -and [string](Get-Field $health 'selected_model') -ceq [string](Get-Field $state 'model')
        } catch { $serves = $false }
    }
}
$decision = Get-WatchdogDecision $found $state $alive $serves
$model = if ($null -ne $found -and $null -eq (Get-Field $found 'error')) { [string]$found.model } else { '' }
Write-Host "V213_FREE_RELAY_WATCHDOG = $decision; model=$model; dry_run=$($DryRun.IsPresent)"
if ($DryRun -or $decision -in @('HEALTHY', 'IDLE_NO_LOCAL_MODEL')) { exit 0 }
$bridge = Join-Path $ProjectRoot 'run-v213-local-llm-bridge.ps1'
& $bridge -ProjectRoot $ProjectRoot -InstallCloudflared -StopExisting -TunnelMode FreeRelay
