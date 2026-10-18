# Restore the runtime retained by the most recent finalized install (v213_runtime_install_coordinator.ps1
# -RestorePrevious <transaction>). Dot-sourced by the coordinator, which defines the V213 helper functions.
#
# Preconditions: the install journal is FINALIZED for exactly this transaction (only the newest install can be undone),
# <runtime>.old.<transaction> exists, the preimage file written at PREPARED exists, and the current runtime still
# matches its own receipt and manifest. The current runtime is moved aside to <runtime>.replaced.<transaction> (never
# deleted), the old root is moved back, state and receipt are restored from the preimages, and ownership is
# re-attested against the restored receipt. Any failure after the first move reverses the swap.

function Invoke-V213RestorePrevious([string]$RuntimeRoot, [string]$TransactionId) {
    if ($TransactionId -notmatch '^[0-9a-f]{32}$') { throw 'RESTORE_TRANSACTION_INVALID' }
    $runtimeIdentity = Resolve-V213DirectoryIdentity $RuntimeRoot 'RUNTIME_ROOT'
    $localAppData = Resolve-V213DirectoryIdentity $env:LOCALAPPDATA 'LOCALAPPDATA'
    $metadataRoot = Join-Path $localAppData 'InvestorIntelligence'
    $journalPath = Join-Path $metadataRoot 'v213-runtime-install.journal.json'
    $receiptPath = Join-Path $metadataRoot 'v213-runtime-install-receipt.json'
    $statePath = Join-Path $metadataRoot 'v213-runtime-state.json'
    $preimagePath = Join-Path $metadataRoot ('v213-previous-' + $TransactionId + '.json')
    foreach ($metadataPath in @($journalPath, $receiptPath, $statePath, $preimagePath)) { Assert-V213MetadataFilePath $metadataPath }
    $runtimeLeaf = Split-Path -Leaf $runtimeIdentity
    $runtimeParent = Split-Path -Parent $runtimeIdentity
    $oldPath = Join-Path $runtimeParent ($runtimeLeaf + '.old.' + $TransactionId)
    $replacedPath = Join-Path $runtimeParent ($runtimeLeaf + '.replaced.' + $TransactionId)
    $lockPath = Join-Path ([IO.Path]::GetTempPath()) 'InvestorIntelligence-v213-runtime-install.lock'
    $lock = $null
    $swapped = $false
    $restored = $false
    $currentState = $null
    $currentReceipt = $null
    $journalBase = $null
    try {
        try { $lock = New-Object IO.FileStream($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch { throw 'RUNTIME_INSTALL_LOCK_BUSY' }
        if (-not (Test-Path -LiteralPath $journalPath -PathType Leaf)) { throw 'RESTORE_JOURNAL_MISSING' }
        $journal = Get-Content -LiteralPath $journalPath -Raw -Encoding utf8 | ConvertFrom-Json
        if ([string]$journal.state -ne 'FINALIZED' -or [string]$journal.transaction_id -ne $TransactionId -or
            [string]$journal.runtime_root -ne $runtimeIdentity) { throw 'RESTORE_NOT_LATEST_TRANSACTION' }
        if (-not (Test-Path -LiteralPath $oldPath -PathType Container)) { throw 'RESTORE_OLD_ROOT_MISSING' }
        if (Test-Path -LiteralPath $replacedPath) { throw 'RESTORE_REPLACED_PATH_OCCUPIED' }
        if (-not (Test-Path -LiteralPath $preimagePath -PathType Leaf)) { throw 'RESTORE_PREIMAGE_MISSING' }
        $preimage = Get-Content -LiteralPath $preimagePath -Raw -Encoding utf8 | ConvertFrom-Json
        if ([string]$preimage.transaction_id -ne $TransactionId -or [string]$preimage.old_root -ne $oldPath -or
            -not [bool]$preimage.receipt_existed) { throw 'RESTORE_PREIMAGE_INVALID' }
        $stateBytes = if ([bool]$preimage.state_existed) { [Convert]::FromBase64String([string]$preimage.state_base64) } else { $null }
        $receiptBytes = [Convert]::FromBase64String([string]$preimage.receipt_base64)
        [void](Assert-V213OwnedDestination $runtimeIdentity $metadataRoot $runtimeIdentity)
        Assert-V213NoReparseTree $oldPath 'RESTORE_OLD_ROOT'
        $journalBase = [ordered]@{}
        foreach ($property in $journal.PSObject.Properties) { if ($property.Name -notin @('schema_version', 'state', 'failure_code')) { $journalBase[$property.Name] = $property.Value } }
        $journalBase['restore_replaced_root'] = $replacedPath
        Write-V213Journal $journalPath $journalBase 'RESTORE_INTENT'
        $currentState = Read-V213Bytes $statePath
        $currentReceipt = Read-V213Bytes $receiptPath
        Move-Item -LiteralPath $runtimeIdentity -Destination $replacedPath
        $swapped = $true
        Move-Item -LiteralPath $oldPath -Destination $runtimeIdentity
        $restored = $true
        Write-V213BytesAtomic $receiptPath $receiptBytes
        if ($null -ne $stateBytes) { Write-V213BytesAtomic $statePath $stateBytes }
        elseif (Test-Path -LiteralPath $statePath -PathType Leaf) { Remove-Item -LiteralPath $statePath -Force }
        [void](Assert-V213OwnedDestination $runtimeIdentity $metadataRoot $runtimeIdentity)
        Write-V213Journal $journalPath $journalBase 'RESTORED_PREVIOUS'
        Remove-Item -LiteralPath $preimagePath -Force
        $global:LASTEXITCODE = 0
        Write-Host "V213_RUNTIME_RESTORE = PASS; transaction=$TransactionId; replaced_root_retained=$replacedPath" -ForegroundColor Green
    }
    catch {
        $failure = [regex]::Match([string]$_.Exception.Message, '^[A-Z][A-Z0-9_]+')
        $code = if ($failure.Success) { $failure.Value } else { 'RESTORE_UNEXPECTED' }
        $reverse = 'PASS'
        try {
            if ($restored) { Move-Item -LiteralPath $runtimeIdentity -Destination $oldPath; $restored = $false }
            if ($swapped) { Move-Item -LiteralPath $replacedPath -Destination $runtimeIdentity; $swapped = $false }
            if ($null -ne $currentReceipt) { Write-V213BytesAtomic $receiptPath $currentReceipt }
            if ($null -ne $currentState) { Write-V213BytesAtomic $statePath $currentState }
            if ($null -ne $journalBase) { Write-V213Journal $journalPath $journalBase 'FINALIZED' }
        }
        catch { $reverse = 'RECOVERY_REQUIRED' }
        if ($lock) { $lock.Dispose(); $lock = $null }
        $global:LASTEXITCODE = 1
        throw "RUNTIME_RESTORE_FAILED;failure=$code;reverse=$reverse"
    }
    finally {
        if ($lock) { $lock.Dispose() }
    }
}
