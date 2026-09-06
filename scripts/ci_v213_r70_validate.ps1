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
        @('scripts\v213_optional_bls_alignment_audit.py'),
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

    $launcherSource = Get-Content -LiteralPath 'launcher\InvestorIntelligenceLauncher.cs' -Raw -Encoding utf8
    foreach ($marker in @(
        'ComboBox modelBox',
        # The launcher pins the Router alias (1d6c6f1 free-relay cutover). The
        # coordinated Q5 alias cutover ships with the standalone delivery and
        # must update this expectation in the same commit (drift-guard test in
        # tests/test_final_distribution_scripts.py).
        'PreferredModel = "qwen38-q6"',
        'RefreshModelsAsync',
        'RunBusyAsync',
        'RunPowerShellAsync',
        'Shown += async delegate'
    )) {
        if (-not $launcherSource.Contains($marker)) { throw "Launcher responsive model-selector contract is missing: $marker" }
    }
    $asyncClickCount = [regex]::Matches($launcherSource,'(?m)\b(?:scanButton|refreshButton|activateButton|bridgeButton)\.Click\s*\+=\s*async\s+delegate').Count
    if ($asyncClickCount -lt 4) { throw "Launcher must keep all long-running/scan UI handlers asynchronous; observed=$asyncClickCount expected>=4" }
    foreach ($buttonName in @('refreshButton','activateButton','bridgeButton')) {
        if ($launcherSource -notmatch ([regex]::Escape($buttonName) + '\.Click\s*\+=\s*async\s+delegate[\s\S]{0,1800}?await\s+RunBusyAsync')) {
            throw "Launcher busy-operation handler is not asynchronous/non-blocking: $buttonName"
        }
    }
    if ($launcherSource -notmatch 'RefreshModelsAsync\(\)[\s\S]{0,1400}?Task\.Run') { throw 'Launcher model scan does not offload discovery from the UI thread.' }
    Write-Host "V213_LAUNCHER_SOURCE_UI_CONTRACT = PASS; model_selector=true; async_handlers=$asyncClickCount; responsive_ui=true; model_scan_off_ui_thread=true" -ForegroundColor Green

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

        $bundleSource = ([string]$bundle.payloads.source_independence_json) | ConvertFrom-Json
        if ([string]$bundleSource.status -ne 'PASS' -or @($bundleSource.records).Count -ne 20 -or @($bundleSource.blocking_violations).Count -ne 0 -or @($bundleSource.violations).Count -ne 0) {
            throw 'Atomic bundle source-independence payload is not a blocking-gate PASS.'
        }
        $evidenceQualified = 0
        $limitedCandidates = 0
        for ($index = 0; $index -lt 20; $index++) {
            $ticker = [string]$top20[$index].ticker
            foreach ($actual in @([string]$five.records[$index].ticker,[string]$seven.records[$index].ticker,[string]$federation.ticker_sources[$index].ticker,[string]$source.records[$index].ticker,[string]$ledger.records[$index].ticker,[string]$bundleSource.records[$index].ticker)) {
                if ($actual -ne $ticker) { throw "Final order mismatch at rank $($index + 1): $ticker / $actual" }
            }

            $bundleRecord = $bundleSource.records[$index]
            $freshness = $bundleRecord.freshness_state
            if ($null -eq $freshness -or [string]$freshness.status -ne 'PASS') { throw "Atomic source freshness gate failed: $ticker" }
            $mode = [string]$freshness.publication_evidence_mode
            if (-not $mode) { $mode = [string]$bundleRecord.publication_evidence_mode }
            if ($mode -eq 'EVIDENCE_QUALIFIED') {
                if ([int]$freshness.claim_source_families -lt 2 -or [int]$freshness.claim_source_domains -lt 2 -or [int]$freshness.claim_primary_units -lt 1) {
                    throw "Evidence-qualified ticker lost multi-source company evidence: $ticker"
                }
                $evidenceQualified++
            }
            elseif ($mode -eq 'LIMITED_RESEARCH_CANDIDATE') {
                if ([int]$freshness.publication_provenance_origin_count -lt 2 -or [int]$freshness.publication_provenance_domain_count -lt 2 -or [int]$freshness.claim_primary_units -lt 1) {
                    throw "Limited research candidate still depends on a single publication origin: $ticker"
                }
                if ($bundleRecord.eligible_for_high_confidence_model_inference -ne $false -or $bundleRecord.public_logic_state.validated_company_thesis -ne $false) {
                    throw "Limited research candidate was incorrectly promoted to a validated/high-confidence thesis: $ticker"
                }
                $factor = $top20[$index].serenity_factors
                foreach ($sensitive in @('demand_wave','chokepoint','pricing_power','replacement_friction','tam_capture')) {
                    if ([double]$factor.$sensitive -gt 0) { throw "Limited research candidate retained a positive sensitive factor: $ticker / $sensitive" }
                }
                $limitedCandidates++
            }
            else {
                throw "Unknown publication evidence mode for ${ticker}: $mode"
            }

            $factor = $top20[$index].serenity_factors
            if ([double]$factor.valuation_expectations -gt 3.75 -and $ledger.records[$index].two_fresh_comparable_non_yahoo_market_providers -ne $true) { throw "Uncorroborated valuation exceeds cap: $ticker" }
            if ($ledger.records[$index].severe_thesis_killer_present -ne $false) { throw "Severe thesis killer remains published: $ticker" }
        }
        if (($evidenceQualified + $limitedCandidates) -ne 20) { throw 'Atomic bundle publication-mode accounting does not equal 20.' }
        Write-Host "V213_ATOMIC_PER_TICKER_PUBLICATION_GATE = PASS; evidence_qualified=$evidenceQualified; limited_research_candidates=$limitedCandidates; single_origin_candidates=0; positive_sensitive_factors_on_limited=0" -ForegroundColor Green

        $validationPath = Join-Path $env:RUNNER_TEMP 'Investor-Intelligence-v2.1.3-R70-Validation.json'
        [ordered]@{
            schema_version = 2
            status = 'PASS'
            commit = $env:GITHUB_SHA.ToLowerInvariant()
            workflow_run_id = [string]$env:GITHUB_RUN_ID
            production_mutation = $false
            latest_public_serenity_source = $serenity.canonical_head_sha
            latest_public_serenity_retrieved_at = $serenity.retrieved_at
            strict_evidence_qualified_count = $evidenceQualified
            limited_research_candidate_count = $limitedCandidates
            limited_candidate_minimum_provenance_origins = 2
            limited_candidate_minimum_provenance_domains = 2
            limited_candidates_can_be_high_confidence = $false
            limited_candidates_can_have_positive_sensitive_factors = $false
            market_provider_minimum_for_high_confidence = 2
            market_same_metric_basis_required = $true
            yahoo_truth_anchor = $false
            source_values_averaged = $false
            value_chain_layer_count = @($audit.value_chain_layers.PSObject.Properties).Count
            factor_ledger_records = 20
            atomic_payloads = 7
            launcher_model_selector_source_contract = $true
            launcher_async_ui_source_contract = $true
            worker_tests = 'complete'
            windows_no_mutation_refresh = $true
        } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $validationPath -Encoding utf8
        "R70_VALIDATION=$validationPath" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
        Write-Host "V213_R70_WINDOWS_NO_MUTATION_VALIDATION = PASS; serenity_head=$($serenity.canonical_head_sha); layers=$(@($audit.value_chain_layers.PSObject.Properties).Count); selector=true; responsive=true" -ForegroundColor Green
    }
    finally {
        $env:LOCALAPPDATA = $savedLocal
        $env:SEC_CONTACT_EMAIL = $savedContact
        Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
finally { Pop-Location }
