from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from phase8_fault_injection_gate import (  # noqa: E402
    PENDING,
    REQUIRED_SCENARIOS,
    audit_phase8_matrix,
    load_object,
)


class Phase8FaultInjectionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_object(ROOT / "config" / "phase8-fault-injection-policy.json")
        cls.release = load_object(ROOT / "config" / "release-candidate-status.json")

    def test_current_matrix_has_retained_tests_for_every_scenario(self) -> None:
        findings, summary = audit_phase8_matrix(self.policy, self.release)
        self.assertEqual(findings, [])
        self.assertEqual(set(item["id"] for item in self.policy["scenarios"]), REQUIRED_SCENARIOS)
        self.assertGreaterEqual(summary["scenario_count"], 18)
        self.assertGreaterEqual(summary["category_count"], 8)
        self.assertEqual(summary["pending_scenarios"], [])
        self.assertEqual(summary["pending_count"], 0)
        self.assertEqual(summary["release_phase8_state"], "PASS")
        self.assertTrue(summary["complete"])
        self.assertTrue(summary["synthetic_offline_only"])
        self.assertFalse(summary["destructive_actions_allowed"])

    def test_tenant_delete_during_retry_has_a_retained_worker_regression(self) -> None:
        scenario = next(
            value
            for value in self.policy["scenarios"]
            if value["id"] == "tenant_delete_during_retry"
        )
        self.assertEqual(scenario["test_module"], "cloud/test/storage.test.ts")
        text = (ROOT / scenario["test_module"]).read_text(encoding="utf-8")
        self.assertIn(
            "prevents an in-flight retry from resurrecting data after tenant deletion",
            text,
        )
        self.assertIn("tenantWriteEpoch", text)

    def test_clean_install_and_package_integrity_have_retained_regressions(self) -> None:
        by_id = {value["id"]: value for value in self.policy["scenarios"]}
        for scenario_id in (
            "clean_install_without_developer_cache",
            "package_checksum_or_sbom_mismatch",
        ):
            self.assertEqual(by_id[scenario_id]["test_module"], "tests.test_release_package")
        text = (ROOT / "tests" / "test_release_package.py").read_text(encoding="utf-8")
        self.assertIn("byte_reproducible", text)
        self.assertIn("rejects_checksum_mismatch", text)
        self.assertIn("rejects_external_sbom_mismatch", text)

    def test_require_complete_accepts_only_passed_release_status(self) -> None:
        findings, summary = audit_phase8_matrix(
            self.policy,
            self.release,
            require_complete=True,
        )
        self.assertEqual(findings, [])
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["release_phase8_state"], "PASS")

        pending_release = copy.deepcopy(self.release)
        pending_release["gates"]["phase_8_disaster_recovery"] = "PENDING"
        findings, summary = audit_phase8_matrix(
            self.policy,
            pending_release,
            require_complete=True,
        )
        self.assertFalse(summary["complete"])
        self.assertTrue(any("release status gate PASS" in item for item in findings))

    def test_release_status_can_mark_phase8_pass_only_when_no_scenario_is_pending(self) -> None:
        release = copy.deepcopy(self.release)
        release["gates"]["phase_8_disaster_recovery"] = "PASS"
        findings, summary = audit_phase8_matrix(self.policy, release, require_complete=True)
        self.assertEqual(findings, [])
        self.assertTrue(summary["complete"])

        pending_policy = copy.deepcopy(self.policy)
        pending_policy["scenarios"][0]["test_module"] = PENDING
        findings, summary = audit_phase8_matrix(pending_policy, release)
        self.assertFalse(summary["complete"])
        self.assertTrue(any("cannot mark Phase 8 PASS" in item for item in findings))

    def test_rejects_real_credentials_data_destructive_or_production_faults(self) -> None:
        for key in (
            "automatic_production_fault_injection",
            "destructive_actions_allowed",
            "real_credentials_allowed",
            "real_user_data_allowed",
        ):
            policy = copy.deepcopy(self.policy)
            policy[key] = True
            findings, _summary = audit_phase8_matrix(policy, self.release)
            with self.subTest(key=key):
                self.assertTrue(any(key in item for item in findings))

    def test_rejects_missing_duplicate_unknown_scenarios(self) -> None:
        policy = copy.deepcopy(self.policy)
        removed = policy["scenarios"].pop()
        duplicate = copy.deepcopy(policy["scenarios"][0])
        policy["scenarios"].append(duplicate)
        policy["scenarios"].append(
            {
                "id": "invented_fault",
                "category": "invented",
                "required_outcome": "invented",
                "test_module": PENDING,
            }
        )
        findings, _summary = audit_phase8_matrix(policy, self.release)
        self.assertTrue(any("duplicate id" in item for item in findings))
        self.assertTrue(any("required Phase 8 scenarios missing" in item for item in findings))
        self.assertTrue(any("unknown Phase 8 scenarios" in item for item in findings))
        self.assertNotEqual(removed["id"], "invented_fault")

    def test_rejects_nonexistent_retained_test_module(self) -> None:
        policy = copy.deepcopy(self.policy)
        scenario = next(
            value for value in policy["scenarios"] if value["id"] == "source_rate_limit_429"
        )
        scenario["test_module"] = "tests.test_does_not_exist"
        findings, _summary = audit_phase8_matrix(policy, self.release)
        self.assertTrue(any("retained test module does not exist" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
