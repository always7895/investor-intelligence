"""Regression for the release ZIP that removed activation's npm test inputs."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "relay_verifier", ROOT / "scripts/verify_v213_r75_free_relay_hotfix.py"
)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class PackagedWorkerPayloadTests(unittest.TestCase):
    def payload(self):
        paths = sorted((ROOT / "cloud/test").glob("*.ts")) + sorted(
            (ROOT / "tests/fixtures/v213-r75-publication-mode").glob("*.json")
        )
        files = {p.relative_to(ROOT).as_posix().lower():
                 (p.relative_to(ROOT).as_posix(), p.read_bytes()) for p in paths}
        refs = {"worker_test_payload": [v[0] for v in files.values()],
                "packaged_worker_test_count": 113}
        return files, refs

    def test_only_reviewed_public_skill_and_all_its_references_are_packaged(self):
        paths = ['skills/serenity-public-research/SKILL.md',
                 'skills/serenity-public-research/references/RESEARCH_METHOD.md',
                 'skills/serenity-public-research/references/CROSS_VALIDATION.md',
                 'cloud/src/v213/top20-report.ts', 'docs/CURRENT_STATUS_BILINGUAL.md']
        files = {p.casefold(): (p, (ROOT / p).read_bytes()) for p in paths}
        VERIFIER.verify_public_research_payload(files)
        for path in files:
            with self.subTest(missing=path), self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.verify_public_research_payload({k:v for k,v in files.items() if k != path})
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.verify_public_research_payload({**files, 'skills/unreviewed.md': ('skills/unreviewed.md', b'synthetic')})

    def test_complete_runtime_payload_passes(self):
        files, refs = self.payload()
        VERIFIER.verify_worker_test_payload(files, refs)

    def test_old_zip_without_tests_fails_closed(self):
        _, refs = self.payload()
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.verify_worker_test_payload({}, refs)

    def test_each_runtime_dependency_is_required(self):
        files, refs = self.payload()
        for path in files:
            with self.subTest(path=path), self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.verify_worker_test_payload(
                    {k: v for k, v in files.items() if k != path}, refs
                )

    def test_missing_fixture_cannot_be_removed_from_inventory(self):
        files, refs = self.payload()
        missing = "tests/fixtures/v213-r75-publication-mode/mixed.json"
        del files[missing]
        refs["worker_test_payload"].remove(missing)
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.verify_worker_test_payload(files, refs)

    def test_zero_or_boolean_test_count_rejected(self):
        files, refs = self.payload()
        for count in (0, -1, True, "113", None):
            with self.subTest(count=count), self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.verify_worker_test_payload(files, dict(refs, packaged_worker_test_count=count))

    def test_non_runtime_tests_rejected(self):
        files, refs = self.payload()
        extra = "tests/internal.py"
        files[extra] = (extra, b"# synthetic")
        refs["worker_test_payload"].append(extra)
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.verify_worker_test_payload(files, refs)


if __name__ == "__main__":
    unittest.main()
