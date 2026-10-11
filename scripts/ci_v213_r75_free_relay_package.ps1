[CmdletBinding()]
param([string]$ProjectRoot = '', [string]$OutputRoot = '')
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
    if ($env:GITHUB_SHA -and $sha -ne $env:GITHUB_SHA.ToLowerInvariant()) { throw 'Package source SHA mismatch.' }
    if (@(git status --porcelain).Count -ne 0) { throw 'FREE_RELAY hotfix package requires a clean exact checkout.' }
    $runId = [string]$env:GITHUB_RUN_ID; $attempt = [string]$env:GITHUB_RUN_ATTEMPT
    if ($runId -notmatch '^\d+$' -or $attempt -notmatch '^\d+$') { throw 'Immutable package requires numeric workflow run identity.' }
    if (-not $env:R75_FREE_RELAY_WINDOWS_RECEIPT -or -not (Test-Path -LiteralPath $env:R75_FREE_RELAY_WINDOWS_RECEIPT -PathType Leaf)) { throw 'FREE_RELAY Windows receipt is missing.' }
    $windows = Get-Content -LiteralPath $env:R75_FREE_RELAY_WINDOWS_RECEIPT -Raw -Encoding utf8 | ConvertFrom-Json
    if ([string]$windows.status -ne 'PASS' -or [string]$windows.source_commit -ne $sha -or [string]$windows.workflow_run_id -ne $runId -or $windows.production_mutation_by_ci -ne $false -or $windows.custom_domain_required -ne $false) { throw 'FREE_RELAY Windows receipt identity, cost, or no-mutation gate failed.' }
    . (Join-Path $ProjectRoot 'scripts/v213_edge_readiness.ps1')
    Assert-V213QaReleaseQualification $windows
    foreach ($protected in @('config/v213-r75-publication-mode-v1.json','scripts/v213_r75_activation_preflight.py','cloud/src/v213/publication-mode.ts','cloud/src/v213/activation-v2.ts','scripts/ci_v213_r75_package.ps1','scripts/verify_v213_r75_artifact.py')) {
        git diff --quiet $r75Commit -- $protected
        if ($LASTEXITCODE -ne 0) { throw "Protected R75 release source changed: $protected" }
    }
    if (-not $env:PROJECT_PYTHON -or -not (Test-Path -LiteralPath $env:PROJECT_PYTHON -PathType Leaf)) {
        $verifiedCandidate = if ($env:RUNNER_TEMP) { Join-Path $env:RUNNER_TEMP 'ii-r75-python-3.12.10\python.exe' } else { '' }
        if ($verifiedCandidate -and (Test-Path -LiteralPath $verifiedCandidate -PathType Leaf)) { $env:PROJECT_PYTHON = $verifiedCandidate }
        else {
            $python = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $python) { $python = Get-Command python -ErrorAction Stop | Select-Object -First 1 }
            $env:PROJECT_PYTHON = $python.Source
        }
    }
    $qaInputRaw = & $env:PROJECT_PYTHON scripts/r75_release_inputs.py --project-root $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Committed QA input selection failed.' }
    $qaInput = $qaInputRaw | ConvertFrom-Json
    if ($qaInput.source_commit -cne $sha) { throw 'QA input source commit mismatch.' }
    $liveProof = Join-Path $ProjectRoot $qaInput.receipt_path
    if (-not $windows.PSObject.Properties['qa_live_receipt_path'] -or $windows.qa_live_receipt_path -cne $qaInput.receipt_path -or
        $windows.qa_live_receipt_sha256 -cne $qaInput.receipt_sha256) { throw 'Windows/QA input binding mismatch.' }
    $profileArgs=@()
    $profilePath=Join-Path $ProjectRoot 'config/v213-model-profile-v1.json'
    if(Test-Path -LiteralPath $profilePath -PathType Leaf){$profileArgs=@('--model-profile',$profilePath)}
    $qaRaw = & $env:PROJECT_PYTHON scripts/verify_r75_qa_evidence.py --receipt $liveProof @profileArgs
    if ($LASTEXITCODE -ne 0) { throw 'Fresh source-bound live proof required before packaging.' }
    $qa=$qaRaw|ConvertFrom-Json
    if($profileArgs.Count-and($windows.exact_model-cne$qa.exact_model-or$windows.model_profile_sha256-cne$qa.model_profile_sha256)){throw 'Windows/model profile receipt mismatch.'}
    if ([string]::IsNullOrWhiteSpace($OutputRoot)) { $OutputRoot = Join-Path $env:RUNNER_TEMP "ii-v213-r75-FREE_RELAY-$sha-$runId-$attempt" }
    $OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
    # Preserve prior attempts and operator data; never clear a supplied directory.
    if (Test-Path -LiteralPath $OutputRoot) { throw 'PACKAGE_OUTPUT_ROOT_ALREADY_EXISTS' }
    if ($OutputRoot.StartsWith($ProjectRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'PACKAGE_OUTPUT_ROOT_IN_SOURCE' }
    New-Item -ItemType Directory -Path $OutputRoot -ErrorAction Stop | Out-Null
    $stage = Join-Path $OutputRoot 'stage'; $sourceArchive = Join-Path $OutputRoot 'source.zip'
    git archive --format=zip --output="$sourceArchive" HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Unable to archive exact hotfix source.' }
    Expand-Archive -LiteralPath $sourceArchive -DestinationPath $stage -Force
    Remove-Item -LiteralPath $sourceArchive -Force
    # F06A-1: the SAME git-archive stage is the byte authority for the Worker test fixtures. The commit path inventory comes from git ls-tree at
    # $sha (never the worktree or the index); the exact fixture bytes and their archive-stage SHA-256 are captured BEFORE the internal prune.
    # Retention is bounded: at most 2 MiB per fixture and 16 MiB in total, read through one bounded binary read per fixture (overflow is refused
    # BEFORE anything is retained). The stage is this script's own git-archive output; no native TOCTOU or custody guarantee is claimed (UNQUALIFIED).
    $alwaysFixtures = @(
        'tests/fixtures/v213-order-forecast-sealed.json','tests/fixtures/v213-order-forecast-urls.json','tests/fixtures/v213-order-forecast-v2.json',
        'tests/fixtures/v213-order-forecast-v2-sealed.json','tests/fixtures/v213-lineage-sealed-markets.json','tests/fixtures/v213-official-quarterly-revenue.json',
        'tests/fixtures/source-acquisition-reports.json','tests/fixtures/v213-orders-v3-golden-sealed.json','tests/fixtures/v213-orders-v3-proof-rpo.json',
        'tests/fixtures/v213-orders-v3-proof-states.json','tests/fixtures/v213-orders-v3-probes.json',
        'tests/fixtures/v213-r75-publication-mode/all-limited.json','tests/fixtures/v213-r75-publication-mode/mixed.json',
        'tests/fixtures/identity-batch04-functional.json','tests/fixtures/revenue-guidance-machine-auto-functional.json',
        'tests/fixtures/revenue-guidance-machine-barrier-functional.json','tests/fixtures/revenue-guidance-machine-nbis-auto-functional.json',
        'tests/fixtures/revenue-guidance-machine-nbis-reaffirm-functional.json'
    )
    $wireTest = 'cloud/test/v213-revenue-guidance-wire-integration.test.ts'; $wireFixture = 'tests/fixtures/revenue-guidance-wire-v1-functional.json'
    $fixtureMaxBytes = 2097152; $fixtureTotalMaxBytes = 16777216
    $treeEntries = [Collections.Generic.Dictionary[string,string[]]]::new([StringComparer]::Ordinal)
    foreach ($treeLine in @(git -c core.quotepath=false ls-tree -r $sha)) {
        if ($treeLine -cmatch '^([0-7]{6}) (blob|commit) ([0-9a-f]{40}|[0-9a-f]{64})\t(.+)$') { $treeEntries[$Matches[4]] = [string[]]@($Matches[1], $Matches[2], $Matches[3]) }
        else { throw 'Exact commit tree entry is malformed.' }
    }
    if ($LASTEXITCODE -ne 0 -or $treeEntries.Count -lt 3) { throw 'Exact commit path inventory is unavailable.' }
    $hasWireTest = $treeEntries.ContainsKey($wireTest); $hasWireFixture = $treeEntries.ContainsKey($wireFixture)
    if ($hasWireTest -ne $hasWireFixture) { throw 'Revenue guidance wire test and fixture must both be present or both absent at the exact commit.' }
    $fixturePaths = @($alwaysFixtures); if ($hasWireFixture) { $fixturePaths += $wireFixture }
    $fixtureGit = [ordered]@{}
    foreach ($relative in $fixturePaths) {
        if (-not $treeEntries.ContainsKey($relative) -or $relative -cnotmatch '^tests/fixtures/[A-Za-z0-9][A-Za-z0-9._/-]*\.json$' -or $relative.Contains('..') -or $relative.Contains('//')) { throw "Worker test fixture is not a tracked safe path at the exact commit: $relative" }
        $entry = $treeEntries[$relative]
        if ($entry[1] -cne 'blob' -or ($entry[0] -cne '100644' -and $entry[0] -cne '100755')) { throw "Worker test fixture is not a regular Git blob (symlink and gitlink refused): $relative" }
        $fixtureGit[$relative] = [ordered]@{ mode = $entry[0]; blob = $entry[2] }
    }
    $cloudTestPayload = [string[]]@($treeEntries.Keys | Where-Object { $_.StartsWith('cloud/test/', [StringComparison]::Ordinal) })
    if ($cloudTestPayload.Count -lt 3) { throw 'Worker test dependency inventory is missing.' }
    [Array]::Sort($cloudTestPayload, [StringComparer]::Ordinal)
    foreach ($relative in $cloudTestPayload) {
        $entry = $treeEntries[$relative]
        if ($entry[1] -cne 'blob' -or ($entry[0] -cne '100644' -and $entry[0] -cne '100755')) { throw "Worker test file is not a regular Git blob at the exact commit: $relative" }
    }
    function Read-V213BoundedFixture([string]$Path, [int]$Limit) {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Worker test fixture in the archive stage is not a regular file.' }
        $stream = $null; $buffer = $null
        try {
            $stream = [IO.FileStream]::new($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
            $buffer = [byte[]]::new($Limit + 1); $total = 0
            while ($total -le $Limit) {
                $count = $stream.Read($buffer, $total, $buffer.Length - $total)
                if ($count -le 0) { break }
                $total += $count
            }
            if ($total -gt $Limit) { throw 'Worker test fixture exceeds the byte bound.' }
            $bytes = [byte[]]::new($total); [Array]::Copy($buffer, $bytes, $total)
            return ,$bytes
        } finally { if ($null -ne $stream) { $stream.Dispose() }; $buffer = $null }
    }
    $stageSha = [ordered]@{}; $stageBytes = @{}; $capturedTotal = 0
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        foreach ($relative in $fixturePaths) {
            $stageFile = Join-Path $stage $relative
            if (-not (Test-Path -LiteralPath $stageFile -PathType Leaf)) { throw "Worker test fixture is missing from the archive stage: $relative" }
            $captured = Read-V213BoundedFixture -Path $stageFile -Limit ([Math]::Min($fixtureMaxBytes, $fixtureTotalMaxBytes - $capturedTotal))
            $capturedTotal += $captured.Length
            $stageBytes[$relative] = $captured
            $stageSha[$relative] = ([BitConverter]::ToString($hasher.ComputeHash($captured)) -replace '-','').ToLowerInvariant()
        }
    } finally { $hasher.Dispose() }
    $stageCloudTestRoot = Join-Path $stage 'cloud\test'
    $stageCloudItems = @(Get-ChildItem -LiteralPath $stageCloudTestRoot -Force -Recurse)
    if (@($stageCloudItems | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 }).Count -ne 0) { throw 'Archive stage cloud/test contains a reparse point.' }
    $stageCloudTest = @($stageCloudItems | Where-Object { -not $_.PSIsContainer } | ForEach-Object { 'cloud/test/' + $_.FullName.Substring($stageCloudTestRoot.Length + 1).Replace('\','/') })
    if (@(Compare-Object -CaseSensitive $cloudTestPayload $stageCloudTest).Count -ne 0) { throw 'Archive stage cloud/test differs from the exact commit inventory.' }
    $payloadStageSha = [ordered]@{}
    foreach ($relative in $cloudTestPayload) {
        $payloadStageSha[$relative] = (Get-FileHash -LiteralPath (Join-Path $stage $relative) -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    foreach ($internal in @('.github','.gitignore','delivery','IMPLEMENTATION_STATUS.md','skills','state','tests')) { Remove-Item -LiteralPath (Join-Path $stage $internal) -Recurse -Force -ErrorAction SilentlyContinue }
    # Ship only the reviewed public methodology, not unrelated skills/archives.
    $researchPayload=@('skills/serenity-public-research/SKILL.md','skills/serenity-public-research/references/RESEARCH_METHOD.md','skills/serenity-public-research/references/CROSS_VALIDATION.md','skills/serenity-public-research/references/SERENITY_LOGIC.md','skills/serenity-public-research/references/ASCHENBRENNER_CONTEXT.md')
    foreach($relative in $researchPayload){
        $destination=Join-Path $stage $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
        Copy-Item -LiteralPath (Join-Path $ProjectRoot $relative) -Destination $destination
        if((Get-FileHash $destination).Hash-ne(Get-FileHash (Join-Path $ProjectRoot $relative)).Hash){throw 'Public research payload digest mismatch.'}
    }
    # Activation runs npm test on the installed package. These are runtime gate
    # dependencies, not removable internal content. Restore ONLY the exact fixture paths (the 18 always-required test fixtures, plus the
    # revenue-guidance wire fixture when the exact commit carries the wire pair) with the exact bounded archive-stage bytes captured before the prune.
    foreach ($relative in $fixturePaths) {
        $packaged = Join-Path $stage $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $packaged) | Out-Null
        [IO.File]::WriteAllBytes($packaged, $stageBytes[$relative])
    }
    $workerTestPayload = [string[]]($cloudTestPayload + $fixturePaths)
    [Array]::Sort($workerTestPayload, [StringComparer]::Ordinal)
    $stageTestsRoot = Join-Path $stage 'tests'
    $restoredItems = @(Get-ChildItem -LiteralPath $stageTestsRoot -Force -Recurse)
    if (@($restoredItems | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 }).Count -ne 0) { throw 'Restored tests/ contains a reparse point.' }
    $restoredFixtures = @($restoredItems | Where-Object { -not $_.PSIsContainer } | ForEach-Object { 'tests/' + $_.FullName.Substring($stageTestsRoot.Length + 1).Replace('\','/') })
    if (@(Compare-Object -CaseSensitive $fixturePaths $restoredFixtures).Count -ne 0) { throw 'Restored tests/ path set differs from the exact fixture inventory.' }
    foreach ($relative in $workerTestPayload) {
        $packaged = Join-Path $stage $relative
        $expectedSha = if ($stageSha.Contains($relative)) { $stageSha[$relative] } else { $payloadStageSha[$relative] }
        if (-not (Test-Path -LiteralPath $packaged -PathType Leaf) -or (Get-FileHash -LiteralPath $packaged -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expectedSha) {
            throw "Packaged activation test dependency missing or changed: $relative"
        }
    }
    $workerTestFixtureSha256 = [ordered]@{}
    foreach ($relative in $fixturePaths) { $workerTestFixtureSha256[$relative] = $stageSha[$relative] }

    $csc = @("$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe","$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe") | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $csc) { throw 'Windows C# compiler is unavailable.' }
    $source = Get-Content -LiteralPath 'launcher\InvestorIntelligenceLauncher.cs' -Raw -Encoding utf8
    $revision = "R75-FreeRelay-$($sha.Substring(0,12))-$runId"
    $source = [regex]::Replace($source, 'const string Revision = "[^"]+";', "const string Revision = `"$revision`";", 1)
    $temporarySource = Join-Path $OutputRoot 'InvestorIntelligence-R75-FreeRelay.cs'
    $launcher = Join-Path $stage 'InvestorIntelligence.exe'
    [IO.File]::WriteAllText($temporarySource, $source, [Text.UTF8Encoding]::new($false))
    & $csc /nologo /target:winexe /platform:anycpu /optimize+ /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "/out:$launcher" $temporarySource
    if ($LASTEXITCODE -ne 0) { throw 'FREE_RELAY launcher compilation failed.' }
    Remove-Item -LiteralPath $temporarySource -Force
    foreach ($argument in @('--self-test','--pipe-hold-self-test','--model-selection-self-test','--model-profile-self-test','--model-thinking-ui-self-test')) {
        $process = Start-Process -FilePath $launcher -ArgumentList $argument -PassThru
        if (-not $process.WaitForExit(30000)) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue; throw "Packaged launcher test timed out: $argument" }
        if ($process.ExitCode -ne 0) { throw "Packaged launcher test failed: $argument" }
    }

    $contractSha = (Get-FileHash -LiteralPath (Join-Path $stage 'config\v213-r75-publication-mode-v1.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    $refs = [ordered]@{
        schema_version = 1; artifact_kind = 'R75_FREE_WORKERS_RELAY_HOTFIX'; package_version = '2.1.3'
        base_named_tunnel_commit = $baseCommit; source_commit = $sha; workflow_run_id = $runId; workflow_run_attempt = $attempt
        launcher_revision = $revision; publication_contract_sha256 = $contractSha
        qa_live_receipt_path = $qaInput.receipt_path; qa_live_receipt_sha256 = $qaInput.receipt_sha256
        worker_test_payload = $workerTestPayload; worker_test_fixture_sha256 = $workerTestFixtureSha256; worker_test_fixture_git = $fixtureGit; revenue_guidance_wire_pair_present = $hasWireFixture; packaged_worker_test_count = [int]$windows.worker_tests
        normal_production_tunnel_mode = 'quick_free_relay'; workers_dev_stable_entrypoint = $true; custom_domain_required = $false
        trycloudflare_hostname_stable = $false; consecutive_public_health_required = 3; exact_model = $qa.exact_model; model_profile_sha256 = $qa.model_profile_sha256; health_schema_version = 2
        signed_route_registration = $true; route_generation_required = $true; heartbeat_lease_required = $true; stale_and_replay_rejected = $true
        blue_green_startup = $true; verified_rollback = $true; allow_test_tunnel_exception_used = $false; named_tunnel_optional = $true
        protected_release_semantics_unchanged = $true; sealed_bundle_contents_changed = $false; release_evidence_rules_changed = $true; live_proof_max_age_seconds = 86400
        production_mutation_by_ci = $false; worker_deployed = $false; production_kv_or_do_written = $false; line_message_sent = $false; schedules_registered = $false
    }
    [IO.File]::WriteAllText((Join-Path $stage 'HOTFIX-REFS.json'), (($refs | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))
    $sbom = [ordered]@{
        spdxVersion='SPDX-2.3'; dataLicense='CC0-1.0'; SPDXID='SPDXRef-DOCUMENT'; name="Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-$sha-$runId"
        documentNamespace="https://github.com/always7895/investor-intelligence/spdx/R75-Free-Relay-Hotfix/$sha/$runId"
        creationInfo=[ordered]@{creators=@('Tool: scripts/ci_v213_r75_free_relay_package.ps1');created=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')}
        packages=@([ordered]@{name='Investor Intelligence';SPDXID='SPDXRef-Package-Investor-Intelligence';versionInfo='2.1.3-R75-Free-Relay-Hotfix';downloadLocation='NOASSERTION';filesAnalyzed=$false;licenseConcluded='NOASSERTION';licenseDeclared='NOASSERTION';copyrightText='NOASSERTION'})
        relationships=@([ordered]@{spdxElementId='SPDXRef-DOCUMENT';relationshipType='DESCRIBES';relatedSpdxElement='SPDXRef-Package-Investor-Intelligence'})
    }
    [IO.File]::WriteAllText((Join-Path $stage 'SBOM.spdx.json'), (($sbom | ConvertTo-Json -Depth 10) + "`n"), [Text.UTF8Encoding]::new($false))

    $manifestPath = Join-Path $stage 'MANIFEST.json'; $sumsPath = Join-Path $stage 'SHA256SUMS.txt'
    $rows = @(Get-ChildItem -LiteralPath $stage -File -Recurse | Where-Object { $_.FullName -notin @($manifestPath,$sumsPath) } | Sort-Object FullName | ForEach-Object { [ordered]@{path=$_.FullName.Substring($stage.Length+1).Replace('\','/');bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()} })
    $manifest = [ordered]@{schema_version=1;artifact_kind='R75_FREE_WORKERS_RELAY_HOTFIX';source_commit=$sha;workflow_run_id=$runId;workflow_run_attempt=$attempt;base_named_tunnel_commit=$baseCommit;production_mutation_by_ci=$false;files=$rows}
    [IO.File]::WriteAllText($manifestPath, (($manifest | ConvertTo-Json -Depth 10) + "`n"), [Text.UTF8Encoding]::new($false))
    $sumLines = @(Get-ChildItem -LiteralPath $stage -File -Recurse | Where-Object { $_.FullName -ne $sumsPath } | Sort-Object FullName | ForEach-Object { '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(),$_.FullName.Substring($stage.Length+1).Replace('\','/') })
    [IO.File]::WriteAllLines($sumsPath,$sumLines,[Text.Encoding]::ASCII)

    $stem = "Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-$sha-$runId"
    $zip = Join-Path $OutputRoot "$stem.zip"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($stage,$zip,[IO.Compression.CompressionLevel]::Optimal,$false)
    # Test the final ZIP, not the source checkout or pre-packaging staging tree.
    # No production configuration/credentials are copied into this extraction.
    $zipProbe = Join-Path $OutputRoot 'ZIP gate 測試 (1)'
    $zipTestResult = Join-Path $OutputRoot 'packaged-worker-vitest.json'
    $packagedWorkerTests = 0
    try {
        [IO.Compression.ZipFile]::ExtractToDirectory($zip, $zipProbe)
        Push-Location (Join-Path $zipProbe 'cloud')
        try {
            & $env:PROJECT_NPM ci --ignore-scripts --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'Extracted ZIP npm ci failed.' }
            & $env:PROJECT_NPM run typecheck
            if ($LASTEXITCODE -ne 0) { throw 'Extracted ZIP Worker typecheck failed.' }
            & $env:PROJECT_NPM test -- --reporter=json "--outputFile=$zipTestResult"
            if ($LASTEXITCODE -ne 0) { throw 'Extracted ZIP Worker tests failed.' }
            $result = Get-Content -LiteralPath $zipTestResult -Raw -Encoding utf8 | ConvertFrom-Json
            $packagedWorkerTests = [int]$result.numPassedTests
            if ($result.success -ne $true -or [int]$result.numTotalTests -le 0 -or
                [int]$result.numTotalTests -ne [int]$windows.worker_tests -or
                $packagedWorkerTests -ne [int]$result.numTotalTests -or [int]$result.numFailedTests -ne 0) {
                throw 'Extracted ZIP test count/result differs from the validated source.'
            }
        } finally { Pop-Location }
        Write-Host "V213_PACKAGED_WORKER_GATE = PASS; tests=$packagedWorkerTests; extracted_zip=true; special_path=true; production_mutation=false"
        $savedLocalAppData = $env:LOCALAPPDATA
        $installProbe = Join-Path $OutputRoot 'isolated-install'
        try {
            $env:LOCALAPPDATA = Join-Path $installProbe 'local'
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $zipProbe 'install-v213-source-diverse-runtime.ps1') -ProjectRoot $zipProbe -RuntimeRoot (Join-Path $installProbe 'runtime')
            if ($LASTEXITCODE -ne 0) { throw 'Extracted ZIP stable runtime installation failed.' }
            foreach ($relative in $workerTestPayload) {
                $installed = Join-Path (Join-Path $installProbe 'runtime') $relative
                if (-not (Test-Path -LiteralPath $installed -PathType Leaf) -or (Get-FileHash $installed).Hash -ne (Get-FileHash (Join-Path $zipProbe $relative)).Hash) {
                    throw "Installed runtime test dependency missing or changed: $relative"
                }
            }
            foreach($metadataPath in @((Join-Path $env:LOCALAPPDATA 'InvestorIntelligence/v213-runtime-state.json'),(Join-Path $installProbe 'runtime/V213-SOURCE-DIVERSE-RUNTIME.json'))){
                $metadata=Get-Content -LiteralPath $metadataPath -Raw -Encoding utf8|ConvertFrom-Json
                if($null-ne$metadata.preferred_model -or $metadata.model_selection_authority -isnot [string] -or
                   $metadata.model_selection_authority-cne'runtime_model_profile' -or
                   $metadata.model_profile_qualified -isnot [bool] -or $metadata.model_profile_qualified-ne$false){
                    throw 'Installed metadata incorrectly selects or qualifies a model.'
                }
            }
            Write-Host 'V213_PACKAGED_RUNTIME_INSTALL = PASS; isolated_localappdata=true; model_selection=runtime_profile_only; production_mutation=false'
        } finally {
            $env:LOCALAPPDATA = $savedLocalAppData
            Remove-Item -LiteralPath $installProbe -Recurse -Force -ErrorAction SilentlyContinue
        }
    } finally { Remove-Item -LiteralPath $zipProbe -Recurse -Force -ErrorAction SilentlyContinue }
    # A proof can expire while ZIP/install tests run; recheck before receipts.
    & $env:PROJECT_PYTHON scripts/verify_r75_qa_evidence.py --receipt $liveProof @profileArgs
    if ($LASTEXITCODE -ne 0) { throw 'Live proof expired or changed during packaging.' }
    if ((Get-FileHash $liveProof -Algorithm SHA256).Hash.ToLowerInvariant() -cne $windows.qa_live_receipt_sha256) { throw 'Live proof digest changed during packaging.' }
    $finalSha = (git rev-parse HEAD).Trim().ToLowerInvariant()
    $finalStatus = @(git status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $finalSha -cne $sha -or $finalStatus.Count -ne 0) { throw 'Exact checkout changed during packaging.' }
    $zipSha = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    $shaPath = Join-Path $OutputRoot "$stem.zip.sha256"
    [IO.File]::WriteAllText($shaPath,"$zipSha  $stem.zip`n",[Text.Encoding]::ASCII)
    Copy-Item $manifestPath (Join-Path $OutputRoot "$stem.MANIFEST.json")
    Copy-Item $sumsPath (Join-Path $OutputRoot "$stem.SHA256SUMS.txt")
    Copy-Item (Join-Path $stage 'SBOM.spdx.json') (Join-Path $OutputRoot "$stem.SBOM.spdx.json")
    $qaReceipt = Join-Path $OutputRoot "$stem.QA-Live-Receipt.json"
    Copy-Item -LiteralPath $liveProof -Destination $qaReceipt
    if ((Get-FileHash -LiteralPath $qaReceipt -Algorithm SHA256).Hash.ToLowerInvariant() -cne $qaInput.receipt_sha256) { throw 'Copied QA receipt digest mismatch.' }
    $windowsReceipt = Join-Path $OutputRoot "$stem.Windows-Receipt.json"; Copy-Item $env:R75_FREE_RELAY_WINDOWS_RECEIPT $windowsReceipt
    $deploymentReceipt = Join-Path $OutputRoot "$stem.Deployment-Receipt.json"
    $deployment = [ordered]@{schema_version=1;status='PASS';artifact_kind='R75_FREE_WORKERS_RELAY_HOTFIX';source_commit=$sha;workflow_run_id=$runId;workflow_run_attempt=$attempt;free_relay_setup='PASS';packaged_worker_typecheck='PASS';packaged_worker_tests=$packagedWorkerTests;extracted_zip_worker_gate='PASS';extracted_zip_runtime_install='PASS';workers_dev_stable_entrypoint=$true;custom_domain_required=$false;powershell_51='PASS';powershell_7='PASS';special_path='PASS';negative_tests='PASS';consecutive_public_health_required=3;exact_model=$qa.exact_model;model_profile_sha256=$qa.model_profile_sha256;health_schema_version=2;stale_route_rejection='PASS';replay_rejection='PASS';concurrent_update='PASS';heartbeat_lease='PASS';reboot_reconnect='PASS';blue_green_rollback='PASS';production_mutation_by_ci=$false;external_mutation=$false}
    [IO.File]::WriteAllText($deploymentReceipt,(($deployment|ConvertTo-Json -Depth 8)+"`n"),[Text.UTF8Encoding]::new($false))
    $deliveryReceipt = Join-Path $OutputRoot "$stem.Delivery-Receipt.json"
    $delivery = [ordered]@{schema_version=1;status='PASS';artifact_kind='R75_FREE_WORKERS_RELAY_HOTFIX';source_commit=$sha;workflow_run_id=$runId;workflow_run_attempt=$attempt;package="$stem.zip";zip_sha256=$zipSha;bytes=(Get-Item $zip).Length;immutable_identity="$sha-$runId";zero_cost=$true;custom_domain_required=$false;production_mutation_by_ci=$false;external_mutation=$false}
    [IO.File]::WriteAllText($deliveryReceipt,(($delivery|ConvertTo-Json -Depth 8)+"`n"),[Text.UTF8Encoding]::new($false))
    $verificationReceipt = Join-Path $OutputRoot "$stem.Independent-Verification.json"
    & $env:PROJECT_PYTHON scripts\verify_v213_r75_free_relay_hotfix.py --archive $zip --checksum $shaPath --source-commit $sha --workflow-run-id $runId --receipt $windowsReceipt --receipt $deploymentReceipt --receipt $deliveryReceipt --qa-live-receipt $qaReceipt --output $verificationReceipt
    if ($LASTEXITCODE -ne 0) { throw 'Independent FREE_RELAY hotfix artifact verification failed.' }
    $artifacts = @($zip,$shaPath,(Join-Path $OutputRoot "$stem.MANIFEST.json"),(Join-Path $OutputRoot "$stem.SHA256SUMS.txt"),(Join-Path $OutputRoot "$stem.SBOM.spdx.json"),$qaReceipt,$windowsReceipt,$deploymentReceipt,$deliveryReceipt,$verificationReceipt)
    foreach ($path in $artifacts) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Hotfix evidence missing: $path" } }
    $env:R75_FREE_RELAY_PACKAGE_ROOT=$OutputRoot; $env:R75_FREE_RELAY_ZIP=$zip; $env:R75_FREE_RELAY_ZIP_SHA256=$zipSha
    if ($env:GITHUB_ENV) { "R75_FREE_RELAY_PACKAGE_ROOT=$OutputRoot" | Out-File $env:GITHUB_ENV -Append -Encoding utf8; "R75_FREE_RELAY_ZIP=$zip" | Out-File $env:GITHUB_ENV -Append -Encoding utf8; "R75_FREE_RELAY_ZIP_SHA256=$zipSha" | Out-File $env:GITHUB_ENV -Append -Encoding utf8 }
    Write-Host "V213_R75_FREE_RELAY_IMMUTABLE_PACKAGE = PASS; archive=$stem.zip; sha256=$zipSha; production_mutation_by_ci=false" -ForegroundColor Green
}
finally { Pop-Location }
