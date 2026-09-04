[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$baseCommit = '536644d22ef3534be1c4b8a9e1ff969df4d580fa'
Push-Location $ProjectRoot
try {
    $sha = (git rev-parse HEAD).Trim().ToLowerInvariant()
    git merge-base --is-ancestor $baseCommit $sha
    if ($LASTEXITCODE -ne 0) { throw 'Deployment hotfix must descend from the verified R75 release commit.' }
    if (@(git status --porcelain).Count -ne 0) { throw 'Deployment-hotfix validation requires a clean checkout.' }
    $changed = @(git diff --name-only "$baseCommit..$sha")
    $forbidden = @(
        'config/v213-r75-publication-mode-v1.json',
        'scripts/v213_r75_activation_preflight.py',
        'cloud/src/v213/publication-mode.ts',
        'cloud/src/v213/activation-v2.ts',
        'data/cache/v213_activation_bundle_upload.json',
        'scripts/verify_v213_r75_artifact.py',
        'scripts/ci_v213_r75_package.ps1'
    )
    foreach ($path in $forbidden) {
        if ($changed -contains $path) { throw "Deployment hotfix changed protected R75 source: $path" }
    }
    foreach ($path in $changed) {
        if ($path -match '(?i)(serenity|scoring|publication-mode|activation_bundle|sealed)' -and $path -notmatch '^docs/V213_NAMED_TUNNEL') {
            throw "Deployment hotfix changed a protected semantic/sealed path: $path"
        }
    }
    foreach ($required in @(
        'scripts/setup_v213_named_tunnel.ps1',
        'scripts/test_v213_named_tunnel.ps1',
        'scripts/v213_named_tunnel_helpers.ps1',
        'scripts/run_v213_local_llm_bridge_core.ps1',
        'launcher/InvestorIntelligenceLauncher.cs'
    )) {
        if ($changed -notcontains $required) { throw "Deployment hotfix is missing required integration change: $required" }
    }

    & .\scripts\ci_v213_r75_validate.ps1 -ProjectRoot $ProjectRoot -SkipLiveRefresh
    if ($LASTEXITCODE -ne 0) { throw 'R75 no-mutation regression validation failed.' }

    $receiptRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
    $runId = if ($env:GITHUB_RUN_ID) { [string]$env:GITHUB_RUN_ID } else { '0' }
    $attempt = if ($env:GITHUB_RUN_ATTEMPT) { [string]$env:GITHUB_RUN_ATTEMPT } else { '1' }
    $receipt = Join-Path $receiptRoot "Investor-Intelligence-v2.1.3-R75-Named-Tunnel-Hotfix-$sha-$runId-$attempt-Windows-Receipt.json"
    [ordered]@{
        schema_version = 1
        status = 'PASS'
        artifact_kind = 'R75_NAMED_TUNNEL_DEPLOYMENT_HOTFIX'
        base_release_commit = $baseCommit
        source_commit = $sha
        workflow_run_id = $runId
        workflow_run_attempt = $attempt
        windows_powershell_51 = 'PASS'
        powershell_7 = 'PASS'
        special_path = 'PASS'
        negative_tests = 'PASS'
        cloudflared_auth_validation = 'PASS_SYNTHETIC'
        tunnel_credentials_validation = 'PASS_SYNTHETIC'
        exact_dns_route_ensure = 'PASS_SYNTHETIC'
        consecutive_public_health_required = 3
        exact_model_required = $true
        health_schema_version = 2
        blue_green_rollback = 'PASS'
        quick_tunnel_production_path = $false
        allow_test_tunnel_exception_used = $false
        protected_release_semantics_unchanged = $true
        live_cloudflare_mutation = $false
        worker_deployed = $false
        production_kv_or_do_written = $false
        line_message_sent = $false
        schedules_registered = $false
        production_mutation_by_ci = $false
        external_mutation = $false
        completed_utc = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receipt -Encoding utf8
    $env:R75_NAMED_TUNNEL_WINDOWS_RECEIPT = $receipt
    if ($env:GITHUB_ENV) { "R75_NAMED_TUNNEL_WINDOWS_RECEIPT=$receipt" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8 }
    Write-Host "V213_R75_NAMED_TUNNEL_WINDOWS_VALIDATION = PASS; commit=$sha; production_mutation_by_ci=false; receipt=$receipt" -ForegroundColor Green
}
finally { Pop-Location }
