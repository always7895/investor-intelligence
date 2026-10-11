# Opt-in registration of the local TAIFEX dataset 11320 EOD collection task (O10; operator authorization 2026-10-11,
# R/OPERATOR-DECISION-ROLLOUT-SCOPE-EXPANSION-20261011.txt). Idempotent; rolls back to the captured preimage on any
# readback failure; -Unregister removes the task (collected files stay).
#
#   * Task: InvestorIntelligence-TaifexOptionsEod, one daily trigger (default 17:30 local), least privilege,
#     interactive token, no password, 5 minute limit.
#   * Action: <python> -I -B -X utf8 <SourceRoot>/scripts/fetch_public_source_observations.py --fetch --source
#     taifex_options_eod --output <DataRoot>/taifex-options-eod-latest.json (atomic whole-file replace, one public GET).
#   * Output: %LOCALAPPDATA%\InvestorIntelligence\local-observations\taifex, outside the installed payload.
#   * Nothing here publishes, writes KV, sends LINE or touches credentials. Public EOD/Delta display stays blocked (O12).
[CmdletBinding()]
param(
    [string]$SourceRoot = '',
    [string]$PythonPath = '',
    [string]$DataRoot = '',
    [string]$RuntimeRoot = '',
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$DailyTime = '17:30',
    [switch]$ValidateOnly,
    [switch]$Unregister)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'taifex_options_eod_task.ps1')

if ($Unregister) {
    $result = Invoke-TaifexTaskUnregistration
    $receipt = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\status\taifex-options-eod-task.json'
    if (Test-Path -LiteralPath $receipt -PathType Leaf) {
        [ordered]@{
            schemaVersion = 1
            taskName = $script:TaifexTaskName
            taskPresent = $false
            unregisteredUtc = (Get-Date).ToUniversalTime().ToString('o')
            removed = $result.Removed
            reason = $result.Reason
            productionMutation = $false
            scheduleMutation = $result.Removed
        } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receipt -Encoding utf8
    }
    Write-Host ("TAIFEX_OPTIONS_EOD_TASK_UNREGISTER = PASS; removed={0}; reason={1}" -f $result.Removed, $result.Reason) -ForegroundColor Green
    exit 0
}

if ([string]::IsNullOrWhiteSpace($SourceRoot)) { $SourceRoot = Split-Path -Parent $PSScriptRoot }
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) { $RuntimeRoot = $SourceRoot }
if ([string]::IsNullOrWhiteSpace($DataRoot)) { $DataRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\local-observations\taifex' }
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = [string]$env:PROJECT_PYTHON
    if ([string]::IsNullOrWhiteSpace($PythonPath)) {
        $found = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($found) { $PythonPath = $found.Source }
    }
}
$template = Join-Path $PSScriptRoot 'task-templates\taifex-options-eod.disabled.xml'

if ($ValidateOnly) {
    $outputFile = Join-Path $DataRoot 'taifex-options-eod-latest.json'
    Assert-TaifexInputs -PythonPath $PythonPath -SourceRoot $SourceRoot -OutputFile $outputFile -DataRoot $DataRoot -RuntimeRoot $RuntimeRoot -DailyTime $DailyTime
    $xml = Build-TaifexTaskXml -TemplateText ([IO.File]::ReadAllText($template)) -PythonPath $PythonPath -SourceRoot $SourceRoot -OutputFile $outputFile -DailyTime $DailyTime
    $expected = Get-TaifexExpected $xml
    Write-Host ("TASK_ACTION {0}: {1} {2}" -f $script:TaifexTaskName, $expected.Execute, $expected.Arguments)
    Write-Host "TAIFEX_OPTIONS_EOD_TASK_VALIDATE = PASS; daily=$DailyTime; production_mutation=false; schedule_mutation=false" -ForegroundColor Green
    exit 0
}

$registered = Invoke-TaifexTaskRegistration -TemplatePath $template -PythonPath $PythonPath -SourceRoot $SourceRoot -DataRoot $DataRoot -RuntimeRoot $RuntimeRoot -DailyTime $DailyTime

$statusDir = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\status'
New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
[ordered]@{
    schemaVersion = 1
    registeredUtc = (Get-Date).ToUniversalTime().ToString('o')
    taskName = $registered.TaskName
    dailyLocalTime = $DailyTime
    source = 'taifex_options_eod'
    dataset = '11320'
    outputFile = $registered.OutputFile
    publicationEligible = $false
    productionMutation = $false
    scheduleMutation = $true
    directKvWrite = $false
    lineDelivery = $false
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $statusDir 'taifex-options-eod-task.json') -Encoding utf8

Write-Host "TAIFEX_OPTIONS_EOD_TASK = PASS; daily $DailyTime local; local collection only." -ForegroundColor Green
