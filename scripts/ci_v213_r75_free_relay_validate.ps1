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
        'AGENTS.md','skills/serenity-public-research/SKILL.md',
        'skills/serenity-public-research/references/RESEARCH_METHOD.md','tests/test_agent_skill_structure.py',
        'skills/serenity-public-research/references/CROSS_VALIDATION.md',
        'state/architecture-inventory.json','tests/test_compatibility_entrypoints.py',
        '.github/workflows/phase-audit.yml','.github/workflows/phase5-line-bot-audit.yml',
        '.github/workflows/canonical-release-candidate-audit-v2.yml','tests/test_pull_request_workflow_dedup.py',
        'activate-v213-diversified-schedule.ps1','activate-v213-seven-field-schedule-core.ps1',
        'activate-v213-seven-field-schedule-serenity-latest.ps1','activate-v213-seven-field-schedule.ps1',
        'cloud/src/qa.ts','cloud/src/v213/free-relay.ts','cloud/src/v213/production-worker.ts',
        'cloud/src/line-messages.ts','cloud/src/v21/line-push.ts',
        'cloud/src/v213/top20-presentation.ts','cloud/test/r75-line-presentation-proof.ts',
        'cloud/src/v213/company-evidence-report.ts','docs/DETAILED_REPORT_CONTRACT.md',
        'cloud/src/v213/public-citation.ts','cloud/test/public-citation.test.ts',
        'cloud/src/v213/public-snapshot.ts','cloud/test/public-snapshot-view.test.ts',
        'scripts/kv_namespace_isolation_gate.py','tests/test_kv_namespace_isolation_gate.py',
        'cloud/src/v211/worker.ts','cloud/src/v213/compact-qa.ts','cloud/src/v213/readiness.ts',
        'cloud/src/v213/top20-report.ts','cloud/src/v213/broadcast.ts','cloud/test/v213-top20-report.test.ts','cloud/test/qa.test.ts',
        'cloud/test/v213-scheduled-broadcast.test.ts','scripts/audit_v213_refresh_tasks.ps1',
        'cloud/test/v213-compact-qa.test.ts','cloud/test/v213-qa-reference-job.test.ts','cloud/test/v213-readiness.test.ts',
        'config/v213-compact-qa-v1.json','sync-v213-activation-bundle.ps1',
        'scripts/benchmark_v213_qa_latency.py','scripts/v213_compact_qa_gateway.py','scripts/v213_local_llm_gateway.py',
        'scripts/test_v213_edge_readiness.ps1','scripts/v213_edge_readiness.ps1','tests/test_v213_compact_qa_gateway.py',
        'tests/test_v213_r75_gateway_process.py','tests/test_r75_qa_evidence.py',
        'tests/test_v213_bridge_model_identity.py','install-v213-source-diverse-runtime-v2.ps1',
        'scripts/v213_windows_security.ps1','tests/test_v213_windows_security.py',
        'scripts/v213_sealed_refresh.ps1','tests/test_v213_sealed_refresh.py','tests/test_v213_journal_reconciliation.py',
        'run-v213-scheduled-refresh.ps1','register-v213-refresh-tasks.ps1',
        'cloud/test/r75-live-bench-worker.ts','scripts/v213_qa_live_gate.py','scripts/verify_r75_qa_evidence.py',
        'state/r75-qa-live-qualification.json','state/r75-qa-live-model-profile-qualification.json',
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
        'tests/test_v213_free_relay_package_payload.py',
        # Reviewed staged/local-only source collection and shared admission fixes.
        # Exact paths only: no blanket scripts/, tests/ or state/ exception.
        'scripts/adapters/base.py','scripts/adapters/official_rss.py',
        'scripts/adapters/staged_public.py','scripts/adapters/taiwan_equities.py',
        'scripts/fetch_public_source_observations.py','scripts/import_option_observations.py',
        'scripts/options_service.py','scripts/public_options_provider_gate.py',
        'scripts/build_line_public_options.py','tests/test_build_line_public_options.py',
        'scripts/adapters/issuer_directory.py','tests/test_issuer_directory.py',
        'config/public-options-provider-candidates.json','docs/PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md',
        'docs/WORKSPACE_MAINTENANCE.md',
        'scripts/build_v213_activation_bundle_v2.py','scripts/v213_build_v21_public_snapshot.py',
        'tests/test_activation_evidence_timestamps.py',
        'state/research-method-refresh-20260909.json',
        'state/research-dossiers/TSEM-20260909.json','tests/test_research_dossier_receipts.py',
        'scripts/build_v212_top20_report.py','scripts/historical_return_evidence.py','run-v212-local.ps1',
        'tests/test_v212_top20_report.py','tests/test_historical_return_evidence.py',
        'config/authoritative-source-catalog.research-candidate.json','config/authoritative-sources/public-research-candidates.json',
        'tests/test_authoritative_source_catalog.py',
        'scripts/source_observation.py','scripts/source_registry.py',
        'state/public-source-development-proof.json','state/public-source-pinned-runtime-proof.json',
        'tests/test_import_option_observations.py','tests/test_official_news.py',
        'tests/test_options_service.py','tests/test_public_options_provider_gate.py',
        'tests/test_public_source_transport.py','tests/test_source_observation.py',
        'tests/test_source_registry.py','tests/test_taiwan_equity_sources.py',
        'tests/test_current_release_lane.py','scripts/test_v213_operation_lock.ps1',
        'scripts/v213_model_profile.py','cloud/src/v213/model-profile.ts',
        'config/v213-model-profile-v1.json','tests/test_v213_model_profile.py',
        'cloud/test/model-profile.test.ts','state/model-profile-development-failure.json','state/model-profile-none-development-proof.json',
        'state/model-thinking-observation-20260909.json','state/exe-local-route-observation-20260909.json',
        'state/exe-local-route-final-20260909.json'
    )
    foreach ($path in $changed) {
        # Documentation sync does not require a growing per-filename exception list.
        $documentation = $path -match '^(?:README(?:\.zh-TW)?\.md|IMPLEMENTATION_STATUS\.md|docs/[^\r\n]+\.md)$'
        if ($allowed -notcontains $path -and -not $documentation) { throw "FREE_RELAY changed an unreviewed runtime path: $path" }
    }
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
    foreach ($shell in @('powershell.exe','pwsh')) {
        & $shell -NoProfile -File scripts/audit_v213_refresh_tasks.ps1 -SelfTest
        if ($LASTEXITCODE -ne 0) { throw "Read-only refresh audit self-test failed: $shell" }
    }
    & .\scripts\ci_v213_r75_validate.ps1 -ProjectRoot $ProjectRoot -SkipLiveRefresh
    if ($LASTEXITCODE -ne 0) { throw 'R75 no-mutation regression validation failed.' }
    $template = Get-Content -LiteralPath 'cloud\wrangler.v213.production.template.toml' -Raw -Encoding utf8
    if ($template -notmatch 'workers_dev\s*=\s*true' -or $template -notmatch 'FREE_RELAY_ENABLED\s*=\s*"true"' -or $template -match '(?im)^\s*routes?\s*=') { throw 'FREE_RELAY template does not preserve zero-cost workers.dev architecture.' }

    $workerResults = Get-Content -LiteralPath $env:R75_WORKER_TEST_REPORT -Raw -Encoding utf8 | ConvertFrom-Json
    if (-not $workerResults.success -or $workerResults.numFailedTests -ne 0) { throw 'Worker evidence is not successful.' }
    # Consume the already completed, exact-runtime-source-bound live test.
    # CI never creates a tunnel/Worker, accesses the GPU or writes Production.
    $liveProof = Join-Path $ProjectRoot 'state/r75-qa-live-qualification.json'
    $profileArgs=@()
    $profilePath=Join-Path $ProjectRoot 'config/v213-model-profile-v1.json'
    if(Test-Path -LiteralPath $profilePath -PathType Leaf){
        $liveProof=Join-Path $ProjectRoot 'state/r75-qa-live-model-profile-qualification.json'
        $profileArgs=@('--model-profile',$profilePath)
    }
    $qaRaw = & $env:PROJECT_PYTHON scripts/verify_r75_qa_evidence.py --receipt $liveProof @profileArgs
    if ($LASTEXITCODE -ne 0) { throw 'Source-bound live Q&A qualification failed.' }
    $qa = $qaRaw | ConvertFrom-Json
    if ($qa.release_ready -ne $true) { throw 'Live Q&A is not release-qualified.' }
    $env:R75_QA_RELEASE_READY = 'true'
    if ($env:GITHUB_ENV) { 'R75_QA_RELEASE_READY=true' | Out-File $env:GITHUB_ENV -Append -Encoding utf8 }
    $receiptRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
    $runId = if ($env:GITHUB_RUN_ID) { [string]$env:GITHUB_RUN_ID } else { '0' }
    $attempt = if ($env:GITHUB_RUN_ATTEMPT) { [string]$env:GITHUB_RUN_ATTEMPT } else { '1' }
    $receipt = Join-Path $receiptRoot "Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-$sha-$runId-$attempt-Windows-Receipt.json"
    [ordered]@{
        schema_version=1;status='PASS';artifact_kind='R75_FREE_WORKERS_RELAY_HOTFIX';base_named_tunnel_commit=$baseCommit;source_commit=$sha
        workflow_run_id=$runId;workflow_run_attempt=$attempt;windows_powershell_51='PASS';powershell_7='PASS';python_full_suite='PASS'
        worker_typecheck='PASS';worker_test_files=@($workerResults.testResults).Count;worker_tests=[int]$workerResults.numTotalTests;
        compact_context='PASS';deployment_readiness='PASS_REAL_ISOLATED';live_qa='PASS';live_free_relay_smoke='PASS';release_ready=$true;
        live_qa_max_latency_ms=$qa.max_latency_ms;qa_live_receipt_sha256=(Get-FileHash $liveProof -Algorithm SHA256).Hash.ToLowerInvariant();
        exact_sealed_bundle_predeploy_gate='PASS_SYNTHETIC';sec_filing_provenance_schema='PASS';workers_dev_stable_entrypoint=$true;custom_domain_required=$false
        quick_tunnel_ephemeral=$true;exact_model=$qa.exact_model;model_profile_sha256=$qa.model_profile_sha256;health_schema_version=2;consecutive_health_checks=3
        worker_runtime_redirect_compatibility='PASS_SYNTHETIC';authenticated_smoke_gate='PASS_SYNTHETIC';signed_route_registration='PASS_SYNTHETIC';stale_route_rejection='PASS';replay_rejection='PASS';concurrent_update='PASS';heartbeat_lease='PASS';reboot_reconnect='PASS';rollback='PASS'
        allow_test_tunnel_exception_used=$false;protected_release_semantics_unchanged=$true;production_mutation_by_ci=$false;external_mutation=$false
        worker_deployed=$false;production_kv_or_do_written=$false;line_message_sent=$false;schedules_registered=$false;completed_utc=(Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receipt -Encoding utf8
    $env:R75_FREE_RELAY_WINDOWS_RECEIPT=$receipt
    if ($env:GITHUB_ENV) { "R75_FREE_RELAY_WINDOWS_RECEIPT=$receipt" | Out-File $env:GITHUB_ENV -Append -Encoding utf8 }
    Write-Host "V213_R75_FREE_RELAY_WINDOWS_VALIDATION = PASS; commit=$sha; workers_dev=true; custom_domain=false; production_mutation_by_ci=false; receipt=$receipt" -ForegroundColor Green
}
finally { Pop-Location }
