param(
    [string]$DestinationPath = '',
    [switch]$ExportGitHubEnvironment
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

$PythonVersion = '3.12.10'
$PythonArchiveName = 'python-3.12.10-embed-amd64.zip'
$PythonArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/$PythonArchiveName"
$PythonArchiveSha256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'

$PipVersion = '26.1.2'
$PipWheelName = 'pip-26.1.2-py3-none-any.whl'
$PipWheelUrl = 'https://files.pythonhosted.org/packages/5d/95/6b5cb3461ea5673ba0995989746db58eb18b91b54dbf331e72f569540946/pip-26.1.2-py3-none-any.whl'
$PipWheelSha256 = '382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab'

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Path))
}

function Download-VerifiedFile {
    param(
        [Parameter(Mandatory = $true)][uri]$Uri,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )

    $parent = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue

    Invoke-WebRequest `
        -Uri $Uri `
        -OutFile $OutputPath `
        -MaximumRedirection 5 `
        -Headers @{ 'User-Agent' = 'investor-intelligence-ci-portable-python/1' }

    $actual = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
        throw "SHA-256 verification failed for $($Uri.AbsoluteUri). Expected $ExpectedSha256, received $actual."
    }
}

function Expand-ZipVerified {
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][string]$OutputDirectory
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
    [System.IO.Compression.ZipFile]::ExtractToDirectory($ArchivePath, $OutputDirectory, $true)
}

if ([string]::IsNullOrWhiteSpace($DestinationPath)) {
    $base = if (-not [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
        $env:RUNNER_TEMP
    }
    else {
        Join-Path ([System.IO.Path]::GetTempPath()) 'investor-intelligence-ci'
    }
    $DestinationPath = Join-Path $base "portable-python-$PythonVersion-x64"
}

$DestinationPath = Resolve-FullPath -Path $DestinationPath
$downloadDirectory = Join-Path (Split-Path -Parent $DestinationPath) '.portable-python-downloads'
$pythonArchive = Join-Path $downloadDirectory $PythonArchiveName
$pipWheel = Join-Path $downloadDirectory $PipWheelName

Remove-Item -LiteralPath $DestinationPath -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $downloadDirectory -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $downloadDirectory | Out-Null

try {
    Download-VerifiedFile -Uri $PythonArchiveUrl -OutputPath $pythonArchive -ExpectedSha256 $PythonArchiveSha256
    Expand-ZipVerified -ArchivePath $pythonArchive -OutputDirectory $DestinationPath

    $pythonExe = Join-Path $DestinationPath 'python.exe'
    $pthFile = Join-Path $DestinationPath 'python312._pth'
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw 'Portable CPython archive did not contain python.exe.'
    }
    if (-not (Test-Path -LiteralPath $pthFile -PathType Leaf)) {
        throw 'Portable CPython archive did not contain python312._pth.'
    }

    $sitePackages = Join-Path $DestinationPath 'Lib\site-packages'
    New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

    $pthLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in [System.IO.File]::ReadAllLines($pthFile)) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '#import site') {
            continue
        }
        if ($trimmed -eq 'import site') {
            continue
        }
        if ($trimmed -eq 'Lib\site-packages') {
            continue
        }
        $pthLines.Add($line)
    }
    $pthLines.Add('Lib\site-packages')
    $pthLines.Add('import site')
    [System.IO.File]::WriteAllLines($pthFile, $pthLines, [System.Text.UTF8Encoding]::new($false))

    Download-VerifiedFile -Uri $PipWheelUrl -OutputPath $pipWheel -ExpectedSha256 $PipWheelSha256
    Expand-ZipVerified -ArchivePath $pipWheel -OutputDirectory $sitePackages

    & $pythonExe -c "import pathlib,struct,sys; assert sys.version_info[:3] == (3,12,10); assert struct.calcsize('P') * 8 == 64; import pip; assert pip.__version__ == '26.1.2'; print(sys.version); print(pathlib.Path(sys.executable).resolve()); print('pip', pip.__version__)"
    if ($LASTEXITCODE -ne 0) {
        throw 'Portable Python or pip validation failed.'
    }

    if ($ExportGitHubEnvironment) {
        if ([string]::IsNullOrWhiteSpace($env:GITHUB_ENV)) {
            throw 'ExportGitHubEnvironment was requested outside GitHub Actions.'
        }
        "PROJECT_PYTHON=$pythonExe" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
        "PORTABLE_PYTHON_HOME=$DestinationPath" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
    }

    Write-Host "Portable Python $PythonVersion with pip $PipVersion is ready."
    Write-Output $pythonExe
}
finally {
    Remove-Item -LiteralPath $downloadDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
