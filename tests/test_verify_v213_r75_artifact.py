from __future__ import annotations

import hashlib
import json
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_v213_r75_artifact import R75ArtifactError, verify_r75_artifact  # noqa: E402


class R75ArtifactVerifierTests(unittest.TestCase):
    SHA = "1" * 40
    RUN = "12345"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @property
    def name(self) -> str:
        return f"Investor-Intelligence-v2.1.3-R75-{self.SHA}-{self.RUN}.zip"

    @staticmethod
    def sha(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def build(self, extras: list[tuple[zipfile.ZipInfo | str, bytes]] | None = None) -> tuple[Path, Path]:
        contract = b'{"contract":"test"}\n'
        files = {
            "VERSION-REFS.json": b"",
            "InvestorIntelligence.exe": b"MZsynthetic-pe",
            "config/v213-r75-publication-mode-v1.json": contract,
            "scripts/v213_r75_activation_preflight.py": b"# test\n",
            "cloud/src/v213/publication-mode.ts": b"// test\n",
            "cloud/src/v213/activation-v2.ts": b"// test\n",
            "SBOM.spdx.json": (json.dumps({
                "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0",
                "SPDXID": "SPDXRef-DOCUMENT",
                "documentNamespace": f"https://example.invalid/spdx/R75/{self.SHA}/{self.RUN}",
                "packages": [{"versionInfo": "2.1.3-R75"}],
            }) + "\n").encode(),
        }
        version = {
            "release": "R75",
            "package_version": "2.1.3",
            "source_commit": self.SHA,
            "workflow_run_id": self.RUN,
            "publication_contract_sha256": self.sha(contract),
            "production_mutation_by_ci": False,
            "known_p0_count": 0,
            "public_package_excludes_internal_evidence": True,
        }
        files["VERSION-REFS.json"] = (json.dumps(version) + "\n").encode()
        manifest = {
            "schema_version": 1,
            "release": "R75",
            "source_commit": self.SHA,
            "workflow_run_id": self.RUN,
            "production_mutation_by_ci": False,
            "files": [
                {"path": name, "bytes": len(data), "sha256": self.sha(data)}
                for name, data in sorted(files.items())
            ],
        }
        manifest_bytes = (json.dumps(manifest) + "\n").encode()
        files["MANIFEST.json"] = manifest_bytes
        sums = "".join(f"{self.sha(data)}  {name}\n" for name, data in sorted(files.items())).encode("ascii")
        files["SHA256SUMS.txt"] = sums
        archive = self.root / self.name
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
            for name, data in files.items():
                handle.writestr(name, data)
            for name, data in extras or []:
                handle.writestr(name, data)
        checksum = self.root / f"{self.name}.sha256"
        checksum.write_text(f"{self.sha(archive.read_bytes())}  {self.name}\n", encoding="ascii")
        return archive, checksum

    def test_valid_archive_passes_complete_integrity_contract(self) -> None:
        archive, checksum = self.build()
        result = verify_r75_artifact(archive, checksum, source_commit=self.SHA, run_id=self.RUN)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["release_marker"], "R75")
        self.assertFalse(result["production_mutation_by_ci"])

    def test_outer_checksum_mismatch_fails_closed(self) -> None:
        archive, checksum = self.build()
        checksum.write_text(f"{'0' * 64}  {self.name}\n", encoding="ascii")
        with self.assertRaises(R75ArtifactError):
            verify_r75_artifact(archive, checksum, source_commit=self.SHA, run_id=self.RUN)

    def test_traversal_and_case_collision_fail_before_manifest_acceptance(self) -> None:
        archive, checksum = self.build([("../escape.txt", b"x")])
        with self.assertRaises(R75ArtifactError):
            verify_r75_artifact(archive, checksum, source_commit=self.SHA, run_id=self.RUN)
        archive, checksum = self.build([("version-refs.json", b"duplicate")])
        with self.assertRaises(R75ArtifactError):
            verify_r75_artifact(archive, checksum, source_commit=self.SHA, run_id=self.RUN)

    def test_symbolic_link_entry_fails_closed(self) -> None:
        link = zipfile.ZipInfo("unsafe-link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive, checksum = self.build([(link, b"target")])
        with self.assertRaises(R75ArtifactError):
            verify_r75_artifact(archive, checksum, source_commit=self.SHA, run_id=self.RUN)


if __name__ == "__main__":
    unittest.main()
