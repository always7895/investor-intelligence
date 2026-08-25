param(
    [string]$VenvPath = ".venv-ci",
    [string]$MinimumVersion = "3.10"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# GitHub Actions uses one reviewed, hash-verified CPython build so the committed
# Windows wheel hashes remain reproducible even when machine-wide Python changes.
# Non-CI/local callers retain the generic discovery and virtual-environment path.
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

    $env:PROJECT_PYTHON = $pythonExe
    if ($env:GITHUB_OUTPUT) {
        "python=$pythonExe" | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
    }
    Write-Host "PROJECT_PYTHON configured from reviewed portable CPython 3.12.10."
    return
}

function Test-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }

    try {
        $probe = & $Path -c "import json,platform,sys; print(json.dumps({'version': list(sys.version_info[:3]), 'bits': platform.architecture()[0], 'executable': sys.executable}))" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $probe) {
            return $null
        }
        $info = $probe | ConvertFrom-Json
        if ($info.bits -ne "64bit") {
            return $null
        }
        $required = [version]$MinimumVersion
        $actual = [version]("{0}.{1}.{2}" -f $info.version[0], $info.version[1], $info.version[2])
        if ($actual -lt $required) {
            return $null
        }
        return [pscustomobject]@{
            Path = [string]$info.executable
            Version = $actual
        }
    }
    catch {
        return $null
    }
}

$candidatePaths = New-Object System.Collections.Generic.List[string]

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

$resolved = $null
foreach ($candidate in ($candidatePaths | Select-Object -Unique)) {
    $result = Test-PythonCandidate -Path $candidate
    if ($result) {
        $resolved = $result
        break
    }
}

if (-not $resolved) {
    throw @"
No service-accessible 64-bit Python $MinimumVersion+ installation was found.
Checked PATH, PYTHON_FOR_RUNNER, py launcher, machine registry and standard installation paths.
Install Python for all users, or set a machine-level PYTHON_FOR_RUNNER variable to an accessible python.exe.
Do not put credentials or user identifiers in this variable or in workflow logs.
"@
}

Write-Host ("Using base Python {0} at {1}" -f $resolved.Version, $resolved.Path)

$venvFullPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $VenvPath))
if (Test-Path -LiteralPath $venvFullPath) {
    Remove-Item -LiteralPath $venvFullPath -Recurse -Force
}

& $resolved.Path -m venv --copies $venvFullPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create virtual environment at $venvFullPath"
}

$venvPython = Join-Path $venvFullPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "Virtual-environment Python not found at $venvPython"
}

& $venvPython -c "import platform,sys; print(sys.version); print(platform.architecture()[0]); print(sys.executable)"
if ($LASTEXITCODE -ne 0) {
    throw "Virtual-environment Python preflight failed"
}

if ($env:GITHUB_ENV) {
    "PROJECT_PYTHON=$venvPython" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
}
if ($env:GITHUB_OUTPUT) {
    "python=$venvPython" | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
}

Write-Host "PROJECT_PYTHON configured for subsequent workflow steps."
