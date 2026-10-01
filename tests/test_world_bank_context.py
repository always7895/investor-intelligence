"""Existing engine/federation callers; public synthetic transport, no live delivery."""
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
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v21_serenity_top20 as engine
import v213_source_federation as federation
import v213_v21_progress_runner as progress_runner
import test_public_json_refresh as transport
from adapters.world_bank import AdapterError, select_us_real_gdp_window


def fixture():
    return [{'page': 1, 'pages': 14, 'per_page': 5, 'total': 66, 'sourceid': '2', 'lastupdated': '2026-07-13'}, [
        {'indicator': {'id': 'NY.GDP.MKTP.KD.ZG', 'value': 'GDP growth (annual %)'},
         'country': {'id': 'US', 'value': 'United States'}, 'countryiso3code': 'USA',
         'date': str(year), 'value': number, 'unit': '', 'obs_status': '', 'decimal': 1}
        for year, number in [(2025, 2.1), (2024, 2.8), (2023, 2.9), (2022, 2.5), (2021, 6.1)]]]


def actual_engine_cli(root, document, *, status=200, progress=False):
    """Run non-synthetic engine CLI with source/market doubles and isolated outputs."""
    root = Path(root); original_report = engine.build_report
    candidates = engine.synthetic_candidates()[:20]
    with ExitStack() as stack:
        stack.enter_context(patch.multiple(engine, TOP20_PATH=root/'top20.json', PLAN_PATH=root/'plan.json',
            METADATA_PATH=root/'metadata.json', REPORT_PATH=root/'report.md', CACHE_ROOT=root/'cache',
            PUBLIC_ROOT=root, REPORT_ROOT=root))
        http = stack.enter_context(engine.session())
        get = stack.enter_context(patch.object(http, 'get', return_value=transport.Response(
            status=status, body=json.dumps(document, allow_nan=False).encode(), url=engine.WORLD_BANK_JSON_URL)))
        stack.enter_context(patch.object(engine, 'session', return_value=http))
        stack.enter_context(patch.object(engine, 'sec_headers', return_value={'User-Agent': 'SYNTHETIC_NOT_SENT'}))
        stack.enter_context(patch.object(engine, 'discover_candidates', return_value=[]))
        stack.enter_context(patch.object(engine, 'sec_reference', return_value={}))
        stack.enter_context(patch.object(engine, 'validate_candidates', return_value=[v[0] for v in candidates]))
        stack.enter_context(patch.object(engine, 'sec_companyfacts', return_value=[]))
        stack.enter_context(patch.object(engine, 'metrics', side_effect=[(v[1], v[2]) for v in candidates]))
        rendered = stack.enter_context(patch.object(engine, 'build_report', wraps=original_report))
        stack.enter_context(patch.object(sys, 'argv', ['engine']))
        output = StringIO()
        with redirect_stdout(output): result = progress_runner.main() if progress else engine.main()
        if result != 0: raise AssertionError('SYNTHETIC_ENGINE_CLI_FAILED')
        text = output.getvalue(); result_json = json.loads(text[text.index('{\n'):])
        return rendered.call_args.args[2], get.call_count, result_json


def actual_federation_cli(root, document):
    root = Path(root)
    rows = [{'rank': i + 1, 'ticker': f'T{i:02}', 'name': f'SYNTHETIC T{i:02}',
             'evidence': [{'source_id': 'sec_edgar', 'tier': 'T0', 'claim_type': 'xbrl_fact',
                           'title': 'SYNTHETIC_FILING', 'url': 'https://data.sec.gov/', 'as_of': '2026-07-13'}]} for i in range(20)]
    top = root/'top.json'; report = root/'five.json'; output = root/'federation.json'
    top.write_text(json.dumps(rows)); report.write_text(json.dumps({'product_version': '2.1.2', 'records': rows}))
    listings = {row['ticker']: SimpleNamespace(security_name=row['name'], exchange='NASDAQ', source_url=federation.NASDAQ_LISTED_URL) for row in rows}
    response = transport.Response(body=json.dumps(document, allow_nan=False).encode(), url=engine.WORLD_BANK_JSON_URL)
    response.content = response.body; response.raise_for_status = lambda: None
    def request(session, method, url, **kwargs):
        if method != 'GET' or url != engine.WORLD_BANK_JSON_URL:
            raise AssertionError('UNEXPECTED_FEDERATION_TRANSPORT')
        return response
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {'ALPHA_VANTAGE_API_KEY': '', 'SEC_CONTACT_EMAIL': ''}))
        stack.enter_context(patch.object(federation, 'CACHE_ROOT', root/'cache'))
        calls = stack.enter_context(patch.object(federation.requests.Session, 'request', autospec=True, side_effect=request))
        stack.enter_context(patch.object(federation, 'fetch_nasdaq', return_value=(listings,
            federation.observation('nasdaq_symbol_directory', 'nasdaq', 'T2', 'SYNTHETIC', 'identity', 'HEALTHY', federation.NASDAQ_LISTED_URL))))
        stack.enter_context(patch.object(federation, 'fetch_bls', return_value=federation.observation('bls_public_data', 'us_bls', 'T1', 'SYNTHETIC', 'macro', 'HEALTHY', federation.BLS_URL)))
        stack.enter_context(patch.object(federation, 'fetch_ecb', return_value=federation.observation('ecb_sdmx', 'ecb', 'T1', 'SYNTHETIC', 'macro', 'HEALTHY', federation.ECB_URL)))
        stack.enter_context(patch.object(federation, 'fetch_gleif', return_value=None))
        stack.enter_context(patch.object(sys, 'argv', ['federation', '--top20', str(top), '--v212', str(report), '--output', str(output)]))
        with redirect_stdout(StringIO()): code = federation.main()
        doc = json.loads(output.read_bytes())
        return next(s for s in doc['global_sources'] if s['source_id'] == 'world_bank_indicators'), code, calls.call_count, doc


class WorldBankContextTests(unittest.TestCase):
    def test_actual_engine_cli_refuses_other_country_or_indicator(self):
        for field in ('country', 'indicator'):
            doc = fixture()
            if field == 'country':
                doc[1][0]['country'] = {'id': 'JP', 'value': 'Japan'}; doc[1][0]['countryiso3code'] = 'JPN'
            else: doc[1][0]['indicator']['id'] = 'NY.GDP.MKTP.CD'
            with self.subTest(field=field), tempfile.TemporaryDirectory() as root:
                macro, calls, result = actual_engine_cli(root, doc)
                self.assertEqual(macro['status'], 'DEGRADED', 'ACTUAL_ENGINE_ACCEPTS_WRONG_GDP_IDENTITY')
                self.assertEqual(result['macro_status'], 'DEGRADED'); self.assertEqual(calls, 1)
                self.assertNotIn('World Bank macro context：HEALTHY', (Path(root)/'report.md').read_text(encoding='utf-8'))

    def test_actual_engine_cli_uses_latest_year_not_first_row(self):
        doc = fixture(); doc[1].reverse()
        with tempfile.TemporaryDirectory() as root:
            macro, calls, _ = actual_engine_cli(root, doc)
        self.assertEqual(macro['period'], '2025', 'ACTUAL_ENGINE_USES_ARRAY_ORDER_AS_LATEST')
        self.assertEqual(macro['value'], 2.1); self.assertEqual(calls, 1)

    def test_actual_federation_cli_refuses_wrong_identity_before_counting_family(self):
        doc = fixture(); doc[1][-1]['countryiso3code'] = 'JPN'
        with tempfile.TemporaryDirectory() as root:
            source, code, calls, result = actual_federation_cli(root, doc)
        self.assertEqual(source['status'], 'DEGRADED', 'FEDERATION_COUNTS_UNVALIDATED_WORLD_BANK_FAMILY')
        self.assertIn('world_bank', result['gates']['missing_required_families'])
        self.assertEqual(code, 1); self.assertEqual(calls, 1)

    def test_actual_serenity_progress_cli_preserves_macro_guard_without_changing_score_hooks(self):
        before = (engine.metrics, engine.score_candidate, engine.validate_policy, engine.sec_companyfacts)
        for valid in (True, False):
            doc = fixture()
            if not valid: doc[1][-1]['indicator']['id'] = 'NY.GDP.MKTP.CD'
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as root:
                macro, calls, result = actual_engine_cli(root, doc, progress=True)
                self.assertEqual(macro['status'], 'HEALTHY' if valid else 'DEGRADED')
                self.assertEqual(result['macro_status'], macro['status']); self.assertEqual(calls, 1)
                rows = json.loads((Path(root)/'top20.json').read_bytes())
                self.assertTrue(all(r['scoring_version'] == progress_runner.PRESELECTION_VERSION for r in rows))
        self.assertEqual(before, (engine.metrics, engine.score_candidate, engine.validate_policy, engine.sec_companyfacts))

    def test_engine_receipt_original_clock_and_raw_hash_survive_new_assembly(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        stamp = lambda n: (now - timedelta(minutes=n)).isoformat().replace('+00:00', 'Z')
        with tempfile.TemporaryDirectory() as root:
            with patch.object(engine, 'iso_now', return_value=stamp(10)):
                first, calls, _ = actual_engine_cli(root, fixture())
            cache = engine.public_json_cache_path(Path(root)/'cache/world_bank_gdp_growth.json'); original = cache.read_bytes()
            changed = fixture(); changed[1][0]['value'] = 99
            with patch.object(engine, 'iso_now', return_value=stamp(5)):
                second, cached_calls, _ = actual_engine_cli(root, changed)
            self.assertEqual(calls, 1); self.assertEqual(cached_calls, 0); self.assertEqual(cache.read_bytes(), original)
            self.assertEqual(json.loads((Path(root)/'metadata.json').read_bytes())['last_successful_pipeline_timestamp'], stamp(5))
        self.assertEqual(first['source_acquisition']['retrieved_at'], stamp(10))
        self.assertEqual(second['source_acquisition']['retrieved_at'], stamp(10))
        self.assertEqual(second['source_acquisition']['retrieval_mode'], 'BOUND_CACHE')
        self.assertEqual(second['value'], 2.1)
        self.assertEqual(first['source_acquisition']['body_sha256'], hashlib.sha256(json.dumps(fixture()).encode()).hexdigest())
        self.assertEqual(second['dataset_last_updated'], '2026-07-13'); self.assertFalse(second['publication_eligible'])
        self.assertFalse(second['window']['latest_release_verified']); self.assertFalse(second['window']['full_history_verified'])

    def test_expired_cache_http_denial_never_reuses_old_context_or_success(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        with tempfile.TemporaryDirectory() as root:
            with patch.object(engine, 'iso_now', return_value=old): actual_engine_cli(root, fixture())
            cache = engine.public_json_cache_path(Path(root)/'cache/world_bank_gdp_growth.json')
            original = json.loads(cache.read_bytes())['last_success']
            value, calls, _ = actual_engine_cli(root, fixture(), status=403)
            self.assertEqual(value['status'], 'DEGRADED'); self.assertNotIn('value', value); self.assertEqual(calls, 1)
            saved = json.loads(cache.read_bytes()); self.assertEqual(saved['attempt']['status'], 'FAILED')
            self.assertEqual(saved['last_success'], original)

    def test_cache_with_recomputed_digest_but_wrong_country_is_not_repaired_or_fetched(self):
        with tempfile.TemporaryDirectory() as root:
            actual_engine_cli(root, fixture()); cache = engine.public_json_cache_path(Path(root)/'cache/world_bank_gdp_growth.json')
            saved = json.loads(cache.read_bytes()); wrong = fixture(); wrong[1][-1]['countryiso3code'] = 'JPN'
            raw = json.dumps(wrong); saved['last_success'].update(body_utf8=raw, body_sha256=hashlib.sha256(raw.encode()).hexdigest())
            cache.write_text(json.dumps(saved)); before = cache.read_bytes()
            value, calls, _ = actual_engine_cli(root, fixture())
            self.assertEqual(value['status'], 'DEGRADED'); self.assertEqual(calls, 0); self.assertEqual(cache.read_bytes(), before)

    def test_actual_cli_corrupt_cache_huge_integer_refuses_without_arithmetic_exception(self):
        with tempfile.TemporaryDirectory() as root:
            actual_engine_cli(root, fixture()); cache = engine.public_json_cache_path(Path(root)/'cache/world_bank_gdp_growth.json')
            saved = json.loads(cache.read_bytes()); wrong = fixture(); wrong[1][0]['value'] = 10**400
            raw = json.dumps(wrong); saved['last_success'].update(body_utf8=raw, body_sha256=hashlib.sha256(raw.encode()).hexdigest())
            cache.write_text(json.dumps(saved)); before = cache.read_bytes()
            value, calls, _ = actual_engine_cli(root, fixture())
            self.assertEqual(value['status'], 'DEGRADED'); self.assertEqual(calls, 0); self.assertEqual(cache.read_bytes(), before)
            self.assertEqual(value['failure_code'], 'PUBLIC_JSON_SOURCE_SHAPE_INVALID')

    def test_whole_window_refusal_preserves_failed_cache_state_and_closed_diagnostics(self):
        for change in ('extra', 'wrong_tail', 'duplicate_year', 'wrong_name'):
            doc = fixture()
            if change == 'extra': doc[1][-1]['owner'] = 'SYNTHETIC_PRIVATE_MARKER'
            if change == 'wrong_tail': doc[1][-1]['indicator']['id'] = 'NY.GDP.MKTP.CD'
            if change == 'duplicate_year': doc[1][-1]['date'] = doc[1][0]['date']
            if change == 'wrong_name': doc[1][-1]['country']['value'] = 'Japan'
            with self.subTest(change=change), tempfile.TemporaryDirectory() as root:
                value, _, _ = actual_engine_cli(root, doc)
                self.assertEqual(value['status'], 'DEGRADED'); self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(value))
                saved = json.loads(engine.public_json_cache_path(Path(root)/'cache/world_bank_gdp_growth.json').read_bytes())
                self.assertIsNone(saved['last_success']); self.assertEqual(saved['attempt']['status'], 'FAILED')

    def test_null_periods_remain_explicit_and_all_null_does_not_become_healthy(self):
        doc = fixture(); doc[1][0]['value'] = None
        with tempfile.TemporaryDirectory() as root:
            value, _, _ = actual_engine_cli(root, doc)
        self.assertEqual(value['period'], '2024'); self.assertEqual(value['window']['latest_returned_period'], '2025')
        self.assertEqual(value['observations'][0]['status'], 'UNAVAILABLE'); self.assertIsNone(value['observations'][0]['value'])
        for row in doc[1]: row['value'] = None
        with tempfile.TemporaryDirectory() as root:
            value, _, _ = actual_engine_cli(root, doc)
        self.assertEqual(value['status'], 'DEGRADED'); self.assertIsNone(value['value'])
        self.assertEqual(len(value['observations']), 5); self.assertIn('source_acquisition', value)

    def test_zero_and_negative_growth_are_observations_not_missing(self):
        for number in (0, -0.0, -2.1, -100, 2.16138195623856):
            doc = fixture(); doc[1][0]['value'] = number
            got = select_us_real_gdp_window(doc, as_of_day='2026-09-10')
            self.assertEqual(got['period'], '2025'); self.assertEqual(got['value'], number)
            self.assertEqual(got['unit'], 'annual_percent_growth_constant_local_currency')

    def test_invalid_numeric_types_unit_flags_and_extra_fields_cannot_rescue_older_year(self):
        changes = [{'value':v} for v in (True, '2.1', float('nan'), float('inf'), -101, 2**53)] + [
            {'unit':'USD'}, {'obs_status':'F'}, {'decimal':True}, {'decimal':16}, {'decimal':-1}, {'extra':'field'}]
        for change in changes:
            with self.subTest(fields=list(change)):
                doc = fixture(); doc[1][0].update(change)
                with self.assertRaisesRegex(AdapterError, 'WORLD_BANK_US_GDP_WINDOW_INVALID'):
                    select_us_real_gdp_window(doc, as_of_day='2026-09-10')

    def test_metadata_and_window_bounds_are_strict_not_coerced(self):
        changes = [{'page':v} for v in (True, '1', 2, 0)] + [{'per_page':50}, {'pages':13}, {'total':True},
            {'total':0}, {'sourceid':'3'}, {'lastupdated':'2026-09-11'}, {'lastupdated':'2026-02-30'}, {'lastupdated':None}, {'extra':1}]
        for change in changes:
            doc = fixture(); doc[0].update(change)
            with self.subTest(fields=list(change)), self.assertRaisesRegex(AdapterError, 'WORLD_BANK_US_GDP_WINDOW_INVALID'):
                select_us_real_gdp_window(doc, as_of_day='2026-09-10')
        for rows in (fixture()[1][:-1], [], fixture()[1]+[fixture()[1][0]]):
            with self.assertRaises(AdapterError): select_us_real_gdp_window([fixture()[0], rows], as_of_day='2026-09-10')

    def test_invalid_year_gaps_and_unfinished_full_year_are_rejected(self):
        for year in ('2025Q4', '02025', '1899', '2027', '2026', True, '2019'):
            doc = fixture(); doc[1][0]['date'] = year
            with self.subTest(year=year), self.assertRaises(AdapterError):
                select_us_real_gdp_window(doc, as_of_day='2026-09-10')
        doc = fixture()
        for row in doc[1]: row['date'] = str(int(row['date']) + 1)
        doc[1][0]['value'] = None
        got = select_us_real_gdp_window(doc, as_of_day='2026-09-10')
        self.assertEqual(got['window']['latest_returned_period'], '2026'); self.assertEqual(got['period'], '2025')
        older = fixture(); older[1][0]['date'] = '2020'  # Contiguous 2024..2020, not a gap.
        got = select_us_real_gdp_window(older, as_of_day='2026-09-10')
        self.assertEqual(got['period'], '2024'); self.assertFalse(got['window']['latest_release_verified'])

    def test_world_bank_denial_fences_same_session_without_second_request(self):
        with tempfile.TemporaryDirectory() as root, engine.session() as http:
            with patch.object(http, 'get', return_value=transport.Response(status=429, url=engine.WORLD_BANK_JSON_URL)) as calls:
                first = engine.world_bank_context({'world_bank_url':engine.WORLD_BANK_JSON_URL}, http, cache_path=Path(root)/'one.json')
                second = engine.world_bank_context({'world_bank_url':engine.WORLD_BANK_JSON_URL}, http, cache_path=Path(root)/'two.json')
            self.assertEqual(first['failure_code'], 'PUBLIC_JSON_HTTP_429')
            self.assertEqual(second['failure_code'], 'PUBLIC_JSON_SOURCE_BLOCKED'); self.assertEqual(calls.call_count, 1)

    def test_federation_uses_same_projection_attribution_and_original_cache_clock(self):
        with tempfile.TemporaryDirectory() as root:
            first, code, calls, _ = actual_federation_cli(root, fixture())
            self.assertEqual(code, 0); self.assertEqual(calls, 1)
            changed = fixture(); changed[1][0]['value'] = 99
            second, code, calls, _ = actual_federation_cli(root, changed)
            self.assertEqual(code, 0); self.assertEqual(calls, 0)
        context = second['detail']['context']; self.assertEqual(second['detail']['value'], 2.1)
        self.assertEqual(context['source_acquisition']['retrieved_at'], first['detail']['context']['source_acquisition']['retrieved_at'])
        self.assertTrue(second['detail']['cache_hit']); self.assertEqual(second['as_of'], '2025')
        self.assertIn('World Development Indicators', context['attribution']['text'])
        self.assertIn('OECD', context['attribution']['text']); self.assertIn('no endorsement', context['attribution']['notice'])
        self.assertTrue(context['attribution']['terms_url'].endswith('/datasets')); self.assertFalse(context['publication_eligible'])

    def test_federation_ignores_legacy_mtime_hex_cache_and_does_not_forward_other_session_state(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Path(root)/'cache'; cache.mkdir()
            key = json.dumps({'method':'GET','url':engine.WORLD_BANK_JSON_URL,'json':None,'params':None}, sort_keys=True, separators=(',', ':'))
            old_path = cache/(hashlib.sha256(key.encode()).hexdigest()+'.cache'); old = fixture(); old[1][0]['value'] = 99
            old_path.write_text(json.dumps({'url':engine.WORLD_BANK_JSON_URL,'body_hex':json.dumps(old).encode().hex(),'retrieved_at':'2001-01-01T00:00:00Z'})); before=old_path.read_bytes()
            source, code, calls, _ = actual_federation_cli(root, fixture())
            self.assertEqual(source['detail']['value'], 2.1); self.assertEqual(calls, 1); self.assertEqual(code, 0)
            self.assertEqual(old_path.read_bytes(), before)
        with tempfile.TemporaryDirectory() as root, patch.object(federation, 'CACHE_ROOT', Path(root)):
            def public_request(http, method, url, **kw):
                self.assertFalse(http.trust_env); self.assertEqual(http.headers, {}); self.assertIsNone(http.auth)
                self.assertEqual(http.proxies, {}); self.assertFalse(kw['allow_redirects'])
                self.assertNotIn('From', kw['headers']); self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(kw))
                return transport.Response(body=json.dumps(fixture()).encode(), url=url)
            with patch.object(federation.requests.Session, 'request', autospec=True, side_effect=public_request):
                source = federation.fetch_world_bank(SimpleNamespace(request=lambda *a, **k: self.fail('LEGACY_SESSION_MUST_NOT_BE_USED'), headers={'From':'SYNTHETIC_PRIVATE_MARKER'}))
            self.assertEqual(source['status'], 'HEALTHY')


if __name__ == '__main__':
    unittest.main()
