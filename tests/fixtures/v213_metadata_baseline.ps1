# Frozen UNACCEPTED diagnostic baseline; NEVER an installer implementation.
# Original coordinator SHA256: 48951e6d45a266faf12fb60a0ccd1b2e8180d5e42847c179f78a42812a5c41e4
function Get-V213Utf8Bytes([string]$Text) {
    $encoding = New-Object Text.UTF8Encoding($false)
    return ,$encoding.GetBytes($Text)
}

function Get-V213Sha256Bytes([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
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
        if (Test-Path -LiteralPath $Path -PathType Leaf) { [IO.File]::Replace($temporary, $Path, $null, $true) }
        else { [IO.File]::Move($temporary, $Path) }
    }
    finally { if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue } }
}

function Write-V213JsonAtomic([string]$Path, [object]$Value) {
    $text = (Get-V213CanonicalJson $Value) + "`n"
    Write-V213BytesAtomic $Path (Get-V213Utf8Bytes $text)
}

function Restore-V213Metadata([string]$Path, [byte[]]$Original, [bool]$Existed, [byte[]]$NewBytes) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -and -not $Existed) { return $true }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $current = [IO.File]::ReadAllBytes($Path)
    if ($null -eq $NewBytes -or (Get-V213Sha256Bytes $current) -ne (Get-V213Sha256Bytes $NewBytes)) { return $false }
    if ($Existed) { Write-V213BytesAtomic $Path $Original }
    else { Remove-Item -LiteralPath $Path -Force; if (Test-Path -LiteralPath $Path) { return $false } }
    return $true
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
