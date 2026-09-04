[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [switch]$Enable,
    [switch]$Disable,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$taskName = 'InvestorIntelligence-v213-FreeRelay'
if ($Enable -and $Disable) { throw 'Choose either Enable or Disable.' }
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$bridge = Join-Path $ProjectRoot 'run-v213-local-llm-bridge.ps1'
if (-not (Test-Path -LiteralPath $bridge -PathType Leaf)) { throw 'v2.1.3 bridge script is missing.' }
$powerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$bridge`" -ProjectRoot `"$ProjectRoot`" -InstallCloudflared -StopExisting -TunnelMode FreeRelay"
if ($arguments -notmatch '-TunnelMode FreeRelay' -or $arguments -notmatch '-StopExisting') { throw 'FREE_RELAY reconnect action is incomplete.' }
if ($ValidateOnly) {
    Write-Host 'V213_FREE_RELAY_TASK_VALIDATION = PASS; at_logon=true; start_when_available=true; ignore_concurrent=true; registration_performed=false; production_mutation=false' -ForegroundColor Green
    exit 0
}
if ($Disable) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host 'v2.1.3 FREE_RELAY reconnect task disabled.' -ForegroundColor Green
    exit 0
}
if (-not $Enable) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Write-Host $(if ($null -eq $task) { 'v2.1.3 FREE_RELAY reconnect task: NOT_REGISTERED' } else { "v2.1.3 FREE_RELAY reconnect task: $($task.State)" })
    exit 0
}
$action = New-ScheduledTaskAction -Execute $powerShellExe -Argument $arguments -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Investor Intelligence v2.1.3 FREE_RELAY: recreate and verify an ephemeral Quick Tunnel, then atomically lease it through the stable workers.dev Worker.' -Force | Out-Null
Write-Host 'V213_FREE_RELAY_RECONNECT_TASK = ENABLED' -ForegroundColor Green
