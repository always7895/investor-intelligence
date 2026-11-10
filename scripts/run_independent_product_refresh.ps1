# Bounded, independent public-product collectors for typed machine preseal failures.
# Called only by the sealed runner under its remaining task budget.
# No guidance, ranking, SEC contact, machine provider, KV or publication.
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = if ($env:PROJECT_PYTHON) { $env:PROJECT_PYTHON } else { 'python' }
$steps = @(
    [pscustomobject]@{Name='zh_names'; Args=@('scripts\build_zh_names.py','--if-older-than-hours','168')},
    [pscustomobject]@{Name='identity_shards'; Args=@('scripts\build_identity_shards.py','--if-older-than-hours','20')},
    [pscustomobject]@{Name='price_shards'; Args=@('scripts\build_price_shards.py','--if-older-than-hours','2.9')},
    [pscustomobject]@{Name='market_observations'; Args=@('scripts\build_market_quotes_options.py','--if-older-than-hours','0.9')}
)
$failures = 0
Push-Location $repo
try {
    foreach ($step in $steps) {
        $started = Get-Date
        $code = 1
        try {
            $global:LASTEXITCODE = $null
            & $python @($step.Args) 2>&1 | Out-Null
            if ($null -ne $global:LASTEXITCODE) { $code = [int]$global:LASTEXITCODE }
        } catch { $code = 1 }
        if ($code -ne 0) { $failures++ }
        Write-Host ('INDEPENDENT_PRODUCT_STEP {0} exit={1} seconds={2}' -f $step.Name,$code,[int]((Get-Date)-$started).TotalSeconds)
    }
} finally { Pop-Location }
if ($failures -gt 0) { exit 1 }
exit 0
