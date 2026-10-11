# Transaction library of scripts/register_taifex_options_eod_task.ps1 (O10, operator-authorized 2026-10-11).
# Kept in its own file so tests can drive it with a fake task scheduler (functions shadow the ScheduledTasks cmdlets).
#
# Renders the reviewed disabled task template under scripts/task-templates (the template itself stays inert)
# into a registrable definition: every placeholder resolved to an absolute path, task and trigger enabled, daily local
# trigger. The task only COLLECTS dataset 11320 (EOD) observations into a local file; it never publishes, never writes KV
# and never sends LINE. Public EOD/Delta display stays blocked by O12.

. (Join-Path $PSScriptRoot 'sealed_freshness_task_transaction.ps1')   # Get-SealedFreshnessTaskPreimage

$script:TaifexTaskName = 'InvestorIntelligence-TaifexOptionsEod'
$script:TaifexTaskNs = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
# The 08:00 InvestorDailyBriefing / Worker 08:00 window is never used (07:45-08:30 refused).
$script:TaifexForbiddenFrom = 7 * 60 + 45
$script:TaifexForbiddenTo = 8 * 60 + 30
# Directory names that denote Production/publication storage; an output path containing one is refused.
$script:TaifexForbiddenSegments = '^(production|prod|kv|public|publish|published|snapshots?|sealed|worker|cloud|_workspace|_archive|\.git)$'

function Get-TaifexUnresolvedPlaceholders([string]$Text) {
    return @([regex]::Matches($Text, '__[A-Z][A-Z0-9_]*__') | ForEach-Object { $_.Value } | Select-Object -Unique)
}

function Test-TaifexPathInside([string]$Path, [string]$Parent) {
    $p = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/') + '\'
    $q = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/') + '\'
    return $p.StartsWith($q, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-TaifexInputs {
    param([string]$PythonPath, [string]$SourceRoot, [string]$OutputFile, [string]$DataRoot, [string]$RuntimeRoot, [string]$DailyTime)
    foreach ($value in @($PythonPath, $SourceRoot, $OutputFile, $DataRoot)) {
        if ([string]::IsNullOrWhiteSpace($value)) { throw 'TAIFEX_TASK_INPUT_MISSING' }
        if ($value -match '["\r\n<>|*?]' -or $value -match '\.\.' -or @(Get-TaifexUnresolvedPlaceholders $value).Count) { throw 'TAIFEX_TASK_PATH_INVALID' }
        if (-not [IO.Path]::IsPathRooted($value)) { throw 'TAIFEX_TASK_PATH_NOT_ABSOLUTE' }
    }
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'TAIFEX_TASK_PYTHON_MISSING' }
    if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot 'scripts\fetch_public_source_observations.py') -PathType Leaf)) {
        throw 'TAIFEX_TASK_COLLECTOR_MISSING'
    }
    if ($DailyTime -notmatch '^([01]\d|2[0-3]):[0-5]\d$') { throw 'TAIFEX_TASK_TIME_INVALID' }
    $minutes = [int]$DailyTime.Substring(0, 2) * 60 + [int]$DailyTime.Substring(3, 2)
    if ($minutes -ge $script:TaifexForbiddenFrom -and $minutes -le $script:TaifexForbiddenTo) { throw 'TAIFEX_TASK_TIME_IN_0800_WINDOW' }
    foreach ($payload in @($SourceRoot, $RuntimeRoot)) {
        if (-not $payload) { continue }
        $full = [IO.Path]::GetFullPath($payload)
        $isCheckout = Test-Path -LiteralPath (Join-Path $full '.git')
        foreach ($segment in ($full.Substring([IO.Path]::GetPathRoot($full).Length) -split '[\\/]')) {
            if ($segment -match '^(_workspace|_archive|\.git)$') { $isCheckout = $true }
        }
        if ($isCheckout) { throw 'TAIFEX_TASK_SOURCE_IS_CHECKOUT' }
    }
    $output = [IO.Path]::GetFullPath($OutputFile)
    if (-not (Test-TaifexPathInside $output $DataRoot)) { throw 'TAIFEX_TASK_OUTPUT_OUTSIDE_DATA_ROOT' }
    foreach ($payload in @($SourceRoot, $RuntimeRoot)) {
        if ($payload -and ((Test-TaifexPathInside $output $payload) -or (Test-TaifexPathInside $DataRoot $payload) -or (Test-TaifexPathInside $payload $DataRoot))) {
            throw 'TAIFEX_TASK_OUTPUT_INSIDE_PAYLOAD'
        }
    }
    foreach ($segment in ($output.Substring([IO.Path]::GetPathRoot($output).Length) -split '[\\/]')) {
        if ($segment -match $script:TaifexForbiddenSegments) { throw 'TAIFEX_TASK_OUTPUT_IN_PRODUCTION_STORAGE' }
    }
    if ([IO.Path]::GetExtension($output) -ne '.json') { throw 'TAIFEX_TASK_OUTPUT_EXTENSION' }
}

function ConvertTo-TaifexForwardSlash([string]$Path) { return ([IO.Path]::GetFullPath($Path)) -replace '\\', '/' }

function Build-TaifexTaskXml {
    param([Parameter(Mandatory)][string]$TemplateText, [Parameter(Mandatory)][string]$PythonPath, [Parameter(Mandatory)][string]$SourceRoot,
          [Parameter(Mandatory)][string]$OutputFile, [Parameter(Mandatory)][string]$DailyTime, [datetime]$Today = (Get-Date))
    $doc = New-Object System.Xml.XmlDocument
    $doc.LoadXml($TemplateText)
    $ns = New-Object System.Xml.XmlNamespaceManager $doc.NameTable
    $ns.AddNamespace('t', $script:TaifexTaskNs)
    $sourceFwd = (ConvertTo-TaifexForwardSlash $SourceRoot).TrimEnd('/')
    $outputFwd = ConvertTo-TaifexForwardSlash $OutputFile
    $exec = $doc.SelectSingleNode('//t:Exec', $ns)
    $command = $exec.SelectSingleNode('t:Command', $ns)
    $command.InnerText = $command.InnerText.Replace('__PROJECT_PYTHON__', [IO.Path]::GetFullPath($PythonPath))
    $workDir = $exec.SelectSingleNode('t:WorkingDirectory', $ns)
    $workDir.InnerText = $workDir.InnerText.Replace('__SOURCE_ROOT__', ([IO.Path]::GetFullPath($SourceRoot)).TrimEnd('\'))
    $argNode = $exec.SelectSingleNode('t:Arguments', $ns)
    $argNode.InnerText = $argNode.InnerText.Replace('__SOURCE_ROOT__', $sourceFwd).Replace('__LOCAL_OUTPUT__', $outputFwd)
    $when = [datetime]::ParseExact(('{0:yyyy-MM-dd}T{1}:00' -f $Today, $DailyTime), 'yyyy-MM-ddTHH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
    $trigger = $doc.SelectSingleNode('//t:CalendarTrigger', $ns)
    $trigger.SelectSingleNode('t:StartBoundary', $ns).InnerText = $when.ToString('yyyy-MM-ddTHH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
    $trigger.SelectSingleNode('t:Enabled', $ns).InnerText = 'true'
    $doc.SelectSingleNode('//t:Settings/t:Enabled', $ns).InnerText = 'true'
    # StartWhenAvailable stays at the reviewed template value (false): no catch-up run can land in the refused 07:45-08:30 window.
    # The template's "disabled" header comment must not describe the live task.
    foreach ($c in @($doc.SelectNodes('//comment()'))) { [void]$c.ParentNode.RemoveChild($c) }
    $text = $doc.OuterXml
    $left = @(Get-TaifexUnresolvedPlaceholders $text)
    if ($left.Count) { throw "TAIFEX_TASK_PLACEHOLDER_UNRESOLVED: $($left -join ',')" }
    return $text
}

function Get-TaifexExpected([string]$Xml) {
    $doc = New-Object System.Xml.XmlDocument
    $doc.LoadXml($Xml)
    $ns = New-Object System.Xml.XmlNamespaceManager $doc.NameTable
    $ns.AddNamespace('t', $script:TaifexTaskNs)
    return @{
        Execute = $doc.SelectSingleNode('//t:Exec/t:Command', $ns).InnerText
        Arguments = $doc.SelectSingleNode('//t:Exec/t:Arguments', $ns).InnerText
        WorkingDirectory = $doc.SelectSingleNode('//t:Exec/t:WorkingDirectory', $ns).InnerText
        StartBoundary = $doc.SelectSingleNode('//t:CalendarTrigger/t:StartBoundary', $ns).InnerText
    }
}

function Assert-TaifexReadback([string]$Name, [hashtable]$Expected) {
    $task = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    $action = @($task.Actions) | Select-Object -First 1
    if (-not $action -or [string]$action.Execute -ne $Expected.Execute) { throw 'TAIFEX_TASK_READBACK_EXECUTE' }
    if ([string]$action.Arguments -cne $Expected.Arguments) { throw 'TAIFEX_TASK_READBACK_ARGUMENTS' }
    if ([string]$action.WorkingDirectory -ne $Expected.WorkingDirectory) { throw 'TAIFEX_TASK_READBACK_WORKDIR' }
    if (-not $task.Settings.Enabled) { throw 'TAIFEX_TASK_READBACK_DISABLED' }
    if ([string]$task.Principal.LogonType -ne 'Interactive') { throw 'TAIFEX_TASK_READBACK_LOGON' }
    $trigger = @($task.Triggers) | Select-Object -First 1
    if (-not $trigger -or -not $trigger.Enabled) { throw 'TAIFEX_TASK_READBACK_TRIGGER_DISABLED' }
    $inv = [Globalization.CultureInfo]::InvariantCulture
    if (([datetime]$trigger.StartBoundary).ToString('HH:mm', $inv) -ne ([datetime]$Expected.StartBoundary).ToString('HH:mm', $inv)) { throw 'TAIFEX_TASK_READBACK_TIME' }
    if ([string]$action.Arguments -match '__[A-Z][A-Z0-9_]*__' -or [string]$action.Execute -match '__[A-Z][A-Z0-9_]*__') { throw 'TAIFEX_TASK_READBACK_PLACEHOLDER' }
}

function Invoke-TaifexTaskRegistration {
    param([Parameter(Mandatory)][string]$TemplatePath, [Parameter(Mandatory)][string]$PythonPath, [Parameter(Mandatory)][string]$SourceRoot,
          [Parameter(Mandatory)][string]$DataRoot, [string]$RuntimeRoot = '', [string]$DailyTime = '17:30', [string]$OutputFile = '')
    if (-not $OutputFile) { $OutputFile = Join-Path $DataRoot 'taifex-options-eod-latest.json' }
    Assert-TaifexInputs -PythonPath $PythonPath -SourceRoot $SourceRoot -OutputFile $OutputFile -DataRoot $DataRoot -RuntimeRoot $RuntimeRoot -DailyTime $DailyTime
    if (-not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) { throw 'TAIFEX_TASK_TEMPLATE_MISSING' }
    $xml = Build-TaifexTaskXml -TemplateText ([IO.File]::ReadAllText($TemplatePath)) -PythonPath $PythonPath -SourceRoot $SourceRoot -OutputFile $OutputFile -DailyTime $DailyTime
    $expected = Get-TaifexExpected $xml
    try { $preimage = Get-SealedFreshnessTaskPreimage $script:TaifexTaskName }
    catch { throw "TAIFEX_TASK_UNCHANGED; $($_.Exception.Message)" }
    try {
        # The output directory is created only after every check passed; it is a local data directory outside the payload.
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent ([IO.Path]::GetFullPath($OutputFile))) | Out-Null
        Register-ScheduledTask -TaskName $script:TaifexTaskName -Xml $xml -Force -ErrorAction Stop | Out-Null
        Assert-TaifexReadback $script:TaifexTaskName $expected
    } catch {
        $failure = $_.Exception.Message
        $rollbackFailed = $false
        try {
            if ($preimage.Exists) { Register-ScheduledTask -TaskName $script:TaifexTaskName -Xml $preimage.Xml -Force -ErrorAction Stop | Out-Null }
            else {
                $present = $true
                try { Get-ScheduledTask -TaskName $script:TaifexTaskName -ErrorAction Stop | Out-Null }
                catch { if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { $present = $false } else { throw } }
                if ($present) { Unregister-ScheduledTask -TaskName $script:TaifexTaskName -Confirm:$false -ErrorAction Stop }
            }
        } catch { $rollbackFailed = $true }
        if ($rollbackFailed) { throw "TAIFEX_TASK_REGISTER_FAILED; rollback_unverified=true. $failure" }
        throw "TAIFEX_TASK_REGISTER_FAILED; rollback completed. $failure"
    }
    return [pscustomobject]@{ TaskName = $script:TaifexTaskName; Expected = $expected; OutputFile = [IO.Path]::GetFullPath($OutputFile); Xml = $xml }
}

function Invoke-TaifexTaskUnregistration {
    $name = $script:TaifexTaskName
    try { $preimage = Get-SealedFreshnessTaskPreimage $name }
    catch { throw "TAIFEX_TASK_UNCHANGED; $($_.Exception.Message)" }
    if (-not $preimage.Exists) { return [pscustomobject]@{ Removed = $false; Reason = 'ALREADY_ABSENT' } }
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop
    $stillPresent = $true
    try { Get-ScheduledTask -TaskName $name -ErrorAction Stop | Out-Null }
    catch { if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { $stillPresent = $false } else { throw } }
    if ($stillPresent) { throw 'TAIFEX_TASK_STILL_PRESENT' }
    return [pscustomobject]@{ Removed = $true; Reason = 'UNREGISTERED' }
}
