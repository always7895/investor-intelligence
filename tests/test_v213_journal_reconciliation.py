"""Actual source recovery caller; persistent fixtures and synthetic transport only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEALED_SOURCE = ROOT / 'scripts/v213_sealed_refresh.ps1'
_spec = importlib.util.spec_from_file_location('recovery_fixtures', ROOT / 'tests/installer_parse_harness.py')
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)


def original_record():
    return dict(schema_version=1, status='FAIL', publication_state='UNKNOWN',
        remote_sync_attempted=True, production_mutation=None, real_line_sent=False,
        worker_deployed=False, error_type='RuntimeException', recorded_utc='2026-09-09T00:00:00Z',
        transaction_id='a' * 32, run_id='20260909T000000Z-123456789abc', bundle_sha256='c' * 64)


SYNC = r'''param($Action,$ProjectRoot,$LocalConfigPath,$TransactionId,$RunId,$ResultPath)
if($Action-cne'Rollback'){throw 'UNEXPECTED_MUTATION'}
@{action=$Action;original_identity=($TransactionId-ceq('a'*32)-and$RunId-ceq'20260909T000000Z-123456789abc')}|ConvertTo-Json -Compress|Add-Content -LiteralPath (Join-Path $ProjectRoot 'calls.jsonl')
if($env:FIXTURE_CASE-eq'transport'){exit 7}
$r=@{status='not_committed';transaction_id=$TransactionId;run_id=$RunId}
if($env:FIXTURE_CASE-in@('rolled_back','bad_restore')){$r.status='rolled_back';$r.exact_pointer_restored=($env:FIXTURE_CASE-eq'rolled_back')}
if($env:FIXTURE_CASE-eq'bad_identity'){$r.transaction_id='b'*32}
$r|ConvertTo-Json|Set-Content -LiteralPath $ResultPath -Encoding utf8
exit 0
'''

RUNNER = r'''$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'scripts/v213_sealed_refresh.ps1')
$script:journal=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence/status/sealed-publication/failed.json'
$script:secondReads=0
$script:sourceJournalReader=(Get-Command Read-V213RefreshJournal).ScriptBlock
function Read-V213RefreshJournal([string]$Path) {
 $snapshot=& $script:sourceJournalReader $Path
 if($env:FIXTURE_CASE-ceq'changed'-and$Path.EndsWith('.original.json')){
  [IO.File]::WriteAllBytes($script:journal,[IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'replacement.json')))
 }
 return $snapshot
}
# Controlled path-read seam: no source edits, unrelated commands delegate unchanged.
function Get-Content {
 param([string]$LiteralPath,[switch]$Raw,[string]$Encoding)
 if($LiteralPath-ceq$script:journal){
  $script:secondReads++
  if($env:FIXTURE_CASE-ceq'second_read'){return [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'replacement.json')))}
 }
 Microsoft.PowerShell.Management\Get-Content -LiteralPath $LiteralPath -Raw:$Raw -Encoding $Encoding
}
function Get-FileHash {
 param([string]$LiteralPath,[string]$Algorithm='SHA256')
 $value=Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $LiteralPath -Algorithm $Algorithm
 if($env:FIXTURE_CASE-ceq'changed'-and$LiteralPath.EndsWith('.original.json')){
  [IO.File]::WriteAllBytes($script:journal,[IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'replacement.json')))
 }
 return $value
}
$errors=@()
try {$null=Resolve-V213SealedRefreshJournal -ProjectRoot $PSScriptRoot -JournalPath $script:journal -LocalConfigPath 'synthetic-only' -ConfirmRollbackReconciliation:($env:FIXTURE_CASE-cne'unconfirmed')}
catch {
 $message=$_.Exception.Message
 $allowed=@('V213_RECONCILE_EXPLICIT_CONFIRMATION_REQUIRED','V213_RECONCILE_STATE_INVALID','V213_REFRESH_JOURNAL_INVALID','V213_RECONCILE_JOURNAL_CHANGED','V213_REFRESH_ACK_IDENTITY_MISMATCH','V213_REFRESH_ROLLBACK_UNPROVEN','V213_RECONCILE_TRANSPORT_FAILED','V213_RECONCILE_ARCHIVE_CREATE_FAILED','V213_RECONCILE_ARCHIVE_MISMATCH')
 $errors+= $(if($message-cin$allowed){$message}else{'UNEXPECTED_EXCEPTION'})
}
if($env:FIXTURE_CASE-cin@('not_committed','rolled_back')){
 try {$null=Resolve-V213SealedRefreshJournal -ProjectRoot $PSScriptRoot -JournalPath $script:journal -LocalConfigPath 'synthetic-only' -ConfirmRollbackReconciliation}
 catch {$errors+= $(if($_.Exception.Message-ceq'V213_RECONCILE_STATE_INVALID'){'V213_RECONCILE_STATE_INVALID'}else{'UNEXPECTED_SECOND_REFUSAL'})}
}
@{errors=@($errors);second_path_reads=$script:secondReads;real_transport=$false;release_qualified=$false}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $PSScriptRoot 'observation.json') -Encoding utf8
'''


class JournalReconciliationTests(unittest.TestCase):
    def _assert_original_archive(self, journal, original, recorded_path=None):
        # Ordinary archives in this checkout already exceed MAX_PATH. Read only
        # the generated owned fixture path, never a path from the response.
        # No system policy changes or shortening of content-addressed names.
        self.assertTrue(journal.is_relative_to(h.AUDIT_CASE_ROOT))
        h.assert_plain_path(journal)
        archive = journal.parent / 'reconciliation-history' / (hashlib.sha256(original).hexdigest() + '.original.json')
        if recorded_path is not None:
            self.assertEqual(Path(recorded_path), archive)
        h.assert_plain_path(archive.parent)
        native = Path('\\\\?\\' + str(archive))
        h.assert_plain_path(native)
        self.assertEqual(native.read_bytes(), original)
        return archive

    def _fixture(self, executable, case, raw=None, *, minimum_archive_length=None):
        parent = h.new_case('r')
        project = parent / 'p'
        (project / 'scripts').mkdir(parents=True)
        env = h.isolated_environment(parent, executable)
        env.update(PATHEXT='.COM;.EXE;.BAT;.CMD', FIXTURE_CASE=case)
        suffix = Path('InvestorIntelligence/status/sealed-publication/reconciliation-history') / ('0' * 64 + '.original.json')
        if minimum_archive_length is not None:
            current_length = len(str(Path(env['LOCALAPPDATA']) / suffix))
            target = max(minimum_archive_length, current_length + 2)
            padded = Path(env['LOCALAPPDATA']) / ('長' * (target - current_length - 1))
            padded.mkdir()
            env['LOCALAPPDATA'] = str(padded)
            self.assertEqual(len(str(padded / suffix)), target)
        journal = Path(env['LOCALAPPDATA']) / 'InvestorIntelligence/status/sealed-publication/failed.json'
        journal.parent.mkdir(parents=True)
        original = raw if raw is not None else json.dumps(original_record()).encode()
        h.write_new(journal, original)
        h.write_new(parent / 'original.json', original)
        replacement = original_record()
        replacement['transaction_id'] = 'b' * 32
        h.write_new(project / 'replacement.json', json.dumps(replacement).encode())
        effective, originals = {}, {}
        for name in ('v213_sealed_refresh.ps1', 'v213_windows_security.ps1', 'v213_operation_lock.ps1'):
            source = SEALED_SOURCE if name == 'v213_sealed_refresh.ps1' else ROOT / 'scripts' / name
            h.assert_plain_path(source)
            data = source.read_bytes()
            originals[name] = hashlib.sha256(data).hexdigest()
            if name == 'v213_operation_lock.ps1':
                needle = b'Local\\InvestorIntelligence_V213_R75_OPERATION'
                self.assertEqual(data.count(needle), 1)
                data = data.replace(needle, ('Local\\V213_RECOVERY_FIXTURE_' + parent.name).encode())
            relative = 'scripts/' + name
            h.write_new(project / relative, data)
            effective[relative] = hashlib.sha256(data).hexdigest()
        for name, text in (('sync-v213-activation-bundle.ps1', SYNC), ('runner.ps1', RUNNER)):
            h.write_new(project / name, text.encode('utf-8-sig'))
            effective[name] = hashlib.sha256((project / name).read_bytes()).hexdigest()
        effective['replacement.json'] = hashlib.sha256((project / 'replacement.json').read_bytes()).hexdigest()
        h.write_json(parent / 'inputs.json', dict(case=case, source_sha256=originals,
            effective_sha256=effective, original_sha256=hashlib.sha256(original).hexdigest(),
            archive_path_characters=len(str(journal.parent / 'reconciliation-history' / ('0' * 64 + '.original.json'))),
            real_mutex_used=False, single_mutex_literal_substitution=True,
            synthetic_transport_only=True, release_qualified=False))
        return parent, project, env, journal, original, effective

    def _run(self, executable, fixture):
        parent, project, env, journal, original, bindings = fixture
        command = [executable, '-NoProfile', '-NonInteractive', '-File', str(project / 'runner.ps1')]
        try:
            result = subprocess.run(command, cwd=project, env=env, capture_output=True, timeout=40)
        except (OSError, subprocess.TimeoutExpired):
            h.write_json(parent / 'transport.json', {'status': 'TRANSPORT_FAILED', 'release_qualified': False})
            raise AssertionError('RECOVERY_FIXTURE_TRANSPORT_FAILED') from None
        output = result.stdout + result.stderr
        h.write_json(parent / 'transport.json', dict(command=command, exit=result.returncode,
            output_bytes=len(output), output_sha256=hashlib.sha256(output).hexdigest(),
            raw_output_retained=False, release_qualified=False))
        self.assertEqual(result.returncode, 0, 'RECOVERY_DRIVER_FAILED')
        for name, digest in bindings.items():
            h.assert_plain_path(project / name)
            self.assertEqual(hashlib.sha256((project / name).read_bytes()).hexdigest(), digest, 'FIXTURE_CODE_CHANGED')
        self.assertEqual((parent / 'original.json').read_bytes(), original)
        calls = project / 'calls.jsonl'
        actions = [json.loads(line) for line in calls.read_text('utf-8-sig').splitlines()] if calls.exists() else []
        return json.loads((project / 'observation.json').read_text('utf-8-sig')), actions

    def test_confirmed_recovery_preserves_failure_and_refuses_bad_ack(self):
        expected_errors = {'unconfirmed': 'V213_RECONCILE_EXPLICIT_CONFIRMATION_REQUIRED',
            'not_committed': 'V213_RECONCILE_STATE_INVALID', 'rolled_back': 'V213_RECONCILE_STATE_INVALID',
            'bad_identity': 'V213_REFRESH_ACK_IDENTITY_MISMATCH', 'bad_restore': 'V213_REFRESH_ROLLBACK_UNPROVEN',
            'transport': 'V213_RECONCILE_TRANSPORT_FAILED'}
        for host, executable in h.required_hosts():
            for case, expected in expected_errors.items():
                with self.subTest(host=host, case=case):
                    # Both native writers' UTF-8 BOM/no-BOM inputs remain accepted.
                    value = original_record()
                    if case == 'not_committed':
                        value['recorded_utc'] = '2026-09-09T00:00:00.1234000+00:00'
                    raw = json.dumps(value).encode('utf-8-sig' if case == 'rolled_back' else 'utf-8')
                    fixture = self._fixture(executable, case, raw)
                    _, _, _, journal, original, _ = fixture
                    observed, actions = self._run(executable, fixture)
                    self.assertEqual(observed['errors'], [expected], 'RECOVERY_CONTROL_REASON_MISMATCH')
                    self.assertEqual(actions, [] if case == 'unconfirmed' else [{'action': 'Rollback', 'original_identity': True}])
                    value = json.loads(journal.read_text('utf-8-sig'))
                    for name in ('status', 'error_type', 'recorded_utc', 'transaction_id', 'run_id', 'bundle_sha256'):
                        self.assertEqual(value[name], json.loads(original.decode('utf-8-sig'))[name])
                    if case in ('not_committed', 'rolled_back'):
                        self.assertEqual(value['publication_state'], case.upper())
                        self._assert_original_archive(journal, original, value['reconciliation']['original_archive'])
                        self.assertEqual(value['reconciliation']['original_sha256'], hashlib.sha256(original).hexdigest())
                        self.assertEqual(value['production_mutation'], True if case == 'rolled_back' else None)
                    else:
                        self.assertEqual(journal.read_bytes(), original)
                    if case == 'unconfirmed':
                        self.assertFalse((journal.parent / 'reconciliation-history').exists())

    def test_malformed_or_unsupported_journal_refuses_before_archive_or_transport(self):
        invalid = []
        for name, value in (('schema_version', 99), ('schema_version', True), ('status', ['FAIL']),
                            ('transaction_id', ['a' * 32]), ('run_id', ['20260909T000000Z-123456789abc']),
                            ('production_mutation', 'false'), ('remote_sync_attempted', 'true')):
            record = original_record()
            record[name] = value
            invalid.append((name + ':' + type(value).__name__, json.dumps(record).encode()))
        record = original_record()
        del record['schema_version']
        invalid.extend([('missing_schema', json.dumps(record).encode()), ('invalid_utf8', b'\xff'), ('size_bound', b' ' * 262145)])
        valid = json.dumps(original_record()).encode()
        for label, duplicate in (('duplicate_schema', b'"schema_version": 99, "schema_version": 1'),
                                 ('escaped_duplicate_schema', b'"schema_version": 99, "\\u0073chema_version": 1')):
            invalid.append((label, valid.replace(b'"schema_version": 1', duplicate)))
        invalid.append(('array_root', b'[' + valid + b']'))
        invalid.append(('nested_duplicate', valid[:-1] + b',"reconciliation":{"status":1,"status":2}}'))
        for host, executable in h.required_hosts():
            for label, raw in invalid:
                with self.subTest(host=host, case=label):
                    fixture = self._fixture(executable, 'invalid', raw)
                    _, _, _, journal, original, _ = fixture
                    observed, actions = self._run(executable, fixture)
                    self.assertEqual(actions, [], 'UNADMITTED_JOURNAL_ISSUED_MUTATING_ROLLBACK')
                    self.assertEqual(observed['errors'], ['V213_REFRESH_JOURNAL_INVALID'])
                    self.assertEqual(journal.read_bytes(), original)
                    self.assertFalse((journal.parent / 'reconciliation-history').exists(), 'UNADMITTED_JOURNAL_ARCHIVED')

    def test_recovery_uses_original_buffer_not_a_second_json_path_read(self):
        for host, executable in h.required_hosts():
            with self.subTest(host=host):
                fixture = self._fixture(executable, 'second_read')
                _, _, _, journal, original, _ = fixture
                observed, actions = self._run(executable, fixture)
                self.assertEqual(actions, [{'action': 'Rollback', 'original_identity': True}], 'ROLLBACK_IDENTITY_NOT_FROM_ARCHIVED_BYTES')
                self.assertEqual(observed['errors'], [])
                self.assertEqual(observed['second_path_reads'], 0, 'JOURNAL_JSON_REOPENED_AFTER_BYTE_CAPTURE')
                value = json.loads(journal.read_text('utf-8-sig'))
                self.assertEqual(value['transaction_id'], original_record()['transaction_id'])
                self._assert_original_archive(journal, original, value['reconciliation']['original_archive'])
                self.assertEqual(value['reconciliation']['original_sha256'], hashlib.sha256(original).hexdigest())

    def test_actual_recovery_archives_at_and_beyond_260_characters_without_shortening(self):
        for host, executable in h.required_hosts():
            for length, existing in ((260, None), (300, None), (260, 'matching'), (260, 'mismatch')):
                with self.subTest(host=host, minimum_length=length, existing=existing):
                    fixture = self._fixture(executable, 'long_archive', minimum_archive_length=length)
                    parent, _, _, journal, original, _ = fixture
                    archive = journal.parent / 'reconciliation-history' / (hashlib.sha256(original).hexdigest() + '.original.json')
                    self.assertGreaterEqual(len(str(archive)), length)
                    initial = original if existing == 'matching' else original.replace(b'RuntimeException', b'OTHER_FAILURE')
                    # Python's ordinary-path IO also has MAX_PATH limits on
                    # this host. Map only this generated, checked fixture path;
                    # never relax the shared harness's root/namespace policy.
                    native_archive = Path('\\\\?\\' + str(archive))
                    if existing:
                        archive.parent.mkdir()
                        h.assert_plain_path(archive.parent)
                        with native_archive.open('xb') as handle:
                            handle.write(initial)
                            handle.flush()
                            os.fsync(handle.fileno())
                        self.assertEqual(native_archive.read_bytes(), initial)
                    observed, actions = self._run(executable, fixture)
                    h.write_json(parent / 'long-archive-observation.json', dict(path_characters=len(str(archive)),
                        existing=existing, errors=observed['errors'], actions=actions, release_qualified=False))
                    if existing == 'mismatch':
                        self.assertEqual(actions, [], 'MISMATCHED_ORIGINAL_ARCHIVE_MUST_NOT_AUTHORIZE_ROLLBACK')
                        self.assertEqual(observed['errors'], ['V213_RECONCILE_ARCHIVE_MISMATCH'])
                        self.assertEqual(native_archive.read_bytes(), initial)
                        self.assertEqual(journal.read_bytes(), original)
                    else:
                        self.assertEqual(actions, [{'action': 'Rollback', 'original_identity': True}], 'LONG_ARCHIVE_PATH_PREVENTED_ACTUAL_RECOVERY')
                        self.assertEqual(observed['errors'], [])
                        value = json.loads(journal.read_text('utf-8-sig'))
                        self.assertEqual(value['publication_state'], 'NOT_COMMITTED')
                        self.assertEqual(value['status'], 'FAIL')
                        self.assertEqual(value['recorded_utc'], original_record()['recorded_utc'])
                        self.assertEqual(Path(value['reconciliation']['original_archive']), archive)
                        self.assertEqual(native_archive.read_bytes(), original)
                        self.assertEqual(value['reconciliation']['original_sha256'], hashlib.sha256(original).hexdigest())

    def test_changed_journal_refuses_before_mutating_transport_not_only_after(self):
        for host, executable in h.required_hosts():
            with self.subTest(host=host):
                fixture = self._fixture(executable, 'changed')
                _, project, _, journal, original, _ = fixture
                observed, actions = self._run(executable, fixture)
                self.assertEqual(actions, [], 'CHANGED_JOURNAL_ROLLBACK_BEFORE_CHANGE_REFUSAL')
                self.assertEqual(observed['errors'], ['V213_RECONCILE_JOURNAL_CHANGED'])
                self.assertEqual(journal.read_bytes(), (project / 'replacement.json').read_bytes())
                archive = self._assert_original_archive(journal, original)
                self.assertEqual(list(archive.parent.glob('*.ack.json')), [])


if __name__ == '__main__':
    unittest.main()
