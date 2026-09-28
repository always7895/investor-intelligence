"""Installer fixture cases are never removed by the tests (project audit 2026-09-29 round 3): creating a new case leaves
every earlier case, its failure receipts and nested journals untouched, whatever their names and ages. Clearing a case
root is a separate maintenance action (docs/WORKSPACE_MAINTENANCE.md). Temporary directories only."""
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
        self.original = harness.AUDIT_CASE_ROOT
        harness.AUDIT_CASE_ROOT = self.root

    def tearDown(self):
        harness.AUDIT_CASE_ROOT = self.original
        self.tmp.cleanup()

    def aged_case(self, name, age_seconds, files):
        path = self.root / name
        for relative, text in files.items():
            (path / relative).parent.mkdir(parents=True, exist_ok=True)
            (path / relative).write_text(text, encoding="utf-8")
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_new_case_preserves_old_failure_evidence_and_other_cases(self):
        failed = self.aged_case("b1-false-green-" + "a" * 32, 3 * 86400, {"result.json": '{"status": "UNEXPECTED"}'})
        journal = self.aged_case("installer-local-source-" + "b" * 32, 3 * 86400,
                                 {"meta/v213-runtime-install.journal.json": '{"state": "ROLLBACK_FAILED"}'})
        os.utime(journal, (time.time() - 3 * 86400,) * 2)  # old parent, freshly written nested journal
        other = self.aged_case("acl-native-" + "c" * 32, 30 * 86400, {"acl.txt": "retained"})
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        first = harness.new_case("read-only-review")
        second = harness.new_case("read-only-review")
        self.assertTrue(first.is_dir() and second.is_dir() and first != second)
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        for case in (failed, journal, other):
            self.assertTrue(case.is_dir(), case.name)

    def test_the_harness_has_no_pruning_path(self):
        for name in ("prune_stale_cases", "_remove_tree_no_follow", "CASE_RETENTION_SECONDS", "_pruned_roots"):
            self.assertFalse(hasattr(harness, name), name)
        with harness.persistent_fixture("b1-retention") as directory:
            self.assertTrue(Path(directory).is_dir())
        self.assertTrue(Path(directory).is_dir())  # no cleanup on exit either

    def test_source_overlap_and_relative_roots_are_refused(self):
        for bad in (ROOT, ROOT / "tests" / "cases", Path("relative-cases")):
            harness.AUDIT_CASE_ROOT = bad
            with self.assertRaises(RuntimeError):
                harness.new_case("root-reject")

    @unittest.skipIf(_winapi is None or not hasattr(_winapi, "CreateJunction"), "junctions need Windows")
    def test_a_junction_case_root_is_refused(self):
        target = Path(self.tmp.name) / "elsewhere"
        target.mkdir()
        link = Path(self.tmp.name) / "linked-cases"
        _winapi.CreateJunction(str(target), str(link))
        harness.AUDIT_CASE_ROOT = link
        with self.assertRaises(RuntimeError):
            harness.new_case("root-reject")
        self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
