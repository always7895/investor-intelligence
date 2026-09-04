[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$setup = Join-Path $ProjectRoot 'scripts\setup_v213_named_tunnel.ps1'
$bridge = Join-Path $ProjectRoot 'scripts\run_v213_local_llm_bridge_core.ps1'
$helper = Join-Path $ProjectRoot 'scripts\v213_named_tunnel_helpers.ps1'
$launcher = Join-Path $ProjectRoot 'launcher\InvestorIntelligenceLauncher.cs'
$refresh = Join-Path $ProjectRoot 'run-v213-local.ps1'
foreach ($path in @($setup,$bridge,$helper,$launcher,$refresh)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Named-tunnel test input missing: $path" }
}
$hostPath = (Get-Process -Id $PID).Path
& $hostPath -NoProfile -ExecutionPolicy Bypass -File $setup -ProjectRoot $ProjectRoot -SelfTest
if ($LASTEXITCODE -ne 0) { throw 'Named Tunnel setup self-test failed.' }
& $hostPath -NoProfile -ExecutionPolicy Bypass -File $bridge -ProjectRoot $ProjectRoot -SelfTest
if ($LASTEXITCODE -ne 0) { throw 'Named Tunnel bridge self-test failed.' }

$bridgeSource = Get-Content -LiteralPath $bridge -Raw -Encoding utf8
$helperSource = Get-Content -LiteralPath $helper -Raw -Encoding utf8
$launcherSource = Get-Content -LiteralPath $launcher -Raw -Encoding utf8
$refreshSource = Get-Content -LiteralPath $refresh -Raw -Encoding utf8
$requiredBridge = @(
    'Wait-PublicHealthStable $url $process.Id $SelectedModel 3',
    "health_schema_version = 2",
    'reportedModel -ieq $SelectedModel',
    'ROLLBACK_NEW_RETAIN_OLD',
    'New-V213RuntimeNamedTunnelConfig',
    "tunnelPolicy.mode -eq 'Named'"
)
foreach ($marker in $requiredBridge) {
    if ($bridgeSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) { throw "Named bridge marker missing: $marker" }
}
foreach ($marker in @("@('tunnel','list')", "@('tunnel','info',`$Name)", "@('tunnel','route','dns','--overwrite-dns',`$Name,`$Hostname)", 'credentials-file', 'TunnelSecret')) {
    if ($helperSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) { throw "Named setup fail-closed marker missing: $marker" }
}
foreach ($marker in @('One-time Named Tunnel setup','NamedTunnelPowerShellArguments(tunnel)','-TunnelMode Named')) {
    if ($launcherSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) { throw "Launcher named-tunnel marker missing: $marker" }
}
foreach ($marker in @("[ValidateSet('None','QuickTest','Named')]", '-NamedTunnelName $NamedTunnelName', '-NamedTunnelHostname $NamedTunnelHostname', '-NamedTunnelConfig $NamedTunnelConfig')) {
    if ($refreshSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) { throw "Refresh named-tunnel marker missing: $marker" }
}
if ($launcherSource -match 'AllowTestTunnelException') { throw 'Launcher normal Production path must not use AllowTestTunnelException.' }
Write-Host "V213_NAMED_TUNNEL_HOST_TEST = PASS; powershell=$($PSVersionTable.PSVersion); special_path=true; negative_tests=true; consecutive_public_health=3; exact_model=true; health_schema_v2=true; blue_green_rollback=true; production_mutation=false" -ForegroundColor Green
