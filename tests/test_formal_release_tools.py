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
            cleanup_authorized=True,
        )
        self.assertEqual(receipt["candidate_version"], "v2.0.0")
        self.assertTrue(receipt["cleanup_authorized"])
        self.assertTrue(receipt["release_ready"])
        self.assertTrue(receipt["full_history_scope_all_clean"])
        self.assertTrue(receipt["post_rewrite_fresh_clone"])
        self.assertTrue(receipt["clean_install"])
        self.assertFalse(receipt["deployed"])
        self.assertFalse(receipt["billing_enabled"])
        self.assertFalse(receipt["external_users_admitted"])

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
                cleanup_authorized=True,
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
