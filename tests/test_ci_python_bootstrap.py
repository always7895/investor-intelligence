from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts" / "resolve_python.ps1"
BOOTSTRAP = ROOT / "scripts" / "bootstrap_portable_python.ps1"


class CiPythonBootstrapPolicyTests(unittest.TestCase):
    def test_github_actions_delegates_to_portable_bootstrap(self):
        text = RESOLVER.read_text(encoding="utf-8")
        self.assertIn('$env:GITHUB_ACTIONS -eq "true"', text)
        self.assertIn('bootstrap_portable_python.ps1', text)
        self.assertIn('-ExportGitHubEnvironment', text)
        self.assertIn('portable-python-3.12.10-', text)
        self.assertIn('PROJECT_PYTHON configured from reviewed portable CPython 3.12.10', text)

    def test_non_ci_generic_resolver_is_retained(self):
        text = RESOLVER.read_text(encoding="utf-8")
        self.assertIn('PYTHON_FOR_RUNNER', text)
        self.assertIn('C:\\Users\\*\\AppData\\Local\\Programs\\Python', text)
        self.assertIn('-m venv --copies', text)

    def test_local_branch_never_deletes_and_reuses_the_reviewed_lock_command(self):
        text = RESOLVER.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"Remove-Item[^\n]*-Recurse")
        self.assertIn('[switch]$InstallLockedDependencies', text)
        # The CI branch and the local locked mode run the same reviewed install command.
        install = re.findall(
            r"-m pip install --isolated --disable-pip-version-check `\s+"
            r"--only-binary=:all: --index-url https://pypi\.org/simple `\s+"
            r"--require-hashes -r \$requirements",
            text,
        )
        self.assertEqual(len(install), 2)

    def test_bootstrap_pins_runtime_and_verifies_every_download(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("$PythonVersion = '3.12.10'", text)
        self.assertIn("$PipVersion = '26.1.2'", text)
        self.assertRegex(text, r"\$PythonArchiveSha256 = '[0-9a-f]{64}'")
        self.assertRegex(text, r"\$PipWheelSha256 = '[0-9a-f]{64}'")
        self.assertIn('Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256', text)
        self.assertIn('SHA-256 verification failed', text)

    def test_bootstrap_uses_only_reviewed_official_download_hosts(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        urls = re.findall(r"https://[^\"']+", text)
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(
                url.startswith('https://www.python.org/')
                or url.startswith('https://files.pythonhosted.org/'),
                url,
            )


if __name__ == "__main__":
    unittest.main()
