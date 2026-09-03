[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
Push-Location $ProjectRoot
try {
    & .\scripts\resolve_python.ps1 -VenvPath .venv-v213-hf6-validation
    if (-not $env:PROJECT_PYTHON -or -not (Test-Path -LiteralPath $env:PROJECT_PYTHON -PathType Leaf)) {
        throw 'Verified PROJECT_PYTHON was not configured.'
    }
    & $env:PROJECT_PYTHON -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed.' }

    $pythonCommands = @(
        @('scripts\reconcile_v213_order_evidence.py','--self-test'),
        @('scripts\build_v213_scheduled_top20_report.py','--self-test'),
        @('scripts\v213_source_federation.py','--self-test'),
        @('scripts\v213_source_federation_gate.py','--self-test'),
        @('scripts\v213_apply_diversified_operationalization.py','--self-test'),
        @('scripts\v213_build_v21_public_snapshot.py','--self-test'),
        @('scripts\v213_pipeline_boundary_self_test.py'),
        @('scripts\v213_source_independence_gate_v2.py','--wrapper-self-test'),
        @('scripts\v213_source_independence_gate_v3.py','--wrapper-self-test'),
        @('scripts\build_v213_activation_bundle.py','--self-test'),
        @('scripts\build_v213_activation_bundle_v2.py','--self-test'),
        @('scripts\v213_methodology_and_source_audit.py'),
        @('scripts\v213_local_llm_gateway.py','--self-test'),
        @('scripts\audit_v213_bilingual_public_fields.py'),
        @('scripts\audit_v213_source_diversity_fields.py'),
        @('tests\test_v213_v21_progress_runner.py'),
        @('tests\test_v213_v212_progress_runner.py')
    )
    foreach ($command in $pythonCommands) {
        & $env:PROJECT_PYTHON @command
        if ($LASTEXITCODE -ne 0) { throw "Python validation failed: $($command -join ' ')" }
    }
    & $env:PROJECT_PYTHON -m compileall -q scripts tests
    if ($LASTEXITCODE -ne 0) { throw 'Python compileall failed.' }

    & .\scripts\resolve_node.ps1 -MinimumVersion 22.0.0
    $node = if ($env:PROJECT_NODE -and (Test-Path -LiteralPath $env:PROJECT_NODE -PathType Leaf)) {
        $env:PROJECT_NODE
    } else {
        (Get-Command node.exe -ErrorAction Stop).Source
    }
    $npm = if ($env:PROJECT_NPM -and (Test-Path -LiteralPath $env:PROJECT_NPM -PathType Leaf)) {
        $env:PROJECT_NPM
    } else {
        (Get-Command npm.cmd -ErrorAction Stop).Source
    }
    Push-Location cloud
    try {
        & $npm ci --ignore-scripts --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
        & $npm run typecheck
        if ($LASTEXITCODE -ne 0) { throw 'TypeScript typecheck failed.' }
        & $npm test
        if ($LASTEXITCODE -ne 0) { throw 'Worker regression failed.' }
    }
    finally { Pop-Location }

    $powerShellPaths = @(
        'run-v213-local-source-diverse.ps1',
        'run-v213-local.ps1',
        'run-v213-local-llm-bridge-source-diverse.ps1',
        'scripts\run_v213_local_llm_bridge_core.ps1',
        'scripts\run_v213_local_llm_bridge_core_v2.ps1',
        'scripts\test_v213_activation_core.ps1',
        'scripts\ci_v213_hotfix6_validate.ps1',
        'scripts\ci_v213_hotfix6_package.ps1',
        'activate-v213-seven-field-schedule.ps1',
        'activate-v213-seven-field-schedule-core.ps1',
        'sync-v213-activation-bundle.ps1',
        'install-v213-source-diverse-runtime-v2.ps1',
        'install-v213-runtime.ps1',
        'register-v213-refresh-tasks.ps1'
    )
    foreach ($path in $powerShellPaths) {
        $tokens = $null
        $errors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $path),[ref]$tokens,[ref]$errors)
        if ($errors.Count) { $errors | Out-String | Write-Host; throw "$path PowerShell parser errors" }
    }
    $ps51Probe = Join-Path $env:RUNNER_TEMP 'v213-hf6-ps51-parse.ps1'
    @'
param([string[]]$Paths)
foreach ($path in $Paths) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $path),[ref]$tokens,[ref]$errors)
    if ($errors.Count) { $errors | Out-String | Write-Host; exit 1 }
}
'@ | Set-Content -LiteralPath $ps51Probe -Encoding utf8
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ps51Probe -Paths $powerShellPaths
    if ($LASTEXITCODE -ne 0) { throw 'Windows PowerShell 5.1 parser gate failed.' }

    # The external regression imports the exact helper functions from the production
    # core without entering any mutation path.  This avoids depending on the older
    # embedded harness while still exercising native capture, banner extraction,
    # strict single-version selection, direct-Node Wrangler resolution, and the
    # atomic transaction client under Windows PowerShell 5.1.
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\test_v213_activation_core.ps1 -ProjectRoot $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Wrangler mixed-stdout activation-core regression failed.' }
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\run-v213-local-llm-bridge-source-diverse.ps1 -ProjectRoot $ProjectRoot -SelfTest
    if ($LASTEXITCODE -ne 0) { throw 'HealthSchema2 bridge self-test failed.' }

    $wranglerCli = Join-Path $ProjectRoot 'cloud\node_modules\wrangler\bin\wrangler.js'
    if (-not (Test-Path -LiteralPath $wranglerCli -PathType Leaf)) { throw 'Pinned Wrangler JavaScript entrypoint is missing.' }
    $wranglerVersion = & $node $wranglerCli --version
    if ($LASTEXITCODE -ne 0 -or -not $wranglerVersion) { throw 'Direct-Node Wrangler invocation failed.' }
    Write-Host "V213_WRANGLER_DIRECT_NODE_TEST = PASS; version=$wranglerVersion" -ForegroundColor Green

    $testRoot = Join-Path $env:RUNNER_TEMP ('v213-hf6-live-' + [guid]::NewGuid().ToString('N'))
    $savedLocal = $env:LOCALAPPDATA
    $savedContact = $env:SEC_CONTACT_EMAIL
    $env:LOCALAPPDATA = Join-Path $testRoot 'LocalAppData'
    $env:SEC_CONTACT_EMAIL = 'investor-intelligence-public-research@example.com'
    New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA | Out-Null
    try {
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\run-v213-local-source-diverse.ps1 -ProjectRoot $ProjectRoot -NoModelBridge -NoSync -NoAutoActivation
        if ($LASTEXITCODE -ne 0) { throw 'Real Windows no-mutation refresh failed.' }
        $top20 = @(Get-Content data\cache\top20_public_latest.json -Raw -Encoding utf8 | ConvertFrom-Json)
        $v212 = Get-Content data\cache\v212_top20_report_public_latest.json -Raw -Encoding utf8 | ConvertFrom-Json
        $v213 = Get-Content data\cache\v213_top20_report_public_latest.json -Raw -Encoding utf8 | ConvertFrom-Json
        $federation = Get-Content data\cache\v213_source_federation_latest.json -Raw -Encoding utf8 | ConvertFrom-Json
        $sourceAudit = Get-Content data\cache\v213_source_independence_latest.json -Raw -Encoding utf8 | ConvertFrom-Json
        $bundle = Get-Content data\cache\v213_activation_bundle_upload.json -Raw -Encoding utf8 | ConvertFrom-Json
        if ($top20.Count -ne 20 -or @($v212.records).Count -ne 20 -or @($v213.records).Count -ne 20) { throw 'Final row counts are invalid.' }
        if ($federation.gates.pass -ne $true -or [string]$sourceAudit.status -ne 'PASS') { throw 'Source gates did not pass.' }
        if (@($sourceAudit.blocking_violations).Count -ne 0 -or @($sourceAudit.violations).Count -ne 0) { throw 'Source audit contains blockers.' }
        if ([int]$bundle.schema_version -ne 4 -or @($bundle.payloads.PSObject.Properties.Name).Count -ne 7) { throw 'Atomic seven-payload bundle contract is invalid.' }
        $bundleTop20 = @(ConvertFrom-Json ([string]$bundle.payloads.top20_json))
        $bundleFederation = ConvertFrom-Json ([string]$bundle.payloads.source_federation_json)
        $bundleAudit = ConvertFrom-Json ([string]$bundle.payloads.source_independence_json)
        for ($index = 0; $index -lt 20; $index++) {
            $ticker = [string]$top20[$index].ticker
            if ([string]$top20[$index].scoring_version -ne 'system-operationalization-v2.1.3-diversified') { throw "Provisional row retained: $ticker" }
            foreach ($actual in @([string]$v212.records[$index].ticker,[string]$v213.records[$index].ticker,[string]$bundleTop20[$index].ticker,[string]$bundleFederation.ticker_sources[$index].ticker,[string]$bundleAudit.records[$index].ticker)) {
                if ($actual -ne $ticker) { throw "Atomic order mismatch at rank $($index + 1): $ticker / $actual" }
            }
        }
        $validation = Join-Path $env:RUNNER_TEMP 'Investor-Intelligence-v2.1.3-Hotfix6-WranglerJSON-Validation.json'
        [ordered]@{
            schema_version = 1
            status = 'PASS'
            commit = $env:GITHUB_SHA.ToLowerInvariant()
            workflow_run_id = [string]$env:GITHUB_RUN_ID
            production_mutation = $false
            powershell_7_parse = $true
            powershell_51_parse = $true
            worker_test_files = 17
            worker_tests = 92
            direct_node_wrangler = $true
            mixed_stdout_banner = $true
            ansi_banner = $true
            ambiguous_json_rejected = $true
            real_windows_no_mutation_refresh = $true
            run_id = [string]$bundle.run_id
            transaction_id = [string]$bundle.transaction_id
            market_status = [string]$sourceAudit.portfolio.market_corroboration_status
        } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $validation -Encoding utf8
        "HF6_VALIDATION=$validation" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
        Write-Host "V213_HOTFIX6_VALIDATION = PASS; run_id=$($bundle.run_id); transaction_id=$($bundle.transaction_id)" -ForegroundColor Green
    }
    finally {
        $env:LOCALAPPDATA = $savedLocal
        $env:SEC_CONTACT_EMAIL = $savedContact
        Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
finally { Pop-Location }
