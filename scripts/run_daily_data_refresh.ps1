# Daily data refresh (operator rule 2026-09-25: data change with the market, nothing
# hand-written, keeps updating after the project is done): the data-driven industry
# rotation, then the data-driven company reports for the newest sealed ranking.
#
# Reads BLS PPI (public API, no key) and SEC EDGAR XBRL frames with the declared SEC
# Fair Access contact. The contact is decrypted from the user's DPAPI file into this
# process only, never printed or written, and cleared afterwards. A failed refresh
# keeps the last good rotation file; the sealed publisher then applies its own age limit.
[CmdletBinding()]
param([double]$IfOlderThanHours = 20)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$statePath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\install-state.json'
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { Write-Host 'ROTATION_SKIPPED install-state missing'; exit 0 }
$state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
$contactPath = Join-Path ([string]$state.user_config_root) 'sec-contact.local.txt'
if (-not (Test-Path -LiteralPath $contactPath -PathType Leaf)) { Write-Host 'ROTATION_SKIPPED SEC contact not configured'; exit 0 }

$pointer = [IntPtr]::Zero
$previous = $env:SEC_CONTACT_EMAIL
try {
    $protected = ConvertTo-SecureString -String (Get-Content -LiteralPath $contactPath -Raw -Encoding utf8).Trim()
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($protected)
    $env:SEC_CONTACT_EMAIL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $env:PYTHONUTF8 = '1'
    Push-Location $repo
    try {
        & python 'scripts\industry_rotation.py' --refresh --if-older-than-hours $IfOlderThanHours
        $code = $LASTEXITCODE
        # Company reports use the rotation just written; a failure keeps the last good file.
        & python 'scripts\company_deep_report.py' --refresh --if-older-than-hours $IfOlderThanHours
        if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE }
    } finally { Pop-Location }
} finally {
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    $env:SEC_CONTACT_EMAIL = $previous
}
exit $code
