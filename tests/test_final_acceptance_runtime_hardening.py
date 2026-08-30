from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAL = (ROOT / ".github" / "workflows" / "formal-private-release.yml").read_text(
    encoding="utf-8"
)
HISTORY = (
    ROOT / ".github" / "workflows" / "final-history-confirmation.yml"
).read_text(encoding="utf-8")


class FinalAcceptanceRuntimeHardeningTests(unittest.TestCase):
    def test_rest_collections_are_flattened_explicitly(self) -> None:
        for text in (FORMAL, HISTORY):
            self.assertNotIn("@(Invoke-RestMethod", text)
            self.assertIn("function ConvertTo-FlatArray", text)
            self.assertIn("[System.Collections.ArrayList]::new()", text)
            self.assertIn("foreach ($item in $Response)", text)

    def test_branch_convergence_retries_boundedly(self) -> None:
        for text in (FORMAL, HISTORY):
            self.assertIn("for ($attempt = 1; $attempt -le 12;", text)
            self.assertIn("Start-Sleep -Seconds 5", text)

    def test_pr18_internal_refs_are_fail_closed(self) -> None:
        for text in (FORMAL, HISTORY):
            self.assertIn("13,14,16,18", text)
            self.assertIn("git/ref/pull/$number/$kind", text)

    def test_history_pull_ref_pages_are_flattened(self) -> None:
        self.assertIn("$batchResponse = Invoke-RestMethod", HISTORY)
        self.assertIn("$batch = @(ConvertTo-FlatArray $batchResponse)", HISTORY)

    def test_optional_inventory_cleanup_is_guarded(self) -> None:
        self.assertIn(
            "if (-not [string]::IsNullOrWhiteSpace($env:PULL_REF_INVENTORY))",
            HISTORY,
        )

    def test_final_notice_records_completed_support_purge(self) -> None:
        self.assertIn(
            "GitHub Support completed the platform-side pull-reference purge",
            FORMAL,
        )

    def test_formal_builder_uses_reviewed_repository_launcher(self) -> None:
        self.assertNotIn(
            "& $bootstrapPython scripts/build_formal_release.py",
            FORMAL,
        )
        self.assertIn(
            "& $bootstrapPython scripts/run_repo_script.py build_formal_release.py",
            FORMAL,
        )


if __name__ == "__main__":
    unittest.main()