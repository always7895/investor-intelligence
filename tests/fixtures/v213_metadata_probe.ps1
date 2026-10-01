# Isolated diagnostics only. No coordinator body, real metadata, elevation or cleanup.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidateSet('Restore','Journal','Inheritance','SaclCapability')][string]$Mode,
      [Parameter(Mandatory=$true)][string]$BaselineSha256,
      [Parameter(Mandatory=$true)][string]$AclSha256)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
$probePhase='INPUT'
trap {
    $allowed=@('System.IO.IOException','System.ArgumentException','System.NotSupportedException','System.UnauthorizedAccessException','System.Management.Automation.MethodInvocationException','System.Management.Automation.RuntimeException')
    $chain=@(); $cursor=$_.Exception
    while ($null -ne $cursor -and $chain.Count -lt 4) {
        $type=$cursor.GetType().FullName; if ($allowed -cnotcontains $type) { $type='UNKNOWN' }
        $chain += @{exception_type=$type; hresult=[int]$cursor.HResult}; $cursor=$cursor.InnerException
    }
    @{kind='METADATA_DIAGNOSTIC_FAILURE'; phase=$probePhase; exceptions=$chain; release_qualified=$false} | ConvertTo-Json -Depth 5 -Compress
    exit 1
}

function Import-ProbeDefinitions([string]$File, [string]$Digest, [string[]]$Names) {
    if ($Digest -cnotmatch '^[0-9a-f]{64}$' -or
        (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Digest) { throw 'PROBE_INPUT_DIGEST_MISMATCH' }
    $tokens=$null; $errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile($File,[ref]$tokens,[ref]$errors)
    if (@($errors).Count -ne 0) { throw 'PROBE_INPUT_PARSE_FAILED' }
    foreach ($name in $Names) {
        $nodes=@($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name },$false))
        if ($nodes.Count -ne 1) { throw 'PROBE_DEFINITION_SET_INVALID' }
        # Definitions only; returning text does not evaluate any input body.
        $nodes[0].Extent.Text
    }
}
$baseline=Join-Path $PSScriptRoot 'baseline.ps1'
$aclInput=Join-Path $PSScriptRoot 'acl.ps1'
$names=@('Get-V213Utf8Bytes','Get-V213Sha256Bytes','Get-V213CanonicalJson','Write-V213BytesAtomic','Write-V213JsonAtomic','Restore-V213Metadata','Write-V213Journal')
foreach ($definition in @(Import-ProbeDefinitions $baseline $BaselineSha256 $names)) { . ([scriptblock]::Create($definition)) }
foreach ($definition in @(Import-ProbeDefinitions $aclInput $AclSha256 @('Read-Descriptor','Equal-Acl','Compare-Descriptors'))) { . ([scriptblock]::Create($definition)) }

function Bounded-Failure([Exception]$ErrorValue) {
    $allowed=@('System.IO.IOException','System.ArgumentException','System.UnauthorizedAccessException','System.Management.Automation.MethodInvocationException','System.Management.Automation.RuntimeException')
    $rows=@(); $cursor=$ErrorValue
    while ($null -ne $cursor -and $rows.Count -lt 4) {
        $type=$cursor.GetType().FullName
        if ($allowed -cnotcontains $type) { $type='UNKNOWN' }
        $rows += @{ exception_type=$type; hresult=[int]$cursor.HResult }
        $cursor=$cursor.InnerException
    }
    return ,$rows
}
function New-ProbeDirectory([string]$Name) {
    $path=Join-Path $PSScriptRoot $Name
    if (Test-Path -LiteralPath $path) { throw 'PROBE_CASE_EXISTS' }
    [void][IO.Directory]::CreateDirectory($path)
    return $path
}
function New-PublicFile([string]$Path, [byte[]]$Bytes) {
    $file=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $file.Write($Bytes,0,$Bytes.Length); $file.Flush($true) } finally { $file.Dispose() }
}
function Content-State([string]$Path) {
    if (Test-Path -LiteralPath $Path -PathType Container) { return 'DIRECTORY' }
    if (-not (Test-Path -LiteralPath $Path)) { return 'ABSENT' }
    $b64=[Convert]::ToBase64String([IO.File]::ReadAllBytes($Path))
    switch -CaseSensitive ($b64) { 'T0xE' { return 'ORIGINAL' }; 'TkVX' { return 'NEW' }; '' { return 'EMPTY' }; default { return 'FOREIGN' } }
}
$result=[ordered]@{ kind='METADATA_DIAGNOSTIC'; mode=$Mode; host_version=$PSVersionTable.PSVersion.ToString();
    full_coordinator_executed=$false; raw_security_data_retained=$false; release_qualified=$false }

if ($Mode -ceq 'Restore') {
    $rows=@()
    $cases=@(
        @{ name='original-present'; existed=$true; current='ORIGINAL'; original='OLD'; desired=$true },
        @{ name='original-empty'; existed=$true; current='EMPTY'; original=''; desired=$true },
        @{ name='original-absent'; existed=$false; current='ABSENT'; original=''; desired=$true },
        @{ name='foreign-directory-absent-original'; existed=$false; current='DIRECTORY'; original=''; desired=$false },
        @{ name='foreign-file'; existed=$true; current='FOREIGN'; original='OLD'; desired=$false },
        @{ name='missing-original'; existed=$true; current='ABSENT'; original='OLD'; desired=$false },
        @{ name='our-new-existing-original'; existed=$true; current='NEW'; original='OLD'; desired=$true },
        @{ name='our-new-absent-original'; existed=$false; current='NEW'; original=''; desired=$true }
    )
    foreach ($case in $cases) {
        $directory=New-ProbeDirectory $case.name; $path=Join-Path $directory 'target.bin'
        $original=[Text.Encoding]::UTF8.GetBytes($case.original); $new=[byte[]]@(78,69,87)
        New-PublicFile (Join-Path $directory 'original.bin') $original
        New-PublicFile (Join-Path $directory 'intended-new.bin') $new
        switch ($case.current) {
            'DIRECTORY' { [void][IO.Directory]::CreateDirectory($path); New-PublicFile (Join-Path $path 'sentinel.bin') ([byte[]]@(88)) }
            'ORIGINAL' { New-PublicFile $path $original }
            'EMPTY' { New-PublicFile $path ([byte[]]@()) }
            'NEW' { New-PublicFile $path $new }
            'FOREIGN' { New-PublicFile $path ([byte[]]@(88)) }
        }
        $answer=$null; $failure=$null
        try { $answer=Restore-V213Metadata $path $original $case.existed $new }
        catch { $failure=Bounded-Failure $_.Exception }
        $rows += @{ case=$case.name; accepted=$answer; failure=$failure; required_acceptance=$case.desired;
            after=Content-State $path; meets_acceptance_oracle=($null -eq $failure -and $answer -eq $case.desired) }
    }
    $result['rows']=$rows
}
elseif ($Mode -ceq 'Journal') {
    $directory=New-ProbeDirectory 'journal-sequence'; $path=Join-Path $directory 'journal.json'
    $base=@{transaction_id='SYNTHETIC_TRANSACTION'; profile='BASE'}
    $rows=@()
    foreach ($state in @('LOCKED','PREPARED','ROLLED_BACK')) {
        $failure=$null
        try { Write-V213Journal $path $base $state } catch { $failure=Bounded-Failure $_.Exception }
        $actual=([IO.File]::ReadAllText($path) | ConvertFrom-Json).state
        $rows += @{requested_state=$state; observed_state=$actual; failure=$failure}
    }
    $result['rows']=$rows
}
else {
    # Passive Win32 queries only. Never enable a privilege or use Get-Acl -Audit.
    $probePhase='NATIVE_BINDING'
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class V213MetadataProbeNative {
 [StructLayout(LayoutKind.Sequential)] public struct Info {
  public uint Attributes; public System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
  public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
 }
 [DllImport("kernel32.dll", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)]
 public static extern bool GetFileInformationByHandle(SafeFileHandle h, out Info value);
 [DllImport("advapi32.dll", CharSet=CharSet.Unicode, ExactSpelling=true)]
 public static extern uint GetNamedSecurityInfoW(string name, uint type, uint info,
  out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
 public static extern SafeFileHandle CreateFileW(string name, uint access, uint sharing, IntPtr security,
  uint disposition, uint attributes, IntPtr template);
 [DllImport("kernel32.dll")] public static extern IntPtr LocalFree(IntPtr memory);
}
'@
    function Native-StreamByte([string]$Path, [bool]$Write, [byte]$Value=0) {
        # Win32 avoids .NET Framework's legacy rejection of ADS path syntax.
        $access=if ($Write) { [uint32]1073741824 } else { [uint32]2147483648 }
        $disposition=if ($Write) { [uint32]1 } else { [uint32]3 }
        $handle=[V213MetadataProbeNative]::CreateFileW($Path,$access,0,[IntPtr]::Zero,$disposition,128,[IntPtr]::Zero)
        try {
            if ($handle.IsInvalid) { throw 'NATIVE_STREAM_OPEN_FAILED' }
            $mode=if ($Write) { [IO.FileAccess]::Write } else { [IO.FileAccess]::Read }
            $stream=[IO.FileStream]::new($handle,$mode)
            try {
                if ($Write) { $stream.WriteByte($Value); $stream.Flush($true) }
                else { $first=$stream.ReadByte(); if ($stream.ReadByte() -ne -1) { throw 'STREAM_LENGTH_INVALID' }; return $first }
            } finally { $stream.Dispose() }
        } finally { $handle.Dispose() }
    }
    function Identity([string]$Path) {
        $file=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        try {
            $info=New-Object V213MetadataProbeNative+Info
            if (-not [V213MetadataProbeNative]::GetFileInformationByHandle($file.SafeFileHandle,[ref]$info)) { throw 'FILE_ID_QUERY_FAILED' }
            return $info
        } finally { $file.Dispose() }
    }
    function Same-Identity($A,$B) { return ($A.Volume -eq $B.Volume -and $A.IndexHigh -eq $B.IndexHigh -and $A.IndexLow -eq $B.IndexLow) }
    $drive=New-Object IO.DriveInfo([IO.Path]::GetPathRoot($PSScriptRoot))
    if ($drive.DriveType -ne [IO.DriveType]::Fixed -or $drive.DriveFormat -cne 'NTFS') { throw 'PROBE_REQUIRES_LOCAL_NTFS' }
    if ($Mode -ceq 'SaclCapability') {
        $path=Join-Path (New-ProbeDirectory 'sacl-capability') 'target.bin'; New-PublicFile $path ([byte[]]@(88))
        $owner=[IntPtr]::Zero; $group=[IntPtr]::Zero; $dacl=[IntPtr]::Zero; $sacl=[IntPtr]::Zero; $sd=[IntPtr]::Zero
        try {
            $code=[V213MetadataProbeNative]::GetNamedSecurityInfoW($path,1,8,[ref]$owner,[ref]$group,[ref]$dacl,[ref]$sacl,[ref]$sd)
            $result['win32_code']=$code; $result['status']=if ($code -eq 0) { 'READABLE' } else { 'BLOCKED' }
            $result['sacl_present']=if ($code -eq 0) { $sacl -ne [IntPtr]::Zero } else { $null }
            $result['privilege_changed']=$false
        } finally { if ($sd -ne [IntPtr]::Zero) { [void][V213MetadataProbeNative]::LocalFree($sd) } }
        $result | ConvertTo-Json -Depth 8 -Compress
        if ($code -ne 0) { exit 2 }
        exit 0
    }
    $rows=@()
    foreach ($protected in @($false,$true)) {
        $name=if ($protected) { 'protected' } else { 'inherited' }
        $directory=New-ProbeDirectory $name
        $control=Join-Path $directory 'control.bin'; $target=Join-Path $directory 'target.bin'
        $temporary=Join-Path $directory 'temporary.bin'; $backup=Join-Path $directory 'backup.bin'
        New-PublicFile $control ([byte[]]@(79,76,68)); New-PublicFile $target ([byte[]]@(79,76,68)); New-PublicFile $temporary ([byte[]]@(78,69,87))
        $probePhase='CREATE_STREAMS'
        # Public synthetic stream data, exclusively on the new case's own files.
        Native-StreamByte ($target+':original-stream') $true 79; Native-StreamByte ($temporary+':replacement-stream') $true 78
        $probePhase='ACL_PREPARE'
        if ($protected) {
            foreach ($file in @($control,$target)) { $acl=Get-Acl -LiteralPath $file; $acl.SetAccessRuleProtection($true,$true); Set-Acl -LiteralPath $file -AclObject $acl }
        }
        $probePhase='IDENTITY'
        $before=Read-Descriptor $target; $oldId=Identity $target; $newId=Identity $temporary
        $probePhase='REPLACE'
        [IO.File]::Replace($temporary,$target,$backup,$false)
        $backupBefore=Read-Descriptor $backup
        $identityNew=Same-Identity $newId (Identity $target); $identityOld=Same-Identity $oldId (Identity $backup)
        # Exercise a real future parent ACL update with a well-known builtin SID.
        $probePhase='PARENT_ACL_UPDATE'
        $sid=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-559')
        $parentAcl=Get-Acl -LiteralPath $directory
        if (@($parentAcl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | Where-Object { $_.IdentityReference.Equals($sid) }).Count -ne 0) { throw 'INHERITANCE_CONTROL_ALREADY_PRESENT' }
        $rule=[Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::ReadData,
            ([Security.AccessControl.InheritanceFlags]::ObjectInherit -bor [Security.AccessControl.InheritanceFlags]::ContainerInherit),
            [Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow)
        [void]$parentAcl.AddAccessRule($rule); Set-Acl -LiteralPath $directory -AclObject $parentAcl
        $targetAfter=Read-Descriptor $target; $controlAfter=Read-Descriptor $control; $backupAfter=Read-Descriptor $backup
        $probePhase='STREAM_READBACK'
        $rows += @{ case=$name; target_uses_replacement_identity=$identityNew; backup_retains_original_identity=$identityOld;
            backup_descriptor_before_parent_update=(Compare-Descriptors $before $backupBefore).sddl_equal;
            backup_descriptor_after_parent_update=(Compare-Descriptors $before $backupAfter).sddl_equal;
            target_access_equals_unreplaced_control=(Compare-Descriptors $controlAfter $targetAfter).dacl_binary_equal;
            target_dacl_changed_by_parent=(-not (Equal-Acl $before.DiscretionaryAcl $targetAfter.DiscretionaryAcl));
            target_original_stream=((Native-StreamByte ($target+':original-stream') $false) -eq 79);
            target_replacement_stream=((Native-StreamByte ($target+':replacement-stream') $false) -eq 78);
            backup_original_stream=((Native-StreamByte ($backup+':original-stream') $false) -eq 79) }
    }
    $result['rows']=$rows
}
$result | ConvertTo-Json -Depth 8 -Compress
