# F02C SOURCE ONLY / IMPLEMENTED_UNVERIFIED. NEVER invokes RunAs or enrollment.
# Entry prerequisite: a trusted privileged operator independently verifies this
# script, stages it and the approved package in the fixed protected staging tree,
# and provisions HKLM64 Approval. This script/payload cannot approve itself.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion -lt [version]'7.4') { throw 'TRUSTED_POWERSHELL_74_REQUIRED' }
$authorityPath = 'SOFTWARE\InvestorIntelligence\GuidanceProtected'
$staging = 'C:\Program Files\InvestorIntelligence\GuidanceInstaller'
$codeBase = 'C:\Program Files\InvestorIntelligence\GuidanceProtected\releases'
$dataBase = 'C:\ProgramData\InvestorIntelligenceGuidance'
$trusted = @('S-1-5-18', 'S-1-5-32-544')
$owners = $trusted + @('S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'PRIVILEGED_TRUSTED_ENTRY_REQUIRED' }
# An elevated, same-user-writable launcher cannot silently route here.
if ($PSCommandPath -cne "$staging\install_revenue_guidance_protected.ps1") { throw 'PRIVILEGED_TRUSTED_ENTRY_REQUIRED' }
# Declarations are installer SOURCE, not a currently executed compiler/probe.
# Synchronous origin queries, distinct from the bounded NT storage I/O domain.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class GuidanceProtectedOrigin {
    [StructLayout(LayoutKind.Sequential)] struct Standard {
        public long AllocationSize, EndOfFile;
        public uint NumberOfLinks;
        public byte DeletePending, Directory;
    }
    [StructLayout(LayoutKind.Sequential)] struct Tags { public uint Attributes, ReparseTag; }
    [StructLayout(LayoutKind.Sequential)] struct SecurityAttributes {
        public int Length; public IntPtr Descriptor; public int InheritHandle;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool CreateDirectoryW(string path, ref SecurityAttributes security);
    public static void CreateDirectoryNew(string path, byte[] descriptor) {
        var pinned = GCHandle.Alloc(descriptor, GCHandleType.Pinned);
        try {
            var sa = new SecurityAttributes { Length = Marshal.SizeOf<SecurityAttributes>(),
                Descriptor = pinned.AddrOfPinnedObject(), InheritHandle = 0 };
            if (!CreateDirectoryW(path, ref sa))
                throw new InvalidOperationException("NEW_PROTECTED_DIRECTORY_UNCONFIRMED");
        } finally { pinned.Free(); }
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security,
                                            uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", EntryPoint="GetFileInformationByHandleEx", SetLastError=true)]
    static extern bool GetStandard(SafeFileHandle h, int cls, out Standard value, uint length);
    [DllImport("kernel32.dll", EntryPoint="GetFileInformationByHandleEx", SetLastError=true)]
    static extern bool GetTags(SafeFileHandle h, int cls, out Tags value, uint length);
    public static void AssertObject(SafeFileHandle h, bool directory) {
        Standard s; Tags t;
        if (h.IsInvalid || !GetStandard(h, 1, out s, 24) || !GetTags(h, 9, out t, 8) ||
            s.DeletePending != 0 || (s.Directory != 0) != directory || t.ReparseTag != 0 ||
            (t.Attributes & 0x400) != 0 || (!directory && s.NumberOfLinks != 1))
            throw new InvalidOperationException("PROTECTED_ORIGIN_UNAVAILABLE");
    }
    public static SafeFileHandle HoldDirectory(string path) {
        var h = CreateFileW(path, 0x80020000, 3, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero);
        try { AssertObject(h, true); return h; } catch { h.Dispose(); throw; }
    }
}
'@
$heldDirectories = [Collections.Generic.List[object]]::new()

function Assert-ProtectedPath([string]$Path, [bool]$Ancestor = $false) {
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'PROTECTED_ORIGIN_UNAVAILABLE' }
    $acl = Get-Acl -LiteralPath $Path
    $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    $allowedOwners = if ($Ancestor) { $owners } else { $trusted }
    if ($owner -notin $allowedOwners) { throw 'PROTECTED_ORIGIN_UNAVAILABLE' }
    $danger = if ($Ancestor) { 0xD0150 } else { 0xD0156 }
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) { continue }
        if (($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) -ne 0) { continue }
        if ($rule.IdentityReference.Value -notin $allowedOwners -and (([int64]$rule.FileSystemRights -band $danger) -ne 0)) {
            throw 'PROTECTED_ORIGIN_UNAVAILABLE'
        }
    }
    if ($item.PSIsContainer) {
        # Actual held ancestry denies delete/rename while the operation composes.
        $heldDirectories.Add([GuidanceProtectedOrigin]::HoldDirectory($item.FullName))
    } else {
        $file = [IO.File]::Open($item.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try { [GuidanceProtectedOrigin]::AssertObject($file.SafeFileHandle, $false) } finally { $file.Dispose() }
    }
}
function Assert-Ancestry([string]$Path) {
    $p = [IO.DirectoryInfo]::new($Path)
    while ($null -ne $p) {
        Assert-ProtectedPath $p.FullName $true
        $p = $p.Parent
    }
}
function New-DirectorySecurity([string]$RuntimeSid) {
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in $trusted) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($sid), 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    }
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        [Security.Principal.SecurityIdentifier]::new($RuntimeSid), 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    return $acl
}
function New-FileSecurity([string]$RuntimeSid) {
    $acl = [Security.AccessControl.FileSecurity]::new()
    $acl.SetSecurityDescriptorSddlForm("O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;$RuntimeSid)")
    return $acl
}
function New-ProtectedDirectory([string]$Path, [string]$RuntimeSid) {
    if (Test-Path -LiteralPath $Path) { Assert-ProtectedPath $Path; return }
    $parent = [IO.Path]::GetDirectoryName($Path)
    if (-not (Test-Path -LiteralPath $parent)) { New-ProtectedDirectory $parent $RuntimeSid }
    Assert-Ancestry $parent
    # Atomically create with Administrators owner and exact DACL. No creator-owner
    # WRITE_DAC window for the medium same-user runtime token.
    $security = New-DirectorySecurity $RuntimeSid
    [GuidanceProtectedOrigin]::CreateDirectoryNew($Path, $security.GetSecurityDescriptorBinaryForm())
    Assert-ProtectedPath $Path
}
function Assert-RegistryProtection($Key, [bool]$Ancestor = $false) {
    $acl = [Microsoft.Win32.RegistryAclExtensions]::GetAccessControl($Key)
    $allowedOwners = if ($Ancestor) { $owners } else { $trusted }
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $allowedOwners) { throw 'INDEPENDENT_APPROVAL_UNAVAILABLE' }
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
            ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) -eq 0 -and
            $rule.IdentityReference.Value -notin $allowedOwners -and
            (([int64]$rule.RegistryRights -band 0xD0026) -ne 0)) { throw 'INDEPENDENT_APPROVAL_UNAVAILABLE' }
    }
}
$hive = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$keys = [Collections.Generic.List[object]]::new()
$streams = [Collections.Generic.List[object]]::new()
$installed = $false
$releaseRoot = $null
try {
    foreach ($path in @('SOFTWARE', 'SOFTWARE\InvestorIntelligence', $authorityPath)) {
        $key = $hive.OpenSubKey($path, $false)
        if ($null -eq $key) { throw 'INDEPENDENT_APPROVAL_UNAVAILABLE' }
        $keys.Add($key)
        Assert-RegistryProtection $key ($path -ne $authorityPath)
    }
    $key = $keys[$keys.Count - 1]
    if ($key.GetValueKind('Approval') -ne [Microsoft.Win32.RegistryValueKind]::String) { throw 'INDEPENDENT_APPROVAL_UNAVAILABLE' }
    $policyText = [string]$key.GetValue('Approval')
    if ([Text.Encoding]::UTF8.GetByteCount($policyText) -gt 2097152) { throw 'INDEPENDENT_APPROVAL_UNAVAILABLE' }
    # Use JsonDocument (trusted PowerShell 7.4+) to reject duplicates before conversion.
    function Assert-UniqueJson($Element) {
        if ($Element.ValueKind -eq [Text.Json.JsonValueKind]::Object) {
            $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
            foreach ($prop in $Element.EnumerateObject()) {
                if (-not $seen.Add($prop.Name)) { throw 'INDEPENDENT_APPROVAL_UNAVAILABLE' }
                Assert-UniqueJson $prop.Value
            }
        } elseif ($Element.ValueKind -eq [Text.Json.JsonValueKind]::Array) {
            foreach ($child in $Element.EnumerateArray()) { Assert-UniqueJson $child }
        }
    }
    $json = [Text.Json.JsonDocument]::Parse($policyText)
    try { Assert-UniqueJson $json.RootElement } finally { $json.Dispose() }
    $policy = ConvertFrom-Json -InputObject $policyText -AsHashtable
    if (($policy.Keys | Sort-Object) -join ',' -cne 'files,release_id,runtime_sid,schema' -or
        $policy.schema -cne 'guidance-protected-approval-v1' -or $policy.release_id -cnotmatch '^[0-9a-f]{64}$' -or
        $policy.runtime_sid -cnotmatch '^S-1-5-21-(\d+-){3}\d+$' -or $policy.files.Count -lt 18 -or $policy.files.Count -gt 4096) {
        throw 'INDEPENDENT_APPROVAL_UNAVAILABLE'
    }
    $required = @('Python/python.exe', 'Python/python312.dll',
        'scripts/revenue_guidance_bootstrap.py', 'scripts/revenue_guidance_provisioner.py',
        'scripts/revenue_guidance_enroll.py', 'scripts/revenue_guidance_storage.py',
        'scripts/revenue_guidance_windows.py', 'scripts/revenue_guidance_revision.py',
        'scripts/revenue_guidance_overlay.py', 'scripts/revenue_guidance.py',
        'scripts/revenue_guidance_auto_verify.py', 'scripts/revenue_guidance_release_check.py',
        'scripts/revenue_guidance_autoupdate.py', 'scripts/issuer_ir_feeds.py',
        'scripts/sec_contact_headers.py', 'scripts/install_revenue_guidance_protected.ps1',
        'config/revenue-guidance-v1.json', 'config/revenue-guidance-approval-v1.json',
        'config/revenue-guidance-extraction-profiles-v1.json', 'config/system-bottleneck-explosion-v1.json',
        'scripts/revenue_guidance_host.py', 'scripts/revenue_guidance_backend.psm1',
        'scripts/revenue_guidance_machine.py',
        'scripts/revenue_guidance_provider.psm1', 'scripts/revenue_guidance_orchestration.psm1',
        'scripts/bottleneck_top20_v3.py', 'scripts/publish_sealed_snapshot.py',
        'scripts/bottleneck_ranking.py', 'scripts/bottleneck_claim_admission.py',
        'scripts/company_claim_admission_bridge.py', 'scripts/multilineage_claim_bundle.py',
        'scripts/source_registry.py', 'scripts/adapters/__init__.py', 'scripts/adapters/base.py',
        'scripts/adapters/sec_edgar.py', 'scripts/adapters/world_bank.py', 'scripts/adapters/ecb_fx_reference.py',
        'scripts/build_v213_macro_industry_research.py',
        'scripts/build_zh_names.py', 'scripts/company_deep_report.py', 'scripts/thesis_phase.py',
        'scripts/listing_lineage.py', 'scripts/order_forecast.py', 'scripts/order_claims.py',
        'scripts/revenue_consensus_quarterly.py', 'scripts/revenue_guidance_wire.py',
        'scripts/top20_carry_forward.py', 'scripts/v213_evidence_policy.py',
        'scripts/official_quarterly_revenue.py', 'config/bottleneck-layers-v3.json',
        'config/listing-lineage-v1.json', 'config/official-quarterly-revenue-v1.json',
        'config/company-zh-names-v1.json', 'config/order-claims-v2.json',
        'config/korea-ir-orders-v1.json', 'config/korea-ir-fundamentals-v1.json')
    # PublicInputs, when used by the explicit host, is independently operator-
    # seeded protected HKLM64 guidance-public-inputs-v1 {root}; not package self-
    # approval, interpreter launch, collector activation or a writable code root.
    foreach ($name in $required) {
        if (-not $policy.files.ContainsKey($name)) { throw 'INDEPENDENT_APPROVAL_MISMATCH' }
    }
    if ($null -ne $key.GetValue('Enrollment') -or $null -ne $key.GetValue('Installation')) { throw 'EXISTING_INSTALLATION_NOT_REPAIRED' }
    Assert-Ancestry $staging
    Assert-ProtectedPath $PSCommandPath
    $approvedScript = $policy.files['scripts/install_revenue_guidance_protected.ps1']
    if ((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $approvedScript) {
        throw 'INDEPENDENT_APPROVAL_MISMATCH'
    }
    $package = "$staging\package"
    Assert-Ancestry $package
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($name in $policy.files.Keys) {
        if ($name -cmatch '(^/|\\|:|(^|/)\.{1,2}(/|$)|\.pth$|\.pyc$)' -or $name.Length -gt 240 -or
            $policy.files[$name] -cnotmatch '^[0-9a-f]{64}$' -or -not $seen.Add($name)) { throw 'INDEPENDENT_APPROVAL_MISMATCH' }
    }
    $inventory = [Collections.Generic.List[object]]::new()
    $directories = [Collections.Generic.Stack[string]]::new()
    $directories.Push($package)
    while ($directories.Count -gt 0) {
        $directory = $directories.Pop()
        Assert-ProtectedPath $directory # reject/hold BEFORE any descent, never follow a junction
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
            Assert-ProtectedPath $item.FullName
            $inventory.Add($item)
            if ($inventory.Count -gt 8192) { throw 'INSTALL_CAPACITY_UNAVAILABLE' }
            if ($item.PSIsContainer) { $directories.Push($item.FullName) }
        }
    }
    $payload = @{}
    $total = 0L
    foreach ($item in $inventory) {
        Assert-ProtectedPath $item.FullName
        if ($item.PSIsContainer) { continue }
        $name = [IO.Path]::GetRelativePath($package, $item.FullName).Replace('\', '/')
        if (-not $policy.files.ContainsKey($name)) { throw 'INDEPENDENT_APPROVAL_MISMATCH' }
        $stream = [IO.File]::Open($item.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $streams.Add($stream) # hold source against rename/write while copying
        [GuidanceProtectedOrigin]::AssertObject($stream.SafeFileHandle, $false)
        $total += $stream.Length
        if ($stream.Length -gt 268435456 -or $total -gt 536870912) { throw 'INSTALL_CAPACITY_UNAVAILABLE' }
        $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant()
        if ($digest -cne $policy.files[$name]) { throw 'INDEPENDENT_APPROVAL_MISMATCH' }
        $stream.Position = 0
        $payload[$name] = $stream
    }
    if ($payload.Count -ne $policy.files.Count) { throw 'INDEPENDENT_APPROVAL_MISMATCH' }
    New-ProtectedDirectory $codeBase $policy.runtime_sid
    New-ProtectedDirectory $dataBase $policy.runtime_sid
    $releaseRoot = "$codeBase\$($policy.release_id)"
    if (Test-Path -LiteralPath $releaseRoot) { throw 'EXISTING_RELEASE_NOT_REPAIRED' }
    $security = New-DirectorySecurity $policy.runtime_sid
    [GuidanceProtectedOrigin]::CreateDirectoryNew($releaseRoot, $security.GetSecurityDescriptorBinaryForm())
    Assert-ProtectedPath $releaseRoot
    foreach ($name in $payload.Keys) {
        $target = Join-Path $releaseRoot $name
        New-ProtectedDirectory ([IO.Path]::GetDirectoryName($target)) $policy.runtime_sid
        $out = [IO.FileSystemAclExtensions]::Create([IO.FileInfo]::new($target), [IO.FileMode]::CreateNew,
            [Security.AccessControl.FileSystemRights]::Write, [IO.FileShare]::None, 65536,
            [IO.FileOptions]::WriteThrough, (New-FileSecurity $policy.runtime_sid))
        try { $payload[$name].CopyTo($out); $out.Flush($true) } finally { $out.Dispose() }
        Assert-ProtectedPath $target
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -cne $policy.files[$name]) {
            throw 'INSTALL_READBACK_UNCONFIRMED'
        }
    }
    # No interpreter/installer/enrollment launch, registry principal creation,
    # credentials, signing keys or paid/runtime service configuration.
    $writeKey = $hive.OpenSubKey($authorityPath, $true)
    $keys.Add($writeKey)
    Assert-RegistryProtection $writeKey
    if ([string]$writeKey.GetValue('Approval') -cne $policyText -or $null -ne $writeKey.GetValue('Installation')) {
        throw 'INDEPENDENT_APPROVAL_CHANGED'
    }
    $receipt = @{ schema = 'guidance-protected-install-v1'; release_id = $policy.release_id } | ConvertTo-Json -Compress
    $writeKey.SetValue('Installation', $receipt, [Microsoft.Win32.RegistryValueKind]::String)
    $writeKey.Flush()
    if ([string]$writeKey.GetValue('Installation') -cne $receipt) { throw 'INSTALL_READBACK_UNCONFIRMED' }
    $installed = $true
    Write-Output '{"status":"PROTECTED_INSTALLED_NOT_ENROLLED","model_complete":false}'
} catch {
    # Keep owned incomplete resources for explicit rollback review; never recursive
    # deletion of guessed paths, nor a successful installation/enrollment receipt.
    throw 'PROTECTED_INSTALL_UNAVAILABLE_RETAINED_FOR_OPERATOR_REVIEW'
} finally {
    foreach ($stream in $streams) { $stream.Dispose() }
    foreach ($held in $heldDirectories) { $held.Dispose() }
    foreach ($key in $keys) { $key.Dispose() }
    $hive.Dispose()
    $identity.Dispose()
}
