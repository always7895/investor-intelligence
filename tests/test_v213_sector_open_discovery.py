"""Active discovery controls with synthetic provider IO; no real fetch/publication."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('sector_open_runner', ROOT / 'scripts/v213_v21_progress_runner.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
e = m.engine
BROAD = {'undervalued_growth_stocks', 'most_actives', 'day_gainers'}


class SectorOpenDiscoveryTests(unittest.TestCase):
    def policy(self):
        return e.load_object(e.POLICY_PATH)

    def test_active_policy_has_no_permanent_technology_screener(self):
        policy = self.policy()
        self.assertEqual({s['name'] for s in policy['candidate_screeners']}, BROAD)
        self.assertEqual(policy['factor_weights'], {'chokepoint': 15, 'demand_wave': 15, 'evidence_quality': 15,
                         'pricing_power': 15, 'replacement_friction': 10, 'tam_capture': 15, 'valuation_expectations': 15})

    def test_active_policy_validator_rejects_sector_reintroduction_and_malformed_specs(self):
        original = self.policy()
        for spec in ({'name': 'growth_technology_stocks', 'weight': 6}, {'name': 'unknown_screener', 'weight': 1},
                     {'name': 'most_actives', 'weight': True}, {'name': 'most_actives', 'weight': float('nan')},
                     {'name': 'most_actives', 'weight': 0}):
            changed = copy.deepcopy(original)
            changed['candidate_screeners'] = [spec]
            real_load = e.load_object
            with patch.object(e, 'load_object', side_effect=lambda path: changed if path == e.POLICY_PATH else real_load(path)):
                with self.assertRaisesRegex(e.PipelineError, 'V213_DISCOVERY_SCREENER_POLICY_INVALID'):
                    m.validate_v213_policy()
        changed = copy.deepcopy(original)
        changed['candidate_screeners'] = [changed['candidate_screeners'][0]] * 2
        real_load = e.load_object
        with patch.object(e, 'load_object', side_effect=lambda path: changed if path == e.POLICY_PATH else real_load(path)):
            with self.assertRaisesRegex(e.PipelineError, 'V213_DISCOVERY_SCREENER_POLICY_INVALID'):
                m.validate_v213_policy()

    def test_actual_discovery_and_sec_preselection_admit_multiple_industries(self):
        policy, _ = m.validate_v213_policy()
        policy = {**policy, 'candidate_seed_limit': 5, 'sec_candidate_limit': 5, 'top_count': 5}
        industries = {'AGRI': 'Agriculture', 'ENERGY': 'Energy', 'HEALTH': 'Healthcare', 'INDUST': 'Industrials', 'TECH': 'Technology'}
        calls = []
        def screen(name, count):
            calls.append(name)
            self.assertIn(name, BROAD)
            return {'quotes': [{'symbol': symbol, 'industry': industry, 'regularMarketPrice': 20,
                               'marketCap': 1_000_000_000, 'averageDailyVolume3Month': 500_000}
                              for symbol, industry in industries.items()]}
        with patch.dict(sys.modules, {'yfinance': SimpleNamespace(screen=screen)}), patch.object(e, 'atomic_json') as write:
            seeds = e.discover_candidates(policy)
        reference = {symbol: {'ticker': symbol, 'name': 'Synthetic', 'cik': '0000000001', 'exchange': 'Nasdaq'} for symbol in industries}
        candidates = e.validate_candidates(seeds, reference, policy)
        self.assertEqual(set(calls), BROAD)
        self.assertEqual({r['ticker'] for r in candidates}, set(industries))
        self.assertTrue(all(set(r['screeners']) == BROAD for r in candidates))
        write.assert_called_once()
        self.assertNotEqual(write.call_args.args[0].name, 'candidate_seed.json')

    def test_discovery_cache_changes_with_policy_and_not_score_weights(self):
        original = self.policy()
        def path_for(policy):
            with patch.dict(sys.modules, {'yfinance': SimpleNamespace(screen=lambda *a, **k: {'quotes': [{'symbol': 'TEST'}]})}), patch.object(e, 'atomic_json') as write:
                e.discover_candidates(policy)
            return write.call_args.args[0]
        first = path_for(original)
        for change in ({'candidate_seed_limit': original['candidate_seed_limit'] + 1},
                       {'per_screener_count': original['per_screener_count'] + 1},
                       {'candidate_screeners': original['candidate_screeners'][:-1]}):
            self.assertNotEqual(path_for({**original, **change}), first)
        self.assertEqual(path_for({**original, 'factor_weights': {}}), first)

    def test_all_provider_failures_cannot_resurrect_old_unbound_seed_cache(self):
        policy = self.policy()
        old = e.CACHE_ROOT / 'candidate_seed.json'
        def old_cache(path, hours):
            return [{'ticker': 'OLDTECH', 'screen_weight': 6, 'screeners': ['growth_technology_stocks'], 'market': {}}] if path == old else None
        def failed(*args, **kwargs):
            raise RuntimeError('SYNTHETIC_PROVIDER_FAILURE')
        with patch.dict(sys.modules, {'yfinance': SimpleNamespace(screen=failed)}), patch.object(e, 'cached', side_effect=old_cache) as cache, \
                patch.object(e, 'nasdaq_screener_rows', side_effect=failed), patch.object(e, 'atomic_json') as write:
            with self.assertRaisesRegex(e.PipelineError, 'All T3 candidate screeners failed'):
                e.discover_candidates(policy)
        self.assertNotEqual(cache.call_args.args[0], old)
        write.assert_not_called()

    def test_same_policy_seed_cache_remains_usable(self):
        policy = self.policy()
        cached = [{'ticker': 'TEST', 'screen_weight': 1.0, 'screeners': ['most_actives'], 'market': {}}]
        def failed(*args, **kwargs): raise RuntimeError('SYNTHETIC_PROVIDER_FAILURE')
        with patch.dict(sys.modules, {'yfinance': SimpleNamespace(screen=failed)}), patch.object(e, 'cached', return_value=cached), \
                patch.object(e, 'nasdaq_screener_rows', side_effect=failed), patch.object(e, 'atomic_json') as write:
            self.assertEqual(e.discover_candidates(policy), cached)
        write.assert_not_called()

    def test_empty_screens_are_bridged_by_the_policy_seed_list_for_seven_days(self):
        # V15: from 2026-10-16 evening every Yahoo screen answered with zero quotes; with the Nasdaq fallback also down, the
        # last seed list of the same policy carries discovery for candidate_cache_hours (168), named in the log, and no new
        # seed list is written.
        policy = self.policy()
        self.assertEqual(policy['candidate_cache_hours'], 168)
        seed = [{'ticker': 'TEST', 'screen_weight': 1.0, 'screeners': ['most_actives'], 'market': {}}]
        empty = SimpleNamespace(screen=lambda name, count: {'quotes': [], 'total': 0})
        with tempfile.TemporaryDirectory() as tmp, patch.object(e, 'CACHE_ROOT', Path(tmp)), \
                patch.dict(sys.modules, {'yfinance': empty}), patch.object(e, 'atomic_json') as write, \
                patch.object(e, 'nasdaq_screener_rows', side_effect=RuntimeError('SYNTHETIC_PROVIDER_FAILURE')):
            path = e.discovery_cache_path(policy)
            path.write_text(json.dumps(seed), encoding='utf-8')
            for hours, usable in ((25, True), (167, True), (169, False)):
                stamp = time.time() - hours * 3600
                os.utime(path, (stamp, stamp))
                with self.subTest(hours=hours):
                    if usable:
                        with self.assertLogs(e.LOGGER, 'WARNING') as logs:
                            self.assertEqual(e.discover_candidates(policy), seed)
                        self.assertIn('undervalued_growth_stocks:EMPTY, most_actives:EMPTY, day_gainers:EMPTY', logs.output[0])
                        self.assertIn('nasdaq_us_stock_screener:RuntimeError', logs.output[0])
                        self.assertIn('reusing the Yahoo seed list', logs.output[0])
                        self.assertIn('bound 168 h', logs.output[0])
                    else:
                        with self.assertRaisesRegex(e.PipelineError, 'All T3 candidate screeners failed: .*day_gainers:EMPTY'):
                            e.discover_candidates(policy)
        write.assert_not_called()

    def test_one_empty_screen_does_not_block_the_others(self):
        policy = self.policy()
        def screen(name, count):
            return {'quotes': [] if name == 'day_gainers' else [{'symbol': 'TEST'}]}
        with patch.dict(sys.modules, {'yfinance': SimpleNamespace(screen=screen)}), patch.object(e, 'atomic_json') as write, \
                patch.object(e, 'nasdaq_screener_rows') as nasdaq:
            seeds = e.discover_candidates(policy)
        nasdaq.assert_not_called()
        self.assertEqual([s['ticker'] for s in seeds], ['TEST'])
        self.assertEqual(set(seeds[0]['screeners']), BROAD - {'day_gainers'})
        write.assert_called_once()

    # V15 second seed source (operator 2026-10-18): the Nasdaq US stock screener seeds discovery when Yahoo gives nothing.
    @staticmethod
    def nasdaq_row(symbol, price, cap, volume, pct):
        return {'symbol': symbol, 'name': f'{symbol} Synthetic Common Stock', 'lastsale': price, 'marketCap': cap,
                'volume': volume, 'pctchange': pct, 'netchange': '0.10', 'sector': 'Industrials',
                'industry': 'Electrical Products', 'country': 'United States', 'ipoyear': '', 'url': '/market-activity/x'}

    def nasdaq_rows(self):
        r = self.nasdaq_row
        return [r('BIG', '$120.00', '900000000000.00', '1000000', '0.5%'), r('ACTV', '$15.25', '2000000000.00', '90000000', '-1.2%'),
                r('GAIN', '$30.00', '800000000.00', '400000', '12.5%'), r('BRK/B', '$480.10', '1000000000000.00', '3000000', '0.1%'),
                r('PENNY', '$3.00', '900000000.00', '5000000', '40%'), r('TINY', '$20.00', '100000000.00', '5000000', '30%'),
                r('THIN', '$20.00', '900000000.00', '1000', '25%'), r('ABR^D', '$20.00', '900000000.00', '500000', '1%'),
                r('NOCAP', '$20.00', 'NA', '500000', '1%')]

    def test_policy_catalog_and_activation_bind_the_nasdaq_fallback_as_t3(self):
        policy, activation = m.validate_v213_policy()
        spec = e.fallback_seed_screen(policy)
        self.assertEqual(spec['source_id'], 'nasdaq_us_stock_screener')
        self.assertEqual([(s['name'], s['sort_field'], s['weight']) for s in spec['slices']],
                         [('nasdaq_largest_market_cap', 'marketCap', 5), ('nasdaq_most_active', 'volume', 2), ('nasdaq_day_gainers', 'pctchange', 1)])
        self.assertEqual(activation['discovery_only_sources']['nasdaq_us_stock_screener'],
                         {'authoritative': False, 'purpose': 'local_candidate_seed_fallback_and_market_observation_only',
                          'raw_payload_redistribution': False, 'runtime_enabled': True})
        _manifest, sources, _warnings = e.load_catalog()
        member = {s.id: s for s in sources}['nasdaq_us_stock_screener']
        self.assertEqual((member.evidence_tier, member.evidence_role, member.host_group, member.runtime_enabled),
                         ('T3', 'public_market_observation', 'api.nasdaq.com', False))
        self.assertEqual(policy['required_catalog_count'], len(sources))
        self.assertNotEqual(e.fallback_cache_path(policy, spec), e.discovery_cache_path(policy))

    def test_nasdaq_screener_seeds_discovery_when_every_yahoo_screen_is_empty(self):
        policy = {**self.policy(), 'per_screener_count': 1}
        empty = SimpleNamespace(screen=lambda name, count: {'quotes': [], 'total': 0})
        with patch.dict(sys.modules, {'yfinance': empty}), patch.object(e, 'nasdaq_screener_rows', return_value=self.nasdaq_rows()) as nasdaq, \
                patch.object(e, 'atomic_json') as write, self.assertLogs(e.LOGGER, 'WARNING') as logs:
            seeds = e.discover_candidates(policy)
        nasdaq.assert_called_once()
        self.assertEqual([(s['ticker'], s['screen_weight'], s['screeners']) for s in seeds],
                         [('BRK-B', 5.0, ['nasdaq_largest_market_cap']), ('ACTV', 2.0, ['nasdaq_most_active']), ('GAIN', 1.0, ['nasdaq_day_gainers'])])
        self.assertTrue(all(s['seed_source'] == 'nasdaq_us_stock_screener' for s in seeds))
        self.assertEqual(seeds[0]['market'], {'symbol': 'BRK-B', 'longName': 'BRK/B Synthetic Common Stock', 'sector': 'Industrials',
                                              'industry': 'Electrical Products', 'regularMarketPrice': 480.1, 'marketCap': 1e12,
                                              'regularMarketVolume': 3e6, 'regularMarketChangePercent': 0.1})
        self.assertIn('day_gainers:EMPTY', logs.output[0])
        self.assertIn('the Nasdaq US stock screener seeded 3', logs.output[0])
        write.assert_called_once()
        self.assertEqual(write.call_args.args[0], e.fallback_cache_path(policy, e.fallback_seed_screen(policy)))
        self.assertNotEqual(write.call_args.args[0], e.discovery_cache_path(policy))
        reference = {s: {'ticker': s, 'name': 'Synthetic', 'cik': '0000000001', 'exchange': 'NYSE'} for s in ('BRK-B', 'ACTV', 'GAIN')}
        admitted = e.validate_candidates(seeds, reference, {**policy, 'top_count': 3})
        self.assertEqual({r['ticker'] for r in admitted}, {'BRK-B', 'ACTV', 'GAIN'})

    def test_nasdaq_slices_skip_rows_below_the_policy_floors(self):
        policy = self.policy()
        merged = e.nasdaq_seed_candidates(policy, e.fallback_seed_screen(policy), self.nasdaq_rows())
        self.assertEqual(set(merged), {'BIG', 'ACTV', 'GAIN', 'BRK-B'})
        self.assertTrue(all(row['screen_weight'] == 8.0 for row in merged.values()))
        self.assertEqual(e.nasdaq_seed_candidates(policy, e.fallback_seed_screen(policy), self.nasdaq_rows()[4:]), {})
        for value, parsed in (('$175.55', 175.55), ('49492610320.00', 49492610320.0), ('-0.058%', -0.058), ('1,234', 1234.0),
                              ('NA', None), ('', None), (None, None), (True, None), ('1e5', None), ('$', None)):
            with self.subTest(value=value):
                self.assertEqual(e._nasdaq_number(value), parsed)

    def test_nasdaq_failure_falls_back_to_the_newest_bound_seed_list(self):
        policy = self.policy()
        empty = SimpleNamespace(screen=lambda name, count: {'quotes': [], 'total': 0})
        def blocked(http):
            raise e.PipelineError('NASDAQ_SCREENER_HTTP_403')
        yahoo_seed = [{'ticker': 'YAHOO1', 'screen_weight': 2.0, 'screeners': ['most_actives'], 'market': {}}]
        nasdaq_seed = [{'ticker': 'NASDAQ1', 'screen_weight': 5.0, 'screeners': ['nasdaq_largest_market_cap'], 'market': {},
                        'seed_source': 'nasdaq_us_stock_screener'}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(e, 'CACHE_ROOT', Path(tmp)), patch.dict(sys.modules, {'yfinance': empty}), \
                patch.object(e, 'nasdaq_screener_rows', side_effect=blocked), patch.object(e, 'atomic_json') as write:
            primary = e.discovery_cache_path(policy)
            fallback = e.fallback_cache_path(policy, e.fallback_seed_screen(policy))
            primary.write_text(json.dumps(yahoo_seed), encoding='utf-8')
            fallback.write_text(json.dumps(nasdaq_seed), encoding='utf-8')
            for (primary_hours, fallback_hours), expected, label in (((30, 5), nasdaq_seed, 'Nasdaq'), ((30, 50), yahoo_seed, 'Yahoo'),
                                                                     ((200, 100), nasdaq_seed, 'Nasdaq'), ((200, 170), None, None)):
                for path, hours in ((primary, primary_hours), (fallback, fallback_hours)):
                    stamp = time.time() - hours * 3600
                    os.utime(path, (stamp, stamp))
                with self.subTest(primary=primary_hours, fallback=fallback_hours):
                    if expected is None:
                        with self.assertRaisesRegex(e.PipelineError, 'nasdaq_us_stock_screener:NASDAQ_SCREENER_HTTP_403'):
                            e.discover_candidates(policy)
                    else:
                        with self.assertLogs(e.LOGGER, 'WARNING') as logs:
                            self.assertEqual(e.discover_candidates(policy), expected)
                        self.assertIn(f'reusing the {label} seed list', logs.output[0])
                        self.assertIn('nasdaq_us_stock_screener:NASDAQ_SCREENER_HTTP_403', logs.output[0])
        write.assert_not_called()

    def test_empty_or_disabled_nasdaq_fallback_is_named(self):
        policy = self.policy()
        empty = SimpleNamespace(screen=lambda name, count: {'quotes': [], 'total': 0})
        with tempfile.TemporaryDirectory() as tmp, patch.object(e, 'CACHE_ROOT', Path(tmp)), patch.dict(sys.modules, {'yfinance': empty}):
            with patch.object(e, 'nasdaq_screener_rows', return_value=self.nasdaq_rows()[4:]):
                with self.assertRaisesRegex(e.PipelineError, 'day_gainers:EMPTY, nasdaq_us_stock_screener:EMPTY$'):
                    e.discover_candidates(policy)
            real_load = e.load_object
            def disabled(path):
                value = real_load(path)
                if path == e.ACTIVATION_PATH:
                    value['discovery_only_sources']['nasdaq_us_stock_screener']['runtime_enabled'] = False
                return value
            with patch.object(e, 'load_object', side_effect=disabled), patch.object(e, 'nasdaq_screener_rows') as nasdaq:
                with self.assertRaisesRegex(e.PipelineError, 'nasdaq_us_stock_screener:DISABLED$'):
                    e.discover_candidates(policy)
            nasdaq.assert_not_called()

    def test_malformed_fallback_policy_or_authoritative_activation_fails_closed(self):
        policy = self.policy()
        spec = policy['fallback_seed_screen']
        bad_slices = ({'name': 'nasdaq_beta', 'sort_field': 'beta', 'weight': 1}, {'name': 'yahoo_most_actives', 'sort_field': 'volume', 'weight': 1},
                      {'name': 'nasdaq_x', 'sort_field': 'volume', 'weight': 0}, {'name': 'nasdaq_x', 'sort_field': 'volume', 'weight': True},
                      {'name': 'nasdaq_x', 'sort_field': 'volume', 'weight': 1, 'sector': 'Technology'})
        for changed in ([{**spec, 'slices': [row]} for row in bad_slices]
                        + [{**spec, 'slices': [spec['slices'][0]] * 2}, {**spec, 'slices': []}, {**spec, 'source_id': 'yahoo_finance_public_unofficial'},
                           {**spec, 'url': 'https://example.invalid/'}, None]):
            with self.subTest(spec=changed), self.assertRaisesRegex(e.PipelineError, 'FALLBACK_SEED_SCREEN_POLICY_INVALID'):
                e.fallback_seed_screen({**policy, 'fallback_seed_screen': changed})
        real_load = e.load_object
        for key, value in (('authoritative', True), ('raw_payload_redistribution', True), ('runtime_enabled', 'yes')):
            def changed_activation(path, key=key, value=value):
                loaded = real_load(path)
                if path == e.ACTIVATION_PATH:
                    loaded['discovery_only_sources']['nasdaq_us_stock_screener'][key] = value
                return loaded
            with self.subTest(key=key), patch.object(e, 'load_object', side_effect=changed_activation):
                with self.assertRaisesRegex(e.PipelineError, 'Nasdaq stock screener must remain T3 discovery-only'):
                    e.fallback_seed_screen(policy)

    def test_nasdaq_fetch_is_one_bounded_json_get(self):
        class Response:
            def __init__(self, status=200, content_type='application/json; charset=utf-8', body=b'', history=()):
                self.status_code, self.headers, self.body, self.history, self.closed = status, {'Content-Type': content_type}, body, list(history), False
            def iter_content(self, chunk_size):
                yield self.body
            def close(self):
                self.closed = True
        class Http:
            def __init__(self, response):
                self.response, self.calls, self.cookies = response, [], SimpleNamespace(clear=lambda: None)
            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return self.response
        good = json.dumps({'data': {'asOf': None, 'headers': {}, 'rows': [{'symbol': 'AAA'}, 'x']}, 'message': None, 'status': {}}).encode()
        http = Http(Response(body=good))
        self.assertEqual(e.nasdaq_screener_rows(http), [{'symbol': 'AAA'}])
        (url, kwargs), = http.calls
        self.assertEqual(url, e.NASDAQ_SCREENER_URL)
        self.assertEqual((kwargs['timeout'], kwargs['allow_redirects'], kwargs['stream'], set(kwargs['headers'])),
                         ((5, 30), False, True, {'User-Agent', 'Accept'}))
        self.assertTrue(http.response.closed)
        for response, code in ((Response(status=302), 'NASDAQ_SCREENER_HTTP_302'), (Response(status=403), 'NASDAQ_SCREENER_HTTP_403'),
                               (Response(body=good, history=[object()]), 'NASDAQ_SCREENER_REDIRECT_REJECTED'),
                               (Response(content_type='text/html', body=good), 'NASDAQ_SCREENER_CONTENT_TYPE_INVALID'),
                               (Response(body=b'{"data": null}'), 'NASDAQ_SCREENER_SHAPE_INVALID'),
                               (Response(body=b'{"data": {"rows": []}, "data": {}}'), 'PUBLIC_JSON_PAYLOAD_INVALID'),
                               (Response(body=b'x' * (e.PUBLIC_JSON_MAX_BYTES + 1)), 'NASDAQ_SCREENER_TOO_LARGE')):
            with self.subTest(code=code), self.assertRaisesRegex(e.PipelineError, code):
                e.nasdaq_screener_rows(Http(response))
            self.assertTrue(response.closed)


if __name__ == '__main__':
    unittest.main()
