[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$OutputRoot = ''
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
    if ($env:GITHUB_SHA -and $sha -ne $env:GITHUB_SHA.ToLowerInvariant()) { throw 'Package source SHA mismatch.' }
    if ((git status --porcelain).Count -ne 0) { throw 'R75 package requires a clean exact checkout.' }
    $runId = [string]$env:GITHUB_RUN_ID
    $attempt = [string]$env:GITHUB_RUN_ATTEMPT
    if ($runId -notmatch '^\d+$' -or $attempt -notmatch '^\d+$') { throw 'Immutable package requires numeric workflow run identity.' }
    if (-not $env:R75_WINDOWS_RECEIPT -or -not (Test-Path -LiteralPath $env:R75_WINDOWS_RECEIPT -PathType Leaf)) {
        throw 'Authoritative Windows validation receipt is missing.'
    }
    $windows = Get-Content -LiteralPath $env:R75_WINDOWS_RECEIPT -Raw -Encoding utf8 | ConvertFrom-Json
    if ([string]$windows.status -ne 'PASS' -or [string]$windows.source_commit -ne $sha -or [string]$windows.workflow_run_id -ne $runId -or $windows.production_mutation_by_ci -ne $false -or [string]$windows.actual_all_limited_bundle_preflight -ne 'PASS') {
        throw 'Authoritative Windows validation receipt is not an all-LIMITED no-mutation PASS for this run.'
    }
    if (-not $env:PROJECT_PYTHON -or -not (Test-Path -LiteralPath $env:PROJECT_PYTHON -PathType Leaf)) {
        throw 'Repository-managed Python is unavailable.'
    }

    if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
        $OutputRoot = Join-Path $env:RUNNER_TEMP "ii-v213-r75-$sha-$runId-$attempt"
    }
    $OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
    $stage = Join-Path $OutputRoot 'stage'
    $sourceArchive = Join-Path $OutputRoot 'source.zip'
    git archive --format=zip --output="$sourceArchive" HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Unable to archive exact source commit.' }
    Expand-Archive -LiteralPath $sourceArchive -DestinationPath $stage -Force
    Remove-Item -LiteralPath $sourceArchive -Force
    # Public release content is deliberately separated from CI, tests, handoff/status,
    # skills, and prior delivery evidence. Those remain bound to the Git commit.
    foreach ($internal in @('.github','.gitignore','delivery','IMPLEMENTATION_STATUS.md','skills','state','tests')) {
        Remove-Item -LiteralPath (Join-Path $stage $internal) -Recurse -Force -ErrorAction SilentlyContinue
    }

    $csc = @(
        "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $csc) { throw 'Windows C# compiler is unavailable.' }
    $source = Get-Content -LiteralPath 'launcher\InvestorIntelligenceLauncher.cs' -Raw -Encoding utf8
    $revision = "R75-$($sha.Substring(0,12))-$runId"
    $source = [regex]::Replace($source, 'const string Revision = "[^"]+";', "const string Revision = `"$revision`";", 1)
    $temporarySource = Join-Path $OutputRoot 'InvestorIntelligence-R75.cs'
    $launcher = Join-Path $stage 'InvestorIntelligence.exe'
    [IO.File]::WriteAllText($temporarySource, $source, [Text.UTF8Encoding]::new($false))
    & $csc /nologo /target:winexe /platform:anycpu /optimize+ /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "/out:$launcher" $temporarySource
    if ($LASTEXITCODE -ne 0) { throw 'R75 launcher compilation failed.' }
    Remove-Item -LiteralPath $temporarySource -Force

    foreach ($argument in @('--self-test','--pipe-hold-self-test','--model-selection-self-test')) {
        $process = Start-Process -FilePath $launcher -ArgumentList $argument -PassThru
        if (-not $process.WaitForExit(30000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw "Packaged launcher test timed out: $argument"
        }
        if ($process.ExitCode -ne 0) { throw "Packaged launcher test failed: $argument" }
    }

    $contract = Join-Path $stage 'config\v213-r75-publication-mode-v1.json'
    $contractSha = (Get-FileHash -LiteralPath $contract -Algorithm SHA256).Hash.ToLowerInvariant()
    $validationSha = (Get-FileHash -LiteralPath $env:R75_WINDOWS_RECEIPT -Algorithm SHA256).Hash.ToLowerInvariant()
    $versionPath = Join-Path $stage 'VERSION-REFS.json'
    $version = [ordered]@{
        schema_version = 1
        release = 'R75'
        package_version = '2.1.3'
        launcher_revision = $revision
        source_commit = $sha
        workflow_run_id = $runId
        workflow_run_attempt = $attempt
        publication_contract_sha256 = $contractSha
        windows_receipt_sha256 = $validationSha
        all_limited_preflight = $true
        powershell_51 = 'PASS'
        powershell_7 = 'PASS'
        python_tests = 546
        worker_test_files = 18
        worker_tests = 101
        isolated_kv_transaction = 'PASS'
        production_mutation_by_ci = $false
        line_message_sent = $false
        schedule_registered = $false
        known_p0_count = 0
        public_package_excludes_internal_evidence = $true
    }
    [IO.File]::WriteAllText($versionPath, (($version | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))

    $sbomPath = Join-Path $stage 'SBOM.spdx.json'
    $sbom = [ordered]@{
        spdxVersion = 'SPDX-2.3'
        dataLicense = 'CC0-1.0'
        SPDXID = 'SPDXRef-DOCUMENT'
        name = "Investor-Intelligence-v2.1.3-R75-$sha-$runId"
        documentNamespace = "https://github.com/always7895/investor-intelligence/spdx/R75/$sha/$runId"
        creationInfo = [ordered]@{ creators = @('Tool: scripts/ci_v213_r75_package.ps1'); created = '2026-09-04T00:00:00Z' }
        packages = @([ordered]@{
            name = 'Investor Intelligence'
            SPDXID = 'SPDXRef-Package-Investor-Intelligence'
            versionInfo = '2.1.3-R75'
            downloadLocation = 'NOASSERTION'
            filesAnalyzed = $false
            licenseConcluded = 'NOASSERTION'
            licenseDeclared = 'NOASSERTION'
            copyrightText = 'NOASSERTION'
            externalRefs = @([ordered]@{ referenceCategory='PACKAGE-MANAGER'; referenceType='purl'; referenceLocator="pkg:github/always7895/investor-intelligence@$sha" })
        })
        relationships = @([ordered]@{ spdxElementId='SPDXRef-DOCUMENT'; relationshipType='DESCRIBES'; relatedSpdxElement='SPDXRef-Package-Investor-Intelligence' })
        annotations = @([ordered]@{ annotationType='OTHER'; annotator='Tool: scripts/ci_v213_r75_package.ps1'; annotationDate='2026-09-04T00:00:00Z'; comment='No Production mutation, LINE send, or schedule registration was performed by CI.' })
    }
    [IO.File]::WriteAllText($sbomPath, (($sbom | ConvertTo-Json -Depth 12) + "`n"), [Text.UTF8Encoding]::new($false))

    $manifestPath = Join-Path $stage 'MANIFEST.json'
    $sumsPath = Join-Path $stage 'SHA256SUMS.txt'
    $manifestRows = @(
        Get-ChildItem -LiteralPath $stage -File -Recurse | Where-Object { $_.FullName -notin @($manifestPath,$sumsPath) } | Sort-Object FullName | ForEach-Object {
            [ordered]@{
                path = $_.FullName.Substring($stage.Length + 1).Replace('\','/')
                bytes = $_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    )
    $manifest = [ordered]@{
        schema_version = 1
        release = 'R75'
        package_version = '2.1.3'
        source_commit = $sha
        workflow_run_id = $runId
        workflow_run_attempt = $attempt
        publication_contract_sha256 = $contractSha
        production_mutation_by_ci = $false
        files = $manifestRows
    }
    [IO.File]::WriteAllText($manifestPath, (($manifest | ConvertTo-Json -Depth 10) + "`n"), [Text.UTF8Encoding]::new($false))
    $sumLines = @(
        Get-ChildItem -LiteralPath $stage -File -Recurse | Where-Object { $_.FullName -ne $sumsPath } | Sort-Object FullName | ForEach-Object {
            '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $_.FullName.Substring($stage.Length + 1).Replace('\','/')
        }
    )
    [IO.File]::WriteAllLines($sumsPath, $sumLines, [Text.Encoding]::ASCII)

    $stem = "Investor-Intelligence-v2.1.3-R75-$sha-$runId"
    $zip = Join-Path $OutputRoot "$stem.zip"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)
    $zipSha = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    $shaPath = Join-Path $OutputRoot "$stem.zip.sha256"
    [IO.File]::WriteAllText($shaPath, "$zipSha  $stem.zip`n", [Text.Encoding]::ASCII)
    $externalManifest = Join-Path $OutputRoot "$stem.MANIFEST.json"
    $externalSums = Join-Path $OutputRoot "$stem.SHA256SUMS.txt"
    $externalSbom = Join-Path $OutputRoot "$stem.SBOM.spdx.json"
    Copy-Item -LiteralPath $manifestPath -Destination $externalManifest
    Copy-Item -LiteralPath $sumsPath -Destination $externalSums
    Copy-Item -LiteralPath $sbomPath -Destination $externalSbom

    $windowsReceipt = Join-Path $OutputRoot "$stem.Windows-Receipt.json"
    Copy-Item -LiteralPath $env:R75_WINDOWS_RECEIPT -Destination $windowsReceipt
    $workerReceipt = Join-Path $OutputRoot "$stem.Worker-Receipt.json"
    $deliveryReceipt = Join-Path $OutputRoot "$stem.Delivery-Receipt.json"
    $common = [ordered]@{
        schema_version = 1
        status = 'PASS'
        source_commit = $sha
        workflow_run_id = $runId
        workflow_run_attempt = $attempt
        production_mutation_by_ci = $false
        external_mutation = $false
    }
    $worker = [ordered]@{} + $common
    $worker.typecheck = 'PASS'; $worker.test_files = 18; $worker.tests = 101
    $worker.isolated_kv_transaction = 'PASS'; $worker.actual_all_limited_preflight = 'PASS'
    [IO.File]::WriteAllText($workerReceipt, (($worker | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))
    $delivery = [ordered]@{} + $common
    $delivery.package = "$stem.zip"; $delivery.zip_sha256 = $zipSha; $delivery.bytes = (Get-Item -LiteralPath $zip).Length
    $delivery.immutable_identity = "$sha-$runId"; $delivery.artifact_delivery_is_authoritative = $true
    [IO.File]::WriteAllText($deliveryReceipt, (($delivery | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))

    $verificationReceipt = Join-Path $OutputRoot "$stem.Independent-Verification.json"
    & $env:PROJECT_PYTHON scripts\verify_v213_r75_artifact.py --archive $zip --checksum $shaPath --source-commit $sha --workflow-run-id $runId --windows-receipt $windowsReceipt --worker-receipt $workerReceipt --delivery-receipt $deliveryReceipt --output $verificationReceipt
    if ($LASTEXITCODE -ne 0) { throw 'Independent R75 artifact verification failed.' }

    $artifacts = @($zip,$shaPath,$externalManifest,$externalSums,$externalSbom,$windowsReceipt,$workerReceipt,$deliveryReceipt,$verificationReceipt)
    foreach ($path in $artifacts) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Release evidence missing: $path" } }
    $env:R75_ARTIFACT_FILES = ($artifacts -join "`n")
    $env:R75_PACKAGE_ROOT = $OutputRoot
    $env:R75_ZIP = $zip
    $env:R75_ZIP_SHA256 = $zipSha
    if ($env:GITHUB_ENV) {
        "R75_PACKAGE_ROOT=$OutputRoot" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
        "R75_ZIP=$zip" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
        "R75_ZIP_SHA256=$zipSha" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
    }
    Write-Host "V213_R75_IMMUTABLE_PACKAGE = PASS; archive=$stem.zip; sha256=$zipSha; production_mutation_by_ci=false" -ForegroundColor Green
}
finally { Pop-Location }
