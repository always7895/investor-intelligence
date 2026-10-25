"""Synthetic O1 real-caller checks. No live response compatibility or rights claim."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import fetch_public_source_observations as collector
import import_option_observations as importer
import taifex_contract as contract
from adapters import ADAPTERS
from public_options_provider_gate import audit_public_options_providers
from tests.test_taifex_options_eod import fixture as eod_row
from tests.test_taifex_delta_reference import row as delta_row, payload

DELTA = 'taifex_options_delta'
EOD = 'taifex_options_eod'
NOW = datetime(2026, 10, 7, 1, 2, 3, tzinfo=timezone.utc)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def import_cli(raw, **limits):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'synthetic.json'
        path.write_bytes(raw)
        output = StringIO()
        with patch.object(sys, 'argv', ['importer', '--source', 'taifex_delta', '--input', str(path)]), \
             patch.object(importer, 'datetime', Clock), patch.multiple(importer, **{'TAIFEX_DELTA_MAX_OUTPUT_BYTES': importer.TAIFEX_DELTA_MAX_OUTPUT_BYTES, **limits}), redirect_stdout(output):
            code = importer.main()
        return code, json.loads(output.getvalue()), output.getvalue()


def collect_cli(sources, bodies, *, limit=None):
    """Inject only the transport/clock/budget; keep parser, builder and atomic writer real."""
    original = collector.collect
    calls = []
    def transport(url):
        calls.append(url)
        value = bodies[url]
        if isinstance(value, Exception):
            raise value
        return value
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'observation.json'
        args = ['collector', '--fetch', '--output', str(path)]
        for source in sources:
            args.extend(['--source', source])
        cap = collector.TAIFEX_DELTA_MAX_OUTPUT_BYTES if limit is None else limit
        with patch.object(sys, 'argv', args), patch.object(collector, 'datetime', Clock), \
             patch.object(collector, 'TAIFEX_DELTA_MAX_OUTPUT_BYTES', cap), \
             patch.object(collector, 'collect', side_effect=lambda chosen: original(chosen, transport=transport)), \
             redirect_stdout(StringIO()) as output:
            code = collector.main()
        raw = path.read_bytes()
        return code, json.loads(raw), raw, json.loads(output.getvalue()), calls


def bodies(delta=None):
    return {contract.TAIFEX_DELTA_URL: payload([delta_row()]) if delta is None else delta,
            contract.TAIFEX_DAILY_URL: json.dumps([eod_row(Date='20261006')], ensure_ascii=False).encode('utf-8')}


class DeltaCallerTests(unittest.TestCase):
    def test_importer_main_preserves_raw_reference_and_unverified_origin(self):
        raw = payload([delta_row(CallPut='買權', Delta='1.75')], bom=True)
        code, result, _ = import_cli(raw)
        self.assertEqual(code, 0)
        self.assertEqual(result['mode'], 'LOCAL_REFERENCE_IMPORT_ONLY')
        self.assertEqual(result['origin_verification'], 'UNVERIFIED_LOCAL_FILE')
        self.assertEqual(result['imported_at'], NOW.isoformat())
        self.assertEqual(result['input_binding'], {'sha256': hashlib.sha256(raw).hexdigest(),
                         'scope': 'EXACT_BYTES_READ_BY_THIS_IMPORT', 'authenticated_origin': False})
        self.assertEqual(result['rights_status'], 'NOT_REVIEWED_BY_IMPORTER')
        envelope = result['reference_envelope']
        for field in ('provider_asof', 'quote_asof', 'trading_session'):
            self.assertIsNone(envelope[field])
        self.assertEqual(envelope['reference_time_status'], 'UNALIGNED_NO_PROVIDER_ASOF')
        self.assertEqual(envelope['delta_unit_convention'], 'UNDOCUMENTED')
        self.assertEqual(envelope['identity_status'], 'EXPECTED_DATASET_UNVERIFIED_FOR_A_MANUAL_FILE')
        row = result['reference_rows'][0]
        self.assertEqual(row['delta_text'], '1.75')
        self.assertEqual(row['reported_contract_day'], '2026-10-15')
        self.assertEqual(row['origin_verification'], 'UNVERIFIED_LOCAL_FILE')
        self.assertEqual(row['reference_scope'], 'LOCAL_REFERENCE_ONLY')
        for key in ('publication_eligible', 'line_quote_eligible', 'executable_quote'):
            self.assertIs(row[key], False)
        for key in ('currency', 'multiplier', 'actual_dte', 'delta', 'quote_time', 'retrieved_at'):
            self.assertNotIn(key, row)

    def test_importer_single_binary_bounded_read_and_no_stat(self):
        raw = payload([delta_row()])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'synthetic.json'
            path.write_bytes(raw)
            opens, reads = [], []
            real_open, real_stat = Path.open, Path.stat
            class Handle:
                def __enter__(self):
                    self.inner = real_open(path, 'rb')
                    return self
                def __exit__(self, *args):
                    self.inner.close()
                def read(self, size=-1):
                    reads.append(size)
                    return self.inner.read(size)
            def opening(target, *args, **kwargs):
                if target == path:
                    opens.append((args, kwargs))
                    return Handle()
                return real_open(target, *args, **kwargs)
            def statting(target, *args, **kwargs):
                if target == path:
                    raise AssertionError('stat-then-read is forbidden')
                return real_stat(target, *args, **kwargs)
            with patch.object(sys, 'argv', ['importer', '--source', 'taifex_delta', '--input', str(path)]), \
                 patch.object(Path, 'open', opening), patch.object(Path, 'stat', statting), redirect_stdout(StringIO()):
                self.assertEqual(importer.main(), 0)
            self.assertEqual(opens, [(('rb',), {})])
            self.assertEqual(reads, [8_000_001])
        # Bounded synthetic cap; both the caller and the actual shared decoder agree.
        with patch.object(contract, 'TAIFEX_DELTA_MAX_BYTES', len(raw)):
            self.assertEqual(import_cli(raw, TAIFEX_DELTA_MAX_BYTES=len(raw))[0], 0)
            code, result, _ = import_cli(raw + b' ', TAIFEX_DELTA_MAX_BYTES=len(raw))
        self.assertEqual(code, 1)
        self.assertEqual(result, {'status': 'FAILED', 'error': 'INVALID_PROVIDER_EXPORT'})

    def test_importer_final_rendering_budget_includes_envelope_escaping_and_crlf(self):
        raw = payload([delta_row(CallPut='買權')])
        code, result, printed = import_cli(raw)
        self.assertEqual(code, 0)
        rendered = json.dumps(result, ensure_ascii=True, allow_nan=False)
        self.assertEqual(printed, rendered + '\n')
        cap = len(rendered) + 2
        self.assertGreater(cap, len(json.dumps(result['reference_rows'], ensure_ascii=False).encode('utf-8')))
        self.assertEqual(import_cli(raw, TAIFEX_DELTA_MAX_OUTPUT_BYTES=cap)[0], 0)
        code, refused, _ = import_cli(raw, TAIFEX_DELTA_MAX_OUTPUT_BYTES=cap - 1)
        self.assertEqual((code, refused), (1, {'status': 'FAILED', 'error': 'TAIFEX_DELTA_OUTPUT_TOO_LARGE'}))

    def test_collector_real_writer_keeps_reference_separate_from_eod(self):
        source_bodies = bodies()
        code, result, raw, summary, calls = collect_cli([EOD, DELTA, DELTA], source_bodies)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [contract.TAIFEX_DAILY_URL, contract.TAIFEX_DELTA_URL])
        self.assertEqual(raw, (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8'))
        self.assertEqual(collector._written_size(result), len(raw))
        self.assertEqual(summary['item_count'], 2)
        self.assertIs(result['publication_eligible'], False)
        eod, delta = result['items']
        self.assertEqual(eod['trade_date'], '2026-10-06')
        self.assertIsNone(eod['quote_time'])
        self.assertIsNone(eod['delta'])
        self.assertEqual(delta['origin_verification'], 'COLLECTOR_CAPTURE_UNQUALIFIED')
        self.assertEqual(delta['retrieved_at'], NOW.isoformat())
        self.assertEqual(delta['content_sha256'], hashlib.sha256(source_bodies[contract.TAIFEX_DELTA_URL]).hexdigest())
        self.assertEqual(delta['delta_text'], '0.1234')
        self.assertNotIn('actual_dte', delta)
        self.assertNotIn('quote_time', delta)
        for row in (eod, delta):
            for key in ('publication_eligible', 'line_quote_eligible', 'executable_quote'):
                self.assertIs(row[key], False)
        envelope = result['sources'][1]['reference_envelope']
        for key in ('provider_asof', 'quote_asof', 'trading_session'):
            self.assertIsNone(envelope[key])
        self.assertEqual(envelope['attribution']['dataset_url'], 'https://data.gov.tw/dataset/11321')

    def test_collector_final_cap_drops_all_delta_not_legacy_or_partial_reference(self):
        source_bodies = bodies(payload([delta_row(), delta_row(Contract='TX1')]))
        _, original, raw, _, _ = collect_cli([EOD, DELTA], source_bodies)
        self.assertEqual(collect_cli([EOD, DELTA], source_bodies, limit=len(raw))[0], 0)
        code, result, _, _, _ = collect_cli([EOD, DELTA], source_bodies, limit=len(raw) - 1)
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(result['items'], [original['items'][0]])
        self.assertEqual(result['sources'][0], original['sources'][0])
        self.assertEqual(result['sources'][1], {'source_id': DELTA, 'status': 'FAILED', 'record_count': 0,
                         'failure_kind': 'INVALID_PAYLOAD', 'failure_code': 'TAIFEX_DELTA_OUTPUT_TOO_LARGE'})
        # Legacy output may exceed the cap; it must not be truncated or relabelled.
        _, legacy, legacy_raw, _, _ = collect_cli([EOD], source_bodies)
        self.assertEqual(collect_cli([EOD], source_bodies, limit=1)[2], legacy_raw)
        code, remainder, remainder_raw, _, _ = collect_cli([EOD, DELTA], source_bodies, limit=1)
        self.assertEqual((code, remainder['items']), (1, legacy['items']))
        self.assertGreater(len(remainder_raw), 1)
        code, delta_only, _, _, _ = collect_cli([DELTA], source_bodies, limit=1)
        self.assertEqual((code, delta_only['status'], delta_only['items']), (1, 'FAILED', []))

    def test_invalid_batches_and_transport_errors_are_fixed_all_or_nothing(self):
        malformed = [b'[{"Contract":"TXO","Contract":"TX1"}]', payload([delta_row(), delta_row()]),
                     payload([delta_row(), delta_row(Contract='TX1', Delta='SYNTHETIC_BAD_DELTA')]),
                     payload([delta_row(receipt='SYNTHETIC_FORGED_ORIGIN')])]
        for bad in malformed:
            with self.subTest(case=hashlib.sha256(bad).hexdigest()[:8]):
                code, result, _ = import_cli(bad)
                self.assertEqual((code, result), (1, {'status': 'FAILED', 'error': 'INVALID_PROVIDER_EXPORT'}))
                code, result, _, _, _ = collect_cli([EOD, DELTA], bodies(bad))
                self.assertEqual((code, result['status'], len(result['items'])), (1, 'PARTIAL', 1))
                self.assertEqual(result['items'][0]['source_id'], EOD)
                health = result['sources'][1]
                self.assertEqual((health['status'], health['record_count']), ('FAILED', 0))
                self.assertNotIn('reference_envelope', health)
                self.assertNotIn('SYNTHETIC_', json.dumps(result))
        code, result, _, _, _ = collect_cli([DELTA], bodies(RuntimeError('SYNTHETIC_TRANSPORT_BODY')))
        self.assertEqual((code, result['status'], result['items']), (1, 'FAILED', []))
        self.assertNotIn('SYNTHETIC_TRANSPORT_BODY', json.dumps(result))

    def test_default_cli_and_runtime_catalog_never_enable_delta_or_eod(self):
        for source in (DELTA, EOD):
            self.assertNotIn(source, collector.DEFAULT_SOURCES)
            self.assertNotIn(source, ADAPTERS)
        with patch.object(sys, 'argv', ['collector', '--fetch', '--output', 'not-written.json']), \
             patch.object(collector, 'collect', return_value={'status': 'OK', 'sources': [], 'items': []}) as collect, \
             patch.object(collector, 'atomic_write_json') as write, redirect_stdout(StringIO()):
            self.assertEqual(collector.main(), 0)
        self.assertEqual(collect.call_args.args[0], list(collector.DEFAULT_SOURCES))
        self.assertNotIn(DELTA, collect.call_args.args[0])
        self.assertNotIn(EOD, collect.call_args.args[0])
        write.assert_called_once()
        findings, summary = audit_public_options_providers(ROOT)
        self.assertEqual(findings, [])
        for key in ('fully_eligible_count', 'runtime_enabled_count', 'line_quote_eligible_count'):
            self.assertEqual(summary[key], 0)
        self.assertIs(summary['production_provider_selected'], False)


if __name__ == '__main__':
    unittest.main()
