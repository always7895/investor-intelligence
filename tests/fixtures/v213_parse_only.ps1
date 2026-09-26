# Test-only driver. Never invoke, dot-source or evaluate an input script.
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$InputManifest)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

function Reject-ParseInput([string]$Code) {
    Write-Output ('PURE_PARSE_REJECT;CODE=' + $Code + ';MAIN_EXECUTED=false')
    exit 1
}

try {
    $manifest = Get-Content -LiteralPath $InputManifest -Raw -Encoding utf8 | ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or
        $manifest.main_execution_allowed -isnot [bool] -or
        $manifest.main_execution_allowed -ne $false) { Reject-ParseInput 'INPUT_INVALID' }
    $items = @($manifest.files)
    $expected = @('control','caller:BASE','caller:SOURCE_DIVERSE','caller:SOURCE_DIVERSE_V2','caller:SERENITY_LATEST','coordinator')
    if ($items.Count -ne $expected.Count) { Reject-ParseInput 'ROLE_SET_INVALID' }
    $roles = @($items | ForEach-Object { [string]$_.role } | Sort-Object)
    $sortedExpected = @($expected | Sort-Object)
    # PowerShell -cne with an array on the left is a filter, not array equality.
    for ($i = 0; $i -lt $expected.Count; $i++) {
        if (-not [string]::Equals($roles[$i], $sortedExpected[$i], [StringComparison]::Ordinal)) {
            Reject-ParseInput 'ROLE_SET_INVALID'
        }
    }
    $inputRoot = Join-Path $PSScriptRoot 'inputs'
    foreach ($item in $items) {
        if ($item.path -isnot [string] -or $item.path -notmatch '^[A-Za-z]:[\\/]' -or
            $item.sha256 -isnot [string] -or $item.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            ($item.bytes -isnot [int] -and $item.bytes -isnot [long])) { Reject-ParseInput 'INPUT_INVALID' }
        $full = [IO.Path]::GetFullPath($item.path)
        if (-not $full.StartsWith($inputRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            Reject-ParseInput 'INPUT_SCOPE_INVALID'
        }
        $file = Get-Item -LiteralPath $full -Force
        if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Reject-ParseInput 'INPUT_SCOPE_INVALID'
        }
        $ancestor = $file.Directory
        while ($null -ne $ancestor) {
            if (($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { Reject-ParseInput 'INPUT_SCOPE_INVALID' }
            $ancestor = $ancestor.Parent
        }
        if ($file.Length -gt 524288 -or $file.Length -ne $item.bytes) { Reject-ParseInput 'INPUT_DIGEST_MISMATCH' }
        $hash = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -cne $item.sha256) { Reject-ParseInput 'INPUT_DIGEST_MISMATCH' }
        $tokens = $null
        $parseErrors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($full, [ref]$tokens, [ref]$parseErrors)
        if (@($parseErrors).Count -gt 0) { Reject-ParseInput 'PARSE_ERROR' }
        if ((Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant() -cne $item.sha256) {
            Reject-ParseInput 'INPUT_DIGEST_MISMATCH'
        }
    }
    Write-Output 'PURE_PARSE_PASS;MAIN_EXECUTED=false;ROLES=6'
    exit 0
}
catch {
    # Do not serialize ErrorRecord, source text, paths or raw exception messages.
    Write-Output 'PURE_PARSE_REJECT;CODE=UNEXPECTED;MAIN_EXECUTED=false'
    exit 1
}
