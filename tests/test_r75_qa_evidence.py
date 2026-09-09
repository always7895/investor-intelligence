import copy
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_r75_qa_evidence import verify
from v213_model_profile import parse_profile, profile_sha256
from v213_qa_live_gate import router_limits, validate_router_proof, wait_isolated_origin, isolated_transport_diagnostics

class LiveQaQualificationTests(unittest.TestCase):
    def setUp(self):
        self.proof = json.loads((ROOT / 'state/r75-qa-live-qualification.json').read_text(encoding='utf-8-sig'))
        self.manifest = copy.deepcopy(self.proof['source_manifest'])
        # In-memory synthetic verifier fixture, never a regenerated live receipt.
        self.now = datetime.now(timezone.utc)
        self.proof['started_at'] = (self.now - timedelta(minutes=1)).isoformat()
        self.proof['completed_at'] = self.now.isoformat()

    def test_failed_gate_diagnostics_are_scoped_bounded_and_not_qualification(self):
        origin = 'https://ii-r75-qa-bench-012345abcd.synthetic.workers.dev'
        version = '12345678-1234-1234-1234-123456789abc'
        body = {'scope': 'ISOLATED_TRANSPORT_DIAGNOSTIC', 'release_qualified': False,
                'http_status': 200, 'body_kind': 'other', 'nonce_match': True,
                'version_match': True, 'ready': True, 'proxy_bypassed': True, 'direct_requested': False}
        response = SimpleNamespace(status_code=200, text='{}', content=b'{}')
        session = SimpleNamespace(get=Mock(return_value=response))
        with patch('v213_qa_live_gate.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(body))) as run:
            rows = isolated_transport_diagnostics(session, origin, version)
            self.assertEqual(run.call_count, 3)
            self.assertTrue(all(r['release_qualified'] is False for r in rows))
            self.assertEqual(session.get.call_count, 1)
            self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
            self.assertEqual(session.get.call_args.kwargs['timeout'], 10)
            for bad in ('https://production.synthetic.workers.dev', origin + '/path', origin + '?secret=redacted'):
                with self.assertRaisesRegex(RuntimeError, 'SCOPE_INVALID'):
                    isolated_transport_diagnostics(session, bad, version)
            self.assertEqual(run.call_count, 3)
        with patch('v213_qa_live_gate.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps({**body, 'private': 'PRIVATE_SENTINEL'}))):
            rows = isolated_transport_diagnostics(session, origin, version)
            self.assertTrue(rows[0]['diagnostic_failed'])
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(rows))

    def test_only_new_test_host_empty_cloudflare_page_can_wait(self):
        pending=SimpleNamespace(status_code=404, headers={'server':'cloudflare'}, text='There is nothing here yet')
        ready=SimpleNamespace(status_code=200, json=lambda:{'ok':True,'product_version':'2.1.3','top20_presentation':'seven_fields'})
        session=SimpleNamespace(get=Mock(side_effect=[pending,ready]))
        now=[0.0]
        result=wait_isolated_origin(session,'https://ii-r75-qa-bench-012345abcd.synthetic.workers.dev',lambda:now[0],lambda n:now.__setitem__(0,now[0]+n))
        self.assertEqual(result['initial_empty_worker_404_count'],1)
        with self.assertRaisesRegex(RuntimeError,'SCOPE_INVALID'):
            wait_isolated_origin(session,'https://production.synthetic.workers.dev')
        for status in (301,401,403,404,429,500):
            bad=SimpleNamespace(status_code=status,headers={'server':'cloudflare'},text='arbitrary failure')
            session=SimpleNamespace(get=Mock(return_value=bad))
            with self.subTest(status=status),self.assertRaisesRegex(RuntimeError,'UNEXPECTED_HTTP'):
                wait_isolated_origin(session,'https://ii-r75-qa-bench-012345abcd.synthetic.workers.dev')
            self.assertEqual(session.get.call_count,1)
        now=[0.0];session=SimpleNamespace(get=Mock(return_value=pending))
        with self.assertRaisesRegex(RuntimeError,'PROVISIONING_TIMEOUT'):
            wait_isolated_origin(session,'https://ii-r75-qa-bench-012345abcd.synthetic.workers.dev',lambda:now[0],lambda n:now.__setitem__(0,now[0]+n))
        self.assertEqual(now[0],20)

    @unittest.skipUnless(sys.platform == 'win32', 'native PowerShell transport')
    def test_readiness_http_error_cannot_become_ready_json(self):
        import http.server, threading, subprocess, shutil, os
        state = {'status': 200, 'ready': True}
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                state.setdefault('paths', []).append(self.path)
                body = json.dumps({'ready': state['ready'], 'code': 'V213_READINESS_VERSION_MISMATCH',
                                   'note': 'PRIVATE_DIAGNOSTIC_SENTINEL'}).encode()
                if state['ready'] == 'invalid_utf8': body = b'\xff'
                if state['ready'] == 'oversize': body = b' ' * 1048577
                self.send_response(state['status']); self.send_header('Content-Length', str(len(body)))
                if state['status'] == 302: self.send_header('Location', '/must-not-follow')
                self.end_headers()
                try: self.wfile.write(body)
                except (ConnectionError, OSError): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            helper = str(ROOT / 'scripts/v213_edge_readiness.ps1').replace("'", "''")
            command = f"$ErrorActionPreference='Stop';. '{helper}'; Invoke-V213ReadinessGet 'http://127.0.0.1:{server.server_port}/v213/readiness'|Out-Null"
            for shell in ('powershell.exe', 'pwsh.exe'):
                if not shutil.which(shell): continue
                for status, ready in ((200, True), (409, False), (409, True), (409, [False]), (500, True), (404, True), (302, True), (200, 'invalid_utf8'), (200, 'oversize')):
                    with self.subTest(shell=shell, status=status, ready=ready):
                        state.update(status=status, ready=ready, paths=[])
                        env = {**os.environ, 'HTTP_PROXY': 'http://127.0.0.1:9', 'HTTPS_PROXY': 'http://127.0.0.1:9', 'ALL_PROXY': 'http://127.0.0.1:9', 'NO_PROXY': ''}
                        result = subprocess.run([shell, '-NoProfile', '-Command', command], env=env, capture_output=True, timeout=20)
                        self.assertEqual(result.returncode == 0, (status == 200 and ready is True) or (status == 409 and ready is False))
                        self.assertEqual(state['paths'], ['/v213/readiness'])
                        self.assertNotIn(b'PRIVATE_DIAGNOSTIC_SENTINEL', result.stdout + result.stderr)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_router_proof_rejects_empty_multiple_or_non_integer_limits(self):
        listener = {'pid': 17, 'name': 'llama-server'}
        props = {'role': 'router', 'max_instances': 1}
        for invalid in (None, {}, [], [listener], {**listener, 'pid': True}, {**listener, 'name': 'unrelated'}):
            with self.subTest(listener=invalid), self.assertRaises(RuntimeError):
                validate_router_proof(invalid, props)
        for invalid in (None, {}, {**props, 'role': 'model'}, {**props, 'max_instances': True}, {**props, 'max_instances': 2}, {**props, 'max_instances': '1'}):
            with self.subTest(props=invalid), self.assertRaises(RuntimeError):
                validate_router_proof(listener, invalid)
        with patch('v213_qa_live_gate.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(listener))), patch('v213_qa_live_gate.requests.get', return_value=SimpleNamespace(status_code=200,json=lambda:props)) as get:
            self.assertEqual(router_limits()['models_max'],1)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_canonical_model_receipt_requires_unique_catalog(self):
        data = copy.deepcopy(self.proof)
        canonical = 'Qwen3.8-27B-UD-Q6_K_XL-844843d973bf'
        # In-memory synthetic verifier fixture only; never rewrite the live receipt.
        data.update(seven_field_line_reply='PASS_REAL_WORKER_MOCK_LINE', bilingual_field_count=7,
                    top20_rows=20, production_health_presentation='seven_fields', line_presentation='flex_carousel',
                    line_message_count=4, line_values_match=True, text_fallback_values_match=True, text_message_count=2)
        data['canonical_model'] = canonical
        data['model_catalog'] = [{'id': canonical, 'aliases': ['qwen38-q6']}]
        for row in data['results']: row['model'] = canonical
        self.assertTrue(verify(data, self.manifest)['release_ready'])
        for catalog in (None, [], [{'id': canonical}], data['model_catalog'] + [{'id':'other','aliases':['qwen38-q6']}]):
            with self.subTest(catalog=catalog), self.assertRaisesRegex(ValueError, 'CATALOG_PROOF_INVALID'):
                verify({**data, 'model_catalog': catalog}, self.manifest)

    def test_readiness_only_cannot_be_relabelled_as_release_pass(self):
        data=copy.deepcopy(self.proof)
        data.update(status='PASS',scope='READINESS_ONLY')
        with self.assertRaisesRegex(ValueError,'READINESS_ONLY_NOT_RELEASE_QUALIFICATION'):
            verify(data,self.manifest)

    def test_synthetic_complete_matrix_still_binds_exact_runtime_source(self):
        # Exercise the default manifest-loader path with an explicitly synthetic
        # runtime. A historical receipt must not be required to certify new code.
        # No receipt, clock or production verifier is rewritten by this test.
        with patch('verify_r75_qa_evidence.source_manifest', return_value=self.manifest) as loader:
            self.assertTrue(verify(self.proof, now=self.now)['release_ready'])
            loader.assert_called_once_with()
        changed = copy.deepcopy(self.manifest)
        runtime_path = next(p for p in changed if p != 'scripts/v213_qa_live_gate.py')
        changed[runtime_path] = '0' * 64 if changed[runtime_path] != '0' * 64 else '1' * 64
        with patch('verify_r75_qa_evidence.source_manifest', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'LIVE_SOURCE_MANIFEST_MISMATCH'):
                verify(self.proof, now=self.now)

    def test_profile_receipt_binds_intended_settings_driver_and_observed_mode(self):
        profile = parse_profile((ROOT / 'config/v213-model-profile-v1.json').read_text(encoding='utf-8-sig'))
        data = copy.deepcopy(self.proof)
        data.update(schema_version=2, model_profile=profile, model_profile_sha256=profile_sha256(profile),
                    exact_model=profile['model'], canonical_model=profile['model'],
                    model_catalog=[{'id': profile['model'], 'aliases': []}], profile_mismatch='PASS')
        for row in data['results']:
            row.update(model=profile['model'], reasoning_present=False)
        for row in data['readiness']:
            row['model_profile_sha256'] = profile_sha256(profile)
        self.assertTrue(verify(data, self.manifest, expected_profile=profile)['release_ready'])
        with self.assertRaisesRegex(ValueError, 'LIVE_PROFILE_DOWNGRADE'):
            verify(self.proof, self.manifest, expected_profile=profile)
        for field, value in [('model_profile_sha256', '0'*64), ('profile_mismatch', 'FAIL'), ('exact_model', 'wrong')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify({**data, field:value}, self.manifest, expected_profile=profile)
        changed = copy.deepcopy(self.manifest)
        changed['scripts/v213_qa_live_gate.py'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'LIVE_SOURCE_MANIFEST_MISMATCH'):
            verify(data, changed, expected_profile=profile)
        for section, field, value, error in [('results','reasoning_present',True,'UNEXPECTED_REASONING'),
                                           ('readiness','model_profile_sha256','0'*64,'READINESS_PROFILE_MISMATCH')]:
            invalid = copy.deepcopy(data); invalid[section][0][field] = value
            with self.subTest(section=section), self.assertRaisesRegex(ValueError,error):
                verify(invalid,self.manifest,expected_profile=profile)
        invalid = copy.deepcopy(data)
        smoke = next(row for row in invalid['results'] if row['case']=='smoke')
        smoke['usage']['completion_tokens'] = profile['smoke_output_tokens']+1
        with self.assertRaisesRegex(ValueError,'OUTPUT_TOKEN_PROOF_INVALID'):
            verify(invalid,self.manifest,expected_profile=profile)
        thinking = {**profile, 'enable_thinking':True,'reasoning_effort':'high'}
        invalid = {**data,'model_profile':thinking,'model_profile_sha256':profile_sha256(thinking)}
        with self.assertRaisesRegex(ValueError,'LIVE_THINKING_CAPABILITY_UNPROVEN'):
            verify(invalid,self.manifest,expected_profile=thinking)

    def test_historical_untimestamped_receipt_cannot_qualify_release(self):
        original = json.loads((ROOT / 'state/r75-qa-live-qualification.json').read_text(encoding='utf-8-sig'))
        original.pop('started_at', None)
        original.pop('completed_at', None)
        with self.assertRaisesRegex(ValueError, 'LIVE_TIMESTAMP_MISSING'):
            verify(original, self.manifest, now=self.now)

    def test_missing_naive_future_stale_and_reversed_timestamps_fail_closed(self):
        cases = [
            ('started_at', None, 'LIVE_TIMESTAMP_MISSING'),
            ('completed_at', 'not-a-date', 'LIVE_TIMESTAMP_INVALID'),
            ('completed_at', self.now.replace(tzinfo=None).isoformat(), 'TIMEZONE_REQUIRED'),
            ('started_at', (self.now - timedelta(hours=25)).isoformat(), 'LIVE_PROOF_STALE'),
            ('completed_at', (self.now + timedelta(minutes=6)).isoformat(), 'LIVE_TIMESTAMP_FUTURE'),
            ('started_at', (self.now + timedelta(seconds=1)).isoformat(), 'TIMESTAMP_ORDER_INVALID'),
        ]
        for field, value, code in cases:
            data = copy.deepcopy(self.proof)
            data[field] = value
            with self.subTest(field=field, code=code), self.assertRaisesRegex(ValueError, code):
                verify(data, self.manifest, now=self.now)
        with self.assertRaisesRegex(ValueError, 'LIVE_CLOCK_INVALID'):
            verify(self.proof, self.manifest, now=self.now.replace(tzinfo=None))

    def test_missing_partial_incomplete_or_synthetic_only_is_rejected(self):
        for field, value in [('status','PASS_SYNTHETIC'),('production_mutation',True),('real_line_sent',True),('preset_unchanged',False),('isolated_resources_deleted',False),('source_manifest',{}),('exact_model','qwen38'),('reference_job','PASS_SYNTHETIC'),('results',[]),('line_values_match',False),('text_fallback_values_match',False),('line_message_count',6),('text_message_count',6)]:
            data=copy.deepcopy(self.proof);data[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify(data,self.manifest)

    def test_latency_truncation_tokens_or_model_errors_fail_closed(self):
        for field,value in [('total_ms',28001),('total_ms',True),('finish_reason','length'),('pass',False),('model','qwen38'),('usage',{}),('http_status',502)]:
            data=copy.deepcopy(self.proof);data['results'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify(data,self.manifest)

    def test_old_schema_wrong_version_and_duplicate_cases_are_rejected(self):
        for field,value in [('parser_schema','old'),('worker_version','old'),('no_write',False),('publication_contract_sha256','bad')]:
            data=copy.deepcopy(self.proof);data['readiness'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify(data,self.manifest)
        data=copy.deepcopy(self.proof);data['results'][0]=copy.deepcopy(data['results'][1])
        with self.assertRaises(ValueError):verify(data,self.manifest)

if __name__=='__main__':unittest.main()
