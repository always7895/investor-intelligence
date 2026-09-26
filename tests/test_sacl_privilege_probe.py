"""Default tests NEVER enable native privileges; real reads need explicit session consent."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sacl_harness', ROOT / 'tests/installer_parse_harness.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
SELF_CASES = ['missing', 'already-enabled', 'restore-success', 'read-failure', 'read-exception',
              'not-all-assigned', 'restore-failure', 'other-privilege-change']
RESULT_KEYS = {'status', 'operation_status', 'assigned', 'enabled_before', 'enable_attempted', 'enabled_during',
               'read_attempted', 'restore_attempted', 'privileges_restored', 'other_privileges_unchanged',
               'sacl_present', 'sacl_null', 'two_reads_equal', 'fixture_bytes_unchanged', 'enable_error',
               'read_error', 'restore_error', 'child_pid', 'release_qualified', 'raw_security_data_retained'}
STATUSES = {'PASS', 'ERROR', 'NOT_ATTEMPTED', 'BLOCKED_PRIVILEGE_NOT_ASSIGNED', 'BLOCKED_ENABLE',
            'UNEXPECTED_PRIVILEGE_STATE', 'BLOCKED_READ', 'READ_CHANGED', 'EXCEPTION', 'RESTORE_FAILED', 'FIXTURE_CHANGED'}


def run_probe(host, executable, mode='self-test', *, session_authorized=False):
    if mode not in {'self-test', 'no-consent', 'bad-scope', 'bad-digest', 'authorized'}:
        raise ValueError('PROBE_MODE_INVALID')
    if mode == 'authorized' and session_authorized is not True:
        raise ValueError('EXPLICIT_SESSION_AUTHORIZATION_REQUIRED')
    case = h.new_case('sacl-read')
    sources = {'probe.ps1': 'v213_sacl_privilege.ps1', 'sacl_probe.cs': 'v213_sacl_privilege.cs'}
    digests = {}
    for name, source in sources.items():
        data = (ROOT / 'tests/fixtures' / source).read_bytes()
        h.write_new(case / name, data)
        digests[name] = hashlib.sha256(data).hexdigest()
    h.write_json(case / 'inputs.json', {'mode': mode, 'session_authorized': session_authorized,
                 'inputs': digests, 'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 'release_qualified': False})
    scope = case / 'nonexistent-child' if mode == 'bad-scope' else case
    digest = '0' * 64 if mode == 'bad-digest' else digests['sacl_probe.cs']
    command = [executable, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
               str(case / 'probe.ps1'), '-CaseRoot', str(scope), '-SourceSha256', digest]
    if mode == 'self-test':
        command.append('-SelfTest')
    elif mode != 'no-consent':
        command.append('-AllowAssignedSeSecurityPrivilege')
    try:
        process = subprocess.run(command, cwd=case, env=h.isolated_environment(case, executable),
                                 capture_output=True, encoding='utf-8', errors='replace', timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        h.write_json(case / 'transport.json', {'status': 'UNEXPECTED', 'host': host, 'release_qualified': False,
                     'code': 'TIMEOUT' if isinstance(error, subprocess.TimeoutExpired) else 'HOST_START_FAILED'})
        raise RuntimeError('SACL_PROBE_TRANSPORT_FAILED') from None
    output = (process.stdout + process.stderr).encode('utf-8')
    h.write_json(case / 'transport.json', {'host': host, 'exit_code': process.returncode, 'output_bytes': len(output),
                 'output_sha256': hashlib.sha256(output).hexdigest(), 'release_qualified': False})
    for name, digest in digests.items():
        h.assert_plain_path(case / name)
        if hashlib.sha256((case / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('SACL_PROBE_INPUT_CHANGED')
    if process.stderr:
        raise RuntimeError('SACL_PROBE_STDERR')
    value = json.loads(process.stdout)
    if 'result' in value:
        result = value['result']
        if set(value) != {'kind', 'host_version', 'result'} or value['kind'] != 'SACL_PRIVILEGE_FIXTURE' or set(result) != RESULT_KEYS:
            raise RuntimeError('SACL_PROBE_SCHEMA_REJECTED')
        for name, item in result.items():
            if name in {'status', 'operation_status'}:
                if item not in STATUSES:
                    raise RuntimeError('SACL_PROBE_STATUS_REJECTED')
            elif item is not None and type(item) not in {bool, int}:
                raise RuntimeError('SACL_PROBE_VALUE_REJECTED')
        if result['release_qualified'] is not False or result['raw_security_data_retained'] is not False:
            raise RuntimeError('SACL_PROBE_BOUNDARY_FAILED')
        if type(result['child_pid']) is not int or result['child_pid'] == os.getpid():
            raise RuntimeError('SACL_CHILD_SCOPE_FAILED')
    elif value.get('kind') == 'SACL_PRIVILEGE_SELF_TEST':
        if (set(value) != {'kind', 'cases', 'native_privilege_api_invoked', 'release_qualified'} or
                value['cases'] != SELF_CASES or value['native_privilege_api_invoked'] is not False or value['release_qualified'] is not False):
            raise RuntimeError('SACL_SELF_TEST_SCHEMA_REJECTED')
    else:
        expected = {'REJECTED_AUTHORIZATION_REQUIRED', 'REJECTED_CONFLICTING_MODES', 'REJECTED_FIXTURE_SCOPE',
                    'REJECTED_CHILD_ENVIRONMENT', 'REJECTED_SOURCE_DIGEST', 'PROBE_ERROR'}
        if value.get('kind') != 'SACL_PRIVILEGE_FIXTURE' or value.get('status') not in expected or value.get('release_qualified') is not False:
            raise RuntimeError('SACL_REJECTION_SCHEMA_REJECTED')
        keys = {'kind', 'status', 'hresult', 'release_qualified'} if value['status'] == 'PROBE_ERROR' else {'kind', 'status', 'native_privilege_api_invoked', 'release_qualified'}
        if set(value) != keys or ('hresult' in value and type(value['hresult']) is not int):
            raise RuntimeError('SACL_REJECTION_KEYS_REJECTED')
    h.write_json(case / 'observation.json', value)
    return case, process.returncode, value


@unittest.skipUnless(os.name == 'nt', 'BLOCKED: native Windows probe hosts required')
class SaclPrivilegeProbeTests(unittest.TestCase):
    def test_explicit_authorization_required_by_caller(self):
        with self.assertRaisesRegex(ValueError, 'EXPLICIT_SESSION_AUTHORIZATION_REQUIRED'):
            run_probe('powershell.exe', None, 'authorized')

    def test_privilege_state_machine_with_fakes_on_both_hosts(self):
        for host, executable in h.required_hosts():
            case, code, value = run_probe(host, executable)
            self.assertEqual(code, 0)
            self.assertEqual(value['cases'], SELF_CASES)
            self.assertFalse((case / 'sacl-read-target.bin').exists())

    def test_native_entrypoint_rejects_no_consent_bad_scope_and_digest(self):
        expected = {'no-consent': 'REJECTED_AUTHORIZATION_REQUIRED', 'bad-scope': 'REJECTED_FIXTURE_SCOPE',
                    'bad-digest': 'REJECTED_SOURCE_DIGEST'}
        for host, executable in h.required_hosts():
            for mode, status in expected.items():
                case, code, value = run_probe(host, executable, mode)
                self.assertEqual(code, 2)
                self.assertEqual(value['status'], status)
                self.assertIs(value['native_privilege_api_invoked'], False)
                self.assertFalse((case / 'sacl-read-target.bin').exists())


if __name__ == '__main__':
    unittest.main()
