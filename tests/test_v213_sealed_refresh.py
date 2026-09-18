"""Actual source publication/scheduled callers; persistent synthetic transport only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEALED_SOURCE = ROOT / 'scripts/v213_sealed_refresh.ps1'
CANARIES = ('SYNTHETIC_CANARY_STDOUT_NOISY', 'SYNTHETIC_CANARY_STDERR_NOISY',
            'SYNTHETIC_CANARY_THROW_MUST_NOT_LEAK')
_spec = importlib.util.spec_from_file_location('sealed_native_fixtures', ROOT / 'tests/installer_parse_harness.py')
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)


def _u16_units(text):
    # .NET String.Length counts UTF-16 code units (Chars), not Unicode code
    # points; non-BMP characters are 2 units in .NET but 1 code point in
    # Python. This reference must match the .NET fit arithmetic exactly.
    return len(text.encode('utf-16-le')) // 2


def reference_commit_summary(records, cap=8192):
    # Python reference of the bounded per-record summary rule: presence flags
    # are maintained for every record; a record is admitted whole only when
    # its normalized form (CRLF/CR -> LF) plus the trailing LF fits in the
    # remaining UTF-16 code unit capacity; the first non-fitting record
    # freezes the content summary (truncated=true). output_bytes/lines/hash
    # describe the same collected content.
    builder = []
    builder_units = 0
    truncated = False
    stdout_present = False
    stderr_present = False
    for is_error, text in records:
        if is_error:
            stderr_present = True
        else:
            stdout_present = True
        if truncated or not text:
            continue
        normalized = text.replace('\r\n', '\n').replace('\r', '\n')
        units = _u16_units(normalized)
        if builder_units + units + 1 > cap:
            truncated = True
            continue
        builder.append(normalized)
        builder_units += units + 1
    content = ''.join(x + '\n' for x in builder)
    payload = content.encode('utf-8')
    return {
        'stdout_present': stdout_present,
        'stderr_present': stderr_present,
        'output_bytes': len(payload),
        'output_lines': sum(1 for line in content.split('\n') if line),
        'output_sha256': hashlib.sha256(payload).hexdigest(),
        'truncated': truncated,
    }

SYNC = r"""param($Action,$ProjectRoot,$BundlePath,$ExpectedBundleSha256,$LocalConfigPath,$ResultPath,$TransactionId,$RunId)
Add-Content -LiteralPath (Join-Path $ProjectRoot 'actions.txt') $Action
if($Action-eq'Commit'){
 $b=Get-Content -LiteralPath $BundlePath -Raw|ConvertFrom-Json
 if((Get-FileHash -LiteralPath $BundlePath).Hash.ToLowerInvariant()-cne$ExpectedBundleSha256){throw 'wrong sealed bytes'}
 $r=@{transaction_id=$b.transaction_id;run_id=$b.run_id;status='accepted';pointer_written_last=$true;object_count=14;objects_read_back=14;rollback_available=$true;idempotent_replay=$false}
 switch($env:FIXTURE_CASE){
  'commit_transport_error' {
   Write-Output "transport prelude`r`nSYNTHETIC_SECRET_MUST_NOT_PERSIST"
   Write-Error -Message 'https://fixture.invalid Authorization Bearer token cookie LINE_CHANNEL LOCAL_LLM_SHARED_SECRET' -ErrorAction Continue
   throw 'SYNTHETIC_SECRET_MUST_NOT_PERSIST'
  }
  'readback' {$r.objects_read_back=13}
  'boolean' {$r.pointer_written_last='True'}
  'identity_boolean' {$r.transaction_id=$true;$r.run_id=$true}
  'status_boolean' {$r.status=$true}
  'upload_count' {$r.object_count=7;$r.objects_read_back=7}
  'unsealed_count' {$r.object_count=13;$r.objects_read_back=13}
  'extra_count' {$r.object_count=15;$r.objects_read_back=15}
  'string_count' {$r.object_count='14';$r.objects_read_back='14'}
  'boolean_count' {$r.object_count=$true;$r.objects_read_back=$true}
  'zero_replay' {$r.object_count=0;$r.idempotent_replay=$true}
  'positive_replay' {$r.idempotent_replay=$true}
  'string_replay' {$r.idempotent_replay='false'}
  'missing_replay' {$r.Remove('idempotent_replay')}
  'commit_noisy_exit0' {
   Write-Output 'SYNTHETIC_CANARY_STDOUT_NOISY'
   Write-Error -Message 'SYNTHETIC_CANARY_STDERR_NOISY' -ErrorAction Continue
  }
  'commit_noisy_nonzero' {
   Write-Output 'SYNTHETIC_CANARY_STDOUT_NOISY'
   Write-Error -Message 'SYNTHETIC_CANARY_STDERR_NOISY' -ErrorAction Continue
  }
  'commit_noisy_throw' {
   Write-Output 'SYNTHETIC_CANARY_STDOUT_NOISY'
   Write-Error -Message 'SYNTHETIC_CANARY_STDERR_NOISY' -ErrorAction Continue
   throw 'SYNTHETIC_CANARY_THROW_MUST_NOT_LEAK'
  }
  'cap_no_output' {
  }
  'cap_many_short' {
   for($i=0;$i-lt2000;$i++){Write-Output ('R{0:D4}' -f $i)}
   Write-Error -Message 'LATE_STDERR_AFTER_TRUNCATION' -ErrorAction Continue
  }
  'cap_oversized_single' {
   Write-Output (('X'*10000)+'OVERSIZED_MARKER_MUST_NOT_LEAK'+('X'*9995))
  }
  'cap_exact' {
   for($i=0;$i-lt1024;$i++){Write-Output ('A'*7)}
  }
  'cap_cjk_crlf' {
   Write-Output "重電`r`n設備"
   Write-Output ''
   Write-Output 'plain'
  }
  'cap_crlf_shrink' {
   Write-Output ("A`r`n"*3000)
  }
  'cap_norm_exact_fit' {
   Write-Output ('A'*8000)
   Write-Output ('B'*190)
  }
  'cap_norm_exact_over' {
   Write-Output ('A'*8000)
   Write-Output ('B'*191)
  }
  'cap_nonbmp_fit' {
   Write-Output ('𝄞'*4000)
  }
  'cap_nonbmp_over' {
   Write-Output ('𝄞'*4100)
  }
  'aux_streams' {
   $InformationPreference='Continue'
   Write-Warning 'SYNTHETIC_CANARY_WARNING_AUX'
   Write-Verbose 'SYNTHETIC_CANARY_VERBOSE_AUX' -Verbose
   # PS5.1 NonInteractive throws after emitting the stream-5 DebugRecord;
   # the guard keeps the child alive on both hosts.
   try { Write-Debug 'SYNTHETIC_CANARY_DEBUG_AUX' -Debug } catch { }
   Write-Information 'SYNTHETIC_CANARY_INFORMATION_AUX'
   Write-Host 'SYNTHETIC_CANARY_HOST_AUX'
  }
 }
}elseif($Action-eq'Finalize'){
 if($env:FIXTURE_CASE-in@('finalize','rollback')){exit 8}
 $r=@{transaction_id=$TransactionId;run_id=$RunId;status='finalized';rollback_handle_deleted=$true}
}else{
 if($Action-cne'Rollback'){throw 'UNEXPECTED_ACTION'}
 if($env:FIXTURE_CASE-eq'rollback'){exit 9}
 $r=@{transaction_id=$TransactionId;run_id=$RunId;status='rolled_back';exact_pointer_restored=$true}
}
$r|ConvertTo-Json|Set-Content -LiteralPath $ResultPath -Encoding utf8
if($Action-eq'Commit'-and($env:FIXTURE_CASE-eq'commit_noisy_nonzero'-or$env:FIXTURE_CASE-like'cap_*')){exit 3}
exit 0
"""

RUNNER = r"""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts/v213_sealed_refresh.ps1')
$preference=Join-Path $PSScriptRoot 'preference.json'
if(Get-V213SealedPublicationPreference -Path $preference){throw 'missing preference enabled publication'}
foreach($flag in @($false,$true)){
 @{sealed_publication_enabled=$flag}|ConvertTo-Json|Set-Content -LiteralPath $preference
 if((Get-V213SealedPublicationPreference -Path $preference)-ne$flag){throw 'preference not preserved'}
}
@{sealed_publication_enabled='false'}|ConvertTo-Json|Set-Content -LiteralPath $preference
try{$null=Get-V213SealedPublicationPreference -Path $preference;throw 'string preference accepted'}catch{if($_.Exception.Message-eq'string preference accepted'){throw}}
try {$null=Invoke-V213SealedRefresh -ProjectRoot $PSScriptRoot -LocalConfigPath 'synthetic-only'}catch{}
if($env:FIXTURE_CASE-eq'rollback'){
 try{$null=Invoke-V213SealedRefresh -ProjectRoot $PSScriptRoot -LocalConfigPath 'synthetic-only';throw 'unresolved journal accepted'}catch{if($_.Exception.Message-eq'unresolved journal accepted'){throw}}
}
"""

RUNNER_NOISY = r"""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts/v213_sealed_refresh.ps1')
$captured=@()
$threw=$false
try {
    $captured += @(Invoke-V213SealedRefresh -ProjectRoot $PSScriptRoot -LocalConfigPath 'synthetic-only' 2>&1)
} catch {
    $threw=$true
    $captured += @($_)
}
$canaryStdout=$false
$canaryStderr=$false
$canaryThrow=$false
$pubCount=0
$scalarOk=$true
foreach($r in $captured){
    $t=$r.ToString()
    if($t -like '*SYNTHETIC_CANARY_STDOUT_NOISY*'){$canaryStdout=$true}
    if($t -like '*SYNTHETIC_CANARY_STDERR_NOISY*'){$canaryStderr=$true}
    if($t -like '*SYNTHETIC_CANARY_THROW_MUST_NOT_LEAK*'){$canaryThrow=$true}
    if($r -isnot [System.Management.Automation.ErrorRecord]){
        $pubCount++
        if($r -isnot [pscustomobject] -or $r.status -isnot [string] -or $r.publication_state -isnot [string] -or $r.real_line_sent -isnot [bool]){$scalarOk=$false}
    }
}
[ordered]@{
    threw=$threw
    captured_records=$captured.Count
    canary_stdout_at_function_boundary=$canaryStdout
    canary_stderr_at_function_boundary=$canaryStderr
    canary_throw_at_function_boundary=$canaryThrow
    publication_record_count=$pubCount
    scalar_types_valid=$scalarOk
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'noisy-observation.json') -Encoding utf8
exit 0
"""


RUNNER_NOISY_STREAM = r"""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts/v213_sealed_refresh.ps1')
$threw=$false
$canaryStdout=$false
$canaryStderr=$false
$canaryThrow=$false
$canaryMarker=$false
$pubCount=0
$scalarOk=$true
$recordTotal=0
$errorTotal=0
$payloadTotal=0
$payloadSeen=0
$payloadList=@()
if($env:OBSERVE_PAYLOADS){$payloadList=@($env:OBSERVE_PAYLOADS -split '\|');$payloadTotal=$payloadList.Count}
try {
    Invoke-V213SealedRefresh -ProjectRoot $PSScriptRoot -LocalConfigPath 'synthetic-only' 2>&1 | ForEach-Object {
        $t=$_.ToString()
        $recordTotal++
        if($t -like '*SYNTHETIC_CANARY_STDOUT_NOISY*'){$canaryStdout=$true}
        if($t -like '*SYNTHETIC_CANARY_STDERR_NOISY*'){$canaryStderr=$true}
        if($t -like '*SYNTHETIC_CANARY_THROW_MUST_NOT_LEAK*'){$canaryThrow=$true}
        if($t -like '*OVERSIZED_MARKER_MUST_NOT_LEAK*'){$canaryMarker=$true}
        foreach($p in $payloadList){if($t -like "*$p*"){$payloadSeen++}}
        if($_ -isnot [System.Management.Automation.ErrorRecord]){
            $pubCount++
            if($_ -isnot [pscustomobject] -or $_.status -isnot [string] -or $_.publication_state -isnot [string] -or $_.real_line_sent -isnot [bool]){$scalarOk=$false}
        } else {
            $errorTotal++
        }
    }
} catch {
    $threw=$true
}
[ordered]@{
    threw=$threw
    canary_stdout_at_stream_boundary=$canaryStdout
    canary_stderr_at_stream_boundary=$canaryStderr
    canary_throw_at_stream_boundary=$canaryThrow
    canary_marker_at_stream_boundary=$canaryMarker
    publication_record_count=$pubCount
    scalar_types_valid=$scalarOk
    record_total=$recordTotal
    error_record_count=$errorTotal
    payload_total=$payloadTotal
    payload_seen_count=$payloadSeen
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'noisy-stream-observation.json') -Encoding utf8
exit 0
"""


RUNNER_AUX = r"""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts/v213_sealed_refresh.ps1')
$bundle=Join-Path $PSScriptRoot 'data/cache/v213_activation_bundle_upload.json'
$bundleSha=(Get-FileHash -LiteralPath $bundle).Hash.ToLowerInvariant()
# Positive control: with the streams NOT discarded, the fixture child emits
# every auxiliary canary (proves the canaries are actually produced, not
# silenced by default preference).
$probe=& (Join-Path $PSScriptRoot 'sync-v213-activation-bundle.ps1') -Action Commit -ProjectRoot $PSScriptRoot -BundlePath $bundle -ExpectedBundleSha256 $bundleSha -LocalConfigPath 'synthetic-only' -ResultPath (Join-Path $PSScriptRoot 'probe-ack.json') 2>&1 3>&1 4>&1 5>&1 6>&1 | Out-String
$auxCanaries=@('SYNTHETIC_CANARY_WARNING_AUX','SYNTHETIC_CANARY_VERBOSE_AUX','SYNTHETIC_CANARY_DEBUG_AUX','SYNTHETIC_CANARY_INFORMATION_AUX','SYNTHETIC_CANARY_HOST_AUX')
$visible=0
foreach($c in $auxCanaries){if($probe -like "*$c*"){$visible++}}
$captured=@()
$threw=$false
try {
    $captured += @(Invoke-V213SealedRefresh -ProjectRoot $PSScriptRoot -LocalConfigPath 'synthetic-only' 2>&1)
} catch {
    $threw=$true
    $captured += @($_)
}
$leak=$false
foreach($r in $captured){
    $t=$r.ToString()
    foreach($c in $auxCanaries){if($t -like "*$c*"){$leak=$true}}
}
[ordered]@{
    aux_visible_count=$visible
    aux_leak_at_assignment_boundary=$leak
    threw=$threw
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'aux-observation.json') -Encoding utf8
exit 0
"""


RUNNER_NOISY_PLAIN = r"""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts/v213_sealed_refresh.ps1')
try {
    Invoke-V213SealedRefresh -ProjectRoot $PSScriptRoot -LocalConfigPath 'synthetic-only'
} catch {
    # canonical failure; observation only
}
exit 0
"""


RUNNER_DIAG_INJECT = r"""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts/v213_sealed_refresh.ps1')
# AST extraction of the real diagnostic saver; injection modes:
#   write   : pre-create the .tmp path as a directory -> WriteAllBytes fails
#   rename  : broken junction at the target -> Move-Item fails
#   oversize: shadow the saver with a copy whose ONLY change is the JSON size
#             threshold (8192 -> 200 bytes), forcing the oversize branch in
#             the real refresh flow; the production function and its 8192
#             threshold are untouched.
$parseTree=$null;$parseErrors=$null
$scriptAst=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'scripts/v213_sealed_refresh.ps1'),[ref]$parseTree,[ref]$parseErrors)
$fnAst=$scriptAst.FindAll({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Save-V213CommitDiagnostic'},$true) | Select-Object -First 1
if($null-eq$fnAst){throw 'V213_DIAG_INJECT_FUNCTION_NOT_FOUND'}
if($env:DIAG_INJECT -eq 'oversize'){
    $cappedText=$fnAst.Extent.Text -replace 'if\(\$jsonBytes\.Length-gt\$cap\)','if($jsonBytes.Length-gt200)'
    if($cappedText-eq$fnAst.Extent.Text){throw 'V213_DIAG_INJECT_OVERSIZE_REWRITE_FAILED'}
    Invoke-Expression $cappedText
} else {
    Invoke-Expression ($fnAst.Extent.Text -replace 'function Save-V213CommitDiagnostic','function Save-V213CommitDiagnosticReal')
    function Save-V213CommitDiagnostic {
        param([string]$DetailsPath,[object]$Summary,[System.Management.Automation.ErrorRecord]$ErrorRecord,[AllowNull()][object]$ExitCode)
        if($env:DIAG_INJECT -eq 'write'){
            New-Item -ItemType Directory -Force (Join-Path $DetailsPath 'COMMIT_REQUEST-diagnostic.json.tmp') | Out-Null
        } elseif($env:DIAG_INJECT -eq 'rename'){
            $target=Join-Path $DetailsPath 'COMMIT_REQUEST-diagnostic.json'
            $missing=Join-Path $DetailsPath 'v213-diag-missing-target'
            New-Item -ItemType Directory -Force $missing | Out-Null
            New-Item -ItemType Junction -Path $target -Target $missing | Out-Null
            Remove-Item $missing -Force
        }
        Save-V213CommitDiagnosticReal -DetailsPath $DetailsPath -Summary $Summary -ErrorRecord $ErrorRecord -ExitCode $ExitCode
    }
}
$threw=$false
try {
    Invoke-V213SealedRefresh -ProjectRoot $PSScriptRoot -LocalConfigPath 'synthetic-only'
} catch {
    $threw=$true
}
"diag_inject_threw=$threw"
# Lock release proof while this runner is still alive: measure the fixture
# lock state, then a separate process probes the same mutex with a direct
# WaitOne and 4-way classification (only NORMAL_ACQUIRED passes; ABANDONED is
# classified distinctly and released as cleanup).
$lockStateCleared=($script:V213OperationLockDepth-eq0)-and($null-eq$script:V213OperationLock)
"lock_state_cleared=$lockStateCleared"
$probeOut=& (Get-Process -Id $PID).Path -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'lock-probe.ps1')
"lock_probe: $probeOut"
exit 0
"""


LOCK_PROBE_PS = r"""$lockScript=Join-Path $PSScriptRoot 'scripts/v213_operation_lock.ps1'
$text=Get-Content -LiteralPath $lockScript -Raw
if($text -notmatch 'Threading\.Mutex\(\$false,\s*''Local\\([^'']+)''\)'){ "probe_status=ERROR"; exit 0 }
$mutexName='Local\' + $Matches[1]
$mutex=New-Object Threading.Mutex($false,$mutexName)
$status='ERROR'
try{
    $acquired=$mutex.WaitOne([TimeSpan]::FromSeconds(3))
    if($acquired){$status='NORMAL_ACQUIRED';$mutex.ReleaseMutex()}else{$status='BUSY'}
}catch [Threading.AbandonedMutexException]{
    # The caller now owns the mutex: classify ABANDONED (not PASS) and release
    # separately so cleanup is never skipped.
    $status='ABANDONED'
    try{$mutex.ReleaseMutex()}catch{}
}catch{
    $status='ERROR'
}
$mutex.Dispose()
"probe_status=$status"
"""


LOCK_ABANDON_PS = r"""$readyPath=Join-Path $PSScriptRoot 'lock-abandon-ready.txt'
$resultPath=Join-Path $PSScriptRoot 'lock-abandon-result.txt'
. (Join-Path $PSScriptRoot 'scripts/v213_operation_lock.ps1')
$lockScript=Join-Path $PSScriptRoot 'scripts/v213_operation_lock.ps1'
$text=Get-Content -LiteralPath $lockScript -Raw
if($text -notmatch 'Threading\.Mutex\(\$false,\s*''Local\\([^'']+)''\)'){ "probe_status=ERROR" | Set-Content -LiteralPath $resultPath -Encoding ascii; exit 0 }
$mutex=New-Object Threading.Mutex($false,('Local\' + $Matches[1]))
# All preparation is done before the ready signal: the holder exits as soon
# as it sees ready, so WaitOne must start immediately after the signal to be
# blocked at the moment of abandonment (.NET only signals abandonment to a
# waiter already waiting).
"ready" | Set-Content -LiteralPath $readyPath -Encoding ascii
$status='ERROR'
try{
    $acquired=$mutex.WaitOne([TimeSpan]::FromSeconds(10))
    if($acquired){$status='NORMAL_ACQUIRED';$mutex.ReleaseMutex()}else{$status='BUSY'}
}catch [Threading.AbandonedMutexException]{
    # The caller now owns the mutex: classify ABANDONED (not PASS) and release
    # separately so cleanup is never skipped.
    $status='ABANDONED'
    try{$mutex.ReleaseMutex()}catch{}
}catch{
    $status='ERROR'
}
$mutex.Dispose()
"probe_status=$status" | Set-Content -LiteralPath $resultPath -Encoding ascii
"""


RUNNER_LOCK_CONTROLS = r"""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts/v213_operation_lock.ps1')
$hostExe=(Get-Process -Id $PID).Path
function Invoke-LockProbe {
    $out=& $hostExe -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'lock-probe.ps1')
    return (($out | Out-String).Trim())
}
# control 1: BUSY - this runner holds the fixture lock; a new waiter must
# time out (BUSY), never acquire.
[void](Enter-V213OperationLock -Owner 'lock-controls' -TimeoutSeconds 3)
$busy=Invoke-LockProbe
Exit-V213OperationLock
# control 2: NORMAL - the lock is free; a new waiter acquires (NORMAL_ACQUIRED).
$normal=Invoke-LockProbe
[ordered]@{
    control_busy=$busy
    control_normal=$normal
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'lock-controls-observation.json') -Encoding utf8
# control 3: ABANDONED - hold the lock, start the waiter, wait for ready,
# then exit without releasing (process death abandons the mutex while the
# waiter is blocked). The waiter classifies and writes its own result file.
Remove-Item (Join-Path $PSScriptRoot 'lock-abandon-ready.txt'),(Join-Path $PSScriptRoot 'lock-abandon-result.txt') -ErrorAction SilentlyContinue
[void](Enter-V213OperationLock -Owner 'lock-abandon-holder' -TimeoutSeconds 3)
$abandonPath='"' + (Join-Path $PSScriptRoot 'lock-abandon.ps1') + '"'
Start-Process -FilePath $hostExe -ArgumentList '-NoProfile','-NonInteractive','-File',$abandonPath -WindowStyle Hidden
$deadline=(Get-Date).AddSeconds(15)
while(-not(Test-Path (Join-Path $PSScriptRoot 'lock-abandon-ready.txt')) -and (Get-Date) -lt $deadline){ Start-Sleep -Milliseconds 100 }
if(-not(Test-Path (Join-Path $PSScriptRoot 'lock-abandon-ready.txt'))){
    Exit-V213OperationLock
    'ready timeout' | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'lock-abandon-result.txt') -Encoding ascii
}
# Deliberately do NOT exit the lock: this process's death abandons the mutex
# while the waiter is blocked.
exit 0
"""


RUNNER_LOCK_ABANDON = r"""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# The holder (runner-lock-controls) exits without releasing; this process's
# only job is to observe the waiter's classification file after the holder
# death, then report it. The waiter is lock-abandon.ps1 (started by the
# holder). Wait for its result file, then copy the observation.
$deadline=(Get-Date).AddSeconds(20)
while(-not(Test-Path (Join-Path $PSScriptRoot 'lock-abandon-result.txt')) -and (Get-Date) -lt $deadline){ Start-Sleep -Milliseconds 100 }
$result=''
if(Test-Path (Join-Path $PSScriptRoot 'lock-abandon-result.txt')){
    $result=((Get-Content -LiteralPath (Join-Path $PSScriptRoot 'lock-abandon-result.txt') -Raw) -replace "\s+",'').Trim()
}
[ordered]@{
    control_abandoned=$result
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'lock-abandon-observation.json') -Encoding utf8
exit 0
"""


RUNNER_AUX_STREAM = r"""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts/v213_sealed_refresh.ps1')
$auxCanaries=@('SYNTHETIC_CANARY_WARNING_AUX','SYNTHETIC_CANARY_VERBOSE_AUX','SYNTHETIC_CANARY_DEBUG_AUX','SYNTHETIC_CANARY_INFORMATION_AUX','SYNTHETIC_CANARY_HOST_AUX')
$streamLeak=$false
$threw=$false
try {
    Invoke-V213SealedRefresh -ProjectRoot $PSScriptRoot -LocalConfigPath 'synthetic-only' 2>&1 | ForEach-Object {
        $t=$_.ToString()
        foreach($c in $auxCanaries){if($t -like "*$c*"){$streamLeak=$true}}
    }
} catch {
    $threw=$true
}
[ordered]@{
    aux_leak_at_stream_boundary=$streamLeak
    threw=$threw
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'aux-stream-observation.json') -Encoding utf8
exit 0
"""


DATA_JOB = r"""param($ProjectRoot,[switch]$NoModelBridge,[switch]$NoTunnel,[switch]$NoSync,[switch]$NoAutoActivation)
if(-not($NoModelBridge-and$NoTunnel-and$NoSync-and$NoAutoActivation)){throw 'unsafe data job arguments'}
. (Join-Path $ProjectRoot 'scripts/v213_windows_security.ps1')
$run=[DateTimeOffset]::UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'")+'-'+[guid]::NewGuid().ToString('N').Substring(0,12)
@{run_id=$run;transaction_id=[guid]::NewGuid().ToString('N')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $ProjectRoot 'data/cache/v213_activation_bundle_upload.json') -Encoding utf8
exit 0
"""


class SealedRefreshTests(unittest.TestCase):
    def _fixture(self, executable, case):
        parent = h.new_case('ack')
        folder = parent / 'synthetic (1) 版本'
        folder.mkdir()
        for name in ('data/cache', 'cloud/node_modules/.bin', 'scripts'):
            (folder / name).mkdir(parents=True)
        env = h.isolated_environment(parent, executable)
        # The real scheduled caller always starts a PS5.1 data-only child.
        env['PATH'] += os.pathsep + str(Path(dict(h.required_hosts())['powershell.exe']).parent)
        # Without PATHEXT, WinPS treats even explicit .exe/.cmd paths as documents.
        env['PATHEXT'] = '.COM;.EXE;.BAT;.CMD'
        env['FIXTURE_CASE'] = case
        originals, effective = {}, {}
        for relative in ('scripts/v213_sealed_refresh.ps1', 'scripts/v213_windows_security.ps1',
                         'scripts/v213_operation_lock.ps1', 'run-v213-scheduled-refresh.ps1'):
            source = SEALED_SOURCE if relative == 'scripts/v213_sealed_refresh.ps1' else ROOT / relative
            h.assert_plain_path(source)
            raw = source.read_bytes()
            originals[relative] = hashlib.sha256(raw).hexdigest()
            if relative.endswith('v213_operation_lock.ps1'):
                needle = b'Local\\InvestorIntelligence_V213_R75_OPERATION'
                self.assertEqual(raw.count(needle), 1)
                # Same lock code, a fixture-only name; never acquire the live mutex.
                raw = raw.replace(needle, ('Local\\V213_ACK_FIXTURE_' + parent.name).encode('ascii'))
            h.write_new(folder / relative, raw)
            effective[relative] = hashlib.sha256(raw).hexdigest()
        bundle = json.dumps({'run_id': '20260905T180113Z-4a4132a50a46', 'transaction_id': 'a' * 32}).encode()
        h.write_new(parent / 'original-bundle.json', bundle)
        h.write_new(folder / 'data/cache/v213_activation_bundle_upload.json', bundle)
        files = {
            'cloud/node_modules/.bin/wrangler.cmd': '@echo off\r\nexit /b 0\r\n',
            'activate-v213-seven-field-schedule.ps1': "param($ProjectRoot,[switch]$PreflightOnly,$FieldLocale)\nif(-not$PreflightOnly){throw 'mutation requested'}\nif($env:FIXTURE_CASE-eq'preflight'){exit 7}\nexit 0\n",
            'sync-v213-activation-bundle.ps1': SYNC,
            'runner.ps1': RUNNER,
            'runner-noisy.ps1': RUNNER_NOISY,
            'runner-noisy-stream.ps1': RUNNER_NOISY_STREAM,
            'runner-noisy-plain.ps1': RUNNER_NOISY_PLAIN,
            'runner-diag-inject.ps1': RUNNER_DIAG_INJECT,
            'runner-aux.ps1': RUNNER_AUX,
            'runner-aux-stream.ps1': RUNNER_AUX_STREAM,
            'runner-lock-controls.ps1': RUNNER_LOCK_CONTROLS,
            'runner-lock-abandon.ps1': RUNNER_LOCK_ABANDON,
            'lock-probe.ps1': LOCK_PROBE_PS,
            'lock-abandon.ps1': LOCK_ABANDON_PS,
            'run-v213-local.ps1': DATA_JOB,
        }
        for name, text in files.items():
            raw = text.encode('utf-8' if name.endswith('.cmd') else 'utf-8-sig')
            h.write_new(folder / name, raw)
            effective[name] = hashlib.sha256(raw).hexdigest()
        h.write_json(parent / 'inputs.json', {'case': case, 'source_sha256': originals,
            'effective_sha256': effective, 'operation_lock_single_literal_substitution': True,
            'real_operation_lock_used': False, 'transport_and_preflight': 'SYNTHETIC',
            'original_bundle_sha256': hashlib.sha256(bundle).hexdigest(), 'release_qualified': False})
        return parent, folder, env, effective

    def _run(self, executable, folder, env, bindings, phase, script, extra=()):
        command = [executable, '-NoProfile', '-NonInteractive', '-File', str(folder / script), *extra]
        try:
            result = subprocess.run(command, cwd=folder, env=env, capture_output=True,
                                    encoding='utf-8', errors='replace', timeout=45)
        except (OSError, subprocess.TimeoutExpired):
            h.write_json(folder.parent / (phase + '.json'), {'status': 'TRANSPORT_FAILED', 'release_qualified': False})
            raise AssertionError('SEALED_CALLER_TRANSPORT_FAILED') from None
        output = (result.stdout + result.stderr).encode('utf-8')
        h.write_json(folder.parent / (phase + '.json'), {'command': command, 'exit_code': result.returncode,
            'output_sha256': hashlib.sha256(output).hexdigest(), 'output_bytes': len(output),
            'raw_output_retained': False, 'release_qualified': False})
        for relative, digest in bindings.items():
            path = folder / relative
            h.assert_plain_path(path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, 'FIXTURE_CODE_CHANGED')
        return result

    def _journals(self, env):
        root = Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/sealed-publication'
        return [json.loads(p.read_text(encoding='utf-8-sig')) for p in root.glob('*.json')]

    def _actions(self, folder):
        path = folder / 'actions.txt'
        return path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []

    def test_transaction_and_failure_journals_on_both_windows_hosts(self):
        for _, executable in h.required_hosts():
            for case, state, actions, phase in (
                ('pass', 'FINALIZED', ['Commit', 'Finalize'], ''),
                ('preflight', 'NOT_ATTEMPTED', [], 'PREFLIGHT'),
                ('readback', 'ROLLED_BACK', ['Commit', 'Rollback'], 'COMMIT_ACK'),
                ('boolean', 'ROLLED_BACK', ['Commit', 'Rollback'], 'COMMIT_ACK'),
                ('identity_boolean', 'ROLLED_BACK', ['Commit', 'Rollback'], 'COMMIT_ACK'),
                ('status_boolean', 'ROLLED_BACK', ['Commit', 'Rollback'], 'COMMIT_ACK'),
                ('finalize', 'ROLLED_BACK', ['Commit', 'Finalize', 'Rollback'], 'FINALIZE_REQUEST'),
                ('rollback', 'UNKNOWN', ['Commit', 'Finalize', 'Rollback'], 'FINALIZE_REQUEST'),
            ):
                with self.subTest(host=Path(executable).name, case=case):
                    _, folder, env, bindings = self._fixture(executable, case)
                    result = self._run(executable, folder, env, bindings, 'direct', 'runner.ps1')
                    self.assertEqual(result.returncode, 0, 'DIRECT_CALLER_DRIVER_FAILED')
                    records = self._journals(env)
                    self.assertIn(state, [r['publication_state'] for r in records])
                    target = next(r for r in records if r['publication_state'] == state)
                    self.assertEqual(target['failed_phase'], phase)
                    self.assertEqual(target['rollback_failed_phase'], 'ROLLBACK_REQUEST' if case == 'rollback' else '')
                    if case == 'rollback':
                        blocked = next(r for r in records if r['publication_state'] == 'NOT_ATTEMPTED')
                        self.assertEqual(blocked['failed_phase'], 'JOURNAL_CHECK')
                        self.assertFalse(blocked['remote_sync_attempted'])
                    self.assertEqual(self._actions(folder), actions)
                    self.assertTrue(all(r['real_line_sent'] is False and r['worker_deployed'] is False for r in records))
                    self.assertTrue(all(r['status'] == ('PASS' if case == 'pass' else 'FAIL') for r in records))
                    if case == 'pass':
                        for enabled in (False, True):
                            args = ['-RuntimeRoot', str(folder), '-Slot', 'manual']
                            if enabled:
                                args.append('-PublishSealedBundle')
                            result = self._run(executable, folder, env, bindings, 'scheduled-' + str(enabled),
                                               'run-v213-scheduled-refresh.ps1', args)
                            self.assertEqual(result.returncode, 0, 'SCHEDULED_POSITIVE_CONTROL_FAILED')
                            receipt = json.loads((Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/v213-r75-scheduled-refresh-manual-latest.json').read_text('utf-8-sig'))
                            self.assertEqual(receipt['status'], 'PASS')
                            self.assertEqual(receipt['remote_sync_attempted'], enabled)
                            self.assertEqual(receipt['publication_state'], 'FINALIZED' if enabled else 'NOT_ATTEMPTED')
                            self.assertFalse(receipt['model_bridge_started'])
                        self.assertEqual(self._actions(folder), ['Commit', 'Finalize', 'Commit', 'Finalize'])

    def test_commit_transport_diagnostic_is_private_and_reproducible(self):
        allowed = {'schema_version', 'phase', 'captured_utc', 'exit_code', 'exception_type',
                   'fully_qualified_error_id', 'category', 'hresult', 'stdout_present',
                   'stderr_present', 'output_bytes', 'output_lines', 'output_sha256', 'truncated'}
        # Canonical output: UTF-8, LF-normalized, one LF appended per emitted record.
        # The terminating exception contributes metadata, not its message, to the artifact.
        output = ('transport prelude\nSYNTHETIC_SECRET_MUST_NOT_PERSIST\n'
                  'https://fixture.invalid Authorization Bearer token cookie LINE_CHANNEL LOCAL_LLM_SHARED_SECRET\n').encode()
        for host, executable in h.required_hosts():
            for repeat in range(2):
                with self.subTest(host=host, repeat=repeat):
                    parent, folder, env, bindings = self._fixture(executable, 'commit_transport_error')
                    original = (folder / 'data/cache/v213_activation_bundle_upload.json').read_bytes()
                    result = self._run(executable, folder, env, bindings, 'direct-diagnostic', 'runner.ps1')
                    self.assertEqual(result.returncode, 0, 'FIXTURE_DRIVER_FAILED')
                    records = self._journals(env)
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    self.assertEqual(record['status'], 'FAIL')
                    self.assertEqual(record['failed_phase'], 'COMMIT_REQUEST')
                    self.assertEqual(record['publication_state'], 'ROLLED_BACK')
                    self.assertTrue(record['production_mutation'])  # Synthetic rollback acknowledgement only.
                    self.assertEqual(record['rollback_failed_phase'], '')
                    self.assertEqual(self._actions(folder), ['Commit', 'Rollback'])
                    self.assertEqual((folder / 'data/cache/v213_activation_bundle_upload.json').read_bytes(), original)
                    root = Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/sealed-publication'
                    journal = next(root.glob('*.json'))
                    diagnostic = Path(str(journal) + '.details') / 'COMMIT_REQUEST-diagnostic.json'
                    self.assertTrue(diagnostic.is_file(), 'PRIVACY_SAFE_COMMIT_DIAGNOSTIC_MISSING')
                    raw = diagnostic.read_bytes()
                    self.assertLessEqual(len(raw), 8192)
                    data = json.loads(raw.decode('utf-8-sig'))
                    self.assertEqual(set(data), allowed)
                    self.assertEqual(data['schema_version'], 1)
                    self.assertEqual(data['phase'], 'COMMIT_REQUEST')
                    self.assertEqual(data['exception_type'], 'RuntimeException')
                    self.assertEqual(data['category'], 'OperationStopped')
                    self.assertEqual(data['fully_qualified_error_id'], 'UNAVAILABLE')
                    self.assertIsNone(data['exit_code'])  # No completed transport exit, not stale whoami=0.
                    self.assertIsInstance(data['hresult'], int)
                    self.assertTrue(data['stdout_present'])
                    self.assertTrue(data['stderr_present'])
                    self.assertEqual(data['output_bytes'], len(output))
                    self.assertEqual(data['output_lines'], 3)
                    self.assertEqual(data['output_sha256'], hashlib.sha256(output).hexdigest())
                    self.assertFalse(data['truncated'])
                    persisted = (raw + journal.read_bytes()).decode('utf-8-sig').lower()
                    for forbidden in ('SYNTHETIC_SECRET_MUST_NOT_PERSIST', 'http://', 'https://',
                                      'Authorization', 'Bearer', 'token', 'secret', 'cookie',
                                      'LINE_CHANNEL', 'LOCAL_LLM_SHARED_SECRET', str(folder), 'synthetic-only'):
                        self.assertNotIn(forbidden.lower(), persisted)
                    self.assertNotIn('SYNTHETIC_SECRET_MUST_NOT_PERSIST', result.stdout + result.stderr)
                    h.write_json(parent / 'diagnostic-observation.json', dict(host=host, repeat=repeat,
                        status=record['status'], failed_phase=record['failed_phase'],
                        diagnostic_bytes=len(raw), output_sha256=data['output_sha256'],
                        bundle_unchanged=True, raw_output_retained=False, release_qualified=False))

    def test_commit_noisy_output_privacy_at_function_boundary(self):
        # Phase B: raw replay removed; the bounded summary never re-emits
        # transport output. All three observation forms (assignment, per-record
        # stream, plain-statement console) must show no canary at any boundary;
        # success must return exactly one scalar publication object. The safe
        # observation summary is written before the privacy assertions so the
        # artifact exists even when a boundary REDs, and the classification is
        # derived from the actual observation (not a fixed RED label).
        for host, executable in h.required_hosts():
            for case in ('commit_noisy_exit0', 'commit_noisy_nonzero', 'commit_noisy_throw'):
                expected_pub = 1 if case == 'commit_noisy_exit0' else 0
                with self.subTest(host=host, case=case):
                    summary = {}
                    for form, runner, obsfile in (
                        ('assignment', 'runner-noisy.ps1', 'noisy-observation.json'),
                        ('stream', 'runner-noisy-stream.ps1', 'noisy-stream-observation.json'),
                        ('plain', 'runner-noisy-plain.ps1', None),
                    ):
                        with self.subTest(host=host, case=case, form=form):
                            parent, folder, env, bindings = self._fixture(executable, case)
                            result = self._run(executable, folder, env, bindings, 'noisy-' + form, runner)
                            self.assertEqual(result.returncode, 0, 'NOISY_DRIVER_FAILED')
                            console = result.stdout + result.stderr
                            canary_console = any(c in console for c in CANARIES)
                            if form == 'plain':
                                obs = {'threw': None, 'canary_stdout': canary_console,
                                       'canary_stderr': canary_console, 'canary_throw': canary_console,
                                       'publication_record_count': None, 'scalar_types_valid': None}
                            else:
                                raw = json.loads((folder / obsfile).read_text('utf-8-sig'))
                                if form == 'assignment':
                                    obs = {'threw': raw['threw'],
                                           'canary_stdout': raw['canary_stdout_at_function_boundary'],
                                           'canary_stderr': raw['canary_stderr_at_function_boundary'],
                                           'canary_throw': raw['canary_throw_at_function_boundary'],
                                           'publication_record_count': raw['publication_record_count'],
                                           'scalar_types_valid': raw['scalar_types_valid']}
                                else:
                                    obs = {'threw': raw['threw'],
                                           'canary_stdout': raw['canary_stdout_at_stream_boundary'],
                                           'canary_stderr': raw['canary_stderr_at_stream_boundary'],
                                           'canary_throw': raw['canary_throw_at_stream_boundary'],
                                           'publication_record_count': raw['publication_record_count'],
                                           'scalar_types_valid': raw['scalar_types_valid']}
                            records = self._journals(env)
                            self.assertEqual(len(records), 1)
                            record = records[0]
                            actions = self._actions(folder)
                            if case == 'commit_noisy_exit0':
                                self.assertEqual(record['status'], 'PASS')
                                self.assertEqual(record['publication_state'], 'FINALIZED')
                                self.assertEqual(actions, ['Commit', 'Finalize'])
                            else:
                                self.assertEqual(record['status'], 'FAIL')
                                self.assertEqual(record['publication_state'], 'ROLLED_BACK')
                                self.assertEqual(record['failed_phase'], 'COMMIT_REQUEST')
                                self.assertEqual(actions, ['Commit', 'Rollback'])
                            self.assertFalse(record['real_line_sent'])
                            self.assertFalse(record['worker_deployed'])
                            if form != 'plain':
                                self.assertEqual(obs['publication_record_count'], expected_pub,
                                                 'PUBLICATION_RECORD_COUNT_INVALID')
                                if expected_pub == 1:
                                    self.assertTrue(obs['scalar_types_valid'],
                                                     'PUBLICATION_SCALAR_TYPES_INVALID')
                            leak = bool(obs['canary_stdout'] or obs['canary_stderr']
                                        or obs['canary_throw'] or canary_console)
                            summary[form] = dict(obs, canary_console=canary_console, leak=leak,
                                                 classification='CANARY_LEAK' if leak else 'NO_LEAK',
                                                 failed_phase=record['failed_phase'],
                                                 publication_state=record['publication_state'],
                                                 actions=actions)
                            h.write_json(parent / ('noisy-observation-' + form + '-' + case + '.json'),
                                         dict(host=host, case=case, form=form, **summary[form],
                                              raw_output_retained=False, release_qualified=False))
                            self.assertFalse(leak, 'CANARY_CROSSED_' + form.upper() + '_BOUNDARY')

    def test_commit_cap_summary_reproducibility(self):
        # Phase B/C: bounded summary reproducibility. The persisted diagnostic
        # must match the independent UTF-16 reference exactly: presence flags
        # survive truncation (late stderr), a record is admitted whole only
        # when its normalized form fits the remaining code unit capacity
        # (raw length above the cap can still fit after CRLF shrink), and
        # UTF-8 bytes/lines/hash describe the same collected content. Output
        # is observed per record at the stream boundary; the oversized record
        # carries an identifiable marker (no length-based exemption).
        cases = {
            'cap_no_output': [],
            'cap_many_short': [(False, 'R%04d' % i) for i in range(2000)]
                               + [(True, 'LATE_STDERR_AFTER_TRUNCATION')],
            'cap_oversized_single': [(False, 'X' * 10000 + 'OVERSIZED_MARKER_MUST_NOT_LEAK' + 'X' * 9995)],
            'cap_exact': [(False, 'A' * 7)] * 1024,
            'cap_cjk_crlf': [(False, '重電\r\n設備'), (False, ''), (False, 'plain')],
            'cap_crlf_shrink': [(False, 'A\r\n' * 3000)],
            'cap_norm_exact_fit': [(False, 'A' * 8000), (False, 'B' * 190)],
            'cap_norm_exact_over': [(False, 'A' * 8000), (False, 'B' * 191)],
            'cap_nonbmp_fit': [(False, '\U0001D11E' * 4000)],
            'cap_nonbmp_over': [(False, '\U0001D11E' * 4100)],
        }
        for host, executable in h.required_hosts():
            for case, records in cases.items():
                with self.subTest(host=host, case=case):
                    parent, folder, env, bindings = self._fixture(executable, case)
                    payloads = self._cap_payloads(case, records)
                    env = dict(env)
                    env['OBSERVE_PAYLOADS'] = '|'.join(payloads)
                    result = self._run(executable, folder, env, bindings, 'cap', 'runner-noisy-stream.ps1')
                    self.assertEqual(result.returncode, 0, 'CAP_DRIVER_FAILED')
                    console = result.stdout + result.stderr
                    stream_obs = json.loads((folder / 'noisy-stream-observation.json').read_text('utf-8-sig'))
                    self.assertFalse(stream_obs['canary_marker_at_stream_boundary'],
                                     'CAP_MARKER_CROSSED_STREAM_BOUNDARY')
                    # All cap cases end non-zero: the function must emit no
                    # success records and no error records at the stream
                    # boundary; none of the expected synthetic payloads may be
                    # seen by the per-record consumer (late stderr included).
                    self.assertEqual(stream_obs['publication_record_count'], 0,
                                     'CAP_UNEXPECTED_SUCCESS_RECORDS')
                    self.assertEqual(stream_obs['error_record_count'], 0,
                                     'CAP_UNEXPECTED_ERROR_RECORDS')
                    self.assertEqual(stream_obs['record_total'], 0, 'CAP_UNEXPECTED_RECORDS')
                    self.assertEqual(stream_obs['payload_total'], len(payloads))
                    self.assertEqual(stream_obs['payload_seen_count'], 0,
                                     'CAP_PAYLOAD_AT_STREAM_BOUNDARY')
                    self.assertNotIn('OVERSIZED_MARKER_MUST_NOT_LEAK', console)
                    for _, text in records:
                        if text and len(text) < 40:
                            self.assertNotIn(text, console)
                    jdata = self._journals(env)[0]
                    self.assertEqual(jdata['status'], 'FAIL')
                    self.assertEqual(jdata['failed_phase'], 'COMMIT_REQUEST')
                    self.assertEqual(jdata['publication_state'], 'ROLLED_BACK')
                    self.assertEqual(self._actions(folder), ['Commit', 'Rollback'])
                    root = Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/sealed-publication'
                    journal = next(root.glob('*.json'))
                    diagnostic = Path(str(journal) + '.details') / 'COMMIT_REQUEST-diagnostic.json'
                    self.assertTrue(diagnostic.is_file(), 'CAP_DIAGNOSTIC_MISSING')
                    raw = diagnostic.read_bytes()
                    self.assertLessEqual(len(raw), 8192)
                    data = json.loads(raw.decode('utf-8-sig'))
                    expected = reference_commit_summary(records)
                    for key in ('stdout_present', 'stderr_present', 'output_bytes',
                                'output_lines', 'output_sha256', 'truncated'):
                        self.assertEqual(data[key], expected[key], 'CAP_FIELD_MISMATCH_' + key)
                    self.assertEqual(data['exception_type'], 'UNAVAILABLE')
                    self.assertEqual(data['exit_code'], 3)
                    h.write_json(parent / ('cap-observation-' + case + '.json'), dict(
                        host=host, case=case, **expected, diagnostic_bytes=len(raw),
                        marker_at_stream_boundary=stream_obs['canary_marker_at_stream_boundary'],
                        unexpected_success_records=stream_obs['publication_record_count'],
                        payload_seen=stream_obs['payload_seen_count'],
                        payload_total=stream_obs['payload_total'],
                        late_stderr_seen=bool(stream_obs['payload_seen_count'] > 0
                                              and 'LATE_STDERR_AFTER_TRUNCATION' in payloads),
                        raw_output_retained=False, release_qualified=False))

    @staticmethod
    def _cap_payloads(case, records):
        # Expected synthetic payloads checked by the per-record stream
        # consumer. Representative subset for the 2000-record case; late
        # stderr and the oversized marker are always included when present.
        if case == 'cap_many_short':
            return ['R%04d' % i for i in range(0, 2000, 50)] + ['LATE_STDERR_AFTER_TRUNCATION']
        if case == 'cap_oversized_single':
            return ['OVERSIZED_MARKER_MUST_NOT_LEAK']
        return [text for _, text in records if text and len(text) < 40]

    def test_commit_diagnostic_failure_injection(self):
        # Phase B/C: diagnostic persistence failure (write, rename, oversize)
        # must not mask the canonical COMMIT_REQUEST failure, must not block
        # rollback, and must release the lock. Injection targets the diagnostic
        # location only; the journal stays intact. Lock release is measured
        # while the runner is still alive: the fixture lock state must be
        # cleared and a separate process must acquire the same mutex.
        for host, executable in h.required_hosts():
            for inject in ('write', 'rename', 'oversize'):
                with self.subTest(host=host, inject=inject):
                    parent, folder, env, bindings = self._fixture(executable, 'commit_noisy_nonzero')
                    env = dict(env)
                    env['DIAG_INJECT'] = inject
                    result = self._run(executable, folder, env, bindings, 'diag-inject-' + inject,
                                       'runner-diag-inject.ps1')
                    self.assertEqual(result.returncode, 0, 'DIAG_INJECT_DRIVER_FAILED')
                    self.assertIn('diag_inject_threw=True', result.stdout)
                    # Lock release measured while the runner process is alive:
                    # state cleared + 4-way probe classifies NORMAL_ACQUIRED
                    # (busy/abandoned/error are distinct and would fail).
                    self.assertIn('lock_state_cleared=True', result.stdout)
                    self.assertIn('probe_status=NORMAL_ACQUIRED', result.stdout)
                    records = self._journals(env)
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    self.assertEqual(record['status'], 'FAIL')
                    self.assertEqual(record['failed_phase'], 'COMMIT_REQUEST')
                    self.assertEqual(record['publication_state'], 'ROLLED_BACK')
                    self.assertEqual(record['rollback_failed_phase'], '')
                    self.assertEqual(self._actions(folder), ['Commit', 'Rollback'])
                    self.assertFalse(record['real_line_sent'])
                    self.assertFalse(record['worker_deployed'])
                    root = Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/sealed-publication'
                    journal = next(root.glob('*.json'))
                    details = Path(str(journal) + '.details')
                    target = details / 'COMMIT_REQUEST-diagnostic.json'
                    if inject == 'write':
                        self.assertTrue((details / 'COMMIT_REQUEST-diagnostic.json.tmp').is_dir())
                    elif inject == 'rename':
                        # Broken junction: lexists checks the reparse point itself
                        # (Path.exists() would follow the missing target).
                        self.assertTrue(os.path.lexists(target))
                    # oversize: the branch throws before any write; nothing
                    # partial or shrunk may be persisted.
                    self.assertFalse(target.is_file(), 'DIAGNOSTIC_MUST_NOT_PERSIST_UNDER_INJECTION')
                    if inject == 'oversize':
                        self.assertFalse(Path(str(target) + '.tmp').exists())
                    h.write_json(parent / ('diag-inject-observation-' + inject + '.json'), dict(
                        host=host, inject=inject, failed_phase=record['failed_phase'],
                        publication_state=record['publication_state'],
                        actions=self._actions(folder),
                        lock_state_cleared=True, probe_status='NORMAL_ACQUIRED',
                        raw_output_retained=False, release_qualified=False))

    def test_lock_probe_controls(self):
        # Phase C1: the 4-way lock probe classification must be live, not a
        # constant. BUSY (holder alive), ABANDONED (holder died while the
        # waiter was blocked; .NET only signals abandonment to a waiter
        # already waiting) and NORMAL_ACQUIRED (lock free) are each produced
        # by their control scenario on both hosts.
        for host, executable in h.required_hosts():
            with self.subTest(host=host):
                parent, folder, env, bindings = self._fixture(executable, 'pass')
                # holder: BUSY + NORMAL controls, then dies while holding
                # (abandon) after the waiter signals ready.
                result = self._run(executable, folder, env, bindings, 'lock-controls',
                                   'runner-lock-controls.ps1')
                self.assertEqual(result.returncode, 0, 'LOCK_CONTROLS_DRIVER_FAILED')
                obs = json.loads((folder / 'lock-controls-observation.json').read_text('utf-8-sig'))
                self.assertEqual(obs['control_busy'], 'probe_status=BUSY')
                self.assertEqual(obs['control_normal'], 'probe_status=NORMAL_ACQUIRED')
                # observer: collects the waiter's ABANDONED classification.
                result2 = self._run(executable, folder, env, bindings, 'lock-abandon',
                                    'runner-lock-abandon.ps1')
                self.assertEqual(result2.returncode, 0, 'LOCK_ABANDON_DRIVER_FAILED')
                obs2 = json.loads((folder / 'lock-abandon-observation.json').read_text('utf-8-sig'))
                self.assertEqual(obs2['control_abandoned'], 'probe_status=ABANDONED')
                h.write_json(parent / 'lock-controls-observation-summary.json', dict(
                    host=host, control_busy=obs['control_busy'],
                    control_normal=obs['control_normal'],
                    control_abandoned=obs2['control_abandoned'],
                    raw_output_retained=False, release_qualified=False))

    def test_commit_aux_streams_discarded(self):
        # Phase C: Warning/Verbose/Debug/Information/Write-Host canaries are
        # explicitly enabled in the fixture child (positive control proves they
        # are actually emitted), then the commit call's local streams 3-6
        # discard must keep them out of every observation surface.
        aux_canaries = ('SYNTHETIC_CANARY_WARNING_AUX', 'SYNTHETIC_CANARY_VERBOSE_AUX',
                        'SYNTHETIC_CANARY_DEBUG_AUX', 'SYNTHETIC_CANARY_INFORMATION_AUX',
                        'SYNTHETIC_CANARY_HOST_AUX')
        for host, executable in h.required_hosts():
            with self.subTest(host=host):
                parent, folder, env, bindings = self._fixture(executable, 'aux_streams')
                result = self._run(executable, folder, env, bindings, 'aux', 'runner-aux.ps1')
                self.assertEqual(result.returncode, 0, 'AUX_DRIVER_FAILED')
                obs = json.loads((folder / 'aux-observation.json').read_text('utf-8-sig'))
                console = result.stdout + result.stderr
                # Positive control: all five canaries are emitted when the
                # streams are not discarded (no false PASS from default silence).
                self.assertEqual(obs['aux_visible_count'], 5, 'AUX_POSITIVE_CONTROL_FAILED')
                self.assertFalse(obs['aux_leak_at_assignment_boundary'],
                                 'AUX_LEAKED_AT_ASSIGNMENT_BOUNDARY')
                for c in aux_canaries:
                    self.assertNotIn(c, console)
                record = self._journals(env)[0]
                self.assertEqual(record['status'], 'PASS')
                self.assertEqual(record['publication_state'], 'FINALIZED')
                # actions: probe Commit + refresh Commit + Finalize
                self.assertEqual(self._actions(folder), ['Commit', 'Commit', 'Finalize'])
                h.write_json(parent / 'aux-observation-summary.json', dict(
                    host=host, aux_visible_count=obs['aux_visible_count'],
                    aux_leak_at_assignment_boundary=obs['aux_leak_at_assignment_boundary'],
                    aux_in_console=any(c in console for c in aux_canaries),
                    publication_state=record['publication_state'],
                    raw_output_retained=False, release_qualified=False))
                # Independent per-record stream form (Phase C2): the same five
                # canaries must not be seen by the stream consumer.
                parent2, folder2, env2, bindings2 = self._fixture(executable, 'aux_streams')
                result2 = self._run(executable, folder2, env2, bindings2, 'aux-stream',
                                    'runner-aux-stream.ps1')
                self.assertEqual(result2.returncode, 0, 'AUX_STREAM_DRIVER_FAILED')
                obs2 = json.loads((folder2 / 'aux-stream-observation.json').read_text('utf-8-sig'))
                self.assertFalse(obs2['aux_leak_at_stream_boundary'],
                                 'AUX_LEAKED_AT_STREAM_BOUNDARY')
                console2 = result2.stdout + result2.stderr
                for c in aux_canaries:
                    self.assertNotIn(c, console2)
                record2 = self._journals(env2)[0]
                self.assertEqual(record2['status'], 'PASS')
                self.assertEqual(record2['publication_state'], 'FINALIZED')
                self.assertEqual(self._actions(folder2), ['Commit', 'Finalize'])
                h.write_json(parent2 / 'aux-stream-observation-summary.json', dict(
                    host=host, aux_leak_at_stream_boundary=obs2['aux_leak_at_stream_boundary'],
                    aux_in_console=any(c in console2 for c in aux_canaries),
                    publication_state=record2['publication_state'],
                    raw_output_retained=False, release_qualified=False))

    def test_scheduled_caller_noisy_integration(self):
        # Phase B: the original scheduled caller (fixture copy) under noisy
        # success/nonzero/throw. Receipt fields must stay scalar and canonical;
        # no canary may reach console, receipt, log or diagnostic artifacts.
        for host, executable in h.required_hosts():
            for case, status, pstate, actions in (
                ('commit_noisy_exit0', 'PASS', 'FINALIZED', ['Commit', 'Finalize']),
                ('commit_noisy_nonzero', 'FAIL', 'ROLLED_BACK', ['Commit', 'Rollback']),
                ('commit_noisy_throw', 'FAIL', 'ROLLED_BACK', ['Commit', 'Rollback']),
            ):
                with self.subTest(host=host, case=case):
                    parent, folder, env, bindings = self._fixture(executable, case)
                    result = self._run(executable, folder, env, bindings, 'scheduled-noisy',
                        'run-v213-scheduled-refresh.ps1',
                        ['-RuntimeRoot', str(folder), '-Slot', 'manual', '-PublishSealedBundle'])
                    receipt_path = (Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/'
                                    'v213-r75-scheduled-refresh-manual-latest.json')
                    receipt_raw = receipt_path.read_text('utf-8-sig')
                    receipt = json.loads(receipt_raw)
                    log_root = Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/logs/scheduled-refresh'
                    log_text = ''.join(p.read_text('utf-8-sig', errors='replace')
                                       for p in log_root.glob('*.log'))
                    console = result.stdout + result.stderr
                    for canary in CANARIES:
                        self.assertNotIn(canary, receipt_raw)
                        self.assertNotIn(canary, log_text)
                        self.assertNotIn(canary, console)
                    # Scheduled artifact scan: journal + diagnostic + any
                    # diagnostic .tmp (booleans and counts only).
                    pub_root = Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/sealed-publication'
                    artifact_files = [p for p in pub_root.glob('*.json') if p.is_file()]
                    for det in pub_root.glob('*.details'):
                        artifact_files.extend(p for p in det.rglob('*') if p.is_file())
                    artifact_blob = ''.join(p.read_text('utf-8-sig', errors='replace')
                                            for p in artifact_files)
                    canary_in_artifacts = any(c in artifact_blob for c in CANARIES)
                    self.assertFalse(canary_in_artifacts, 'CANARY_IN_SCHEDULED_ARTIFACTS')
                    self.assertEqual(receipt['status'], status)
                    self.assertEqual(receipt['publication_state'], pstate)
                    self.assertIsInstance(receipt['publication_state'], str)
                    self.assertIsInstance(receipt['remote_sync_attempted'], bool)
                    self.assertIsInstance(receipt['production_mutation'], bool)
                    if case == 'commit_noisy_exit0':
                        self.assertEqual(result.returncode, 0)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self._actions(folder), actions)
                    h.write_json(parent / ('scheduled-noisy-observation-' + case + '.json'), dict(
                        host=host, case=case, status=receipt['status'],
                        publication_state=receipt['publication_state'],
                        actions=self._actions(folder),
                        canary_in_receipt=False, canary_in_log=False, canary_in_console=False,
                        canary_in_artifacts=False, artifact_count=len(artifact_files),
                        raw_output_retained=False, release_qualified=False))

    def test_scheduled_caller_does_not_ignore_an_unadmitted_terminal_journal(self):
        for host, executable in h.required_hosts():
            with self.subTest(host=host):
                parent, folder, env, bindings = self._fixture(executable, 'pass')
                root = Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/sealed-publication'
                root.mkdir(parents=True)
                previous = root / 'previous.json'
                raw = json.dumps(dict(schema_version=99, status='PASS', publication_state='FINALIZED',
                    remote_sync_attempted=True, production_mutation=True, real_line_sent=False,
                    worker_deployed=False, run_id='20260909T000000Z-123456789abc', transaction_id='a' * 32,
                    bundle_sha256='c' * 64, error_type='', recorded_utc='2026-09-09T00:00:00Z')).encode()
                h.write_new(previous, raw)
                result = self._run(executable, folder, env, bindings, 'scheduled-journal-negative',
                    'run-v213-scheduled-refresh.ps1', ['-RuntimeRoot', str(folder), '-Slot', 'manual', '-PublishSealedBundle'])
                records = [r for r in self._journals(env) if r['schema_version'] == 1]
                receipt = json.loads((Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/v213-r75-scheduled-refresh-manual-latest.json').read_text('utf-8-sig'))
                actions = self._actions(folder)
                h.write_json(parent / 'observation.json', dict(actions=actions, caller_status=receipt['status'],
                    previous_bytes_unchanged=previous.read_bytes() == raw,
                    failed_phases=[r['failed_phase'] for r in records], release_qualified=False))
                self.assertEqual(actions, [], 'UNADMITTED_TERMINAL_JOURNAL_BYPASSED_PUBLICATION_FENCE')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(previous.read_bytes(), raw)
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]['failed_phase'], 'JOURNAL_CHECK')
                self.assertEqual(records[0]['status'], 'FAIL')
                self.assertFalse(records[0]['remote_sync_attempted'])
                self.assertEqual(receipt['status'], 'FAIL')
                self.assertEqual(receipt['publication_state'], 'NOT_ATTEMPTED')
                self.assertFalse(receipt['remote_sync_attempted'])
                self.assertFalse(receipt['model_bridge_started'])

    def test_scheduled_caller_refuses_incomplete_or_replayed_ack(self):
        for _, executable in h.required_hosts():
            for case in ('upload_count', 'unsealed_count', 'extra_count', 'string_count', 'boolean_count',
                         'zero_replay', 'positive_replay', 'string_replay', 'missing_replay'):
                with self.subTest(host=Path(executable).name, case=case):
                    parent, folder, env, bindings = self._fixture(executable, case)
                    result = self._run(executable, folder, env, bindings, 'scheduled-negative',
                        'run-v213-scheduled-refresh.ps1', ['-RuntimeRoot', str(folder), '-Slot', 'manual', '-PublishSealedBundle'])
                    receipt = json.loads((Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/v213-r75-scheduled-refresh-manual-latest.json').read_text('utf-8-sig'))
                    records = self._journals(env)
                    actions = self._actions(folder)
                    h.write_json(parent / 'observation.json', {'caller_status': receipt['status'],
                        'publication_state': receipt['publication_state'], 'actions': actions,
                        'failed_phases': [r['failed_phase'] for r in records], 'release_qualified': False})
                    self.assertNotEqual(result.returncode, 0, 'INCOMPLETE_OR_REPLAYED_ACK_FALSE_SCHEDULED_SUCCESS')
                    self.assertEqual(receipt['status'], 'FAIL')
                    self.assertEqual(receipt['publication_state'], 'ROLLED_BACK')
                    self.assertTrue(receipt['remote_sync_attempted'])
                    self.assertFalse(receipt['model_bridge_started'])
                    self.assertEqual(actions, ['Commit', 'Rollback'], 'UNADMITTED_ACK_MUST_NOT_FINALIZE')
                    self.assertEqual(len(records), 1)
                    self.assertEqual(records[0]['status'], 'FAIL')
                    self.assertEqual(records[0]['failed_phase'], 'COMMIT_ACK')
                    self.assertFalse(records[0]['real_line_sent'])
                    self.assertFalse(records[0]['worker_deployed'])


if __name__ == '__main__':
    unittest.main()
