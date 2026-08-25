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

    def test_rejects_literal_windows_profile(self):
        findings = scanner.scan_text(
            Path("scripts/unsafe.ps1"),
            'Set-Location "C:\\Users\\named-profile\\private\\"\n',
        )
        self.assertTrue(any("user-specific Windows profile path" in item for item in findings))

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


if __name__ == "__main__":
    unittest.main()
