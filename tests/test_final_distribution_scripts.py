from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FinalDistributionScriptTests(unittest.TestCase):
    def _read(self, relative: str) -> str:
        path = ROOT / relative
        self.assertTrue(path.is_file(), relative)
        return path.read_text(encoding="utf-8")

    def test_final_installer_verifies_archive_before_extraction(self) -> None:
        text = self._read("install-final.ps1")
        self.assertIn("Get-FileHash", text)
        self.assertIn("SHA-256 verification failed", text)
        self.assertIn("Expand-Archive", text)
        self.assertLess(text.index("Get-FileHash"), text.index("Expand-Archive"))
        self.assertIn("build_mode", text)
        self.assertIn("final_release", text)

    def test_bootstrap_uses_verified_python_and_hash_locked_dependencies(self) -> None:
        text = self._read("bootstrap.ps1")
        self.assertIn("bootstrap_portable_python.ps1", text)
        for fragment in (
            "--isolated",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--index-url https://pypi.org/simple",
            "--require-hashes",
            "requirements-ci.txt",
            "pip check",
            "--distribution",
        ):
            self.assertIn(fragment, text)
        self.assertIn("LINE, Cloudflare deployment, schedules, memory, IBKR and billing remain disabled", text)
        self.assertIn("UpgradeStaging", text)
        for preserved in ("data", "reports", "daily_briefing.log"):
            self.assertIn(f"'{preserved}'", text)

    def test_portable_python_bootstrap_is_windows_powershell_51_compatible(self) -> None:
        text = self._read("scripts/bootstrap_portable_python.ps1")
        self.assertIn(
            "[System.IO.Compression.ZipFile]::ExtractToDirectory($ArchivePath, $OutputDirectory)",
            text,
        )
        self.assertNotIn(
            "[System.IO.Compression.ZipFile]::ExtractToDirectory($ArchivePath, $OutputDirectory, $true)",
            text,
        )

    def test_bootstrap_seeds_the_exact_research_universe_example(self) -> None:
        text = self._read("bootstrap.ps1")
        self.assertIn("research-universe.example.json", text)
        self.assertNotIn("research-unive.example.json", text)
    def test_cmd_wrapper_invokes_checksum_verifying_installer(self) -> None:
        text = self._read("install-final.cmd")
        self.assertIn("-ExecutionPolicy Bypass", text)
        self.assertIn("install-final.ps1", text)
        self.assertIn("-CreateDesktopShortcut", text)

    def test_scheduler_requires_explicit_enable_and_supports_disable(self) -> None:
        text = self._read("register-task.ps1")
        self.assertIn("[switch]$Enable", text)
        self.assertIn("[switch]$Disable", text)
        self.assertIn("Use -Enable or -Disable explicitly", text)
        self.assertIn("LINE and delivery remain disabled", text)
        self.assertNotIn("LINE_CHANNEL_ACCESS_TOKEN", text)

    def test_uninstaller_preserves_local_data_unless_explicitly_removed(self) -> None:
        text = self._read("uninstall.ps1")
        self.assertIn("[switch]$RemoveLocalData", text)
        self.assertIn("Preserved-", text)
        self.assertIn("Use -RemoveLocalData only", text)

    def test_local_launcher_stays_fail_closed(self) -> None:
        text = self._read("run-local.ps1")
        required = {
            "DELIVERY_ENABLED": "false",
            "LINE_ENABLED": "false",
            "LINE_PUSH_ENABLED": "false",
            "LINE_ACCESS_MODE": "disabled",
            "PUBLIC_KV_SYNC_ENABLED": "false",
            "CLOUD_INFERENCE_ENABLED": "false",
            "IBKR_READONLY_ENABLED": "false",
        }
        for name, value in required.items():
            self.assertIn(f"$env:{name} = '{value}'", text)
        self.assertIn("scripts\\daily_briefing.py", text)

    def test_release_policy_requires_final_installation_assets(self) -> None:
        policy = json.loads(self._read("config/release-package-policy.json"))
        required = set(policy["required_paths"])
        self.assertTrue(
            {
                "bootstrap.ps1",
                "install-final.ps1",
                "install-final.cmd",
                "install.ps1",
                "run-local.ps1",
                "register-task.ps1",
                "uninstall.ps1",
                "docs/FINAL_RELEASE.md",
                "scripts/build_delivery_bundle.py",
                "tests/test_delivery_bundle.py",
            }.issubset(required)
        )


if __name__ == "__main__":
    unittest.main()
