from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import final_cleanup_gate as module  # noqa: E402


class FinalCleanupGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads(
            (ROOT / "config" / "final-cleanup-policy.json").read_text(encoding="utf-8")
        )
        self.candidate = "a" * 40
        self.receipt = {
            "schema_version": 1,
            "candidate_commit": self.candidate,
            "candidate_tree": "b" * 40,
            "candidate_version": "v1.0.0",
            "completed_utc": "2026-08-25T10:00:00Z",
            "cleanup_authorized": True,
            "release_ready": True,
            "deployed": False,
            "billing_enabled": False,
            "external_users_admitted": False,
            "post_rewrite_fresh_clone": True,
            "full_history_scope_all_clean": True,
            "canonical_acceptance": True,
            "clean_install": True,
            "reproducible_package": True,
            "sbom_manifest_checksums": True,
            "final_package_sha256": "c" * 64,
        }

    def test_current_policy_is_valid_and_fail_closed(self) -> None:
        self.assertEqual(module.audit_policy(self.policy), [])
        self.assertEqual(
            self.policy["policy_state"], "LOCKED_UNTIL_FINAL_RECEIPT"
        )
        self.assertFalse(self.policy["automatic_cleanup"])
        self.assertFalse(self.policy["destructive_apply_default"])

    def test_retained_gate_has_no_destructive_implementation(self) -> None:
        source = (ROOT / "scripts" / "final_cleanup_gate.py").read_text(
            encoding="utf-8"
        )
        for primitive in (
            "shutil.rmtree(",
            ".unlink(",
            "os.remove(",
            "Remove-Item",
            "git push",
            "delete_ref",
        ):
            with self.subTest(primitive=primitive):
                self.assertNotIn(primitive, source)

    def test_complete_exact_receipt_unlocks_validation_only(self) -> None:
        self.assertEqual(
            module.audit_receipt(
                self.receipt,
                self.policy,
                expected_candidate=self.candidate,
            ),
            [],
        )

    def test_incomplete_or_deployed_receipt_fails_closed(self) -> None:
        receipt = copy.deepcopy(self.receipt)
        receipt["full_history_scope_all_clean"] = False
        receipt["deployed"] = True
        findings = module.audit_receipt(receipt, self.policy)
        self.assertTrue(
            any("full_history_scope_all_clean" in finding for finding in findings)
        )
        self.assertTrue(any("deployed" in finding for finding in findings))

    def test_receipt_must_bind_to_exact_candidate(self) -> None:
        findings = module.audit_receipt(
            self.receipt,
            self.policy,
            expected_candidate="d" * 40,
        )
        self.assertTrue(any("expected candidate" in finding for finding in findings))

    def test_repository_cleanup_cannot_escape_reviewed_allowlist(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["repository_cleanup"]["allowed_relative_directories"][0] = (
            "../outside"
        )
        findings = module.audit_policy(policy)
        self.assertTrue(any("unsafe" in finding for finding in findings))
        self.assertTrue(any("allowlist changed" in finding for finding in findings))

    def test_at_least_one_verified_rollback_bundle_is_always_retained(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["backup_cleanup"]["minimum_verified_backups_to_keep"] = 0
        findings = module.audit_policy(policy)
        self.assertTrue(any("at least one verified backup" in finding for finding in findings))

    def test_github_managed_pull_refs_are_never_a_cleanup_target(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["git_cleanup"]["github_managed_pull_refs_are_read_only"] = False
        findings = module.audit_policy(policy)
        self.assertTrue(any("github_managed_pull_refs" in finding for finding in findings))


if __name__ == "__main__":
    unittest.main()
