# Explicit opt-in, child-only SACL read probe. Never a production helper.
[CmdletBinding()]
param([switch]$AllowAssignedSeSecurityPrivilege, [switch]$SelfTest,
      [Parameter(Mandatory=$true)][string]$CaseRoot,
      [Parameter(Mandatory=$true)][string]$SourceSha256)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
function Reject-Probe([string]$Code) {
    @{kind='SACL_PRIVILEGE_FIXTURE';status=$Code;native_privilege_api_invoked=$false;release_qualified=$false} | ConvertTo-Json -Compress
    exit 2
}
if (-not $SelfTest -and -not $AllowAssignedSeSecurityPrivilege) { Reject-Probe 'REJECTED_AUTHORIZATION_REQUIRED' }
if ($SelfTest -and $AllowAssignedSeSecurityPrivilege) { Reject-Probe 'REJECTED_CONFLICTING_MODES' }
if (-not [string]::Equals($CaseRoot,$PSScriptRoot,[StringComparison]::Ordinal) -or
    (Split-Path -Leaf $CaseRoot) -cnotmatch '^sacl-read-[0-9a-f]{32}$') { Reject-Probe 'REJECTED_FIXTURE_SCOPE' }
foreach ($name in @('TEMP','TMP','LOCALAPPDATA','APPDATA','USERPROFILE','HOME')) {
    $value=[Environment]::GetEnvironmentVariable($name)
    if (-not $value -or -not ([IO.Path]::GetFullPath($value)).StartsWith($CaseRoot+'\',[StringComparison]::OrdinalIgnoreCase)) {
        Reject-Probe 'REJECTED_CHILD_ENVIRONMENT'
    }
}
$source=Join-Path $PSScriptRoot 'sacl_probe.cs'
if ($SourceSha256 -cnotmatch '^[0-9a-f]{64}$' -or
    (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -cne $SourceSha256) { Reject-Probe 'REJECTED_SOURCE_DIGEST' }
try {
    Add-Type -Path $source
    if ($SelfTest) {
        $cases=[V213SaclPrivilegeProbe]::SelfTest()
        @{kind='SACL_PRIVILEGE_SELF_TEST';cases=$cases;native_privilege_api_invoked=$false;release_qualified=$false} | ConvertTo-Json -Depth 4 -Compress
        exit 0
    }
    $result=[V213SaclPrivilegeProbe]::ReadNewFixture($CaseRoot)
    @{kind='SACL_PRIVILEGE_FIXTURE';host_version=$PSVersionTable.PSVersion.ToString();result=$result} | ConvertTo-Json -Depth 5 -Compress
    if ($result.status -ceq 'PASS') { exit 0 }
    if ($result.status -ceq 'BLOCKED_PRIVILEGE_NOT_ASSIGNED' -and $result.privileges_restored -eq $true) { exit 2 }
    exit 1
}
catch {
    # No ErrorRecord, descriptor, account, handle, privilege list or raw message.
    @{kind='SACL_PRIVILEGE_FIXTURE';status='PROBE_ERROR';hresult=[int]$_.Exception.HResult;release_qualified=$false} | ConvertTo-Json -Compress
    exit 1
}
