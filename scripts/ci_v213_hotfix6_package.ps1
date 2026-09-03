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
    $csc = @(
        "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $csc) { throw 'csc.exe is unavailable.' }
    $launcherSource = Get-Content launcher\InvestorIntelligenceLauncher.cs -Raw -Encoding utf8
    $launcherSource = [regex]::Replace($launcherSource,'const string Revision = "[^"]+";','const string Revision = "SourceDiverse-R60-Hotfix6-WranglerJSON";',1)
    $temporarySource = Join-Path $env:RUNNER_TEMP 'InvestorIntelligence-Hotfix6-WranglerJSON.cs'
    $launcherExe = Join-Path $env:RUNNER_TEMP 'InvestorIntelligence-Hotfix6-WranglerJSON.exe'
    [IO.File]::WriteAllText($temporarySource,$launcherSource,[Text.UTF8Encoding]::new($false))
    & $csc /nologo /target:winexe /platform:anycpu /optimize+ /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "/out:$launcherExe" $temporarySource
    if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
    foreach ($argument in @('--self-test','--pipe-hold-self-test','--model-selection-self-test')) {
        $process = Start-Process $launcherExe -ArgumentList $argument -PassThru
        if (-not $process.WaitForExit(25000)) {
            Stop-Process $process.Id -Force -ErrorAction SilentlyContinue
            throw "Launcher test timed out: $argument"
        }
        if ($process.ExitCode -ne 0) { throw "Launcher test failed: $argument / $($process.ExitCode)" }
    }

    $root = Join-Path $env:RUNNER_TEMP "ii-v213-hf6-delivery-$env:GITHUB_RUN_ID"
    $stage = Join-Path $root 'Investor-Intelligence-v2.1.3-SourceDiverse-R60-Hotfix6-WranglerJSON'
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
    Copy-Item (Join-Path $stage 'run-v213-local-source-diverse.ps1') (Join-Path $stage 'run-v213-local.ps1') -Force
    Copy-Item (Join-Path $stage 'run-v213-local-llm-bridge-source-diverse.ps1') (Join-Path $stage 'run-v213-local-llm-bridge.ps1') -Force
    Copy-Item (Join-Path $stage 'install-v213-source-diverse-runtime-v2.ps1') (Join-Path $stage 'install-v213-source-diverse-runtime.ps1') -Force
    Remove-Item (Join-Path $stage 'tmp') -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item $launcherExe (Join-Path $stage 'InvestorIntelligence.exe') -Force

    [ordered]@{
        schema_version = 9
        package_version = '2.1.3'
        launcher_revision = 'SourceDiverse-R60-Hotfix6-WranglerJSON'
        current_commit = $env:GITHUB_SHA.ToLowerInvariant()
        versions = $refs
        local_model = [ordered]@{explicit_selector=$true;preferred_model='RVN-Q6_K-multilingual-mtp';silent_model_substitution=$false;health_schema_version=2}
        atomic_activation = [ordered]@{enabled=$true;payload_count=7;builder='scripts/build_v213_activation_bundle_v2.py';client='sync-v213-activation-bundle.ps1';worker='cloud/src/v213/activation-v2.ts';immutable_objects_before_pointer=$true;pointer_written_last=$true;pointer_readback_verified=$true;exact_pointer_rollback=$true;exact_worker_rollback=$true;idempotent_replay=$true;run_id_collision_rejected=$true}
        wrangler_json = [ordered]@{invocation='direct_node';cli='node_modules/wrangler/bin/wrangler.js';mixed_stdout_banner_tolerant=$true;ansi_banner_tolerant=$true;ambiguous_documents_rejected=$true;strict_single_active_version=$true;regression='Invalid JSON primitive: wrangler'}
        source_fidelity = [ordered]@{yahoo_role='compatibility_calculation_only';market_endpoint_unavailability_is_global_blocker=$false;high_confidence_requires_market_corroboration=$true;uncorroborated_valuation_factor_max=3.75;source_conflicts_averaged=$false}
        serenity_public_logic = [ordered]@{label='public-logic high-fidelity reconstruction';private_method_reproduced=$false;official_formula=$false;official_score=$false}
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
    [ordered]@{schema_version=9;commit=$env:GITHUB_SHA.ToLowerInvariant();generated_utc=(Get-Date).ToUniversalTime().ToString('o');files=$manifest} |
        ConvertTo-Json -Depth 12 | Set-Content (Join-Path $stage 'MANIFEST.json') -Encoding utf8
    Get-ChildItem $stage -File -Recurse | ForEach-Object {
        '{0}  {1}' -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(),$_.FullName.Substring($stage.Length + 1).Replace('\','/')
    } | Set-Content (Join-Path $stage 'SHA256SUMS.txt') -Encoding ascii

    $zip = Join-Path $root 'Investor-Intelligence-v2.1.3-SourceDiverse-R60-Hotfix6-WranglerJSON.zip'
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
    $sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    $shaFile = $zip + '.sha256'
    Set-Content $shaFile $sha -Encoding ascii

    $check = Join-Path $root 'check'
    $stable = Join-Path $root 'stable'
    Expand-Archive $zip $check
    foreach ($file in @(
        'InvestorIntelligence.exe',
        'activate-v213-seven-field-schedule-core.ps1',
        'scripts\test_v213_activation_core.ps1',
        'sync-v213-activation-bundle.ps1',
        'scripts\build_v213_activation_bundle_v2.py',
        'cloud\src\v213\activation-v2.ts',
        'cloud\test\v213-activation.test.ts',
        'VERSION-REFS.json','MANIFEST.json','SHA256SUMS.txt'
    )) {
        if (-not (Test-Path (Join-Path $check $file) -PathType Leaf)) { throw "Package missing: $file" }
    }
    $core = Get-Content (Join-Path $check 'activate-v213-seven-field-schedule-core.ps1') -Raw -Encoding utf8
    foreach ($marker in @('node_modules\wrangler\bin\wrangler.js','V213_WRANGLER_INVOCATION = DIRECT_NODE','multiple deployment JSON documents','mixed_stdout_banner=true')) {
        if (-not $core.Contains($marker)) { throw "Packaged Wrangler hardening marker missing: $marker" }
    }
    foreach ($argument in @('--self-test','--pipe-hold-self-test','--model-selection-self-test')) {
        $process = Start-Process (Join-Path $check 'InvestorIntelligence.exe') -ArgumentList $argument -PassThru
        if (-not $process.WaitForExit(25000)) {
            Stop-Process $process.Id -Force -ErrorAction SilentlyContinue
            throw "Packaged EXE test timed out: $argument"
        }
        if ($process.ExitCode -ne 0) { throw "Packaged EXE test failed: $argument / $($process.ExitCode)" }
    }
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $check 'scripts\test_v213_activation_core.ps1') -ProjectRoot $check
    if ($LASTEXITCODE -ne 0) { throw 'Packaged activation-core regression failed.' }
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $check 'install-v213-source-diverse-runtime.ps1') -ProjectRoot $check -RuntimeRoot $stable
    if ($LASTEXITCODE -ne 0) { throw 'Stable runtime install failed.' }
    foreach ($file in @('run-v213-local.ps1','activate-v213-seven-field-schedule-core.ps1','sync-v213-activation-bundle.ps1','scripts\build_v213_activation_bundle_v2.py')) {
        if (-not (Test-Path (Join-Path $stable $file) -PathType Leaf)) { throw "Stable runtime missing: $file" }
    }
    $manifestDocument = Get-Content (Join-Path $check 'MANIFEST.json') -Raw -Encoding utf8 | ConvertFrom-Json
    foreach ($entry in @($manifestDocument.files)) {
        $path = Join-Path $check ([string]$entry.path).Replace('/','\')
        if (-not (Test-Path $path -PathType Leaf)) { throw "Manifest missing: $($entry.path)" }
        if ((Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$entry.sha256) { throw "Manifest hash mismatch: $($entry.path)" }
        if ((Get-Item $path).Length -ne [long]$entry.bytes) { throw "Manifest size mismatch: $($entry.path)" }
    }

    $verification = Join-Path $root 'Investor-Intelligence-v2.1.3-SourceDiverse-R60-Hotfix6-WranglerJSON-Verification.json'
    [ordered]@{
        schema_version = 1
        status = 'PASS'
        commit = $env:GITHUB_SHA.ToLowerInvariant()
        workflow_run_id = [string]$env:GITHUB_RUN_ID
        production_mutation = $false
        validation_receipt = $env:HF6_VALIDATION
        worker_transaction_tests = $true
        real_windows_no_mutation_refresh = $true
        wrangler_direct_node_test = $true
        wrangler_mixed_stdout_test = $true
        wrangler_ansi_banner_test = $true
        wrangler_ambiguous_json_rejection_test = $true
        packaged_launcher_tests = $true
        stable_runtime_test = $true
        manifest_verified = $true
        zip_sha256 = $sha
    } | ConvertTo-Json -Depth 8 | Set-Content $verification -Encoding utf8

    "HF6_ZIP=$zip" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
    "HF6_SHA_FILE=$shaFile" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
    "HF6_VERIFICATION=$verification" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
    "HF6_SHA=$sha" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
    Write-Host "V213_HOTFIX6_PACKAGE = PASS; sha256=$sha" -ForegroundColor Green
}
finally { Pop-Location }
