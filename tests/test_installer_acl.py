"""ACL diagnostics, not installer qualification; never emit raw principals/ACLs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer_parse_harness", ROOT / "tests/installer_parse_harness.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


@unittest.skipUnless(os.name == "nt", "BLOCKED: Windows ACL acceptance requires native hosts")
class InstallerAclTests(unittest.TestCase):
    def _run_probe(self, host, executable, self_test):
        case = harness.new_case("acl-comparator" if self_test else "acl-native")
        driver = case / "acl-probe.ps1"
        harness.write_new(driver, (ROOT / "tests/fixtures/v213_acl_probe.ps1").read_bytes())
        command = [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(driver)]
        if self_test:
            command.append("-ComparatorSelfTest")
        try:
            result = subprocess.run(command, cwd=case, env=harness.isolated_environment(case, executable),
                                    capture_output=True, encoding="utf-8", errors="replace", timeout=45)
        except (OSError, subprocess.TimeoutExpired) as error:
            harness.write_json(case / "transport.json", {"status": "UNEXPECTED", "host": host,
                               "code": "TIMEOUT" if isinstance(error, subprocess.TimeoutExpired) else "HOST_START_FAILED",
                               "driver_sha256": hashlib.sha256(driver.read_bytes()).hexdigest(), "release_qualified": False})
            raise AssertionError("ACL_PROBE_TRANSPORT_FAILED") from None
        raw = (result.stdout + result.stderr).encode("utf-8")
        harness.write_json(case / "transport.json", {"host": host, "exit_code": result.returncode,
                           "output_bytes": len(raw), "output_sha256": hashlib.sha256(raw).hexdigest(),
                           "driver_sha256": hashlib.sha256(driver.read_bytes()).hexdigest(), "release_qualified": False})
        self.assertEqual(result.returncode, 0, "ACL_PROBE_TRANSPORT_FAILED")
        self.assertTrue(result.stderr == "", "ACL_PROBE_STDERR")
        record = json.loads(result.stdout)
        self.assertIs(record["raw_security_data_retained"], False)
        self.assertIs(record["release_qualified"], False)
        # Never persist unexpected raw metadata fields or private principals.
        self.assertTrue("S-1-" not in result.stdout and "O:BA" not in result.stdout, "ACL_REDACTION_FAILED")
        return case, record

    def test_access_comparator_accepts_only_exact_or_documented_marker_addition(self):
        names = {"equal", "auto-inherited-added", "auto-inherited-removed", "owner-changed", "group-changed",
                 "rights-changed", "deny-added", "ace-order-changed", "protection-changed",
                 "ace-inheritance-changed", "null-versus-empty", "null-not-admitted"}
        for host, executable in harness.required_hosts():
            case, record = self._run_probe(host, executable, True)
            self.assertEqual(record["kind"], "ACCESS_COMPARATOR_SELF_TEST")
            self.assertEqual(len(record["results"]), 12)
            self.assertEqual({r["case"] for r in record["results"]}, names)
            for row in record["results"]:
                self.assertIs(type(row["accepted"]), bool)
                self.assertIs(row["accepted"], row["case"] in {"equal", "auto-inherited-added"})
                self.assertIs(row["expected"], row["accepted"])
            harness.write_json(case / "result.json", record)

    def test_native_strict_replace_preserves_access_and_exact_backup_metadata(self):
        for host, executable in harness.required_hosts():
            case, record = self._run_probe(host, executable, False)
            self.assertEqual(record["kind"], "ACL_DECOMPOSITION_DIAGNOSTIC")
            modes = {r["mode"]: r for r in record["rows"]}
            self.assertEqual(len(record["rows"]), 4)
            self.assertEqual(set(modes), {"inherited-ignore", "inherited-strict", "protected-strict", "backup-strict"})
            for row in modes.values():
                self.assertIsNone(row["failure"])
                self.assertIs(row["new_bytes_present"], True)
                self.assertIs(row["access_metadata_preserved"], True)
                self.assertEqual((case / row["mode"] / "target.bin").read_bytes(), b"NEW")
                self.assertFalse((case / row["mode"] / "temporary.bin").exists())
                comparison = row["target_comparison"]
                for key in ("owner_equal", "group_equal", "dacl_binary_equal", "dacl_ace_sequence_equal"):
                    self.assertIs(comparison[key], True)
                self.assertEqual(comparison["dacl_count_before"], comparison["dacl_count_after"])
                self.assertIn(comparison["control_flags_xor"], (0, 1024))
                if comparison["control_flags_xor"]:
                    self.assertEqual(comparison["control_flags_before"] & 1024, 0)
                # SACL is explicitly not certified by this access-metadata probe.
                self.assertIs(comparison["sacl_not_requested"], True)
            self.assertIs(modes["protected-strict"]["target_comparison"]["sddl_equal"], True)
            backup = modes["backup-strict"]["backup_comparison"]
            self.assertIs(backup["sddl_equal"], True)
            self.assertEqual(backup["control_flags_xor"], 0)
            self.assertEqual((case / "backup-strict" / "original-backup.bin").read_bytes(), b"OLD")
            harness.write_json(case / "result.json", record)

    def test_native_transport_failures_leave_bounded_receipts(self):
        host, executable = harness.required_hosts()[0]
        errors = ((subprocess.TimeoutExpired("SYNTHETIC_PRIVATE_COMMAND", 1), "TIMEOUT"),
                  (OSError("SYNTHETIC_PRIVATE_START_FAILURE"), "HOST_START_FAILED"))
        for error, code in errors:
            case = harness.new_case("acl-transport-negative")
            with patch.object(harness, "new_case", return_value=case), patch.object(subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(AssertionError, "ACL_PROBE_TRANSPORT_FAILED"):
                    self._run_probe(host, executable, True)
            raw = (case / "transport.json").read_text(encoding="utf-8")
            record = json.loads(raw)
            self.assertEqual(record["status"], "UNEXPECTED")
            self.assertEqual(record["code"], code)
            self.assertIs(record["release_qualified"], False)
            self.assertNotIn("SYNTHETIC_PRIVATE", raw)

    def test_fixture_roots_reject_relative_parent_and_remote_namespaces(self):
        for root in (Path("relative"), ROOT / ".." / "other", Path(r"\\server\share\audit"), Path(r"\\?\D:\audit")):
            with patch.object(harness, "AUDIT_CASE_ROOT", root):
                with self.assertRaisesRegex(RuntimeError, "FIXTURE_ABSOLUTE_LOCAL_ROOT_REQUIRED"):
                    harness.new_case("root-reject")


if __name__ == "__main__":
    unittest.main()
