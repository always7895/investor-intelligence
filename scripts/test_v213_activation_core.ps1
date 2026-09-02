[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$corePath = Join-Path $ProjectRoot 'activate-v213-seven-field-schedule-core.ps1'
$clientPath = Join-Path $ProjectRoot 'sync-v213-activation-bundle.ps1'
foreach ($path in @($corePath, $clientPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Activation test prerequisite is missing: $path"
    }
}

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    $corePath,
    [ref]$tokens,
    [ref]$errors)
if ($errors.Count) {
    $errors | Out-String | Write-Host
    throw 'Activation core has PowerShell parser errors.'
}
$core = Get-Content -LiteralPath $corePath -Raw -Encoding utf8
foreach ($marker in @(
    'V213_ATOMIC_DATA_COMMIT = PASS',
    'V213_ACTIVATION_POINTER_ROLLBACK = PASS',
    'V213_ACTIVATION_WORKER_ROLLBACK = PASS',
    'sync-v213-activation-bundle.ps1',
    'pointer_written_last=true',
    "-Action Commit",
    "-Action Rollback",
    "-Action Finalize"
)) {
    if (-not $core.Contains($marker)) {
        throw "Activation core contract marker is missing: $marker"
    }
}
if ($core.Contains('$name:')) {
    throw 'Activation core contains unsafe variable-colon interpolation.'
}

$version = '12345678-1234-1234-1234-123456789abc'
$json = '{"versions":[{"version_id":"' + $version + '","percentage":100}]}'
$escapedJson = $json.Replace("'", "''")
$childScript = @(
    '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)',
    "[Console]::Error.WriteLine('search...')",
    "[Console]::Out.WriteLine('$escapedJson')",
    'exit 0'
) -join ';'
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($childScript))
$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$utf8 = New-Object System.Text.UTF8Encoding($false)
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $powershell
$psi.Arguments = '-NoProfile -NonInteractive -EncodedCommand ' + $encoded
$psi.WorkingDirectory = $ProjectRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = $utf8
$psi.StandardErrorEncoding = $utf8
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $psi
if (-not $process.Start()) {
    throw 'Unable to start the activation capture probe.'
}
$stdoutTask = $process.StandardOutput.ReadToEndAsync()
$stderrTask = $process.StandardError.ReadToEndAsync()
$process.WaitForExit()
$stdout = [string]$stdoutTask.GetAwaiter().GetResult()
$stderr = [string]$stderrTask.GetAwaiter().GetResult()
$exitCode = $process.ExitCode
$process.Dispose()
if ($exitCode -ne 0) {
    throw "Activation capture probe exited with $exitCode. stderr=$stderr"
}
if ($stderr -notmatch 'search\.\.\.') {
    throw 'Activation capture probe did not produce the expected stderr noise.'
}
if ($stdout -match 'search\.\.\.') {
    throw 'Activation capture probe mixed stderr into stdout.'
}
try {
    $document = $stdout.Trim().TrimStart([char]0xFEFF) | ConvertFrom-Json
}
catch {
    throw "Activation capture stdout is not valid JSON: $stdout"
}
$versions = @($document.versions)
if ($versions.Count -ne 1 -or [string]$versions[0].version_id -ne $version) {
    throw 'Activation capture did not preserve the exact Worker version ID.'
}
$percentage = 0.0
if (-not [double]::TryParse([string]$versions[0].percentage, [ref]$percentage) -or [Math]::Abs($percentage - 100.0) -gt 0.001) {
    throw 'Activation capture did not preserve 100% traffic.'
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $clientPath -ProjectRoot $ProjectRoot -SelfTest
if ($LASTEXITCODE -ne 0) {
    throw 'Activation transaction client self-test failed.'
}
Write-Host 'V213_ACTIVATION_CORE_EXTERNAL_SELF_TEST = PASS; stderr_isolated=true; exact_version=true; transaction_client=true' -ForegroundColor Green
