# Investor Intelligence: choose the local model when several are served (operator 2026-09-26).
# Lists every model on the loopback model servers (scripts/local_model_endpoint.py --all) and saves the choice as the
# launcher selection (UserData\config\v213-model-selection.json). The launcher, the hourly translator, the Q&A bridge
# and the relay all try the saved model first; a model that later disappears falls back to auto-detection.
[CmdletBinding()]
param([string]$Model = '', [switch]$Reconnect, [switch]$NoPause)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PROJECT_PYTHON) { $env:PROJECT_PYTHON } else { 'python' }
$selectionPath = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\v213-model-selection.json'
function Finish([int]$Code) {
    if (-not $NoPause) { Write-Host ''; Write-Host '按任意鍵關閉視窗…'; [void][Console]::ReadKey($true) }
    exit $Code
}
try {
    Write-Host '正在掃描本機模型伺服器…' -ForegroundColor Cyan
    $raw = & $python (Join-Path $root 'scripts\local_model_endpoint.py') --all 2>$null
    $found = ($raw | Select-Object -Last 1) | ConvertFrom-Json
    $choices = @()
    foreach ($server in @($found.servers)) {
        foreach ($id in @($server.models)) { $choices += [pscustomobject]@{ model = [string]$id; base = [string]$server.base_url } }
    }
    if ($choices.Count -eq 0) { throw '沒有找到任何本機模型伺服器；請先啟動模型伺服器。' }
    $current = ''
    if (Test-Path -LiteralPath $selectionPath -PathType Leaf) {
        try { $current = [string]((Get-Content -LiteralPath $selectionPath -Raw -Encoding utf8 | ConvertFrom-Json).model) } catch { }
    }
    $pick = $null
    if ($Model) {
        $pick = $choices | Where-Object { $_.model -ieq $Model } | Select-Object -First 1
        if (-not $pick) { throw "伺服器上沒有模型：$Model" }
    } else {
        Write-Host ''
        for ($i = 0; $i -lt $choices.Count; $i++) {
            $mark = if ($choices[$i].model -ieq $current) { '（目前設定）' } elseif ($choices[$i].model -ieq [string]$found.model) { '（自動偵測會選）' } else { '' }
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
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $selectionPath) | Out-Null
    [ordered]@{
        schema_version = 2; product_version = '2.1.3'; model = $pick.model; llama_base_url = $pick.base
        available_models = @($choices | ForEach-Object { $_.model }); selected_utc = (Get-Date).ToUniversalTime().ToString('o')
        source = 'desktop_model_selector'; preferred_model = ''
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $selectionPath -Encoding utf8
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
