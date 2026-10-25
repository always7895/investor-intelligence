"""Causal checks on private product copies; no source rewrite or policy bypass."""
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from tests import test_batch05_cache_carry as checks
from tests import test_identity_batch04 as identity_fixture

ROOT = Path(__file__).resolve().parents[1]


class Batch05MutationTests(unittest.TestCase):
    def test_cache_writer_reader_and_sidecar_checks_are_causal(self):
        cases = [
            ("scripts/company_deep_report.py", "cache.write_bytes(raw)",
             'cache.write_bytes(json.dumps({**json.loads(acquisition), "body_utf8": raw.decode("utf-8")}).encode("utf-8"))',
             "cdr", "test_new_cache_write_remains_compatible_with_real_raw_readers"),
            ("scripts/company_deep_report.py", "sidecar.write_bytes(acquisition)", "pass",
             "cdr", "test_writer_to_identity_reader_preserves_body_origin_and_acquisition_not_mtime"),
            ("scripts/build_identity_shards.py",
             "modified = acquired if acquired is not None else datetime.fromtimestamp(before.st_mtime, timezone.utc)",
             "modified = datetime.fromtimestamp(before.st_mtime, timezone.utc)",
             "shards", "test_writer_to_identity_reader_preserves_body_origin_and_acquisition_not_mtime"),
            ("scripts/sec_ticker_cache.py",
             'if hashlib.sha256(body).hexdigest() != doc["body_sha256"]:',
             "if False:", "cache_codec", "test_bad_or_missing_sidecar_is_unverified_in_both_age_readers"),
            ("scripts/sec_ticker_cache.py",
             'or doc["schema"] != SCHEMA or doc["origin_url"] != ORIGIN',
             'or doc["schema"] != SCHEMA',
             "cache_codec", "test_bad_or_missing_sidecar_is_unverified_in_both_age_readers"),
        ]
        for index, (relative, old, new, attribute, method) in enumerate(cases):
            with self.subTest(product=relative, case=index):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertEqual(source.count(old), 1)
                for broken in (False, True):
                    with tempfile.TemporaryDirectory() as tmp:
                        path = Path(tmp) / Path(relative).name
                        path.write_text(source.replace(old, new) if broken else source, encoding="utf-8")
                        spec = importlib.util.spec_from_file_location("batch05_owned_copy", path)
                        product = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(product)
                        # Patch all import aliases actually used by the real test callers.
                        with mock.patch.object(checks, attribute, product), mock.patch.object(
                            identity_fixture, "shards", product if attribute == "shards" else checks.shards
                        ), mock.patch.object(checks.shards, "sec_ticker_cache",
                                             product if attribute == "cache_codec" else checks.cache_codec):
                            suite = unittest.TestSuite([checks.CacheCarryBatch05Tests(method)])
                            result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
                        self.assertEqual(result.testsRun, 1)
                        self.assertEqual(len(result.skipped), 0)
                        if broken:
                            self.assertTrue(result.failures or result.errors, "mutant survived")
                        else:
                            self.assertEqual(result.failures + result.errors, [])


if __name__ == "__main__":
    unittest.main()
