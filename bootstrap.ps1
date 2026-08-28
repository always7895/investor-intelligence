[CmdletBinding()]
param(
    [string]$BaseInstallRoot = '',
    [switch]$CreateDesktopShortcut,
    [switch]$Force,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

$Version = '2.0.0'
$PythonVersion = '3.12.10'
$SourceRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Path))
}

function Assert-SafeInstallationContext {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if ($env:OS -ne 'Windows_NT') {
        throw 'Investor Intelligence local installation supports Windows only.'
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'Investor Intelligence requires 64-bit Windows.'
    }

    $forbidden = @('\\_work\\', '\\_diag\\', '\\actions-runner', '\\runner\\_work\\')
    foreach ($fragment in $forbidden) {
        if ($Source.IndexOf($fragment, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $Destination.IndexOf($fragment, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw 'Installation inside a GitHub Actions runner workspace is forbidden.'
        }
    }
}

function Assert-RequiredSourceFiles {
    param([Parameter(Mandatory = $true)][string]$Root)

    $required = @(
        'README.md',
        'release-metadata.json',
        'requirements-ci.txt',
        'scripts\bootstrap_portable_python.ps1',
        'scripts\daily_briefing.py',
        'scripts\run_offline_tests.py',
        'config\research-universe.example.json',
        'config\user-preferences.example.json',
        'run-local.ps1',
        'register-task.ps1',
        'uninstall.ps1'
    )
    foreach ($relative in $required) {
        $path = Join-Path $Root $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required final-release file is missing: $relative"
        }
    }

    $metadataPath = Join-Path $Root 'release-metadata.json'
    $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ([string]$metadata.version -ne $Version) {
        throw "Package version mismatch. Expected $Version, found $($metadata.version)."
    }
    if ([string]$metadata.build_mode -ne 'final_release') {
        throw 'bootstrap.ps1 accepts only a final_release package.'
    }
    if ($metadata.secrets_included -ne $false -or $metadata.user_data_included -ne $false) {
        throw 'Final-release metadata does not assert a clean secret-free and user-data-free package.'
    }
}

function Copy-FinalReleaseTree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$UpgradeStagingRoot,
        [switch]$Replace
    )

    if ($Source.Equals($Destination, [System.StringComparison]::OrdinalIgnoreCase)) {
        return
    }

    $preserved = @()
    if (Test-Path -LiteralPath $Destination) {
        if (-not $Replace) {
            $existingMetadata = Join-Path $Destination 'release-metadata.json'
            if (Test-Path -LiteralPath $existingMetadata -PathType Leaf) {
                $existing = Get-Content -LiteralPath $existingMetadata -Raw -Encoding utf8 | ConvertFrom-Json
                if ([string]$existing.version -eq $Version) {
                    Write-Host "Investor Intelligence v$Version is already installed. Revalidating runtime." -ForegroundColor Cyan
                    return
                }
            }
            throw "Destination already exists: $Destination. Use -Force only for an intentional verified reinstall."
        }

        Remove-Item -LiteralPath $UpgradeStagingRoot -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $UpgradeStagingRoot | Out-Null
        foreach ($relative in @('data', 'reports', 'daily_briefing.log')) {
            $candidate = Join-Path $Destination $relative
            if (Test-Path -LiteralPath $candidate) {
                Move-Item -LiteralPath $candidate -Destination $UpgradeStagingRoot -Force
                $preserved += $relative
            }
        }
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }

    try {
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
            if ($_.Name -in @('.git', '.github', '.venv', 'node_modules', 'data', 'reports', 'state')) {
                return
            }
            Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
        }
        foreach ($relative in $preserved) {
            $staged = Join-Path $UpgradeStagingRoot $relative
            if (Test-Path -LiteralPath $staged) {
                Move-Item -LiteralPath $staged -Destination $Destination -Force
            }
        }
    }
    catch {
        # Preserve user-generated output even if application replacement fails.
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        foreach ($relative in $preserved) {
            $staged = Join-Path $UpgradeStagingRoot $relative
            if (Test-Path -LiteralPath $staged) {
                Move-Item -LiteralPath $staged -Destination $Destination -Force -ErrorAction SilentlyContinue
            }
        }
        throw
    }
    finally {
        Remove-Item -LiteralPath $UpgradeStagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function New-DesktopShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$ApplicationRoot,
        [Parameter(Mandatory = $true)][string]$ShortcutPath
    )

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = (Get-Command powershell.exe).Source
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $ApplicationRoot 'run-local.ps1')`""
    $shortcut.WorkingDirectory = $ApplicationRoot
    $shortcut.Description = "Investor Intelligence v$Version"
    $shortcut.Save()
}

if ([string]::IsNullOrWhiteSpace($BaseInstallRoot)) {
    $BaseInstallRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence'
}
$BaseInstallRoot = Resolve-FullPath -Path $BaseInstallRoot
$ApplicationRoot = Join-Path $BaseInstallRoot "App\$Version"
$RuntimeRoot = Join-Path $BaseInstallRoot "Runtime\Python-$PythonVersion"
$UserConfigRoot = Join-Path $BaseInstallRoot 'UserData\config'
$StatePath = Join-Path $BaseInstallRoot 'install-state.json'
$UpgradeStagingRoot = Join-Path $BaseInstallRoot 'UpgradeStaging'

Assert-SafeInstallationContext -Source $SourceRoot -Destination $BaseInstallRoot
Assert-RequiredSourceFiles -Root $SourceRoot

if ($ValidateOnly) {
    Write-Host "FINAL INSTALLER VALIDATION PASSED: v$Version, Windows x64 policy, final-release metadata and required files." -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Force -Path $BaseInstallRoot,$UserConfigRoot | Out-Null
Copy-FinalReleaseTree -Source $SourceRoot -Destination $ApplicationRoot -UpgradeStagingRoot $UpgradeStagingRoot -Replace:$Force
Assert-RequiredSourceFiles -Root $ApplicationRoot

$PortableBootstrap = Join-Path $ApplicationRoot 'scripts\bootstrap_portable_python.ps1'
$PythonExe = Join-Path $RuntimeRoot 'python.exe'
$RuntimeValid = $false
if (Test-Path -LiteralPath $PythonExe -PathType Leaf) {
    try {
        $versionOutput = (& $PythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
        $RuntimeValid = $versionOutput -eq $PythonVersion
    }
    catch {
        $RuntimeValid = $false
    }
}
if (-not $RuntimeValid) {
    & $PortableBootstrap -DestinationPath $RuntimeRoot | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw 'Verified portable Python bootstrap failed.'
    }
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw 'Verified portable Python executable was not created.'
}

Push-Location $ApplicationRoot
try {
    & $PythonExe -m pip install --isolated --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple --require-hashes -r requirements-ci.txt
    if ($LASTEXITCODE -ne 0) {
        throw 'Hash-locked Python dependency installation failed.'
    }
    & $PythonExe -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw 'Python dependency consistency check failed.'
    }
    & $PythonExe scripts\run_offline_tests.py --distribution
    if ($LASTEXITCODE -ne 0) {
        throw 'Final distribution offline smoke tests failed.'
    }
}
finally {
    Pop-Location
}

$UniversePath = Join-Path $UserConfigRoot 'research-universe.local.json'
$PreferencesPath = Join-Path $UserConfigRoot 'user-preferences.local.json'
if (-not (Test-Path -LiteralPath $UniversePath -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path $ApplicationRoot 'config\research-unive.example.json') -Destination $UniversePath
}
if (-not (Test-Path -LiteralPath $PreferencesPath -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path $ApplicationRoot 'config\user-preferences.example.json') -Destination $PreferencesPath
}

$metadata = Get-Content -LiteralPath (Join-Path $ApplicationRoot 'release-metadata.json') -Raw -Encoding utf8 | ConvertFrom-Json
$state = [ordered]@{
    schema_version = 1
    version = $Version
    source_commit = [string]$metadata.source_commit
    installed_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    application_root = $ApplicationRoot
    python_executable = $PythonExe
    user_config_root = $UserConfigRoot
    schedules_enabled = $false
    line_enabled = $false
    ibkr_readonly_enabled = $false
    billing_enabled = $false
}
$state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8

if ($CreateDesktopShortcut) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    New-DesktopShortcut -ApplicationRoot $ApplicationRoot -ShortcutPath (Join-Path $desktop 'Investor Intelligence.lnk')
}

Write-Host ''
Write-Host "Investor Intelligence v$Version installed and verified." -ForegroundColor Green
Write-Host "Application: $ApplicationRoot" -ForegroundColor Cyan
Write-Host "Local configuration: $UserConfigRoot" -ForegroundColor Cyan
Write-Host 'LINE, Cloudflare deployment, schedules, memory, IBKR and billing remain disabled.' -ForegroundColor Green
Write-Host "Run: powershell -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $ApplicationRoot 'run-local.ps1')`"" -ForegroundColor White
exit 0
