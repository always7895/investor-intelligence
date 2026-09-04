[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [ValidateSet('zh-TW','en','bilingual')][string]$FieldLocale = 'zh-TW',
    [string]$ExpectedModel = '',
    [switch]$ConfirmActivation,
    [switch]$RequireLocalModel,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

function Get-PropertyValue([object]$Object,[string]$Name,[object]$Default=$null) {
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function ConvertTo-NativeArgument([string]$Value) {
    if ($null -eq $Value -or $Value.Length -eq 0) { return '""'.Replace('\','') }
    if ($Value -notmatch '[\s"]') { return $Value }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"'.Replace('\',''))
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') { $slashes++; continue }
        if ($character -eq '"'.Replace('\','')) {
            if ($slashes -gt 0) { [void]$builder.Append(('\' * ($slashes * 2))) }
            [void]$builder.Append('\"')
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) { [void]$builder.Append(('\' * $slashes)); $slashes = 0 }
        [void]$builder.Append($character)
    }
    if ($slashes -gt 0) { [void]$builder.Append(('\' * ($slashes * 2))) }
    [void]$builder.Append('"'.Replace('\',''))
    return $builder.ToString()
}

function Invoke-NativeCapture([string]$Exe,[string[]]$ArgumentList,[string]$Cwd,[string]$InputText='') {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $quotedArgs = ($ArgumentList | ForEach-Object { ConvertTo-NativeArgument ([string]$_) }) -join ' '
    $extension = [IO.Path]::GetExtension($Exe)
    if ($extension -ieq '.cmd' -or $extension -ieq '.bat') {
        $psi.FileName = if ($env:ComSpec) { $env:ComSpec } else { 'cmd.exe' }
        $psi.Arguments = '/d /s /c ""'.Replace('\','') + $Exe + '" '.Replace('\','') + $quotedArgs + '"'.Replace('\','')
    }
    else {
        $psi.FileName = $Exe
        $psi.Arguments = $quotedArgs
    }
    $psi.WorkingDirectory = $Cwd
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.StandardOutputEncoding = $utf8NoBom
    $psi.StandardErrorEncoding = $utf8NoBom
    $psi.EnvironmentVariables['NO_COLOR'] = '1'
    $psi.EnvironmentVariables['CI'] = 'true'
    $psi.EnvironmentVariables['TERM'] = 'dumb'
    $psi.EnvironmentVariables['WRANGLER_SEND_METRICS'] = 'false'
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    if (-not $process.Start()) { throw "Unable to start native command: $Exe" }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if ($InputText) { $process.StandardInput.WriteLine($InputText) }
    $process.StandardInput.Close()
    $process.WaitForExit()
    $result = [pscustomobject]@{
        ExitCode = $process.ExitCode
        Stdout = [string]$stdoutTask.GetAwaiter().GetResult()
        Stderr = [string]$stderrTask.GetAwaiter().GetResult()
    }
    $process.Dispose()
    return $result
}

function Capture([string]$Exe,[string[]]$ArgumentList,[string]$Cwd,[string]$InputText='') {
    $result = Invoke-NativeCapture $Exe $ArgumentList $Cwd $InputText
    if ($result.ExitCode -ne 0) {
        $tail = (($result.Stdout + "`n" + $result.Stderr) -split '\r?\n' | Select-Object -Last 30) -join "`n"
        throw "$Exe failed with exit code $($result.ExitCode)`n$tail"
    }
    return [string]$result.Stdout
}

function Run([string]$Exe,[string[]]$ArgumentList,[string]$Cwd,[string]$InputText='') {
    $result = Invoke-NativeCapture $Exe $ArgumentList $Cwd $InputText
    if ($result.Stdout) { Write-Host $result.Stdout.TrimEnd() }
    if ($result.Stderr) { Write-Host $result.Stderr.TrimEnd() }
    if ($result.ExitCode -ne 0) {
        $tail = (($result.Stdout + "`n" + $result.Stderr) -split '\r?\n' | Select-Object -Last 30) -join "`n"
        throw "$Exe failed with exit code $($result.ExitCode)`n$tail"
    }
    return [string]$result.Stdout
}

function Get-BalancedJsonDocumentEnd([string]$Text,[int]$Start) {
    if ($Start -lt 0 -or $Start -ge $Text.Length) { return -1 }
    $first = $Text[$Start]
    if ($first -ne [char]'{' -and $first -ne [char]'[') { return -1 }
    $closers = New-Object 'System.Collections.Generic.List[char]'
    if ($first -eq [char]'{') { $closers.Add([char]'}') }
    else { $closers.Add([char]']') }
    $inString = $false
    $escaped = $false
    for ($index = $Start + 1; $index -lt $Text.Length; $index++) {
        $character = $Text[$index]
        if ($inString) {
            if ($escaped) { $escaped = $false; continue }
            if ($character -eq [char]'\') { $escaped = $true; continue }
            if ($character -eq [char]'"') { $inString = $false }
            continue
        }
        if ($character -eq [char]'"') { $inString = $true; continue }
        if ($character -eq [char]'{') { $closers.Add([char]'}'); continue }
        if ($character -eq [char]'[') { $closers.Add([char]']'); continue }
        if ($character -eq [char]'}' -or $character -eq [char]']') {
            if ($closers.Count -eq 0 -or $closers[$closers.Count - 1] -ne $character) { return -1 }
            $closers.RemoveAt($closers.Count - 1)
            if ($closers.Count -eq 0) { return $index }
        }
    }
    return -1
}

function Parse-JsonOutput([string]$Raw) {
    if ([string]::IsNullOrWhiteSpace($Raw)) { throw 'Wrangler JSON stdout was empty.' }
    $escape = [regex]::Escape([string][char]27)
    $value = [regex]::Replace($Raw, $escape + '\[[0-?]*[ -/]*[@-~]', '').Trim().TrimStart([char]0xFEFF)
    $deploymentDocuments = @()
    for ($start = 0; $start -lt $value.Length; $start++) {
        if ($value[$start] -ne [char]'{' -and $value[$start] -ne [char]'[') { continue }
        $end = Get-BalancedJsonDocumentEnd $value $start
        if ($end -lt $start) { continue }
        $candidate = $value.Substring($start, $end - $start + 1)
        $document = $null
        try { $document = $candidate | ConvertFrom-Json -ErrorAction Stop }
        catch { continue }
        if ($null -ne $document -and $null -ne $document.PSObject.Properties['versions']) {
            $deploymentDocuments += ,$document
            $start = $end
        }
    }
    if ($deploymentDocuments.Count -eq 0) {
        $preview = [regex]::Replace($value, '[\x00-\x20]+', ' ').Trim()
        if ($preview.Length -gt 240) { $preview = $preview.Substring(0,240) + '...' }
        throw "Wrangler stdout did not contain a deployment JSON document. preview=$preview"
    }
    if ($deploymentDocuments.Count -ne 1) {
        throw "Wrangler stdout contained multiple deployment JSON documents; refusing ambiguous Production state ($($deploymentDocuments.Count))."
    }
    return $deploymentDocuments[0]
}

function Get-SingleActiveVersion([string]$Raw) {
    $root = Parse-JsonOutput $Raw
    $versions = @($root.versions)
    if ($versions.Count -eq 0) { throw 'Wrangler deployment JSON has no versions array.' }
    $active = @($versions | Where-Object {
        $percentage = 0.0
        $parsed = [double]::TryParse(
            [string]$_.percentage,
            [Globalization.NumberStyles]::Float,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$percentage)
        $parsed -and (
            ($percentage -ge 99.999 -and $percentage -le 100.001) -or
            ($percentage -ge .99999 -and $percentage -le 1.00001)
        )
    })
    if ($active.Count -ne 1) { throw "Expected exactly one 100% active Worker version; found $($active.Count)." }
    $version = [string]$active[0].version_id
    if ($version -notmatch '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') {
        throw 'Active Worker version_id is invalid.'
    }
    return $version.ToLowerInvariant()
}

function Resolve-WranglerCommand([string]$CloudRoot) {
    $wranglerCli = Join-Path $CloudRoot 'node_modules\wrangler\bin\wrangler.js'
    if (-not (Test-Path -LiteralPath $wranglerCli -PathType Leaf)) {
        throw 'Pinned Wrangler JavaScript entrypoint is unavailable after npm ci.'
    }
    $nodePath = ''
    if ($env:PROJECT_NODE -and (Test-Path -LiteralPath $env:PROJECT_NODE -PathType Leaf)) {
        $nodePath = (Resolve-Path -LiteralPath $env:PROJECT_NODE).Path
    }
    else {
        $nodeCommand = Get-Command node.exe -ErrorAction Stop | Select-Object -First 1
        $nodePath = (Resolve-Path -LiteralPath $nodeCommand.Source).Path
    }
    return [pscustomobject]@{
        Executable = $nodePath
        PrefixArguments = @((Resolve-Path -LiteralPath $wranglerCli).Path)
    }
}

function Invoke-WranglerCapture([object]$Command,[string[]]$ArgumentList,[string]$Cwd) {
    return Capture ([string]$Command.Executable) (@($Command.PrefixArguments) + @($ArgumentList)) $Cwd
}

function Invoke-WranglerRun([object]$Command,[string[]]$ArgumentList,[string]$Cwd,[string]$InputText='') {
    return Run ([string]$Command.Executable) (@($Command.PrefixArguments) + @($ArgumentList)) $Cwd $InputText
}

function Set-Var([string]$Text,[string]$Key,[string]$Value) {
    $Text = [regex]::Replace($Text, "(?m)^\s*$Key\s*=.*(?:\r?\n)?", '')
    $escaped = $Value.Replace('\','\\').Replace('"','\"')
    return [regex]::Replace($Text, '(?m)^\[vars\]\s*$', "[vars]`r`n$Key = `"$escaped`"", 1)
}

function Remove-Var([string]$Text,[string]$Key) {
    return [regex]::Replace($Text, "(?m)^\s*$Key\s*=.*(?:\r?\n)?", '')
}

function Get-HealthyModelState([string]$Path,[string]$RequiredModel) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try {
        $modelState = Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json
        $publicUrl = [string](Get-PropertyValue $modelState 'public_url' '')
        $allowedHost = [string](Get-PropertyValue $modelState 'allowed_host' '')
        $model = [string](Get-PropertyValue $modelState 'model' '')
        $secret = [string](Get-PropertyValue $modelState 'encrypted_shared_secret' '')
        if (-not $publicUrl -or -not $allowedHost -or -not $model -or -not $secret) { return $null }
        if ((Get-PropertyValue $modelState 'selected_model_verified' $false) -ne $true) { return $null }
        if ($RequiredModel -and $model -ine $RequiredModel) { return $null }
        $connected = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse([string](Get-PropertyValue $modelState 'connected_at' ''), [ref]$connected)) { return $null }
        $age = ([DateTimeOffset]::UtcNow - $connected.ToUniversalTime()).TotalMinutes
        if ($age -lt -5 -or $age -gt 30) { return $null }
        $health = Invoke-RestMethod -Method Get -Uri ($publicUrl.TrimEnd('/') + '/health') -Headers @{'cache-control'='no-cache';'pragma'='no-cache'} -TimeoutSec 20
        if ((Get-PropertyValue $health 'ok' $false) -ne $true) { return $null }
        if ((Get-PropertyValue $health 'llama_reachable' $false) -ne $true) { return $null }
        if ((Get-PropertyValue $health 'selected_model_available' $false) -ne $true) { return $null }
        if ([string](Get-PropertyValue $health 'selected_model' '') -ine $model) { return $null }
        return $modelState
    }
    catch { return $null }
}

function Backup-RefreshTasks {
    $backup = @{}
    foreach ($name in @('InvestorIntelligence-v21-MorningRefresh','InvestorIntelligence-v21-EveningRefresh')) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task) {
            try { $backup[$name] = Export-ScheduledTask -TaskName $name }
            catch { $backup[$name] = $null }
        }
        else { $backup[$name] = $null }
    }
    return $backup
}

function Restore-RefreshTasks([hashtable]$Backup) {
    foreach ($name in @('InvestorIntelligence-v21-MorningRefresh','InvestorIntelligence-v21-EveningRefresh')) {
        try {
            if ($Backup.ContainsKey($name) -and $Backup[$name]) {
                Register-ScheduledTask -TaskName $name -Xml ([string]$Backup[$name]) -Force | Out-Null
            }
            else {
                Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
            }
        }
        catch { Write-Warning "Unable to restore scheduled task ${name}: $($_.Exception.Message)" }
    }
}

if ($SelfTest) {
    if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
    $version = '12345678-1234-1234-1234-123456789abc'
    $json = '{"versions":[{"version_id":"' + $version + '","percentage":100}],"annotations":{"message":"brace { value } and escaped quote \" preserved"}}'
    $testRoot = Join-Path $env:TEMP ('ii-v213-wrangler-json-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
    $testScript = Join-Path $testRoot 'emit.ps1'
    $escapedJson = $json.Replace("'", "''")
    $testBody = @(
        "Write-Output 'wrangler 4.123.0'",
        "Write-Output '$escapedJson'",
        "[Console]::Error.WriteLine('search...')",
        'exit 0'
    ) -join "`r`n"
    [IO.File]::WriteAllText($testScript, $testBody, [Text.UTF8Encoding]::new($false))
    try {
        $powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
        $captured = Invoke-NativeCapture $powershell @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$testScript) $testRoot
        if ($captured.ExitCode -ne 0) { throw 'Native capture self-test process failed.' }
        if ($captured.Stderr -notmatch 'search\.\.\.') { throw 'Native stderr was not captured separately.' }
        if ($captured.Stdout -match 'search\.\.\.') { throw 'Native stderr contaminated stdout.' }
        if ((Get-SingleActiveVersion $captured.Stdout) -ne $version) { throw 'Wrangler mixed-stdout JSON parser self-test failed.' }
        $ansiBanner = ([string][char]27) + '[36mwrangler 4.123.0' + ([string][char]27) + '[0m'
        if ((Get-SingleActiveVersion ($ansiBanner + "`r`n" + $json)) -ne $version) { throw 'ANSI banner parser self-test failed.' }
        $ambiguousRejected = $false
        try { [void](Get-SingleActiveVersion ($json + "`r`n" + $json)) }
        catch { $ambiguousRejected = $_.Exception.Message -match 'multiple deployment JSON documents' }
        if (-not $ambiguousRejected) { throw 'Ambiguous Wrangler JSON documents were not rejected.' }
        $missingRejected = $false
        try { [void](Get-SingleActiveVersion 'wrangler 4.123.0') }
        catch { $missingRejected = $_.Exception.Message -match 'did not contain a deployment JSON document' }
        if (-not $missingRejected) { throw 'Missing Wrangler JSON document was not rejected.' }
        & (Join-Path $ProjectRoot 'sync-v213-activation-bundle.ps1') -SelfTest
        if ($LASTEXITCODE -ne 0) { throw 'Activation transaction client self-test failed.' }
    }
    finally { Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host 'V213_ACTIVATION_CORE_SELF_TEST = PASS; mixed_stdout_banner=true; ansi_banner=true; ambiguous_json_rejected=true; json_stderr_isolated=true; pointer_transaction=commit_rollback_finalize' -ForegroundColor Green
    exit 0
}

if (-not $ConfirmActivation) { throw 'Formal scheduled activation requires -ConfirmActivation.' }
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$CloudRoot = Join-Path $ProjectRoot 'cloud'
$BundlePath = Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json'
$SyncClient = Join-Path $ProjectRoot 'sync-v213-activation-bundle.ps1'
$SyncConfig = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v21-owner-line.local.json'
foreach ($path in @($BundlePath,$SyncClient,$SyncConfig)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Activation prerequisite is missing: $path" }
}
$expectedBundleSha = [string]$env:V213_R75_SEALED_BUNDLE_SHA256
if ($expectedBundleSha -notmatch '^[0-9a-fA-F]{64}$') { throw 'The validated sealed R75 bundle SHA-256 is missing.' }
$actualBundleSha = (Get-FileHash -LiteralPath $BundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualBundleSha -ne $expectedBundleSha.ToLowerInvariant()) { throw 'The sealed R75 bundle changed after preflight.' }
$bundleText = Get-Content -LiteralPath $BundlePath -Raw -Encoding utf8
$bundle = $bundleText | ConvertFrom-Json
$transactionId = [string](Get-PropertyValue $bundle 'transaction_id' '')
$runId = [string](Get-PropertyValue $bundle 'run_id' '')
if ((Get-PropertyValue $bundle 'schema_version' 0) -ne 4 -or [string](Get-PropertyValue $bundle 'product_version' '') -ne '2.1.3' -or $transactionId -notmatch '^[0-9a-f]{32}$' -or $runId -notmatch '^\d{8}T\d{6}Z-[0-9a-f]{12}$') {
    throw 'The atomic v2.1.3 activation bundle failed the activation preflight.'
}
$payloads = Get-PropertyValue $bundle 'payloads' $null
if ($null -eq $payloads) { throw 'The sealed activation payload object is missing.' }
$reportPayload = [string](Get-PropertyValue $payloads 'v213_top20_report_json' '')
if ([string]::IsNullOrWhiteSpace($reportPayload)) { throw 'The sealed v2.1.3 report payload is missing.' }
$report = $reportPayload | ConvertFrom-Json
if ([string](Get-PropertyValue $report 'product_version' '') -ne '2.1.3' -or @((Get-PropertyValue $report 'records' @())).Count -ne 20) {
    throw 'The sealed v2.1.3 report failed the activation preflight.'
}
$reportTime = [DateTimeOffset]::MinValue
if (-not [DateTimeOffset]::TryParse([string](Get-PropertyValue $report 'generated_at' ''), [ref]$reportTime)) { throw 'The sealed v2.1.3 report generated_at value is invalid.' }
$reportAge = ([DateTimeOffset]::UtcNow - $reportTime.ToUniversalTime()).TotalSeconds
if ($reportAge -lt -300 -or $reportAge -gt 7200) { throw "The sealed v2.1.3 report is outside the 2-hour activation freshness gate (age_seconds=$([Math]::Round($reportAge))). Refresh first." }
Write-Host "V213_R75_SEALED_BUNDLE_TOCTOU = PASS; sha256=$actualBundleSha" -ForegroundColor Green

& (Join-Path $ProjectRoot 'scripts\resolve_node.ps1') -MinimumVersion '22.0.0'
$npm = if ($env:PROJECT_NPM) { $env:PROJECT_NPM } else { (Get-Command npm.cmd -ErrorAction Stop).Source }
Push-Location $CloudRoot
try {
    & $npm ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Hash-locked cloud npm ci failed.' }
    & $npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Worker typecheck failed before activation.' }
    & $npm test
    if ($LASTEXITCODE -ne 0) { throw 'Worker tests failed before activation.' }
}
finally { Pop-Location }
$wrangler = Resolve-WranglerCommand $CloudRoot
Write-Host "V213_WRANGLER_INVOCATION = DIRECT_NODE; node=$($wrangler.Executable); cli=$($wrangler.PrefixArguments[0])" -ForegroundColor DarkGray

$configRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
$selectionPath = Join-Path $configRoot 'v213-model-selection.json'
if (-not $ExpectedModel -and (Test-Path -LiteralPath $selectionPath -PathType Leaf)) {
    try { $ExpectedModel = [string](Get-PropertyValue (Get-Content -LiteralPath $selectionPath -Raw -Encoding utf8 | ConvertFrom-Json) 'model' '') }
    catch {}
}
if ($ExpectedModel -and $ExpectedModel -notmatch '^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}$') { throw 'ExpectedModel contains unsupported characters.' }
$productionConfig = @(
    (Join-Path $configRoot 'wrangler.v213.production.local.toml'),
    (Join-Path $configRoot 'wrangler.v211.production.local.toml'),
    (Join-Path $configRoot 'wrangler.v21.production.local.toml')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $productionConfig) { throw 'Installed Production Wrangler config was not found.' }

$modelState = Join-Path $configRoot 'v213-local-model.json'
$healthyModel = Get-HealthyModelState $modelState $ExpectedModel
if ($RequireLocalModel -and -not $healthyModel) { throw "Formal activation requires a fresh healthy bridge for the explicitly selected model '$ExpectedModel'. Production was not changed." }
if ($healthyModel) {
    $ExpectedModel = [string](Get-PropertyValue $healthyModel 'model' '')
    Write-Host "V213_SELECTED_MODEL_PREFLIGHT = PASS; model=$ExpectedModel" -ForegroundColor Green
}

$operationLockScript = Join-Path $ProjectRoot 'scripts\v213_operation_lock.ps1'
if (-not (Test-Path -LiteralPath $operationLockScript -PathType Leaf)) { throw 'R75 operation-lock module is missing.' }
. $operationLockScript
[void](Enter-V213OperationLock -Owner 'activation' -TimeoutSeconds 0)
Write-Host 'V213_OPERATION_LOCK = ACQUIRED; owner=activation' -ForegroundColor Green
$temp = Join-Path $CloudRoot ('.wrangler.v213.activation.' + [guid]::NewGuid().ToString('N') + '.toml')
$text = Get-Content -LiteralPath $productionConfig -Raw -Encoding utf8
$text = [regex]::Replace($text, '(?m)^\s*main\s*=.*$', 'main = "src/v213/production-worker.ts"', 1)
$text = Set-Var $text 'V213_FIELD_LOCALE' $FieldLocale
if ($healthyModel) {
    $text = Set-Var $text 'LOCAL_LLM_BASE_URL' ([string](Get-PropertyValue $healthyModel 'public_url' ''))
    $text = Set-Var $text 'LOCAL_LLM_ALLOWED_HOSTS' ([string](Get-PropertyValue $healthyModel 'allowed_host' ''))
    $text = Set-Var $text 'LOCAL_LLM_MODEL' ([string](Get-PropertyValue $healthyModel 'model' ''))
    Write-Host "V213_LOCAL_MODEL_ROUTE_PREFLIGHT = PASS; host=$([string](Get-PropertyValue $healthyModel 'allowed_host' '')); model=$ExpectedModel" -ForegroundColor Green
}
else {
    foreach ($key in @('LOCAL_LLM_BASE_URL','LOCAL_LLM_ALLOWED_HOSTS','LOCAL_LLM_MODEL')) { $text = Remove-Var $text $key }
    Write-Warning 'No fresh healthy v2.1.3 local-model tunnel is available; open-ended generation remains fail closed.'
}
if ($text -notmatch '(?m)^\s*name\s*=\s*"V213_BROADCAST_DEDUPE"\s*$') {
    $text += "`r`n[[durable_objects.bindings]]`r`nname = `"V213_BROADCAST_DEDUPE`"`r`nclass_name = `"V213BroadcastDedupe`"`r`n"
}
if ($text -notmatch '(?m)^\s*tag\s*=\s*"v213-r75-broadcast-dedupe-v1"\s*$') {
    $text += "`r`n[[migrations]]`r`ntag = `"v213-r75-broadcast-dedupe-v1`"`r`nnew_sqlite_classes = [`"V213BroadcastDedupe`"]`r`n"
}
[IO.File]::WriteAllText($temp, $text, [Text.UTF8Encoding]::new($false))

$installedCopy = Join-Path $configRoot 'wrangler.v213.production.local.toml'
$installedCopyExisted = Test-Path -LiteralPath $installedCopy -PathType Leaf
$installedCopyBackup = if ($installedCopyExisted) { Get-Content -LiteralPath $installedCopy -Raw -Encoding utf8 } else { '' }
$taskBackup = Backup-RefreshTasks
$tasksTouched = $false
$prior = ''
$current = ''
$deployed = $false
$bundleCommitAttempted = $false
$bundleCommitted = $false
$pointerRollbackVerified = $false
$workerRollbackVerified = $false
try {
    $prior = Get-SingleActiveVersion (Invoke-WranglerCapture $wrangler @('deployments','status','--json','--config',$temp) $CloudRoot)
    Write-Host "V213_ACTIVATION_PRIOR_VERSION = $prior" -ForegroundColor Cyan
    if ($healthyModel) {
        $secure = ConvertTo-SecureString -String ([string](Get-PropertyValue $healthyModel 'encrypted_shared_secret' ''))
        $sp = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $shared = ''
        try {
            $shared = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($sp)
            [void](Invoke-WranglerRun $wrangler @('secret','put','LOCAL_LLM_SHARED_SECRET','--config',$temp) $CloudRoot $shared)
            $deployed = $true
        }
        finally {
            if ($sp -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($sp) }
            $shared = $null
        }
    }
    [void](Invoke-WranglerRun $wrangler @('deploy','--config',$temp,'--message','v2.1.3 atomic source-diverse seven-field activation') $CloudRoot)
    $deployed = $true
    $current = Get-SingleActiveVersion (Invoke-WranglerCapture $wrangler @('deployments','status','--json','--config',$temp) $CloudRoot)
    if ($current -eq $prior) { throw 'Deployment did not produce a new active Worker version.' }

    $commitResult = Join-Path $env:TEMP ('ii-v213-activation-commit-' + [guid]::NewGuid().ToString('N') + '.json')
    $bundleCommitAttempted = $true
    & $SyncClient -Action Commit -ProjectRoot $ProjectRoot -BundlePath $BundlePath -LocalConfigPath $SyncConfig -ResultPath $commitResult
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $commitResult -PathType Leaf)) { throw 'Atomic activation bundle did not return a commit receipt.' }
    $commit = Get-Content -LiteralPath $commitResult -Raw -Encoding utf8 | ConvertFrom-Json
    Remove-Item -LiteralPath $commitResult -Force -ErrorAction SilentlyContinue
    if ([string](Get-PropertyValue $commit 'status' '') -ne 'accepted' -or [string](Get-PropertyValue $commit 'run_id' '') -ne $runId -or [string](Get-PropertyValue $commit 'transaction_id' '') -ne $transactionId) {
        throw 'Atomic activation bundle receipt does not match the local run.'
    }
    $bundleCommitted = $true
    Write-Host "V213_ATOMIC_DATA_COMMIT = PASS; run_id=$runId; transaction_id=$transactionId; pointer_written_last=true" -ForegroundColor Green

    & (Join-Path $ProjectRoot 'install-v213-source-diverse-runtime.ps1') -ProjectRoot $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Stable source-diverse runtime installation failed.' }
    $stableRuntime = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\V213Runtime'
    $tasksTouched = $true
    & (Join-Path $ProjectRoot 'register-v213-refresh-tasks.ps1') -RuntimeRoot $stableRuntime
    if ($LASTEXITCODE -ne 0) { throw 'Scheduled refresh task registration failed.' }

    Copy-Item -LiteralPath $temp -Destination $installedCopy -Force
    [ordered]@{
        schema_version = 3
        status = 'PASS'
        product_version = '2.1.3'
        activated_utc = (Get-Date).ToUniversalTime().ToString('o')
        prior_worker_version = $prior
        active_worker_version = $current
        activation_transaction_id = $transactionId
        activation_run_id = $runId
        pointer_written_last = $true
        atomic_reports_committed = @('v21_top20','v212_five_field','v213_seven_field','source_federation','source_independence')
        scheduled_times = @('08:00 Asia/Taipei','21:00 Asia/Taipei')
        local_refresh_times = @('07:20','20:20')
        scheduled_format = 'v213_seven_fields'
        field_locale = $FieldLocale
        runtime_root = $stableRuntime
        selected_model = $ExpectedModel
        local_model_route = $(if ($healthyModel) { 'HEALTHY_WIRED_EXACT_MODEL' } else { 'FAIL_CLOSED_NOT_WIRED' })
        local_model_required = [bool]$RequireLocalModel
        wrangler_json_stdout_isolated = $true
        pointer_rollback_on_failure = $true
        worker_rollback_on_failure = $true
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $env:USERPROFILE 'Desktop\Investor-Intelligence-v2.1.3-Scheduled-Activation-Receipt.json') -Encoding utf8

    try {
        & $SyncClient -Action Finalize -ProjectRoot $ProjectRoot -LocalConfigPath $SyncConfig -TransactionId $transactionId -RunId $runId
        Write-Host 'V213_ATOMIC_DATA_FINALIZE = PASS' -ForegroundColor Green
    }
    catch {
        Write-Warning ("Activation is coherent and complete, but rollback-handle cleanup will rely on its 30-minute TTL. " + $_.Exception.Message)
    }
    Write-Host "V2.1.3 SCHEDULED SEVEN-FIELD ACTIVATION = PASS; active_version=$current; run_id=$runId; model=$ExpectedModel" -ForegroundColor Green
}
catch {
    $failure = $_.Exception.Message
    $rollbackFailures = New-Object System.Collections.Generic.List[string]
    if ($bundleCommitAttempted) {
        try {
            & $SyncClient -Action Rollback -ProjectRoot $ProjectRoot -LocalConfigPath $SyncConfig -TransactionId $transactionId -RunId $runId
            $pointerRollbackVerified = $true
            Write-Host 'V213_ACTIVATION_POINTER_ROLLBACK = PASS' -ForegroundColor Green
        }
        catch { $rollbackFailures.Add('pointer=' + $_.Exception.Message) }
    }
    if ($tasksTouched) { Restore-RefreshTasks $taskBackup }
    try {
        if ($installedCopyExisted) { [IO.File]::WriteAllText($installedCopy, $installedCopyBackup, [Text.UTF8Encoding]::new($false)) }
        else { Remove-Item -LiteralPath $installedCopy -Force -ErrorAction SilentlyContinue }
    }
    catch { $rollbackFailures.Add('local_config=' + $_.Exception.Message) }
    if ($deployed -and $prior) {
        try {
            Write-Host 'Activation failed; restoring exact prior Worker version...' -ForegroundColor Yellow
            [void](Invoke-WranglerRun $wrangler @('versions','deploy',($prior + '@100%'),'-y','--config',$temp,'--message','Rollback failed v2.1.3 atomic activation') $CloudRoot)
            $restored = Get-SingleActiveVersion (Invoke-WranglerCapture $wrangler @('deployments','status','--json','--config',$temp) $CloudRoot)
            if ($restored -ne $prior) { throw "Expected $prior, observed $restored" }
            $workerRollbackVerified = $true
            Write-Host 'V213_ACTIVATION_WORKER_ROLLBACK = PASS' -ForegroundColor Green
        }
        catch { $rollbackFailures.Add('worker=' + $_.Exception.Message) }
    }
    if ($rollbackFailures.Count -gt 0) {
        throw "ACTIVATION FAILED AND COMPLETE ROLLBACK COULD NOT BE VERIFIED. Original: $failure; rollback: $($rollbackFailures -join '; ')"
    }
    throw "V213_ATOMIC_ACTIVATION_FAILED; production_restored=true; pointer_rollback=$pointerRollbackVerified; worker_rollback=$workerRollbackVerified; cause=$failure"
}
finally {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    Exit-V213OperationLock
    Write-Host 'V213_OPERATION_LOCK = RELEASED; owner=activation' -ForegroundColor DarkGray
}
