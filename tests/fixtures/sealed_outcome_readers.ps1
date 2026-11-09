param([Parameter(Mandatory=$true)][string]$ProjectRoot,
      [Parameter(Mandatory=$true)][string]$CasesPath)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$cases = Get-Content -LiteralPath $CasesPath -Raw -Encoding utf8 | ConvertFrom-Json
$answers = [Collections.Generic.List[object]]::new()
foreach ($operation in @('SYNC','WATCHDOG')) {
    # Separate scopes retain each caller's own integer/path guard definitions.
    & {
        param($Operation, $Cases, $Answers)
        if ($Operation -ceq 'SYNC') {
            $source = Join-Path $ProjectRoot 'scripts/run_production_sealed_refresh.ps1'
            $names = @('Assert-PlainLocalRefreshPath','Test-OutcomeInteger','Read-SafeSyncOutcome')
        } else {
            $source = Join-Path $ProjectRoot 'scripts/freshness_watchdog.ps1'
            $names = @('Assert-PlainLocalPath','Test-OutcomeInteger','Read-SafeWatchdogOutcome')
        }
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$parseErrors)
        if (@($parseErrors).Count -ne 0) { throw 'OUTCOME_SOURCE_SYNTAX_INVALID' }
        foreach ($name in $names) {
            $wanted = $name
            $definitions = @($ast.FindAll({param($node)
                $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $wanted
            }, $true))
            if ($definitions.Count -ne 1) { throw 'OUTCOME_FUNCTION_ABSENT_OR_AMBIGUOUS' }
            # Original definitions only; NEVER dot-source or execute script entrypoints.
            Invoke-Expression $definitions[0].Extent.Text
        }
        foreach ($case in $Cases) {
            if ($case.operation -cne $Operation) { continue }
            try {
                $record = if ($Operation -ceq 'SYNC') {
                    Read-SafeSyncOutcome $case.path $case.expected_run
                } else {
                    Read-SafeWatchdogOutcome $case.path
                }
                $Answers.Add([pscustomobject]@{name=$case.name;accepted=$true;record=$record})
            } catch {
                # No exception messages, paths or file contents escape the probe.
                $Answers.Add([pscustomobject]@{name=$case.name;accepted=$false;record=$null})
            }
        }
    } $operation $cases $answers
}
ConvertTo-Json -InputObject @($answers.ToArray()) -Depth 30 -Compress
