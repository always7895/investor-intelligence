"""Frozen baseline diagnostics, NOT a passing installer/recovery acceptance suite."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metadata_harness', ROOT / 'tests/installer_parse_harness.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
BASELINE_LF_SHA256 = '68956b7d64467be25acdcc26c7a4780b9b45e50a0f7228accd4e21e61a63d275'


def run_probe(mode, host, executable):
    case = h.new_case('metadata-' + mode.lower())
    inputs = {}
    for name, source in (('baseline.ps1', 'v213_metadata_baseline.ps1'), ('acl.ps1', 'v213_acl_probe.ps1'),
                         ('probe.ps1', 'v213_metadata_probe.ps1')):
        raw = (ROOT / 'tests/fixtures' / source).read_bytes()
        if name == 'baseline.ps1' and hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() != BASELINE_LF_SHA256:
            raise AssertionError('FROZEN_BASELINE_CHANGED')
        h.write_new(case / name, raw)
        inputs[name] = hashlib.sha256(raw).hexdigest()
    h.write_json(case / 'inputs.json', {'files': inputs, 'mode': mode, 'release_qualified': False})
    cmd = [executable, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(case / 'probe.ps1'),
           '-Mode', mode, '-BaselineSha256', inputs['baseline.ps1'], '-AclSha256', inputs['acl.ps1']]
    try:
        result = subprocess.run(cmd, cwd=case, env=h.isolated_environment(case, executable), capture_output=True,
                                encoding='utf-8', errors='replace', timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        h.write_json(case / 'transport.json', {'status': 'UNEXPECTED', 'host': host,
                     'code': 'TIMEOUT' if isinstance(error, subprocess.TimeoutExpired) else 'HOST_START_FAILED'})
        raise AssertionError('METADATA_PROBE_TRANSPORT_FAILED') from None
    raw = (result.stdout + result.stderr).encode('utf-8')
    h.write_json(case / 'transport.json', {'host': host, 'exit_code': result.returncode,
                 'output_bytes': len(raw), 'output_sha256': hashlib.sha256(raw).hexdigest(), 'release_qualified': False})
    allowed = (0, 2) if mode == 'SaclCapability' else (0,)
    if result.returncode not in allowed or result.stderr:
        # Admit only the fixture's bounded failure schema, never raw PS stderr.
        if result.returncode == 1 and not result.stderr:
            try:
                failure = json.loads(result.stdout)
                phases = {'INPUT', 'NATIVE_BINDING', 'CREATE_STREAMS', 'ACL_PREPARE', 'IDENTITY',
                          'REPLACE', 'PARENT_ACL_UPDATE', 'STREAM_READBACK'}
                types = {'System.IO.IOException', 'System.ArgumentException', 'System.NotSupportedException',
                         'System.UnauthorizedAccessException', 'System.Management.Automation.MethodInvocationException',
                         'System.Management.Automation.RuntimeException', 'UNKNOWN'}
                valid = (set(failure) == {'kind', 'phase', 'exceptions', 'release_qualified'}
                         and failure['kind'] == 'METADATA_DIAGNOSTIC_FAILURE' and failure['phase'] in phases
                         and failure['release_qualified'] is False and 1 <= len(failure['exceptions']) <= 4
                         and all(set(e) == {'exception_type', 'hresult'} and e['exception_type'] in types
                                 and type(e['hresult']) is int for e in failure['exceptions']))
                if valid:
                    h.write_json(case / 'failure.json', failure)
            except (ValueError, TypeError, KeyError):
                pass
        raise AssertionError('METADATA_PROBE_TRANSPORT_FAILED')
    for name, digest in inputs.items():
        h.assert_plain_path(case / name)
        if hashlib.sha256((case / name).read_bytes()).hexdigest() != digest:
            raise AssertionError('PROBE_INPUT_CHANGED')
    value = json.loads(result.stdout)
    if any(s in result.stdout for s in ('S-1-', 'O:BA', 'SYNTHETIC_PRIVATE')):
        raise AssertionError('METADATA_REDACTION_FAILED')
    if value['kind'] != 'METADATA_DIAGNOSTIC' or value['mode'] != mode:
        raise AssertionError('METADATA_PROBE_SCHEMA_FAILED')
    for key in ('raw_security_data_retained', 'release_qualified', 'full_coordinator_executed'):
        if value[key] is not False:
            raise AssertionError('METADATA_PROBE_BOUNDARY_FAILED')
    h.write_json(case / 'observation.json', value)
    if result.returncode == 2:
        raise RuntimeError('BLOCKED_SACL_ACCESS_UNAVAILABLE')
    return case, value


@unittest.skipUnless(os.name == 'nt', 'BLOCKED: native Windows metadata diagnostics required')
class InstallerMetadataDiagnostics(unittest.TestCase):
    def test_frozen_restore_exposes_noop_and_directory_false_success(self):
        expected = {
            'original-present': (False, 'ORIGINAL', False),
            'original-empty': (False, 'EMPTY', False),
            'original-absent': (True, 'ABSENT', True),
            'foreign-directory-absent-original': (True, 'DIRECTORY', False),
            'foreign-file': (False, 'FOREIGN', True),
            'missing-original': (False, 'ABSENT', True),
            'our-new-existing-original': (None, 'NEW', False),
            'our-new-absent-original': (True, 'ABSENT', True),
        }
        for host, executable in h.required_hosts():
            case, value = run_probe('Restore', host, executable)
            rows = {r['case']: r for r in value['rows']}
            self.assertEqual(len(value['rows']), 8)
            self.assertEqual(set(rows), set(expected))
            for name, (accepted, after, meets) in expected.items():
                row = rows[name]
                self.assertIs(row['accepted'], accepted)
                self.assertEqual(row['after'], after)
                self.assertIs(row['meets_acceptance_oracle'], meets)
                if name == 'our-new-existing-original':
                    self.assertIn(-2147024809, [e['hresult'] for e in row['failure']])
                else:
                    self.assertIsNone(row['failure'])
            self.assertEqual((case / 'foreign-directory-absent-original/target.bin/sentinel.bin').read_bytes(), b'X')
            self.assertEqual((case / 'original-present/target.bin').read_bytes(), b'OLD')
            self.assertEqual((case / 'original-empty/target.bin').read_bytes(), b'')

    def test_frozen_journal_primary_and_rollback_updates_both_fail(self):
        for host, executable in h.required_hosts():
            _, value = run_probe('Journal', host, executable)
            self.assertEqual([r['requested_state'] for r in value['rows']], ['LOCKED', 'PREPARED', 'ROLLED_BACK'])
            self.assertEqual([r['observed_state'] for r in value['rows']], ['LOCKED'] * 3)
            self.assertIsNone(value['rows'][0]['failure'])
            for row in value['rows'][1:]:
                self.assertIn(-2147024809, [e['hresult'] for e in row['failure']])

    def test_inheritance_identity_streams_and_mutable_backup_acl(self):
        for host, executable in h.required_hosts():
            case, value = run_probe('Inheritance', host, executable)
            self.assertEqual([r['case'] for r in value['rows']], ['inherited', 'protected'])
            for row in value['rows']:
                for key in ('target_uses_replacement_identity', 'backup_retains_original_identity',
                            'backup_descriptor_before_parent_update', 'target_access_equals_unreplaced_control',
                            'target_original_stream', 'target_replacement_stream', 'backup_original_stream'):
                    self.assertIs(row[key], True)
                protected = row['case'] == 'protected'
                self.assertIs(row['target_dacl_changed_by_parent'], not protected)
                self.assertIs(row['backup_descriptor_after_parent_update'], protected)
                self.assertEqual((case / row['case'] / 'target.bin').read_bytes(), b'NEW')
                self.assertEqual((case / row['case'] / 'backup.bin').read_bytes(), b'OLD')


if __name__ == '__main__':
    unittest.main()
