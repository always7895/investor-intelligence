[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
Push-Location $ProjectRoot
try {
    if (-not $env:R70_VALIDATION -or -not (Test-Path -LiteralPath $env:R70_VALIDATION -PathType Leaf)) { throw 'R70 validation receipt is missing.' }
    $validation = Get-Content -LiteralPath $env:R70_VALIDATION -Raw -Encoding utf8 | ConvertFrom-Json
    if ([string]$validation.status -ne 'PASS' -or $validation.production_mutation -ne $false) { throw 'R70 validation receipt is not a no-mutation PASS.' }

    $csc = @(
        "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $csc) { throw 'csc.exe is unavailable.' }
    $launcherSource = Get-Content launcher\InvestorIntelligenceLauncher.cs -Raw -Encoding utf8
    $launcherSource = [regex]::Replace($launcherSource,'const string Revision = "[^"]+";','const string Revision = "Serenity-Latest-MultiSource-R70";',1)
    $temporarySource = Join-Path $env:RUNNER_TEMP 'InvestorIntelligence-R70.cs'
    $launcherExe = Join-Path $env:RUNNER_TEMP 'InvestorIntelligence-R70.exe'
    [IO.File]::WriteAllText($temporarySource,$launcherSource,[Text.UTF8Encoding]::new($false))
    & $csc /nologo /target:winexe /platform:anycpu /optimize+ /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "/out:$launcherExe" $temporarySource
    if ($LASTEXITCODE -ne 0) { throw 'R70 launcher compilation failed.' }

    # The temporary EXE is intentionally not beside the package scripts yet.
    # Only standalone launcher tests are valid before hydration.  The complete
    # --self-test is executed again below after the EXE is inside the expanded
    # package root, where it can resolve run-v213-local.ps1 and the bridge.
    foreach ($argument in @('--pipe-hold-self-test','--model-selection-self-test')) {
        $process = Start-Process $launcherExe -ArgumentList $argument -PassThru
        if (-not $process.WaitForExit(25000)) { Stop-Process $process.Id -Force -ErrorAction SilentlyContinue; throw "Standalone launcher self-test timed out: $argument" }
        if ($process.ExitCode -ne 0) { throw "Standalone launcher self-test failed: $argument / $($process.ExitCode)" }
    }
    Write-Host 'V213_R70_LAUNCHER_PREPACKAGE = PASS; model_selector=true; pipe_nonblocking=true; full_self_test_deferred_until_hydrated=true' -ForegroundColor Green

    $root = Join-Path $env:RUNNER_TEMP "ii-v213-r70-delivery-$env:GITHUB_RUN_ID"
    $stage = Join-Path $root 'Investor-Intelligence-v2.1.3-Serenity-Latest-MultiSource-R70'
    $versions = Join-Path $stage 'versions'
    New-Item -ItemType Directory -Force -Path $stage,$versions | Out-Null
    $refs = [ordered]@{
        '2.1.0' = 'bbc2987e54eccef350685447b48e1841c4e5ba19'
        '2.1.1' = '22593c82743ad97aff91469ba001700d2a384c48'
        '2.1.2' = '1a36935bf8532be074707eeb7f941d8a46be6ca9'
        '2.1.3' = $env:GITHUB_SHA.ToLowerInvariant()
    }
    foreach ($entry in $refs.GetEnumerator()) {
        $archive = Join-Path $versions ("Investor-Intelligence-v$($entry.Key)-source.zip")
        git archive --format=zip --output="$archive" $entry.Value
        if ($LASTEXITCODE -ne 0) { throw "git archive failed for v$($entry.Key)" }
    }
    Expand-Archive (Join-Path $versions 'Investor-Intelligence-v2.1.3-source.zip') $stage -Force
    Copy-Item (Join-Path $stage 'run-v213-local-serenity-latest.ps1') (Join-Path $stage 'run-v213-local.ps1') -Force
    Copy-Item (Join-Path $stage 'activate-v213-seven-field-schedule-serenity-latest.ps1') (Join-Path $stage 'activate-v213-seven-field-schedule.ps1') -Force
    Copy-Item (Join-Path $stage 'install-v213-serenity-latest-runtime.ps1') (Join-Path $stage 'install-v213-source-diverse-runtime.ps1') -Force
    Copy-Item $launcherExe (Join-Path $stage 'InvestorIntelligence.exe') -Force
    if ((Get-FileHash -LiteralPath $launcherExe -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath (Join-Path $stage 'InvestorIntelligence.exe') -Algorithm SHA256).Hash) {
        throw 'Staged launcher does not exactly match the newly compiled model-selector launcher.'
    }
    Remove-Item (Join-Path $stage 'tmp') -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $stage '.venv-v213-r70-validation') -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $stage 'cloud\node_modules') -Recurse -Force -ErrorAction SilentlyContinue

    [ordered]@{
        schema_version = 11
        package_version = '2.1.3'
        launcher_revision = 'Serenity-Latest-MultiSource-R70'
        launcher_ui = [ordered]@{model_selector=$true;scan_button=$true;use_button=$true;async_long_running_handlers=$true;model_scan_off_ui_thread=$true}
        current_commit = $env:GITHUB_SHA.ToLowerInvariant()
        versions = $refs
        local_model = [ordered]@{explicit_selector=$true;preferred_model='RVN-Q6_K-multilingual-mtp';silent_model_substitution=$false;health_schema_version=2}
        serenity_public_logic = [ordered]@{label='high-fidelity public-logic reconstruction';official_formula=$false;official_score=$false;private_method_reproduced=$false;latest_public_source_required=$true;public_posts_are_company_fact_authority=$false}
        source_policy = [ordered]@{policy='v213-serenity-latest-multisource-v5';per_ticker_claim_families=2;per_ticker_claim_domains=2;per_ticker_primary=1;claim_dated_ratio=0.8;portfolio_source_families=3;portfolio_domains=3;maximum_single_family_share=0.70;source_values_averaged=$false}
        freshness_days = [ordered]@{snapshot_hours=2;market_high_confidence=4;market_absolute_maximum=7;market_provider_gap=3;company_current_state=135;structural_claim=550;official_macro=45;serenity_metadata_retrieval_hours=24}
        market = [ordered]@{yahoo_role='compatibility_calculation_only_not_truth_anchor';high_confidence_independent_providers=2;same_metric_basis_required=$true;pairwise_conflict_detection=$true;uncorroborated_valuation_factor_max=3.75}
        factor_logic = [ordered]@{factor_ledger='data/cache/v213_serenity_factor_ledger_latest.json';severe_thesis_killers_override_score=$true;tam_capture_requires_current_revenue_or_order_evidence=$true;keyword_sector_margin_shortcuts_prohibited=$true}
        methodology_lineage = 'config/v213-serenity-methodology-lineage-v1.json'
        atomic_activation = [ordered]@{payloads=7;pointer_written_last=$true;pointer_readback_verified=$true;exact_pointer_rollback=$true;exact_worker_rollback=$true;idempotent_replay=$true;run_id_collision_rejected=$true}
        wrangler_json = [ordered]@{invocation='direct_node';mixed_stdout_banner_tolerant=$true;ansi_banner_tolerant=$true;ambiguous_documents_rejected=$true;single_active_version_required=$true}
        schedule = @('08:00 Asia/Taipei','21:00 Asia/Taipei')
        local_refresh = @('07:20','20:20')
        production_deployment_performed_by_packaging = $false
    } | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $stage 'VERSION-REFS.json') -Encoding utf8

    $manifest = @()
    Get-ChildItem $stage -File -Recurse | ForEach-Object {
        $manifest += [ordered]@{
            path = $_.FullName.Substring($stage.Length + 1).Replace('\','/')
            bytes = $_.Length
            sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    [ordered]@{schema_version=11;commit=$env:GITHUB_SHA.ToLowerInvariant();generated_utc=(Get-Date).ToUniversalTime().ToString('o');files=$manifest} | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $stage 'MANIFEST.json') -Encoding utf8
    Get-ChildItem $stage -File -Recurse | ForEach-Object {
        '{0}  {1}' -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(),$_.FullName.Substring($stage.Length + 1).Replace('\','/')
    } | Set-Content (Join-Path $stage 'SHA256SUMS.txt') -Encoding ascii

    $zip = Join-Path $root 'Investor-Intelligence-v2.1.3-Serenity-Latest-MultiSource-R70.zip'
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
    $sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    $shaFile = $zip + '.sha256'
    Set-Content -LiteralPath $shaFile -Value $sha -Encoding ascii

    $check = Join-Path $root 'check'
    $stable = Join-Path $root 'stable'
    Expand-Archive $zip $check
    foreach ($file in @(
        'InvestorIntelligence.exe','run-v213-local.ps1','activate-v213-seven-field-schedule.ps1',
        'activate-v213-seven-field-schedule-core.ps1','install-v213-source-diverse-runtime.ps1',
        'scripts\v213_refresh_serenity_public_sources.py','scripts\v213_serenity_latest_multisource_audit.py',
        'scripts\v213_tam_capture_claim_guard.py','scripts\v213_serenity_latest_static_audit.py',
        'config\v213-serenity-latest-multisource-policy-v5.json','config\v213-serenity-methodology-lineage-v1.json',
        'sync-v213-activation-bundle.ps1','cloud\src\v213\activation-v2.ts',
        'VERSION-REFS.json','MANIFEST.json','SHA256SUMS.txt',
        'versions\Investor-Intelligence-v2.1.0-source.zip','versions\Investor-Intelligence-v2.1.1-source.zip',
        'versions\Investor-Intelligence-v2.1.2-source.zip','versions\Investor-Intelligence-v2.1.3-source.zip'
    )) { if (-not (Test-Path -LiteralPath (Join-Path $check $file) -PathType Leaf)) { throw "Final package missing: $file" } }
    if (Test-Path -LiteralPath (Join-Path $check 'tmp')) { throw 'Temporary data leaked into final package.' }

    $packageRefs = Get-Content -LiteralPath (Join-Path $check 'VERSION-REFS.json') -Raw -Encoding utf8 | ConvertFrom-Json
    if ([string]$packageRefs.launcher_revision -ne 'Serenity-Latest-MultiSource-R70' -or $packageRefs.launcher_ui.model_selector -ne $true -or $packageRefs.launcher_ui.scan_button -ne $true -or $packageRefs.launcher_ui.use_button -ne $true -or $packageRefs.launcher_ui.async_long_running_handlers -ne $true -or $packageRefs.local_model.explicit_selector -ne $true -or [string]$packageRefs.local_model.preferred_model -ne 'RVN-Q6_K-multilingual-mtp') {
        throw 'Packaged launcher/model-selector metadata contract is invalid.'
    }
    if ((Get-FileHash -LiteralPath (Join-Path $check 'InvestorIntelligence.exe') -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $launcherExe -Algorithm SHA256).Hash) {
        throw 'Expanded package contains a stale or different launcher EXE.'
    }
    foreach ($argument in @('--self-test','--pipe-hold-self-test','--model-selection-self-test')) {
        $process = Start-Process (Join-Path $check 'InvestorIntelligence.exe') -ArgumentList $argument -PassThru
        if (-not $process.WaitForExit(25000)) { Stop-Process $process.Id -Force -ErrorAction SilentlyContinue; throw "Packaged EXE self-test timed out: $argument" }
        if ($process.ExitCode -ne 0) { throw "Packaged EXE self-test failed: $argument / $($process.ExitCode)" }
    }
    Write-Host 'V213_R70_PACKAGED_LAUNCHER = PASS; model_selector=true; scan=true; use=true; async_ui=true; stale_exe=false; full_self_test=true' -ForegroundColor Green

    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $check 'run-v213-local.ps1') -ProjectRoot $check -SelfTest
    if ($LASTEXITCODE -ne 0) { throw 'Packaged final refresh self-test failed.' }
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $check 'activate-v213-seven-field-schedule.ps1') -ProjectRoot $check -SelfTest
    if ($LASTEXITCODE -ne 0) { throw 'Packaged final activation self-test failed.' }
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $check 'install-v213-source-diverse-runtime.ps1') -ProjectRoot $check -RuntimeRoot $stable
    if ($LASTEXITCODE -ne 0) { throw 'Stable final runtime installation failed.' }
    foreach ($file in @('run-v213-local.ps1','activate-v213-seven-field-schedule.ps1','scripts\v213_serenity_latest_multisource_audit.py','config\v213-serenity-latest-multisource-policy-v5.json','V213-SERENITY-LATEST-RUNTIME.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $stable $file) -PathType Leaf)) { throw "Stable runtime missing: $file" }
    }
    $manifestDoc = Get-Content (Join-Path $check 'MANIFEST.json') -Raw -Encoding utf8 | ConvertFrom-Json
    foreach ($entry in @($manifestDoc.files)) {
        $path = Join-Path $check ([string]$entry.path).Replace('/','\')
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Manifest path missing: $($entry.path)" }
        if ((Get-Item -LiteralPath $path).Length -ne [long]$entry.bytes) { throw "Manifest size mismatch: $($entry.path)" }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$entry.sha256) { throw "Manifest hash mismatch: $($entry.path)" }
    }

    $verification = Join-Path $root 'Investor-Intelligence-v2.1.3-Serenity-Latest-MultiSource-R70-Verification.json'
    [ordered]@{
        schema_version = 2
        status = 'PASS'
        commit = $env:GITHUB_SHA.ToLowerInvariant()
        workflow_run_id = [string]$env:GITHUB_RUN_ID
        production_mutation = $false
        windows_validation = $env:R70_VALIDATION
        latest_public_serenity_source = [string]$validation.latest_public_serenity_source
        per_ticker_multi_source = $true
        two_market_providers_for_high_confidence = $true
        same_market_metric_basis_required = $true
        yahoo_truth_anchor = $false
        source_values_averaged = $false
        factor_ledger = $true
        severe_thesis_killer_precedence = $true
        atomic_payloads = 7
        launcher_model_selector = $true
        launcher_scan_button = $true
        launcher_use_button = $true
        launcher_async_long_running_handlers = $true
        launcher_stale_exe_rejected = $true
        packaged_exe_tests = $true
        stable_runtime_test = $true
        manifest_verified = $true
        zip_sha256 = $sha
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $verification -Encoding utf8

    $receipt = Join-Path $root 'Investor-Intelligence-v2.1.3-Serenity-Latest-MultiSource-R70-Delivery-Receipt.json'
    [ordered]@{
        schema_version = 2
        status = 'PASS'
        package = [IO.Path]::GetFileName($zip)
        zip_sha256 = $sha
        bytes = (Get-Item -LiteralPath $zip).Length
        commit = $env:GITHUB_SHA.ToLowerInvariant()
        workflow_run_id = [string]$env:GITHUB_RUN_ID
        launcher_revision = 'Serenity-Latest-MultiSource-R70'
        model_selector_verified = $true
        responsive_async_ui_verified = $true
        production_mutation_by_ci = $false
        next_stage = 'user_local_formal_activation'
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receipt -Encoding utf8

    $desktopCandidates = @(
        [Environment]::GetFolderPath('Desktop'),
        (Join-Path $env:USERPROFILE 'Desktop'),
        'C:\Users\moon9\Desktop'
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) } | Select-Object -Unique
    $desktopDeliveries = @()
    foreach ($desktop in $desktopCandidates) {
        $destination = Join-Path $desktop 'Investor-Intelligence-v2.1.3-Final-Delivery'
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        foreach ($file in @($zip,$shaFile,$verification,$receipt,$env:R70_VALIDATION)) { Copy-Item -LiteralPath $file -Destination $destination -Force }
        $copied = Join-Path $destination ([IO.Path]::GetFileName($zip))
        if ((Get-FileHash -LiteralPath $copied -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha) { throw "Desktop delivery hash mismatch: $copied" }
        $desktopDeliveries += $destination
    }
    if ($desktopDeliveries.Count -eq 0) { throw 'No user Desktop directory was available for direct delivery.' }

    "R70_ZIP=$zip" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
    "R70_SHA_FILE=$shaFile" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
    "R70_VERIFICATION=$verification" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
    "R70_RECEIPT=$receipt" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
    "R70_SHA=$sha" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
    "R70_DESKTOP=$($desktopDeliveries[0])" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
    Write-Host "V213_R70_PACKAGE_AND_DESKTOP_DELIVERY = PASS; sha256=$sha; desktop=$($desktopDeliveries -join ';')" -ForegroundColor Green
}
finally { Pop-Location }
