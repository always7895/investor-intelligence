import copy
import json
from pathlib import Path
import sys
import unittest
import os
import threading
import time
import tempfile
import subprocess
import shutil
import re
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from v213_model_profile import validate_profile, parse_profile, profile_sha256
from v213_compact_qa_gateway import compact_upstream, POLICY

PROFILE = dict(schema_version=1, model='synthetic-model-a', enable_thinking=True,
               reasoning_effort='xhigh', max_output_tokens=1024, smoke_output_tokens=128, timeout_ms=18000)


class ModelProfileTests(unittest.TestCase):
    def body(self, profile):
        return dict(model=profile['model'], ii_context_mode=POLICY['smoke_mode'],
                    ii_model_profile=copy.deepcopy(profile),
                    messages=[dict(role='user', content=POLICY['smoke_prompt'])])

    @unittest.skipUnless(os.name == 'nt', 'Windows native launcher')
    def test_compiled_exe_profile_persistence_and_child_propagation(self):
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        self.assertTrue(compiler.is_file())
        source = ROOT / 'launcher/InvestorIntelligenceLauncher.cs'
        required = source.read_text(encoding='utf-8').split('string[] required = {', 1)[1].split('};', 1)[0]
        with tempfile.TemporaryDirectory(prefix='Profile EXE 測試 (1) ') as directory:
            stage = Path(directory)
            for relative in re.findall(r'@?"([^"]+)"', required) + ['config/v213-model-profile-v1.json']:
                destination = stage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            exe = stage / 'InvestorIntelligence.exe'
            result = subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:anycpu',
                '/reference:System.dll', '/reference:System.Core.dll', '/reference:System.Drawing.dll',
                '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll',
                '/out:' + str(exe), str(source)], capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, 'Native profile launcher compilation failed')
            for flag in ('--model-profile-self-test', '--model-selection-self-test', '--self-test', '--pipe-hold-self-test'):
                with self.subTest(flag=flag):
                    result = subprocess.run([str(exe), flag], capture_output=True, timeout=45)
                    self.assertEqual(result.returncode, 0)
            self._assert_native_catalog_transport(exe)

    def _assert_native_catalog_transport(self, exe):
        mode = ['valid']
        paths = []
        body = json.dumps({'data': [{'id': PROFILE['model']}]}).encode()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                paths.append(self.path)
                selected = mode[0]
                if selected == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', '/must-not-follow')
                    self.end_headers()
                    return
                if selected == 'alias' and self.path == '/models':
                    self.send_response(404); self.end_headers(); return
                self.send_response(200)
                payload = b'\xff' if selected == 'invalid_utf8' else b'{broken' if selected == 'invalid_json' else body
                if selected in ('oversize_header', 'oversize_stream'):
                    payload = b'x' * (1024 * 1024 + 1)
                if selected != 'oversize_stream':
                    self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                try:
                    if selected == 'slow_stream':
                        for byte in payload:
                            self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(0.15)
                    else:
                        self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        child_env = {**os.environ, 'V213_MODEL_PROFILE_JSON': json.dumps(PROFILE)}
        try:
            for case in ('valid', 'alias', 'redirect', 'invalid_utf8', 'invalid_json', 'oversize_header', 'oversize_stream', 'slow_stream'):
                with self.subTest(catalog=case):
                    mode[0] = case; paths.clear()
                    result = subprocess.run([str(exe), '--model-catalog-check', base],
                                            env=child_env, capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 0 if case in ('valid', 'alias') else 71)
                    self.assertEqual(paths, ['/models'] if case == 'valid' else ['/models', '/v1/models'])
                    self.assertNotIn(b'{broken', result.stdout + result.stderr)
            for suffix in ('?key=fixture', '#fixture', '/path'):
                paths.clear()
                result = subprocess.run([str(exe), '--model-catalog-check', base + suffix],
                                        env=child_env, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 70)
                self.assertEqual(paths, [])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_actual_profile_cli_and_bounded_invalid_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            for valid in (True, False):
                path.write_text(json.dumps(PROFILE if valid else {**PROFILE, 'unreviewed': 'SYNTHETIC_PRIVATE_VALUE'}), encoding='utf-8')
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/v213_model_profile.py'), '--profile', str(path)],
                                        cwd=directory, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0 if valid else 1)
                self.assertNotIn('SYNTHETIC_PRIVATE_VALUE', result.stdout + result.stderr)
                if valid:
                    self.assertEqual(json.loads(result.stdout)['profile_sha256'], profile_sha256(PROFILE))
                    self.assertFalse(json.loads(result.stdout)['release_qualified'])

    def test_cross_runtime_digest_vector(self):
        self.assertEqual(profile_sha256(PROFILE), '2bea7c8ce0f160ea609ddf82c7f34631a6841f9a939debdb0a663444b5307d19')
        self.assertEqual(parse_profile(json.dumps(PROFILE)), PROFILE)

    def test_model_and_thinking_change_without_code_changes(self):
        for model, thinking, effort in [('synthetic-model-a', True, 'xhigh'), ('other/model-v2', False, 'none')]:
            profile = {**PROFILE, 'model': model, 'enable_thinking': thinking, 'reasoning_effort': effort}
            result = compact_upstream(self.body(profile), model, profile)
            self.assertEqual(result['model'], model)
            self.assertEqual(result['reasoning_effort'], effort)
            self.assertEqual(result['chat_template_kwargs']['enable_thinking'], thinking)
            self.assertEqual(result['max_tokens'], profile['smoke_output_tokens'])
            self.assertNotIn('ii_model_profile', result)

    def test_duplicate_unknown_invalid_and_conflicting_fields_fail_closed(self):
        with self.assertRaises(ValueError):
            parse_profile(json.dumps(PROFILE)[:-1] + ',"model":"hidden"}')
        for key, value in [('schema_version', True), ('model', 'bad\nmodel'), ('model', 'x' * 201), ('enable_thinking', 'true'),
                           ('reasoning_effort', []), ('reasoning_effort', 'unknown'), ('reasoning_effort', 'none'),
                           ('max_output_tokens', True), ('max_output_tokens', 8193),
                           ('smoke_output_tokens', 1025), ('timeout_ms', 20001), ('extra', 'unreviewed')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_profile({**PROFILE, key: value})

    def test_client_cannot_select_profile_or_silently_downgrade(self):
        for change in ({'model': 'other'}, {'enable_thinking': False, 'reasoning_effort': 'none'}, {'timeout_ms': 1000}):
            body = self.body(PROFILE)
            body['ii_model_profile'].update(change)
            with self.assertRaises(ValueError):
                compact_upstream(body, PROFILE['model'], PROFILE)
        for body, profile in [(self.body(PROFILE), None),
                              ({**self.body(PROFILE), 'ii_model_profile': None}, PROFILE),
                              ({**self.body(PROFILE), 'ii_context_mode': None}, PROFILE)]:
            with self.assertRaises(ValueError):
                compact_upstream(body, PROFILE['model'], profile)

    def test_actual_authenticated_gateway_enforces_profile_and_completion(self):
        import v213_local_llm_gateway as gateway
        import secrets
        auth_value = secrets.token_hex(32)
        response = Mock(ok=True)
        response.json.return_value = {'model': PROFILE['model'], 'choices': [
            {'finish_reason': 'stop', 'message': {'content': 'synthetic complete answer'}}]}
        server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.V213GatewayHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        def call(body, auth=auth_value):
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                data=json.dumps(body).encode(), headers={'content-type': 'application/json', 'x-investor-shared-secret': auth})
            try:
                result = urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as exc:
                result = exc
            with result:
                return result.status, json.load(result)
        with patch.dict(os.environ, {'II_LOCAL_LLM_SHARED_SECRET': auth_value, 'II_LOCAL_LLM_MODEL': 'ignored-legacy-selection',
                                     'V213_MODEL_PROFILE_JSON': json.dumps(PROFILE)}), \
             patch.object(gateway, '_available_model_catalog', return_value=[{'id': PROFILE['model']}]), \
             patch.object(gateway.requests, 'post', return_value=response) as upstream:
            thread.start()
            try:
                self.assertEqual(call(self.body(PROFILE), 'wrong')[0], 401)
                self.assertEqual(upstream.call_count, 0)
                status, result = call(self.body(PROFILE))
                self.assertEqual(status, 200)
                self.assertEqual(result['ii_exact_model_pin']['model_profile_sha256'], profile_sha256(PROFILE))
                self.assertEqual(upstream.call_args.kwargs['json']['reasoning_effort'], 'xhigh')
                self.assertTrue(upstream.call_args.kwargs['json']['chat_template_kwargs']['enable_thinking'])
                self.assertEqual(upstream.call_args.kwargs['timeout'], (2, 18))
                changed = self.body(PROFILE)
                changed['ii_model_profile']['reasoning_effort'] = 'high'
                self.assertEqual(call(changed)[0], 400)
                self.assertEqual(upstream.call_count, 1)
                response.json.return_value['choices'][0]['finish_reason'] = 'length'
                status, result = call(self.body(PROFILE))
                self.assertEqual(status, 502)
                self.assertEqual(result['failure_kind'], 'INCOMPLETE')
                upstream.side_effect = gateway.requests.Timeout('SYNTHETIC_PRIVATE_VALUE')
                status, result = call(self.body(PROFILE))
                self.assertEqual(status, 504)
                self.assertEqual(result, {'error': 'MODEL_PROFILE_TIMEOUT'})
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_every_configuration_change_invalidates_digest(self):
        for key, value in [('model', 'other'), ('reasoning_effort', 'high'), ('max_output_tokens', 512),
                           ('smoke_output_tokens', 64), ('timeout_ms', 10000)]:
            self.assertNotEqual(profile_sha256(PROFILE), profile_sha256({**PROFILE, key: value}))


if __name__ == '__main__':
    unittest.main()
