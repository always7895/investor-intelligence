"""Original JSON numeric spelling at real report/progress callers; synthetic transport."""
import hashlib
import json
import math
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Inexact, InvalidOperation, ROUND_DOWN, Rounded, localcontext
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_v212_top20_report as builder
import company_financial_products as products
import v21_serenity_top20 as engine
import test_public_json_refresh as transport
import test_report_source_acquisition as acquisition_fixture
import test_v212_top20_report as financial_fixture
import test_world_bank_context as wdi_fixture

LOSS = 'PUBLIC_JSON_NUMBER_PRECISION_LOSS'
LOSSY = (b'1e-400', b'-1e-400', b'0.100000000000000005', b'9007199254740991.01')


def body_with_literal(token):
    helper = financial_fixture.V212Top20ReportTests()
    facts = [helper.fact(), helper.fact(tag='NetIncomeLoss', value=20),
             helper.fact(tag='LongTermDebtCurrent', start=None, value=654321),
             helper.fact(tag='LongTermDebtNoncurrent', start=None, value=70),
             helper.fact(tag='LongTermDebt', start=None, value=70)]
    body = builder.json_bytes(helper.wire_document(facts))
    assert body.count(b'"val": 654321') == 1
    return body.replace(b'"val": 654321', b'"val": ' + token)


def old_envelope(body, age_hours=1):
    stamp = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    return {'schema_version': 1, 'url': transport.SEC_URL,
            'attempt': {'status': 'AVAILABLE', 'at': stamp, 'failure_code': None},
            'last_success': {'retrieved_at': stamp, 'body_sha256': hashlib.sha256(body).hexdigest(),
                             'body_utf8': body.decode('utf-8')}}


def actual_cli(root, token, *, progress=False, cached=False, history=False):
    """Keep output/cache files under caller-owned root; no live source or model."""
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    output = root/'report.json'; top = root/'top20.json'
    top.write_bytes(builder.json_bytes(acquisition_fixture.progress_fixture.provisional_rows()))
    body = body_with_literal(token)
    cache = root/'cache'; path = cache/'companyfacts/CIK0000000001.json'
    bound = engine.public_json_cache_path(path)
    before = None
    if cached or history:
        before = builder.json_bytes(old_envelope(body if cached else body_with_literal(b'0'), 1 if cached else 25))
        bound.parent.mkdir(parents=True); bound.write_bytes(before)
    original = builder.build
    with ExitStack() as stack:
        http = stack.enter_context(engine.session())
        response = transport.Response(body=body)
        get = stack.enter_context(patch.object(http, 'get', return_value=response))
        stack.enter_context(patch.object(engine, 'CACHE_ROOT', cache))
        stack.enter_context(patch.object(engine, 'session', return_value=http))
        stack.enter_context(patch.object(engine, 'sec_headers', side_effect=transport.headers))
        policy = {'sec_companyfacts_url': transport.SEC_URL.replace('0000000001', '{cik}'), 'sec_minimum_interval_seconds': 0}
        stack.enter_context(patch.object(engine, 'validate_policy', return_value=(policy, {})))
        stack.enter_context(patch.object(acquisition_fixture.progress_fixture.MODULE.preselection, 'validate_v213_policy', return_value=(policy, {})))
        stack.enter_context(patch.object(engine, 'sec_reference', return_value={'T00': {'cik': '0000000001'}}))
        stack.enter_context(patch.object(builder, 'build', side_effect=lambda **kw: original(top20_path=top, **kw)))
        stack.enter_context(patch.object(builder.snapshot, 'validate_top20', side_effect=acquisition_fixture.progress_fixture.MODULE.validate_provisional_top20))
        stack.enter_context(patch.object(builder, '_market_observation', return_value=(None, None, '未分類')))
        stack.enter_context(patch.object(sys, 'argv', ['build', '--output', str(output)]))
        with redirect_stdout(StringIO()):
            code = acquisition_fixture.progress_fixture.MODULE.main() if progress else builder.main()
    if code != 0:
        raise AssertionError('SYNTHETIC_ACTUAL_REPORT_CLI_FAILED')
    report = output.read_bytes(); basis = (root/'report.financial-evidence-candidate.json').read_bytes()
    content = (root/'report.financial-products-candidate.json').read_bytes()
    products.verify_financial_products(content, report, basis)
    return {'report': json.loads(report), 'basis': json.loads(basis), 'products': json.loads(content),
            'cache_before': before, 'cache_after': bound.read_bytes(), 'http_calls': get.call_count,
            'response_closed': response.closed, 'source_body': body}


class PublicJsonNumericPrecisionTests(unittest.TestCase):
    def assert_unavailable(self, result):
        self.assertEqual(result['basis']['records']['T00'],
                         {'status': 'SOURCE_FETCH_OR_VALIDATION_FAILED', 'publication_eligible': False},
                         'ACTUAL_CLI_ADMITS_LOSSY_WIRE_NUMBER')
        row = result['report']['records'][0]
        self.assertIsNone(row['retrieved_at'])
        self.assertEqual(row['profit_summary'], 'SEC 可用獲利指標不足')
        for value in result['products']['records'][0]['products'].values():
            self.assertEqual(value['status'], 'UNAVAILABLE')
            self.assertIsNone(value['content_utf8']); self.assertEqual(value['pages'], [])
            self.assertFalse(value['publication_eligible']); self.assertIsNone(value['snapshot_run_id'])

    def test_actual_report_and_progress_cli_refuse_lossy_http_numbers_before_financial_math(self):
        for progress in (False, True):
            for token in LOSSY:
                with self.subTest(progress=progress, literal=token), tempfile.TemporaryDirectory() as tmp:
                    result = actual_cli(tmp, token, progress=progress)
                    self.assert_unavailable(result)
                    self.assertEqual(result['http_calls'], 1); self.assertTrue(result['response_closed'])
                    cache = json.loads(result['cache_after'])
                    self.assertEqual(cache['attempt']['status'], 'FAILED')
                    self.assertEqual(cache['attempt']['failure_code'], LOSS)
                    self.assertIsNone(cache['last_success'])

    def test_lossy_new_body_keeps_previous_receipt_only_as_history_not_profit_rescue(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = actual_cli(tmp, b'1e-400', progress=True, history=True)
        self.assert_unavailable(result); self.assertEqual(result['http_calls'], 1)
        before, after = (json.loads(result[k]) for k in ('cache_before', 'cache_after'))
        self.assertEqual(after['last_success'], before['last_success'])
        self.assertEqual(after['attempt']['status'], 'FAILED'); self.assertEqual(after['attempt']['failure_code'], LOSS)

    def test_old_hash_valid_lossy_cache_is_refused_without_mutation_or_new_request(self):
        for token in LOSSY:
            with self.subTest(literal=token), tempfile.TemporaryDirectory() as tmp:
                result = actual_cli(tmp, token, progress=True, cached=True)
                self.assert_unavailable(result)
                self.assertEqual(result['http_calls'], 0)
                self.assertEqual(result['cache_before'], result['cache_after'])

    def test_http_and_cache_refusals_clear_receipt_sink_without_echoing_tokens(self):
        token = b'0.12345678901234567890123456789'
        with tempfile.TemporaryDirectory() as tmp, engine.session() as http:
            path = Path(tmp)/'body.json'; bound = engine.public_json_cache_path(path)
            sink = {'old': 'SYNTHETIC_NOT_A_RECEIPT'}
            with patch.object(http, 'get', return_value=transport.Response(body=body_with_literal(token))):
                with self.assertRaisesRegex(engine.PipelineError, '^' + LOSS + '$') as failure:
                    engine.get_json(http, transport.SEC_URL, headers=transport.headers(), cache_path=path, cache_hours=24, receipt_sink=sink)
            self.assertEqual(sink, {}); self.assertNotIn(token.decode(), str(failure.exception))
            bound.write_bytes(builder.json_bytes(old_envelope(body_with_literal(token))))
            before = bound.read_bytes(); sink['old'] = 'SYNTHETIC_NOT_A_RECEIPT'
            with patch.object(http, 'get') as get, self.assertRaisesRegex(engine.PipelineError, '^PUBLIC_JSON_CACHE_INVALID$'):
                engine.get_json(http, transport.SEC_URL, headers=transport.headers(), cache_path=path, cache_hours=24, receipt_sink=sink)
            get.assert_not_called(); self.assertEqual(sink, {}); self.assertEqual(bound.read_bytes(), before)

    def test_roundtrip_decimal_numbers_are_not_rejected_for_binary_float_representation(self):
        tokens = [b'0', b'-0.0', b'0.1', b'1e-1', b'0.1000', b'5e-324', b'-5e-324',
                  b'1e15', b'9007199254740991.0', b'2.16138195623856', b'0e9999', b'-0e-9999']
        for token in tokens:
            with self.subTest(literal=token):
                raw = b'{"number":' + token + b'}'
                got = engine._strict_public_json(raw)['number']; expected = json.loads(raw)['number']
                self.assertIs(type(got), type(expected)); self.assertEqual(got, expected)
                if type(got) is float and got == 0:
                    self.assertEqual(math.copysign(1, got), math.copysign(1, expected))
        # Exact arbitrary-size integers are not silently converted into floats;
        # downstream field-specific bounds still decide their admissibility.
        self.assertEqual(engine._strict_public_json(b'{"n":' + b'1' + b'0'*400 + b'}')['n'], 10**400)

    def test_actual_success_and_cache_replay_preserve_numeric_spelling_hash_and_time(self):
        for token, expected in ((b'0.1000', .1), (b'1e-1', .1), (b'0.0', 0), (b'5e-324', 5e-324)):
            for cached in (False, True):
                with self.subTest(literal=token, cached=cached), tempfile.TemporaryDirectory() as tmp:
                    result = actual_cli(tmp, token, progress=True, cached=cached)
                    company = result['basis']['records']['T00']; receipt = company['source_acquisition']
                    self.assertEqual(company['debt_bridge']['observations']['current_debt']['operand']['value'], expected)
                    self.assertEqual(result['http_calls'], 0 if cached else 1)
                    if cached:
                        self.assertEqual(result['cache_before'], result['cache_after'])
                    original = json.loads(result['cache_after'])['last_success']
                    self.assertEqual(original['body_utf8'].encode(), result['source_body'])
                    self.assertEqual(receipt['body_sha256'], hashlib.sha256(result['source_body']).hexdigest())
                    self.assertEqual(receipt['retrieved_at'], original['retrieved_at'])
                    self.assertEqual(receipt['retrieval_mode'], 'BOUND_CACHE' if cached else 'DIRECT_HTTP')
                    self.assertFalse(company['publication_eligible'])

    def test_numeric_tokens_are_bounded_without_logging_their_content(self):
        for token in (b'1'*1025, b'0.' + b'0'*1022 + b'1', b'0e' + b'9'*1023, b'1e999'):
            with self.subTest(length=len(token)):
                with self.assertRaisesRegex(engine.PipelineError, '^PUBLIC_JSON_PAYLOAD_INVALID$') as failure:
                    engine._strict_public_json(b'{"n":' + token + b'}')
                self.assertNotIn(token.decode(), str(failure.exception))
        self.assertEqual(engine._strict_public_json(b'{"n":' + b'1'*1024 + b'}')['n'], int('1'*1024))

    def test_parser_precision_check_is_independent_of_decimal_context_and_preserves_flags(self):
        for precision in (2, 28):
            with self.subTest(precision=precision), localcontext() as ctx:
                ctx.prec = precision; ctx.rounding = ROUND_DOWN; ctx.Emin = -2; ctx.Emax = 2
                for signal in (Inexact, InvalidOperation, Rounded): ctx.traps[signal] = False
                ctx.clear_flags()
                self.assertEqual(engine._strict_public_json(b'{"n":0.1000}')['n'], .1)
                for token in LOSSY:
                    with self.assertRaisesRegex(engine.PipelineError, '^' + LOSS + '$'):
                        engine._strict_public_json(b'{"n":' + token + b'}')
                with self.assertRaisesRegex(engine.PipelineError, '^PUBLIC_JSON_PAYLOAD_INVALID$'):
                    engine._strict_public_json(b'{"n":0e' + b'9'*100 + b'}')
                self.assertFalse(any(ctx.flags.values()))

    def test_actual_wdi_engine_and_federation_cli_refuse_underflow_not_admit_zero_growth(self):
        original_response = transport.Response
        class LiteralResponse(original_response):
            def __init__(self, status=200, body=b'', **kw):
                if b'"value": 2.1' not in body:
                    raise AssertionError('SYNTHETIC_WDI_LITERAL_TARGET_MISSING')
                super().__init__(status, body.replace(b'"value": 2.1', b'"value": 1e-400', 1), **kw)
        with patch.object(transport, 'Response', LiteralResponse):
            with tempfile.TemporaryDirectory() as tmp:
                macro, calls, result = wdi_fixture.actual_engine_cli(tmp, wdi_fixture.fixture(), progress=True)
                self.assertEqual(macro['status'], 'DEGRADED', 'ACTUAL_WDI_CLI_UNDERFLOW_ADMITTED_AS_ZERO')
                self.assertEqual(macro['failure_code'], LOSS); self.assertEqual(calls, 1)
                self.assertNotIn('value', macro); self.assertEqual(result['macro_status'], 'DEGRADED')
            with tempfile.TemporaryDirectory() as tmp:
                source, code, calls, result = wdi_fixture.actual_federation_cli(tmp, wdi_fixture.fixture())
                self.assertEqual(source['status'], 'DEGRADED')
                self.assertIn('world_bank', result['gates']['missing_required_families'])
                self.assertEqual(code, 1); self.assertEqual(calls, 1)


if __name__ == '__main__':
    unittest.main()
