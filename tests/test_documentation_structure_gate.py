from __future__ import annotations

import hashlib
import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('doc_structure', ROOT / 'scripts/documentation_structure_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class DocumentationStructureTests(unittest.TestCase):
    def test_actual_repository_and_cli(self):
        findings, stats = gate.audit(ROOT)
        self.assertEqual(findings, [])
        self.assertGreaterEqual(stats['markdown_files'], 80)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/documentation_structure_gate.py')],
                                cwd=ROOT, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('PASSED', result.stdout)

    def test_local_paths_reference_links_images_and_code_fences(self):
        text = '''[page](guide.md#title) ![image](image.png)
[reference]: ../README.md "title"
`[sample](not-a-link.md)`
```md
[example](also-not-a-link.md)
```
~~~text
[example](not-a-link-either.md)
~~~
'''
        self.assertEqual(gate.link_targets(text), ['guide.md#title', 'image.png', '../README.md'])
        self.assertIsNone(gate.local_target(ROOT, 'docs/README.md', 'https://example.org/reference'))
        self.assertIsNone(gate.local_target(ROOT, 'docs/README.md', '#same-page'))
        for value in ('../../outside.md', '../../%6futside.md', '../_workspace/evidence.md',
                      'file:///outside.md', '..\\outside.md'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gate.local_target(ROOT, 'docs/README.md', value)

    def test_new_untracked_docs_broken_link_and_budget_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'docs').mkdir()
            (root / 'docs/README.md').write_text('[guide](guide.md)\n', encoding='utf-8')
            (root / 'docs/guide.md').write_text('# Guide\n[missing](missing.md)\n', encoding='utf-8')
            (root / 'new.md').write_text('# New\n', encoding='utf-8')
            with patch.object(gate, 'BUDGETS', {'docs/guide.md': 5}):
                findings, stats = gate.audit(root)
            self.assertEqual(stats['markdown_files'], 3)
            self.assertTrue(any('missing local file' in item for item in findings))
            self.assertTrue(any('exceeds 5' in item for item in findings))
            self.assertTrue(any('new.md: not linked' in item for item in findings))

    def test_git_unavailable_never_falls_back_to_recursive_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.CalledProcessError):
                gate.audit(Path(directory))

    def test_existing_r75_caller_runs_documentation_before_unit_suite(self):
        text = (ROOT / 'scripts/ci_v213_r75_validate.ps1').read_text(encoding='utf-8')
        for name in ('documentation_boundary_gate.py', 'documentation_structure_gate.py'):
            self.assertLess(text.index(name), text.index('-m unittest discover'))

    def test_windows_and_r75_assert_same_committed_worker_lock(self):
        expected = hashlib.sha256((ROOT / 'cloud/package-lock.json').read_bytes()).hexdigest()
        workflow = (ROOT / '.github/workflows/windows-local-validation.yml').read_text(encoding='utf-8')
        self.assertEqual(re.search(r"EXPECTED_WORKER_LOCK_SHA256: '([a-f0-9]{64})'", workflow)[1], expected)
        r75 = (ROOT / 'scripts/ci_v213_r75_validate.ps1').read_text(encoding='utf-8')
        self.assertIn(f"$lock -ne '{expected}'", r75)


if __name__ == '__main__':
    unittest.main()
