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
_spec = importlib.util.spec_from_file_location('sealed_native_fixtures', ROOT / 'tests/installer_parse_harness.py')
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)

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
