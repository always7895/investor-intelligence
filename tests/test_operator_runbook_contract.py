"""Command contract of docs/OPERATOR_RUNBOOK.md (project audit 2026-09-29, finding 1): verification steps are read-only
and production KV reads are remote. The sync writes objects and the pointer, so it is never a validation command."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = (ROOT / "docs" / "OPERATOR_RUNBOOK.md").read_text(encoding="utf-8")
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


class OperatorRunbookContractTests(unittest.TestCase):
    def test_every_production_kv_read_is_remote(self):
        for path in DOCS:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"wrangler\s+kv\s+key\s+get", line):
                    self.assertIn("--remote", line, f"{path.name}:{number}")

    def test_no_document_runs_the_sync_or_an_applied_rollback_as_verification(self):
        for path in DOCS:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"python\s+scripts[\\/]sync_sealed_snapshot_kv\.py\s+--run-dir", line):
                    self.fail(f"{path.name}:{number} tells the operator to run the sync")
                if re.search(r"valid|verif", line, re.I) and re.search(r"python\s+scripts[\\/]rollback_sealed_snapshot\.py[^`]*--apply", line):
                    self.assertRegex(line, r"never|not a validation", f"{path.name}:{number}")

    def test_the_post_action_validation_uses_the_read_only_tools(self):
        block = RUNBOOK[RUNBOOK.index("- Full post-action validation"):RUNBOOK.index("Escalation:")]
        self.assertIn("fetch_live_public_snapshot.py", block)
        self.assertIn("stage_sealed_replay.py", block)
        self.assertIn("never run `sync_sealed_snapshot_kv.py`", block)

    def test_object_counts_come_from_the_run(self):
        self.assertNotRegex(RUNBOOK, r"READBACK_VERIFIED 14\b|\"verified_objects\": 14\b|OBJECTS_UPLOADED 14\b")

    def test_the_named_verification_tools_are_read_only(self):
        fetch = (ROOT / "scripts" / "fetch_live_public_snapshot.py").read_text(encoding="utf-8")
        self.assertIn('"kv", "key", "get"', fetch)
        self.assertIn('"--remote"', fetch)
        self.assertNotRegex(fetch, r'"(?:put|delete)"|bulk')
        replay = (ROOT / "scripts" / "stage_sealed_replay.py").read_text(encoding="utf-8")
        self.assertNotIn("wrangler", replay)
        self.assertNotRegex(replay, r"urlopen|requests\.")


if __name__ == "__main__":
    unittest.main()
