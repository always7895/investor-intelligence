"""Real binding/endpoint callers; fake owned HTTP, no model/native qualification."""
import copy
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from tests.batch07_fixtures import ROOT, PROFILE, FakeStrata, binding, isolated_intent, profile, save
import local_model_endpoint as endpoint


class BindingCallers(unittest.TestCase):
    def test_offline_save_resolve_remove_and_original_digests(self):
        with isolated_intent(), patch.object(profile, 'binding_json_http', side_effect=AssertionError('NO_HTTP')):
            result = save('http://127.0.0.1:49199/v1/')
            resolved = profile.resolve_binding(str(ROOT))
            self.assertEqual(resolved['binding']['base_url'], 'http://127.0.0.1:49199')
            self.assertEqual(resolved['binding_sha256'], result['binding_sha256'])
            self.assertEqual(resolved['profile_sha256'], profile.profile_sha256(PROFILE))
            self.assertFalse(result['release_qualified'])
            self.assertEqual(resolved['qualification'], 'UNQUALIFIED')
            selection = json.loads(profile._user_paths()[3].read_bytes())
            self.assertEqual(selection['runtime_binding_sha256'], resolved['binding_sha256'])
            self.assertIs(selection['model_profile_qualified'], False)
            profile.remove_binding()
            self.assertEqual(profile.resolve_binding(str(ROOT)), {'mode': 'LEGACY_ABSENT'})
            self.assertTrue(profile._user_paths()[2].is_file())

    def test_save_interruption_keeps_pending_barrier_at_each_commit_step(self):
        real_replace = os.replace
        for fail_at in (2, 3, 4):
            with self.subTest(fail_at=fail_at), isolated_intent():
                calls = []

                def interrupted(src, dst):
                    calls.append(dst.name)
                    if len(calls) == fail_at:
                        raise OSError('synthetic interruption')
                    return real_replace(src, dst)

                with patch.object(os, 'replace', side_effect=interrupted), self.assertRaises(OSError):
                    save('http://127.0.0.1:49199')
                self.assertEqual(profile._user_paths()[1].read_text(), '{')
                with self.assertRaises(ValueError):
                    profile.resolve_binding(str(ROOT))
                self.assertFalse(list(profile._user_paths()[0].glob('*.tmp')))

    def test_remove_interruption_and_external_intent_are_not_legacy(self):
        with isolated_intent():
            save('http://127.0.0.1:49199')
            selection = profile._user_paths()[3]
            real_unlink = type(selection).unlink

            def interrupted(path, *args, **kwargs):
                if path == selection:
                    raise OSError('synthetic interruption')
                return real_unlink(path, *args, **kwargs)

            with patch.object(type(selection), 'unlink', interrupted), self.assertRaises(OSError):
                profile.remove_binding()
            self.assertEqual(profile._user_paths()[1].read_text(), '{')
            with self.assertRaises(ValueError):
                profile.resolve_binding(str(ROOT))
            with patch.dict(os.environ, {'V213_RUNTIME_BINDING_JSON': ''}), self.assertRaisesRegex(
                    ValueError, 'BINDING_ENV_CONFLICT_REMOVE_EXPLICITLY'):
                profile.remove_binding()

    def test_present_invalid_conflicting_or_orphaned_state_refuses(self):
        with isolated_intent():
            save('http://127.0.0.1:49199')
            good = profile.resolve_binding(str(ROOT))
            for raw in ('', 'null', '{', json.dumps({**good['binding'], 'qualification': 'QUALIFIED'})):
                with self.subTest(raw=raw), patch.dict(os.environ, {'V213_RUNTIME_BINDING_JSON': raw}), self.assertRaises(ValueError):
                    profile.resolve_binding(str(ROOT))
            for kwargs in ({'model': PROFILE['model'].upper()}, {'base_url': 'http://127.0.0.1:49200'}, {'binding_json': ''}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    profile.resolve_binding(str(ROOT), **kwargs)
            before = [p.read_bytes() for p in profile._user_paths()[1:]]
            with patch.dict(os.environ, {'II_LOCAL_LLM_MODEL': 'different'}), self.assertRaises(ValueError):
                save('http://127.0.0.1:49200')
            self.assertEqual(before, [p.read_bytes() for p in profile._user_paths()[1:]])
            profile._user_paths()[1].unlink()
            with self.assertRaisesRegex(ValueError, 'BINDING_SELECTION_WITHOUT_INTENT'):
                profile.resolve_binding(str(ROOT))

    def test_selected_metadata_real_transport_exact_paths_and_projection(self):
        with FakeStrata() as fake:
            fake.catalog['data'].append({'id': 'unrelated-private-fixture'})
            result = profile.selected_metadata(binding(fake.base), PROFILE, 262144)
            self.assertEqual([(x[0], x[1]) for x in fake.calls], [('GET', '/health'), ('GET', '/v1/models')])
            self.assertEqual(result['selected_catalog'], [fake.catalog['data'][0]])
            self.assertNotIn('unrelated-private-fixture', json.dumps(result))
            self.assertNotIn('complete_exact_marker', result)
            self.assertFalse(result['release_qualified'])

    def test_health_and_catalog_identity_negatives_no_alias_or_fallback(self):
        with FakeStrata() as fake:
            good_health, good_catalog = copy.deepcopy(fake.health), copy.deepcopy(fake.catalog)
            cases = [({'loaded': 1}, None), ({'api_key': True}, None), ({'model': PROFILE['model'].upper()}, None),
                     ({'max_context': True}, None), (None, {'alias_of': PROFILE['model']}),
                     (None, {'meta': {'n_ctx': 1}}), (None, {'status': {'value': 'loading'}})]
            for health_change, row_change in cases:
                with self.subTest(health=health_change, catalog=row_change):
                    fake.health, fake.catalog = copy.deepcopy(good_health), copy.deepcopy(good_catalog)
                    if health_change:
                        fake.health.update(health_change)
                    if row_change:
                        fake.catalog['data'][0].update(row_change)
                    fake.calls.clear()
                    with self.assertRaises(ValueError):
                        profile.selected_metadata(binding(fake.base), PROFILE, 262144)
                    self.assertLessEqual(len(fake.calls), 2)
                    self.assertTrue(all(c[0] == 'GET' and c[1] in ('/health', '/v1/models') for c in fake.calls))
            fake.health, fake.catalog = good_health, good_catalog
            fake.catalog['data'] *= 2
            with self.assertRaisesRegex(ValueError, 'STRATA_CATALOG_AMBIGUOUS'):
                profile.selected_metadata(binding(fake.base), PROFILE, 262144)

    def test_transport_redirect_invalid_utf8_body_bounds_and_budget(self):
        with FakeStrata() as fake:
            for mode in ('redirect', 'utf8', 'oversize'):
                fake.mode = mode
                fake.calls.clear()
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    profile.selected_metadata(binding(fake.base), PROFILE, 262144, max_response_bytes=512)
                self.assertEqual([(c[0], c[1]) for c in fake.calls], [('GET', '/health')])
        with patch.object(profile, 'binding_json_http', return_value={}) as transport:
            for kwargs in ({'budget': 0}, {'budget': 16}, {'budget': True}, {'max_response_bytes': 262145}):
                with self.assertRaises(ValueError):
                    profile.selected_metadata(binding('http://127.0.0.1:49199'), PROFILE, 262144, **kwargs)
            transport.assert_not_called()

    def test_actual_endpoint_cli_shared_binding_and_failure_sanitization(self):
        # Only the OS terminal attribute seam is fake. Canonical resolution, saved
        # envelope, endpoint caller, selected metadata and HTTP transport are real.
        with isolated_intent(), FakeStrata() as fake, patch.object(endpoint, '_file_attributes', return_value=None), \
                patch.object(endpoint, 'candidate_bases', side_effect=AssertionError('NO_SCAN')), \
                patch.object(endpoint, 'saved_selection', side_effect=AssertionError('NO_LEGACY')):
            save(fake.base)
            output = io.StringIO()
            with redirect_stdout(output):
                code = endpoint.main(['--want', 'ignored', '--base', 'http://127.0.0.1:49200'])
            result = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual((result['model'], result['base_url']), (PROFILE['model'], fake.base))
            self.assertTrue(result['legacy_hints_ignored'])
            fake.calls.clear()
            result = endpoint.resolve(scan_all=True)
            self.assertEqual(result['reason'], 'BINDING_SCAN_ALL_REFUSED')
            self.assertEqual(fake.calls, [])
            result = endpoint.resolve(metadata_reader=Mock(side_effect=RuntimeError('synthetic-private-detail')))
            self.assertEqual(result['reason'], 'BINDING_METADATA_OPERATION_FAILED')
            self.assertNotIn('synthetic-private-detail', json.dumps(result))
            self.assertEqual(fake.calls, [])

    def test_endpoint_rechecks_changed_intent_after_metadata(self):
        with isolated_intent(), FakeStrata() as fake, patch.object(endpoint, '_file_attributes', return_value=None):
            save(fake.base)

            def changing(bound, settings, minimum):
                metadata = profile.selected_metadata(bound, settings, minimum)
                save('http://127.0.0.1:49200')  # offline-only; never contacted
                return metadata

            result = endpoint.resolve(metadata_reader=changing, listeners=Mock(side_effect=AssertionError('NO_LISTENERS')))
            self.assertEqual(result['reason'], 'BINDING_CHANGED_DURING_METADATA')
            self.assertEqual(len(fake.calls), 2)


if __name__ == '__main__':
    unittest.main()
