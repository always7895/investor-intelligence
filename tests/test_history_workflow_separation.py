from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / ".github" / "workflows" / "full-history-privacy-inventory.yml"
FINAL_CLEAN = ROOT / ".github" / "workflows" / "full-history-clean-release-gate.yml"


def scanner_invocations(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if "scripts/full_history_privacy_scan.py" in line
        and not line.lstrip().startswith("#")
    ]


class HistoryWorkflowSeparationTests(unittest.TestCase):
    def test_non_destructive_inventory_scans_exact_candidate_ancestry(self) -> None:
        text = INVENTORY.read_text(encoding="utf-8")
        invocations = scanner_invocations(text)
        self.assertEqual(len(invocations), 1)
        self.assertIn(
            "scripts/full_history_privacy_scan.py --scope head --json-output",
            invocations[0],
        )
        self.assertNotIn("--require-clean", invocations[0])
        self.assertIn("complete ancestry reachable from the exact candidate head", text)
        self.assertIn("Final release gate: remains PENDING", text)
        self.assertIn("History rewrite/force-push performed: no", text)

    def test_final_manual_gate_is_the_only_workflow_that_requires_clean(self) -> None:
        text = FINAL_CLEAN.read_text(encoding="utf-8")
        invocations = scanner_invocations(text)
        self.assertEqual(len(invocations), 1)
        self.assertIn("--scope all --require-clean --json-output", invocations[0])
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("candidate_sha:", text)
        self.assertNotIn("push:", text)
        self.assertNotIn("pull_request:", text)

    def test_both_history_workflows_are_read_only_and_exact_sha_bound(self) -> None:
        for path in (INVENTORY, FINAL_CLEAN):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("contents: read", text)
                self.assertNotIn("contents: write", text)
                self.assertIn("persist-credentials: false", text)
                self.assertIn("TARGET_SHA", text)
                self.assertNotIn("git push", text)
                self.assertNotIn("git commit", text)


if __name__ == "__main__":
    unittest.main()
