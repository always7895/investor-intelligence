[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [switch]$SkipLiveRefresh
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
Push-Location $ProjectRoot
try {
    $sha = (git rev-parse HEAD).Trim().ToLowerInvariant()
    if ($env:GITHUB_SHA -and $sha -ne $env:GITHUB_SHA.ToLowerInvariant()) {
        throw "Exact checkout mismatch: expected=$env:GITHUB_SHA actual=$sha"
    }

    $portableRoot = Join-Path $(if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }) 'ii-r75-python-3.12.10'
    $resolvedPython = @(
        & .\scripts\bootstrap_portable_python.ps1 -DestinationPath $portableRoot
    ) | Select-Object -Last 1
    $env:PROJECT_PYTHON = [IO.Path]::GetFullPath([string]$resolvedPython)
    if (-not $env:PROJECT_PYTHON -or -not (Test-Path -LiteralPath $env:PROJECT_PYTHON -PathType Leaf)) {
        throw 'Repository-managed Python resolution failed.'
    }
    & $env:PROJECT_PYTHON -m pip install --isolated --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple --require-hashes -r requirements-ci.txt
    if ($LASTEXITCODE -ne 0) { throw 'Hash-locked Python dependency installation failed.' }
    & $env:PROJECT_PYTHON -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed.' }

    foreach ($gate in @(
        'scripts\workflow_supply_chain_gate.py',
        'scripts\actions_storage_policy_gate.py',
        'scripts\security_check.py',
        'scripts\canonical_release_candidate_gate_v2.py'
    )) {
        & $env:PROJECT_PYTHON $gate
        if ($LASTEXITCODE -ne 0) { throw "Repository gate failed: $gate" }
    }
    & $env:PROJECT_PYTHON -m compileall -q scripts tests
    if ($LASTEXITCODE -ne 0) { throw 'Python compile gate failed.' }
    & $env:PROJECT_PYTHON -m unittest discover -s tests -p 'test_*.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Complete Python regression failed.' }
    & $env:PROJECT_PYTHON scripts\v213_r75_activation_preflight.py --self-test
    if ($LASTEXITCODE -ne 0) { throw 'R75 publication preflight self-test failed.' }

    & .\scripts\resolve_node.ps1 -MinimumVersion 22.0.0
    if (-not $env:PROJECT_NPM -or -not (Test-Path -LiteralPath $env:PROJECT_NPM -PathType Leaf)) {
        $env:PROJECT_NPM = (Get-Command npm.cmd -ErrorAction Stop).Source
    }
    $lock = (Get-FileHash cloud\package-lock.json -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($lock -ne '365ca38feb288fbed62bb5723303186e5e591c44b7d60b242e530db357535a57') {
        throw "Worker lock hash mismatch: $lock"
    }
    Push-Location cloud
    try {
        & $env:PROJECT_NPM ci --ignore-scripts --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
        & $env:PROJECT_NPM run typecheck
        if ($LASTEXITCODE -ne 0) { throw 'Worker typecheck failed.' }
        & $env:PROJECT_NPM test
        if ($LASTEXITCODE -ne 0) { throw 'Worker regression failed.' }
    }
    finally { Pop-Location }

    $psScripts = @(
        'activate-v213-seven-field-schedule.ps1',
        'activate-v213-seven-field-schedule-core.ps1',
        'run-v213-local-llm-bridge.ps1',
        'register-v213-refresh-tasks.ps1',
        'run-v213-scheduled-refresh.ps1',
        'scripts\v213_operation_lock.ps1',
        'scripts\test_v213_activation_core.ps1',
        'scripts\ci_v213_r75_validate.ps1'
    )
    foreach ($path in $psScripts) {
        $tokens = $null; $errors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile(
            (Resolve-Path -LiteralPath $path), [ref]$tokens, [ref]$errors
        )
        if (@($errors).Count -ne 0) { throw "PowerShell 7 parser failure: $path" }
    }
    $parseProbe = Join-Path ([IO.Path]::GetTempPath()) ('ii-r75-ps51-parse-' + [guid]::NewGuid().ToString('N') + '.ps1')
    try {
        @(
            'param([string[]]$Paths)',
            'foreach ($path in $Paths) {',
            '  $tokens = $null; $errors = $null',
            '  [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $path),[ref]$tokens,[ref]$errors)',
            '  if (@($errors).Count -ne 0) { $errors | Out-String | Write-Host; exit 1 }',
            '}'
        ) | Set-Content -LiteralPath $parseProbe -Encoding utf8
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $parseProbe -Paths $psScripts
        if ($LASTEXITCODE -ne 0) { throw 'Windows PowerShell 5.1 parser gate failed.' }
    }
    finally { Remove-Item -LiteralPath $parseProbe -Force -ErrorAction SilentlyContinue }

    foreach ($hostExe in @('powershell.exe', 'pwsh.exe')) {
        & $hostExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\test_v213_activation_core.ps1 -ProjectRoot $ProjectRoot
        if ($LASTEXITCODE -ne 0) { throw "Isolated KV-compatible transaction failed under $hostExe" }
        & $hostExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\activate-v213-seven-field-schedule.ps1 -ProjectRoot $ProjectRoot -SelfTest
        if ($LASTEXITCODE -ne 0) { throw "Activation self-test failed under $hostExe" }
        & $hostExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\test_v213_operation_lock.ps1 -ProjectRoot $ProjectRoot
        if ($LASTEXITCODE -ne 0) { throw "Operation-lock test failed under $hostExe" }
    }

    if (-not $SkipLiveRefresh) {
        # The retained R70 validator performs the real public-network refresh in
        # an isolated LOCALAPPDATA root with every mutation/delivery switch off.
        & .\scripts\ci_v213_r70_validate.ps1 -ProjectRoot $ProjectRoot
        if ($LASTEXITCODE -ne 0) { throw 'Real Windows no-mutation refresh failed.' }

        $bundle = Join-Path $ProjectRoot 'data\cache\v213_activation_bundle_upload.json'
        $preflightReceipt = Join-Path $env:RUNNER_TEMP "v213-r75-all-limited-$($env:GITHUB_RUN_ID)-$($env:GITHUB_RUN_ATTEMPT).json"
        & $env:PROJECT_PYTHON scripts\v213_r75_activation_preflight.py --bundle $bundle --receipt $preflightReceipt
        if ($LASTEXITCODE -ne 0) { throw 'Actual sealed-bundle Python preflight failed.' }
        $preflight = Get-Content -LiteralPath $preflightReceipt -Raw -Encoding utf8 | ConvertFrom-Json
        if ([int]$preflight.evidence_qualified_candidate_count -ne 0 -or [int]$preflight.limited_research_candidate_count -ne 20) {
            throw 'Authoritative Windows release gate requires the observed all-LIMITED 20-row bundle.'
        }
        foreach ($hostExe in @('powershell.exe', 'pwsh.exe')) {
            & $hostExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\activate-v213-seven-field-schedule.ps1 -ProjectRoot $ProjectRoot -PreflightOnly
            if ($LASTEXITCODE -ne 0) { throw "Actual all-LIMITED sealed preflight failed under $hostExe" }
        }
    }

    $receiptRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
    $runId = if ($env:GITHUB_RUN_ID) { [string]$env:GITHUB_RUN_ID } else { 'local' }
    $attempt = if ($env:GITHUB_RUN_ATTEMPT) { [string]$env:GITHUB_RUN_ATTEMPT } else { '1' }
    $receipt = Join-Path $receiptRoot "Investor-Intelligence-v2.1.3-R75-$sha-$runId-$attempt-Windows-Receipt.json"
    [ordered]@{
        schema_version = 1
        status = 'PASS'
        source_commit = $sha
        workflow_run_id = $runId
        workflow_run_attempt = $attempt
        windows_powershell_51 = 'PASS'
        powershell_7 = 'PASS'
        python_full_suite = 'PASS'
        worker_typecheck = 'PASS'
        worker_full_tests = 'PASS'
        isolated_kv_transaction = [ordered]@{
            pointer_last = $true
            object_readback = $true
            corrupt_replay_rejected = $true
            rollback = $true
            finalize = $true
        }
        actual_all_limited_bundle_preflight = $(if ($SkipLiveRefresh) { 'SKIPPED_LOCAL_ONLY' } else { 'PASS' })
        production_mutation_by_ci = $false
        line_message_sent = $false
        schedules_registered = $false
        external_mutation = $false
        completed_utc = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receipt -Encoding utf8
    $env:R75_WINDOWS_RECEIPT = $receipt
    if ($env:GITHUB_ENV) { "R75_WINDOWS_RECEIPT=$receipt" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8 }
    Write-Host "V213_R75_WINDOWS_VALIDATION = PASS; commit=$sha; production_mutation_by_ci=false; receipt=$receipt" -ForegroundColor Green
}
finally {
    Pop-Location
}
