[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [switch]$DryRun
)
# Keeps LINE Q&A connected to whatever local model is served (operator 2026-09-26: a changed port or model, or a model
# server started later, must reconnect without a manual step). Run by the InvestorIntelligence-v213-FreeRelay task at
# logon and every five minutes. It does nothing while the bridge is healthy on the model the resolver would choose, and
# nothing while no local model is served; otherwise it restarts the bridge (-StopExisting), which verifies the model,
# starts the gateway and tunnel and leases the route. The heartbeat keeps the lease between runs.
# Explicit Strata intent (F04): the resolver CLI first resolves the shared request binding. A CLI failure, refusal or
# error ends the run BEFORE any process inspection, gateway health request or reconnect (IDLE_BINDING_UNAVAILABLE for an
# explicit-intent refusal). A valid explicit result is the exact bound root/model; the live gateway must report that
# model plus the SAME runtime-binding and profile digests (UNQUALIFIED) to count as healthy, otherwise the normal bridge
# reconnect runs, which revalidates the binding itself. No credentials, model start, schedule change or probe is added.
# The resolver runs on the SAME existing interpreter the bridge core uses: an existing PROJECT_PYTHON, else the fixed portable
# python-3.12.10 under %LOCALAPPDATA% (resolved path; no import/version probe, bootstrap, install or Get-Command). A configured
# but unusable PROJECT_PYTHON, or no portable interpreter while explicit/orphan/malformed intent is present, ends the run
# early as IDLE_BINDING_UNAVAILABLE (BINDING_PYTHON_PREREQUISITE_UNAVAILABLE); the PATH 'python' fallback survives only for
# true legacy absence. The early intent test is a conservative mode discriminator, not a binding validator. A configured
# install-state alternate folder is touched only after a lexical (never provider-aware) spelling check, a QueryDosDeviceW
# proof that its drive is ONE direct local volume (no mapped, subst or missing drive) and a no-follow ancestor walk; the
# terminal files are inspected without following them. Anything unproven, linked or throwing is a sanitized INVALID (typed
# BINDING_SELECTION_INVALID), never LEGACY absence. The native declaration is source text for future runtime: NOT_RUN here.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$statePath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v213-local-model.json'
$script:DosDeviceSource = @'
using System;
using System.Runtime.InteropServices;
namespace V213Watchdog {
    public static class DosDevice {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint QueryDosDeviceW(string lpDeviceName, [Out] char[] lpTargetPath, uint ucchMax);
        public static string[] Targets(string deviceName) {
            char[] buffer = new char[1024];
            uint length = QueryDosDeviceW(deviceName, buffer, (uint)buffer.Length);
            if (length == 0 || length >= buffer.Length) { return null; }
            return new string(buffer, 0, (int)length).TrimEnd('\0').Split('\0');
        }
    }
}
'@

function Test-Alive([object]$ProcessId, [string]$ExpectedName) {
    $id = 0
    if (-not [int]::TryParse([string]$ProcessId, [ref]$id) -or $id -le 0) { return $false }
    try { return (Get-Process -Id $id -ErrorAction Stop).ProcessName -match $ExpectedName } catch { return $false }
}

function Get-Field([object]$Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Test-PathWithinCeiling([string]$Path) {
    # N5: the FULL resulting path against a conservative 240 ceiling in UTF-16 code units (.NET string Length counts UTF-16 units) and a
    # lone-surrogate refusal, BEFORE any native metadata call. No filesystem-resolving normalization.
    return ($Path.Length -le 240 -and $Path -cnotmatch '[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]')
}

function Read-JsonObjectState([string]$Path, [int]$Limit) {
    # MISSING (legitimate optional absence) | INVALID (present link/directory/oversized/unreadable/malformed/non-object) | OBJECT.
    # The raw text must open with a top-level object BEFORE decoding, so the decision never depends on how ConvertFrom-Json
    # enumerates a singleton array in a pipeline (PowerShell 5.1 vs 7). A conservative discriminator, not a JSON parser.
    try {
        # The terminal entry is inspected WITHOUT following it (attributes only): a link/reparse point or directory is INVALID
        # before any read. A swap between this check and the read is a narrowed, not eliminated, race (NOT_RUN, unproven).
        if (-not (Test-PathWithinCeiling $Path)) { return [pscustomobject]@{ State = 'INVALID'; Value = $null } }
        $attributes = $null
        try { $attributes = [IO.File]::GetAttributes($Path) }
        catch [IO.FileNotFoundException] { return [pscustomobject]@{ State = 'MISSING'; Value = $null } }
        catch [IO.DirectoryNotFoundException] { return [pscustomobject]@{ State = 'MISSING'; Value = $null } }
        if (([int]$attributes -band 0x441400) -ne 0 -or ($attributes -band [IO.FileAttributes]::Directory) -ne 0 -or [IO.FileInfo]::new($Path).Length -gt $Limit) { return [pscustomobject]@{ State = 'INVALID'; Value = $null } }
        $text = [IO.File]::ReadAllText($Path)
        if ($text -cnotmatch '\A[ \t\r\n]*\{') { return [pscustomobject]@{ State = 'INVALID'; Value = $null } }
        $value = $text | ConvertFrom-Json -ErrorAction Stop
    } catch { return [pscustomobject]@{ State = 'INVALID'; Value = $null } }
    if ($null -eq $value -or $value -isnot [pscustomobject]) { return [pscustomobject]@{ State = 'INVALID'; Value = $null } }
    return [pscustomobject]@{ State = 'OBJECT'; Value = $value }
}

function Test-SelectionMarkers([object]$Value) {
    return ($null -ne $Value.PSObject.Properties['engine'] -or $null -ne $Value.PSObject.Properties['runtime_binding_sha256'])
}

function Get-AlternateFolderSpelling([object]$Root) {
    # Lexical only (no Join-Path, no provider, no filesystem): an unambiguous drive-letter absolute spelling or $null. UNC, device,
    # relative, parent, stream (colon), doubled-separator, trailing dot/space, dot-only, reserved-device and over-long spellings
    # are refused. Spelling never proves the folder is local: Test-LocalFolderChain does.
    if ($Root -isnot [string] -or $Root.Length -lt 3 -or $Root -cnotmatch '\A[A-Za-z]:[\\/][^<>:"|?*\x00-\x1f]*\z') { return $null }
    if (-not (Test-PathWithinCeiling (($Root.TrimEnd('\', '/')) + '\v213-model-selection.json'))) { return $null }  # N5: full resulting path
    $parts = @()
    if ($Root.Length -gt 3) {
        $parts = @($Root.Substring(3) -split '[\\/]')
        if ($parts[$parts.Count - 1].Length -eq 0) { $parts = @($parts | Select-Object -SkipLast 1) }
    }
    foreach ($part in $parts) {
        if ($part.Length -eq 0 -or $part.Length -gt 255 -or $part -cmatch '[. ]\z' -or $part -match '(?i)\A(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[0-9\u00b9\u00b2\u00b3])(?:\..*)?\z') { return $null }
    }
    return [pscustomobject]@{ Drive = $Root.Substring(0, 2); Parts = $parts }
}

function Test-LocalFolderChain([object]$Spelling) {
    # OK | INVALID. OK means the drive is ONE direct local volume (QueryDosDeviceW target is exactly one HarddiskVolumeN device:
    # mapped, subst, missing-in-this-session and overlaid drives and any API/compile failure are INVALID) and every existing
    # component from the root is a plain directory without the reparse-point, offline, recall-on-open or recall-on-data-access flag (mask 0x441400; attributes only, never followed, no recursion; no wider placeholder or remote-backing claim). The
    # first genuinely missing component ends the walk as legitimate absence. Any other error is INVALID. Native/race behavior
    # is NOT_RUN and unproven.
    try {
        $type = 'V213Watchdog.DosDevice' -as [type]
        if ($null -eq $type) {
            Add-Type -TypeDefinition $script:DosDeviceSource -ErrorAction Stop
            $type = 'V213Watchdog.DosDevice' -as [type]
        }
        if ($null -eq $type) { return 'INVALID' }
        $targets = $type::Targets($Spelling.Drive.ToUpperInvariant())
        if ($null -eq $targets -or @($targets).Count -ne 1 -or [string]$targets[0] -cnotmatch '\A\\Device\\HarddiskVolume[0-9]{1,6}\z') { return 'INVALID' }
        $current = $Spelling.Drive
        foreach ($part in $Spelling.Parts) {
            $current = $current + '\' + $part
            $attributes = $null
            try { $attributes = [IO.File]::GetAttributes($current) }
            catch [IO.FileNotFoundException] { return 'OK' }
            catch [IO.DirectoryNotFoundException] { return 'OK' }
            if (([int]$attributes -band 0x441400) -ne 0 -or ($attributes -band [IO.FileAttributes]::Directory) -eq 0) { return 'INVALID' }
        }
        return 'OK'
    } catch { return 'INVALID' }
}

function Get-LexicalFolderKey([string]$Path) {
    # Separator, repeated-separator, trailing-separator and (at comparison) case normalization ONLY: no GetFullPath, Resolve-Path,
    # GetLongPathName/short-name expansion or any filesystem access before the authority proof. Mirrors the Python normpath/
    # normcase comparison; a short-path or otherwise aliased spelling of the canonical folder conservatively compares different.
    return ([regex]::Replace($Path.Replace('/', '\'), '\\{2,}', '\')).TrimEnd('\')
}

function Get-AlternateSelectionState([string]$ConfigFolder) {
    # NONE | INVALID | EXPLICIT for the install-state user_config_root the Python resolver also consults. Missing install state
    # or field is legitimate absence; a present unusable state, an unsafe or ambiguous spelling, an unproven local volume, a
    # link/reparse ancestor or an unreadable selection is INVALID (uncertainty is never absence); explicit markers in a
    # DIFFERENT alternate folder are unsupported and reach the resolver, which refuses them. The canonical folder was already
    # inspected by the caller. The alternate path is joined lexically, only after the chain is proven. Metadata reads only.
    $install = Read-JsonObjectState (Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\install-state.json') 65536
    if ($install.State -ceq 'MISSING') { return 'NONE' }
    if ($install.State -ceq 'INVALID') { return 'INVALID' }
    $property = $install.Value.PSObject.Properties['user_config_root']
    if ($null -eq $property) { return 'NONE' }
    $root = $property.Value
    $spelling = Get-AlternateFolderSpelling $root
    if ($null -eq $spelling) { return 'INVALID' }
    if ([string]::Equals((Get-LexicalFolderKey $root), (Get-LexicalFolderKey $ConfigFolder), [StringComparison]::OrdinalIgnoreCase)) { return 'NONE' }
    if ((Test-LocalFolderChain $spelling) -cne 'OK') { return 'INVALID' }
    $alternate = Read-JsonObjectState (($root.TrimEnd('\', '/')) + '\v213-model-selection.json') 16384
    if ($alternate.State -ceq 'MISSING') { return 'NONE' }
    if ($alternate.State -ceq 'INVALID') { return 'INVALID' }
    if (Test-SelectionMarkers $alternate.Value) { return 'EXPLICIT' }
    return 'NONE'
}

function Get-IntentPresence([string]$ConfigFolder) {
    # ABSENT | EXPLICIT | INVALID, mirroring the presence rules of the bridge core (env binding, saved intent, selection
    # engine/runtime_binding_sha256 after JSON decoding of escaped names) for the canonical folder AND the install-state
    # alternate folder. Never validates a binding itself: the shared resolver validates the original bytes.
    if ($null -ne [Environment]::GetEnvironmentVariable('V213_RUNTIME_BINDING_JSON')) { return 'EXPLICIT' }
    if (Test-Path -LiteralPath (Join-Path $ConfigFolder 'v213-runtime-binding-v1.json')) { return 'EXPLICIT' }
    $canonical = Read-JsonObjectState (Join-Path $ConfigFolder 'v213-model-selection.json') 16384
    if ($canonical.State -ceq 'INVALID') { return 'INVALID' }
    $state = if ($canonical.State -ceq 'OBJECT' -and (Test-SelectionMarkers $canonical.Value)) { 'EXPLICIT' } else { 'ABSENT' }
    $alternate = Get-AlternateSelectionState $ConfigFolder
    if ($alternate -ceq 'INVALID') { return 'INVALID' }
    if ($alternate -ceq 'EXPLICIT') { return 'EXPLICIT' }
    return $state
}

function Get-ResolverInterpreter([string]$IntentState) {
    # Existing configured PROJECT_PYTHON, else the fixed portable path core uses. A configured but missing interpreter is
    # unavailable, never permission to pick another. PATH 'python' only for true legacy absence. File existence only.
    $configured = $env:PROJECT_PYTHON
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        if (Test-Path -LiteralPath $configured -PathType Leaf) { return [pscustomobject]@{ Path = (Resolve-Path -LiteralPath $configured).ProviderPath; Reason = '' } }
        return [pscustomobject]@{ Path = ''; Reason = 'BINDING_PYTHON_PREREQUISITE_UNAVAILABLE' }
    }
    $portable = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\Runtime\python-3.12.10\python.exe'
    if (Test-Path -LiteralPath $portable -PathType Leaf) { return [pscustomobject]@{ Path = (Resolve-Path -LiteralPath $portable).ProviderPath; Reason = '' } }
    if ($IntentState -ceq 'ABSENT') { return [pscustomobject]@{ Path = 'python'; Reason = '' } }
    return [pscustomobject]@{ Path = ''; Reason = 'BINDING_PYTHON_PREREQUISITE_UNAVAILABLE' }
}

function Test-FoundShape([object]$Found) {
    # Strict shape of a usable resolver result; an explicit result must carry the exact digests and stay UNQUALIFIED.
    $model = Get-Field $Found 'model'
    $base = Get-Field $Found 'base_url'
    if ($model -isnot [string] -or $model.Length -eq 0 -or $base -isnot [string] -or $base.Length -eq 0) { return $false }
    if ([string](Get-Field $Found 'mode') -cne 'EXPLICIT_STRATA') { return $true }
    return ($base -cmatch '^http://127\.0\.0\.1:[1-9][0-9]{0,4}$' -and
        [string](Get-Field $Found 'binding_sha256') -cmatch '^[0-9a-f]{64}$' -and
        [string](Get-Field $Found 'model_profile_sha256') -cmatch '^[0-9a-f]{64}$' -and
        [string](Get-Field $Found 'qualification') -ceq 'UNQUALIFIED')
}

function Test-GatewayServesFound([object]$Health, [object]$State, [object]$Found) {
    $available = Get-Field $Health 'selected_model_available'
    if ($available -isnot [bool] -or -not $available -or [string](Get-Field $Health 'selected_model') -cne [string](Get-Field $State 'model')) { return $false }
    if ([string](Get-Field $Found 'mode') -cne 'EXPLICIT_STRATA') { return $true }  # legacy decision unchanged
    # Explicit: the exact bound identity and BOTH digests of the live gateway, never a requested/discovered substitute.
    $ok = Get-Field $Health 'ok'
    return ($ok -is [bool] -and $ok -and [string](Get-Field $Health 'service') -ceq 'v213-local-llm-gateway' -and
        [string](Get-Field $Health 'selected_model') -ceq [string](Get-Field $Found 'model') -and
        [string](Get-Field $Health 'runtime_binding_sha256') -ceq [string](Get-Field $Found 'binding_sha256') -and
        [string](Get-Field $Health 'model_profile_sha256') -ceq [string](Get-Field $Found 'model_profile_sha256') -and
        [string](Get-Field $Health 'qualification') -ceq 'UNQUALIFIED')
}

function Get-WatchdogDecision([object]$Found, [object]$State, [bool]$ProcessesAlive, [bool]$GatewayServesModel) {
    if ($null -ne $Found -and [string](Get-Field $Found 'error') -ceq 'LOCAL_MODEL_BINDING_UNAVAILABLE') { return 'IDLE_BINDING_UNAVAILABLE' }
    if ($null -eq $Found -or $null -ne (Get-Field $Found 'error')) { return 'IDLE_NO_LOCAL_MODEL' }
    if ($null -eq $State) { return 'CONNECT' }
    if ([string](Get-Field $State 'model') -cne [string]$Found.model -or
        ([string](Get-Field $State 'llama_base_url')).TrimEnd('/') -ne ([string]$Found.base_url).TrimEnd('/')) { return 'RECONNECT_MODEL_CHANGED' }
    if (-not $ProcessesAlive) { return 'RECONNECT_PROCESS_UNAVAILABLE' }
    if (-not $GatewayServesModel) { return 'RECONNECT_GATEWAY_UNHEALTHY' }
    return 'HEALTHY'
}

$found = $null
$cliExit = $null
try { $intentState = Get-IntentPresence (Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config') }
catch { $intentState = 'INVALID' }  # the whole early classification is exception-safe: never an escaping error or silent legacy
if ($intentState -ceq 'INVALID') {
    # Malformed/oversized/non-file selection: refuse BEFORE any interpreter choice, PATH lookup or resolver run.
    $found = [pscustomobject]@{ error = 'LOCAL_MODEL_BINDING_UNAVAILABLE'; reason = 'BINDING_SELECTION_INVALID' }
} else {
    $interpreter = Get-ResolverInterpreter $intentState
    if ([string]::IsNullOrEmpty($interpreter.Path)) {
        # No usable interpreter: typed prerequisite refusal for explicit/orphan intent; legacy absence keeps its old idle result.
        $found = if ($intentState -ceq 'ABSENT') { $null } else { [pscustomobject]@{ error = 'LOCAL_MODEL_BINDING_UNAVAILABLE'; reason = [string]$interpreter.Reason } }
    } else {
        try {
            $raw = & $interpreter.Path (Join-Path $ProjectRoot 'scripts\local_model_endpoint.py') 2>$null
            $cliExit = $LASTEXITCODE
            $found = ($raw | Select-Object -Last 1) | ConvertFrom-Json
        } catch { $found = $null }
    }
}
# Command failure/error/refusal is decided HERE, before the state file, process inspection, health request or reconnect.
if ($null -ne $found -and $null -eq (Get-Field $found 'error')) {
    if ($cliExit -ne 0 -or -not (Test-FoundShape $found)) {
        $found = if ([string](Get-Field $found 'mode') -ceq 'EXPLICIT_STRATA') {
            [pscustomobject]@{ error = 'LOCAL_MODEL_BINDING_UNAVAILABLE'; reason = 'WATCHDOG_RESOLVER_RESULT_INVALID' }
        } else { $null }
    }
}
if ($null -eq $found -or $null -ne (Get-Field $found 'error')) {
    $earlyReason = [string](Get-Field $found 'reason')
    if ($earlyReason -cnotmatch '^[A-Z][A-Z0-9_]{0,63}$') { $earlyReason = '' }
    Write-Host "V213_FREE_RELAY_WATCHDOG = $(Get-WatchdogDecision $found $null $false $false); model=; reason=$earlyReason; dry_run=$($DryRun.IsPresent)"
    exit 0
}
$state = $null
if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    try { $state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json } catch { $state = $null }
}
$alive = $false
$serves = $false
if ($null -ne $state) {
    $alive = (Test-Alive (Get-Field $state 'gateway_pid') '(?i)^python') -and (Test-Alive (Get-Field $state 'cloudflared_pid') '(?i)^cloudflared$') -and
        (Test-Alive (Get-Field $state 'free_relay_heartbeat_pid') '(?i)^powershell$')
    if ($alive) {
        try {
            $health = Invoke-RestMethod -Method Get -Uri ("http://127.0.0.1:{0}/health" -f [int](Get-Field $state 'gateway_port')) -TimeoutSec 8 -MaximumRedirection 0
            $serves = Test-GatewayServesFound $health $state $found
        } catch { $serves = $false }
    }
}
$decision = Get-WatchdogDecision $found $state $alive $serves
$model = if ($null -ne $found -and $null -eq (Get-Field $found 'error')) { [string]$found.model } else { '' }
Write-Host "V213_FREE_RELAY_WATCHDOG = $decision; model=$model; dry_run=$($DryRun.IsPresent)"
if ($DryRun -or $decision -in @('HEALTHY', 'IDLE_NO_LOCAL_MODEL', 'IDLE_BINDING_UNAVAILABLE')) { exit 0 }
$bridge = Join-Path $ProjectRoot 'run-v213-local-llm-bridge.ps1'
& $bridge -ProjectRoot $ProjectRoot -InstallCloudflared -StopExisting -TunnelMode FreeRelay
