# Investor Intelligence: choose the local model when several are served (operator 2026-09-26).
# Lists every model on the loopback model servers (scripts/local_model_endpoint.py --all) and saves the choice as the
# launcher selection (UserData\config\v213-model-selection.json). The launcher, the hourly translator, the Q&A bridge
# and the relay all try the saved model first; a model that later disappears falls back to auto-detection.
[CmdletBinding()]
param([string]$Model = '', [switch]$Reconnect, [switch]$NoPause,
      [ValidateSet('Strata','Legacy')][string]$Engine,
      [AllowNull()][AllowEmptyString()][string]$BaseUrl,
      [string]$ProfilePath,
      [switch]$CheckBinding, [switch]$RemoveRuntimeBinding)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PROJECT_PYTHON) { $env:PROJECT_PYTHON } else { 'python' }
$selectionPath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v213-model-selection.json'
function Finish([int]$Code) {
    if (-not $NoPause) { Write-Host ''; Write-Host '按任意鍵關閉視窗…'; [void][Console]::ReadKey($true) }
    exit $Code
}
# L1 (legacy scan only): presence is never validity, and an unreadable state is a finite refusal, never absence.
function Test-PathPresent([string]$Path) {
    # File.GetAttributes does not follow a final link: a file, a directory, a reparse point or a broken link is PRESENT. Only the two
    # not-found exceptions mean absent; every other fault is a finite refusal. Static .NET semantics; native PS 5.1 behavior NOT_RUN.
    try { [void][IO.File]::GetAttributes($Path); return $true }
    catch [IO.FileNotFoundException] { return $false }
    catch [IO.DirectoryNotFoundException] { return $false }
    catch { throw 'MODEL_STATE_UNAVAILABLE' }
}
function Get-SelectionState([string]$Path) {
    # Bounded strict view of the saved legacy selection: absent, or ONE regular file of at most 16 KiB holding a UTF-8 top-level JSON
    # object; anything else is MODEL_SELECTION_INVALID (never ignored). Explicit = engine / runtime_binding_sha256 property PRESENCE.
    if (-not (Test-PathPresent $Path)) { return [pscustomobject]@{ Present = $false; Sha256 = ''; Explicit = $false; Value = $null } }
    $bytes = $null
    $value = $null
    try {
        $attributes = [IO.File]::GetAttributes($Path)
        if (($attributes -band ([IO.FileAttributes]::Directory -bor [IO.FileAttributes]::ReparsePoint)) -ne 0) { throw 'invalid' }
        $stream = [IO.FileStream]::new($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try {
            $buffer = New-Object byte[] 16385
            $count = 0
            while ($count -lt $buffer.Length) {
                $read = $stream.Read($buffer, $count, $buffer.Length - $count)
                if ($read -le 0) { break }
                $count += $read
            }
        } finally { $stream.Dispose() }
        if ($count -gt 16384) { throw 'invalid' }
        $bytes = New-Object byte[] $count
        [Array]::Copy($buffer, $bytes, $count)
        $skip = if ($count -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { 3 } else { 0 }
        $text = [Text.UTF8Encoding]::new($false, $true).GetString($bytes, $skip, $count - $skip)
        if ($text -cnotmatch '\A[ \t\r\n]*\{') { throw 'invalid' }
        $value = $text | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $value -or $value -isnot [pscustomobject]) { throw 'invalid' }
    } catch { throw 'MODEL_SELECTION_INVALID' }
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $digest = [BitConverter]::ToString($hasher.ComputeHash($bytes)).Replace('-', '') } finally { $hasher.Dispose() }
    return [pscustomobject]@{ Present = $true; Sha256 = $digest; Value = $value
        Explicit = ($null -ne $value.PSObject.Properties['engine'] -or $null -ne $value.PSObject.Properties['runtime_binding_sha256']) }
}
try {
    $intentPath = Join-Path (Split-Path $selectionPath -Parent) 'v213-runtime-binding-v1.json'
    if ($PSBoundParameters.ContainsKey('Engine') -and $Engine -cne 'Strata' -and $Engine -cne 'Legacy') { throw 'ENGINE_INTENT_INVALID' }
    $explicit = ($PSBoundParameters.ContainsKey('Engine') -and $Engine -ceq 'Strata') -or (Test-Path -LiteralPath $intentPath) -or $null -ne [Environment]::GetEnvironmentVariable('V213_RUNTIME_BINDING_JSON')
    if (-not $RemoveRuntimeBinding -and (Test-Path -LiteralPath $selectionPath)) {
        if (-not (Test-Path -LiteralPath $selectionPath -PathType Leaf) -or (Get-Item -LiteralPath $selectionPath).Length -gt 16384) { throw 'MODEL_SELECTION_INVALID' }
        # Raw top-level object check BEFORE decoding: never infer the type from pipeline-enumerated output (version-independent).
        # -RemoveRuntimeBinding skips this block, so offline removal of a corrupt selection still works.
        try {
            $savedSelectionText = [IO.File]::ReadAllText($selectionPath)
            if ($savedSelectionText -cnotmatch '\A[ \t\r\n]*\{') { throw 'MODEL_SELECTION_INVALID' }
            $savedSelection = $savedSelectionText | ConvertFrom-Json -ErrorAction Stop
        } catch { throw 'MODEL_SELECTION_INVALID' }
        if ($null -eq $savedSelection -or $savedSelection -isnot [pscustomobject]) { throw 'MODEL_SELECTION_INVALID' }
        $explicit = $explicit -or $null -ne $savedSelection.PSObject.Properties['engine'] -or $null -ne $savedSelection.PSObject.Properties['runtime_binding_sha256']
    }
    if ($RemoveRuntimeBinding -or $CheckBinding -or $explicit) {
        if ($Reconnect -or ($CheckBinding -and $PSBoundParameters.ContainsKey('ProfilePath')) -or ($RemoveRuntimeBinding -and ($CheckBinding -or $PSBoundParameters.ContainsKey('ProfilePath') -or $PSBoundParameters.ContainsKey('Engine') -or $PSBoundParameters.ContainsKey('Model') -or $PSBoundParameters.ContainsKey('BaseUrl')))) { throw 'EXPLICIT_INTENT_ACTION_CONFLICT' }
        # Existing interpreter only. No PATH discovery/bootstrap/install/import
        # probe, and no catalog/scheduled task access in offline selection.
        $intentPython = $env:PROJECT_PYTHON
        if ([string]::IsNullOrWhiteSpace($intentPython)) { $intentPython = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\Runtime\python-3.12.10\python.exe' }
        if (-not (Test-Path -LiteralPath $intentPython -PathType Leaf)) { throw 'BINDING_PYTHON_PREREQUISITE_UNAVAILABLE' }
        $helper = Join-Path $root 'scripts\v213_model_profile.py'
        if ($RemoveRuntimeBinding) {
            $result = & $intentPython $helper --remove-binding
        } elseif ($CheckBinding) {
            if ($PSBoundParameters.ContainsKey('Engine') -and $Engine -cne 'Strata') { throw 'EXPLICIT_INTENT_ACTION_CONFLICT' }
            $request = @{root=$root}
            if ($PSBoundParameters.ContainsKey('Model')) { $request.model=$Model }
            if ($PSBoundParameters.ContainsKey('BaseUrl')) { $request.base_url=$BaseUrl }
            $result = ($request | ConvertTo-Json -Compress) | & $intentPython $helper --resolve-stdin --metadata-check
        } else {
            if (-not $PSBoundParameters.ContainsKey('Engine') -or $Engine -cne 'Strata' -or -not $PSBoundParameters.ContainsKey('Model') -or -not $PSBoundParameters.ContainsKey('BaseUrl')) { throw 'SAVED_EXPLICIT_INTENT_REQUIRES_STRATA_OR_EXPLICIT_REMOVAL' }
            if (-not $PSBoundParameters.ContainsKey('ProfilePath')) {
                $ProfilePath = Join-Path (Split-Path $selectionPath -Parent) 'v213-model-profile-v1.json'
                if (-not (Test-Path -LiteralPath $ProfilePath)) { $ProfilePath=Join-Path $root 'config\v213-model-profile-v1.json' }
            }
            if (-not(Test-Path -LiteralPath $ProfilePath -PathType Leaf) -or (Get-Item -LiteralPath $ProfilePath).Length -gt 4096) { throw 'MODEL_PROFILE_UNAVAILABLE' }
            $request = @{root=$root;base_url=$BaseUrl;model=$Model;profile=[IO.File]::ReadAllText($ProfilePath)}
            $result = ($request | ConvertTo-Json -Compress -Depth 8) | & $intentPython $helper --save-binding-stdin
        }
        if ($LASTEXITCODE -ne 0) { throw 'EXPLICIT_BINDING_UNAVAILABLE' }
        Write-Host ($result -join "`n")
        Write-Host 'REQUEST INTENT / METADATA ONLY — UNQUALIFIED；未啟動模型或 LINE。'
        Finish 0
    }
    if ($PSBoundParameters.ContainsKey('BaseUrl') -or $PSBoundParameters.ContainsKey('ProfilePath')) { throw 'LEGACY_SELECTION_ARGUMENT_CONFLICT' }
    # L1: legacy discovery is refused once the EXE model registry exists (any form: an invalid registry is not absence).
    $registryPath = Join-Path (Split-Path $selectionPath -Parent) 'v213-model-registry-v1.json'
    if (Test-PathPresent $registryPath) { throw 'REGISTRY_PRESENT_USE_EXE_MODEL_REGISTRY' }
    $pinned = Get-SelectionState $selectionPath
    if ($pinned.Explicit) { throw 'EXPLICIT_INTENT_APPEARED' }
    Write-Host '正在掃描本機模型伺服器…' -ForegroundColor Cyan
    $raw = $null
    $exitCode = $null
    # A native stderr / ErrorActionPreference=Stop failure under Windows PowerShell 5.1 (not run) also lands in the finite refusal below.
    try { $raw = & $python (Join-Path $root 'scripts\local_model_endpoint.py') --all 2>$null; $exitCode = $LASTEXITCODE } catch { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
    # Exactly one bounded JSON object line; the finite error status and the exit code decide, never a last-line salvage.
    $lines = @($raw | ForEach-Object { [string]$_ } | Where-Object { $_.Trim() })
    if ($lines.Count -ne 1 -or $lines[0].Length -gt 262144 -or $lines[0] -cnotmatch '\A\s*\{') { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
    try { $found = $lines[0] | ConvertFrom-Json -ErrorAction Stop } catch { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
    if ($null -eq $found -or $found -isnot [pscustomobject]) { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
    $errorProperty = $found.PSObject.Properties['error']
    # The real endpoint ALWAYS sends mode SELECTED_INTENT_UNAVAILABLE with this error, so the dedicated refusal is decided FIRST,
    # before the mode check, the exit code and any server rows. Any other mode-bearing output is refused below; never a fallback.
    if ($null -ne $errorProperty -and $errorProperty.Value -is [string] -and $errorProperty.Value -ceq 'LOCAL_MODEL_BINDING_UNAVAILABLE') { throw 'LOCAL_MODEL_BINDING_UNAVAILABLE' }
    if ($null -ne $found.PSObject.Properties['mode']) { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
    if ($null -ne $errorProperty -and $errorProperty.Value -isnot [string]) { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
    if ($exitCode -eq 0) {
        if ($null -ne $errorProperty) { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
    } elseif ($exitCode -eq 3 -and $null -ne $errorProperty) {
        # Known endpoint behavior: LOCAL_MODEL_AMBIGUOUS carries valid servers and stays a MANUAL choice (no automatic inference).
        if ($errorProperty.Value -ceq 'LOCAL_MODEL_NOT_FOUND') { throw '沒有找到任何本機模型伺服器；請先啟動模型伺服器。' }
        if ($errorProperty.Value -cne 'LOCAL_MODEL_AMBIGUOUS') { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
    } else { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
    # servers and every models list must be real JSON arrays (object[] in Windows PowerShell 5.1 and 7); no scalar is coerced into one.
    # Only http://127.0.0.1:<port> bases are accepted (other forms, including IPv6, are refused, not repaired) and EVERY model ID must
    # match the ID grammar before it can be shown or stored.
    $serversProperty = $found.PSObject.Properties['servers']
    if ($null -eq $serversProperty -or $serversProperty.Value -isnot [object[]]) { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
    $choices = @()
    foreach ($server in $serversProperty.Value) {
        if ($server -isnot [pscustomobject] -or $null -eq $server.PSObject.Properties['base_url'] -or $null -eq $server.PSObject.Properties['models']) { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
        $base = $server.base_url
        if ($base -isnot [string] -or $base -cnotmatch '\Ahttp://127\.0\.0\.1:[1-9][0-9]{0,4}\z') { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
        $port = [int]$base.Substring($base.LastIndexOf(':') + 1)
        if ($port -gt 65535 -or $port -eq 5000 -or $port -eq 8000) { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
        if ($server.models -isnot [object[]]) { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
        foreach ($id in $server.models) {
            if ($id -isnot [string] -or $id -cnotmatch '\A[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}\z') { throw 'LOCAL_MODEL_SCAN_UNAVAILABLE' }
            $choices += [pscustomobject]@{ model = $id; base = $base }
        }
    }
    if ($choices.Count -eq 0) { throw '沒有找到任何本機模型伺服器；請先啟動模型伺服器。' }
    $autoModel = ''
    $modelProperty = $found.PSObject.Properties['model']
    if ($null -ne $modelProperty -and $modelProperty.Value -is [string] -and $modelProperty.Value -cmatch '\A[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}\z') { $autoModel = $modelProperty.Value }
    $current = if ($pinned.Present) { [string]$pinned.Value.model } else { '' }
    $pick = $null
    if ($Model) {
        $pick = $choices | Where-Object { $_.model -ieq $Model } | Select-Object -First 1
        if (-not $pick) { throw "伺服器上沒有模型：$Model" }
    } else {
        Write-Host ''
        for ($i = 0; $i -lt $choices.Count; $i++) {
            $mark = if ($choices[$i].model -ieq $current) { '（目前設定）' } elseif ($autoModel -and $choices[$i].model -ieq $autoModel) { '（自動偵測會選）' } else { '' }
            Write-Host ("  [{0}] {1}  @ {2} {3}" -f ($i + 1), $choices[$i].model, $choices[$i].base, $mark)
        }
        Write-Host ''
        $answer = Read-Host '輸入要使用的模型編號（直接按 Enter 取消）'
        if ([string]::IsNullOrWhiteSpace($answer)) { Write-Host '未變更。'; Finish 0 }
        $index = 0
        if (-not [int]::TryParse($answer.Trim(), [ref]$index) -or $index -lt 1 -or $index -gt $choices.Count) { throw '編號無效，未變更。' }
        $pick = $choices[$index - 1]
    }
    if ($pick.model -notmatch '\A[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}\z') { throw '模型 ID 含不支援的字元，未變更。' }
    $selectionDirectory = Split-Path -Parent $selectionPath
    $document = [ordered]@{
        schema_version = 2; product_version = '2.1.3'; model = $pick.model; llama_base_url = $pick.base
        available_models = @($choices | ForEach-Object { $_.model }); selected_utc = (Get-Date).ToUniversalTime().ToString('o')
        source = 'desktop_model_selector'; preferred_model = ''
    }
    $encoded = [Text.UTF8Encoding]::new($false).GetBytes(($document | ConvertTo-Json -Depth 4))
    if ($encoded.Length -gt 16384) { throw 'MODEL_SELECTION_TOO_LARGE' }
    New-Item -ItemType Directory -Force -Path $selectionDirectory | Out-Null
    # Same-directory unique temp file, then ONE atomic replace/move. The recheck below only DETECTS observed drift (registry, explicit
    # markers, saved selection); it is NOT a cross-process lock, NOT exclusive writer ownership and NOT M2 admission. Only this
    # script's own temp file is ever removed; the user's selection is never deleted.
    $temporary = Join-Path $selectionDirectory ('v213-model-selection.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $created = $false
    $committed = $false
    try {
        $stream = [IO.FileStream]::new($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $created = $true
        try { $stream.Write($encoded, 0, $encoded.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        if (Test-PathPresent $registryPath) { throw 'REGISTRY_PRESENT_USE_EXE_MODEL_REGISTRY' }
        if ($null -ne [Environment]::GetEnvironmentVariable('V213_RUNTIME_BINDING_JSON') -or (Test-PathPresent $intentPath)) { throw 'EXPLICIT_INTENT_APPEARED' }
        $latest = Get-SelectionState $selectionPath
        if ($latest.Explicit) { throw 'EXPLICIT_INTENT_APPEARED' }
        if ($latest.Present -ne $pinned.Present -or $latest.Sha256 -cne $pinned.Sha256) { throw 'MODEL_SELECTION_CHANGED' }
        if ($latest.Present) { [IO.File]::Replace($temporary, $selectionPath, $null) } else { [IO.File]::Move($temporary, $selectionPath) }
        $committed = $true
    } catch {
        if ([string]$_.Exception.Message -cmatch '\A[A-Z][A-Z0-9_]{5,63}\z') { throw }
        throw 'MODEL_SELECTION_COMMIT_FAILED'
    } finally {
        if ($created -and -not $committed) { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
    }
    Write-Host ("已設定：{0} @ {1}" -f $pick.model, $pick.base) -ForegroundColor Green
    $task = Get-ScheduledTask -TaskName 'InvestorIntelligence-v213-FreeRelay' -ErrorAction SilentlyContinue
    if ($task) {
        $go = $Reconnect -or (-not $Model -and (Read-Host '要立即以此模型重新連線 LINE 問答嗎？(Y/N)') -match '^[Yy]')
        if ($go) { Start-ScheduledTask -TaskName 'InvestorIntelligence-v213-FreeRelay'; Write-Host '已重新啟動 LINE 問答連線（約 1–2 分鐘完成）。' -ForegroundColor Green }
    }
    Finish 0
} catch {
    Write-Host ('失敗：' + $_.Exception.Message) -ForegroundColor Red
    Finish 1
}
