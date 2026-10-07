"""M6 actual v213 HTTP caller to owned fake Strata; no :8814/shared server."""
import copy
import json
import os
import secrets
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from tests.batch07_fixtures import ROOT, PROFILE, FakeStrata, isolated_intent, profile, save
import v213_local_llm_gateway as gateway
from v213_compact_qa_gateway import POLICY


@contextmanager
def answer_chain():
    with isolated_intent(), FakeStrata() as fake:
        save(fake.base)
        intent = profile.resolve_binding(str(ROOT))
        auth = secrets.token_hex(32)  # ephemeral fixture only; never printed/persisted
        with patch.dict(os.environ, {'II_LOCAL_LLM_SHARED_SECRET': auth}), \
                patch.object(gateway, '_START_BINDING_STATE', intent), \
                patch.object(gateway._LOOPBACK_SESSION, 'request', side_effect=AssertionError('NO_LEGACY_TRANSPORT')), \
                patch.object(gateway, '_decision_client', side_effect=AssertionError('NO_DECIDER_SERVER')), \
                patch.object(gateway.base.GatewayHandler, 'log_message', return_value=None):
            server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.V213GatewayHandler)
            assert server.server_port not in {5000, 8000, 8080, 8081, 8814}
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def call(body, authorized=True):
                request = urllib.request.Request('http://127.0.0.1:' + str(server.server_port) + '/v1/chat/completions',
                    data=json.dumps(body).encode(), headers={'content-type': 'application/json',
                    'x-investor-shared-secret': auth if authorized else 'wrong-fixture'})
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                try:
                    response = opener.open(request, timeout=10)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    return response.status, json.load(response)

            try:
                yield fake, intent, call
            finally:
                server.shutdown()
                server.server_close()
                thread.join(5)
                assert not thread.is_alive()


def body():
    return dict(model=PROFILE['model'], ii_context_mode=POLICY['smoke_mode'], ii_model_profile=copy.deepcopy(PROFILE),
                messages=[dict(role='user', content=POLICY['smoke_prompt'])])


class GatewayCallers(unittest.TestCase):
    def test_complete_answer_chain_propagates_both_digests_and_profile(self):
        with answer_chain() as (fake, intent, call):
            status, result = call(body())
            self.assertEqual(status, 200)
            pin = result['ii_exact_model_pin']
            self.assertEqual(pin['runtime_binding_sha256'], intent['binding_sha256'])
            self.assertEqual(pin['model_profile_sha256'], intent['profile_sha256'])
            self.assertEqual(pin['qualification'], 'UNQUALIFIED')
            self.assertEqual(result['choices'][0]['message']['content'], 'synthetic complete answer')
            posts = [c for c in fake.calls if c[0] == 'POST']
            self.assertEqual(len(posts), 2)  # structured capability then product completion
            self.assertIn('response_format', posts[0][2])
            sent = posts[1][2]
            self.assertEqual(sent['model'], PROFILE['model'])
            self.assertEqual(sent['max_tokens'], PROFILE['smoke_output_tokens'])
            self.assertEqual(sent['reasoning_effort'], 'none')
            self.assertFalse(sent['chat_template_kwargs']['enable_thinking'])
            self.assertTrue(all(c[1] in ('/health', '/v1/models', '/v1/chat/completions') for c in fake.calls))
            self.assertNotIn('release_qualified', result)

    def test_auth_exact_model_and_request_profile_refuse_before_backend(self):
        with answer_chain() as (fake, _, call):
            self.assertEqual(call(body(), authorized=False)[0], 401)
            changed = body()
            changed['model'] = PROFILE['model'].upper()
            self.assertEqual(call(changed)[0], 409)
            changed = body()
            changed['ii_model_profile']['timeout_ms'] = 1000
            self.assertEqual(call(changed)[0], 400)
            self.assertEqual(fake.calls, [])

    def test_identity_metadata_failure_never_generates(self):
        with answer_chain() as (fake, _, call):
            fake.health['model'] = 'not-selected'
            status, result = call(body())
            self.assertEqual(status, 502)
            self.assertEqual(result, {'error': 'LOCAL_GATEWAY_FAILED', 'detail': 'BindingUnavailable'})
            self.assertEqual([(c[0], c[1]) for c in fake.calls], [('GET', '/health')])

    def test_incomplete_or_wrong_model_cannot_be_a_complete_answer(self):
        with answer_chain() as (fake, _, call):
            fake.response['choices'][0]['finish_reason'] = 'length'
            status, result = call(body())
            self.assertEqual(status, 502)
            self.assertEqual(result['failure_kind'], 'INCOMPLETE')
            fake.response['choices'][0]['finish_reason'] = 'stop'
            fake.response['model'] = 'wrong-model'
            status, result = call(body())
            self.assertNotEqual(status, 200)
            self.assertNotIn('ii_exact_model_pin', result)

    def test_identity_change_during_product_post_rejects_result_and_next_request(self):
        with answer_chain() as (fake, _, call):
            def change(payload):
                if 'response_format' not in payload:
                    save('http://127.0.0.1:49200')  # offline intent; never contact this root
            fake.post_hook = change
            status, result = call(body())
            self.assertEqual(status, 502)
            self.assertEqual(result['detail'], 'BindingUnavailable')
            fake.calls.clear()
            self.assertEqual(call(body()), (503, {'error': 'RUNTIME_BINDING_UNAVAILABLE'}))
            self.assertEqual(fake.calls, [])

    def test_separate_marker_operation_requires_literal_complete_response(self):
        with isolated_intent(), FakeStrata() as fake:
            save(fake.base)
            fake.response['choices'][0]['message']['content'] = POLICY['smoke_prompt'].removeprefix('Reply exactly ')
            result = profile.selected_route_check({'root': str(ROOT)})
            self.assertTrue(result['complete_exact_marker'])
            self.assertFalse(result['release_qualified'])
            self.assertEqual(result['qualification'], 'UNQUALIFIED')
            fake.response['choices'][0]['message']['content'] = 'not-the-marker'
            with self.assertRaisesRegex(ValueError, 'BINDING_COMPLETE_MARKER_UNAVAILABLE'):
                profile.selected_route_check({'root': str(ROOT)})


if __name__ == '__main__':
    unittest.main()
