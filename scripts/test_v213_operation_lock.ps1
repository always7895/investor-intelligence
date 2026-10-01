[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)}
$module=Join-Path ([IO.Path]::GetFullPath($ProjectRoot)) 'scripts\v213_operation_lock.ps1'
. $module
[void](Enter-V213OperationLock -Owner 'self-test-parent')
try {
    [void](Enter-V213OperationLock -Owner 'self-test-reentrant')
    Exit-V213OperationLock
    $escaped=$module.Replace("'","''")
    # EncodedCommand serializes first-use module progress as CLIXML on stderr.
    # Suppress only progress; preserve terminating errors and child exit checks.
    $source="`$ErrorActionPreference='Stop'; `$ProgressPreference='SilentlyContinue'; . '$escaped'; try{[void](Enter-V213OperationLock -Owner 'self-test-child' -TimeoutSeconds 0); exit 9}catch{if(`$_.Exception.Message-notmatch'V213_OPERATION_LOCK_BUSY'){exit 8};exit 0}"
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($source))
    & powershell.exe -NoProfile -NonInteractive -EncodedCommand $encoded
    if($LASTEXITCODE-ne0){throw "Cross-process operation lock self-test failed: $LASTEXITCODE"}
}
finally { Exit-V213OperationLock }
Write-Host 'V213_OPERATION_LOCK_SELF_TEST = PASS; cross_process=true; reentrant=true; production_mutation=false' -ForegroundColor Green
