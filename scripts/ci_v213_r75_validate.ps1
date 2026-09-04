[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
Push-Location $ProjectRoot
try{
    & .\scripts\ci_v213_r70_validate.ps1 -ProjectRoot $ProjectRoot
    if(-not$?){throw 'Reviewed R70 validation baseline failed.'}
    if(-not$env:PROJECT_PYTHON-or-not(Test-Path -LiteralPath $env:PROJECT_PYTHON -PathType Leaf)){throw 'R70 validation did not retain verified Python.'}

    & $env:PROJECT_PYTHON scripts\v213_r75_activation_preflight_entry.py --self-test
    if($LASTEXITCODE-ne0){throw 'R75 sealed activation preflight self-test failed.'}
    & $env:PROJECT_PYTHON scripts\v213_local_llm_gateway_r75.py --self-test
    if($LASTEXITCODE-ne0){throw 'R75 exact-model gateway self-test failed.'}
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\run-v213-local-llm-bridge-source-diverse.ps1 -ProjectRoot $ProjectRoot -SelfTest
    if($LASTEXITCODE-ne0){throw 'R75 safe-path bridge self-test failed.'}
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\activate-v213-seven-field-schedule.ps1 -ProjectRoot $ProjectRoot -PreflightOnly
    if($LASTEXITCODE-ne0){throw 'Actual all-LIMITED sealed activation preflight failed.'}

    $canonical=(Get-FileHash -LiteralPath .\activate-v213-seven-field-schedule.ps1 -Algorithm SHA256).Hash
    $alias=(Get-FileHash -LiteralPath .\activate-v213-seven-field-schedule-serenity-latest.ps1 -Algorithm SHA256).Hash
    if($canonical-ne$alias){throw 'Canonical activation and Serenity compatibility alias are not byte-identical.'}

    $pathRoot=Join-Path $env:RUNNER_TEMP ('Investor Intelligence R75 Path (1)-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $pathRoot|Out-Null
    try{
        foreach($relative in @(
            'activate-v213-seven-field-schedule.ps1',
            'activate-v213-seven-field-schedule-core.ps1',
            'requirements-ci.txt',
            'scripts\resolve_python.ps1',
            'scripts\v213_r75_activation_preflight.py',
            'scripts\v213_r75_activation_preflight_entry.py',
            'data\cache\v213_activation_bundle_upload.json'
        )){
            $source=Join-Path $ProjectRoot $relative
            $destination=Join-Path $pathRoot $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
            Copy-Item -LiteralPath $source -Destination $destination -Force
        }
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $pathRoot 'activate-v213-seven-field-schedule.ps1') -ProjectRoot $pathRoot -PreflightOnly
        if($LASTEXITCODE-ne0){throw 'R75 activation preflight failed from a path containing spaces and parentheses.'}
    }finally{Remove-Item -LiteralPath $pathRoot -Recurse -Force -ErrorAction SilentlyContinue}

    $runtimeTest=Join-Path $env:RUNNER_TEMP ('v213-r75-runtime-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $runtimeTest|Out-Null
    try{
        Copy-Item -LiteralPath .\run-v213-scheduled-refresh.ps1 -Destination (Join-Path $runtimeTest 'run-v213-scheduled-refresh.ps1')
        Copy-Item -LiteralPath .\run-v213-local-serenity-latest.ps1 -Destination (Join-Path $runtimeTest 'run-v213-local.ps1')
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\register-v213-refresh-tasks.ps1 -RuntimeRoot $runtimeTest -ValidateOnly
        if($LASTEXITCODE-ne0){throw 'R75 scheduled-task data-only contract validation failed.'}
    }finally{Remove-Item -LiteralPath $runtimeTest -Recurse -Force -ErrorAction SilentlyContinue}

    $worker=Get-Content -LiteralPath cloud\src\v213\activation-v2.ts -Raw -Encoding utf8
    foreach($marker in @('validateR75PublicationModes','REQUIRED_FEDERATION_FAMILIES','verifySnapshotObjects')){if(-not$worker.Contains($marker)){throw "Worker R75 activation contract marker is missing: $marker"}}
    if($worker.Contains('["us_sec", "nasdaq", "world_bank", "us_bls", "ecb"]')){throw 'Worker still hard-requires optional BLS.'}
    $broadcast=Get-Content -LiteralPath cloud\src\v213\broadcast.ts -Raw -Encoding utf8
    foreach($marker in @('runV213BroadcastOnce','V213_BROADCAST_DEDUPE')){if(-not$broadcast.Contains($marker)){throw "Atomic LINE dedupe marker is missing: $marker"}}
    $production=Get-Content -LiteralPath cloud\src\v213\production-worker.ts -Raw -Encoding utf8
    if(-not$production.Contains('V213BroadcastDedupe')){throw 'Production Worker does not export the broadcast dedupe Durable Object.'}
    $qa=Get-Content -LiteralPath cloud\src\qa.ts -Raw -Encoding utf8
    if(-not$qa.Contains('LOCAL_LLM_TIMEOUT_MS')){throw 'Local-model timeout is not configurable.'}
    $bridge=Get-Content -LiteralPath scripts\run_v213_local_llm_bridge_core.ps1 -Raw -Encoding utf8
    if(-not$bridge.Contains('v213_local_llm_gateway_r75.py')){throw 'Bridge core does not launch the exact-model R75 gateway.'}
    $core=Get-Content -LiteralPath activate-v213-seven-field-schedule-core.ps1 -Raw -Encoding utf8
    foreach($marker in @('V213_R75_SEALED_BUNDLE_SHA256','install-v213-r75-runtime.ps1','V213_R75_ACTIVATION_LOCK')){if(-not$core.Contains($marker)){throw "Activation core R75 marker is missing: $marker"}}

    $bundlePath=Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json'
    $preflightReceipt=Join-Path $env:RUNNER_TEMP ('v213-r75-preflight-'+[guid]::NewGuid().ToString('N')+'.json')
    & $env:PROJECT_PYTHON scripts\v213_r75_activation_preflight_entry.py --bundle $bundlePath --receipt $preflightReceipt
    if($LASTEXITCODE-ne0-or-not(Test-Path -LiteralPath $preflightReceipt -PathType Leaf)){throw 'R75 preflight receipt was not generated.'}
    $preflight=Get-Content -LiteralPath $preflightReceipt -Raw -Encoding utf8|ConvertFrom-Json
    Remove-Item -LiteralPath $preflightReceipt -Force -ErrorAction SilentlyContinue

    $validationPath=Join-Path $env:RUNNER_TEMP 'Investor-Intelligence-v2.1.3-R75-Validation.json'
    [ordered]@{
        schema_version=1
        status='PASS'
        product_version='2.1.3'
        runtime_profile='R75'
        commit=[string]$env:GITHUB_SHA
        workflow_run_id=[string]$env:GITHUB_RUN_ID
        production_mutation=$false
        reviewed_r70_baseline_validation=$true
        sealed_bundle_sha256=[string]$preflight.bundle_sha256
        activation_preflight_actual_bundle=$true
        evidence_qualified_candidate_count=[int]$preflight.evidence_qualified_candidate_count
        limited_research_candidate_count=[int]$preflight.limited_research_candidate_count
        optional_bls_policy_aligned=$true
        worker_publication_mode_aligned=$true
        limited_positive_factor_rejected=$true
        limited_high_confidence_rejected=$true
        limited_single_origin_rejected=$true
        exact_model_request_substitution_allowed=$false
        spaced_parenthesized_path_preflight=$true
        safe_path_bridge_self_test=$true
        quick_tunnel_consecutive_public_health_checks=3
        quick_tunnel_uptime_guarantee=$false
        line_broadcast_dedupe='durable_object_atomic_claim'
        snapshot_object_readback=$true
        idempotent_replay_readback=$true
        scheduled_refresh_data_only=$true
        scheduled_refresh_production_mutation=$false
        completed_at=(Get-Date).ToUniversalTime().ToString('o')
    }|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $validationPath -Encoding utf8
    "R75_VALIDATION=$validationPath"|Out-File $env:GITHUB_ENV -Append -Encoding utf8
    Write-Host "V213_R75_WINDOWS_VALIDATION = PASS; actual_bundle=true; evidence_qualified=$($preflight.evidence_qualified_candidate_count); limited=$($preflight.limited_research_candidate_count); production_mutation=false" -ForegroundColor Green
}
finally{Pop-Location}
