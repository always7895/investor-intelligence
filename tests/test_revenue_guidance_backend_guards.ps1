# tests/test_revenue_guidance_backend_guards.ps1
#
# G2-32-GUARD - pins the pre-launch guards of Invoke-GuidanceObservedProcess in
# scripts/revenue_guidance_backend.psm1 with NO process, Add-Type, native, registry, network or file
# access: the omitted / null / empty / malformed / valid -MachineRunId distinction (presence of the
# parameter is the request; a typed null is never converted into "not requested"), the budget guard and
# the retained-owner guard. Every call below returns or throws BEFORE _GuidanceObservationDeclarations,
# so the C# observer type is never compiled; the test asserts that explicitly (type absence) before and
# after. A harness safety check refuses any call with budget > 0 that would not be stopped by one of the
# guards. Importing the module is native-free (its Add-Type sites live inside functions only).
#
# Not an H5 gate proof: inside H5 the PowerShell hosts are absent. Acceptance is a pinned-pwsh run outside
# H5 (record the pwsh path and sha256). Self-contained assertions, no Pester. Exits nonzero on the first
# assertion failure. These are guard examples, not certification of the native/process path.

$ErrorActionPreference = 'Continue'
$W = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:Rows = 0

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        Write-Output ("ASSERT_FAIL: {0}" -f $Message)
        exit 1
    }
    $script:Rows++
}

function Assert-Equal([object]$Actual, [object]$Expected, [string]$Message) {
    if ($Actual -ne $Expected) {
        Write-Output ("ASSERT_FAIL: {0} (expected [{1}], got [{2}])" -f $Message, $Expected, $Actual)
        exit 1
    }
    $script:Rows++
}

function Assert-NoObserverType([string]$When) {
    Assert-True (-not ('GuidanceProcessObservation' -as [type])) ("GuidanceProcessObservation type absent " + $When + " (no Add-Type ran)")
    Assert-True (-not ('GuidanceParentOrigin' -as [type])) ("GuidanceParentOrigin type absent " + $When + " (no native declaration ran)")
}

$validA = '0123456789abcdef0123456789abcdef'
$validB = '00000000000000000000000000000000'

Write-Output 'SETUP: import the backend module (native-free) and prove the clean starting state'
Assert-NoObserverType 'before import'
$modulePath = Join-Path (Join-Path $W 'scripts') 'revenue_guidance_backend.psm1'
try {
    Import-Module $modulePath -Force -DisableNameChecking -ErrorAction Stop
}
catch {
    Assert-True $false 'backend module imports without error'
}
$mod = Get-Module 'revenue_guidance_backend'
Assert-True ($null -ne $mod) 'backend module is loaded'
Assert-NoObserverType 'after import'
Assert-True ($null -ne (Get-Command Invoke-GuidanceObservedProcess -Module 'revenue_guidance_backend' -ErrorAction SilentlyContinue)) 'function exported'

function Get-OwnerState {
    & $mod { [pscustomobject]@{ Count = $script:ObservedGuidanceProcesses.Count } }
}

function Set-OwnerState([object[]]$Entries) {
    & $mod {
        param($items)
        $script:ObservedGuidanceProcesses.Clear()
        foreach ($i in $items) { $script:ObservedGuidanceProcesses.Add($i) }
    } $Entries
}

function Test-OwnerGuardWouldStop([string]$Label) {
    & $mod {
        param($l)
        ($script:ObservedGuidanceProcesses.Count -ge 16) -or (@($script:ObservedGuidanceProcesses | Where-Object { $_.Label -ceq $l }).Count -gt 0)
    } $Label
}

function Invoke-Guard {
    # $Machine: 'omit' leaves -MachineRunId off; otherwise the bound value (including $null and '').
    # Returns { Threw, Message, Result }. Refuses (ASSERT_FAIL) any call that no guard would stop.
    param([long]$Budget, [object]$Machine = 'omit', [bool]$MachineSupplied = $false, [string]$Label = 'GUARD_TEST_LABEL', [bool]$ExpectThrow = $false)
    $params = @{
        Label = $Label
        Executable = 'GUARD_TEST_NOT_AN_EXECUTABLE'
        Arguments = @('guard-test')
        WorkingDirectory = [System.IO.Path]::GetTempPath()
        RemainingMilliseconds = $Budget
    }
    if ($MachineSupplied) { $params['MachineRunId'] = $Machine }
    if ($Budget -gt 0 -and -not $ExpectThrow) {
        Assert-True ([bool](Test-OwnerGuardWouldStop $Label)) 'harness safety: a budget>0 call must be stopped by the owner guard'
    }
    $out = [pscustomobject]@{ Threw = $false; Message = ''; Result = $null }
    try { $out.Result = Invoke-GuidanceObservedProcess @params }
    catch { $out.Threw = $true; $out.Message = [string]$_.Exception.Message }
    $out
}

function Assert-NotAttempted([object]$Result, [string]$Status, [string]$Message) {
    Assert-True ($null -ne $Result) ($Message + ' returned a result')
    Assert-Equal $Result.Status $Status ($Message + ' status')
    Assert-Equal $Result.ExitCode 125 ($Message + ' exit 125')
    Assert-True ($Result.Attempted -is [bool] -and -not $Result.Attempted) ($Message + ' Attempted=false')
    Assert-True ($Result.Completed -is [bool] -and -not $Result.Completed) ($Message + ' Completed=false')
    Assert-Equal @($Result.Lines).Count 0 ($Message + ' no lines')
}

try {
    Assert-Equal (Get-OwnerState).Count 0 'owner list starts empty in the fresh module scope'

    Write-Output 'ROW 1: -MachineRunId omitted -> not requested; zero budget returns NOT_ATTEMPTED_BUDGET'
    $g = Invoke-Guard -Budget 0
    Assert-True (-not $g.Threw) 'omitted machine id never throws'
    Assert-NotAttempted $g.Result 'NOT_ATTEMPTED_BUDGET' 'row1'

    Write-Output 'ROW 2: present-but-null / empty / malformed -MachineRunId throws before the budget guard'
    $arabic = ([string][char]0x0661) * 32
    $malformed = @(
        [pscustomobject]@{ Name = 'null'; Value = $null },
        [pscustomobject]@{ Name = 'empty'; Value = '' },
        [pscustomobject]@{ Name = 'uppercase hex'; Value = $validA.ToUpperInvariant() },
        [pscustomobject]@{ Name = 'mixed case'; Value = 'A123456789abcdef0123456789abcdef' },
        [pscustomobject]@{ Name = '31 hex'; Value = $validA.Substring(0, 31) },
        [pscustomobject]@{ Name = '33 hex'; Value = $validA + 'a' },
        [pscustomobject]@{ Name = 'trailing newline'; Value = $validA + "`n" },
        [pscustomobject]@{ Name = 'trailing CRLF'; Value = $validA + "`r`n" },
        [pscustomobject]@{ Name = 'leading newline'; Value = "`n" + $validA },
        [pscustomobject]@{ Name = 'leading space'; Value = ' ' + $validA },
        [pscustomobject]@{ Name = 'trailing space'; Value = $validA + ' ' },
        [pscustomobject]@{ Name = 'non-hex letter'; Value = ('g' * 32) },
        [pscustomobject]@{ Name = 'dashed'; Value = '01234567-89ab-cdef-0123-456789abcdef' },
        [pscustomobject]@{ Name = 'non-ascii digits'; Value = $arabic },
        [pscustomobject]@{ Name = 'two ids'; Value = ($validA + $validB) }
    )
    foreach ($m in $malformed) {
        foreach ($budget in @(0L, 1000L)) {
            $label = ('row2 ' + $m.Name + ' budget=' + $budget)
            $g = Invoke-Guard -Budget $budget -Machine $m.Value -MachineSupplied $true -ExpectThrow $true
            Assert-True $g.Threw ($label + ' throws')
            Assert-Equal $g.Message 'MACHINE_INPUTS_UNAVAILABLE' ($label + ' exact bounded token')
            Assert-True ($null -eq $g.Result) ($label + ' returns no result')
        }
    }
    Assert-NoObserverType 'after the malformed rows'

    Write-Output 'ROW 3: valid 32 lowercase hex with zero budget -> NOT_ATTEMPTED_BUDGET (machine id accepted, never launched)'
    foreach ($valid in @($validA, $validB)) {
        $g = Invoke-Guard -Budget 0 -Machine $valid -MachineSupplied $true
        Assert-True (-not $g.Threw) 'valid machine id with zero budget never throws'
        Assert-NotAttempted $g.Result 'NOT_ATTEMPTED_BUDGET' 'row3'
    }
    Assert-Equal (Get-OwnerState).Count 0 'row3 budget guard does not touch the owner list'

    Write-Output 'ROW 4: retained-owner guard (same label, or 16 retained owners) returns NOT_ATTEMPTED_OWNER_RETAINED'
    Set-OwnerState @(@{ Label = 'GUARD_TEST_LABEL' })
    $g = Invoke-Guard -Budget 1000
    Assert-True (-not $g.Threw) 'row4 same label (machine id omitted) does not throw'
    Assert-NotAttempted $g.Result 'NOT_ATTEMPTED_OWNER_RETAINED' 'row4 same label'
    $g = Invoke-Guard -Budget 1000 -Machine $validA -MachineSupplied $true
    Assert-True (-not $g.Threw) 'row4 same label with a valid machine id does not throw'
    Assert-NotAttempted $g.Result 'NOT_ATTEMPTED_OWNER_RETAINED' 'row4 same label + valid machine id'
    $g = Invoke-Guard -Budget 1000 -Machine 'NOT-HEX' -MachineSupplied $true -ExpectThrow $true
    Assert-True ($g.Threw -and $g.Message -ceq 'MACHINE_INPUTS_UNAVAILABLE') 'row4 malformed machine id still throws first despite a retained owner'
    $g = Invoke-Guard -Budget 0 -Label 'GUARD_TEST_LABEL'
    Assert-NotAttempted $g.Result 'NOT_ATTEMPTED_BUDGET' 'row4 budget guard precedes the owner guard'
    Assert-Equal (Get-OwnerState).Count 1 'row4 owner list unchanged by the guards'

    $entries = @()
    foreach ($i in 1..16) { $entries += , @{ Label = ('OTHER_OWNER_' + $i) } }
    Set-OwnerState $entries
    Assert-Equal (Get-OwnerState).Count 16 'row4 sixteen retained owners installed'
    $g = Invoke-Guard -Budget 1000 -Label 'GUARD_TEST_UNRELATED_LABEL'
    Assert-True (-not $g.Threw) 'row4 sixteen owners (unrelated label) does not throw'
    Assert-NotAttempted $g.Result 'NOT_ATTEMPTED_OWNER_RETAINED' 'row4 sixteen retained owners'
    Assert-Equal (Get-OwnerState).Count 16 'row4 owner list unchanged by the 16-owner guard'
    Assert-NoObserverType 'after the owner rows'
}
finally {
    # Restore the module-scope state, then drop the module so nothing leaks into other tests.
    try { & $mod { $script:ObservedGuidanceProcesses.Clear() } } catch { }
    Remove-Module 'revenue_guidance_backend' -Force -ErrorAction SilentlyContinue
}

Assert-NoObserverType 'at the end'
Write-Output ('pwsh {0} {1}' -f $PSVersionTable.PSVersion, $PSVersionTable.PSEdition)
Write-Output ('BACKEND GUARDS: {0} rows passed (no process, Add-Type or native call)' -f $script:Rows)
exit 0
