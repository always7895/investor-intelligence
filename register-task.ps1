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

if ($Enable -and $Disable) {
    throw 'Choose either -Enable or -Disable, not both.'
}
if ([string]::IsNullOrWhiteSpace($BaseInstallRoot)) {
    $BaseInstallRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
}
$BaseInstallRoot = [System.IO.Path]::GetFullPath($BaseInstallRoot)
$StatePath = Join-Path $BaseInstallRoot 'install-state.json'
$TaskNames = @(
    'InvestorIntelligence-v21-MorningRefresh',
    'InvestorIntelligence-v21-EveningRefresh'
)

if ($Disable) {
    foreach ($name in $TaskNames) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
        $state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
        $state.schedules_enabled = $false
        $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StatePath -Encoding UTF8
    }
    Write-Host 'Investor Intelligence v2.1 local refresh tasks are disabled.' -ForegroundColor Green
    exit 0
}

if (-not $Enable) {
    foreach ($name in $TaskNames) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            Write-Host "${name}: not registered"
        }
        else {
            Write-Host "${name}: $($task.State)"
        }
    }
    Write-Host 'No schedule was changed. Use -Enable or -Disable explicitly.' -ForegroundColor Cyan
    exit 0
}

if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw 'Investor Intelligence v2.1 is not installed. Run install-final.cmd first.'
}
$state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
if ([string]$state.version -ne '2.1.0') {
    throw 'Scheduled refresh requires Investor Intelligence v2.1.0.'
}
$RunScript = Join-Path ([string]$state.application_root) 'run-local.ps1'
if (-not (Test-Path -LiteralPath $RunScript -PathType Leaf)) {
    throw 'Installed run-local.ps1 is missing.'
}

$PowerShellExe = (Get-Command powershell.exe).Source
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
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
    $action = New-ScheduledTaskAction `
        -Execute $PowerShellExe `
        -Argument $arguments `
        -WorkingDirectory ([string]$state.application_root)
    $trigger = New-ScheduledTaskTrigger `
        -Daily `
        -At ([DateTime]::ParseExact($definition.Time, 'HH:mm', $null))
    Register-ScheduledTask `
        -TaskName $definition.Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description 'Investor Intelligence v2.1 public Top20 refresh; signed sync occurs only when owner LINE is explicitly configured.' `
        -Force | Out-Null
}

$state.schedules_enabled = $true
$state.local_refresh_times = @($MorningRefreshTime, $EveningRefreshTime)
$state.line_push_times = @('08:00 Asia/Taipei', '21:00 Asia/Taipei')
$state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StatePath -Encoding UTF8

Write-Host "Investor Intelligence daily refresh enabled at $MorningRefreshTime and $EveningRefreshTime." -ForegroundColor Green
Write-Host 'Owner LINE Worker pushes at 08:00 and 21:00 Asia/Taipei only after explicit production setup.' -ForegroundColor Cyan
exit 0
