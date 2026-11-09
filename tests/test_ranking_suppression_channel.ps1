# Synthetic private-observation frame parser only; no process, native, network or installed state.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Import-Module (Join-Path $root 'scripts/revenue_guidance_backend.psm1') -Force -DisableNameChecking
$module = Get-Module revenue_guidance_backend
function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw ('ASSERT_FAIL: ' + $Message) }
}
try {
    & $module { _GuidanceObservationDeclarations } # In-memory managed parser; does not launch a process.
    $run = '0123456789abcdef0123456789abcdef'
    $good = 'GUIDANCE_MACHINE_RETAINED_V1|' + $run + '|NO_CHANGE'
    $cases = @(
        @{ Text = ($good + "`n"); Valid = $true },
        @{ Text = ("unrelated diagnostic`n" + $good + "`r`n"); Valid = $true },
        @{ Text = ($good + "`n" + $good + "`n"); Valid = $false },
        @{ Text = ($good.Replace($run, ('a' * 32)) + "`n"); Valid = $false },
        @{ Text = ($good.Replace('NO_CHANGE', 'APPROVED') + "`n"); Valid = $false },
        @{ Text = $good; Valid = $false },
        @{ Text = ($good + ('x' * 600) + "`n"); Valid = $false },
        @{ Text = ($good + "`nGUIDANCE_MACHINE_ERROR_V1|" + $run + "|MACHINE_EXPORT_UNAVAILABLE`n"); Valid = $false },
        @{ Text = ('GUIDANCE_MACHINE_ERROR_V1|' + $run + "|MACHINE_EXPORT_UNAVAILABLE`n" + $good + "`n"); Valid = $false },
        @{ Text = ($good + "`nGUIDANCE_MACHINE_RESULT_V1|" + $run + '|' + ('b' * 32) + '|' + ('c' * 64) + '|' + ('d' * 64) + "`n"); Valid = $false }
    )
    foreach ($case in $cases) {
        $capture = [GuidanceProcessObservation+MachineCapture]::new($run)
        $bytes = [Text.Encoding]::UTF8.GetBytes($case.Text)
        $memory = [IO.MemoryStream]::new($bytes)
        $reader = [IO.StreamReader]::new($memory)
        try {
            [GuidanceProcessObservation]::DrainMachine($reader, $capture).GetAwaiter().GetResult()
        } finally { $reader.Dispose(); $memory.Dispose() }
        $accepted = $capture.Seen -and $capture.Retained -and -not $capture.Invalid -and $null -eq $capture.ErrorReason
        Assert-True ($accepted -eq $case.Valid) 'retained frame must be exact, unique, complete and bound to expected run'
        if ($case.Valid) {
            Assert-True ($null -eq $capture.Token -and $null -eq $capture.BodySha256 -and $null -eq $capture.BindingSha256) 'historical skip never synthesizes fresh bundle evidence'
        }
    }
    Write-Output 'RANKING SUPPRESSION CHANNEL: synthetic frame cases passed'
} finally { Remove-Module revenue_guidance_backend -Force }
