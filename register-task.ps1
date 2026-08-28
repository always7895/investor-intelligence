[CmdletBinding()]
param(
    [string]$BaseInstallRoot = '',
    [switch]$Enable,
    [switch]$Disable,
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$MorningTime = '07:30',
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$EveningTime = '20:30'
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
$TaskNames = @('InvestorIntelligence-Morning', 'InvestorIntelligence-Evening')

if ($Disable) {
    foreach ($name in $TaskNames) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
        $state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
        $state.schedules_enabled = $false
        $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8
    }
    Write-Host 'Investor Intelligence scheduled tasks are disabled.' -ForegroundColor Green
    exit 0
}

if (-not $Enable) {
    foreach ($name in $TaskNames) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            Write-Host "$name: not registered"
        }
        else {
            Write-Host "$name: $($task.State)"
        }
    }
    Write-Host 'No schedule was changed. Use -Enable or -Disable explicitly.' -ForegroundColor Cyan
    exit 0
}

if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw 'Investor Intelligence is not installed. Run install-final.ps1 first.'
}
$state = Get-Content -LiteralPath $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
$RunScript = Join-Path ([string]$state.application_root) 'run-local.ps1'
if (-not (Test-Path -LiteralPath $RunScript -PathType Leaf)) {
    throw 'Installed run-local.ps1 is missing.'
}

$PowerShellExe = (Get-Command powershell.exe).Source
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`" -BaseInstallRoot `"$BaseInstallRoot`" -NonInteractive"
$action = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $arguments -WorkingDirectory ([string]$state.application_root)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$days = @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
$definitions = @(
    @{ Name = $TaskNames[0]; Time = $MorningTime },
    @{ Name = $TaskNames[1]; Time = $EveningTime }
)
foreach ($definition in $definitions) {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At ([DateTime]::ParseExact($definition.Time, 'HH:mm', $null))
    Register-ScheduledTask -TaskName $definition.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Investor Intelligence local-only research briefing; LINE and delivery remain disabled.' -Force | Out-Null
}
$state.schedules_enabled = $true
$state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8
Write-Host "Investor Intelligence tasks enabled for weekdays at $MorningTime and $EveningTime." -ForegroundColor Green
exit 0
