"""Causal tests on private copies only; canonical products are never rewritten."""
import importlib.util
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests import test_batch06_taifex_callers as callers
from tests import test_batch06_taifex_task as tasks

ROOT = Path(__file__).resolve().parents[1]


def run_case(case):
    result = unittest.TextTestRunner(stream=StringIO()).run(unittest.TestSuite([case]))
    if result.errors:
        raise AssertionError('private-copy check had unexpected test error')
    if result.testsRun != 1 or result.skipped:
        raise AssertionError('private-copy check did not execute exactly one test')
    return len(result.failures)


class Batch06MutationTests(unittest.TestCase):
    def test_delta_caller_assertions_reject_five_private_product_mutants(self):
        cases = [
            ('scripts/import_option_observations.py', 'importer',
             'if args.source == "taifex_delta" and len(rendered) + 2 > TAIFEX_DELTA_MAX_OUTPUT_BYTES:',
             'if False:', 'test_importer_final_rendering_budget_includes_envelope_escaping_and_crlf'),
            ('scripts/import_option_observations.py', 'importer',
             'content = handle.read(TAIFEX_DELTA_MAX_BYTES + 1)', 'content = handle.read()',
             'test_importer_single_binary_bounded_read_and_no_stat'),
            ('scripts/import_option_observations.py', 'importer',
             'origin_verification="UNVERIFIED_LOCAL_FILE")', 'origin_verification="COLLECTOR_CAPTURE_UNQUALIFIED")',
             'test_importer_main_preserves_raw_reference_and_unverified_origin'),
            ('scripts/fetch_public_source_observations.py', 'collector',
             'return _bound_delta_output(result) if any(source in TAIFEX_DELTA_FEEDS for source in sources) else result',
             'return result', 'test_collector_final_cap_drops_all_delta_not_legacy_or_partial_reference'),
            ('scripts/fetch_public_source_observations.py', 'collector',
             'ENDPOINTS = {**ENDPOINTS, **TAIFEX_EOD_FEEDS, **TAIFEX_DELTA_FEEDS}',
             'ENDPOINTS = {**ENDPOINTS, **TAIFEX_EOD_FEEDS, **TAIFEX_DELTA_FEEDS}\nDEFAULT_SOURCES += ("taifex_options_delta",)',
             'test_default_cli_and_runtime_catalog_never_enable_delta_or_eod'),
        ]
        for relative, alias, old, new, method in cases:
            source = (ROOT / relative).read_text(encoding='utf-8')
            self.assertEqual(source.count(old), 1)
            for broken in (False, True):
                with self.subTest(product=relative, check=method, broken=broken), tempfile.TemporaryDirectory() as tmp:
                    copy = Path(tmp) / Path(relative).name
                    copy.write_text(source.replace(old, new) if broken else source, encoding='utf-8', newline='\n')
                    before = sys.path[:]
                    try:
                        spec = importlib.util.spec_from_file_location('batch06_owned_copy', copy)
                        product = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(product)
                        with patch.object(callers, alias, product):
                            failures = run_case(callers.DeltaCallerTests(method))
                    finally:
                        sys.path[:] = before
                    self.assertEqual(failures, 1 if broken else 0, 'private mutant survived or fixed copy failed')

    def test_template_task_trigger_and_action_mutants_are_caught(self):
        source = tasks.TEMPLATE.read_text(encoding='utf-8')
        cases = [
            ('      <Enabled>false</Enabled>', '      <Enabled>true</Enabled>'),
            ('    <Enabled>false</Enabled>', '    <Enabled>true</Enabled>'),
            ('--source taifex_options_eod', '--source taifex_options_delta'),
        ]
        for old, new in cases:
            # Match complete lines: the four-space token is a suffix of the six-space line.
            if old.lstrip().startswith('<Enabled>'):
                old, new = '\n' + old + '\n', '\n' + new + '\n'
            self.assertEqual(source.count(old), 1)
            for broken in (False, True):
                with self.subTest(change=old.strip(), broken=broken), tempfile.TemporaryDirectory() as tmp:
                    copy = Path(tmp) / 'owned-template.xml'
                    copy.write_text(source.replace(old, new) if broken else source, encoding='utf-8', newline='\n')
                    with patch.object(tasks, 'TEMPLATE', copy):
                        failures = run_case(tasks.TaifexTaskTests('test_template_is_disabled_closed_action_and_has_no_registration_caller'))
                    self.assertEqual(failures, 1 if broken else 0, 'private template mutant survived or fixed copy failed')


if __name__ == '__main__':
    unittest.main()
