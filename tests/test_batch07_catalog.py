"""Catalog real callers with fake OS authority/lock and owned temporary storage.
These tests prove logic and serialization calls, NOT native lock/race/volume proof.
"""
import copy
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from contextlib import contextmanager, redirect_stdout
from unittest.mock import Mock, patch

from tests.batch07_fixtures import ROOT, PROFILE, isolated_intent, profile
import local_model_catalog as catalog
import local_model_endpoint as endpoint


def entry(priority=1):
    settings = {**PROFILE, 'model': 'batch07-' + str(priority)}
    return dict(base_url='http://127.0.0.1:' + str(49190 + priority), model=settings['model'],
                profile=settings, priority=priority)


def registry(*items, enabled=True):
    return catalog.validate_registry(dict(schema_version=1, auto_select_opt_in=enabled, candidates=list(items)))


def snapshot(value):
    return copy.deepcopy(value), catalog._registry_sha256(value)


def metadata(bound, settings, minimum, **kwargs):
    return dict(binding_sha256=profile.binding_sha256(bound, settings), model=bound['model'], declared_context=262144)


def attributes(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    return endpoint._DIRECTORY_ATTRIBUTE if Path(path).is_dir() else getattr(info, 'st_file_attributes', 0)


@contextmanager
def fixture_storage(lock=None):
    with isolated_intent() as folder, patch.object(catalog, '_proven_folder', return_value=folder), \
            patch.object(endpoint, '_file_attributes', side_effect=attributes), \
            patch.dict(sys.modules, {'msvcrt': SimpleNamespace(LK_NBLCK=1, LK_UNLCK=0, locking=lock or Mock())}):
        yield folder


class CatalogCallers(unittest.TestCase):
    def test_closed_schema_duplicates_priorities_ports_and_original_identity(self):
        valid = entry()
        bound, settings, digest = catalog._identity(valid)
        self.assertEqual(digest, profile.binding_sha256(bound, settings))
        self.assertEqual(bound['model_profile_sha256'], profile.profile_sha256(PROFILE | {'model': valid['model']}))
        for changed in ({**valid, 'extra': 1}, {**valid, 'priority': True}, {**valid, 'priority': 65},
                        {**valid, 'model': valid['model'].upper()},
                        {**valid, 'base_url': 'http://127.0.0.1:5000'}, {**valid, 'base_url': 'http://127.0.0.1:8000'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                registry(changed)
        for value in (dict(schema_version=True, auto_select_opt_in=False, candidates=[]),
                      dict(schema_version=1, auto_select_opt_in=0, candidates=[]),
                      dict(schema_version=1, auto_select_opt_in=False, candidates=[entry(i) for i in range(1, 18)])):
            with self.assertRaises(ValueError):
                catalog.validate_registry(value)
        for other in (valid, {**valid, 'priority': 2}, {**entry(2), 'priority': 1}):
            with self.assertRaisesRegex(ValueError, 'CATALOG_DUPLICATE'):
                registry(valid, other)

    def test_main_register_list_remove_and_opt_in_are_offline(self):
        lock = Mock()
        with fixture_storage(lock) as folder, patch.object(profile, 'binding_json_http', side_effect=AssertionError('NO_HTTP')):
            operations = [('register', {'entry': entry()}), ('set-opt-in', {'value': True}), ('list', {})]
            result = None
            for operation, request in operations:
                output = io.StringIO()
                with patch.object(sys, 'stdin', io.StringIO(json.dumps(request))), redirect_stdout(output):
                    self.assertEqual(catalog.main(['--op', operation]), 0)
                result = json.loads(output.getvalue())
                self.assertFalse(result['weights_replaced'])
                self.assertEqual(result['qualification'], 'UNQUALIFIED')
            self.assertTrue(result['auto_select_opt_in'])
            self.assertEqual(result['candidates'][0]['state'], 'REGISTERED')
            catalog.remove(result['candidates'][0]['binding_sha256'])
            self.assertEqual(catalog.list_registry()['candidates'], [])
            self.assertTrue((folder / catalog.LOCK_NAME).is_file())
            self.assertFalse((folder / catalog.TEMP_NAME).exists())
            self.assertEqual([c.args[1:] for c in lock.call_args_list], [(1, 1), (0, 1)] * 3)

    def test_missing_empty_malformed_duplicate_and_oversize_presence(self):
        with fixture_storage() as folder:
            self.assertEqual(catalog.list_registry()['candidates'], [])
            path = folder / catalog.REGISTRY_NAME
            for raw in (b'', b'null', b'{', b'{"schema_version":1,"schema_version":1}', b'x' * 65537):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    catalog.load_registry()
            path.unlink()
            path.mkdir()
            with self.assertRaises(ValueError):
                catalog.load_registry()

    def test_lock_busy_never_mutates_registry_or_steals_lock(self):
        with fixture_storage(Mock(side_effect=OSError('synthetic busy'))) as folder:
            with self.assertRaisesRegex(ValueError, 'CATALOG_BUSY'):
                catalog.register(entry())
            self.assertTrue((folder / catalog.LOCK_NAME).is_file())
            self.assertFalse((folder / catalog.REGISTRY_NAME).exists())
            self.assertFalse((folder / catalog.TEMP_NAME).exists())

    def test_write_leftover_and_failed_replace_cleanup_are_owned_only(self):
        with fixture_storage() as folder:
            temp = folder / catalog.TEMP_NAME
            temp.write_bytes(b'owned-by-other-fixture-operation')
            with self.assertRaisesRegex(ValueError, 'CATALOG_TEMP_LEFTOVER'):
                catalog.register(entry())
            self.assertEqual(temp.read_bytes(), b'owned-by-other-fixture-operation')
            temp.unlink()
            with patch.object(os, 'replace', side_effect=OSError('fixture failure')), self.assertRaisesRegex(
                    ValueError, 'CATALOG_STATE_UNAVAILABLE'):
                catalog.register(entry())
            self.assertFalse(temp.exists())
            self.assertFalse((folder / catalog.REGISTRY_NAME).exists())
            temp.write_bytes(b'not-the-created-identity')
            catalog._discard_owned_temp(endpoint, temp, (-1, -1))
            self.assertEqual(temp.read_bytes(), b'not-the-created-identity')

    def test_successful_replace_does_not_clean_a_reused_temp_name(self):
        real_replace = os.replace
        with fixture_storage() as folder:
            temp = folder / catalog.TEMP_NAME

            def replace_then_reuse(src, dst):
                real_replace(src, dst)
                temp.write_bytes(b'new-owner-fixture')

            with patch.object(os, 'replace', side_effect=replace_then_reuse):
                catalog.register(entry())
            self.assertEqual(temp.read_bytes(), b'new-owner-fixture')
            self.assertEqual(len(catalog.list_registry()['candidates']), 1)

    def test_refresh_priority_limits_no_retry_and_sanitized_failures(self):
        value = registry(entry(3), entry(1), entry(2))
        reader = Mock(side_effect=[profile.BindingUnavailable('BINDING_AUTH_REQUIRED'),
                                  RuntimeError('synthetic-private-detail'), metadata(*catalog._identity(entry(3))[:2], 262144)])
        with patch.object(catalog, 'load_registry', return_value=snapshot(value)), \
                patch.object(catalog, '_context_minimum', return_value=262144):
            result = catalog.refresh(str(ROOT), metadata_reader=reader, clock=lambda: 0)
        self.assertEqual([r['priority'] for r in result['rows']], [1, 2, 3])
        self.assertEqual([r['state'] for r in result['rows']], ['UNAVAILABLE', 'UNAVAILABLE', 'SERVED_METADATA_ONLY'])
        self.assertEqual(reader.call_count, 3)
        self.assertEqual(result['max_received_body_bytes'], 4 * 1024 * 1024)
        self.assertNotIn('synthetic-private-detail', json.dumps(result))
        for call in reader.call_args_list:
            self.assertEqual(call.kwargs, dict(budget=15, max_response_bytes=131071))

    def test_late_refresh_exhaustion_prevents_remaining_evaluations(self):
        value = registry(entry(1), entry(2))
        clock = iter([0, 0, 21, 21])
        reader = Mock(side_effect=metadata)
        with patch.object(catalog, 'load_registry', return_value=snapshot(value)), \
                patch.object(catalog, '_context_minimum', return_value=262144):
            result = catalog.refresh(str(ROOT), metadata_reader=reader, clock=lambda: next(clock))
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(result['rows'][0]['reason'], 'CATALOG_REFRESH_LATE_REPLY_REFUSED')
        self.assertEqual(result['rows'][1]['state'], 'BUDGET_EXHAUSTED')

    def test_select_real_offline_save_only_after_stable_candidate(self):
        value = registry(entry())
        digest = catalog._identity(entry())[2]
        with isolated_intent(), patch.object(catalog, 'load_registry', return_value=snapshot(value)), \
                patch.object(catalog, '_context_minimum', return_value=262144):
            result = catalog.select(str(ROOT), digest, metadata_reader=metadata)
            self.assertEqual(result['state'], 'SELECTED_INTENT')
            self.assertEqual(profile.resolve_binding(str(ROOT))['binding_sha256'], digest)
        changed = registry({**entry(), 'priority': 2})
        for again, error in ((changed, 'CATALOG_REGISTRY_CHANGED'), (registry(), 'CATALOG_CANDIDATE_UNKNOWN')):
            with patch.object(catalog, 'load_registry', side_effect=[snapshot(value), snapshot(again)]), \
                    patch.object(catalog, '_context_minimum', return_value=262144), patch.object(catalog, '_save') as writer:
                with self.assertRaisesRegex(ValueError, error):
                    catalog.select(str(ROOT), digest, metadata_reader=metadata)
                writer.assert_not_called()

    def test_suggestion_is_opt_in_read_only_priority_with_external_intent_preserved(self):
        value = registry(entry(2), entry(1))
        with patch.object(catalog, 'load_registry', return_value=snapshot(value)), \
                patch.object(catalog, '_current_intent', return_value=('EXPLICIT_STRATA', 'f' * 64)), \
                patch.object(catalog, '_context_minimum', return_value=262144), \
                patch.object(catalog, '_save', side_effect=AssertionError('NO_SAVE')), \
                patch.object(catalog, '_write_registry', side_effect=AssertionError('NO_WRITE')), \
                patch.dict(os.environ, {'V213_RUNTIME_BINDING_JSON': 'external-fixture'}):
            before = dict(os.environ)
            result = catalog.suggest(str(ROOT), metadata_reader=metadata, clock=lambda: 0)
            self.assertEqual(result['priority'], 1)
            self.assertTrue(result['requires_manual_confirmation'])
            self.assertTrue(result['differs_from_current_intent'])
            self.assertTrue(result['external_intent_present'])
            self.assertFalse(result['saved'])
            self.assertEqual(dict(os.environ), before)
        with patch.object(catalog, 'load_registry', return_value=snapshot(registry(entry(), enabled=False))), \
                patch.object(catalog, 'refresh', side_effect=AssertionError('NO_REFRESH')):
            self.assertEqual(catalog.suggest(str(ROOT), startup=True)['state'], 'NOT_ENABLED_OR_EMPTY')
            with self.assertRaisesRegex(ValueError, 'CATALOG_AUTO_NOT_OPTED_IN'):
                catalog.suggest(str(ROOT))

    def test_suggestion_refuses_opt_in_registry_or_saved_intent_drift(self):
        value = registry(entry())
        for after in (registry(entry(), enabled=False), registry({**entry(), 'priority': 2})):
            with patch.object(catalog, 'load_registry', side_effect=[snapshot(value), snapshot(value), snapshot(after)]), \
                    patch.object(catalog, '_current_intent', return_value=('LEGACY_ABSENT', '')), \
                    patch.object(catalog, '_context_minimum', return_value=262144), self.assertRaisesRegex(
                        ValueError, 'CATALOG_PROPOSAL_STALE'):
                catalog.suggest(str(ROOT), metadata_reader=metadata, clock=lambda: 0)
        with patch.object(catalog, 'load_registry', return_value=snapshot(value)), \
                patch.object(catalog, '_current_intent', side_effect=[('LEGACY_ABSENT', ''), ('EXPLICIT_STRATA', 'f' * 64)]), \
                patch.object(catalog, '_context_minimum', return_value=262144), self.assertRaisesRegex(
                    ValueError, 'CATALOG_PROPOSAL_STALE'):
            catalog.suggest(str(ROOT), metadata_reader=metadata, clock=lambda: 0)

    def test_cli_invalid_request_is_finite_and_has_no_io(self):
        for request in ('{"value":1}', '{"value":true,"extra":"synthetic-private-detail"}', '{'):
            output = io.StringIO()
            with patch.object(sys, 'stdin', io.StringIO(request)), redirect_stdout(output), \
                    patch.object(catalog, '_Serialized', side_effect=AssertionError('NO_LOCK')):
                self.assertEqual(catalog.main(['--op', 'set-opt-in']), 1)
            result = json.loads(output.getvalue())
            self.assertEqual(result['error'], 'MODEL_CATALOG_UNAVAILABLE')
            self.assertNotIn('synthetic-private-detail', output.getvalue())


if __name__ == '__main__':
    unittest.main()
