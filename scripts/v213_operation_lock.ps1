Set-StrictMode -Version Latest
if (-not (Get-Variable -Scope Script -Name V213OperationLockDepth -ErrorAction SilentlyContinue)) { $script:V213OperationLockDepth = 0 }
if (-not (Get-Variable -Scope Script -Name V213OperationLock -ErrorAction SilentlyContinue)) { $script:V213OperationLock = $null }
if (-not (Get-Variable -Scope Script -Name V213OperationLockOwner -ErrorAction SilentlyContinue)) { $script:V213OperationLockOwner = '' }
if (-not (Get-Variable -Scope Script -Name V213OperationLockName -ErrorAction SilentlyContinue)) { $script:V213OperationLockName = 'Local\InvestorIntelligence_V213_R75_OPERATION' }

function Enter-V213OperationLock {
    param([string]$Owner,[int]$TimeoutSeconds=0,[string]$MutexName='Local\InvestorIntelligence_V213_R75_OPERATION')
    if ($env:V213_TEST_MUTEX_MUST_BE_ISOLATED -eq '1' -and $MutexName -eq 'Local\InvestorIntelligence_V213_R75_OPERATION') {
        throw 'V213_TEST_MUTEX_NOT_ISOLATED'
    }
    if ($script:V213OperationLockDepth -and $script:V213OperationLock) {
        if ($script:V213OperationLockName -ne $MutexName) { throw 'V213_OPERATION_LOCK_NAME_MISMATCH' }
        $script:V213OperationLockDepth++
        return $script:V213OperationLock
    }
    $mutex = New-Object Threading.Mutex($false, $MutexName)
    $acquired = $false
    try { $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds([Math]::Max(0,$TimeoutSeconds))) }
    catch [Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { $mutex.Dispose(); throw "V213_OPERATION_LOCK_BUSY; requested_owner=$Owner" }
    $script:V213OperationLock = $mutex
    $script:V213OperationLockDepth = 1
    $script:V213OperationLockName = $MutexName
    $script:V213OperationLockOwner = $Owner
    return $mutex
}

function Exit-V213OperationLock {
    if (-not $script:V213OperationLock) { return }
    $script:V213OperationLockDepth--
    if ($script:V213OperationLockDepth -gt 0) { return }
    try { $script:V213OperationLock.ReleaseMutex() } catch {}
    try { $script:V213OperationLock.Dispose() } catch {}
    $script:V213OperationLock = $null
    $script:V213OperationLockDepth = 0
    $script:V213OperationLockName = ''
    $script:V213OperationLockOwner = ''
}
