param(
    [string]$VenvPath = ".venv-ci",
    [string]$MinimumVersion = "3.10",
    [string]$BasePython = "",
    [switch]$InstallLockedDependencies
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# GitHub Actions uses one reviewed, hash-verified CPython build so the committed
# Windows wheel hashes remain reproducible even when machine-wide Python changes.
# Non-CI/local callers retain the generic discovery and virtual-environment path;
# -InstallLockedDependencies makes a local environment reproduce the CI lock.
if ($env:GITHUB_ACTIONS -eq "true") {
    $bootstrapScript = Join-Path $PSScriptRoot "bootstrap_portable_python.ps1"
    if (-not (Test-Path -LiteralPath $bootstrapScript -PathType Leaf)) {
        throw "Verified portable Python bootstrap is missing: $bootstrapScript"
    }
    if ([string]::IsNullOrWhiteSpace($env:GITHUB_ENV)) {
        throw "GITHUB_ENV is required for deterministic CI Python bootstrap."
    }

    $runtimeRoot = if (-not [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
        $env:RUNNER_TEMP
    }
    else {
        Join-Path ([System.IO.Path]::GetTempPath()) "investor-intelligence-ci"
    }
    $runtimeName = [regex]::Replace(
        [System.IO.Path]::GetFileName($VenvPath),
        "[^A-Za-z0-9_.-]",
        "-"
    )
    if ([string]::IsNullOrWhiteSpace($runtimeName)) {
        $runtimeName = "default"
    }
    $destination = Join-Path $runtimeRoot "portable-python-3.12.10-$runtimeName"

    & $bootstrapScript -DestinationPath $destination -ExportGitHubEnvironment

    $projectLine = Get-Content -LiteralPath $env:GITHUB_ENV |
        Where-Object { $_ -like "PROJECT_PYTHON=*" } |
        Select-Object -Last 1
    if (-not $projectLine) {
        throw "Portable Python bootstrap did not export PROJECT_PYTHON."
    }
    $pythonExe = $projectLine.Substring("PROJECT_PYTHON=".Length)
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw "Portable Python executable is unavailable after bootstrap."
    }

    # Scripts imported by package/integration tests use the same reviewed runtime
    # dependencies as the actual local refresh. Install only from the committed,
    # hash-locked requirements file; never resolve an unpinned package here.
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $requirements = Join-Path $projectRoot "requirements-ci.txt"
    if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
        throw "Hash-locked CI requirements are missing: $requirements"
    }
    $requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash.ToLowerInvariant()
    $requirementsMarker = Join-Path $destination (".investor-intelligence-requirements-" + $requirementsHash + ".ok")
    if (-not (Test-Path -LiteralPath $requirementsMarker -PathType Leaf)) {
        & $pythonExe -m pip install --isolated --disable-pip-version-check `
            --only-binary=:all: --index-url https://pypi.org/simple `
            --require-hashes -r $requirements
        if ($LASTEXITCODE -ne 0) {
            throw "Hash-locked CI dependency installation failed."
        }
        & $pythonExe -m pip check
        if ($LASTEXITCODE -ne 0) {
            throw "CI pip check failed."
        }
        Set-Content -LiteralPath $requirementsMarker -Value $requirementsHash -Encoding ascii
    }

    $env:PROJECT_PYTHON = $pythonExe
    if ($env:GITHUB_OUTPUT) {
        "python=$pythonExe" | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
    }
    Write-Host "PROJECT_PYTHON configured from reviewed portable CPython 3.12.10 with hash-locked dependencies."
    return
}

# Local callers. Generic mode accepts any 64-bit Python >= MinimumVersion and
# installs nothing. -InstallLockedDependencies accepts only the approved CPython
# 3.12.10 (the interpreter requirements-ci.txt carries Windows wheel hashes for),
# then installs that lock and runs pip check on every call. An existing
# destination is reused only when it is a compatible virtual environment;
# anything else fails and is never deleted or replaced. PROJECT_PYTHON is set in
# the calling process only after every requested check has passed, and a stale
# value never survives a failed resolution.
$ApprovedLockedVersion = [version]"3.12.10"
Remove-Item -LiteralPath Env:PROJECT_PYTHON -ErrorAction SilentlyContinue

$projectRoot = Split-Path -Parent $PSScriptRoot
$requirements = Join-Path $projectRoot "requirements-ci.txt"
if ($InstallLockedDependencies -and -not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
    throw "Hash-locked requirements are missing: $requirements"
}
$requirement = if ($InstallLockedDependencies) {
    "approved 64-bit CPython $ApprovedLockedVersion"
}
else {
    "64-bit Python $MinimumVersion+"
}

function Get-PythonProbe {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }

    try {
        $probe = & $Path -c "import json,platform,sys; print(json.dumps({'version': list(sys.version_info[:3]), 'bits': platform.architecture()[0], 'executable': sys.executable, 'prefix': sys.prefix, 'venv': sys.prefix != sys.base_prefix, 'implementation': sys.implementation.name}))" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $probe) {
            return $null
        }
        $info = ($probe | Select-Object -Last 1) | ConvertFrom-Json
        return [pscustomobject]@{
            Path = [string]$info.executable
            Version = [version]("{0}.{1}.{2}" -f $info.version[0], $info.version[1], $info.version[2])
            Bits = [string]$info.bits
            Prefix = [string]$info.prefix
            IsVenv = [bool]$info.venv
            Implementation = [string]$info.implementation
        }
    }
    catch {
        return $null
    }
}

function Test-InterpreterAccepted {
    param($Info)

    if ($null -eq $Info -or $Info.Bits -ne "64bit") {
        return $false
    }
    if ($InstallLockedDependencies) {
        return $Info.Implementation -eq "cpython" -and $Info.Version -eq $ApprovedLockedVersion
    }
    return $Info.Version -ge [version]$MinimumVersion
}

function Get-NormalizedPath {
    param([string]$Path)

    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    if ($full.Length -gt $root.Length) {
        $full = $full.TrimEnd([char[]]@('\', '/'))
    }
    return $full
}

function Test-PathWithin {
    # True when $Path equals $Container or lies below it.
    param([string]$Path, [string]$Container)

    $p = Get-NormalizedPath $Path
    $c = Get-NormalizedPath $Container
    if ([string]::Equals($p, $c, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $prefix = if ($c.EndsWith("\")) { $c } else { $c + "\" }
    return $p.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

$location = $ExecutionContext.SessionState.Path.CurrentFileSystemLocation.ProviderPath
if ([string]::IsNullOrWhiteSpace($VenvPath)) {
    throw "VenvPath must not be empty."
}
$venvFullPath = if ([System.IO.Path]::IsPathRooted($VenvPath)) {
    Get-NormalizedPath $VenvPath
}
else {
    Get-NormalizedPath (Join-Path $location $VenvPath)
}

# Refuse destinations that are, or contain, the checkout, the current directory,
# a drive root or a well-known profile/system directory.
$protected = New-Object System.Collections.Generic.List[string]
$protected.Add($projectRoot)
$protected.Add($location)
foreach ($name in @("USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "PUBLIC")) {
    $value = [System.Environment]::GetEnvironmentVariable($name)
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        $protected.Add($value)
    }
}
if ([string]::Equals($venvFullPath, [System.IO.Path]::GetPathRoot($venvFullPath), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing unsafe virtual-environment destination $venvFullPath (drive root)."
}
foreach ($path in $protected) {
    if (Test-PathWithin -Path $path -Container $venvFullPath) {
        throw "Refusing unsafe virtual-environment destination $venvFullPath (it is or contains $path)."
    }
}

# Never follow a junction or symbolic link at the destination or any ancestor.
$cursor = $venvFullPath
while ($cursor) {
    if (Test-Path -LiteralPath $cursor) {
        $item = Get-Item -LiteralPath $cursor -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Refusing virtual-environment destination $venvFullPath because $cursor is a reparse point."
        }
    }
    $cursor = [System.IO.Path]::GetDirectoryName($cursor)
}

$venvPython = Join-Path $venvFullPath "Scripts\python.exe"

function Test-EnvironmentAccepted {
    param($Info)

    return (Test-InterpreterAccepted $Info) -and $Info.IsVenv -and
        [string]::Equals((Get-NormalizedPath $Info.Prefix), $venvFullPath, [System.StringComparison]::OrdinalIgnoreCase)
}

$createEnvironment = $true
if (Test-Path -LiteralPath $venvFullPath) {
    if (-not (Test-Path -LiteralPath $venvFullPath -PathType Container)) {
        throw "Virtual-environment destination $venvFullPath exists and is not a directory; it was left untouched."
    }
    # Any existing directory, even an empty one, must already be a compatible venv.
    $createEnvironment = $false
    $existing = $null
    if (Test-Path -LiteralPath (Join-Path $venvFullPath "pyvenv.cfg") -PathType Leaf) {
        $existing = Get-PythonProbe -Path $venvPython
    }
    if (-not (Test-EnvironmentAccepted $existing)) {
        throw "Existing directory $venvFullPath is not a compatible virtual environment ($requirement); it was left untouched. Choose another -VenvPath, or inspect and remove it yourself."
    }
    Write-Host ("Reusing virtual environment {0} (Python {1})" -f $venvFullPath, $existing.Version)
}

if ($createEnvironment) {
    $candidatePaths = New-Object System.Collections.Generic.List[string]

    if (-not [string]::IsNullOrWhiteSpace($BasePython)) {
        $candidatePaths.Add($BasePython)
    }
    else {
        if ($env:PYTHON_FOR_RUNNER) {
            $candidatePaths.Add($env:PYTHON_FOR_RUNNER)
        }

        foreach ($commandName in @("python.exe", "python3.exe", "py.exe")) {
            Get-Command $commandName -All -ErrorAction SilentlyContinue |
                ForEach-Object {
                    if ($_.Source) {
                        if ($commandName -eq "py.exe") {
                            try {
                                (& $_.Source -0p 2>$null) |
                                    ForEach-Object {
                                        $candidate = ($_ -replace '^\s*-V:[^\s]+\s+', '').Trim()
                                        if ($candidate) {
                                            $candidatePaths.Add($candidate)
                                        }
                                    }
                            }
                            catch { }
                        }
                        else {
                            $candidatePaths.Add($_.Source)
                        }
                    }
                }
        }

        foreach ($path in @(
            "C:\Program Files\Python313\python.exe",
            "C:\Program Files\Python312\python.exe",
            "C:\Program Files\Python311\python.exe",
            "C:\Program Files\Python310\python.exe",
            "C:\Python313\python.exe",
            "C:\Python312\python.exe",
            "C:\Python311\python.exe",
            "C:\Python310\python.exe"
        )) {
            $candidatePaths.Add($path)
        }

        # Discover per-user installations without embedding any person's Windows profile name.
        Get-ChildItem -Path "C:\Users\*\AppData\Local\Programs\Python\Python*\python.exe" -File -ErrorAction SilentlyContinue |
            ForEach-Object { $candidatePaths.Add($_.FullName) }

        # Discover machine-wide PythonCore registry installations.
        foreach ($registryRoot in @(
            "HKLM:\SOFTWARE\Python\PythonCore",
            "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore"
        )) {
            Get-ChildItem -Path $registryRoot -ErrorAction SilentlyContinue |
                ForEach-Object {
                    try {
                        $installPath = (Get-ItemProperty -Path (Join-Path $_.PSPath "InstallPath") -ErrorAction Stop).'(default)'
                        if ($installPath) {
                            $candidatePaths.Add((Join-Path $installPath "python.exe"))
                        }
                    }
                    catch { }
                }
        }
    }

    $resolved = $null
    foreach ($candidate in ($candidatePaths | Select-Object -Unique)) {
        $result = Get-PythonProbe -Path $candidate
        if (Test-InterpreterAccepted $result) {
            $resolved = $result
            break
        }
    }

    if (-not $resolved) {
        throw @"
No service-accessible $requirement installation was found.
Checked -BasePython, or PATH, PYTHON_FOR_RUNNER, py launcher, machine registry and standard installation paths.
Install Python for all users, or set a machine-level PYTHON_FOR_RUNNER variable to an accessible python.exe.
Do not put credentials or user identifiers in this variable or in workflow logs.
"@
    }

    Write-Host ("Using base Python {0} at {1}" -f $resolved.Version, $resolved.Path)

    # Native output goes to the host so callers receive nothing on the success stream.
    & $resolved.Path -m venv --copies $venvFullPath | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment at $venvFullPath"
    }

    $created = Get-PythonProbe -Path $venvPython
    if (-not (Test-EnvironmentAccepted $created)) {
        throw "Virtual-environment Python preflight failed at $venvPython; the new environment was left in place for inspection."
    }
    Write-Host ("Created virtual environment {0} (Python {1}, {2})" -f $venvFullPath, $created.Version, $created.Bits)
}

if ($InstallLockedDependencies) {
    # Same reviewed command as the CI bootstrap: binary-only, explicit PyPI, hashes required.
    & $venvPython -m pip install --isolated --disable-pip-version-check `
        --only-binary=:all: --index-url https://pypi.org/simple `
        --require-hashes -r $requirements | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Hash-locked dependency installation failed; PROJECT_PYTHON was not set."
    }
    & $venvPython -m pip check | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "pip check failed; PROJECT_PYTHON was not set."
    }
}

# Optional GitHub files first: if one cannot be written the call fails with
# PROJECT_PYTHON still unset (an earlier append to the other file is not undone).
if ($env:GITHUB_ENV) {
    "PROJECT_PYTHON=$venvPython" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
}
if ($env:GITHUB_OUTPUT) {
    "python=$venvPython" | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
}
$env:PROJECT_PYTHON = $venvPython

if ($InstallLockedDependencies) {
    Write-Host "PROJECT_PYTHON set to $venvPython with hash-locked dependencies."
}
else {
    Write-Host "PROJECT_PYTHON set to $venvPython (generic mode: no packages installed)."
}
