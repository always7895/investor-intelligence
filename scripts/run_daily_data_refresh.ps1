# Post-seal data refresh (operator rules 2026-09-25/26: data change with the market, nothing hand-written, refreshed
# near real time). Each step keeps its own cadence (--if-older-than-hours) and its last good output on failure; the
# sealed publisher applies its own age limits.
#
# SEC steps (rotation, company reports, Leopold 13F, bottleneck v3) need the declared SEC Fair Access contact, which is
# decrypted from the user's DPAPI file into this process only, never printed or written, and cleared afterwards.
# Steps that need no SEC contact (Chinese names, identity shards, Serenity signals, quotes/options) always run. Every step logs one
# STEP line with its exit code; native stderr never aborts the remaining steps (Windows PowerShell 5.1 would turn a
# warning line into a terminating error under Stop). The script exits non-zero when any step failed.
[CmdletBinding()]
param([double]$IfOlderThanHours = 20)

$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = if ($env:PROJECT_PYTHON) { $env:PROJECT_PYTHON } else { 'python' }
$failed = New-Object System.Collections.Generic.List[string]

function Invoke-Step([string]$Name, [string[]]$Arguments) {
    $started = Get-Date
    & $python @Arguments 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    Write-Host ("STEP {0} exit={1} seconds={2}" -f $Name, $code, [int]((Get-Date) - $started).TotalSeconds)
    if ($code -ne 0) { $failed.Add($Name) }
}

$contactPath = $null
$statePath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\install-state.json'
if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    try {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
        $candidate = Join-Path ([string]$state.user_config_root) 'sec-contact.local.txt'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $contactPath = $candidate }
    } catch { $contactPath = $null }
}

$env:PYTHONUTF8 = '1'
Push-Location $repo
$pointer = [IntPtr]::Zero
$previous = $env:SEC_CONTACT_EMAIL
try {
    # Steps without the SEC contact. Chinese names (weekly, sourced, never translated) feed the identity shards.
    Invoke-Step 'zh_names' @('scripts\build_zh_names.py', '--if-older-than-hours', '168')
    Invoke-Step 'identity_shards' @('scripts\build_identity_shards.py', '--if-older-than-hours', "$IfOlderThanHours")
    Invoke-Step 'serenity_signals' @('scripts\serenity_signals.py', '--refresh', '--if-older-than-hours', '6')
    if ($contactPath) {
        try {
            $protected = ConvertTo-SecureString -String (Get-Content -LiteralPath $contactPath -Raw -Encoding utf8).Trim()
            $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($protected)
            $env:SEC_CONTACT_EMAIL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
            Invoke-Step 'industry_rotation' @('scripts\industry_rotation.py', '--refresh', '--if-older-than-hours', "$IfOlderThanHours")
            # Company reports use the rotation just written; a failure keeps the last good file.
            Invoke-Step 'company_reports' @('scripts\company_deep_report.py', '--refresh', '--if-older-than-hours', "$IfOlderThanHours")
            Invoke-Step 'leopold_13f' @('scripts\leopold_positions.py', '--if-older-than-hours', '24')
            Invoke-Step 'bottleneck_v3' @('scripts\bottleneck_top20_v3.py', '--if-older-than-hours', '3')
        } catch {
            Write-Host ('STEP sec_contact exit=1 ' + $_.Exception.GetType().Name)
            $failed.Add('sec_contact')
        }
    } else {
        Write-Host 'STEP sec_steps SKIPPED (install-state or SEC contact not configured)'
        $failed.Add('sec_contact_missing')
    }
    # Delayed quotes and covered-call suggestions for the LINE lookup and options queries, every hour.
    # Delayed daily prices for every listing (official bulk feeds per market) for the stock lookup, every 3 hours.
    Invoke-Step 'price_shards' @('scripts\build_price_shards.py', '--if-older-than-hours', '2.9')
    Invoke-Step 'market_observations' @('scripts\build_market_quotes_options.py', '--if-older-than-hours', '0.9')
} finally {
    Pop-Location
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    $env:SEC_CONTACT_EMAIL = $previous
}
if ($failed.Count -gt 0) {
    Write-Host ('DATA_REFRESH FAILED steps=' + ($failed -join ','))
    exit 1
}
Write-Host 'DATA_REFRESH OK'
exit 0
