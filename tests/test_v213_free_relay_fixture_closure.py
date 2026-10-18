"""R75 FREE_RELAY packaging keeps every tests/fixtures JSON the Worker tests read.

Static source inspection only: no packaging, ZIP, npm or subprocess run. The
packager prunes tests/ and restores exactly $alwaysFixtures (plus the wire
pair); an omitted fixture makes the extracted-ZIP npm test fail at module load.
"""
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "relay_verifier_closure", ROOT / "scripts/verify_v213_r75_free_relay_hotfix.py"
)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
REFERENCE = re.compile(r"tests/fixtures/[A-Za-z0-9._/-]+\.json")


class FreeRelayFixtureClosure(unittest.TestCase):
    def test_every_worker_test_fixture_is_packaged(self):
        referenced = {}
        for path in sorted((ROOT / "cloud/test").rglob("*.ts")):
            for name in REFERENCE.findall(path.read_text(encoding="utf-8")):
                referenced.setdefault(name, path.relative_to(ROOT).as_posix())
        # Non-vacuous scan: the frozen NBIS machine fixture is a module-level read.
        self.assertIn("tests/fixtures/revenue-guidance-machine-nbis-auto-functional.json", referenced)
        packaged = set(VERIFIER.ALWAYS_FIXTURES) | {VERIFIER.WIRE_FIXTURE}
        self.assertEqual({name: where for name, where in referenced.items() if name not in packaged}, {})
        for name in referenced:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_packager_restores_exactly_the_verifier_fixtures(self):
        text = (ROOT / "scripts/ci_v213_r75_free_relay_package.ps1").read_text(encoding="utf-8")
        block = re.search(r"\$alwaysFixtures = @\((.*?)\n    \)", text, re.S)
        self.assertIsNotNone(block)
        listed = re.findall(r"'([^']+)'", block.group(1))
        self.assertEqual(len(set(listed)), len(listed))
        self.assertEqual(sorted(listed), sorted(VERIFIER.ALWAYS_FIXTURES))
        self.assertIn(f"$wireTest = '{VERIFIER.WIRE_TEST}'; $wireFixture = '{VERIFIER.WIRE_FIXTURE}'", text)
        self.assertIn(f"(the {len(listed)} always-required test fixtures, plus the", text)


if __name__ == "__main__":
    unittest.main()
