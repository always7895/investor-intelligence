"""Synthetic grammar fixture isolation/integrity, not statutory authority."""
import ast
import hashlib
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "carb-parser-synthetic.txt"
SHA256 = "a9de16a4ea23865434a6e5f107a416b9399a80f5912c1a37862428b883e3ba29"
CONSUMERS = (
    ("test_carb_statutory_citations", "RETAINED_CORPUS_PATH", ("TestCarbStatutoryCitations",)),
    ("test_statutory_authority_resolution", "RETAINED_CORPUS", ("TestStatutoryAuthorityResolution",)),
    ("test_carb_typed_section_parser", "FIXTURE_PATH", ("TestCarbParserPositiveFixture", "TestCarbParserNegativeMutations", "TestCarbParserTypeSafety")),
)


class CarbFixtureBoundaryTests(unittest.TestCase):
    def test_fixture_bytes_and_all_consumer_paths_are_local(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), SHA256)
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertTrue(raw.decode("utf-8").startswith("SYNTHETIC TEST FIXTURE - NOT REAL LEGAL OR PUBLIC RESEARCH EVIDENCE\n"))
        root = Path(__file__).resolve().parent
        for name, attribute, _ in CONSUMERS:
            with self.subTest(consumer=name):
                module = importlib.import_module(name)
                self.assertTrue(Path(module.__file__).resolve().is_relative_to(root))
                self.assertEqual(getattr(module, attribute).resolve(), FIXTURE.resolve())

    def test_missing_fixture_fails_in_every_dependent_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-synthetic-fixture.txt"
            self.assertFalse(missing.exists())
            for name, attribute, classes in CONSUMERS:
                module = importlib.import_module(name)
                with mock.patch.object(module, attribute, missing):
                    for class_name in classes:
                        with self.subTest(consumer=name, fixture_class=class_name):
                            with self.assertRaisesRegex(FileNotFoundError, "SYNTHETIC_FIXTURE_MISSING"):
                                getattr(module, class_name).setUpClass()

    def test_no_skip_or_external_audit_fallback_in_consumers(self):
        for name, _, _ in CONSUMERS:
            with self.subTest(consumer=name):
                module = importlib.import_module(name)
                text = Path(module.__file__).read_text(encoding="utf-8")
                self.assertNotIn("audit-runtime", text)
                self.assertNotIn("D:/", text)
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        self.assertNotEqual(node.attr, "SkipTest")


if __name__ == "__main__":
    unittest.main()
