from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_scanner():
    spec = importlib.util.spec_from_file_location(
        "security_check_under_test", ROOT / "scripts/security_check.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load scripts/security_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scanner = load_scanner()

# Credential-shaped negative samples are assembled only at runtime so the
# repository scanner can safely scan its own regression tests.


class SecurityScannerTests(unittest.TestCase):
    def test_allows_explicit_non_secret_fixture(self):
        findings = scanner.scan_text(
            Path("cloud/test/example.test.ts"),
            'const secret = "EXAMPLE_CHANNEL_SECRET_NOT_REAL";\n',
        )
        self.assertEqual(findings, [])

    def test_allows_generic_windows_discovery_glob(self):
        findings = scanner.scan_text(
            Path("scripts/resolver.ps1"),
            'Get-ChildItem "C:\\Users\\*\\AppData\\Local\\Programs\\Tool\\tool.exe"\n',
        )
        self.assertEqual(findings, [])

    def test_does_not_join_assignments_across_lines(self):
        sensitive_word = "Se" + "cret"
        source = f'label = "{sensitive_word}"\nordinary_value = "not-a-credential"\n'
        findings = scanner.scan_text(Path("tests/meta_sample.py"), source)
        self.assertEqual(findings, [])

    def test_history_scanner_does_not_match_its_own_label_map(self):
        path = ROOT / "scripts" / "full_history_privacy_scan.py"
        findings = scanner.scan_text(
            Path("scripts/full_history_privacy_scan.py"),
            path.read_text(encoding="utf-8"),
        )
        self.assertEqual(findings, [])

    # Profile paths are assembled from parts so this file never contains a
    # literal user-specific path that the scanner would flag in its own source.
    PROFILE_LABEL = "user-specific Windows profile path"

    @staticmethod
    def profile_path(separator: str, name: str, tail: str = "AppData") -> str:
        return separator.join(["C:", "Users", name, tail])

    def test_rejects_literal_windows_profile(self):
        findings = scanner.scan_text(
            Path("scripts/unsafe.ps1"),
            "Set-Location \"" + self.profile_path("\\", "named-profile", "private") + "\\\"\n",
        )
        self.assertTrue(any(self.PROFILE_LABEL in item for item in findings))

    def test_rejects_escaped_windows_profile_in_string_literals(self):
        for backslashes in (2, 3, 4):
            with self.subTest(backslashes=backslashes):
                literal = self.profile_path("\\" * backslashes, "synthetic-account")
                findings = scanner.scan_text(
                    Path("cloud/test/unsafe.ts"),
                    'export const EXE = "' + literal + '";\n',
                )
                self.assertEqual(
                    findings,
                    [f"{Path('cloud/test/unsafe.ts')}:1: possible " + self.PROFILE_LABEL],
                )

    def test_rejects_forward_slash_windows_profile(self):
        findings = scanner.scan_text(
            Path("scripts/unsafe.py"),
            'EXE = "' + self.profile_path("/", "synthetic-account") + '/python.exe"\n',
        )
        self.assertTrue(any(self.PROFILE_LABEL in item for item in findings))

    def test_profile_path_findings_never_echo_the_account_name(self):
        account = "synthetic-account-name"
        findings = scanner.scan_text(
            Path("cloud/test/unsafe.ts"),
            self.profile_path("\\" * 2, account) + "\n",
        )
        self.assertTrue(findings)
        self.assertFalse(any(account in item for item in findings))

    def test_profile_path_exemptions_hold_in_every_form(self):
        for name in ("*", "Public", "Default", "Default User", "All Users", "<user>", "%USERNAME%"):
            for separator in ("\\", "\\" * 2, "/"):
                with self.subTest(name=name, separator=separator):
                    findings = scanner.scan_text(
                        Path("scripts/placeholder.ps1"),
                        self.profile_path(separator, name) + "\n",
                    )
                    self.assertEqual(findings, [])

    def test_profile_path_without_following_separator_is_not_matched(self):
        findings = scanner.scan_text(
            Path("scripts/placeholder.py"),
            "C:" + "\\" * 2 + "Users" + "\\" * 2 + "synthetic-account\n",
        )
        self.assertEqual(findings, [])

    def test_task0_harness_embeds_no_profile_path(self):
        harness = ROOT / "cloud" / "test" / "helpers" / "task0-general-qa-harness.ts"
        text = harness.read_text(encoding="utf-8")
        self.assertEqual(scanner.scan_text(Path("cloud/test/helpers/task0-general-qa-harness.ts"), text), [])
        self.assertNotIn("APPROVED_PYTHON_DEFAULT", text)

    def test_rejects_realistic_assigned_secret(self):
        assignment_name = "channel" + "Secret"
        suspicious_value = "live-value-" + "that-must-not-be-committed"
        source = "const " + assignment_name + ' = "' + suspicious_value + '";\n'
        findings = scanner.scan_text(Path("config/unsafe.ts"), source)
        self.assertTrue(any("assigned sensitive value" in item for item in findings))

    def test_rejects_uppercase_assigned_secret(self):
        assignment_name = "se" + "cret"
        suspicious_value = "QWERTYUIOPASDFGH" + "JKLZXCVBNM123456"
        source = "const " + assignment_name + ' = "' + suspicious_value + '";\n'
        findings = scanner.scan_text(Path("config/unsafe.ts"), source)
        self.assertTrue(any("assigned sensitive value" in item for item in findings))

    def test_rejects_raw_line_identifier(self):
        raw_identifier = "U0123456789abcdef" + "0123456789abcdef"
        findings = scanner.scan_text(
            Path("config/unsafe.json"),
            f'{{"user": "{raw_identifier}"}}\n',
        )
        self.assertTrue(any("raw LINE user identifier" in item for item in findings))



class WorkersDevAccountTests(unittest.TestCase):
    """A <worker>.<account>.workers.dev host names the operator's Cloudflare account (Fable 5.1 h-privacy-1, 2026-10-12).

    Hosts are assembled at runtime so this file never holds one that the scanner would flag."""

    LABEL = "workers.dev account subdomain"
    DOC = Path("docs/sample.md")

    @staticmethod
    def host(account: str) -> str:
        return ".".join(["my-worker", account, "workers", "dev"])

    def test_rejects_an_account_host_without_echoing_the_account(self):
        account = "acct" + "label" + "42"
        for text in (f"https://{self.host(account)}/v213/readiness\n", f"base `{self.host(account).upper()}`\n",
                     f"[string]$WorkerUrl = 'https://{self.host(account)}',\n"):
            findings = scanner.scan_text(self.DOC, text)
            self.assertEqual(findings, [f"{self.DOC}:1: possible {self.LABEL}"])
            self.assertNotIn(account, findings[0].lower())

    def test_allows_reserved_labels_single_label_hosts_and_placeholders(self):
        for account in ("synthetic", "example", "test", "invalid", "placeholder", "SYNTHETIC"):
            self.assertEqual(scanner.scan_text(self.DOC, f"https://{self.host(account)}\n"), [], account)
        for text in ("https://" + ".".join(["stable-worker", "workers", "dev"]),
                     "https://investor-intelligence-v21-owner-line.<account>.workers.dev",
                     "'(?i)^[a-z0-9-]+(?:\\.[a-z0-9-]+)*\\.workers\\.dev$'"):
            self.assertEqual(scanner.scan_text(self.DOC, text + "\n"), [], text)

    def test_a_reserved_label_must_be_the_whole_label(self):
        self.assertEqual(len(scanner.scan_text(self.DOC, self.host("synthetic-" + "acct") + "\n")), 1)

    def test_the_rule_is_current_tree_only(self):
        self.assertNotIn(scanner.WORKERS_DEV_ACCOUNT_PATTERN, [pattern for _, pattern, _ in scanner.PATTERNS])
        self.assertIn(scanner.WORKERS_DEV_ACCOUNT_PATTERN, [pattern for _, pattern, _ in scanner.CURRENT_TREE_PATTERNS])


if __name__ == "__main__":
    unittest.main()
