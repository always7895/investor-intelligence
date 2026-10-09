from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import final_release_receipt  # noqa: E402
import formal_release_status  # noqa: E402
import release_package  # noqa: E402


class FormalReleaseToolTests(unittest.TestCase):
    def test_ephemeral_status_is_exact_head_private_distribution_only(self) -> None:
        commit = "1" * 40
        value = formal_release_status.build_status(
            candidate_commit=commit,
            version="2.0.0",
        )
        self.assertFalse(value["release_ready"])
        self.assertFalse(value["package_release_ready"])
        self.assertFalse(value["public_repository_publication_ready"])
        self.assertEqual(value["distribution_scope"], "private_direct_delivery")
        self.assertEqual(value["candidate_commit"], commit)
        self.assertEqual(value["candidate_version"], "2.0.0")
        self.assertTrue(all(result == "UNVERIFIED" for result in value["gates"].values()))
        self.assertEqual(
            value["hard_blockers"], ["SOURCE_BOUND_RELEASE_EVIDENCE_REQUIRED"]
        )
        self.assertTrue(value["local_action_required"])
        self.assertFalse(value["deployed"])
        self.assertFalse(value["billing_enabled"])
        self.assertFalse(value["external_users_admitted"])
        self.assertFalse(value["secrets_required_now"])

    def test_receipt_matches_closed_final_cleanup_contract(self) -> None:
        receipt = final_release_receipt.build_receipt(
            candidate_commit="2" * 40,
            candidate_tree="3" * 40,
            version="2.0.0",
            final_package_sha256="4" * 64,
            completed_utc="2026-08-25T00:00:00Z",
            cleanup_authorized=False,
        )
        self.assertEqual(receipt["candidate_version"], "v2.0.0")
        self.assertFalse(receipt["cleanup_authorized"])
        self.assertFalse(receipt["release_ready"])
        self.assertFalse(receipt["full_history_scope_all_clean"])
        self.assertFalse(receipt["post_rewrite_fresh_clone"])
        self.assertFalse(receipt["canonical_acceptance"])
        self.assertFalse(receipt["clean_install"])
        self.assertFalse(receipt["reproducible_package"])
        self.assertFalse(receipt["sbom_manifest_checksums"])
        self.assertFalse(receipt["deployed"])
        self.assertFalse(receipt["billing_enabled"])
        self.assertFalse(receipt["external_users_admitted"])

    def test_receipt_explicit_authorization_rejected_without_evidence(self) -> None:
        with self.assertRaises(ValueError) as context:
            final_release_receipt.build_receipt(
                candidate_commit="2" * 40,
                candidate_tree="3" * 40,
                version="2.0.0",
                final_package_sha256="4" * 64,
                completed_utc="2026-08-25T00:00:00Z",
                cleanup_authorized=True,
            )
        self.assertIn(
            "SOURCE_BOUND_RELEASE_EVIDENCE_REQUIRED", str(context.exception)
        )

    def test_receipt_cli_emits_unverified_template_with_inert_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "candidate.zip"
            archive.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
            output = root / "receipt.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "final_release_receipt.py"),
                    "--archive",
                    str(archive),
                    "--version",
                    "2.0.0",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(output.is_file())
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(data["cleanup_authorized"])
            self.assertFalse(data["release_ready"])
            self.assertFalse(data["canonical_acceptance"])
            self.assertFalse(data["full_history_scope_all_clean"])
            self.assertFalse(data["post_rewrite_fresh_clone"])
            self.assertFalse(data["clean_install"])
            self.assertFalse(data["reproducible_package"])
            self.assertFalse(data["sbom_manifest_checksums"])
            self.assertFalse(data["deployed"])
            self.assertFalse(data["billing_enabled"])
            self.assertFalse(data["external_users_admitted"])

    def test_receipt_cli_authorize_cleanup_fails_closed_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "candidate.zip"
            archive.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
            output = root / "receipt.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "final_release_receipt.py"),
                    "--archive",
                    str(archive),
                    "--version",
                    "2.0.0",
                    "--output",
                    str(output),
                    "--authorize-cleanup",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(output.exists())
            self.assertIn("SOURCE_BOUND_RELEASE_EVIDENCE_REQUIRED", proc.stdout)

    def test_non_synthetic_package_fails_closed_without_release_evidence(self) -> None:
        head = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
        ).strip()
        status = formal_release_status.build_status(
            candidate_commit=head,
            version="2.0.0-test.1",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status_path = root / "status.json"
            status_path.write_text(
                json.dumps(status, sort_keys=True),
                encoding="utf-8",
            )
            package_dir = root / "package"
            with self.assertRaises(release_package.ReleasePackageError) as context:
                release_package.build_release_package(
                    output_dir=package_dir,
                    version="2.0.0-test.1",
                    synthetic=False,
                    release_status_path=status_path,
                )
            self.assertIn("release_ready", str(context.exception))
            if package_dir.is_dir():
                self.assertFalse(list(package_dir.glob("*.zip")))

    def test_invalid_status_and_receipt_identities_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            formal_release_status.build_status(candidate_commit="short", version="2.0.0")
        with self.assertRaises(ValueError):
            final_release_receipt.build_receipt(
                candidate_commit="2" * 40,
                candidate_tree="3" * 40,
                version="v2.0.0",
                final_package_sha256="4" * 64,
                completed_utc="2026-08-25T00:00:00Z",
                cleanup_authorized=False,
            )

    def test_release_ready_is_false_without_evidence(self) -> None:
        # No evidence is supplied to build_status, so release_ready must be False.
        value = formal_release_status.build_status(
            candidate_commit="0" * 40,
            version="99.0.0",
        )
        self.assertFalse(value["release_ready"])
        self.assertFalse(value["package_release_ready"])
        self.assertTrue(all(result == "UNVERIFIED" for result in value["gates"].values()))
        self.assertEqual(
            value["hard_blockers"], ["SOURCE_BOUND_RELEASE_EVIDENCE_REQUIRED"]
        )
        self.assertTrue(value["local_action_required"])


if __name__ == "__main__":
    unittest.main()
