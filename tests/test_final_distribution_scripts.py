from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FinalDistributionScriptTests(unittest.TestCase):
    def _read(self, relative: str) -> str:
        path = ROOT / relative
        self.assertTrue(path.is_file(), relative)
        return path.read_text(encoding="utf-8-sig")

    def test_final_installer_is_v21_and_verifies_archive_before_extraction(self) -> None:
        text = self._read("install-final.ps1")
        self.assertIn("$Version = '2.1.0'", text)
        self.assertIn("Get-FileHash", text)
        self.assertIn("SHA-256 verification failed", text)
        self.assertIn("Expand-Archive", text)
        self.assertLess(text.index("Get-FileHash"), text.index("Expand-Archive"))
        self.assertIn("build_mode", text)
        self.assertIn("final_release", text)
        self.assertIn("SkipSecContactConfiguration", text)

    def test_bootstrap_uses_verified_python_hash_locked_dependencies_and_exe(self) -> None:
        text = self._read("bootstrap.ps1")
        self.assertIn("$Version = '2.1.0'", text)
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
            "scripts\\v21_serenity_top20.py",
            "scripts\\build_v21_public_snapshot.py",
            "InvestorIntelligenceLauncher.cs",
            "InvestorIntelligence.exe",
        ):
            self.assertIn(fragment, text)
        self.assertIn("manual_ticker_configuration_required = $false", text)
        self.assertIn("LINE/Cloudflare, IBKR, billing and automatic trading remain disabled", text)
        self.assertIn("UpgradeStaging", text)

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

    def test_no_manual_ticker_configuration_remains(self) -> None:
        bootstrap = self._read("bootstrap.ps1")
        launcher = self._read("run-local.ps1")
        self.assertNotIn("research-universe.local.json", bootstrap)
        self.assertNotIn("research-universe.example.json", bootstrap)
        self.assertNotIn("notepad.exe", launcher.casefold())
        self.assertNotIn('"ticker"\\s*:\\s*"EXAMPLE"', launcher)
        self.assertIn("scripts\\v21_serenity_top20.py", launcher)
        self.assertIn("scripts\\build_v21_public_snapshot.py", launcher)

    def test_run_local_uses_protected_sec_contact_and_optional_signed_sync(self) -> None:
        text = self._read("run-local.ps1")
        self.assertIn("sec-contact.local.txt", text)
        self.assertIn("ConvertTo-SecureString", text)
        self.assertIn("$env:SEC_CONTACT_EMAIL", text)
        self.assertIn("sync-v21-public-snapshot.ps1", text)
        self.assertIn("v21-owner-line.local.json", text)
        self.assertIn("[switch]$NoSync", text)
        self.assertIn("[switch]$Synthetic", text)

    def test_cmd_wrapper_invokes_checksum_verifying_installer(self) -> None:
        text = self._read("install-final.cmd")
        self.assertIn("-ExecutionPolicy Bypass", text)
        self.assertIn("install-final.ps1", text)
        self.assertIn("-CreateDesktopShortcut", text)

    def test_scheduler_is_daily_0720_2020_and_explicit(self) -> None:
        text = self._read("register-task.ps1")
        self.assertIn("[switch]$Enable", text)
        self.assertIn("[switch]$Disable", text)
        self.assertIn("$MorningRefreshTime = '07:20'", text)
        self.assertIn("$EveningRefreshTime = '20:20'", text)
        self.assertIn("New-ScheduledTaskTrigger", text)
        self.assertIn("-Daily", text)
        self.assertIn("08:00 Asia/Taipei", text)
        self.assertIn("21:00 Asia/Taipei", text)
        self.assertNotIn("LINE_CHANNEL_ACCESS_TOKEN", text)

    def test_launcher_source_is_local_powershell_bridge_only(self) -> None:
        text = self._read("launcher/InvestorIntelligenceLauncher.cs")
        self.assertIn("run-v213-local.ps1", text)
        self.assertIn("--self-test", text)
        self.assertIn("--model-selection-self-test", text)
        self.assertIn("--pipe-hold-self-test", text)
        self.assertIn("powershell.exe", text)
        for forbidden in (
            "LINE_CHANNEL_ACCESS_TOKEN",
            "LINE_CHANNEL_SECRET",
            "api.interactivebrokers",
            "placeOrder",
        ):
            self.assertNotIn(forbidden, text)

    def test_uninstaller_preserves_local_data_unless_explicitly_removed(self) -> None:
        text = self._read("uninstall.ps1")
        self.assertIn("[switch]$RemoveLocalData", text)
        self.assertIn("Preserved-", text)
        self.assertIn("Use -RemoveLocalData only", text)

    def test_v21_final_distribution_uses_repo_script_launcher_for_release_tools(self) -> None:
        workflow_path = ROOT / ".github" / "workflows" / "v21-final-distribution.yml"
        policy = json.loads(self._read("config/release-package-policy.json"))

        if not workflow_path.is_file():
            # The application distribution deliberately excludes .github/.
            # This branch is valid only inside a verified final_release package;
            # it must never make a repository checkout silently tolerate a
            # missing acceptance workflow.
            metadata_path = ROOT / "release-metadata.json"
            self.assertTrue(
                metadata_path.is_file(),
                "v21 final-distribution workflow is missing outside a final package",
            )
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("build_mode"), "final_release")
            self.assertEqual(metadata.get("version"), "2.1.0")
            self.assertFalse((ROOT / ".github").exists())
            self.assertIn(".github/", set(policy["excluded_prefixes"]))
            self.assertIn("scripts/run_repo_script.py", set(policy["required_paths"]))
            return

        workflow = workflow_path.read_text(encoding="utf-8")
        self.assertIn("scripts\\run_repo_script.py build_formal_release.py", workflow)
        self.assertIn("scripts\\run_repo_script.py verify_release_package.py", workflow)
        self.assertNotIn("PROJECT_PYTHON scripts\\build_formal_release.py", workflow)
        self.assertNotIn("PROJECT_PYTHON scripts\\verify_release_package.py", workflow)
        self.assertTrue((ROOT / "scripts" / "run_repo_script.py").is_file())
        self.assertIn("scripts/run_repo_script.py", set(policy["required_paths"]))

    def test_release_policy_requires_v21_final_assets(self) -> None:
        policy = json.loads(self._read("config/release-package-policy.json"))
        required = set(policy["required_paths"])
        expected = {
            "bootstrap.ps1",
            "install-final.ps1",
            "install-final.cmd",
            "run-local.ps1",
            "register-task.ps1",
            "launcher/InvestorIntelligenceLauncher.cs",
            "scripts/v21_serenity_top20.py",
            "scripts/build_v21_public_snapshot.py",
            "setup-v21-owner-line.ps1",
            "sync-v21-public-snapshot.ps1",
            "cloud/src/v21/worker.ts",
            "cloud/wrangler.v21.production.template.toml",
            "docs/V2_1_0_FINAL.zh-TW.md",
        }
        self.assertTrue(expected.issubset(required))


if __name__ == "__main__":
    unittest.main()
