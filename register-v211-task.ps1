[CmdletBinding()]
param(
    [string]$BaseInstallRoot = '',
    [switch]$Enable,
    [switch]$Disable,
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$MorningRefreshTime = '07:20',
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$EveningRefreshTime = '20:20'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($Enable -and $Disable) { throw 'Choose either -Enable or -Disable, not both.' }
if ([string]::IsNullOrWhiteSpace($BaseInstallRoot)) {
    $BaseInstallRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
}
$BaseInstallRoot = [System.IO.Path]::GetFullPath($BaseInstallRoot)
$StatePath = Join-Path $BaseInstallRoot 'install-state.json'
$TaskNames = @('InvestorIntelligence-v21-MorningRefresh', 'InvestorIntelligence-v21-EveningRefresh')

if ($Disable) {
    foreach ($name in $TaskNames) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    }
    Write-Host 'Investor Intelligence refresh tasks are disabled.' -ForegroundColor Green
    exit 0
}
if (-not $Enable) {
    foreach ($name in $TaskNames) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($null -eq $task) { Write-Host "${name}: not registered" }
        else { Write-Host "${name}: $($task.State)" }
    }
    exit 0
}
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw 'Investor Intelligence v2.1 base installation is missing.'
}
$state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
if ([string]$state.version -ne '2.1.0') { throw 'v2.1.1 patch requires accepted v2.1.0 base installation.' }
$RunScript = Join-Path ([string]$state.application_root) 'run-v211-local.ps1'
if (-not (Test-Path -LiteralPath $RunScript -PathType Leaf)) { throw 'Installed run-v211-local.ps1 is missing.' }

$PowerShellExe = (Get-Command powershell.exe).Source
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$definitions = @(
    @{ Name = $TaskNames[0]; Time = $MorningRefreshTime; Slot = 'morning' },
    @{ Name = $TaskNames[1]; Time = $EveningRefreshTime; Slot = 'evening' }
)
foreach ($definition in $definitions) {
    $arguments = (
        "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`" " +
        "-BaseInstallRoot `"$BaseInstallRoot`" -NonInteractive " +
        "-ScheduledSlot $($definition.Slot)"
    )
    $action = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $arguments -WorkingDirectory ([string]$state.application_root)
    $trigger = New-ScheduledTaskTrigger -Daily -At ([DateTime]::ParseExact($definition.Time, 'HH:mm', $null))
    Register-ScheduledTask `
        -TaskName $definition.Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description 'Investor Intelligence v2.1.1 owner-independent research universe + public options refresh.' `
        -Force | Out-Null
}
$state.schedules_enabled = $true
$state.local_refresh_times = @($MorningRefreshTime, $EveningRefreshTime)
$state.line_push_times = @('08:00 Asia/Taipei', '21:00 Asia/Taipei')
if ($null -eq $state.PSObject.Properties['production_patch']) {
    $state | Add-Member -NotePropertyName production_patch -NotePropertyValue '2.1.1'
} else {
    $state.production_patch = '2.1.1'
}
$state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StatePath -Encoding UTF8
Write-Host "Investor Intelligence v2.1.1 daily refresh enabled at $MorningRefreshTime and $EveningRefreshTime." -ForegroundColor Green
exit 0
