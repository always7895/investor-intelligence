"""Diagnostic serialization tests only; no full coordinator execution."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer_parse_harness", ROOT / "tests/installer_parse_harness.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


@unittest.skipUnless(os.name == "nt", "BLOCKED: native Windows diagnostic hosts required")
class InstallerDiagnosticTests(unittest.TestCase):
    def test_bounded_primary_and_journal_failures_on_both_hosts(self):
        for name, executable in harness.required_hosts():
            case = harness.new_case("b2-evidence")
            driver = case / "io-probe.ps1"
            harness.write_new(driver, (ROOT / "tests/fixtures/v213_io_probe.ps1").read_bytes())
            driver_digest = hashlib.sha256(driver.read_bytes()).hexdigest()
            try:
                result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                         "-File", str(driver), "-EvidenceSelfTest"], cwd=case,
                                        env=harness.isolated_environment(case, executable), capture_output=True,
                                        encoding="utf-8", errors="replace", timeout=30)
            except (OSError, subprocess.TimeoutExpired) as error:
                harness.write_json(case / "transport.json", {"status": "UNEXPECTED", "host": name,
                                   "code": "TIMEOUT" if isinstance(error, subprocess.TimeoutExpired) else "HOST_START_FAILED",
                                   "driver_sha256": driver_digest, "release_qualified": False})
                raise AssertionError("EVIDENCE_SELF_TEST_TRANSPORT_FAILED") from None
            raw = (result.stdout + result.stderr).encode("utf-8")
            harness.write_json(case / "transport.json", {"status": "TRANSPORT_OBSERVATION", "host": name,
                               "exit_code": result.returncode, "output_bytes": len(raw),
                               "output_sha256": hashlib.sha256(raw).hexdigest(), "driver_sha256": driver_digest,
                               "release_qualified": False})
            self.assertEqual(result.returncode, 0, "EVIDENCE_SELF_TEST_TRANSPORT_FAILED")
            self.assertTrue(result.stderr == "", "EVIDENCE_SELF_TEST_STDERR")
            self.assertTrue("SYNTHETIC_PRIVATE" not in result.stdout, "EVIDENCE_REDACTION_FAILED")
            record = json.loads(result.stdout)
            self.assertEqual(set(record), {"phase", "primary_failure", "rollback", "journal_write_failure", "release_qualified"})
            self.assertEqual(record["phase"], "EVIDENCE_SELF_TEST")
            self.assertEqual(record["rollback"], "NOT_ATTEMPTED")
            self.assertIs(record["release_qualified"], False)
            for field in ("primary_failure", "journal_write_failure"):
                failure = record[field]
                self.assertEqual(set(failure), {"code", "exceptions"})
                self.assertEqual(failure["code"], "OPERATION_FAILED")
                self.assertTrue(1 <= len(failure["exceptions"]) <= 4)
                for exception in failure["exceptions"]:
                    self.assertEqual(set(exception), {"exception_type", "hresult"})
                    self.assertIs(type(exception["hresult"]), int)
            self.assertIn("System.IO.IOException", [e["exception_type"] for e in record["primary_failure"]["exceptions"]])
            self.assertIn("System.UnauthorizedAccessException", [e["exception_type"] for e in record["journal_write_failure"]["exceptions"]])
            self.assertNotEqual(record["primary_failure"], record["journal_write_failure"])
            harness.write_json(case / "bounded-evidence.json", record)


if __name__ == "__main__":
    unittest.main()
