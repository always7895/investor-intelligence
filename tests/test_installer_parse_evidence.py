"""Parse-only evidence integrity. No installer body, privilege, DPAPI or live caller."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parse_evidence_harness', ROOT / 'tests/installer_parse_harness.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


@unittest.skipUnless(os.name == 'nt', 'BLOCKED: Windows parse evidence requires both native hosts')
class ParseEvidenceTests(unittest.TestCase):
    def fixture(self):
        # Self-contained controls: clean Git tests must not require an untracked coordinator.
        native = self._testMethodName == 'test_native_control_parse_binds_all_inputs_on_both_hosts'
        case = h.new_case('parse-evidence-native' if native else 'parse-evidence-mock')
        h.write_json(case / 'test-scope.json', {'test': self._testMethodName,
                     'transport': 'NATIVE_PARSE_ONLY' if native else 'MOCKED', 'release_qualified': False})
        inputs = case / 'inputs'; inputs.mkdir()
        roles = ['control', *(role for role, _ in h.PARSE_INPUTS)]
        entries = []
        for index, role in enumerate(roles):
            target = inputs / ('input-' + str(index) + '.ps1')
            data = b"param()\nthrow 'CONTROL_BODY_MUST_NOT_EXECUTE'\n"
            h.write_new(target, data)
            entries.append({'role': role, 'path': str(target), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        manifest = case / 'pure-parse-input.json'
        h.write_json(manifest, {'schema_version': 1, 'main_execution_allowed': False, 'files': entries})
        driver = case / 'parse-only.ps1'
        h.write_new(driver, (ROOT / 'tests/fixtures/v213_parse_only.ps1').read_bytes())
        return case, manifest, driver

    def completion(self, returncode=0, stderr=''):
        return subprocess.CompletedProcess([], returncode, h.PASS_MARKER, stderr)

    def first_record(self, case):
        return json.loads((case / 'powershell_exe-result.json').read_bytes())

    def binding_hash(self, case):
        return hashlib.sha256((case / 'parse-run-inputs.json').read_bytes()).hexdigest()

    def test_changed_input_never_leaves_a_pass_receipt_and_stops_next_host(self):
        fixture = self.fixture(); case = fixture[0]
        def changed(*args, **kwargs):
            with (case / 'inputs/input-0.ps1').open('ab') as stream: stream.write(b'\n# changed')
            return self.completion()
        with patch.object(h, 'prepare_parse_case', return_value=fixture), patch.object(h.subprocess, 'run', side_effect=changed) as run:
            with self.assertRaisesRegex(RuntimeError, 'PARSE_INPUT_CHANGED'):
                h.run_parse_case()
        self.assertEqual(run.call_count, 1)
        record = self.first_record(case)
        self.assertEqual(record['status'], 'UNEXPECTED')
        self.assertEqual(record['returncode'], 0)
        self.assertEqual(record['input_integrity'], 'CHANGED')
        self.assertEqual(record['input_binding_sha256'], self.binding_hash(case))
        self.assertFalse((case / 'pwsh_exe-result.json').exists())

    def test_native_control_parse_binds_all_inputs_on_both_hosts(self):
        fixture = self.fixture(); case = fixture[0]
        with patch.object(h, 'prepare_parse_case', return_value=fixture):
            self.assertEqual(h.run_parse_case(), case)
        binding = json.loads((case / 'parse-run-inputs.json').read_bytes())
        self.assertEqual(binding['harness_sha256'], hashlib.sha256(Path(h.__file__).read_bytes()).hexdigest())
        self.assertEqual(len(binding['inputs']), 8)
        self.assertEqual(binding['hosts'], ['powershell.exe', 'pwsh.exe'])
        self.assertIs(binding['main_execution_allowed'], False)
        self.assertIs(binding['release_qualified'], False)
        for entry in binding['inputs']:
            data = (case / entry['path']).read_bytes()
            self.assertEqual(len(data), entry['bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])
        for host in h.REQUIRED_NATIVE_HOSTS:
            record = json.loads((case / (host.replace('.', '_') + '-result.json')).read_bytes())
            self.assertEqual(record['status'], 'PURE_PARSE_PASS')
            self.assertEqual(record['input_integrity'], 'UNCHANGED')
            self.assertEqual(record['input_binding_sha256'], self.binding_hash(case))

    def test_transport_failure_binds_inputs_and_stops_next_host(self):
        for error, code in ((subprocess.TimeoutExpired('SYNTHETIC_PRIVATE_COMMAND', 1, output=b'SYNTHETIC_PRIVATE_OUTPUT'), 'TIMEOUT'),
                            (OSError('SYNTHETIC_PRIVATE_ERROR'), 'HOST_START_FAILED')):
            fixture = self.fixture(); case = fixture[0]
            with patch.object(h, 'prepare_parse_case', return_value=fixture), patch.object(h.subprocess, 'run', side_effect=error) as run:
                with self.assertRaisesRegex(RuntimeError, 'UNEXPECTED_PARSE_TRANSPORT'):
                    h.run_parse_case()
            self.assertEqual(run.call_count, 1)
            raw = (case / 'powershell_exe/transport-failure.json').read_text()
            value = json.loads(raw)
            self.assertEqual(value['code'], code)
            self.assertEqual(value['input_binding_sha256'], self.binding_hash(case))
            self.assertEqual(value['input_integrity'], 'UNCHANGED')
            self.assertNotIn('SYNTHETIC_PRIVATE', raw)
            self.assertFalse((case / 'pwsh_exe-result.json').exists())

    def test_unavailable_input_blocks_before_process_start(self):
        fixture = self.fixture(); case = fixture[0]
        original_environment = h.isolated_environment
        def unavailable(*args):
            env = original_environment(*args)
            (case / 'inputs/input-0.ps1').rename(case / 'retained-original.ps1')
            return env
        with patch.object(h, 'prepare_parse_case', return_value=fixture), patch.object(h, 'isolated_environment', side_effect=unavailable), patch.object(h.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'PARSE_INPUT_UNAVAILABLE'):
                h.run_parse_case()
        run.assert_not_called()
        value = json.loads((case / 'powershell_exe/transport-failure.json').read_bytes())
        self.assertEqual(value['code'], 'INPUT_UNAVAILABLE')
        self.assertEqual(value['input_integrity'], 'UNAVAILABLE')
        self.assertTrue((case / 'retained-original.ps1').exists())

    def test_primary_returncode_survives_evidence_write_failure_without_private_error(self):
        fixture = self.fixture(); case = fixture[0]
        original_write = h.write_json
        def failed_write(path, value):
            if path.name.endswith('-result.json'):
                raise OSError('SYNTHETIC_PRIVATE_WRITE_ERROR')
            return original_write(path, value)
        with patch.object(h, 'prepare_parse_case', return_value=fixture), patch.object(h, 'write_json', side_effect=failed_write), patch.object(h.subprocess, 'run', return_value=self.completion(17, 'SYNTHETIC_PRIVATE_CHILD')) as run:
            with self.assertRaisesRegex(RuntimeError, 'UNEXPECTED_PARSE_EVIDENCE_WRITE') as error:
                h.run_parse_case()
        self.assertEqual(run.call_count, 1)
        self.assertIn('returncode=17', str(error.exception))
        self.assertIn('primary_status=UNEXPECTED', str(error.exception))
        self.assertNotIn('SYNTHETIC_PRIVATE', str(error.exception))
        self.assertTrue((case / 'parse-run-inputs.json').exists())

    def test_existing_receipt_is_not_overwritten_or_restamped(self):
        fixture = self.fixture(); case = fixture[0]
        receipt = case / 'powershell_exe-result.json'
        h.write_json(receipt, {'status': 'FAILED_PREVIOUS_ATTEMPT'})
        original = receipt.read_bytes()
        with patch.object(h, 'prepare_parse_case', return_value=fixture), patch.object(h.subprocess, 'run', return_value=self.completion()) as run:
            with self.assertRaisesRegex(RuntimeError, 'UNEXPECTED_PARSE_EVIDENCE_WRITE'):
                h.run_parse_case()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(receipt.read_bytes(), original)

    def test_input_change_keeps_nonzero_primary_returncode(self):
        fixture = self.fixture(); case = fixture[0]
        def failed(*args, **kwargs):
            with (case / 'inputs/input-0.ps1').open('ab') as stream: stream.write(b'\n# changed')
            return self.completion(19, 'SYNTHETIC_PRIVATE_CHILD')
        with patch.object(h, 'prepare_parse_case', return_value=fixture), patch.object(h.subprocess, 'run', side_effect=failed) as run:
            with self.assertRaisesRegex(RuntimeError, 'PARSE_INPUT_CHANGED'):
                h.run_parse_case()
        self.assertEqual(run.call_count, 1)
        value = self.first_record(case)
        self.assertEqual(value['returncode'], 19)
        self.assertEqual(value['status'], 'UNEXPECTED')
        self.assertEqual(value['input_integrity'], 'CHANGED')
        self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(value))

    def test_stderr_or_nonzero_cannot_masquerade_as_parse_pass(self):
        for code, stderr in ((1, ''), (0, 'SYNTHETIC_PRIVATE_STDERR')):
            fixture = self.fixture(); case = fixture[0]
            with patch.object(h, 'prepare_parse_case', return_value=fixture), patch.object(h.subprocess, 'run', return_value=self.completion(code, stderr)) as run:
                with self.assertRaisesRegex(AssertionError, 'UNEXPECTED_PURE_PARSE_RESULT'):
                    h.run_parse_case()
            self.assertEqual(run.call_count, 1)
            value = self.first_record(case)
            self.assertEqual(value['status'], 'UNEXPECTED')
            self.assertEqual(value['input_integrity'], 'UNCHANGED')
            self.assertEqual(value['input_binding_sha256'], self.binding_hash(case))
            self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(value))

    def test_binding_itself_is_covered_by_integrity_checks(self):
        fixture = self.fixture(); case = fixture[0]
        before = {}
        def changed(*args, **kwargs):
            before['sha'] = self.binding_hash(case)
            path = case / 'parse-run-inputs.json'
            h.write_new(case / 'retained-original-binding.json', path.read_bytes())
            with path.open('ab') as stream: stream.write(b'\n')
            return self.completion()
        with patch.object(h, 'prepare_parse_case', return_value=fixture), patch.object(h.subprocess, 'run', side_effect=changed) as run:
            with self.assertRaisesRegex(RuntimeError, 'PARSE_INPUT_CHANGED'):
                h.run_parse_case()
        self.assertEqual(run.call_count, 1)
        value = self.first_record(case)
        self.assertEqual(value['status'], 'UNEXPECTED')
        self.assertEqual(value['input_binding_sha256'], before['sha'])
        self.assertNotEqual(before['sha'], self.binding_hash(case))


if __name__ == '__main__':
    unittest.main()
