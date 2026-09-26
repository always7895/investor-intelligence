# Test-only ACL decomposition. Never emit descriptors, principals or ACE bytes.
[CmdletBinding()]
param([switch]$ComparatorSelfTest)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

function Read-Descriptor([string]$Path) {
    $security = Get-Acl -LiteralPath $Path
    return [Security.AccessControl.RawSecurityDescriptor]::new($security.GetSecurityDescriptorBinaryForm(), 0)
}
function Equal-Acl($Left, $Right) {
    if ($null -eq $Left -or $null -eq $Right) { return ($null -eq $Left -and $null -eq $Right) }
    $a = New-Object byte[] $Left.BinaryLength
    $b = New-Object byte[] $Right.BinaryLength
    $Left.GetBinaryForm($a, 0)
    $Right.GetBinaryForm($b, 0)
    return [Convert]::ToBase64String($a) -ceq [Convert]::ToBase64String($b)
}
function Compare-Descriptors($Before, $After) {
    $aceEqual = $false
    $beforeCount = 0
    $afterCount = 0
    if ($null -ne $Before.DiscretionaryAcl) { $beforeCount = $Before.DiscretionaryAcl.Count }
    if ($null -ne $After.DiscretionaryAcl) { $afterCount = $After.DiscretionaryAcl.Count }
    if ($beforeCount -eq $afterCount) {
        $aceEqual = $true
        for ($i = 0; $i -lt $beforeCount; $i++) {
            if (-not (Equal-Acl $Before.DiscretionaryAcl[$i] $After.DiscretionaryAcl[$i])) { $aceEqual = $false }
        }
    }
    return [ordered]@{
        sddl_equal = [string]::Equals($Before.GetSddlForm([Security.AccessControl.AccessControlSections]::All), $After.GetSddlForm([Security.AccessControl.AccessControlSections]::All), [StringComparison]::Ordinal)
        owner_equal = [object]::Equals($Before.Owner, $After.Owner)
        group_equal = [object]::Equals($Before.Group, $After.Group)
        dacl_binary_equal = Equal-Acl $Before.DiscretionaryAcl $After.DiscretionaryAcl
        dacl_ace_sequence_equal = $aceEqual
        dacl_count_before = $beforeCount
        dacl_count_after = $afterCount
        control_flags_before = [int]$Before.ControlFlags
        control_flags_after = [int]$After.ControlFlags
        control_flags_xor = ([int]$Before.ControlFlags -bxor [int]$After.ControlFlags)
        sacl_not_requested = $true
    }
}

function Test-AccessMetadataPreserved($Before, $After) {
    # Access metadata only: SACL/streams/file identity require separate admission.
    if ($null -eq $Before.Owner -or $null -eq $After.Owner -or
        $null -eq $Before.Group -or $null -eq $After.Group -or
        $null -eq $Before.DiscretionaryAcl -or $null -eq $After.DiscretionaryAcl) { return $false }
    $comparison = Compare-Descriptors $Before $After
    if (-not $comparison.owner_equal -or -not $comparison.group_equal -or
        -not $comparison.dacl_binary_equal -or
        $Before.ResourceManagerControl -ne $After.ResourceManagerControl) { return $false }
    $changed = $comparison.control_flags_xor
    if ($changed -eq 0) { return $true }
    # Only addition of SE_DACL_AUTO_INHERITED; never its removal or protection changes.
    return ($changed -eq 0x0400 -and ([int]$Before.ControlFlags -band 0x0400) -eq 0)
}

if ($ComparatorSelfTest) {
    $base = 'O:BAG:SYD:(A;;FR;;;WD)(A;;FA;;;SY)'
    $inherited = 'O:BAG:SYD:AI(A;;FR;;;WD)(A;;FA;;;SY)'
    $cases = @(
        @{ name='equal'; before=$base; after=$base; expected=$true },
        @{ name='auto-inherited-added'; before=$base; after=$inherited; expected=$true },
        @{ name='auto-inherited-removed'; before=$inherited; after=$base; expected=$false },
        @{ name='owner-changed'; before=$base; after='O:SYG:SYD:(A;;FR;;;WD)(A;;FA;;;SY)'; expected=$false },
        @{ name='group-changed'; before=$base; after='O:BAG:BAD:(A;;FR;;;WD)(A;;FA;;;SY)'; expected=$false },
        @{ name='rights-changed'; before=$base; after='O:BAG:SYD:(A;;FA;;;WD)(A;;FA;;;SY)'; expected=$false },
        @{ name='deny-added'; before=$base; after='O:BAG:SYD:(D;;FW;;;WD)(A;;FR;;;WD)(A;;FA;;;SY)'; expected=$false },
        @{ name='ace-order-changed'; before=$base; after='O:BAG:SYD:(A;;FA;;;SY)(A;;FR;;;WD)'; expected=$false },
        @{ name='protection-changed'; before=$base; after='O:BAG:SYD:P(A;;FR;;;WD)(A;;FA;;;SY)'; expected=$false },
        @{ name='ace-inheritance-changed'; before=$base; after='O:BAG:SYD:(A;OI;FR;;;WD)(A;;FA;;;SY)'; expected=$false },
        @{ name='null-versus-empty'; before='O:BAG:SY'; after='O:BAG:SYD:'; expected=$false },
        @{ name='null-not-admitted'; before='O:BAG:SY'; after='O:BAG:SY'; expected=$false }
    )
    $results = @()
    foreach ($case in $cases) {
        $before = [Security.AccessControl.RawSecurityDescriptor]::new($case.before)
        $after = [Security.AccessControl.RawSecurityDescriptor]::new($case.after)
        $accepted = Test-AccessMetadataPreserved $before $after
        $results += @{ case=$case.name; accepted=$accepted; expected=$case.expected }
        if ($accepted -ne $case.expected) { throw 'ACCESS_COMPARATOR_ORACLE_FAILED' }
    }
    @{ kind='ACCESS_COMPARATOR_SELF_TEST'; results=$results; raw_security_data_retained=$false; release_qualified=$false } | ConvertTo-Json -Depth 5 -Compress
    exit 0
}

$rows = @()
foreach ($mode in @('inherited-ignore','inherited-strict','protected-strict','backup-strict')) {
    $directory = Join-Path $PSScriptRoot $mode
    if (Test-Path -LiteralPath $directory) { throw 'ACL_PROBE_CASE_EXISTS' }
    [void][IO.Directory]::CreateDirectory($directory)
    $target = Join-Path $directory 'target.bin'
    $temporary = Join-Path $directory 'temporary.bin'
    $backup = Join-Path $directory 'original-backup.bin'
    [IO.File]::WriteAllBytes($target, [byte[]]@(79,76,68))
    [IO.File]::WriteAllBytes($temporary, [byte[]]@(78,69,87))
    if ($mode -ceq 'protected-strict') {
        $acl = Get-Acl -LiteralPath $target
        $acl.SetAccessRuleProtection($true, $true)
        Set-Acl -LiteralPath $target -AclObject $acl
    }
    $before = Read-Descriptor $target
    $failure = $null
    try {
        if ($mode -ceq 'backup-strict') { [IO.File]::Replace($temporary, $target, $backup, $false) }
        else { [IO.File]::Replace($temporary, $target, [System.Management.Automation.Language.NullString]::Value, ($mode -ceq 'inherited-ignore')) }
    }
    catch {
        $exception = $_.Exception
        for ($i = 0; $i -lt 4 -and $null -ne $exception.InnerException; $i++) { $exception = $exception.InnerException }
        $failure = [ordered]@{code='REPLACE_FAILED'; hresult=[int]$exception.HResult}
    }
    $after = Read-Descriptor $target
    $backupComparison = $null
    if (Test-Path -LiteralPath $backup -PathType Leaf) { $backupComparison = Compare-Descriptors $before (Read-Descriptor $backup) }
    $rows += [ordered]@{
        mode = $mode
        failure = $failure
        new_bytes_present = ([Convert]::ToBase64String([IO.File]::ReadAllBytes($target)) -ceq 'TkVX')
        target_comparison = Compare-Descriptors $before $after
        access_metadata_preserved = Test-AccessMetadataPreserved $before $after
        backup_comparison = $backupComparison
    }
}
[ordered]@{kind='ACL_DECOMPOSITION_DIAGNOSTIC'; host_version=$PSVersionTable.PSVersion.ToString(); rows=$rows;
    raw_security_data_retained=$false; release_qualified=$false; product_code_modified=$false} | ConvertTo-Json -Depth 8 -Compress
