[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [Parameter(Mandatory = $true)][string]$RuntimeRoot,
    [ValidateSet('BASE','SOURCE_DIVERSE','SOURCE_DIVERSE_V2','SERENITY_LATEST')][string]$Profile,
    # R75_PACKAGE: a CI package (HOTFIX-REFS.json / VERSION-REFS.json with a workflow run id).
    # LOCAL_SOURCE_CHECKOUT: an export of one commit of -SourceRepository (scripts/export_local_source_checkout.ps1,
    # LOCAL-SOURCE-REFS.json); every exported file must equal that commit's git blob. Never release-qualified.
    [ValidateSet('R75_PACKAGE','LOCAL_SOURCE_CHECKOUT')][string]$PackageOrigin = 'R75_PACKAGE',
    [string]$SourceRepository = '',
    # Undo the most recent finalized install: swap <runtime>.old.<transaction> back and restore state and receipt.
    [string]$RestorePrevious = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

# Path segments outside manifest/ownership coverage. data/ is mutable
# runtime state (refresh caches, activation bundles, publication journals),
# reports/ is regenerated public output, .wrangler/ is a wrangler auth cache,
# and __pycache__ is a Python execution byproduct. All can change after
# install without changing the runtime payload, so ownership attests the
# immutable payload only.
$script:V213ManifestExcluded = @('.git', 'versions', 'node_modules', '.venv-v213-local', '.npm-cache', 'data', '__pycache__', 'reports', '.wrangler')

function Test-V213PathExcluded([string]$Relative) {
    foreach ($segment in ($Relative -split '\\')) { if ($script:V213ManifestExcluded -contains $segment) { return $true } }
    return $false
}

function Remove-V213TrailingSeparator([string]$Path) {
    if ($Path -match '^[A-Za-z]:\\$' -or $Path -match '^\\\\[^\\]+\\[^\\]+\\$') { return $Path }
    return $Path.TrimEnd('\')
}

function Resolve-V213DirectoryIdentity([string]$Path, [string]$Label) {
    if ($Path -match '^\\\\\.\\') { throw "${Label}_TOPOLOGY_DEVICE_NAMESPACE" }
    try { $full = [IO.Path]::GetFullPath($Path) }
    catch { throw "${Label}_TOPOLOGY_PATH_INVALID" }
    if (-not (Test-Path -LiteralPath $full -PathType Container)) {
        if (Test-Path -LiteralPath $full) { throw "${Label}_TOPOLOGY_NOT_DIRECTORY" }
    }
    $probe = $full
    $missing = New-Object 'System.Collections.Generic.List[string]'
    while (-not (Test-Path -LiteralPath $probe -PathType Container)) {
        $leaf = Split-Path -Leaf $probe
        if ([string]::IsNullOrWhiteSpace($leaf)) { throw "${Label}_TOPOLOGY_PATH_INVALID" }
        $missing.Insert(0, $leaf)
        $parent = Split-Path -Parent $probe
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $probe) { throw "${Label}_TOPOLOGY_PARENT_UNAVAILABLE" }
        $probe = $parent
    }
    $existing = Get-Item -LiteralPath $probe -Force
    $walk = $existing
    while ($null -ne $walk) {
        if (($walk.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "${Label}_TOPOLOGY_REPARSE_ANCESTOR" }
        $walk = $walk.Parent
    }
    $canonical = Remove-V213TrailingSeparator ([string]$existing.FullName)
    foreach ($part in $missing) { $canonical = Join-Path $canonical $part }
    return (Remove-V213TrailingSeparator $canonical)
}

function Test-V213SameOrBelow([string]$Ancestor, [string]$Candidate) {
    $a = Remove-V213TrailingSeparator $Ancestor
    $c = Remove-V213TrailingSeparator $Candidate
    return [string]::Equals($a, $c, [StringComparison]::OrdinalIgnoreCase) -or
        $c.StartsWith($a + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-V213NoReparseTree([string]$Root, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return }
    $pending = New-Object 'System.Collections.Generic.Stack[System.IO.DirectoryInfo]'
    $pending.Push([IO.DirectoryInfo](Get-Item -LiteralPath $Root -Force))
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($entry in $directory.GetFileSystemInfos()) {
            if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "${Label}_TOPOLOGY_REPARSE_ENTRY" }
            if ($entry -is [IO.DirectoryInfo]) { $pending.Push([IO.DirectoryInfo]$entry) }
        }
    }
}

function Get-V213Utf8Bytes([string]$Text) {
    $encoding = New-Object Text.UTF8Encoding($false)
    return ,$encoding.GetBytes($Text)
}

function Get-V213Sha256Bytes([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Get-V213Sha256File([string]$Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $stream = [IO.File]::OpenRead($Path)
        try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
        finally { $stream.Dispose() }
    }
    finally { $sha.Dispose() }
}

function Get-V213CanonicalJson([object]$Value) {
    return ($Value | ConvertTo-Json -Depth 16 -Compress)
}

function Write-V213BytesAtomic([string]$Path, [byte[]]$Bytes) {
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
    $temporary = Join-Path $directory ('.' + (Split-Path -Leaf $Path) + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllBytes($temporary, $Bytes)
        if (Test-Path -LiteralPath $Path -PathType Leaf) { [IO.File]::Replace($temporary, $Path, [System.Management.Automation.Language.NullString]::Value, $true) }
        else { [IO.File]::Move($temporary, $Path) }
    }
    finally { if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue } }
}

function Write-V213JsonAtomic([string]$Path, [object]$Value) {
    $text = (Get-V213CanonicalJson $Value) + "`n"
    Write-V213BytesAtomic $Path (Get-V213Utf8Bytes $text)
}

function Assert-V213MetadataFilePath([string]$Path) {
    # Inspect only named entries/ancestors, never recurse through UserData.
    [void](Resolve-V213DirectoryIdentity (Split-Path -Parent $Path) 'METADATA_ROOT')
    try { $entry = Get-Item -LiteralPath $Path -Force -ErrorAction Stop }
    catch [System.Management.Automation.ItemNotFoundException] { return }
    if ($entry -isnot [IO.FileInfo] -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'METADATA_PATH_UNADMITTED'
    }
}

function Read-V213Bytes([string]$Path) {
    Assert-V213MetadataFilePath $Path
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    return ,([IO.File]::ReadAllBytes($Path))
}

function Get-V213RelativePath([string]$Root, [IO.FileSystemInfo]$Entry) {
    return $Entry.FullName.Substring($Root.Length).TrimStart('\')
}

function Get-V213Manifest([string]$Root) {
    $entries = New-Object 'System.Collections.Generic.List[object]'
    $pending = New-Object 'System.Collections.Generic.Stack[System.IO.DirectoryInfo]'
    $pending.Push([IO.DirectoryInfo](Get-Item -LiteralPath $Root -Force))
    $fileCount = 0
    $byteCount = [int64]0
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($entry in $directory.GetFileSystemInfos()) {
            if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'RUNTIME_MANIFEST_REPARSE_ENTRY' }
            $relative = Get-V213RelativePath $Root $entry
            if ($relative -eq 'V213-RUNTIME-MANIFEST.json' -or $relative -eq 'V213-INSTALL-TRANSACTION.marker') { continue }
            if (Test-V213PathExcluded $relative) { continue }
            if ($entry -is [IO.DirectoryInfo]) {
                [void]$entries.Add([ordered]@{ path = $relative; kind = 'directory' })
                $pending.Push([IO.DirectoryInfo]$entry)
            }
            else {
                $size = [int64]$entry.Length
                $hash = Get-V213Sha256File $entry.FullName
                [void]$entries.Add([ordered]@{ path = $relative; kind = 'file'; size = $size; sha256 = $hash })
                $fileCount++
                $byteCount += $size
                if ($fileCount -gt 20000 -or $byteCount -gt 536870912) { throw 'RUNTIME_MANIFEST_BOUNDS_EXCEEDED' }
            }
        }
    }
    $sorted = @($entries | Sort-Object -Property path)
    $canonical = Get-V213CanonicalJson $sorted
    [pscustomobject]@{
        entries = $sorted
        sha256 = Get-V213Sha256Bytes (Get-V213Utf8Bytes $canonical)
        file_count = $fileCount
        byte_count = $byteCount
    }
}

function Assert-V213PackageIdentity([string]$Root) {
    if (Test-Path -LiteralPath (Join-Path $Root 'LOCAL-SOURCE-REFS.json')) { throw 'PACKAGE_IDENTITY_AMBIGUOUS' }
    $versionRefs = Join-Path $Root 'VERSION-REFS.json'
    $path = if (Test-Path -LiteralPath $versionRefs -PathType Leaf) { $versionRefs } else { Join-Path $Root 'HOTFIX-REFS.json' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'PACKAGE_IDENTITY_MISSING' }
    try { $identity = Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json }
    catch { throw 'PACKAGE_IDENTITY_INVALID' }
    if ($identity.artifact_kind -ne 'R75_FREE_WORKERS_RELAY_HOTFIX' -or
        $identity.package_version -ne '2.1.3' -or
        [string]$identity.source_commit -notmatch '^[0-9a-f]{40}$' -or
        [string]$identity.workflow_run_id -notmatch '^\d+$' -or
        $identity.production_mutation_by_ci -ne $false) { throw 'PACKAGE_IDENTITY_INVALID' }
    return $identity
}

function Assert-V213LocalSourceIdentity([string]$Root) {
    foreach ($other in @('VERSION-REFS.json', 'HOTFIX-REFS.json')) {
        if (Test-Path -LiteralPath (Join-Path $Root $other)) { throw 'PACKAGE_IDENTITY_AMBIGUOUS' }
    }
    $path = Join-Path $Root 'LOCAL-SOURCE-REFS.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'PACKAGE_IDENTITY_MISSING' }
    try {
        $identity = Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json
        $names = @($identity.PSObject.Properties.Name)
        $valid = ($names -contains 'workflow_run_id') -and ($names -contains 'release_qualified') -and
            $identity.artifact_kind -eq 'LOCAL_SOURCE_CHECKOUT' -and $identity.package_version -eq '2.1.3' -and
            [string]$identity.source_commit -match '^[0-9a-f]{40}$' -and $null -eq $identity.workflow_run_id -and
            $identity.release_qualified -eq $false -and $identity.production_mutation_by_ci -eq $false
    }
    catch { throw 'PACKAGE_IDENTITY_INVALID' }
    if (-not $valid) { throw 'PACKAGE_IDENTITY_INVALID' }
    return $identity
}

function Get-V213GitBlobSha1([string]$Path) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    $header = [Text.Encoding]::ASCII.GetBytes('blob ' + $bytes.Length + [char]0)
    $sha = [Security.Cryptography.SHA1]::Create()
    try {
        [void]$sha.TransformBlock($header, 0, $header.Length, $null, 0)
        [void]$sha.TransformFinalBlock($bytes, 0, $bytes.Length)
        return ([BitConverter]::ToString($sha.Hash)).Replace('-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

# Every exported file equals the git blob of the named commit and every tracked file is present. Allowed extras: the
# locally compiled launcher, the identity file and the pinned cloud/node_modules toolchain (npm ci of the lockfile).
function Assert-V213LocalSourceTree([string]$Root, [string]$Repository, [string]$Commit) {
    $git = (Get-Command git.exe -ErrorAction Stop).Source
    $encoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
        $listing = (& $git -C $Repository -c core.quotepath=off ls-tree -r -z --full-tree $Commit 2>$null) -join "`n"
        $code = $LASTEXITCODE
    }
    finally { [Console]::OutputEncoding = $encoding }
    if ($code -ne 0 -or [string]::IsNullOrEmpty($listing)) { throw 'PACKAGE_SOURCE_COMMIT_UNKNOWN' }
    $expected = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([StringComparer]::Ordinal)
    foreach ($record in ($listing -split [char]0)) {
        if ([string]::IsNullOrEmpty($record.Trim("`n"))) { continue }
        $match = [regex]::Match($record.Trim("`n"), '^(\d{6}) (\w+) ([0-9a-f]{40})\t(.+)$')
        if (-not $match.Success -or ($match.Groups[1].Value -notin @('100644', '100755'))) { throw 'PACKAGE_SOURCE_TREE_UNSUPPORTED' }
        $expected[$match.Groups[4].Value.Replace('/', '\')] = $match.Groups[3].Value
    }
    $allowed = @('InvestorIntelligence.exe', 'LOCAL-SOURCE-REFS.json')
    $seen = 0
    $pending = New-Object 'System.Collections.Generic.Stack[System.IO.DirectoryInfo]'
    $pending.Push([IO.DirectoryInfo](Get-Item -LiteralPath $Root -Force))
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($entry in $directory.GetFileSystemInfos()) {
            $relative = Get-V213RelativePath $Root $entry
            if ($entry -is [IO.DirectoryInfo]) {
                if ($relative -cne 'cloud\node_modules') { $pending.Push([IO.DirectoryInfo]$entry) }
                continue
            }
            if ($allowed -ccontains $relative) { continue }
            if (-not $expected.ContainsKey($relative) -or (Get-V213GitBlobSha1 $entry.FullName) -cne $expected[$relative]) {
                throw 'PACKAGE_SOURCE_TREE_MISMATCH'
            }
            $seen++
        }
    }
    if ($seen -ne $expected.Count) { throw 'PACKAGE_SOURCE_TREE_MISMATCH' }
}

function Get-V213ProfileMaps([string]$SelectedProfile) {
    $base = @(
        [ordered]@{ source = 'run-v213-local-llm-bridge-source-diverse.ps1'; destination = 'run-v213-local-llm-bridge.ps1' },
        [ordered]@{ source = 'install-v213-source-diverse-runtime-v2.ps1'; destination = 'install-v213-source-diverse-runtime.ps1' }
    )
    $sourceDiverse = @(
        [ordered]@{ source = 'run-v213-local-llm-bridge.ps1'; destination = 'run-v213-local-llm-bridge.ps1' },
        [ordered]@{ source = 'scripts\run_v213_local_llm_bridge_core.ps1'; destination = 'scripts\run_v213_local_llm_bridge_core.ps1' },
        [ordered]@{ source = 'scripts\v213_local_llm_gateway.py'; destination = 'scripts\v213_local_llm_gateway.py' },
        [ordered]@{ source = 'scripts\v213_source_independence_gate.py'; destination = 'scripts\v213_source_independence_gate.py' },
        [ordered]@{ source = 'config\v213-serenity-public-logic-policy.json'; destination = 'config\v213-serenity-public-logic-policy.json' },
        [ordered]@{ source = 'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.zh-TW.md'; destination = 'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.zh-TW.md' },
        [ordered]@{ source = 'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.en.md'; destination = 'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.en.md' }
    )
    $v2 = @(
        [ordered]@{ source = 'run-v213-local-llm-bridge-source-diverse.ps1'; destination = 'run-v213-local-llm-bridge.ps1' },
        [ordered]@{ source = 'scripts\run_v213_local_llm_bridge_core.ps1'; destination = 'scripts\run_v213_local_llm_bridge_core.ps1' },
        [ordered]@{ source = 'scripts\run_v213_local_llm_bridge_core_v2.ps1'; destination = 'scripts\run_v213_local_llm_bridge_core_v2.ps1' },
        [ordered]@{ source = 'scripts\v213_local_llm_gateway.py'; destination = 'scripts\v213_local_llm_gateway.py' },
        [ordered]@{ source = 'scripts\v213_source_independence_gate.py'; destination = 'scripts\v213_source_independence_gate.py' },
        [ordered]@{ source = 'scripts\v213_source_independence_gate_v2.py'; destination = 'scripts\v213_source_independence_gate_v2.py' },
        [ordered]@{ source = 'scripts\v213_source_independence_gate_v3.py'; destination = 'scripts\v213_source_independence_gate_v3.py' },
        [ordered]@{ source = 'scripts\build_v213_activation_bundle_v2.py'; destination = 'scripts\build_v213_activation_bundle_v2.py' },
        [ordered]@{ source = 'sync-v213-activation-bundle.ps1'; destination = 'sync-v213-activation-bundle.ps1' },
        [ordered]@{ source = 'config\v213-serenity-public-logic-policy.json'; destination = 'config\v213-serenity-public-logic-policy.json' },
        [ordered]@{ source = 'config\v213-market-corroboration-degradation-policy.json'; destination = 'config\v213-market-corroboration-degradation-policy.json' },
        [ordered]@{ source = 'config\v213-source-diversity-field-labels.zh-en.json'; destination = 'config\v213-source-diversity-field-labels.zh-en.json' },
        [ordered]@{ source = 'scripts\audit_v213_source_diversity_fields.py'; destination = 'scripts\audit_v213_source_diversity_fields.py' },
        [ordered]@{ source = 'scripts\v213_methodology_and_source_audit.py'; destination = 'scripts\v213_methodology_and_source_audit.py' },
        [ordered]@{ source = 'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.zh-TW.md'; destination = 'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.zh-TW.md' },
        [ordered]@{ source = 'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.en.md'; destination = 'docs\V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.en.md' },
        [ordered]@{ source = 'activate-v213-seven-field-schedule.ps1'; destination = 'activate-v213-seven-field-schedule.ps1' },
        [ordered]@{ source = 'install-v213-source-diverse-runtime-v2.ps1'; destination = 'install-v213-source-diverse-runtime.ps1' }
    )
    $latest = @(
        [ordered]@{ source = 'run-v213-local-serenity-latest.ps1'; destination = 'run-v213-local.ps1' },
        [ordered]@{ source = 'activate-v213-seven-field-schedule.ps1'; destination = 'activate-v213-seven-field-schedule.ps1' },
        [ordered]@{ source = 'install-v213-serenity-latest-runtime.ps1'; destination = 'install-v213-source-diverse-runtime.ps1' },
        [ordered]@{ source = 'scripts\v213_refresh_serenity_public_sources.py'; destination = 'scripts\v213_refresh_serenity_public_sources.py' },
        [ordered]@{ source = 'scripts\v213_serenity_latest_multisource_audit.py'; destination = 'scripts\v213_serenity_latest_multisource_audit.py' },
        [ordered]@{ source = 'scripts\v213_tam_capture_claim_guard.py'; destination = 'scripts\v213_tam_capture_claim_guard.py' },
        [ordered]@{ source = 'config\v213-serenity-latest-multisource-policy-v5.json'; destination = 'config\v213-serenity-latest-multisource-policy-v5.json' },
        [ordered]@{ source = 'config\v213-serenity-methodology-lineage-v1.json'; destination = 'config\v213-serenity-methodology-lineage-v1.json' }
    )
    switch ($SelectedProfile) {
        'BASE' { return $base }
        'SOURCE_DIVERSE' { return @($base + $sourceDiverse) }
        'SOURCE_DIVERSE_V2' { return @($base + $v2) }
        'SERENITY_LATEST' { return @($base + $v2 + $latest) }
    }
    throw 'RUNTIME_PROFILE_INVALID'
}

function Assert-V213OwnedDestination([string]$Root, [string]$MetadataRoot, [string]$ExpectedRuntimeIdentity) {
    $items = @(Get-Item -LiteralPath $Root -Force | ForEach-Object { $_.GetFileSystemInfos() })
    if ($items.Count -eq 0) { return $null }
    $receiptPath = Join-Path $MetadataRoot 'v213-runtime-install-receipt.json'
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { throw 'RUNTIME_OWNERSHIP_UNPROVEN' }
    try { $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding utf8 | ConvertFrom-Json }
    catch { throw 'RUNTIME_OWNERSHIP_INVALID' }
    if ([string]$receipt.runtime_root -ne $ExpectedRuntimeIdentity -or
        [string]$receipt.manifest_path -ne 'V213-RUNTIME-MANIFEST.json' -or
        [string]$receipt.manifest_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$receipt.effective_entries_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$receipt.profile -notmatch '^(BASE|SOURCE_DIVERSE|SOURCE_DIVERSE_V2|SERENITY_LATEST)$') { throw 'RUNTIME_OWNERSHIP_INVALID' }
    if (Test-Path -LiteralPath (Join-Path $Root 'V213-INSTALL-TRANSACTION.marker')) { throw 'RUNTIME_RECOVERY_REQUIRED' }
    $manifestPath = Join-Path $Root 'V213-RUNTIME-MANIFEST.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'RUNTIME_OWNERSHIP_UNPROVEN' }
    try { $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json }
    catch { throw 'RUNTIME_OWNERSHIP_INVALID' }
    if ($manifest.schema_version -ne 1 -or [string]$manifest.entries_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [int]$manifest.entry_count -lt 0 -or [int64]$manifest.byte_count -lt 0) { throw 'RUNTIME_OWNERSHIP_INVALID' }
    $manifestBytes = [IO.File]::ReadAllBytes($manifestPath)
    if ((Get-V213Sha256Bytes $manifestBytes) -ne [string]$receipt.manifest_sha256) { throw 'RUNTIME_OWNERSHIP_DIGEST_MISMATCH' }
    # Coverage-aware ownership: the manifest file must be authentic per the
    # receipt, every live payload file must be a known unmodified manifest
    # entry, and every payload entry of the historical manifest must remain
    # present and unmodified. Paths dropped by a coverage migration (mutable
    # data/) are never re-attested, so a completed refresh cannot block the
    # next reinstall.
    $manifestFiles = @{}
    foreach ($e in $manifest.entries) { if ($e.kind -eq 'file') { $manifestFiles[[string]$e.path] = [string]$e.sha256 } }
    $actual = Get-V213Manifest $Root
    foreach ($e in $actual.entries) {
        if ($e.kind -ne 'file') { continue }
        $path = [string]$e.path
        if (-not $manifestFiles.ContainsKey($path) -or $manifestFiles[$path] -cne [string]$e.sha256) { throw 'RUNTIME_OWNERSHIP_DIGEST_MISMATCH' }
    }
    foreach ($e in $manifest.entries) {
        if ($e.kind -ne 'file') { continue }
        $path = [string]$e.path
        if (Test-V213PathExcluded $path) { continue }
        $livePath = Join-Path $Root $path
        if (-not (Test-Path -LiteralPath $livePath -PathType Leaf)) { throw 'RUNTIME_OWNERSHIP_DIGEST_MISMATCH' }
        if ((Get-V213Sha256File $livePath) -cne [string]$e.sha256) { throw 'RUNTIME_OWNERSHIP_DIGEST_MISMATCH' }
    }
    return $receipt
}

function Write-V213Journal([string]$Path, [hashtable]$Base, [string]$State, [string]$FailureCode = '') {
    $value = [ordered]@{}
    foreach ($key in $Base.Keys) { $value[$key] = $Base[$key] }
    $value['schema_version'] = 1
    $value['state'] = $State
    if ($FailureCode) { $value['failure_code'] = $FailureCode }
    else { $value.Remove('failure_code') }
    Write-V213JsonAtomic $Path $value
}

function Remove-V213OwnedTree([string]$Root, [string]$MarkerPath, [string]$MarkerValue) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return $true }
    if (-not (Test-Path -LiteralPath $MarkerPath -PathType Leaf)) { return $false }
    $marker = [IO.File]::ReadAllText($MarkerPath, (New-Object Text.UTF8Encoding($false)))
    if ($marker -cne $MarkerValue) { return $false }
    Assert-V213NoReparseTree $Root 'RUNTIME_ROLLBACK'
    Remove-Item -LiteralPath $Root -Recurse -Force
    return (-not (Test-Path -LiteralPath $Root))
}

function Restore-V213Metadata([string]$Path, [byte[]]$Original, [bool]$Existed, [byte[]]$NewBytes) {
    if (-not (Test-Path -LiteralPath $Path) -and -not $Existed) { return $true }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $current = [IO.File]::ReadAllBytes($Path)
    if ($null -eq $NewBytes -or (Get-V213Sha256Bytes $current) -ne (Get-V213Sha256Bytes $NewBytes)) { return $false }
    if ($Existed) { Write-V213BytesAtomic $Path $Original }
    else { Remove-Item -LiteralPath $Path -Force; if (Test-Path -LiteralPath $Path) { return $false } }
    return $true
}

$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
if ($RestorePrevious) {
    . (Join-Path $PSScriptRoot 'v213_runtime_restore_previous.ps1')
    Invoke-V213RestorePrevious -RuntimeRoot $RuntimeRoot -TransactionId $RestorePrevious
    return
}
if (-not $Profile) { throw 'RUNTIME_PROFILE_INVALID' }
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { throw 'PROJECT_ROOT_REQUIRED' }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$localSource = $PackageOrigin -eq 'LOCAL_SOURCE_CHECKOUT'
if ($localSource) {
    if ([string]::IsNullOrWhiteSpace($SourceRepository)) { throw 'PACKAGE_SOURCE_REPOSITORY_REQUIRED' }
    $identity = Assert-V213LocalSourceIdentity $ProjectRoot
    Assert-V213LocalSourceTree $ProjectRoot ([IO.Path]::GetFullPath($SourceRepository)) ([string]$identity.source_commit)
}
else {
    $identity = Assert-V213PackageIdentity $ProjectRoot
}
$sourceIdentity = Resolve-V213DirectoryIdentity $ProjectRoot 'PROJECT_ROOT'
$runtimeIdentity = Resolve-V213DirectoryIdentity $RuntimeRoot 'RUNTIME_ROOT'
if ((Test-V213SameOrBelow $sourceIdentity $runtimeIdentity) -or (Test-V213SameOrBelow $runtimeIdentity $sourceIdentity)) {
    throw 'RUNTIME_TOPOLOGY_SOURCE_DESTINATION_OVERLAP'
}
foreach ($reserved in @('_workspace', '_archive')) {
    if (Test-Path -LiteralPath (Join-Path $sourceIdentity $reserved) -PathType Container) { throw 'PROJECT_ROOT_MIXED_USE' }
}
Assert-V213NoReparseTree $sourceIdentity 'PROJECT_ROOT'
Assert-V213NoReparseTree $runtimeIdentity 'RUNTIME_ROOT'
$maps = Get-V213ProfileMaps $Profile
$sourceBefore = Get-V213Manifest $sourceIdentity

$localAppData = Resolve-V213DirectoryIdentity $env:LOCALAPPDATA 'LOCALAPPDATA'
if (Test-V213SameOrBelow $sourceIdentity $localAppData) { throw 'METADATA_TOPOLOGY_SOURCE_OVERLAP' }
$metadataRoot = Join-Path $localAppData 'InvestorIntelligence'
$journalPath = Join-Path $metadataRoot 'v213-runtime-install.journal.json'
$receiptPath = Join-Path $metadataRoot 'v213-runtime-install-receipt.json'
$statePath = Join-Path $metadataRoot 'v213-runtime-state.json'
# Refuse occupied metadata paths before lock creation, journal writes or staging.
# This is a shape guard, not a lock/ownership or durable recovery guarantee.
foreach ($metadataPath in @($journalPath, $receiptPath, $statePath)) {
    Assert-V213MetadataFilePath $metadataPath
}
# The lock lives in an already-existing system temp directory so acquiring it is the first mutation-safe operation even when LOCALAPPDATA is a new fixture root.
$lockPath = Join-Path ([IO.Path]::GetTempPath()) 'InvestorIntelligence-v213-runtime-install.lock'
$transactionId = [guid]::NewGuid().ToString('N')
$runtimeLeaf = Split-Path -Leaf $runtimeIdentity
$runtimeParent = Split-Path -Parent $runtimeIdentity
$stagePath = Join-Path $runtimeParent ($runtimeLeaf + '.stage.' + $transactionId)
$oldPath = Join-Path $runtimeParent ($runtimeLeaf + '.old.' + $transactionId)
$markerName = 'V213-INSTALL-TRANSACTION.marker'
$markerPath = Join-Path $stagePath $markerName
$markerValue = 'V213_RUNTIME_INSTALL_V1:' + $transactionId
$lock = $null
$oldMoved = $false
$newCommitted = $false
$stageCreated = $false
$metadataRootCreated = $false
$journalBase = [ordered]@{
    transaction_id = $transactionId
    profile = $Profile
    source_commit = [string]$identity.source_commit
    runtime_root = $runtimeIdentity
    stage_root = $stagePath
    old_root = $oldPath
    metadata_scope = 'local_non_secret_runtime_metadata'
}
$stateExisted = $false
$stateOriginal = $null
$receiptExisted = $false
$receiptOriginal = $null
$newStateBytes = $null
$newReceiptBytes = $null
$journalInitialized = $false
$finalized = $false
$failureCode = 'RUNTIME_INSTALL_UNEXPECTED'

try {
    try { $lock = New-Object IO.FileStream($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
    catch { throw 'RUNTIME_INSTALL_LOCK_BUSY' }
    if (Test-Path -LiteralPath $journalPath -PathType Leaf) {
        try { $existingJournal = Get-Content -LiteralPath $journalPath -Raw -Encoding utf8 | ConvertFrom-Json }
        catch { throw 'RUNTIME_RECOVERY_REQUIRED' }
        if ([int]$existingJournal.schema_version -ne 1 -or [string]$existingJournal.state -notmatch '^(FINALIZED|ROLLED_BACK|RESTORED_PREVIOUS)$') {
            throw 'RUNTIME_RECOVERY_REQUIRED'
        }
    }
    New-Item -ItemType Directory -Force -Path $metadataRoot | Out-Null
    $runtimeExisted = Test-Path -LiteralPath $runtimeIdentity -PathType Container
    $oldReceipt = $null
    if ($runtimeExisted) {
        $oldReceipt = Assert-V213OwnedDestination $runtimeIdentity $metadataRoot $runtimeIdentity
    }
    foreach ($map in $maps) {
        if (-not (Test-Path -LiteralPath (Join-Path $sourceIdentity $map.source) -PathType Leaf)) { throw 'RUNTIME_PROFILE_SOURCE_MISSING' }
    }
    New-Item -ItemType Directory -Force -Path $metadataRoot | Out-Null
    $metadataRootCreated = $true
    $stateOriginal = Read-V213Bytes $statePath
    $stateExisted = $null -ne $stateOriginal
    $receiptOriginal = Read-V213Bytes $receiptPath
    $receiptExisted = $null -ne $receiptOriginal
    if ((Test-Path -LiteralPath $stagePath -PathType Leaf) -or (Test-Path -LiteralPath $stagePath -PathType Container) -or
        (Test-Path -LiteralPath $oldPath -PathType Leaf) -or (Test-Path -LiteralPath $oldPath -PathType Container)) { throw 'RUNTIME_RECOVERY_REQUIRED' }
    Write-V213Journal $journalPath $journalBase 'LOCKED'
    $journalInitialized = $true

    New-Item -ItemType Directory -Force -Path $runtimeParent | Out-Null
    New-Item -ItemType Directory -Force -Path $stagePath | Out-Null
    $stageCreated = $true
    [IO.File]::WriteAllText((Join-Path $stagePath $markerName), $markerValue, (New-Object Text.UTF8Encoding($false)))
    $robocopy = (Get-Command robocopy.exe -ErrorAction Stop).Source
    # Exclusions are full paths (top level only). Name-based /XD would also
    # exclude cloud/node_modules, but the runtime needs that pinned toolchain:
    # the sealed refresh AUTH_CHECK invokes cloud/node_modules/.bin/wrangler.cmd
    # before any production mutation.
    $robocopyArgs = @(
        $sourceIdentity, $stagePath, '/MIR', '/R:2', '/W:1',
        '/NFL', '/NDL', '/NJH', '/NJS', '/NP',
        '/XD', (Join-Path $sourceIdentity '.git'), (Join-Path $sourceIdentity 'versions'),
              (Join-Path $sourceIdentity 'node_modules'), (Join-Path $sourceIdentity '.venv-v213-local'),
              (Join-Path $sourceIdentity '.npm-cache'),
        '/XF', $markerName, 'V213-RUNTIME-MANIFEST.json'
    )
    & $robocopy @robocopyArgs
    $copyCode = $LASTEXITCODE
    if ($copyCode -gt 7) { throw 'RUNTIME_STAGE_COPY_FAILED' }
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) { throw 'RUNTIME_STAGE_OWNERSHIP_UNPROVEN' }
    Assert-V213NoReparseTree $stagePath 'RUNTIME_STAGE'
    $sourceAfterCopy = Get-V213Manifest $sourceIdentity
    if ($sourceBefore.sha256 -ne $sourceAfterCopy.sha256) { throw 'RUNTIME_SOURCE_CHANGED_DURING_COPY' }

    foreach ($map in $maps) {
        $from = Join-Path $sourceIdentity $map.source
        $to = Join-Path $stagePath $map.destination
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $to) | Out-Null
        Copy-Item -LiteralPath $from -Destination $to -Force
        if ((Get-V213Sha256File $from) -ne (Get-V213Sha256File $to)) { throw 'RUNTIME_OVERLAY_HASH_MISMATCH' }
    }

    $required = @(
        'run-v213-local.ps1','run-v213-local-llm-bridge.ps1','activate-v213-seven-field-schedule.ps1',
        'activate-v213-seven-field-schedule-core.ps1','activate-v213-diversified-schedule.ps1','sync-v213-top20-report.ps1',
        'register-v213-refresh-tasks.ps1','install-v213-source-diverse-runtime.ps1','InvestorIntelligence.exe',
        'config\v213-source-federation-policy.json','config\v213-serenity-evidence-standard-v3.json',
        'config\v213-serenity-public-logic-policy.json','config\v213-market-corroboration-degradation-policy.json',
        'config\v213-source-diversity-field-labels.zh-en.json','config\authoritative-sources\v213-runtime-extensions.json',
        'scripts\v213_source_federation.py','scripts\v213_source_federation_gate.py',
        'scripts\v213_apply_diversified_operationalization.py','scripts\v213_build_v21_public_snapshot.py',
        'scripts\build_v213_activation_bundle_v2.py','sync-v213-activation-bundle.ps1',
        'scripts\v213_pipeline_boundary_self_test.py','scripts\v213_methodology_and_source_audit.py',
        'scripts\v213_source_independence_gate.py','scripts\v213_source_independence_gate_v2.py',
        'scripts\v213_source_independence_gate_v3.py','scripts\audit_v213_source_diversity_fields.py',
        'scripts\v213_local_llm_gateway.py','scripts\run_v213_local_llm_bridge_core.ps1',
        'scripts\run_v213_local_llm_bridge_core_v2.ps1','scripts\adapters\nasdaq_symbol_directory.py',
        'scripts\v213_runtime_install_coordinator.ps1'
    )
    if ($Profile -eq 'SERENITY_LATEST') {
        $required += @('scripts\v213_refresh_serenity_public_sources.py','scripts\v213_serenity_latest_multisource_audit.py',
            'scripts\v213_tam_capture_claim_guard.py','config\v213-serenity-latest-multisource-policy-v5.json',
            'config\v213-serenity-methodology-lineage-v1.json')
    }
    foreach ($item in $required) { if (-not (Test-Path -LiteralPath (Join-Path $stagePath $item) -PathType Leaf)) { throw 'RUNTIME_REQUIRED_FILE_MISSING' } }
    # Publication toolchain: when the source ships wrangler (pinned by the
    # cloud package-lock), the stage must carry it for AUTH_CHECK.
    $wranglerSource = Join-Path $sourceIdentity 'cloud\node_modules\.bin\wrangler.cmd'
    if ((Test-Path -LiteralPath $wranglerSource -PathType Leaf) -and
        -not (Test-Path -LiteralPath (Join-Path $stagePath 'cloud\node_modules\.bin\wrangler.cmd') -PathType Leaf)) { throw 'RUNTIME_REQUIRED_FILE_MISSING' }

    $refresh = [IO.File]::ReadAllText((Join-Path $stagePath 'run-v213-local.ps1'), (New-Object Text.UTF8Encoding($false)))
    $orderedPipeline = @('v213_v21_progress_runner.py','v213_v212_progress_runner.py','reconcile_v213_order_evidence.py',
        'build_v213_scheduled_top20_report.py','v213_source_federation.py','v213_source_federation_gate.py',
        'v213_apply_diversified_operationalization.py','v213_source_independence_gate_v3.py','v213_build_v21_public_snapshot.py')
    $previous = -1
    foreach ($token in $orderedPipeline) { $position = $refresh.IndexOf($token, [StringComparison]::Ordinal); if ($position -le $previous) { throw 'RUNTIME_PIPELINE_ORDER_INVALID' }; $previous = $position }
    if ($refresh.Contains("& `$python 'scripts\build_v21_public_snapshot.py'")) { throw 'RUNTIME_LEGACY_SNAPSHOT_BUILDER' }
    if ($localSource -and -not (Test-Path -LiteralPath (Join-Path $stagePath 'cloud\node_modules\.bin\wrangler.cmd') -PathType Leaf)) {
        throw 'RUNTIME_REQUIRED_FILE_MISSING'
    }
    if (-not $refresh.Contains('--enforce')) { throw 'RUNTIME_SOURCE_GATE_NOT_ENFORCED' }
    if (-not $refresh.Contains('company/claim diversity is blocking; unavailable free market cross-checks are disclosed and cap confidence')) { throw 'RUNTIME_MARKET_BOUNDARY_MISSING' }
    $bridge = [IO.File]::ReadAllText((Join-Path $stagePath 'run-v213-local-llm-bridge.ps1'), (New-Object Text.UTF8Encoding($false)))
    if (-not $bridge.Contains('run_v213_local_llm_bridge_core_v2.ps1')) { throw 'RUNTIME_BRIDGE_CORE_INVALID' }
    $activation = [IO.File]::ReadAllText((Join-Path $stagePath 'activate-v213-seven-field-schedule.ps1'), (New-Object Text.UTF8Encoding($false)))
    $sourceMarkers = @('V213_SOURCE_INDEPENDENCE_PREFLIGHT','V213_MARKET_CORROBORATION_QUALITY = DEGRADED',
        'market_corroboration_status','health-schema-v2','install-v213-source-diverse-runtime.ps1','rollback')
    $r75Markers = @('v213_r75_activation_preflight.py','V213_R75_ACTIVATION_WRAPPER_SELF_TEST',
        'V213_R75_SEALED_BUNDLE_SHA256','activate-v213-seven-field-schedule-core.ps1','ConfirmActivation','RequireLocalModel')
    $validActivation = $true
    foreach ($marker in $sourceMarkers) { if (-not $activation.Contains($marker)) { $validActivation = $false; break } }
    if (-not $validActivation) {
        $validActivation = $true
        foreach ($marker in $r75Markers) { if (-not $activation.Contains($marker)) { $validActivation = $false; break } }
    }
    if (-not $validActivation) { throw 'RUNTIME_ACTIVATION_CONTRACT_INVALID' }
    $gateway = [IO.File]::ReadAllText((Join-Path $stagePath 'scripts\v213_local_llm_gateway.py'), (New-Object Text.UTF8Encoding($false)))
    foreach ($marker in @('SOURCE-INDEPENDENCE RULES','v213_source_independence_latest.json','cap confidence at LIMITED','Yahoo/yfinance','Conflicting sources')) {
        if (-not $gateway.Contains($marker)) { throw 'RUNTIME_GATEWAY_CONTRACT_INVALID' }
    }

    $stateValue = [ordered]@{
        schema_version = 6; product_version = '2.1.3'; runtime_root = $runtimeIdentity; source_root = $sourceIdentity
        installed_utc = (Get-Date).ToUniversalTime().ToString('o')
        runtime_profile = 'source-diverse-exact-model-health-schema2-pipeline-v3-market-quality-aware'
        activation_contract_profile = $Profile
        scoring_version = 'system-operationalization-v2.1.3-diversified'
        provisional_scoring_version = 'system-operationalization-v2.1.3-safe-preselection'
        provisional_snapshot_promotion_blocked = $true; diversified_operationalization_required_before_snapshot = $true
        canonical_snapshot_builder = 'scripts/v213_build_v21_public_snapshot.py'; serenity_evidence_standard = '2.1.3-source-independence-v3'
        source_catalog_count = 101; source_catalog_is_not_live_use = $true; live_source_federation_required = $true
        claim_level_source_independence_required = $true; source_independence_gate = 'scripts/v213_source_independence_gate_v3.py'
        source_independence_policy = 'config/v213-serenity-public-logic-policy.json'
        market_quality_policy = 'config/v213-market-corroboration-degradation-policy.json'
        market_endpoint_unavailability_is_global_blocker = $false; market_corroboration_required_for_high_confidence_inference = $true
        uncorroborated_valuation_factor_max = 3.75; provider_failures_disclosed = $true; source_conflicts_averaged = $false
        source_diversity_labels = 'config/v213-source-diversity-field-labels.zh-en.json'; market_calculation_source = 'yfinance_compatibility_only'
        preferred_model = $null; model_selection_authority = 'runtime_model_profile'; model_profile_qualified = $false
        health_schema_version = 2; official_serenity_formula_claimed = $false; official_serenity_score_claimed = $false
        private_serenity_method_reproduced = $false
    }
    if ($localSource) {
        $stateValue['package_origin'] = 'LOCAL_SOURCE_CHECKOUT'; $stateValue['workflow_run_id'] = $null; $stateValue['release_qualified'] = $false
        $stateValue['source_commit'] = [string]$identity.source_commit
    }
    if ($Profile -eq 'SOURCE_DIVERSE') {
        $profileReceipt = [ordered]@{ schema_version=1; product_version='2.1.3'; runtime_profile='source-diverse-exact-model'; installed_utc=(Get-Date).ToUniversalTime().ToString('o'); preferred_model=$null; model_selection_authority='runtime_model_profile'; model_profile_qualified=$false; health_schema_version=2; source_independence_gate='scripts/v213_source_independence_gate.py'; source_policy='config/v213-serenity-public-logic-policy.json'; official_serenity_formula_claimed=$false; private_serenity_method_reproduced=$false }
        Write-V213JsonAtomic (Join-Path $stagePath 'V213-SOURCE-DIVERSE-RUNTIME.json') $profileReceipt
    }
    elseif ($Profile -eq 'SOURCE_DIVERSE_V2' -or $Profile -eq 'SERENITY_LATEST') {
        $profileReceipt = [ordered]@{ schema_version=3; product_version='2.1.3'; runtime_profile='source-diverse-exact-model-health-schema2-market-quality-aware'; installed_utc=(Get-Date).ToUniversalTime().ToString('o'); preferred_model=$null; model_selection_authority='runtime_model_profile'; model_profile_qualified=$false; health_schema_version=2; source_independence_gate='scripts/v213_source_independence_gate_v3.py'; source_policy='config/v213-serenity-public-logic-policy.json'; market_quality_policy='config/v213-market-corroboration-degradation-policy.json'; market_endpoint_unavailability_is_global_blocker=$false; market_corroboration_required_for_high_confidence_inference=$true; uncorroborated_valuation_factor_max=3.75; provider_failures_disclosed=$true; source_conflicts_averaged=$false; source_field_labels='config/v213-source-diversity-field-labels.zh-en.json'; official_serenity_formula_claimed=$false; private_serenity_method_reproduced=$false }
        Write-V213JsonAtomic (Join-Path $stagePath 'V213-SOURCE-DIVERSE-RUNTIME.json') $profileReceipt
    }
    if ($Profile -eq 'SERENITY_LATEST') {
        $latestReceipt = [ordered]@{ schema_version=2; product_version='2.1.3'; runtime_profile='serenity-latest-per-ticker-multisource-v5'; installed_utc=(Get-Date).ToUniversalTime().ToString('o'); base_runtime_handoff='exception-free-plus-receipt-verified'; stable_activation_wrapper='source-independence-aware-current-contract'; retired_strict_post_bundle_audit=$false; stale_native_exit_code_is_success_authority=$false; preferred_model=$null; model_selection_authority='runtime_model_profile'; model_profile_qualified=$false; latest_public_serenity_source_required=$true; per_ticker_claim_source_families_minimum=2; per_ticker_claim_source_domains_minimum=2; per_ticker_primary_sources_minimum=1; market_providers_for_high_confidence=2; market_same_metric_basis_required=$true; yahoo_truth_anchor=$false; source_values_averaged=$false; severe_thesis_killers_override_score=$true; exact_pointer_rollback=$true; exact_worker_rollback=$true; official_serenity_formula_claimed=$false; private_serenity_method_reproduced=$false }
        Write-V213JsonAtomic (Join-Path $stagePath 'V213-SERENITY-LATEST-RUNTIME.json') $latestReceipt
    }

    $effective = Get-V213Manifest $stagePath
    $manifestValue = [ordered]@{ schema_version=1; transaction_id=$transactionId; profile=$Profile; source_commit=[string]$identity.source_commit; entries_sha256=$effective.sha256; entry_count=$effective.file_count; file_count=$effective.file_count; byte_count=$effective.byte_count; entries=@($effective.entries) }
    Write-V213JsonAtomic (Join-Path $stagePath 'V213-RUNTIME-MANIFEST.json') $manifestValue
    $manifestBytes = [IO.File]::ReadAllBytes((Join-Path $stagePath 'V213-RUNTIME-MANIFEST.json'))
    $effectiveAfterManifest = Get-V213Manifest $stagePath
    if ($effectiveAfterManifest.sha256 -ne $effective.sha256) { throw 'RUNTIME_EFFECTIVE_MANIFEST_CHANGED' }
    Write-V213Journal $journalPath $journalBase 'PREPARED'
    if ($runtimeExisted) {
        # Preimages for -RestorePrevious: the retained old root is only restorable with the metadata it was attested by.
        $preimage = [ordered]@{ schema_version = 1; transaction_id = $transactionId; runtime_root = $runtimeIdentity; old_root = $oldPath
            state_existed = $stateExisted; state_base64 = $(if ($stateExisted) { [Convert]::ToBase64String($stateOriginal) } else { $null })
            receipt_existed = $receiptExisted; receipt_base64 = $(if ($receiptExisted) { [Convert]::ToBase64String($receiptOriginal) } else { $null }) }
        Write-V213JsonAtomic (Join-Path $metadataRoot ('v213-previous-' + $transactionId + '.json')) $preimage
    }

    # The live root is rechecked immediately before the only destructive rename.
    $runtimeExistsNow = Test-Path -LiteralPath $runtimeIdentity -PathType Container
    if ($runtimeExistsNow -ne $runtimeExisted) { throw 'RUNTIME_CONCURRENT_MUTATION' }
    if ($runtimeExisted) {
        [void](Assert-V213OwnedDestination $runtimeIdentity $metadataRoot $runtimeIdentity)
        $currentState = Read-V213Bytes $statePath
        if (($stateExisted -and $null -eq $currentState) -or (-not $stateExisted -and $null -ne $currentState) -or
            ($stateExisted -and (Get-V213Sha256Bytes $currentState) -ne (Get-V213Sha256Bytes $stateOriginal))) { throw 'METADATA_CONCURRENT_MUTATION' }
    }
    Write-V213Journal $journalPath $journalBase 'COMMIT_INTENT'
    if ($runtimeExisted) {
        Move-Item -LiteralPath $runtimeIdentity -Destination $oldPath
        $oldMoved = $true
        Write-V213Journal $journalPath $journalBase 'OLD_RETAINED'
    }
    Move-Item -LiteralPath $stagePath -Destination $runtimeIdentity
    $newCommitted = $true
    $stageCreated = $false
    Write-V213Journal $journalPath $journalBase 'NEW_PRESENT'
    $liveManifest = Get-V213Manifest $runtimeIdentity
    if ($liveManifest.sha256 -ne $effective.sha256 -or -not (Test-Path -LiteralPath (Join-Path $runtimeIdentity $markerName) -PathType Leaf)) { throw 'RUNTIME_LIVE_MANIFEST_INVALID' }

    $newStateBytes = Get-V213Utf8Bytes ((Get-V213CanonicalJson $stateValue) + "`n")
    $newReceiptValue = [ordered]@{ schema_version=1; status='LOCAL_COMMITTED_PENDING_FINALIZE'; transaction_id=$transactionId; profile=$Profile; runtime_root=$runtimeIdentity; manifest_path='V213-RUNTIME-MANIFEST.json'; manifest_sha256=Get-V213Sha256Bytes $manifestBytes; effective_entries_sha256=$effective.sha256; file_count=$effective.file_count; byte_count=$effective.byte_count; source_commit=[string]$identity.source_commit; model_selection_authority='runtime_model_profile'; preferred_model=$null; model_profile_qualified=$false; production_mutation_by_ci=$false }
    if ($localSource) {
        $newReceiptValue['package_origin'] = 'LOCAL_SOURCE_CHECKOUT'; $newReceiptValue['workflow_run_id'] = $null; $newReceiptValue['release_qualified'] = $false
        $newReceiptValue['overlay_map'] = @($maps | ForEach-Object { [string]$_.source + ' -> ' + [string]$_.destination })
    }
    $newReceiptBytes = Get-V213Utf8Bytes ((Get-V213CanonicalJson $newReceiptValue) + "`n")
    Write-V213BytesAtomic $statePath $newStateBytes
    Write-V213BytesAtomic $receiptPath $newReceiptBytes
    Write-V213Journal $journalPath $journalBase 'LOCAL_COMMITTED_PENDING_FINALIZE'
    Remove-Item -LiteralPath (Join-Path $runtimeIdentity $markerName) -Force
    if (Test-Path -LiteralPath (Join-Path $runtimeIdentity $markerName)) { throw 'RUNTIME_TRANSACTION_MARKER_REMAINS' }
    Write-V213Journal $journalPath $journalBase 'FINALIZED'
    $finalized = $true
    if ($lock) { $lock.Dispose(); $lock = $null }
    $global:LASTEXITCODE = 0
    Write-Host "V213_RUNTIME_INSTALL = PASS; profile=$Profile; package_origin=$PackageOrigin; staging=true; transaction=$transactionId; rollback_original_retained=$oldMoved; model_selection=runtime_profile_only" -ForegroundColor Green
}
catch {
    $matchedFailure = [regex]::Match([string]$_.Exception.Message, '^[A-Z][A-Z0-9_]+')
    if ($matchedFailure.Success) { $failureCode = $matchedFailure.Value }
    $rollbackCode = 'PASS'
    try {
        if ($newCommitted -and (Test-Path -LiteralPath $runtimeIdentity -PathType Container)) {
            if (-not (Remove-V213OwnedTree $runtimeIdentity (Join-Path $runtimeIdentity $markerName) $markerValue)) { throw 'LIVE_OWNERSHIP_UNVERIFIED' }
            $newCommitted = $false
        }
        if ($stageCreated -and (Test-Path -LiteralPath $stagePath -PathType Container)) {
            if (-not (Remove-V213OwnedTree $stagePath (Join-Path $stagePath $markerName) $markerValue)) { throw 'STAGE_OWNERSHIP_UNVERIFIED' }
            $stageCreated = $false
        }
        if ($oldMoved) {
            if (Test-Path -LiteralPath $runtimeIdentity) { throw 'RUNTIME_RESTORE_TARGET_OCCUPIED' }
            Assert-V213NoReparseTree $oldPath 'RUNTIME_ROLLBACK_OLD'
            Move-Item -LiteralPath $oldPath -Destination $runtimeIdentity
            $oldMoved = $false
        }
        if ($null -ne $newStateBytes) {
            if (-not (Restore-V213Metadata $statePath $stateOriginal $stateExisted $newStateBytes)) { throw 'STATE_ROLLBACK_UNVERIFIED' }
        }
        if ($null -ne $newReceiptBytes) {
            if (-not (Restore-V213Metadata $receiptPath $receiptOriginal $receiptExisted $newReceiptBytes)) { throw 'RECEIPT_ROLLBACK_UNVERIFIED' }
        }
        $preimagePath = Join-Path $metadataRoot ('v213-previous-' + $transactionId + '.json')
        if (Test-Path -LiteralPath $preimagePath -PathType Leaf) { Remove-Item -LiteralPath $preimagePath -Force }
        if ($journalInitialized) { Write-V213Journal $journalPath $journalBase 'ROLLED_BACK' $failureCode }
    }
    catch { $rollbackCode = 'RECOVERY_REQUIRED' ; if ($journalInitialized) { try { Write-V213Journal $journalPath $journalBase 'RECOVERY_REQUIRED' 'RUNTIME_INSTALL_ROLLBACK_FAILED' } catch {} } }
    if ($lock) { $lock.Dispose(); $lock = $null }
    $global:LASTEXITCODE = 1
    throw "RUNTIME_INSTALL_FAILED;failure=$failureCode;rollback=$rollbackCode"
}
finally {
    if ($lock) { $lock.Dispose() }
}
