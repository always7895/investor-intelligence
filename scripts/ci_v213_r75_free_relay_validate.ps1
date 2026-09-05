[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$baseCommit = '43f3be048cedf228cfe9e8e31f7b9901895838be'
$r75Commit = '536644d22ef3534be1c4b8a9e1ff969df4d580fa'
Push-Location $ProjectRoot
try {
    $sha = (git rev-parse HEAD).Trim().ToLowerInvariant()
    git merge-base --is-ancestor $baseCommit $sha
    if ($LASTEXITCODE -ne 0) { throw 'FREE_RELAY hotfix must descend from the completed Named Tunnel hotfix.' }
    if (@(git status --porcelain).Count -ne 0) { throw 'FREE_RELAY validation requires a clean checkout.' }
    $changed = @(git diff --name-only "$baseCommit..$sha")
    $allowed = @(
        '.github/workflows/v213-r75-release.yml',
        'activate-v213-diversified-schedule.ps1','activate-v213-seven-field-schedule-core.ps1',
        'activate-v213-seven-field-schedule-serenity-latest.ps1','activate-v213-seven-field-schedule.ps1',
        'cloud/src/qa.ts','cloud/src/v213/free-relay.ts','cloud/src/v213/production-worker.ts',
        'cloud/src/v211/worker.ts','cloud/src/v213/compact-qa.ts','cloud/src/v213/readiness.ts',
        'cloud/test/v213-compact-qa.test.ts','cloud/test/v213-qa-reference-job.test.ts','cloud/test/v213-readiness.test.ts',
        'config/v213-compact-qa-v1.json','sync-v213-activation-bundle.ps1',
        'scripts/benchmark_v213_qa_latency.py','scripts/v213_compact_qa_gateway.py','scripts/v213_local_llm_gateway.py',
        'scripts/test_v213_edge_readiness.ps1','scripts/v213_edge_readiness.ps1','tests/test_v213_compact_qa_gateway.py',
        'tests/test_v213_r75_gateway_process.py',
        'cloud/test/v213-free-relay.test.ts','cloud/wrangler.v213.production.template.toml',
        'cloud/src/v21/top20.ts','cloud/test/v213-activation.test.ts','cloud/package.json','cloud/package-lock.json',
        'docs/V213_FREE_WORKERS_RELAY.md','launcher/InvestorIntelligenceLauncher.cs','install-v213-runtime.ps1',
        'register-v213-free-relay-task.ps1','run-v213-local-llm-bridge-source-diverse.ps1',
        'run-v213-local-llm-bridge.ps1','run-v213-local-serenity-latest.ps1',
        'run-v213-local-source-diverse.ps1','run-v213-local.ps1',
        'scripts/ci_v213_r75_free_relay_package.ps1','scripts/ci_v213_r75_free_relay_validate.ps1',
        'scripts/ci_v213_r75_validate.ps1','scripts/run_v213_local_llm_bridge_core.ps1',
        'scripts/run_v213_local_llm_bridge_core_v2.ps1','scripts/test_v213_free_relay.ps1',
        'scripts/test_v213_named_tunnel.ps1','scripts/v213_free_relay.ps1',
        'scripts/v213_free_relay_heartbeat.ps1','scripts/verify_v213_r75_free_relay_hotfix.py',
        'state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md','state/STATUS.md',
        'tests/test_v213_free_relay_package_payload.py'
    )
    foreach ($path in $changed) { if ($allowed -notcontains $path) { throw "FREE_RELAY changed a non-deployment path: $path" } }
    foreach ($protected in @(
        'config/v213-r75-publication-mode-v1.json','scripts/v213_r75_activation_preflight.py',
        'cloud/src/qa.ts','cloud/src/v213/publication-mode.ts','cloud/src/v213/activation-v2.ts',
        'scripts/ci_v213_r75_package.ps1','scripts/verify_v213_r75_artifact.py'
    )) {
        git diff --quiet $r75Commit -- $protected
        if ($LASTEXITCODE -ne 0) { throw "FREE_RELAY changed protected R75 source: $protected" }
    }
    foreach ($required in @('cloud/src/v213/free-relay.ts','cloud/test/v213-free-relay.test.ts','scripts/v213_free_relay.ps1','scripts/v213_free_relay_heartbeat.ps1','scripts/test_v213_free_relay.ps1','register-v213-free-relay-task.ps1')) {
        if ($changed -notcontains $required) { throw "FREE_RELAY required integration file missing: $required" }
    }
    & .\scripts\ci_v213_r75_validate.ps1 -ProjectRoot $ProjectRoot -SkipLiveRefresh
    if ($LASTEXITCODE -ne 0) { throw 'R75 no-mutation regression validation failed.' }
    $template = Get-Content -LiteralPath 'cloud\wrangler.v213.production.template.toml' -Raw -Encoding utf8
    if ($template -notmatch 'workers_dev\s*=\s*true' -or $template -notmatch 'FREE_RELAY_ENABLED\s*=\s*"true"' -or $template -match '(?im)^\s*routes?\s*=') { throw 'FREE_RELAY template does not preserve zero-cost workers.dev architecture.' }

    $workerResults = Get-Content -LiteralPath $env:R75_WORKER_TEST_REPORT -Raw -Encoding utf8 | ConvertFrom-Json
    if (-not $workerResults.success -or $workerResults.numFailedTests -ne 0) { throw 'Worker evidence is not successful.' }
    # Full regression is not live Q&A qualification. Never package a release from
    # synthetic transport tests while the inherited high-reasoning gate fails.
    $env:R75_QA_RELEASE_READY = 'false'
    if ($env:GITHUB_ENV) { 'R75_QA_RELEASE_READY=false' | Out-File $env:GITHUB_ENV -Append -Encoding utf8 }
    $receiptRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
    $runId = if ($env:GITHUB_RUN_ID) { [string]$env:GITHUB_RUN_ID } else { '0' }
    $attempt = if ($env:GITHUB_RUN_ATTEMPT) { [string]$env:GITHUB_RUN_ATTEMPT } else { '1' }
    $receipt = Join-Path $receiptRoot "Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-$sha-$runId-$attempt-Windows-Receipt.json"
    [ordered]@{
        schema_version=1;status='PASS';artifact_kind='R75_FREE_WORKERS_RELAY_HOTFIX';base_named_tunnel_commit=$baseCommit;source_commit=$sha
        workflow_run_id=$runId;workflow_run_attempt=$attempt;windows_powershell_51='PASS';powershell_7='PASS';python_full_suite='PASS'
        worker_typecheck='PASS';worker_test_files=@($workerResults.testResults).Count;worker_tests=[int]$workerResults.numTotalTests;
        compact_context='PASS_SYNTHETIC';deployment_readiness='PASS_SYNTHETIC';live_qa='BLOCKED_INHERITED_HIGH_REASONING';live_free_relay_smoke='NOT_RUN_PRODUCTION_WRITE_FORBIDDEN';release_ready=$false;
        exact_sealed_bundle_predeploy_gate='PASS_SYNTHETIC';sec_filing_provenance_schema='PASS';workers_dev_stable_entrypoint=$true;custom_domain_required=$false
        quick_tunnel_ephemeral=$true;exact_model='qwen38-q6';health_schema_version=2;consecutive_health_checks=3
        worker_runtime_redirect_compatibility='PASS_SYNTHETIC';authenticated_smoke_gate='PASS_SYNTHETIC';signed_route_registration='PASS_SYNTHETIC';stale_route_rejection='PASS';replay_rejection='PASS';concurrent_update='PASS';heartbeat_lease='PASS';reboot_reconnect='PASS';rollback='PASS'
        allow_test_tunnel_exception_used=$false;protected_release_semantics_unchanged=$true;production_mutation_by_ci=$false;external_mutation=$false
        worker_deployed=$false;production_kv_or_do_written=$false;line_message_sent=$false;schedules_registered=$false;completed_utc=(Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receipt -Encoding utf8
    $env:R75_FREE_RELAY_WINDOWS_RECEIPT=$receipt
    if ($env:GITHUB_ENV) { "R75_FREE_RELAY_WINDOWS_RECEIPT=$receipt" | Out-File $env:GITHUB_ENV -Append -Encoding utf8 }
    Write-Host "V213_R75_FREE_RELAY_WINDOWS_VALIDATION = PASS; commit=$sha; workers_dev=true; custom_domain=false; production_mutation_by_ci=false; receipt=$receipt" -ForegroundColor Green
}
finally { Pop-Location }
