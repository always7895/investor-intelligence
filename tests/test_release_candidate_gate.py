from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_candidate_gate import (  # noqa: E402
    MANDATORY_GATES,
    audit_release_status,
    load_status,
)


class ReleaseCandidateGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.status = load_status()

    def test_development_status_is_valid_and_fail_closed(self) -> None:
        self.assertEqual(audit_release_status(self.status), [])
        self.assertFalse(self.status["release_ready"])
        self.assertFalse(self.status["deployed"])
        self.assertFalse(self.status["billing_enabled"])
        self.assertFalse(self.status["external_users_admitted"])
        self.assertFalse(self.status["local_action_required"])
        self.assertFalse(self.status["secrets_required_now"])
        self.assertEqual(set(self.status["gates"]), MANDATORY_GATES)
        self.assertTrue(self.status["hard_blockers"])

    def test_release_ready_requires_all_pass_empty_blockers_and_exact_sha(self) -> None:
        document = copy.deepcopy(self.status)
        document.update(
            {
                "release_ready": True,
                "candidate_commit": "a" * 40,
                "candidate_version": "v1.0.0",
                "hard_blockers": [],
            }
        )
        for key in document["gates"]:
            document["gates"][key] = "PASS"
        self.assertEqual(
            audit_release_status(document, expected_head="a" * 40, require_ready=True),
            [],
        )

        document["candidate_commit"] = "b" * 40
        findings = audit_release_status(
            document,
            expected_head="a" * 40,
            require_ready=True,
        )
        self.assertTrue(any("does not match" in item for item in findings))

    def test_cannot_deploy_admit_users_or_enable_billing_while_pending(self) -> None:
        for key in ("deployed", "billing_enabled", "external_users_admitted"):
            document = copy.deepcopy(self.status)
            document[key] = True
            with self.subTest(key=key):
                findings = audit_release_status(document)
                self.assertTrue(any(key in item for item in findings))

    def test_old_or_partial_passes_cannot_promote_release(self) -> None:
        document = copy.deepcopy(self.status)
        document["release_ready"] = True
        document["candidate_commit"] = "c" * 40
        document["candidate_version"] = "v1.0.0"
        document["hard_blockers"] = []
        for key in document["gates"]:
            document["gates"][key] = "PASS"
        document["gates"]["public_options_provider_review"] = "BLOCKED"
        findings = audit_release_status(document, expected_head="c" * 40)
        self.assertTrue(any("every mandatory gate" in item for item in findings))

    def test_rejects_missing_unknown_or_invalid_gate_states(self) -> None:
        document = copy.deepcopy(self.status)
        document["gates"].pop("phase_8_disaster_recovery")
        document["gates"]["invented_gate"] = "PASS"
        document["gates"]["phase_4_reports"] = "GREEN"
        findings = audit_release_status(document)
        self.assertTrue(any("missing" in item for item in findings))
        self.assertTrue(any("unknown release gates" in item for item in findings))
        self.assertTrue(any("invalid state" in item for item in findings))

    def test_release_only_mode_refuses_current_pending_status(self) -> None:
        findings = audit_release_status(
            self.status,
            expected_head="d" * 40,
            require_ready=True,
        )
        self.assertTrue(any("release was requested" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
