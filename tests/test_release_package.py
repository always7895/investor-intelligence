from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clean_install_gate_policy import (  # noqa: E402
    PACKAGE_COMPATIBLE_GATE_SCRIPTS,
    REPOSITORY_ONLY_GATE_SCRIPTS,
)
from release_package import ReleasePackageError, build_release_package  # noqa: E402
from verify_release_package import (  # noqa: E402
    ReleaseVerificationError,
    verify_release_package,
)


class ReleasePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.first = build_release_package(
            root=ROOT,
            output_dir=cls.root / "first",
            version="0.0.0-dev.package-test",
            synthetic=True,
        )
        cls.second = build_release_package(
            root=ROOT,
            output_dir=cls.root / "second",
            version="0.0.0-dev.package-test",
            synthetic=True,
        )
        cls.policy = ROOT / "config" / "release-package-policy.json"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def verify(self, archive: Path, checksum: Path, manifest: Path, sbom: Path):
        return verify_release_package(
            archive_path=archive,
            checksum_path=checksum,
            manifest_path=manifest,
            sbom_path=sbom,
            policy_path=self.policy,
        )

    def test_valid_synthetic_package_verifies_without_secrets_or_owner_files(self) -> None:
        summary = self.verify(
            self.first.archive,
            self.first.checksum,
            self.first.manifest,
            self.first.sbom,
        )
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["build_mode"], "synthetic_validation")
        manifest = json.loads(self.first.manifest.read_text(encoding="utf-8"))
        paths = {value["path"] for value in manifest["files"]}
        self.assertNotIn("config/watchlist.json", paths)
        self.assertNotIn("config/user-preferences.json", paths)
        self.assertFalse(any("node_modules" in path for path in paths))
        self.assertFalse(any(path.startswith("data/") for path in paths))
        self.assertFalse(any(path.startswith("reports/") for path in paths))
        self.assertFalse(any(path.startswith(".github/") for path in paths))
        self.assertIn("scripts/clean_install_gate_policy.py", paths)

    def test_repository_only_gates_are_not_reexecuted_in_reduced_package_context(self) -> None:
        self.assertIn("scripts/line_public_boundary_gate.py", REPOSITORY_ONLY_GATE_SCRIPTS)
        self.assertIn("scripts/workflow_supply_chain_gate.py", REPOSITORY_ONLY_GATE_SCRIPTS)
        self.assertIn("scripts/full_history_privacy_scan.py", REPOSITORY_ONLY_GATE_SCRIPTS)
        self.assertNotIn("scripts/line_public_boundary_gate.py", PACKAGE_COMPATIBLE_GATE_SCRIPTS)
        self.assertTrue(
            set(PACKAGE_COMPATIBLE_GATE_SCRIPTS).isdisjoint(REPOSITORY_ONLY_GATE_SCRIPTS)
        )

    def test_two_builds_from_one_commit_are_byte_reproducible(self) -> None:
        self.assertEqual(self.first.archive.read_bytes(), self.second.archive.read_bytes())
        self.assertEqual(self.first.manifest.read_bytes(), self.second.manifest.read_bytes())
        self.assertEqual(self.first.sbom.read_bytes(), self.second.sbom.read_bytes())
        self.assertEqual(self.first.archive_sha256, self.second.archive_sha256)

    def test_rejects_checksum_mismatch(self) -> None:
        checksum = self.root / "bad.sha256"
        checksum.write_text(f"{'0' * 64}  {self.first.archive.name}\n", encoding="ascii")
        with self.assertRaises(ReleaseVerificationError):
            self.verify(
                self.first.archive,
                checksum,
                self.first.manifest,
                self.first.sbom,
            )

    def test_rejects_external_manifest_mismatch(self) -> None:
        manifest = json.loads(self.first.manifest.read_text(encoding="utf-8"))
        manifest["files"][0]["sha256"] = "0" * 64
        path = self.root / "bad.manifest.json"
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(ReleaseVerificationError):
            self.verify(self.first.archive, self.first.checksum, path, self.first.sbom)

    def test_rejects_external_sbom_mismatch(self) -> None:
        sbom = json.loads(self.first.sbom.read_text(encoding="utf-8"))
        sbom["files"][0]["checksums"][0]["checksumValue"] = "0" * 64
        path = self.root / "bad.sbom.json"
        path.write_text(
            json.dumps(sbom, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(ReleaseVerificationError):
            self.verify(self.first.archive, self.first.checksum, self.first.manifest, path)

    def test_rejects_extra_zip_entry_even_with_recomputed_outer_checksum(self) -> None:
        archive = self.root / self.first.archive.name
        shutil.copy2(self.first.archive, archive)
        with zipfile.ZipFile(archive, "a", compression=zipfile.ZIP_DEFLATED) as handle:
            handle.writestr("unexpected.txt", b"unexpected")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum = self.root / "recomputed.sha256"
        checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
        with self.assertRaises(ReleaseVerificationError):
            self.verify(archive, checksum, self.first.manifest, self.first.sbom)

    def test_final_package_is_rejected_while_release_status_is_pending(self) -> None:
        with self.assertRaises(ReleasePackageError):
            build_release_package(
                root=ROOT,
                output_dir=self.root / "final-rejected",
                version="1.0.0",
                synthetic=False,
            )


if __name__ == "__main__":
    unittest.main()
