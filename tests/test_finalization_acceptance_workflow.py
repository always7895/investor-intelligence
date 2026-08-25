from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "final-release-candidate-v3-pre-rewrite-audit.yml"
)


class FinalizationAcceptanceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_is_read_only_and_exact_finalization_branch_bound(self) -> None:
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertIn("branches:\n      - main", self.text)
        self.assertIn(
            "github.event.pull_request.head.ref == 'integration/final-release-candidate-v3'",
            self.text,
        )
        self.assertIn("ref: ${{ env.TARGET_SHA }}", self.text)
        self.assertIn("fetch-depth: 0", self.text)
        self.assertIn("persist-credentials: false", self.text)
        for forbidden in (
            "contents: write",
            "persist-credentials: true",
            "git push",
            "git commit",
            "wrangler deploy",
            "upload-artifact",
            "delete_ref",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.text)

    def test_all_finalization_boundaries_run_on_one_exact_head(self) -> None:
        required = (
            "scripts/security_check.py",
            "scripts/owner_config_boundary_gate.py",
            "scripts/line_public_boundary_gate.py",
            "scripts/documentation_boundary_gate.py",
            "scripts/kv_namespace_isolation_gate.py",
            "scripts/authoritative_adapter_gate.py",
            "scripts/authoritative_source_catalog.py",
            "scripts/source_claim_coverage_gate.py",
            "scripts/source_diversity_gate.py",
            "scripts/public_options_provider_gate.py",
            "scripts/final_cleanup_gate.py",
            "scripts/release_candidate_gate.py",
            "scripts/canonical_release_candidate_gate_v2.py",
            "scripts/schedule_planner.py",
            "scripts/phase8_fault_injection_gate.py",
            "scripts/full_history_privacy_scan.py --scope head",
            "-m unittest discover -s tests -p 'test_*.py' -v",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_supply_chain_and_clean_install_are_explicit(self) -> None:
        self.assertIn("--require-hashes -r requirements-ci.txt", self.text)
        self.assertIn("-m pip check", self.text)
        self.assertIn("ci --ignore-scripts --no-audit --no-fund", self.text)
        self.assertIn("scripts/release_package.py", self.text)
        self.assertIn("verify_release_package.py", self.text)
        self.assertIn("clean_install_acceptance.py", self.text)
        self.assertIn("empty-npm-cache", self.text)
        self.assertIn("distinct verified Python root", self.text)

    def test_pre_rewrite_inventory_does_not_claim_clean_history(self) -> None:
        self.assertIn("--scope head --json-output", self.text)
        self.assertNotIn("--scope head --require-clean", self.text)
        self.assertIn("Pre-rewrite history clean", self.text)
        self.assertIn("Final cleanup: locked", self.text)
        self.assertIn(
            "Final release: remains blocked until backup-first history remediation and post-rewrite fresh-clone acceptance",
            self.text,
        )
        self.assertIn(
            "Public-options licensing boundary: PASS; live shared quotes remain fail-closed",
            self.text,
        )

    def test_all_external_capabilities_are_disabled(self) -> None:
        for marker in (
            "DELIVERY_ENABLED: 'false'",
            "LINE_ENABLED: 'false'",
            "LINE_PUSH_ENABLED: 'false'",
            "CURRENT_PUBLIC_DATA_ENABLED: 'false'",
            "PUBLIC_KV_SYNC_ENABLED: 'false'",
            "CLOUD_INFERENCE_ENABLED: 'false'",
            "IBKR_READONLY_ENABLED: 'false'",
            "FREE_ONLY_MODE: 'true'",
            "PAID_FALLBACK_ENABLED: 'false'",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)


if __name__ == "__main__":
    unittest.main()
