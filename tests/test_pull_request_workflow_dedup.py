from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PR_ACCEPTANCE_WORKFLOWS = (
    ".github/workflows/line-kv-isolation-audit.yml",
    ".github/workflows/phase4-public-briefing-audit.yml",
    ".github/workflows/phase7-schedule-recovery-audit.yml",
    ".github/workflows/phase8-fault-injection-audit.yml",
    ".github/workflows/release-candidate-truth-audit.yml",
    ".github/workflows/full-history-privacy-inventory.yml",
)

CANONICAL_WORKFLOW = (
    ROOT / ".github" / "workflows" / "canonical-release-candidate-audit-v2.yml"
)


def trigger_header(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if "\npermissions:\n" not in text:
        raise AssertionError(f"{path.name}: permissions boundary is missing")
    return text.split("\npermissions:\n", 1)[0]


class PullRequestWorkflowDedupTests(unittest.TestCase):
    def test_pr_acceptance_workflows_do_not_duplicate_feature_branch_pushes(self) -> None:
        for relative in PR_ACCEPTANCE_WORKFLOWS:
            with self.subTest(workflow=relative):
                header = trigger_header(ROOT / relative)
                self.assertIn("\n  workflow_dispatch:\n", header)
                self.assertIn("\n  pull_request:\n", header)
                self.assertIn(
                    "      - reconcile/phase3-authoritative-sources-v1",
                    header,
                )
                self.assertNotIn("\n  push:\n", header)

    def test_historical_canonical_workflow_retains_legacy_branch_only(self) -> None:
        header = trigger_header(CANONICAL_WORKFLOW)
        self.assertIn("\n  workflow_dispatch:\n", header)
        self.assertIn("\n  push:\n", header)
        self.assertIn("      - hardening/line-kv-isolation-v1", header)
        self.assertNotIn("\n  pull_request:\n", header)
        self.assertNotIn(
            "      - reconcile/phase3-authoritative-sources-v1",
            header,
        )

    def test_obsolete_main_pr_audits_do_not_duplicate_r75_acceptance(self) -> None:
        for name in ("phase-audit.yml", "phase5-line-bot-audit.yml", "canonical-release-candidate-audit-v2.yml"):
            with self.subTest(workflow=name):
                header = trigger_header(ROOT / ".github/workflows" / name)
                self.assertIn("\n  workflow_dispatch:\n", header)
                self.assertNotIn("\n  pull_request:\n", header)
                self.assertNotIn("\n  workflow_run:\n", header)
        current = (ROOT / ".github/workflows/v213-r75-release.yml").read_text(encoding="utf-8")
        self.assertIn("'pi/**'", trigger_header(ROOT / ".github/workflows/v213-r75-release.yml"))
        self.assertIn("runs-on: [self-hosted, Windows, X64, investor-intelligence-reviewed]", current)
        self.assertIn("LINE_PUSH_ENABLED: 'false'", current)


if __name__ == "__main__":
    unittest.main()
