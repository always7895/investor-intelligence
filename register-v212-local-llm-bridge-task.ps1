[CmdletBinding()]
param(
    [string]$BaseInstallRoot = '',
    [switch]$Enable,
    [switch]$Disable
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$TaskName = 'InvestorIntelligence-v212-LocalModelBridge'
if ($Enable -and $Disable) { throw 'Choose either -Enable or -Disable.' }
if ([string]::IsNullOrWhiteSpace($BaseInstallRoot)) {
    $BaseInstallRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
}
$StatePath = Join-Path $BaseInstallRoot 'install-state.json'
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) { throw 'install-state.json is missing.' }
$state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
$ApplicationRoot = [string]$state.application_root
$BridgeScript = Join-Path $ApplicationRoot 'run-v212-local-llm-bridge.ps1'
if (-not (Test-Path -LiteralPath $BridgeScript -PathType Leaf)) { throw 'Installed v2.1.2 bridge script is missing.' }

if ($Disable) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host 'v2.1.2 local-model bridge logon task disabled.' -ForegroundColor Green
    exit 0
}
if (-not $Enable) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) { Write-Host 'v2.1.2 local-model bridge logon task: NOT_REGISTERED' }
    else { Write-Host "v2.1.2 local-model bridge logon task: $($task.State)" }
    exit 0
}

$PowerShellExe = (Get-Command powershell.exe).Source
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$BridgeScript`" -BaseInstallRoot `"$BaseInstallRoot`" -InstallCloudflared -StopExisting"
$action = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $arguments -WorkingDirectory $ApplicationRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Investor Intelligence v2.1.2: localhost llama.cpp -> authenticated local gateway -> Cloudflare tunnel -> owner-only LINE Worker.' `
    -Force | Out-Null
Write-Host 'v2.1.2 local-model bridge logon task enabled.' -ForegroundColor Green
