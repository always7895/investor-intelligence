"""Actual HTTP handler and real bounded child tests; no real LINE/model calls."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v213_pi_transport as pi
import v213_local_llm_gateway as gateway
from test_v213_r75_gateway_process import request


def body():
    return {'model': pi.PROFILE['model_id'], 'messages': [{'role': 'user', 'content': 'Public methodology?'}], 'ii_context_mode': pi.MODE}


def result():
    return {'model': pi.PROFILE['model_id'], 'provider': 'llama.cpp', 'thinking_level': 'xhigh',
            'finish_reason': 'stop', 'xhigh_payload_validated': True, 'tools_executed': 0,
            'production_ready': False, 'content': 'Public answer'}


class PiTransportTests(unittest.TestCase):
    def test_strict_canonical_protocol_no_silent_context_loss(self):
        self.assertEqual(pi.validate_body(body(), pi.PROFILE['model_id'])['query'], 'Public methodology?')
        for field, value in [('model', 'qwen38-q6'), ('ii_context_mode', 'compact_public_v1'),
                             ('context', {'freshness': 'FRESH'}), ('sdk_entry', 'malicious')]:
            b = body(); b[field] = value
            with self.assertRaises(pi.PiTransportError): pi.validate_body(b, pi.PROFILE['model_id'])
        b = body(); b['messages'].insert(0, {'role': 'system', 'content': 'private context'})
        with self.assertRaises(pi.PiTransportError): pi.validate_body(b, pi.PROFILE['model_id'])

    def test_child_proof_types_and_allowlisted_output(self):
        r = result(); r['private_extra'] = 'not forwarded'
        self.assertNotIn('private_extra', pi.validate_result(r))
        for field, value in [('tools_executed', False), ('production_ready', 0), ('finish_reason', 'length'),
                             ('xhigh_payload_validated', 1), ('thinking_level', 'high'), ('model', 'qwen38-q6')]:
            r = result(); r[field] = value
            with self.assertRaises(pi.PiTransportError): pi.validate_result(r)

    def test_child_does_not_inherit_credentials_proxy_or_node_injection(self):
        with patch.dict(os.environ, {'LINE_CHANNEL_ACCESS_TOKEN': 'synthetic-not-real',
                                     'NODE_OPTIONS': '--require=untrusted', 'HTTPS_PROXY': 'https://example.invalid',
                                     'II_LOCAL_LLM_SHARED_SECRET': 'synthetic-not-real'}):
            env = pi.child_environment()
        for key in ['LINE_CHANNEL_ACCESS_TOKEN', 'NODE_OPTIONS', 'HTTPS_PROXY', 'II_LOCAL_LLM_SHARED_SECRET']:
            self.assertNotIn(key, env)

    def test_real_child_utf8_spaces_unicode_and_no_prompt_persistence(self):
        with tempfile.TemporaryDirectory(prefix='Pi 測試 (1) ') as folder:
            script = Path(folder) / 'child (1).py'
            script.write_text("import json,sys,os\nx=json.load(sys.stdin)\nassert 'II_LOCAL_LLM_SHARED_SECRET' not in os.environ\nprint(json.dumps({'content':x['query']},ensure_ascii=False))", encoding='utf-8')
            raw = pi._bounded_child([sys.executable, str(script)], {'query': '公開研究'}, 5)
            self.assertEqual(json.loads(raw)['content'], '公開研究')
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['child (1).py'])

    def test_actual_child_output_limit_timeout_and_failure_are_redacted(self):
        for code, timeout, expected in [
            ("import sys; sys.stdout.write('x'*100000)", 5, 'PI_CHILD_OUTPUT_LIMIT'),
            ("import time; time.sleep(30)", .1, 'PI_CHILD_TIMEOUT'),
            ("import sys; sys.stderr.write('PRIVATE_SENTINEL'); sys.exit(2)", 5, 'PI_CHILD_FAILED')]:
            with self.assertRaisesRegex(pi.PiTransportError, expected):
                pi._bounded_child([sys.executable, '-c', code], {'query': 'fixture'}, timeout)

    def test_transport_capacity_rejects_without_starting_child(self):
        with patch.dict(os.environ, {'II_PI_SDK_ENTRY': str(Path(__file__).resolve())}), patch.object(pi.shutil, 'which', return_value=sys.executable):
            pi.SLOTS.acquire()
            try:
                with patch.object(pi, '_bounded_child') as child:
                    with self.assertRaisesRegex(pi.PiTransportError, 'PI_CAPACITY_EXHAUSTED'):
                        pi.complete(body(), pi.PROFILE['model_id'])
                    child.assert_not_called()
            finally:
                pi.SLOTS.release()

    def test_actual_authenticated_gateway_routes_pi_and_never_direct_fallback(self):
        secret = 'synthetic-gateway-fixture-' * 2
        with patch.dict(os.environ, {'II_LOCAL_LLM_BACKEND': 'pi', 'II_LOCAL_LLM_MODEL': pi.PROFILE['model_id'], 'II_LOCAL_LLM_SHARED_SECRET': secret}), \
             patch.object(gateway, '_available_model_catalog', return_value=[{'id': pi.PROFILE['model_id']}]), \
             patch.object(gateway.requests, 'post') as direct, \
             patch.object(pi, 'complete', return_value=pi.validate_result(result())) as invoke:
            server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.V213GatewayHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            url = f'http://127.0.0.1:{server.server_port}/v1/chat/completions'
            try:
                status, _, _ = request(url, body=body())
                self.assertEqual(status, 401); invoke.assert_not_called()
                status, answer, _ = request(url, body=body(), secret=secret)
                self.assertEqual(status, 200)
                self.assertEqual(answer['ii_pi']['thinking_level'], 'xhigh')
                self.assertEqual(answer['ii_exact_model_pin']['selected_model'], pi.PROFILE['model_id'])
                invoke.side_effect = pi.PiTransportError('PI_CHILD_TIMEOUT')
                self.assertEqual(request(url, body=body(), secret=secret)[0], 504)
                invoke.side_effect = pi.PiTransportError('PI_CAPACITY_EXHAUSTED')
                self.assertEqual(request(url, body=body(), secret=secret)[0], 429)
                direct.assert_not_called()
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_pi_health_cannot_certify_generation(self):
        with patch.dict(os.environ, {'II_LOCAL_LLM_BACKEND': 'pi'}):
            health = gateway._build_health_payload(pi.PROFILE['model_id'], [pi.PROFILE['model_id']], True)
        self.assertFalse(health['production_ready'])
        self.assertFalse(health['thinking_verified_by_health'])

if __name__ == '__main__': unittest.main()
