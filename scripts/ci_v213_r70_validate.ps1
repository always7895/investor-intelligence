[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
Push-Location $ProjectRoot
try {
    & .\scripts\resolve_python.ps1 -VenvPath .venv-v213-r70-validation
    if (-not $env:PROJECT_PYTHON -or -not (Test-Path -LiteralPath $env:PROJECT_PYTHON -PathType Leaf)) { throw 'Verified Python was not configured.' }
    & $env:PROJECT_PYTHON -m pip install --isolated --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple --require-hashes -r requirements-ci.txt
    if ($LASTEXITCODE -ne 0) { throw 'Hash-locked Python dependency installation failed.' }
    & $env:PROJECT_PYTHON -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed.' }

    $pythonTests = @(
        @('scripts\v213_refresh_serenity_public_sources.py','--self-test'),
        @('scripts\v213_serenity_latest_multisource_audit.py','--self-test'),
        @('scripts\v213_tam_capture_claim_guard.py','--self-test'),
        @('scripts\v213_serenity_latest_static_audit.py'),
        @('scripts\reconcile_v213_order_evidence.py','--self-test'),
        @('scripts\build_v213_scheduled_top20_report.py','--self-test'),
        @('scripts\v213_source_federation.py','--self-test'),
        @('scripts\v213_source_federation_gate.py','--self-test'),
        @('scripts\v213_apply_diversified_operationalization.py','--self-test'),
        @('scripts\v213_source_independence_gate_v2.py','--wrapper-self-test'),
        @('scripts\v213_source_independence_gate_v3.py','--wrapper-self-test'),
        @('scripts\v213_build_v21_public_snapshot.py','--self-test'),
        @('scripts\build_v213_activation_bundle_v2.py','--self-test'),
        @('scripts\v213_pipeline_boundary_self_test.py'),
        @('scripts\v213_methodology_and_source_audit.py'),
        @('scripts\v213_local_llm_gateway.py','--self-test'),
        @('scripts\audit_v213_bilingual_public_fields.py'),
        @('scripts\audit_v213_source_diversity_fields.py'),
        @('tests\test_v213_v21_progress_runner.py'),
        @('tests\test_v213_v212_progress_runner.py')
    )
    foreach ($command in $pythonTests) {
        & $env:PROJECT_PYTHON @command
        if ($LASTEXITCODE -ne 0) { throw "Python validation failed: $($command -join ' ')" }
    }
    & $env:PROJECT_PYTHON -m compileall -q scripts tests
    if ($LASTEXITCODE -ne 0) { throw 'Python compileall failed.' }

    & .\scripts\resolve_node.ps1 -MinimumVersion 22.0.0
    $npm = if ($env:PROJECT_NPM -and (Test-Path -LiteralPath $env:PROJECT_NPM -PathType Leaf)) { $env:PROJECT_NPM } else { (Get-Command npm.cmd -ErrorAction Stop).Source }
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
        'run-v213-local-serenity-latest.ps1',
        'activate-v213-seven-field-schedule-serenity-latest.ps1',
        'install-v213-serenity-latest-runtime.ps1',
        'activate-v213-seven-field-schedule-core.ps1',
        'sync-v213-activation-bundle.ps1',
        'run-v213-local-llm-bridge-source-diverse.ps1',
        'scripts\run_v213_local_llm_bridge_core_v2.ps1',
        'scripts\ci_v213_r70_validate.ps1',
        'scripts\ci_v213_r70_package.ps1'
    )
    foreach ($path in $powerShellPaths) {
        $tokens = $null; $errors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $path),[ref]$tokens,[ref]$errors)
        if ($errors.Count) { $errors | Out-String | Write-Host; throw "$path PowerShell 7 parser errors" }
    }
    $ps51Probe = Join-Path $env:RUNNER_TEMP 'v213-r70-ps51-parse.ps1'
    @'
param([string[]]$Paths)
foreach ($path in $Paths) {
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $path),[ref]$tokens,[ref]$errors)
    if ($errors.Count) { $errors | Out-String | Write-Host; exit 1 }
}
'@ | Set-Content -LiteralPath $ps51Probe -Encoding utf8
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ps51Probe -Paths $powerShellPaths
    if ($LASTEXITCODE -ne 0) { throw 'Windows PowerShell 5.1 parser gate failed.' }

    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\run-v213-local-serenity-latest.ps1 -ProjectRoot $ProjectRoot -SelfTest
    if ($LASTEXITCODE -ne 0) { throw 'Final refresh entrypoint self-test failed.' }
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\activate-v213-seven-field-schedule-serenity-latest.ps1 -ProjectRoot $ProjectRoot -SelfTest
    if ($LASTEXITCODE -ne 0) { throw 'Final activation entrypoint self-test failed.' }

    $testRoot = Join-Path $env:RUNNER_TEMP ('v213-r70-live-' + [guid]::NewGuid().ToString('N'))
    $savedLocal = $env:LOCALAPPDATA
    $savedContact = $env:SEC_CONTACT_EMAIL
    $env:LOCALAPPDATA = Join-Path $testRoot 'LocalAppData'
    $env:SEC_CONTACT_EMAIL = 'investor-intelligence-public-research@example.com'
    New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA | Out-Null
    try {
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\run-v213-local-serenity-latest.ps1 -ProjectRoot $ProjectRoot -NoModelBridge -NoSync -NoAutoActivation
        if ($LASTEXITCODE -ne 0) { throw 'Real Windows no-mutation final refresh failed.' }
        $top20 = @(Get-Content data\cache\top20_public_latest.json -Raw -Encoding utf8 | ConvertFrom-Json)
        $five = Get-Content data\cache\v212_top20_report_public_latest.json -Raw -Encoding utf8 | ConvertFrom-Json
        $seven = Get-Content data\cache\v213_top20_report_public_latest.json -Raw -Encoding utf8 | ConvertFrom-Json
        $federation = Get-Content data\cache\v213_source_federation_latest.json -Raw -Encoding utf8 | ConvertFrom-Json
        $source = Get-Content data\cache\v213_source_independence_latest.json -Raw -Encoding utf8 | ConvertFrom-Json
        $serenity = Get-Content data\cache\v213_serenity_public_source_latest.json -Raw -Encoding utf8 | ConvertFrom-Json
        $ledger = Get-Content data\cache\v213_serenity_factor_ledger_latest.json -Raw -Encoding utf8 | ConvertFrom-Json
        $audit = Get-Content data\cache\v213_serenity_latest_multisource_audit.json -Raw -Encoding utf8 | ConvertFrom-Json
        $bundle = Get-Content data\cache\v213_activation_bundle_upload.json -Raw -Encoding utf8 | ConvertFrom-Json
        if ($top20.Count -ne 20 -or @($five.records).Count -ne 20 -or @($seven.records).Count -ne 20 -or @($source.records).Count -ne 20 -or @($ledger.records).Count -ne 20) { throw 'Final row-count contract failed.' }
        if ([string]$audit.status -ne 'PASS' -or $serenity.latest_available_verified -ne $true) { throw 'Latest Serenity/source audit did not pass.' }
        if ([int]$audit.per_ticker_claim_family_minimum -lt 2 -or [int]$audit.per_ticker_claim_domain_minimum -lt 2 -or [int]$audit.per_ticker_primary_minimum -lt 1) { throw 'Per-ticker multi-source minimums are too weak.' }
        if ($audit.yahoo_truth_anchor -ne $false -or $audit.source_values_averaged -ne $false) { throw 'Yahoo/anti-averaging boundary failed.' }
        if (@($audit.value_chain_layers.PSObject.Properties).Count -lt 3) { throw 'Fewer than three value-chain layers were represented.' }
        if ([int]$bundle.schema_version -ne 4 -or @($bundle.payloads.PSObject.Properties).Count -ne 7) { throw 'Atomic bundle contract failed.' }
        for ($index = 0; $index -lt 20; $index++) {
            $ticker = [string]$top20[$index].ticker
            foreach ($actual in @([string]$five.records[$index].ticker,[string]$seven.records[$index].ticker,[string]$federation.ticker_sources[$index].ticker,[string]$source.records[$index].ticker,[string]$ledger.records[$index].ticker)) {
                if ($actual -ne $ticker) { throw "Final order mismatch at rank $($index + 1): $ticker / $actual" }
            }
            $metrics = $source.records[$index].source_metrics
            if ([int]$metrics.claim_relevant_independent_families -lt 2 -or [int]$metrics.claim_relevant_independent_domains -lt 2 -or [int]$metrics.claim_relevant_primary_sources -lt 1 -or [double]$metrics.claim_dated_evidence_ratio -lt 0.8) { throw "Per-ticker source gate failed: $ticker" }
            $factor = $top20[$index].serenity_factors
            if ([double]$factor.valuation_expectations -gt 3.75 -and $ledger.records[$index].two_fresh_comparable_non_yahoo_market_providers -ne $true) { throw "Uncorroborated valuation exceeds cap: $ticker" }
            if ($ledger.records[$index].severe_thesis_killer_present -ne $false) { throw "Severe thesis killer remains published: $ticker" }
        }
        $validationPath = Join-Path $env:RUNNER_TEMP 'Investor-Intelligence-v2.1.3-R70-Validation.json'
        [ordered]@{
            schema_version = 1
            status = 'PASS'
            commit = $env:GITHUB_SHA.ToLowerInvariant()
            workflow_run_id = [string]$env:GITHUB_RUN_ID
            production_mutation = $false
            latest_public_serenity_source = $serenity.canonical_head_sha
            latest_public_serenity_retrieved_at = $serenity.retrieved_at
            per_ticker_claim_source_families_minimum = 2
            per_ticker_claim_source_domains_minimum = 2
            per_ticker_primary_minimum = 1
            market_provider_minimum_for_high_confidence = 2
            market_same_metric_basis_required = $true
            yahoo_truth_anchor = $false
            source_values_averaged = $false
            value_chain_layer_count = @($audit.value_chain_layers.PSObject.Properties).Count
            factor_ledger_records = 20
            atomic_payloads = 7
            worker_tests = 'complete'
            windows_no_mutation_refresh = $true
        } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $validationPath -Encoding utf8
        "R70_VALIDATION=$validationPath" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
        Write-Host "V213_R70_WINDOWS_NO_MUTATION_VALIDATION = PASS; serenity_head=$($serenity.canonical_head_sha); layers=$(@($audit.value_chain_layers.PSObject.Properties).Count)" -ForegroundColor Green
    }
    finally {
        $env:LOCALAPPDATA = $savedLocal
        $env:SEC_CONTACT_EMAIL = $savedContact
        Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
finally { Pop-Location }
