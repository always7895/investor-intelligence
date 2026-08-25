from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import actions_storage_policy_gate as gate  # noqa: E402


class ActionsStoragePolicyGateTests(unittest.TestCase):
    def test_current_repository_passes(self) -> None:
        self.assertEqual(gate.audit_workflows(ROOT), [])

    def test_rejects_actions_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / ".github" / "workflows").mkdir(parents=True)
            policy = json.loads(
                (ROOT / "config" / "actions-storage-policy.json").read_text(
                    encoding="utf-8"
                )
            )
            (root / "config" / "actions-storage-policy.json").write_text(
                json.dumps(policy), encoding="utf-8"
            )
            (root / ".github" / "workflows" / "bad.yml").write_text(
                "name: bad\non: workflow_dispatch\njobs:\n  bad:\n    steps:\n"
                "      - uses: actions/cache@1111111111111111111111111111111111111111\n",
                encoding="utf-8",
            )
            findings = gate.audit_workflows(root)
            self.assertTrue(
                any("dependency cache is forbidden" in item.casefold() for item in findings)
            )

    def test_rejects_unbounded_artifact_retention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / ".github" / "workflows").mkdir(parents=True)
            policy = json.loads(
                (ROOT / "config" / "actions-storage-policy.json").read_text(
                    encoding="utf-8"
                )
            )
            (root / "config" / "actions-storage-policy.json").write_text(
                json.dumps(policy), encoding="utf-8"
            )
            (root / ".github" / "workflows" / "bad.yml").write_text(
                "name: bad\non: workflow_dispatch\njobs:\n  bad:\n    steps:\n"
                "      - name: Upload final release evidence\n"
                "        uses: actions/upload-artifact@2222222222222222222222222222222222222222\n"
                "        with:\n          retention-days: 30\n",
                encoding="utf-8",
            )
            findings = gate.audit_workflows(root)
            self.assertTrue(any("retention exceeds 1 day" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
