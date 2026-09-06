"""Run the Pi adapter's SDK-caller/negative contract tests without model/network."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PiInferenceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for Pi adapter tests')
    def test_node_contracts(self):
        result = subprocess.run([shutil.which('node'), '--test', 'tests/v213_pi_inference.test.mjs'],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == '__main__':
    unittest.main()
