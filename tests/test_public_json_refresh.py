"""Existing SEC/World Bank JSON caller boundaries; public synthetic data only."""
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v21_serenity_top20 as engine
import build_v212_top20_report as builder
import test_v212_top20_report as report_fixture

SEC_URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json'


class Response:
    def __init__(self, status=200, body=b'{"public":1}', *, url=SEC_URL, content_type='application/json'):
        self.status_code = status
        self.body = body
        self.url = url
        self.history = []
        self.headers = {'Content-Type': content_type}
        self.closed = False

    def json(self):
        return json.loads(self.body)

    def iter_content(self, chunk_size):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i + chunk_size]

    def close(self):
        self.closed = True


def headers():
    with patch.dict(os.environ, {'SEC_CONTACT_EMAIL': 'synthetic@example.invalid', 'SEC_USER_AGENT': ''}):
        # A synthetic header set, never used for a real HTTP request.
        return {'User-Agent': 'Investor Intelligence/2.1 synthetic@example.invalid',
                'From': 'synthetic@example.invalid', 'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate'}


class PublicJsonRefreshTests(unittest.TestCase):
    def _actual_cli(self, status):
        helper = report_fixture.V212Top20ReportTests()
        wire = helper.wire_document([helper.fact(), helper.fact(tag='NetIncomeLoss', value=20)])
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp); cache = root / 'cache'; (cache / 'companyfacts').mkdir(parents=True)
            legacy = cache / 'companyfacts/CIK0000000001.json'
            old_bytes = builder.json_bytes(wire); legacy.write_bytes(old_bytes); os.utime(legacy, (1, 1))
            top = root / 'top20.json'; top.write_text('[]', encoding='utf-8')
            output = root / 'report.json'; original = builder.build
            session = engine.session()
            fresh = helper.wire_document([helper.fact(), helper.fact(tag='NetIncomeLoss', value=30)])
            get = stack.enter_context(patch.object(session, 'get', return_value=Response(status, builder.json_bytes(fresh))))
            stack.enter_context(patch.object(builder, 'build', side_effect=lambda **kw: original(top20_path=top, **kw)))
            stack.enter_context(patch.object(engine, 'CACHE_ROOT', cache))
            stack.enter_context(patch.object(engine, 'session', return_value=session))
            stack.enter_context(patch.object(engine, 'sec_headers', side_effect=headers))
            stack.enter_context(patch.object(engine, 'validate_policy', return_value=({'sec_companyfacts_url': SEC_URL.replace('0000000001', '{cik}'), 'sec_minimum_interval_seconds': 0}, {})))
            rows = [{'ticker': f'T{i:02}', 'rank': i + 1} for i in range(20)]
            stack.enter_context(patch.object(builder.snapshot, 'validate_top20', return_value=rows))
            stack.enter_context(patch.object(engine, 'sec_reference', return_value={r['ticker']: {'cik': '0000000001'} for r in rows}))
            stack.enter_context(patch.object(builder, '_market_observation', return_value=(None, None, '工業設備')))
            stack.enter_context(patch.object(sys, 'argv', ['build', '--output', str(output)]))
            with redirect_stdout(StringIO()):
                self.assertEqual(builder.main(), 0)
            doc = json.loads(output.read_bytes())
            basis = json.loads(output.with_name('report.financial-evidence-candidate.json').read_bytes())
            products = json.loads(output.with_name('report.financial-products-candidate.json').read_bytes())
            if status == 403:
                self.assertEqual(doc['records'][0]['profit_summary'], 'SEC 可用獲利指標不足')
                self.assertEqual(basis['records']['T00']['status'], 'SOURCE_FETCH_OR_VALIDATION_FAILED')
                self.assertTrue(all(p['status'] == 'UNAVAILABLE' for p in products['records'][0]['products'].values()))
            else:
                self.assertEqual(doc['records'][0]['profit_summary'], '獲利；淨利率 30.0%')
                self.assertEqual(basis['records']['T00']['metrics']['net_margin']['value'], 0.3)
                self.assertIn('30.0000%', products['records'][0]['products']['data_report']['content_utf8'])
                self.assertFalse(basis['records']['T00']['source_refresh_verified'])
            self.assertEqual(legacy.read_bytes(), old_bytes)
            self.assertEqual(get.call_count, 1, '403 fences requests; 200 reuses only the new bound cache')
            session.close()

    def test_actual_cli_http403_cannot_turn_expired_cache_into_current_profit(self):
        self._actual_cli(403)

    def test_actual_cli_200_uses_new_body_not_old_profit_and_keeps_unqualified_scope(self):
        self._actual_cli(200)

    def valid_body(self, amount=20):
        helper = report_fixture.V212Top20ReportTests()
        return builder.json_bytes(helper.wire_document([helper.fact(), helper.fact(tag='NetIncomeLoss', value=amount)]))

    def fetch(self, session, path, **changes):
        args = dict(headers=headers(), cache_path=path, cache_hours=24, minimum_delay=0)
        args.update(changes)
        return engine.get_json(session, SEC_URL, **args)

    def test_public_session_has_no_ambient_auth_proxy_cookie_or_retry(self):
        with engine.session() as session:
            self.assertFalse(session.trust_env)
            self.assertIs(session.verify, True)
            self.assertIsNone(session.auth)
            self.assertEqual(session.headers, {})
            self.assertEqual(session.proxies, {})
            self.assertEqual(session.get_adapter(SEC_URL).max_retries.total, 0)
            self.assertFalse(session.cookies.get_policy().set_ok(None, None))
            self.assertFalse(session.cookies.get_policy().return_ok(None, None))

    def test_exact_utf8_body_hash_and_original_receipt_time_survive_cache_reuse(self):
        with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
            path = Path(tmp) / 'raw.json'; raw = self.valid_body() + b' \n'
            response = Response(body=raw)
            with patch.object(session, 'get', return_value=response) as get:
                self.assertEqual(self.fetch(session, path), json.loads(raw))
                cached = engine.public_json_cache_path(path); original = cached.read_bytes()
                self.assertEqual(self.fetch(session, path), json.loads(raw)); self.assertEqual(get.call_count, 1)
                self.assertFalse(get.call_args.kwargs['allow_redirects']); self.assertTrue(get.call_args.kwargs['stream'])
            saved = json.loads(original)
            self.assertEqual(saved['last_success']['body_utf8'].encode(), raw)
            self.assertEqual(saved['last_success']['body_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(cached.read_bytes(), original)
            self.assertNotIn('synthetic@example.invalid', original.decode())
            self.assertFalse(path.exists())
            self.assertTrue(response.closed)

    def test_failed_or_pending_attempt_does_not_reuse_retained_success(self):
        with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
            path = Path(tmp) / 'raw.json'; bound = engine.public_json_cache_path(path)
            with patch.object(session, 'get', return_value=Response(body=self.valid_body())):
                self.fetch(session, path)
            original = json.loads(bound.read_bytes())['last_success']
            with patch.object(session, 'get', return_value=Response(503)) as get:
                with self.assertRaisesRegex(engine.PipelineError, 'PUBLIC_JSON_HTTP_503'):
                    self.fetch(session, path, cache_hours=0)
                self.assertEqual(get.call_count, 1)
            failed = json.loads(bound.read_bytes())
            self.assertEqual(failed['attempt']['status'], 'FAILED'); self.assertEqual(failed['last_success'], original)
            for state in ('FAILED', 'PENDING'):
                doc = copy.deepcopy(failed); doc['attempt']['status'] = state
                if state == 'PENDING': doc['attempt']['failure_code'] = None
                bound.write_bytes(builder.json_bytes(doc))
                with patch.object(session, 'get', return_value=Response(body=self.valid_body(30))) as get:
                    value = self.fetch(session, path); self.assertEqual(get.call_count, 1)
                self.assertEqual(value, json.loads(self.valid_body(30)))

    def test_denial_fences_sec_family_including_a_different_endpoint_but_not_world_bank(self):
        for status in (403, 429):
            with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
                root = Path(tmp)
                with patch.object(session, 'get', return_value=Response(status)) as get:
                    with self.assertRaisesRegex(engine.PipelineError, f'PUBLIC_JSON_HTTP_{status}'):
                        self.fetch(session, root / 'facts.json')
                    with self.assertRaisesRegex(engine.PipelineError, 'PUBLIC_JSON_SOURCE_BLOCKED'):
                        engine.get_json(session, engine.SEC_REFERENCE_URL, headers=headers(), cache_path=root / 'ref.json', cache_hours=24)
                    self.assertEqual(get.call_count, 1)
                body = b'[{"page":1},[]]'
                with patch.object(session, 'get', return_value=Response(body=body, url=engine.WORLD_BANK_JSON_URL)):
                    value = engine.get_json(session, engine.WORLD_BANK_JSON_URL, headers={'User-Agent':'SyntheticPublicTest/1.0'}, cache_path=root/'macro.json', cache_hours=24)
                    self.assertEqual(value, json.loads(body))

    def test_all_non200_statuses_and_redirects_fail_without_body_fallback(self):
        for response in [*(Response(s) for s in (204, 301, 302, 401, 404, 500)),
                         Response(body=self.valid_body(), url='https://example.invalid/redirect')]:
            with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
                path = Path(tmp) / 'raw.json'
                with patch.object(session, 'get', return_value=response) as get:
                    with self.assertRaises(engine.PipelineError): self.fetch(session, path)
                    self.assertEqual(get.call_count, 1)
                self.assertIsNone(json.loads(engine.public_json_cache_path(path).read_bytes())['last_success'])
                self.assertTrue(response.closed)

    def test_duplicate_nonfinite_wrong_shape_encoding_type_and_size_fail_closed(self):
        valid = self.valid_body()
        cases = [Response(body=b''), Response(body=b'\xff'), Response(body=b'{"cik":1,"cik":1}'),
                 Response(body=b'{"x":NaN}'), Response(body=b'{"x":1e999}'),
                 Response(body=b'{"x":1,"\\u0078":2}'), Response(body=b'null'),
                 Response(body=valid, content_type='text/html'),
                 Response(body=valid.replace(b'"cik": 1', b'"cik": 2', 1))]
        for response in cases:
            with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
                path = Path(tmp) / 'raw.json'
                with patch.object(session, 'get', return_value=response):
                    with self.assertRaises(engine.PipelineError): self.fetch(session, path)
                self.assertIsNone(json.loads(engine.public_json_cache_path(path).read_bytes())['last_success'])
        with tempfile.TemporaryDirectory() as tmp, engine.session() as session, patch.object(engine, 'PUBLIC_JSON_MAX_BYTES', 64):
            with patch.object(session, 'get', return_value=Response(body=valid)):
                with self.assertRaisesRegex(engine.PipelineError, 'PUBLIC_JSON_TOO_LARGE'):
                    self.fetch(session, Path(tmp) / 'large.json')

    def test_url_headers_and_unsafe_session_rejected_before_network_or_cache_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
            root = Path(tmp)
            with patch.object(session, 'get') as get:
                for url in ['http://data.sec.gov/x', SEC_URL+'?token=SYNTHETIC_PRIVATE_MARKER',
                            'https://name:password@data.sec.gov/x', 'https://example.invalid/?sec.gov',
                            'https://data.sec.gov/api/xbrl/companyfacts/CIK0000000000.json']:
                    with self.assertRaises(engine.PipelineError) as error:
                        engine.get_json(session, url, headers=headers(), cache_path=root/'raw.json', cache_hours=24)
                    self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', str(error.exception))
                for bad in [{**headers(), 'Cookie':'SYNTHETIC_PRIVATE_MARKER'}, {**headers(), 'Authorization':'SYNTHETIC_PRIVATE_MARKER'},
                            {**headers(), 'From':'bad'}, {**headers(), 'User-Agent':'a\r\nb'}]:
                    with self.assertRaises(engine.PipelineError): self.fetch(session, root/'raw.json', headers=bad)
                for field, value in [('verify',False), ('trust_env',True), ('auth',('synthetic','not-used'))]:
                    with patch.object(session, field, value), self.assertRaisesRegex(engine.PipelineError, 'PUBLIC_JSON_SESSION_UNSAFE'):
                        self.fetch(session, root/'raw.json')
                get.assert_not_called(); self.assertEqual(list(root.iterdir()), [])

    def test_cache_url_hash_future_stamp_and_corruption_do_not_get_repaired_from_mtime(self):
        with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
            path = Path(tmp) / 'raw.json'; bound = engine.public_json_cache_path(path)
            with patch.object(session, 'get', return_value=Response(body=self.valid_body())): self.fetch(session, path)
            valid = json.loads(bound.read_bytes())
            future = (datetime.now(timezone.utc)+timedelta(days=1)).replace(microsecond=0).isoformat().replace('+00:00','Z')
            mutations = [lambda d:d.update(url=engine.SEC_REFERENCE_URL),
                         lambda d:d['last_success'].update(body_sha256='0'*64),
                         lambda d:d['attempt'].update(at=future), lambda d:d.update(schema_version=True),
                         lambda d:d['last_success'].update(body_utf8='SYNTHETIC_PRIVATE_MARKER')]
            with patch.object(session, 'get') as get:
                for change in mutations:
                    doc=copy.deepcopy(valid);change(doc);raw=builder.json_bytes(doc);bound.write_bytes(raw)
                    with self.assertRaisesRegex(engine.PipelineError, 'PUBLIC_JSON_CACHE_INVALID'): self.fetch(session,path)
                    self.assertEqual(bound.read_bytes(),raw)
                bound.write_bytes(b'{"schema_version":1,"schema_version":1}')
                with self.assertRaises(engine.PipelineError): self.fetch(session,path)
                get.assert_not_called()

    def test_expired_receipt_requires_new_http_even_if_file_mtime_is_future(self):
        with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
            path=Path(tmp)/'raw.json';bound=engine.public_json_cache_path(path)
            with patch.object(session,'get',return_value=Response(body=self.valid_body())):self.fetch(session,path)
            doc=json.loads(bound.read_bytes());doc['attempt']['at']=doc['last_success']['retrieved_at']='2000-01-01T00:00:00Z'
            bound.write_bytes(builder.json_bytes(doc));os.utime(bound,(4102444800,4102444800))
            with patch.object(session,'get',return_value=Response(503)) as get:
                with self.assertRaisesRegex(engine.PipelineError,'PUBLIC_JSON_HTTP_503'):self.fetch(session,path)
                self.assertEqual(get.call_count,1)

    def test_response_echo_and_exception_text_cannot_persist_contact(self):
        reflected=json.loads(self.valid_body());reflected['entityName']='synthetic@example.invalid'
        for failure in (Response(body=builder.json_bytes(reflected)), engine.PipelineError('PUBLIC_JSON_SYNTHETIC_PRIVATE_MARKER'),
                        ValueError('SYNTHETIC_PRIVATE_MARKER')):
            with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
                path=Path(tmp)/'raw.json'
                kwargs={'side_effect':failure} if isinstance(failure,Exception) else {'return_value':failure}
                with patch.object(session,'get',**kwargs):
                    with self.assertRaises(engine.PipelineError) as error:self.fetch(session,path)
                self.assertNotIn('SYNTHETIC_PRIVATE_MARKER',str(error.exception))
                self.assertNotIn('synthetic@example.invalid',engine.public_json_cache_path(path).read_text())
                self.assertNotIn('SYNTHETIC_PRIVATE_MARKER',engine.public_json_cache_path(path).read_text())

    def test_invalid_timing_policy_and_initial_cache_failure_do_not_start_http(self):
        with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
            path=Path(tmp)/'raw.json'
            with patch.object(session,'get') as get:
                for option in ({'cache_hours':True},{'cache_hours':-1},{'cache_hours':169},
                               {'minimum_delay':True},{'minimum_delay':-1},{'minimum_delay':float('nan')},
                               {'minimum_delay':float('inf')}):
                    with self.assertRaisesRegex(engine.PipelineError,'PUBLIC_JSON_POLICY_INVALID'):
                        self.fetch(session,path,**option)
                with patch.object(engine,'atomic_json',side_effect=OSError('SYNTHETIC_PRIVATE_MARKER')):
                    with self.assertRaisesRegex(engine.PipelineError,'PUBLIC_JSON_CACHE_WRITE_FAILED'):
                        self.fetch(session,path)
                get.assert_not_called()
                self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_secondary_cache_failure_never_masks_primary_http_denial(self):
        with tempfile.TemporaryDirectory() as tmp, engine.session() as session:
            path=Path(tmp)/'raw.json';save=engine._save_source_cache
            def failing_save(p,value):
                if value['attempt']['status']=='FAILED':raise engine.PipelineError('PUBLIC_JSON_CACHE_WRITE_FAILED')
                save(p,value)
            with patch.object(engine,'_save_source_cache',side_effect=failing_save), patch.object(session,'get',return_value=Response(403)):
                with self.assertRaisesRegex(engine.PipelineError,'PUBLIC_JSON_HTTP_403'):self.fetch(session,path)
            self.assertEqual(json.loads(engine.public_json_cache_path(path).read_bytes())['attempt']['status'],'PENDING')
            with self.assertRaisesRegex(engine.PipelineError,'PUBLIC_JSON_SOURCE_BLOCKED'):self.fetch(session,path)


if __name__ == '__main__':
    unittest.main()
