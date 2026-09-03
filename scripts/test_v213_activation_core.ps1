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
    'Invoke-WranglerCapture'
)) {
    if (-not $core.Contains($marker)) { throw "Activation core contract marker is missing: $marker" }
}
if ($core.Contains('$name:')) { throw 'Activation core contains unsafe variable-colon interpolation.' }
if ($core -match '(?m)^\s*\$wrangler\s*=\s*Join-Path.*node_modules\\\.bin\\wrangler\.cmd') {
    throw 'Activation core still launches Wrangler through the Windows batch shim.'
}

# Load the exact production helper functions, but do not enter any activation
# mutation path.  This exercises the same parser and ProcessStartInfo code used
# by formal activation.
$functionStart = $core.IndexOf('function Get-PropertyValue',[StringComparison]::Ordinal)
$selfTestStart = $core.IndexOf('if ($SelfTest) {',[StringComparison]::Ordinal)
if ($functionStart -lt 0 -or $selfTestStart -le $functionStart) {
    throw 'Unable to isolate activation-core helper functions for external testing.'
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
Invoke-Expression $core.Substring($functionStart,$selfTestStart-$functionStart)

$wranglerCommand = Resolve-WranglerCommand (Join-Path $ProjectRoot 'cloud')
if ([IO.Path]::GetFileName([string]$wranglerCommand.Executable) -ine 'node.exe') { throw 'Wrangler is not resolved through node.exe.' }
if ([IO.Path]::GetFileName([string]$wranglerCommand.PrefixArguments[0]) -ine 'wrangler.js') { throw 'Wrangler JavaScript entrypoint was not resolved.' }

$version = '12345678-1234-1234-1234-123456789abc'
$json = '{"versions":[{"version_id":"' + $version + '","percentage":100}],"annotations":{"message":"brace { value } and escaped quote \" preserved"}}'
$jsonBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
$testRoot = Join-Path $env:TEMP ('ii-v213-wrangler-json-external-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
$testScript = Join-Path $testRoot 'emit-wrangler-output.js'
$nodeSource = @(
    "const payload = Buffer.from('$jsonBase64', 'base64').toString('utf8');",
    "process.stdout.write('wrangler 4.123.0\\n');",
    "process.stdout.write(payload + '\\n');",
    "process.stderr.write('search...\\n');",
    'process.exit(0);'
) -join "`r`n"
[IO.File]::WriteAllText($testScript,$nodeSource,[Text.UTF8Encoding]::new($false))
try {
    $captured = Invoke-NativeCapture ([string]$wranglerCommand.Executable) @($testScript) $testRoot
    if ($captured.ExitCode -ne 0) {
        throw "Native capture regression process failed; exit=$($captured.ExitCode); stdout=$($captured.Stdout); stderr=$($captured.Stderr)"
    }
    if ($captured.Stderr -notmatch 'search\.\.\.') { throw 'Native stderr was not captured separately.' }
    if ($captured.Stdout -match 'search\.\.\.') { throw 'Native stderr contaminated stdout.' }
    if ($captured.Stdout -notmatch '(?m)^wrangler 4\.123\.0\s*$') { throw 'Human-readable Wrangler banner was not emitted.' }
    if ((Get-SingleActiveVersion $captured.Stdout) -ne $version) { throw 'Mixed-stdout deployment JSON extraction failed.' }

    $ansiBanner = ([string][char]27) + '[36mwrangler 4.123.0' + ([string][char]27) + '[0m'
    if ((Get-SingleActiveVersion ($ansiBanner + "`r`n" + $json)) -ne $version) { throw 'ANSI banner deployment JSON extraction failed.' }

    $ambiguousRejected = $false
    try { [void](Get-SingleActiveVersion ($json + "`r`n" + $json)) }
    catch { $ambiguousRejected = $_.Exception.Message -match 'multiple deployment JSON documents' }
    if (-not $ambiguousRejected) { throw 'Ambiguous deployment JSON documents were not rejected.' }

    $missingRejected = $false
    try { [void](Get-SingleActiveVersion 'wrangler 4.123.0') }
    catch { $missingRejected = $_.Exception.Message -match 'did not contain a deployment JSON document' }
    if (-not $missingRejected) { throw 'Missing deployment JSON document was not rejected.' }

    $powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
    & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $clientPath -ProjectRoot $ProjectRoot -SelfTest
    if ($LASTEXITCODE -ne 0) { throw 'Activation transaction client self-test failed.' }
}
finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host 'V213_ACTIVATION_CORE_EXTERNAL_SELF_TEST = PASS; production_helpers_loaded=true; node_process_class=true; direct_node=true; mixed_stdout_banner=true; ansi_banner=true; ambiguous_json_rejected=true; stderr_isolated=true; exact_version=true; transaction_client=true' -ForegroundColor Green
