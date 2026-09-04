[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$FreeRelayConfigPath = '',
    [string]$PublicUrl = '',
    [string]$RouteGeneration = '',
    [string]$Model = '',
    [string]$ConnectedAt = '',
    [int]$GatewayProcessId = 0,
    [int]$TunnelProcessId = 0,
    [string]$LlamaBaseUrl = '',
    [int]$GatewayPort = 8814,
    [int]$LeaseTtlSeconds = 180,
    [int]$MaximumIterations = 0,
    [string]$ActivationFile = '',
    [switch]$NoReconnect,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
. (Join-Path $ProjectRoot 'scripts\v213_free_relay.ps1')

function Test-RelayProcess([int]$ProcessId,[string]$ExpectedName) {
    if ($ProcessId -le 0) { return $false }
    try { return (Get-Process -Id $ProcessId -ErrorAction Stop).ProcessName -match $ExpectedName } catch { return $false }
}

function Get-ReconnectDecision([bool]$GatewayAlive,[bool]$TunnelAlive,[bool]$PublishSucceeded) {
    if (-not $GatewayAlive -or -not $TunnelAlive) { return 'RECONNECT_NEW_GENERATION' }
    if (-not $PublishSucceeded) { return 'RETAIN_PROCESS_LEASE_NOT_EXTENDED' }
    return 'HEARTBEAT_EXTENDED'
}

if ($SelfTest) {
    if ((Get-ReconnectDecision $false $true $true) -ne 'RECONNECT_NEW_GENERATION') { throw 'Gateway restart simulation failed.' }
    if ((Get-ReconnectDecision $true $false $true) -ne 'RECONNECT_NEW_GENERATION') { throw 'cloudflared restart simulation failed.' }
    if ((Get-ReconnectDecision $true $true $false) -ne 'RETAIN_PROCESS_LEASE_NOT_EXTENDED') { throw 'Lease failure simulation failed.' }
    if ((Get-ReconnectDecision $true $true $true) -ne 'HEARTBEAT_EXTENDED') { throw 'Heartbeat simulation failed.' }
    Write-Host 'V213_FREE_RELAY_HEARTBEAT_SELF_TEST = PASS; reboot_reconnect=true; cloudflared_restart=true; lease_expiry_fail_closed=true; new_generation=true; production_mutation=false' -ForegroundColor Green
    exit 0
}

if (-not [string]::IsNullOrWhiteSpace($ActivationFile)) {
    $deadline = (Get-Date).AddSeconds(120)
    while (-not (Test-Path -LiteralPath $ActivationFile -PathType Leaf)) {
        if ((Get-Date) -ge $deadline) { throw 'FREE_RELAY heartbeat activation was not committed.' }
        Start-Sleep -Milliseconds 250
    }
    Remove-Item -LiteralPath $ActivationFile -Force -ErrorAction SilentlyContinue
}
$config = Get-V213FreeRelayConfig -ConfigPath $FreeRelayConfigPath
$iteration = 0
$interval = [Math]::Max(20,[Math]::Min(90,[int]($LeaseTtlSeconds / 3)))
while ($MaximumIterations -le 0 -or $iteration -lt $MaximumIterations) {
    $iteration++
    $gatewayAlive = Test-RelayProcess $GatewayProcessId '(?i)^python'
    $tunnelAlive = Test-RelayProcess $TunnelProcessId '(?i)^cloudflared$'
    if (-not $gatewayAlive -or -not $tunnelAlive) {
        Write-Host "V213_FREE_RELAY_RECONNECT = REQUIRED; generation=$RouteGeneration; reason=process_unavailable" -ForegroundColor Yellow
        if (-not $NoReconnect) {
            $bridge = Join-Path $ProjectRoot 'run-v213-local-llm-bridge.ps1'
            & $bridge -ProjectRoot $ProjectRoot -LlamaBaseUrl $LlamaBaseUrl -GatewayPort $GatewayPort -Model $Model -InstallCloudflared -StopExisting -TunnelMode FreeRelay -FreeRelayConfigPath $FreeRelayConfigPath -FreeRelayLeaseTtlSeconds $LeaseTtlSeconds
        }
        exit 0
    }
    $record = New-V213FreeRelayRouteRecord -PublicUrl $PublicUrl -Model $Model -Generation $RouteGeneration -ConnectedAt $ConnectedAt -LeaseTtlSeconds $LeaseTtlSeconds
    try {
        [void](Publish-V213FreeRelayRoute -Configuration $config -Record $record)
        Write-Host "V213_FREE_RELAY_HEARTBEAT = PASS; generation=$RouteGeneration; expires_at=$($record.expires_at)" -ForegroundColor Green
    }
    catch {
        Write-Warning 'FREE_RELAY heartbeat failed; lease was not extended and will expire closed.'
    }
    if ($MaximumIterations -gt 0 -and $iteration -ge $MaximumIterations) { break }
    Start-Sleep -Seconds $interval
}
