"""Synthetic fixture mechanics only; no public research or native authority."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import company_evidence_test_corpus as corpus


class SyntheticCorpusTests(unittest.TestCase):
    def test_deterministic_byte_bindings_and_nonadmitted_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            left, right = Path(tmp)/"left", Path(tmp)/"right"
            left.mkdir(); right.mkdir()
            manifest, proposals = corpus.build_corpus(left)
            corpus.build_corpus(right)
            contents = lambda root: {p.name:p.read_bytes() for p in root.iterdir()}
            self.assertEqual(contents(left), contents(right))
            self.assertEqual(len(contents(left)), 7)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["record_count"], 4); self.assertEqual(len(data["sources"]), 4)
            self.assertEqual(data["scope"], "PUBLIC_RESEARCH_INPUT_NOT_ADMITTED")
            for entry in data["sources"]:
                raw = (left/entry["text_file"]).read_bytes()
                self.assertTrue(raw.startswith(corpus.MARKER.encode()))
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["text_sha256"])
                self.assertEqual(len(raw), entry["text_bytes"])
                self.assertTrue(entry["source_url"].startswith("https://example.com/synthetic/"))
                self.assertEqual(entry["rights"], "NOT_REVIEWED"); self.assertIs(entry["runtime_admitted"], False)
            for entry in data["source_receipts"]:
                raw = (left/entry["file"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
                receipt = json.loads(raw)
                self.assertIs(receipt["synthetic_fixture"], True)
                self.assertIs(receipt["runtime_admitted"], False)
                self.assertEqual(receipt["purpose"], corpus.MARKER)
            self.assertEqual(len(json.loads(proposals.read_text(encoding="utf-8"))["proposals"]), 2)

    def test_exclusive_refusal_and_independent_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/"a", Path(tmp)/"b"; a.mkdir(); b.mkdir()
            corpus.build_corpus(a)
            original = {p.name:p.read_bytes() for p in a.iterdir()}
            with self.assertRaisesRegex(ValueError, "EMPTY_FIXTURE_DIR_REQUIRED"):
                corpus.build_corpus(a)
            self.assertEqual({p.name:p.read_bytes() for p in a.iterdir()}, original)
            (a/"hitachi-fy2025-results.md").write_bytes(b"SYNTHETIC_MUTATION")
            corpus.build_corpus(b)
            self.assertEqual({p.name:p.read_bytes() for p in b.iterdir()}, original)

    def test_import_does_not_write_fixture_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run([sys.executable, "-B", "-c", "import runpy,sys;runpy.run_path(sys.argv[1])", str(Path(corpus.__file__).resolve())], cwd=tmp, capture_output=True, timeout=20)
            self.assertEqual(run.returncode, 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            self.assertEqual(run.stdout, b""); self.assertEqual(run.stderr, b"")


if __name__ == "__main__":
    unittest.main()
