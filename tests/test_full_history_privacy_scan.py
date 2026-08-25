from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from full_history_privacy_scan import scan_history  # noqa: E402


def git(root: Path, *arguments: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout)
    return completed.stdout.strip()


class FullHistoryPrivacyScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Synthetic Tester")
        git(self.repo, "config", "user.email", "tester@example.test")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def commit(self, message: str, *, email: str = "tester@example.test") -> None:
        environment = dict(os.environ)
        environment.update(
            {
                "GIT_AUTHOR_NAME": "Synthetic Tester",
                "GIT_AUTHOR_EMAIL": email,
                "GIT_COMMITTER_NAME": "Synthetic Tester",
                "GIT_COMMITTER_EMAIL": email,
            }
        )
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message, env=environment)

    def test_clean_candidate_history_reports_no_raw_identifiers(self) -> None:
        (self.repo / "README.md").write_text(
            "API_KEY=EXAMPLE_RUNTIME_VALUE_NOT_REAL\ncontact=person@example.test\n",
            encoding="utf-8",
        )
        self.commit("safe synthetic commit")
        report = scan_history(self.repo)
        self.assertTrue(report["clean"])
        self.assertEqual(report["finding_count"], 0)
        self.assertFalse(report["matched_content_in_report"])
        self.assertFalse(report["raw_paths_in_report"])
        self.assertFalse(report["raw_email_addresses_in_report"])

    def test_detects_removed_history_without_echoing_secret_email_path_or_message(self) -> None:
        sensitive_name = "API_" + "KEY"
        sensitive_value = "live_" + "z" * 48
        private_email = "private-user" + "@sample.org"
        bearer_value = "Bearer " + "A" * 40
        private_path = self.repo / ".env"
        private_path.write_text(
            f"{sensitive_name}={sensitive_value}\n",
            encoding="utf-8",
        )
        self.commit("initial private fixture", email=private_email)
        private_path.unlink()
        (self.repo / "safe.txt").write_text("safe\n", encoding="utf-8")
        self.commit("remove fixture; " + bearer_value)

        report = scan_history(self.repo)
        codes = set(report["finding_counts"])
        self.assertFalse(report["clean"])
        self.assertIn("HISTORIC_SENSITIVE_FILENAME", codes)
        self.assertIn("ASSIGNED_SENSITIVE_VALUE", codes)
        self.assertIn("BEARER_CREDENTIAL", codes)
        self.assertIn("NON_NOREPLY_AUTHOR_EMAIL", codes)

        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(sensitive_value, encoded)
        self.assertNotIn(private_email, encoded)
        self.assertNotIn(bearer_value, encoded)
        self.assertNotIn('".env"', encoded)
        for finding in report["findings"]:
            self.assertRegex(finding["object_prefix"], r"^[0-9a-f]{16}$")
            self.assertRegex(finding["locator_hash"], r"^[0-9a-f]{24}$")

    def test_head_scope_excludes_but_all_scope_detects_unreachable_objects(self) -> None:
        (self.repo / "safe.txt").write_text("safe\n", encoding="utf-8")
        self.commit("safe root")
        safe_head = git(self.repo, "rev-parse", "HEAD")

        git(self.repo, "checkout", "--orphan", "orphan-private")
        git(self.repo, "rm", "-rf", ".")
        private_path = self.repo / ".env"
        private_path.write_text(
            ("API_" + "KEY") + "=" + ("live_" + "q" * 48),
            encoding="utf-8",
        )
        self.commit("orphan private fixture")
        git(self.repo, "checkout", "--detach", safe_head)
        # Remove the branch ref so only the object database retains the private
        # object. The final all-object gate must still find its secret content.
        git(self.repo, "branch", "-D", "orphan-private")

        head_report = scan_history(self.repo, scope="head")
        all_report = scan_history(self.repo, scope="all")
        self.assertTrue(head_report["clean"])
        self.assertFalse(all_report["clean"])
        self.assertIn("ASSIGNED_SENSITIVE_VALUE", all_report["finding_counts"])
        self.assertEqual(head_report["scope"], "candidate_ancestry")
        self.assertEqual(all_report["scope"], "available_objects")


if __name__ == "__main__":
    unittest.main()
