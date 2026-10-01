# Test-only evidence serializer and isolated probe of one exact source helper.
[CmdletBinding()]
param([switch]$EvidenceSelfTest, [string]$Coordinator = '', [string]$SourceSha256 = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

function Get-BoundedFailure([Exception]$Exception) {
    $allowed = @('System.Exception','System.IO.IOException','System.ArgumentException',
        'System.ArgumentNullException','System.UnauthorizedAccessException',
        'System.Management.Automation.MethodInvocationException','System.Management.Automation.RuntimeException')
    $chain = New-Object 'System.Collections.Generic.List[object]'
    $cursor = $Exception
    while ($null -ne $cursor -and $chain.Count -lt 4) {
        $name = $cursor.GetType().FullName
        if ($allowed -cnotcontains $name) { $name = 'UNKNOWN' }
        [void]$chain.Add([ordered]@{ exception_type = $name; hresult = [int]$cursor.HResult })
        $cursor = $cursor.InnerException
    }
    return [ordered]@{ code = 'OPERATION_FAILED'; exceptions = @($chain.ToArray()) }
}

if ($EvidenceSelfTest) {
    $primary = $null
    $journal = $null
    try { throw [IO.IOException]::new('SYNTHETIC_PRIVATE_PRIMARY_MUST_NOT_APPEAR') }
    catch { $primary = Get-BoundedFailure $_.Exception }
    try { throw [UnauthorizedAccessException]::new('SYNTHETIC_PRIVATE_JOURNAL_MUST_NOT_APPEAR') }
    catch { $journal = Get-BoundedFailure $_.Exception }
    [ordered]@{ phase = 'EVIDENCE_SELF_TEST'; primary_failure = $primary; rollback = 'NOT_ATTEMPTED';
        journal_write_failure = $journal; release_qualified = $false } | ConvertTo-Json -Depth 8 -Compress
    exit 0
}

# The Python caller supplies a new, verified case and a byte-exact input copy.
if ($Coordinator -cne (Join-Path $PSScriptRoot 'coordinator.ps1') -or
    $SourceSha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'IO_PROBE_INPUT_REJECTED' }
if ((Get-FileHash -LiteralPath $Coordinator -Algorithm SHA256).Hash.ToLowerInvariant() -cne $SourceSha256) {
    throw 'IO_PROBE_SOURCE_MISMATCH'
}
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Coordinator, [ref]$tokens, [ref]$parseErrors)
if (@($parseErrors).Count -ne 0) { throw 'IO_PROBE_SOURCE_PARSE_FAILED' }
$functions = @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Write-V213BytesAtomic'
}, $false))
if ($functions.Count -ne 1) { throw 'IO_PROBE_FUNCTION_SET_INVALID' }
# Only this function definition is loaded; never dot-source the coordinator.
. ([scriptblock]::Create($functions[0].Extent.Text))

$cases = @('new','overwrite','empty','utf8','directory','locked','before_fault','after_fault')
$rows = New-Object 'System.Collections.Generic.List[object]'
foreach ($name in $cases) {
    $directory = Join-Path $PSScriptRoot ('case-' + $name)
    if (Test-Path -LiteralPath $directory) { throw 'IO_PROBE_CASE_EXISTS' }
    [void][IO.Directory]::CreateDirectory($directory)
    $target = Join-Path $directory 'target.bin'
    [byte[]]$oldBytes = @(79,76,68)
    [byte[]]$newBytes = @(78,69,87)
    if ($name -ceq 'empty') { $newBytes = [byte[]]@() }
    if ($name -ceq 'utf8') { $newBytes = [Text.Encoding]::UTF8.GetBytes([string][char]0x4e2d + [char]0x6587) }
    [IO.File]::WriteAllBytes((Join-Path $directory 'intended-new.bin'), $newBytes)
    if (@('overwrite','locked') -ccontains $name) {
        [IO.File]::WriteAllBytes($target, $oldBytes)
        [IO.File]::WriteAllBytes((Join-Path $directory 'original.bin'), $oldBytes)
    }
    if ($name -ceq 'directory') { [void][IO.Directory]::CreateDirectory($target) }
    $hold = $null
    $failure = $null
    $phase = 'WRITE'
    try {
        if ($name -ceq 'locked') { $hold = [IO.File]::Open($target, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        if ($name -ceq 'before_fault') { $phase = 'BEFORE_WRITE'; throw [IO.IOException]::new('SYNTHETIC_BEFORE_WRITE') }
        Write-V213BytesAtomic $target $newBytes
        if ($name -ceq 'after_fault') { $phase = 'AFTER_WRITE'; throw [IO.IOException]::new('SYNTHETIC_AFTER_WRITE') }
    }
    catch { $failure = Get-BoundedFailure $_.Exception }
    finally { if ($null -ne $hold) { $hold.Dispose() } }
    $present = Test-Path -LiteralPath $target -PathType Leaf
    $isDirectory = Test-Path -LiteralPath $target -PathType Container
    $matchesNew = $false
    $matchesOld = $false
    $digest = $null
    if ($present) {
        $actual = [IO.File]::ReadAllBytes($target)
        $matchesNew = [Convert]::ToBase64String($actual) -ceq [Convert]::ToBase64String($newBytes)
        $matchesOld = [Convert]::ToBase64String($actual) -ceq [Convert]::ToBase64String($oldBytes)
        $digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    [void]$rows.Add([ordered]@{ case = $name; phase = $phase; operation_succeeded = ($null -eq $failure);
        primary_failure = $failure; rollback = 'NOT_ATTEMPTED'; journal_write = 'NOT_ATTEMPTED';
        file_present = $present; directory_present = $isDirectory; matches_new = $matchesNew;
        matches_old = $matchesOld; target_sha256 = $digest })
}
[ordered]@{ kind = 'SOURCE_HELPER_DIAGNOSTIC'; source_sha256 = $SourceSha256;
    host_version = $PSVersionTable.PSVersion.ToString(); rows = @($rows.ToArray());
    full_coordinator_executed = $false; release_qualified = $false; crash_recovery_tested = $false;
    acl_preservation_tested = $false } | ConvertTo-Json -Depth 9 -Compress
