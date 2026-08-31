[CmdletBinding()]
param(
    [string]$BaseInstallRoot = '',
    [switch]$CreateDesktopShortcut,
    [switch]$Force,
    [switch]$ValidateOnly,
    [switch]$SkipSecContactConfiguration
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

$Version = '2.1.0'
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
        if (
            $Source.IndexOf($fragment, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $Destination.IndexOf($fragment, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        ) {
            throw 'Installation inside a GitHub Actions runner workspace is forbidden.'
        }
    }
}

function Assert-RequiredSourceFiles {
    param([Parameter(Mandatory = $true)][string]$Root)

    $required = @(
        'README.md',
        'README.zh-TW.md',
        'release-metadata.json',
        'requirements-ci.txt',
        'launcher\InvestorIntelligenceLauncher.cs',
        'scripts\bootstrap_portable_python.ps1',
        'scripts\run_offline_tests.py',
        'scripts\v21_serenity_top20.py',
        'scripts\build_v21_public_snapshot.py',
        'config\v21-serenity-policy.json',
        'config\v21-source-activation.json',
        'cloud\src\v21\worker.ts',
        'cloud\wrangler.v21.production.template.toml',
        'run-local.ps1',
        'register-task.ps1',
        'setup-v21-owner-line.ps1',
        'sync-v21-public-snapshot.ps1',
        'uninstall.ps1'
    )
    foreach ($relative in $required) {
        $path = Join-Path $Root $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required v2.1 final-release file is missing: $relative"
        }
    }

    $metadata = Get-Content -LiteralPath (Join-Path $Root 'release-metadata.json') `
        -Raw -Encoding utf8 | ConvertFrom-Json
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
        foreach ($relative in @('data', 'reports', 'v21_pipeline.log', 'daily_briefing.log')) {
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

function Resolve-CSharpCompiler {
    $candidates = @(
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    throw 'Windows .NET Framework C# compiler csc.exe is unavailable.'
}

function Build-Launcher {
    param([Parameter(Mandatory = $true)][string]$ApplicationRoot)

    $source = Join-Path $ApplicationRoot 'launcher\InvestorIntelligenceLauncher.cs'
    $output = Join-Path $ApplicationRoot 'InvestorIntelligence.exe'
    $compiler = Resolve-CSharpCompiler
    & $compiler `
        '/nologo' `
        '/target:winexe' `
        '/platform:anycpu' `
        '/optimize+' `
        '/reference:System.dll' `
        '/reference:System.Core.dll' `
        '/reference:System.Windows.Forms.dll' `
        "/out:$output" `
        $source
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $output -PathType Leaf)) {
        throw 'Investor Intelligence EXE compilation failed.'
    }
    & $output '--self-test'
    if ($LASTEXITCODE -ne 0) {
        throw 'Investor Intelligence EXE self-test failed.'
    }
    return $output
}

function New-DesktopShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$LauncherPath,
        [Parameter(Mandatory = $true)][string]$ApplicationRoot,
        [Parameter(Mandatory = $true)][string]$ShortcutPath
    )

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $LauncherPath
    $shortcut.Arguments = ''
    $shortcut.WorkingDirectory = $ApplicationRoot
    $shortcut.Description = "Investor Intelligence v$Version"
    $shortcut.Save()
}

function Configure-SecContact {
    param(
        [Parameter(Mandatory = $true)][string]$UserConfigRoot,
        [switch]$Skip
    )
    $path = Join-Path $UserConfigRoot 'sec-contact.local.txt'
    if ($Skip -or (Test-Path -LiteralPath $path -PathType Leaf)) {
        return $path
    }

    $secure = Read-Host 'SEC Fair Access contact email（隱藏輸入）' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $plain = ''
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ($plain -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
            throw 'SEC Fair Access contact email format is invalid.'
        }
        ConvertFrom-SecureString -SecureString $secure |
            Set-Content -LiteralPath $path -Encoding UTF8
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
        $plain = $null
    }
    return $path
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
    Write-Host "FINAL INSTALLER VALIDATION PASSED: v$Version, no manual ticker configuration, EXE source and v2.1 delivery files present." -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Force -Path $BaseInstallRoot,$UserConfigRoot | Out-Null
Copy-FinalReleaseTree `
    -Source $SourceRoot `
    -Destination $ApplicationRoot `
    -UpgradeStagingRoot $UpgradeStagingRoot `
    -Replace:$Force
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
    & $PythonExe -m pip install `
        --isolated `
        --disable-pip-version-check `
        --only-binary=:all: `
        --index-url https://pypi.org/simple `
        --require-hashes `
        -r requirements-ci.txt
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
    & $PythonExe scripts\v21_serenity_top20.py --self-test
    if ($LASTEXITCODE -ne 0) {
        throw 'Serenity-first v2.1 distribution self-test failed.'
    }
    & $PythonExe scripts\build_v21_public_snapshot.py --self-test
    if ($LASTEXITCODE -ne 0) {
        throw 'V2.1 public snapshot distribution self-test failed.'
    }
}
finally {
    Pop-Location
}

$LauncherExe = Build-Launcher -ApplicationRoot $ApplicationRoot
$SecContactPath = Configure-SecContact `
    -UserConfigRoot $UserConfigRoot `
    -Skip:$SkipSecContactConfiguration

$metadata = Get-Content -LiteralPath (Join-Path $ApplicationRoot 'release-metadata.json') `
    -Raw -Encoding utf8 | ConvertFrom-Json
$state = [ordered]@{
    schema_version = 1
    version = $Version
    source_commit = [string]$metadata.source_commit
    installed_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    application_root = $ApplicationRoot
    python_executable = $PythonExe
    launcher_executable = $LauncherExe
    user_config_root = $UserConfigRoot
    manual_ticker_configuration_required = $false
    sec_contact_configured = (Test-Path -LiteralPath $SecContactPath -PathType Leaf)
    schedules_enabled = $false
    local_refresh_times = @('07:20', '20:20')
    line_push_times = @('08:00 Asia/Taipei', '21:00 Asia/Taipei')
    line_enabled = $false
    cloudflare_deployed = $false
    ibkr_readonly_enabled = $false
    billing_enabled = $false
}
$state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StatePath -Encoding UTF8

if ($CreateDesktopShortcut) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    New-DesktopShortcut `
        -LauncherPath $LauncherExe `
        -ApplicationRoot $ApplicationRoot `
        -ShortcutPath (Join-Path $desktop 'Investor Intelligence v2.1.lnk')
}

Write-Host ''
Write-Host "Investor Intelligence v$Version installed and verified." -ForegroundColor Green
Write-Host "Application: $ApplicationRoot" -ForegroundColor Cyan
Write-Host "Launcher: $LauncherExe" -ForegroundColor Cyan
Write-Host 'Manual ticker configuration: NOT REQUIRED' -ForegroundColor Green
Write-Host 'Local refresh defaults: 07:20 and 20:20; schedules remain disabled until explicitly enabled.' -ForegroundColor Green
Write-Host 'Owner LINE push: 08:00 and 21:00 Asia/Taipei after explicit production setup.' -ForegroundColor Green
Write-Host 'LINE/Cloudflare, IBKR, billing and automatic trading remain disabled.' -ForegroundColor Green
exit 0
