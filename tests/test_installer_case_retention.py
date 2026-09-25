"""Installer fixture cases are kept for a day, then pruned without following links."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("retention_harness", ROOT / "tests/installer_parse_harness.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

try:
    import _winapi
except ImportError:  # pragma: no cover - non-Windows hosts
    _winapi = None


class CaseRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "cases"
        self.root.mkdir()
        self.outside = Path(self.tmp.name) / "outside"
        self.outside.mkdir()
        (self.outside / "sentinel.txt").write_text("keep", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def case(self, name, age_seconds):
        path = self.root / name
        (path / "nested").mkdir(parents=True)
        (path / "nested" / "evidence.json").write_text("{}", encoding="utf-8")
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_prunes_only_old_case_directories(self):
        old = self.case("ack-" + "a" * 32, 3 * 86400)
        fresh = self.case("ack-" + "b" * 32, 60)
        other = self.root / "notes"
        other.mkdir()
        os.utime(other, (0, 0))
        pruned = harness.prune_stale_cases(self.root)
        self.assertEqual(pruned, [old.name])
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(other.exists())

    @unittest.skipIf(_winapi is None or not hasattr(_winapi, "CreateJunction"), "junctions need Windows")
    def test_junction_inside_a_case_is_removed_as_a_link_only(self):
        old = self.case("installer-reparse-" + "c" * 32, 3 * 86400)
        _winapi.CreateJunction(str(self.outside), str(old / "nested" / "link"))
        stamp = time.time() - 3 * 86400
        os.utime(old, (stamp, stamp))
        harness.prune_stale_cases(self.root)
        self.assertFalse(old.exists())
        self.assertEqual((self.outside / "sentinel.txt").read_text(encoding="utf-8"), "keep")

    @unittest.skipIf(_winapi is None or not hasattr(_winapi, "CreateJunction"), "junctions need Windows")
    def test_top_level_junction_is_never_pruned(self):
        link = self.root / ("r-" + "d" * 32)
        _winapi.CreateJunction(str(self.outside), str(link))
        harness.prune_stale_cases(self.root, retention_seconds=-1)
        self.assertTrue((self.outside / "sentinel.txt").exists())

    def test_new_case_prunes_once_per_root(self):
        old = self.case("ack-" + "e" * 32, 3 * 86400)
        original = harness.AUDIT_CASE_ROOT
        harness.AUDIT_CASE_ROOT = self.root
        try:
            first = harness.new_case("ack")
            self.assertFalse(old.exists())
            stale = self.case("ack-" + "f" * 32, 3 * 86400)
            harness.new_case("ack")
            self.assertTrue(stale.exists())
            self.assertTrue(first.exists())
        finally:
            harness.AUDIT_CASE_ROOT = original
            harness._pruned_roots.discard(self.root)


if __name__ == "__main__":
    unittest.main()
