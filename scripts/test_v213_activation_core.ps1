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
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Activation test prerequisite is missing: $path" }
}

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($corePath,[ref]$tokens,[ref]$errors)
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
    '-Action Commit',
    '-Action Rollback',
    '-Action Finalize',
    'Get-BalancedJsonDocumentEnd',
    'multiple deployment JSON documents',
    'node_modules\wrangler\bin\wrangler.js',
    'V213_WRANGLER_INVOCATION = DIRECT_NODE',
    'Invoke-WranglerCapture',
    'mixed_stdout_banner=true',
    'ambiguous_json_rejected=true'
)) {
    if (-not $core.Contains($marker)) { throw "Activation core contract marker is missing: $marker" }
}
if ($core.Contains('$name:')) { throw 'Activation core contains unsafe variable-colon interpolation.' }
if ($core -match "(?m)^\s*\$wrangler\s*=\s*Join-Path.*node_modules\\\.bin\\wrangler\.cmd") {
    throw 'Activation core still launches Wrangler through the Windows batch shim.'
}

$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $corePath -ProjectRoot $ProjectRoot -SelfTest
if ($LASTEXITCODE -ne 0) { throw 'Activation core mixed-stdout self-test failed.' }

& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $clientPath -ProjectRoot $ProjectRoot -SelfTest
if ($LASTEXITCODE -ne 0) { throw 'Activation transaction client self-test failed.' }
Write-Host 'V213_ACTIVATION_CORE_EXTERNAL_SELF_TEST = PASS; direct_node=true; mixed_stdout_banner=true; ansi_banner=true; ambiguous_json_rejected=true; stderr_isolated=true; exact_version=true; transaction_client=true' -ForegroundColor Green
