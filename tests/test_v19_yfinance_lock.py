"""Lane V19 A4: the CI lock carries yfinance 1.7.0 and its one new dependency, lxml, hash-pinned (operator 2026-10-19)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s]+) --hash=sha256:([0-9a-f]{64})$")


def lock_pins() -> dict[str, tuple[str, str]]:
    pins = {}
    for line in (ROOT / "requirements-ci.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        m = PIN.match(line)
        if m is None:
            raise AssertionError(f"unhashed or malformed lock line: {line[:60]}")
        pins[m.group(1).lower()] = (m.group(2), m.group(3))
    return pins


class YfinanceLockTests(unittest.TestCase):
    def test_every_lock_line_is_exact_and_hashed(self):
        pins = lock_pins()
        self.assertGreaterEqual(len(pins), 20)

    def test_direct_inputs_agree_with_the_lock(self):
        pins = lock_pins()
        direct = [line for line in (ROOT / "requirements-ci.in").read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")]
        for line in direct:
            name, version = line.split("==")
            self.assertEqual(pins[name.lower()][0], version, name)
        self.assertIn("yfinance==1.7.0", direct)

    def test_yfinance_170_and_its_new_lxml_dependency_are_pinned(self):
        pins = lock_pins()
        self.assertEqual(pins["yfinance"], ("1.7.0", "91281ecd1f71069a37155ff8653aff2d3085f3492bd8721f18b70955da62911a"))
        self.assertEqual(pins["lxml"][0], "6.1.3")


if __name__ == "__main__":
    unittest.main()
