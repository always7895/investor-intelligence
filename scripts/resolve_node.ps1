param(
    [string]$MinimumVersion = "20.0.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-NodeCandidate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodePath,
        [string]$NpmPath
    )

    if (-not (Test-Path -LiteralPath $NodePath -PathType Leaf)) {
        return $null
    }
    if (-not $NpmPath -or -not (Test-Path -LiteralPath $NpmPath -PathType Leaf)) {
        return $null
    }
    try {
        $nodeVersion = & $NodePath --version 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $nodeVersion) {
            return $null
        }
        $actual = [version]($nodeVersion.TrimStart('v'))
        if ($actual -lt [version]$MinimumVersion) {
            return $null
        }
        $npmVersion = & $NpmPath --version 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $npmVersion) {
            return $null
        }
        return [pscustomobject]@{
            Node = (Resolve-Path -LiteralPath $NodePath).Path
            Npm = (Resolve-Path -LiteralPath $NpmPath).Path
            NodeVersion = $actual
            NpmVersion = $npmVersion.Trim()
        }
    }
    catch {
        return $null
    }
}

$candidates = New-Object System.Collections.Generic.List[object]

if ($env:NODE_FOR_RUNNER) {
    $node = $env:NODE_FOR_RUNNER
    $npm = if ($env:NPM_FOR_RUNNER) {
        $env:NPM_FOR_RUNNER
    } else {
        Join-Path (Split-Path $node) "npm.cmd"
    }
    $candidates.Add([pscustomobject]@{ Node = $node; Npm = $npm })
}

Get-Command node.exe -All -ErrorAction SilentlyContinue | ForEach-Object {
    $directory = Split-Path $_.Source
    $candidates.Add([pscustomobject]@{
        Node = $_.Source
        Npm = (Join-Path $directory "npm.cmd")
    })
}

foreach ($directory in @(
    "C:\Program Files\nodejs",
    "C:\Program Files (x86)\nodejs",
    "C:\nodejs"
)) {
    $candidates.Add([pscustomobject]@{
        Node = (Join-Path $directory "node.exe")
        Npm = (Join-Path $directory "npm.cmd")
    })
}

Get-ChildItem "C:\Users\*\AppData\Local\Programs\nodejs\node.exe" -ErrorAction SilentlyContinue |
    ForEach-Object {
        $directory = Split-Path $_.FullName
        $candidates.Add([pscustomobject]@{
            Node = $_.FullName
            Npm = (Join-Path $directory "npm.cmd")
        })
    }

$resolved = $null
foreach ($candidate in $candidates) {
    $result = Test-NodeCandidate -NodePath $candidate.Node -NpmPath $candidate.Npm
    if ($result) {
        $resolved = $result
        break
    }
}

if (-not $resolved) {
    throw @"
No service-accessible Node.js $MinimumVersion+ installation with npm was found.
Install the current Node.js LTS for all users, or configure machine-level NODE_FOR_RUNNER and NPM_FOR_RUNNER paths.
Do not place credentials in these variables.
"@
}

$nodeDirectory = Split-Path $resolved.Node
$env:PATH = "$nodeDirectory;$env:PATH"

if ($env:GITHUB_ENV) {
    # A package must not dirty its exact checkout through ambient npm exports.
    # Validate before writing any job environment/path records; no local fallback.
    if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP) -or $env:RUNNER_TEMP -match '[\x00-\x1f]' -or
        $env:RUNNER_TEMP -notmatch '^[A-Za-z]:[\\/]') { throw 'CI_NPM_TEMP_ROOT_INVALID' }
    $cacheTemp = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd([char[]]'\/')
    $cacheSource = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd([char[]]'\/')
    if (-not (Test-Path -LiteralPath $cacheTemp -PathType Container) -or
        $cacheTemp.Equals($cacheSource,[StringComparison]::OrdinalIgnoreCase) -or
        $cacheTemp.StartsWith($cacheSource+'\',[StringComparison]::OrdinalIgnoreCase)) {
        throw 'CI_NPM_TEMP_ROOT_INVALID'
    }
    $cachePath = Join-Path $cacheTemp ('ii-npm-cache-'+[guid]::NewGuid().ToString('N'))
    "PROJECT_NODE=$($resolved.Node)" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
    "PROJECT_NPM=$($resolved.Npm)" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
    "$nodeDirectory" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
    "NPM_CONFIG_CACHE=$cachePath" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
}

Write-Host "Using Node $($resolved.NodeVersion) at $($resolved.Node)"
Write-Host "Using npm $($resolved.NpmVersion) at $($resolved.Npm)"
