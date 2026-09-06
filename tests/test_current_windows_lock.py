"""Current automatic Windows CI must verify the actual committed lock bytes."""
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CurrentWindowsLockTests(unittest.TestCase):
    def test_current_workflow_pin_matches_lock(self):
        text = (ROOT / '.github/workflows/windows-local-validation.yml').read_text(encoding='utf-8')
        pin = re.search(r"EXPECTED_WORKER_LOCK_SHA256: '([a-f0-9]{64})'", text)
        self.assertIsNotNone(pin)
        self.assertEqual(pin.group(1), hashlib.sha256((ROOT / 'cloud/package-lock.json').read_bytes()).hexdigest())
        self.assertIn('if ($actual -ne $env:EXPECTED_WORKER_LOCK_SHA256)', text)
        self.assertIn('ci --ignore-scripts --no-audit --no-fund', text)

if __name__ == '__main__':
    unittest.main()
